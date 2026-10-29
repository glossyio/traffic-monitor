"""The device's date, time, time zone, and NTP through timedatectl (systemd-timedated).

Reading needs no privilege; polkit lets tm-control's user set the time, the time zone, and NTP
(the org.freedesktop.timedate1 actions in tmsetup_tm_control_polkit).
"""

import logging
import threading
from datetime import UTC, datetime

from pydantic import BaseModel

from tm_control.adapters.command import TRUNCATED, CommandResult, run

log = logging.getLogger(__name__)

SHOW_TIMEOUT = 4  # seconds; GET /time and the time check read it
SET_TIMEOUT = 10
MAX_OUTPUT = 65536  # list-timezones prints about 600 names
# TimeUSec is left out: on the Pi it's a local string such as "Wed 2026-10-28 14:41:35 PDT", and systemd 257's
# timedatectl has no --timestamp= option. The device's time comes from tm-control's own clock instead (now()).
PROPERTIES = ["Timezone", "NTP", "NTPSynchronized", "CanNTP", "RTCTimeUSec"]


class Ntp(BaseModel):
    enabled: bool  # NTP: systemd-timesyncd is on
    synchronized: bool  # NTPSynchronized: the kernel's clock is synchronized
    available: bool  # CanNTP: there is an NTP service to turn on


class TimeState(BaseModel):
    device_time: str  # ISO 8601 with the device's offset, to the second
    timezone: str
    ntp: Ntp
    rtc_time: str | None  # RTCTimeUSec as timedatectl prints it; None when the device has no (readable) RTC


def now() -> datetime:
    """The device's time in its time zone, as tm-control's process sees it (time.tzset() after a zone change)."""
    return datetime.now().astimezone()


def device_time() -> str:
    return now().isoformat(timespec="seconds")


def _properties(stdout: str) -> dict[str, str]:
    values = dict.fromkeys(PROPERTIES, "")
    for line in stdout.splitlines():
        key, sep, value = line.partition("=")
        if sep and key in values:
            values[key] = value
    return values


def show() -> TimeState | None:
    """The time state from `timedatectl show`; None if it can't be read."""
    argv = ["timedatectl", "show", *(f"--property={name}" for name in PROPERTIES)]
    try:
        result = run(argv, timeout=SHOW_TIMEOUT, max_output=MAX_OUTPUT)
    except OSError as exc:
        log.warning("timedatectl show failed (%s)", type(exc).__name__)
        return None
    if result.returncode != 0 or result.timed_out:
        log.warning("timedatectl show failed with exit status %s", result.returncode)
        return None
    values = _properties(result.stdout)
    rtc = values["RTCTimeUSec"]
    return TimeState(
        device_time=device_time(),
        timezone=values["Timezone"],
        ntp=Ntp(
            enabled=values["NTP"] == "yes",
            synchronized=values["NTPSynchronized"] == "yes",
            available=values["CanNTP"] == "yes",
        ),
        rtc_time=rtc if rtc and rtc != "n/a" else None,
    )


_timezones: list[str] | None = None
_timezones_lock = threading.Lock()


def list_timezones() -> list[str]:
    """`timedatectl list-timezones`, read once per process; raises RuntimeError (not cached) if it can't be read."""
    global _timezones
    with _timezones_lock:
        if _timezones is None:
            try:
                result = run(["timedatectl", "list-timezones"], timeout=SHOW_TIMEOUT, max_output=MAX_OUTPUT)
            except OSError as exc:
                raise RuntimeError(f"timedatectl list-timezones failed ({type(exc).__name__})") from None
            if result.returncode != 0 or result.timed_out or result.stdout.endswith(TRUNCATED):
                raise RuntimeError(f"timedatectl list-timezones failed with exit status {result.returncode}")
            zones = [line.strip() for line in result.stdout.splitlines() if line.strip()]
            if not zones:
                raise RuntimeError("timedatectl list-timezones printed no time zones")
            _timezones = zones
        return list(_timezones)


def _set(argv: list[str], env: dict[str, str] | None = None) -> CommandResult:
    """Run a set-* command; a timedatectl that can't be run at all is exit status 127, like the shell's."""
    try:
        return run(argv, timeout=SET_TIMEOUT, env=env)
    except OSError as exc:
        log.warning("%s %s failed (%s)", argv[0], argv[1], type(exc).__name__)
        return CommandResult(127, "", "", False)


def set_timezone(name: str) -> CommandResult:
    return _set(["timedatectl", "set-timezone", name])


def set_ntp(enabled: bool) -> CommandResult:
    return _set(["timedatectl", "set-ntp", "true" if enabled else "false"])


def set_time(when: datetime) -> CommandResult:
    """Set the clock to `when` (aware), to the second. timedatectl reads the time in its own time zone, so it's
    given the time in UTC with TZ=UTC. timedated refuses this while NTP is on."""
    utc = when.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S")
    return _set(["timedatectl", "set-time", utc], env={"TZ": "UTC"})
