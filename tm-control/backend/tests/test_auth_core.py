import base64
import hashlib
import hmac
import json
import re
import sqlite3

import pytest

from tm_control.core import auth
from tm_control.core.auth import (
    Audit,
    Backoff,
    Device,
    NodeRedToken,
    SessionClaims,
    Sessions,
    SetupCode,
    Users,
    check_password_rules,
    check_username_rules,
    hash_password,
    verify_password,
)
from tm_control.core.errors import ApiError
from tm_control.core.state import State
from tm_control.modules.setup.eula import load_eula

ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


@pytest.fixture
def state(settings):
    settings.state_dir.mkdir(parents=True)
    state = State(settings.state_dir / "state.sqlite")
    state.migrate()
    return state


def test_password_hash_is_argon2id_and_verifies():
    h = hash_password("correct horse 1")
    assert h.startswith("$argon2id$")
    assert verify_password(h, "correct horse 1") and not verify_password(h, "x")


def test_verify_password_is_false_for_a_broken_hash():
    assert not verify_password("not-a-hash", "correct horse 1")


@pytest.mark.parametrize("bad", ["short", "a" * 9, "a" * 257])
def test_password_rules(bad):
    with pytest.raises(ApiError) as e:
        check_password_rules(bad)
    assert e.value.status == 422 and e.value.code == "validation"


@pytest.mark.parametrize("good", ["a" * 10, "a" * 256, "correct horse 1"])
def test_password_rules_accept_10_to_256_characters(good):
    check_password_rules(good)


@pytest.mark.parametrize("bad", ["ab", "Has Space", "x" * 33, "ädmin", "a/b", ""])
def test_username_rules(bad):
    with pytest.raises(ApiError) as e:
        check_username_rules(bad)
    assert e.value.status == 422 and e.value.code == "validation"


@pytest.mark.parametrize("good", ["abc", "x" * 32, "pi.user_1-a", "Admin"])
def test_username_rules_accept_the_lowercased_form(good):
    check_username_rules(good)


def test_mixed_case_username_is_stored_lowercased(state):
    user = Users(state).create("Admin", "correct horse 1", "admin")
    assert user.username == "admin"
    assert Users(state).by_username("ADMIN").id == user.id


def test_session_round_trip_and_epoch():
    s = Sessions("k")
    c = s.issue(7, 2, now=1000)
    assert s.load(c, now=1000) == SessionClaims(uid=7, epoch=2, iat=1000)


def test_session_expires_after_seven_days():
    s = Sessions("k")
    c = s.issue(7, 2, now=1000)
    assert s.load(c, now=1000 + 7 * 86400) is not None
    assert s.load(c, now=1000 + 7 * 86400 + 1) is None


def test_session_refresh_after_a_day():
    s = Sessions("k")
    claims = s.load(s.issue(7, 2, now=1000), now=1000)
    assert not s.needs_refresh(claims, now=1000 + 3600)
    assert s.needs_refresh(claims, now=1000 + 86401)


def test_tampered_or_foreign_session_is_rejected():
    s = Sessions("k")
    c = s.issue(7, 2, now=1000)
    assert Sessions("other").load(c, now=1000) is None
    tampered = c[:-2] + ("zz" if not c.endswith("zz") else "yy")
    assert s.load(tampered, now=1000) is None
    assert s.load("", now=1000) is None and s.load("garbage", now=1000) is None


def test_node_red_token_matches_the_javascript_verifier():
    t = NodeRedToken("key").mint("admin", "admin", now=1_700_000_000)
    body, sig = t.split(".")
    assert "=" not in t
    assert json.loads(base64.urlsafe_b64decode(body + "==")) == {"u": "admin", "r": "admin", "exp": 1_700_000_300}
    expected = hmac.new(b"key", body.encode(), hashlib.sha256).digest()
    assert sig == base64.urlsafe_b64encode(expected).rstrip(b"=").decode()


def test_node_red_token_rejects_expired_and_tampered():
    tokens = NodeRedToken("key")
    t = tokens.mint("admin", "admin", now=1000, ttl=300)
    assert tokens.verify(t, now=1299) == {"u": "admin", "r": "admin", "exp": 1300}
    assert tokens.verify(t, now=1300) is None
    assert NodeRedToken("other").verify(t, now=1000) is None
    body, sig = t.split(".")
    forged = base64.urlsafe_b64encode(b'{"u":"admin","r":"admin","exp":9999999999}').rstrip(b"=").decode()
    assert tokens.verify(f"{forged}.{sig}", now=1000) is None
    assert tokens.verify("no-dot", now=1000) is None and tokens.verify("", now=1000) is None


