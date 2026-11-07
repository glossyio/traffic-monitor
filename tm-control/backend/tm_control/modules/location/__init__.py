"""The Location page: the unit's places (surveys), deploying one, and correcting what was recorded (/api/v1/surveys)."""

from tm_control.modules import Module
from tm_control.modules.location.router import router

module = Module("location", router)
