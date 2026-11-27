"""The Sharing page's download card, API side: GET /sharing's `download` (the database's size from Node-RED's status
and how many places have an exact location) and POST /sharing/download (a one-time link to the plain database).

claimed_client runs in fake mode: its Node-RED is fake.FakeNodeRed, whose status reports FakeNodeRed.DATABASE_BYTES.
No link, token, or coordinate reaches a log line or an audit row.
"""

import json
import logging
import re
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tm_control.adapters.nodered import NodeRedError
from tm_control.core.auth import Users
from tm_control.fake import FakeNodeRed
from tm_control.modules.location.places import Places
from tm_control.modules.location.router import NODERED_MESSAGES
from tm_control.modules.sharing.download import database_bytes

BASE = "http://tm-test.local"
ORIGIN = {"Origin": BASE}
JSON_HEADERS = {**ORIGIN, "Content-Type": "application/json"}  # the cross-site check wants JSON on every non-GET
ADMIN = ("admin", "correct horse 1")
VIEWER = ("viewer", "viewer pass 1")
URL = "/api/v1/sharing/download"
LINK = re.compile(r"^/storefiles\?files=/db/tmdb\.sqlite&tm_token=([A-Za-z0-9_-]+)$")
FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def admin(claimed_client, login):
    login(claimed_client, *ADMIN)
    return claimed_client


@pytest.fixture
def viewer(claimed_client, login):
    Users(claimed_client.app.state.state).create(*VIEWER, "viewer")
    login(claimed_client, *VIEWER)
    return claimed_client


def audit_rows(client) -> list[tuple]:
    """Every audit row, unfiltered, so a row written twice or under another action shows."""
    with sqlite3.connect(client.app.state.state.path) as con:
        return con.execute("SELECT action, detail FROM audit ORDER BY id").fetchall()


def sharing(client) -> dict:
    r = client.get("/api/v1/sharing")
    assert r.status_code == 200, r.text
    return r.json()


def locate_in_use(client) -> str:
    """The place in use, at the example coordinates."""
    in_use = client.get("/api/v1/surveys").json()["in_use"]
    assert in_use
    r = client.post(f"/api/v1/surveys/{in_use}/location", json={"lat": 45.52252, "lon": -122.6912}, headers=ORIGIN)
    assert r.status_code == 200, r.text
    return in_use


def unreachable(*args):
    raise NodeRedError("unreachable")


# What GET and PUT /sharing say


def test_a_viewer_gets_no_download_facts(viewer):
    assert sharing(viewer)["download"] is None


def test_an_admin_gets_the_size_and_the_count(admin):
    locate_in_use(admin)
    Places(admin.app.state.state).create("aaaaaaaa-si", None, None, None, [], "ui", "used", None)  # no location
    assert sharing(admin)["download"] == {"database_bytes": FakeNodeRed.DATABASE_BYTES, "exact_places": 1}


def test_an_admin_on_a_unit_with_no_located_place_gets_a_count_of_zero(admin):
    in_use = admin.get("/api/v1/surveys").json()["in_use"]
    created = admin.post("/api/v1/surveys", json={"description": None, "lat": None, "lon": None, "headings": []},
                         headers=ORIGIN)
    assert created.status_code == 201, created.text
    r = admin.post(f"/api/v1/surveys/{created.json()['id']}/deploy", json={"headings": []}, headers=ORIGIN)
    assert r.status_code == 200, r.text  # in use with no location; the first place is used now
    with sqlite3.connect(admin.app.state.state.path) as con:
        con.execute("UPDATE surveys SET lat = NULL, lon = NULL WHERE id = ?", (in_use,))
    admin.post("/api/v1/surveys", json={"description": None, "lat": 45.0, "lon": -122.0, "headings": []},
               headers=ORIGIN)  # located, but planned
    assert sharing(admin)["download"]["exact_places"] == 0


def test_the_put_answers_with_the_facts_too(admin):
    locate_in_use(admin)
    body = {
        "target": "maintainer", "host": None, "protocol": "https", "port": None, "enabled": False,
        "exact_location": False, "public_map": "none", "notice_version": None,
    }
    r = admin.put("/api/v1/sharing", json=body, headers=ORIGIN)
    assert r.status_code == 200, r.text
    assert r.json()["download"] == {"database_bytes": FakeNodeRed.DATABASE_BYTES, "exact_places": 1}


