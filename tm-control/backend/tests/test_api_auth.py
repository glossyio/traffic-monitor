import logging
import time
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi import APIRouter, Depends
from fastapi.testclient import TestClient

from tm_control.app import create_app
from tm_control.core.auth import COOKIE_NAME, MAX_AGE, Device, NodeRedToken, Users
from tm_control.core.secrets import FakeSecrets
from tm_control.modules import MODULES, Module
from tm_control.modules.auth.deps import current_user, require_admin
from tm_control.modules.setup.eula import Eula

BASE = "http://tm-test.local"
ORIGIN = {"Origin": BASE}
ADMIN = ("admin", "correct horse 1")
VIEWER = ("viewer", "viewer pass 1")


def other_client(client):
    """A second browser on the same app, with its own cookie jar."""
    return TestClient(client.app, base_url=BASE)


def add_viewer(client):
    Users(client.app.state.state).create(*VIEWER, "viewer")


def verify(client, uri="/dashboard/", role=None):
    headers = {"X-Original-URI": uri}
    if role:
        headers["X-TM-Required-Role"] = role
    return client.get("/api/v1/auth/verify", headers=headers)


def login_next(r):
    """The decoded next= of a 401's X-TM-Redirect."""
    redirect = urlsplit(r.headers["X-TM-Redirect"])
    assert redirect.path == "/login"
    return parse_qs(redirect.query)["next"][0]


def set_cookie_headers(r):
    return [v for k, v in r.headers.multi_items() if k == "set-cookie"]


def test_validation_errors_use_the_shape(claimed_client):
    r = claimed_client.post("/api/v1/auth/login", json={"username": 5}, headers=ORIGIN)
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation"


def test_auth_module_is_registered():
    assert "auth" in [m.id for m in MODULES]


def test_verify_sends_an_unclaimed_device_to_setup(client):
    r = client.get("/api/v1/auth/verify", headers={"X-Original-URI": "/frigate/"})
    assert (r.status_code, r.headers["X-TM-Redirect"]) == (401, "/setup")


def test_verify_without_a_session_redirects_to_login_with_next(claimed_client):
    r = verify(claimed_client, "/dashboard/")
    assert (r.status_code, r.headers["X-TM-Redirect"]) == (401, "/login?next=/dashboard/")
    assert r.json()["error"]["code"] == "unauthenticated"


@pytest.mark.parametrize(
    "uri, expected",
    [
        ("//evil", "/"),
        ("http://evil/x", "/"),
        ("/ok?a=1", "/ok?a=1"),
        ("/ok?a=1&b=2", "/ok?a=1&b=2"),
        ("/\\evil", "/"),
        ("evil", "/"),
        ("", "/"),
        ("/frigate/review#frag", "/frigate/review"),
        ("/a b", "/"),
    ],
)
def test_verify_sanitizes_next(claimed_client, uri, expected):
    r = verify(claimed_client, uri)
    assert r.status_code == 401 and login_next(r) == expected


def test_verify_without_an_original_uri_uses_the_root(claimed_client):
    r = claimed_client.get("/api/v1/auth/verify")
    assert r.status_code == 401 and login_next(r) == "/"


def test_verify_returns_identity_headers_for_a_logged_in_admin(claimed_client, login):
    login(claimed_client, *ADMIN)
    r = verify(claimed_client, "/nr/", role="admin")
    assert r.status_code == 200
    assert r.headers["X-TM-User"] == "admin" and r.headers["X-TM-Role"] == "admin"
    assert r.headers["X-TM-Frigate-Secret"] == FakeSecrets().frigate_proxy_secret
    claims = NodeRedToken(FakeSecrets().node_red_token_key).verify(r.headers["X-TM-NR-Token"])
    assert claims["u"] == "admin" and claims["r"] == "admin"
    assert "set-cookie" not in r.headers  # a fresh cookie isn't re-issued


def test_verify_gives_viewers_no_node_red_token_and_403_on_admin_paths(claimed_client, login):
    add_viewer(claimed_client)
    login(claimed_client, *VIEWER)
    r = verify(claimed_client, "/dashboard/")
    assert r.status_code == 200 and r.headers["X-TM-User"] == "viewer" and r.headers["X-TM-Role"] == "viewer"
    assert r.headers["X-TM-Frigate-Secret"] == FakeSecrets().frigate_proxy_secret
    assert "X-TM-NR-Token" not in r.headers
    r = verify(claimed_client, "/nr/", role="admin")
    assert r.status_code == 403 and r.json()["error"]["code"] == "forbidden"
    assert "X-TM-User" not in r.headers and "X-TM-Redirect" not in r.headers


def test_verify_refuses_an_unknown_required_role(claimed_client, login):
    login(claimed_client, *ADMIN)
    assert verify(claimed_client, "/nr/", role="root").status_code == 403


