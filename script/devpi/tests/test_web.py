"""The reverse proxy, the login in front of the apps, and the apps behind it, on the Pi and from this machine.

The checks that log in (tm-control M2) skip until the inventory has the unit's admin login as tm_control_login.
They make their own viewer account, tmdev-viewer-<random>, and delete it afterwards.
"""

import re
import secrets
import shlex
import socket
import time
import urllib.parse

import pytest
from devpi_checks import (API, UNCLAIMED, Redacted, is_claimed, request_from_this_machine, retry_after, role_vars,
                          session)

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
# 404 on purpose; test_verify_and_auth_locations_are_hidden checks it
HIDDEN_LOCATIONS = {f"{API}/auth/verify"}
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


def delete_user(address, admin_session, username):
    """Delete the account with this name, if there is one. It's found by name, so it goes even when the request that
    created it failed after the account was made."""
    listing = request_from_this_machine(address, f"{API}/users", cookie=admin_session)
    found = listing.json() if listing.status == 200 else None
    users = found.get("users") if isinstance(found, dict) else None
    assert isinstance(users, list), f"couldn't list the users to delete {username}: HTTP {listing.status}"
    for user in users:
        if user.get("username") == username:
            deleted = request_from_this_machine(address, f"{API}/users/{user['id']}", "DELETE", admin_session)
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


@pytest.mark.parametrize("path", [f"{API}/auth/verify", f"{API}/auth/verify%0A", f"{API}/auth/verif%79",
                                  f"{API}/auth/verify/x", f"{API}/auth/verifyx", "/_auth", "/_auth_admin"])
def test_verify_and_auth_locations_are_hidden(address, path):
    """Only nginx's internal /_auth locations may ask tm-control who's logged in, even when a client names a role."""
    status = request_from_this_machine(address, path, headers={"X-TM-Required-Role": "admin"}).status
    assert status == 404, f"{path} answered {status}"


def test_unavailable_page_is_served_for_errors(address):
    """The rescue page is internal: nginx serves it only for its own errors (see test_disruptive.py), never by name."""
    status = status_from_this_machine(address, "/unavailable.html")
    assert status == 404, f"/unavailable.html answered {status}"


# What an admin gets. Without files, /storefiles is Node-RED's own 400; Cockpit shows its login page or redirects to it.
ADMIN_OPENS = [("/dashboard/", {200}), ("/frigate/", {200}), ("/ui/", {200}), ("/nr/", {200}), ("/feeds/", {200}),
               ("/storefiles", {400}), ("/system/", {200, 303})]


@pytest.mark.parametrize("path, expected", ADMIN_OPENS)
def test_admin_session_opens_every_app(address, admin_session, path, expected):
    status = status_from_this_machine(address, path, cookie=admin_session)
    assert status in expected, f"{path} with the admin session answered {status}"


VIEWER_STATUSES = [("/nr/", 403), ("/feeds/", 403), ("/storefiles?files=x", 403), ("/system/", 403),
                   (f"{API}/users", 403), ("/dashboard/", 200), ("/ui/", 200), ("/frigate/", 200)]


@pytest.mark.parametrize("path, expected", VIEWER_STATUSES)
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


def test_frigate_knows_the_user(address, admin_session, tm_login):
    """The proxy passes who's logged in, and Frigate takes it: its profile is the inventory's admin, as admin."""
    username, _ = tm_login
    answer = request_from_this_machine(address, "/frigate/api/profile", cookie=admin_session)
    profile = answer.json() if answer.status == 200 else None
    assert isinstance(profile, dict), f"/frigate/api/profile answered {answer.status}, not a profile"
    role = profile.get("role")
    # A bool, so a failure can't print either name; tm-control lowercases usernames
    same_user = profile.get("username") == username.lower()
    assert same_user, "Frigate's profile names another user than tm_control_login's"
    assert role == "admin", f"Frigate gives the admin the role {role!r}"


def test_node_red_editor_opens_with_the_proxy_token(address, admin_session, tm_login):
    """For an admin, the proxy adds the editor token, so the editor opens without a login of its own (settings.js)."""
    username, _ = tm_login
    without = status_from_this_machine(address, "/nr/settings")
    assert without == 302, f"/nr/settings without a session answered {without}"
    answer = request_from_this_machine(address, "/nr/settings", cookie=admin_session)
    settings = answer.json() if answer.status == 200 else None
    assert isinstance(settings, dict), f"/nr/settings with the admin session answered {answer.status}, not settings"
    user = settings.get("user")
    has_user = isinstance(user, dict) and bool(user.get("username"))
    assert has_user, "Node-RED's settings name no user, so the editor would ask for its own login"
    same_user = user["username"] == username.lower()
    assert same_user, "Node-RED's editor names another user than tm_control_login's"


