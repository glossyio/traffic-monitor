"""The apps checks (Frigate, Node-RED with its config.yml and schema, go2rtc, the broker login) and their adapters."""

import http.server
import socket
import threading
import time

import pytest

from tm_control.adapters import frigate, go2rtc, httpjson, mqtt, nodered
from tm_control.adapters.command import CommandResult
from tm_control.core.checks import Fix, run_group
from tm_control.modules import MODULES
from tm_control.modules.apps import checks as apps_checks
from tm_control.modules.apps.checks import newest_migration

# The URLs the `apps` fixture answers (conftest.FakeApps)
VERSION = "http://127.0.0.1:5000/api/version"
CONFIG = "http://127.0.0.1:5000/api/config"
STATS = "http://127.0.0.1:5000/api/stats"
NODE_RED_STATUS = "http://127.0.0.1:1880/tm-internal/status"
GO2RTC_STREAMS = "http://127.0.0.1:1984/api/streams"


def apps_group(apps):
    group = run_group(apps_checks.GROUP, apps.context())
    assert group.title == "Apps"
    return {check.id: check for check in group.checks}


def test_apps_module_comes_after_services_with_the_apps_and_config_groups():
    ids = [m.id for m in MODULES]
    assert ids[ids.index("services") + 1] == "apps"
    assert ids.index("apps") < ids.index("system")
    (module,) = [m for m in MODULES if m.id == "apps"]
    assert [g.id for g in module.check_groups] == ["apps", "config"]
    assert module.router.routes == []


def test_all_apps_checks_are_ok_on_a_healthy_device(apps):
    checks = apps_group(apps)
    assert list(checks) == [
        "apps.frigate.reachable",
        "apps.frigate.cameras",
        "apps.nodered.reachable",
        "apps.nodered.config",
        "apps.nodered.schema",
        "apps.go2rtc.streams",
        "apps.broker.login",
    ]
    assert {c.id: c.status for c in checks.values() if c.status != "ok"} == {}
    assert [c.title for c in checks.values()] == [
        "Frigate", "Cameras", "Node-RED", "Node-RED configuration", "Database schema", "Camera streams", "MQTT broker",
    ]
    # Each Frigate and go2rtc read happens once per report, however many checks use it.
    assert all(apps.asked(url) == 1 for url in (VERSION, CONFIG, STATS, NODE_RED_STATUS, GO2RTC_STREAMS))


# Frigate


def test_frigate_reachable_and_version_mismatch(apps):
    check = apps_group(apps)["apps.frigate.reachable"]
    assert check.status == "ok"
    assert "Frigate 0.18.1-cf67f08" in check.detail

    apps.answers[VERSION] = (200, b"0.17.2-0a1b2c3\n")
    check = apps_group(apps)["apps.frigate.reachable"]
    assert check.status == "warn"
    assert "0.17.2-0a1b2c3" in check.detail and "0.18.1" in check.detail


def test_frigate_down_has_a_restart_fix(apps):
    apps.answers[VERSION] = (None, None)
    checks = apps_group(apps)
    check = checks["apps.frigate.reachable"]
    assert check.status == "error"
    assert check.fix == Fix(kind="restart", text="Restart Frigate", unit="frigate.service")
    assert checks["apps.frigate.cameras"].status == "unknown"
    # A Frigate that doesn't answer its version isn't asked for its config or stats: one timeout, not three.
    assert apps.asked(VERSION) == 1 and apps.asked(CONFIG) == 0 and apps.asked(STATS) == 0


def test_frigate_answering_an_error_page_is_not_a_version(apps):
    apps.answers[VERSION] = (502, b"<html><body>Bad Gateway</body></html>")
    assert apps_group(apps)["apps.frigate.reachable"].status == "error"


def test_camera_without_frames_is_an_error(apps):
    apps.edit_json(STATS, lambda stats: stats["cameras"]["picam_h265"].update(camera_fps=0.0))
    check = apps_group(apps)["apps.frigate.cameras"]
    assert check.status == "error"
    assert "picam_h265" in check.detail
    assert check.fix == Fix(kind="restart", text="Restart Frigate", unit="frigate.service")


def test_a_camera_missing_from_the_stats_has_no_frames(apps):
    apps.edit_json(STATS, lambda stats: stats["cameras"].clear())
    check = apps_group(apps)["apps.frigate.cameras"]
    assert check.status == "error" and "picam_h265" in check.detail


