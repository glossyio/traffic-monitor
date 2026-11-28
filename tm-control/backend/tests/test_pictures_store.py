"""The device's store of kept reference pictures: two files per picture under the state directory, a row in
`pictures`, the order they are written and removed in, and the sweep at start."""

import json
import os
import sqlite3
import stat
from types import SimpleNamespace

import pytest

from tests.jpegs import jpeg
from tests.test_cameras_zones import CAMERA
from tm_control.core.state import State
from tm_control.modules.cameras.reference import Shot
from tm_control.modules.cameras.zones import zone_facts
from tm_control.modules.pictures import store as store_module
from tm_control.modules.pictures.clock import Clock, ManualClock
from tm_control.modules.pictures.store import FACTS, FREE_MIN, ID, PICTURES, Pictures, Stored

NOW = "2026-11-27T12:00:00+00:00"
PLACE = "3f9a1c2e-si"
OTHER_PLACE = "7b2d4e6f-si"
POINT = (45.0, -122.0)
BOOT = "6c1f0a3e-8b2d-4f5a-9e7c-1d2b3a4c5e6f"


@pytest.fixture(autouse=True)
def nothing_logged(caplog):
    """The store logs nothing, in any test here."""
    caplog.set_level("DEBUG")
    yield
    assert caplog.records == []


@pytest.fixture
def state(tmp_path):
    state = State(tmp_path / "state" / "state.sqlite")
    state.path.parent.mkdir(mode=0o700)
    state.migrate()
    con = state.connect()
    with con:
        for survey_id in (PLACE, OTHER_PLACE):
            con.execute(
                "INSERT INTO surveys (id, status, source, created_at, updated_at) VALUES (?, 'used', 'ui', ?, ?)",
                (survey_id, NOW, NOW),
            )
        con.execute(
            "INSERT INTO users (username, password_hash, role, created_at) VALUES ('admin', 'placeholder', 'admin', ?)",
            (NOW,),
        )
    con.close()
    return state


@pytest.fixture
def pictures(state):
    return Pictures(state, state.path.parent)


def shot(**changes) -> Shot:
    """A Shot from made-up values at PLACE; the clean picture's time is 2026-11-18 18:30:05 UTC."""
    values = dict(
        camera="camera_1_3fa9c2", survey_id=PLACE, point=POINT, deployment_id="1795026000000-1a2b3c4d-d",
        pose={"heading_deg": 40, "pitch_deg": 15.0, "height_m": 3.66, "view_distance_m": 13.66, "mount": "pole",
              "hfov_deg": None},
        clean=jpeg(1536, 864), zones_picture=jpeg(1536, 864)[:-2] + b"zones\xff\xd9",
        clean_at=1795026605.0, zones_at=1795026606.0, width=1536, height=864, unit="m",
        zones=[zone_facts(CAMERA)[0]],
        objects={"checked": True, "before": [{"label": "car", "stationary": True}],
                 "after": [{"label": "car", "stationary": True}], "person": False},
        tm_version="0.8.0", frigate_version="0.18.2-abc1234",
    )
    return Shot(**values | changes)


def rows(state) -> list[dict]:
    con = state.connect()
    try:
        return [dict(row) for row in con.execute("SELECT * FROM pictures ORDER BY rowid")]
    finally:
        con.close()


def entries(pictures) -> list[str]:
    root = pictures.root
    return sorted(os.listdir(root)) if root.exists() else []


def mode(path) -> int:
    return stat.S_IMODE(os.lstat(path).st_mode)


def test_add_writes_two_files_then_the_row(pictures, state):
    taken = shot()
    old_umask = os.umask(0o022)  # the modes are set, whatever the umask
    try:
        stored = pictures.add(taken, "manual", BOOT, kept_by=1)
    finally:
        os.umask(old_umask)
    directory = pictures.root / stored.id
    assert (directory / "clean.jpg").read_bytes() == taken.clean
    assert (directory / "zones.jpg").read_bytes() == taken.zones_picture
    assert [mode(pictures.root), mode(directory), mode(directory / "clean.jpg"), mode(directory / "zones.jpg")] == [
        0o700, 0o700, 0o600, 0o600]
    assert sorted(os.listdir(directory)) == ["clean.jpg", "zones.jpg"]

    [row] = rows(state)
    assert row == {
        "id": stored.id, "survey_id": PLACE, "camera": "camera_1_3fa9c2", "reason": "manual", "mark": "clear",
        "after_restart": 0, "boot_id": BOOT, "clean_at": taken.clean_at, "zones_at": taken.zones_at,
        "clean_bytes": len(taken.clean), "zones_bytes": len(taken.zones_picture), "facts": row["facts"],
        "kept_by": 1,
    }
    facts = json.loads(row["facts"])
    assert tuple(facts) == FACTS
    assert facts == {
        "width": 1536, "height": 864, "unit": "m", "zones": [zone.model_dump() for zone in taken.zones],
        "objects": taken.objects, "tm_version": "0.8.0", "frigate_version": "0.18.2-abc1234", "pose": taken.pose,
        "deployment_id": "1795026000000-1a2b3c4d-d",
    }
    # No column and no fact holds the place's point.
    assert not {POINT[0], POINT[1]} & set(row.values())
    assert "45.0" not in row["facts"] and "-122" not in row["facts"] and "point" not in row["facts"]
    assert stored == pictures.get(stored.id)
    assert stored.kept_by == 1 and stored.after_restart is False and stored.facts == facts


