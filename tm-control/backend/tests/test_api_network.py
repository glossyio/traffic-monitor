"""GET /network: the unit's network details for any signed-in user.

Fake mode answers from fake.FakeNetwork; the device cases run against adapter functions replaced by FakeLinks. Synthetic
names and addresses only.
"""

import sqlite3

import pytest

from tm_control.adapters import network
from tm_control.adapters.network import Hotspot, Link

URL = "/api/v1/network"
PASSWORD_URL = URL + "/hotspot/password"
HOTSPOT_URL = URL + "/hotspot"
ORIGIN = {"Origin": "http://tm-test.local"}
NO_HOTSPOT = "The hotspot isn't set up. Run the installer again (tmsetup.sh -t wifi)."
PASSWORD = "placeholder-pass-1"
ADMIN, ADMIN_PASSWORD = "admin", "correct horse 1"
VIEWER, VIEWER_PASSWORD = "viewer", "viewer pass 1"
ETH = Link(100, "Wired connection 1", "B8:27:EB:00:00:01", ("192.168.1.57",), "192.168.1.1", ("192.168.1.1",))
WLAN = Link(100, "Cafe", "B8:27:EB:00:00:02", ("192.168.1.80",), "192.168.1.1", ("192.168.1.1", "9.9.9.9"))
PROFILE = Hotspot(True, "TM-AB12", "wpa-psk", False)


class FakeLinks:
    """NetworkManager as the adapter sees it. Set the fields before the request; None is a failed read."""

    def __init__(self, monkeypatch):
        self.devices = [("lo", "loopback"), ("veth0", "ethernet"), ("eth0", "ethernet"), ("wlan0", "wifi")]
        self.physical = {"eth0", "wlan0"}
        self.links = {"eth0": ETH, "wlan0": WLAN}
        self.kind = "builtin"
        self.radio = True
        self.wifi_network = ("Cafe", 64)
        self.hotspot = PROFILE
        self.connectivity = "full"
        monkeypatch.setattr(network, "devices", lambda: self.devices)
        monkeypatch.setattr(network, "physical", lambda name, *args: name in self.physical)
        monkeypatch.setattr(network, "link", lambda name: self.links.get(name))
        monkeypatch.setattr(network, "radio_kind", lambda name, *args: self.kind)
        monkeypatch.setattr(network, "radio_enabled", lambda: self.radio)
        monkeypatch.setattr(network, "wifi_network", lambda name: self.wifi_network)
        monkeypatch.setattr(network, "hotspot", lambda profile: self.hotspot)
        monkeypatch.setattr(network, "connectivity", lambda: self.connectivity)


@pytest.fixture
def links(monkeypatch):
    return FakeLinks(monkeypatch)


def read(device_client, login, username=VIEWER, password=VIEWER_PASSWORD):
    login(device_client, username, password)
    r = device_client.get(URL)
    assert r.status_code == 200, r.text
    return r.json()


def test_anyone_logged_in_reads_the_network_state(claimed_client, login):
    from tm_control.core.auth import Users

    Users(claimed_client.app.state.state).create(VIEWER, VIEWER_PASSWORD, "viewer")
    login(claimed_client, VIEWER, VIEWER_PASSWORD)
    body = claimed_client.get(URL).json()
    assert body["hostname"] and body["local_name"] == body["hostname"] + ".local"
    assert body["readable"] is True
    assert body["ethernet"]["connected"] is True and body["ethernet"]["addresses"] == ["192.168.1.57"]
    assert body["wifi"]["mode"] == "hotspot" and body["wifi"]["network"] is None
    assert body["hotspot"] == {
        "enabled": True,
        "active": True,
        "name": "TM-AB12",
        "hidden": False,
        "security": "wpa2",
        "address": "10.42.0.1",
    }


def test_no_login_no_state(claimed_client):
    assert claimed_client.get(URL).status_code == 401


def test_the_state_never_holds_a_password(claimed_client, login):
    login(claimed_client, ADMIN, ADMIN_PASSWORD)
    text = claimed_client.get(URL).text
    assert "password" not in text and "ABCD-EFGH-JKLM" not in text


def test_the_fake_hotspot_follows_a_change(claimed_client, login):
    login(claimed_client, ADMIN, ADMIN_PASSWORD)
    claimed_client.app.state.fake_network.apply({"enabled": False, "name": "TM-ZZ99", "hidden": True})
    body = claimed_client.get(URL).json()
    assert body["hotspot"]["enabled"] is False and body["hotspot"]["active"] is False
    assert (body["hotspot"]["name"], body["hotspot"]["hidden"]) == ("TM-ZZ99", True)
    assert body["wifi"]["mode"] == "idle"


