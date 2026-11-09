"""The status report: every module's checks, cached for a few seconds, and a rescan for admins."""

from tm_control.modules import Module
from tm_control.modules.status.router import router

module = Module("status", router)
