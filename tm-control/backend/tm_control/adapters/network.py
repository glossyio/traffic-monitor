"""The Wi-Fi as NetworkManager and the kernel show it: the radio, the Wi-Fi device, the hotspot's profile, the
signal, the saved networks, internet reachability, and the regulatory country.

Everything is read; nothing is changed, and no secret is asked for (no `nmcli -s`). None of these raises: a command
that is missing, outlives TIMEOUT, or exits non-zero gives None.
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from tm_control.adapters.command import run

TIMEOUT = 3  # seconds for each command; these are status probes
MAX_OUTPUT = 65536
NO_SUCH_PROFILE = 10  # nmcli's exit status for a connection it doesn't know
WIFI = "802-11-wireless"
# yes and no, not a translation
ENV = {"LC_ALL": "C.UTF-8"}

RadioKind = Literal["builtin", "usb", "missing"]


def unescape(field: str) -> str:
    """A value as `nmcli -t` and `nmcli -g` print it: a backslash escapes the character after it (`:` and `\\`)."""
    return re.sub(r"\\(.)", r"\1", field)


def _run(argv: list[str]) -> tuple[int, str] | None:
    """(exit status, stdout), or None when the program is missing or timed out."""
    try:
        result = run(argv, timeout=TIMEOUT, max_output=MAX_OUTPUT, env=ENV)
    except OSError:
        return None
    if result.timed_out:
        return None
    return result.returncode, result.stdout


def _nmcli(*args: str) -> str | None:
    answer = _run(["nmcli", *args])
    if answer is None or answer[0] != 0:
        return None
    return answer[1]


def radio_kind(device: str, sys_net: Path = Path("/sys/class/net")) -> RadioKind:
    """Whether the Wi-Fi device is part of the unit, a USB adapter, or not there (no `wireless` directory)."""
    base = sys_net / device
    if not (base / "wireless").is_dir():
        return "missing"
    try:
        subsystem = (base / "device" / "subsystem").resolve()
    except OSError:
        return "builtin"
    return "usb" if subsystem.name == "usb" else "builtin"


def physical(name: str, sys_net: Path = Path("/sys/class/net")) -> bool:
    """Whether real hardware is behind the network device (a virtual one, such as a container's veth, has none)."""
    return (sys_net / name / "device").exists()


def radio_enabled() -> bool | None:
    out = _nmcli("radio", "wifi")
    if out is None:
        return None
    word = out.strip()
    return {"enabled": True, "disabled": False}.get(word)


@dataclass(frozen=True)
class Device:
    state: int  # NetworkManager's device state: 30 disconnected, 40 to 90 connecting, 100 connected
    connection: str | None  # the active profile's name; None when there is none


def device(name: str) -> Device | None:
    out = _nmcli("-t", "-f", "GENERAL.STATE,GENERAL.CONNECTION", "device", "show", name)
    if out is None:
        return None
    values = {}
    for line in out.splitlines():
        key, _, value = line.partition(":")
        values[key] = unescape(value)
    state = re.match(r"\d+", values.get("GENERAL.STATE", ""))
    if state is None:
        return None
    connection = values.get("GENERAL.CONNECTION", "")
    return Device(int(state.group()), None if connection in ("", "--") else connection)


@dataclass(frozen=True)
class Hotspot:
    autoconnect: bool
    ssid: str
    key_mgmt: str  # "" when the profile has no security
    hidden: bool  # the name is not broadcast


def hotspot(profile: str) -> Hotspot | None | Literal[False]:
    """The hotspot profile's settings; False when NetworkManager answered and has no such profile."""
    # One call per property: nmcli -g leaves out the lines of a setting the profile doesn't have (an open profile has
    # no 802-11-wireless-security), so with several properties in one call the values could not be told apart.
    values = []
    keys = ("connection.autoconnect", f"{WIFI}.ssid", f"{WIFI}-security.key-mgmt", f"{WIFI}.hidden")
    for key in keys:
        answer = _run(["nmcli", "-g", key, "connection", "show", profile])
        if answer is None:
            return None
        status, out = answer
        if status == NO_SUCH_PROFILE:
            return False
        if status != 0:
            return None
        values.append(unescape(out.split("\n")[0]))
    autoconnect, ssid, key_mgmt, hidden = values
    return Hotspot(autoconnect == "yes", ssid, key_mgmt, hidden == "yes")


def devices() -> list[tuple[str, str]] | None:
    """(name, type) of every network device NetworkManager knows, in its order: ("eth0", "ethernet")."""
    out = _nmcli("-t", "-f", "DEVICE,TYPE", "device", "status")
    if out is None:
        return None
    found = []
    for line in out.splitlines():
        name, _, kind = line.partition(":")
        if name:
            found.append((unescape(name), unescape(kind)))
    return found


@dataclass(frozen=True)
class Link:
    state: int  # NetworkManager's device state, as Device.state
    connection: str | None  # the active profile's name
    mac: str | None  # upper case, colons
    addresses: tuple[str, ...]  # IPv4, without the prefix length
    gateway: str | None
    dns: tuple[str, ...]


def _value(text: str) -> str | None:
    """A field's text unescaped, or None for what nmcli prints for nothing (empty, or `--` in older versions)."""
    value = unescape(text)
    return None if value in ("", "--") else value


def link(name: str) -> Link | None:
    fields = "GENERAL.HWADDR,GENERAL.STATE,GENERAL.CONNECTION,IP4.ADDRESS,IP4.GATEWAY,IP4.DNS"
    out = _nmcli("-t", "-f", fields, "device", "show", name)
    if out is None:
        return None
    single: dict[str, str | None] = {}
    addresses: list[str] = []
    dns: list[str] = []
    for line in out.splitlines():
        key, _, text = line.partition(":")
        key = re.sub(r"\[\d+\]$", "", key)
        value = _value(text)
        if value is None:
            continue
        if key == "IP4.ADDRESS":
            addresses.append(value.partition("/")[0])
        elif key == "IP4.DNS":
            dns.append(value)
        else:
            single[key] = value
    state = re.match(r"\d+", single.get("GENERAL.STATE") or "")
    if state is None:
        return None
    mac = single.get("GENERAL.HWADDR")
    return Link(
        int(state.group()),
        single.get("GENERAL.CONNECTION"),
        mac.upper() if mac else None,
        tuple(addresses),
        single.get("IP4.GATEWAY"),
        tuple(dns),
    )


def wifi_network(name: str) -> tuple[str, int | None] | None | Literal[False]:
    """(SSID, signal in percent) of the network the device is on; False when nmcli answered and it is on none.

    Meaningful only when a saved network is joined: on the hotspot, the list shows the hotspot itself as in use.
    """
    out = _nmcli("-t", "-f", "IN-USE,SIGNAL,SSID", "device", "wifi", "list", "ifname", name, "--rescan", "no")
    if out is None:
        return None
    for line in out.splitlines():
        in_use, _, rest = line.partition(":")
        if in_use != "*":
            continue
        strength, _, ssid = rest.partition(":")  # the SSID may hold colons of its own
        return unescape(ssid), int(strength) if strength.strip().isdigit() else None
    return False


def signal(name: str) -> int | None:
    """The signal strength (percent) of the network the device is on; None when it can't be read or it is on none."""
    out = _nmcli("-t", "-f", "IN-USE,SIGNAL", "device", "wifi", "list", "ifname", name, "--rescan", "no")
    if out is None:
        return None
    for line in out.splitlines():
        in_use, _, value = line.partition(":")
        if in_use == "*" and value.strip().isdigit():
            return int(value)
    return None


def saved_networks() -> int | None:
    """How many Wi-Fi profiles are in infrastructure mode (joined to a network), the hotspot's among none."""
    out = _nmcli("-t", "-f", "UUID,TYPE", "connection", "show")
    if out is None:
        return None
    count = 0
    for line in out.splitlines():
        uuid, _, kind = line.partition(":")
        if unescape(kind) != WIFI:
            continue
        mode = _nmcli("-g", f"{WIFI}.mode", "connection", "show", "uuid", uuid)
        if mode is None:
            return None
        count += mode.strip() == "infrastructure"
    return count


def connectivity() -> str | None:
    """NetworkManager's view of the internet: full, limited, portal, none, or unknown."""
    out = _nmcli("-t", "-f", "CONNECTIVITY", "general")
    if out is None:
        return None
    return out.strip() or None


COUNTRY_LINE = re.compile(r"^\s*country ([A-Z0-9]{2}):", re.MULTILINE)


def wifi_country() -> str | None:
    """The regulatory country from `iw reg get`'s first `country` line (the global one); "" when unset (00)."""
    answer = _run(["iw", "reg", "get"])
    if answer is None or answer[0] != 0:
        return None
    match = COUNTRY_LINE.search(answer[1])
    if match is None:
        return None
    return "" if match.group(1) == "00" else match.group(1)
