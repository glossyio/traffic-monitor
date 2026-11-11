"""GET /network/join and the routes that start a join, end its countdown early, and cancel or dismiss it.

Fake mode answers from fake.FakeNetwork; the device cases run against adapter functions replaced by WifiLinks, with the
join job's state file (network-join.json) written into settings.network_run_dir and the join unit's ActiveState
replaced by the `systemd` fixture. Names and passwords are placeholders.
"""

import json
import sqlite3
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_api_network_wifi import WifiLinks, saved, write_scan

from tm_control.modules.network import wifi

URL = "/api/v1/network"
ORIGIN = {"Origin": "http://tm-test.local"}
ADMIN, ADMIN_PASSWORD = "admin", "correct horse 1"
VIEWER, VIEWER_PASSWORD = "viewer", "viewer pass 1"
UUID_A = "11111111-1111-4111-8111-111111111111"
UUID_B = "22222222-2222-4222-8222-222222222222"
FIXTURES = Path(__file__).parent / "fixtures"
PASSWORD = "placeholder-pass-1"


class Unit:
    """The join job's unit: the ActiveState systemctl shows for it."""

    def __init__(self):
        self.active_state = "activating"
        self.asked = []


@pytest.fixture(autouse=True)
def unit(monkeypatch):
    unit = Unit()

    def show_unit(name, properties):
        unit.asked.append(name)
        return {"ActiveState": unit.active_state}

    monkeypatch.setattr(wifi, "systemd", SimpleNamespace(show_unit=show_unit))
    return unit


class Jobs:
    """The jobs a device client's runner was asked to start, in place of starting any."""

    def __init__(self):
        self.last_name = None
        self.last_request = None

    def start(self, name, request, user_id):
        self.last_name, self.last_request = name, request
        return SimpleNamespace(id="job-1")


@pytest.fixture
def jobs(device_client):
    jobs = Jobs()
    device_client.app.state.jobs.start = jobs.start
    return jobs


@pytest.fixture
def links(monkeypatch):
    return WifiLinks(monkeypatch)


@pytest.fixture
def run_dir(settings):
    settings.network_run_dir.mkdir(parents=True)
    return settings.network_run_dir


def write_join(run_dir, **changes):
    state = json.loads((FIXTURES / "network_join.json").read_text())
    state.update(changes)
    (run_dir / "network-join.json").write_text(json.dumps(state))


def scan(run_dir, *entries):
    """The last scan, with these (name, security) networks on top of the fixture's."""
    extra = [{"ssid": name, "signal": 70, "security": security} for name, security in entries]
    write_scan(run_dir, networks=extra + json.loads((FIXTURES / "network_scan.json").read_text())["networks"])


def get_join(client, login, username=ADMIN, password=ADMIN_PASSWORD):
    login(client, username, password)
    r = client.get(f"{URL}/join")
    assert r.status_code == 200, r.text
    return r.json()


def post(client, path, body=None):
    return client.post(f"{URL}/wifi/{path}", json={} if body is None else body, headers=ORIGIN)


def audit_rows(settings):
    con = sqlite3.connect(settings.state_dir / "state.sqlite")
    try:
        return con.execute("SELECT action, detail FROM audit ORDER BY id").fetchall()
    finally:
        con.close()


def no_job(jobs):
    assert jobs.last_request is None


# Reading the join


def test_no_join_reads_as_null(device_client, login, run_dir):
    assert get_join(device_client, login, VIEWER, VIEWER_PASSWORD) is None


def test_a_countdown_reports_its_seconds_left(device_client, login, run_dir, monkeypatch):
    monkeypatch.setattr(time, "monotonic", lambda: 880.2)
    write_join(run_dir)
    body = get_join(device_client, login, VIEWER, VIEWER_PASSWORD)
    assert body == {
        "stage": "countdown", "network": "HomeNet", "saved": False, "before": "tm-hotspot", "joined": True,
        "reason": None, "address": "192.168.1.57", "internet": "reachable", "seconds_left": 120, "finished_at": None,
    }
    monkeypatch.setattr(time, "monotonic", lambda: 1005.0)
    assert get_join(device_client, login)["seconds_left"] == 0


