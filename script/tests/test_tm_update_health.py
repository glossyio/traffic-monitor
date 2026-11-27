"""tm-update's health check: four conditions in one round, for up to five minutes, with a fake clock."""

import http.server
import json
import socket
import subprocess
import threading

import pytest
from tm_update_support import COMMIT, OLD_COMMIT, SWITCH_USEC, Device, handover, installed

from tm_update import health
from tm_update.cli import Context
from tm_update.health import UNITS
from tm_update.state import Failed, State

REAL_GET_STATUS = health._get_status


@pytest.fixture
def device(tmp_path, monkeypatch):
    return Device(tmp_path, monkeypatch)


@pytest.fixture
def ctx(device, tmp_path):
    hand = handover(device.paths)
    hand.work_dir.mkdir(parents=True)
    (hand.work_dir / "facts.json").write_text(json.dumps({"tm_control_port": 8090, "images": []}))
    set_commit(device, COMMIT)
    log = open(tmp_path / "health.log", "a", encoding="utf-8")
    yield Context(device.paths, device.tree, hand, device.handover_path, installed(),
                  State.open(hand, installed(), "0.8.0"), log)
    log.close()


def set_commit(device, commit):
    data = json.loads(device.paths.manifest.read_text())
    data["git"]["commit"] = commit
    device.paths.manifest.write_text(json.dumps(data))


def test_the_units_are_the_pod_frigate_node_red_the_revproxy_and_go2rtc():
    assert UNITS == ("traffic-monitor.service", "frigate.service", "node-red-tm.service", "revproxy.service",
                     "go2rtc_server.service")


def test_a_healthy_device_passes_in_the_first_round(device, ctx):
    health.wait(ctx, since_monotonic_usec=SWITCH_USEC)
    assert device.time.slept == []
    assert device.endpoint_urls == [8090]
    asked = [argv[2] for argv in device.systemctl_calls("is-active")]
    assert asked == ["tm-control.service", *UNITS]
    assert device.systemctl_calls("show") == [
        ["systemctl", "show", "--property=ActiveEnterTimestampMonotonic", "--value", "tm-control.service"]]


def test_health_passes_only_when_all_four_hold_in_one_round(device, ctx, monkeypatch):
    # Each round fixes the last round's problem and breaks another, until the fifth, where all four hold
    rounds = [
        lambda: set_commit(device, OLD_COMMIT),
        lambda: (set_commit(device, COMMIT), setattr(device, "tm_control_entered", SWITCH_USEC - 1)),
        lambda: (setattr(device, "tm_control_entered", SWITCH_USEC + 1), setattr(device, "endpoint_status", 503)),
        lambda: (setattr(device, "endpoint_status", 200), device.unit_state.update({"frigate.service": "failed"})),
        lambda: device.unit_state.clear(),
    ]
    rounds[0]()
    real_sleep = device.time.sleep

    def sleep(seconds):
        real_sleep(seconds)
        rounds[len(device.time.slept)]()

    monkeypatch.setattr(health, "_sleep", sleep)
    health.wait(ctx, since_monotonic_usec=SWITCH_USEC)
    assert device.time.slept == [5.0] * 4


@pytest.mark.parametrize(("breaks", "detail"), [
    (lambda device: set_commit(device, OLD_COMMIT), "manifest"),
    (lambda device: setattr(device, "tm_control_entered", SWITCH_USEC), "tm-control"),
    (lambda device: device.unit_state.update({"tm-control.service": "activating"}), "tm-control"),
    (lambda device: setattr(device, "endpoint_status", None), "health endpoint"),
    (lambda device: setattr(device, "endpoint_status", 500), "health endpoint"),
    (lambda device: device.unit_state.update({"go2rtc_server.service": "inactive"}), "go2rtc_server.service"),
    (lambda device: device.unit_state.update({"node-red-tm.service": "failed",
                                              "revproxy.service": "failed"}), "node-red-tm.service"),
])
def test_health_names_what_was_missing_when_time_runs_out(device, ctx, breaks, detail):
    breaks(device)
    with pytest.raises(Failed) as error:
        health.wait(ctx, since_monotonic_usec=SWITCH_USEC)
    assert (error.value.reason, error.value.detail) == ("health_failed", detail)
    waited = sum(device.time.slept)
    assert 300 <= waited <= 305


def test_the_limit_and_the_pause_can_be_given(device, ctx):
    device.endpoint_status = None
    with pytest.raises(Failed):
        health.wait(ctx, since_monotonic_usec=0, limit=20.0, every=10.0)
    assert device.time.slept == [10.0, 10.0]


def test_after_a_restart_any_active_control_app_counts(device, ctx):
    device.tm_control_entered = 1
    health.wait(ctx, since_monotonic_usec=0)
    device.unit_state["tm-control.service"] = "failed"
    with pytest.raises(Failed) as error:
        health.wait(ctx, since_monotonic_usec=0)
    assert error.value.detail == "tm-control"


@pytest.mark.parametrize("answer", ["", "n/a", "-1", "12.5"])
def test_a_start_time_that_is_not_a_number_is_not_a_start(device, ctx, answer):
    original = device.run.answer
    device.run.answer = lambda call: (
        subprocess.CompletedProcess(call["argv"], 0, answer + "\n", "")
        if call["argv"][:2] == ["systemctl", "show"] else original(call))
    with pytest.raises(Failed) as error:
        health.wait(ctx, since_monotonic_usec=0)
    assert error.value.detail == "tm-control"


@pytest.mark.parametrize("port", ["8090", True, 8090.0, None, 0, 70000])
def test_the_port_from_facts_json_must_be_a_whole_number(device, ctx, port):
    (ctx.handover.work_dir / "facts.json").write_text(json.dumps({"tm_control_port": port}))
    with pytest.raises(Failed) as error:
        health.wait(ctx, since_monotonic_usec=0)
    assert (error.value.reason, error.value.detail) == ("health_failed", "facts tm_control_port")
    assert device.endpoint_urls == []


def test_no_facts_file_is_a_failed_check(device, ctx):
    (ctx.handover.work_dir / "facts.json").unlink()
    with pytest.raises(Failed) as error:
        health.wait(ctx, since_monotonic_usec=0)
    assert error.value.detail == "facts tm_control_port"


@pytest.mark.parametrize("git", [{"commit": None}, {"commit": 5}, "x", None])
def test_a_manifest_commit_that_is_not_text_is_not_the_new_commit(device, ctx, git):
    data = json.loads(device.paths.manifest.read_text())
    data["git"] = git
    device.paths.manifest.write_text(json.dumps(data))
    with pytest.raises(Failed) as error:
        health.wait(ctx, since_monotonic_usec=0)
    assert error.value.detail == "manifest"


class _Health(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        self.send_response(200 if self.path == "/api/v1/health" else 404)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, *args):
        pass


def test_the_health_endpoint_is_asked_on_the_loopback_without_a_proxy(monkeypatch):
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Health)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        # A proxy that answers nothing: asked through it, the request would fail
        for name in ("http_proxy", "HTTP_PROXY", "all_proxy", "ALL_PROXY"):
            monkeypatch.setenv(name, "http://127.0.0.1:9")
        for name in ("no_proxy", "NO_PROXY"):
            monkeypatch.delenv(name, raising=False)
        assert REAL_GET_STATUS(server.server_address[1]) == 200
    finally:
        server.shutdown()
        server.server_close()


def test_a_closed_port_is_no_answer():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    assert REAL_GET_STATUS(port) is None