def test_backoff_schedule():
    b = Backoff()
    for _ in range(4):
        b.record_failure("k", now=0)
    assert b.check("k", now=0) == 0
    b.record_failure("k", now=0)
    assert b.check("k", now=0) == 2.0
    b.record_failure("k", now=0)
    assert b.check("k", now=0) == 4.0
    assert b.check("k", now=1) == 3.0
    assert b.check("k", now=1000) == 0
    assert b.check("other", now=0) == 0


def test_backoff_caps_at_five_minutes():
    b = Backoff()
    for _ in range(30):
        b.record_failure("k", now=0)
    assert b.check("k", now=0) == 300.0


def test_backoff_survives_a_huge_failure_count():
    b = Backoff()
    for _ in range(2000):  # 2.0 ** 1996 would overflow a float
        b.record_failure("k", now=0)
    assert b.check("k", now=0) == 300.0


def test_backoff_forgets_a_key_15_minutes_after_its_last_failure():
    b = Backoff()
    for _ in range(10):
        b.record_failure("k", now=0)
    b.record_failure("k", now=900)  # the old failures are forgotten, so this one starts a new count
    assert b.check("k", now=900) == 0
    for _ in range(4):
        b.record_failure("k", now=900)
    assert b.check("k", now=900) == 2.0


def test_backoff_prunes_old_keys_when_recording():
    b = Backoff()
    for n in range(100):
        b.record_failure(f"user:{n}", now=0)
    b.record_failure("user:new", now=901)
    assert len(b) == 1


def test_backoff_reset():
    b = Backoff()
    for _ in range(6):
        b.record_failure("k", now=0)
    b.reset("k")
    assert b.check("k", now=0) == 0
    b.reset("never-seen")


def test_setup_code_format_and_alphabet():
    for _ in range(20):
        c = SetupCode.generate()
        assert re.fullmatch(rf"[{ALPHABET}]{{4}}-[{ALPHABET}]{{4}}", c)


def test_setup_code_normalizes_before_verifying():
    h = SetupCode.hash_code("ABCD-EFGH")
    assert h.startswith("$argon2id$")
    assert SetupCode.normalize(" abcd efgh ") == "ABCDEFGH"
    assert SetupCode.verify_code(h, " abcd efgh ") and SetupCode.verify_code(h, "abcdefgh")
    assert not SetupCode.verify_code(h, "ABCD-EFGJ")


def test_claim_creates_the_admin_and_records_the_eula_in_one_step(state):
    device = Device(state)
    device.set_setup_code_hash(SetupCode.hash_code("ABCD-EFGH"))
    assert not device.is_claimed() and device.setup_code_hash() is not None
    user = device.claim("admin", "correct horse 1", "1", now=1_700_000_000)
    assert user.role == "admin" and user.username == "admin"
    assert device.is_claimed() and device.eula_accepted("1") and not device.eula_accepted("2")
    assert device.setup_code_hash() is None
    con = sqlite3.connect(state.path)
    assert con.execute("SELECT value FROM device WHERE key = 'claimed_at'").fetchone() is not None


def test_claim_twice_is_refused_and_changes_nothing(state):
    device = Device(state)
    device.claim("admin", "correct horse 1", "1")
    with pytest.raises(ApiError) as e:
        device.claim("other", "correct horse 2", "1")
    assert e.value.status == 409 and e.value.code == "already_claimed"
    assert [u.username for u in Users(state).list()] == ["admin"]


def test_claim_checks_the_rules_before_writing(state):
    device = Device(state)
    with pytest.raises(ApiError):
        device.claim("admin", "short", "1")
    with pytest.raises(ApiError):
        device.claim("a b", "correct horse 1", "1")
    assert not device.is_claimed() and not device.eula_accepted("1")


def test_unclaim_removes_every_user_and_sets_a_new_code(state):
    device = Device(state)
    admin = device.claim("admin", "correct horse 1", "1")
    Users(state).create("viewer", "viewer pass 1", "viewer")
    device.unclaim(SetupCode.hash_code("WXYZ-2345"))
    assert not device.is_claimed() and Users(state).list() == []
    assert Users(state).get(admin.id) is None
    assert SetupCode.verify_code(device.setup_code_hash(), "WXYZ-2345")
    con = sqlite3.connect(state.path)
    assert con.execute("SELECT value FROM device WHERE key = 'claimed_at'").fetchone() is None


