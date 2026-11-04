"""The entered secrets' API: GET /secrets, and POST and DELETE /secrets/{name}, which start the set-secret root job.

claimed_client runs in fake mode, whose FakeSecrets.entered starts empty and whose job runner succeeds at once; the
fixture manifest has no Plate Recognizer add-on.
"""

import dataclasses
import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from tm_control.app import create_app
from tm_control.core.auth import Device, Users
from tm_control.modules import MODULES
from tm_control.modules.setup.eula import load_eula

BASE = "http://tm-test.local"
ORIGIN = {"Origin": BASE}
DELETE_HEADERS = {**ORIGIN, "Content-Type": "application/json"}  # the cross-site check wants JSON on every non-GET
ADMIN = ("admin", "correct horse 1")
VIEWER = ("viewer", "viewer pass 1")
TB = "thingsboard_access_token"
TB_VALUE = "tb-placeholder-0001"
PR_TOKEN = "plate_recognizer_token"
PR_KEY = "plate_recognizer_license_key"
EMPTY_MESSAGE = "Enter a value, or leave this as it is."
ADMIN_ONLY = "Only an admin can do this."  # require_admin's refusal


def set_secret(client, name, value):
    return client.post(f"/api/v1/secrets/{name}", json={"value": value}, headers=ORIGIN)


def remove_secret(client, name):
    return client.delete(f"/api/v1/secrets/{name}", headers=DELETE_HEADERS)


def secrets(client):
    r = client.get("/api/v1/secrets")
    assert r.status_code == 200, r.text
    return {secret["name"]: secret for secret in r.json()["secrets"]}


def addon_client(settings, tmp_path):
    """A claimed fake-mode client whose manifest says the Plate Recognizer add-on is installed. It has its own state
    and runtime directories, so a test can use claimed_client beside it."""
    manifest = json.loads(settings.manifest_path.read_text())
    manifest["options"]["plate_recognizer"] = True
    path = tmp_path / "manifest-addon.json"
    path.write_text(json.dumps(manifest))
    settings = dataclasses.replace(
        settings, manifest_path=path, state_dir=tmp_path / "addon-state", runtime_dir=tmp_path / "addon-run"
    )
    client = TestClient(create_app(settings), base_url=BASE)
    Device(client.app.state.state).claim(*ADMIN, load_eula(settings.eula_path).version)
    return client


def test_secrets_module_is_registered():
    ids = [m.id for m in MODULES]
    assert ids[ids.index("jobs") + 1] == "secrets"


def test_get_secrets_is_admin_only_and_lists_the_available_ones(claimed_client, login):
    Users(claimed_client.app.state.state).create(*VIEWER, "viewer")
    login(claimed_client, *VIEWER)
    r = claimed_client.get("/api/v1/secrets")
    assert r.status_code == 403 and r.json()["error"]["message"] == ADMIN_ONLY

    login(claimed_client, *ADMIN)
    r = claimed_client.get("/api/v1/secrets")
    assert r.status_code == 200
    assert r.json() == {
        "secrets": [
            {
                "name": TB,
                "title": "ThingsBoard access token",
                "set": False,
                "ends_with": None,
                "restarts": ["node-red-tm.service"],
            }
        ]
    }


def test_plate_recognizer_secrets_appear_only_with_the_addon(settings, tmp_path, login, claimed_client):
    client = addon_client(settings, tmp_path)
    login(client, *ADMIN)
    listed = client.get("/api/v1/secrets").json()["secrets"]
    assert [s["name"] for s in listed] == [TB, PR_TOKEN, PR_KEY]
    assert [s["title"] for s in listed] == [
        "ThingsBoard access token", "Plate Recognizer API token", "Plate Recognizer license key",
    ]
    assert listed[1]["restarts"] == ["plate-recognizer.service", "node-red-tm.service"]
    assert listed[2]["restarts"] == ["plate-recognizer.service"]
    assert set_secret(client, PR_TOKEN, "pr-placeholder-0002").status_code == 202
    assert set_secret(client, PR_KEY, "pr-placeholder-0003").status_code == 202
    state = secrets(client)
    assert state[PR_TOKEN]["set"] is True and state[PR_TOKEN]["ends_with"] == "0002"
    assert state[PR_KEY]["set"] is True and state[PR_KEY]["ends_with"] is None  # the license key shows no ending

    login(claimed_client, *ADMIN)
    for name in (PR_TOKEN, PR_KEY):
        r = set_secret(claimed_client, name, "pr-placeholder-0004")
        assert r.status_code == 404 and r.json()["error"]["code"] == "not_found", name
        r = remove_secret(claimed_client, name)
        assert r.status_code == 404 and r.json()["error"]["code"] == "not_found", name
    assert claimed_client.app.state.jobs.last_request is None


