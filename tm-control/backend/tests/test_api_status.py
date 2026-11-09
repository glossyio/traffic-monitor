import json
import sqlite3
from datetime import datetime
from pathlib import Path

from tm_control.adapters.command import CommandResult
from tm_control.core.auth import Users
from tm_control.core.checks import Group
from tm_control.modules import MODULES

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


def test_status_module_comes_right_after_jobs():
    ids = [m.id for m in MODULES]
    assert ids[ids.index("jobs") + 1] == "status"


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
        assert [g["id"] for g in body["groups"]] == ["services", "apps", "config", "hardware", "device", "time"]
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
    assert {f["href"] for f in fixes if f["kind"] == "link"} == {"/device", "/time"}


def test_the_fake_report_has_the_real_groups_and_fixes():
    from tm_control.modules.apps.checks import DIAGNOSTICS
    from tm_control.modules.hardware.checks import RESCAN
    from tm_control.modules.time.checks import SET_IT

    groups = fake_groups()
    assert [(g["id"], g["title"]) for g in groups] == [(g.id, g.title) for m in MODULES for g in m.check_groups]
    fixes = [c["fix"] for g in groups for c in g["checks"] if c["fix"] and c["fix"]["kind"] in ("rescan", "link")]
    assert {tuple(f.items()) for f in fixes} == {tuple(f.model_dump().items()) for f in (DIAGNOSTICS, RESCAN, SET_IT)}
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
