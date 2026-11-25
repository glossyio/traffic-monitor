"""The restore point: what is saved before an update switches, and how it is kept."""

import hashlib
import json
import os
import re
import sqlite3
from pathlib import Path

import pytest
from tm_update_support import COMMIT, OLD_COMMIT, handover, installed, make_world

from tm_update import restore

NAME = re.compile(r"\d{8}T\d{6}Z-[0-9a-f]{7}")
MARKER = "marker-value-4f2a9c"
CODEDIR = "/opt/traffic-monitor"


def _put(paths, device_path, text="data\n", mode=0o644):
    real = paths.rooted(Path(device_path))
    real.parent.mkdir(parents=True, exist_ok=True)
    real.write_text(text)
    real.chmod(mode)
    return real


def _every_listed_file(paths):
    listed = [
        f"{CODEDIR}/node-red-tm/config/config.yml",
        f"{CODEDIR}/frigate/config/config.yml",
        f"{CODEDIR}/node-red-tm/node-red-tm.env",
        f"{CODEDIR}/frigate/frigate.env",
        "/var/lib/go2rtc/go2rtc.yaml",
        "/etc/containers/systemd/frigate.container",
        "/etc/containers/systemd/frigate.build",
        "/etc/containers/systemd/sub/extra.network",
        "/etc/systemd/system/tm-control.service",
        "/etc/systemd/system/tm-job-network.service",
        f"{CODEDIR}/services/go2rtc_server.service",
        "/etc/polkit-1/rules.d/50-traffic-monitor.rules",
        "/etc/traffic-monitor/secrets/node_red_token_key",
        "/etc/traffic-monitor/secrets/thingsboard_access_token",
    ]
    for item in listed:
        _put(paths, item, text=f"content of {item}\n")
    _put(paths, "/etc/systemd/system/other.service")  # not ours
    _put(paths, f"{CODEDIR}/frigate/notes.txt")  # not listed
    return listed + ["/etc/traffic-monitor/manifest.json"]


def _state_db(path, rows=50):
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.execute("create table t (a integer primary key, b text)")
    db.executemany("insert into t (b) values (?)", [("x" * 200,)] * rows)
    db.commit()
    db.close()


@pytest.fixture
def world(tmp_path):
    paths, tree = make_world(tmp_path)
    return paths, tree


def _make(paths, previous_tree=None, **changes):
    return restore.make(installed(**changes), handover(paths), paths, previous_tree)


def _doc(folder):
    return json.loads((folder / "restore.json").read_text())


def _copy_of(folder, device_path):
    return folder / "files" / device_path.lstrip("/")


def test_the_folder_is_roots_alone_and_named_for_the_time_and_the_old_commit(world):
    paths, _ = world
    folder = _make(paths)
    assert folder.parent == paths.restore_root
    assert NAME.fullmatch(folder.name) and folder.name.endswith("-" + OLD_COMMIT[:7])
    assert oct(folder.stat().st_mode & 0o777) == "0o700"
    assert oct((folder / "restore.json").stat().st_mode & 0o777) == "0o600"
    assert oct(paths.restore_root.stat().st_mode & 0o777) == "0o700"
    for entry in folder.rglob("*"):
        if entry.is_dir():
            assert oct(entry.stat().st_mode & 0o777) == "0o700"
    doc = _doc(folder)
    assert doc["schema"] == 1
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", doc["made_at"])
    assert doc["from"] == {"version": "0.7.1", "commit": OLD_COMMIT}
    assert doc["to"] == {"commit": COMMIT}
    assert doc["tmdb_backup"] is None and doc["previous_tree"] is None


def test_an_unknown_old_commit_still_gives_a_name_of_the_pattern(world):
    paths, _ = world
    folder = _make(paths, commit="unknown")
    assert NAME.fullmatch(folder.name)


def test_the_previous_tree_is_recorded_as_given(world):
    paths, _ = world
    tree = paths.src_root / OLD_COMMIT
    tree.mkdir(parents=True)
    assert _doc(_make(paths, tree))["previous_tree"] == str(tree)


def test_it_holds_every_listed_file_under_its_full_path(world):
    paths, _ = world
    expected = _every_listed_file(paths)
    folder = _make(paths)
    recorded = {row["path"] for row in _doc(folder)["files"]}
    assert recorded == set(expected)
    for item in expected:
        assert _copy_of(folder, item).is_file()
        assert _copy_of(folder, item).read_bytes() == paths.rooted(Path(item)).read_bytes()
    assert not _copy_of(folder, "/etc/systemd/system/other.service").exists()
    assert not _copy_of(folder, f"{CODEDIR}/frigate/notes.txt").exists()


