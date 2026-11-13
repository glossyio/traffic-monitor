import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path

from tm_control.adapters.command import CommandResult
from tm_control.core.auth import Users
from tm_control.core.checks import Group
from tm_control.modules import MODULES
from tm_control.modules.location import reconcile
from tm_control.modules.location.places import Places

FIXTURES = Path(__file__).resolve().parent / "fixtures"
ORIGIN = {"Origin": "http://tm-test.local"}
ADMIN = ("admin", "correct horse 1")
VIEWER = ("viewer", "viewer pass 1")


def fake_groups():
    """The fake fixture's groups as the API serializes them (unset fields as null)."""
    groups = json.loads((FIXTURES / "status_fake.json").read_text())["groups"]
    return [Group.model_validate(group).model_dump() for group in groups]


def audit_actions(settings):
    con = sqlite3.connect(settings.state_dir / "state.sqlite")
    try:
        return [row[0] for row in con.execute("SELECT action FROM audit ORDER BY id")]
    finally:
        con.close()


def test_status_module_comes_right_after_jobs_secrets_detection_location_and_cameras():
    ids = [m.id for m in MODULES]
    assert ids[ids.index("jobs") + 1:ids.index("jobs") + 6] == ["secrets", "detection", "location", "cameras", "status"]


def test_status_needs_a_session(claimed_client):
    r = claimed_client.get("/api/v1/status")
    assert r.status_code == 401 and r.json()["error"]["code"] == "unauthenticated"


def test_status_report_for_a_viewer_and_an_admin(claimed_client, login):
    Users(claimed_client.app.state.state).create(*VIEWER, "viewer")
    for account in (VIEWER, ADMIN):
        login(claimed_client, *account)
        r = claimed_client.get("/api/v1/status")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["groups"] == fake_groups()
        assert [g["id"] for g in body["groups"]] == ["services", "apps", "config", "hardware", "network", "device", "time"]
        assert datetime.fromisoformat(body["generated_at"]).utcoffset() is not None
        assert set(body["summary"]) == {"ok", "warn", "error", "unknown"}
        assert sum(body["summary"].values()) == sum(len(g["checks"]) for g in body["groups"])


def test_the_fake_report_shows_every_status_and_fix_kind(claimed_client, login):
    login(claimed_client, *ADMIN)
    checks = [c for g in claimed_client.get("/api/v1/status").json()["groups"] for c in g["checks"]]
    assert {c["status"] for c in checks} == {"ok", "warn", "error", "unknown"}
    fixes = [c["fix"] for c in checks if c["fix"]]
    assert {f["kind"] for f in fixes} == {"restart", "rescan", "link", "hint"}
    assert all(f["unit"] for f in fixes if f["kind"] == "restart")
    assert {f["href"] for f in fixes if f["kind"] == "link"} == {"/device", "/time", "/cameras"}


def test_the_fake_report_has_the_real_groups_and_fixes():
    from tm_control.modules.apps.checks import DIAGNOSTICS
    from tm_control.modules.apps.contracts import CAMERAS_LINK
    from tm_control.modules.hardware.checks import RESCAN
    from tm_control.modules.time.checks import SET_IT

    groups = fake_groups()
    assert [(g["id"], g["title"]) for g in groups] == [(g.id, g.title) for m in MODULES for g in m.check_groups]
    fixes = [c["fix"] for g in groups for c in g["checks"] if c["fix"] and c["fix"]["kind"] in ("rescan", "link")]
    real = (CAMERAS_LINK, DIAGNOSTICS, RESCAN, SET_IT)
    assert {tuple(f.items()) for f in fixes} == {tuple(f.model_dump().items()) for f in real}
    for group in groups:
        assert all(c["id"].startswith(f"{group['id']}.") for c in group["checks"])


def test_rescan_is_admin_only_and_audited(claimed_client, login, settings):
    Users(claimed_client.app.state.state).create(*VIEWER, "viewer")
    login(claimed_client, *VIEWER)
    r = claimed_client.post("/api/v1/status/rescan", json={}, headers=ORIGIN)
    assert r.status_code == 403 and r.json()["error"]["code"] == "forbidden"
    assert "status.rescan" not in audit_actions(settings)

    login(claimed_client, *ADMIN)
    r = claimed_client.post("/api/v1/status/rescan", json={}, headers=ORIGIN)
    assert r.status_code == 200, r.text
    assert r.json()["groups"] == fake_groups()
    assert audit_actions(settings).count("status.rescan") == 1


