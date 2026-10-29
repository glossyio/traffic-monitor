"""Helpers for the device tests: inventory expectations and read-only probes of the Pi.

Named devpi_checks, not helpers, so it can't collide with another test directory's
module when several run in one pytest session.
"""

import email.message
import functools
import json
import re
import shlex
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest
import yaml

ROLE_DEFAULTS = Path(__file__).resolve().parents[2] / "ansible" / "roles" / "tmsetup" / "defaults" / "main.yml"
ROLE_VARS = ROLE_DEFAULTS.parents[1] / "vars" / "main.yml"

DEFAULT_CODEDIR = "/opt/traffic-monitor"
DEFAULT_CODEOWNER = "tmadmin"
AI_COPROCESSORS = ("none", "edgetpu_usb", "edgetpu_pci", "hailo8l", "hailo8")
CAMERA_SOURCES = ("csi", "rtsp")
EXPECT_KEYS = {"pii_free", "live_traffic", "ai_coprocessor", "radars", "cameras", "environmental"}
# The /dev/media* device whose model is rpi-hevc-dec, the scan setup used before the udev symlink (#231).
FIND_HEVC = """for device in /dev/media*; do
  udevadm info -a -n "$device" 2>/dev/null | grep -q 'ATTR{model}=="rpi-hevc-dec"' && echo "$device"
done; true"""
# Units with Restart= set, where NRestarts counts crashes since the unit was last started.
RESTARTING_UNITS = ["go2rtc_server.service", "traffic-monitor.service", "frigate.service", "node-red-tm.service",
                    "revproxy.service", "tm-control.service"]
# tm-control's API through nginx, and its session cookie's name (tm_control/core/auth.py COOKIE_NAME)
API = "/api/v1"
SESSION_COOKIE = "tm_session"
UNCLAIMED = ("the unit isn't claimed yet: open http://<pi>/setup, follow setup with the code the installer printed, "
             "then put that admin login in the inventory as tm_control_login")
LOGIN_ATTEMPTS = 4


class Redacted(str):
    """A string, such as the Pi's address or a login, that pytest's output shows only as a placeholder.

    pytest prints a failing test's arguments, and with -l its locals, so a plain value there would show.
    """

    def __new__(cls, value, label):
        self = super().__new__(cls, value)
        self.label = label
        return self

    def __repr__(self):
        return f"<{self.label}>"


@functools.cache
def role_defaults():
    """The tmsetup role's defaults/main.yml, so the tests use the same device paths as the install."""
    return yaml.safe_load(ROLE_DEFAULTS.read_text())


@functools.cache
def role_vars():
    """The tmsetup role's vars/main.yml, for the fixed paths the install uses."""
    return yaml.safe_load(ROLE_VARS.read_text())


def radar_ports():
    return role_defaults()["tmsetup_radar_paths"]


def radar_env_names():
    """node-red-tm.env names the radars TM_RADAR_SERIAL_PORT_00.. in the order of tmsetup_radar_paths."""
    return [f"TM_RADAR_SERIAL_PORT_{index:02d}" for index in range(len(radar_ports()))]


def validate_expect(expect):
    """Check tm_expect for typos and fill in defaults; a bad entry fails every test on that host."""
    if not isinstance(expect, dict):
        pytest.fail("the inventory has no tm_expect for this host (see dev-pis.example.yml)", pytrace=False)
    problems = []
    if unknown := set(expect) - EXPECT_KEYS:
        problems.append(f"unknown keys {sorted(unknown)}")
    if expect.get("ai_coprocessor") not in AI_COPROCESSORS:
        problems.append(f"ai_coprocessor must be one of {', '.join(AI_COPROCESSORS)}")
    for key in ("radars", "cameras", "environmental"):
        entries = expect.get(key) or []
        if not isinstance(entries, list) or not all(isinstance(entry, dict) for entry in entries):
            problems.append(f"{key} must be a list of mappings, like the ones in dev-pis.example.yml")
            expect = {**expect, key: []}
    for radar in expect.get("radars") or []:
        if radar.get("port") not in radar_ports():
            problems.append(f"radar port {radar.get('port')!r} isn't one of {', '.join(radar_ports())}")
        if radar.get("env_name") not in radar_env_names():
            problems.append(f"radar env_name {radar.get('env_name')!r} isn't one of {', '.join(radar_env_names())}")
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


def find_hevc_decoder(host):
    """The /dev/mediaN whose model is rpi-hevc-dec on this boot, found independently of the udev rule."""
    with host.sudo():
        found = host.check_output(FIND_HEVC).split()
    if not found:
        pytest.fail("no /dev/media* device with model rpi-hevc-dec", pytrace=False)
    return found[0]


def frigate_host_devices(host):
    """The host path of every device the running frigate container was given."""
    template = '{{range .HostConfig.Devices}}{{.PathOnHost}}{{"\\n"}}{{end}}'
    with host.sudo():
        return host.check_output(f"podman inspect frigate --format {shlex.quote(template)}").split()


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


# --- tm-control's login, over HTTP from this machine -------------------------------------------------------------
# Logins, cookies, and setup codes stay out of assertion messages: values are Redacted, answers show only their
# status, and comparisons with a login are made into a bool before they're asserted, so pytest can't print them.

