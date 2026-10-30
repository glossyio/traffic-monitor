"""The reverse proxy, the login in front of the apps, and the apps behind it, on the Pi and from this machine.

The checks that log in (tm-control M2 and M3) skip until the inventory has the unit's admin login as tm_control_login.
They make their own viewer account, tmdev-viewer-<random>, and delete it afterwards.
"""

import json
import re
import secrets
import shlex
import socket
import time
import urllib.parse

import pytest
from devpi_checks import (API, UNCLAIMED, Redacted, is_claimed, request_from_this_machine, retry_after, role_vars,
                          session, status_checks, tm_internal_token, tm_login_or_none)

TM_CONTROL_PORT = role_vars()["tmsetup_tm_control_port"]
SECRETS_DIR = role_vars()["tmsetup_secrets_dir"]

# Prefix locations from `nginx -T`; exact (=), regex (~), and named (@) locations are skipped,
# since those are error pages and internal routes rather than apps.
LOCATION = re.compile(r"^\s*location\s+(?:\^~\s*)?(/\S*)\s*\{", re.MULTILINE)
DIRECT_PORTS = [(1880, "/"), (5000, "/api/version"), (1984, "/api/streams"), (TM_CONTROL_PORT, f"{API}/health")]
# Locations whose own path doesn't show them working, and what to request instead. /api/ itself is tm-control's 404;
# /assets/ serves only the UI's built files, so test_proxied_locations_respond requests one the home page names.
PROBE_INSTEAD = {"/api/": f"{API}/health"}
# Locations that must answer exactly this. The rest pass with anything but a 404, a 5xx, or no answer, which
# includes the app paths' 302 to the login page.
MUST_ANSWER = {"/": "200", "/api/": "200", "/assets/": "200"}
# 404 on purpose; test_verify_and_auth_locations_are_hidden and test_tm_internal_is_hidden_behind_the_proxy check them
HIDDEN_LOCATIONS = {f"{API}/auth/verify", "/nr/tm-internal/"}
ASSET = re.compile(r"/assets/[\w.-]+\.(?:js|css)")


def http_status(host, url, host_header=None):
    header = f"-H {shlex.quote('Host: ' + host_header)} " if host_header else ""
    # host.run, not check_output: when curl can't connect it exits non-zero and still prints 000.
    return host.run(f"curl -s -o /dev/null -w '%{{http_code}}' --max-time 10 {header}{url}").stdout.strip()


def test_nginx_config_valid(host):
    with host.sudo():
        result = host.run("podman exec revproxy nginx -t")
    assert result.rc == 0, result.stderr.strip()


def location_fails(location, code):
    if location in MUST_ANSWER:
        return code != MUST_ANSWER[location]
    return code in ("000", "404") or code.startswith("5")


def test_proxied_locations_respond(host, address):
    """Every location the running proxy serves answers without a 404, a 5xx, or a timeout.

    Requests carry the Pi's address as Host, as a browser's would. With Host: localhost, the
    nginx image's stock default.conf (server_name localhost) would answer instead.
    """
    with host.sudo():
        config = host.check_output("podman exec revproxy nginx -T 2>/dev/null")
    locations = sorted(set(LOCATION.findall(config)) - HIDDEN_LOCATIONS)
    assert "/" in locations, f"no 'location /' in the running config; found {locations}"
    probes = dict(PROBE_INSTEAD)
    if "/assets/" in locations:
        home = host.run(f"curl -s --max-time 10 -H {shlex.quote('Host: ' + address)} http://localhost/").stdout
        asset = ASSET.search(home)
        assert asset, "the home page names no /assets/ file; was tm-control's UI built into the revproxy image?"
        probes["/assets/"] = asset.group(0)
    statuses = {path: http_status(host, f"http://localhost{probes.get(path, path)}", address) for path in locations}
    failing = {path: code for path, code in statuses.items() if location_fails(path, code)}
    assert not failing, f"proxied paths failing: {failing} (all: {statuses}; requested instead: {probes})"


@pytest.mark.parametrize("port, path", DIRECT_PORTS)
def test_direct_port_responds(host, port, path):
    code = http_status(host, f"http://localhost:{port}{path}")
    assert code == "200", f"http://localhost:{port}{path} returned {code}"


def test_home_page_reachable_from_this_machine(address):
    """The home page (tm-control's UI) opens without a session, from the network."""
    status = request_from_this_machine(address, "/").status
    assert status == 200, f"/ from this machine: {status}"


# Edge and ports (tm-control M1): from this machine, only nginx answers, and /feeds is view-only.
# Before M1 the pod also published Frigate's go2rtc (1964), port 8080, and Frigate's restream ports (8564, 8565).
# tm-control (M2) listens on 8090.
CLOSED_TO_NETWORK = [1880, 1964, 1984, 5000, 8080, 8564, 8565, 8971, TM_CONTROL_PORT]  # 1883: see the MQTT tests
CLOSED = ("refused", "timed out")


def port_state(address, port):
    """'open', 'refused', or 'timed out' from this machine, or the error's type. Never includes the address."""
    try:
        socket.create_connection((address, port), timeout=5).close()
    except ConnectionRefusedError:
        return "refused"
    except TimeoutError:
        return "timed out"
    except OSError as error:
        return type(error).__name__
    return "open"


def check_closed_to_this_machine(address, port):
    assert port_state(address, 80) == "open", "port 80 doesn't answer from this machine, so a closed port shows nothing"
    state = port_state(address, port)
    assert state in CLOSED, f"port {port} is {state} from this machine"


@pytest.mark.parametrize("port", CLOSED_TO_NETWORK)
def test_app_port_closed_to_the_network(address, port):
    """The apps listen on 127.0.0.1 only, so from this machine their ports refuse or time out."""
    check_closed_to_this_machine(address, port)


