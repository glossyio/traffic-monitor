"""The Network checks (the hotspot, the Wi-Fi network, the internet, the Wi-Fi country) and the network adapter.

The checks run against monkeypatched adapter functions, one test per row of the design's table; the adapter runs
against small fake `nmcli` and `iw` programs on PATH. Synthetic names only.
"""

import shutil
import stat
import textwrap
from pathlib import Path

import pytest

from tm_control.adapters import network, systemd
from tm_control.adapters.network import Device, Hotspot
from tm_control.core.checks import Context, Fix, run_group
from tm_control.core.manifest import load_manifest
from tm_control.core.secrets import FakeSecrets
from tm_control.modules import MODULES
from tm_control.modules.network.checks import FIREWALL_UNIT, GROUP, RESTART_HOTSPOT, RETRY_UNIT, RUN_INSTALLER

FIXTURES = Path(__file__).resolve().parent / "fixtures"
ON = Device(100, "tm-hotspot")
PROFILE = Hotspot(True, "TM-AB12", "wpa-psk", False)
SET_A_PASSWORD = Fix(kind="hint", text="See Wi-Fi and the hotspot in the docs to set one.")
SET_THE_COUNTRY = Fix(kind="hint", text="Run the installer again (tmsetup.sh -t wifi); it asks for the country.")


class FakeNetwork:
    """The Wi-Fi as the adapter sees it. Set the fields, then ask check() or report(); None is a failed read."""

    def __init__(self, monkeypatch):
        self.kind = "builtin"
        self.radio = True
        self.device = ON
        self.hotspot = PROFILE
        self.firewall = "active"
        self.signal = 72
        self.saved = 2
        self.connectivity = "limited"
        self.country = "US"
        self.reads = []
        monkeypatch.setattr(network, "radio_kind", lambda name: self.kind)
        monkeypatch.setattr(network, "radio_enabled", lambda: self._read("radio", self.radio))
        monkeypatch.setattr(network, "device", lambda name: self._read("device", self.device))
        monkeypatch.setattr(network, "hotspot", lambda profile: self._read("hotspot", self.hotspot))
        monkeypatch.setattr(network, "signal", lambda name: self.signal)
        monkeypatch.setattr(network, "saved_networks", lambda: self.saved)
        monkeypatch.setattr(network, "connectivity", lambda: self.connectivity)
        monkeypatch.setattr(network, "wifi_country", lambda: self.country)
        monkeypatch.setattr(systemd, "show_unit", self._show_unit)

    def _read(self, name, value):
        self.reads.append(name)
        return value

    def _show_unit(self, name, properties):
        assert (name, properties) == (FIREWALL_UNIT, ["ActiveState"])
        if self.firewall is None:
            raise RuntimeError("systemctl show failed")
        return {"ActiveState": self.firewall}

    def context(self):
        return Context(settings=None, manifest=load_manifest(FIXTURES / "manifest.json"), secrets=FakeSecrets())


@pytest.fixture
def net(monkeypatch):
    return FakeNetwork(monkeypatch)


def report(net):
    group = run_group(GROUP, net.context())
    assert (group.id, group.title) == ("network", "Network")
    return group


def check(net, check_id):
    (found,) = [c for c in report(net).checks if c.id == check_id]
    return found.status, found.detail, found.fix


def test_the_network_module_comes_after_hardware_and_has_no_routes():
    ids = [m.id for m in MODULES]
    assert ids[ids.index("hardware") + 1] == "network"
    (module,) = [m for m in MODULES if m.id == "network"]
    assert [g.id for g in module.check_groups] == ["network"]
    assert module.router.routes == []


def test_the_group_has_the_four_checks_in_order(net):
    assert [(c.id, c.title) for c in report(net).checks] == [
        ("network.hotspot", "Hotspot"),
        ("network.wifi", "Wi-Fi network"),
        ("network.internet", "Internet"),
        ("network.wifi_country", "Wi-Fi country"),
    ]


def test_the_fixes_are_the_retry_unit_and_the_installer():
    assert RESTART_HOTSPOT == Fix(kind="restart", text="Restart the hotspot", unit="tm-network-retry.service")
    assert RETRY_UNIT == "tm-network-retry.service" and FIREWALL_UNIT == "tm-hotspot-firewall.service"
    assert RUN_INSTALLER == Fix(kind="hint", text="Run the installer again (tmsetup.sh -t wifi).")


def test_the_device_hotspot_and_radio_are_each_read_once_per_report(net):
    report(net)
    assert sorted(net.reads) == ["device", "hotspot", "radio"]


# The hotspot, row by row


def test_the_hotspot_state_could_not_be_read(net):
    for field in ("device", "hotspot", "radio"):
        net.device, net.hotspot, net.radio = ON, PROFILE, True
        setattr(net, field, None)
        assert check(net, "network.hotspot") == ("unknown", "The Wi-Fi state couldn't be read.", None)


