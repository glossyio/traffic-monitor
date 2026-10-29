"""GET /time, the device's date, time, time zone, and NTP state, and GET /time/timezones, the zones it knows (any
user); POST /time (admins) sets the time from the browser, NTP, and the time zone through polkit.

The browser's time is used only when NTP doesn't have the time. With NTP on but no time source reachable, NTP is
turned off for set-time and back on after it, so the device resyncs once it's online; only `ntp: false` leaves it
off. A new time zone restarts the pod and nginx after the response, so the containers see it. Fake mode keeps a fake
clock in memory."""

import logging
import time
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from pydantic import BaseModel, Field

from tm_control.adapters import systemd, timedate
from tm_control.adapters.command import CommandResult
from tm_control.adapters.timedate import TimeState
from tm_control.core.auth import Audit, User
from tm_control.core.errors import ApiError
from tm_control.modules.auth.deps import current_user, require_admin
from tm_control.modules.time.checks import FLOOR

log = logging.getLogger(__name__)

router = APIRouter(prefix="/time", tags=["time"])

CEILING = datetime.fromisoformat("2046-01-01T00:00:00Z")
# Frigate, Node-RED, and nginx bind-mount /etc/localtime, which a container keeps seeing as the old zone's file until
# it restarts; restarting the pod restarts its containers.
CONTAINERS = ["traffic-monitor.service", "revproxy.service"]


class TimeChange(BaseModel):
    timezone: str | None = Field(default=None, max_length=64)
    ntp: bool | None = None
    time: str | None = Field(default=None, max_length=64)  # ISO 8601 with an offset, as new Date().toISOString()


class TimeResult(TimeState):
    time_kept_from_ntp: bool  # a time was sent, but NTP has the time, so the device kept its own
    restarting: list[str]  # units restarting after a time zone change


def _clock(app_state):
    return app_state.fake_clock if app_state.settings.fake else timedate


def _show(clock) -> TimeState:
    state = clock.show()
    if state is None:
        raise ApiError(500, "internal", "The device's date and time couldn't be read.")
    return state


def _timezones(clock) -> list[str]:
    try:
        return clock.list_timezones()
    except RuntimeError as exc:
        log.error("%s", exc)
        raise ApiError(500, "internal", "The device's list of time zones couldn't be read.") from None


def _parse_time(text: str) -> datetime:
    try:
        when = datetime.fromisoformat(text)
    except ValueError:
        raise ApiError(422, "validation", "The time isn't an ISO 8601 date and time.") from None
    if when.utcoffset() is None:
        raise ApiError(422, "validation", "The time needs its offset from UTC, such as Z or +02:00.")
    if not FLOOR <= when <= CEILING:
        raise ApiError(422, "validation", "The time must be between 2026-01-01 and 2046-01-01 (UTC).")
    return when


def _failed(result: CommandResult, what: str) -> bool:
    if result.returncode == 0 and not result.timed_out:
        return False
    # The exit status only: timedatectl's stderr is no business of the log or the browser.
    log.error("timedatectl %s failed with exit status %s", what, result.returncode)
    return True


def _done(result: CommandResult, what: str, message: str) -> None:
    if _failed(result, what):
        raise ApiError(500, "internal", message)


def _restart_containers() -> None:
    """Restart the pod and nginx, run after the response has been sent: nginx carries it."""
    for unit in CONTAINERS:
        try:
            result = systemd.restart_unit(unit)
        except Exception as exc:
            log.error("systemctl restart %s failed (%s)", unit, type(exc).__name__)
            continue
        if result.returncode != 0 or result.timed_out:
            log.error("systemctl restart %s failed with exit status %s", unit, result.returncode)


@router.get("", response_model=TimeState)
def time_state(request: Request, user: User = Depends(current_user)):
    return _show(_clock(request.app.state))


@router.get("/timezones", response_model=list[str])
def timezones(request: Request, user: User = Depends(current_user)):
    return _timezones(_clock(request.app.state))


