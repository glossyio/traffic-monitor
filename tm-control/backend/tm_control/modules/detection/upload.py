"""Writing an upload into model_cache: what it is by its name, the caps, the free-space floor, and a body streamed to a
temporary name that is placed under its own name only once it's complete and checked.

Every name is opened relative to the cache's directory descriptor without following a link, and a temporary name is
created with O_EXCL. A temporary name starts with a dot, so the inventory skips it while it's written, and every
refusal or failure removes it.
"""

import os
import secrets
import stat
from pathlib import Path
from typing import AsyncIterator, Literal

from starlette.concurrency import run_in_threadpool

from tm_control.modules.detection.inventory import SIDECAR_MAX, open_in
from tm_control.modules.system.checks import STORAGE_ERROR

FREE_SPACE_MIN = STORAGE_ERROR  # the Device check's problem threshold: an upload mustn't be what trips it
MAGIC = {"zip": b"PK\x03\x04", "gzip": b"\x1f\x8b"}
ARCHIVES = {".zip": "zip", ".tar.gz": "gzip", ".tgz": "gzip"}
ARCHIVE_TITLES = {"zip": "zip", "gzip": "tar.gz"}
TEMP_MAX = 200

BAD_NAME = "That name isn't allowed."
NO_SPACE = "The device would have less than 512 MB free."
SHORT_BODY = "The body ended before Content-Length."
LONG_BODY = "The body is longer than Content-Length."
EMPTY = "The file is empty."
FILE_TOO_LARGE = "The file is larger than 100 MB."
SIDECAR_TOO_LARGE = "The sidecar is larger than 2 MB."


class UploadError(Exception):
    """A refused upload: the HTTP status and a fixed message that never quotes what was sent."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def exists(name: str) -> UploadError:
    return UploadError(409, f"A model named {name} is already on the device; delete it first.")


def too_large(limit: int) -> UploadError:
    return UploadError(413, SIDECAR_TOO_LARGE if limit == SIDECAR_MAX else FILE_TOO_LARGE)


def kind_of_upload(filename: str) -> Literal["archive", "sidecar", "model"]:
    """An archive by its ending (its first bytes must agree), a sidecar for .json, else a model file."""
    if archive_kind(filename) is not None:
        return "archive"
    return "sidecar" if filename.endswith(".json") else "model"


def archive_kind(filename: str) -> Literal["zip", "gzip"] | None:
    return next((kind for ending, kind in ARCHIVES.items() if filename.endswith(ending)), None)


def free_space_ok(cache: Path | int, needed: int) -> bool:
    """Whether the file system, given by a path or a descriptor, would still have FREE_SPACE_MIN bytes for
    unprivileged users after `needed` more."""
    try:
        found = os.statvfs(cache)
    except OSError:
        return False
    return found.f_bavail * found.f_frsize - needed >= FREE_SPACE_MIN


def temp_name(name: str) -> str:
    return f".upload-{secrets.token_hex(4)}-{name}"[:TEMP_MAX]


def unlink_quietly(dir_fd: int, name: str) -> None:
    try:
        os.unlink(name, dir_fd=dir_fd)
    except FileNotFoundError:
        pass


def write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        view = view[os.write(fd, view):]


async def receive(stream: AsyncIterator[bytes], dir_fd: int, temp_name: str, limit: int, declared: int | None) -> int:
    """Write the stream to a new file named temp_name and return its size. More than `limit` bytes, or more than
    `declared`, is a 413 (nothing past either is written); a stream that ends short of `declared` is a 400. On any
    failure the file is removed."""
    cap = limit if declared is None else min(limit, declared)
    fd = open_in(dir_fd, temp_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        try:
            size = 0
            async for chunk in stream:
                size += len(chunk)
                if size > cap:
                    raise too_large(limit) if size > limit else UploadError(413, LONG_BODY)
                if chunk:
                    await run_in_threadpool(write_all, fd, chunk)
            if declared is not None and size < declared:
                raise UploadError(400, SHORT_BODY)
            await run_in_threadpool(os.fsync, fd)
        finally:
            os.close(fd)
    except BaseException:  # a disconnect cancels as well as raises
        unlink_quietly(dir_fd, temp_name)
        raise
    return size


def write_new(dir_fd: int, temp: str, data: bytes) -> None:
    """Write data to a new file named temp, synced; removed again if the write fails."""
    fd = open_in(dir_fd, temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        try:
            write_all(fd, data)
            os.fsync(fd)
        finally:
            os.close(fd)
    except BaseException:
        unlink_quietly(dir_fd, temp)
        raise


def read_small(dir_fd: int, name: str, limit: int) -> bytes:
    """At most limit bytes of a regular file in the directory."""
    fd = open_in(dir_fd, name, os.O_RDONLY)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise OSError("not a regular file")
        data = b""
        while len(data) < limit and (block := os.read(fd, limit - len(data))):
            data += block
        return data
    finally:
        os.close(fd)


def place(dir_fd: int, temp: str, final: str) -> None:
    """Give the temporary file its own name, then sync the directory. A name that appeared since the upload was
    checked is never replaced: the link fails, the 409 is raised, and the caller removes the temporary name."""
    try:
        os.link(temp, final, src_dir_fd=dir_fd, dst_dir_fd=dir_fd, follow_symlinks=False)
    except FileExistsError:
        raise exists(final.removesuffix(".json")) from None
    os.unlink(temp, dir_fd=dir_fd)
    os.fsync(dir_fd)


def check_archive(dir_fd: int, temp: str, kind: Literal["zip", "gzip"]) -> None:
    if read_small(dir_fd, temp, len(MAGIC[kind])) != MAGIC[kind]:
        raise UploadError(422, f"The file isn't a {ARCHIVE_TITLES[kind]} archive.")
