"""The state file of a run: one JSON file, replaced whole each time it changes, which the control app reads while the
run goes on. It holds codes and numbers, never a line from another program and never a secret."""

import copy
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .handover import CONTRACT, Handover
from .paths import Paths

SCHEMA = 1
STAGES = ("prepare", "images", "restore_point", "switch", "reboot", "health", "cleanup")
REASONS = ("busy", "needs_manual_update", "addon_needs_installer", "reboot_pending", "low_space", "no_internet",
           "hardware_needs_installer", "settings_need_attention", "prepare_failed", "build_failed", "switch_failed",
           "health_failed")
RESULTS = ("ok", "failed")
SETTABLE = ("restore_point", "tmdb_backup", "reboot", "boot_id", "switch_attempts")
_DETAIL_LIMIT = 200


class Failed(Exception):
    """A run that ends here: a reason code and a short detail this code made (a step's name, numbers)."""

    def __init__(self, reason: str, detail: "str | None" = None):
        if reason not in REASONS:
            raise ValueError("not a reason code")
        super().__init__(reason if detail is None else f"{reason}: {detail}")
        self.reason = reason
        self.detail = detail


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_whole(path: Path, data: dict) -> None:
    """Write beside the file, sync, then rename over it: a reader sees the old file or the new one, never half."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".state-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            os.fchmod(handle.fileno(), 0o644)
            json.dump(data, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _fresh(handover: Handover, installed, to_version: "str | None") -> dict:
    return {
        "schema": SCHEMA, "run_id": handover.run_id, "channel": handover.channel,
        "from": {"version": installed.tm_version if installed else None,
                 "commit": installed.commit if installed else None},
        "to": {"version": to_version, "commit": handover.commit, "tag": handover.tag},
        "stage": None, "stages": [], "result": None, "reason": None, "detail": None, "boot_id": None,
        "reboot": None, "restore_point": None, "tmdb_backup": None, "switch_attempts": 0,
    }


def _usable(old: object, run_id: str) -> bool:
    return (isinstance(old, dict) and old.get("run_id") == run_id and isinstance(old.get("stages", []), list)
            and all(isinstance(row, dict) for row in old.get("stages", [])))


class State:
    def __init__(self, path: Path, data: dict):
        self._path = path
        self._data = data

    @classmethod
    def open(cls, handover: Handover, installed, to_version: "str | None") -> "State":
        """Carry on the file when it is this run's (the caller may have started it), else start a new one."""
        data = _fresh(handover, installed, to_version)
        try:
            old = json.loads(handover.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            old = None
        if _usable(old, handover.run_id):
            for key in ("stage", "stages", "boot_id", "reboot", "restore_point", "tmdb_backup", "switch_attempts"):
                if key in old:
                    data[key] = old[key]
        state = cls(handover.state_path, data)
        state._save()
        return state

    @classmethod
    def carry_on(cls, handover: Handover) -> "State | None":
        """The state of this run when a restart cut it off: its file, still running, every key kept (its from as
        well, which the manifest no longer knows after a switch). None when the file is another run's, has ended, or
        can't be read as one."""
        try:
            old = json.loads(handover.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not _usable(old, handover.run_id) or old.get("result") is not None:
            return None
        attempts = old.get("switch_attempts", 0)
        if (old.get("stage") not in STAGES or type(attempts) is not int or attempts < 0
                or not isinstance(old.get("boot_id"), (str, type(None)))):
            return None
        data = _fresh(handover, None, None)
        for key in data:
            if key in old:
                data[key] = old[key]
        return cls(handover.state_path, data)

    @property
    def data(self) -> dict:
        return copy.deepcopy(self._data)

    def _save(self) -> None:
        _write_whole(self._path, self._data)

    def begin(self, stage: str) -> None:
        if stage not in STAGES:
            raise ValueError("not a stage id")
        self._data["stage"] = stage
        self._data["stages"].append({"id": stage, "started_at": _now(), "finished_at": None})
        self._save()

    def _close(self, stage: "str | None") -> None:
        for row in reversed(self._data["stages"]):
            if row.get("finished_at") is None and (stage is None or row.get("id") == stage):
                row["finished_at"] = _now()
                return

    def finish(self, stage: str) -> None:
        self._close(stage)
        self._save()

    def set(self, **keys) -> None:
        for key in keys:
            if key not in SETTABLE:
                raise ValueError("not a key a stage may set")
        self._data.update(keys)
        self._save()

    def end(self, result: str, reason: "str | None" = None, detail: "str | None" = None) -> None:
        if result not in RESULTS:
            raise ValueError("not a result")
        if result == "ok" and reason is not None:
            raise ValueError("a run that ended well has no reason")
        if result == "failed" and reason not in REASONS:
            raise ValueError("a failed run needs a reason code")
        if detail is not None:
            detail = " ".join(str(detail).split())[:_DETAIL_LIMIT]
        self._close(None)
        self._data.update(result=result, reason=reason, detail=detail)
        self._save()


def write_marker(paths: Paths, tree: Path, handover_path: Path) -> None:
    """Tell a restart which tree and hand-over to carry on with (resume.json)."""
    _write_whole(paths.resume, {"contract": CONTRACT, "tree": str(tree), "handover": str(handover_path)})


def clear_marker(paths: Paths) -> None:
    try:
        paths.resume.unlink()
    except FileNotFoundError:
        pass
