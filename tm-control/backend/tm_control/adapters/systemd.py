"""systemd through its command-line tools: start or restart a unit, read its properties, read its journal, and
reboot or power off the device.

tm-control runs unprivileged; polkit lets it start, stop, and restart the named units, reboot, and power off
(tmsetup_tm_control_polkit). Reading properties needs no privilege, and reading a system unit's journal needs the
systemd-journal (or adm) group.
"""

import json
import logging
from concurrent.futures import ThreadPoolExecutor

from tm_control.adapters.command import TRUNCATED, CommandResult, run

log = logging.getLogger(__name__)

JOURNAL_MAX_OUTPUT = 1024 * 1024
JOURNAL_TAIL_MAX_OUTPUT = 256 * 1024
JOURNAL_CUT = "[The rest of the journal was cut here: it was longer than tm-control keeps.]"
SHOW_TIMEOUT = 4  # seconds; show_units is a status probe
SHOW_MAX_OUTPUT = 16384


def start_unit(name: str) -> CommandResult:
    """Queue a start and return at once (--no-block); the caller follows the run with show_unit."""
    return run(["systemctl", "start", "--no-block", name], timeout=30)


def restart_unit(name: str) -> CommandResult:
    """Queue a restart and return at once (--no-block)."""
    return run(["systemctl", "restart", "--no-block", name], timeout=30)


def reboot() -> CommandResult:
    """Ask logind to reboot; polkit allows org.freedesktop.login1.reboot (and -multiple-sessions)."""
    return run(["systemctl", "reboot"], timeout=30)


def power_off() -> CommandResult:
    """Ask logind to power off; polkit allows org.freedesktop.login1.power-off (and -multiple-sessions)."""
    return run(["systemctl", "poweroff"], timeout=30)


LOGIND = ["busctl", "call", "org.freedesktop.login1", "/org/freedesktop/login1", "org.freedesktop.login1.Manager"]
CAN_TIMEOUT = 4  # seconds; asked before the API answers


def can(method: str) -> bool:
    """Whether logind would reboot or power off now (method CanReboot or CanPowerOff): only a plain "yes" counts.

    "challenge" means polkit would ask for a password, and anything else, or a failure, means no; a block inhibitor
    (an update, say) is one reason. Asked first, because systemctl's refusal would come after the 202. A failure to
    ask is logged by its exit status or timeout, never busctl's output.
    """
    try:
        result = run([*LOGIND, method], timeout=CAN_TIMEOUT, max_output=4096)
    except OSError as exc:
        log.warning("busctl %s failed (%s)", method, type(exc).__name__)
        return False
    if result.timed_out:
        log.warning("busctl %s timed out", method)
        return False
    if result.returncode != 0:
        log.warning("busctl %s failed with exit status %s", method, result.returncode)
        return False
    return result.stdout.strip() == 's "yes"'


def _properties(stdout: str, properties: list[str]) -> dict[str, str]:
    """systemctl show's Key=Value lines as the named properties; one it doesn't print is ""."""
    values = dict.fromkeys(properties, "")
    for line in stdout.splitlines():
        key, sep, value = line.partition("=")
        if sep and key in values:
            values[key] = value
    return values


def show_unit(name: str, properties: list[str]) -> dict[str, str]:
    """The unit's current values of the named properties; a property systemctl doesn't print is "".

    This reads Key=Value lines rather than using --value: with several properties, --value prints them in
    systemd's own order, not the order asked for, so the bare values can't be told apart.
    """
    result = run(["systemctl", "show", f"--property={','.join(properties)}", name], timeout=10)
    if result.returncode != 0 or result.timed_out:
        raise RuntimeError(f"systemctl show {name} failed with exit status {result.returncode}")
    return _properties(result.stdout, properties)


def show_units(names: list[str], properties: list[str]) -> dict[str, dict[str, str]]:
    """Each unit's values of the named properties, from one `systemctl show` per unit, all run at the same time so
    a slow systemd costs one timeout. Timestamps are in --timestamp=unix form, `@<unix seconds>` ("" when unset).

    A unit that isn't installed still answers (LoadState=not-found). A unit whose read fails or times out is left
    out of the result; only its exit status is logged.
    """

    def show(name):
        argv = ["systemctl", "show", "--timestamp=unix", f"--property={','.join(properties)}", name]
        result = run(argv, timeout=SHOW_TIMEOUT, max_output=SHOW_MAX_OUTPUT)
        if result.returncode != 0 or result.timed_out:
            log.warning("systemctl show %s failed with exit status %s", name, result.returncode)
            return None
        return _properties(result.stdout, properties)

    if not names:
        return {}
    with ThreadPoolExecutor(max_workers=len(names), thread_name_prefix="systemctl-show") as pool:
        results = list(pool.map(show, names))
    return {name: values for name, values in zip(names, results) if values is not None}


def _message(value) -> str | None:
    """A journalctl JSON field: a string, a list of byte values when it isn't UTF-8, or null when too large."""
    if isinstance(value, str):
        return value
    if isinstance(value, list) and all(isinstance(b, int) and 0 <= b < 256 for b in value):
        return bytes(value).decode("utf-8", errors="replace")
    return None