def test_a_camera_disabled_in_frigate_isnt_expected_to_have_frames(apps):
    apps.edit_json(CONFIG, lambda config: config["cameras"]["picam_h265"].update(enabled=False))
    apps.edit_json(STATS, lambda stats: stats["cameras"]["picam_h265"].update(camera_fps=0.0))
    check = apps_group(apps)["apps.frigate.cameras"]
    assert check.status == "warn"
    assert check.detail.startswith("Frigate has no enabled camera")


# Node-RED


def test_nodered_up_and_its_token(apps):
    check = apps_group(apps)["apps.nodered.reachable"]
    assert check.status == "ok"
    assert check.detail.startswith("Node-RED up")
    [headers] = [headers for url, headers in apps.requests if url == NODE_RED_STATUS]
    assert headers == {"X-TM-Internal-Token": "fake-node_red_internal_token-not-secret"}


def test_nodered_status_token_mismatch_names_the_fix(apps):
    apps.answers[NODE_RED_STATUS] = (401, b'{"error":"unauthorized"}')
    checks = apps_group(apps)
    check = checks["apps.nodered.reachable"]
    assert check.status == "error"
    assert "internal token doesn't match" in check.detail
    assert "tmsetup.sh -t node-red-tm" in check.detail
    assert check.fix is None  # a restart wouldn't help
    # The 401's body is JSON too; it isn't Node-RED's status.
    assert checks["apps.nodered.config"].status == "unknown"
    assert checks["apps.nodered.schema"].status == "unknown"
    assert "schema version is unknown" in checks["apps.nodered.schema"].detail


def test_nodered_down_has_a_restart_fix(apps):
    apps.answers[NODE_RED_STATUS] = (None, None)
    checks = apps_group(apps)
    check = checks["apps.nodered.reachable"]
    assert check.status == "error"
    assert check.fix == Fix(kind="restart", text="Restart Node-RED", unit="node-red-tm.service")
    assert checks["apps.nodered.config"].status == "unknown"


def test_nodered_without_the_status_endpoint_is_an_error(apps):
    apps.answers[NODE_RED_STATUS] = (404, b"Cannot GET /tm-internal/status")
    check = apps_group(apps)["apps.nodered.reachable"]
    assert check.status == "error"
    assert "tmsetup.sh -t node-red-tm" in check.detail


@pytest.mark.parametrize(
    "seconds, expected",
    [(11, "less than a minute"), (60, "1 minute"), (150, "2 minutes"), (3 * 3600 + 5, "3 hours"),
     (86400 * 2, "2 days")],
)
def test_nodered_uptime_reads_as_a_duration(apps, seconds, expected):
    apps.edit_json(NODE_RED_STATUS, lambda status: status.update(uptime_seconds=seconds))
    assert apps_group(apps)["apps.nodered.reachable"].detail.startswith(f"Node-RED up {expected}")


def test_nodered_config_errors_are_a_warning(apps):
    errors = [
        "bad indentation of a mapping entry (7:4)",
        "Invalid bearing value 'up' for sensor 'cameras.picam_h265'",
        "third message",
        "fourth message",
        "fifth message",
    ]
    apps.edit_json(NODE_RED_STATUS, lambda status: status["config"].update(errors=errors))
    check = apps_group(apps)["apps.nodered.config"]
    assert check.status == "warn"
    assert all(message in check.detail for message in errors[:3])
    assert "fourth message" not in check.detail and "and 2 more" in check.detail


def test_nodered_config_without_errors_is_ok(apps):
    assert apps_group(apps)["apps.nodered.config"].status == "ok"


def test_yaml_error_is_reported_without_the_file_content(apps):
    apps.config_yml.write_text(
        "thingsboard:\n"
        "    enabled: false\n"
        "    access_token: canary-not-a-secret\n"
        "   protocol: http\n"
    )
    check = apps_group(apps)["apps.nodered.config"]
    assert check.status == "error"
    assert check.detail.startswith("config.yml has a YAML error: line 4, column 4.")
    assert "canary" not in check.detail and "protocol" not in check.detail and "thingsboard" not in check.detail


def test_a_missing_config_yml_is_an_error(apps):
    apps.config_yml.unlink()
    check = apps_group(apps)["apps.nodered.config"]
    assert check.status == "error"
    assert "missing" in check.detail


# Database schema


def test_schema_behind_is_an_error_with_the_journal_hint(apps):
    (apps.migrations / "0002_events_index.sql").write_text("-- synthetic\n")
    apps.edit_json(NODE_RED_STATUS, lambda status: status.update(schema_version=0))
    check = apps_group(apps)["apps.nodered.schema"]
    assert check.status == "error"
    assert "0 of 2" in check.detail
    assert "Node-RED can't write new data" in check.detail
    assert "sudo journalctl -u node-red-tm | grep tmdb-migrate" in check.detail
    assert check.fix == Fix(kind="link", href="/device", text="Diagnostics")