def test_a_fake_password_makes_the_hotspot_wpa2(claimed_client):
    fake = claimed_client.app.state.fake_network
    fake.hotspot["security"] = "none"
    fake.apply({"password": "placeholder-pass-1"})
    assert fake.password == "placeholder-pass-1" and fake.hotspot["security"] == "wpa2"


def test_a_device_has_no_fake_network(device_client):
    assert device_client.app.state.fake_network is None


def test_a_unit_on_a_saved_network(device_client, login, links):
    body = read(device_client, login)
    assert body["readable"] is True and body["internet"] == "reachable"
    assert body["ethernet"] == {
        "connected": True,
        "mac": "B8:27:EB:00:00:01",
        "addresses": ["192.168.1.57"],
        "gateway": "192.168.1.1",
        "dns": ["192.168.1.1"],
    }
    assert body["wifi"]["mode"] == "network"
    assert (body["wifi"]["network"], body["wifi"]["signal"]) == ("Cafe", 64)
    assert body["wifi"]["connected"] is True and body["wifi"]["dns"] == ["192.168.1.1", "9.9.9.9"]
    assert body["hotspot"]["enabled"] is True and body["hotspot"]["active"] is False
    assert body["hotspot"]["address"] == "10.42.0.1"


def test_a_saved_network_with_a_hidden_name_is_shown_by_its_profile(device_client, login, links):
    links.wifi_network = ("", 40)
    wifi = read(device_client, login)["wifi"]
    assert (wifi["network"], wifi["signal"]) == ("Cafe", 40)


def test_a_saved_network_whose_signal_cannot_be_read(device_client, login, links):
    for answer in (None, False):
        links.wifi_network = answer
        wifi = read(device_client, login)["wifi"]
        assert (wifi["mode"], wifi["network"], wifi["signal"]) == ("network", "Cafe", None)


def test_a_unit_on_its_hotspot(device_client, login, links):
    links.links["wlan0"] = Link(100, "tm-hotspot", "B8:27:EB:00:00:02", ("10.42.0.1",), None, ())
    body = read(device_client, login)
    assert body["wifi"]["mode"] == "hotspot" and body["wifi"]["network"] is None
    assert body["wifi"]["signal"] is None and body["hotspot"]["active"] is True


@pytest.mark.parametrize("state", [40, 50, 70, 90])
def test_a_radio_that_is_joining(device_client, login, links, state):
    links.links["wlan0"] = Link(state, "Cafe", "B8:27:EB:00:00:02", (), None, ())
    wifi = read(device_client, login)["wifi"]
    assert (wifi["mode"], wifi["connected"], wifi["network"]) == ("joining", False, None)


def test_a_radio_that_is_on_nothing(device_client, login, links):
    links.links["wlan0"] = Link(30, None, "B8:27:EB:00:00:02", (), None, ())
    wifi = read(device_client, login)["wifi"]
    assert (wifi["mode"], wifi["connected"]) == ("idle", False)


def test_a_unit_with_its_radio_off(device_client, login, links):
    links.radio = False
    links.links["wlan0"] = Link(20, None, "B8:27:EB:00:00:02", (), None, ())
    body = read(device_client, login)
    assert body["wifi"]["mode"] == "off" and body["wifi"]["mac"] == "B8:27:EB:00:00:02"
    assert body["hotspot"]["active"] is False


def test_a_unit_without_ethernet_or_a_built_in_radio(device_client, login, links):
    links.physical = {"wlan0"}  # only podman's veth0 and loopback are left besides the radio
    body = read(device_client, login)
    assert body["ethernet"] is None and body["wifi"]["mode"] == "network"
    links.kind = "usb"
    body = read(device_client, login)
    assert body["wifi"] is None and body["hotspot"]["active"] is False


def test_the_first_physical_ethernet_device_is_used(device_client, login, links):
    links.devices = [("veth0", "ethernet"), ("eth1", "ethernet"), ("eth0", "ethernet"), ("wlan0", "wifi")]
    links.physical = {"eth1", "eth0", "wlan0"}
    links.links["eth1"] = Link(30, None, "B8:27:EB:00:00:03", (), None, ())
    ethernet = read(device_client, login)["ethernet"]
    assert ethernet["connected"] is False and ethernet["mac"] == "B8:27:EB:00:00:03"


