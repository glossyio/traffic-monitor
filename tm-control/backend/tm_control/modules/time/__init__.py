"""The device's date and time: its state (any user), setting it from the browser, the time zone, and NTP (admins),
and the time checks in the status report."""

from tm_control.modules import Module
from tm_control.modules.time.checks import GROUP
from tm_control.modules.time.router import router

module = Module("time", router, check_groups=(GROUP,))
