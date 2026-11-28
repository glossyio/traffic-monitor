"""The device test of each radar's info in Node-RED's status, with its device calls replaced: it skips while
node-red-tm.service is young, and fails on a missing info once the service has been up longer."""

import importlib.util
import sys
from pathlib import Path

import pytest

DEVPI_TESTS = Path(__file__).resolve().parents[1] / "devpi" / "tests"


@pytest.fixture
def test_web(monkeypatch):
    monkeypatch.syspath_prepend(str(DEVPI_TESTS))
    spec = importlib.util.spec_from_file_location("devpi_test_web_under_test", DEVPI_TESTS / "test_web.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop("devpi_checks", None)


EXPECT = {"pii_free": True, "radars": [{"env_name": "TM_RADAR_SERIAL_PORT_00"}]}


def run(module, monkeypatch, active_seconds):
    reads = []
    monkeypatch.setattr(module, "service_active_seconds", lambda host, unit: (reads.append(unit), active_seconds)[1])
    monkeypatch.setattr(module, "tm_internal_token", lambda host: "placeholder")
    monkeypatch.setattr(module, "tm_internal_answer", lambda host, token: (
        "200", {"radars": {"TM_RADAR_SERIAL_PORT_00": {"info": None}}}))
    module.test_tm_internal_status_has_each_radars_answers(object(), EXPECT)
    return reads


def test_a_missing_info_is_a_skip_in_node_reds_first_minutes(test_web, monkeypatch):
    with pytest.raises(pytest.skip.Exception, match="node-red-tm.service has been active for 30 seconds"):
        run(test_web, monkeypatch, 30.0)


def test_a_missing_info_fails_once_node_red_has_been_up_longer(test_web, monkeypatch):
    with pytest.raises(AssertionError, match="TM_RADAR_SERIAL_PORT_00 has no info"):
        run(test_web, monkeypatch, 3600.0)
