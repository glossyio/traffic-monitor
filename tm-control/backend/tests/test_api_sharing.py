"""The Sharing page's API: /api/v1/sharing (what the unit uploads, where, and what the owner agreed to).

claimed_client runs in fake mode: its config.yml is the seeded copy of fixtures/node_red_config_ok.yml, whose upload
is off and goes to tb.example.invalid, which the fixture manifest names as the maintainer's server. Its Node-RED is
fake.FakeNodeRed, whose status reports an accepted upload a minute ago while the upload is on. The token is the fake
secrets' `entered` value. Nothing here logs or audits a host, a token, or a notice version
(test_the_audit_row_names_fields_only, test_no_host_or_token_in_any_log_line).
"""

import dataclasses
import importlib
import logging
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from ruamel.yaml import YAML

from tm_control.adapters.nodered import NodeRedError
from tm_control.core.auth import Users
from tm_control.core.secrets import THINGSBOARD_ACCESS_TOKEN
from tm_control.modules.sharing import follow
from tm_control.modules.sharing.consents import MAINTAINER, OWN_SERVER, Consents

BASE = "http://tm-test.local"
ORIGIN = {"Origin": BASE}
JSON_HEADERS = {**ORIGIN, "Content-Type": "application/json"}  # the cross-site check wants JSON on every non-GET
ADMIN = ("admin", "correct horse 1")
VIEWER = ("viewer", "viewer pass 1")
MAINTAINER_HOST = "tb.example.invalid"  # the fixture manifest's maintainer_host
OTHER = "other.example.invalid"
TOKEN = "tb-placeholder-0001"
CHANGED_NOTE = "the server changed"
OFF_NOTE = "the upload was off in config.yml"  # follow's, for a hand edit


@pytest.fixture
def admin(claimed_client, login):
    login(claimed_client, *ADMIN)
    return claimed_client


@pytest.fixture
def viewer_login(claimed_client, login):
    """Log the client in as a viewer (created on first use); log in as the admin again with login(client, *ADMIN)."""
    users = Users(claimed_client.app.state.state)

    def as_viewer():
        if users.by_username(VIEWER[0]) is None:
            users.create(*VIEWER, "viewer")
        login(claimed_client, *VIEWER)

    return as_viewer


def notice(client) -> str:
    return client.app.state.notice.version


def admin_id(client) -> int:
    return Users(client.app.state.state).by_username(ADMIN[0]).id


def set_token(client, value=TOKEN):
    client.app.state.secrets.entered[THINGSBOARD_ACCESS_TOKEN] = value


def body(client, **changes) -> dict:
    """A valid save for the maintainer's server with the upload on, changed by `changes`."""
    base = {
        "target": "maintainer", "host": None, "protocol": "https", "port": None, "enabled": True,
        "exact_location": False, "public_map": "none", "notice_version": notice(client),
    }
    return {**base, **changes}


def put(client, **changes):
    return client.put("/api/v1/sharing", json=body(client, **changes), headers=ORIGIN)


def get(client) -> dict:
    r = client.get("/api/v1/sharing")
    assert r.status_code == 200, r.text
    return r.json()


def rows(client) -> list[tuple]:
    con = client.app.state.state.connect()
    try:
        return [tuple(row) for row in con.execute(
            "SELECT target, consent, granted, notice_version, user_id, note FROM sharing_consents ORDER BY id"
        )]
    finally:
        con.close()


def audit_rows(client) -> list[tuple]:
    con = client.app.state.state.connect()
    try:
        return [tuple(row) for row in con.execute(
            "SELECT action, detail FROM audit WHERE action LIKE 'sharing.%' ORDER BY id"
        )]
    finally:
        con.close()


def file_data(client) -> dict:
    return YAML(typ="safe", pure=True).load(client.app.state.config_path.read_text())


def backups(client) -> list:
    path = client.app.state.config_path
    return sorted(path.parent.glob(f"{path.name}.*.bak"))


def error(r, status: int, code: str) -> dict:
    assert r.status_code == status, r.text
    found = r.json()["error"]
    assert found["code"] == code, found
    return found


