"""The restore point: the device's settings, env files, secrets, unit files, the manifest, and a consistent copy of the
control app's database, saved in a folder only root can open before an update switches, with a list of what is in it.

Nothing here is logged or quoted: a secret's copy is the only place its value appears, and for a file under the
secrets folder the list holds the path, the mode, and the owner, with no size and no checksum."""

import hashlib
import json
import os
import re
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from .handover import Handover
from .installed import Installed
from .paths import Paths

SCHEMA = 1
KEEP = 2
_NAME = re.compile(r"\d{8}T\d{6}Z-[0-9a-f]{7}")
_PARTIAL = re.compile(r"(\d{8}T\d{6}Z-[0-9a-f]{7})\.partial")
_COMMIT = re.compile(r"[0-9a-f]{40}")
_PAGES = 256  # database pages copied between two looks at the source


def _progress(status: int, remaining: int, total: int) -> None:
    """Called after each batch of pages of the database copy."""


def _give(path: Path, uid: int, gid: int) -> None:
    """Give a copy the owner and group of its original; nothing to do when it already has them."""
    info = path.stat()
    if (info.st_uid, info.st_gid) != (uid, gid):
        os.chown(path, uid, gid)


def _private_dir(path: Path) -> None:
    """Make a folder (and the ones above it, below the restore point) root's alone, whatever the umask."""
    missing = []
    walk = path
    while not walk.is_dir():
        missing.append(walk)
        walk = walk.parent
    for folder in reversed(missing):
        folder.mkdir()
        folder.chmod(0o700)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _regular(path: Path) -> bool:
    return path.is_file() and not path.is_symlink()


def _files_under(folder: Path) -> "list[Path]":
    found = []
    if not folder.is_dir() or folder.is_symlink():
        return found
    for here, _dirs, names in os.walk(folder, followlinks=False):
        found.extend(Path(here) / name for name in names if _regular(Path(here) / name))
    return sorted(found)


def _listed(installed: Installed, paths: Paths) -> "tuple[list[Path], list[Path]]":
    """The files the restore point is meant to hold, as paths on the device: (those there, those not)."""
    code = paths.rooted(installed.codedir)
    fixed = [
        installed.codedir / "node-red-tm" / "config" / "config.yml",
        installed.codedir / "frigate" / "config" / "config.yml",
        Path("/var/lib/go2rtc/go2rtc.yaml"),
        Path("/etc/polkit-1/rules.d/50-traffic-monitor.rules"),
        Path("/" + str(paths.manifest.relative_to(paths.root))),
    ]
    there = []
    missing = []
    for device in fixed:
        (there if _regular(paths.rooted(device)) else missing).append(device)
    found = []
    if code.is_dir():
        found += [p for p in sorted(code.glob("*/*.env")) if _regular(p)]
        found += [p for p in sorted(code.glob("services/*.service")) if _regular(p)]
    found += _files_under(paths.secrets_dir)
    found += _files_under(paths.rooted(Path("/etc/containers/systemd")))
    units = paths.rooted(Path("/etc/systemd/system"))
    if units.is_dir():
        for entry in sorted(units.glob("tm-*")):
            found += [entry] if _regular(entry) else _files_under(entry)
    return there + [Path("/" + str(p.relative_to(paths.root))) for p in found], missing


def _mode_text(mode: int) -> str:
    return format(mode & 0o7777, "04o")


def _copy_file(source: Path, device: Path, target_root: Path, secret: bool) -> dict:
    info = source.stat()
    target = target_root / str(device).lstrip("/")
    _private_dir(target.parent)
    shutil.copy2(source, target)
    _give(target, info.st_uid, info.st_gid)
    row = {"path": str(device), "mode": _mode_text(info.st_mode), "uid": info.st_uid, "gid": info.st_gid}
    if not secret:
        row["size"] = target.stat().st_size
        row["sha256"] = _sha256(target)
    return row


def _copy_database(source: Path, device: Path, target_root: Path) -> dict:
    """Copy a database with SQLite's backup API, so the copy is whole while the control app keeps writing."""
    info = source.stat()
    target = target_root / str(device).lstrip("/")
    _private_dir(target.parent)
    reader = sqlite3.connect(f"file:{quote(str(source))}?mode=ro", uri=True)
    try:
        writer = sqlite3.connect(target)
        try:
            reader.backup(writer, pages=_PAGES, progress=_progress)
        finally:
            writer.close()
    finally:
        reader.close()
    target.chmod(info.st_mode & 0o7777)
    _give(target, info.st_uid, info.st_gid)
    return {"path": str(device), "mode": _mode_text(info.st_mode), "uid": info.st_uid, "gid": info.st_gid,
            "size": target.stat().st_size, "sha256": _sha256(target)}


def _clear_dead_runs(paths: Paths) -> None:
    for entry in paths.restore_root.iterdir():
        if _PARTIAL.fullmatch(entry.name):
            if entry.is_dir() and not entry.is_symlink():
                shutil.rmtree(entry)
            else:
                entry.unlink()


def make(installed: Installed, handover: Handover, paths: Paths, previous_tree: "Path | None") -> Path:
    """Save the restore point and return its folder. It is built under a name ending in .partial and renamed when
    whole, so a folder with the final name is always complete. Anything that goes wrong removes the partial one."""
    now = datetime.now(timezone.utc)
    short = installed.commit[:7] if _COMMIT.fullmatch(installed.commit) else "0" * 7
    name = now.strftime("%Y%m%dT%H%M%SZ") + "-" + short
    _private_dir(paths.restore_root)
    paths.restore_root.chmod(0o700)
    _clear_dead_runs(paths)
    final = paths.restore_root / name
    partial = paths.restore_root / (name + ".partial")
    _private_dir(partial)
    try:
        target_root = partial / "files"
        _private_dir(target_root)
        secrets_dir = paths.secrets_dir
        there, missing = _listed(installed, paths)
        rows = []
        for device in there:
            source = paths.rooted(device)
            rows.append(_copy_file(source, device, target_root, secrets_dir in source.parents))
        database = Path("/var/lib/tm-control/state.sqlite")
        if _regular(paths.tm_control_state):
            rows.append(_copy_database(paths.tm_control_state, database, target_root))
        else:
            missing.append(database)
        document = {
            "schema": SCHEMA,
            "made_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "from": {"version": installed.tm_version, "commit": installed.commit},
            "to": {"commit": handover.commit},
            "previous_tree": str(previous_tree) if previous_tree is not None else None,
            "tmdb_backup": None,
            "files": rows,
            "missing": [str(device) for device in missing],
        }
        listing = partial / "restore.json"
        descriptor = os.open(listing, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            os.fchmod(handle.fileno(), 0o600)
            json.dump(document, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.rename(partial, final)
    except BaseException:
        shutil.rmtree(partial, ignore_errors=True)
        raise
    return final


def keep_newest(paths: Paths, count: int = KEEP) -> None:
    """Remove all but the newest restore points, by name (the time comes first). Anything else in the folder, a
    partial one included, is left alone."""
    if not paths.restore_root.is_dir():
        return
    folders = sorted(entry for entry in paths.restore_root.iterdir()
                     if _NAME.fullmatch(entry.name) and entry.is_dir() and not entry.is_symlink())
    for entry in folders[:max(len(folders) - count, 0)]:
        shutil.rmtree(entry)
