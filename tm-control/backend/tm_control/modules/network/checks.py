"""The network check group: whether the unit's own Wi-Fi hotspot is up when it should be, which Wi-Fi network it
is on, whether the internet is reachable, and the Wi-Fi country.

An offline unit is normal, so the internet is never a warning or an error. A read that fails is `unknown`, never an
error. Within a check, the first row that applies is the answer.
"""

from tm_control.adapters import network, systemd
from tm_control.core.checks import Check, CheckGroup, Context, Fix

RETRY_UNIT = "tm-network-retry.service"
FIREWALL_UNIT = "tm-hotspot-firewall.service"
RESTART_HOTSPOT = Fix(kind="restart", text="Restart the hotspot", unit=RETRY_UNIT)
RUN_INSTALLER = Fix(kind="hint", text="Run the installer again (tmsetup.sh -t wifi).")
SET_A_PASSWORD = Fix(kind="link", text="Set a password", href="/network")
SET_THE_COUNTRY = Fix(kind="hint", text="Run the installer again (tmsetup.sh -t wifi); it asks for the country.")

UNREADABLE = "The Wi-Fi state couldn't be read."
JOINING = range(40, 91)  # NetworkManager's device states from preparing to getting an address
CONNECTED = 100


def _device(context: Context):
    return context.probe("network.device", lambda: network.device(context.manifest.network.wifi_device))


def _hotspot(context: Context):
    return context.probe("network.hotspot", lambda: network.hotspot(context.manifest.network.hotspot_profile))


def _radio(context: Context):
    return context.probe("network.radio", network.radio_enabled)


def _firewall_state() -> str | None:
    try:
        return systemd.show_unit(FIREWALL_UNIT, ["ActiveState"])["ActiveState"]
    except (OSError, RuntimeError):
        return None


def hotspot(context: Context) -> list[Check]:
    def check(status, detail, fix=None):
        return [Check(id="network.hotspot", title="Hotspot", status=status, detail=detail, fix=fix)]

    info = context.manifest.network
    # Without the built-in radio the reads below fail, so say why first.
    kind = network.radio_kind(info.wifi_device)
    if kind == "missing":
        return check("unknown", "No built-in Wi-Fi radio was found.")
    if kind == "usb":
        return check(
            "error",
            "A USB Wi-Fi adapter has taken the built-in radio's place, so the hotspot stays off. "
            "Unplug it and reboot.",
        )
    device, profile, radio = _device(context), _hotspot(context), _radio(context)
    if device is None or profile is None or radio is None:
        return check("unknown", UNREADABLE)
    if profile is False:
        return check("error", "The hotspot isn't set up.", RUN_INSTALLER)
    if not profile.autoconnect:
        return check("ok", "Off by choice. This unit has no wireless way in when its Wi-Fi network is missing.")
    if not radio:
        return check("error", "The Wi-Fi radio is switched off, so the hotspot can't start.", RUN_INSTALLER)
    if device.state == CONNECTED and device.connection == info.hotspot_profile:
        name = profile.ssid
        if not profile.key_mgmt:
            return check("error", f"On as {name}, with no password: anyone nearby can join it.", SET_A_PASSWORD)
        if profile.key_mgmt != "wpa-psk":
            return check("warn", f"On as {name}, secured with {profile.key_mgmt} rather than WPA2.")
        firewall = _firewall_state()
        if firewall is None:
            return check("unknown", UNREADABLE)
        if firewall != "active":
            return check(
                "error",
                f"On as {name}, but its firewall isn't loaded, so phones on it may reach your other networks. "
                "Reboot the device.",
                RUN_INSTALLER,
            )
        return check("ok", f"On as {name}, at http://{info.hotspot_address}/.")
    if device.state == CONNECTED and device.connection is not None:
        return check("ok", f"Standing by. It starts when {device.connection} is out of reach.")
    if device.state in JOINING:
        return check("ok", "The radio is joining a network.")
    return check("error", "The hotspot should be on and isn't.", RESTART_HOTSPOT)


def wifi(context: Context) -> list[Check]:
    def check(status, detail):
        return [Check(id="network.wifi", title="Wi-Fi network", status=status, detail=detail)]

    info = context.manifest.network
    device = _device(context)
    if device is None:
        return check("unknown", UNREADABLE)
    if device.state == CONNECTED and device.connection not in (None, info.hotspot_profile):
        strength = network.signal(info.wifi_device)
        return check("ok", f"{device.connection}, signal {strength}%." if strength is not None
                     else f"{device.connection}.")
    saved = network.saved_networks()
    if saved is None:
        return check("unknown", UNREADABLE)
    if saved == 0:
        return check("ok", "No saved networks.")
    if saved == 1:
        return check("ok", "The saved network isn't in reach.")
    return check("ok", f"None of the {saved} saved networks is in reach.")


def internet(context: Context) -> list[Check]:
    def check(status, detail):
        return [Check(id="network.internet", title="Internet", status=status, detail=detail)]

    value = network.connectivity()
    if value == "full":
        return check("ok", "Reachable.")
    if value == "portal":
        return check("ok", "This network needs a sign-in page, so the unit has no internet.")
    if value in ("limited", "none"):
        return check("ok", "Not reachable. That's normal for an offline unit.")
    return check("unknown", "Not checked yet.")


def wifi_country(context: Context) -> list[Check]:
    def check(status, detail, fix=None):
        return [Check(id="network.wifi_country", title="Wi-Fi country", status=status, detail=detail, fix=fix)]

    country = network.wifi_country()
    if country is None:
        return check("unknown", "The Wi-Fi country couldn't be read.")
    if country == "":
        return check(
            "warn", "Not set. The radio uses limited worldwide settings until the country is set.", SET_THE_COUNTRY
        )
    return check("ok", f"{country}.")


GROUP = CheckGroup("network", "Network", [hotspot, wifi, internet, wifi_country])
