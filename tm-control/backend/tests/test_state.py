import sqlite3

import pytest

from tm_control.core.state import MIGRATIONS, State

NOW = "2026-10-27T12:00:00+00:00"


def _migrated(tmp_path):
    state = State(tmp_path / "state.sqlite")
    state.migrate()
    return state


def _add_user(con, username, role="admin"):
    with con:
        con.execute(
            "INSERT INTO users (username, password_hash, role, created_at) VALUES (?, ?, ?, ?)",
            (username, "placeholder-hash", role, NOW),
        )


def test_fresh_database_gets_every_migration(tmp_path):
    state = State(tmp_path / "state.sqlite")
    assert state.version() == 0
    assert state.migrate() == len(MIGRATIONS) == state.version() == 8


def test_migrate_twice_changes_nothing(tmp_path):
    state = _migrated(tmp_path)
    _add_user(state.connect(), "admin")
    assert state.migrate() == len(MIGRATIONS)
    assert state.connect().execute("SELECT count(*) FROM users").fetchone()[0] == 1


def test_migration_one_creates_the_tables(tmp_path):
    con = _migrated(tmp_path).connect()
    tables = {row["name"] for row in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"users", "device", "eula_acceptances", "jobs", "audit"} <= tables


def test_failed_migration_leaves_the_version_and_tables_alone(tmp_path, monkeypatch):
    monkeypatch.setattr("tm_control.core.state.MIGRATIONS", ["CREATE TABLE t (a INTEGER); SELECT * FROM missing;"])
    state = State(tmp_path / "state.sqlite")
    with pytest.raises(sqlite3.OperationalError):
        state.migrate()
    assert state.version() == 0
    assert state.connect().execute("SELECT count(*) FROM sqlite_master WHERE name = 't'").fetchone()[0] == 0


def test_connection_uses_wal_and_foreign_keys(tmp_path):
    con = State(tmp_path / "state.sqlite").connect()
    assert con.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert con.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert con.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
    assert con.row_factory is sqlite3.Row


def test_users_role_is_constrained(tmp_path):
    con = _migrated(tmp_path).connect()
    with pytest.raises(sqlite3.IntegrityError):
        _add_user(con, "admin", role="root")


def test_usernames_are_unique_ignoring_case(tmp_path):
    con = _migrated(tmp_path).connect()
    _add_user(con, "admin")
    with pytest.raises(sqlite3.IntegrityError):
        _add_user(con, "Admin")


def test_deleting_a_user_keeps_their_eula_acceptance_and_jobs(tmp_path):
    con = _migrated(tmp_path).connect()
    _add_user(con, "admin")
    user_id = con.execute("SELECT id FROM users WHERE username = 'admin'").fetchone()[0]
    with con:
        con.execute("INSERT INTO eula_acceptances (version, accepted_at, user_id) VALUES ('1', ?, ?)", (NOW, user_id))
        con.execute(
            "INSERT INTO jobs (id, name, requested_by, requested_at, status) VALUES ('j1', 'x', ?, ?, 'succeeded')",
            (user_id, NOW),
        )
    with con:
        con.execute("DELETE FROM users WHERE id = ?", (user_id,))
    assert [tuple(row) for row in con.execute("SELECT version, user_id FROM eula_acceptances")] == [("1", None)]
    assert [tuple(row) for row in con.execute("SELECT id, requested_by FROM jobs")] == [("j1", None)]


def test_jobs_refer_to_existing_users(tmp_path):
    con = _migrated(tmp_path).connect()
    with pytest.raises(sqlite3.IntegrityError), con:
        con.execute(
            "INSERT INTO jobs (id, name, requested_by, requested_at, status) VALUES ('j1', 'x', 42, ?, 'queued')",
            (NOW,),
        )


def test_migration_3_creates_the_survey_tables(tmp_path):
    con = _migrated(tmp_path).connect()
    tables = {row["name"] for row in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"surveys", "survey_sensors", "survey_corrections"} <= tables
    with pytest.raises(sqlite3.IntegrityError):
        with con:
            con.execute(
                "INSERT INTO surveys (id, status, source, created_at, updated_at) "
                "VALUES ('0123abcd-si', 'elsewhere', 'ui', ?, ?)",
                (NOW, NOW),
            )


def test_migration_four_creates_the_consents_table(tmp_path):
    con = _migrated(tmp_path).connect()
    columns = [row["name"] for row in con.execute("PRAGMA table_info(sharing_consents)")]
    assert columns == ["id", "target", "consent", "granted", "notice_version", "at", "user_id", "note"]
    with pytest.raises(sqlite3.IntegrityError):
        with con:
            con.execute(
                "INSERT INTO sharing_consents (target, consent, granted, notice_version, at) "
                "VALUES ('maintainer', 'other', 1, 'v1', ?)",
                (NOW,),
            )


