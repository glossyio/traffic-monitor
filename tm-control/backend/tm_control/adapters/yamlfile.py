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


def write_atomic(path, text):
    """Replace path with text so readers see the old file or the new one, never a partial write.

    Keeps the file's permission bits, and its owner when running as root.
    """
    original = path.stat()
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, stat.S_IMODE(original.st_mode))
        if os.geteuid() == 0:
            os.chown(tmp, original.st_uid, original.st_gid)
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
        self._loaded_text = self.path.read_text()
        self.data = self._yaml.load(self._loaded_text)

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
        if self.path.read_text() != self._loaded_text:
            raise ConcurrentEditError(f"{self.path} changed after it was loaded; not saving")
        backup = backup_path(self.path, now)
        shutil.copy2(self.path, backup)
        write_atomic(self.path, text)
        self._loaded_text = text
        return backup
