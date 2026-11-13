"""/api/v1/sharing: what the unit uploads, where, and what the owner agreed to.

GET (any signed-in user) follows config.yml first (follow.run), then says where the upload goes, which choices are
recorded for that server, and how the server last answered (from Node-RED's status; tm-control never contacts the
server). A viewer gets no host of an operator's own server and no token state. PUT (admins) saves the server and the
choices: under app.state.reconcile_lock, config.yml is written first (the thingsboard: and sharing: blocks) and the
consent rows second, so a refused or failed save records nothing and a failure between the two leaves less shared,
never more. POST /reviewed clears the review an upload found on asks for.

No host, token, or notice version is logged, audited, or put in an error message: audit rows name the fields that
changed, never a value.
"""

import re
import time
from typing import Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field

from tm_control.adapters.nodered import NodeRedError
from tm_control.core.auth import Audit, User
from tm_control.core.errors import ApiError
from tm_control.core.secrets import THINGSBOARD_ACCESS_TOKEN
from tm_control.modules import Module
from tm_control.modules.auth.deps import current_user, require_admin
from tm_control.modules.location.access import config_error, load_config, save_config
from tm_control.modules.location.config import ConfigError, Upload
from tm_control.modules.secrets.router import SecretState, secret_state
from tm_control.modules.sharing import follow
from tm_control.modules.sharing.consents import (
    CONSENTS,
    MAINTAINER,
    OWN_SERVER,
    Consent,
    Consents,
    normalize_host,
    target_key,
)
from tm_control.modules.sharing.server import ServerStatus, server_status

router = APIRouter(prefix="/sharing", tags=["sharing"])

# An own server's host as typed: a name or an address, with no scheme, port, or path (those are separate fields).
HOST = re.compile(r"[a-z0-9]([a-z0-9.-]{0,251}[a-z0-9])?")
CHANGED_NOTE = "the server changed"
# The settings an audit row may name, in the form's order.
FIELDS = ("target", "host", "protocol", "port", "enabled", "exact_location", "public_map")


class ConsentOut(BaseModel):
    """The latest row recorded for a choice and the server the upload goes to; granted false with no row."""

    granted: bool
    at: str | None
    notice_version: str | None


class SharingState(BaseModel):
    enabled: bool  # the upload is on (Share data)
    target: Literal["maintainer", "own"] | None  # None without a host
    host: str | None  # normalised; for a viewer, only the maintainer's
    protocol: Literal["http", "https"]
    port: int | None
    maintainer_host: str
    token: SecretState | None  # the ThingsBoard access token; None for a viewer
    share_data: ConsentOut
    exact_location: ConsentOut
    public_map: ConsentOut
    public_map_live: bool
    notice_version: str  # the current notice's
    notice_current: bool  # an own server, or Share data granted under the current notice
    review_needed: bool
    has_location: bool  # the place in use has a point in config.yml, which the exact location would send
    precision: Literal["none", "1", "2"]
    writable: bool  # the user may save (an admin)
    server: ServerStatus


class NoticeOut(BaseModel):
    version: str
    markdown: str


class SharingIn(BaseModel):
    target: Literal["maintainer", "own"]
    host: str | None = Field(None, max_length=253)
    protocol: Literal["http", "https"] = "https"
    port: int | None = Field(None, ge=1, le=65535)
    enabled: bool
    exact_location: bool
    public_map: Literal["none", "rounded_point"]
    notice_version: str | None = Field(None, max_length=64)


def _invalid(message: str, field: str) -> ApiError:
    return ApiError(422, "validation", message, detail={"field": field})


# Reading


def _kind(target: str | None) -> Literal["maintainer", "own"] | None:
    return None if target is None else ("maintainer" if target == MAINTAINER else "own")


def _granted(found: Consent | None) -> bool:
    return found is not None and found.granted


def _consent_out(found: Consent | None) -> ConsentOut:
    if found is None:
        return ConsentOut(granted=False, at=None, notice_version=None)
    return ConsentOut(granted=found.granted, at=found.at, notice_version=found.notice_version)


