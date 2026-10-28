"""The reverse proxy and the apps behind it answer, on the Pi and from this machine."""

import re
import shlex
import socket
import urllib.error
import urllib.request

import pytest
from devpi_checks import Redacted

# Prefix locations from `nginx -T`; exact (=), regex (~), and named (@) locations are skipped,
# since those are error pages and internal routes rather than apps.
LOCATION = re.compile(r"^\s*location\s+(?:\^~\s*)?(/\S*)\s*\{", re.MULTILINE)
DIRECT_PORTS = [(1880, "/"), (5000, "/api/version"), (1984, "/api/streams")]


def http_status(host, url, host_header=None):
    header = f"-H {shlex.quote('Host: ' + host_header)} " if host_header else ""
    # host.run, not check_output: when curl can't connect it exits non-zero and still prints 000.
    return host.run(f"curl -s -o /dev/null -w '%{{http_code}}' --max-time 10 {header}{url}").stdout.strip()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None  # report the 3xx itself


def test_nginx_config_valid(host):
    with host.sudo():
        result = host.run("podman exec revproxy nginx -t")
    assert result.rc == 0, result.stderr.strip()


def test_proxied_locations_respond(host, hostvars):
    """Every location the running proxy serves answers without a 404, a 5xx, or a timeout.

    Requests carry the Pi's address as Host, as a browser's would. With Host: localhost, the
    nginx image's stock default.conf (server_name localhost) would answer instead.
    """
    with host.sudo():
        config = host.check_output("podman exec revproxy nginx -T 2>/dev/null")
    locations = sorted(set(LOCATION.findall(config)))
    assert "/" in locations, f"no 'location /' in the running config; found {locations}"
    address = hostvars.get("ansible_host", host.backend.hostname)
    statuses = {path: http_status(host, f"http://localhost{path}", address) for path in locations}
    failing = {path: code for path, code in statuses.items() if code in ("000", "404") or code.startswith("5")}
    assert not failing, f"proxied paths failing: {failing} (all: {statuses})"


@pytest.mark.parametrize("port, path", DIRECT_PORTS)
def test_direct_port_responds(host, port, path):
    code = http_status(host, f"http://localhost:{port}{path}")
    assert code == "200", f"http://localhost:{port}{path} returned {code}"


def test_home_page_reachable_from_this_machine(host, hostvars):
    address = hostvars.get("ansible_host", host.backend.hostname)
    try:
        with urllib.request.build_opener(NoRedirect).open(f"http://{address}/", timeout=10) as response:
            status = response.status
    except urllib.error.HTTPError as exc:
        status = exc.code
    except urllib.error.URLError as exc:
        pytest.fail(f"can't reach http://{address}/ from this machine: {exc.reason}", pytrace=False)
    assert status == 200, f"http://{address}/ returned {status}"


# Edge and ports (tm-control M1): from this machine, only nginx answers, and /feeds is view-only.
# Before M1 the pod also published Frigate's go2rtc (1964), port 8080, and Frigate's restream ports (8564, 8565).
CLOSED_TO_NETWORK = [1880, 1964, 1984, 5000, 8080, 8564, 8565, 8971]  # 1883: see the MQTT tests below
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


def status_from_this_machine(address, path, method="GET"):
    """The HTTP status, or why there was none. Never includes the address."""
    request = urllib.request.Request(f"http://{address}{path}", method=method)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code
    except (urllib.error.URLError, OSError) as error:
        return f"no answer ({type(getattr(error, 'reason', error)).__name__})"


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
def test_feeds_is_view_only_from_this_machine(address, path, method, expected):
    status = status_from_this_machine(address, path, method)
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
def test_data_export_errors_from_this_machine(address, query, expected):
    """Node-RED's download endpoint answers through the proxy with real error statuses (#211, #223)."""
    status = status_from_this_machine(address, f"/storefiles{query}")
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
    """/frigate/api/config is open to the network. Frigate fills the go2rtc RTSP password into the camera input,
    and must not show it. The comparison runs on the Pi, so the password never leaves it."""
    secret = "/etc/traffic-monitor/secrets/go2rtc_rtsp_password"
    counts = host.run(
        'cfg=$(curl -sf http://127.0.0.1/frigate/api/config) && printf %s "$cfg" | grep -c ffmpeg; '
        f'printf %s "$cfg" | sudo grep -c -F -f {secret}'
    ).stdout.split()
    assert len(counts) == 2 and counts[0] != "0", "couldn't read Frigate's /api/config through the proxy"
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