def status_from_this_machine(address, path, method="GET", cookie=None):
    """The HTTP status, or why there was none. Never includes the address.

    Redirects aren't followed: without a session every app path is a 302 to the login page, which answers 200.
    """
    return request_from_this_machine(address, path, method, cookie).status


@pytest.fixture(scope="module")
def admin_session(address, tm_login):
    """The inventory admin's session cookie (Redacted), from one login per module from this machine."""
    username, password = tm_login
    return session(address, username, password)


def user_ids_named(address, admin_session, username):
    """(status of the user list, ids of the accounts with this name, or None if the list couldn't be read).

    Only ids come back, so no caller's local holds the other accounts' names for pytest -l to print.
    """
    listing = request_from_this_machine(address, f"{API}/users", cookie=admin_session)
    found = listing.json() if listing.status == 200 else None
    users = found.get("users") if isinstance(found, dict) else None
    if not isinstance(users, list):
        return listing.status, None
    return listing.status, [user["id"] for user in users if user.get("username") == username]


def delete_user(address, admin_session, username):
    """Delete the account with this name, if there is one. It's found by name, so it goes even when the request that
    created it failed after the account was made."""
    status, ids = user_ids_named(address, admin_session, username)
    assert ids is not None, f"couldn't list the users to delete {username}: HTTP {status}"
    for user_id in ids:
        deleted = request_from_this_machine(address, f"{API}/users/{user_id}", "DELETE", admin_session)
        assert deleted.status == 204, (f"deleting the test account {username} answered HTTP {deleted.status}; "
                                       "delete it on the device's Users page")


@pytest.fixture(scope="module")
def viewer_session(address, admin_session):
    """A viewer account made through the API for these tests, logged in: yields its session cookie (Redacted).

    The account is deleted afterwards, even when a test, the login, or the account's creation fails.
    """
    username = f"tmdev-viewer-{secrets.token_hex(4)}"
    password = Redacted(secrets.token_urlsafe(18), "test viewer's password")
    try:
        created = request_from_this_machine(address, f"{API}/users", "POST", admin_session,
                                            {"username": username, "password": password})
        assert created.status == 201, f"creating the test viewer {username} answered HTTP {created.status}"
        yield session(address, username, password)
    finally:
        delete_user(address, admin_session, username)


@pytest.mark.parametrize(
    "path, method, expected",
    [
        ("/feeds/", "GET", 200),
        ("/feeds/api/streams", "GET", 200),
        ("/feeds/api", "GET", 403),
        ("/feeds/api/config", "GET", 403),
        ("/feeds/api/log", "GET", 403),
        ("/feeds/api/stream.mp4?src=exec:id", "GET", 403),
        ("/feeds/api/stream.mp4?src=exec%3Aid", "GET", 403),
        ("/feeds/api/stream.mp4?%73rc=rtsp://192.0.2.1/x", "GET", 403),
        ("/feeds/api/stream.mp4?SRC=picam_h265_detect&src=rtsp://192.0.2.1/x", "GET", 403),
        ("/feeds/api/ws?dst=picam_h265_detect", "GET", 403),
        ("/feeds/api/streams?src=x", "POST", 403),
    ],
)
def test_feeds_is_view_only_from_this_machine(address, admin_session, path, method, expected):
    """With the admin session: since M2 only admins can open /feeds/, and it stays view-only for them."""
    status = status_from_this_machine(address, path, method, admin_session)
    assert status == expected, f"{method} {path} returned {status}"


@pytest.mark.parametrize(
    "query, expected",
    [
        ("", 400),
        ("?files=tmdev-missing.json", 404),
        ("?files=../tmdb.sqlite", 400),
        ("?files=../temp-other.json", 400),
        ("?files=-v", 400),
        ("?files=a%20b.json", 400),
    ],
)
def test_data_export_errors_from_this_machine(address, admin_session, query, expected):
    """Node-RED's download endpoint answers through the proxy with real error statuses (#211, #223).

    With the admin session: since M2, /storefiles is for admins only."""
    status = status_from_this_machine(address, f"/storefiles{query}", cookie=admin_session)
    assert status == expected, f"/storefiles{query} returned {status}"


def curl_outcome(result):
    """curl's exit code, the HTTP status it printed last, and whether the headers offered a file to save.

    The headers aren't returned: Content-Disposition's filename starts with the Pi's hostname.
    """
    lines = result.stdout.strip().splitlines()
    return result.rc, lines[-1] if lines else "", "content-disposition" in result.stdout.lower()


def test_failed_data_export_ends_the_download(host, expect, codedir, codeowner):
    """When tar fails, Node-RED ends the download instead of leaving it open (#223)."""
    if not expect["pii_free"]:
        pytest.skip("writes a file into the Pi's data folder; set tm_expect.pii_free: true (bench units only)")
    if codeowner == "root":
        pytest.skip("Node-RED runs as root, so it can read the planted file")
    temp = f"{codedir}/node-red-tm/db/temp"
    with host.sudo():
        if host.run(f"test -d {temp}").rc != 0:
            pytest.skip("Node-RED hasn't created db/temp yet")
        # An empty file only root can read: it exists, so validation passes, and tar fails on it.
        host.check_output(f"install -m 000 /dev/null {temp}/tmdev-unreadable.json")
    try:
        # Straight to Node-RED on the Pi, so nginx's read timeout can't end a download that Node-RED left open.
        result = host.run("curl -s -o /dev/null -D - -w '%{http_code}' --max-time 20 "
                          "'http://localhost:1880/storefiles?files=tmdev-unreadable.json'")
    finally:
        with host.sudo():
            host.check_output(f"rm -f {temp}/tmdev-unreadable.json")
    rc, status, offers_file = curl_outcome(result)
    # 500 if tar failed before sending anything; otherwise the connection is cut mid-download (curl exit 18).
    # Before #223's fix the download stayed open until curl gave up (exit 28).
    assert (rc, status) in {(0, "500"), (18, "200")}, f"curl exit {rc}, HTTP {status or 'none'}"
    if status == "500":
        assert not offers_file, "the browser would save the error as a file"


