"""GET /services, the state of each Traffic Monitor unit (any user), and POST /services/{unit}/restart (admins),
which queues a restart through polkit. Fake mode lists fake states and restarts nothing."""

import logging

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from tm_control.adapters import systemd
from tm_control.core.auth import Audit, User
from tm_control.core.errors import ApiError
from tm_control.modules.auth.deps import current_user, require_admin
from tm_control.modules.services.units import Service, read_units, service, units_for

log = logging.getLogger(__name__)

router = APIRouter(prefix="/services", tags=["services"])


class RestartQueued(BaseModel):
    unit: str


@router.get("", response_model=list[Service])
def services(request: Request, user: User = Depends(current_user)):
    app_state = request.app.state
    units = units_for(app_state.manifest)
    values = read_units(app_state.settings, units)
    return [service(unit, values.get(unit.unit)) for unit in units]


@router.post("/{unit}/restart", status_code=202, response_model=RestartQueued)
def restart(unit: str, request: Request, admin: User = Depends(require_admin)):
    app_state = request.app.state
    match = next((u for u in units_for(app_state.manifest) if u.unit == unit and u.restartable), None)
    if match is None:
        raise ApiError(404, "not_found", "There is no such service to restart.")
    if not app_state.settings.fake:
        result = systemd.restart_unit(match.unit)
        if result.returncode != 0 or result.timed_out:
            # The exit status only: systemctl's stderr is no business of the log or the browser.
            log.error("systemctl restart %s failed with exit status %s", match.unit, result.returncode)
            raise ApiError(500, "internal", f"{match.title} ({match.unit}) couldn't be restarted.")
    Audit(app_state.state).record(admin.id, "services.restart", match.unit)
    return {"unit": match.unit}