def map_live(client, live: bool = True) -> None:
    manifest = client.app.state.manifest
    sharing = dataclasses.replace(manifest.sharing, public_map_live=live)
    client.app.state.manifest = manifest.model_copy(update={"sharing": sharing})


# Who may do what


def test_sharing_needs_a_login_and_put_needs_an_admin(claimed_client, viewer_login, login):
    client = claimed_client
    assert client.get("/api/v1/sharing").status_code == 401
    assert client.get("/api/v1/sharing/notice").status_code == 401
    assert client.put("/api/v1/sharing", json=body(client), headers=ORIGIN).status_code == 401
    assert client.post("/api/v1/sharing/reviewed", headers=JSON_HEADERS).status_code == 401

    viewer_login()
    state = get(client)
    assert state["writable"] is False
    assert state["token"] is None
    assert client.get("/api/v1/sharing/notice").status_code == 200
    error(client.put("/api/v1/sharing", json=body(client), headers=ORIGIN), 403, "forbidden")
    error(client.post("/api/v1/sharing/reviewed", headers=JSON_HEADERS), 403, "forbidden")

    login(client, *ADMIN)
    state = get(client)
    assert state["writable"] is True
    assert state["token"]["name"] == THINGSBOARD_ACCESS_TOKEN
    assert state["token"]["set"] is False


def test_a_viewer_never_sees_an_own_servers_host(admin, viewer_login, login):
    set_token(admin)
    viewer_login()
    state = get(admin)
    assert state["target"] == "maintainer"
    assert state["host"] == MAINTAINER_HOST  # the maintainer's server isn't the operator's

    login(admin, *ADMIN)
    assert put(admin, target="own", host=OTHER).status_code == 200
    viewer_login()
    r = admin.get("/api/v1/sharing")
    assert r.status_code == 200
    state = r.json()
    assert state["target"] == "own"
    assert state["host"] is None
    assert state["token"] is None
    assert state["maintainer_host"] == MAINTAINER_HOST
    assert OTHER not in r.text
    assert TOKEN not in r.text


def test_the_notice_is_served(admin):
    r = admin.get("/api/v1/sharing/notice")
    assert r.status_code == 200
    assert r.json() == {"version": notice(admin), "markdown": admin.app.state.notice.markdown}


# What a save does


def test_a_new_unit_shares_nothing(admin):
    state = get(admin)
    assert state["enabled"] is False
    assert state["target"] == "maintainer"  # the fixture's host is the manifest's maintainer_host
    for name in ("share_data", "exact_location", "public_map"):
        assert state[name] == {"granted": False, "at": None, "notice_version": None}
    assert state["notice_version"] == notice(admin)
    assert state["notice_current"] is False
    assert state["review_needed"] is False
    assert state["public_map_live"] is False
    assert state["has_location"] is True
    assert state["precision"] == "2"
    assert state["server"] == {"state": "off", "at": None}
    assert rows(admin) == []


def test_a_place_with_no_point_has_no_location(admin):
    path = admin.app.state.config_path
    text = path.read_text()
    assert "    lat: 45.0\n    lon: -122.0\n" in text
    path.write_text(text.replace("    lat: 45.0\n    lon: -122.0\n", "    lat:\n    lon:\n", 1))
    assert get(admin)["has_location"] is False


def test_turning_on_needs_a_token(admin):
    found = error(put(admin), 409, "no_token")
    assert found["message"] == "Set the access token first."
    assert rows(admin) == []
    assert file_data(admin)["thingsboard"]["enabled"] is False


def test_turning_on_records_share_data_under_the_notice_version(admin):
    set_token(admin)
    r = put(admin)
    assert r.status_code == 200, r.text
    state = r.json()
    assert state["enabled"] is True
    assert state["share_data"]["granted"] is True
    assert state["share_data"]["notice_version"] == notice(admin)
    assert state["notice_current"] is True
    assert state["token"]["set"] is True
    assert rows(admin) == [(MAINTAINER, "share_data", 1, notice(admin), admin_id(admin), None)]
    data = file_data(admin)
    assert data["thingsboard"]["enabled"] is True
    assert data["thingsboard"]["host"] == MAINTAINER_HOST
    assert data["thingsboard"]["protocol"] == "https"
    assert "port" not in data["thingsboard"]
    assert data["sharing"] == {
        "target": "maintainer", "host": MAINTAINER_HOST, "exact_location": False, "public_map": "none",
        "notice_version": notice(admin),
    }


