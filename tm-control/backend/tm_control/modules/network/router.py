"""The Network page's routes: GET /network, GET /network/wifi, and GET /network/join for any signed-in user, and for
admins the hotspot's password, a change to the hotspot, Refresh, Forget, and the order of the saved Wi-Fi networks, and
a join to a Wi-Fi network with its Switch now and Cancel.

A change is only checked here. POST /network/hotspot, /network/wifi/scan, /network/wifi/forget, /network/wifi/order,
and the join's switch and cancel start the `network` root job with the request, and POST /network/wifi/join starts
`network-join`; the UI polls GET /jobs/{id} for the outcome and GET /network/join for the join. While a join is testing,
counting down, or switching, every other change is refused (409 join_pending). No password is logged, audited, or
answered, except by GET /network/hotspot/password.
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
from tm_control.modules.network.wifi import (
    REFUSALS,
    JoinState,
    WifiNetworks,
    choices,
    read_join,
    read_wifi,
    refuse_while_joining,
)
from tm_control.modules.system.router import hostname

router = APIRouter(prefix="/network", tags=["network"])

# The root job copies these three; a test compares the two.
NAME_MAX_BYTES = 32
NAME_PATTERN = r"[^\x00-\x20\x7f](?:[^\x00-\x1f\x7f]*[^\x00-\x20\x7f])?"  # no control characters or edge spaces
PASSWORD_PATTERN = r"[\x21-\x7e][\x20-\x7e]{6,61}[\x21-\x7e]"  # 8 to 63 printable ASCII
NETWORK_NAME_PATTERN = r"[^\x00-\x1f\x7f]+"  # the join job copies these two (and NAME_MAX_BYTES); a test compares them
NETWORK_PASSWORD_PATTERN = r"[\x20-\x7e]{8,63}"  # spaces included: a network's password is what it is
NETWORK_NAME_MESSAGE = "A network name is 1 to 32 bytes, with no control characters."
NETWORK_PASSWORD_MESSAGE = "A Wi-Fi password is 8 to 63 letters, digits, and symbols."
NAME_MESSAGE = "A hotspot name is 1 to 32 characters (fewer with accents or emoji), with no space at either end."
PASSWORD_MESSAGE = "A hotspot password is 8 to 63 letters, digits, and symbols, with no space at either end."
NOTHING_MESSAGE = "Nothing to change."
NO_HOTSPOT_MESSAGE = "The hotspot isn't set up. Run the installer again (tmsetup.sh -t wifi)."
NO_RADIO_MESSAGE = "This unit has no built-in Wi-Fi radio."
RADIO_OFF_MESSAGE = "The Wi-Fi radio is switched off. Turn the hotspot on to switch it on."
STALE_ORDER_MESSAGE = "The saved networks changed. Reload the page."
NOT_LISTED_MESSAGE = "That network isn't in the list any more. Tap Refresh and pick it again."
NEEDS_PASSWORD_MESSAGE = "Enter the network's password."
NO_COUNTDOWN_MESSAGE = "There is no countdown to end."
NOTHING_TO_CANCEL_MESSAGE = "There is no join to cancel."


class HotspotChange(BaseModel):
    enabled: bool | None = None
    name: str | None = Field(default=None, max_length=128)
    password: str | None = Field(default=None, max_length=128)
    hidden: bool | None = None


class JoinRequest(BaseModel):
    name: str = Field(max_length=128)
    password: str | None = Field(default=None, max_length=128)  # None: the saved network's own


class HotspotPassword(BaseModel):
    password: str | None  # None: no password file; "": the hotspot has no password


class JobStarted(BaseModel):
    id: str


class ForgetRequest(BaseModel):
    uuid: str = Field(max_length=64)


class OrderRequest(BaseModel):
    uuids: list[str] = Field(max_length=64)


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
    refuse_while_joining(app_state)
    if app_state.fake_network is None and network.hotspot(app_state.manifest.network.hotspot_profile) is False:
        raise ApiError(409, "no_hotspot", NO_HOTSPOT_MESSAGE)
    job_request = {"action": "hotspot", **change}
    job = app_state.jobs.start("network", job_request, admin.id)
    Audit(app_state.state).record(admin.id, "network.hotspot", detail=", ".join(change))
    if app_state.fake_network is not None:
        app_state.fake_network.apply(job_request)
    return JobStarted(id=job.id)


@router.get("/join", response_model=JoinState | None)
def get_join(request: Request, user: User = Depends(current_user)) -> JoinState | None:
    """The join to show, from the job's state file and its unit; runs no nmcli."""
    return read_join(request.app.state)


@router.get("/wifi", response_model=WifiNetworks)
def get_wifi(request: Request, user: User = Depends(current_user)) -> WifiNetworks:
    return read_wifi(request.app.state)


def _start(app_state, admin: User, job_request: dict) -> JobStarted:
    job = app_state.jobs.start("network", job_request, admin.id)
    if app_state.fake_network is not None:
        app_state.fake_network.apply(job_request)
    return JobStarted(id=job.id)