def _notice_current(target: str | None, latest: dict[str, Consent], version: str) -> bool:
    if target is None:
        return False
    if target != MAINTAINER:
        return True  # the notice doesn't apply to an operator's own server
    share = latest.get("share_data")
    return _granted(share) and share.notice_version == version


def _server(app_state) -> ServerStatus:
    try:
        report = app_state.nodered.report()
    except NodeRedError:
        report = None
    return server_status(report, time.time())


def _state(app_state, user: User, server: ServerStatus) -> SharingState:
    config = load_config(app_state)
    maintainer_host = app_state.manifest.sharing.maintainer_host
    upload = config.upload()
    host = normalize_host(upload.host)
    target = target_key(host, maintainer_host)
    consents = Consents(app_state.state)
    latest = consents.latest(target) if target is not None else {}
    admin = user.role == "admin"
    place = config.deployment()  # the place in use, as Node-RED reads it
    notice_version = app_state.notice.version
    return SharingState(
        enabled=upload.enabled,
        target=_kind(target),
        host=host if admin or target == MAINTAINER else None,
        protocol=upload.protocol,
        port=upload.port,
        maintainer_host=maintainer_host,
        token=secret_state(app_state, THINGSBOARD_ACCESS_TOKEN) if admin else None,
        share_data=_consent_out(latest.get("share_data")),
        exact_location=_consent_out(latest.get("exact_location")),
        public_map=_consent_out(latest.get("public_map")),
        public_map_live=app_state.manifest.sharing.public_map_live,
        notice_version=notice_version,
        notice_current=_notice_current(target, latest, notice_version),
        review_needed=consents.review_needed(),
        has_location=place is not None and place.lat is not None and place.lon is not None,
        precision=config.deployment().precision,
        writable=admin,
        server=server,
    )


def _settings(upload: Upload, target: str | None, latest: dict[str, Consent]) -> dict:
    """The file's and the store's settings, by the names in FIELDS, to tell what a save changed."""
    return {
        "target": _kind(target),
        "host": normalize_host(upload.host),
        "protocol": upload.protocol,
        "port": upload.port,
        "enabled": upload.enabled,
        "exact_location": _granted(latest.get("exact_location")),
        "public_map": _granted(latest.get("public_map")),
    }


# Checking a save


def _server_for(body: SharingIn, maintainer_host: str) -> tuple[str, str, Literal["http", "https"], int | None]:
    """(target key, host, protocol, port) the save is for. The maintainer's server, chosen or typed as an own one, is
    its host, https, and no port, whatever was sent."""
    if body.target == "own":
        host = (body.host or "").strip().lower()
        if HOST.fullmatch(host) is None:
            raise _invalid("Enter the server's name or address, with no https:// and no path.", "host")
        target = target_key(host, maintainer_host)
        if target != MAINTAINER:
            return target, host, body.protocol, body.port
    return MAINTAINER, maintainer_host, "https", None


def _check(app_state, body: SharingIn, target: str, protocol: str) -> None:
    if body.enabled and not app_state.secrets.is_set(THINGSBOARD_ACCESS_TOKEN):
        raise ApiError(409, "no_token", "Set the access token first.")
    if not body.enabled and body.exact_location:
        raise _invalid("Turn on Share data first.", "exact_location")
    if not body.enabled and body.public_map != "none":
        raise _invalid("Turn on Share data first.", "public_map")
    if body.exact_location and protocol == "http":
        raise _invalid("The exact location is only sent over https.", "exact_location")
    if body.public_map != "none":
        if target != MAINTAINER:
            raise ApiError(409, "map_not_live", "The public map is only for Traffic Monitor's server.")
        if not app_state.manifest.sharing.public_map_live:
            raise ApiError(409, "map_not_live", "The public map isn't live yet.")


def _check_notice(body: SharingIn, target: str, latest: dict[str, Consent], version: str) -> None:
    """Turning the upload on, or keeping it on, for the maintainer's server needs the current notice. A save that
    leaves the version out is taken while Share data is already granted under the current notice."""
    if target != MAINTAINER or not body.enabled:
        return
    if body.notice_version == version:
        return
    if body.notice_version is None and _notice_current(target, latest, version):
        return
    raise _invalid("That isn't the current notice. Reload the page to read it.", "notice_version")