# PID 1 logs the end of the unit's start job ("Finished …", "Failed …") with INVOCATION_ID, JOB_TYPE, JOB_RESULT;
# the unit's own processes log with _SYSTEMD_INVOCATION_ID.
JOURNAL_FIELDS = ["MESSAGE", "_SYSTEMD_INVOCATION_ID", "INVOCATION_ID", "JOB_TYPE", "JOB_RESULT"]


def journal_entries(unit: str, since: str) -> list[dict[str, str]]:
    """The unit's journal entries since `since` (a journalctl time, such as @<unix seconds>), oldest first, each
    with whichever of JOURNAL_FIELDS it has, as strings.

    On any failure to read the journal this returns [], so a caller can't mistake it for an outcome.
    """
    argv = [
        "journalctl",
        "--quiet",
        "--no-pager",
        "-u",
        unit,
        "--since",
        since,
        "--output=json",
        f"--output-fields={','.join(JOURNAL_FIELDS)}",
    ]
    result = run(argv, timeout=10, max_output=JOURNAL_MAX_OUTPUT)
    if result.returncode != 0 or result.timed_out:
        log.warning("journalctl for %s failed with exit status %s", unit, result.returncode)
        return []
    entries = []
    for line in result.stdout.splitlines():
        try:
            raw = json.loads(line)
        except ValueError:
            continue  # the output cap cut this entry short
        if not isinstance(raw, dict):
            continue
        entry = {}
        for field in JOURNAL_FIELDS:
            value = _message(raw.get(field))
            if value is not None:
                entry[field] = value
        entries.append(entry)
    return entries


# PID 1's catalog message ids: a unit's main process exited (with EXIT_CODE and EXIT_STATUS), and a restart after a
# failure was scheduled (with N_RESTARTS).
UNIT_PROCESS_EXITED = "98e322203f7a4ed290d09fe03c09fe15"
UNIT_RESTART_SCHEDULED = "5eb03494b6584870a536b337290809b3"


def automatic_restart_exits(unit: str) -> list[str | None] | None:
    """For each restart systemd scheduled for the unit this boot, oldest first, the EXIT_STATUS of the main-process
    exit logged just before it (None when there was none, or it had no status). None if the journal can't be read."""
    argv = [
        "journalctl",
        "--quiet",
        "--no-pager",
        "-b",
        "_PID=1",
        f"UNIT={unit}",
        f"MESSAGE_ID={UNIT_PROCESS_EXITED}",
        f"MESSAGE_ID={UNIT_RESTART_SCHEDULED}",
        "--output=json",
        "--output-fields=MESSAGE_ID,EXIT_STATUS",
    ]
    try:
        result = run(argv, timeout=4, max_output=JOURNAL_MAX_OUTPUT)
    except OSError:
        return None
    if result.returncode != 0 or result.timed_out:
        log.warning("journalctl for %s's restarts failed with exit status %s", unit, result.returncode)
        return None
    exits, last_exit = [], None
    for line in result.stdout.splitlines():
        try:
            entry = json.loads(line)
        except ValueError:
            continue  # the output cap cut this entry short
        if not isinstance(entry, dict):
            continue
        if entry.get("MESSAGE_ID") == UNIT_PROCESS_EXITED:
            last_exit = _message(entry.get("EXIT_STATUS"))
        elif entry.get("MESSAGE_ID") == UNIT_RESTART_SCHEDULED:
            exits.append(last_exit)
            last_exit = None
    return exits


def journal_lines(unit: str, since: str, limit: int = 200, invocation_id: str | None = None) -> list[str]:
    """The first `limit` MESSAGE fields the unit logged since `since`; with invocation_id, only that run's own
    (_SYSTEMD_INVOCATION_ID). [] if the journal can't be read, so a job's status still shows when its log can't."""
    lines = []
    for entry in journal_entries(unit, since):
        if invocation_id is not None and entry.get("_SYSTEMD_INVOCATION_ID") != invocation_id:
            continue
        if "MESSAGE" in entry:
            lines.append(entry["MESSAGE"])
            if len(lines) >= limit:
                break
    return lines


def journal_tail(unit: str, lines: int) -> list[str] | None:
    """The unit's last `lines` journal lines as journalctl prints them, with ISO 8601 times; None if the journal
    can't be read."""
    argv = ["journalctl", "-u", unit, "-n", str(lines), "--no-pager", "-o", "short-iso"]
    try:
        result = run(argv, timeout=10, max_output=JOURNAL_TAIL_MAX_OUTPUT)
    except OSError:
        return None
    if result.returncode != 0 or result.timed_out:
        log.warning("journalctl for %s failed with exit status %s", unit, result.returncode)
        return None
    if not result.stdout.endswith(TRUNCATED):
        return result.stdout.splitlines()
    # The cap cut the output mid-line, and a secret cut in two can't be matched by its value: drop that line.
    return result.stdout.removesuffix(TRUNCATED).splitlines()[:-1] + [JOURNAL_CUT]
