"""The Traffic Monitor units: their state, a restart for admins, and the services checks in the status report."""

from tm_control.modules import Module
from tm_control.modules.services.checks import GROUP
from tm_control.modules.services.router import router

module = Module("services", router, check_groups=(GROUP,))
