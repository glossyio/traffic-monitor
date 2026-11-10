"""The device's card: `sudo tm-control card` prints its addresses, its hotspot's name and password, and its setup code.

The hotspot password and the setup code are root-only files, so this is the one place a person can read them back.
Run as root it reads the manifest, the hotspot's name, the password file and the setup-code file first, and only then
opens the state database for the claim state, which drops to the state directory's owner (see claim_cli.open_state).
The card goes to stdout and nowhere else: nothing here logs, stores, or returns it to a caller that writes it down.
"""

import json
import os
import socket
from dataclasses import dataclass

from tm_control.adapters.network import hotspot
from tm_control.core.auth import Device
from tm_control.core.claim_cli import CommandError, open_state
from tm_control.core.manifest import ManifestError, load_manifest
from tm_control.core.settings import Settings

ALREADY_CLAIMED_STATUS = 3  # the status set-setup-code already uses for "claimed"
LABEL_WIDTH = 23  # the longest label, "Open on your network", and three spaces


@dataclass(frozen=True)
class Card:
    hostname: str
    local_url: str  # http://<hostname>.local/
    hotspot_name: str | None  # None: no hotspot profile (or, with hotspot_unreadable, NetworkManager didn't say)
    hotspot_password: str | None  # None: no password file; "": an adopted hotspot without a password
    hotspot_url: str  # http://<manifest.network.hotspot_address>/
    claimed: bool
    setup_code: str | None  # None once claimed, or when the file is missing
    hotspot_unreadable: bool = False  # NetworkManager didn't answer, so the profile's name is unknown


def _read(path) -> str | None:
    """A root-only file's text without its trailing newline, or None when it can't be read."""
    try:
        return path.read_text().strip("\r\n")
    except OSError:
        return None


def read_card(settings: Settings) -> Card:
    """Gather the card. Every file and nmcli answer is read while still root; the database is opened last."""
    try:
        manifest = load_manifest(settings.manifest_path)
    except ManifestError as error:
        raise CommandError(str(error)) from None
    profile = hotspot(manifest.network.hotspot_profile)
    password = _read(settings.secrets_dir / "hotspot_password") if profile is not False else None
    code = (_read(settings.setup_code_file) or "").strip() or None
    claimed = Device(open_state(settings)).is_claimed()
    hostname = socket.gethostname()
    return Card(
        hostname=hostname,
        local_url=f"http://{hostname}.local/",
        hotspot_name=profile.ssid if profile else None,
        hotspot_password=password,
        hotspot_url=f"http://{manifest.network.hotspot_address}/",
        claimed=claimed,
        setup_code=None if claimed else code,
        hotspot_unreadable=profile is None,
    )


def _line(label: str, text: str) -> str:
    return f"  {label:<{LABEL_WIDTH}}{text}"


def render(card: Card) -> str:
    lines = [f"Traffic Monitor {card.hostname}", _line("Open on your network", card.local_url)]
    if card.hotspot_unreadable:
        lines.append(_line("Hotspot name", "Unknown. NetworkManager did not answer."))
    elif card.hotspot_name is None:
        lines.append(_line("Hotspot name", "Not set up. Run tmsetup.sh -t wifi."))
    else:
        lines.append(_line("Hotspot name", card.hotspot_name))
    if card.hotspot_name is not None or card.hotspot_unreadable:
        if card.hotspot_password is None:
            lines.append(_line("Hotspot password", "Not stored on this device."))
        elif card.hotspot_password == "":
            lines.append(_line("Hotspot password", "None. Anyone nearby can join."))
        else:
            lines.append(_line("Hotspot password", card.hotspot_password))
        lines.append(_line("Open on the hotspot", f"{card.hotspot_url} (a phone that joins opens it by itself)"))
    if card.claimed:
        lines.append(_line("Setup code", "Already claimed."))
    elif card.setup_code is None:
        lines.append(_line("Setup code", "Missing. Run tmsetup.sh again to get one."))
    else:
        lines.append(_line("Setup code", f"{card.setup_code} (works once)"))
    return "\n".join(lines) + "\n"


def render_json(card: Card) -> str:
    has_hotspot = card.hotspot_name is not None or card.hotspot_unreadable
    return json.dumps(
        {
            "hostname": card.hostname,
            "local_url": card.local_url,
            "hotspot": (
                {"name": card.hotspot_name, "password": card.hotspot_password, "url": card.hotspot_url}
                if has_hotspot
                else None
            ),
            "claimed": card.claimed,
            "setup_code": card.setup_code,
        },
        indent=2,
    ) + "\n"


def card(settings: Settings, as_json: bool = False, unclaimed_only: bool = False) -> int:
    if os.geteuid() != 0:
        raise CommandError("card must run as root: sudo tm-control card", exit_code=2)
    result = read_card(settings)
    if unclaimed_only and result.claimed:
        return ALREADY_CLAIMED_STATUS
    print(render_json(result) if as_json else render(result), end="")
    return 0