def test_turning_off_withdraws_share_data_and_needs_no_notice(admin):
    set_token(admin)
    assert put(admin, exact_location=True).status_code == 200
    r = put(admin, enabled=False, exact_location=False, notice_version=None)
    assert r.status_code == 200, r.text
    state = r.json()
    assert state["enabled"] is False
    assert state["share_data"]["granted"] is False
    assert state["exact_location"]["granted"] is False
    assert rows(admin)[-2:] == [
        (MAINTAINER, "share_data", 0, notice(admin), admin_id(admin), None),
        (MAINTAINER, "exact_location", 0, notice(admin), admin_id(admin), None),
    ]
    data = file_data(admin)
    assert data["thingsboard"]["enabled"] is False
    assert data["sharing"]["exact_location"] is False
    assert data["sharing"]["notice_version"] is None


def test_the_exact_location_needs_https_and_the_upload_on(admin):
    set_token(admin)
    found = error(put(admin, target="own", host=OTHER, protocol="http", exact_location=True), 422, "validation")
    assert found["message"] == "The exact location is only sent over https."
    assert found["detail"] == {"field": "exact_location"}
    found = error(put(admin, enabled=False, exact_location=True), 422, "validation")
    assert found["detail"] == {"field": "exact_location"}
    found = error(put(admin, enabled=False, public_map="rounded_point"), 422, "validation")
    assert found["detail"] == {"field": "public_map"}
    assert rows(admin) == []


def test_exact_location_is_recorded_and_written(admin):
    set_token(admin)
    r = put(admin, exact_location=True)
    assert r.status_code == 200, r.text
    assert r.json()["exact_location"]["granted"] is True
    assert (MAINTAINER, "exact_location", 1, notice(admin), admin_id(admin), None) in rows(admin)
    assert file_data(admin)["sharing"]["exact_location"] is True

    r = put(admin, exact_location=False)
    assert r.status_code == 200, r.text
    assert r.json()["exact_location"]["granted"] is False
    assert rows(admin)[-1] == (MAINTAINER, "exact_location", 0, notice(admin), admin_id(admin), None)
    assert file_data(admin)["sharing"]["exact_location"] is False


def test_the_map_is_refused_until_it_is_live(admin):
    set_token(admin)
    error(put(admin, public_map="rounded_point"), 409, "map_not_live")
    assert rows(admin) == []
    map_live(admin)
    r = put(admin, public_map="rounded_point")
    assert r.status_code == 200, r.text
    assert r.json()["public_map"]["granted"] is True
    assert r.json()["public_map_live"] is True
    assert (MAINTAINER, "public_map", 1, notice(admin), admin_id(admin), None) in rows(admin)
    assert file_data(admin)["sharing"]["public_map"] == "rounded_point"
    error(put(admin, target="own", host=OTHER, public_map="rounded_point"), 409, "map_not_live")


def test_an_old_notice_version_is_refused(admin):
    set_token(admin)
    for version in ("2000-01", None):
        found = error(put(admin, notice_version=version), 422, "validation")
        assert found["message"] == "That isn't the current notice. Reload the page to read it."
        assert found["detail"] == {"field": "notice_version"}
    assert rows(admin) == []
    assert file_data(admin)["thingsboard"]["enabled"] is False


def test_a_current_grant_needs_no_notice_version_again(admin):
    """With the notice read and the upload on, a later save (the exact location) may leave the version out."""
    set_token(admin)
    assert put(admin).status_code == 200
    r = put(admin, exact_location=True, notice_version=None)
    assert r.status_code == 200, r.text
    assert rows(admin)[-1] == (MAINTAINER, "exact_location", 1, notice(admin), admin_id(admin), None)


