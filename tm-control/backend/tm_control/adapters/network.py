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


def hotspot(profile: str) -> Hotspot | None | Literal[False]:
    """The hotspot profile's settings; False when NetworkManager answered and has no such profile."""
    keys = f"connection.autoconnect,{WIFI}.ssid,{WIFI}-security.key-mgmt"
    answer = _run(["nmcli", "-g", keys, "connection", "show", profile])
    if answer is None:
        return None
    status, out = answer
    if status == NO_SUCH_PROFILE:
        return False
    if status != 0:
        return None
    # -g prints each value on its own line, in the order asked for; an unset one is an empty line
    lines = out.split("\n")
    autoconnect, ssid, key_mgmt = (unescape(lines[i]) if i < len(lines) else "" for i in range(3))
    return Hotspot(autoconnect == "yes", ssid, key_mgmt)


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