def test_no_builtin_radio_is_unknown(net):
    net.kind = "missing"
    assert check(net, "network.hotspot") == ("unknown", "No built-in Wi-Fi radio was found.", None)


def test_a_missing_radio_is_not_hidden_by_the_failed_reads_it_causes(net):
    net.kind, net.device, net.hotspot, net.radio = "missing", None, None, None
    assert check(net, "network.hotspot") == ("unknown", "No built-in Wi-Fi radio was found.", None)


def test_a_usb_radio_leaves_the_hotspot_off(net):
    net.kind = "usb"
    assert check(net, "network.hotspot") == (
        "error",
        "A USB Wi-Fi adapter has taken the built-in radio's place, so the hotspot stays off. Unplug it and reboot.",
        None,
    )


def test_no_hotspot_profile_asks_for_the_installer(net):
    net.hotspot = False
    assert check(net, "network.hotspot") == ("error", "The hotspot isn't set up.", RUN_INSTALLER)


def test_a_hotspot_turned_off_by_choice_is_ok(net):
    net.hotspot = Hotspot(False, "TM-AB12", "wpa-psk", False)
    net.device = Device(30, None)
    assert check(net, "network.hotspot") == (
        "ok", "Off by choice. This unit has no wireless way in when its Wi-Fi network is missing.", None
    )


def test_a_radio_switched_off_asks_for_the_installer(net):
    net.radio = False
    assert check(net, "network.hotspot") == (
        "error", "The Wi-Fi radio is switched off, so the hotspot can't start.", RUN_INSTALLER
    )


def test_a_hotspot_with_no_password_is_an_error(net):
    net.hotspot = Hotspot(True, "TM-AB12", "", False)
    assert check(net, "network.hotspot") == (
        "error", "On as TM-AB12, with no password: anyone nearby can join it.", SET_A_PASSWORD
    )


def test_a_hotspot_secured_with_something_else_warns(net):
    net.hotspot = Hotspot(True, "TM-AB12", "sae", False)
    assert check(net, "network.hotspot") == ("warn", "On as TM-AB12, secured with sae rather than WPA2.", None)


def test_a_hotspot_without_its_firewall_is_an_error(net):
    net.firewall = "inactive"
    assert check(net, "network.hotspot") == (
        "error",
        "On as TM-AB12, but its firewall isn't loaded, so phones on it may reach your other networks. "
        "Reboot the device.",
        RUN_INSTALLER,
    )


def test_a_firewall_that_cant_be_read_is_unknown(net):
    net.firewall = None
    assert check(net, "network.hotspot") == ("unknown", "The Wi-Fi state couldn't be read.", None)


def test_the_hotspot_is_on(net):
    assert check(net, "network.hotspot") == ("ok", "On as TM-AB12, at http://10.42.0.1/.", None)


def test_the_hotspot_is_standing_by_while_a_saved_network_is_joined(net):
    net.device = Device(100, "Café 5G")
    assert check(net, "network.hotspot") == (
        "ok", "Standing by. It starts when Café 5G is out of reach.", None
    )


@pytest.mark.parametrize("state", [40, 50, 70, 90])
def test_a_radio_that_is_joining_a_network_is_ok(net, state):
    net.device = Device(state, None)
    assert check(net, "network.hotspot") == ("ok", "The radio is joining a network.", None)


def test_a_hotspot_that_should_be_on_offers_a_restart(net):
    net.device = Device(30, None)
    assert check(net, "network.hotspot") == ("error", "The hotspot should be on and isn't.", RESTART_HOTSPOT)


# The Wi-Fi network


def test_a_joined_network_shows_its_name_and_signal(net):
    net.device = Device(100, "Home")
    assert check(net, "network.wifi") == ("ok", "Home, signal 72%.", None)


def test_a_joined_network_without_a_readable_signal(net):
    net.device, net.signal = Device(100, "Home"), None
    assert check(net, "network.wifi") == ("ok", "Home.", None)


def test_no_saved_networks(net):
    net.device, net.saved = Device(30, None), 0
    assert check(net, "network.wifi") == ("ok", "No saved networks.", None)


def test_the_one_saved_network_is_not_in_reach(net):
    net.device, net.saved = Device(30, None), 1
    assert check(net, "network.wifi") == ("ok", "The saved network isn't in reach.", None)


def test_none_of_the_saved_networks_is_in_reach(net):
    net.saved = 3
    assert check(net, "network.wifi") == ("ok", "None of the 3 saved networks is in reach.", None)


def test_the_hotspot_is_not_a_joined_network(net):
    net.saved = 0
    assert check(net, "network.wifi")[1] == "No saved networks."