def test_data_export_tars_a_database_copy(host, expect, codedir):
    """The database download tars a VACUUM INTO copy, then removes it (2026-10-25)."""
    if not expect["pii_free"]:
        pytest.skip("downloads the whole database; set tm_expect.pii_free: true (bench units only)")
    # The archive stays on the Pi: only its file list comes back.
    listing = host.run("curl -sf --max-time 900 'http://localhost:1880/storefiles?files=/db/tmdb.sqlite' | tar tzf -")
    rc, members, stderr = listing.rc, listing.stdout.split(), listing.stderr.strip()
    assert (rc, members) == (0, ["tmdb.sqlite"]), stderr
    with host.sudo():
        leftovers = host.run(f"find {codedir}/node-red-tm/db/snapshot -mindepth 1").stdout.split()
    assert leftovers == []


def test_data_export_copy_failure_is_an_http_error(host, expect, codedir, codeowner):
    """If the database copy fails, the download is a 500 with no file to save."""
    if not expect["pii_free"]:
        pytest.skip("writes into the Pi's data folder; set tm_expect.pii_free: true (bench units only)")
    if codeowner == "root":
        pytest.skip("Node-RED runs as root, so it can write to the planted folder")
    snapshot = f"{codedir}/node-red-tm/db/snapshot"
    try:
        with host.sudo():
            # The copies' folder, owned by root and read-only, so Node-RED can't make the copy's own folder in it
            host.check_output(f"rm -rf {snapshot} && install -d -m 0555 -o root -g root {snapshot}")
        result = host.run("curl -s -o /dev/null -D - -w '%{http_code}' --max-time 60 "
                          "'http://localhost:1880/storefiles?files=/db/tmdb.sqlite'")
    finally:
        with host.sudo():
            host.check_output(f"rm -rf {snapshot}")
    rc, status, offers_file = curl_outcome(result)
    assert (rc, status) == (0, "500"), f"curl exit {rc}, HTTP {status or 'none'}"
    assert not offers_file, "the browser would save the error as a file"


def test_camera_stream_needs_credentials(address):
    """go2rtc's RTSP server answers a DESCRIBE without credentials with 401."""
    request = f"DESCRIBE rtsp://{address}:8554/picam_h265_detect RTSP/1.0\r\nCSeq: 1\r\n\r\n"
    with socket.create_connection((address, 8554), timeout=5) as connection:
        connection.sendall(request.encode())
        reply = connection.recv(1024).decode(errors="replace").splitlines()
    status_line = reply[0] if reply else "go2rtc closed the connection without answering"
    assert status_line.startswith("RTSP/1.0 401"), status_line


def test_frigate_api_hides_the_rtsp_password(host):
    """Frigate fills the go2rtc RTSP password into the camera input, and its /api/config must not show it.

    Read on the Pi's port 5000, which needs no login; through the proxy it now needs a session. The comparison
    runs on the Pi, so the password never leaves it."""
    secret = f"{SECRETS_DIR}/go2rtc_rtsp_password"
    counts = host.run(
        'cfg=$(curl -sf --max-time 20 http://localhost:5000/api/config) && printf %s "$cfg" | grep -c ffmpeg; '
        f'printf %s "$cfg" | sudo grep -c -F -f {secret}'
    ).stdout.split()
    assert len(counts) == 2 and counts[0] != "0", "couldn't read Frigate's /api/config on the Pi's port 5000"
    assert counts[1] == "0", "Frigate's /api/config shows the go2rtc RTSP password"


def mqtt_connack(address, username=None, password=None, port=1883):
    """Send an MQTT 3.1.1 CONNECT and return the CONNACK return code: 0 accepted, 5 not authorized."""
    def field(text):
        data = text.encode()
        return len(data).to_bytes(2, "big") + data

    flags = 0x02 | (0x80 if username is not None else 0) | (0x40 if password is not None else 0)
    body = field("MQTT") + bytes([4, flags]) + (30).to_bytes(2, "big") + field("tmdev-check")
    body += (field(username) if username is not None else b"") + (field(password) if password is not None else b"")
    length, encoded = len(body), b""
    while True:
        length, digit = divmod(length, 128)
        encoded += bytes([digit | (0x80 if length else 0)])
        if not length:
            break
    with socket.create_connection((address, port), timeout=5) as connection:
        connection.sendall(b"\x10" + encoded + body)
        return connection.recv(4)[3]


def connack_code(address, username=None, password=None, port=1883):
    """mqtt_connack's return code, or -1 if the connection fails. Never raises, so no traceback shows the login."""
    try:
        return mqtt_connack(address, username, password, port)
    except Exception:
        return -1


def broker_login(host, expect, codedir):
    if not expect["pii_free"]:
        pytest.skip("reads node-red-tm.env; set tm_expect.pii_free: true (bench units only)")
    with host.sudo():
        text = host.run(f"grep '^TM_MQTT_BROKER_' {codedir}/node-red-tm/node-red-tm.env").stdout
    values = dict(line.split("=", 1) for line in text.splitlines() if "=" in line)
    return (Redacted(values.get("TM_MQTT_BROKER_USERNAME", ""), "broker username"),
            Redacted(values.get("TM_MQTT_BROKER_PASSWORD", ""), "broker password"))


