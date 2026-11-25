"""tm-update run: the order of the frame, and what each refusal and failure leaves behind."""

import fcntl
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from tm_update_support import (
    COMMIT,
    RUN,
    FakeRun,
    completed,
    handover_dict,
    make_world,
    manifest,
)

from tm_update import cli, installed as installed_module, playbook, proc
from tm_update.state import Failed

SCRIPT = Path(__file__).resolve().parents[1] / "tm-update"


class Device:
    """A device under a temporary root, the calls that would reach it recorded, and main() run against it."""

    def __init__(self, tmp_path, monkeypatch, **world):
        self.paths, self.tree = make_world(tmp_path, **world)
        self.handover_path = tmp_path / "handover.json"
        self.handover_path.write_text(json.dumps(handover_dict(self.paths)))
        self.stages = []
        self.playbook_rc = {}
        self.images = []
        self.when_a_stage_starts = None
        self.run = FakeRun(self._answer)
        monkeypatch.setattr(proc, "run", self.run)
        monkeypatch.setattr(installed_module, "_free_bytes", lambda path: 10**12)
        monkeypatch.setattr(playbook, "ensure_venv", self._ensure_venv)
        monkeypatch.setattr(playbook, "run_playbook", self._run_playbook)

    def _answer(self, call):
        if call["argv"][:2] == ["podman", "images"]:
            return completed(call["argv"], stdout=json.dumps(self.images))
        return None

    def _ensure_venv(self, tree, paths, log):
        if self.when_a_stage_starts:
            self.when_a_stage_starts()
        self.stages.append("venv")
        return paths.venv_root / "ansible-test"

    def _run_playbook(self, venv, tree, name, vars_file, handover, log, tags=None):
        self.stages.append((name, tuple(tags or ())))
        assert (handover.work_dir / "reason").parent.is_dir()
        key = tuple(tags or ())
        if self.playbook_rc.get(key):
            reason = self.playbook_rc[key]
            if isinstance(reason, str):
                (handover.work_dir / "reason").write_text(reason + "\n")
            return 1
        return 0

    def main(self, *args, is_root=True):
        argv = list(args) or ["run", "--contract", "1", "--handover", str(self.handover_path)]
        return cli.main(argv, paths=self.paths, tree=self.tree, is_root=lambda: is_root)

    def state(self):
        return json.loads(self.paths.state.read_text())

    def log(self):
        return (self.paths.log_dir / (RUN + ".log")).read_text()


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


def test_a_good_run_prepares_and_builds_in_order(device):
    assert device.main() == 0
    assert device.stages == ["venv", ("update_prepare.yml", ("stage",)), ("update_prepare.yml", ("images",))]
    state = device.state()
    assert state["result"] == "ok" and state["reason"] is None
    assert [row["id"] for row in state["stages"]] == ["prepare", "images"]
    assert all(row["finished_at"] for row in state["stages"])
    assert state["from"] == {"version": "0.7.1", "commit": "b" * 40}
    assert state["to"] == {"version": "0.8.0", "commit": COMMIT, "tag": "v0.8.0"}
    assert (device.paths.work_root / RUN).is_dir()
    assert oct((device.paths.work_root / RUN).stat().st_mode & 0o777) == "0o755"
    assert oct(device.paths.work_root.stat().st_mode & 0o777) == "0o755"
    assert oct((device.paths.log_dir / (RUN + ".log")).stat().st_mode & 0o777) == "0o640"
    assert "prepare" in device.log()


def test_the_vars_file_is_written_before_the_playbook(device, monkeypatch):
    seen = []
    real = playbook.write_vars

    def spy(hand, installed, tree, *, update_mode):
        seen.append((installed.codeowner, update_mode))
        return real(hand, installed, tree, update_mode=update_mode)

    monkeypatch.setattr(playbook, "write_vars", spy)
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

    device.when_a_stage_starts = look
    assert device.main() == 0
    assert before_the_first_stage["old_folder"] is False and before_the_first_stage["old_file"] is False
    assert len(before_the_first_stage["untags"]) == 2
    assert not other.exists() and not (device.paths.work_root / "stray-file").exists()
    assert (mine / "kept").exists()
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


def test_resume_reads_its_arguments(device):
    assert device.main("resume", "--handover", str(device.handover_path)) in (1, 2)


def test_the_command_line_names_both_commands():
    result = subprocess.run([sys.executable, "-EP", str(SCRIPT), "--help"], capture_output=True, text=True)
    assert result.returncode == 0
    assert "run" in result.stdout and "resume" in result.stdout


def test_no_command_is_a_usage_error():
    result = subprocess.run([sys.executable, "-EP", str(SCRIPT)], capture_output=True, text=True)
    assert result.returncode == 2