def test_an_unreadable_wifi_network_is_unknown(net):
    net.device = None
    assert check(net, "network.wifi") == ("unknown", "The Wi-Fi state couldn't be read.", None)
    net.device, net.saved = Device(30, None), None
    assert check(net, "network.wifi") == ("unknown", "The Wi-Fi state couldn't be read.", None)


# Internet


@pytest.mark.parametrize("value, detail", [
    ("full", "Reachable."),
    ("portal", "This network needs a sign-in page, so the unit has no internet."),
    ("limited", "Not reachable. That's normal for an offline unit."),
    ("none", "Not reachable. That's normal for an offline unit."),
])
def test_internet_answers(net, value, detail):
    net.connectivity = value
    assert check(net, "network.internet") == ("ok", detail, None)


def test_internet_is_never_a_warning_or_an_error(net):
    for value in ("full", "portal", "limited", "none"):
        net.connectivity = value
        assert check(net, "network.internet")[0] == "ok"


@pytest.mark.parametrize("value", ["unknown", None])
def test_internet_not_checked_yet(net, value):
    net.connectivity = value
    assert check(net, "network.internet") == ("unknown", "Not checked yet.", None)


# Wi-Fi country


def test_the_wifi_country_is_shown(net):
    net.country = "DE"
    assert check(net, "network.wifi_country") == ("ok", "DE.", None)


def test_an_unset_wifi_country_warns_and_names_the_cure(net):
    net.country = ""
    assert check(net, "network.wifi_country") == (
        "warn", "Not set. The radio uses limited worldwide settings until the country is set.", SET_THE_COUNTRY
    )


def test_an_unreadable_wifi_country_is_unknown(net):
    net.country = None
    assert check(net, "network.wifi_country") == ("unknown", "The Wi-Fi country couldn't be read.", None)


def test_unreadable_wifi_state_is_unknown_not_an_error(net):
    net.device = net.hotspot = net.radio = net.connectivity = net.country = None
    assert {c.status for c in report(net).checks} == {"unknown"}


# The adapter, against fake nmcli and iw on PATH


@pytest.fixture
def commands(tmp_path, monkeypatch):
    """A directory first on PATH for fake programs; add(name, script) writes one. A program that is not added is
    missing (the rest of PATH is kept off)."""
    directory = tmp_path / "bin"
    directory.mkdir()
    for tool in ("cat", "sleep"):  # the fakes' own needs; everything else on PATH stays out of reach
        (directory / tool).symlink_to(shutil.which(tool))
    monkeypatch.setenv("PATH", str(directory))

    def add(name, body):
        path = directory / name
        path.write_text("#!/bin/sh\n" + textwrap.dedent(body))
        path.chmod(path.stat().st_mode | stat.S_IXUSR)

    return add


def test_network_names_with_colons_are_read_whole(commands):
    commands("nmcli", r"""
        printf 'GENERAL.STATE:100 (connected)\nGENERAL.CONNECTION:Caf\\:e \\\\ 5G\nGENERAL.HWADDR:AA\\:BB\\:CC\n'
        """)
    assert network.device("wlan0") == Device(100, "Caf:e \\ 5G")


def test_a_device_with_no_connection_has_none(commands):
    commands("nmcli", "printf 'GENERAL.STATE:30 (disconnected)\\nGENERAL.CONNECTION:--\\n'")
    assert network.device("wlan0") == Device(30, None)


def test_unescape_handles_colons_and_backslashes():
    assert network.unescape(r"a\:b\\c") == "a:b\\c"


def test_a_missing_nmcli_reads_as_none(commands):
    assert network.device("wlan0") is None
    assert network.radio_enabled() is None
    assert network.hotspot("tm-hotspot") is None
    assert network.signal("wlan0") is None
    assert network.saved_networks() is None
    assert network.connectivity() is None
    assert network.wifi_country() is None


def test_a_failing_nmcli_reads_as_none(commands):
    commands("nmcli", "exit 3")
    assert network.device("wlan0") is None
    assert network.hotspot("tm-hotspot") is None


def test_a_slow_nmcli_reads_as_none(commands, monkeypatch):
    commands("nmcli", "sleep 5\necho enabled")
    monkeypatch.setattr(network, "TIMEOUT", 0.3)
    assert network.radio_enabled() is None


def test_no_such_profile_is_false_not_none(commands):
    commands("nmcli", "echo \"Error: unknown connection 'tm-hotspot'.\" >&2\nexit 10")
    assert network.hotspot("tm-hotspot") is False