def test_a_new_notice_is_recorded_again(admin):
    set_token(admin)
    assert put(admin, exact_location=True).status_code == 200
    old = notice(admin)
    admin.app.state.notice = dataclasses.replace(admin.app.state.notice, version="2099-01")
    state = get(admin)
    assert state["notice_current"] is False
    assert state["notice_version"] == "2099-01"
    r = put(admin, exact_location=True)
    assert r.status_code == 200, r.text
    assert r.json()["notice_current"] is True
    assert rows(admin)[-2:] == [
        (MAINTAINER, "share_data", 1, "2099-01", admin_id(admin), None),
        (MAINTAINER, "exact_location", 1, "2099-01", admin_id(admin), None),
    ]
    assert old != "2099-01"
    assert file_data(admin)["sharing"]["notice_version"] == "2099-01"


def stale_notice(admin) -> str:
    """Share data and the exact location granted under the current notice, then a new notice published; returns the
    version they were granted under."""
    set_token(admin)
    assert put(admin, exact_location=True).status_code == 200
    old = notice(admin)
    admin.app.state.notice = dataclasses.replace(admin.app.state.notice, version="2099-01")
    assert get(admin)["notice_current"] is False
    return old


def test_withdrawing_under_a_stale_notice_needs_no_version_and_keeps_the_other_grants(admin):
    """A new notice asks again without pausing sharing: a save that only withdraws a choice is taken without the
    version, records only the withdrawal, and leaves Share data under the notice it was given under."""
    old = stale_notice(admin)
    count = len(rows(admin))
    r = put(admin, exact_location=False, notice_version=None)
    assert r.status_code == 200, r.text
    assert rows(admin)[count:] == [(MAINTAINER, "exact_location", 0, old, admin_id(admin), None)]
    state = r.json()
    assert state["enabled"] is True
    assert state["exact_location"]["granted"] is False
    assert state["share_data"]["notice_version"] == old
    assert state["notice_current"] is False
    assert file_data(admin)["sharing"]["notice_version"] == old


def test_keeping_the_choices_under_a_stale_notice_records_nothing(admin):
    old = stale_notice(admin)
    count = len(rows(admin))
    r = put(admin, exact_location=True, notice_version=None)
    assert r.status_code == 200, r.text
    assert rows(admin)[count:] == []
    assert r.json()["share_data"]["notice_version"] == old
    assert r.json()["notice_current"] is False


def test_granting_more_under_a_stale_notice_needs_the_current_version(admin):
    stale_notice(admin)
    assert put(admin, exact_location=False, notice_version=None).status_code == 200
    count = len(rows(admin))
    found = error(put(admin, exact_location=True, notice_version=None), 422, "validation")
    assert found["detail"] == {"field": "notice_version"}
    assert rows(admin)[count:] == []
    # With the current version the grants are recorded again under it, as before
    assert put(admin, exact_location=True).status_code == 200
    assert rows(admin)[-2:] == [
        (MAINTAINER, "share_data", 1, "2099-01", admin_id(admin), None),
        (MAINTAINER, "exact_location", 1, "2099-01", admin_id(admin), None),
    ]


def test_changing_the_server_withdraws_the_other_choices(admin):
    set_token(admin)
    assert put(admin, exact_location=True).status_code == 200
    r = put(admin, target="own", host=OTHER, notice_version=None)
    assert r.status_code == 200, r.text
    state = r.json()
    assert state["target"] == "own"
    assert state["host"] == OTHER
    assert state["exact_location"]["granted"] is False
    assert state["share_data"] == {"granted": True, "at": state["share_data"]["at"], "notice_version": OWN_SERVER}
    assert state["notice_current"] is True
    found = rows(admin)
    me = admin_id(admin)
    assert (MAINTAINER, "share_data", 0, notice(admin), me, CHANGED_NOTE) in found
    assert (MAINTAINER, "exact_location", 0, notice(admin), me, CHANGED_NOTE) in found
    assert found[-1] == (f"own:{OTHER}", "share_data", 1, OWN_SERVER, me, None)
    assert not Consents(admin.app.state.state).granted(MAINTAINER, "exact_location")
    data = file_data(admin)
    assert data["thingsboard"]["host"] == OTHER
    assert data["sharing"] == {
        "target": "own", "host": OTHER, "exact_location": False, "public_map": "none", "notice_version": OWN_SERVER,
    }


