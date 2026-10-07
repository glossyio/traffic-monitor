"""Environmental (air-quality) monitors: enabled in Node-RED and writing readings."""

import pytest
from devpi_checks import db_query, pi_now, require_pii_free

# The monitor reports continuously, whether or not there's traffic.
MAX_READING_AGE_SECONDS = 15 * 60


@pytest.fixture
def monitors(expect):
    if not expect["environmental"]:
        pytest.skip("no environmental monitor expected")
    return expect["environmental"]


def test_monitors_enabled(monitors, node_red_config):
    configured = (node_red_config.get("sensors") or {}).get("airquality_monitors") or {}
    disabled = [monitor["name"] for monitor in monitors if not (configured.get(monitor["name"]) or {}).get("enabled")]
    assert not disabled, f"not enabled under sensors.airquality_monitors in config.yml: {disabled}"


def test_readings_recent(host, monitors, expect, codedir):
    require_pii_free(expect)
    newest = db_query(host, codedir, "SELECT MAX(entryDateTime) FROM airquality")[0][0]
    assert newest is not None, "the airquality table is empty"
    age = pi_now(host) - newest
    assert age < MAX_READING_AGE_SECONDS, f"newest air-quality reading is {age / 60:.0f} minutes old"
