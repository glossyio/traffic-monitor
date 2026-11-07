"""Frigate's model_cache directory as a list of models, each file with its SHA-256.

A model is a file plus a sidecar named <file>.json, in the shape of a Frigate+ model record. Everything here opens
names relative to a descriptor for the directory (opened without following a link at the end), never follows a link
on a file, and never lets one bad entry stop the others from being listed.

Sidecars are read for the eight fields Frigate reads and nothing else: a record's other fields, such as the counts
Frigate+ keeps per camera, are never kept.
"""

import errno
import hashlib
import json
import os
import re
import stat
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from tm_control.modules.apps.contracts import installer_model_file

NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
PLUS_ID = re.compile(r"[0-9a-f]{32}")
MODEL_FILE_MAX = 100 * 1024 * 1024
SIDECAR_MAX = 2 * 1024 * 1024
SIDECAR = ".json"
CONFIG_PREFIX = "/config/"  # where Frigate's container sees the directory tmsetup mounts at <codedir>/frigate/config
HASH_BLOCK = 1024 * 1024
LABEL_KEY = re.compile(r"[0-9]{1,9}")

FILE_UNREADABLE = "The file can't be read."
SIDECAR_UNREADABLE = "The sidecar can't be read."
SIDECAR_TOO_LARGE = "The sidecar is too large."


def valid_name(name: str) -> bool:
    """A file name tm-control may write or read in model_cache: ASCII, no path, not hidden, not a sidecar's."""
    return NAME.fullmatch(name) is not None and not name.endswith(SIDECAR) and name not in (".", "..")


class SidecarError(ValueError):
    """The sidecar can't be used. The message says why, and never quotes the sidecar's content."""


@dataclass(frozen=True)
class Sidecar:
    id: str | None
    name: str | None
    trained_at: str | None
    type: str
    detectors: tuple[str, ...]
    width: int
    height: int
    input_shape: str
    pixel_format: str
    input_dtype: str | None
    labels: tuple[str, ...]  # in label-map index order


def _int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _field(document: dict, field: str, check, optional=False):
    if field not in document:
        if optional:
            return None
        raise SidecarError(f"The sidecar lacks {field}.")
    value = document[field]
    if optional and value is None:
        return None
    if not check(value):
        raise SidecarError(f"The sidecar's {field} has the wrong type.")
    return value


def _text(value) -> bool:
    return isinstance(value, str)


def _optional_text(document: dict, field: str) -> str | None:
    value = document.get(field)
    return value if isinstance(value, str) else None


def parse_sidecar(data: bytes) -> Sidecar:
    """The fields Frigate reads from <id>.json: type, supportedDetectors, width, height, inputShape, pixelFormat,
    labelMap, and optionally inputDataType, checked for presence and type. Every other field is ignored, so a record
    with new fields still parses."""
    try:
        document = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise SidecarError("The sidecar isn't a JSON object.") from None
    if not isinstance(document, dict):
        raise SidecarError("The sidecar isn't a JSON object.")
    kind = _field(document, "type", _text)
    detectors = _field(document, "supportedDetectors", lambda v: isinstance(v, list) and all(_text(i) for i in v))
    width = _field(document, "width", _int)
    height = _field(document, "height", _int)
    input_shape = _field(document, "inputShape", _text)
    pixel_format = _field(document, "pixelFormat", _text)
    label_map = _field(document, "labelMap", lambda v: isinstance(v, dict) and all(_text(i) for i in v.values()))
    input_dtype = _field(document, "inputDataType", _text, optional=True)
    if not detectors:
        raise SidecarError("The sidecar's supportedDetectors is empty.")
    if not all(LABEL_KEY.fullmatch(key) for key in label_map) or len({int(key) for key in label_map}) != len(label_map):
        raise SidecarError("The sidecar's labelMap keys must be decimal strings.")
    labels = tuple(label_map[key] for key in sorted(label_map, key=int))
    return Sidecar(
        id=_optional_text(document, "id"), name=_optional_text(document, "name"),
        trained_at=_optional_text(document, "trainDate"), type=kind, detectors=tuple(detectors), width=width,
        height=height, input_shape=input_shape, pixel_format=pixel_format, input_dtype=input_dtype, labels=labels,
    )


@dataclass(frozen=True)
class ModelFile:
    name: str
    size: int
    sha256: str | None  # None while it isn't known yet


