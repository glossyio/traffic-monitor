"""tm-update run: the order of the frame, and what each refusal and failure leaves behind."""

import fcntl
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from tm_update_support import (
    BOOT,
    COMMIT,
    OTHER_BOOT,
    RUN,
    SWITCH_USEC,
    Device,
    manifest,
)

from tm_update import cleanup, installed as installed_module, playbook, restore
from tm_update.state import Failed

SCRIPT = Path(__file__).resolve().parents[1] / "tm-update"


@pytest.fixture
def device(tmp_path, monkeypatch):
    return Device(tmp_path, monkeypatch)


def test_it_refuses_to_run_as_anyone_but_root(device, capsys):
    assert device.main(is_root=False) == 2
    assert "root" in capsys.readouterr().err
    assert not device.paths.state.exists() and not device.paths.update_dir.joinpath("lock").exists()
    assert device.run.calls == []


@pytest.mark.parametrize("text", ["", "[]", "{}"])
def test_no_usable_hand_over_is_exit_2_and_writes_nothing(device, capsys, text):
    device.handover_path.write_text(text)
    assert device.main() == 2
    assert capsys.readouterr().err.count("\n") == 1
    assert not device.paths.state.exists() and not device.paths.log_dir.exists()


def test_a_contract_the_tree_does_not_accept_is_exit_2(device, capsys):
    assert device.main("run", "--contract", "2", "--handover", str(device.handover_path)) == 2
    assert not device.paths.state.exists()


def test_a_good_run_prepares_builds_switches_and_checks_in_order(device):
    modes = {}

    def look():
        modes["work"] = oct((device.paths.work_root / RUN).stat().st_mode & 0o777)
        modes["work_root"] = oct(device.paths.work_root.stat().st_mode & 0o777)

    device.when_a_stage_starts = look
    assert device.main() == 0
    assert device.stages == ["venv", ("update_prepare.yml", ("stage",)), ("update_prepare.yml", ("images",)),
                             ("setup.yml", ())]
    state = device.state()
    assert state["result"] == "ok" and state["reason"] is None
    assert [row["id"] for row in state["stages"]] == ["prepare", "images", "restore_point", "switch", "health",
                                                      "cleanup"]
    assert state["switch_attempts"] == 1 and state["reboot"] is False
    assert not device.paths.resume.exists()
    assert all(row["finished_at"] for row in state["stages"])
    assert state["from"] == {"version": "0.7.1", "commit": "b" * 40}
    assert state["to"] == {"version": "0.8.0", "commit": COMMIT, "tag": "v0.8.0"}
    assert modes == {"work": "0o755", "work_root": "0o755"}
    # The clean-up removed the work folder once the switch was healthy
    assert not (device.paths.work_root / RUN).exists() and device.paths.work_root.is_dir()
    assert oct((device.paths.log_dir / (RUN + ".log")).stat().st_mode & 0o777) == "0o640"
    assert "prepare" in device.log()


def test_the_restore_point_is_saved_after_the_images_and_its_folder_is_in_the_state(device):
    old_tree = device.paths.src_root / ("b" * 40)
    old_tree.mkdir(parents=True)
    (device.paths.secrets_dir).mkdir(parents=True)
    (device.paths.secrets_dir / "node_red_token_key").write_text("marker-7e1d\n")
    assert device.main() == 0
    state = device.state()
    folder = Path(state["restore_point"])
    assert folder.parent == device.paths.restore_root and (folder / "restore.json").is_file()
    assert json.loads((folder / "restore.json").read_text())["previous_tree"] == str(old_tree)
    row = next(row for row in state["stages"] if row["id"] == "restore_point")
    assert row["finished_at"] and [r["id"] for r in state["stages"]].index("restore_point") == 2
    assert "marker-7e1d" not in device.log() and "marker-7e1d" not in device.paths.state.read_text()