# Routes


@router.get("", response_model=SharingState)
def get_sharing(request: Request, user: User = Depends(current_user)):
    """Where the upload goes and what is shared, after config.yml is followed. Node-RED not answering isn't an error:
    the server's state is unknown."""
    app_state = request.app.state
    server = _server(app_state)
    with app_state.reconcile_lock:
        try:
            follow.run(app_state)
        except ConfigError as error:
            raise config_error(error) from None
        return _state(app_state, user, server)


@router.get("/notice", response_model=NoticeOut)
def get_notice(request: Request, user: User = Depends(current_user)):
    notice = request.app.state.notice
    return NoticeOut(version=notice.version, markdown=notice.markdown)


@router.put("", response_model=SharingState)
def save_sharing(body: SharingIn, request: Request, admin: User = Depends(require_admin)):
    """Save the server and the choices: config.yml first, the consent rows second. Changing the server withdraws
    every choice recorded for any other one."""
    app_state = request.app.state
    maintainer_host = app_state.manifest.sharing.maintainer_host
    target, host, protocol, port = _server_for(body, maintainer_host)
    _check(app_state, body, target, protocol)
    notice_version = app_state.notice.version
    version = notice_version if target == MAINTAINER else OWN_SERVER  # what the rows for this server record
    wanted = {
        "share_data": body.enabled,
        "exact_location": body.exact_location,
        "public_map": body.public_map != "none",
    }
    consents = Consents(app_state.state)
    with app_state.reconcile_lock:
        latest = consents.latest(target)
        _check_notice(body, target, latest, notice_version)
        config = load_config(app_state)
        upload = config.upload()
        old_target = target_key(upload.host, maintainer_host)
        old_latest = latest if old_target == target else (consents.latest(old_target) if old_target else {})
        before = _settings(upload, old_target, old_latest)

        # The file, from the state the rows below will record.
        share = None
        if body.enabled:
            share = Consent(
                consent="share_data", granted=True, notice_version=version, at="", user_id=admin.id, note=None
            )
        block = follow.wanted_block(target, host, share, wanted["exact_location"], wanted["public_map"])
        try:
            config.set_upload(body.enabled, host, protocol, port)
            config.set_sharing(block)
        except ConfigError as error:
            raise config_error(error) from None
        save_config(app_state, config)

        # The rows.
        for other in consents.targets():
            if other != target:
                consents.withdraw_all(other, admin.id, CHANGED_NOTE)
        for name in CONSENTS:
            found = latest.get(name)
            if _granted(found) != wanted[name] or (wanted[name] and found.notice_version != version):
                consents.record(target, name, wanted[name], version, admin.id)
        consents.set_review_needed(False)

        after = {
            "target": _kind(target), "host": normalize_host(host), "protocol": protocol, "port": port,
            "enabled": body.enabled, **{name: wanted[name] for name in ("exact_location", "public_map")},
        }
        changed = [name for name in FIELDS if before[name] != after[name]]
        old_share = old_latest.get("share_data")
        if old_target == target and before["enabled"] and body.enabled and _granted(old_share) and (
            old_share.notice_version != version
        ):
            changed.append("notice_version")
        Audit(app_state.state).record(admin.id, "sharing.update", ",".join(changed) or None)
    server = _server(app_state)
    with app_state.reconcile_lock:
        return _state(app_state, admin, server)


@router.post("/reviewed", status_code=204, response_class=Response)
def mark_reviewed(request: Request, admin: User = Depends(require_admin)):
    """The admin reviewed an upload found on (the Status page's "Review sharing")."""
    app_state = request.app.state
    Consents(app_state.state).set_review_needed(False)
    Audit(app_state.state).record(admin.id, "sharing.reviewed")
    return Response(status_code=204)


module = Module("sharing", router)  # in MODULES after location's (see this package's __init__.py)