@dataclass(frozen=True)
class Model:
    name: str
    kind: Literal["frigate_plus", "local", "installer_default"]
    sidecar: Sidecar | None
    files: tuple[ModelFile, ...]
    complete: bool
    problem: str | None  # why a file or sidecar couldn't be used, when one couldn't


@dataclass(frozen=True)
class InstallerDefault:
    section: dict  # the manifest's model section, as the installer gives it to Frigate
    file: str
    labels_file: Path | None


def host_path(codedir, container_path) -> Path | None:
    """Where Frigate's /config/<rest> is on the host; None for any other path, or one with an empty, '.', or '..'
    component."""
    if not isinstance(container_path, str) or not container_path.startswith(CONFIG_PREFIX) or "\0" in container_path:
        return None
    rest = container_path[len(CONFIG_PREFIX):]
    if any(part in ("", ".", "..") for part in rest.split("/")):  # an empty part would make a later one absolute
        return None
    return Path(codedir) / "frigate" / "config" / rest


def installer_default(manifest, codedir) -> InstallerDefault | None:
    section = manifest.frigate.coral_model
    file = installer_model_file(manifest)
    if not section or file is None:
        return None
    return InstallerDefault(section=section, file=file, labels_file=host_path(codedir, section.get("labelmap_path")))


def model_cache_dir(settings, manifest) -> Path:
    if settings.fake:
        return settings.state_dir.parent / "model_cache"
    return Path(manifest.codedir) / "frigate" / "config" / "model_cache"


def open_cache(path: Path) -> int:
    """A descriptor for the directory, which the caller closes. A link at the end of the path is refused."""
    return os.open(path, os.O_DIRECTORY | os.O_NOFOLLOW | os.O_RDONLY | os.O_CLOEXEC)


def open_in(dir_fd: int, name: str, flags: int, mode: int = 0o644) -> int:
    """Open a name in the directory without following a link, and without blocking on a FIFO."""
    return os.open(name, flags | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, mode, dir_fd=dir_fd)


def stat_in(dir_fd: int, name: str) -> os.stat_result | None:
    """The entry's own stat, a link's rather than its target's; None when there is no such entry."""
    try:
        return os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None


def kind_of(name: str, sidecar: Sidecar | None) -> str:
    """A Frigate+ pair is named by its model id, and its sidecar says the same id; anything else is local."""
    if PLUS_ID.fullmatch(name) and sidecar is not None and sidecar.id == name:
        return "frigate_plus"
    return "local"


HASHES: dict[tuple[str, int, int], str] = {}  # sha256 by name, size, and st_mtime_ns, so an unchanged file is read once
_HASH_LOCK = threading.Lock()


def sha256_in(dir_fd: int, name: str, stat_result: os.stat_result) -> str:
    """The file's SHA-256, from the cache when its name, size, and mtime are the ones in stat_result. Otherwise it's
    read in 1 MiB blocks and keyed by what the open file is, so a file replaced after the stat is cached under its
    own size and mtime."""
    key = (name, stat_result.st_size, stat_result.st_mtime_ns)
    with _HASH_LOCK:
        known = HASHES.get(key)
    if known is not None:
        return known
    fd = open_in(dir_fd, name, os.O_RDONLY)
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode):
            raise OSError(errno.EINVAL, "not a regular file")
        digest = hashlib.sha256()
        while block := os.read(fd, HASH_BLOCK):
            digest.update(block)
    finally:
        os.close(fd)
    _remember((name, opened.st_size, opened.st_mtime_ns), digest.hexdigest())
    return digest.hexdigest()


def _remember(key: tuple[str, int, int], digest: str) -> None:
    with _HASH_LOCK:
        for stale in [other for other in HASHES if other[0] == key[0] and other != key]:
            del HASHES[stale]
        HASHES[key] = digest


def forget(names) -> None:
    """Drop the cached hashes of files that were removed."""
    with _HASH_LOCK:
        for stale in [key for key in HASHES if key[0] in names]:
            del HASHES[stale]


def _model_file(dir_fd: int, name: str, stat_result: os.stat_result | None) -> tuple[ModelFile, str | None]:
    """The file's entry with its hash, and a problem when it can't be read. The hash comes from HASHES when the
    name, size, and mtime are unchanged, so a repeat listing doesn't read the file again."""
    if stat_result is None:
        return ModelFile(name, 0, None), FILE_UNREADABLE
    try:
        return ModelFile(name, stat_result.st_size, sha256_in(dir_fd, name, stat_result)), None
    except OSError:
        return ModelFile(name, stat_result.st_size, None), FILE_UNREADABLE