def test_only_two_restore_points_are_kept_by_a_run(device):
    for name in ("20261101T000000Z-aaaaaaa", "20261102T000000Z-bbbbbbb", "20261103T000000Z-ccccccc"):
        (device.paths.restore_root / name).mkdir(parents=True)
    assert device.main() == 0
    names = sorted(entry.name for entry in device.paths.restore_root.iterdir())
    assert names == sorted(["20261103T000000Z-ccccccc", Path(device.state()["restore_point"]).name])


def test_the_new_restore_point_survives_a_clock_behind_the_old_ones(device):
    for name in ("29990101T000000Z-aaaaaaa", "29990102T000000Z-bbbbbbb"):
        (device.paths.restore_root / name).mkdir(parents=True)
    assert device.main() == 0
    folder = Path(device.state()["restore_point"])
    assert folder.is_dir()
    assert sorted(entry.name for entry in device.paths.restore_root.iterdir()) == sorted(
        [folder.name, "29990102T000000Z-bbbbbbb"])


def test_a_failed_restore_point_ends_the_run_as_prepare_failed_with_nothing_half_made(device, monkeypatch):
    def boom(*args, **kwargs):
        raise OSError("disk trouble")

    monkeypatch.setattr(restore.shutil, "copy2", boom)
    (device.paths.rooted(Path("/var/lib/go2rtc"))).mkdir(parents=True)
    (device.paths.rooted(Path("/var/lib/go2rtc/go2rtc.yaml"))).write_text("x")
    assert device.main() == 1
    state = device.state()
    assert (state["result"], state["reason"], state["stage"]) == ("failed", "prepare_failed", "restore_point")
    assert state["restore_point"] is None
    assert list(device.paths.restore_root.iterdir()) == []


def test_the_vars_file_is_written_before_the_playbook(device, monkeypatch):
    seen = []
    real = playbook.write_vars

    def spy(hand, installed, tree, *, update_mode):
        seen.append((installed.codeowner, update_mode))
        return real(hand, installed, tree, update_mode=update_mode)

    monkeypatch.setattr(playbook, "write_vars", spy)
    monkeypatch.setattr(cleanup, "run", lambda ctx: [])  # it would remove the work folder this test looks in
    assert device.main() == 0
    assert seen and (device.paths.work_root / RUN / "vars.json").is_file()


def test_a_held_lock_ends_the_run_as_busy_and_leaves_the_state_of_the_other_run(device, capsys):
    device.paths.update_dir.mkdir(parents=True)
    device.paths.state.write_text('{"run_id": "other", "result": null}')
    device.paths.lock.touch()
    fd = os.open(device.paths.lock, os.O_RDONLY)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        assert device.main() == 1
    finally:
        os.close(fd)
    assert json.loads(device.paths.state.read_text()) == {"run_id": "other", "result": None}
    err = capsys.readouterr().err
    assert err.count("\n") == 1 and "busy" in err
    assert "busy" in device.log()
    assert device.run.calls == [] and device.stages == []


def test_the_lock_is_created_and_never_replaced(device):
    device.paths.update_dir.mkdir(parents=True)
    device.paths.lock.write_text("kept")
    assert device.main() == 0
    assert device.paths.lock.read_text() == "kept"


@pytest.mark.parametrize("contracts", [[True], [1.0], "1", [], [None], ["1"], {"1": 1}])
def test_contract_numbers_in_update_json_must_be_whole_numbers(device, capsys, contracts):
    path = device.tree / "script" / "update.json"
    data = json.loads(path.read_text())
    data["contracts"] = contracts
    path.write_text(json.dumps(data))
    assert device.main() == 2
    assert capsys.readouterr().err.count("\n") == 1
    assert not device.paths.state.exists() and not device.paths.log_dir.exists()


def test_a_new_lock_is_0644(device):
    assert device.main() == 0
    assert oct(device.paths.lock.stat().st_mode & 0o777) == "0o644"


def test_a_manifest_that_cannot_be_trusted_ends_the_run_as_a_manual_update(tmp_path, monkeypatch):
    device = Device(tmp_path, monkeypatch, manifest_data=manifest(installing_user="root"))
    assert device.main() == 1
    state = device.state()
    assert (state["result"], state["reason"]) == ("failed", "needs_manual_update")
    assert state["from"] == {"version": None, "commit": None}
    assert device.stages == []


