"""The reference pictures an admin keeps on the device: `<state directory>/pictures/<id>/clean.jpg` and `zones.jpg`,
the bytes Frigate sent, and a row in state.sqlite's `pictures` with what the data file needs. The place's point is
never stored with a picture.

The order keeps the two in step across a crash: a picture's files are written and synced before its row is inserted,
and removed before its row is deleted, so a row never names files that were not whole; whatever a crash leaves
between the two steps, the sweep at start removes. A path under `pictures` is built only from an id that matched ID.
Nothing here logs.
"""

import json
import os
import re
import secrets
import shutil
import sqlite3
import stat
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from tm_control.core.auth import _reading, _writing
from tm_control.core.state import State
from tm_control.modules.cameras.reference import Mark, Shot, mark_of
from tm_control.modules.cameras.zones import ZoneFacts

PICTURES = "pictures"  # the directory under the state directory
ID = re.compile(r"[0-9a-f]{16}")
FREE_MIN = 500 * 1024 * 1024  # 500 MB: a picture is kept only while at least this much is free
PICTURES_MAX = 200  # the most the device keeps on its own; a manual keep needs only the free space
Reason = Literal["deployed", "opted_in", "mounting", "setup", "daylight", "manual"]
FACTS = ("width", "height", "unit", "zones", "objects", "tm_version", "frigate_version", "pose", "deployment_id")
Frame = Literal["clean.jpg", "zones.jpg"]
FRAMES: tuple[Frame, Frame] = ("clean.jpg", "zones.jpg")

_COLUMNS = (
    "id, survey_id, camera, reason, mark, after_restart, boot_id, clean_at, zones_at, clean_bytes, zones_bytes, facts, "
    "kept_by"
)


@dataclass(frozen=True)
class Stored:
    """A kept picture's row."""

    id: str
    survey_id: str
    camera: str  # the sensors.cameras key
    reason: Reason
    mark: Mark
    after_restart: bool  # the first picture of a camera after the unit restarted
    boot_id: str
    clean_at: float  # Unix seconds
    zones_at: float
    clean_bytes: int
    zones_bytes: int
    facts: dict  # FACTS
    kept_by: int | None  # the admin who kept it (manual only)


_StoredList = list[Stored]


class _Refused(Exception):
    """The guard said no: the transaction rolls back."""


def _stored(row: sqlite3.Row) -> Stored:
    values = dict(row)
    return Stored(**values | {"after_restart": bool(values["after_restart"]), "facts": json.loads(values["facts"])})


def _write(path: Path, data: bytes) -> None:
    """A new file, 0600 whatever the umask, written and synced."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.fchmod(fd, 0o600)
        view = memoryview(data)
        while view:
            view = view[os.write(fd, view):]
        os.fsync(fd)
    finally:
        os.close(fd)


def _sync(directory: Path) -> None:
    """Sync a directory's entries, so a file in it is still there after a power cut."""
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _read(path: Path) -> bytes | None:
    try:
        with open(path, "rb") as file:
            return file.read()
    except (FileNotFoundError, NotADirectoryError):
        return None


def _is_file(path: Path) -> bool:
    try:
        return stat.S_ISREG(os.lstat(path).st_mode)
    except OSError:
        return False


def _remove(path: Path) -> bool:
    """Remove a directory and what it holds, or a file or a link (never what a link points at); whether there was
    one."""
    try:
        if os.path.isdir(path) and not os.path.islink(path):
            shutil.rmtree(path)
        else:
            os.unlink(path)
    except FileNotFoundError:
        return False
    return True


def _remove_quietly(path: Path) -> int:
    """`_remove`, but a failure counts as nothing removed: the sweep goes on, and the entry is tried again at the
    next start. Nothing is logged, because the error's text holds the path."""
    try:
        return int(_remove(path))
    except OSError:
        return 0