def _read_sidecar(dir_fd: int, name: str) -> tuple[bytes | None, os.stat_result | None]:
    """The sidecar's bytes and the open file's stat, from one read of at most SIDECAR_MAX + 1 bytes; (None, None)
    when it can't be read. More than SIDECAR_MAX bytes back means the sidecar is over the cap."""
    try:
        fd = open_in(dir_fd, name, os.O_RDONLY)
    except OSError:
        return None, None
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode):
            return None, None
        data = b""
        while len(data) <= SIDECAR_MAX and (block := os.read(fd, SIDECAR_MAX + 1 - len(data))):
            data += block
    except OSError:
        return None, None
    finally:
        os.close(fd)
    return data, opened


def _sidecar_half(dir_fd: int, name: str) -> tuple[Sidecar | None, ModelFile, str | None]:
    """The parsed sidecar, its entry in the model's files, and why there's no sidecar when there isn't one. The hash
    is of the bytes that were parsed, and is None for a sidecar over the cap."""
    data, opened = _read_sidecar(dir_fd, name)
    if data is None:
        return None, ModelFile(name, 0, None), SIDECAR_UNREADABLE
    if len(data) > SIDECAR_MAX:
        return None, ModelFile(name, opened.st_size, None), SIDECAR_TOO_LARGE
    digest = hashlib.sha256(data).hexdigest()
    if len(data) == opened.st_size:  # not a file that changed under the read
        _remember((name, opened.st_size, opened.st_mtime_ns), digest)
    entry = ModelFile(name, len(data), digest)
    try:
        return parse_sidecar(data), entry, None
    except SidecarError as error:
        return None, entry, str(error)


def _regular(dir_fd: int, name: str) -> os.stat_result | None:
    try:
        found = stat_in(dir_fd, name)
    except OSError:
        return None
    return found if found is not None and stat.S_ISREG(found.st_mode) else None


def _entries(dir_fd: int, skip: str | None) -> dict[str, dict[str, os.stat_result]]:
    """The regular files with valid names, grouped by model name, as {"model": stat, "sidecar": stat}."""
    try:
        names = os.listdir(dir_fd)
    except OSError:
        return {}
    grouped: dict[str, dict[str, os.stat_result]] = {}
    for name in names:
        role, base = ("sidecar", name[:-len(SIDECAR)]) if name.endswith(SIDECAR) else ("model", name)
        if not valid_name(base) or base == skip:
            continue
        found = _regular(dir_fd, name)
        if found is not None:
            grouped.setdefault(base, {})[role] = found
    return grouped


def _model(dir_fd: int, name: str, found: dict[str, os.stat_result]) -> Model:
    problems = []
    files: tuple[ModelFile, ...] = ()
    read = False  # the model file was read to hash it
    if "model" in found:
        file, problem = _model_file(dir_fd, name, found["model"])
        files = (file,)
        read = file.sha256 is not None
        problems.append(problem)
    sidecar = None
    if "sidecar" in found:
        sidecar, entry, problem = _sidecar_half(dir_fd, name + SIDECAR)
        files += (entry,)
        problems.append(problem)
    return Model(
        name=name, kind=kind_of(name, sidecar), sidecar=sidecar, files=files,
        complete=read and sidecar is not None, problem=" ".join(p for p in problems if p) or None,
    )


def inventory(cache: Path, installer: InstallerDefault | None) -> list[Model]:
    """What's in the cache: the installer's default first, when its file is there as a regular file, then the other
    models by name. A directory that can't be opened lists nothing."""
    try:
        dir_fd = open_cache(cache)
    except OSError:
        return []
    models: list[Model] = []
    try:
        if installer is not None:
            found = _regular(dir_fd, installer.file)
            if found is not None:
                file, problem = _model_file(dir_fd, installer.file, found)
                models.append(Model(installer.file, "installer_default", None, (file,), problem is None, problem))
        grouped = _entries(dir_fd, installer.file if installer else None)
        for name in sorted(grouped):
            try:
                models.append(_model(dir_fd, name, grouped[name]))
            except OSError:
                continue
    finally:
        os.close(dir_fd)
    return models
