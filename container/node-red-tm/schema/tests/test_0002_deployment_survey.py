"""0002 on synthetic rows: ids per place before rounding, rounding to two decimals, NULL pairs, and the legacy shape."""
import sqlite3
from helpers import SCHEMA_DIR, LEGACY_SCHEMA, create_db, migrate, query, user_version, columns

BASELINE = (SCHEMA_DIR / "migrations" / "0001_baseline.sql").read_text()
ROWS = [  # id, start, end, lat, lon, bearing, sensorType, sensorName
    ("1-a-d", 1, 2, 45.52252, -122.69120, "n", "cameras", "picam_h265"),      # place A, closed
    ("2-b-d", 3, None, 45.52252, -122.69120, "s", "radars", "TM_RADAR_SERIAL_PORT_00"),  # place A, open
    ("3-c-d", 4, None, 45.52, -122.69, "e", "cameras", "picam_h265"),         # place B
    ("4-d-d", 5, None, None, None, "", "cameras", "picam_h265"),             # no location
    ("5-e-d", 6, None, 45.52252, None, "w", "radars", "TM_RADAR_SERIAL_PORT_01"),  # half blank
    ("6-f-d", 7, None, "", "", "n", "radars", "TM_RADAR_SERIAL_PORT_02"),          # blank text, kept as TEXT
    ("7-g-d", 8, None, "north", -122.69120, "n", "radars", "TM_RADAR_SERIAL_PORT_03"),  # text lat
]

def v1_db(path):
    create_db(path, BASELINE, user_version=1)
    con = sqlite3.connect(path)
    con.executemany("INSERT INTO deployment (id, entryStartDateTime, entryEndDateTime, lat, lon, bearing, sensorType, sensorName)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?)", ROWS)
    con.commit(); con.close()

def test_0002_adds_columns_index_and_version(db_path):
    v1_db(db_path)
    assert migrate("--db", db_path) == 0
    assert user_version(db_path) == 2
    assert columns(db_path, "deployment")[-2:] == ["survey_id", "location_precision"]
    assert query(db_path, "SELECT name FROM sqlite_master WHERE type = 'index' AND name = 'index_events_deployment_id'")

def test_0002_assigns_one_survey_id_per_exact_place_before_rounding(db_path):
    v1_db(db_path)
    migrate("--db", db_path)
    ids = dict(query(db_path, "SELECT id, survey_id FROM deployment"))
    assert ids["1-a-d"] == ids["2-b-d"]                      # same exact place, open or closed
    assert ids["1-a-d"] != ids["3-c-d"]                      # A rounds to B's 2 dp cell, still a different place
    assert all(len(i) == 11 and i.endswith("-si") for i in (ids["1-a-d"], ids["3-c-d"]))
    assert ids["4-d-d"] is None and ids["5-e-d"] is None      # no location, no survey
    assert ids["6-f-d"] is None and ids["7-g-d"] is None      # text coordinates are no location

def test_0002_rounds_to_two_decimals_and_nulls_half_blank_pairs(db_path):
    v1_db(db_path)
    migrate("--db", db_path)
    rows = {r[0]: r[1:] for r in query(db_path, "SELECT id, lat, lon, location_precision FROM deployment")}
    assert rows["1-a-d"] == (45.52, -122.69, 2)
    assert rows["3-c-d"] == (45.52, -122.69, 2)
    assert rows["4-d-d"] == (None, None, None)
    assert rows["5-e-d"] == (None, None, None)

def test_0002_nulls_text_coordinates_instead_of_rounding_them(db_path):
    v1_db(db_path)
    assert query(db_path, "SELECT typeof(lat), typeof(lon) FROM deployment WHERE id IN ('6-f-d', '7-g-d') ORDER BY id") \
        == [("text", "text"), ("text", "real")]
    migrate("--db", db_path)
    rows = {r[0]: r[1:] for r in query(db_path, "SELECT id, lat, lon, location_precision, survey_id FROM deployment")}
    assert rows["6-f-d"] == (None, None, None, None)  # ROUND('', 2) would be 0.0
    assert rows["7-g-d"] == (None, None, None, None)

def test_0002_keeps_the_exact_rows_in_the_backup(db_path):
    v1_db(db_path)
    migrate("--db", db_path)
    [backup] = (db_path.parent / "backup").glob("tmdb-v1-*.sqlite")
    assert query(backup, "SELECT lat, lon FROM deployment WHERE id = '1-a-d'") == [(45.52252, -122.69120)]

def test_0002_from_a_released_unit_at_version_0_backs_up_as_v0(db_path):
    create_db(db_path, LEGACY_SCHEMA.read_text())  # what 0.7.1 and earlier leave: tables, user_version 0
    con = sqlite3.connect(db_path)
    con.executemany("INSERT INTO deployment (id, entryStartDateTime, entryEndDateTime, lat, lon, bearing, sensorType, sensorName)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?)", ROWS[:2])
    con.commit(); con.close()
    assert migrate("--db", db_path) == 0
    assert user_version(db_path) == 2
    [backup] = (db_path.parent / "backup").glob("tmdb-v0-*.sqlite")
    assert not list((db_path.parent / "backup").glob("tmdb-v1-*.sqlite"))
    assert query(backup, "SELECT id, lat, lon FROM deployment ORDER BY id") == [
        ("1-a-d", 45.52252, -122.69120), ("2-b-d", 45.52252, -122.69120)]
    assert query(db_path, "SELECT id, lat, lon, location_precision FROM deployment ORDER BY id") == [
        ("1-a-d", 45.52, -122.69, 2), ("2-b-d", 45.52, -122.69, 2)]

OLDEST_DEPLOYMENT = ("CREATE TABLE deployment (id TEXT PRIMARY KEY, entryDateTime REAL, lat REAL, lon REAL,"
                     " orientation TEXT, address TEXT, description TEXT);")  # the shape on the oldest devices

def test_0002_applies_to_the_legacy_deployment_shape(db_path, capsys):
    create_db(db_path, OLDEST_DEPLOYMENT)  # version 0, no other tables: baseline adds them and keeps this one
    con = sqlite3.connect(db_path)
    con.execute("INSERT INTO deployment (id, lat, lon) VALUES ('old-d', 45.52252, -122.69120)")
    con.commit(); con.close()
    assert migrate("--db", db_path) == 0
    assert user_version(db_path) == 2
    assert query(db_path, "SELECT lat, lon, location_precision, survey_id IS NOT NULL FROM deployment") == [
        (45.52, -122.69, 2, 1)]
    out = capsys.readouterr()
    assert "DRIFT" in out.out + out.err  # the missing baseline columns are reported, as today
