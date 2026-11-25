"""The hand-over file (contract 1): what the caller tells tm-update about the run. Every value is type-checked; an
error names the key and never the value."""

import json
import re
from dataclasses import dataclass
from pathlib import Path

from .paths import Paths

CONTRACT = 1
CHANNELS = ("stable", "development")
_RUN_ID = re.compile(r"[A-Za-z0-9T_-]{1,64}")
_COMMIT = re.compile(r"[0-9a-f]{40}")
_KEYS = ("contract", "run_id", "channel", "commit", "tag", "from_version", "work_dir", "state_path", "log_path")


class HandoverError(ValueError):
    """The hand-over can't be used. The message names a key and says what is wrong with it, never quotes a value."""


@dataclass(frozen=True)
class Handover:
    run_id: str
    channel: str
    commit: str
    tag: "str | None"
    from_version: str
    work_dir: Path
    state_path: Path
    log_path: Path


def _text(data: dict, key: str, *, none_ok: bool = False) -> "str | None":
    value = data[key]
    if value is None and none_ok:
        return None
    if not isinstance(value, str) or not 1 <= len(value) <= 200 or not value.isprintable():
        raise HandoverError(f"{key} is not valid text")
    return value


def _inside(data: dict, key: str, folder: Path) -> Path:
    value = data[key]
    if not isinstance(value, str) or "\x00" in value or not value.startswith("/"):
        raise HandoverError(f"{key} is not an absolute path")
    path = Path(value)
    if ".." in path.parts:
        raise HandoverError(f"{key} is not inside the update folder")
    if path == folder or folder not in path.parents:
        raise HandoverError(f"{key} is not inside the update folder")
    return path


def load(path: Path, paths: Paths) -> Handover:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise HandoverError("the hand-over file can't be read as JSON") from None
    if not isinstance(data, dict):
        raise HandoverError("the hand-over file is not a JSON object")
    for key in _KEYS:
        if key not in data:
            raise HandoverError(f"{key} is missing")
    # bool is a kind of int in Python, and true must not pass for 1
    if type(data["contract"]) is not int or data["contract"] != CONTRACT:
        raise HandoverError("contract is not 1")
    run_id = data["run_id"]
    if not isinstance(run_id, str) or not _RUN_ID.fullmatch(run_id):
        raise HandoverError("run_id is not valid")
    if not isinstance(data["channel"], str) or data["channel"] not in CHANNELS:
        raise HandoverError("channel is not stable or development")
    commit = data["commit"]
    if not isinstance(commit, str) or not _COMMIT.fullmatch(commit):
        raise HandoverError("commit is not a full commit id")
    tag = _text(data, "tag", none_ok=True)
    from_version = _text(data, "from_version")
    folder = paths.update_dir
    return Handover(
        run_id=run_id, channel=data["channel"], commit=commit, tag=tag, from_version=from_version,
        work_dir=_inside(data, "work_dir", folder), state_path=_inside(data, "state_path", folder),
        log_path=_inside(data, "log_path", folder),
    )