def test_schema_current_is_ok(apps):
    check = apps_group(apps)["apps.nodered.schema"]
    assert check.status == "ok"
    assert "schema version 1" in check.detail.lower()


def test_schema_newer_than_the_install_is_a_warning(apps):
    apps.edit_json(NODE_RED_STATUS, lambda status: status.update(schema_version=3))
    check = apps_group(apps)["apps.nodered.schema"]
    assert check.status == "warn"
    assert "newer than this install" in check.detail


def test_schema_unknown_when_nodered_is_down(apps):
    apps.edit_json(NODE_RED_STATUS, lambda status: status.update(schema_version=None))  # the DB couldn't be read
    assert apps_group(apps)["apps.nodered.schema"].status == "unknown"
    apps.answers[NODE_RED_STATUS] = (None, None)
    assert apps_group(apps)["apps.nodered.schema"].status == "unknown"


def test_schema_unknown_without_migration_files(apps):
    (apps.migrations / "0001_baseline.sql").unlink()
    assert apps_group(apps)["apps.nodered.schema"].status == "unknown"


def test_newest_migration_reads_the_highest_number(tmp_path):
    migrations = tmp_path / "node-red-tm" / "schema" / "migrations"
    migrations.mkdir(parents=True)
    assert newest_migration(tmp_path) is None
    for name in ("0001_baseline.sql", "0003_x.sql", "README.md", "0009_draft.sql.bak", "12_short.sql"):
        (migrations / name).write_text("")
    assert newest_migration(tmp_path) == 3
    assert newest_migration(tmp_path / "missing") is None


# go2rtc


def test_go2rtc_streams_with_a_running_producer_are_ok(apps):
    check = apps_group(apps)["apps.go2rtc.streams"]
    assert check.status == "ok"
    assert "picam_h265_detect" in check.detail


def test_go2rtc_stream_without_producer_is_an_error(apps):
    # An idle producer is listed with only its source URL.
    apps.edit_json(GO2RTC_STREAMS, lambda streams: streams["picam_h265_detect"].update(
        producers=[{"url": "exec:rpicam-vid --camera 0 -o -"}], consumers=None,
    ))
    check = apps_group(apps)["apps.go2rtc.streams"]
    assert check.status == "error"
    assert "picam_h265_detect" in check.detail and "picam_h265 " in check.detail
    assert "exec:" not in check.detail and "rtsp://" not in check.detail and "8554" not in check.detail
    assert check.fix == Fix(kind="restart", text="Restart Camera streams (go2rtc)", unit="go2rtc_server.service")


def test_go2rtc_without_the_stream_frigate_reads_is_an_error(apps):
    apps.edit_json(GO2RTC_STREAMS, lambda streams: streams.pop("picam_h265_detect"))
    check = apps_group(apps)["apps.go2rtc.streams"]
    assert check.status == "error" and "picam_h265_detect" in check.detail


def test_go2rtc_stream_names_drop_the_query(apps):
    apps.edit_json(CONFIG, lambda config: config["cameras"]["picam_h265"]["ffmpeg"]["inputs"][0].update(
        path="rtsp://*:*@host.containers.internal:8554/picam_h265_detect?video=h265",
    ))
    assert apps_group(apps)["apps.go2rtc.streams"].status == "ok"


def test_go2rtc_not_answering_is_an_error(apps):
    apps.answers[GO2RTC_STREAMS] = (None, None)
    check = apps_group(apps)["apps.go2rtc.streams"]
    assert check.status == "error"
    assert check.fix.unit == "go2rtc_server.service"


# The MQTT broker's login


def test_broker_check_only_connects_when_1883_is_open(apps, monkeypatch):
    calls = []
    monkeypatch.setattr(mqtt, "anonymous_connect_refused", lambda *args, **kwargs: calls.append(1))
    apps.ss = (
        "LISTEN 0      4096       127.0.0.1:1883      0.0.0.0:*\n"
        "LISTEN 0      4096           [::1]:1883         [::]:*\n"
        "LISTEN 0      4096         0.0.0.0:80        0.0.0.0:*\n"
    )
    check = apps_group(apps)["apps.broker.login"]
    assert check.status == "ok"
    assert "broker on this device only" in check.detail.lower()
    assert calls == []