def test_mqtt_port_follows_the_broker_login(host, address, expect, codedir):
    """MQTT is open to the network only with a broker login, and the broker enforces it (Task 10)."""
    username, password = broker_login(host, expect, codedir)
    if not (username and password):
        check_closed_to_this_machine(address, 1883)
        return
    # The assertion sees only the CONNACK codes, and connack_code never raises, so no message or traceback
    # carries the login.
    codes = (connack_code(address), connack_code(address, username, password + "x"),
             connack_code(address, username, password))
    assert codes == (5, 5, 0), f"CONNACK codes without, wrong, right login: {codes}"


# Retries for up to 30 seconds, because a deploy that restarts Node-RED leaves the broker down for a moment
PI_MQTT_CONNACK = """\
import socket, time
for attempt in range(30):
    try:
        s = socket.create_connection(('127.0.0.1', 1883), timeout=5)
        break
    except OSError:
        time.sleep(1)
s.sendall(bytes([0x10, 23]) + b'\\x00\\x04MQTT\\x04\\x02\\x00\\x1e\\x00\\x0btmdev-check')
print(s.recv(4)[3])
"""


def test_mqtt_broker_enforces_its_login_on_the_pi(host, expect, codedir):
    """On the Pi, a client without a login is refused exactly when a broker login is set."""
    username, password = broker_login(host, expect, codedir)
    expected = 5 if username and password else 0
    output = host.run("python3 -c " + shlex.quote(PI_MQTT_CONNACK)).stdout.strip()
    code = int(output) if output.isdigit() else -1
    assert code == expected, f"CONNACK without a login, on the Pi: {code}, expected {expected}"


FRIGATE_JOURNAL_COUNTS = (
    'out=$(journalctl -u frigate.service --since {since} --no-pager -o cat) || exit 3; '
    'printf "%s\\n" "$out" | grep -c .; printf "%s\\n" "$out" | grep -c -i "unable to connect to mqtt"'
)


def test_frigate_logs_in_to_the_mqtt_broker(host):
    """Frigate has reached the broker with its login since it last started (Task 10)."""
    with host.sudo():
        since = host.check_output("systemctl show -p ActiveEnterTimestamp --value frigate.service")
        assert since, "frigate.service has no start time; is it running?"
        result = host.run(FRIGATE_JOURNAL_COUNTS.format(since=shlex.quote(since)))
    assert result.rc != 3, "journalctl failed"
    counts = result.stdout.split()
    assert len(counts) == 2 and counts[0] != "0", f"couldn't count Frigate's journal lines since it started: {counts}"
    assert counts[1] == "0", f"{counts[1]} MQTT connection errors in Frigate's journal since it started"


# --- The login in front of the apps (tm-control M2) ------------------------------------------------------------------
# Every app path asks tm-control through nginx's auth_request (container/revproxy/tm/snippets/auth-*.conf).

APP_PATHS = ["/dashboard/", "/frigate/", "/ui/", "/nr/", "/feeds/", "/storefiles", "/system/"]


@pytest.mark.parametrize("path", APP_PATHS)
def test_app_paths_redirect_to_login_without_a_session(address, path):
    """Without a session, each app path sends the browser to the login page, which returns to the path afterwards."""
    answer = request_from_this_machine(address, path)
    location = answer.headers.get("Location")
    if location == "/setup":
        pytest.skip(UNCLAIMED)
    expected = "/login?next=" + urllib.parse.quote(path, safe="/")
    assert (answer.status, location) == (302, expected), f"{path} without a session"


def test_redirects_are_relative(address):
    """nginx's own redirects keep the host and port the browser used (absolute_redirect off)."""
    answer = request_from_this_machine(address, "/frigate")
    assert (answer.status, answer.headers.get("Location")) == (301, "/frigate/")


HIDDEN_PATHS = {
    "verify": f"{API}/auth/verify",
    "verify-newline": f"{API}/auth/verify%0A",
    "verify-encoded-y": f"{API}/auth/verif%79",
    "verify-subpath": f"{API}/auth/verify/x",
    "verify-suffix": f"{API}/auth/verifyx",
    "auth": "/_auth",
    "auth-admin": "/_auth_admin",
}


@pytest.mark.parametrize("path", HIDDEN_PATHS.values(), ids=HIDDEN_PATHS.keys())
def test_verify_and_auth_locations_are_hidden(address, path):
    """Only nginx's internal /_auth locations may ask tm-control who's logged in, even when a client names a role.

    nginx itself answers: its HTML 404 page, not tm-control's JSON error, so the request never reached tm-control.
    """
    answer = request_from_this_machine(address, path, headers={"X-TM-Required-Role": "admin"})
    from_nginx = (answer.headers.get("Content-Type", "").startswith("text/html") and answer.json() is None
                  and b"<center>nginx" in answer.body)
    assert (answer.status, from_nginx) == (404, True), f"{path}: (status, nginx's own 404 page)"


def test_unavailable_page_is_served_for_errors(address):
    """The rescue page is internal: nginx serves it only for its own errors (see test_disruptive.py), never by name."""
    status = status_from_this_machine(address, "/unavailable.html")
    assert status == 404, f"/unavailable.html answered {status}"


# What an admin gets. Without files, /storefiles is Node-RED's own 400; Cockpit shows its login page or redirects to it.
ADMIN_OPENS = [("/dashboard/", {200}), ("/frigate/", {200}), ("/ui/", {200}), ("/nr/", {200}), ("/feeds/", {200}),
               ("/storefiles", {400}), ("/system/", {200, 303})]


@pytest.mark.parametrize("path, expected", ADMIN_OPENS, ids=[path for path, _ in ADMIN_OPENS])
def test_admin_session_opens_every_app(address, admin_session, path, expected):
    status = status_from_this_machine(address, path, cookie=admin_session)
    assert status in expected, f"{path} with the admin session answered {status}"


