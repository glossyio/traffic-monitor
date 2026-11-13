"""GET /services, the state of each Traffic Monitor unit (any user), and POST /services/{unit}/restart (admins),
which queues a restart through polkit once the 202 has been sent. A unit in FIX_UNITS, which a check's fix starts, can be
restarted too, though the list doesn't show it. Fake mode lists fake states and restarts nothing."""

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from pydantic import BaseModel

from tm_control.core.auth import Audit, User
from tm_control.core.errors import ApiError
from tm_control.modules.auth.deps import current_user, require_admin
from tm_control.modules.services.units import FIX_UNITS, Service, read_units, restart_or_log, service, units_for

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
def restart(unit: str, request: Request, background: BackgroundTasks, admin: User = Depends(require_admin)):
    app_state = request.app.state
    match = next((u.unit for u in units_for(app_state.manifest) if u.unit == unit and u.restartable), None)
    if match is None and unit in FIX_UNITS:
        match = unit
    if match is None:
        raise ApiError(404, "not_found", "There is no such service to restart.")
    Audit(app_state.state).record(admin.id, "services.restart", match)
    if not app_state.settings.fake:
        background.add_task(restart_or_log, match)
    return {"unit": match}
