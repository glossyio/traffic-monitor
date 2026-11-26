"""The switch: stop the pod and the control app, install the new tree with the installer in update mode, and, when the
installer says the device must restart, ask for that restart. A switch that fails starts the control app, the pod, and
the revproxy again before it ends."""

import os
import re
import subprocess
import time
import traceback
from datetime import datetime, timezone

from . import playbook, proc
from .handover import Handover
from .installed import Refusal, check_database_space
from .paths import Paths
from .state import Failed, clear_marker, write_marker

STOPPED_FIRST = ("traffic-monitor.service", "tm-control.service")
STARTED_AFTER_A_FAILURE = ("tm-control.service", "traffic-monitor.service", "revproxy.service")
ATTEMPTS = 2
_BOOT_ID = re.compile(r"[0-9a-f-]{36}")
_STOP_TIMEOUT = 300
_START_TIMEOUT = 600


def say(log, text: str) -> None:
    log.write(datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") + " " + text + "\n")
    log.flush()


def _monotonic_usec() -> int:
    """CLOCK_MONOTONIC in microseconds: the clock systemd stamps ActiveEnterTimestampMonotonic with."""
    return time.clock_gettime_ns(time.CLOCK_MONOTONIC) // 1000


def boot_id(paths: Paths) -> "str | None":
    try:
        text = paths.boot_id.read_text(encoding="ascii").strip()
    except (OSError, ValueError):
        return None
    return text if _BOOT_ID.fullmatch(text) else None


def _flag(handover: Handover):
    return handover.work_dir / "reboot-required"


def wants_reboot(handover: Handover) -> bool:
    """The role's restart flag (tmsetup_reboot_touch_file) holds anything but 0. No flag is no restart."""
    try:
        text = _flag(handover).read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return False
    except OSError:
        return True
    return text.strip() != "0"


def _reset_flag(handover: Handover) -> None:
    """0 before each installer run, as tmsetup.sh does, so a flag an earlier attempt left can't ask for a restart."""
    flag = _flag(handover)
    flag.write_text("0", encoding="utf-8")
    flag.chmod(0o644)


def start_again(log) -> None:
    """Start the control app, the pod, and the revproxy, each tried whatever happened to the others."""
    for unit in STARTED_AFTER_A_FAILURE:
        try:
            status = proc.run(["systemctl", "start", unit], log=log, timeout=_START_TIMEOUT).returncode
        except (OSError, subprocess.SubprocessError) as error:
            say(log, f"could not start {unit}: {type(error).__name__}")
            continue
        if status != 0:
            say(log, f"starting {unit} ended with status {status}")


def _after_a_failure(ctx, error: BaseException, detail: str) -> None:
    """Start the three units again and remove the marker, then raise Failed("switch_failed", detail) (or the error
    itself when it is not an Exception, such as KeyboardInterrupt)."""
    if not isinstance(error, Failed):
        traceback.print_exc(file=ctx.log)
    start_again(ctx.log)
    clear_marker(ctx.paths)
    if not isinstance(error, Exception):
        raise error
    raise Failed("switch_failed", detail) from None


def _install(ctx) -> None:
    status = proc.run(["systemctl", "stop", *STOPPED_FIRST], log=ctx.log, timeout=_STOP_TIMEOUT).returncode
    if status != 0:
        raise Failed("switch_failed", f"stop exit status {status}")
    _reset_flag(ctx.handover)
    status = playbook.run_playbook(ctx.venv, ctx.tree, "setup.yml", ctx.vars_file, ctx.handover, ctx.log)
    if status != 0:
        raise Failed("switch_failed", f"playbook exit status {status}")


def run(ctx) -> None:
    """Switch to the tree.

    A first attempt (switch_attempts 0) changes nothing before the stop: it raises Refusal("low_space") when the
    migration runner's copy of the database has no room, or Failed("switch_failed") when the installer can't be made
    ready, and stops nothing. A repeated attempt (a restart cut the first one off, which may have stopped the units and
    run part of the installer) skips the space check, which the first passed and whose copy the runner replaces, and
    treats any failure before its marker like one after the stop. After the stop, or on a repeated attempt, any failure
    starts the three units again and removes the marker before it raises Failed("switch_failed")."""
    redo = ctx.state.data["switch_attempts"] > 0
    step = "space"
    try:
        if not redo:
            check_database_space(ctx.installed, ctx.paths)
        step = "venv"
        if ctx.venv is None:
            ctx.venv = playbook.ensure_venv(ctx.tree, ctx.paths, ctx.log)
        step = "vars"
        ctx.vars_file = playbook.write_vars(ctx.handover, ctx.installed, ctx.tree, update_mode=True)
        step = "marker"
        ctx.state.set(switch_attempts=ctx.state.data["switch_attempts"] + 1)
        write_marker(ctx.paths, ctx.tree, ctx.handover_path)
    except BaseException as error:
        if redo:
            _after_a_failure(ctx, error, step)
        if isinstance(error, Refusal):
            raise
        if isinstance(error, Failed):
            raise Failed("switch_failed", error.detail) from None
        raise
    ctx.switch_monotonic_usec = _monotonic_usec()
    try:
        _install(ctx)
    except BaseException as error:
        if isinstance(error, Failed):
            _after_a_failure(ctx, error, error.detail)
        _after_a_failure(ctx, error, f"unexpected {type(error).__name__}")


def restart(ctx) -> None:
    """Ask for the restart the installer wants. The state already says so; the log reaches the disk first. A request
    that fails starts the three units again and ends the run."""
    try:
        say(ctx.log, "restarting the device; tm-update resume carries the run on")
        os.fsync(ctx.log.fileno())
    except OSError:
        pass  # the restart matters more than the log's last line
    try:
        status = proc.run(["systemctl", "reboot"], log=ctx.log, timeout=_STOP_TIMEOUT).returncode
    except (OSError, subprocess.SubprocessError) as error:
        say(ctx.log, f"the restart request failed: {type(error).__name__}")
        status = None
    if status != 0:
        start_again(ctx.log)
        clear_marker(ctx.paths)
        raise Failed("switch_failed", "restart request")
