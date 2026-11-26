"""Radars: on their serial ports, passed to Node-RED, and configured under the expected names; the serial nodes
of the others switched off."""

import json
import re
import shlex

import pytest
from devpi_checks import radar_env_names, read_root_file, require_pii_free

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


# Prints only the serial nodes' id, type, port, and whether each is off, so nothing else in the file is read back.
SERIAL_NODES = """\
import json, sys
nodes = json.load(open(sys.argv[1], encoding="utf-8"))
print(json.dumps([{key: node.get(key) for key in ("id", "type", "serialport", "serial", "d")} for node in nodes
                  if node.get("type") in ("serial-port", "serial in", "serial out")]))
"""


def env_ports(host, codedir):
    """Each radar name's port in node-red-tm.env. The file holds secrets, so the Pi sends back only its
    TM_RADAR_SERIAL_PORT_ lines; the caller has checked that the unit is pii_free."""
    with host.sudo():
        lines = host.run(f"grep -E '^TM_RADAR_SERIAL_PORT_0[0-3]=' {codedir}/node-red-tm/node-red-tm.env").stdout
    return {name: port.strip() for name, port in ENV_LINE.findall(lines)}


def test_missing_radars_serial_nodes_are_off(host, expect, codedir):
    """The installer switches off the three serial nodes of each radar name the host has no radar for, and no
    other; the repo's flows.json has none off (tasks/node-red-tm_setup.yml, flows.json.j2). Only on pii_free units,
    since it reads under the code folder."""
    require_pii_free(expect, "the unit's flows.json")
    expected = {radar["env_name"] for radar in expect["radars"]}
    with host.sudo():
        nodes = json.loads(host.check_output(
            "python3 -c " + shlex.quote(SERIAL_NODES) + " " + shlex.quote(f"{codedir}/node-red-tm/data/flows.json")))
    ports = {node["id"]: node["serialport"][2:-1] for node in nodes if node["type"] == "serial-port"}
    assert sorted(ports.values()) == radar_env_names()
    off = {}
    for node in nodes:
        name = ports[node["id"]] if node["type"] == "serial-port" else ports.get(node["serial"])
        off.setdefault(name, []).append(node.get("d") is True)
    wanted = {name: [name not in expected] * 3 for name in radar_env_names()}
    assert off == wanted, (f"serial nodes off (True) by radar name: {off}, expected {wanted}; "
                           "re-run tmsetup.sh -t node-red-tm")


NODE_RED_SERIAL_ERRORS = (
    'out=$(journalctl -u node-red-tm.service --since {since} --no-pager -o cat) || exit 3; '
    'printf "%s\\n" "$out" | grep -c .; printf "%s\\n" "$out" | grep -c -F -- {line}'
)


def test_no_serial_error_for_a_port_that_is_not_there(host, expect, codedir):
    """Since Node-RED last started, it hasn't logged "serial port <path> error" for the port of a radar name the
    host has no radar for: that radar's nodes are off, so nothing tries to open the port. Only on pii_free units,
    since it reads node-red-tm.env's radar lines."""
    require_pii_free(expect, "node-red-tm.env's radar lines")
    expected = {radar["env_name"] for radar in expect["radars"]}
    paths = sorted({port for name, port in env_ports(host, codedir).items() if name not in expected and port})
    if not paths:
        pytest.skip("every radar name has a radar")
    with host.sudo():
        since = host.check_output("systemctl show -p ActiveEnterTimestamp --value node-red-tm.service")
        assert since, "node-red-tm.service has no start time; is it running?"
        found = {}
        for path in paths:
            result = host.run(NODE_RED_SERIAL_ERRORS.format(since=shlex.quote(since),
                                                            line=shlex.quote(f"serial port {path} error")))
            assert result.rc != 3, "journalctl failed"
            counts = result.stdout.split()
            assert len(counts) == 2 and counts[0] != "0", f"couldn't count Node-RED's journal lines: {counts}"
            found[path] = int(counts[1])
    errors = {path: count for path, count in found.items() if count}
    assert not errors, f"serial port errors in Node-RED's journal since it started: {errors}"
