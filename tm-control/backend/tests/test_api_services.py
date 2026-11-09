import json
import sqlite3
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from tm_control.adapters import systemd
from tm_control.adapters.command import TRUNCATED, CommandResult
from tm_control.core.checks import Fix
from tm_control.core.settings import FAKE_STATUS
from tm_control.modules import MODULES
from tm_control.modules.services.units import UNITS, restart_fix, units_for

BASE = "http://tm-test.local"
ORIGIN = {"Origin": BASE}
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
        self.journal = []  # PID 1's entries that `journalctl ... --output=json` answers with, as dicts
        self.journal_rc = 0

    def __call__(self, argv, **kwargs):
        self.calls.append(list(argv))
        if argv[0] == "journalctl":
            stdout = "".join(json.dumps(entry) + "\n" for entry in self.journal)
            return CommandResult(self.journal_rc, stdout if self.journal_rc == 0 else "", "", False)
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


def recording(app, events):
    """The app, wrapped so that each response's start is recorded in `events` as it's sent."""

    async def wrapped(scope, receive, send):
        async def send_and_record(message):
            if message["type"] == "http.response.start":
                events.append(("response", message["status"]))
            await send(message)

        await app(scope, receive, send_and_record)

    return wrapped


@pytest.mark.parametrize("unit", ["frigate.service", "revproxy.service"])
def test_restart_queues_a_no_block_restart_after_the_response(device_client, login, systemctl, monkeypatch, unit):
    """Restarting revproxy stops the nginx that carries the answer, so the restart runs only once the 202 is sent."""
    events = []

    def run(argv, **kwargs):
        events.append(("run", list(argv)))
        return systemctl(argv, **kwargs)

    monkeypatch.setattr("tm_control.adapters.systemd.run", run)
    client = TestClient(recording(device_client.app, events), base_url=BASE)
    login(client, *ADMIN)
    events.clear()
    r = restart(client, unit)
    assert r.status_code == 202, r.text
    assert r.json() == {"unit": unit}
    assert events == [("response", 202), ("run", ["systemctl", "restart", "--no-block", unit])]
    assert ("services.restart", unit) in audit_rows(device_client)


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


def test_a_failed_restart_is_logged_without_its_output(device_client, login, systemctl, caplog):
    """The 202 means queued: a restart that then fails can only be logged, and the Status page shows the unit's
    state on its next refresh."""
    systemctl.restart_rc = 1
    login(device_client, *ADMIN)
    r = restart(device_client, "frigate.service")
    assert r.status_code == 202, r.text
    assert systemctl.restarts() == [["systemctl", "restart", "--no-block", "frigate.service"]]
    assert "systemctl restart frigate.service failed with exit status 1" in caplog.text
    assert "synthetic-stderr-detail" not in caplog.text
    assert ("services.restart", "frigate.service") in audit_rows(device_client)


def test_a_restart_that_cant_run_systemctl_is_logged(device_client, login, monkeypatch, caplog):
    def missing(argv, **kwargs):
        raise FileNotFoundError(2, "No such file or directory")

    login(device_client, *ADMIN)
    monkeypatch.setattr("tm_control.adapters.systemd.run", missing)
    r = restart(device_client, "frigate.service")
    assert r.status_code == 202, r.text
    assert "systemctl restart frigate.service failed (FileNotFoundError)" in caplog.text


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


def at(entry, seconds):
    """The journal entry, logged `seconds` after this boot started."""
    return {**entry, "__MONOTONIC_TIMESTAMP": str(int(seconds * 1_000_000))}


EXITED = at({"MESSAGE_ID": systemd.UNIT_PROCESS_EXITED, "EXIT_CODE": "exited", "EXIT_STATUS": "143"}, 100)
CRASHED = at({"MESSAGE_ID": systemd.UNIT_PROCESS_EXITED, "EXIT_CODE": "exited", "EXIT_STATUS": "1"}, 100)
RESTARTED = at({"MESSAGE_ID": systemd.UNIT_RESTART_SCHEDULED, "N_RESTARTS": "1"}, 100.1)


def test_frigate_restarting_itself_is_ok(device_client, login, systemctl):
    """Saving Frigate's config restarts it: its main process exits with 143 and systemd restarts it, which counts in
    NRestarts like a failure."""
    systemctl.units = {"frigate.service": {"NRestarts": "1"}}
    systemctl.journal = [EXITED, RESTARTED]
    login(device_client, *ADMIN)
    frigate = service_group(device_client)["services.frigate.service"]
    assert frigate["status"] == "ok" and frigate["fix"] is None
    assert frigate["detail"].endswith(
        ". It restarted itself 1 time, as Frigate does when its config is saved or it's restarted from its own page.")


