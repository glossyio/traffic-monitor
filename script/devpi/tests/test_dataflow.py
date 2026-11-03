"""The database: schema current, no plate reads, new radar and event rows when there's traffic, and
deployment rows that are rounded, one open per enabled sensor, and on the configured survey.

Every test here reads tmdb.sqlite, so they run only on units marked pii_free, and they
print only counts, timestamps, sensor names, and survey ids.
"""

import re

import pytest
from devpi_checks import db_query, pi_now, require_pii_free

MAX_RADAR_AGE_SECONDS = 15 * 60
MAX_EVENT_AGE_SECONDS = 60 * 60


@pytest.fixture(autouse=True)
def pii_free_only(expect):
    require_pii_free(expect)


def test_schema_current(host, codedir, codeowner):
    """tmdb_migrate.py --check exits 0: no pending migrations and no drift."""
    runner = f"{codedir}/node-red-tm/schema/tmdb_migrate.py"
    # Code from before the migrations (#208) leaves no ExecStartPre; a runner left by an
    # earlier deploy would then report the unmigrated database as pending.
    if runner not in host.file("/etc/containers/systemd/node-red-tm.container").content_string:
        pytest.skip("the deployed node-red-tm.container doesn't run tmdb_migrate.py (code from before #208)")
    with host.sudo():
        result = host.run(f"runuser -u {codeowner} -- python3 {runner} "
                          f"--db {codedir}/node-red-tm/db/tmdb.sqlite --check")
    assert result.rc == 0, f"exit {result.rc}: {result.stderr.strip()}"


def test_no_plate_reads(host, codedir):
    count = db_query(host, codedir, "SELECT COUNT(*) FROM plate_recognizer")[0][0]
    assert count == 0, f"plate_recognizer has {count} rows on a unit marked pii_free"


def newest_age(host, codedir, table, column):
    newest = db_query(host, codedir, f"SELECT MAX({column}) FROM {table}")[0][0]
    return None if newest is None else pi_now(host) - newest


def test_new_radar_rows(host, expect, codedir):
    if not (expect["live_traffic"] and expect["radars"]):
        pytest.skip("needs live_traffic and a radar")
    age = newest_age(host, codedir, "radar_dov", "time")
    assert age is not None, "radar_dov is empty"
    assert age < MAX_RADAR_AGE_SECONDS, f"newest radar_dov row is {age / 60:.0f} minutes old"


def test_new_events(host, expect, codedir):
    if not (expect["live_traffic"] and expect["cameras"]):
        pytest.skip("needs live_traffic and a camera")
    age = newest_age(host, codedir, "events", "end_time")
    assert age is not None, "events is empty"
    assert age < MAX_EVENT_AGE_SECONDS, f"newest event is {age / 60:.0f} minutes old"


def test_deployment_rows_are_never_finer_than_two_decimals(host, codedir):
    """tmdb keeps no coordinate finer than two decimal places, and lat, lon and location_precision
    are all set or all NULL."""
    # lat * 100 against its nearest whole number, so a value stored as Number(x.toFixed(2)) and one
    # from SQLite's ROUND both pass even if they differ in the last bit
    finer = db_query(host, codedir, "SELECT COUNT(*) FROM deployment WHERE lat IS NOT NULL AND "
                                    "(ABS(lat * 100 - ROUND(lat * 100)) > 1e-6 "
                                    "OR ABS(lon * 100 - ROUND(lon * 100)) > 1e-6)")[0][0]
    assert finer == 0, f"{finer} deployment rows have a coordinate finer than two decimal places"
    half = db_query(host, codedir, "SELECT COUNT(*) FROM deployment WHERE (lat IS NULL) != (lon IS NULL) "
                                   "OR (lat IS NULL) != (location_precision IS NULL)")[0][0]
    assert half == 0, f"{half} deployment rows have only some of lat, lon and location_precision"


def enabled_sensors(node_red_config):
    """(sensorType, sensorName) of each enabled sensor in config.yml. The engine leaves the rows of
    disabled sensors alone, so the deployment checks look only at these."""
    return {(sensor_type, name)
            for sensor_type, sensors in (node_red_config.get("sensors") or {}).items()
            for name, sensor in (sensors or {}).items() if (sensor or {}).get("enabled") is True}


def test_each_enabled_sensor_has_one_open_deployment(host, codedir, node_red_config):
    """Each enabled sensor in config.yml has exactly one open deployment row."""
    counts = {(sensor_type, name): count for sensor_type, name, count in db_query(
        host, codedir, "SELECT sensorType, sensorName, COUNT(*) FROM deployment "
                       "WHERE entryEndDateTime IS NULL GROUP BY sensorType, sensorName")}
    wrong = sorted(f"{sensor_type}.{name}: {counts.get((sensor_type, name), 0)}"
                   for sensor_type, name in enabled_sensors(node_red_config)
                   if counts.get((sensor_type, name), 0) != 1)
    assert not wrong, f"enabled sensors without exactly one open deployment row: {', '.join(wrong)}"


def test_open_deployments_carry_the_configured_survey(host, codedir, node_red_config):
    """Once config.yml names a survey, every enabled sensor's open deployment row carries it."""
    survey_id = str((node_red_config.get("deployment") or {}).get("survey_id") or "").lower()
    if not survey_id:
        pytest.skip("config.yml sets no deployment.survey_id")
    if not re.fullmatch(r"[0-9a-f]{8}-si", survey_id):
        pytest.fail("config.yml's deployment.survey_id isn't a survey id (8 hex characters and -si)", pytrace=False)
    enabled = enabled_sensors(node_red_config)
    rows = db_query(host, codedir, "SELECT sensorType, sensorName, survey_id FROM deployment "
                                   "WHERE entryEndDateTime IS NULL")
    wrong = sorted(f"{sensor_type}.{name}: {row_survey}" for sensor_type, name, row_survey in rows
                   if (sensor_type, name) in enabled and row_survey != survey_id)
    assert not wrong, f"open deployment rows without the configured survey {survey_id}: {', '.join(wrong)}"
