import json
import sqlite3
from datetime import datetime, timedelta

import pytest

from tm_control.adapters import systemd
from tm_control.adapters.command import CommandResult
from tm_control.core.checks import Fix
from tm_control.core.settings import FAKE_STATUS
from tm_control.modules import MODULES
from tm_control.modules.services.units import UNITS, restart_fix, units_for

ORIGIN = {"Origin": "http://tm-test.local"}
ADMIN = ("admin", "correct horse 1")
VIEWER = ("viewer", "viewer pass 1")
INSTALLED = [
    "traffic-monitor.service",
    "frigate.service",
    "node-red-tm.service",
    "go2rtc_server.service",
    "revproxy.service",
    "tm-control.service",
]
STDERR = "Failed to restart: synthetic-stderr-detail"
STARTED = datetime(2026, 10, 27, 9, 12, 30).astimezone()  # a fixed instant in the device's (the test's) zone


class FakeSystemctl:
    """Stands in for command.run: records each argv and answers `systemctl show` from a dict of unit properties."""

    def __init__(self, units=None, restart_rc=0, timed_out=()):
        self.calls = []
        self.units = units or {}
        self.restart_rc = restart_rc
        self.timed_out = set(timed_out)

    def __call__(self, argv, **kwargs):
        self.calls.append(list(argv))
        if argv[:2] == ["systemctl", "show"]:
            name = argv[-1]
            if name in self.timed_out:
                return CommandResult(-9, "", "", True)
            values = {
                "LoadState": "loaded",
                "ActiveState": "active",
                "SubState": "running",
                "NRestarts": "0",
                "ActiveEnterTimestamp": f"@{int(STARTED.timestamp())}",
                "InvocationID": "0123456789abcdef0123456789abcdef",
            } | self.units.get(name, {})
            return CommandResult(0, "".join(f"{key}={value}\n" for key, value in values.items()), "", False)
        if argv[:2] == ["systemctl", "restart"]:
            return CommandResult(self.restart_rc, "", STDERR if self.restart_rc else "", False)
        raise AssertionError(f"unexpected command {argv}")

    def restarts(self):
        return [call for call in self.calls if call[:2] == ["systemctl", "restart"]]


@pytest.fixture
def systemctl(monkeypatch):
    fake = FakeSystemctl()
    monkeypatch.setattr("tm_control.adapters.systemd.run", fake)
    return fake


def audit_rows(client):
    con = sqlite3.connect(client.app.state.settings.state_dir / "state.sqlite")
    try:
        return [tuple(row) for row in con.execute("SELECT action, detail FROM audit ORDER BY id")]
    finally:
        con.close()


def restart(client, unit):
    return client.post(f"/api/v1/services/{unit}/restart", json={}, headers=ORIGIN)


def service_group(client):
    r = client.post("/api/v1/status/rescan", json={}, headers=ORIGIN)
    assert r.status_code == 200, r.text
    (group,) = [g for g in r.json()["groups"] if g["id"] == "services"]
    return {check["id"]: check for check in group["checks"]}


def test_services_module_comes_right_after_status():
    ids = [m.id for m in MODULES]
    assert ids[ids.index("status") + 1] == "services"


def test_units_and_the_manifest_option(device_client):
    assert [u.unit for u in UNITS] == [
        "traffic-monitor.service",
        "frigate.service",
        "node-red-tm.service",
        "plate-recognizer.service",
        "go2rtc_server.service",
        "revproxy.service",
        "tm-control.service",
    ]
    manifest = device_client.app.state.manifest
    assert [u.unit for u in units_for(manifest)] == INSTALLED
    with_option = manifest.model_copy(update={"options": {"plate_recognizer": True}})
    assert "plate-recognizer.service" in [u.unit for u in units_for(with_option)]
    assert [u.unit for u in UNITS if not u.restartable] == ["tm-control.service"]