def test_modes_and_owners_are_kept(world, monkeypatch):
    paths, _ = world
    _put(paths, "/etc/traffic-monitor/secrets/node_red_token_key", mode=0o640)
    _put(paths, f"{CODEDIR}/frigate/frigate.env", mode=0o600)
    given = []
    monkeypatch.setattr(restore, "_give", lambda path, uid, gid: given.append((path.name, uid, gid)))
    folder = _make(paths)
    rows = {row["path"]: row for row in _doc(folder)["files"]}
    me = os.getuid()
    for item, mode in (("/etc/traffic-monitor/secrets/node_red_token_key", 0o640),
                       (f"{CODEDIR}/frigate/frigate.env", 0o600)):
        row = rows[item]
        assert row["mode"] == format(mode, "04o")
        assert (row["uid"], row["gid"]) == (me, os.getgid())
        assert _copy_of(folder, item).stat().st_mode & 0o777 == mode
    assert ("node_red_token_key", me, os.getgid()) in given


def test_a_listed_file_that_is_not_there_is_recorded_as_missing_and_is_not_an_error(world):
    paths, _ = world
    _put(paths, f"{CODEDIR}/node-red-tm/config/config.yml")
    paths.manifest.unlink()
    doc = _doc(_make(paths))
    assert f"{CODEDIR}/frigate/config/config.yml" in doc["missing"]
    assert "/var/lib/go2rtc/go2rtc.yaml" in doc["missing"]
    assert "/etc/traffic-monitor/manifest.json" in doc["missing"]
    assert "/var/lib/tm-control/state.sqlite" in doc["missing"]
    assert f"{CODEDIR}/node-red-tm/config/config.yml" not in doc["missing"]


def test_state_sqlite_is_copied_with_the_backup_api_and_opens(world, monkeypatch):
    paths, _ = world
    _state_db(paths.tm_control_state)
    writer = sqlite3.connect(paths.tm_control_state)
    wrote = []

    def progress(status, remaining, total):
        if not wrote:
            writer.execute("insert into t (b) values ('written during the copy')")
            writer.commit()
            wrote.append(1)

    monkeypatch.setattr(restore, "_progress", progress)
    folder = _make(paths)
    writer.close()
    assert wrote
    copy = _copy_of(folder, "/var/lib/tm-control/state.sqlite")
    db = sqlite3.connect(f"file:{copy}?mode=ro", uri=True)
    assert db.execute("pragma integrity_check").fetchall() == [("ok",)]
    assert db.execute("select count(*) from t").fetchone()[0] in (50, 51)
    db.close()
    row = next(row for row in _doc(folder)["files"] if row["path"] == "/var/lib/tm-control/state.sqlite")
    assert row["sha256"] == hashlib.sha256(copy.read_bytes()).hexdigest() and row["size"] == copy.stat().st_size
    assert "/var/lib/tm-control/state.sqlite" not in _doc(folder)["missing"]


def test_the_source_of_state_sqlite_is_opened_read_only(world, monkeypatch):
    paths, _ = world
    _state_db(paths.tm_control_state)
    opened = []
    real = sqlite3.connect

    def spy(target, *args, **kwargs):
        opened.append(str(target))
        return real(target, *args, **kwargs)

    monkeypatch.setattr(restore.sqlite3, "connect", spy)
    _make(paths)
    source = [target for target in opened if str(paths.tm_control_state) in target]
    assert source and all(target.startswith("file:") and target.endswith("?mode=ro") for target in source)


def test_a_secrets_content_and_checksum_are_in_no_json_and_no_log(world, capsys, caplog):
    paths, _ = world
    secret = _put(paths, "/etc/traffic-monitor/secrets/frigate_proxy_secret", text=MARKER + "\n", mode=0o640)
    folder = _make(paths)
    row = next(row for row in _doc(folder)["files"] if row["path"].endswith("/frigate_proxy_secret"))
    assert set(row) == {"path", "mode", "uid", "gid"}
    for entry in folder.rglob("*"):
        if entry.is_file() and "files" not in entry.relative_to(folder).parts[:1]:
            assert MARKER not in entry.read_text()
    assert MARKER in _copy_of(folder, "/etc/traffic-monitor/secrets/frigate_proxy_secret").read_text()
    text = (folder / "restore.json").read_text()
    assert hashlib.sha256(secret.read_bytes()).hexdigest() not in text
    seen = capsys.readouterr()
    assert MARKER not in seen.out + seen.err + caplog.text