def test_tm_control_listens_on_loopback_only(host):
    """tm-control listens on 127.0.0.1 only, and the listener is tm-control.service's own process."""
    with host.sudo():
        lines = [line for line in host.check_output(f"ss -Htlnp 'sport = :{TM_CONTROL_PORT}'").splitlines()
                 if line.strip()]
    listening = sorted({line.split()[3] for line in lines})
    assert listening == [f"127.0.0.1:{TM_CONTROL_PORT}"], f"listening on port {TM_CONTROL_PORT}: {listening}"
    pids = sorted(set(re.findall(r"pid=(\d+)", "\n".join(lines))))
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


def test_frigate_config_hides_the_proxy_secret(host, address, expect, admin_session):
    """Frigate's config, which an admin reads through the proxy, doesn't show the secret that proves a request came
    through the proxy (FRIGATE_PROXY_AUTH_SECRET in frigate.env). Compared on the Pi, so the value never leaves it."""
    if not expect["pii_free"]:
        pytest.skip("compares a device secret with Frigate's config; set tm_expect.pii_free: true (bench units only)")
    result = host.run(FRIGATE_CONFIG_COUNTS.format(host_header=shlex.quote(f"Host: {address}"),
                                                   cookie_header=shlex.quote(f"Cookie: {admin_session}"),
                                                   secret=f"{SECRETS_DIR}/frigate_proxy_secret"))
    # Plain values: an assertion on result.rc would print the whole result, command and cookie included
    rc, counts = result.rc, result.stdout.split()
    assert rc != 3, "couldn't read /frigate/api/config through the proxy with the admin session"
    assert rc != 4, "the frigate_proxy_secret file is missing or empty"
    assert len(counts) == 2 and counts[0] != "0", f"/frigate/api/config isn't Frigate's config: {counts}"
    assert counts[1] == "0", "Frigate's /api/config shows the proxy secret"


# The three secrets M2 added. Prints each one's name and how many of the SSH user's install logs hold its value, so
# the values never leave the Pi. tmsetup.sh writes ~/tmsetup-*.log for the user who ran it, so on-Pi deploys leave
# it here and remote ones (-H) on the dev machine. `test -s` first: an empty pattern file would match nothing.
M2_SECRETS = ["tm_control_session_key", "frigate_proxy_secret", "node_red_token_key"]
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
    """tmsetup.sh copies all of its output into its log; none of M2's secrets may be in it. The setup code may be:
    the installer prints it on purpose."""
    if not expect["pii_free"]:
        pytest.skip("compares device secrets with the install logs; set tm_expect.pii_free: true (bench units only)")
    result = host.run(INSTALL_LOG_COUNTS.format(names=" ".join(M2_SECRETS), secrets_dir=SECRETS_DIR))
    rc, output = result.rc, result.stdout
    if rc == 3:
        pytest.skip("no ~/tmsetup-*.log for the SSH user on the Pi; a remote deploy (-H) keeps the log on the "
                    "dev machine, so deploy with --on-pi to check it")
    counts = dict(line.split(" ", 1) for line in output.splitlines() if " " in line)
    assert sorted(counts) == sorted(M2_SECRETS), f"couldn't check every secret: {counts}"
    leaked = {name: count for name, count in counts.items() if count != "0"}
    assert not leaked, f"install logs holding a secret (number of logs, or missing): {leaked}"


# Last in the module: it leaves this machine's address backing off for a few seconds.
def test_login_backs_off(address):
    """After five failed logins, the next one must wait (tm_control/core/auth.py Backoff) and is told how long.

    The user is made up, but the backoff also counts this machine's address. The test waits out the Retry-After,
    and the next successful login from this machine clears the count.
    """
    if not is_claimed(address):
        pytest.skip(UNCLAIMED)
    username = f"tmdev-nobody-{secrets.token_hex(4)}"
    answers = [request_from_this_machine(address, f"{API}/auth/login", "POST",
                                         body={"username": username, "password": "tmdev-wrong-password"})
               for _ in range(6)]
    statuses = [answer.status for answer in answers]
    wait = answers[-1].headers.get("Retry-After") or ""
    if statuses[-1] == 429:
        time.sleep(retry_after(answers[-1]))
    assert statuses == [401] * 5 + [429], f"six wrong logins answered {statuses}"
    assert wait.isdigit() and int(wait) > 0, f"the 429 says Retry-After {wait!r}"