@pytest.mark.parametrize("journal, count", [
    ([CRASHED, RESTARTED], 1),  # a crash
    ([CRASHED, RESTARTED, EXITED, RESTARTED], 2),  # a crash, then a save: the crash still shows
    ([RESTARTED], 1),  # no exit before the restart in this boot's journal
    ([EXITED, RESTARTED], 2),  # fewer restarts in the journal than NRestarts
    ([EXITED, at(RESTARTED, 161)], 1),  # a stop that logged 143 a minute before a restart that logged no exit
])
def test_frigate_restarts_after_failures_still_warn(device_client, login, systemctl, journal, count):
    systemctl.units = {"frigate.service": {"NRestarts": str(count)}}
    systemctl.journal = journal
    login(device_client, *ADMIN)
    frigate = service_group(device_client)["services.frigate.service"]
    assert frigate["status"] == "warn" and "after failures" in frigate["detail"]
    assert frigate["fix"]["kind"] == "restart"


def test_frigate_restarts_warn_when_the_journal_cant_be_read(device_client, login, systemctl):
    systemctl.units = {"frigate.service": {"NRestarts": "1"}}
    systemctl.journal = [EXITED, RESTARTED]
    systemctl.journal_rc = 1
    login(device_client, *ADMIN)
    assert service_group(device_client)["services.frigate.service"]["status"] == "warn"


def test_only_frigate_restarts_itself(device_client, login, systemctl):
    """Another unit's 143 isn't its own restart, so the journal isn't read for it."""
    systemctl.units = {"node-red-tm.service": {"NRestarts": "1"}}
    systemctl.journal = [EXITED, RESTARTED]
    login(device_client, *ADMIN)
    assert service_group(device_client)["services.node-red-tm.service"]["status"] == "warn"
    assert not [call for call in systemctl.calls if call[0] == "journalctl"]


def test_automatic_restart_exits_reads_pid_1s_entries_this_boot(monkeypatch):
    seen = []

    def fake_run(argv, **kwargs):
        seen.append((list(argv), kwargs))
        entries = [EXITED, at({"MESSAGE_ID": systemd.UNIT_PROCESS_EXITED}, 100), RESTARTED, CRASHED, RESTARTED]
        return CommandResult(0, "".join(json.dumps(entry) + "\n" for entry in entries) + '{"cut', "", False)

    monkeypatch.setattr("tm_control.adapters.systemd.run", fake_run)
    # The second restart follows an exit with no status (killed by a signal, for example).
    assert systemd.automatic_restart_exits("frigate.service") == [None, "1"]
    ((argv, kwargs),) = seen
    assert argv[0] == "journalctl" and "-b" in argv and "_PID=1" in argv and "UNIT=frigate.service" in argv
    assert f"MESSAGE_ID={systemd.UNIT_PROCESS_EXITED}" in argv
    assert f"MESSAGE_ID={systemd.UNIT_RESTART_SCHEDULED}" in argv
    assert "__MONOTONIC_TIMESTAMP" in argv[-1]
    # The unit read runs first, and the whole Services group has 5 seconds.
    assert 0 < kwargs["timeout"] <= 2


def test_automatic_restart_exits_pairs_an_exit_only_with_a_restart_soon_after(monkeypatch):
    entries = [EXITED, at(RESTARTED, 159), at(EXITED, 200), at(RESTARTED, 200.1), at(RESTARTED, 300)]
    stdout = "".join(json.dumps(entry) + "\n" for entry in entries)
    monkeypatch.setattr("tm_control.adapters.systemd.run", lambda argv, **kwargs: CommandResult(0, stdout, "", False))
    assert systemd.automatic_restart_exits("frigate.service") == ["143", "143", None]

    no_time = [{k: v for k, v in entry.items() if k != "__MONOTONIC_TIMESTAMP"} for entry in (EXITED, RESTARTED)]
    stdout = "".join(json.dumps(entry) + "\n" for entry in no_time)
    assert systemd.automatic_restart_exits("frigate.service") == [None]


def test_automatic_restart_exits_is_none_when_the_output_was_cut(monkeypatch):
    """The cap drops the newest entries, the ones NRestarts counts."""
    stdout = json.dumps(EXITED) + "\n" + json.dumps(RESTARTED) + "\n" + '{"cut' + TRUNCATED
    monkeypatch.setattr("tm_control.adapters.systemd.run", lambda argv, **kwargs: CommandResult(0, stdout, "", False))
    assert systemd.automatic_restart_exits("frigate.service") is None


def test_automatic_restart_exits_is_none_when_journalctl_fails(monkeypatch):
    monkeypatch.setattr("tm_control.adapters.systemd.run", lambda argv, **kwargs: CommandResult(1, "", "", False))
    assert systemd.automatic_restart_exits("frigate.service") is None

    def missing(argv, **kwargs):
        raise FileNotFoundError(argv[0])

    monkeypatch.setattr("tm_control.adapters.systemd.run", missing)
    assert systemd.automatic_restart_exits("frigate.service") is None


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