def test_the_checksums_match_the_copies(world):
    paths, _ = world
    _every_listed_file(paths)
    _state_db(paths.tm_control_state)
    folder = _make(paths)
    seen = 0
    for row in _doc(folder)["files"]:
        if "sha256" not in row:
            continue
        copy = _copy_of(folder, row["path"])
        assert row["sha256"] == hashlib.sha256(copy.read_bytes()).hexdigest()
        assert row["size"] == copy.stat().st_size
        seen += 1
    assert seen >= 12


def _folder(paths, name):
    path = paths.restore_root / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def test_only_the_two_newest_are_kept(world):
    paths, _ = world
    names = ["20261101T000000Z-aaaaaaa", "20261102T000000Z-bbbbbbb", "20261103T000000Z-ccccccc",
             "20261104T000000Z-ddddddd"]
    for name in names:
        _folder(paths, name)
    others = ["notes", "20261101T000000Z-AAAAAAA", "20261101T000000Z-aaaaaaa.partial", "20261101T000000Z-aaaaaa",
              "x20261101T000000Z-aaaaaaa", "20261101T000000Z-aaaaaaa-old"]
    for name in others:
        _folder(paths, name)
    (paths.restore_root / "a-file").write_text("x")
    restore.keep_newest(paths)
    left = sorted(entry.name for entry in paths.restore_root.iterdir())
    assert left == sorted(names[2:] + others + ["a-file"])


def test_keep_newest_with_nothing_there_does_nothing(world):
    paths, _ = world
    restore.keep_newest(paths)
    _folder(paths, "20261101T000000Z-aaaaaaa")
    restore.keep_newest(paths)
    assert len(list(paths.restore_root.iterdir())) == 1


def test_a_failure_half_way_leaves_no_half_made_restore_point(world, monkeypatch):
    paths, _ = world
    _every_listed_file(paths)
    calls = []
    real = restore.shutil.copy2

    def broken(source, target, **kwargs):
        calls.append(source)
        if len(calls) == 4:
            raise OSError("disk trouble")
        return real(source, target, **kwargs)

    monkeypatch.setattr(restore.shutil, "copy2", broken)
    with pytest.raises(OSError):
        _make(paths)
    assert [entry.name for entry in paths.restore_root.iterdir()] == []


def test_a_partial_folder_of_a_dead_run_is_removed_first(world):
    paths, _ = world
    dead = _folder(paths, "20261101T000000Z-aaaaaaa.partial")
    (dead / "stuff").write_text("x")
    keep = _folder(paths, "notes.partial")
    folder = _make(paths)
    assert not dead.exists() and keep.exists()
    assert folder.is_dir()


def test_it_says_nothing_to_the_log_streams(world, capsys):
    paths, _ = world
    _every_listed_file(paths)
    _make(paths)
    out = capsys.readouterr()
    assert out.out == "" and out.err == ""


def test_the_new_one_is_kept_even_when_the_clock_names_it_older_than_the_rest(world):
    paths, _ = world
    for name in ("29990101T000000Z-aaaaaaa", "29990102T000000Z-bbbbbbb", "29990103T000000Z-ccccccc"):
        _folder(paths, name)
    new = _make(paths)
    restore.keep_newest(paths, just_made=new)
    assert sorted(entry.name for entry in paths.restore_root.iterdir()) == sorted(
        [new.name, "29990103T000000Z-ccccccc"])


def test_just_made_alone_is_kept_with_a_count_of_one(world):
    paths, _ = world
    _folder(paths, "29990101T000000Z-aaaaaaa")
    new = _make(paths)
    restore.keep_newest(paths, count=1, just_made=new)
    assert [entry.name for entry in paths.restore_root.iterdir()] == [new.name]


def test_everything_is_synced_before_the_rename_and_the_folder_after_it(world, monkeypatch):
    paths, _ = world
    _every_listed_file(paths)
    events = []
    monkeypatch.setattr(restore.os, "sync", lambda: events.append("sync"))
    real_fsync, real_rename = os.fsync, os.rename

    def fsync(fd):
        events.append(("fsync", os.readlink(f"/proc/self/fd/{fd}")))
        real_fsync(fd)

    def rename(source, target):
        events.append(("rename", Path(source).name))
        real_rename(source, target)

    monkeypatch.setattr(restore.os, "fsync", fsync)
    monkeypatch.setattr(restore.os, "rename", rename)
    folder = _make(paths)
    kinds = [event if isinstance(event, str) else event[0] for event in events]
    assert kinds.count("sync") == 1 and kinds.count("rename") == 1
    assert kinds.index("sync") < kinds.index("rename")
    after = events[kinds.index("rename") + 1:]
    assert ("fsync", str(paths.restore_root)) in after
    assert folder.is_dir()
