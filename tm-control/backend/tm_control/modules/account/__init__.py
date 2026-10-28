"""The logged-in user's own account, and the admin's viewer accounts."""

from tm_control.modules import Module
from tm_control.modules.account.router import router

module = Module("account", router)