def test_seconds_left_come_from_the_monotonic_clock(device_client, login, run_dir, monkeypatch):
    write_join(run_dir, switch_monotonic=1000.0)
    monkeypatch.setattr(time, "monotonic", lambda: 880.2)
    monkeypatch.setattr(time, "time", lambda: 1_900_000_000.0 + 3600)
    assert get_join(device_client, login)["seconds_left"] == 120


def test_only_a_countdown_has_seconds_left(device_client, login, run_dir):
    write_join(run_dir, stage="testing", joined=None, address=None, internet=None, switch_monotonic=None)
    assert get_join(device_client, login)["seconds_left"] is None
    write_join(run_dir, stage="joined", switch_monotonic=None, finished_at="2026-11-11T10:05:00+00:00")
    body = get_join(device_client, login)
    assert body["seconds_left"] is None and body["finished_at"] == "2026-11-11T10:05:00+00:00"


def test_a_join_whose_job_is_gone_reads_as_interrupted(device_client, login, run_dir, unit):
    write_join(run_dir, stage="testing", joined=None, switch_monotonic=None)
    for state in ("inactive", "failed"):
        unit.active_state = state
        assert get_join(device_client, login)["stage"] == "interrupted"
    for state in ("activating", "active", "deactivating"):
        unit.active_state = state
        assert get_join(device_client, login)["stage"] == "testing"
    assert unit.asked[-1] == "tm-job-network-join.service"


def test_a_final_stage_does_not_ask_the_unit(device_client, login, run_dir, unit):
    write_join(run_dir, stage="failed", joined=False, reason="not_joined", switch_monotonic=None)
    unit.active_state = "inactive"
    body = get_join(device_client, login)
    assert (body["stage"], body["reason"]) == ("failed", "not_joined") and unit.asked == []


def test_a_unit_that_cannot_be_read_leaves_the_stage_as_it_is(device_client, login, run_dir, monkeypatch):
    write_join(run_dir)

    def fail(name, properties):
        raise RuntimeError("systemctl show failed")

    monkeypatch.setattr(wifi, "systemd", SimpleNamespace(show_unit=fail))
    monkeypatch.setattr(time, "monotonic", lambda: 880.2)
    assert get_join(device_client, login)["stage"] == "countdown"


@pytest.mark.parametrize("reason", [None, "not_in_range", "not_joined", "no_address", "busy", "error"])
def test_the_state_file_is_one_tm_control_can_read(device_client, login, run_dir, reason):
    write_join(run_dir, stage="failed", joined=False, reason=reason, address=None, internet=None, switch_monotonic=None)
    assert get_join(device_client, login)["reason"] == reason


@pytest.mark.parametrize(
    "text",
    [
        "",
        "not json",
        "[]",
        "{}",
        '{"stage": "countdown"}',
        json.dumps({**json.loads((FIXTURES / "network_join.json").read_text()), "stage": "dancing"}),
        json.dumps({**json.loads((FIXTURES / "network_join.json").read_text()), "stage": "interrupted"}),
        json.dumps({**json.loads((FIXTURES / "network_join.json").read_text()), "reason": "tired"}),
        json.dumps({**json.loads((FIXTURES / "network_join.json").read_text()), "internet": "yes"}),
        json.dumps({**json.loads((FIXTURES / "network_join.json").read_text()), "saved": "no"}),
        json.dumps({**json.loads((FIXTURES / "network_join.json").read_text()), "ssid": 7}),
        json.dumps({**json.loads((FIXTURES / "network_join.json").read_text()), "switch_monotonic": "soon"}),
        json.dumps({**json.loads((FIXTURES / "network_join.json").read_text()), "switch_monotonic": True}),
    ],
)
def test_a_state_file_that_makes_no_sense_reads_as_no_join(device_client, login, run_dir, text):
    (run_dir / "network-join.json").write_text(text)
    assert get_join(device_client, login) is None


def test_a_countdown_without_its_deadline_reads_as_no_join(device_client, login, run_dir):
    write_join(run_dir, switch_monotonic=None)
    assert get_join(device_client, login) is None


def test_the_answer_never_holds_a_password(device_client, login, run_dir):
    write_join(run_dir)
    login(device_client, ADMIN, ADMIN_PASSWORD)
    assert "password" not in device_client.get(f"{URL}/join").text.lower()


def test_no_login_no_join(claimed_client):
    assert claimed_client.get(f"{URL}/join").status_code == 401