@pytest.mark.parametrize("listen", ["0.0.0.0:1883", "[::]:1883", "*:1883", "192.0.2.10:1883"])
def test_broker_accepting_anonymous_clients_is_an_error(apps, monkeypatch, listen):
    monkeypatch.setattr(mqtt, "anonymous_connect_refused", lambda *args, **kwargs: False)
    apps.ss = f"LISTEN 0      4096       127.0.0.1:1883      0.0.0.0:*\nLISTEN 0      4096   {listen}   0.0.0.0:*\n"
    check = apps_group(apps)["apps.broker.login"]
    assert check.status == "error"
    assert "accepts clients without a login while port 1883 is open to the network" in check.detail


def test_broker_refusing_anonymous_clients_on_the_network_port_is_ok(apps, monkeypatch):
    monkeypatch.setattr(mqtt, "anonymous_connect_refused", lambda *args, **kwargs: True)
    apps.ss = "LISTEN 0      4096       0.0.0.0:1883      0.0.0.0:*\n"
    check = apps_group(apps)["apps.broker.login"]
    assert check.status == "ok" and "login enforced on the network port" in check.detail.lower()


def test_broker_not_answering_on_the_network_port_is_unknown(apps, monkeypatch):
    monkeypatch.setattr(mqtt, "anonymous_connect_refused", lambda *args, **kwargs: None)
    apps.ss = "LISTEN 0      4096       0.0.0.0:1883      0.0.0.0:*\n"
    assert apps_group(apps)["apps.broker.login"].status == "unknown"


def test_ss_failing_makes_the_broker_check_unknown(apps, monkeypatch):
    monkeypatch.setattr(mqtt, "run", lambda argv, **kwargs: CommandResult(1, "", "ss: error", False))
    assert apps_group(apps)["apps.broker.login"].status == "unknown"


def test_ss_is_run_as_a_short_probe(monkeypatch):
    seen = {}

    def run(argv, **kwargs):
        seen.update(argv=argv, **kwargs)
        return CommandResult(0, "", "Cannot open netlink socket: Address family not supported by protocol\n", False)

    monkeypatch.setattr(mqtt, "run", run)
    assert mqtt.port_1883_open_to_network() is False
    assert seen["argv"] == ["ss", "-ltnH"]
    assert seen["timeout"] <= 4 and seen["max_output"] <= 65536


def test_mqtt_connect_packet_is_well_formed():
    packet = mqtt.connect_packet()
    body = (
        b"\x00\x04MQTT"  # protocol name
        + b"\x04"  # protocol level 4: MQTT 3.1.1
        + b"\x02"  # connect flags: clean session, no user name or password
        + b"\x00\x1e"  # keepalive, 30 seconds
        + b"\x00\x10tm-control-check"  # client id
    )
    assert packet == b"\x10" + bytes([len(body)]) + body


class Broker:
    """A TCP server on a free loopback port that reads one packet and answers `reply` (or closes on None)."""

    def __init__(self, reply):
        self.reply = reply
        self.received = b""
        self.server = socket.create_server(("127.0.0.1", 0))
        self.port = self.server.getsockname()[1]
        self.thread = threading.Thread(target=self.serve, daemon=True)
        self.thread.start()

    def serve(self):
        connection, _ = self.server.accept()
        with connection:
            connection.settimeout(2)
            self.received = connection.recv(1024)
            if self.reply is not None:
                connection.sendall(self.reply)
                time.sleep(0.2)

    def close(self):
        self.server.close()
        self.thread.join(timeout=2)


@pytest.mark.parametrize(
    "reply, expected",
    [(b"\x20\x02\x00\x00", False), (b"\x20\x02\x00\x05", True), (b"\x20\x02\x00\x04", True), (None, None),
     (b"\x20\x02\x00\x03", None), (b"HTTP/1.1", None)],
)
def test_anonymous_connect_reads_the_connack(reply, expected):
    broker = Broker(reply)
    try:
        assert mqtt.anonymous_connect_refused("127.0.0.1", broker.port, timeout=2) is expected
    finally:
        broker.close()
    assert broker.received == mqtt.connect_packet()


def free_port():
    with socket.create_server(("127.0.0.1", 0)) as server:
        return server.getsockname()[1]


def test_anonymous_connect_to_nothing_is_none():
    assert mqtt.anonymous_connect_refused("127.0.0.1", free_port(), timeout=1) is None


# The adapters never raise


class Handler(http.server.BaseHTTPRequestHandler):
    status = 200
    body = b"not json"

    def do_GET(self):
        self.send_response(self.status)
        self.end_headers()
        self.wfile.write(self.body)

    def log_message(self, *args):
        pass


@pytest.fixture
def http_app():
    """A real HTTP server on a free loopback port whose answer the test sets on Handler."""
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