def test_an_unreadable_link_is_shown_as_not_connected(device_client, login, links):
    links.links = {}
    body = read(device_client, login)
    empty = {"connected": False, "mac": None, "addresses": [], "gateway": None, "dns": []}
    assert body["ethernet"] == empty
    assert {key: body["wifi"][key] for key in empty} == empty and body["wifi"]["mode"] == "idle"


def test_a_silent_networkmanager_is_not_an_error(device_client, login, links):
    links.devices = None
    body = read(device_client, login)
    assert body["readable"] is False and body["hostname"] and body["internet"] == "unknown"
    assert body["ethernet"] is None and body["wifi"] is None and body["hotspot"] is None
    assert body["local_name"] == body["hostname"] + ".local"


@pytest.mark.parametrize(
    "answer, internet",
    [
        ("full", "reachable"),
        ("portal", "sign_in_page"),
        ("limited", "not_reachable"),
        ("none", "not_reachable"),
        ("unknown", "unknown"),
        (None, "unknown"),
    ],
)
def test_the_internet_answers(device_client, login, links, answer, internet):
    links.connectivity = answer
    assert read(device_client, login)["internet"] == internet


@pytest.mark.parametrize(
    "profile, security",
    [
        (Hotspot(True, "TM-AB12", "wpa-psk", False), "wpa2"),
        (Hotspot(True, "TM-AB12", "", False), "none"),
        (Hotspot(True, "TM-AB12", "sae", False), "other"),
    ],
)
def test_the_hotspots_security(device_client, login, links, profile, security):
    links.hotspot = profile
    assert read(device_client, login)["hotspot"]["security"] == security


def test_a_hotspot_without_a_password_is_security_none(device_client, login, links):
    links.hotspot = Hotspot(False, "TM-AB12", "", True)
    hotspot = read(device_client, login)["hotspot"]
    assert hotspot == {
        "enabled": False,
        "active": False,
        "name": "TM-AB12",
        "hidden": True,
        "security": "none",
        "address": "10.42.0.1",
    }


@pytest.mark.parametrize("answer", [None, False])
def test_a_hotspot_that_is_not_set_up(device_client, login, links, answer):
    links.hotspot = answer
    body = read(device_client, login)
    assert body["hotspot"] is None and body["wifi"]["mode"] == "network"


# The hotspot password and the change request


def add_viewer(client):
    from tm_control.core.auth import Users

    Users(client.app.state.state).create(VIEWER, VIEWER_PASSWORD, "viewer")


def audit_rows(client, settings):
    con = sqlite3.connect(settings.state_dir / "state.sqlite")
    try:
        return con.execute("SELECT action, detail FROM audit ORDER BY id").fetchall(), "\n".join(con.iterdump())
    finally:
        con.close()


def change(client, body):
    return client.post(HOTSPOT_URL, json=body, headers=ORIGIN)


def test_only_an_admin_reads_the_hotspot_password(claimed_client, login, settings):
    assert claimed_client.get(PASSWORD_URL).status_code == 401
    add_viewer(claimed_client)
    login(claimed_client, VIEWER, VIEWER_PASSWORD)
    assert claimed_client.get(PASSWORD_URL).status_code == 403
    assert audit_rows(claimed_client, settings)[0] == []
    login(claimed_client, ADMIN, ADMIN_PASSWORD)
    r = claimed_client.get(PASSWORD_URL)
    assert r.status_code == 200 and r.json() == {"password": "ABCD-EFGH-JKLM"}
    assert r.headers["cache-control"] == "no-store"
    assert audit_rows(claimed_client, settings)[0] == [("network.hotspot_password_shown", None)]


def test_a_missing_password_file_reads_as_null_and_an_empty_one_as_empty(device_client, login, settings):
    login(device_client, ADMIN, ADMIN_PASSWORD)
    assert device_client.get(PASSWORD_URL).json() == {"password": None}
    path = settings.secrets_dir / "hotspot_password"
    path.write_text("")
    assert device_client.get(PASSWORD_URL).json() == {"password": ""}
    path.write_text(PASSWORD + "\n")
    assert device_client.get(PASSWORD_URL).json() == {"password": PASSWORD}


def test_a_change_starts_the_network_job_with_only_what_was_sent(claimed_client, login):
    login(claimed_client, ADMIN, ADMIN_PASSWORD)
    r = change(claimed_client, {"name": "TM-ROAD"})
    assert r.status_code == 202 and r.json()["id"]
    assert claimed_client.app.state.jobs.last_request == {"action": "hotspot", "name": "TM-ROAD"}
    change(claimed_client, {"enabled": False, "hidden": True, "password": PASSWORD})
    assert claimed_client.app.state.jobs.last_request == {
        "action": "hotspot", "enabled": False, "hidden": True, "password": PASSWORD,
    }


