"""Helpers for the device tests: inventory expectations and read-only probes of the Pi.

Named devpi_checks, not helpers, so it can't collide with another test directory's
module when several run in one pytest session.
"""

import json
import re
import shlex

import pytest

DEFAULT_CODEDIR = "/opt/traffic-monitor"
DEFAULT_CODEOWNER = "tmadmin"
AI_COPROCESSORS = ("none", "edgetpu_usb", "edgetpu_pci", "hailo8l", "hailo8")
CAMERA_SOURCES = ("csi", "rtsp")
EXPECT_KEYS = {"pii_free", "live_traffic", "ai_coprocessor", "radars", "cameras", "environmental"}
RADAR_PORT = re.compile(r"^/dev/ttyACM[0-3]$")
RADAR_ENV_NAME = re.compile(r"^TM_RADAR_SERIAL_PORT_0[0-3]$")


def validate_expect(expect):
    """Check tm_expect for typos and fill in defaults; a bad entry fails every test on that host."""
    if not isinstance(expect, dict):
        pytest.fail("the inventory has no tm_expect for this host (see dev-pis.example.yml)", pytrace=False)
    problems = []
    if unknown := set(expect) - EXPECT_KEYS:
        problems.append(f"unknown keys {sorted(unknown)}")
    if expect.get("ai_coprocessor") not in AI_COPROCESSORS:
        problems.append(f"ai_coprocessor must be one of {', '.join(AI_COPROCESSORS)}")
    for radar in expect.get("radars") or []:
        if not RADAR_PORT.match(str(radar.get("port"))):
            problems.append(f"radar port {radar.get('port')!r} isn't /dev/ttyACM0-3")
        if not RADAR_ENV_NAME.match(str(radar.get("env_name"))):
            problems.append(f"radar env_name {radar.get('env_name')!r} isn't TM_RADAR_SERIAL_PORT_00-03")
    for camera in expect.get("cameras") or []:
        if not camera.get("name"):
            problems.append("a camera has no name")
        if camera.get("source") not in CAMERA_SOURCES:
            problems.append(f"camera {camera.get('name')!r}: source must be one of {', '.join(CAMERA_SOURCES)}")
        elif camera["source"] == "csi" and camera.get("csi_port") not in (0, 1):
            problems.append(f"camera {camera.get('name')!r}: csi_port must be 0 or 1")
    for monitor in expect.get("environmental") or []:
        if not monitor.get("name"):
            problems.append("an environmental monitor has no name")
    if problems:
        pytest.fail("tm_expect in the inventory: " + "; ".join(problems), pytrace=False)
    return {
        "pii_free": bool(expect.get("pii_free")),
        "live_traffic": bool(expect.get("live_traffic")),
        "ai_coprocessor": expect["ai_coprocessor"],
        "radars": expect.get("radars") or [],
        "cameras": expect.get("cameras") or [],
        "environmental": expect.get("environmental") or [],
    }


def require_pii_free(expect):
    if not expect["pii_free"]:
        pytest.skip("reads config.yml or tmdb.sqlite; set tm_expect.pii_free: true (bench units only)")


def read_root_file(host, path):
    with host.sudo():
        return host.file(path).content_string


def pi_json(host, url):
    """GET a URL on the Pi itself, so it works whatever ports the pod publishes, and parse the JSON."""
    return json.loads(host.check_output(f"curl -fsS --max-time 10 {shlex.quote(url)}"))


def pi_now(host):
    return float(host.check_output("date +%s"))


def db_query(host, codedir, sql):
    """Run one read-only query on the Pi's tmdb.sqlite and return the rows.

    node-red-node-sqlite sets no busy timeout, so a Node-RED write landing during this
    read can fail; keep queries short.
    """
    script = ("import json, sqlite3, sys; "
              "con = sqlite3.connect('file:' + sys.argv[1] + '?mode=ro', uri=True); "
              "print(json.dumps(con.execute(sys.argv[2]).fetchall()))")
    database = f"{codedir}/node-red-tm/db/tmdb.sqlite"
    with host.sudo():
        output = host.check_output(f"python3 -c {shlex.quote(script)} {shlex.quote(database)} {shlex.quote(sql)}")
    return json.loads(output)
