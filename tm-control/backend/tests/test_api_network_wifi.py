"""GET /network/wifi and the routes that start a scan, forget a network, and set the order.

Fake mode answers from fake.FakeNetwork; the device cases run against adapter functions replaced by FakeLinks, with the
job's scan file and the retry's state file written into settings.network_run_dir. Synthetic names only.
"""

import json
import sqlite3
import time
from pathlib import Path

import pytest
from test_api_network import FakeLinks

from tm_control.adapters import network
from tm_control.adapters.network import SavedWifi

URL = "/api/v1/network/wifi"
ORIGIN = {"Origin": "http://tm-test.local"}
ADMIN, ADMIN_PASSWORD = "admin", "correct horse 1"
VIEWER, VIEWER_PASSWORD = "viewer", "viewer pass 1"
UUID_A = "11111111-1111-4111-8111-111111111111"
UUID_B = "22222222-2222-4222-8222-222222222222"
UUID_C = "33333333-3333-4333-8333-333333333333"
FIXTURES = Path(__file__).parent / "fixtures"
RADIO_OFF = "The Wi-Fi radio is switched off. Turn the hotspot on to switch it on."
NO_RADIO = "This unit has no built-in Wi-Fi radio."
STALE = "The saved networks changed. Reload the page."


def saved(uuid, ssid, autoconnect=True, hidden=False, priority=0):
    return SavedWifi(uuid, ssid, ssid, autoconnect, priority, 0, hidden)


class WifiLinks(FakeLinks):
    """FakeLinks, and the saved Wi-Fi networks: Home (in use) then Depot."""

    def __init__(self, monkeypatch):
        super().__init__(monkeypatch)
        self.saved = [saved(UUID_A, "Home"), saved(UUID_B, "Depot")]
        self.active = UUID_A
        monkeypatch.setattr(network, "saved_wifi", lambda: self.saved)
        monkeypatch.setattr(network, "active_uuid", lambda name: self.active)


@pytest.fixture
def links(monkeypatch):
    return WifiLinks(monkeypatch)


@pytest.fixture
def run_dir(settings):
    settings.network_run_dir.mkdir(parents=True)
    return settings.network_run_dir


def write_scan(run_dir, seconds_ago=12, **changes):
    scan = json.loads((FIXTURES / "network_scan.json").read_text())
    scan["monotonic"] = time.monotonic() - seconds_ago
    scan.update(changes)
    (run_dir / "network-scan.json").write_text(json.dumps(scan))


def write_retry(run_dir, uuid, failures=2):
    state = {"networks": {uuid: {"name": "x", "failures": failures, "last_failure": 5.0}}, "last_run": {}}
    (run_dir / "network-retry.json").write_text(json.dumps(state))


def read(client, login, username=ADMIN, password=ADMIN_PASSWORD):
    login(client, username, password)
    r = client.get(URL)
    assert r.status_code == 200, r.text
    return r.json()


def post(client, path, body=None):
    return client.post(f"{URL}/{path}", json={} if body is None else body, headers=ORIGIN)


def audit_rows(settings):
    con = sqlite3.connect(settings.state_dir / "state.sqlite")
    try:
        return con.execute("SELECT action, detail FROM audit ORDER BY id").fetchall()
    finally:
        con.close()


def test_anyone_logged_in_reads_the_wifi_networks(claimed_client, login):
    from tm_control.core.auth import Users

    Users(claimed_client.app.state.state).create(VIEWER, VIEWER_PASSWORD, "viewer")
    body = read(claimed_client, login, VIEWER, VIEWER_PASSWORD)
    assert body["readable"] is True and body["radio"] == "on"
    assert [s["name"] for s in body["saved"]] == ["Home", "Depot"]
    assert len(body["nearby"]) == 5


def test_no_login_no_networks(claimed_client):
    assert claimed_client.get(URL).status_code == 401


def test_saved_networks_say_which_is_in_use_in_range_and_failing(device_client, login, links, run_dir):
    write_scan(run_dir)
    write_retry(run_dir, UUID_B)
    body = read(device_client, login, VIEWER, VIEWER_PASSWORD)
    assert [(s["name"], s["in_use"], s["in_range"], s["could_not_join"]) for s in body["saved"]] == [
        ("Home", True, True, False),
        ("Depot", False, False, True),
    ]
    assert body["saved"][0]["uuid"] == UUID_A and body["saved"][0]["automatic"] is True
    assert body["readable"] is True and body["radio"] == "on"


def test_a_retry_with_no_failure_is_not_a_failure(device_client, login, links, run_dir):
    write_retry(run_dir, UUID_B, failures=0)
    assert read(device_client, login)["saved"][1]["could_not_join"] is False


def test_a_network_saved_with_autoconnect_off_comes_last_and_is_not_automatic(device_client, login, links):
    links.saved = [saved(UUID_A, "Home"), saved(UUID_B, "Spare", autoconnect=False), saved(UUID_C, "Depot")]
    body = read(device_client, login)
    assert [(s["name"], s["automatic"]) for s in body["saved"]] == [("Home", True), ("Depot", True), ("Spare", False)]


