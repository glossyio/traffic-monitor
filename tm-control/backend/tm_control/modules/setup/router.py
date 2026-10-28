"""First run: the device's claim state, the EULA, and claiming the device with its setup code.

status, eula, and claim are open; claim works once, while the device has no admin.
"""

import logging
import time

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field

from tm_control.core.auth import Audit, Device, SetupCode, User, check_password_rules, check_username_rules
from tm_control.core.errors import ApiError
from tm_control.modules.auth.deps import client_ip, rate_limited, require_admin, set_session_cookie

log = logging.getLogger(__name__)

router = APIRouter(prefix="/setup", tags=["setup"])


def _check_eula_version(request: Request, version: str) -> None:
    if version != request.app.state.eula.version:
        raise ApiError(422, "validation", "That isn't the current license agreement. Reload the page to read it.")


@router.get("/status")
def status(request: Request):
    app_state = request.app.state
    device = Device(app_state.state)
    version = app_state.eula.version
    return {"claimed": device.is_claimed(), "eula": {"version": version, "accepted": device.eula_accepted(version)}}


@router.get("/eula")
def eula(request: Request):
    current = request.app.state.eula
    return {"version": current.version, "markdown": current.markdown}


class Claim(BaseModel):
    setup_code: str = Field(max_length=64)
    username: str = Field(max_length=64)
    password: str = Field(max_length=1024)
    eula_version: str = Field(max_length=64)


@router.post("/claim", status_code=201)
def claim(body: Claim, request: Request, response: Response):
    """Create the first admin with the setup code tmsetup printed, accept the EULA for them, and log them in."""
    app_state = request.app.state
    device = Device(app_state.state)
    if device.is_claimed():
        raise ApiError(409, "already_claimed", "This device has already been claimed.")
    _check_eula_version(request, body.eula_version)
    check_username_rules(body.username)
    check_password_rules(body.password)

    ip = client_ip(request)
    key = f"ip:{ip}"
    backoff = app_state.claim_backoff
    wait = backoff.check(key, time.monotonic())
    if wait > 0:
        log.warning("claim refused while backing off: from %s", ip)
        raise rate_limited(wait, "Too many wrong setup codes. Try again later.")

    # Counted as a failure before the slow code check and forgiven on success, as in login.
    backoff.record_failure(key, time.monotonic())
    code_hash = device.setup_code_hash()
    if code_hash is None or not SetupCode.verify_code(code_hash, body.setup_code):
        log.warning("wrong setup code from %s", ip)
        raise ApiError(403, "invalid_setup_code", "That setup code is wrong.")
    backoff.reset(key)

    user = device.claim(body.username, body.password, body.eula_version)
    Audit(app_state.state).record(user.id, "claim", user.username)
    set_session_cookie(request, response, user)
    log.info("device claimed from %s by %r", ip, user.username)
    return {"user": user}


class EulaAcceptance(BaseModel):
    version: str = Field(max_length=64)


@router.post("/eula/accept", status_code=204)
def accept_eula(body: EulaAcceptance, request: Request, user: User = Depends(require_admin)):
    """An admin accepts a new EULA version for the device, which lets everyone back into the apps."""
    _check_eula_version(request, body.version)
    app_state = request.app.state
    Device(app_state.state).accept_eula(body.version, user.id)
    Audit(app_state.state).record(user.id, "eula.accept", body.version)