def test_migration_five_turns_bearings_into_headings(tmp_path, monkeypatch):
    """survey_bearings becomes survey_sensors with a heading in degrees (an old bearing's centre, else NULL), each
    place's rows in their order and the map columns kept; a bearing correction becomes a heading_deg one."""
    monkeypatch.setattr("tm_control.core.state.MIGRATIONS", MIGRATIONS[:4])
    state = _migrated(tmp_path)
    con = state.connect()
    with con:
        con.execute(
            "INSERT INTO surveys (id, status, source, created_at, updated_at) "
            "VALUES ('0123abcd-si', 'used', 'ui', ?, ?)",
            (NOW, NOW),
        )
        con.executemany(
            "INSERT INTO survey_bearings (survey_id, sensor_type, sensor_name, bearing, map_block_ref, map_side) "
            "VALUES ('0123abcd-si', ?, ?, ?, ?, ?)",
            [
                ("radars", "TM_RADAR_SERIAL_PORT_00", "ne", None, None),
                ("cameras", "picam_h265", "", "block-7", "left"),
                ("airquality_monitors", "sensorname01", " NW ", None, "both"),
            ],
        )
        con.executemany(
            "INSERT INTO survey_corrections "
            "(id, survey_id, deployment_id, field, old_value, new_value, reason, source, at) "
            "VALUES (?, '0123abcd-si', ?, ?, ?, ?, ?, 'ui', ?)",
            [
                (7, "1-0123abcd-d", "bearing", "n", "e", "Compass check", NOW),
                (9, None, "location", "45.0,-122.0", None, None, NOW),
                (11, "2-0123abcd-d", "bearing", "", "up", None, NOW),
            ],
        )
    con.close()

    monkeypatch.setattr("tm_control.core.state.MIGRATIONS", MIGRATIONS[:5])
    assert state.migrate() == 5
    con = state.connect()
    tables = {row["name"] for row in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert "survey_bearings" not in tables
    rows = [tuple(row) for row in con.execute(
        "SELECT survey_id, sensor_type, sensor_name, heading_deg, map_block_ref, map_side FROM survey_sensors "
        "ORDER BY rowid"
    )]
    assert rows == [
        ("0123abcd-si", "radars", "TM_RADAR_SERIAL_PORT_00", 45, None, None),
        ("0123abcd-si", "cameras", "picam_h265", None, "block-7", "left"),
        ("0123abcd-si", "airquality_monitors", "sensorname01", 315, None, "both"),
    ]
    corrections = [tuple(row) for row in con.execute(
        "SELECT id, survey_id, deployment_id, field, old_value, new_value, reason, source, at FROM survey_corrections "
        "ORDER BY id"
    )]
    assert corrections == [
        (7, "0123abcd-si", "1-0123abcd-d", "heading_deg", "0", "90", "Compass check", "ui", NOW),
        (9, "0123abcd-si", None, "location", "45.0,-122.0", None, None, "ui", NOW),
        (11, "0123abcd-si", "2-0123abcd-d", "heading_deg", None, None, None, "ui", NOW),
    ]
    indexes = {row["name"] for row in con.execute("SELECT name FROM sqlite_master WHERE type = 'index'")}
    assert "survey_corrections_survey" in indexes

    with pytest.raises(sqlite3.IntegrityError), con:
        con.execute(
            "INSERT INTO survey_sensors (survey_id, sensor_type, sensor_name, heading_deg) "
            "VALUES ('0123abcd-si', 'cameras', 'other', 360)"
        )
    with pytest.raises(sqlite3.IntegrityError), con:
        con.execute(
            "INSERT INTO survey_corrections (survey_id, field, source, at) VALUES ('0123abcd-si', 'bearing', 'ui', ?)",
            (NOW,),
        )
    with pytest.raises(sqlite3.IntegrityError), con:
        con.execute(
            "INSERT INTO survey_sensors (survey_id, sensor_type, sensor_name, map_side) "
            "VALUES ('0123abcd-si', 'cameras', 'other', 'middle')"
        )
    with con:
        con.execute("DELETE FROM surveys WHERE id = '0123abcd-si'")  # the rows go with their place, as before
    assert con.execute("SELECT count(*) FROM survey_sensors").fetchone()[0] == 0
    assert con.execute("SELECT count(*) FROM survey_corrections").fetchone()[0] == 0


def test_migration_six_adds_the_mounting_columns(tmp_path, monkeypatch):
    """The five facts' other four join a sensor's row: a row written before keeps its heading and NULLs, and measured
    is one of pitch or distance."""
    monkeypatch.setattr("tm_control.core.state.MIGRATIONS", MIGRATIONS[:5])
    state = _migrated(tmp_path)
    con = state.connect()
    with con:
        con.execute(
            "INSERT INTO surveys (id, status, source, created_at, updated_at) "
            "VALUES ('0123abcd-si', 'used', 'ui', ?, ?)",
            (NOW, NOW),
        )
        con.execute(
            "INSERT INTO survey_sensors (survey_id, sensor_type, sensor_name, heading_deg, map_block_ref) "
            "VALUES ('0123abcd-si', 'cameras', 'picam_h265', 40, 'block-7')"
        )
    con.close()

    monkeypatch.setattr("tm_control.core.state.MIGRATIONS", MIGRATIONS[:6])
    assert state.migrate() == 6
    con = state.connect()
    columns = [row["name"] for row in con.execute("PRAGMA table_info(survey_sensors)")]
    assert columns == [
        "survey_id", "sensor_type", "sensor_name", "heading_deg", "map_block_ref", "map_side",
        "pitch_deg", "height_m", "view_distance_m", "measured", "mount",
    ]
    row = con.execute("SELECT * FROM survey_sensors").fetchone()
    assert (row["heading_deg"], row["map_block_ref"]) == (40, "block-7")
    assert [row[key] for key in ("pitch_deg", "height_m", "view_distance_m", "measured", "mount")] == [None] * 5
    with con:
        con.execute(
            "UPDATE survey_sensors SET pitch_deg = 15.0, height_m = 3.66, view_distance_m = 13.66, "
            "measured = 'pitch', mount = 'pole'"
        )
    with pytest.raises(sqlite3.IntegrityError), con:
        con.execute("UPDATE survey_sensors SET measured = 'both'")


def test_migration_seven_leaves_every_row_confirmed(tmp_path, monkeypatch):
    """A row's mounting is marked unconfirmed when a move brings it back; every row from before holds what the file
    has, so it stays confirmed."""
    monkeypatch.setattr("tm_control.core.state.MIGRATIONS", MIGRATIONS[:6])
    state = _migrated(tmp_path)
    con = state.connect()
    with con:
        con.execute(
            "INSERT INTO surveys (id, status, source, created_at, updated_at) "
            "VALUES ('0123abcd-si', 'used', 'ui', ?, ?)",
            (NOW, NOW),
        )
        con.execute(
            "INSERT INTO survey_sensors (survey_id, sensor_type, sensor_name, heading_deg, pitch_deg, height_m, "
            "measured, mount) VALUES ('0123abcd-si', 'cameras', 'picam_h265', 40, 15.0, 3.66, 'pitch', 'pole')"
        )
    con.close()

    monkeypatch.setattr("tm_control.core.state.MIGRATIONS", MIGRATIONS)
    assert state.migrate() == 8
    con = state.connect()
    columns = [row["name"] for row in con.execute("PRAGMA table_info(survey_sensors)")]
    assert columns[-1] == "unconfirmed"
    row = con.execute("SELECT * FROM survey_sensors").fetchone()
    assert (row["heading_deg"], row["height_m"], row["mount"], row["unconfirmed"]) == (40, 3.66, "pole", 0)
    with pytest.raises(sqlite3.IntegrityError), con:
        con.execute("UPDATE survey_sensors SET unconfirmed = 2")


def test_migration_8_adds_the_zone_and_keeps_every_place(tmp_path, monkeypatch):
    """A place from before keeps every column and has no time zone."""
    monkeypatch.setattr("tm_control.core.state.MIGRATIONS", MIGRATIONS[:7])
    state = _migrated(tmp_path)
    con = state.connect()
    with con:
        con.execute(
            "INSERT INTO surveys (id, description, lat, lon, status, source, created_at, updated_at) "
            "VALUES ('0123abcd-si', 'a note', 45.0, -122.0, 'used', 'ui', ?, ?)",
            (NOW, NOW),
        )
    con.close()

    monkeypatch.setattr("tm_control.core.state.MIGRATIONS", MIGRATIONS)
    assert state.migrate() == 8
    con = state.connect()
    assert [row["name"] for row in con.execute("PRAGMA table_info(surveys)")][-1] == "timezone"
    row = con.execute("SELECT * FROM surveys").fetchone()
    assert (row["id"], row["description"], row["lat"], row["lon"], row["status"]) == (
        "0123abcd-si", "a note", 45.0, -122.0, "used")
    assert row["timezone"] is None
