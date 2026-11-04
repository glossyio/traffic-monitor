"""Edit YAML config files in place: keep comments, key order, and quoting, and write atomically with a backup."""

import contextlib
import io
import os
import shutil
import stat
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from ruamel.yaml import YAML


class ConcurrentEditError(RuntimeError):
    """The file changed on disk after it was loaded, so saving would overwrite someone else's edit."""


def _round_trip_yaml(mapping_indent):
    yaml = YAML()  # round-trip mode keeps comments, key order, and (with preserve_quotes) quoting
    yaml.preserve_quotes = True
    yaml.indent(mapping=mapping_indent, sequence=mapping_indent + 2, offset=mapping_indent)
    yaml.width = 4096  # never re-wrap long lines such as ffmpeg arguments
    return yaml


def backup_path(path, now=None):
    """Where save() copies the current file before replacing it, e.g. config.yml.20261002T153000Z.bak."""
    now = now or datetime.now(timezone.utc)
    return path.with_name(f"{path.name}.{now:%Y%m%dT%H%M%SZ}.bak")


def read_text(path):
    """A file's text, refusing a symbolic link: as root, following one would read a file the link's maker chose."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, encoding="utf-8") as handle:
        return handle.read()


def back_up(path, now=None):
    """Copy path to backup_path(path), with its permission bits, times, and, when running as root, its owner. Return
    the copy's path.

    The copy is made as a new file and never through a symbolic link, and neither is the original read through one:
    the name is easy to guess, and the directory may be writable by others (Node-RED's container mounts its config
    directory). Both are set up through the open files, never by name.
    """
    backup = backup_path(path, now)
    source = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        original = os.fstat(source)
        mode = stat.S_IMODE(original.st_mode)
        target = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
        try:
            with os.fdopen(os.dup(source), "rb") as reader, os.fdopen(os.dup(target), "wb") as writer:
                shutil.copyfileobj(reader, writer)
                writer.flush()
                os.fsync(writer.fileno())
            os.fchmod(target, mode)  # whatever the umask
            if os.geteuid() == 0:
                os.fchown(target, original.st_uid, original.st_gid)
            os.utime(target, ns=(original.st_atime_ns, original.st_mtime_ns))
        except BaseException:
            os.close(target)
            with contextlib.suppress(FileNotFoundError):
                os.unlink(backup)
            raise
        os.close(target)
    finally:
        os.close(source)
    return backup


def write_atomic(path, text):
    """Replace path with text so readers see the old file or the new one, never a partial write.

    Keeps the file's permission bits, and its owner when running as root. Both are set on the open temporary file, so
    a name swapped in the directory meanwhile can't redirect them; os.replace swaps a link at path, never its target.
    """
    original = os.stat(path, follow_symlinks=False)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fchmod(handle.fileno(), stat.S_IMODE(original.st_mode))
            if os.geteuid() == 0:
                os.fchown(handle.fileno(), original.st_uid, original.st_gid)
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        raise


class RoundTripFile:
    """A YAML file loaded for editing. Change .data, then call save()."""

    def __init__(self, path, mapping_indent=2):
        self.path = Path(path)
        self._yaml = _round_trip_yaml(mapping_indent)
        self._loaded_text = read_text(self.path)
        self.data = self._yaml.load(self._loaded_text)

    @property
    def loaded_text(self):
        """The file's text as it was loaded (or last saved)."""
        return self._loaded_text

    def render(self):
        out = io.StringIO()
        self._yaml.dump(self.data, out)
        text = out.getvalue()
        if not self._loaded_text.endswith("\n"):
            text = text.removesuffix("\n")  # keep a missing final newline, so an unedited file renders identically
        return text

    def save(self, now=None):
        """Write the edited data if it differs from the file. Return the backup's path, or None if nothing changed."""
        text = self.render()
        if text == self._loaded_text:
            return None
        if read_text(self.path) != self._loaded_text:
            raise ConcurrentEditError(f"{self.path} changed after it was loaded; not saving")
        backup = back_up(self.path, now)
        write_atomic(self.path, text)
        self._loaded_text = text
        return backup