@router.post("/wifi/scan", status_code=202, response_model=JobStarted)
def scan_wifi(request: Request, admin: User = Depends(require_admin)) -> JobStarted:
    """Start a scan (Refresh). A radio known to be missing or off is refused before any job; one that can't be read
    is left to the job."""
    app_state = request.app.state
    if app_state.fake_network is None:
        info = app_state.manifest.network
        if network.radio_kind(info.wifi_device) != "builtin":
            raise ApiError(409, "no_radio", NO_RADIO_MESSAGE)
        if network.radio_enabled() is False:
            raise ApiError(409, "radio_off", RADIO_OFF_MESSAGE)
    refuse_while_joining(app_state)
    return _start(app_state, admin, {"action": "scan"})


@router.post("/wifi/forget", status_code=202, response_model=JobStarted)
def forget_wifi(body: ForgetRequest, request: Request, admin: User = Depends(require_admin)) -> JobStarted:
    app_state = request.app.state
    refuse_while_joining(app_state)
    names = {uuid: name for uuid, name, _ in choices(app_state) or []}
    if body.uuid not in names:
        raise ApiError(404, "not_found", "That network isn't saved.")
    started = _start(app_state, admin, {"action": "forget", "uuid": body.uuid})
    Audit(app_state.state).record(admin.id, "network.wifi_forget", detail=names[body.uuid])
    return started


@router.post("/wifi/order", status_code=202, response_model=JobStarted)
def order_wifi(body: OrderRequest, request: Request, admin: User = Depends(require_admin)) -> JobStarted:
    """Set the order the unit tries its saved networks in. It must name exactly the ones that join by themselves."""
    app_state = request.app.state
    refuse_while_joining(app_state)
    automatic = {uuid for uuid, _, joins in choices(app_state) or [] if joins}
    if len(set(body.uuids)) != len(body.uuids) or set(body.uuids) != automatic or not automatic:
        raise ApiError(409, "stale_order", STALE_ORDER_MESSAGE)
    started = _start(app_state, admin, {"action": "order", "uuids": body.uuids})
    Audit(app_state.state).record(admin.id, "network.wifi_order")
    return started


def _valid_network_name(name: str) -> bool:
    if re.fullmatch(NETWORK_NAME_PATTERN, name) is None:
        return False
    try:
        return len(name.encode("utf-8")) <= NAME_MAX_BYTES
    except UnicodeEncodeError:  # a lone surrogate
        return False


@router.post("/wifi/join", status_code=202, response_model=JobStarted)
def join_wifi(body: JoinRequest, request: Request, admin: User = Depends(require_admin)) -> JobStarted:
    """Start the join job: test the network, then count down to the switch. Everything that can be known now is
    checked first, in this order, so a refusal starts no job. The password goes to the job and nowhere else."""
    app_state = request.app.state
    if not _valid_network_name(body.name):
        raise ApiError(422, "validation", NETWORK_NAME_MESSAGE)
    if body.password is not None and re.fullmatch(NETWORK_PASSWORD_PATTERN, body.password) is None:
        raise ApiError(422, "validation", NETWORK_PASSWORD_MESSAGE)
    if app_state.fake_network is None:
        info = app_state.manifest.network
        if network.radio_kind(info.wifi_device) != "builtin":
            raise ApiError(409, "no_radio", NO_RADIO_MESSAGE)
        if network.radio_enabled() is False:
            raise ApiError(409, "radio_off", RADIO_OFF_MESSAGE)
    refuse_while_joining(app_state)
    wifi = read_wifi(app_state)
    mine = [n for n in wifi.saved if n.name == body.name]
    if any(n.in_use for n in mine):
        raise ApiError(409, "already_joined", f"The unit is already on {body.name}.")
    if not any(n.name == body.name and n.security == "password" for n in wifi.nearby):
        raise ApiError(409, "not_listed", NOT_LISTED_MESSAGE)
    if body.password is not None:
        job_request = {"ssid": body.name, "password": body.password}
    elif mine:
        job_request = {"uuid": mine[0].uuid}
    else:
        raise ApiError(422, "validation", NEEDS_PASSWORD_MESSAGE)
    job = app_state.jobs.start("network-join", job_request, admin.id)
    Audit(app_state.state).record(admin.id, "network.wifi_join", detail=body.name)
    if app_state.fake_network is not None:
        app_state.fake_network.start_join(body.name, body.password, "uuid" in job_request)
    return JobStarted(id=job.id)


@router.post("/wifi/join/switch", status_code=202, response_model=JobStarted)
def switch_join(request: Request, admin: User = Depends(require_admin)) -> JobStarted:
    """End the countdown early: the join switches at once."""
    app_state = request.app.state
    join = read_join(app_state)
    if join is None or join.stage != "countdown":
        raise ApiError(409, "no_countdown", NO_COUNTDOWN_MESSAGE)
    started = _start(app_state, admin, {"action": "switch-now"})
    Audit(app_state.state).record(admin.id, "network.wifi_join_switch", detail=join.network)
    return started


@router.post("/wifi/join/cancel", status_code=202, response_model=JobStarted)
def cancel_join(request: Request, admin: User = Depends(require_admin)) -> JobStarted:
    """Cancel a test or a countdown, or dismiss what a finished or interrupted join left. Not while it switches."""
    app_state = request.app.state
    join = read_join(app_state)
    if join is None:
        raise ApiError(409, "nothing_to_cancel", NOTHING_TO_CANCEL_MESSAGE)
    if join.stage == "switching":
        raise ApiError(409, "join_pending", REFUSALS["switching"].format(join.network))
    started = _start(app_state, admin, {"action": "cancel"})
    Audit(app_state.state).record(admin.id, "network.wifi_join_cancel", detail=join.network)
    return started
