"""The database: schema current, no plate reads, and new radar and event rows when there's traffic.

Every test here reads tmdb.sqlite, so they run only on units marked pii_free, and they
print only counts and timestamps.
"""

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
