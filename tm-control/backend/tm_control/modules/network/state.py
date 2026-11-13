"""The unit's network as the Network page shows it: the Ethernet and Wi-Fi links, the internet, and the hotspot.

Read only, and never a password. An answer NetworkManager doesn't give is shown as missing, not as an error: the page
says "unknown", and the status report has its own checks.
"""

from typing import Literal

from pydantic import BaseModel

from tm_control.adapters import network

CONNECTED = 100  # NetworkManager's device state
JOINING = range(40, 91)  # from preparing to getting an address
INTERNET = {
    "full": "reachable",
    "portal": "sign_in_page",
    "limited": "not_reachable",
    "none": "not_reachable",
}


class Link(BaseModel):
    connected: bool
    mac: str | None
    addresses: list[str]
    gateway: str | None
    dns: list[str]


class Wifi(Link):
    mode: Literal["network", "hotspot", "joining", "idle", "off"]
    network: str | None  # the joined network's name; None unless mode is "network"
    signal: int | None  # percent


class HotspotState(BaseModel):
    enabled: bool  # starts by itself
    active: bool  # up now
    name: str
    hidden: bool
    security: Literal["wpa2", "none", "other"]
    address: str  # the manifest's hotspot address


class NetworkState(BaseModel):
    hostname: str
    local_name: str  # "<hostname>.local"
    readable: bool  # False: NetworkManager didn't answer, and the rest is empty
    ethernet: Link | None  # None: the unit has no Ethernet device
    wifi: Wifi | None  # None: no built-in Wi-Fi radio
    internet: Literal["reachable", "not_reachable", "sign_in_page", "unknown"]
    hotspot: HotspotState | None  # None: not set up


def _link(found: network.Link | None) -> Link:
    if found is None:
        return Link(connected=False, mac=None, addresses=[], gateway=None, dns=[])
    return Link(
        connected=found.state == CONNECTED,
        mac=found.mac,
        addresses=list(found.addresses),
        gateway=found.gateway,
        dns=list(found.dns),
    )


def _ethernet(devices: list[tuple[str, str]]) -> Link | None:
    for name, kind in devices:
        if kind == "ethernet" and network.physical(name):
            return _link(network.link(name))
    return None


def _wifi(device: str, profile: str) -> Wifi | None:
    if network.radio_kind(device) != "builtin":
        return None
    found = network.link(device)
    link = _link(found)
    network_name = signal = None
    if network.radio_enabled() is False:
        mode = "off"
    elif found is not None and found.state == CONNECTED and found.connection == profile:
        mode = "hotspot"
    elif found is not None and found.state == CONNECTED and found.connection is not None:
        mode = "network"
        read = network.wifi_network(device)
        ssid, signal = read if read else ("", None)
        network_name = ssid or found.connection
    elif found is not None and found.state in JOINING:
        mode = "joining"
    else:
        mode = "idle"
    return Wifi(**link.model_dump(), mode=mode, network=network_name, signal=signal)


def _hotspot(profile: str, address: str, active: bool) -> HotspotState | None:
    found = network.hotspot(profile)
    if not found:
        return None
    security = "wpa2" if found.key_mgmt == "wpa-psk" else "none" if not found.key_mgmt else "other"
    return HotspotState(
        enabled=found.autoconnect,
        active=active,
        name=found.ssid,
        hidden=found.hidden,
        security=security,
        address=address,
    )


def _fake_state(app_state, hostname: str) -> NetworkState:
    """Fake mode: Ethernet connected, and the Wi-Fi on the hotspot while it is up."""
    hotspot = HotspotState(**app_state.fake_network.hotspot)
    mac = "00:00:5E:00:53:02"
    if hotspot.active:
        wifi = Wifi(
            connected=True, mac=mac, addresses=[hotspot.address], gateway=None, dns=[], mode="hotspot",
            network=None, signal=None,
        )
    else:
        wifi = Wifi(
            connected=False, mac=mac, addresses=[], gateway=None, dns=[], mode="idle", network=None, signal=None
        )
    return NetworkState(
        hostname=hostname,
        local_name=f"{hostname}.local",
        readable=True,
        ethernet=Link(
            connected=True, mac="00:00:5E:00:53:01", addresses=["192.168.1.57"], gateway="192.168.1.1",
            dns=["192.168.1.1"],
        ),
        wifi=wifi,
        internet="reachable",
        hotspot=hotspot,
    )


def read_state(app_state, hostname: str) -> NetworkState:
    local_name = f"{hostname}.local"
    if app_state.fake_network is not None:
        return _fake_state(app_state, hostname)
    info = app_state.manifest.network
    devices = network.devices()
    if devices is None:
        return NetworkState(
            hostname=hostname,
            local_name=local_name,
            readable=False,
            ethernet=None,
            wifi=None,
            internet="unknown",
            hotspot=None,
        )
    wifi = _wifi(info.wifi_device, info.hotspot_profile)
    return NetworkState(
        hostname=hostname,
        local_name=local_name,
        readable=True,
        ethernet=_ethernet(devices),
        wifi=wifi,
        internet=INTERNET.get(network.connectivity() or "", "unknown"),
        hotspot=_hotspot(info.hotspot_profile, info.hotspot_address, wifi is not None and wifi.mode == "hotspot"),
    )
