import sqlite3

from fastapi.testclient import TestClient

from tm_control.core.auth import Users

BASE = "http://tm-test.local"
ORIGIN = {"Origin": BASE}
# A DELETE carries no body, but the cross-site check still wants the JSON content type, as the UI sends it.
DELETE_HEADERS = {**ORIGIN, "Content-Type": "application/json"}
ADMIN = ("admin", "correct horse 1")
VIEWER = ("viewer", "viewer pass 1")


def other_client(client):
    """A second browser on the same app, with its own cookie jar."""
    return TestClient(client.app, base_url=BASE)


def verify(client):
    return client.get("/api/v1/auth/verify", headers={"X-Original-URI": "/"})


def change_password(client, current, new):
    body = {"current_password": current, "new_password": new}
    return client.post("/api/v1/account/password", json=body, headers=ORIGIN)


def create_viewer(client, username=VIEWER[0], password=VIEWER[1]):
    return client.post("/api/v1/users", json={"username": username, "password": password}, headers=ORIGIN)


def test_account_shows_the_current_user(claimed_client, login):
    r = claimed_client.get("/api/v1/account")
    assert r.status_code == 401 and r.json()["error"]["code"] == "unauthenticated"
    login(claimed_client, *ADMIN)
    r = claimed_client.get("/api/v1/account")
    assert r.status_code == 200
    assert r.json()["user"]["username"] == "admin" and r.json()["user"]["role"] == "admin"
    assert set(r.json()["user"]) == {"id", "username", "role", "created_at"}


def test_password_change_needs_the_current_password(claimed_client, login):
    login(claimed_client, *ADMIN)
    r = change_password(claimed_client, "placeholder-wrong", "a new pass 12")
    assert r.status_code == 401 and r.json()["error"]["code"] == "unauthenticated"
    r = change_password(claimed_client, ADMIN[1], "short")
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation"
    assert Users(claimed_client.app.state.state).authenticate(*ADMIN) is not None
    assert verify(claimed_client).status_code == 200  # a wrong current password doesn't end the session


def test_password_change_backs_off_wrong_guesses(claimed_client, login):
    login(claimed_client, *ADMIN)
    for _ in range(5):
        assert change_password(claimed_client, "placeholder-wrong", "a new pass 12").status_code == 401
    r = change_password(claimed_client, ADMIN[1], "a new pass 12")
    assert r.status_code == 429 and r.json()["error"]["code"] == "rate_limited"


def test_password_change_keeps_this_browser_and_logs_out_the_others(claimed_client, login):
    second = other_client(claimed_client)
    login(claimed_client, *ADMIN)
    login(second, *ADMIN)
    r = change_password(claimed_client, ADMIN[1], "a new pass 12")
    assert r.status_code == 204
    assert "tm_session" in r.cookies
    assert verify(second).status_code == 401
    assert verify(claimed_client).status_code == 200
    assert Users(claimed_client.app.state.state).authenticate("admin", "a new pass 12") is not None
    assert len(claimed_client.app.state.login_backoff) == 0


def test_admin_creates_lists_resets_and_deletes_viewers(claimed_client, login):
    viewer_browser = other_client(claimed_client)
    login(claimed_client, *ADMIN)

    r = create_viewer(claimed_client, "Viewer")
    assert r.status_code == 201, r.text
    viewer = r.json()["user"]
    assert viewer["username"] == "viewer" and viewer["role"] == "viewer"
    assert set(viewer) == {"id", "username", "role", "created_at"}

    users = claimed_client.get("/api/v1/users").json()["users"]
    assert [u["username"] for u in users] == ["admin", "viewer"]
    assert all("session_epoch" not in u for u in users)

    login(viewer_browser, *VIEWER)
    r = claimed_client.post(
        f"/api/v1/users/{viewer['id']}/password", json={"new_password": "viewer pass 2"}, headers=ORIGIN
    )
    assert r.status_code == 204
    assert verify(viewer_browser).status_code == 401
    login(viewer_browser, "viewer", "viewer pass 2")

    r = claimed_client.delete(f"/api/v1/users/{viewer['id']}", headers=DELETE_HEADERS)
    assert r.status_code == 204
    assert verify(viewer_browser).status_code == 401
    assert [u["username"] for u in claimed_client.get("/api/v1/users").json()["users"]] == ["admin"]


def test_new_users_follow_the_rules(claimed_client, login):
    login(claimed_client, *ADMIN)
    for username, password in [("x", VIEWER[1]), ("has space", VIEWER[1]), ("viewer", "short")]:
        r = create_viewer(claimed_client, username, password)
        assert r.status_code == 422 and r.json()["error"]["code"] == "validation"
    viewer_id = create_viewer(claimed_client).json()["user"]["id"]
    r = claimed_client.post(f"/api/v1/users/{viewer_id}/password", json={"new_password": "short"}, headers=ORIGIN)
    assert r.status_code == 422


