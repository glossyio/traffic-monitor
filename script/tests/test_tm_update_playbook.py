"""tm-update's Ansible environment and the two prepare runs of the role's playbook."""

import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest
from tm_update_support import COMMIT, FakeRun, completed, handover, installed, make_world

from tm_update import playbook, proc
from tm_update.state import REASONS, Failed


@pytest.fixture
def world(tmp_path):
    paths, tree = make_world(tmp_path)
    work = paths.work_root / "20261125T101500Z-abc"
    work.mkdir(parents=True)
    return paths, tree, handover(paths)


def test_the_venv_is_named_for_the_lock(world):
    paths, tree, _ = world
    lock = tree / "script" / "requirements.lock"
    name = "ansible-" + hashlib.sha256(lock.read_bytes()).hexdigest()[:12]
    assert playbook.venv_path(lock, paths) == paths.venv_root / name
    other = tree / "other.lock"
    other.write_text("different")
    assert playbook.venv_path(other, paths) != playbook.venv_path(lock, paths)


def test_a_finished_venv_is_used_as_it_is(world, monkeypatch):
    paths, tree, _ = world
    venv = playbook.venv_path(tree / "script" / "requirements.lock", paths)
    (venv / "bin").mkdir(parents=True)
    (venv / "bin" / "ansible-playbook").write_text("")
    fake = FakeRun()
    monkeypatch.setattr(proc, "run", fake)
    assert playbook.ensure_venv(tree, paths, None) == venv
    assert fake.calls == []


def test_a_half_made_venv_is_made_again(world, monkeypatch):
    paths, tree, _ = world
    venv = playbook.venv_path(tree / "script" / "requirements.lock", paths)
    (venv / "bin").mkdir(parents=True)
    (venv / "bin" / "python").write_text("")
    (venv / "stale").write_text("")

    def answer(call):
        if call["argv"][1:3] == ["-m", "venv"]:
            assert not (venv / "stale").exists()
            (venv / "bin").mkdir(parents=True)
        if call["argv"][0].endswith("/pip"):
            (venv / "bin" / "ansible-playbook").write_text("")

    fake = FakeRun(answer)
    monkeypatch.setattr(proc, "run", fake)
    assert playbook.ensure_venv(tree, paths, None) == venv
    first, second = fake.argvs()
    assert first == ["python3", "-m", "venv", str(venv)]
    assert second[0] == str(venv / "bin" / "pip")
    assert "--require-hashes" in second
    assert "--no-cache-dir" in second
    assert second[second.index("-r") + 1] == str(tree / "script" / "requirements.lock")
    assert (venv / "bin" / "ansible-playbook").exists()


def test_a_venv_that_cannot_be_made_fails_the_prepare_and_is_removed(world, monkeypatch):
    paths, tree, _ = world

    def answer(call):
        venv = Path(call["argv"][3]) if call["argv"][1:3] == ["-m", "venv"] else None
        if venv:
            venv.mkdir(parents=True)
            return completed(call["argv"])
        return completed(call["argv"], rc=1)

    monkeypatch.setattr(proc, "run", FakeRun(answer))
    with pytest.raises(Failed) as error:
        playbook.ensure_venv(tree, paths, None)
    assert error.value.reason == "prepare_failed"
    assert not playbook.venv_path(tree / "script" / "requirements.lock", paths).exists()


def vars_for(world, *, update_mode, **changes):
    paths, tree, hand = world
    file = playbook.write_vars(hand, installed(**changes), tree, update_mode=update_mode)
    return file, json.loads(file.read_text())


def test_vars_hold_text_as_text_and_only_the_listed_keys(world):
    paths, tree, hand = world
    work = str(hand.work_dir)
    for mode in (True, False):
        file, data = vars_for(world, update_mode=mode)
        assert file == hand.work_dir / "vars.json"
        assert data == {
            "tmsetup_codedir": "/opt/traffic-monitor", "tmsetup_codeowner": "tmadmin", "tmsetup_codegroup": "tmadmin",
            "tmsetup_installing_user": "pi", "tmsetup_update_repo": "example/traffic-monitor-test",
            "tmsetup_source_commit": COMMIT, "tmsetup_source_branch": "main", "tmsetup_source_modified": False,
            "tmsetup_tmp_dir": work, "tmsetup_reboot_touch_file": work + "/reboot-required",
            "tmsetup_update_work_dir": work, "tmsetup_update_stage_dir": work + "/stage",
            "tmsetup_update_reason_file": work + "/reason", "tmsetup_update_build_tag": "prepare-" + COMMIT[:7],
            "tmsetup_update_mode": mode,
        }


def test_a_manifest_with_no_repository_leaves_the_variable_out(world):
    _, data = vars_for(world, update_mode=True, repo=None)
    assert "tmsetup_update_repo" not in data


