"""First run: the EULA and claiming the device with its setup code."""

from tm_control.modules import Module
from tm_control.modules.setup.router import router

module = Module("setup", router)
