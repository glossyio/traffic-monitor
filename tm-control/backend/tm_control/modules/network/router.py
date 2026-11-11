"""The Network page's routes: GET /network for any signed-in user, and for admins the hotspot's password and a change
to the hotspot.

A change is only checked here. POST /network/hotspot starts the `network` root job with the fields that were sent; the
UI polls GET /jobs/{id} for the outcome. No password is logged, audited, or answered, except by GET
/network/hotspot/password.
"""

import re

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from tm_control.adapters import network
from tm_control.core.auth import Audit, User
from tm_control.core.errors import ApiError
from tm_control.core.secrets import read_hotspot_password
from tm_control.modules.auth.deps import current_user, require_admin
from tm_control.modules.network.state import NetworkState, read_state
from tm_control.modules.system.router import hostname

router = APIRouter(prefix="/network", tags=["network"])

# The root job copies these three; a test compares the two.
NAME_MAX_BYTES = 32
NAME_PATTERN = r"[^\x00-\x20\x7f](?:[^\x00-\x1f\x7f]*[^\x00-\x20\x7f])?"  # no control characters or edge spaces
PASSWORD_PATTERN = r"[\x21-\x7e][\x20-\x7e]{6,61}[\x21-\x7e]"  # 8 to 63 printable ASCII
NAME_MESSAGE = "A hotspot name is 1 to 32 characters (fewer with accents or emoji), with no space at either end."
PASSWORD_MESSAGE = "A hotspot password is 8 to 63 letters, digits, and symbols, with no space at either end."
NOTHING_MESSAGE = "Nothing to change."
NO_HOTSPOT_MESSAGE = "The hotspot isn't set up. Run the installer again (tmsetup.sh -t wifi)."


class HotspotChange(BaseModel):
    enabled: bool | None = None
    name: str | None = Field(default=None, max_length=128)
    password: str | None = Field(default=None, max_length=128)
    hidden: bool | None = None


class HotspotPassword(BaseModel):
    password: str | None  # None: no password file; "": the hotspot has no password


class JobStarted(BaseModel):
    id: str


def _valid_name(name: str) -> bool:
    if re.fullmatch(NAME_PATTERN, name) is None:
        return False
    try:
        return len(name.encode("utf-8")) <= NAME_MAX_BYTES
    except UnicodeEncodeError:  # a lone surrogate
        return False


def _check(change: dict) -> None:
    if not change:
        raise ApiError(422, "validation", NOTHING_MESSAGE)
    if "name" in change and not _valid_name(change["name"]):
        raise ApiError(422, "validation", NAME_MESSAGE)
    if "password" in change and re.fullmatch(PASSWORD_PATTERN, change["password"]) is None:
        raise ApiError(422, "validation", PASSWORD_MESSAGE)


@router.get("", response_model=NetworkState)
def get_network(request: Request, user: User = Depends(current_user)) -> NetworkState:
    return read_state(request.app.state, hostname(request.app.state))


@router.get("/hotspot/password", response_model=HotspotPassword)
def get_hotspot_password(request: Request, admin: User = Depends(require_admin)) -> JSONResponse:
    app_state = request.app.state
    if app_state.fake_network is not None:
        password = app_state.fake_network.password
    else:
        password = read_hotspot_password(app_state.settings.secrets_dir)
    Audit(app_state.state).record(admin.id, "network.hotspot_password_shown")
    return JSONResponse({"password": password}, headers={"Cache-Control": "no-store"})


@router.post("/hotspot", status_code=202, response_model=JobStarted)
def change_hotspot(body: HotspotChange, request: Request, admin: User = Depends(require_admin)) -> JobStarted:
    """Start the job that applies the change to the hotspot. A value that breaks its rule is refused before any job."""
    app_state = request.app.state
    change = body.model_dump(exclude_none=True)
    _check(change)
    if app_state.fake_network is None and network.hotspot(app_state.manifest.network.hotspot_profile) is False:
        raise ApiError(409, "no_hotspot", NO_HOTSPOT_MESSAGE)
    job_request = {"action": "hotspot", **change}
    job = app_state.jobs.start("network", job_request, admin.id)
    Audit(app_state.state).record(admin.id, "network.hotspot", detail=", ".join(change))
    if app_state.fake_network is not None:
        app_state.fake_network.apply(job_request)
    return JobStarted(id=job.id)