def test_rescan_bypasses_the_cache(claimed_client, login):
    login(claimed_client, *ADMIN)
    cache = claimed_client.app.state.status
    first = cache.report()
    claimed_client.post("/api/v1/status/rescan", json={}, headers=ORIGIN)
    assert cache.report() is not first


def created_by(state):
    con = state.connect()
    try:
        return [row[0] for row in con.execute("SELECT created_by FROM surveys")]
    finally:
        con.close()


def test_a_viewers_status_report_reconciles_the_places(claimed_client, login):
    """claimed_client's device was claimed without the claim API, so nothing has set its places up yet. Fake mode's
    config.yml has a location and Node-RED answers, so the place in use comes from the file."""
    state = claimed_client.app.state.state
    places = Places(state)
    assert places.reconciled_at() is None
    Users(state).create(*VIEWER, "viewer")
    login(claimed_client, *VIEWER)
    assert claimed_client.get("/api/v1/status").status_code == 200
    assert places.reconciled_at() is not None
    assert places.in_use().source == "imported_config"
    assert created_by(state) == [None]


def test_a_status_report_skips_reconcile_while_the_lock_is_held(claimed_client, login, monkeypatch):
    monkeypatch.setattr(reconcile, "STATUS_LOCK_WAIT", 0.05)
    login(claimed_client, *ADMIN)
    lock = claimed_client.app.state.reconcile_lock
    lock.acquire()
    try:
        r = claimed_client.get("/api/v1/status")
    finally:
        lock.release()
    assert r.status_code == 200, r.text
    assert Places(claimed_client.app.state.state).reconciled_at() is None
    # the next report, with the lock free, catches up
    assert claimed_client.post("/api/v1/status/rescan", json={}, headers=ORIGIN).status_code == 200
    assert Places(claimed_client.app.state.state).reconciled_at() is not None


def test_a_failing_reconcile_leaves_the_status_report_whole(claimed_client, login, monkeypatch, caplog):
    def broken(path):
        raise RuntimeError("synthetic 45.52252")

    monkeypatch.setattr(reconcile, "NodeRedConfig", broken)
    login(claimed_client, *ADMIN)
    with caplog.at_level(logging.INFO, logger=reconcile.__name__):
        r = claimed_client.get("/api/v1/status")
    assert r.status_code == 200, r.text
    assert r.json()["groups"] == fake_groups()
    messages = [record.getMessage() for record in caplog.records if record.name == reconcile.__name__]
    assert messages == ["reconcile for the status report failed: RuntimeError"]
    assert not any("45" in record.getMessage() for record in caplog.records)


def test_openapi_declares_the_report_model(client):
    document = client.app.openapi()
    for path, method in (("/api/v1/status", "get"), ("/api/v1/status/rescan", "post")):
        schema = document["paths"][path][method]["responses"]["200"]["content"]["application/json"]["schema"]
        assert schema == {"$ref": "#/components/schemas/Report"}
    report = document["components"]["schemas"]["Report"]
    assert set(report["properties"]) == {"generated_at", "summary", "groups"}


def test_device_client_serves_the_modules_groups(device_client, login, monkeypatch):
    def systemctl(argv, **kwargs):
        assert argv[:2] == ["systemctl", "show"], argv
        return CommandResult(0, "LoadState=loaded\nActiveState=active\nSubState=running\nNRestarts=0\n", "", False)

    monkeypatch.setattr("tm_control.adapters.systemd.run", systemctl)
    assert device_client.app.state.settings.fake is False
    login(device_client, *VIEWER)
    r = device_client.get("/api/v1/status")
    assert r.status_code == 200, r.text
    body = r.json()
    groups = [group.id for module in MODULES for group in module.check_groups]
    assert [g["id"] for g in body["groups"]] == groups
    assert "services" in groups
    assert datetime.fromisoformat(body["generated_at"]).utcoffset() is not None
    assert set(body["summary"]) == {"ok", "warn", "error", "unknown"}
    assert sum(body["summary"].values()) == sum(len(g["checks"]) for g in body["groups"])
    login(device_client, *ADMIN)
    assert device_client.post("/api/v1/status/rescan", json={}, headers=ORIGIN).status_code == 200
