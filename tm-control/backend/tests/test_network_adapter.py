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


LIST = ("NAME,UUID,TYPE,AUTOCONNECT,TIMESTAMP", "connection", "show")
DETAILS = "802-11-wireless.mode,802-11-wireless.hidden,connection.autoconnect-priority,802-11-wireless.ssid"


def saved(nm, rows, details):
    """rows: the -t list as nmcli prints it; details: {uuid: (mode, hidden, priority, ssid)} as -g prints them."""
    nm.answer(*LIST, out="".join(row + "\n" for row in rows))
    for uuid, values in details.items():
        nm.answer("-g", DETAILS, "connection", "show", "uuid", uuid, out="".join(v + "\n" for v in values))


def test_saved_networks_come_in_the_units_order(nm):
    saved(
        nm,
        [
            "Phone:u1:802-11-wireless:yes:100",
            "Depot:u2:802-11-wireless:yes:0",
            "tm-hotspot:u3:802-11-wireless:yes:900",
            "Home:u4:802-11-wireless:yes:500",
        ],
        {
            "u1": ("infrastructure", "no", "0", "Phone"),
            "u2": ("infrastructure", "yes", "2", "Depot"),
            "u3": ("ap", "no", "0", "TM-AB12"),
            "u4": ("infrastructure", "no", "0", "Home"),
        },
    )
    found = network.saved_wifi()
    assert [n.ssid for n in found] == ["Depot", "Home", "Phone"]  # priority 2, then newer, then older
    assert found[0] == network.SavedWifi("u2", "Depot", "Depot", True, 2, 0, True)


def test_the_hotspot_and_ethernet_are_not_saved_networks(nm):
    saved(
        nm,
        ["tm-hotspot:u1:802-11-wireless:yes:5", "Wired connection 1:u2:802-3-ethernet:yes:6", "lo:u3:loopback:no:0"],
        {"u1": ("ap", "no", "0", "TM-AB12")},
    )
    assert network.saved_wifi() == []


def test_a_saved_name_with_a_colon_and_a_backslash_is_read_whole(nm):
    saved(
        nm,
        ["Caf\\\\e\\: 2:u1:802-11-wireless:no:7"],
        {"u1": ("infrastructure", "no", "-3", "Caf\\\\e\\: 2")},
    )
    [found] = network.saved_wifi()
    assert found.ssid == "Caf\\e: 2" and found.profile == "Caf\\e: 2"
    assert (found.autoconnect, found.priority, found.timestamp) == (False, -3, 7)


def test_a_profile_without_a_name_of_its_own_uses_the_profiles(nm):
    saved(nm, ["Depot:u1:802-11-wireless:yes:0"], {"u1": ("infrastructure", "no", "0", "")})
    assert network.saved_wifi()[0].ssid == "Depot"


def test_a_profile_that_has_never_been_used_has_timestamp_zero(nm):
    saved(nm, ["Depot:u1:802-11-wireless:yes:"], {"u1": ("infrastructure", "no", "0", "Depot")})
    assert network.saved_wifi()[0].timestamp == 0


def test_a_row_that_is_not_five_fields_makes_the_read_none(nm):
    saved(nm, ["Depot:u1:802-11-wireless:yes"], {"u1": ("infrastructure", "no", "0", "Depot")})
    assert network.saved_wifi() is None


def test_a_profile_whose_details_cannot_be_read_makes_the_read_none(nm):
    saved(nm, ["Depot:u1:802-11-wireless:yes:0"], {})
    assert network.saved_wifi() is None


def test_the_device_reports_the_profile_it_is_on(nm):
    nm.answer("device", "show", "wlan0", out="GENERAL.CON-UUID:1b0c-uuid\n")
    assert network.active_uuid("wlan0") == "1b0c-uuid"
    assert nm.calls == [["nmcli", "-t", "-f", "GENERAL.CON-UUID", "device", "show", "wlan0"]]


@pytest.mark.parametrize("out", ["GENERAL.CON-UUID:\n", "GENERAL.CON-UUID:--\n"])
def test_a_device_on_nothing_reads_as_false(nm, out):
    nm.answer("device", "show", "wlan0", out=out)
    assert network.active_uuid("wlan0") is False


def test_a_failed_read_is_none(nm):
    assert network.saved_wifi() is None and network.active_uuid("wlan0") is None


def test_a_timeout_is_none(nm):
    nm.fail = "timeout"
    assert network.saved_wifi() is None and network.active_uuid("wlan0") is None


def test_a_missing_nmcli_is_none(nm):
    nm.fail = FileNotFoundError()
    assert network.saved_wifi() is None and network.active_uuid("wlan0") is None


def test_the_count_of_saved_networks_follows_the_list(nm):
    saved(
        nm,
        ["A:u1:802-11-wireless:yes:1", "B:u2:802-11-wireless:yes:2", "tm-hotspot:u3:802-11-wireless:yes:3"],
        {"u1": ("infrastructure", "no", "0", "A"), "u2": ("infrastructure", "no", "0", "B"), "u3": ("ap", "no", "0", "H")},
    )
    assert network.saved_networks() == 2


def test_split_terse_splits_at_unescaped_colons_only():
    assert network.split_terse("a\\:b:c\\\\:d:") == ["a:b", "c\\", "d", ""]
