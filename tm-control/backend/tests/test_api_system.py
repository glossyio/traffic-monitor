import dataclasses
import json
import socket
import sqlite3
from datetime import datetime

from fastapi.testclient import TestClient

from tm_control.app import create_app
from tm_control.core.auth import Device, Users
from tm_control.modules import MODULES
from tm_control.modules.setup.eula import load_eula
from tm_control.modules.system.router import read_serial

BASE = "http://tm-test.local"
ORIGIN = {"Origin": BASE}
ADMIN = ("admin", "correct horse 1")
VIEWER = ("viewer", "viewer pass 1")
SYSTEM_PASSWORD = "placeholder system 1"


def add_viewer(client):
    Users(client.app.state.state).create(*VIEWER, "viewer")


def set_system_password(client, password=SYSTEM_PASSWORD):
    return client.post("/api/v1/system/password", json={"password": password}, headers=ORIGIN)


def test_jobs_and_system_modules_are_registered():
    assert {"jobs", "system"} <= {m.id for m in MODULES}


def test_device_card_and_apps_for_an_admin(claimed_client, login):
    login(claimed_client, *ADMIN)
    r = claimed_client.get("/api/v1/system/device")
    assert r.status_code == 200
    body = r.json()
    assert body["hostname"] == socket.gethostname()
    assert body["serial"] == "0000000012345678"
    assert body["tm_version"] == "0.7.1-test"
    assert datetime.fromisoformat(body["time"]).utcoffset() is not None
    assert body["apps"] == [
        {"id": "dashboard", "path": "/dashboard/", "title": "Dashboard", "admin_only": False},
        {"id": "frigate", "path": "/frigate/", "title": "Frigate", "admin_only": False},
        {"id": "legacy-ui", "path": "/ui/", "title": "Legacy Dashboard", "admin_only": False},
        {"id": "nodered", "path": "/nr/", "title": "Node-RED editor", "admin_only": True},
        {"id": "feeds", "path": "/feeds/", "title": "Camera feeds", "admin_only": True},
        {"id": "cockpit", "path": "/system/", "title": "Cockpit", "admin_only": True},
    ]
    assert body["theme"] == {
        "font": "Helvetica",
        "colors": {
            "background": "#0C1120",
            "header_text": "#3a82ff",
            "body_text": "#f8fafc",
            "link_hover_text": "#8895a7",
        },
    }


def test_viewers_see_no_admin_tiles(claimed_client, login):
    add_viewer(claimed_client)
    login(claimed_client, *VIEWER)
    r = claimed_client.get("/api/v1/system/device")
    assert r.status_code == 200
    apps = r.json()["apps"]
    assert [app["id"] for app in apps] == ["dashboard", "frigate", "legacy-ui"]
    assert not any(app["admin_only"] for app in apps)


def test_the_device_card_needs_a_login(claimed_client):
    r = claimed_client.get("/api/v1/system/device")
    assert r.status_code == 401 and r.json()["error"]["code"] == "unauthenticated"


def test_apps_follow_the_manifest_locations(settings, tmp_path, login):
    manifest = json.loads(settings.manifest_path.read_text())
    manifest["revproxy_locations"].remove("cockpit.conf")
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))
    client = TestClient(create_app(dataclasses.replace(settings, manifest_path=path)), base_url=BASE)
    Device(client.app.state.state).claim(*ADMIN, load_eula(settings.eula_path).version)
    login(client, *ADMIN)
    ids = [app["id"] for app in client.get("/api/v1/system/device").json()["apps"]]
    assert ids == ["dashboard", "frigate", "legacy-ui", "nodered", "feeds"]


def test_read_serial_strips_the_devicetree_padding(tmp_path):
    path = tmp_path / "serial-number"
    path.write_bytes(b"10000000abcdef01\x00")
    assert read_serial(path) == "10000000abcdef01"
    path.write_bytes(b"\x00\n")
    assert read_serial(path) == "unknown"
    assert read_serial(tmp_path / "missing") == "unknown"


def test_system_password_job_is_admin_only_and_returns_202(claimed_client, login):
    add_viewer(claimed_client)
    login(claimed_client, *VIEWER)
    r = set_system_password(claimed_client)
    assert r.status_code == 403 and r.json()["error"]["code"] == "forbidden"
    assert claimed_client.app.state.jobs.last_request is None

    login(claimed_client, *ADMIN)
    r = set_system_password(claimed_client)
    assert r.status_code == 202
    job_id = r.json()["id"]
    assert claimed_client.app.state.jobs.last_request == {"username": "pi", "password": SYSTEM_PASSWORD}
    r = claimed_client.get(f"/api/v1/jobs/{job_id}")
    assert r.status_code == 200
    job = r.json()
    assert job["id"] == job_id and job["name"] == "system-password" and job["status"] == "succeeded"
    assert job["log"] == ["fake: system-password done"]
    assert set(job) == {"id", "name", "status", "requested_at", "finished_at", "log"}

    assert set_system_password(claimed_client).status_code == 202  # the fake leaves no request behind

    login(claimed_client, *VIEWER)
    r = claimed_client.get(f"/api/v1/jobs/{job_id}")
    assert r.status_code == 403


def test_an_unknown_job_is_404(claimed_client, login):
    login(claimed_client, *ADMIN)
    r = claimed_client.get("/api/v1/jobs/no-such-job")
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"


def test_system_password_enforces_the_rules(claimed_client, login):
    login(claimed_client, *ADMIN)
    for password in ["short", "x" * 257, "a\nb" + "x" * 10, "a\rb" + "x" * 10, "a\x00b" + "x" * 10]:
        r = set_system_password(claimed_client, password)
        assert r.status_code == 422 and r.json()["error"]["code"] == "validation", password
    r = claimed_client.post("/api/v1/system/password", json={}, headers=ORIGIN)
    assert r.status_code == 422
    assert claimed_client.app.state.jobs.last_request is None


def test_jobs_are_audited_without_the_password(claimed_client, login, settings):
    login(claimed_client, *ADMIN)
    assert set_system_password(claimed_client).status_code == 202
    admin = Users(claimed_client.app.state.state).by_username("admin")
    con = sqlite3.connect(settings.state_dir / "state.sqlite")
    try:
        rows = con.execute("SELECT user_id, action, detail FROM audit ORDER BY id").fetchall()
        dump = "\n".join(con.iterdump())
    finally:
        con.close()
    assert (admin.id, "system.password", None) in rows
    assert SYSTEM_PASSWORD not in dump