@pytest.fixture
def silent_app():
    """A loopback port that accepts connections and never answers, like a wedged app."""
    server = socket.create_server(("127.0.0.1", 0))
    yield f"http://127.0.0.1:{server.getsockname()[1]}"
    server.close()


def test_frigate_adapter_gives_up_on_an_app_that_never_answers(silent_app, monkeypatch):
    monkeypatch.setattr(httpjson, "TIMEOUT", 0.5)
    monkeypatch.setattr(frigate, "BASE", f"{silent_app}/api")
    started = time.monotonic()
    assert frigate.version() is None
    assert frigate.config() is None
    assert time.monotonic() - started < 3


def test_the_http_timeout_is_three_seconds():
    assert httpjson.TIMEOUT == 3


def test_adapters_never_raise_on_timeout_or_bad_json(http_app, monkeypatch, tmp_path):
    monkeypatch.setattr(frigate, "BASE", f"{http_app}/api")
    monkeypatch.setattr(nodered, "STATUS_URL", f"{http_app}/tm-internal/status")
    monkeypatch.setattr(go2rtc, "STREAMS_URL", f"{http_app}/api/streams")
    monkeypatch.setattr(Handler, "body", b"{not json")
    assert frigate.config() is None and frigate.stats() is None and go2rtc.streams() is None
    assert nodered.status("token") == (200, None)
    assert frigate.version() is None  # not a version string

    monkeypatch.setattr(Handler, "body", b"[1, 2]")  # JSON, but not an object
    assert frigate.config() is None and go2rtc.streams() is None and nodered.status("token") == (200, None)

    monkeypatch.setattr(Handler, "status", 500)
    monkeypatch.setattr(Handler, "body", b'{"message": "error"}')
    assert frigate.config() is None and frigate.version() is None
    assert nodered.status("token") == (500, {"message": "error"})

    monkeypatch.setattr(Handler, "status", 200)
    monkeypatch.setattr(Handler, "body", b"0.18.1-cf67f08\n")
    assert frigate.version() == "0.18.1-cf67f08"

    def broken(*args, **kwargs):
        raise TimeoutError("timed out")

    monkeypatch.setattr(httpjson._OPENER, "open", broken)
    assert httpjson.get(f"{http_app}/x") == (None, None)
    assert httpjson.get_json(f"{http_app}/x") == (None, None)
    assert frigate.config() is None and nodered.status("token") == (None, None)


def test_nodered_status_is_none_none_when_nothing_answers(monkeypatch):
    monkeypatch.setattr(nodered, "STATUS_URL", f"http://127.0.0.1:{free_port()}/tm-internal/status")
    assert nodered.status("token") == (None, None)


def test_http_reads_go_to_loopback_only():
    with pytest.raises(ValueError):
        httpjson.get("http://192.0.2.1:5000/api/version")


def test_a_body_over_the_cap_is_no_answer(http_app, monkeypatch):
    monkeypatch.setattr(httpjson, "MAX_BODY", 16)
    monkeypatch.setattr(Handler, "body", b'{"padding": "' + b"x" * 64 + b'"}')
    assert httpjson.get_json(f"{http_app}/x") == (200, None)


def test_config_yml_reader_never_raises(tmp_path):
    path = tmp_path / "node-red-tm" / "config" / "config.yml"
    assert nodered.config(tmp_path) == nodered.ConfigRead(None, "missing")
    path.parent.mkdir(parents=True)
    path.write_text("- a list\n- not a mapping\n")
    assert nodered.config(tmp_path) == nodered.ConfigRead(None, "invalid")
    path.write_text("a: [unclosed\n")
    read = nodered.config(tmp_path)
    assert read.data is None and read.problem == "invalid" and read.line is not None
    path.write_bytes(b"\xff\xfe\x00bad")
    assert nodered.config(tmp_path).data is None
    path.write_text("deployment:\n    lat: 1.5\n")
    assert nodered.config(tmp_path) == nodered.ConfigRead({"deployment": {"lat": 1.5}}, None)
    path.chmod(0o000)
    try:
        read = nodered.config(tmp_path)
        assert read.data is None or read.problem is None  # unreadable, unless the tests run as root
    finally:
        path.chmod(0o600)


def test_ss_missing_or_timing_out_is_none(monkeypatch):
    def missing(argv, **kwargs):
        raise FileNotFoundError("ss")

    monkeypatch.setattr(mqtt, "run", missing)
    assert mqtt.port_1883_open_to_network() is None
    monkeypatch.setattr(mqtt, "run", lambda argv, **kwargs: CommandResult(-9, "", "", True))
    assert mqtt.port_1883_open_to_network() is None
