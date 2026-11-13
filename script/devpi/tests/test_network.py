"""The Wi-Fi hotspot: its profile, password file, firewall, DNS, retry timer, country, and the sign-in redirect.

The checks that call the hotspot's address need the unit's radio to be on the hotspot, and are skipped, with a message,
when it is on a saved network. None of these changes the unit's Wi-Fi. The hotspot's password never reaches a test: the
password file is checked with stat, and the device card test prints only its keys and the password's length.
"""

import json
import re
import shlex

import pytest
from devpi_checks import API, role_vars

VARS = role_vars()
PROFILE = VARS["tmsetup_hotspot_profile"]
DEVICE = VARS["tmsetup_wifi_device"]
ADDRESS = VARS["tmsetup_hotspot_address"]
SUBNET = VARS["tmsetup_hotspot_subnet"]
PASSWORD_FILE = f"{VARS['tmsetup_secrets_dir']}/hotspot_password"
RETRY_STATE = "/run/traffic-monitor/network-retry.json"
CARD_KEYS = ["claimed", "hostname", "hotspot", "local_url", "setup_code"]
HOTSPOT_KEYS = ["name", "password", "url"]
PASSWORD_LENGTH = 14  # XXXX-XXXX-XXXX, which the installer makes


@pytest.fixture(scope="module")
def radio(usable_host):
    """What the Wi-Fi radio is doing: "hotspot", "network" (joined to a saved network), or "idle" (neither)."""
    output = usable_host.run(f"sudo nmcli -t -f GENERAL.CONNECTION device show {DEVICE}").stdout.strip()
    connection = output.partition(":")[2].strip()
    if connection == PROFILE:
        return "hotspot"
    return "idle" if connection in ("", "--") else "network"


def require_hotspot(radio):
    if radio != "hotspot":
        pytest.skip(f"the radio is {'on a saved network' if radio == 'network' else 'not connected'}, not on the "
                    f"hotspot, so {ADDRESS} isn't an address of this unit")


def test_the_hotspot_profile_has_the_fixed_address_and_yields_to_saved_networks(host):
    """-g prints one value per line, in the order asked for; no secrets are requested."""
    fields = ["ipv4.method", "ipv4.addresses", "connection.autoconnect-priority", "connection.interface-name",
              "ipv6.method"]
    result = host.run(f"sudo nmcli -g {','.join(fields)} connection show {PROFILE}")
    assert result.rc == 0, f"no connection profile {PROFILE}: {result.stderr.strip()[:200]}"
    found = dict(zip(fields, result.stdout.splitlines()))
    expected = {"ipv4.method": "shared", "ipv4.addresses": f"{ADDRESS}/{SUBNET.split('/')[1]}",
                "connection.autoconnect-priority": "-100", "connection.interface-name": DEVICE,
                "ipv6.method": "disabled"}
    assert found == expected, f"the {PROFILE} profile's settings (found, expected): {found}, {expected}"


def test_the_hotspot_password_file_is_for_root_and_the_code_group(host, hostvars, codeowner):
    """Only its owner, group, and mode are read: stat prints no contents."""
    group = hostvars.get("tmsetup_codegroup", codeowner)
    found = host.run(f"sudo stat -c '%U %G %a' {PASSWORD_FILE}")
    assert found.rc == 0, f"{PASSWORD_FILE}: {found.stderr.strip()[:200]}"
    assert found.stdout.strip() == f"root {group} 640", (
        f"{PASSWORD_FILE}'s owner, group, and mode are {found.stdout.strip()}, not root {group} 640")


def test_the_hotspot_firewall_is_loaded(host):
    """Phones on the hotspot reach this unit and nothing behind it: one drop rule for each direction."""
    table = host.run("sudo nft list table inet tm_hotspot")
    assert table.rc == 0, f"table inet tm_hotspot isn't loaded: {table.stderr.strip()[:200]}"
    escaped = re.escape(SUBNET)
    rules = [rf'iifname "{DEVICE}" ip saddr {escaped} drop', rf'oifname "{DEVICE}" ip daddr {escaped} drop']
    missing = [rule for rule in rules if not re.search(rule, table.stdout)]
    assert not missing, f"the table has no rule matching {missing}"
    unit = "tm-hotspot-firewall.service"
    found = (host.run(f"systemctl is-active {unit}").stdout.strip(),
             host.run(f"systemctl is-enabled {unit}").stdout.strip())
    assert found == ("active", "enabled"), f"{unit} is (active, enabled) = {found}"


def test_every_name_resolves_to_the_unit_on_the_hotspot(host):
    with host.sudo():
        lines = host.file("/etc/NetworkManager/dnsmasq-shared.d/tm-hotspot.conf").content_string.splitlines()
    assert f"address=/#/{ADDRESS}" in lines, f"tm-hotspot.conf's lines are {lines}"


def test_the_retry_timer_is_waiting(host):
    """The timer waits for its next run, the last run succeeded, and the state file it keeps in /run (the networks
    that failed lately and the last run's outcome) is JSON that names no key."""
    timer = "tm-network-retry.timer"
    output = host.check_output(f"systemctl show -p ActiveState -p SubState {timer}")
    state = dict(line.split("=", 1) for line in output.splitlines())
    assert (state.get("ActiveState"), state.get("SubState")) == ("active", "waiting"), (
        f"{timer}'s state (active, sub) is {(state.get('ActiveState'), state.get('SubState'))}")
    result = host.check_output("systemctl show -p Result --value tm-network-retry.service")
    assert result == "success", f"tm-network-retry.service's last result is {result}"
    state_file = host.run(f"cat {RETRY_STATE}")
    assert state_file.rc == 0, f"{RETRY_STATE} doesn't exist: the retry service hasn't run since boot"
    assert "psk" not in state_file.stdout.lower(), f"{RETRY_STATE} mentions a key"
    document = json.loads(state_file.stdout)
    assert isinstance(document, dict) and "last_run" in document, f"{RETRY_STATE}'s keys are {sorted(document)}"