@pytest.mark.parametrize(("host", "target"), [
    ("https://x", None),
    ("a b", None),
    ("x/y", None),
    ("", None),
    (None, None),
    (OTHER, "own"),
    ("  Other.Example.INVALID ", "own"),
    (MAINTAINER_HOST, "maintainer"),
])
def test_an_own_server_host_is_validated(admin, host, target):
    set_token(admin)
    r = put(admin, target="own", host=host, protocol="http", port=8080, notice_version=notice(admin))
    if target is None:
        found = error(r, 422, "validation")
        assert found["detail"] == {"field": "host"}
        assert rows(admin) == []
        return
    assert r.status_code == 200, r.text
    state = r.json()
    assert state["target"] == target
    data = file_data(admin)["thingsboard"]
    if target == "own":
        assert state["host"] == OTHER
        assert (data["host"], data["protocol"], data["port"]) == (OTHER, "http", 8080)
    else:  # the maintainer's server: its host, https, and no port, whatever was sent
        assert state["host"] == MAINTAINER_HOST
        assert (state["protocol"], state["port"]) == ("https", None)
        assert (data["host"], data["protocol"]) == (MAINTAINER_HOST, "https")
        assert "port" not in data
        assert rows(admin)[-1][:4] == (MAINTAINER, "share_data", 1, notice(admin))


def edit_file(client, old, new):
    path = client.app.state.config_path
    text = path.read_text()
    assert old in text
    path.write_text(text.replace(old, new, 1))


def grants_since(client, count: int) -> list[tuple]:
    return [row for row in rows(client)[count:] if row[2] == 1]


def test_a_hand_edit_before_the_save_needs_the_notice_again(admin):
    """The upload turned off by hand after the page was read: a save that leaves the notice version out is judged
    against the withdrawal the follow step records, not the grant the page saw."""
    set_token(admin)
    assert put(admin).status_code == 200
    assert get(admin)["notice_current"] is True
    edit_file(admin, "thingsboard:\n    enabled: true\n", "thingsboard:\n    enabled: false\n")
    count = len(rows(admin))
    found = error(put(admin, notice_version=None), 422, "validation")
    assert found["detail"] == {"field": "notice_version"}
    assert rows(admin)[count:] == [(MAINTAINER, "share_data", 0, notice(admin), None, OFF_NOTE)]
    assert file_data(admin)["thingsboard"]["enabled"] is False


def test_a_hand_switch_to_another_server_needs_the_notice_again(admin):
    """thingsboard.host edited by hand to another server: the maintainer's grant is withdrawn before the save is
    judged, so a save for the maintainer's server that leaves the notice version out doesn't revive it."""
    set_token(admin)
    assert put(admin, exact_location=True).status_code == 200
    edit_file(admin, f"    host: {MAINTAINER_HOST}\n    protocol: https\n", f"    host: {OTHER}\n    protocol: https\n")
    count = len(rows(admin))
    error(put(admin, notice_version=None), 422, "validation")
    found = rows(admin)[count:]
    assert (MAINTAINER, "share_data", 0, notice(admin), None, "the server changed in config.yml") in found
    assert (MAINTAINER, "exact_location", 0, notice(admin), None, "the server changed in config.yml") in found
    # The follow step records the upload it found on for the other server (no user); nothing is granted for the
    # maintainer's, and nothing in the admin's name.
    assert all(row[0] != MAINTAINER and row[4] is None for row in grants_since(admin, count))
    assert not Consents(admin.app.state.state).granted(MAINTAINER, "share_data")
    assert file_data(admin)["thingsboard"]["host"] == OTHER


