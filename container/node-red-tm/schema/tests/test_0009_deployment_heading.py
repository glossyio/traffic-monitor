"""0008 to 0010: heading_deg takes the place of bearing, and the old text is kept only in the runner's backup."""

import sqlite3

import pytest

from helpers import LATEST_VERSION, LEGACY_SCHEMA, SCHEMA_DIR, columns, create_db, files_in, migrate, query, user_version

OLD_COLUMNS = ["id", "entryStartDateTime", "entryEndDateTime", "lat", "lon", "bearing", "sensorType",
               "sensorName", "deviceName", "survey_id", "location_precision"]
LATER_COLUMNS = ["pitch_deg", "height_m", "view_distance_m", "mount", "timezone"]  # the columns later migrations add (0011: the four mounting columns; 0012: timezone), after the file under test
NEW_COLUMNS = [name for name in OLD_COLUMNS if name != "bearing"] + ["heading_deg"] + LATER_COLUMNS


def at_version(tmp_path, version, bearings=()):
    """A database migrated through the given version only, with one deployment row for each bearing given."""
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    for path in sorted((SCHEMA_DIR / "migrations").glob("*.sql"))[:version]:
        (migrations / path.name).write_text(path.read_text())
    db_path = tmp_path / "db" / "tmdb.sqlite"
    db_path.parent.mkdir()
    assert migrate("--db", db_path, "--migrations", migrations) == 0
    assert user_version(db_path) == version
    con = sqlite3.connect(db_path)
    for number, bearing in enumerate(bearings):
        con.execute("INSERT INTO deployment (id, entryStartDateTime, entryEndDateTime, lat, lon, bearing, sensorType,"
                    " sensorName, deviceName, survey_id, location_precision) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (f"{number}-d", 1000 + number, None, 45.0, -122.0, bearing, "cameras", "camera_1_3fa9c2",
                     "tm-test", "ab12cd34-si", 2))
    con.commit()
    con.close()
    return db_path


def at_version_7(tmp_path, bearings=()):
    return at_version(tmp_path, 7, bearings)


def add_view_on_bearing(db_path):
    """A view on the device that names deployment.bearing, which makes DROP COLUMN fail."""
    con = sqlite3.connect(db_path)
    con.execute("CREATE VIEW old_bearings AS SELECT id, bearing FROM deployment")
    con.commit()
    con.close()


@pytest.mark.parametrize("bearing, heading", [
    ("n", 0), ("NE", 45), (" e ", 90), ("se", 135), ("s", 180), ("sw", 225), ("w", 270), ("nw", 315),
    ("ne\t", 45), ("\tSw", 225), ("\nNe\n", 45), ("\r\nNW\r\n", 315), (" \t\x0b\x0c\r\n S \n", 180),
    ("", None), (None, None), ("null", None), ("undefined", None), ("north", None), (45, None),
])
def test_bearings_become_headings(tmp_path, bearing, heading):
    db_path = at_version_7(tmp_path, [bearing])

    assert migrate("--db", db_path) == 0

    assert user_version(db_path) == LATEST_VERSION
    assert query(db_path, "SELECT heading_deg FROM deployment") == [(heading,)]


def test_the_bearing_column_is_gone_and_nothing_else_changed(tmp_path):
    db_path = at_version_7(tmp_path, ["ne", "w"])
    con = sqlite3.connect(db_path)
    con.execute("UPDATE deployment SET entryEndDateTime = 2000 WHERE id = '0-d'")  # one closed row, one open
    con.commit()
    con.close()
    before = query(db_path, "SELECT id, entryStartDateTime, entryEndDateTime, lat, lon, sensorType, sensorName,"
                            " deviceName, survey_id, location_precision FROM deployment ORDER BY id")
    assert columns(db_path, "deployment") == OLD_COLUMNS

    assert migrate("--db", db_path) == 0

    assert columns(db_path, "deployment") == NEW_COLUMNS
    assert query(db_path, "SELECT id, entryStartDateTime, entryEndDateTime, lat, lon, sensorType, sensorName,"
                          " deviceName, survey_id, location_precision FROM deployment ORDER BY id") == before
    assert query(db_path, "SELECT id, heading_deg FROM deployment ORDER BY id") == [("0-d", 45), ("1-d", 270)]


