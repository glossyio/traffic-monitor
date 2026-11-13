"""The Wi-Fi: the hotspot, the Wi-Fi network, the internet, and the Wi-Fi country, in the status report's network
checks. Read-only, and no API of its own yet."""

from fastapi import APIRouter

from tm_control.modules import Module
from tm_control.modules.network.checks import GROUP

module = Module("network", APIRouter(prefix="/network", tags=["network"]), check_groups=(GROUP,))