def test_a_hidden_saved_network_is_never_in_range_once_there_is_a_scan(device_client, login, links, run_dir):
    links.saved = [saved(UUID_A, "Home"), saved(UUID_B, "Hush", hidden=True)]
    write_scan(run_dir)
    hush = read(device_client, login)["saved"][1]
    assert hush["hidden"] is True and hush["in_range"] is False


def test_nearby_networks_say_which_are_saved(device_client, login, links, run_dir):
    write_scan(run_dir, seconds_ago=12)
    body = read(device_client, login)
    assert [(n["name"], n["signal"], n["security"], n["saved"], n["in_use"]) for n in body["nearby"]] == [
        ("Home", 82, "password", True, True),
        ("Cafe", 64, "wpa3", False, False),
        ("Guest", 41, "open", False, False),
        ("Office", 30, "enterprise", False, False),
        ("Neighbour", 18, "other", False, False),
    ]
    assert 12 <= body["scanned_seconds_ago"] <= 20


def test_a_saved_network_that_is_not_in_use_is_marked_saved_only(device_client, login, links, run_dir):
    links.active = False
    write_scan(run_dir)
    home = read(device_client, login)["nearby"][0]
    assert (home["saved"], home["in_use"]) == (True, False)


def test_without_a_scan_nothing_is_nearby_and_in_range_is_unknown(device_client, login, links):
    body = read(device_client, login)
    assert body["nearby"] == [] and body["scanned_seconds_ago"] is None and body["saved"][0]["in_range"] is None


@pytest.mark.parametrize(
    "text",
    [
        "",
        "not json",
        "[]",
        '{"monotonic": 1.0}',
        '{"monotonic": "soon", "networks": []}',
        '{"monotonic": 1.0, "networks": {"ssid": "Home"}}',
        '{"monotonic": 1.0, "networks": [{"ssid": "Home", "signal": 80}]}',
        '{"monotonic": 1.0, "networks": [{"ssid": "Home", "signal": 80, "security": "wep"}]}',
        '{"monotonic": 1.0, "networks": [{"ssid": 7, "signal": 80, "security": "open"}]}',
    ],
)
def test_a_scan_file_that_makes_no_sense_reads_as_no_scan(device_client, login, links, run_dir, text):
    (run_dir / "network-scan.json").write_text(text)
    body = read(device_client, login)
    assert body["nearby"] == [] and body["scanned_seconds_ago"] is None and body["saved"][0]["in_range"] is None


def test_a_retry_file_that_makes_no_sense_reads_as_no_failures(device_client, login, links, run_dir):
    (run_dir / "network-retry.json").write_text('{"networks": {"%s": {"failures": "two"}}}' % UUID_B)
    assert [s["could_not_join"] for s in read(device_client, login)["saved"]] == [False, False]
    (run_dir / "network-retry.json").write_text("[1, 2")
    assert [s["could_not_join"] for s in read(device_client, login)["saved"]] == [False, False]


def test_a_silent_networkmanager_is_not_an_error(device_client, login, links):
    links.saved = None
    body = read(device_client, login)
    assert body["readable"] is False and body["saved"] == [] and body["nearby"] == []


def test_a_radio_that_is_off_or_missing(device_client, login, links):
    links.radio = False
    assert read(device_client, login)["radio"] == "off"
    links.kind = "usb"
    assert read(device_client, login)["radio"] == "none"


def test_the_answer_never_holds_a_password(claimed_client, login):
    login(claimed_client, ADMIN, ADMIN_PASSWORD)
    text = claimed_client.get(URL).text.lower()
    assert "password" not in text.replace('"security":"password"', "") and "abcd-efgh" not in text


# Refresh, Forget, and the order


def test_refresh_starts_a_scan(claimed_client, login):
    login(claimed_client, ADMIN, ADMIN_PASSWORD)
    r = post(claimed_client, "scan")
    assert r.status_code == 202 and r.json()["id"]
    assert claimed_client.app.state.jobs.last_request == {"action": "scan"}


def test_no_scan_on_a_radio_that_is_off(device_client, login, links, settings):
    login(device_client, ADMIN, ADMIN_PASSWORD)
    links.radio = False
    r = post(device_client, "scan")
    assert r.status_code == 409 and r.json()["error"]["code"] == "radio_off"
    assert r.json()["error"]["message"] == RADIO_OFF
    assert not (settings.runtime_dir / "jobs" / "network.json").exists()


def test_no_scan_without_a_built_in_radio(device_client, login, links, settings):
    login(device_client, ADMIN, ADMIN_PASSWORD)
    links.kind = "usb"
    r = post(device_client, "scan")
    assert r.status_code == 409 and r.json()["error"]["code"] == "no_radio"
    assert r.json()["error"]["message"] == NO_RADIO
    assert not (settings.runtime_dir / "jobs" / "network.json").exists()


