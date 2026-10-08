"""Radars: on their serial ports, passed to Node-RED, and configured under the expected names."""

import re

import pytest
from devpi_checks import read_root_file

ENV_LINE = re.compile(r"^(TM_RADAR_SERIAL_PORT_0[0-3])=(.*)$", re.MULTILINE)


@pytest.fixture
def radars(expect):
    if not expect["radars"]:
        pytest.skip("no radars expected")
    return expect["radars"]


def test_expected_radars_present(host, radars):
    missing = [radar["port"] for radar in radars if not host.file(radar["port"]).exists]
    assert not missing, f"missing radar ports: {missing}; check the USB cables"


def test_no_unexpected_serial_devices(host, expect):
    found = set(host.run("ls /dev/ttyACM* 2>/dev/null").stdout.split())
    extra = sorted(found - {radar["port"] for radar in expect["radars"]})
    assert not extra, f"serial devices not in the inventory: {extra}"


def test_node_red_gets_the_radars(host, expect):
    unit = host.file("/etc/containers/systemd/node-red-tm.container").content_string
    passed = set(re.findall(r"^AddDevice=(/dev/ttyACM[0-3])", unit, re.MULTILINE))
    expected = {radar["port"] for radar in expect["radars"]}
    assert passed == expected, (
        f"node-red-tm.container passes {sorted(passed)}, expected {sorted(expected)}; re-run tmsetup.sh -t node-red-tm")


def test_radar_names_match_ports(host, radars, expect, codedir, node_red_config):
    # Reads only the TM_RADAR_SERIAL_PORT_* lines; the env file also holds secrets.
    with host.sudo():
        lines = host.run(f"grep -E '^TM_RADAR_SERIAL_PORT_0[0-3]=' {codedir}/node-red-tm/node-red-tm.env").stdout
    ports = dict(ENV_LINE.findall(lines))
    configured = (node_red_config.get("sensors") or {}).get("radars") or {}
    problems = []
    for radar in radars:
        name = radar["env_name"]
        if ports.get(name) != radar["port"]:
            problems.append(f"{name} is {ports.get(name)!r} in node-red-tm.env, expected {radar['port']}")
        if not (configured.get(name) or {}).get("enabled"):
            problems.append(f"sensors.radars.{name} isn't enabled in config.yml")
    assert not problems, "; ".join(problems)