def test_the_wifi_answer_carries_the_join(device_client, login, links, run_dir):
    login(device_client, VIEWER, VIEWER_PASSWORD)
    assert device_client.get(f"{URL}/wifi").json()["join"] is None
    write_join(run_dir, stage="failed", joined=False, reason="not_joined", switch_monotonic=None)
    body = device_client.get(f"{URL}/wifi").json()
    assert body["join"]["stage"] == "failed" and body["join"]["network"] == "HomeNet"
    assert body["join"] == device_client.get(f"{URL}/join").json()


# Starting a join


def start(client, login, body, username=ADMIN, password=ADMIN_PASSWORD):
    login(client, username, password)
    return post(client, "join", body)


def test_joining_a_new_network_starts_the_join_job_with_its_name_and_password(
    jobs, device_client, login, links, run_dir
):
    scan(run_dir, ("HomeNet", "password"))
    r = start(device_client, login, {"name": "HomeNet", "password": PASSWORD})
    assert r.status_code == 202, r.text
    assert r.json()["id"]
    assert jobs.last_name == "network-join"
    assert jobs.last_request == {"ssid": "HomeNet", "password": PASSWORD}


def test_joining_a_saved_network_without_a_password_names_its_profile(jobs, device_client, login, links, run_dir):
    scan(run_dir, ("Depot", "password"))
    r = start(device_client, login, {"name": "Depot"})
    assert r.status_code == 202
    assert (jobs.last_name, jobs.last_request) == ("network-join", {"uuid": UUID_B})


def test_a_new_password_for_a_saved_network_goes_as_a_new_network(jobs, device_client, login, links, run_dir):
    scan(run_dir, ("Depot", "password"))
    r = start(device_client, login, {"name": "Depot", "password": PASSWORD})
    assert r.status_code == 202
    assert jobs.last_request == {"ssid": "Depot", "password": PASSWORD}


def test_the_first_saved_network_of_a_name_is_the_one_joined(jobs, device_client, login, links, run_dir):
    links.saved = [
        saved(UUID_A, "Home"),
        saved(UUID_B, "Depot"),
        saved("33333333-3333-4333-8333-333333333333", "Depot"),
    ]
    links.active = UUID_A
    scan(run_dir, ("Depot", "password"))
    start(device_client, login, {"name": "Depot"})
    assert jobs.last_request == {"uuid": UUID_B}


def test_an_unsaved_network_needs_a_password(jobs, device_client, login, links, run_dir, settings):
    scan(run_dir, ("HomeNet", "password"))
    for body in ({"name": "HomeNet"}, {"name": "HomeNet", "password": None}):
        r = start(device_client, login, body)
        assert r.status_code == 422 and r.json()["error"]["message"] == "Enter the network's password."
    no_job(jobs)
    assert audit_rows(settings) == []


def test_a_network_the_scan_did_not_list_as_a_password_network_is_refused(jobs, device_client, login, links, run_dir):
    message = "That network isn't in the list any more. Tap Refresh and pick it again."
    login(device_client, ADMIN, ADMIN_PASSWORD)
    attempts = []
    # no scan at all
    attempts.append(post(device_client, "join", {"name": "HomeNet", "password": PASSWORD}))
    scan(run_dir, ("OpenNet", "open"), ("ThreeNet", "wpa3"), ("WorkNet", "enterprise"), ("OtherNet", "other"))
    for name in ("Nowhere", "OpenNet", "ThreeNet", "WorkNet", "OtherNet", "Neighbour"):
        attempts.append(post(device_client, "join", {"name": name, "password": PASSWORD}))
    for r in attempts:
        assert r.status_code == 409 and r.json()["error"]["code"] == "not_listed", r.text
        assert r.json()["error"]["message"] == message
    no_job(jobs)