def test_a_dead_runs_work_folders_and_build_tags_are_cleared_first(device):
    other = device.paths.work_root / "older-run"
    (other / "stage").mkdir(parents=True)
    (other / "stage" / "file").write_text("x")
    (device.paths.work_root / "stray-file").write_text("x")
    mine = device.paths.work_root / RUN
    mine.mkdir()
    (mine / "kept").write_text("x")
    device.images = [
        {"Id": "id1", "Names": ["localhost/frigate-tm:prepare-abc1234", "localhost/frigate-tm:0.18.2"]},
        {"Id": "id2", "Names": ["localhost/revproxy:prepare-9999999", "localhost/revproxy:stage-ui"]},
        {"Id": "id3", "Names": ["docker.io/library/node:prepare-x", "localhost/node-red-tm:latest"]},
        {"Id": "id4", "Names": None},
        {"Id": 5, "Names": ["localhost/x:prepare-1"]},
    ]
    before_the_first_stage = {}

    def look():
        before_the_first_stage["old_folder"] = other.exists()
        before_the_first_stage["old_file"] = (device.paths.work_root / "stray-file").exists()
        before_the_first_stage["untags"] = [a for a in device.run.argvs() if a[:2] == ["podman", "untag"]]
        before_the_first_stage["mine_kept"] = (mine / "kept").exists()

    device.when_a_stage_starts = look
    assert device.main() == 0
    assert before_the_first_stage["old_folder"] is False and before_the_first_stage["old_file"] is False
    assert len(before_the_first_stage["untags"]) == 2
    assert not other.exists() and not (device.paths.work_root / "stray-file").exists()
    assert before_the_first_stage["mine_kept"] is True
    untags = [argv for argv in device.run.argvs() if argv[:2] == ["podman", "untag"]]
    assert untags == [["podman", "untag", "id1", "localhost/frigate-tm:prepare-abc1234"],
                      ["podman", "untag", "id2", "localhost/revproxy:prepare-9999999"]]
    assert all(len(argv) == 4 for argv in untags)


def test_a_refusal_ends_the_run_before_any_playbook(device, monkeypatch, capsys):
    monkeypatch.setattr(installed_module, "_free_bytes", lambda path: 1_000_000)
    assert device.main() == 1
    state = device.state()
    assert (state["result"], state["reason"]) == ("failed", "low_space")
    assert state["detail"] == "1 MB free, 8000 MB needed"
    assert device.stages == []
    assert "low_space" in capsys.readouterr().err


def test_a_refused_add_on_is_the_addon_code(tmp_path, monkeypatch):
    device = Device(tmp_path, monkeypatch, manifest_data=manifest(options={"plate_recognizer": True}))
    assert device.main() == 1
    assert device.state()["reason"] == "addon_needs_installer"


def test_a_waiting_restart_is_the_reboot_pending_code(device):
    device.paths.reboot_required.parent.mkdir(parents=True)
    device.paths.reboot_required.touch()
    assert device.main() == 1
    assert device.state()["reason"] == "reboot_pending"


@pytest.mark.parametrize("key,default,stage", [(("stage",), "prepare_failed", "prepare"),
                                               (("images",), "build_failed", "images")])
def test_each_failure_takes_its_default_code(device, key, default, stage):
    device.playbook_rc[key] = True
    assert device.main() == 1
    state = device.state()
    assert (state["result"], state["reason"], state["stage"]) == ("failed", default, stage)
    assert state["stages"][-1]["id"] == stage and state["stages"][-1]["finished_at"]
    assert "\n" not in state["detail"]


def test_a_failure_takes_the_code_the_playbook_wrote(device):
    device.playbook_rc[("stage",)] = "no_internet"
    assert device.main() == 1
    assert device.state()["reason"] == "no_internet"
    assert device.stages[-1] == ("update_prepare.yml", ("stage",))