VIEWER_STATUSES = [("/nr/", 403), ("/feeds/", 403), ("/storefiles?files=x", 403), ("/system/", 403),
                   (f"{API}/users", 403), ("/dashboard/", 200), ("/ui/", 200), ("/frigate/", 200)]


@pytest.mark.parametrize("path, expected", VIEWER_STATUSES, ids=[path for path, _ in VIEWER_STATUSES])
def test_viewer_gets_403_on_admin_paths(address, viewer_session, path, expected):
    """A viewer opens the dashboards and Frigate, and gets 403 on the admin apps and on tm-control's user list."""
    status = status_from_this_machine(address, path, cookie=viewer_session)
    assert status == expected, f"{path} with a viewer session answered {status}"


# Headers a client could send to pass as an admin: Frigate reads the user's role from X-Forwarded-Groups (and would
# read Remote-*), and treats X-Server-Port 5000 as its internal, unauthenticated port. nginx sets X-Forwarded-User and
# -Groups from tm-control's answer and clears Remote-*; Frigate's own nginx sets X-Server-Port.
CLIENT_ROLE_HEADERS = {
    "forwarded-groups-and-remote-role": {"X-Forwarded-User": "admin", "X-Forwarded-Groups": "admin",
                                         "Remote-Role": "admin"},
    "remote-role-only": {"Remote-Role": "admin"},
    "server-port-5000": {"X-Server-Port": "5000"},
}
FRIGATE_ADMIN_ONLY = "/frigate/api/config/raw"


@pytest.mark.parametrize("headers", CLIENT_ROLE_HEADERS.values(), ids=CLIENT_ROLE_HEADERS.keys())
def test_frigate_ignores_client_supplied_roles(address, viewer_session, headers):
    status = request_from_this_machine(address, FRIGATE_ADMIN_ONLY, cookie=viewer_session, headers=headers).status
    assert status == 403, f"a viewer sending {sorted(headers)} got {status} from {FRIGATE_ADMIN_ONLY}"


def test_frigate_admin_page_opens_for_the_admin(address, admin_session):
    """The control for the test above: the same page opens with the admin session."""
    status = status_from_this_machine(address, FRIGATE_ADMIN_ONLY, cookie=admin_session)
    assert status == 200, f"{FRIGATE_ADMIN_ONLY} with the admin session answered {status}"


def user_in_json(address, path, cookie, username, *keys):
    """What an app's JSON at `path` says about its user, as (status, is JSON, the user found, it's `username`, role).

    Only bools and the role come back, so no local in a test holds a name for a failure or pytest -l to print.
    The user is at body[keys...]["username"]; tm-control lowercases usernames.
    """
    answer = request_from_this_machine(address, path, cookie=cookie)
    found = answer.json() if answer.status == 200 else None
    is_json = isinstance(found, dict)
    for key in keys:
        found = found.get(key) if isinstance(found, dict) else None
    named = found.get("username") if isinstance(found, dict) else None
    role = found.get("role") if isinstance(found, dict) else None
    return answer.status, is_json, bool(named), named == username.lower(), role


def test_frigate_knows_the_user(address, admin_session, tm_login):
    """The proxy passes who's logged in, and Frigate takes it: its profile is the inventory's admin, as admin."""
    status, is_json, has_user, same_user, role = user_in_json(address, "/frigate/api/profile", admin_session,
                                                              tm_login[0])
    assert is_json and has_user, f"/frigate/api/profile answered {status} without a user"
    assert same_user, "Frigate's profile names another user than tm_control_login's"
    assert role == "admin", f"Frigate gives the admin the role {role!r}"


def test_node_red_editor_opens_with_the_proxy_token(address, admin_session, tm_login):
    """For an admin, the proxy adds the editor token, so the editor opens without a login of its own (settings.js)."""
    without = status_from_this_machine(address, "/nr/settings")
    assert without == 302, f"/nr/settings without a session answered {without}"
    status, is_json, has_user, same_user, _ = user_in_json(address, "/nr/settings", admin_session, tm_login[0],
                                                           "user")
    assert is_json, f"/nr/settings with the admin session answered {status}, not settings"
    assert has_user, "Node-RED's settings name no user, so the editor would ask for its own login"
    assert same_user, "Node-RED's editor names another user than tm_control_login's"


LISTEN_SHOWN = {"127.0.0.1", "[::1]", "0.0.0.0", "[::]", "*", "[::ffff:127.0.0.1]"}


def tm_control_listeners(host):
    """The addresses tm-control's port listens on, and the listening pids. The raw ss output can hold the Pi's LAN
    address, so it stays in here, where pytest -l in the test can't print it."""
    with host.sudo():
        lines = [line for line in host.check_output(f"ss -Htlnp 'sport = :{TM_CONTROL_PORT}'").splitlines()
                 if line.strip()]
    # Loopback and wildcard addresses as they are; any other is the Pi's own address, which stays out of the run log
    listening = sorted({local if local.rsplit(":", 1)[0] in LISTEN_SHOWN else "<a LAN address>"
                        for local in (line.split()[3] for line in lines)})
    return listening, sorted(set(re.findall(r"pid=(\d+)", "\n".join(lines))))


def test_tm_control_listens_on_loopback_only(host):
    """tm-control listens on 127.0.0.1 only, and the listener is tm-control.service's own process."""
    listening, pids = tm_control_listeners(host)
    assert listening == [f"127.0.0.1:{TM_CONTROL_PORT}"], f"listening on port {TM_CONTROL_PORT}: {listening}"
    with host.sudo():
        cgroups = {pid: host.check_output(f"cat /proc/{pid}/cgroup") for pid in pids}
    others = {pid: cgroup for pid, cgroup in cgroups.items() if "/tm-control.service" not in cgroup}
    assert pids and not others, f"port {TM_CONTROL_PORT} isn't held by tm-control.service: pids {pids}, {others}"


