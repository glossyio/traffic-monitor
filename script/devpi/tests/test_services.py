"""Host services and the Traffic Monitor pod: running, built, and not crash-looping."""

import pytest
from devpi_checks import require_pii_free

CORE_UNITS = [
    "go2rtc_server.service",
    "traffic-monitor.service",
    "frigate.service",
    "node-red-tm.service",
    "revproxy.service",
    "NetworkManager.service",
    "sysstat.service",
]
# Units with Restart= set, where NRestarts counts crashes since the unit was last started.
RESTARTING_UNITS = ["go2rtc_server.service", "traffic-monitor.service", "frigate.service", "node-red-tm.service",
                    "revproxy.service"]


@pytest.mark.parametrize("unit", CORE_UNITS)
def test_unit_active(host, unit):
    state = host.run(f"systemctl is-active {unit}").stdout.strip()
    assert state == "active", f"{unit} is {state}"


def test_image_builds_succeeded(host):
    listing = host.check_output("systemctl list-units --all --plain --no-legend '*-build.service'")
    units = [line.split()[0] for line in listing.splitlines() if line.strip()]
    assert units, "no *-build.service units found"
    results = {unit: host.check_output(f"systemctl show -p Result --value {unit}") for unit in units}
    failed = {unit: result for unit, result in results.items() if result != "success"}
    assert not failed, f"image builds that didn't succeed: {failed}"


@pytest.mark.parametrize("unit", RESTARTING_UNITS)
def test_no_crash_restarts(host, unit):
    restarts = int(host.check_output(f"systemctl show -p NRestarts --value {unit}"))
    assert restarts == 0, f"{unit} restarted itself {restarts} times since it was last started"


def test_plate_recognizer_absent_on_pii_free_unit(host, expect):
    require_pii_free(expect)
    assert not host.file("/etc/containers/systemd/plate-recognizer.container").exists, (
        "plate-recognizer is installed on a unit marked pii_free; its database may hold plate reads")