def test_the_network_in_use_is_refused(jobs, device_client, login, links, run_dir):
    scan(run_dir, ("Home", "password"))
    r = start(device_client, login, {"name": "Home"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "already_joined"
    assert r.json()["error"]["message"] == "The unit is already on Home."
    no_job(jobs)


def test_a_radio_that_is_off_or_missing_is_refused(jobs, device_client, login, links, run_dir):
    scan(run_dir, ("HomeNet", "password"))
    links.radio = False
    r = start(device_client, login, {"name": "HomeNet", "password": PASSWORD})
    assert r.status_code == 409 and r.json()["error"]["code"] == "radio_off"
    links.kind = "usb"
    r = post(device_client, "join", {"name": "HomeNet", "password": PASSWORD})
    assert r.status_code == 409 and r.json()["error"]["code"] == "no_radio"
    no_job(jobs)


def test_a_name_is_counted_in_bytes(jobs, device_client, login, links, run_dir):
    scan(run_dir, ("é" * 16, "password"), ("é" * 17, "password"))
    assert start(device_client, login, {"name": "é" * 16, "password": PASSWORD}).status_code == 202
    r = post(device_client, "join", {"name": "é" * 17, "password": PASSWORD})  # 34 bytes
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation"
    r = post(device_client, "join", {"name": "a" * 33, "password": PASSWORD})
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation"


@pytest.mark.parametrize("name", ["", "Bad\nName", "Bad\x7fName"])
def test_a_name_with_a_control_character_or_nothing_is_refused(jobs, device_client, login, links, run_dir, name):
    r = start(device_client, login, {"name": name, "password": PASSWORD})
    assert r.status_code == 422, r.text
    no_job(jobs)


@pytest.mark.parametrize("password", ["short12", "x" * 64, "pässwörd-1"])
def test_a_password_outside_the_rule_is_refused_before_any_job(jobs, device_client, login, links, run_dir, password):
    scan(run_dir, ("HomeNet", "password"))
    r = start(device_client, login, {"name": "HomeNet", "password": password})
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation"
    assert r.json()["error"]["message"] == "A Wi-Fi password is 8 to 63 letters, digits, and symbols."
    no_job(jobs)


def test_a_password_may_have_spaces_at_its_ends(jobs, device_client, login, links, run_dir):
    scan(run_dir, ("HomeNet", "password"))
    r = start(device_client, login, {"name": "HomeNet", "password": " placeholder pass "})
    assert r.status_code == 202
    assert jobs.last_request["password"] == " placeholder pass "


def test_the_audit_names_the_network_and_never_the_password(jobs, device_client, login, links, run_dir, settings):
    scan(run_dir, ("HomeNet", "password"))
    start(device_client, login, {"name": "HomeNet", "password": PASSWORD})
    assert ("network.wifi_join", "HomeNet") in audit_rows(settings)
    con = sqlite3.connect(settings.state_dir / "state.sqlite")
    try:
        dump = "\n".join(con.iterdump())
    finally:
        con.close()
    assert PASSWORD not in dump


@pytest.mark.parametrize("stage", ["testing", "countdown", "switching"])
@pytest.mark.parametrize(
    "path, body",
    [
        ("hotspot", {"name": "TM-ROAD"}),
        ("wifi/scan", None),
        ("wifi/forget", {"uuid": UUID_A}),
        ("wifi/order", {"uuids": [UUID_A]}),
        ("wifi/join", {"name": "Other", "password": PASSWORD}),
    ],
)
def test_every_other_change_is_refused_while_a_join_is_pending(
    jobs, device_client, login, links, run_dir, stage, path, body
):
    scan(run_dir, ("Other", "password"))
    write_join(run_dir, stage=stage, switch_monotonic=time.monotonic() + 100 if stage == "countdown" else None)
    login(device_client, ADMIN, ADMIN_PASSWORD)
    r = device_client.post(f"{URL}/{path}", json={} if body is None else body, headers=ORIGIN)
    assert r.status_code == 409 and r.json()["error"]["code"] == "join_pending", r.text
    assert "HomeNet" in r.json()["error"]["message"]
    no_job(jobs)


@pytest.mark.parametrize(
    "stage, message",
    [
        ("testing", "The unit is testing HomeNet. Wait for the result."),
        ("countdown", "The unit is about to join HomeNet. Switch now or cancel first."),
        ("switching", "The unit is joining HomeNet now."),
    ],
)
def test_the_refusal_says_what_the_unit_is_doing(device_client, login, links, run_dir, stage, message):
    write_join(run_dir, stage=stage, switch_monotonic=time.monotonic() + 100 if stage == "countdown" else None)
    login(device_client, ADMIN, ADMIN_PASSWORD)
    assert post(device_client, "scan").json()["error"]["message"] == message


def test_a_finished_or_interrupted_join_does_not_block_other_changes(jobs, device_client, login, links, run_dir, unit):
    login(device_client, ADMIN, ADMIN_PASSWORD)
    write_join(run_dir, stage="failed", joined=False, reason="not_joined", switch_monotonic=None)
    assert post(device_client, "scan").status_code == 202
    write_join(run_dir, stage="testing", joined=None, switch_monotonic=None)
    unit.active_state = "inactive"
    assert post(device_client, "scan").status_code == 202


# Switch now, cancel


def test_switch_now_needs_a_countdown(jobs, device_client, login, run_dir):
    login(device_client, ADMIN, ADMIN_PASSWORD)
    r = post(device_client, "join/switch")
    assert r.status_code == 409 and r.json()["error"]["code"] == "no_countdown"
    assert r.json()["error"]["message"] == "There is no countdown to end."
    for stage in ("testing", "switching", "joined", "failed", "cancelled"):
        write_join(run_dir, stage=stage, switch_monotonic=None)
        assert post(device_client, "join/switch").status_code == 409, stage
    no_job(jobs)
    write_join(run_dir, switch_monotonic=time.monotonic() + 100)
    r = post(device_client, "join/switch")
    assert r.status_code == 202 and r.json()["id"]
    assert (jobs.last_name, jobs.last_request) == ("network", {"action": "switch-now"})


def test_cancel_cancels_a_countdown_and_dismisses_a_result(jobs, device_client, login, run_dir, settings):
    login(device_client, ADMIN, ADMIN_PASSWORD)
    write_join(run_dir, switch_monotonic=time.monotonic() + 100)
    assert post(device_client, "join/cancel").status_code == 202
    assert (jobs.last_name, jobs.last_request) == ("network", {"action": "cancel"})
    jobs.last_request = None
    write_join(run_dir, stage="failed", joined=False, reason="not_joined", switch_monotonic=None)
    assert post(device_client, "join/cancel").status_code == 202
    assert jobs.last_request == {"action": "cancel"}
    jobs.last_request = None
    write_join(run_dir, stage="testing", joined=None, switch_monotonic=None)
    assert post(device_client, "join/cancel").status_code == 202  # a test cancels too
    audit = [row for row in audit_rows(settings) if row[0] == "network.wifi_join_cancel"]
    assert len(audit) == 3


def test_cancel_with_nothing_there_is_a_409(jobs, device_client, login, run_dir):
    login(device_client, ADMIN, ADMIN_PASSWORD)
    r = post(device_client, "join/cancel")
    assert r.status_code == 409 and r.json()["error"]["code"] == "nothing_to_cancel"
    no_job(jobs)


def test_cancel_is_refused_while_the_unit_switches(jobs, device_client, login, run_dir):
    write_join(run_dir, stage="switching", switch_monotonic=None)
    login(device_client, ADMIN, ADMIN_PASSWORD)
    r = post(device_client, "join/cancel")
    assert r.status_code == 409 and r.json()["error"]["code"] == "join_pending"
    assert r.json()["error"]["message"] == "The unit is joining HomeNet now."
    no_job(jobs)


def test_cancel_clears_a_join_that_was_interrupted(jobs, device_client, login, run_dir, unit):
    write_join(run_dir, stage="switching", switch_monotonic=None)
    unit.active_state = "failed"
    login(device_client, ADMIN, ADMIN_PASSWORD)
    assert post(device_client, "join/cancel").status_code == 202
    assert jobs.last_request == {"action": "cancel"}


def test_switch_and_cancel_are_audited(jobs, device_client, login, run_dir, settings):
    login(device_client, ADMIN, ADMIN_PASSWORD)
    write_join(run_dir, switch_monotonic=time.monotonic() + 100)
    post(device_client, "join/switch")
    post(device_client, "join/cancel")
    actions = [row[0] for row in audit_rows(settings)]
    assert actions == ["network.wifi_join_switch", "network.wifi_join_cancel"]


@pytest.mark.parametrize("path", ["wifi/join", "wifi/join/switch", "wifi/join/cancel"])
def test_a_viewer_cannot_join_switch_or_cancel(claimed_client, login, path):
    from tm_control.core.auth import Users

    Users(claimed_client.app.state.state).create(VIEWER, VIEWER_PASSWORD, "viewer")
    login(claimed_client, VIEWER, VIEWER_PASSWORD)
    body = {"name": "Cafe", "password": PASSWORD} if path == "wifi/join" else {}
    r = claimed_client.post(f"{URL}/{path}", json=body, headers=ORIGIN)
    assert r.status_code == 403
    assert claimed_client.app.state.jobs.last_request is None


# Fake mode


def test_fake_mode_runs_a_join_to_its_countdown_and_a_wrong_password_to_a_failure(claimed_client, login):
    login(claimed_client, ADMIN, ADMIN_PASSWORD)
    assert claimed_client.get(f"{URL}/join").json() is None
    r = post(claimed_client, "join", {"name": "Cafe", "password": "wrong-password"})
    assert r.status_code == 202
    failed = claimed_client.get(f"{URL}/join").json()
    assert (failed["stage"], failed["joined"], failed["reason"]) == ("failed", False, "not_joined")
    assert post(claimed_client, "join/cancel").status_code == 202  # dismissed
    assert claimed_client.get(f"{URL}/join").json() is None
    r = post(claimed_client, "join", {"name": "Cafe", "password": "no-address-pass"})
    assert claimed_client.get(f"{URL}/join").json()["reason"] == "no_address"
    post(claimed_client, "join/cancel")
    r = post(claimed_client, "join", {"name": "Cafe", "password": PASSWORD})
    assert r.status_code == 202
    counting = claimed_client.get(f"{URL}/join").json()
    assert counting["stage"] == "countdown" and 295 <= counting["seconds_left"] <= 300
    assert counting["network"] == "Cafe" and counting["joined"] is True and counting["saved"] is False
    assert claimed_client.get(f"{URL}/wifi").json()["join"]["stage"] == "countdown"
    assert post(claimed_client, "scan").status_code == 409  # pending


def test_fake_mode_switches_now_and_puts_the_network_first_and_in_use(claimed_client, login):
    login(claimed_client, ADMIN, ADMIN_PASSWORD)
    post(claimed_client, "join", {"name": "Cafe", "password": PASSWORD})
    assert post(claimed_client, "join/switch").status_code == 202
    assert claimed_client.get(f"{URL}/join").json()["stage"] == "joined"
    wifi = claimed_client.get(f"{URL}/wifi").json()
    assert [(s["name"], s["in_use"]) for s in wifi["saved"]] == [("Cafe", True), ("Home", False), ("Depot", False)]
    assert claimed_client.get(URL).json()["hotspot"]["active"] is False
    assert post(claimed_client, "join/cancel").status_code == 202  # dismissed
    assert claimed_client.get(f"{URL}/join").json() is None


def test_fake_mode_cancels_a_countdown_and_joins_a_saved_network_by_uuid(claimed_client, login):
    login(claimed_client, ADMIN, ADMIN_PASSWORD)
    post(claimed_client, "join", {"name": "Cafe", "password": PASSWORD})
    assert post(claimed_client, "join/cancel").status_code == 202
    assert claimed_client.get(f"{URL}/join").json()["stage"] == "cancelled"
    assert post(claimed_client, "join/cancel").status_code == 202
    assert claimed_client.get(f"{URL}/join").json() is None
    assert claimed_client.get(f"{URL}/wifi").json()["saved"][0]["name"] == "Home"


def test_fake_mode_joins_a_saved_network_by_its_profile(claimed_client, login):
    login(claimed_client, ADMIN, ADMIN_PASSWORD)
    saved_uuid = claimed_client.get(f"{URL}/wifi").json()["saved"][0]["uuid"]
    assert post(claimed_client, "join", {"name": "Home"}).status_code == 202
    assert claimed_client.app.state.jobs.last_request == {"uuid": saved_uuid}
    assert claimed_client.get(f"{URL}/join").json()["saved"] is True


def test_fake_mode_reads_a_countdown_that_has_run_out_as_joined(claimed_client, login):
    login(claimed_client, ADMIN, ADMIN_PASSWORD)
    post(claimed_client, "join", {"name": "Cafe", "password": PASSWORD})
    claimed_client.app.state.fake_network.join["switch_monotonic"] = time.monotonic() - 1
    assert claimed_client.get(f"{URL}/join").json()["stage"] == "joined"
    assert claimed_client.get(f"{URL}/wifi").json()["saved"][0]["name"] == "Cafe"
