"""0011 adds the four mounting columns to deployment: columns only, and the rows already there are left as they are."""

import sqlite3

from helpers import LATEST_VERSION, LEGACY_SCHEMA, SCHEMA_DIR, columns, create_db, migrate, query, user_version

NEW_COLUMNS = {"pitch_deg": "REAL", "height_m": "REAL", "view_distance_m": "REAL", "mount": "TEXT"}


def at_version_10(tmp_path):
    """A database migrated through 0010 only, with one open and one closed deployment."""
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    for path in sorted((SCHEMA_DIR / "migrations").glob("*.sql"))[:10]:
        (migrations / path.name).write_text(path.read_text())
    db_path = tmp_path / "db" / "tmdb.sqlite"
    db_path.parent.mkdir()
    assert migrate("--db", db_path, "--migrations", migrations) == 0
    con = sqlite3.connect(db_path)
    for number, end in enumerate((None, 2000)):
        con.execute("INSERT INTO deployment (id, entryStartDateTime, entryEndDateTime, lat, lon, sensorType,"
                    " sensorName, deviceName, survey_id, location_precision, heading_deg)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (f"{number}-d", 1000 + number, end, 45.0, -122.0, "cameras", "camera_1_3fa9c2",
                     "tm-test", "ab12cd34-si", 2, 90))
    con.commit()
    con.close()
    return db_path


def test_0011_adds_the_four_columns_and_rewrites_no_row(tmp_path):
    db_path = at_version_10(tmp_path)
    before = query(db_path, "SELECT * FROM deployment ORDER BY id")
    assert user_version(db_path) == 10
    assert migrate("--db", db_path, "--backup-dir", tmp_path / "backup") == 0
    assert user_version(db_path) == LATEST_VERSION
    names = columns(db_path, "deployment")
    assert names[-5:] == ["heading_deg", *NEW_COLUMNS]
    types = {row[1]: row[2] for row in query(db_path, "PRAGMA table_info(deployment)")}
    assert {name: types[name] for name in NEW_COLUMNS} == NEW_COLUMNS
    after = query(db_path, "SELECT * FROM deployment ORDER BY id")
    assert len(before) == 2
    assert after == [row + (None, None, None, None) for row in before]


def test_0011_applies_to_a_legacy_shaped_deployment_table(tmp_path):
    db_path = tmp_path / "tmdb.sqlite"
    create_db(db_path, LEGACY_SCHEMA.read_text())
    assert migrate("--db", db_path, "--backup-dir", tmp_path / "backup") == 0
    assert user_version(db_path) == LATEST_VERSION
    names = columns(db_path, "deployment")
    assert names[-4:] == list(NEW_COLUMNS)
    assert "heading_deg" in names