def test_a_grant_whose_record_failed_is_written_back(admin, monkeypatch):
    set_token(admin)
    assert put(admin).status_code == 200
    count = len(rows(admin))

    def fails(*args, **kwargs):
        raise RuntimeError("the database is locked")

    monkeypatch.setattr(Consents, "record", fails)
    client = TestClient(admin.app, base_url=BASE, raise_server_exceptions=False, cookies=dict(admin.cookies))
    r = client.put("/api/v1/sharing", json=body(admin, exact_location=True), headers=ORIGIN)
    assert r.status_code == 500
    assert r.json()["error"]["code"] == "internal"
    assert rows(admin)[count:] == []
    assert file_data(admin)["sharing"]["exact_location"] is False  # written back by the follow step
    assert file_data(admin)["thingsboard"]["enabled"] is True  # Share data is still recorded


def test_a_withdrawal_keeps_the_version_of_its_grant(admin):
    set_token(admin)
    assert put(admin, exact_location=True).status_code == 200
    old = notice(admin)
    admin.app.state.notice = dataclasses.replace(admin.app.state.notice, version="2099-01")
    assert put(admin, enabled=False, notice_version=None).status_code == 200
    assert rows(admin)[-2:] == [
        (MAINTAINER, "share_data", 0, old, admin_id(admin), None),
        (MAINTAINER, "exact_location", 0, old, admin_id(admin), None),
    ]


def test_a_changed_file_records_no_consent(admin, monkeypatch):
    sharing_router = importlib.import_module("tm_control.modules.sharing.router")
    set_token(admin)
    edit_file(admin, "thingsboard:\n    enabled: false\n", "thingsboard:\n    enabled: true\n")
    assert get(admin)["review_needed"] is True  # an upload found on
    count = len(rows(admin))
    real_load = sharing_router.load_config

    def load_then_edit(app_state):
        config = real_load(app_state)
        path = app_state.config_path
        path.write_text(path.read_text() + "# edited by hand\n")  # another edit lands after the load
        return config

    monkeypatch.setattr(sharing_router, "load_config", load_then_edit)
    error(put(admin, exact_location=True), 409, "config_changed")
    assert rows(admin)[count:] == []
    assert Consents(admin.app.state.state).review_needed() is True
    assert audit_rows(admin) == []
    assert file_data(admin)["sharing"]["exact_location"] is False


def test_a_save_leaves_nothing_for_the_follow_step_to_rewrite(admin):
    set_token(admin)
    app_state = admin.app.state
    for changes in ({}, {"exact_location": True}, {"enabled": False, "notice_version": None}):
        assert put(admin, **changes).status_code == 200
        before_rows, before_backups = rows(admin), backups(admin)
        with app_state.reconcile_lock:
            assert follow.run(app_state) is False
        assert rows(admin) == before_rows
        assert backups(admin) == before_backups


def test_reviewed_clears_the_flag(admin):
    consents = Consents(admin.app.state.state)
    edit_file(admin, "thingsboard:\n    enabled: false\n", "thingsboard:\n    enabled: true\n")
    assert get(admin)["review_needed"] is True  # an upload found on
    r = admin.post("/api/v1/sharing/reviewed", headers=JSON_HEADERS)
    assert r.status_code == 204
    assert get(admin)["review_needed"] is False
    assert audit_rows(admin) == [("sharing.reviewed", None)]
    consents.set_review_needed(True)
    set_token(admin)
    assert put(admin).status_code == 200  # a save is a review too
    assert consents.review_needed() is False


def test_an_upload_found_on_is_recorded_for_review_when_the_page_opens(admin):
    path = admin.app.state.config_path
    path.write_text(path.read_text().replace("    enabled: false\n    host:", "    enabled: true\n    host:", 1))
    state = get(admin)
    assert state["enabled"] is True
    assert state["review_needed"] is True
    assert state["share_data"]["granted"] is True
    assert state["share_data"]["notice_version"] == "pre-consent"
    assert state["notice_current"] is False


# The server's answer


def iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


NOW = datetime(2026, 11, 13, 12, 0, tzinfo=timezone.utc)