def test_restart_fix_names_the_unit():
    assert restart_fix("frigate.service") == Fix(kind="restart", text="Restart Frigate", unit="frigate.service")
    assert restart_fix("traffic-monitor.service").text == "Restart Traffic Monitor pod"
    assert restart_fix("tm-control.service") is None
    assert restart_fix("sshd.service") is None


def test_fake_report_restart_fixes_match_the_device():
    groups = json.loads(FAKE_STATUS.read_text())["groups"]
    fixes = [c["fix"] for g in groups for c in g["checks"] if c.get("fix") and c["fix"]["kind"] == "restart"]
    assert fixes
    for fix in fixes:
        assert Fix.model_validate(fix) == restart_fix(fix["unit"])


def test_services_list_for_a_viewer(device_client, login, systemctl):
    login(device_client, *VIEWER)
    r = device_client.get("/api/v1/services")
    assert r.status_code == 200, r.text
    services = {s["unit"]: s for s in r.json()}
    assert list(services) == INSTALLED
    assert services["tm-control.service"]["restartable"] is False
    assert services["frigate.service"] == {
        "unit": "frigate.service",
        "title": "Frigate",
        "active_state": "active",
        "sub_state": "running",
        "since": STARTED.replace(microsecond=0).isoformat(),
        "restarts": 0,
        "restartable": True,
    }
    assert ["systemctl", "show", "--timestamp=unix"] == systemctl.calls[0][:3]
    assert sorted(call[-1] for call in systemctl.calls) == sorted(INSTALLED)
    assert systemctl.restarts() == []


def test_services_since_only_while_running(device_client, login, systemctl):
    systemctl.units = {
        "frigate.service": {"ActiveState": "failed", "SubState": "failed", "NRestarts": "2"},
        "revproxy.service": {"ActiveEnterTimestamp": ""},
    }
    login(device_client, *VIEWER)
    services = {s["unit"]: s for s in device_client.get("/api/v1/services").json()}
    assert services["frigate.service"]["since"] is None
    assert services["frigate.service"]["restarts"] == 2
    assert services["revproxy.service"]["since"] is None
    assert datetime.fromisoformat(services["node-red-tm.service"]["since"]).utcoffset() is not None


def test_services_list_when_a_unit_cannot_be_read(device_client, login, systemctl):
    systemctl.timed_out = {"frigate.service"}
    login(device_client, *VIEWER)
    r = device_client.get("/api/v1/services")
    assert r.status_code == 200, r.text
    services = {s["unit"]: s for s in r.json()}
    assert services["frigate.service"]["active_state"] == "unknown"
    assert services["node-red-tm.service"]["active_state"] == "active"


def test_restart_queues_a_no_block_restart(device_client, login, systemctl):
    login(device_client, *ADMIN)
    r = restart(device_client, "frigate.service")
    assert r.status_code == 202, r.text
    assert r.json() == {"unit": "frigate.service"}
    assert systemctl.restarts() == [["systemctl", "restart", "--no-block", "frigate.service"]]
    assert ("services.restart", "frigate.service") in audit_rows(device_client)


@pytest.mark.parametrize(
    "unit", ["sshd.service", "tm-control.service", "..%2Ffrigate.service", "plate-recognizer.service", "frigate"]
)
def test_restart_refuses_a_unit_off_the_list(device_client, login, systemctl, unit):
    login(device_client, *ADMIN)
    r = restart(device_client, unit)
    assert r.status_code == 404, r.text
    assert r.json()["error"]["code"] == "not_found"
    assert systemctl.restarts() == []
    assert not [row for row in audit_rows(device_client) if row[0] == "services.restart"]


def test_restart_refuses_a_dot_dot_path(device_client, login, systemctl):
    login(device_client, *ADMIN)
    r = device_client.post("/api/v1/services/../frigate.service/restart", json={}, headers=ORIGIN)
    assert r.status_code == 404
    assert systemctl.restarts() == []


