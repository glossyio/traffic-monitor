"""The Wi-Fi networks as the Network page's join section shows them: the ones the unit has saved, in the order it tries
them, and the ones its last scan heard.

Read only, and never a password. The scan is root's network job's file (network-scan.json) and the failures are the
retry's (network-retry.json), both in settings.network_run_dir. A file that is missing, unreadable, or not in its form
reads as "none", never as an error, and NetworkManager's sentences are never read: a saved network is what `saved_wifi`
returns and the one in use is the profile's UUID.
"""

import json
import math
import time
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from tm_control.adapters import network

Security = Literal["password", "wpa3", "enterprise", "open", "other"]
SECURITIES = ("password", "wpa3", "enterprise", "open", "other")
SCAN_FILE = "network-scan.json"
RETRY_FILE = "network-retry.json"


class Saved(BaseModel):
    uuid: str
    name: str  # the network's name
    in_use: bool
    automatic: bool  # joins by itself; False: saved with autoconnect off, and not part of the order
    hidden: bool
    in_range: bool | None  # heard in the last scan; None: no scan yet
    could_not_join: bool  # the retry has a failure on record for it


class Nearby(BaseModel):
    name: str
    signal: int  # percent
    security: Security
    saved: bool
    in_use: bool


class WifiNetworks(BaseModel):
    readable: bool  # False: NetworkManager didn't answer
    radio: Literal["on", "off", "none"]  # none: no built-in radio
    saved: list[Saved]  # the ordered ones first, then those that don't join by themselves
    nearby: list[Nearby]  # strongest first
    scanned_seconds_ago: int | None  # None: no scan since the unit started


def _number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _json(path: Path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):  # missing, unreadable, or not JSON (a bad encoding is a ValueError too)
        return None


def _network(entry) -> bool:
    return (
        isinstance(entry, dict)
        and isinstance(entry.get("ssid"), str)
        and isinstance(entry.get("signal"), int)
        and not isinstance(entry["signal"], bool)
        and 0 <= entry["signal"] <= 100
        and entry.get("security") in SECURITIES
    )


def read_scan(run_dir: Path) -> tuple[list[dict], float] | None:
    """The last scan's networks (strongest first) and the monotonic time the job wrote them; None when the file is
    missing, unreadable, not in its form, or from another boot (a time still to come)."""
    scan = _json(run_dir / SCAN_FILE)
    if not isinstance(scan, dict) or not _number(scan.get("monotonic")):
        return None
    networks = scan.get("networks")
    if not isinstance(networks, list) or not all(_network(entry) for entry in networks):
        return None
    if scan["monotonic"] > time.monotonic():
        return None
    return sorted(networks, key=lambda entry: -entry["signal"]), float(scan["monotonic"])


def _failed(run_dir: Path) -> set[str]:
    """The UUIDs of the saved networks the retry has a failure on record for."""
    state = _json(run_dir / RETRY_FILE)
    networks = state.get("networks") if isinstance(state, dict) else None
    if not isinstance(networks, dict):
        return set()
    return {
        uuid
        for uuid, entry in networks.items()
        if isinstance(entry, dict)
        and isinstance(entry.get("failures"), int)
        and not isinstance(entry["failures"], bool)
        and entry["failures"] >= 1
    }


def _nearby(scan: list[dict], saved: list[Saved]) -> list[Nearby]:
    saved_names = {n.name for n in saved}
    in_use = {n.name for n in saved if n.in_use}
    return [
        Nearby(
            name=entry["ssid"],
            signal=entry["signal"],
            security=entry["security"],
            saved=entry["ssid"] in saved_names,
            in_use=entry["ssid"] in in_use,
        )
        for entry in scan
    ]


def _ordered(saved: list[Saved]) -> list[Saved]:
    return [n for n in saved if n.automatic] + [n for n in saved if not n.automatic]


def choices(app_state) -> list[tuple[str, str, bool]] | None:
    """The saved networks as (uuid, name, automatic); None when NetworkManager didn't answer."""
    if app_state.fake_network is not None:
        return [(n["uuid"], n["name"], n["automatic"]) for n in app_state.fake_network.saved]
    found = network.saved_wifi()
    return None if found is None else [(n.uuid, n.ssid, n.autoconnect) for n in found]


def _fake(app_state) -> WifiNetworks:
    fake = app_state.fake_network
    saved = [Saved(**n) for n in fake.saved]
    return WifiNetworks(
        readable=True,
        radio="on",
        saved=_ordered(saved),
        nearby=_nearby([{"ssid": n["name"], **n} for n in fake.nearby], saved),
        scanned_seconds_ago=None if fake.scanned is None else max(0, int(time.monotonic() - fake.scanned)),
    )


def read_wifi(app_state) -> WifiNetworks:
    if app_state.fake_network is not None:
        return _fake(app_state)
    info = app_state.manifest.network
    if network.radio_kind(info.wifi_device) != "builtin":
        radio = "none"
    else:
        radio = "off" if network.radio_enabled() is False else "on"
    found = network.saved_wifi()
    if found is None:
        return WifiNetworks(readable=False, radio=radio, saved=[], nearby=[], scanned_seconds_ago=None)
    run_dir = app_state.settings.network_run_dir
    scan = read_scan(run_dir)
    heard = None if scan is None else {entry["ssid"] for entry in scan[0]}
    active = network.active_uuid(info.wifi_device)
    failed = _failed(run_dir)
    saved = [
        Saved(
            uuid=n.uuid,
            name=n.ssid,
            in_use=isinstance(active, str) and n.uuid == active,
            automatic=n.autoconnect,
            hidden=n.hidden,
            in_range=None if heard is None else (not n.hidden and n.ssid in heard),
            could_not_join=n.uuid in failed,
        )
        for n in found
    ]
    saved = _ordered(saved)
    if scan is None:
        return WifiNetworks(readable=True, radio=radio, saved=saved, nearby=[], scanned_seconds_ago=None)
    return WifiNetworks(
        readable=True,
        radio=radio,
        saved=saved,
        nearby=_nearby(scan[0], saved),
        scanned_seconds_ago=max(0, int(time.monotonic() - scan[1])),
    )
