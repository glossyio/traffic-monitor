"""A model uploaded as a zip or tar.gz: its file, its <file>.json sidecar, and optionally SHA256SUMS, unpacked into
model_cache.

The archive is never trusted. It's read from a file object, never by name, and nothing in it is extracted by
zipfile or tarfile: each member's name is checked, and each member is copied by hand to a new temporary name in the
cache. At most ENTRIES_MAX entries are examined, ignored ones included. A member that is a link, a device, or
anything but a plain file is refused, and so is any name with a path. Declared sizes are checked against the caps
before anything is read, and a copy stops one byte past its cap whatever the header said. The two halves are placed
under their own names only once both are complete and SHA256SUMS, when there is one, matches them. A name already in
the cache is never replaced, and every temporary name is removed on the way out.
"""

import gzip
import hashlib
import os
import re
import stat
import tarfile
import zipfile
from collections.abc import Container
from dataclasses import dataclass
from typing import BinaryIO, Callable, Literal

from tm_control.modules.detection import upload
from tm_control.modules.detection.inventory import (
    HASH_BLOCK,
    MODEL_FILE_MAX,
    SIDECAR,
    SIDECAR_MAX,
    SidecarError,
    open_in,
    parse_sidecar,
    stat_in,
    valid_name,
)
from tm_control.modules.detection.upload import UploadError

MEMBERS_MAX = 3
ENTRIES_MAX = 32  # entries examined in all, the ignored ones counted
SUMS_NAME = "SHA256SUMS"
SUMS_MAX = 4096  # two lines are under 400 bytes
CENTRAL_MAX = 256 * 1024  # a zip's central directory for ENTRIES_MAX entries is a few kilobytes
TAR_MAX = MODEL_FILE_MAX + SIDECAR_MAX + SUMS_MAX + 1024 * 1024  # decompressed, headers and padding included
IGNORED_PREFIX = "__MACOSX/"
SUM_LINE = re.compile(r"([0-9A-Fa-f]{64}) [ *](.+)")

NO_PAIR = "The archive has no model file and sidecar pair."
TOO_MANY = "The archive holds more than a model, its sidecar, and SHA256SUMS."
NOT_PLAIN = "An archive member has a path, or isn't a plain file."
TOO_LARGE = "An archive member is larger than its cap."
MISMATCH = "SHA256SUMS doesn't match the files."
UNREADABLE = "The archive can't be read."


