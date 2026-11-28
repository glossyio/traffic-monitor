"""0007 adds the setup history's two tables, their indexes, and the view that ties each event to the setup in force."""

import sqlite3

from helpers import ALL_TABLES, BASELINE_TABLES, SCHEMA_DIR, columns, migrate, query, tables, user_version

SETUP_DEVICE = {
    "id": "TEXT", "started": "INTEGER", "ended": "INTEGER", "tm_version": "TEXT", "tm_commit": "TEXT",
    "schema_version": "INTEGER", "frigate_version": "TEXT", "unit_system": "TEXT", "detector": "TEXT",
    "model_id": "TEXT", "model_file": "TEXT", "model_sha256": "TEXT", "model_kind": "TEXT", "model_title": "TEXT",
    "model_trained_at": "TEXT", "model_base": "TEXT", "model_type": "TEXT", "model_width": "INTEGER",
    "model_height": "INTEGER", "labels_available": "TEXT",
}
SETUP_CAMERA = {
    "id": "TEXT", "started": "INTEGER", "ended": "INTEGER", "camera": "TEXT", "detect_width": "INTEGER",
    "detect_height": "INTEGER", "detect_fps": "INTEGER", "stationary_threshold": "INTEGER",
    "stationary_interval": "INTEGER", "lens_hfov": "REAL", "labels_tracked": "TEXT", "thresholds": "TEXT",
    "zones": "TEXT", "masks": "TEXT", "profile": "TEXT",
}


def at_version_6(tmp_path):
    """A database migrated through 0006 only."""
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    for path in sorted((SCHEMA_DIR / "migrations").glob("000[1-6]_*.sql")):
        (migrations / path.name).write_text(path.read_text())
    db_path = tmp_path / "tmdb.sqlite"
    assert migrate("--db", db_path, "--migrations", migrations) == 0
    return db_path


def migrated(tmp_path):
    db_path = tmp_path / "tmdb.sqlite"
    assert migrate("--db", db_path) == 0
    return db_path


def device_row(id, started, ended=None):
    return {"id": id, "started": started * 1000, "ended": None if ended is None else ended * 1000}


def insert(con, table, rows):
    for row in rows:
        con.execute(f"INSERT INTO {table} ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})", list(row.values()))


def add_event(con, id, camera, start_time):
    con.execute("INSERT INTO events (id, camera, label, start_time) VALUES (?, ?, 'car', ?)", (id, camera, start_time))


def test_0007_adds_the_two_tables_and_nothing_else(tmp_path):
    db_path = at_version_6(tmp_path)
    before = {name: query(db_path, f"PRAGMA table_info({name})") for name in tables(db_path)}
    assert user_version(db_path) == 6
    migrations = tmp_path / "migrations"
    (migrations / "0007_setup_history.sql").write_text((SCHEMA_DIR / "migrations" / "0007_setup_history.sql").read_text())
    assert migrate("--db", db_path, "--migrations", migrations, "--backup-dir", tmp_path / "backup") == 0
    assert user_version(db_path) == 7
    assert tables(db_path) == set(before) | {"setup_device", "setup_camera"}
    assert {"setup_device", "setup_camera"} <= ALL_TABLES - BASELINE_TABLES
    for table, expected in (("setup_device", SETUP_DEVICE), ("setup_camera", SETUP_CAMERA)):
        info = query(db_path, f"PRAGMA table_info({table})")
        assert [(row[1], row[2]) for row in info] == list(expected.items())
        assert [row[1] for row in info if row[5]] == ["id"]
        required = {"started"} | ({"camera"} if table == "setup_camera" else set())
        assert {row[1] for row in info if row[3]} == required
    for name, info in before.items():
        assert query(db_path, f"PRAGMA table_info({name})") == info
    indexes = {name for (name,) in query(db_path, "SELECT name FROM sqlite_master WHERE type = 'index'")}
    assert {"index_setup_device_started", "index_setup_camera_camera_started"} <= indexes


