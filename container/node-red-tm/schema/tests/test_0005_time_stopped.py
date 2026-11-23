"""0005 adds the time stopped and the time in each zone: columns only, and the rows already there are left as they are."""

import sqlite3

from helpers import LATEST_VERSION, SCHEMA_DIR, columns, migrate, query, user_version

NEW_COLUMNS = {"stationary_time": "REAL", "stops": "INTEGER", "zone_times": "TEXT"}


def at_version_4(tmp_path):
    """A database migrated through 0004 only, with one event."""
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    for path in sorted((SCHEMA_DIR / "migrations").glob("000[1-4]_*.sql")):
        (migrations / path.name).write_text(path.read_text())
    db_path = tmp_path / "tmdb.sqlite"
    assert migrate("--db", db_path, "--migrations", migrations) == 0
    con = sqlite3.connect(db_path)
    con.execute("INSERT INTO events (id, camera, label, speed_calc, direction_source) VALUES (?, ?, ?, ?, ?)",
                ("1761800000.1-abc123", "camera_1_3fa9c2", "car", 22.5, "zones_radar"))
    con.commit()
    con.close()
    return db_path


def test_0005_adds_the_columns_and_rewrites_nothing(tmp_path):
    db_path = at_version_4(tmp_path)
    before = query(db_path, "SELECT * FROM events")
    assert user_version(db_path) == 4
    assert migrate("--db", db_path, "--backup-dir", tmp_path / "backup") == 0
    assert user_version(db_path) == LATEST_VERSION
    names = columns(db_path, "events")
    start = names.index("stationary_time")
    assert names[start:start + len(NEW_COLUMNS)] == list(NEW_COLUMNS)
    types = {row[1]: row[2] for row in query(db_path, "PRAGMA table_info(events)")}
    assert {name: types[name] for name in NEW_COLUMNS} == NEW_COLUMNS
    assert query(db_path, "SELECT * FROM events") == [before[0] + (None, None, None)]
