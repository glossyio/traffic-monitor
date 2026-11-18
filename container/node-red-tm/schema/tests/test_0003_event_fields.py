"""0003 adds the event fields: columns only, and the rows already there are left as they are."""

import sqlite3

from helpers import LATEST_VERSION, SCHEMA_DIR, columns, migrate, query, user_version

NEW_COLUMNS = {
    "path_data": "TEXT", "box": "TEXT", "best_box": "TEXT", "best_frame_time": "REAL", "frigate_speed": "REAL",
    "frigate_speed_unit": "TEXT", "frigate_velocity_angle": "REAL", "speed_unit": "TEXT", "speed_source": "TEXT",
    "radar_readings": "INTEGER",
}


def at_version_2(tmp_path):
    """A database migrated through 0002 only, with one event that has a radar speed."""
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    for name in ("0001_baseline.sql", "0002_deployment_survey.sql"):
        (migrations / name).write_text((SCHEMA_DIR / "migrations" / name).read_text())
    db_path = tmp_path / "tmdb.sqlite"
    assert migrate("--db", db_path, "--migrations", migrations) == 0
    con = sqlite3.connect(db_path)
    con.execute("INSERT INTO events (id, camera, label, sub_label, speed_calc) VALUES (?, ?, ?, ?, ?)",
                ("1761800000.1-abc123", "camera_1_3fa9c2", "car", "a name from before", 22.5))
    con.commit()
    con.close()
    return db_path


def test_0003_adds_the_columns_and_rewrites_nothing(tmp_path):
    db_path = at_version_2(tmp_path)
    assert user_version(db_path) == 2
    assert migrate("--db", db_path, "--backup-dir", tmp_path / "backup") == 0
    assert user_version(db_path) == LATEST_VERSION == 3
    assert columns(db_path, "events")[-len(NEW_COLUMNS):] == list(NEW_COLUMNS)
    types = {row[1]: row[2] for row in query(db_path, "PRAGMA table_info(events)")}
    assert {name: types[name] for name in NEW_COLUMNS} == NEW_COLUMNS
    assert query(db_path, "SELECT sub_label, speed_calc, speed_unit, speed_source, path_data FROM events") == [
        ("a name from before", 22.5, None, None, None)]
