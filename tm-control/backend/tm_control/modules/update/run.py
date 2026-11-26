"""An update run as the control app sees it: the state file tm-update writes, the two units that can be running it,
the resume marker, and this boot's id, worked into one status.

The file's values are type-checked one by one: a wrong one becomes None or an empty list, never an error. Stage ids
and reason codes pass through as text, so a code a later version adds still shows.
"""

import json
import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from ...adapters import systemd

JOB_UNIT = "tm-job-update.service"
RESUME_UNIT = "tm-update-resume.service"
# The stages after which the services have been stopped: a run cut off from here on needs the launcher to carry on.
SWITCHED = ("switch", "reboot", "health", "cleanup")
STATE_FILE = "state.json"
MARKER_FILE = "resume.json"
BOOT_ID = Path("/proc/sys/kernel/random/boot_id")
MAX_FILE = 1_048_576  # a state file is a few kilobytes; a larger one is not one
MAX_STAGES = 50
MAX_TEXT = 200


class StageRow(BaseModel):
    id: str
    started_at: str | None
    finished_at: str | None


class Run(BaseModel):
    status: Literal["running", "ok", "failed", "interrupted", "cut_off"]
    readable: bool  # false: a state file of a schema this version doesn't know
    run_id: str | None = None
    channel: str | None = None
    from_version: str | None = None
    from_commit: str | None = None
    to_version: str | None = None
    to_commit: str | None = None
    to_tag: str | None = None
    stage: str | None = None
    stages: list[StageRow] = []
    reason: str | None = None
    detail: str | None = None
    restore_point: str | None = None  # the folder's name, never its path
    finished_at: str | None = None


def _text(value: object, limit: int = MAX_TEXT) -> str | None:
    """The value when it is non-empty text, cut to the limit; else None."""
    return value[:limit] if isinstance(value, str) and value else None


def _object(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def _commit(value: object) -> str | None:
    """A commit id; "unknown" is what tm-update writes when it could not read one."""
    found = _text(value)
    return None if found == "unknown" else found


def _name(value: object) -> str | None:
    """The last part of a folder's path, when it is a plain name."""
    found = _text(value, 1000)
    if found is None:
        return None
    name = os.path.basename(found.rstrip("/"))
    return None if name in ("", ".", "..") or len(name) > 100 or "\x00" in name else name


def _stages(value: object) -> list[StageRow]:
    rows = []
    for entry in value[:MAX_STAGES] if isinstance(value, list) else []:
        row = _object(entry)
        if _text(row.get("id"), 100) is not None:
            rows.append(
                StageRow(
                    id=_text(row["id"], 100), started_at=_text(row.get("started_at"), 40),
                    finished_at=_text(row.get("finished_at"), 40),
                )
            )
    return rows


def derive(state: object, *, unit_running: bool, marker: bool, boot_id: str | None) -> Run | None:
    """The run to show, or None when there is nothing readable and no unit running."""
    readable = isinstance(state, dict) and state.get("schema") == 1 and not isinstance(state.get("schema"), bool)
    file = state if readable else {}
    final = file.get("result") if file.get("result") in ("ok", "failed") else None
    if unit_running:
        if not readable or final:
            # An unreadable file isn't known to be this run's, and a final one is an older run's until the job writes
            # its own, so neither is shown.
            return Run(status="running", readable=readable)
        return _run("running", file)
    if not readable:
        return None
    if final:
        return _run(final, file)
    # The run stopped without an end. A restart that is about to happen is still part of the run.
    recorded = file.get("boot_id")
    if file.get("stage") == "reboot" and isinstance(recorded, str) and boot_id is not None and recorded == boot_id:
        return _run("running", file)
    return _run("cut_off" if marker else "interrupted", file)


def _run(status: str, file: dict) -> Run:
    origin, target = _object(file.get("from")), _object(file.get("to"))
    stages = _stages(file.get("stages"))
    ended = status in ("ok", "failed")
    return Run(
        status=status,
        readable=True,
        run_id=_text(file.get("run_id"), 40),
        channel=_text(file.get("channel"), 40),
        from_version=_text(origin.get("version"), 100),
        from_commit=_commit(origin.get("commit")),
        to_version=_text(target.get("version"), 100),
        to_commit=_commit(target.get("commit")),
        to_tag=_text(target.get("tag"), 100),
        stage=_text(file.get("stage"), 100),
        stages=stages,
        reason=_text(file.get("reason"), 100),
        detail=_text(file.get("detail")),
        restore_point=_name(file.get("restore_point")),
        finished_at=stages[-1].finished_at if ended and stages else None,
    )


def _state_file(path: Path) -> object:
    """The parsed file, or None when it is missing, too large, or not JSON."""
    try:
        if path.stat().st_size > MAX_FILE:
            return None
        return json.loads(path.read_text())
    except (OSError, ValueError, RecursionError):  # a bad encoding is a ValueError too
        return None


def _running(unit: str) -> bool:
    """False when the unit is inactive or failed; a unit that can't be asked is taken to be running."""
    try:
        return systemd.show_unit(unit, ["ActiveState"]).get("ActiveState") not in ("inactive", "failed")
    except RuntimeError:
        return True


def _boot_id() -> str | None:
    try:
        return BOOT_ID.read_text().strip() or None
    except (OSError, ValueError):
        return None


def read(app_state) -> Run | None:
    """The run to show now: the state file, the two units (as the network join's is read), the marker, and this boot."""
    folder = app_state.settings.update_dir
    try:
        marker = (folder / MARKER_FILE).is_file()
    except OSError:
        marker = False
    return derive(
        _state_file(folder / STATE_FILE),
        unit_running=_running(JOB_UNIT) or _running(RESUME_UNIT),
        marker=marker,
        boot_id=_boot_id(),
    )