def tm_control_login(hostvars):
    """The dev Pi's admin login from the inventory's tm_control_login, as Redacted (username, password).

    Skips when the inventory has none, so the login checks wait until a person has claimed the unit.
    """
    login = hostvars.get("tm_control_login")
    if not login:
        pytest.skip("needs the dev Pi's admin login: claim the unit, then set tm_control_login in the inventory "
                    "(see dev-pis.example.yml)")
    if not isinstance(login, dict) or not login.get("username") or not login.get("password"):
        pytest.fail("tm_control_login in the inventory must be a mapping with username and password", pytrace=False)
    return (Redacted(str(login["username"]), "tm_control_login username"),
            Redacted(str(login["password"]), "tm_control_login password"))


def tm_login_or_none(request):
    """The tm_login fixture's (username, password), or None when the inventory has no tm_control_login."""
    try:
        return request.getfixturevalue("tm_login")
    except pytest.skip.Exception:
        return None


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None  # report the 3xx itself


class Answer:
    """One HTTP answer: status (an int, or a string saying why there was none), headers, and body.

    Its repr shows only the status: the headers can carry a session cookie, and the body a username.
    """

    def __init__(self, status, headers=None, body=b""):
        self.status = status
        self.headers = headers if headers is not None else email.message.Message()
        self.body = body

    def __repr__(self):
        return f"<HTTP {self.status}>"

    def json(self):
        """The body parsed as JSON, or None if it isn't JSON."""
        try:
            return json.loads(self.body)
        except ValueError:
            return None


def request_from_this_machine(address, path, method="GET", cookie=None, body=None, headers=None):
    """Send one request to the Pi's port 80 from this machine and return its Answer. Redirects aren't followed.

    A write (any method but GET and HEAD) is sent as JSON with Origin: http://<address>, as the device's own pages
    send it; tm-control refuses any other write (tm_control/core/csrf.py). Never raises for an HTTP or network
    error, so no traceback shows the cookie or the body.
    """
    # The body goes straight into the request, whose repr doesn't show it: a local holding it as bytes would print
    # under pytest -l, password included.
    request = urllib.request.Request(f"http://{address}{path}", method=method,
                                     data=json.dumps(body).encode() if body is not None else None)
    for name, value in (headers or {}).items():
        request.add_header(name, value)
    if cookie is not None:
        request.add_header("Cookie", cookie)
    if method not in ("GET", "HEAD"):
        request.add_header("Content-Type", "application/json")
        request.add_header("Origin", f"http://{address}")
    try:
        with urllib.request.build_opener(NoRedirect).open(request, timeout=30) as response:
            return Answer(response.status, response.headers, response.read())
    except urllib.error.HTTPError as error:
        return Answer(error.code, error.headers, error.read())
    except (urllib.error.URLError, OSError) as error:
        return Answer(f"no answer ({type(getattr(error, 'reason', error)).__name__})")


def is_claimed(address):
    """Whether the device has an admin, from tm-control's open /setup/status."""
    answer = request_from_this_machine(address, f"{API}/setup/status")
    status = answer.json() if answer.status == 200 else None
    if not isinstance(status, dict) or "claimed" not in status:
        pytest.fail(f"GET {API}/setup/status answered HTTP {answer.status}, not tm-control's status", pytrace=False)
    return bool(status["claimed"])


def session_cookie(answer):
    """The Cookie header value for the session cookie an answer sets (Redacted), or None."""
    for header in answer.headers.get_all("Set-Cookie") or []:
        pair = header.split(";", 1)[0].strip()
        if pair.startswith(SESSION_COOKIE + "="):
            return Redacted(pair, "session cookie")
    return None


def retry_after(answer):
    try:
        return min(max(int(answer.headers.get("Retry-After", "5")), 1), 60)
    except ValueError:
        return 5


def session(address, username, password):
    """Log in over HTTP from this machine, as the login page does, and return the Cookie header value (Redacted).

    Skips while the unit is unclaimed. Waits out the login backoff (429 with Retry-After) a few times, since
    test_login_backs_off leaves this machine's address backing off for a few seconds.
    """
    for _ in range(LOGIN_ATTEMPTS):
        answer = request_from_this_machine(address, f"{API}/auth/login", "POST",
                                           body={"username": username, "password": password})
        if answer.status != 429:
            break
        time.sleep(retry_after(answer))
    if answer.status == 409:
        pytest.skip(UNCLAIMED)
    cookie = session_cookie(answer) if answer.status == 200 else None
    if cookie is None:
        pytest.fail(f"logging in as {username!r} from this machine answered HTTP {answer.status}"
                    + (" without a session cookie" if answer.status == 200 else ""), pytrace=False)
    return cookie


def status_checks(address, cookie):
    """tm-control's status report (GET /status, cached for 5 seconds) as {check id: (status, detail)}.

    Details name cameras, zones, radars, and device paths, never a secret, so a failure may show them.
    """
    answer = request_from_this_machine(address, f"{API}/status", cookie=cookie)
    report = answer.json() if answer.status == 200 else None
    groups = report.get("groups") if isinstance(report, dict) else None
    if not isinstance(groups, list):
        pytest.fail(f"GET {API}/status answered HTTP {answer.status}, not a status report", pytrace=False)
    return {check["id"]: (check["status"], check["detail"]) for group in groups for check in group.get("checks", [])}


def tm_internal_token(host):
    """Node-RED's internal token, which tm-control sends with each read of 127.0.0.1:1880/tm-internal/status, read as
    root and Redacted. Never print it; only tests on pii_free units read it."""
    path = f"{role_vars()['tmsetup_secrets_dir']}/node_red_internal_token"
    with host.sudo():
        result = host.run(f"cat {path}")
    token = Redacted(result.stdout.strip() if result.rc == 0 else "", "node_red_internal_token")
    del result
    if not token:
        pytest.fail(f"{path} is missing or empty on the Pi; re-run tmsetup.sh", pytrace=False)
    return token