@pytest.mark.parametrize("person, mark", [(True, "person"), (False, "clear"), (None, "unchecked")])
def test_the_mark_comes_from_the_objects_block(pictures, person, mark):
    objects = {"checked": person is not None, "before": [], "after": [], "person": person}
    stored = pictures.add(shot(objects=objects), "deployed", BOOT, after_restart=True)
    assert (stored.mark, stored.reason, stored.after_restart) == (mark, "deployed", True)


def test_the_id_is_sixteen_hex_and_never_a_counter(pictures):
    first = pictures.add(shot(), "manual", BOOT)
    second = pictures.add(shot(), "manual", BOOT)
    assert ID.fullmatch(first.id) and ID.fullmatch(second.id)
    assert first.id != second.id
    assert int(second.id, 16) - int(first.id, 16) != 1


def test_a_shot_with_no_place_is_not_stored(pictures, state):
    with pytest.raises(ValueError):
        pictures.add(shot(survey_id=None), "manual", BOOT)
    assert rows(state) == [] and entries(pictures) == []


def test_a_write_that_fails_leaves_nothing(pictures, state, monkeypatch):
    real_fsync = os.fsync
    calls = []

    def fsync(fd):
        calls.append(fd)
        if len(calls) == 2:  # the second file
            raise OSError(28, "No space left on device")
        real_fsync(fd)

    monkeypatch.setattr(store_module.os, "fsync", fsync)
    with pytest.raises(OSError):
        pictures.add(shot(), "manual", BOOT)
    assert len(calls) == 2
    assert rows(state) == []
    assert entries(pictures) == []


def test_a_row_that_fails_leaves_no_directory(pictures, state):
    with pytest.raises(sqlite3.IntegrityError):
        pictures.add(shot(survey_id="missing-si"), "manual", BOOT)  # no such place
    assert rows(state) == [] and entries(pictures) == []


def test_a_guard_that_refuses_leaves_nothing(pictures, state):
    seen = []

    def guard(con):
        seen.append(con.execute("SELECT count(*) FROM pictures").fetchone()[0])
        return False

    assert pictures.add(shot(), "manual", BOOT, guard=guard) is None
    assert seen == [0]
    assert rows(state) == []
    assert entries(pictures) == []


def test_a_guard_that_agrees_runs_inside_the_transaction(pictures, state):
    def guard(con):
        assert con.in_transaction
        return True

    stored = pictures.add(shot(), "manual", BOOT, guard=guard)
    assert [row["id"] for row in rows(state)] == [stored.id]


def test_a_replacement_swaps_rows_in_one_transaction_and_removes_the_old_files(pictures, state):
    old = pictures.add(shot(), "deployed", BOOT)
    other = pictures.add(shot(camera="camera_2"), "deployed", BOOT)
    seen = []

    def guard(con):
        seen.append(sorted(row[0] for row in con.execute("SELECT id FROM pictures")))
        return True

    new = pictures.add(shot(clean_at=1795030000.0), "daylight", BOOT, guard=guard, replaces=old.id)
    assert seen == [sorted([old.id, other.id])]
    assert sorted(row["id"] for row in rows(state)) == sorted([other.id, new.id])
    assert entries(pictures) == sorted([other.id, new.id])
    assert pictures.get(old.id) is None


def test_a_refused_replacement_keeps_the_old_picture(pictures, state):
    old = pictures.add(shot(), "deployed", BOOT)
    assert pictures.add(shot(), "daylight", BOOT, guard=lambda con: False, replaces=old.id) is None
    assert [row["id"] for row in rows(state)] == [old.id]
    assert entries(pictures) == [old.id]
    assert pictures.frame(old.id, "clean.jpg") == shot().clean