class Pictures:
    def __init__(self, state: State, state_dir: Path):
        self.state = state
        self.state_dir = Path(state_dir)
        self.root = self.state_dir / PICTURES

    def _dir(self, picture_id: str) -> Path:
        if not ID.fullmatch(picture_id):  # every caller checked; this is the last line
            raise ValueError("not a picture id")
        return self.root / picture_id

    def add(
        self,
        shot: Shot,
        reason: Reason,
        boot_id: str,
        *,
        after_restart: bool = False,
        kept_by: int | None = None,
        guard: Callable[[sqlite3.Connection], bool] | None = None,
        replaces: str | None = None,
    ) -> Stored | None:
        """Store a take at its place: both files, synced, then in one transaction `guard` (False stores nothing),
        the row, and the deletion of the row `replaces` names, whose directory goes after. None when the guard
        refused or `replaces` isn't an id. On any error, the directory made here is removed and the error raised."""
        if shot.survey_id is None:
            raise ValueError("a picture is stored only at a place")
        if replaces is not None and not ID.fullmatch(replaces):
            return None
        stored = Stored(
            id=secrets.token_hex(8),
            survey_id=shot.survey_id,
            camera=shot.camera,
            reason=reason,
            mark=mark_of(shot.objects),
            after_restart=after_restart,
            boot_id=boot_id,
            clean_at=shot.clean_at,
            zones_at=shot.zones_at,
            clean_bytes=len(shot.clean),
            zones_bytes=len(shot.zones_picture),
            facts={
                "width": shot.width,
                "height": shot.height,
                "unit": shot.unit,
                "zones": [zone.model_dump() for zone in shot.zones],
                "objects": shot.objects,
                "tm_version": shot.tm_version,
                "frigate_version": shot.frigate_version,
                "pose": shot.pose,
                "deployment_id": shot.deployment_id,
            },
            kept_by=kept_by,
        )
        directory = self._dir(stored.id)
        made = False
        try:
            root_made = self._make_root()
            os.mkdir(directory, 0o700)  # an id already on the card fails here, before anything of it is touched
            made = True
            os.chmod(directory, 0o700)
            _write(directory / "clean.jpg", shot.clean)
            _write(directory / "zones.jpg", shot.zones_picture)
            _sync(directory)
            _sync(self.root)
            if root_made:
                _sync(self.state_dir)
            replaced = self._insert(stored, guard, replaces)
        except _Refused:
            self._discard(directory)
            return None
        except BaseException:
            if made:
                self._discard(directory)
            raise
        if replaced:
            self._discard(self._dir(replaces))  # its row is gone; a crash before this leaves it to the sweep
        return stored

    def _make_root(self) -> bool:
        """Make `pictures` 0700 if it isn't there; whether it was made."""
        try:
            os.mkdir(self.root, 0o700)
            made = True
        except FileExistsError:
            made = False
        os.chmod(self.root, 0o700)
        return made

    def _insert(self, stored: Stored, guard, replaces: str | None) -> bool:
        """The row, in one transaction with the guard and the replaced row's deletion; whether a row was replaced."""
        with _writing(self.state) as con:
            if guard is not None and not guard(con):
                raise _Refused
            con.execute(
                f"INSERT INTO pictures ({_COLUMNS}) VALUES ({', '.join('?' * 13)})",
                (
                    stored.id, stored.survey_id, stored.camera, stored.reason, stored.mark, int(stored.after_restart),
                    stored.boot_id, stored.clean_at, stored.zones_at, stored.clean_bytes, stored.zones_bytes,
                    json.dumps(stored.facts, ensure_ascii=False), stored.kept_by,
                ),
            )
            if replaces is None:
                return False
            return self._delete_rows(con, [replaces]) > 0

    @staticmethod
    def _discard(directory: Path) -> None:
        """Remove a directory this store made, quietly: a failure leaves it to the sweep."""
        try:
            _remove(directory)
        except OSError:
            pass

    def _delete_rows(self, con: sqlite3.Connection, ids: list[str]) -> int:
        deleted = 0
        for picture_id in ids:
            deleted += con.execute("DELETE FROM pictures WHERE id = ?", (picture_id,)).rowcount
        return deleted

    def all(self, survey_id: str | None = None) -> _StoredList:
        """Every picture, or one place's, newest first."""
        where, params = ("WHERE survey_id = ?", (survey_id,)) if survey_id is not None else ("", ())
        with _reading(self.state) as con:
            found = con.execute(f"SELECT {_COLUMNS} FROM pictures {where} ORDER BY clean_at DESC, rowid DESC", params)
            return [_stored(row) for row in found]

    def get(self, picture_id: str) -> Stored | None:
        if not ID.fullmatch(picture_id):
            return None
        with _reading(self.state) as con:
            row = con.execute(f"SELECT {_COLUMNS} FROM pictures WHERE id = ?", (picture_id,)).fetchone()
        return None if row is None else _stored(row)

    def frame(self, picture_id: str, name: Frame) -> bytes | None:
        """One of a picture's frames; None for a picture with no row or with either file gone."""
        if not ID.fullmatch(picture_id) or name not in FRAMES or self.get(picture_id) is None:
            return None
        directory = self._dir(picture_id)
        other = FRAMES[1] if name == FRAMES[0] else FRAMES[0]
        if not _is_file(directory / other):
            return None
        return _read(directory / name)

    def shot(self, stored: Stored, point: tuple[float, float] | None) -> Shot | None:
        """The picture as a take again, at `point` (the place's as it is now); None when a file is gone."""
        if not ID.fullmatch(stored.id):
            return None
        directory = self._dir(stored.id)
        clean = _read(directory / "clean.jpg")
        zones_picture = _read(directory / "zones.jpg")
        if clean is None or zones_picture is None:
            return None
        facts = stored.facts
        return Shot(
            camera=stored.camera,
            survey_id=stored.survey_id,
            point=point,
            deployment_id=facts["deployment_id"],
            pose=facts["pose"],
            clean=clean,
            zones_picture=zones_picture,
            clean_at=stored.clean_at,
            zones_at=stored.zones_at,
            width=facts["width"],
            height=facts["height"],
            unit=facts["unit"],
            zones=[ZoneFacts.model_validate(zone) for zone in facts["zones"]],
            objects=facts["objects"],
            tm_version=facts["tm_version"],
            frigate_version=facts["frigate_version"],
        )

    def delete(self, picture_id: str) -> Stored | None:
        """Remove a picture: its files, then its row. The picture, or None when there was none."""
        stored = self.get(picture_id)  # None for a bad id
        if stored is None:
            return None
        _remove(self._dir(stored.id))
        with _writing(self.state) as con:
            self._delete_rows(con, [stored.id])
        return stored

    def delete_place(self, survey_id: str) -> int:
        """Remove every picture of a place, files first; how many rows went."""
        with _reading(self.state) as con:
            ids = [row["id"] for row in con.execute("SELECT id FROM pictures WHERE survey_id = ?", (survey_id,))]
        for picture_id in ids:
            if ID.fullmatch(picture_id):
                _remove(self._dir(picture_id))
        with _writing(self.state) as con:
            return self._delete_rows(con, ids)

    def counts(self) -> dict[str, int]:
        """How many pictures each place has."""
        with _reading(self.state) as con:
            found = con.execute("SELECT survey_id, count(*) AS n FROM pictures GROUP BY survey_id")
            return {row["survey_id"]: row["n"] for row in found}

    def total(self) -> tuple[int, int]:
        """The pictures on the device, and their bytes."""
        with _reading(self.state) as con:
            row = con.execute("SELECT count(*), coalesce(sum(clean_bytes + zones_bytes), 0) FROM pictures").fetchone()
        return row[0], row[1]

    def has_room(self) -> bool:
        """Whether at least FREE_MIN is free for the service where the state directory is."""
        try:
            found = os.statvfs(self.state_dir)
        except OSError:
            return False
        return found.f_bavail * found.f_frsize >= FREE_MIN

    def rename_camera(self, old: str, new: str) -> None:
        """Move every place's pictures of a camera to its new key."""
        if old == new:
            return
        with _writing(self.state) as con:
            con.execute("UPDATE pictures SET camera = ? WHERE camera = ?", (new, old))

    def sweep(self) -> tuple[int, int]:
        """Run once at start, before anything else uses the store: remove every entry under `pictures` that isn't
        the directory of a row (a stray file or link too), then every row whose directory or either file is missing,
        its files first. The entries removed and the rows deleted. An entry that can't be removed isn't counted, and
        the sweep goes on."""
        with _reading(self.state) as con:
            ids = {row["id"] for row in con.execute("SELECT id FROM pictures")}
        removed = 0
        try:
            with os.scandir(self.root) as found:
                names = [(entry.name, entry.is_dir(follow_symlinks=False)) for entry in found]
        except FileNotFoundError:
            names = []
        for name, is_dir in names:
            if not (is_dir and ID.fullmatch(name) and name in ids):
                removed += _remove_quietly(self.root / name)
        broken = []
        for picture_id in sorted(ids):
            if not ID.fullmatch(picture_id):
                broken.append(picture_id)  # no file can be its; only the row goes
                continue
            directory = self._dir(picture_id)
            if not all(_is_file(directory / name) for name in FRAMES):
                removed += _remove_quietly(directory)  # a stray folder is the next start's to clear
                broken.append(picture_id)
        deleted = 0
        if broken:
            with _writing(self.state) as con:
                deleted = self._delete_rows(con, broken)
        return removed, deleted
