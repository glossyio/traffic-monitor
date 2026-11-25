"""tm-update's Ansible environment and the two prepare runs of the role's playbook."""

import hashlib
import json
import subprocess
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
                                 tags=["stage"]) == 0
    call = fake.calls[0]
    assert call["argv"] == ["/v/ansible/bin/ansible-playbook", "-i", "localhost", "update_prepare.yml", "-e",
                            "@" + str(vars_file), "--tags", "stage"]
    assert call["cwd"] == tree / "script" / "ansible"
    assert call["log"] is log and call["check"] is False
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
    assert playbook.run_playbook(Path("/v"), tree, "setup.yml", hand.work_dir / "vars.json", hand, None) == 2
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
