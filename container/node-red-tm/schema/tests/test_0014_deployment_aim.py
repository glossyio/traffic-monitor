"""0014 adds the eight aim columns to deployment: columns only, and the rows already there are left as they are."""

import sqlite3

from helpers import LATEST_VERSION, LEGACY_SCHEMA, SCHEMA_DIR, columns, create_db, migrate, query, user_version

NEW_COLUMNS = {
    "road_angle_deg": "REAL",
    "lane_distance_m": "REAL",
    "lane_width_m": "REAL",
    "lanes_toward": "INTEGER",
    "lanes_away": "INTEGER",
    "turn_lane": "INTEGER",
    "toward_side": "TEXT",
    "intersection": "INTEGER",
}


def at_version_13(tmp_path):
    """A database migrated through 0013 only, with one open and one closed deployment."""
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    for path in sorted((SCHEMA_DIR / "migrations").glob("*.sql"))[:13]:
        (migrations / path.name).write_text(path.read_text())
    db_path = tmp_path / "db" / "tmdb.sqlite"
    db_path.parent.mkdir()
    assert migrate("--db", db_path, "--migrations", migrations) == 0
    con = sqlite3.connect(db_path)
    for number, end in enumerate((None, 2000)):
        con.execute("INSERT INTO deployment (id, entryStartDateTime, entryEndDateTime, lat, lon, sensorType,"
                    " sensorName, deviceName, survey_id, location_precision, heading_deg, timezone)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (f"{number}-d", 1000 + number, end, 45.0, -122.0, "radars", "radar_1_3fa9c2",
                     "tm-test", "ab12cd34-si", 2, 90, "America/New_York"))
    con.commit()
    con.close()
    return db_path


def test_0014_adds_the_eight_columns_and_rewrites_no_row(tmp_path):
    db_path = at_version_13(tmp_path)
    before = query(db_path, "SELECT * FROM deployment ORDER BY id")
    assert user_version(db_path) == 13
    assert migrate("--db", db_path, "--backup-dir", tmp_path / "backup") == 0
    assert user_version(db_path) == LATEST_VERSION
    names = columns(db_path, "deployment")
    start = names.index("timezone")
    assert names[start:start + 9] == ["timezone", *NEW_COLUMNS]
    types = {row[1]: row[2] for row in query(db_path, "PRAGMA table_info(deployment)")}
    assert {name: types[name] for name in NEW_COLUMNS} == NEW_COLUMNS
    after = query(db_path, "SELECT * FROM deployment ORDER BY id")
    assert len(before) == 2
    assert [row[:len(before[0]) + 8] for row in after] == [row + (None,) * 8 for row in before]


def test_0014_applies_to_a_legacy_shaped_deployment_table(tmp_path):
    db_path = tmp_path / "tmdb.sqlite"
    create_db(db_path, LEGACY_SCHEMA.read_text())
    assert migrate("--db", db_path, "--backup-dir", tmp_path / "backup") == 0
    assert user_version(db_path) == LATEST_VERSION
    names = columns(db_path, "deployment")
    assert "timezone" in names
    start = names.index("timezone")
    assert names[start + 1:start + 9] == list(NEW_COLUMNS)