def test_set_password_bumps_the_epoch(state):
    users = Users(state)
    user = users.create("viewer", "viewer pass 1", "viewer")
    first = user.session_epoch
    users.set_password(user.id, "viewer pass 2")
    assert users.get(user.id).session_epoch == first + 1
    assert users.authenticate("viewer", "viewer pass 2").id == user.id
    assert users.authenticate("viewer", "viewer pass 1") is None
    users.bump_epoch(user.id)
    assert users.get(user.id).session_epoch == first + 2


def test_set_password_checks_the_rules(state):
    users = Users(state)
    user = users.create("viewer", "viewer pass 1", "viewer")
    with pytest.raises(ApiError):
        users.set_password(user.id, "short")
    assert users.get(user.id).session_epoch == user.session_epoch


def test_user_ids_are_never_reused(state):
    users = Users(state)
    users.create("first", "first pass 1", "admin")
    second = users.create("second", "second pass 1", "viewer")
    users.delete(second.id)
    assert users.create("third", "third pass 1", "viewer").id > second.id
    Device(state).unclaim(SetupCode.hash_code("WXYZ-2345"))  # deletes every user
    assert Device(state).claim("owner", "owner pass 12", "1").id > second.id + 1


def test_new_users_start_at_a_random_epoch(state):
    users = Users(state)
    epochs = {users.create(f"user{n}", "user pass 12", "viewer").session_epoch for n in range(4)}
    assert len(epochs) == 4 and all(0 <= e < 2**62 for e in epochs)
    assert Device(state).claim("owner", "owner pass 12", "1").session_epoch not in epochs


def test_users_create_list_count_and_delete(state):
    users = Users(state)
    admin = users.create("admin", "correct horse 1", "admin")
    viewer = users.create("viewer", "viewer pass 1", "viewer")
    assert users.count_admins() == 1
    assert [u.username for u in users.list()] == ["admin", "viewer"]
    with pytest.raises(ApiError) as e:
        users.create("VIEWER", "viewer pass 1", "viewer")
    assert e.value.status == 409 and e.value.code == "conflict"
    users.delete(viewer.id)
    assert users.get(viewer.id) is None and users.get(admin.id) is not None
    with pytest.raises(ValueError):
        users.create("other", "correct horse 1", "root")


def test_unknown_user_ids_are_not_found(state):
    users = Users(state)
    for call in (lambda: users.delete(99), lambda: users.bump_epoch(99), lambda: users.set_password(99, "a" * 10)):
        with pytest.raises(ApiError) as e:
            call()
        assert e.value.status == 404 and e.value.code == "not_found"


def test_authenticate_is_case_insensitive_and_none_for_unknown_users(state):
    users = Users(state)
    users.create("admin", "correct horse 1", "admin")
    assert users.authenticate("ADMIN", "correct horse 1").username == "admin"
    assert users.authenticate("nobody", "correct horse 1") is None


def test_an_unknown_username_still_costs_one_password_verify(state, monkeypatch):
    calls = []
    real = auth.verify_password
    monkeypatch.setattr(auth, "verify_password", lambda h, p: calls.append(h) or real(h, p))
    assert Users(state).authenticate("nobody", "correct horse 1") is None
    assert len(calls) == 1 and calls[0].startswith("$argon2id$")


def test_eula_acceptance_is_kept_when_its_user_is_deleted(state):
    device = Device(state)
    users = Users(state)
    viewer = users.create("viewer", "viewer pass 1", "viewer")
    device.accept_eula("3", viewer.id)
    users.delete(viewer.id)
    assert device.eula_accepted("3")


def test_audit_records_rows(state):
    Audit(state).record(None, "reset-admin")
    Audit(state).record(1, "user.create", "viewer")
    con = sqlite3.connect(state.path)
    rows = con.execute("SELECT user_id, action, detail FROM audit ORDER BY id").fetchall()
    assert rows == [(None, "reset-admin", None), (1, "user.create", "viewer")]


def test_load_eula_reads_the_version(tmp_path, settings):
    eula = load_eula(settings.eula_path)
    assert eula.version == "1" and "placeholder" in eula.markdown
    path = tmp_path / "EULA.md"
    path.write_text("<!-- eula-version: 2026.1 -->\n# Terms\n\nText.\n", encoding="utf-8")
    assert load_eula(path).version == "2026.1"
    assert load_eula(path).markdown.startswith("# Terms")


def test_load_eula_without_the_version_line_raises(tmp_path):
    path = tmp_path / "EULA.md"
    path.write_text("# Terms\n\n<!-- eula-version: 1 -->\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_eula(path)
