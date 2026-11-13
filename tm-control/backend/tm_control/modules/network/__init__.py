"""The unit's network: the details the Network page shows (GET /network: Ethernet, Wi-Fi, the internet, and the
hotspot), and the network checks of the status report (the hotspot, the Wi-Fi network, the internet, and the Wi-Fi
country)."""

from tm_control.modules import Module
from tm_control.modules.network.checks import GROUP
from tm_control.modules.network.router import router

module = Module("network", router, check_groups=(GROUP,))