class ArchiveError(ValueError):
    """A refused archive, with one of the fixed messages above and its HTTP status."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message
        self.status = 413 if message == TOO_LARGE else 422


@dataclass
class Member:
    name: str
    size: int  # as the archive declares it
    open: Callable[[], BinaryIO]


def cap_of(name: str) -> int:
    if name == SUMS_NAME:
        return SUMS_MAX
    return SIDECAR_MAX if name.endswith(SIDECAR) else MODEL_FILE_MAX


def _ignored(name: str) -> bool:
    return name.startswith(IGNORED_PREFIX)


def _kept(name: str, size: int) -> bool:
    """Whether an entry that isn't a directory is one of the members: False for one that is ignored. A name with a
    path, or a size over its cap, is refused."""
    if _ignored(name):
        return False
    if "/" in name or "\\" in name:
        raise ArchiveError(NOT_PLAIN)
    if name.startswith("."):
        return False
    if size > cap_of(name):
        raise ArchiveError(TOO_LARGE)
    return True


class _Capped:
    """The decompressed tar stream, refusing any read or seek past TAR_MAX bytes, so that neither a member that is
    skipped nor a header that claims a huge extension is decompressed without end."""

    def __init__(self, raw: gzip.GzipFile):
        self.raw = raw

    def read(self, size: int = -1) -> bytes:
        position = self.raw.tell()
        if size is None or size < 0:
            size = TAR_MAX + 1 - position
        if position + size > TAR_MAX:
            raise ArchiveError(TOO_LARGE)
        return self.raw.read(size)

    def seek(self, offset: int, whence: int = os.SEEK_SET) -> int:
        if whence not in (os.SEEK_SET, os.SEEK_CUR):
            raise ArchiveError(UNREADABLE)
        target = offset if whence == os.SEEK_SET else self.raw.tell() + offset
        if target > TAR_MAX:
            raise ArchiveError(TOO_LARGE)
        return self.raw.seek(target)

    def tell(self) -> int:
        return self.raw.tell()


def _tar_members(file: BinaryIO) -> list[Member]:
    tar = tarfile.TarFile(fileobj=_Capped(gzip.GzipFile(fileobj=file, mode="rb")), mode="r")
    found = []
    examined = 0
    while (info := tar.next()) is not None:
        examined += 1
        if examined > ENTRIES_MAX:
            raise ArchiveError(TOO_MANY)
        if info.isdir():
            continue
        if not _kept(info.name, info.size):
            continue
        if not info.isfile():
            raise ArchiveError(NOT_PLAIN)
        found.append(Member(info.name, info.size, lambda info=info: tar.extractfile(info)))
        if len(found) > MEMBERS_MAX:
            raise ArchiveError(TOO_MANY)
    return found


def _zip_directory_ok(file: BinaryIO) -> None:
    """Refuse a zip whose end record promises more entries, or a larger central directory, than ENTRIES_MAX could
    take, before zipfile parses it; zipfile reads the whole directory, whatever the count says."""
    end_record = getattr(zipfile, "_EndRecData", None)
    if end_record is None:
        return
    found = end_record(file)
    if found is None:
        raise ArchiveError(UNREADABLE)
    if found[zipfile._ECD_ENTRIES_TOTAL] > ENTRIES_MAX or found[zipfile._ECD_SIZE] > CENTRAL_MAX:
        raise ArchiveError(TOO_MANY)
    file.seek(0)


def _zip_members(file: BinaryIO) -> list[Member]:
    _zip_directory_ok(file)
    archive = zipfile.ZipFile(file)
    infos = archive.infolist()
    if len(infos) > ENTRIES_MAX:
        raise ArchiveError(TOO_MANY)
    found = []
    for info in infos:
        if info.is_dir() or not _kept(info.filename, info.file_size):
            continue
        if info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
            raise ArchiveError(UNREADABLE)  # zipfile inflates the others a whole chunk at a time, whatever the cap
        kind = stat.S_IFMT(info.external_attr >> 16)
        if kind and kind != stat.S_IFREG:  # the type bits are set only by Unix tools; set, they must say a file
            raise ArchiveError(NOT_PLAIN)
        found.append(Member(info.filename, info.file_size, lambda info=info: archive.open(info)))
        if len(found) > MEMBERS_MAX:
            raise ArchiveError(TOO_MANY)
    return found


def members(file: BinaryIO, kind: Literal["zip", "gzip"]) -> list[Member]:
    """The archive's members in archive order, without directories, names starting with a dot, or anything under
    __MACOSX/. Each member's open() works while `file` is open."""
    return _reading(_zip_members if kind == "zip" else _tar_members, file)


def _reading(call: Callable, *args):
    """call(*args), with whatever an archive that doesn't parse makes it raise turned into UNREADABLE."""
    try:
        return call(*args)
    except ArchiveError:
        raise
    except Exception:
        raise ArchiveError(UNREADABLE) from None


