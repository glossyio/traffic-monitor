"""The Software update: the API (modules/update/router.py), and the pieces it works from: the source, the offer,
the run, and the checks that come before a start."""

from tm_control.modules import Module
from tm_control.modules.update.router import router as update_router  # not `router`: that name is the submodule's

module = Module("update", update_router)