def test_the_size_is_none_when_node_red_does_not_answer(admin, monkeypatch):
    locate_in_use(admin)
    monkeypatch.setattr(admin.app.state.nodered, "report", unreachable)
    body = sharing(admin)
    assert body["download"] == {"database_bytes": None, "exact_places": 1}
    assert body["server"]["state"] == "unknown"


FIXTURE_BYTES = json.loads((FIXTURES / "nodered_status.json").read_text())["database_bytes"]


@pytest.mark.parametrize(
    "report, expected",
    [
        ({"database_bytes": 5}, 5),
        ({"database_bytes": 0}, 0),
        ({"database_bytes": -1}, None),
        ({"database_bytes": True}, None),
        ({"database_bytes": 1.5}, None),
        ({"database_bytes": "5"}, None),
        ({"database_bytes": None}, None),
        ({"status": "ok"}, None),
        (None, None),
        ([{"database_bytes": 5}], None),
        (json.loads((FIXTURES / "nodered_status.json").read_text()), FIXTURE_BYTES),
    ],
)
def test_database_bytes_reads_only_a_whole_number(report, expected):
    assert database_bytes(report) == expected


# POST /sharing/download


def test_download_is_admin_only(claimed_client, login):
    before = audit_rows(claimed_client)
    assert claimed_client.post(URL, headers=JSON_HEADERS).status_code == 401
    assert audit_rows(claimed_client) == before
    Users(claimed_client.app.state.state).create(*VIEWER, "viewer")
    login(claimed_client, *VIEWER)
    before = audit_rows(claimed_client)
    assert claimed_client.post(URL, headers=JSON_HEADERS).status_code == 403
    assert len(claimed_client.app.state.download_grants) == 0
    assert audit_rows(claimed_client) == before


def test_download_answers_a_one_time_link_to_the_database(admin):
    before = len(admin.app.state.download_grants)
    rows = audit_rows(admin)
    r = admin.post(URL, headers=JSON_HEADERS)
    assert r.status_code == 200, r.text
    assert r.headers["cache-control"] == "no-store"
    assert LINK.match(r.json()["url"]), r.json()
    assert len(admin.app.state.download_grants) == before + 1
    assert audit_rows(admin) == [*rows, ("sharing.download", None)]


def test_the_link_passes_verify_once_without_a_session(admin):
    url = admin.post(URL, headers=JSON_HEADERS).json()["url"]
    helper = TestClient(admin.app, base_url=BASE)

    def verify():
        return helper.get("/api/v1/auth/verify", headers={"X-Original-URI": url, "X-TM-Required-Role": "admin"})

    assert verify().status_code == 200
    assert verify().status_code == 401


@pytest.mark.parametrize("code", ["unreachable", "refused"])
def test_download_makes_no_link_when_node_red_does_not_answer(admin, monkeypatch, code):
    def failing(*args):
        raise NodeRedError(code)

    monkeypatch.setattr(admin.app.state.nodered, "report", failing)
    rows = audit_rows(admin)
    r = admin.post(URL, headers=JSON_HEADERS)
    assert r.status_code == 502 and r.json()["error"]["code"] == "nodered_error"
    assert r.json()["error"]["message"] == f"The download wasn't started. {NODERED_MESSAGES[code]}"
    assert len(admin.app.state.download_grants) == 0
    assert audit_rows(admin) == rows


def test_no_token_reaches_a_log_line_or_an_audit_row(admin, caplog):
    caplog.set_level(logging.DEBUG)
    r = admin.post(URL, headers=JSON_HEADERS)
    assert r.status_code == 200
    url = r.json()["url"]
    token = LINK.match(url).group(1)
    helper = TestClient(admin.app, base_url=BASE)
    for expected in (200, 401):  # the one call that carries the token in a request: verify's X-Original-URI
        verify = helper.get("/api/v1/auth/verify", headers={"X-Original-URI": url, "X-TM-Required-Role": "admin"})
        assert verify.status_code == expected
    for action, detail in audit_rows(admin):
        assert token not in action and token not in (detail or "")
    assert any("download link used by" in record.getMessage() for record in caplog.records)  # capture works
    for record in caplog.records:
        assert token not in record.getMessage()
        assert "/storefiles?" not in record.getMessage()