# The cookie is on the Pi's command line while curl runs, but never under sudo, whose log would keep it.
FRIGATE_CONFIG_COUNTS = """\
cfg=$(curl -sf --max-time 20 -H {host_header} -H {cookie_header} http://localhost/frigate/api/config) || exit 3
printf %s "$cfg" | grep -c '"cameras"'
sudo test -s {secret} || exit 4
printf %s "$cfg" | sudo grep -c -F -f {secret}"""


def frigate_config_counts(host, address, cookie):
    """FRIGATE_CONFIG_COUNTS's exit code and counts. The command holds the cookie, so its CommandResult stays in here,
    where neither an assertion nor pytest -l in the test can print it."""
    result = host.run(FRIGATE_CONFIG_COUNTS.format(host_header=shlex.quote(f"Host: {address}"),
                                                   cookie_header=shlex.quote(f"Cookie: {cookie}"),
                                                   secret=f"{SECRETS_DIR}/frigate_proxy_secret"))
    return result.rc, result.stdout.split()


def test_frigate_config_hides_the_proxy_secret(host, address, expect, admin_session):
    """Frigate's config, which an admin reads through the proxy, doesn't show the secret that proves a request came
    through the proxy (FRIGATE_PROXY_AUTH_SECRET in frigate.env). Compared on the Pi, so the value never leaves it."""
    if not expect["pii_free"]:
        pytest.skip("compares a device secret with Frigate's config; set tm_expect.pii_free: true (bench units only)")
    rc, counts = frigate_config_counts(host, address, admin_session)
    assert rc != 3, "couldn't read /frigate/api/config through the proxy with the admin session"
    assert rc != 4, "the frigate_proxy_secret file is missing or empty"
    assert len(counts) == 2 and counts[0] != "0", f"/frigate/api/config isn't Frigate's config: {counts}"
    assert counts[1] == "0", "Frigate's /api/config shows the proxy secret"


# The secrets the control app added (M2 and M3). Prints each one's name and how many of the SSH user's install logs
# hold its value, so the values never leave the Pi. tmsetup.sh writes ~/tmsetup-*.log for the user who ran it, so on-Pi
# deploys leave it here and remote ones (-H) on the dev machine. `test -s` first: an empty pattern file would match
# nothing.
CONTROL_APP_SECRETS = ["tm_control_session_key", "frigate_proxy_secret", "node_red_token_key",
                       "node_red_internal_token"]
INSTALL_LOG_COUNTS = """\
ls ~/tmsetup-*.log >/dev/null 2>&1 || exit 3
for name in {names}; do
  file={secrets_dir}/$name
  if sudo test -s "$file"; then
    echo "$name $(sudo grep -l -F -f "$file" ~/tmsetup-*.log | wc -l)"
  else
    echo "$name missing"
  fi
done"""


def test_no_secret_in_the_install_log(host, expect):
    """tmsetup.sh copies all of its output into its log; none of the control app's secrets may be in it. The setup
    code may be: the installer prints it on purpose."""
    if not expect["pii_free"]:
        pytest.skip("compares device secrets with the install logs; set tm_expect.pii_free: true (bench units only)")
    result = host.run(INSTALL_LOG_COUNTS.format(names=" ".join(CONTROL_APP_SECRETS), secrets_dir=SECRETS_DIR))
    rc, output = result.rc, result.stdout
    if rc == 3:
        pytest.skip("no ~/tmsetup-*.log for the SSH user on the Pi; a remote deploy (-H) keeps the log on the "
                    "dev machine, so deploy with --on-pi to check it")
    counts = dict(line.split(" ", 1) for line in output.splitlines() if " " in line)
    assert sorted(counts) == sorted(CONTROL_APP_SECRETS), f"couldn't check every secret: {counts}"
    leaked = {name: count for name, count in counts.items() if count != "0"}
    assert not leaked, f"install logs holding a secret (number of logs, or missing): {leaked}"


# --- The status page, the control app's actions, and Node-RED's internal endpoint (tm-control M3) ---------------------

# The inventory's hailo8 is set up as hailo8l, as in test_ai_coprocessor.py
DETECTOR_KIND = {"hailo8": "hailo8l"}
# The status page's runtime assumptions, which only a device shows: Frigate and Node-RED answer tm-control, and the
# sandboxed tm-control sees the pod's published 1883 with ss
APPS_OK = ["apps.frigate.reachable", "apps.nodered.reachable", "apps.nodered.schema", "apps.broker.login"]
CONFIG_CHECKS = ["config.cameras", "config.zones", "config.radars", "config.deployment"]


def test_status_report_agrees_with_the_inventory(address, expect, admin_session):
    """The status report matches the inventory: the expected accelerator, each radar, and the apps are ok, every
    service runs, and no name contract is broken. On a bench unit this also checks what the status page assumes about
    the device: tm-control reads USB ids from sysfs (lsusb can't start in its sandbox), sees port 1883 with ss, and
    go2rtc shows its producing stream with more than its url."""
    checks = status_checks(address, admin_session)
    kind = DETECTOR_KIND.get(expect["ai_coprocessor"], expect["ai_coprocessor"])
    expected = {"hardware.detector.none": {"warn"}} if kind == "none" else {f"hardware.detector.{kind}": {"ok"}}
    expected |= {f"hardware.radar.{radar['port'].rsplit('/', 1)[1]}": {"ok"} for radar in expect["radars"]}
    expected |= {check_id: {"ok"} for check_id in checks if check_id.startswith("services.")}
    expected |= {check_id: {"ok"} for check_id in APPS_OK}
    if expect["cameras"]:
        expected["apps.go2rtc.streams"] = {"ok"}
    expected |= {check_id: {"ok", "warn"} for check_id in CONFIG_CHECKS}
    expected["time.plausible"] = {"ok", "warn"}  # a bench unit may have no time source
    assert any(check_id.startswith("services.") for check_id in checks), "the status report has no services checks"
    problems = []
    for check_id, wanted in sorted(expected.items()):
        status, detail = checks.get(check_id, ("missing", None))
        if status not in wanted:
            problems.append(f"{check_id}: {status}" + (f" ({detail})" if detail else ""))
    problems += [f"{check_id}: {status} ({detail}), which the inventory doesn't expect"
                 for check_id, (status, detail) in sorted(checks.items())
                 if check_id.startswith(("hardware.detector.", "hardware.radar.")) and check_id not in expected]
    assert not problems, "status checks that don't match the inventory: " + "; ".join(problems)