def test_an_unknown_code_in_the_reason_file_gives_the_default(device):
    device.playbook_rc[("images",)] = "something else"
    assert device.main() == 1
    assert device.state()["reason"] == "build_failed"


def test_the_images_do_not_build_after_a_failed_prepare(device):
    device.playbook_rc[("stage",)] = True
    device.main()
    assert ("update_prepare.yml", ("images",)) not in device.stages


def test_an_unexpected_exception_is_logged_and_ends_the_run_with_the_stages_code(device, monkeypatch, capsys):
    def boom(*args, **kwargs):
        raise RuntimeError("secret-looking text")

    monkeypatch.setattr(playbook, "write_vars", boom)
    assert device.main() == 1
    state = device.state()
    assert (state["result"], state["reason"]) == ("failed", "prepare_failed")
    assert state["detail"] == "unexpected RuntimeError"
    assert "Traceback" in device.log() and "secret-looking text" in device.log()
    assert "secret-looking text" not in capsys.readouterr().err


def test_a_venv_failure_carries_its_own_code(device, monkeypatch):
    def broken(tree, paths, log):
        raise Failed("prepare_failed", "ansible environment")

    monkeypatch.setattr(playbook, "ensure_venv", broken)
    assert device.main() == 1
    assert device.state()["detail"] == "ansible environment"




def test_the_command_line_names_both_commands():
    result = subprocess.run([sys.executable, "-EP", str(SCRIPT), "--help"], capture_output=True, text=True)
    assert result.returncode == 0
    assert "run" in result.stdout and "resume" in result.stdout


def test_no_command_is_a_usage_error():
    result = subprocess.run([sys.executable, "-EP", str(SCRIPT)], capture_output=True, text=True)
    assert result.returncode == 2


# The switch's end, resume, and health, as the command runs them

def _cut_off(device, stage, *, attempts=1, boot_id=None, result=None, run_id=RUN, switched=True,
             switch_started="2026-11-25T10:20:00Z"):
    """A run a restart cut off at this stage: its state file, its marker, its work folder."""
    finished = [{"id": name, "started_at": "2026-11-25T10:00:00Z", "finished_at": "2026-11-25T10:10:00Z"}
                for name in ("prepare", "images", "restore_point")]
    rows = finished + [{"id": "switch", "started_at": switch_started,
                        "finished_at": None if stage == "switch" else "2026-11-25T10:30:00Z"}]
    if stage in ("reboot", "health", "cleanup"):
        rows.append({"id": stage, "started_at": "2026-11-25T10:31:00Z", "finished_at": None})
    if stage == "cleanup":
        rows.insert(-1, {"id": "health", "started_at": "2026-11-25T10:31:00Z",
                         "finished_at": "2026-11-25T10:32:00Z"})
    state = {"schema": 1, "run_id": run_id, "channel": "stable", "from": {"version": "0.7.1", "commit": "b" * 40},
             "to": {"version": "0.8.0", "commit": COMMIT, "tag": "v0.8.0"}, "stage": stage, "stages": rows,
             "result": result, "reason": None, "detail": None, "boot_id": boot_id,
             "reboot": True if stage == "reboot" else None, "restore_point": None, "tmdb_backup": None,
             "switch_attempts": attempts}
    device.paths.update_dir.mkdir(parents=True, exist_ok=True)
    device.paths.state.write_text(json.dumps(state))
    device.paths.resume.write_text(json.dumps(
        {"contract": 1, "tree": str(device.tree), "handover": str(device.handover_path)}))
    device.work.mkdir(parents=True, exist_ok=True)
    (device.work / "facts.json").write_text(json.dumps({"tm_control_port": 8090, "images": []}))
    if switched:
        data = json.loads(device.paths.manifest.read_text())
        data["git"]["commit"] = COMMIT
        device.paths.manifest.write_text(json.dumps(data))
    return state


@pytest.mark.parametrize(("stage", "attempts", "same_boot", "does"), [
    ("reboot", 1, False, "health"), ("reboot", 1, True, "nothing"),
    ("switch", 1, False, "switch"), ("switch", 2, False, "fail"), ("health", 1, False, "health"),
    ("cleanup", 1, False, "cleanup")])
