"""What the install manifest says about the device, and the refusals that come before anything changes."""

import grp
import json
import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from .paths import Paths
from .state import Failed

# What an update does with each tmsetup.sh -C option. Every name in tmsetup.sh's _VALID_CUSTOM_VARS is in exactly one.
OPTIONS_PASSED_BACK = ()  # a standing choice, passed again as tmsetup_bool_<name>=true
OPTIONS_KEPT_IN_FILES = ("mqtt_lan",)  # acted once; its result is in a file the installer keeps
OPTIONS_REFUSED = ("plate_recognizer",)  # a device that has it is not updated this way

_BASE = 8_000_000_000
_USER = re.compile(r"[a-z_][a-z0-9_-]{0,31}")
_DIR = re.compile(r"/[A-Za-z0-9._-][A-Za-z0-9._/-]*")
_REPO = re.compile(r"[A-Za-z0-9._-]+/[A-Za-z0-9._-]+")
_COMMIT = re.compile(r"[0-9a-f]{40}|unknown")


@dataclass(frozen=True)
class Installed:
    tm_version: str
    commit: str
    installing_user: str
    codedir: Path
    codeowner: str
    codegroup: str
    repo: "str | None"
    plate_recognizer: bool
    options: dict = field(default_factory=dict)  # the manifest's options that are on, by name


class Refusal(Failed):
    """A Failed raised before anything changed."""


def _bad(detail: str) -> Refusal:
    return Refusal("needs_manual_update", detail)


def _text(value: object, name: str, pattern: "re.Pattern | None" = None) -> str:
    if not isinstance(value, str) or not value or not value.isprintable() or len(value) > 200:
        raise _bad(f"manifest {name}")
    if pattern is not None and not pattern.fullmatch(value):
        raise _bad(f"manifest {name}")
    return value


def _section(data: dict, key: str) -> dict:
    value = data.get(key, {})
    if not isinstance(value, dict):
        raise _bad(f"manifest {key}")
    return value


def _repository(update: dict) -> "str | None":
    if "repo" not in update:
        return None
    repo = update["repo"]
    # The value becomes part of a URL, so a segment of only dots (. and ..) is refused here, though the role allows it
    if (not isinstance(repo, str) or not _REPO.fullmatch(repo)
            or any(set(part) == {"."} for part in repo.split("/"))):
        raise _bad("manifest update.repo")
    return repo


def read(paths: Paths) -> Installed:
    try:
        data = json.loads(paths.manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise _bad("manifest unreadable") from None
    if not isinstance(data, dict):
        raise _bad("manifest")
    user = _text(data.get("installing_user"), "installing_user", _USER)
    if user == "root":
        raise _bad("manifest installing_user")
    codedir = _text(data.get("codedir"), "codedir", _DIR)
    if ".." in Path(codedir).parts:
        raise _bad("manifest codedir")
    codeowner = _text(data.get("codeowner"), "codeowner", _USER)
    git = _section(data, "git")
    commit = _text(git.get("commit"), "git.commit", _COMMIT)
    version = _text(data.get("tm_version"), "tm_version")
    options = _section(data, "options")
    if not all(isinstance(value, bool) for value in options.values()):
        raise _bad("manifest options")
    repo = _repository(_section(data, "update"))
    try:
        group = grp.getgrgid(os.stat(paths.rooted(Path(codedir))).st_gid).gr_name
    except (OSError, KeyError):
        raise _bad("the code folder's group") from None
    return Installed(
        tm_version=version, commit=commit, installing_user=user, codedir=Path(codedir), codeowner=codeowner,
        codegroup=group, repo=repo,
        plate_recognizer=options.get("plate_recognizer") is True or paths.plate_recognizer_unit.exists(),
        options={name: True for name, value in options.items() if value},
    )


def space_needed(db_bytes: int) -> int:
    """8 GB plus 1.2 times the database, in whole bytes."""
    return _BASE + (db_bytes * 6 + 4) // 5


def _free_bytes(path: Path) -> int:
    return shutil.disk_usage(path).free


def _database_bytes(codedir: Path) -> int:
    try:
        return os.stat(codedir / "node-red-tm" / "db" / "tmdb.sqlite").st_size  # its size only; never opened
    except OSError:
        return 0


def _megabytes(count: int) -> int:
    return count // 1_000_000


def check_before_prepare(installed: Installed, paths: Paths) -> None:
    if installed.plate_recognizer or paths.plate_recognizer_unit.exists():
        raise Refusal("addon_needs_installer")
    if paths.reboot_required.exists():
        raise Refusal("reboot_pending")
    needed = space_needed(_database_bytes(paths.rooted(installed.codedir)))
    free = _free_bytes(paths.update_dir if paths.update_dir.exists() else paths.root)
    if free < needed:
        raise Refusal("low_space", f"{_megabytes(free)} MB free, {_megabytes(needed)} MB needed")


def check_database_space(installed: Installed, paths: Paths) -> None:
    """The copy of the database the migration runner makes needs 1.2 times its size free on the code folder's
    filesystem."""
    code = paths.rooted(installed.codedir)
    needed = (_database_bytes(code) * 6 + 4) // 5
    free = _free_bytes(code)
    if free < needed:
        raise Refusal("low_space", f"{_megabytes(free)} MB free, {_megabytes(needed)} MB needed")