def test_the_hotspot_profile_is_read_by_property(commands):
    commands("nmcli", """
        [ "$1" = "-g" ] && [ "$3" = connection ] && [ "$4" = show ] && [ "$5" = tm-hotspot ] || exit 2
        case "$2" in
          connection.autoconnect) echo yes ;;
          802-11-wireless.ssid) echo TM-AB12 ;;
          802-11-wireless-security.key-mgmt) echo wpa-psk ;;
          802-11-wireless.hidden) echo no ;;
          *) exit 2 ;;
        esac
        """)
    assert network.hotspot("tm-hotspot") == Hotspot(True, "TM-AB12", "wpa-psk", False)


def test_a_hotspot_with_no_security_has_an_empty_key_management(commands):
    # as real nmcli answers: no 802-11-wireless-security setting, so no line for it
    commands("nmcli", """
        case "$2" in
          connection.autoconnect) echo no ;;
          802-11-wireless.ssid) echo TM-AB12 ;;
        esac
        """)
    assert network.hotspot("tm-hotspot") == Hotspot(False, "TM-AB12", "", False)


def test_a_profile_missing_a_whole_setting_in_the_middle_keeps_the_values_apart(commands):
    # all of nmcli -g's lines for an absent setting are left out, whatever their place in the request
    commands("nmcli", """
        case "$2" in
          connection.autoconnect) echo yes ;;
          802-11-wireless-security.key-mgmt) echo wpa-psk ;;
        esac
        """)
    assert network.hotspot("tm-hotspot") == Hotspot(True, "", "wpa-psk", False)


def test_nmcli_is_never_asked_for_secrets(commands, tmp_path):
    log = tmp_path / "calls"
    commands("nmcli", f"echo \"$@\" >> {log}\necho yes")
    network.hotspot("tm-hotspot")
    network.saved_networks()
    assert "-s" not in log.read_text().split() and "--show-secrets" not in log.read_text()


@pytest.mark.parametrize("out, expected", [("enabled\n", True), ("disabled\n", False), ("what\n", None)])
def test_the_radio_switch(commands, out, expected):
    commands("nmcli", f"echo {out.strip()}")
    assert network.radio_enabled() is expected


def test_the_signal_is_the_in_use_rows(commands):
    commands("nmcli", "printf ' :45\\n*:78\\n :20\\n'")
    assert network.signal("wlan0") == 78


def test_no_signal_when_no_network_is_in_use(commands):
    commands("nmcli", "printf ' :45\\n'")
    assert network.signal("wlan0") is None


def test_saved_networks_counts_infrastructure_profiles_only(commands):
    commands("nmcli", """
        case "$*" in
          *"UUID,TYPE"*) printf 'u1:802-11-wireless\\nu2:802-11-wireless\\nu3:802-3-ethernet\\nu4:802-11-wireless\\n' ;;
          *"uuid u1") echo infrastructure ;;
          *"uuid u2") echo ap ;;
          *"uuid u4") echo infrastructure ;;
          *) exit 2 ;;
        esac
        """)
    assert network.saved_networks() == 2


@pytest.mark.parametrize("out, expected", [("full\n", "full"), ("portal\n", "portal"), ("\n", None)])
def test_connectivity(commands, out, expected):
    commands("nmcli", f"printf '{out.strip()}\\n'")
    assert network.connectivity() == expected


IW_SET = """global
country US: DFS-FCC
\t(2400 - 2472 @ 40), (N/A, 30), (N/A)

phy#0
country 99: DFS-UNSET
"""
IW_UNSET = IW_SET.replace("country US: DFS-FCC", "country 00: DFS-UNSET")


@pytest.mark.parametrize("text, expected", [(IW_SET, "US"), (IW_UNSET, "")])
def test_country_00_is_unset(commands, tmp_path, text, expected):
    (tmp_path / "reg").write_text(text)
    commands("iw", f"cat {tmp_path / 'reg'}")
    assert network.wifi_country() == expected


def test_an_iw_that_fails_without_netlink_reads_as_none(commands):
    commands("iw", "echo 'Failed to connect to generic netlink.' >&2\nexit 243")
    assert network.wifi_country() is None


def test_a_usb_radio_is_told_from_the_built_in_one(tmp_path):
    sys_net = tmp_path / "net"
    buses = tmp_path / "bus"
    for name in ("sdio", "usb"):
        (buses / name).mkdir(parents=True)
    for device, bus in (("wlan0", "sdio"), ("wlan1", "usb")):
        (sys_net / device / "wireless").mkdir(parents=True)
        (sys_net / device / "device").mkdir()
        (sys_net / device / "device" / "subsystem").symlink_to(buses / bus)
    (sys_net / "eth0").mkdir()
    assert network.radio_kind("wlan0", sys_net) == "builtin"
    assert network.radio_kind("wlan1", sys_net) == "usb"
    assert network.radio_kind("eth0", sys_net) == "missing"
    assert network.radio_kind("wlan9", sys_net) == "missing"