def test_viewer_cannot_manage_users(claimed_client, login):
    Users(claimed_client.app.state.state).create(*VIEWER, "viewer")
    login(claimed_client, *VIEWER)
    admin_id = Users(claimed_client.app.state.state).by_username("admin").id
    for r in [
        claimed_client.get("/api/v1/users"),
        create_viewer(claimed_client, "another"),
        claimed_client.delete(f"/api/v1/users/{admin_id}", headers=DELETE_HEADERS),
        claimed_client.post(f"/api/v1/users/{admin_id}/password", json={"new_password": "x" * 12}, headers=ORIGIN),
    ]:
        assert r.status_code == 403 and r.json()["error"]["code"] == "forbidden"
    assert claimed_client.get("/api/v1/account").json()["user"]["username"] == "viewer"


def test_delete_needs_the_json_content_type(claimed_client, login):
    login(claimed_client, *ADMIN)
    viewer_id = create_viewer(claimed_client).json()["user"]["id"]
    assert claimed_client.delete(f"/api/v1/users/{viewer_id}", headers=ORIGIN).status_code == 403


def test_duplicate_username_is_409_ignoring_case(claimed_client, login):
    login(claimed_client, *ADMIN)
    assert create_viewer(claimed_client, "viewer").status_code == 201
    r = create_viewer(claimed_client, "Viewer")
    assert r.status_code == 409 and r.json()["error"]["code"] == "conflict"
    r = create_viewer(claimed_client, "ADMIN")
    assert r.status_code == 409


def test_admin_cannot_delete_themselves(claimed_client, login):
    login(claimed_client, *ADMIN)
    admin_id = claimed_client.get("/api/v1/account").json()["user"]["id"]
    r = claimed_client.delete(f"/api/v1/users/{admin_id}", headers=DELETE_HEADERS)
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation"
    assert verify(claimed_client).status_code == 200


def test_an_admin_may_delete_another_admin(claimed_client, login):
    other = Users(claimed_client.app.state.state).create("second", "second pass 1", "admin")
    login(claimed_client, *ADMIN)
    assert claimed_client.delete(f"/api/v1/users/{other.id}", headers=DELETE_HEADERS).status_code == 204


def test_admin_resets_their_own_password_only_on_the_account_page(claimed_client, login):
    """The users endpoint skips the current password, so a borrowed admin session can't take the account over."""
    login(claimed_client, *ADMIN)
    admin_id = claimed_client.get("/api/v1/account").json()["user"]["id"]
    r = claimed_client.post(f"/api/v1/users/{admin_id}/password", json={"new_password": "taken over 1"}, headers=ORIGIN)
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation"
    assert Users(claimed_client.app.state.state).authenticate(*ADMIN) is not None


def test_unknown_user_ids_are_404(claimed_client, login):
    login(claimed_client, *ADMIN)
    r = claimed_client.delete("/api/v1/users/9999", headers=DELETE_HEADERS)
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
    r = claimed_client.post("/api/v1/users/9999/password", json={"new_password": "viewer pass 2"}, headers=ORIGIN)
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
    for user_id in ("0", "-1", str(2**63), "abc"):
        r = claimed_client.delete(f"/api/v1/users/{user_id}", headers=DELETE_HEADERS)
        assert r.status_code == 422 and r.json()["error"]["code"] == "validation"


def test_user_actions_are_audited(claimed_client, login, settings):
    login(claimed_client, *ADMIN)
    viewer_id = create_viewer(claimed_client).json()["user"]["id"]
    claimed_client.post(f"/api/v1/users/{viewer_id}/password", json={"new_password": "viewer pass 2"}, headers=ORIGIN)
    claimed_client.delete(f"/api/v1/users/{viewer_id}", headers=DELETE_HEADERS)
    change_password(claimed_client, ADMIN[1], "a new pass 12")

    con = sqlite3.connect(settings.state_dir / "state.sqlite")
    rows = con.execute("SELECT user_id, action, detail FROM audit ORDER BY id").fetchall()
    con.close()
    admin_id = Users(claimed_client.app.state.state).by_username("admin").id
    assert rows == [
        (admin_id, "user.create", "viewer"),
        (admin_id, "user.password", "viewer"),
        (admin_id, "user.delete", "viewer"),
        (admin_id, "account.password", None),
    ]
    assert "viewer pass" not in str(rows) and "a new pass" not in str(rows)