def test_view_columns(tmp_path):
    db_path = migrated(tmp_path)
    expected = columns(db_path, "events") + ["setup_device_id"]
    expected += [f"setup_{name}" for name in list(SETUP_DEVICE)[3:]]
    expected += ["setup_camera_id"] + [f"camera_{name}" for name in list(SETUP_CAMERA)[4:]]
    # 0013 adds the radar's columns after these; its own test checks them.
    assert columns(db_path, "events_with_setup")[:len(expected)] == expected


def test_view_joins_the_rows_in_force(tmp_path):
    db_path = migrated(tmp_path)
    con = sqlite3.connect(db_path)
    insert(con, "setup_device", [device_row("d1", 1000, 2000), device_row("d2", 2000)])
    insert(con, "setup_camera", [
        {**device_row("a1", 1000, 2000), "camera": "cam_a"}, {**device_row("a2", 2000), "camera": "cam_a"},
        {**device_row("b1", 1000), "camera": "cam_b"}])
    add_event(con, "e1", "cam_a", 1500)
    add_event(con, "e2", "cam_a", 2500)
    add_event(con, "e3", "cam_a", 2000)
    add_event(con, "e4", "cam_b", 2500)
    con.commit()
    rows = con.execute("SELECT id, setup_device_id, setup_camera_id FROM events_with_setup ORDER BY id").fetchall()
    con.close()
    assert rows == [("e1", "d1", "a1"), ("e2", "d2", "a2"), ("e3", "d2", "a2"), ("e4", "d2", "b1")]


def test_view_lists_an_event_once_whatever_the_tables_hold(tmp_path):
    db_path = migrated(tmp_path)
    con = sqlite3.connect(db_path)
    insert(con, "setup_device", [device_row("d1", 1000), device_row("d2", 1500)])
    insert(con, "setup_camera", [{**device_row("a1", 1000), "camera": "cam_a"},
                                 {**device_row("a2", 1500), "camera": "cam_a"}])
    for number in range(5):
        add_event(con, f"e{number}", "cam_a", 2000 + number)
    con.commit()
    total = con.execute("SELECT count(*) FROM events").fetchone()[0]
    assert con.execute("SELECT count(*) FROM events_with_setup").fetchone()[0] == total == 5
    assert set(con.execute("SELECT setup_device_id, setup_camera_id FROM events_with_setup")) == {("d2", "a2")}
    con.close()


def test_view_leaves_the_setup_empty_when_no_row_is_in_force(tmp_path):
    db_path = migrated(tmp_path)
    con = sqlite3.connect(db_path)
    insert(con, "setup_device", [device_row("d1", 1000)])
    insert(con, "setup_camera", [{**device_row("a1", 1000), "camera": "cam_a"}])
    add_event(con, "before", "cam_a", 500)
    add_event(con, "no_row", "cam_x", 1500)
    add_event(con, "no_camera", "", 1500)
    add_event(con, "null_camera", None, 1500)
    con.commit()
    rows = {row[0]: row[1:] for row in con.execute(
        "SELECT id, setup_device_id, setup_camera_id FROM events_with_setup")}
    con.close()
    assert rows == {"before": (None, None), "no_row": ("d1", None), "no_camera": ("d1", None),
                    "null_camera": ("d1", None)}


def test_view_shows_a_column_added_to_events_later(tmp_path):
    db_path = migrated(tmp_path)
    con = sqlite3.connect(db_path)
    add_event(con, "e1", "cam_a", 1500)
    con.commit()
    con.close()
    con = sqlite3.connect(db_path)
    con.execute("ALTER TABLE events ADD COLUMN later TEXT")
    con.commit()
    con.close()
    con = sqlite3.connect(db_path)
    assert con.execute("SELECT later FROM events_with_setup").fetchall() == [(None,)]
    con.close()