def test_the_wifi_country_is_set(host):
    """The regulatory domain is a real country, not the world domain (00) a radio uses with none set."""
    output = host.check_output("/usr/sbin/iw reg get")
    countries = re.findall(r"^country ([A-Z0-9]{2}):", output, re.MULTILINE)
    assert countries, f"iw reg get names no country: {output.strip()[:200]}"
    assert countries[0] != "00", "the Wi-Fi country is 00 (not set): run tmsetup.sh -t wifi -w <country>"


def test_the_old_wifi_check_is_gone(host, codedir, codeowner):
    crontab = host.run(f"sudo crontab -l -u {shlex.quote(codeowner)}")
    assert "Traffic Monitor Wifi Check" not in crontab.stdout, f"{codeowner}'s crontab still has the old Wi-Fi check"
    leftovers = [path for path in (f"/etc/sudoers.d/{codeowner}", f"{codedir}/utils/wlan_check.sh",
                                   f"{codedir}/utils/network-wlan-ap")
                 if host.run(f"sudo test -e {shlex.quote(path)}").rc == 0]
    assert not leftovers, f"left over from the old Wi-Fi check: {leftovers}"


def curl_on_the_pi(host, url, host_header=None, extra=()):
    """(HTTP status, redirect target, body) of a request the Pi makes to itself."""
    header = f"-H {shlex.quote('Host: ' + host_header)} " if host_header else ""
    result = host.run(f"curl -s --max-time 10 {header}{' '.join(extra)} -w '\\n%{{http_code}} %{{redirect_url}}' {url}")
    body, _, trailer = result.stdout.rpartition("\n")
    status, _, target = trailer.partition(" ")
    return status, target, body


def test_a_foreign_host_is_redirected_only_on_the_hotspot_address(host, radio):
    """A phone's connection test asks the hotspot address for a name that isn't the unit's; the redirect opens the
    phone's sign-in window. The same request over loopback, or for the unit's address, is not redirected."""
    require_hotspot(radio)
    foreign = curl_on_the_pi(host, f"http://{ADDRESS}/", "example.com")[:2]
    foreign_on_loopback = curl_on_the_pi(host, "http://127.0.0.1/", "example.com")[0]
    own = curl_on_the_pi(host, f"http://{ADDRESS}/", ADDRESS)[0]
    assert (foreign, foreign_on_loopback, own) == (("302", f"http://{ADDRESS}/"), "200", "200"), (
        f"Host example.com to {ADDRESS}, to 127.0.0.1, and Host {ADDRESS} to {ADDRESS} answered "
        f"{(foreign, foreign_on_loopback, own)}")


def test_setup_status_names_the_hotspot_only_on_its_address(host, radio):
    """The hotspot's local name is for a phone that joined it: it comes only over the hotspot address, and a request
    can't ask for it by sending its own X-TM-Hotspot header."""
    require_hotspot(radio)
    url = f"{API}/setup/status"
    answers = {}
    for label, address, extra in (("hotspot", ADDRESS, ()), ("loopback", "127.0.0.1", ()),
                                  ("loopback with the header", "127.0.0.1", ("-H 'X-TM-Hotspot: 1'",))):
        status, _, body = curl_on_the_pi(host, f"http://{address}{url}", extra=extra)
        assert status == "200", f"GET {url} over {label} answered {status}"
        answers[label] = json.loads(body).get("hotspot")
    assert isinstance(answers["hotspot"], dict) and answers["hotspot"].get("local_name"), (
        f"GET {url} over {ADDRESS} has hotspot {answers['hotspot']!r}, not a local_name")
    assert (answers["loopback"], answers["loopback with the header"]) == (None, None), (
        f"GET {url} over loopback names the hotspot: {answers['loopback']!r}, with the header "
        f"{answers['loopback with the header']!r}")


# Prints the card's keys and the password's length, never a value: the test log keeps everything a command prints.
CARD_SUMMARY = (
    "import json, sys\n"
    "card = json.load(sys.stdin)\n"
    "hotspot = card.get('hotspot') or {}\n"
    "print(' '.join(sorted(card)))\n"
    "print(' '.join(sorted(hotspot)))\n"
    "print(len(hotspot.get('password') or ''))\n"
)


def test_the_device_card_names_the_hotspot_and_never_reaches_the_log(host):
    """sudo tm-control card --json has the card's five keys, the hotspot's three, and the 14-character password the
    installer made; without sudo it exits 2. The card goes through a pipe to a script that prints only the keys and
    the length, so no value (the password or the setup code) enters the test log."""
    summary = host.run(f"sudo tm-control card --json | python3 -c {shlex.quote(CARD_SUMMARY)}")
    assert summary.rc == 0, f"reading the card failed with exit {summary.rc}: {summary.stderr.strip()[:200]}"
    keys, hotspot_keys, length = summary.stdout.splitlines()
    assert (keys, hotspot_keys, length) == (" ".join(CARD_KEYS), " ".join(HOTSPOT_KEYS), str(PASSWORD_LENGTH)), (
        f"the card's keys, the hotspot's keys, and the password's length are {(keys, hotspot_keys, length)}; "
        f"a hotspot that was already there before the installer may have another password length")
    without_sudo = host.run("tm-control card --json")
    assert without_sudo.rc == 2, f"tm-control card without sudo exited {without_sudo.rc}, not 2"