# require_admin's refusal (tm_control/modules/auth/deps.py), which the cross-site check's 403 doesn't say
ADMIN_ONLY = "Only an admin can do this."
VIEWER_ACTIONS = [
    ("POST", f"{API}/services/frigate.service/restart", 403),
    ("POST", f"{API}/status/rescan", 403),
    ("POST", f"{API}/system/reboot", 403),
    ("POST", f"{API}/system/power-off", 403),
    ("POST", f"{API}/time", 403),
    ("GET", f"{API}/system/diagnostics", 403),
    ("GET", f"{API}/status", 200),
    ("GET", f"{API}/services", 200),
    ("GET", f"{API}/system/info", 200),
    ("GET", f"{API}/time", 200),
]
POWER_ACTIONS = {f"{API}/system/reboot", f"{API}/system/power-off"}


def admin_refusal(answer):
    """(HTTP status, the error's message or None) of an answer, to compare with (403, ADMIN_ONLY)."""
    found = answer.json()
    error = found.get("error") if isinstance(found, dict) else None
    return answer.status, error.get("message") if isinstance(error, dict) else None


@pytest.mark.parametrize("method, path, expected", VIEWER_ACTIONS,
                         ids=[f"{method} {path.removeprefix(API)}" for method, path, _ in VIEWER_ACTIONS])
def test_viewer_gets_403_on_every_action(address, viewer_session, method, path, expected):
    """A viewer reads the status, the services, the device's facts, and the time, and every action is refused before
    anything runs. Each write sends an empty change, so POST /time would change nothing even if it were let through.

    A viewer's reboot or power-off is sent only after a harmless action, a re-scan, was refused as admin-only: if
    require_admin ever let viewers through, the Pi would reboot, or power off until someone power-cycles it.
    """
    if path in POWER_ACTIONS:
        guard = admin_refusal(request_from_this_machine(address, f"{API}/status/rescan", "POST", viewer_session, {}))
        if guard != (403, ADMIN_ONLY):
            pytest.fail(f"a viewer's POST {API}/status/rescan answered {guard}, not require_admin's 403, so {path} "
                        "wasn't sent: it would reboot or power off the Pi", pytrace=False)
    answer = request_from_this_machine(address, path, method, viewer_session, {} if method == "POST" else None)
    if expected == 200:
        assert answer.status == 200, f"{method} {path} with a viewer session answered {answer.status}"
        return
    refusal = admin_refusal(answer)
    assert refusal == (403, ADMIN_ONLY), f"{method} {path} with a viewer session (status, message)"


@pytest.mark.parametrize("path", ["/nr/tm-internal/status", "/nr/tm-internal", "/nr/TM-Internal/status"])
def test_tm_internal_is_hidden_behind_the_proxy(address, admin_session, path):
    """Node-RED's internal status endpoint is for tm-control on the Pi only: nginx itself answers 404 for it, even to
    the admin, whose requests to /nr/ carry the editor token."""
    answer = request_from_this_machine(address, path, cookie=admin_session)
    from_nginx = (answer.headers.get("Content-Type", "").startswith("text/html") and answer.json() is None
                  and b"<center>nginx" in answer.body)
    assert (answer.status, from_nginx) == (404, True), f"{path} with the admin session: (status, nginx's own 404 page)"


TM_INTERNAL_STATUS = "http://127.0.0.1:1880/tm-internal/status"
TM_INTERNAL_HEADER = "X-TM-Internal-Token"  # tm_control/adapters/nodered.py


def tm_internal_answer(host, token=None):
    """(HTTP status, JSON body or None) of Node-RED's internal status, asked on the Pi with this token or none.

    The token is on curl's command line, never under sudo, whose log would keep it; the CommandResult holds it, so it
    stays in here, where neither an assertion nor pytest -l in the test can print it.
    """
    header = "" if token is None else "-H " + shlex.quote(f"{TM_INTERNAL_HEADER}: {token}") + " "
    result = host.run(f"curl -s --max-time 10 -w '\\n%{{http_code}}' {header}{TM_INTERNAL_STATUS}")
    body, _, status = result.stdout.rpartition("\n")
    del result
    try:
        return status, json.loads(body)
    except ValueError:
        return status, None


def test_tm_internal_needs_the_token_on_the_pi(host, expect):
    """On the Pi, Node-RED's internal status answers 401 without the token or with a wrong one, and with the token,
    its status with the database's schema version."""
    if not expect["pii_free"]:
        pytest.skip("reads a device secret; set tm_expect.pii_free: true (bench units only)")
    token = tm_internal_token(host)
    refused = (tm_internal_answer(host)[0], tm_internal_answer(host, "tmdev-wrong-token")[0])
    assert refused == ("401", "401"), f"without a token and with a wrong one, {TM_INTERNAL_STATUS} answered {refused}"
    status, body = tm_internal_answer(host, token)
    # Only the version is kept: the body also holds the deployment's location
    version = body.get("schema_version") if isinstance(body, dict) else None
    del body
    assert status == "200", f"with the token, {TM_INTERNAL_STATUS} answered {status}"
    assert isinstance(version, int) and not isinstance(version, bool), (
        f"Node-RED's status gives schema_version as {type(version).__name__}, not an integer")