def test_resume_carries_a_run_on_from_where_it_stopped(device, stage, attempts, same_boot, does):
    _cut_off(device, stage, attempts=attempts, boot_id=BOOT if same_boot else OTHER_BOOT,
             switched=stage != "switch")
    if stage != "switch":
        # After a restart the control app started early in this boot: any start time counts
        device.tm_control_entered = 1
    before = device.paths.state.read_bytes()
    status = device.resume()
    state = device.state()
    ran_setup = ("setup.yml", ()) in device.stages
    checked = bool(device.systemctl_calls("is-active"))
    if does == "nothing":
        assert status == 0
        assert device.paths.state.read_bytes() == before
        assert device.paths.resume.exists() and device.run.calls == []
        return
    assert not device.paths.resume.exists()
    if does == "fail":
        assert status == 1
        assert (state["result"], state["reason"]) == ("failed", "switch_failed")
        assert device.systemctl_calls("start") == [["systemctl", "start", unit] for unit in
                                                   ("tm-control.service", "traffic-monitor.service",
                                                    "revproxy.service")]
        assert not ran_setup and not checked
        assert all(row["finished_at"] for row in state["stages"])
        return
    assert status == 0 and state["result"] == "ok"
    assert all(row["finished_at"] for row in state["stages"])
    # The manifest names the new commit by now; the state keeps where the run came from
    assert state["from"] == {"version": "0.7.1", "commit": "b" * 40}
    ids = [row["id"] for row in state["stages"]]
    if does == "switch":
        assert ran_setup and checked and state["switch_attempts"] == 2
        assert ids[-4:] == ["switch", "switch", "health", "cleanup"]
        assert device.systemctl_calls("stop") == [["systemctl", "stop", "traffic-monitor.service",
                                                   "tm-control.service"]]
    elif does == "health":
        assert checked and not ran_setup
        assert ids[-2:] == ["health", "cleanup"] and ids.count("switch") == 1
        assert device.systemctl_calls("stop") == []
    else:  # cleanup
        assert not checked and not ran_setup
        assert ids[-1] == "cleanup"


def test_a_resumed_switch_records_its_own_start_for_the_health_check(device):
    _cut_off(device, "switch", attempts=1, switched=False)
    device.tm_control_entered = SWITCH_USEC  # not later than the redone switch's stop: the old control app
    assert device.resume() == 1
    assert (device.state()["reason"], device.state()["detail"]) == ("health_failed", "tm-control")


def test_a_resumed_switch_that_wants_a_restart_hands_over_again(device):
    _cut_off(device, "switch", attempts=1, switched=False)
    device.reboot_flag = "1"
    assert device.resume() == 0
    state = device.state()
    assert (state["stage"], state["reboot"], state["boot_id"], state["result"]) == ("reboot", True, BOOT, None)
    assert device.paths.resume.exists()


@pytest.mark.parametrize("case", ["no marker", "finished", "failed", "another run"])
def test_resume_without_a_marker_or_with_a_finished_run_does_nothing(device, case):
    _cut_off(device, "health", result={"finished": "ok", "failed": "failed"}.get(case),
             run_id="another-run" if case == "another run" else RUN)
    if case == "no marker":
        device.paths.resume.unlink()
    before = device.paths.state.read_bytes()
    assert device.resume() == 0
    assert device.paths.state.read_bytes() == before
    assert not device.paths.resume.exists()
    assert device.run.calls == [] and device.stages == []


def test_resume_takes_the_lock_like_run(device, capsys):
    _cut_off(device, "health")
    before = device.paths.state.read_bytes()
    device.paths.lock.touch()
    fd = os.open(device.paths.lock, os.O_RDONLY)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        assert device.resume() == 1
    finally:
        os.close(fd)
    assert device.paths.state.read_bytes() == before
    assert device.paths.resume.exists()
    assert "busy" in capsys.readouterr().err
    assert device.run.calls == []


