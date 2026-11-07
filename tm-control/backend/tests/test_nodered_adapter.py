"""The Node-RED adapter's client for /tm-internal/: the token header, the URL and body of each call, and how each
HTTP status becomes an error code."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tm_control.adapters import httpjson, nodered
from tm_control.adapters.nodered import NodeRed, NodeRedError

TOKEN = "placeholder-token"
SURVEY = "3f9a1c2e-si"
DEPLOYMENT = "1700000000000-0badf00d-d"
BASE = "http://127.0.0.1:1880/tm-internal"


@pytest.fixture
def wire(monkeypatch):
    """Record every request and answer the canned (status, body) set in wire.answer."""
    calls = []
    state = SimpleNamespace(answer=(200, b"{}"), calls=calls)

    def get(url, headers=None, timeout=None):
        calls.append(("GET", url, dict(headers or {}), None, None))
        return state.answer

    def post(url, body, content_type, headers=None, timeout=None):
        calls.append(("POST", url, dict(headers or {}), body, content_type))
        return state.answer

    monkeypatch.setattr(httpjson, "get", get)
    monkeypatch.setattr(httpjson, "post", post)
    return state


def answer(value):
    return 200, json.dumps(value).encode()


def test_deployments_sends_the_token_and_parses_the_rows(wire):
    rows = [{"id": DEPLOYMENT, "bearing": "ne"}]
    wire.answer = answer({"deployments": rows})
    assert NodeRed(TOKEN).deployments(SURVEY) == rows
    assert wire.calls == [("GET", f"{BASE}/deployments?survey_id={SURVEY}", {"X-TM-Internal-Token": TOKEN}, None, None)]


def test_usage_and_events_and_report_read_their_bodies(wire):
    client = NodeRed(TOKEN)
    wire.answer = answer({"surveys": [{"survey_id": SURVEY}]})
    assert client.usage() == [{"survey_id": SURVEY}]
    wire.answer = answer({"survey_id": SURVEY, "event_count": 3})
    assert client.events(SURVEY) == {"survey_id": SURVEY, "event_count": 3}
    wire.answer = answer({"schema_version": 7})
    assert client.report() == {"schema_version": 7}
    assert [call[1] for call in wire.calls] == [
        f"{BASE}/surveys/usage", f"{BASE}/surveys/{SURVEY}/events", f"{BASE}/status"]


def test_a_body_of_the_wrong_shape_is_unexpected(wire):
    wire.answer = answer(["not", "an", "object"])
    with pytest.raises(NodeRedError) as raised:
        NodeRed(TOKEN).usage()
    assert raised.value.code == "unexpected"
    wire.answer = answer({"deployments": "nope"})
    with pytest.raises(NodeRedError) as raised:
        NodeRed(TOKEN).deployments(SURVEY)
    assert raised.value.code == "unexpected"


def test_a_body_that_is_not_json_is_unexpected(wire):
    wire.answer = (200, b"<html>")
    with pytest.raises(NodeRedError) as raised:
        NodeRed(TOKEN).report()
    assert (raised.value.code, raised.value.status) == ("unexpected", 200)


@pytest.mark.parametrize(
    ("status", "code"),
    [(None, "unreachable"), (401, "refused"), (400, "bad_request"), (500, "database_error"), (418, "unexpected")],
)
def test_each_status_maps_to_an_error_code(wire, status, code):
    wire.answer = (status, b'{"error": "x"}')
    with pytest.raises(NodeRedError) as raised:
        NodeRed(TOKEN).deployments(SURVEY)
    assert raised.value.code == code
    assert raised.value.status == status
    assert str(raised.value) == code  # never the body, which could carry what was sent


def test_set_precision_posts_json(wire):
    wire.answer = (204, b"")
    assert NodeRed(TOKEN).set_precision("2") is None
    method, url, headers, body, content_type = wire.calls[0]
    assert (method, url, content_type) == ("POST", f"{BASE}/deployments/precision", "application/json")
    assert headers == {"X-TM-Internal-Token": TOKEN}
    assert json.loads(body) == {"precision": "2"}


def test_correct_location_posts_json(wire):
    wire.answer = (204, b"")
    assert NodeRed(TOKEN).correct_location(SURVEY, 45.52252, -122.6912) is None
    method, url, headers, body, content_type = wire.calls[0]
    assert (method, url, content_type) == ("POST", f"{BASE}/surveys/{SURVEY}/location", "application/json")
    assert headers == {"X-TM-Internal-Token": TOKEN}
    assert json.loads(body) == {"lat": 45.52252, "lon": -122.6912}


def test_correct_bearing_posts_json(wire):
    wire.answer = (204, b"")
    assert NodeRed(TOKEN).correct_bearing(DEPLOYMENT, "ne") is None
    method, url, _, body, content_type = wire.calls[0]
    assert (method, url, content_type) == ("POST", f"{BASE}/deployments/{DEPLOYMENT}/bearing", "application/json")
    assert json.loads(body) == {"bearing": "ne"}


def test_a_failed_post_raises(wire):
    wire.answer = (400, b'{"error": "bad_request", "detail": "lat"}')
    with pytest.raises(NodeRedError) as raised:
        NodeRed(TOKEN).correct_location(SURVEY, 45.0, -122.0)
    assert raised.value.code == "bad_request"
    assert "45" not in str(raised.value)


def test_after_config_write_does_nothing(wire):
    assert NodeRed(TOKEN).after_config_write() is None
    assert wire.calls == []


def test_status_and_config_path_keep_working(wire):
    wire.answer = answer({"ok": True})
    assert nodered.status(TOKEN) == (200, {"ok": True})
    assert nodered.config_path("/opt/tm") == Path("/opt/tm/node-red-tm/config/config.yml")


def test_config_file_path_in_fake_mode_is_beside_the_state_dir(tmp_path):
    settings = SimpleNamespace(fake=True, state_dir=tmp_path / "fake" / "state")
    manifest = SimpleNamespace(codedir="/opt/traffic-monitor")
    assert nodered.config_file_path(settings, manifest) == tmp_path / "fake" / "node-red-tm" / "config" / "config.yml"


def test_config_file_path_on_a_device_is_under_codedir(tmp_path):
    settings = SimpleNamespace(fake=False, state_dir=tmp_path / "state")
    manifest = SimpleNamespace(codedir="/opt/traffic-monitor")
    assert nodered.config_file_path(settings, manifest) == Path(
        "/opt/traffic-monitor/node-red-tm/config/config.yml")


def test_open_config_is_a_round_trip_file_indented_by_four(tmp_path):
    path = tmp_path / "config.yml"
    path.write_text("sensors:\n    cameras:\n        a: 1\n", encoding="utf-8")
    config = nodered.open_config(path)
    assert config.path == path
    config.data["sensors"]["cameras"]["b"] = 2
    assert config.render() == "sensors:\n    cameras:\n        a: 1\n        b: 2\n"