def test_set_secret_starts_the_job_and_the_state_follows(claimed_client, login):
    login(claimed_client, *ADMIN)
    r = set_secret(claimed_client, TB, TB_VALUE)
    assert r.status_code == 202
    job_id = r.json()["id"]
    assert claimed_client.app.state.jobs.last_request == {"name": TB, "value": TB_VALUE}
    job = claimed_client.get(f"/api/v1/jobs/{job_id}").json()
    assert job["name"] == "set-secret" and job["status"] == "succeeded"
    state = secrets(claimed_client)[TB]
    assert state["set"] is True and state["ends_with"] == "0001"


@pytest.mark.parametrize("value", ["", "   "])
def test_set_secret_refuses_an_empty_value(claimed_client, login, value):
    login(claimed_client, *ADMIN)
    r = set_secret(claimed_client, TB, value)
    assert r.status_code == 422
    assert r.json()["error"] == {"code": "validation", "message": EMPTY_MESSAGE, "detail": None}
    assert claimed_client.app.state.jobs.last_request is None


@pytest.mark.parametrize("value", ["a b", "a/b", "a?b", "é", "x" * 257])
def test_set_secret_enforces_the_value_pattern(claimed_client, login, value):
    login(claimed_client, *ADMIN)
    r = set_secret(claimed_client, TB, value)
    assert r.status_code == 422
    error = r.json()["error"]
    assert error["code"] == "validation"
    assert error["message"] == (
        "A ThingsBoard access token is 1 to 256 letters, digits, dots, dashes, underscores, or tildes."
    )
    assert claimed_client.app.state.jobs.last_request is None
    assert secrets(claimed_client)[TB]["set"] is False


def test_plate_recognizer_values_take_printable_ascii(settings, tmp_path, login):
    client = addon_client(settings, tmp_path)
    login(client, *ADMIN)
    assert set_secret(client, PR_TOKEN, "pr/placeholder?0005").status_code == 202
    for value in ["a b", "é", "x" * 257, "a\tb"]:
        r = set_secret(client, PR_KEY, value)
        assert r.status_code == 422
        assert r.json()["error"]["message"] == (
            "A Plate Recognizer value is 1 to 256 printable characters with no spaces."
        )


def test_unknown_secret_is_404(claimed_client, login):
    login(claimed_client, *ADMIN)
    for r in (set_secret(claimed_client, "session_key", TB_VALUE), remove_secret(claimed_client, "session_key")):
        assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
    assert claimed_client.app.state.jobs.last_request is None
    assert "session_key" not in secrets(claimed_client)
    assert "tm_control_session_key" not in secrets(claimed_client)


def test_remove_secret_sends_an_empty_value(claimed_client, login):
    login(claimed_client, *ADMIN)
    assert set_secret(claimed_client, TB, TB_VALUE).status_code == 202
    r = remove_secret(claimed_client, TB)
    assert r.status_code == 202 and r.json()["id"]
    assert claimed_client.app.state.jobs.last_request == {"name": TB, "value": ""}
    state = secrets(claimed_client)[TB]
    assert state["set"] is False and state["ends_with"] is None
    assert remove_secret(claimed_client, TB).status_code == 202  # removing what isn't set still works


def test_secret_actions_are_audited_without_the_value(claimed_client, login, settings):
    login(claimed_client, *ADMIN)
    assert set_secret(claimed_client, TB, TB_VALUE).status_code == 202
    assert remove_secret(claimed_client, TB).status_code == 202
    admin = Users(claimed_client.app.state.state).by_username("admin")
    con = sqlite3.connect(settings.state_dir / "state.sqlite")
    try:
        rows = con.execute("SELECT user_id, action, detail FROM audit ORDER BY id").fetchall()
        dump = "\n".join(con.iterdump())
    finally:
        con.close()
    assert (admin.id, "secrets.set", TB) in rows
    assert (admin.id, "secrets.removed", TB) in rows
    assert TB_VALUE not in dump


def test_validation_errors_do_not_echo_the_value(claimed_client, login):
    login(claimed_client, *ADMIN)
    for value in ["tb placeholder 0006", "tb-placeholder-0007/x"]:
        r = set_secret(claimed_client, TB, value)
        assert r.status_code == 422
        assert value not in r.text and "placeholder" not in r.text
    r = set_secret(claimed_client, TB, "tb-placeholder-0008" + "x" * 1024)  # over the body's max_length
    assert r.status_code == 422 and "placeholder" not in r.text
    r = claimed_client.post(f"/api/v1/secrets/{TB}", json={"value": 12345678}, headers=ORIGIN)
    assert r.status_code == 422 and "12345678" not in r.text
    assert claimed_client.app.state.jobs.last_request is None


def test_viewer_cannot_set_or_remove(claimed_client, login):
    Users(claimed_client.app.state.state).create(*VIEWER, "viewer")
    login(claimed_client, *VIEWER)
    for r in (set_secret(claimed_client, TB, TB_VALUE), remove_secret(claimed_client, TB)):
        assert r.status_code == 403
        assert r.json()["error"]["message"] == ADMIN_ONLY  # refused as a viewer, not by the cross-site check
    assert claimed_client.app.state.jobs.last_request is None