def test_viewer_cannot_restart(device_client, login, systemctl):
    login(device_client, *VIEWER)
    r = restart(device_client, "frigate.service")
    assert r.status_code == 403 and r.json()["error"]["code"] == "forbidden"
    assert systemctl.restarts() == []
    assert not [row for row in audit_rows(device_client) if row[0] == "services.restart"]


def test_restart_needs_a_session(device_client, systemctl):
    assert restart(device_client, "frigate.service").status_code == 401
    assert device_client.get("/api/v1/services").status_code == 401
    assert systemctl.calls == []


def test_restart_failure_is_an_api_error(device_client, login, systemctl, caplog):
    systemctl.restart_rc = 1
    login(device_client, *ADMIN)
    r = restart(device_client, "frigate.service")
    assert r.status_code == 500
    error = r.json()["error"]
    assert error["code"] == "internal"
    assert "frigate.service" in error["message"]
    assert "synthetic-stderr-detail" not in r.text
    assert "synthetic-stderr-detail" not in caplog.text
    assert not [row for row in audit_rows(device_client) if row[0] == "services.restart"]


def test_service_checks_name_the_fix(device_client, login, systemctl):
    systemctl.units = {
        "frigate.service": {"ActiveState": "failed", "SubState": "failed"},
        "node-red-tm.service": {"NRestarts": "3"},
    }
    login(device_client, *VIEWER)
    r = device_client.get("/api/v1/status")
    assert r.status_code == 200, r.text
    (group,) = [g for g in r.json()["groups"] if g["id"] == "services"]
    assert group["title"] == "Services"
    checks = {check["id"]: check for check in group["checks"]}
    assert list(checks) == [f"services.{unit}" for unit in INSTALLED]

    frigate = checks["services.frigate.service"]
    assert frigate["status"] == "error" and frigate["title"] == "Frigate"
    assert frigate["fix"]["kind"] == "restart" and frigate["fix"]["unit"] == "frigate.service"
    assert frigate["fix"]["text"] == "Restart Frigate"

    node_red = checks["services.node-red-tm.service"]
    assert node_red["status"] == "warn" and "3 times" in node_red["detail"]
    assert "since boot" not in node_red["detail"]

    control = checks["services.tm-control.service"]
    assert control["status"] == "ok" and control["fix"] is None
    assert control["title"] == "Control app"


def test_service_check_states(device_client, login, systemctl):
    today = datetime.now().astimezone().replace(hour=9, minute=12, second=0, microsecond=0)
    systemctl.units = {
        "traffic-monitor.service": {"ActiveEnterTimestamp": f"@{int(today.timestamp())}"},
        "frigate.service": {"ActiveState": "inactive", "SubState": "dead", "LoadState": "loaded"},
        "node-red-tm.service": {"ActiveState": "activating", "SubState": "start-pre"},
        "go2rtc_server.service": {"ActiveState": "activating", "SubState": "auto-restart", "NRestarts": "1"},
        "revproxy.service": {"ActiveState": "active", "ActiveEnterTimestamp": ""},
        "tm-control.service": {"ActiveState": "failed", "SubState": "failed"},
    }
    login(device_client, *ADMIN)
    checks = service_group(device_client)

    pod = checks["services.traffic-monitor.service"]
    assert (pod["status"], pod["detail"], pod["fix"]) == ("ok", "Running since 09:12.", None)
    stopped = checks["services.frigate.service"]
    assert stopped["status"] == "error" and stopped["detail"] == "Stopped."
    assert stopped["fix"] == {"kind": "restart", "text": "Restart Frigate", "unit": "frigate.service", "href": None}
    starting = checks["services.node-red-tm.service"]
    assert starting["status"] == "warn" and starting["detail"] == "Starting." and starting["fix"] is None
    assert checks["services.go2rtc_server.service"]["status"] == "warn"
    assert checks["services.revproxy.service"]["detail"] == "Running."
    control = checks["services.tm-control.service"]
    assert control["status"] == "error" and control["fix"] is None  # not restartable from here


