"""0004 adds the watch log's two tables and leaves every other table as it is."""

import sqlite3

import pytest

from helpers import ALL_TABLES, BASELINE_TABLES, LATEST_VERSION, SCHEMA_DIR, migrate, query, tables, user_version

WATCH_CAMERA = {
    "time": "INTEGER", "camera": "TEXT", "config_enabled": "INTEGER", "deployment_id": "TEXT",
    "frigate_answers": "INTEGER", "camera_answers": "INTEGER", "camera_fps": "REAL", "process_fps": "REAL",
    "skipped_fps": "REAL", "detection_fps": "REAL", "detection_enabled": "INTEGER",
    "camera_on": "INTEGER",
}
WATCH_RADAR = {"time": "INTEGER", "radar": "TEXT", "config_enabled": "INTEGER", "deployment_id": "TEXT",
               "port_open": "INTEGER", "last_reading_at": "REAL", "radar_answers": "INTEGER",
               "radar_on": "INTEGER"}


def at_version_3(tmp_path):
    """A database migrated through 0003 only, with one event."""
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    for name in ("0001_baseline.sql", "0002_deployment_survey.sql", "0003_event_fields.sql"):
        (migrations / name).write_text((SCHEMA_DIR / "migrations" / name).read_text())
    db_path = tmp_path / "tmdb.sqlite"
    assert migrate("--db", db_path, "--migrations", migrations) == 0
    con = sqlite3.connect(db_path)
    con.execute("INSERT INTO events (id, camera, label, speed_calc) VALUES (?, ?, ?, ?)",
                ("1761800000.1-abc123", "camera_1_3fa9c2", "car", 22.5))
    con.commit()
    con.close()
    return db_path


def test_0004_adds_the_two_tables_and_rewrites_nothing(tmp_path):
    db_path = at_version_3(tmp_path)
    before = query(db_path, "SELECT * FROM events")
    assert user_version(db_path) == 3 and tables(db_path) == BASELINE_TABLES
    assert migrate("--db", db_path, "--backup-dir", tmp_path / "backup") == 0
    assert user_version(db_path) == LATEST_VERSION
    assert tables(db_path) == ALL_TABLES == BASELINE_TABLES | {"watch_camera", "watch_radar"}
    for table, expected in (("watch_camera", WATCH_CAMERA), ("watch_radar", WATCH_RADAR)):
        info = query(db_path, f"PRAGMA table_info({table})")
        assert {row[1]: row[2] for row in info} == expected
        assert [row[1] for row in info] == list(expected)
        # the primary key: the mark, then the sensor
        assert sorted((row[5], row[1]) for row in info if row[5]) == [(1, "time"), (2, list(expected)[1])]
    # later migrations may add columns at the end; the ones there before keep their values
    assert [row[:len(before[0])] for row in query(db_path, "SELECT * FROM events")] == before


def test_a_sensor_has_one_row_per_window(tmp_path):
    db_path = tmp_path / "tmdb.sqlite"
    assert migrate("--db", db_path) == 0
    con = sqlite3.connect(db_path)
    con.execute("INSERT INTO watch_camera (time, camera) VALUES (1761800100, 'camera_1_3fa9c2')")
    con.execute("INSERT INTO watch_camera (time, camera) VALUES (1761800400, 'camera_1_3fa9c2')")
    with pytest.raises(sqlite3.IntegrityError):
        con.execute("INSERT INTO watch_camera (time, camera) VALUES (1761800100, 'camera_1_3fa9c2')")
    con.close()


@pytest.mark.parametrize("table", ["watch_camera", "watch_radar"])
def test_the_watch_tables_keep_no_rowid(tmp_path, table):
    """WITHOUT ROWID: the rows are stored by their key, with no hidden row number and no second copy of the key."""
    db_path = tmp_path / "tmdb.sqlite"
    assert migrate("--db", db_path) == 0
    con = sqlite3.connect(db_path)
    with pytest.raises(sqlite3.OperationalError, match="no such column: rowid"):
        con.execute(f"SELECT rowid FROM {table}")
    assert con.execute("SELECT rowid FROM events").fetchall() == []  # an ordinary table still has one
    con.close()