def copy_member(member: Member, dir_fd: int, cap: int, created: list[str]) -> tuple[str, bytes | None]:
    """Copy the member to a new temporary name in the directory, synced, and add the name to `created` (the caller
    removes it). Returns the SHA-256 of the bytes written, and the bytes themselves for a sidecar. No more than cap+1
    bytes are read, and fewer bytes than the member declared make it unreadable."""
    temp = upload.temp_name(member.name)
    fd = open_in(dir_fd, temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    created.append(temp)
    digest = hashlib.sha256()
    kept = [] if member.name.endswith(SIDECAR) else None
    total = 0
    try:
        with _reading(member.open) as source:
            while block := _reading(source.read, min(HASH_BLOCK, cap + 1 - total)):
                total += len(block)
                if total > cap:
                    raise ArchiveError(TOO_LARGE)
                upload.write_all(fd, block)
                digest.update(block)
                if kept is not None:
                    kept.append(block)
        if total != member.size:
            raise ArchiveError(UNREADABLE)
        os.fsync(fd)
    finally:
        os.close(fd)
    return digest.hexdigest(), None if kept is None else b"".join(kept)


def check_sums(data: bytes, expected: dict[str, str]) -> None:
    """SHA256SUMS must list exactly the expected names, once each, with their hashes, in sha256sum's format."""
    try:
        text = data.decode("ascii")
    except UnicodeDecodeError:
        raise ArchiveError(MISMATCH) from None
    listed: dict[str, str] = {}
    for line in text.split("\n"):
        line = line.removesuffix("\r")
        if not line:
            continue
        found = SUM_LINE.fullmatch(line)
        if found is None or found[2] in listed:
            raise ArchiveError(MISMATCH)
        listed[found[2]] = found[1].lower()
    if listed != expected:
        raise ArchiveError(MISMATCH)


def _pair(found: list[Member]) -> tuple[Member, Member, Member | None]:
    sums = [member for member in found if member.name == SUMS_NAME]
    rest = [member for member in found if member.name != SUMS_NAME]
    if len(sums) > 1 or len(rest) > 2:
        raise ArchiveError(TOO_MANY)
    models = [member for member in rest if not member.name.endswith(SIDECAR)]
    if len(rest) != 2 or len(models) != 1:
        raise ArchiveError(NO_PAIR)
    model = models[0]
    sidecar = next(member for member in rest if member is not model)
    if sidecar.name != model.name + SIDECAR:
        raise ArchiveError(NO_PAIR)
    return model, sidecar, sums[0] if sums else None


def _place_both(dir_fd: int, halves: list[tuple[str, str]]) -> None:
    """Place each (temporary, final) name; when one is refused, the halves already placed are removed again, as
    long as they are still the files this placed."""
    placed: list[tuple[str, int]] = []
    try:
        for temp, final in halves:
            placed.append((final, os.stat(temp, dir_fd=dir_fd, follow_symlinks=False).st_ino))
            upload.place(dir_fd, temp, final)
    except BaseException:
        for final, inode in placed:
            found = stat_in(dir_fd, final)
            if found is not None and found.st_ino == inode:
                upload.unlink_quietly(dir_fd, final)
        raise


def extract(file: BinaryIO, kind: Literal["zip", "gzip"], dir_fd: int, reserved: Container[str] = ()
            ) -> tuple[str, str, bool]:
    """Unpack the archive's model and sidecar into the directory and return (model, sidecar, sums_checked).
    `reserved` holds the model names that may not be written (the defaults'). Raises ArchiveError, SidecarError, or
    UploadError (a bad or taken name, an empty model file, too little free space)."""
    found = members(file, kind)
    model, sidecar, sums = _pair(found)
    if not valid_name(model.name):
        raise UploadError(422, upload.BAD_NAME)
    if stat_in(dir_fd, model.name) is not None or stat_in(dir_fd, sidecar.name) is not None:
        raise upload.exists(model.name)
    if model.name in reserved:
        raise UploadError(422, upload.BAD_NAME)  # a default's file is the installer's or Frigate's to write
    if model.size == 0:
        raise UploadError(422, upload.EMPTY)
    if not upload.free_space_ok(dir_fd, model.size + sidecar.size):
        raise UploadError(507, upload.NO_SPACE)
    created: list[str] = []
    temps: dict[str, str] = {}
    hashes: dict[str, str] = {}
    sidecar_data = sums_data = b""
    try:
        for member in found:  # in archive order, so a tar is read front to back
            if member is sums:
                with _reading(member.open) as source:
                    sums_data = _reading(source.read, SUMS_MAX + 1)
                if len(sums_data) > SUMS_MAX:
                    raise ArchiveError(TOO_LARGE)
                continue
            hashes[member.name], data = copy_member(member, dir_fd, cap_of(member.name), created)
            temps[member.name] = created[-1]
            if member is sidecar:
                sidecar_data = data
        parse_sidecar(sidecar_data)
        if sums is not None:
            check_sums(sums_data, hashes)
        _place_both(dir_fd, [(temps[model.name], model.name), (temps[sidecar.name], sidecar.name)])
    finally:
        for temp in created:
            upload.unlink_quietly(dir_fd, temp)
    return model.name, sidecar.name, sums is not None


def place_archive(dir_fd: int, temp: str, kind: Literal["zip", "gzip"], reserved: Container[str] = ()) -> str:
    """Unpack the archive staged under the temporary name `temp` in the directory and return the model's name. The
    staged file is opened through the directory's descriptor, without following a link, and removed on the way out.
    Every refusal is an UploadError."""
    try:
        try:
            fd = open_in(dir_fd, temp, os.O_RDONLY)
        except OSError:
            raise ArchiveError(UNREADABLE) from None
        with os.fdopen(fd, "rb") as file:
            if not stat.S_ISREG(os.fstat(file.fileno()).st_mode):
                raise ArchiveError(UNREADABLE)
            return extract(file, kind, dir_fd, reserved)[0]
    except ArchiveError as error:
        raise UploadError(error.status, error.message) from None
    except SidecarError as error:
        raise UploadError(422, str(error)) from None
    finally:
        upload.unlink_quietly(dir_fd, temp)
