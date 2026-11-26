"""Reading an update's files for show: its log, from the end, and its state file's text. Nothing here is a rule's
input; the text goes to the page and the diagnostics through redaction."""

import os
import re
import stat
from pathlib import Path

LOG_FOLDER = "log"
# A run id in a path: the hand-over's rule (letters, digits, underscore, hyphen; 1 to 64).
_PLAIN_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
STATE_TEXT_MAX = 65_536


def plain_id(value: object) -> bool:
    return isinstance(value, str) and _PLAIN_ID.fullmatch(value) is not None


def tail(path: Path, count: int, cap: int) -> list[str] | None:
    """The last `count` lines of a regular file, read from its last `cap` bytes; None when it can't be read.

    A link is not followed. When the read began inside the file, its first line is probably cut and is dropped.
    """
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    except OSError:
        return None
    try:
        with os.fdopen(fd, "rb") as file:
            found = os.fstat(file.fileno())
            if not stat.S_ISREG(found.st_mode):
                return None
            start = max(0, found.st_size - cap)
            file.seek(start)
            data = file.read(cap)
    except OSError:
        return None
    lines = data.decode("utf-8", errors="replace").splitlines()
    if start > 0 and lines:
        lines = lines[1:]
    return lines[-count:] if count > 0 else []


def run_log(folder: Path, run_id: object, count: int, cap: int) -> list[str]:
    """The last lines of log/<run_id>.log; an id that isn't a plain name, or a file that can't be read, gives []."""
    if not plain_id(run_id):
        return []
    return tail(folder / LOG_FOLDER / f"{run_id}.log", count, cap) or []


def newest_log(folder: Path, count: int, cap: int) -> list[str] | None:
    """The last lines of the log written most recently, or None when there is none."""
    try:
        found = [(path.stat().st_mtime, path) for path in (folder / LOG_FOLDER).glob("*.log") if path.is_file()]
    except OSError:
        return None
    if not found:
        return None
    return tail(max(found, key=lambda item: item[0])[1], count, cap)


def state_text(folder: Path) -> str | None:
    """The state file's text (its last 64 KiB, if it is larger than a state file is); None when it can't be read."""
    lines = tail(folder / "state.json", 10**9, STATE_TEXT_MAX)
    return None if lines is None else "\n".join(lines)