def test_the_branch_follows_the_channel(world):
    paths, tree, _ = world
    for channel, branch in (("stable", "main"), ("development", "dev")):
        file = playbook.write_vars(handover(paths, channel=channel), installed(), tree, update_mode=True)
        assert json.loads(file.read_text())["tmsetup_source_branch"] == branch


def test_a_standing_option_is_passed_back(world, monkeypatch):
    monkeypatch.setattr(playbook, "OPTIONS_PASSED_BACK", ("mqtt_lan", "other"))
    _, data = vars_for(world, update_mode=True, options={"mqtt_lan": True, "other": False})
    assert data["tmsetup_bool_mqtt_lan"] is True and "tmsetup_bool_other" not in data


def test_the_playbook_gets_no_terminal_and_its_own_home(world, monkeypatch):
    paths, tree, hand = world
    fake = FakeRun()
    monkeypatch.setattr(proc, "run", fake)
    vars_file = hand.work_dir / "vars.json"
    log = object()
    assert playbook.run_playbook(Path("/v/ansible"), tree, "update_prepare.yml", vars_file, hand, log,
                                 tags=["stage"], timeout=1800) == 0
    call = fake.calls[0]
    assert call["argv"] == ["/v/ansible/bin/ansible-playbook", "-i", "localhost", "update_prepare.yml", "-e",
                            "@" + str(vars_file), "--tags", "stage"]
    assert call["cwd"] == tree / "script" / "ansible"
    assert call["log"] is log and call["check"] is False and call["timeout"] == 1800
    env = call["env"]
    assert env["HOME"] == str(hand.work_dir / "home")
    assert env["ANSIBLE_LOCAL_TEMP"] == env["ANSIBLE_REMOTE_TEMP"] == str(hand.work_dir / "ansible-tmp")
    assert env["ANSIBLE_NOCOLOR"] == "1" and env["ANSIBLE_FORCE_COLOR"] == "0"
    assert env["PATH"] == "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
    assert "TERM" not in env and "SSH_AUTH_SOCK" not in env
    assert (hand.work_dir / "home").is_dir() and (hand.work_dir / "ansible-tmp").is_dir()


def test_the_playbook_runs_without_tags_when_none_are_given(world, monkeypatch):
    paths, tree, hand = world
    fake = FakeRun(lambda call: completed(call["argv"], rc=2))
    monkeypatch.setattr(proc, "run", fake)
    assert playbook.run_playbook(Path("/v"), tree, "setup.yml", hand.work_dir / "vars.json", hand, None,
                                 timeout=2700) == 2
    assert "--tags" not in fake.argvs()[0]


def test_a_reason_file_names_the_code(world):
    _, _, hand = world
    for code in REASONS:
        (hand.work_dir / "reason").write_text(code + "\n")
        assert playbook.reason_from(hand, "prepare_failed") == code


@pytest.mark.parametrize("text", ["ship_it\n", "", "low_space and more\n", "\n", "build_failed\x00", "x" * 5000,
                                  "No such file or directory"])
def test_a_reason_file_with_an_unknown_code_gives_the_default(world, text):
    _, _, hand = world
    (hand.work_dir / "reason").write_text(text)
    assert playbook.reason_from(hand, "prepare_failed") == "prepare_failed"


def test_no_reason_file_gives_the_default(world):
    _, _, hand = world
    assert playbook.reason_from(hand, "build_failed") == "build_failed"


def test_proc_runs_an_argv_list_with_no_stdin_and_never_a_shell(tmp_path):
    result = proc.run(["sh", "-c", "cat; echo out; echo err >&2"])
    assert (result.returncode, result.stdout.strip()) == (0, "out")
    with pytest.raises(TypeError):
        proc.run("echo hi")
    log = (tmp_path / "log").open("w")
    proc.run(["sh", "-c", "echo out; echo err >&2"], log=log, cwd=tmp_path)
    log.close()
    assert sorted((tmp_path / "log").read_text().split()) == ["err", "out"]
    with pytest.raises(subprocess.CalledProcessError):
        proc.run(["false"], check=True)
    assert proc.run(["sh", "-c", "pwd"], cwd=tmp_path).stdout.strip() == str(tmp_path)


def test_a_playbook_run_needs_its_limit(world):
    paths, tree, hand = world
    with pytest.raises(TypeError):
        playbook.run_playbook(Path("/v"), tree, "setup.yml", hand.work_dir / "vars.json", hand, None)


def _venv_answer(venv_made_by):
    def answer(call):
        if call["argv"][1:3] == ["-m", "venv"]:
            venv = Path(call["argv"][3])
            venv_made_by.append(venv)
            (venv / "bin").mkdir(parents=True)
        elif call["argv"][0].endswith("/pip"):
            (venv_made_by[-1] / "bin" / "ansible-playbook").write_text("")
    return answer