# The diagnostics through the proxy with the admin session, then: how many lines are the status section's header, and
# for each device secret, and the broker password when node-red-tm.env sets one, how many lines of the text hold its
# value. The values stay on the Pi: each is piped to grep as its pattern, never put on a command line. The cookie is on
# curl's command line, never under sudo, whose log would keep it. `test -s` first: an empty pattern matches every line.
DIAGNOSTICS_COUNTS = """\
diag=$(mktemp) || exit 3
trap 'rm -f "$diag"' EXIT
curl -sf --max-time 90 -H {host_header} -H {cookie_header} -o "$diag" http://localhost{path} || exit 3
grep -c -x -F '== Status ==' "$diag"
for name in {names}; do
  file={secrets_dir}/$name
  if sudo test -s "$file"; then
    echo "$name $(sudo cat "$file" | grep -c -F -f - "$diag")"
  else
    echo "$name missing"
  fi
done
password=$(sudo sed -n 's/^TM_MQTT_BROKER_PASSWORD=//p' {env_file} | head -n 1)
if [ -n "$password" ]; then
  echo "TM_MQTT_BROKER_PASSWORD $(printf '%s\\n' "$password" | grep -c -F -f - "$diag")"
fi"""


def diagnostics_counts(host, address, cookie, codedir):
    """DIAGNOSTICS_COUNTS's exit code and output lines. The command holds the cookie, so its CommandResult stays in
    here, where neither an assertion nor pytest -l in the test can print it."""
    result = host.run(DIAGNOSTICS_COUNTS.format(host_header=shlex.quote(f"Host: {address}"),
                                                cookie_header=shlex.quote(f"Cookie: {cookie}"),
                                                path=f"{API}/system/diagnostics",
                                                names=" ".join(role_vars()["tmsetup_secret_names"]),
                                                secrets_dir=SECRETS_DIR,
                                                env_file=shlex.quote(f"{codedir}/node-red-tm/node-red-tm.env")))
    return result.rc, result.stdout.splitlines()


def test_diagnostics_has_no_secret_value(host, address, expect, codedir, admin_session):
    """The diagnostics text an admin downloads holds none of the device's secrets, nor the broker password, which
    Node-RED's journal can print on a connection error. Compared on the Pi, so no value leaves it."""
    if not expect["pii_free"]:
        pytest.skip("compares device secrets and node-red-tm.env with the diagnostics; set tm_expect.pii_free: true "
                    "(bench units only)")
    rc, lines = diagnostics_counts(host, address, admin_session, codedir)
    assert rc != 3, f"couldn't download {API}/system/diagnostics through the proxy with the admin session"
    assert lines and lines[0] != "0", "the diagnostics text has no == Status == section"
    counts = dict(line.split(" ", 1) for line in lines[1:] if " " in line)
    missing = sorted(set(role_vars()["tmsetup_secret_names"]) - set(counts))
    assert not missing, f"couldn't check {missing}"
    leaked = {name: count for name, count in counts.items() if count != "0"}
    assert not leaked, f"secrets in the diagnostics text (lines holding the value, or missing): {leaked}"


def test_time_state_matches_timedatectl(host, address, admin_session):
    """The Date and time page's time zone and NTP switch are the device's, as timedatectl reports them."""
    answer = request_from_this_machine(address, f"{API}/time", cookie=admin_session)
    state = answer.json() if answer.status == 200 else None
    assert isinstance(state, dict), f"GET {API}/time answered {answer.status}"
    found = (state.get("timezone"), (state.get("ntp") or {}).get("enabled"))
    device = (host.check_output("timedatectl show -p Timezone --value"),
              host.check_output("timedatectl show -p NTP --value") == "yes")
    assert found == device, "(time zone, NTP on) from GET /time and from timedatectl differ"


# Last in the module: it leaves this machine's address backing off for a few seconds.
def test_login_backs_off(request, address):
    """After five failed logins, the next one must wait (tm_control/core/auth.py Backoff) and is told how long.

    The user is made up, but the backoff also counts this machine's address, and remembers it for 15 minutes after
    the last failure. So the test starts from a clean count: with tm_control_login, a successful login clears it;
    without one, it skips if the address is still backing off from an earlier run. At the end it waits out the
    Retry-After, and the next successful login from this machine clears the count.
    """
    if not is_claimed(address):
        pytest.skip(UNCLAIMED)
    login = tm_login_or_none(request)
    if login is not None:
        session(address, *login)  # a fresh login, not the module's cached one, so it resets this address's count
    username = f"tmdev-nobody-{secrets.token_hex(4)}"
    answers = []
    for _ in range(6):
        answers.append(request_from_this_machine(address, f"{API}/auth/login", "POST",
                                                 body={"username": username, "password": "tmdev-wrong-password"}))
        if login is None and len(answers) < 6 and answers[-1].status == 429:
            pytest.skip("this machine's address is still backing off from an earlier run: log in once from this "
                        "machine, or wait 15 minutes (or add tm_control_login, which lets the test clear it)")
    statuses = [answer.status for answer in answers]
    wait = answers[-1].headers.get("Retry-After") or ""
    if statuses[-1] == 429:
        time.sleep(retry_after(answers[-1]))
    assert statuses == [401] * 5 + [429], f"six wrong logins answered {statuses}"
    assert wait.isdigit() and int(wait) > 0, f"the 429 says Retry-After {wait!r}"
