"""Login, sessions, and nginx's verify endpoint."""

from tm_control.modules import Module
from tm_control.modules.auth.router import root_router, router

module = Module("auth", router, root_router)