def test_a_scan_on_a_radio_that_cannot_be_read_still_starts_the_job(device_client, login, links):
    login(device_client, ADMIN, ADMIN_PASSWORD)
    links.radio = None
    started = []
    device_client.app.state.jobs.start = lambda name, request, user_id: started.append((name, request)) or type(
        "Job", (), {"id": "job-1"}
    )()
    assert post(device_client, "scan").status_code == 202 and started == [("network", {"action": "scan"})]


def test_forget_starts_the_job_and_audits_the_name(claimed_client, login, settings):
    login(claimed_client, ADMIN, ADMIN_PASSWORD)
    uuid = claimed_client.get(URL).json()["saved"][1]["uuid"]
    r = post(claimed_client, "forget", {"uuid": uuid})
    assert r.status_code == 202 and r.json()["id"]
    assert claimed_client.app.state.jobs.last_request == {"action": "forget", "uuid": uuid}
    assert ("network.wifi_forget", "Depot") in audit_rows(settings)


def test_forget_on_a_device_checks_the_saved_networks(device_client, login, links, settings):
    login(device_client, ADMIN, ADMIN_PASSWORD)
    started = []
    device_client.app.state.jobs.start = lambda name, request, user_id: started.append((name, request)) or type(
        "Job", (), {"id": "job-1"}
    )()
    assert post(device_client, "forget", {"uuid": UUID_B}).status_code == 202
    assert started == [("network", {"action": "forget", "uuid": UUID_B})]
    assert ("network.wifi_forget", "Depot") in audit_rows(settings)


def test_forgetting_an_unknown_network_is_a_404(device_client, login, links, settings):
    login(device_client, ADMIN, ADMIN_PASSWORD)
    r = post(device_client, "forget", {"uuid": UUID_C})
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
    assert audit_rows(settings) == []
    assert not (settings.runtime_dir / "jobs" / "network.json").exists()


def test_forgetting_when_networkmanager_is_silent_is_a_404(device_client, login, links):
    login(device_client, ADMIN, ADMIN_PASSWORD)
    links.saved = None
    assert post(device_client, "forget", {"uuid": UUID_A}).status_code == 404


def test_an_order_must_name_exactly_the_saved_networks(device_client, login, links, settings):
    login(device_client, ADMIN, ADMIN_PASSWORD)
    links.saved = [saved(UUID_A, "Home"), saved(UUID_B, "Depot"), saved(UUID_C, "Spare", autoconnect=False)]
    started = []
    device_client.app.state.jobs.start = lambda name, request, user_id: started.append((name, request)) or type(
        "Job", (), {"id": "job-1"}
    )()
    for uuids in ([UUID_A], [UUID_A, UUID_B, UUID_C], [UUID_A, UUID_A], [UUID_A, UUID_B, UUID_B], []):
        r = post(device_client, "order", {"uuids": uuids})
        assert r.status_code == 409 and r.json()["error"]["code"] == "stale_order", uuids
        assert r.json()["error"]["message"] == STALE
    assert started == [] and audit_rows(settings) == []
    r = post(device_client, "order", {"uuids": [UUID_B, UUID_A]})
    assert r.status_code == 202
    assert started == [("network", {"action": "order", "uuids": [UUID_B, UUID_A]})]
    assert ("network.wifi_order", None) in audit_rows(settings)


@pytest.mark.parametrize("path, body", [("scan", None), ("forget", {"uuid": UUID_A}), ("order", {"uuids": [UUID_A]})])
def test_a_viewer_cannot_change_the_wifi_networks(claimed_client, login, path, body):
    from tm_control.core.auth import Users

    Users(claimed_client.app.state.state).create(VIEWER, VIEWER_PASSWORD, "viewer")
    login(claimed_client, VIEWER, VIEWER_PASSWORD)
    assert post(claimed_client, path, body).status_code == 403
    assert claimed_client.app.state.jobs.last_request is None


def test_fake_mode_shows_a_forgotten_network_gone(claimed_client, login):
    login(claimed_client, ADMIN, ADMIN_PASSWORD)
    first = claimed_client.get(URL).json()
    assert [(s["name"], s["in_range"]) for s in first["saved"]] == [("Home", True), ("Depot", False)]
    assert [n["name"] for n in first["nearby"]][0] == "Home" and len(first["nearby"]) == 5
    assert first["scanned_seconds_ago"] is None
    assert post(claimed_client, "forget", {"uuid": first["saved"][1]["uuid"]}).status_code == 202
    assert [s["name"] for s in claimed_client.get(URL).json()["saved"]] == ["Home"]
    assert post(claimed_client, "scan").status_code == 202
    assert claimed_client.get(URL).json()["scanned_seconds_ago"] is not None


def test_fake_mode_shows_the_new_order(claimed_client, login):
    login(claimed_client, ADMIN, ADMIN_PASSWORD)
    saved_now = claimed_client.get(URL).json()["saved"]
    uuids = [s["uuid"] for s in reversed(saved_now)]
    assert post(claimed_client, "order", {"uuids": uuids}).status_code == 202
    assert [s["uuid"] for s in claimed_client.get(URL).json()["saved"]] == uuids
