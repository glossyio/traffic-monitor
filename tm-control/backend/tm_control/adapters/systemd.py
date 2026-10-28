"""systemd through its command-line tools: start a unit, read its properties, and read its journal.

tm-control runs unprivileged; polkit lets it start the named units (Task 6's rules). Reading properties needs no
privilege, and reading a system unit's journal needs the systemd-journal (or adm) group.
"""

import json
import logging

from tm_control.adapters.command import CommandResult, run

log = logging.getLogger(__name__)

JOURNAL_MAX_OUTPUT = 1024 * 1024


def start_unit(name: str) -> CommandResult:
    """Queue a start and return at once (--no-block); the caller follows the run with show_unit."""
    return run(["systemctl", "start", "--no-block", name], timeout=30)


def show_unit(name: str, properties: list[str]) -> dict[str, str]:
    """The unit's current values of the named properties; a property systemctl doesn't print is "".

    This reads Key=Value lines rather than using --value: with several properties, --value prints them in
    systemd's own order, not the order asked for, so the bare values can't be told apart.
    """
    result = run(["systemctl", "show", f"--property={','.join(properties)}", name], timeout=10)
    if result.returncode != 0 or result.timed_out:
        raise RuntimeError(f"systemctl show {name} failed with exit status {result.returncode}")
    values = dict.fromkeys(properties, "")
    for line in result.stdout.splitlines():
        key, sep, value = line.partition("=")
        if sep and key in values:
            values[key] = value
    return values


def _message(value) -> str | None:
    """journalctl's JSON MESSAGE: a string, a list of byte values when it isn't UTF-8, or null when too large."""
    if isinstance(value, str):
        return value
    if isinstance(value, list) and all(isinstance(b, int) and 0 <= b < 256 for b in value):
        return bytes(value).decode("utf-8", errors="replace")
    return None


def journal_lines(unit: str, since: str, limit: int = 200, invocation_id: str | None = None) -> list[str]:
    """The first `limit` MESSAGE fields the unit logged since `since` (a journalctl time, such as @<unix seconds>).

    With invocation_id, only the messages of that run (_SYSTEMD_INVOCATION_ID). On any failure to read the journal
    this returns [], so a job's status still shows when its log can't.
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
        "--output-fields=MESSAGE,_SYSTEMD_INVOCATION_ID",
    ]
    result = run(argv, timeout=10, max_output=JOURNAL_MAX_OUTPUT)
    if result.returncode != 0 or result.timed_out:
        log.warning("journalctl for %s failed with exit status %s", unit, result.returncode)
        return []
    lines = []
    for line in result.stdout.splitlines():
        try:
            entry = json.loads(line)
        except ValueError:
            continue  # the output cap cut this entry short
        if not isinstance(entry, dict):
            continue
        if invocation_id is not None and entry.get("_SYSTEMD_INVOCATION_ID") != invocation_id:
            continue
        message = _message(entry.get("MESSAGE"))
        if message is not None:
            lines.append(message)
            if len(lines) >= limit:
                break
    return lines
