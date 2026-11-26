"""The health check after a switch, and the record of the database copy the migration runner made during it.

Health passes when, in one round, the manifest names the new commit, the control app started after the switch began
and its health endpoint answers, and the pod, Frigate, Node-RED, the revproxy, and go2rtc are active."""

import json
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.client import HTTPException
from pathlib import Path

from . import proc, restore
from .state import Failed
from .switch import say

UNITS = ("traffic-monitor.service", "frigate.service", "node-red-tm.service", "revproxy.service",
         "go2rtc_server.service")
_ENDPOINT_TIMEOUT = 5
_SYSTEMCTL_TIMEOUT = 30
_clock = time.monotonic
_sleep = time.sleep


def _port(ctx) -> int:
    try:
        port = json.loads((ctx.handover.work_dir / "facts.json").read_text(encoding="utf-8"))["tm_control_port"]
    except (OSError, ValueError, KeyError, TypeError):
        port = None
    # bool is a kind of int, and true must not pass for a port
    if type(port) is not int or not 1 <= port <= 65535:
        raise Failed("health_failed", "facts tm_control_port")
    return port


def _manifest_names_the_commit(ctx) -> bool:
    try:
        data = json.loads(ctx.paths.manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    git = data.get("git") if isinstance(data, dict) else None
    return isinstance(git, dict) and isinstance(git.get("commit"), str) and git["commit"] == ctx.handover.commit


def _systemctl(argv: "list[str]") -> "str | None":
    try:
        result = proc.run(["systemctl", *argv], timeout=_SYSTEMCTL_TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() if isinstance(result.stdout, str) else None


def _active(unit: str) -> bool:
    return _systemctl(["is-active", unit]) == "active"


def _control_app_started_since(since_monotonic_usec: int) -> bool:
    if not _active("tm-control.service"):
        return False
    text = _systemctl(["show", "--property=ActiveEnterTimestampMonotonic", "--value", "tm-control.service"])
    if text is None or not text.isdigit():
        return False
    return int(text) > since_monotonic_usec


def _get_status(port: int) -> "int | None":
    """GET the control app's health endpoint on the loopback, with no proxy. Its status, or None for no answer."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(f"http://127.0.0.1:{port}/api/v1/health", timeout=_ENDPOINT_TIMEOUT) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code
    except (urllib.error.URLError, HTTPException, OSError, ValueError):
        return None


def _first_missing(ctx, port: int, since_monotonic_usec: int) -> "str | None":
    """One round: the name of the first check that doesn't pass, or None when all four do."""
    if not _manifest_names_the_commit(ctx):
        return "manifest"
    if not _control_app_started_since(since_monotonic_usec):
        return "tm-control"
    if _get_status(port) != 200:
        return "health endpoint"
    for unit in UNITS:
        if not _active(unit):
            return unit
    return None


def wait(ctx, *, since_monotonic_usec: int, limit: float = 300.0, every: float = 5.0) -> None:
    """Check in rounds until one passes or the limit is reached. Raises Failed("health_failed", <the first check that
    didn't pass in the last round>)."""
    port = _port(ctx)
    deadline = _clock() + limit
    said = None
    while True:
        missing = _first_missing(ctx, port, since_monotonic_usec)
        if missing is None:
            say(ctx.log, "healthy")
            return
        if missing != said:
            say(ctx.log, f"waiting for {missing}")
            said = missing
        if _clock() >= deadline:
            raise Failed("health_failed", missing)
        _sleep(every)


def _switch_began(stages: object) -> "float | None":
    """When the first switch of this run began (a resumed switch is the same switch), as a POSIX time."""
    if not isinstance(stages, list):
        return None
    for row in stages:
        if isinstance(row, dict) and row.get("id") == "switch" and isinstance(row.get("started_at"), str):
            try:
                began = datetime.strptime(row["started_at"], "%Y-%m-%dT%H:%M:%SZ")
            except ValueError:
                return None
            return began.replace(tzinfo=timezone.utc).timestamp()
    return None


def record_tmdb_backup(ctx) -> None:
    """The newest copy the migration runner made in <codedir>/node-red-tm/db/backup/ since the switch began goes into
    the state and the restore point's restore.json. None made: both stay null."""
    data = ctx.state.data
    began = _switch_began(data["stages"])
    folder = ctx.paths.rooted(ctx.installed.codedir) / "node-red-tm" / "db" / "backup"
    if began is None or not folder.is_dir():
        return
    found = []
    for entry in folder.glob("tmdb-v*.sqlite"):
        try:
            if entry.is_file() and not entry.is_symlink():
                mtime = entry.stat().st_mtime
                if mtime >= began:
                    found.append((mtime, entry.name, entry))
        except OSError:
            continue
    if not found:
        say(ctx.log, "no new copy of the traffic database")
        return
    newest = str(max(found)[2])
    ctx.state.set(tmdb_backup=newest)
    point = data["restore_point"]
    if not isinstance(point, str) or not (Path(point) / "restore.json").is_file():
        say(ctx.log, "no restore point to record the database copy in")
        return
    try:
        restore.record_tmdb_backup(Path(point), newest)
    except (OSError, ValueError):
        say(ctx.log, "could not record the database copy in the restore point")