def test_service_check_shows_the_date_when_not_today(device_client, login, systemctl):
    login(device_client, *ADMIN)
    checks = service_group(device_client)
    detail = checks["services.frigate.service"]["detail"]
    if STARTED.date() == datetime.now().astimezone().date():
        assert detail == "Running since 09:12."
    else:
        assert detail == f"Running since {STARTED:%Y-%m-%d} 09:12."


def test_service_check_for_a_unit_not_installed_or_unreadable(device_client, login, systemctl):
    systemctl.units = {"frigate.service": {"LoadState": "not-found", "ActiveState": "inactive", "SubState": "dead"}}
    systemctl.timed_out = {"node-red-tm.service"}
    login(device_client, *ADMIN)
    checks = service_group(device_client)
    missing = checks["services.frigate.service"]
    assert missing["status"] == "error" and missing["fix"]["kind"] == "hint"
    unreadable = checks["services.node-red-tm.service"]
    assert unreadable["status"] == "unknown" and unreadable["fix"] is None


def test_the_report_reads_each_unit_once(device_client, login, systemctl):
    login(device_client, *ADMIN)
    service_group(device_client)
    shows = [call[-1] for call in systemctl.calls if call[:2] == ["systemctl", "show"]]
    assert sorted(shows) == sorted(INSTALLED)


def test_show_units_bounds_each_call(monkeypatch):
    seen = []

    def fake_run(argv, **kwargs):
        seen.append(kwargs)
        return CommandResult(0, "ActiveState=active\nSubState=running\nOther=x\n", "", False)

    monkeypatch.setattr("tm_control.adapters.systemd.run", fake_run)
    values = systemd.show_units(["a.service", "b.service"], ["ActiveState", "SubState", "NRestarts"])
    assert values == {
        "a.service": {"ActiveState": "active", "SubState": "running", "NRestarts": ""},
        "b.service": {"ActiveState": "active", "SubState": "running", "NRestarts": ""},
    }
    assert all(0 < kwargs["timeout"] <= 4 and kwargs["max_output"] <= 65536 for kwargs in seen)


def test_fake_mode_lists_fake_states_and_restarts_nothing(claimed_client, login, monkeypatch):
    def no_run(argv, **kwargs):
        raise AssertionError(f"fake mode ran {argv}")

    monkeypatch.setattr("tm_control.adapters.systemd.run", no_run)
    login(claimed_client, *ADMIN)
    r = claimed_client.get("/api/v1/services")
    assert r.status_code == 200, r.text
    services = r.json()
    assert [s["unit"] for s in services] == INSTALLED
    assert {"active", "failed", "activating"} <= {s["active_state"] for s in services}
    running = [s for s in services if s["active_state"] == "active"]
    assert all(datetime.fromisoformat(s["since"]) < datetime.now().astimezone() - timedelta(minutes=1) for s in running)

    r = restart(claimed_client, "frigate.service")
    assert r.status_code == 202 and r.json() == {"unit": "frigate.service"}
    assert ("services.restart", "frigate.service") in audit_rows(claimed_client)
    assert restart(claimed_client, "tm-control.service").status_code == 404


def test_openapi_declares_the_service_models(client):
    document = client.app.openapi()
    listing = document["paths"]["/api/v1/services"]["get"]["responses"]["200"]["content"]["application/json"]
    assert listing["schema"]["type"] == "array"
    assert listing["schema"]["items"] == {"$ref": "#/components/schemas/Service"}
    queued = document["paths"]["/api/v1/services/{unit}/restart"]["post"]["responses"]["202"]
    assert queued["content"]["application/json"]["schema"]["$ref"].startswith("#/components/schemas/")
    service = document["components"]["schemas"]["Service"]
    assert set(service["properties"]) == {
        "unit",
        "title",
        "active_state",
        "sub_state",
        "since",
        "restarts",
        "restartable",
    }