@pytest.mark.parametrize("marker", ['{"contract": "1", "tree": "/x", "handover": "/y"}', "[]", "{",
                                    '{"contract": 1, "tree": 5, "handover": "/y"}',
                                    '{"contract": true, "tree": "/x", "handover": "/y"}'])
def test_a_marker_that_cannot_be_read_is_removed(device, marker, capsys):
    _cut_off(device, "health")
    before = device.paths.state.read_bytes()
    device.paths.resume.write_text(marker)
    assert device.resume() == 2
    assert not device.paths.resume.exists()
    assert device.paths.state.read_bytes() == before
    assert capsys.readouterr().err.count("\n") == 1


@pytest.mark.parametrize("key", ["tree", "handover"])
def test_a_marker_for_another_tree_or_hand_over_is_left_for_it(device, key):
    _cut_off(device, "health")
    data = json.loads(device.paths.resume.read_text())
    data[key] = "/somewhere/else"
    device.paths.resume.write_text(json.dumps(data))
    assert device.resume() == 2
    assert json.loads(device.paths.resume.read_text())[key] == "/somewhere/else"
    assert device.run.calls == []


def test_an_unhealthy_update_leaves_the_new_version_and_keeps_its_work_folder(device):
    device.unit_state["frigate.service"] = "failed"
    assert device.main() == 1
    state = device.state()
    assert (state["result"], state["reason"], state["detail"], state["stage"]) == (
        "failed", "health_failed", "frigate.service", "health")
    assert json.loads(device.paths.manifest.read_text())["git"]["commit"] == COMMIT
    assert (device.work / "vars.json").is_file()
    assert not device.paths.resume.exists()
    assert device.systemctl_calls("start") == [] and len(device.systemctl_calls("stop")) == 1
    assert [row["id"] for row in state["stages"]][-1] == "health"
    assert state["tmdb_backup"] is None


def _backup_dir(device):
    folder = device.paths.root / "opt" / "traffic-monitor" / "node-red-tm" / "db" / "backup"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def test_the_migration_runners_database_copy_is_recorded(device):
    folder = _backup_dir(device)
    old = folder / "tmdb-v9-20200101T000000Z.sqlite"
    old.write_bytes(b"old")
    os.utime(old, (946684800, 946684800))

    def migrate():
        (folder / "tmdb-v10-20261125T103000Z.sqlite").write_bytes(b"new")
        (folder / "tmdb-v10-20261125T103001Z.sqlite.partial").write_bytes(b"half")

    device.during_setup = migrate
    assert device.main() == 0
    state = device.state()
    expected = str(folder / "tmdb-v10-20261125T103000Z.sqlite")
    assert state["tmdb_backup"] == expected
    listing = Path(state["restore_point"]) / "restore.json"
    assert json.loads(listing.read_text())["tmdb_backup"] == expected
    assert oct(listing.stat().st_mode & 0o777) == "0o600"
    assert [p.name for p in listing.parent.iterdir() if p.name.startswith(".")] == []


def test_no_new_database_copy_leaves_the_record_empty(device):
    folder = _backup_dir(device)
    old = folder / "tmdb-v9-20200101T000000Z.sqlite"
    old.write_bytes(b"old")
    os.utime(old, (946684800, 946684800))
    assert device.main() == 0
    state = device.state()
    assert state["tmdb_backup"] is None
    assert json.loads((Path(state["restore_point"]) / "restore.json").read_text())["tmdb_backup"] is None


def test_after_a_restart_the_copy_is_the_newest_made_since_the_first_switch_began(device):
    _cut_off(device, "reboot", boot_id=OTHER_BOOT, switch_started="2026-11-25T10:20:00Z")
    device.tm_control_entered = 1
    folder = _backup_dir(device)
    began = 1_795_602_000  # 2026-11-25T10:20:00Z
    for name, when in (("tmdb-v9-a.sqlite", began - 60), ("tmdb-v10-b.sqlite", began + 60),
                       ("tmdb-v10-c.sqlite", began + 120)):
        (folder / name).write_bytes(b"x")
        os.utime(folder / name, (when, when))
    assert device.resume() == 0
    assert device.state()["tmdb_backup"] == str(folder / "tmdb-v10-c.sqlite")