@router.post("", response_model=TimeResult)
def change(body: TimeChange, request: Request, background: BackgroundTasks, admin: User = Depends(require_admin)):
    """The time (with what NTP needs for it), then an NTP toggle, then the time zone, whose change restarts the
    containers."""
    app_state = request.app.state
    clock = _clock(app_state)
    if body.timezone is None and body.ntp is None and body.time is None:
        raise ApiError(422, "validation", "There is nothing to change: send a time, a time zone, or NTP on or off.")
    when = _parse_time(body.time) if body.time is not None else None
    if body.timezone is not None and body.timezone not in _timezones(clock):
        raise ApiError(422, "validation", "The device doesn't know that time zone.")
    before = _show(clock)
    if body.ntp and not before.ntp.enabled and not before.ntp.available:
        raise ApiError(422, "validation", "The device has no time synchronization service to turn on.")

    ntp = before.ntp.enabled
    kept = False
    zone_changed = False
    changed: set[str] = set()  # for the audit: which settings changed, never their values
    finished = False
    try:
        # 1. The time, and NTP as far as setting it needs.
        if when is not None and body.ntp is False:  # NTP off for good, and the time set by hand
            if ntp:  # timedated refuses set-time while NTP is on
                _done(clock.set_ntp(False), "set-ntp", "NTP couldn't be turned off, so the time wasn't set.")
                ntp = False
                changed.add("ntp")
            _done(clock.set_time(when), "set-time", "The time couldn't be set.")
            changed.add("time")
        elif when is not None and ntp and before.ntp.synchronized:
            kept = True  # NTP has the time; the browser's clock could be the wrong one
        elif when is not None and ntp:
            # No time source reachable: set the time, and keep NTP on so it takes over once one is.
            _done(clock.set_ntp(False), "set-ntp", "NTP couldn't be turned off, so the time wasn't set.")
            time_set = not _failed(clock.set_time(when), "set-time")
            ntp_back = not _failed(clock.set_ntp(True), "set-ntp")
            if time_set:
                changed.add("time")
            if not ntp_back:
                ntp = False
                changed.add("ntp")
            if not time_set and ntp_back:
                raise ApiError(500, "internal", "The time couldn't be set; NTP is back on.")
            if not time_set:
                raise ApiError(500, "internal", "The time couldn't be set, and NTP couldn't be turned back on, so "
                                                "it's now off.")
            if not ntp_back:
                raise ApiError(500, "internal", "The time was set, but NTP couldn't be turned back on, so it's now "
                                                "off.")
        elif when is not None:
            _done(clock.set_time(when), "set-time", "The time couldn't be set.")
            changed.add("time")
        # 2. An NTP toggle that step 1 didn't already make.
        if body.ntp is not None and body.ntp != ntp:
            _done(clock.set_ntp(body.ntp), "set-ntp", f"NTP couldn't be turned {'on' if body.ntp else 'off'}.")
            ntp = body.ntp
            changed.add("ntp")
        # 3. The time zone last: once it has changed, nothing can fail before the restart is queued.
        if body.timezone is not None and body.timezone != before.timezone:
            _done(clock.set_timezone(body.timezone), "set-timezone", "The time zone couldn't be changed.")
            zone_changed = True
            changed.add("timezone")
            if not app_state.settings.fake:
                time.tzset()  # tm-control's own clock (the home page's device card, reports) follows
                background.add_task(_restart_containers)
        finished = True
    finally:
        if finished or changed:
            fields = [field for field in ("ntp", "time", "timezone") if field in changed]
            Audit(app_state.state).record(admin.id, "time.set", ", ".join(fields) or None)

    after = clock.show()
    if after is None:  # what was asked for happened; answer with it rather than an error
        after = before.model_copy(
            update={
                "device_time": timedate.device_time(),
                "timezone": body.timezone if zone_changed else before.timezone,
                "ntp": before.ntp.model_copy(update={"enabled": ntp, "synchronized": ntp and before.ntp.synchronized}),
            }
        )
    restarting = list(CONTAINERS) if zone_changed else []
    return TimeResult(**after.model_dump(), time_kept_from_ntp=kept, restarting=restarting)
