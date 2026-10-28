"""The device: the home page's device card and app tiles, the Device page's facts and diagnostics, reboot and power
off, the installing user's Linux password, and the device checks in the status report."""

from tm_control.modules import Module
from tm_control.modules.system.checks import GROUP
from tm_control.modules.system.router import router

module = Module("system", router, check_groups=(GROUP,))