def test_a_viewer_cannot_change_the_hotspot(claimed_client, login):
    add_viewer(claimed_client)
    login(claimed_client, VIEWER, VIEWER_PASSWORD)
    assert change(claimed_client, {"name": "TM-ROAD"}).status_code == 403
    assert claimed_client.app.state.jobs.last_request is None


def test_a_change_needs_a_login_and_an_origin(claimed_client, login):
    assert change(claimed_client, {"name": "TM-ROAD"}).status_code == 401
    login(claimed_client, ADMIN, ADMIN_PASSWORD)
    assert claimed_client.post(HOTSPOT_URL, json={"name": "TM-ROAD"}).status_code == 403
    assert claimed_client.app.state.jobs.last_request is None


@pytest.mark.parametrize(
    "body",
    [
        {}, {"name": ""}, {"name": " TM"}, {"name": "a" * 33}, {"name": "TM\n1"}, {"name": "TM "},
        {"password": "short12"}, {"password": "x" * 64}, {"password": "pässwörd1"},
        {"password": " leading-space"}, {"password": "trailing-space "}, {"name": "a" * 129},
        {"enabled": "maybe"},
    ],
)
def test_a_change_is_refused_before_any_job(claimed_client, login, body):
    login(claimed_client, ADMIN, ADMIN_PASSWORD)
    r = change(claimed_client, body)
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation"
    assert claimed_client.app.state.jobs.last_request is None


def test_a_refusal_says_the_rule_and_never_the_value(claimed_client, login):
    login(claimed_client, ADMIN, ADMIN_PASSWORD)
    messages = {
        "nothing": change(claimed_client, {}).json()["error"]["message"],
        "name": change(claimed_client, {"name": "a" * 33}).json()["error"]["message"],
        "password": change(claimed_client, {"password": "short12"}).json()["error"]["message"],
    }
    assert messages["nothing"] == "Nothing to change."
    assert messages["name"] == (
        "A hotspot name is 1 to 32 characters (fewer with accents or emoji), with no space at either end."
    )
    assert messages["password"] == (
        "A hotspot password is 8 to 63 letters, digits, and symbols, with no space at either end."
    )
    assert "short12" not in messages["password"]


def test_a_name_is_counted_in_bytes(claimed_client, login):
    login(claimed_client, ADMIN, ADMIN_PASSWORD)
    euro = "\u20ac"  # three bytes in UTF-8
    assert change(claimed_client, {"name": euro * 11}).status_code == 422
    assert change(claimed_client, {"name": euro * 10 + "ab"}).status_code == 202


def test_the_audit_names_what_changed_and_never_the_password(claimed_client, login, settings):
    login(claimed_client, ADMIN, ADMIN_PASSWORD)
    assert change(claimed_client, {"password": PASSWORD, "name": "TM-ROAD"}).status_code == 202
    rows, dump = audit_rows(claimed_client, settings)
    assert ("network.hotspot", "name, password") in rows
    assert PASSWORD not in dump


def test_no_hotspot_profile_is_a_409(device_client, login, links):
    login(device_client, ADMIN, ADMIN_PASSWORD)
    links.hotspot = False
    r = change(device_client, {"name": "TM-ROAD"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "no_hotspot"
    assert r.json()["error"]["message"] == NO_HOTSPOT
    assert not (device_client.app.state.settings.runtime_dir / "jobs" / "network.json").exists()


def test_a_change_to_an_unreadable_networkmanager_still_starts_the_job(device_client, login, links):
    login(device_client, ADMIN, ADMIN_PASSWORD)
    links.hotspot = None
    started = []
    device_client.app.state.jobs.start = lambda name, request, user_id: started.append((name, request)) or type(
        "Job", (), {"id": "job-1"}
    )()
    r = change(device_client, {"hidden": True})
    assert r.status_code == 202 and started == [("network", {"action": "hotspot", "hidden": True})]


def test_fake_mode_shows_the_change(claimed_client, login):
    login(claimed_client, ADMIN, ADMIN_PASSWORD)
    assert change(claimed_client, {"name": "TM-ROAD", "password": PASSWORD, "hidden": True}).status_code == 202
    body = claimed_client.get(URL).json()
    assert (body["hotspot"]["name"], body["hotspot"]["hidden"]) == ("TM-ROAD", True)
    assert claimed_client.get(PASSWORD_URL).json() == {"password": PASSWORD}