def test_verify_blocks_an_admin_until_the_current_eula_is_accepted(claimed_client, login, monkeypatch):
    add_viewer(claimed_client)
    viewer = other_client(claimed_client)
    login(claimed_client, *ADMIN)
    login(viewer, *VIEWER)
    monkeypatch.setattr(claimed_client.app.state, "eula", Eula(version="2", markdown="# New terms\n"))

    r = verify(claimed_client, "/frigate/")
    assert (r.status_code, r.headers["X-TM-Redirect"]) == (401, "/welcome")
    assert r.json()["error"]["code"] == "eula_required"
    r = verify(viewer, "/frigate/")
    assert r.status_code == 403 and r.json()["error"]["code"] == "eula_required"

    Device(claimed_client.app.state.state).accept_eula("2", 1)
    assert verify(claimed_client, "/frigate/").status_code == 200
    assert verify(viewer, "/frigate/").status_code == 200


def test_verify_rejects_a_cookie_after_the_user_is_deleted(claimed_client, login):
    add_viewer(claimed_client)
    login(claimed_client, *VIEWER)
    users = Users(claimed_client.app.state.state)
    users.delete(users.by_username("viewer").id)
    assert verify(claimed_client).status_code == 401


def test_login_sets_a_cookie_and_session_shows_the_user(claimed_client):
    r = claimed_client.post("/api/v1/auth/login", json={"username": "Admin", "password": ADMIN[1]}, headers=ORIGIN)
    assert r.status_code == 200 and r.json()["user"]["username"] == "admin"
    assert set(r.json()["user"]) == {"id", "username", "role", "session_epoch", "created_at"}
    cookie = r.headers["set-cookie"]
    assert cookie.startswith(f"{COOKIE_NAME}=")
    flags = [part.strip().lower() for part in cookie.split(";")[1:]]
    assert "httponly" in flags and "samesite=lax" in flags and "path=/" in flags and f"max-age={MAX_AGE}" in flags
    assert "secure" not in flags
    s = claimed_client.get("/api/v1/auth/session").json()
    assert s["claimed"] and s["eula_accepted"] and s["user"]["username"] == "admin"


def test_login_fails_the_same_way_for_a_wrong_password_and_an_unknown_user(claimed_client, caplog):
    caplog.set_level(logging.WARNING)
    wrong = claimed_client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "placeholder-wrong"}, headers=ORIGIN
    )
    unknown = claimed_client.post(
        "/api/v1/auth/login", json={"username": "nobody", "password": "placeholder-wrong"}, headers=ORIGIN
    )
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json() and wrong.json()["error"]["code"] == "unauthenticated"
    assert "set-cookie" not in wrong.headers
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert any("admin" in m and "testclient" in m for m in warnings)
    assert any("nobody" in m for m in warnings)
    assert "placeholder-wrong" not in caplog.text


def test_login_backs_off_after_five_failures(claimed_client):
    for _ in range(5):
        r = claimed_client.post("/api/v1/auth/login", json={"username": "admin", "password": "x" * 10}, headers=ORIGIN)
        assert r.status_code == 401
    r = claimed_client.post("/api/v1/auth/login", json={"username": "admin", "password": ADMIN[1]}, headers=ORIGIN)
    assert r.status_code == 429 and r.json()["error"]["code"] == "rate_limited"
    assert int(r.headers["Retry-After"]) >= 1


def test_login_backs_off_per_user_across_addresses(claimed_client):
    for _ in range(5):
        claimed_client.app.state.login_backoff.record_failure("user:admin", time.monotonic())
    r = claimed_client.post("/api/v1/auth/login", json={"username": "ADMIN", "password": ADMIN[1]}, headers=ORIGIN)
    assert r.status_code == 429


def test_successful_login_resets_the_backoff(claimed_client):
    backoff = claimed_client.app.state.login_backoff
    for _ in range(4):
        claimed_client.post("/api/v1/auth/login", json={"username": "admin", "password": "x" * 10}, headers=ORIGIN)
    claimed_client.post("/api/v1/auth/login", json={"username": "admin", "password": ADMIN[1]}, headers=ORIGIN)
    assert len(backoff) == 0


def test_a_login_counts_as_a_failure_while_its_password_is_checked(claimed_client, monkeypatch):
    """So parallel guesses can't all pass the backoff check during argon2's verify."""
    backoff = claimed_client.app.state.login_backoff
    keys_during_check = []
    real = Users.authenticate

    def spy(self, username, password):
        keys_during_check.append(len(backoff))
        return real(self, username, password)

    monkeypatch.setattr(Users, "authenticate", spy)
    r = claimed_client.post("/api/v1/auth/login", json={"username": "admin", "password": ADMIN[1]}, headers=ORIGIN)
    assert r.status_code == 200
    assert keys_during_check == [2] and len(backoff) == 0  # the IP and user keys, then forgiven