def test_a_replacement_whose_row_fails_keeps_the_old_picture(pictures, state):
    old = pictures.add(shot(), "deployed", BOOT)
    with pytest.raises(sqlite3.IntegrityError):
        pictures.add(shot(survey_id="missing-si"), "daylight", BOOT, replaces=old.id)
    assert [row["id"] for row in rows(state)] == [old.id]
    assert entries(pictures) == [old.id]


def test_all_is_newest_first_and_by_place(pictures):
    first = pictures.add(shot(clean_at=100.0), "manual", BOOT)
    third = pictures.add(shot(clean_at=300.0), "manual", BOOT)
    elsewhere = pictures.add(shot(clean_at=200.0, survey_id=OTHER_PLACE), "manual", BOOT)
    assert [picture.id for picture in pictures.all()] == [third.id, elsewhere.id, first.id]
    assert [picture.id for picture in pictures.all(PLACE)] == [third.id, first.id]
    assert pictures.all("unknown-si") == []
    assert all(isinstance(picture, Stored) for picture in pictures.all())


def test_frame_and_shot_give_back_the_stored_take(pictures):
    taken = shot()
    stored = pictures.add(taken, "manual", BOOT)
    assert pictures.frame(stored.id, "clean.jpg") == taken.clean
    assert pictures.frame(stored.id, "zones.jpg") == taken.zones_picture
    assert pictures.frame(stored.id, "other.jpg") is None
    assert pictures.frame("0123456789abcdef", "clean.jpg") is None  # no row
    assert pictures.shot(stored, POINT) == taken
    assert pictures.shot(stored, None) == shot(point=None)


BAD_IDS = ["..", "../x", "a" * 15, "a" * 17, "A" * 16, "%2e%2e", ""]


@pytest.mark.parametrize("bad", BAD_IDS)
def test_only_an_id_makes_a_path(pictures, monkeypatch, bad):
    good = pictures.add(shot(), "manual", BOOT)
    stored = pictures.get(good.id)

    def refuse(*args, **kwargs):
        raise AssertionError("no file is opened for a bad id")

    monkeypatch.setattr(os, "open", refuse)
    monkeypatch.setattr("builtins.open", refuse)
    monkeypatch.setattr(os, "scandir", refuse)
    assert pictures.get(bad) is None
    assert pictures.frame(bad, "clean.jpg") is None
    assert pictures.frame(bad, "zones.jpg") is None
    assert pictures.delete(bad) is None
    assert pictures.shot(Stored(**vars(stored) | {"id": bad}), POINT) is None


@pytest.mark.parametrize("bad", BAD_IDS)
def test_a_replacement_named_by_a_bad_id_stores_nothing(pictures, state, monkeypatch, bad):
    monkeypatch.setattr(os, "open", lambda *args, **kwargs: pytest.fail("no file is written"))
    assert pictures.add(shot(), "manual", BOOT, replaces=bad) is None
    assert rows(state) == []


@pytest.mark.parametrize("gone", ["clean.jpg", "zones.jpg"])
def test_a_row_whose_file_is_gone_is_a_404(pictures, gone):
    stored = pictures.add(shot(), "manual", BOOT)
    os.remove(pictures.root / stored.id / gone)
    assert pictures.frame(stored.id, "clean.jpg") is None
    assert pictures.frame(stored.id, "zones.jpg") is None
    assert pictures.shot(stored, POINT) is None


def test_delete_removes_the_files_first(pictures, state, monkeypatch):
    stored = pictures.add(shot(), "manual", BOOT)

    def fail(self, con, ids):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(Pictures, "_delete_rows", fail)
    with pytest.raises(sqlite3.OperationalError):
        pictures.delete(stored.id)
    assert entries(pictures) == []
    assert [row["id"] for row in rows(state)] == [stored.id]
    assert pictures.frame(stored.id, "clean.jpg") is None


def test_delete_answers_the_picture_once(pictures, state):
    stored = pictures.add(shot(), "manual", BOOT)
    assert pictures.delete(stored.id) == stored
    assert pictures.delete(stored.id) is None
    assert rows(state) == [] and entries(pictures) == []


def test_delete_place_takes_every_picture_of_the_place_and_no_other(pictures, state):
    pictures.add(shot(), "manual", BOOT)
    pictures.add(shot(camera="camera_2"), "deployed", BOOT)
    kept = pictures.add(shot(survey_id=OTHER_PLACE), "manual", BOOT)
    assert pictures.delete_place(PLACE) == 2
    assert [row["id"] for row in rows(state)] == [kept.id]
    assert entries(pictures) == [kept.id]
    assert pictures.delete_place(PLACE) == 0