def test_each_step_of_the_ansible_environment_has_its_limit(world, monkeypatch):
    paths, tree, _ = world
    fake = FakeRun(_venv_answer([]))
    monkeypatch.setattr(proc, "run", fake)
    playbook.ensure_venv(tree, paths, None)
    assert [call["timeout"] for call in fake.calls] == [900, 900]


def test_a_pip_that_outlives_its_limit_fails_the_prepare_with_the_minutes_and_is_removed(world, monkeypatch):
    paths, tree, _ = world
    made = []
    answer = _venv_answer(made)

    def slow_pip(call):
        answer(call)
        if call["argv"][0].endswith("/pip"):
            raise proc.TimedOut(call["argv"][0], call["timeout"])

    monkeypatch.setattr(proc, "run", FakeRun(slow_pip))
    with pytest.raises(Failed) as error:
        playbook.ensure_venv(tree, paths, None)
    assert (error.value.reason, error.value.detail) == ("prepare_failed", "timed out after 15 min")
    assert made and not made[0].exists()


def test_a_time_out_is_a_timeout_expired_and_says_its_whole_minutes():
    error = proc.TimedOut("/v/bin/ansible-playbook", 7200)
    assert isinstance(error, subprocess.TimeoutExpired)
    assert (error.cmd, error.seconds, error.timeout) == ("/v/bin/ansible-playbook", 7200, 7200)
    assert error.detail == "timed out after 120 min"
    assert proc.TimedOut("x", 2700).detail == "timed out after 45 min"
    assert proc.TimedOut("x", 119).detail == "timed out after 1 min"


def _gone(pid, within=3.0):
    """The process has ended: it is gone, or a zombie waiting for its new parent to reap it."""
    deadline = time.monotonic() + within
    while time.monotonic() < deadline:
        try:
            with open(f"/proc/{pid}/stat", encoding="ascii") as handle:
                if handle.read().rsplit(")", 1)[1].split()[0] == "Z":
                    return True
        except (FileNotFoundError, ProcessLookupError):
            return True
        time.sleep(0.05)
    return False


def _script(tmp_path, body):
    script = tmp_path / "script.sh"
    script.write_text(body)
    return script


def test_a_command_that_outlives_its_limit_is_killed_with_what_it_started(tmp_path):
    pidfile = tmp_path / "grandchild"
    script = _script(tmp_path, f"echo started\nsleep 60 &\necho $! > {pidfile}\nwait\n")
    log = (tmp_path / "log").open("w")
    began = time.monotonic()
    with pytest.raises(proc.TimedOut) as error:
        proc.run(["sh", str(script)], log=log, timeout=1)
    took = time.monotonic() - began
    log.close()
    assert isinstance(error.value, subprocess.TimeoutExpired)
    assert (error.value.cmd, error.value.seconds) == ("sh", 1)
    # The TERM ends it: no wait for the grace before the KILL
    assert took < 5
    assert _gone(int(pidfile.read_text()))
    # What the command wrote before the limit stays in the log
    assert (tmp_path / "log").read_text() == "started\n"


def test_a_command_that_ignores_the_term_is_killed_after_the_grace(tmp_path, monkeypatch):
    monkeypatch.setattr(proc, "_GRACE", 0.5)
    pidfile = tmp_path / "grandchild"
    # An ignored signal stays ignored across exec, so the sleep ignores the TERM too
    script = _script(tmp_path, f"trap '' TERM\nsleep 60 &\necho $! > {pidfile}\nwait\n")
    began = time.monotonic()
    with pytest.raises(proc.TimedOut):
        proc.run(["sh", str(script)], timeout=0.5)
    took = time.monotonic() - began
    assert 1.0 <= took < 5
    assert _gone(int(pidfile.read_text()))


def test_a_command_without_output_captured_is_killed_the_same_way(tmp_path):
    pidfile = tmp_path / "grandchild"
    script = _script(tmp_path, f"sleep 60 &\necho $! > {pidfile}\nwait\n")
    with pytest.raises(proc.TimedOut):
        proc.run(["sh", str(script)], timeout=1)
    assert _gone(int(pidfile.read_text()))


def test_every_command_runs_in_a_session_of_its_own(tmp_path):
    code = "import os; print(os.getsid(0) == os.getpid(), os.getpgid(0) == os.getpid())"
    assert proc.run([sys.executable, "-c", code]).stdout.split() == ["True", "True"]


def test_a_command_that_ends_in_time_is_not_signalled(tmp_path, monkeypatch):
    signalled = []
    monkeypatch.setattr(proc.os, "killpg", lambda *args: signalled.append(args))
    assert proc.run(["sh", "-c", "exit 3"], timeout=30).returncode == 3
    assert signalled == []
