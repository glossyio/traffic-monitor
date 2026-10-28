import sqlite3

import pytest

from tm_control.core.auth import COOKIE_NAME, Device, SetupCode, Users
from tm_control.modules import MODULES

ORIGIN = {"Origin": "http://tm-test.local"}
CLAIM = "/api/v1/setup/claim"
ADMIN = ("admin", "correct horse 1")


def claim_body(code, **changes):
    return {"setup_code": code, "username": "owner", "password": "owner pass 12", "eula_version": "1", **changes}


def wrong_code(code):
    return "ZZZZ-ZZZZ" if code != "ZZZZ-ZZZZ" else "YYYY-YYYY"


def audit_rows(settings):
    con = sqlite3.connect(settings.state_dir / "state.sqlite")
    try:
        return con.execute("SELECT user_id, action, detail FROM audit ORDER BY id").fetchall()
    finally:
        con.close()


def test_setup_and_account_modules_are_registered():
    assert {"setup", "account"} <= {m.id for m in MODULES}


def test_status_and_eula_are_open(client):
    r = client.get("/api/v1/setup/status")
    assert r.status_code == 200 and r.json() == {"claimed": False, "eula": {"version": "1", "accepted": False}}
    r = client.get("/api/v1/setup/eula")
    assert r.status_code == 200 and r.json()["version"] == "1" and "placeholder" in r.json()["markdown"]


def test_claim_with_the_right_code_creates_the_admin_and_logs_in(client, setup_code):
    r = client.post(CLAIM, json=claim_body(setup_code), headers=ORIGIN)
    assert r.status_code == 201, r.text
    assert r.json()["user"]["role"] == "admin" and r.json()["user"]["username"] == "owner"
    assert set(r.json()["user"]) == {"id", "username", "role", "created_at"}
    assert COOKIE_NAME in r.cookies
    assert client.get("/api/v1/setup/status").json() == {"claimed": True, "eula": {"version": "1", "accepted": True}}
    assert client.get("/api/v1/auth/session").json()["user"]["username"] == "owner"
    assert Device(client.app.state.state).setup_code_hash() is None  # the code works once


def test_claim_accepts_the_code_in_lowercase_without_the_dash(client, setup_code):
    r = client.post(CLAIM, json=claim_body(setup_code.replace("-", "").lower()), headers=ORIGIN)
    assert r.status_code == 201


def test_claim_with_a_wrong_code_is_403_and_backs_off(client, setup_code):
    for _ in range(5):
        r = client.post(CLAIM, json=claim_body(wrong_code(setup_code)), headers=ORIGIN)
        assert r.status_code == 403 and r.json()["error"]["code"] == "invalid_setup_code"
    r = client.post(CLAIM, json=claim_body(setup_code), headers=ORIGIN)
    assert r.status_code == 429 and r.json()["error"]["code"] == "rate_limited"
    assert int(r.headers["Retry-After"]) >= 1
    assert not Device(client.app.state.state).is_claimed()


def test_a_claim_counts_as_a_failure_while_its_code_is_checked(client, setup_code, monkeypatch):
    """So parallel guesses can't all pass the backoff check during argon2's verify."""
    backoff = client.app.state.claim_backoff
    keys_during_check = []
    real = SetupCode.verify_code

    def spy(hash, code):
        keys_during_check.append(len(backoff))
        return real(hash, code)

    monkeypatch.setattr(SetupCode, "verify_code", staticmethod(spy))
    assert client.post(CLAIM, json=claim_body(setup_code), headers=ORIGIN).status_code == 201
    assert keys_during_check == [1] and len(backoff) == 0  # the IP key, then forgiven


def test_claim_failures_do_not_hold_up_logins(client, setup_code):
    for _ in range(5):
        client.post(CLAIM, json=claim_body(wrong_code(setup_code)), headers=ORIGIN)
    assert len(client.app.state.login_backoff) == 0


def test_claim_twice_is_409(client, setup_code):
    assert client.post(CLAIM, json=claim_body(setup_code), headers=ORIGIN).status_code == 201
    r = client.post(CLAIM, json=claim_body(setup_code, username="second"), headers=ORIGIN)
    assert r.status_code == 409 and r.json()["error"]["code"] == "already_claimed"
    assert [u.username for u in Users(client.app.state.state).list()] == ["owner"]


def test_claim_requires_the_current_eula_version(client, setup_code):
    r = client.post(CLAIM, json=claim_body(setup_code, eula_version="0"), headers=ORIGIN)
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation"
    assert not Device(client.app.state.state).is_claimed()


@pytest.mark.parametrize("changes", [{"username": "x"}, {"username": "has space"}, {"password": "short"}])
def test_claim_enforces_username_and_password_rules(client, setup_code, changes):
    r = client.post(CLAIM, json=claim_body(setup_code, **changes), headers=ORIGIN)
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation"
    assert not Device(client.app.state.state).is_claimed()
    assert len(client.app.state.claim_backoff) == 0  # a rule break isn't a guess


def test_claim_on_a_device_without_a_code_is_403(client):
    r = client.post(CLAIM, json=claim_body("ABCD-EFGH"), headers=ORIGIN)
    assert r.status_code == 403 and r.json()["error"]["code"] == "invalid_setup_code"


def test_claim_never_logs_the_code_or_password(client, setup_code, caplog):
    caplog.set_level("DEBUG")
    client.post(CLAIM, json=claim_body(wrong_code(setup_code)), headers=ORIGIN)
    client.post(CLAIM, json=claim_body(setup_code), headers=ORIGIN)
    for secret in (wrong_code(setup_code), setup_code, "owner pass 12"):
        assert secret not in caplog.text


def test_eula_accept_is_admin_only_and_needs_the_current_version(claimed_client, login, settings):
    url = "/api/v1/setup/eula/accept"
    r = claimed_client.post(url, json={"version": "1"}, headers=ORIGIN)
    assert r.status_code == 401
    Users(claimed_client.app.state.state).create("viewer", "viewer pass 1", "viewer")
    login(claimed_client, "viewer", "viewer pass 1")
    r = claimed_client.post(url, json={"version": "1"}, headers=ORIGIN)
    assert r.status_code == 403 and r.json()["error"]["code"] == "forbidden"
    login(claimed_client, *ADMIN)
    r = claimed_client.post(url, json={"version": "0"}, headers=ORIGIN)
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation"
    r = claimed_client.post(url, json={"version": "1"}, headers=ORIGIN)
    assert r.status_code == 204
    admin = Users(claimed_client.app.state.state).by_username("admin")
    assert (admin.id, "eula.accept", "1") in audit_rows(settings)


def test_audit_records_the_claim(client, setup_code, settings):
    r = client.post(CLAIM, json=claim_body(setup_code), headers=ORIGIN)
    assert [row[:2] for row in audit_rows(settings)] == [(r.json()["user"]["id"], "claim")]