def test_counts_and_total(pictures):
    assert pictures.counts() == {} and pictures.total() == (0, 0)
    one = pictures.add(shot(), "manual", BOOT)
    pictures.add(shot(), "manual", BOOT)
    pictures.add(shot(survey_id=OTHER_PLACE), "manual", BOOT)
    assert pictures.counts() == {PLACE: 2, OTHER_PLACE: 1}
    assert pictures.total() == (3, 3 * (one.clean_bytes + one.zones_bytes))


def _row(state, picture_id):
    con = state.connect()
    with con:
        con.execute(
            "INSERT INTO pictures (id, survey_id, camera, reason, mark, boot_id, clean_at, zones_at, clean_bytes, "
            "zones_bytes, facts) VALUES (?, ?, 'camera_1', 'manual', 'clear', 'boot', 1.0, 2.0, 3, 4, '{}')",
            (picture_id, PLACE),
        )
    con.close()


def test_the_sweep_removes_files_with_no_row_and_rows_with_no_files(pictures, state):
    whole = pictures.add(shot(), "manual", BOOT)
    one_file = pictures.add(shot(), "manual", BOOT)
    os.remove(pictures.root / one_file.id / "zones.jpg")
    orphan = pictures.root / "0123456789abcdef"
    orphan.mkdir(mode=0o700)
    (orphan / "clean.jpg").write_bytes(b"left by a crash")
    _row(state, "fedcba9876543210")  # no directory
    (pictures.root / "stray.txt").write_bytes(b"not a picture")

    assert pictures.sweep() == (3, 2)
    assert [row["id"] for row in rows(state)] == [whole.id]
    assert entries(pictures) == [whole.id]
    assert pictures.frame(whole.id, "clean.jpg") == shot().clean
    assert pictures.frame(whole.id, "zones.jpg") == shot().zones_picture
    assert pictures.sweep() == (0, 0)


def test_the_sweep_takes_a_row_whose_id_makes_no_path(pictures, state):
    _row(state, "../../escape-here")
    assert pictures.sweep() == (0, 1)
    assert rows(state) == []


def test_the_sweep_with_no_pictures_directory(pictures):
    assert not pictures.root.exists()
    assert pictures.sweep() == (0, 0)


def test_the_sweep_removes_a_link_and_leaves_its_target(pictures, tmp_path):
    pictures.add(shot(), "manual", BOOT)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "clean.jpg").write_bytes(b"x")
    (pictures.root / "0123456789abcdef").symlink_to(outside)
    assert pictures.sweep() == (1, 0)
    assert (outside / "clean.jpg").exists()


def _refuse_removing(monkeypatch, *names):
    """Make removing the named entries under `pictures` fail the way a folder the service can't remove does; the
    error's text holds the path, as the real one does."""
    real = store_module.shutil.rmtree

    def rmtree(path, *args, **kwargs):
        if os.path.basename(path) in names:
            raise PermissionError(13, "Permission denied", str(path))
        return real(path, *args, **kwargs)

    monkeypatch.setattr(store_module.shutil, "rmtree", rmtree)


def test_the_sweep_goes_on_past_an_entry_it_cannot_remove(pictures, state, monkeypatch):
    whole = pictures.add(shot(), "manual", BOOT)
    stuck = pictures.root / "0123456789abcdef"
    stuck.mkdir(mode=0o700)
    (stuck / "clean.jpg").write_bytes(b"left by a hand copy")
    other = pictures.root / "aaaaaaaaaaaaaaaa"
    other.mkdir(mode=0o700)
    one_file = pictures.add(shot(), "manual", BOOT)
    os.remove(pictures.root / one_file.id / "zones.jpg")
    _refuse_removing(monkeypatch, stuck.name, one_file.id)

    assert pictures.sweep() == (1, 1)  # the entries that couldn't be removed aren't counted
    assert sorted(entries(pictures)) == sorted([whole.id, stuck.name, one_file.id])
    assert [row["id"] for row in rows(state)] == [whole.id]  # the broken row still goes
    assert pictures.frame(whole.id, "clean.jpg") == shot().clean


def test_the_sweep_goes_on_past_a_stray_file_it_cannot_unlink(pictures, monkeypatch):
    pictures.add(shot(), "manual", BOOT)
    (pictures.root / "stray.txt").write_bytes(b"x")
    (pictures.root / "other.txt").write_bytes(b"y")
    real = os.unlink

    def unlink(path, *args, **kwargs):
        if os.path.basename(path) == "stray.txt":
            raise OSError(5, "Input/output error", str(path))
        return real(path, *args, **kwargs)

    monkeypatch.setattr(store_module.os, "unlink", unlink)
    assert pictures.sweep() == (1, 0)
    assert not (pictures.root / "other.txt").exists()