def test_login_on_an_unclaimed_device_is_409(client):
    r = client.post("/api/v1/auth/login", json={"username": "admin", "password": ADMIN[1]}, headers=ORIGIN)
    assert r.status_code == 409 and r.json()["error"]["code"] == "not_claimed"


def test_logout_clears_the_cookie_and_get_logout_redirects(claimed_client, login):
    login(claimed_client, *ADMIN)
    r = claimed_client.post("/api/v1/auth/logout", headers=ORIGIN, json={})
    assert r.status_code == 204 and f'{COOKIE_NAME}=""' in r.headers["set-cookie"]
    assert verify(claimed_client).status_code == 401

    login(claimed_client, *ADMIN)
    r = claimed_client.get("/logout", follow_redirects=False)
    assert (r.status_code, r.headers["location"]) == (302, "/login")
    assert f'{COOKIE_NAME}=""' in r.headers["set-cookie"]
    assert verify(claimed_client).status_code == 401


def test_logout_everywhere_invalidates_the_other_session(claimed_client, login):
    second = other_client(claimed_client)
    login(claimed_client, *ADMIN)
    login(second, *ADMIN)
    assert verify(second).status_code == 200
    r = claimed_client.post("/api/v1/auth/logout-everywhere", headers=ORIGIN, json={})
    assert r.status_code == 204
    assert verify(second).status_code == 401
    assert verify(claimed_client).status_code == 401


def test_logout_everywhere_needs_a_session(claimed_client):
    r = claimed_client.post("/api/v1/auth/logout-everywhere", headers=ORIGIN, json={})
    assert r.status_code == 401 and r.json()["error"]["code"] == "unauthenticated"


def test_session_is_never_401_on_an_unclaimed_device(client):
    r = client.get("/api/v1/auth/session")
    assert r.status_code == 200 and r.json() == {"claimed": False, "eula_accepted": False, "user": None}


def test_session_is_never_401_without_a_login(claimed_client):
    r = claimed_client.get("/api/v1/auth/session")
    assert r.status_code == 200 and r.json() == {"claimed": True, "eula_accepted": True, "user": None}
    claimed_client.cookies.set(COOKIE_NAME, "garbage")
    assert claimed_client.get("/api/v1/auth/session").json()["user"] is None


def issue_old_cookie(client, days=2):
    """A valid cookie for the admin, issued `days` ago."""
    app = client.app
    admin = Users(app.state.state).by_username("admin")
    return app.state.sessions.issue(admin.id, admin.session_epoch, now=time.time() - days * 86400)


def test_old_cookie_is_refreshed(claimed_client):
    claimed_client.cookies.set(COOKIE_NAME, issue_old_cookie(claimed_client))
    r = verify(claimed_client)
    assert r.status_code == 200
    (cookie,) = set_cookie_headers(r)
    assert cookie.startswith(f"{COOKIE_NAME}=") and f"Max-Age={MAX_AGE}" in cookie
    new = cookie.split(";")[0].split("=", 1)[1]
    assert claimed_client.app.state.sessions.load(new).iat >= int(time.time()) - 5


def test_expired_cookie_is_401(claimed_client):
    claimed_client.cookies.set(COOKIE_NAME, issue_old_cookie(claimed_client, days=8))
    assert verify(claimed_client).status_code == 401


@pytest.fixture
def probe_client(settings, monkeypatch):
    """An app with a route behind current_user and one behind require_admin, beside the real modules."""
    router = APIRouter()

    @router.get("/me")
    def me(user=Depends(current_user)):
        return {"username": user.username}

    @router.get("/admin-only")
    def admin_only(user=Depends(require_admin)):
        return {"username": user.username}

    monkeypatch.setattr("tm_control.modules.MODULES", [*MODULES, Module("probe", router)])
    client = TestClient(create_app(settings), base_url=BASE)
    Device(client.app.state.state).claim(*ADMIN, client.app.state.eula.version)
    return client


def test_current_user_needs_a_session_and_refreshes_an_old_cookie(probe_client, login):
    r = probe_client.get("/api/v1/me")
    assert r.status_code == 401 and r.json()["error"]["code"] == "unauthenticated"

    probe_client.cookies.set(COOKIE_NAME, issue_old_cookie(probe_client))
    r = probe_client.get("/api/v1/me")
    assert r.status_code == 200 and r.json() == {"username": "admin"}
    (cookie,) = set_cookie_headers(r)
    assert cookie.startswith(f"{COOKIE_NAME}=")

    login(probe_client, *ADMIN)
    assert set_cookie_headers(probe_client.get("/api/v1/me")) == []


def test_require_admin_refuses_viewers(probe_client, login):
    add_viewer(probe_client)
    login(probe_client, *VIEWER)
    r = probe_client.get("/api/v1/admin-only")
    assert r.status_code == 403 and r.json()["error"]["code"] == "forbidden"
    login(probe_client, *ADMIN)
    assert probe_client.get("/api/v1/admin-only").status_code == 200
