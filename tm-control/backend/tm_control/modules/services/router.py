"""GET /services, the state of each Traffic Monitor unit (any user), and POST /services/{unit}/restart (admins),
which queues a restart through polkit once the 202 has been sent. Fake mode lists fake states and restarts nothing."""

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, Request
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


def _restart(unit: str) -> None:
    """Restart the unit, run after the 202 has been sent: restarting revproxy stops the nginx that carries it. A
    failure can only be logged, by its exit status (systemctl's stderr is no business of the log); the Status page
    shows the unit's state on its next refresh."""
    try:
        result = systemd.restart_unit(unit)
    except Exception as exc:
        log.error("systemctl restart %s failed (%s)", unit, type(exc).__name__)
        return
    if result.returncode != 0 or result.timed_out:
        log.error("systemctl restart %s failed with exit status %s", unit, result.returncode)


@router.post("/{unit}/restart", status_code=202, response_model=RestartQueued)
def restart(unit: str, request: Request, background: BackgroundTasks, admin: User = Depends(require_admin)):
    app_state = request.app.state
    match = next((u for u in units_for(app_state.manifest) if u.unit == unit and u.restartable), None)
    if match is None:
        raise ApiError(404, "not_found", "There is no such service to restart.")
    Audit(app_state.state).record(admin.id, "services.restart", match.unit)
    if not app_state.settings.fake:
        background.add_task(_restart, match.unit)
    return {"unit": match.unit}