@pytest.mark.parametrize("free, expected", [(FREE_MIN - 1, False), (FREE_MIN, True), (FREE_MIN + 1, True)])
def test_has_room(pictures, monkeypatch, free, expected):
    seen = []

    def statvfs(path):
        seen.append(path)
        return SimpleNamespace(f_bavail=free, f_frsize=1)

    monkeypatch.setattr(store_module.os, "statvfs", statvfs)
    assert pictures.has_room() is expected
    assert seen == [pictures.state_dir]


def test_has_room_is_false_when_the_space_cannot_be_read(pictures, monkeypatch):
    def statvfs(path):
        raise OSError(5, "Input/output error")

    monkeypatch.setattr(store_module.os, "statvfs", statvfs)
    assert pictures.has_room() is False


def test_rename_camera_moves_every_place(pictures):
    here = pictures.add(shot(camera="picam_h265"), "manual", BOOT)
    there = pictures.add(shot(camera="picam_h265", survey_id=OTHER_PLACE), "manual", BOOT)
    other = pictures.add(shot(camera="camera_2"), "manual", BOOT)
    pictures.rename_camera("picam_h265", "camera_1_3fa9c2")
    assert [pictures.get(p.id).camera for p in (here, there, other)] == ["camera_1_3fa9c2", "camera_1_3fa9c2",
                                                                         "camera_2"]


def test_the_store_logs_nothing(pictures, state, caplog):
    """Every method, including the failing paths; the autouse fixture checks the records."""
    stored = pictures.add(shot(), "manual", BOOT)
    pictures.add(shot(), "manual", BOOT, guard=lambda con: False)
    pictures.add(shot(), "daylight", BOOT, replaces=stored.id)
    pictures.all(), pictures.all(PLACE), pictures.counts(), pictures.total(), pictures.has_room()
    for picture in pictures.all():
        pictures.frame(picture.id, "clean.jpg"), pictures.shot(picture, POINT)
    pictures.get("../x"), pictures.frame("../x", "zones.jpg"), pictures.delete("../x")
    pictures.rename_camera("camera_1_3fa9c2", "camera_9")
    _row(state, "fedcba9876543210")
    pictures.sweep()
    with pytest.raises(ValueError):
        pictures.add(shot(survey_id=None), "manual", BOOT)
    pictures.delete_place(PLACE)
    assert caplog.records == []


def test_the_clock_reads_the_boot_id_once(monkeypatch, tmp_path):
    boot_id = tmp_path / "boot_id"
    boot_id.write_text(BOOT + "\n")
    monkeypatch.setattr("tm_control.modules.pictures.clock.BOOT_ID", boot_id)
    clock = Clock()
    assert clock.boot_id() == BOOT
    boot_id.write_text("changed\n")
    assert clock.boot_id() == BOOT
    assert isinstance(clock.boot(), float) and isinstance(clock.wall(), float)


def test_fake_mode_without_a_boot_id_or_a_boot_clock(monkeypatch, tmp_path):
    monkeypatch.setattr("tm_control.modules.pictures.clock.BOOT_ID", tmp_path / "missing")
    monkeypatch.delattr("time.CLOCK_BOOTTIME", raising=False)
    monkeypatch.setattr("time.monotonic", lambda: 12.5)
    clock = Clock(fake=True)
    assert (clock.boot_id(), clock.boot()) == ("fake", 12.5)
    with pytest.raises(OSError):
        Clock().boot_id()  # a device has one


def test_a_manual_clock_answers_what_a_test_sets():
    clock = ManualClock(boot_id="boot-a", boot=10.0, wall=1795026605.0)
    assert (clock.boot_id(), clock.boot(), clock.wall()) == ("boot-a", 10.0, 1795026605.0)
    clock.set(boot_id="boot-b", boot=0.0)
    clock.advance(30.0)
    assert (clock.boot_id(), clock.boot(), clock.wall()) == ("boot-b", 30.0, 1795026635.0)
    assert isinstance(clock, Clock)


def test_the_app_holds_the_store_and_the_clock(settings):
    from tm_control.app import create_app

    app = create_app(settings)
    assert isinstance(app.state.pictures, Pictures)
    assert app.state.pictures.root == settings.state_dir / PICTURES
    assert isinstance(app.state.clock, Clock)
