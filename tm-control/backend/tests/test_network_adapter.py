"""The network adapter's reads of the links, the joined network and the hotspot's hidden setting.

`network.run` is replaced with a function that answers from a table of nmcli arguments. Synthetic names only.
"""

import pytest

from tm_control.adapters import network
from tm_control.adapters.command import CommandResult

ETH = (
    "GENERAL.HWADDR:2C:CF:67:00:AB:11\nGENERAL.STATE:100 (connected)\n"
    "GENERAL.CONNECTION:Wired connection 1\nIP4.ADDRESS[1]:192.168.1.57/24\nIP4.GATEWAY:192.168.1.1\n"
    "IP4.DNS[1]:192.168.1.1\nIP4.DNS[2]:9.9.9.9\n"
)


class FakeNmcli:
    """Answers `nmcli` from a table. A key is a run of arguments that must appear, in order and side by side, in the
    command line; the first key that does answers."""

    def __init__(self, monkeypatch):
        self.answers = []
        self.fail = None
        self.calls = []
        monkeypatch.setattr(network, "run", self._run)

    def answer(self, *key, out="", status=0):
        self.answers.append((key, CommandResult(status, out, "", False)))

    def _run(self, argv, **kwargs):
        self.calls.append(argv)
        if self.fail == "timeout":
            return CommandResult(-9, "", "", True)
        if self.fail is not None:
            raise self.fail
        for key, result in self.answers:
            if any(tuple(argv[i : i + len(key)]) == key for i in range(len(argv))):
                return result
        return CommandResult(2, "", "unexpected", False)


@pytest.fixture
def nm(monkeypatch):
    return FakeNmcli(monkeypatch)


def test_a_connected_link_has_its_mac_addresses_gateway_and_dns(nm):
    nm.answer("device", "show", "eth0", out=ETH)
    assert network.link("eth0") == network.Link(
        100, "Wired connection 1", "2C:CF:67:00:AB:11", ("192.168.1.57",), "192.168.1.1", ("192.168.1.1", "9.9.9.9")
    )


def test_an_unplugged_link_keeps_its_mac_and_has_nothing_else(nm):
    nm.answer(
        "device", "show", "eth0",
        out="GENERAL.HWADDR:2C:CF:67:00:AB:11\nGENERAL.STATE:20 (unavailable)\nGENERAL.CONNECTION:\nIP4.GATEWAY:\n",
    )
    assert network.link("eth0") == network.Link(20, None, "2C:CF:67:00:AB:11", (), None, ())


def test_a_dash_dash_value_also_reads_as_nothing(nm):  # older nmcli prints "--"
    nm.answer(
        "device", "show", "eth0",
        out="GENERAL.HWADDR:2C:CF:67:00:AB:11\nGENERAL.STATE:20 (unavailable)\nGENERAL.CONNECTION:--\nIP4.GATEWAY:--\n",
    )
    assert network.link("eth0") == network.Link(20, None, "2C:CF:67:00:AB:11", (), None, ())


def test_a_link_with_no_state_line_is_none(nm):
    nm.answer("device", "show", "eth0", out="GENERAL.HWADDR:2C:CF:67:00:AB:11\n")
    assert network.link("eth0") is None


def test_a_connection_name_with_a_colon_is_read_whole(nm):
    nm.answer("device", "show", "wlan0", out="GENERAL.STATE:100 (connected)\nGENERAL.CONNECTION:Caf\\:e\n")
    assert network.link("wlan0") == network.Link(100, "Caf:e", None, (), None, ())


def test_the_link_is_read_with_one_command_for_the_device(nm):
    nm.answer("device", "show", "eth0", out=ETH)
    network.link("eth0")
    assert nm.calls == [[
        "nmcli", "-t", "-f", "GENERAL.HWADDR,GENERAL.STATE,GENERAL.CONNECTION,IP4.ADDRESS,IP4.GATEWAY,IP4.DNS",
        "device", "show", "eth0",
    ]]


def test_only_a_device_with_hardware_behind_it_is_physical(tmp_path):
    (tmp_path / "eth0" / "device").mkdir(parents=True)
    (tmp_path / "veth0").mkdir()
    assert network.physical("eth0", tmp_path) and not network.physical("veth0", tmp_path)
    assert not network.physical("gone0", tmp_path)


def test_devices_lists_each_name_with_its_type(nm):
    nm.answer("device", "status", out="eth0:ethernet\nwlan0:wifi\nlo:loopback\n")
    assert network.devices() == [("eth0", "ethernet"), ("wlan0", "wifi"), ("lo", "loopback")]


def test_a_name_with_a_colon_and_a_backslash_is_read_whole(nm):
    nm.answer("device", "wifi", "list", out=" :40:Other\n*:72:Caf\\\\e\\: 2\n")
    assert network.wifi_network("wlan0") == ("Caf\\e: 2", 72)


def test_the_joined_network_is_read_from_the_named_device_without_a_rescan(nm):
    nm.answer("device", "wifi", "list", out="*:81:Home\n")
    assert network.wifi_network("wlan0") == ("Home", 81)
    assert nm.calls == [[
        "nmcli", "-t", "-f", "IN-USE,SIGNAL,SSID", "device", "wifi", "list", "ifname", "wlan0", "--rescan", "no",
    ]]


def test_a_radio_on_no_network_reads_as_false(nm):
    nm.answer("device", "wifi", "list", out=" :40:Other\n")
    assert network.wifi_network("wlan0") is False


def test_the_hotspot_read_includes_hidden(nm):  # four -g reads: autoconnect, ssid, key-mgmt, hidden
    for prop, value in (
        ("connection.autoconnect", "yes"),
        ("802-11-wireless.ssid", "TM-AB12"),
        ("802-11-wireless-security.key-mgmt", "wpa-psk"),
        ("802-11-wireless.hidden", "yes"),
    ):
        nm.answer("-g", prop, "connection", "show", "tm-hotspot", out=value + "\n")
    assert network.hotspot("tm-hotspot") == network.Hotspot(True, "TM-AB12", "wpa-psk", True)


def test_a_hotspot_that_is_not_hidden(nm):
    for prop, value in (
        ("connection.autoconnect", "yes"),
        ("802-11-wireless.ssid", "TM-AB12"),
        ("802-11-wireless-security.key-mgmt", "wpa-psk"),
        ("802-11-wireless.hidden", "no"),
    ):
        nm.answer("-g", prop, "connection", "show", "tm-hotspot", out=value + "\n")
    assert network.hotspot("tm-hotspot").hidden is False


@pytest.mark.parametrize(
    "failure", [FileNotFoundError("nmcli"), "timeout", "exit"], ids=["missing", "timed out", "exit 1"]
)
def test_a_failed_read_is_none_for_every_probe(nm, failure):
    if failure == "exit":
        nm.answer("nmcli", status=1)
    else:
        nm.fail = failure
    assert network.devices() is None and network.link("eth0") is None and network.wifi_network("wlan0") is None
