"""GET /network: the unit's network details for any signed-in user.

Fake mode answers from fake.FakeNetwork; the device cases run against adapter functions replaced by FakeLinks. Synthetic
names and addresses only.
"""

import pytest

from tm_control.adapters import network
from tm_control.adapters.network import Hotspot, Link

URL = "/api/v1/network"
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