def upload(enabled=True, ok=None, failed=None, failure=None) -> dict:
    return {"upload": {
        "enabled": enabled,
        "last_ok_at": None if ok is None else iso(NOW - ok),
        "last_failure_at": None if failed is None else iso(NOW - failed),
        "last_failure": failure,
    }}


MINUTE = timedelta(minutes=1)


@pytest.mark.parametrize(("report", "state", "at"), [
    (None, "unknown", None),
    ({"status": "ok"}, "unknown", None),
    (upload(enabled=False), "off", None),
    (upload(), "waiting", None),
    (upload(ok=5 * MINUTE, failed=MINUTE, failure="refused"), "refused", MINUTE),
    (upload(failed=MINUTE, failure="unreachable"), "unreachable", MINUTE),
    (upload(ok=3 * MINUTE, failed=4 * MINUTE, failure="rejected"), "ok", 3 * MINUTE),
    (upload(ok=MINUTE, failed=2 * MINUTE, failure="server_error"), "ok", MINUTE),
    (upload(ok=MINUTE), "ok", MINUTE),
    (upload(ok=16 * MINUTE), "stale", 16 * MINUTE),
    (upload(ok=MINUTE, failed=0 * MINUTE, failure="server_error"), "server_error", 0 * MINUTE),
])
def test_server_status(report, state, at):
    from tm_control.modules.sharing.server import STALE_AFTER, server_status

    assert STALE_AFTER == 900
    found = server_status(report, NOW.timestamp())
    assert found.state == state
    if at is None:
        assert found.at is None
    else:
        assert datetime.fromisoformat(found.at) == NOW - at


def test_server_status_takes_a_time_that_does_not_parse_as_missing():
    from tm_control.modules.sharing.server import server_status

    report = {"upload": {"enabled": True, "last_ok_at": "yesterday", "last_failure_at": None, "last_failure": None}}
    assert server_status(report, NOW.timestamp()).state == "waiting"
    report["upload"]["last_ok_at"] = "2026-11-13T11:59:00Z"
    assert server_status(report, NOW.timestamp()).state == "ok"


def test_get_sharing_reports_the_server_and_survives_node_red_being_down(admin, monkeypatch):
    set_token(admin)
    assert put(admin).status_code == 200
    server = get(admin)["server"]
    assert server["state"] == "ok"  # the fake's accepted upload a minute ago
    assert server["at"] is not None

    def unreachable():
        raise NodeRedError("unreachable")

    monkeypatch.setattr(admin.app.state.nodered, "report", unreachable)
    assert get(admin)["server"] == {"state": "unknown", "at": None}


# What is recorded and logged


def test_the_audit_row_names_fields_only(admin):
    set_token(admin)
    assert put(admin).status_code == 200
    assert put(admin, exact_location=True).status_code == 200
    assert put(admin, target="own", host=OTHER, notice_version=None).status_code == 200
    found = audit_rows(admin)
    assert found == [
        ("sharing.update", "protocol,enabled"),  # the fixture's upload was http
        ("sharing.update", "exact_location"),
        ("sharing.update", "target,host,exact_location"),
    ]
    for _, detail in found:
        assert OTHER not in detail and MAINTAINER_HOST not in detail and notice(admin) not in detail


def test_no_host_or_token_in_any_log_line(admin, caplog, monkeypatch):
    caplog.set_level(logging.DEBUG)
    put(admin)  # no token yet
    set_token(admin)
    put(admin, target="own", host="https://" + OTHER)
    put(admin, target="own", host=OTHER, protocol="http", exact_location=True)
    put(admin, exact_location=True)
    put(admin, target="own", host=OTHER, notice_version=None)
    get(admin)

    def unreachable():
        raise NodeRedError("unreachable")

    monkeypatch.setattr(admin.app.state.nodered, "report", unreachable)
    get(admin)
    put(admin, enabled=False, notice_version=None)
    assert caplog.records
    for record in caplog.records:
        message = record.getMessage()
        for secret in (OTHER, MAINTAINER_HOST, TOKEN):
            assert secret not in message, message