# A repeated switch: the first attempt may have stopped the units and run part of the installer

STARTS = [["systemctl", "start", unit] for unit in ("tm-control.service", "traffic-monitor.service",
                                                     "revproxy.service")]


def test_a_repeated_switch_skips_the_space_check_for_the_database_copy(device, monkeypatch):
    _cut_off(device, "switch", attempts=1, switched=False)
    db = device.paths.root / "opt" / "traffic-monitor" / "node-red-tm" / "db"
    (db / "tmdb.sqlite").write_bytes(b"x" * 5_000_000)
    monkeypatch.setattr(installed_module, "_free_bytes", lambda path: 0)
    assert device.resume() == 0
    assert ("setup.yml", ()) in device.stages
    state = device.state()
    assert (state["result"], state["switch_attempts"]) == ("ok", 2)


@pytest.mark.parametrize(("breaks", "detail"), [("ensure_venv", "venv"), ("write_vars", "vars")])
def test_a_repeated_switch_that_fails_before_its_marker_starts_the_three_services(device, monkeypatch, breaks,
                                                                                    detail):
    _cut_off(device, "switch", attempts=1, switched=False)

    def broken(*args, **kwargs):
        if breaks == "ensure_venv":
            raise Failed("prepare_failed", "ansible environment")
        raise OSError("disk trouble")

    monkeypatch.setattr(playbook, breaks, broken)
    assert device.resume() == 1
    state = device.state()
    assert (state["result"], state["reason"], state["detail"]) == ("failed", "switch_failed", detail)
    assert device.systemctl_calls("start") == STARTS
    assert device.systemctl_calls("stop") == [] and ("setup.yml", ()) not in device.stages
    assert state["switch_attempts"] == 1
    assert not device.paths.resume.exists()
    assert all(row["finished_at"] for row in state["stages"])


@pytest.mark.parametrize("problem", ["missing", "root"])
def test_a_resumed_switch_whose_manifest_cannot_be_used_starts_the_three_services(device, problem):
    _cut_off(device, "switch", attempts=1, switched=False)
    if problem == "missing":
        device.paths.manifest.unlink()
    else:
        device.paths.manifest.write_text(json.dumps(manifest(installing_user="root")))
    assert device.resume() == 1
    state = device.state()
    assert (state["result"], state["reason"], state["detail"]) == ("failed", "switch_failed", "manifest")
    assert device.systemctl_calls("start") == STARTS
    assert ("setup.yml", ()) not in device.stages
    assert not device.paths.resume.exists()
    assert state["from"] == {"version": "0.7.1", "commit": "b" * 40}


@pytest.mark.parametrize("stage", ["reboot", "health", "cleanup"])
def test_a_manifest_that_cannot_be_used_after_the_switch_keeps_its_own_code(device, stage):
    _cut_off(device, stage, boot_id=OTHER_BOOT)
    device.paths.manifest.unlink()
    assert device.resume() == 1
    assert device.state()["reason"] == "needs_manual_update"
    assert device.systemctl_calls("start") == []


def test_a_first_switch_that_fails_before_its_marker_stops_and_starts_nothing(device, monkeypatch):
    real = playbook.write_vars
    calls = []

    def third_call_breaks(hand, installed, tree, *, update_mode):
        calls.append(update_mode)
        if len(calls) == 3:  # Prepare writes it twice; the switch is the third
            raise OSError("disk trouble")
        return real(hand, installed, tree, update_mode=update_mode)

    monkeypatch.setattr(playbook, "write_vars", third_call_breaks)
    assert device.main() == 1
    state = device.state()
    assert (state["reason"], state["stage"], state["detail"]) == ("switch_failed", "switch", "unexpected OSError")
    assert state["switch_attempts"] == 0
    assert device.systemctl_calls("stop") == [] and device.systemctl_calls("start") == []
    assert not device.paths.resume.exists()