def test_the_backup_from_before_still_holds_the_bearing(tmp_path):
    db_path = at_version_7(tmp_path, ["se"])

    assert migrate("--db", db_path) == 0

    backups = files_in(db_path.parent / "backup")
    assert len(backups) == 1 and backups[0].startswith("tmdb-v7-")
    old = db_path.parent / "backup" / backups[0]
    assert columns(old, "deployment") == OLD_COLUMNS
    assert query(old, "SELECT bearing FROM deployment") == [("se",)]


def test_a_fresh_database_has_no_bearing(db_path):
    assert migrate("--db", db_path) == 0

    assert user_version(db_path) == LATEST_VERSION
    assert columns(db_path, "deployment") == NEW_COLUMNS
    assert "bearing" not in columns(db_path, "deployment")


@pytest.mark.parametrize("start", ["empty", "legacy"])
def test_the_setup_view_still_reads_after_the_drop(db_path, start):
    # 0007's events_with_setup is in the schema when 0010 drops bearing, and SQLite checks every view on a drop
    if start == "legacy":
        create_db(db_path, LEGACY_SCHEMA.read_text())  # what 0.7.1 and earlier leave, bearing included
        assert "bearing" in columns(db_path, "deployment")

    assert migrate("--db", db_path) == 0

    assert user_version(db_path) == LATEST_VERSION
    assert "bearing" not in columns(db_path, "deployment")
    assert query(db_path, "SELECT * FROM events_with_setup LIMIT 0") == []


def test_a_row_that_already_has_a_heading_keeps_it(tmp_path):
    # At version 8 the flows already write heading_deg, so 0009 fills only the rows that have none.
    db_path = at_version(tmp_path, 8, ["n", "ne"])
    con = sqlite3.connect(db_path)
    con.execute("UPDATE deployment SET heading_deg = 90 WHERE id = '0-d'")
    con.commit()
    con.close()

    assert migrate("--db", db_path) == 0

    assert query(db_path, "SELECT id, heading_deg FROM deployment ORDER BY id") == [("0-d", 90), ("1-d", 45)]


def test_a_drop_that_fails_leaves_the_rows_converted(tmp_path, capsys):
    db_path = at_version_7(tmp_path, ["ne"])
    add_view_on_bearing(db_path)

    assert migrate("--db", db_path) == 1

    assert user_version(db_path) == 9
    assert query(db_path, "SELECT id, bearing, heading_deg FROM deployment") == [("0-d", "ne", 45)]
    assert "0010_deployment_drop_bearing.sql failed and was rolled back" in capsys.readouterr().err


def test_rows_written_before_a_failed_drop_is_retried_keep_their_heading(tmp_path):
    db_path = at_version_7(tmp_path, ["ne"])
    add_view_on_bearing(db_path)
    assert migrate("--db", db_path) == 1
    con = sqlite3.connect(db_path)  # Node-RED runs at version 9 and records a deployment, then the view goes
    con.execute("INSERT INTO deployment (id, entryStartDateTime, lat, lon, sensorType, sensorName, deviceName,"
                " survey_id, location_precision, heading_deg) VALUES ('1-d', 2000, 45.0, -122.0, 'cameras',"
                " 'camera_1_3fa9c2', 'tm-test', 'ab12cd34-si', 2, 90)")
    con.execute("DROP VIEW old_bearings")
    con.commit()
    con.close()

    assert migrate("--db", db_path) == 0

    assert user_version(db_path) == LATEST_VERSION
    assert columns(db_path, "deployment") == NEW_COLUMNS
    assert query(db_path, "SELECT id, heading_deg FROM deployment ORDER BY id") == [("0-d", 45), ("1-d", 90)]
