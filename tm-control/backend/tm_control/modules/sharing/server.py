"""How the sharing server answered, from the upload section of Node-RED's /tm-internal/status.

Node-RED records the result of each upload: the time of the last one the server accepted, and the time and kind of
the last failure (refused, rejected, server_error, unreachable), taken from the status code or the lack of an answer.
tm-control reads that and never contacts the server itself. Nothing here names the server.
"""

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel

STALE_AFTER = 900  # seconds: three of the five-minute system metrics missed
FAILURES = ("refused", "rejected", "server_error", "unreachable")


class ServerStatus(BaseModel):
    state: Literal["off", "waiting", "ok", "stale", "unreachable", "refused", "rejected", "server_error", "unknown"]
    at: str | None  # the time of the upload the state is about, as Node-RED gave it


def _time(value) -> float | None:
    """An ISO time as a Unix time (a trailing Z allowed, no zone read as UTC); None for anything that doesn't parse."""
    if not isinstance(value, str):
        return None
    try:
        moment = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.timestamp()


def server_status(report: dict | None, now: float) -> ServerStatus:
    """The state from Node-RED's status body (None when Node-RED didn't answer): unknown without an upload section;
    off with the upload off; waiting with nothing recorded since the settings loaded; the failure's kind when it is
    newer than the last accepted upload; else ok, or stale when that upload is more than STALE_AFTER seconds old."""
    upload = report.get("upload") if isinstance(report, dict) else None
    if not isinstance(upload, dict) or not isinstance(upload.get("enabled"), bool):
        return ServerStatus(state="unknown", at=None)
    if not upload["enabled"]:
        return ServerStatus(state="off", at=None)
    ok_at, failed_at, failure = _time(upload.get("last_ok_at")), _time(upload.get("last_failure_at")), None
    if failed_at is not None:
        failure = upload.get("last_failure")
        if failure not in FAILURES:
            return ServerStatus(state="unknown", at=None)
    if failure is not None and (ok_at is None or failed_at > ok_at):
        return ServerStatus(state=failure, at=upload["last_failure_at"])
    if ok_at is None:
        return ServerStatus(state="waiting", at=None)
    return ServerStatus(state="stale" if now - ok_at > STALE_AFTER else "ok", at=upload["last_ok_at"])
