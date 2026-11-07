"""A model packaged for download: a zip of its file, its sidecar, and SHA256SUMS, which an upload of the zip checks.

The files are read through model_cache's descriptor without following a link, and the zip is written to a new name
in tm-control's own state directory, which the route removes once it has been sent.
"""

import hashlib
import os
import secrets
import stat
import time
import zipfile
from pathlib import Path
from typing import BinaryIO

from tm_control.modules.detection.archives import SUMS_NAME
from tm_control.modules.detection.inventory import HASH_BLOCK, SIDECAR, open_cache, open_in, stat_in

PACKAGES = "packages"
STALE_AFTER = 3600  # seconds: a package this old was left by a download that never finished
ENTRY_MODE = (stat.S_IFREG | 0o644) << 16


def _date_time(mtime: float) -> tuple[int, int, int, int, int, int]:
    """A zip entry's local time, inside the range a zip can hold."""
    found = time.localtime(mtime)[:6]
    return max(min(found, (2107, 12, 31, 23, 59, 58)), (1980, 1, 1, 0, 0, 0))


def _add(archive: zipfile.ZipFile, dir_fd: int, name: str) -> tuple[str, float]:
    """Add the regular file to the zip in 1 MiB blocks; returns the SHA-256 of what was added and its mtime."""
    fd = open_in(dir_fd, name, os.O_RDONLY)
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode):
            raise OSError("not a regular file")
        info = zipfile.ZipInfo(name, _date_time(opened.st_mtime))
        info.external_attr = ENTRY_MODE
        info.file_size = opened.st_size  # lets zipfile choose ZIP64 up front for a large file
        digest = hashlib.sha256()
        with archive.open(info, "w") as entry:
            while block := os.read(fd, HASH_BLOCK):
                entry.write(block)
                digest.update(block)
    finally:
        os.close(fd)
    return digest.hexdigest(), opened.st_mtime


def write_package(dir_fd: int, name: str, out: BinaryIO) -> None:
    """A stored zip of <name>, <name>.json, and SHA256SUMS (sha256sum's format) for the bytes added. The sums entry
    carries the newer of the two files' mtimes, so an unchanged model always packages the same."""
    with zipfile.ZipFile(out, "w", zipfile.ZIP_STORED) as archive:
        lines, newest = [], 0.0
        for file in (name, name + SIDECAR):
            digest, mtime = _add(archive, dir_fd, file)
            lines.append(f"{digest}  {file}\n")
            newest = max(newest, mtime)
        info = zipfile.ZipInfo(SUMS_NAME, _date_time(newest))
        info.external_attr = ENTRY_MODE
        archive.writestr(info, "".join(lines))


def _sweep(dir_fd: int) -> None:
    now = time.time()
    for entry in os.listdir(dir_fd):
        found = stat_in(dir_fd, entry)
        if found is not None and stat.S_ISREG(found.st_mode) and now - found.st_mtime > STALE_AFTER:
            try:
                os.unlink(entry, dir_fd=dir_fd)
            except FileNotFoundError:
                pass


def create(state_dir: Path, name: str) -> tuple[Path, BinaryIO]:
    """A new, empty file for the package in <state_dir>/packages (created 0700), named <name>-<random>.zip and
    created O_EXCL, 0600. Packages older than STALE_AFTER are removed first."""
    directory = state_dir / PACKAGES
    try:
        directory.mkdir(mode=0o700)
    except FileExistsError:
        pass
    dir_fd = open_cache(directory)
    try:
        _sweep(dir_fd)
        file = f"{name}-{secrets.token_hex(8)}.zip"
        fd = open_in(dir_fd, file, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
    finally:
        os.close(dir_fd)
    return directory / file, os.fdopen(fd, "w+b")
