"""0013 adds the radar's setup history table and the radar's columns in events_with_setup."""

import sqlite3

from helpers import ALL_TABLES, LATEST_VERSION, LEGACY_SCHEMA, SCHEMA_DIR, columns, create_db, migrate, query, tables, user_version

SETUP_RADAR = {
    "id": "TEXT", "started": "INTEGER", "ended": "INTEGER", "radar": "TEXT", "part_number": "TEXT",
    "firmware_version": "TEXT", "cosine_inbound_deg": "REAL", "cosine_outbound_deg": "REAL",
    "speed_unit": "TEXT", "sampling_rate": "INTEGER", "speed_min": "REAL", "magnitude_min": "REAL",
}
RADAR_VIEW_COLUMNS = [
    "setup_radar_id", "radar_part_number", "radar_firmware_version", "radar_cosine_inbound_deg",
    "radar_cosine_outbound_deg", "radar_speed_unit", "radar_sampling_rate", "radar_speed_min",
    "radar_magnitude_min",
]


def at_version_12(tmp_path):
    """A database migrated through 0012 only, with an event and a row in each older setup table."""
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    for path in sorted((SCHEMA_DIR / "migrations").glob("*.sql"))[:12]:
        (migrations / path.name).write_text(path.read_text())
    db_path = tmp_path / "db" / "tmdb.sqlite"
    db_path.parent.mkdir()
    assert migrate("--db", db_path, "--migrations", migrations) == 0
    con = sqlite3.connect(db_path)
    add_event(con, "e1", "cam_a", 1500, "R")
    con.execute("INSERT INTO setup_device (id, started, tm_version) VALUES ('d1', 1000000, '0.0.0')")
    con.execute("INSERT INTO setup_camera (id, started, camera, detect_width) VALUES ('c1', 1000000, 'cam_a', 640)")
    con.commit()
    con.close()
    return db_path


def migrated(tmp_path):
    db_path = tmp_path / "tmdb.sqlite"
    assert migrate("--db", db_path) == 0
    return db_path


def add_event(con, id, camera, start_time, radar_name):
    con.execute("INSERT INTO events (id, camera, label, start_time, radarName) VALUES (?, ?, 'car', ?, ?)",
                (id, camera, start_time, radar_name))


def radar_row(id, radar, started, ended=None, **values):
    row = {"id": id, "radar": radar, "started": started, "ended": ended}
    row.update(values)
    return row


def insert(con, table, rows):
    for row in rows:
        con.execute(f"INSERT INTO {table} ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})", list(row.values()))


def test_0013_adds_the_table_and_rewrites_nothing(tmp_path):
    db_path = at_version_12(tmp_path)
    before_tables = {name: query(db_path, f"PRAGMA table_info({name})") for name in tables(db_path)}
    before_rows = {name: query(db_path, f"SELECT * FROM {name}") for name in ("events", "setup_device", "setup_camera")}
    assert user_version(db_path) == 12
    assert migrate("--db", db_path, "--backup-dir", tmp_path / "backup") == 0
    assert user_version(db_path) == LATEST_VERSION
    assert tables(db_path) == set(before_tables) | {"setup_radar"}
    assert "setup_radar" in ALL_TABLES
    info = query(db_path, "PRAGMA table_info(setup_radar)")
    assert [(row[1], row[2]) for row in info] == list(SETUP_RADAR.items())
    assert [row[1] for row in info if row[5]] == ["id"]
    assert {row[1] for row in info if row[3]} == {"started", "radar"}
    for name, expected in before_tables.items():
        assert query(db_path, f"PRAGMA table_info({name})") == expected
    for name, rows in before_rows.items():
        assert len(rows) == 1
        assert query(db_path, f"SELECT * FROM {name}") == rows
    indexes = {name: sql for name, sql in query(db_path, "SELECT name, sql FROM sqlite_master WHERE type = 'index'")}
    assert "(radar, started)" in indexes["index_setup_radar_radar_started"]
    assert "ON setup_radar" in indexes["index_setup_radar_radar_started"]


def test_0013_the_view_keeps_its_columns_and_adds_the_radars(tmp_path):
    db_path = at_version_12(tmp_path)
    before = columns(db_path, "events_with_setup")
    assert migrate("--db", db_path, "--backup-dir", tmp_path / "backup") == 0
    after = columns(db_path, "events_with_setup")
    assert after[:len(before)] == before
    assert after[len(before):] == RADAR_VIEW_COLUMNS
    assert [name[len("radar_"):] for name in RADAR_VIEW_COLUMNS[1:]] == list(SETUP_RADAR)[4:]


def test_0013_the_view_shows_the_radar_row_in_force(tmp_path):
    db_path = migrated(tmp_path)
    con = sqlite3.connect(db_path)
    insert(con, "setup_radar", [
        radar_row("r1", "R", 100, 200, part_number="OPS243-A", firmware_version="1.0", cosine_inbound_deg=10.5,
                  cosine_outbound_deg=20.0, speed_unit="mph", sampling_rate=10000, speed_min=1.0, magnitude_min=20.0),
        radar_row("r2", "R", 200, part_number="OPS243-A", firmware_version="1.1", cosine_inbound_deg=11.0),
        radar_row("o1", "S", 0, part_number="OPS243-C")])
    add_event(con, "first", "cam_a", 0.15, "R")
    add_event(con, "second", "cam_a", 0.25, "R")
    add_event(con, "edge", "cam_a", 0.2, "R")
    add_event(con, "before", "cam_a", 0.05, "R")
    add_event(con, "other", "cam_a", 0.15, "T")
    add_event(con, "none", "cam_a", 0.15, None)
    add_event(con, "blank", "cam_a", 0.15, "")
    con.commit()
    sql = f"SELECT id, {', '.join(RADAR_VIEW_COLUMNS)} FROM events_with_setup"
    rows = {row[0]: row[1:] for row in con.execute(sql)}
    con.close()
    first = ("r1", "OPS243-A", "1.0", 10.5, 20.0, "mph", 10000, 1.0, 20.0)
    second = ("r2", "OPS243-A", "1.1", 11.0, None, None, None, None, None)
    assert rows == {"first": first, "second": second, "edge": second, "before": (None,) * 9,
                    "other": (None,) * 9, "none": (None,) * 9, "blank": (None,) * 9}
    con = sqlite3.connect(db_path)
    assert con.execute("SELECT count(*) FROM events_with_setup").fetchone() == (7,)
    con.close()


def test_0013_applies_to_a_legacy_shaped_database(tmp_path):
    db_path = tmp_path / "tmdb.sqlite"
    create_db(db_path, LEGACY_SCHEMA.read_text())
    assert migrate("--db", db_path, "--backup-dir", tmp_path / "backup") == 0
    assert user_version(db_path) == LATEST_VERSION
    assert "setup_radar" in tables(db_path)
    assert columns(db_path, "events_with_setup")[-9:] == RADAR_VIEW_COLUMNS
    assert query(db_path, "SELECT * FROM events_with_setup LIMIT 0") == []
