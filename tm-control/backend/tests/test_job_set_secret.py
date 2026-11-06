"""The set-secret root job, run as a script against a fake systemctl that records each call.

fixtures/run_job.py runs it with a non-root euid, so the fake systemctl is used and the secrets directory may be the
test's own, even when the suite runs as root.
"""

import importlib.machinery
import importlib.util
import json
import os
import pwd
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from placeholders import PLACEHOLDER_KEY
from tm_control.core.secrets import ENTERED_SECRETS, VALUE_PATTERNS
from tm_control.modules.secrets.router import ENTERED

JOB = Path(__file__).resolve().parents[2] / "jobs" / "tm-job-set-secret"
FIXTURE_MANIFEST = Path(__file__).resolve().parent / "fixtures" / "manifest.json"
RUNNER = Path(__file__).resolve().parent / "fixtures" / "run_job.py"
VALUE = "tb-placeholder-0001"
NODE_RED_ENV = "A=1\nTM_THINGSBOARD_ACCESS_TOKEN=\nB=2\n"
PLATE_RECOGNIZER_ENV = "TOKEN=\nLICENSE_KEY=\nWORKERS=2\n"


def me():
    return pwd.getpwuid(os.getuid()).pw_name


@pytest.fixture
def codedir(tmp_path):
    """A code directory with node-red-tm.env and the add-on's plate-recognizer.env, as tmsetup renders them."""
    path = tmp_path / "code"
    for service, text in [("node-red-tm", NODE_RED_ENV), ("plate-recognizer", PLATE_RECOGNIZER_ENV)]:
        (path / service).mkdir(parents=True)
        env = path / service / f"{service}.env"
        env.write_text(text)
        env.chmod(0o640)
    return path


@pytest.fixture
def manifest(tmp_path, codedir):
    """The fixture manifest, with the test's own user as the code owner and the test's code directory."""
    data = {**json.loads(FIXTURE_MANIFEST.read_text()), "codeowner": me(), "codedir": str(codedir)}
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(data))
    return path


@pytest.fixture
def jobs_dir(tmp_path):
    path = tmp_path / "jobs"
    path.mkdir()
    path.chmod(0o700)
    return path


@pytest.fixture
def secrets_dir(tmp_path):
    """The secrets directory, 0750 like the device's, with every entered secret's file empty."""
    path = tmp_path / "secrets"
    path.mkdir()
    path.chmod(0o750)
    for name in ENTERED_SECRETS:
        (path / name).write_text("")
        (path / name).chmod(0o640)
    return path


@pytest.fixture
def systemctl(tmp_path):
    """A fake systemctl that appends its argv as a JSON line to systemctl.calls and exits with systemctl.exit."""
    fake = tmp_path / "systemctl"
    fake.write_text(
        f"#!{sys.executable}\n"
        "import json, sys\n"
        f"with open({str(tmp_path / 'systemctl.calls')!r}, 'a') as file:\n"
        "    file.write(json.dumps(sys.argv[1:]) + '\\n')\n"
        "try:\n"
        f"    sys.exit(int(open({str(tmp_path / 'systemctl.exit')!r}).read()))\n"
        "except FileNotFoundError:\n"
        "    sys.exit(0)\n"
    )
    fake.chmod(0o755)
    return fake


def calls(tmp_path):
    path = tmp_path / "systemctl.calls"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def write_request(tmp_path, body):
    jobs = tmp_path / "jobs"
    jobs.mkdir(exist_ok=True)
    jobs.chmod(0o700)
    path = jobs / "set-secret.json"
    path.write_text(body if isinstance(body, str) else json.dumps(body))
    path.chmod(0o600)
    return path


def run_job(request_path, systemctl, manifest, secrets_dir):
    env = {
        "SYSTEMCTL": str(systemctl),
        "TM_CONTROL_MANIFEST": str(manifest),
        "TM_CONTROL_SECRETS_DIR": str(secrets_dir),
    }
    return subprocess.run(
        [sys.executable, "-I", str(RUNNER), str(JOB), str(request_path)],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


def node_red_env(codedir):
    return (codedir / "node-red-tm" / "node-red-tm.env").read_text()


def plate_recognizer_env(codedir):
    return (codedir / "plate-recognizer" / "plate-recognizer.env").read_text()


def assert_untouched(tmp_path, codedir, secrets_dir):
    for name in ENTERED_SECRETS:
        assert (secrets_dir / name).read_text() == ""
    assert node_red_env(codedir) == NODE_RED_ENV
    assert plate_recognizer_env(codedir) == PLATE_RECOGNIZER_ENV
    assert calls(tmp_path) == []
    assert sorted(path.name for path in secrets_dir.iterdir()) == sorted(ENTERED_SECRETS)  # no temporary file left


def test_the_job_is_executable():
    assert os.access(JOB, os.X_OK)


def test_sets_the_secret_rewrites_the_env_line_and_restarts(tmp_path, codedir, manifest, secrets_dir, systemctl):
    request = write_request(tmp_path, {"name": "thingsboard_access_token", "value": VALUE})
    result = run_job(request, systemctl, manifest, secrets_dir)
    assert result.returncode == 0, result.stdout + result.stderr
    secret = secrets_dir / "thingsboard_access_token"
    assert secret.read_text() == VALUE + "\n"
    assert stat.S_IMODE(secret.stat().st_mode) == 0o640
    env = codedir / "node-red-tm" / "node-red-tm.env"
    assert env.read_text() == "A=1\nTM_THINGSBOARD_ACCESS_TOKEN=tb-placeholder-0001\nB=2\n"
    assert stat.S_IMODE(env.stat().st_mode) == 0o640
    assert calls(tmp_path) == [["restart", "node-red-tm.service"]]
    assert result.stdout.splitlines() == [
        "set secret thingsboard_access_token",
        "updated node-red-tm.env",
        "restarted node-red-tm.service",
    ]
    assert VALUE not in result.stdout + result.stderr
    assert not request.exists()
    assert sorted(path.name for path in secrets_dir.iterdir()) == sorted(ENTERED_SECRETS)
    assert sorted(path.name for path in env.parent.iterdir()) == ["node-red-tm.env"]


def test_a_secret_with_two_env_files_updates_both_and_restarts_both(
    tmp_path, codedir, manifest, secrets_dir, systemctl
):
    value = "pr-placeholder-0002"
    request = write_request(tmp_path, {"name": "plate_recognizer_token", "value": value})
    result = run_job(request, systemctl, manifest, secrets_dir)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (secrets_dir / "plate_recognizer_token").read_text() == value + "\n"
    assert plate_recognizer_env(codedir) == f"TOKEN={value}\nLICENSE_KEY=\nWORKERS=2\n"
    assert node_red_env(codedir) == NODE_RED_ENV + f"TM_PLATE_RECOGNIZER_TOKEN={value}\n"
    assert calls(tmp_path) == [["restart", "plate-recognizer.service"], ["restart", "node-red-tm.service"]]
    assert "updated plate-recognizer.env" in result.stdout and "updated node-red-tm.env" in result.stdout
    assert value not in result.stdout + result.stderr


def test_an_empty_value_removes_the_secret(tmp_path, codedir, manifest, secrets_dir, systemctl):
    (secrets_dir / "thingsboard_access_token").write_text(VALUE + "\n")
    env = codedir / "node-red-tm" / "node-red-tm.env"
    env.write_text(f"A=1\nTM_THINGSBOARD_ACCESS_TOKEN={VALUE}\nB=2\n")
    request = write_request(tmp_path, {"name": "thingsboard_access_token", "value": ""})
    result = run_job(request, systemctl, manifest, secrets_dir)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (secrets_dir / "thingsboard_access_token").read_text() == ""
    assert env.read_text() == NODE_RED_ENV
    assert "removed secret thingsboard_access_token" in result.stdout
    assert calls(tmp_path) == [["restart", "node-red-tm.service"]]


def test_the_frigate_plus_key_rewrites_frigate_env_and_restarts_frigate_only(
    tmp_path, codedir, manifest, secrets_dir, systemctl
):
    (codedir / "frigate").mkdir()
    env = codedir / "frigate" / "frigate.env"
    text = "FRIGATE_GO2RTC_RTSP_USER=frigate\nPLUS_API_KEY=\nTZ=UTC\n"
    env.write_text(text)
    env.chmod(0o640)
    request = write_request(tmp_path, {"name": "frigate_plus_api_key", "value": PLACEHOLDER_KEY})
    result = run_job(request, systemctl, manifest, secrets_dir)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (secrets_dir / "frigate_plus_api_key").read_text() == PLACEHOLDER_KEY + "\n"
    assert env.read_text() == text.replace("PLUS_API_KEY=\n", f"PLUS_API_KEY={PLACEHOLDER_KEY}\n")
    assert stat.S_IMODE(env.stat().st_mode) == 0o640
    assert node_red_env(codedir) == NODE_RED_ENV and plate_recognizer_env(codedir) == PLATE_RECOGNIZER_ENV
    assert calls(tmp_path) == [["restart", "frigate.service"]]
    assert result.stdout.splitlines() == [
        "set secret frigate_plus_api_key",
        "updated frigate.env",
        "restarted frigate.service",
    ]
    assert PLACEHOLDER_KEY not in result.stdout + result.stderr


def test_a_missing_env_line_is_appended(tmp_path, codedir, manifest, secrets_dir, systemctl):
    env = codedir / "node-red-tm" / "node-red-tm.env"
    env.write_text("A=1")
    request = write_request(tmp_path, {"name": "thingsboard_access_token", "value": VALUE})
    result = run_job(request, systemctl, manifest, secrets_dir)
    assert result.returncode == 0, result.stdout + result.stderr
    assert env.read_text() == "A=1\nTM_THINGSBOARD_ACCESS_TOKEN=tb-placeholder-0001\n"


def test_every_env_line_of_the_key_changes_and_every_other_byte_is_kept(
    tmp_path, codedir, manifest, secrets_dir, systemctl
):
    """podman's env file takes the last of duplicate keys, so every KEY= line gets the value, where it stands."""
    env = codedir / "node-red-tm" / "node-red-tm.env"
    text = (
        b"# TM_THINGSBOARD_ACCESS_TOKEN=x\r\nX_TM_THINGSBOARD_ACCESS_TOKEN=y\n"
        b"TM_THINGSBOARD_ACCESS_TOKEN=old\r\nTM_THINGSBOARD_ACCESS_TOKEN=2nd\n\xff\n"
    )
    env.write_bytes(text)
    request = write_request(tmp_path, {"name": "thingsboard_access_token", "value": VALUE})
    assert run_job(request, systemctl, manifest, secrets_dir).returncode == 0
    expected = (
        b"# TM_THINGSBOARD_ACCESS_TOKEN=x\r\nX_TM_THINGSBOARD_ACCESS_TOKEN=y\n"
        b"TM_THINGSBOARD_ACCESS_TOKEN=tb-placeholder-0001\r\nTM_THINGSBOARD_ACCESS_TOKEN=tb-placeholder-0001\n\xff\n"
    )
    assert env.read_bytes() == expected


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("thingsboard_access_token", v)
        for v in ["a b", "a/b", "a?b", "a#b", "a=b", 'a"b', "é", "x" * 257, "a\nb", "\x00"]
    ]
    + [("plate_recognizer_token", v) for v in ["a b", "é", "x" * 257, "a\nb", "\x00"]],
)
def test_refuses_values_the_env_line_or_url_cannot_carry(
    tmp_path, codedir, manifest, secrets_dir, systemctl, name, value
):
    request = write_request(tmp_path, {"name": name, "value": value})
    result = run_job(request, systemctl, manifest, secrets_dir)
    assert result.returncode == 1
    assert result.stdout.startswith("refused: ")
    assert_untouched(tmp_path, codedir, secrets_dir)
    assert not request.exists()
    if len(value) > 1:
        assert value not in result.stdout + result.stderr


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("thingsboard_access_token", ("Az09._~-" * 32)),
        ("plate_recognizer_token", ("!~\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}" * 8)[:256]),
        ("plate_recognizer_license_key", (r"\1\n\g<0>" + "x" * 256)[:256]),  # what a re template would expand
    ],
)
def test_accepts_a_value_of_256_characters(tmp_path, codedir, manifest, secrets_dir, systemctl, name, value):
    assert len(value) == 256
    request = write_request(tmp_path, {"name": name, "value": value})
    result = run_job(request, systemctl, manifest, secrets_dir)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (secrets_dir / name).read_text() == value + "\n"
    assert f"={value}\n" in node_red_env(codedir) + plate_recognizer_env(codedir)  # a backslash stays one
    assert value not in result.stdout + result.stderr


def test_plate_recognizer_values_may_hold_url_characters(tmp_path, codedir, manifest, secrets_dir, systemctl):
    value = "a/b?c=d#e"
    request = write_request(tmp_path, {"name": "plate_recognizer_license_key", "value": value})
    result = run_job(request, systemctl, manifest, secrets_dir)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (secrets_dir / "plate_recognizer_license_key").read_text() == value + "\n"
    assert plate_recognizer_env(codedir) == f"TOKEN=\nLICENSE_KEY={value}\nWORKERS=2\n"
    assert calls(tmp_path) == [["restart", "plate-recognizer.service"]]


@pytest.mark.parametrize(
    "request_body",
    [
        {"name": "session_key", "value": VALUE},
        {"name": "../x", "value": VALUE},
        {"name": "thingsboard_access_token"},
        {"name": "thingsboard_access_token", "value": 1},
        {"name": "thingsboard_access_token", "value": VALUE, "extra": 1},
        ["x"],
        "not json",
        "",
    ],
)
def test_refuses_bad_requests_and_deletes_them(tmp_path, codedir, manifest, secrets_dir, systemctl, request_body):
    request = write_request(tmp_path, request_body)
    result = run_job(request, systemctl, manifest, secrets_dir)
    assert result.returncode == 1
    assert result.stdout.startswith("refused: ")
    assert_untouched(tmp_path, codedir, secrets_dir)
    assert not request.exists()
    assert VALUE not in result.stdout + result.stderr
    assert not (tmp_path / "x").exists()


def test_refuses_an_oversized_request(tmp_path, codedir, manifest, secrets_dir, systemctl):
    request = write_request(tmp_path, {"name": "thingsboard_access_token", "value": VALUE, "pad": "x" * 5000})
    result = run_job(request, systemctl, manifest, secrets_dir)
    assert result.returncode == 1 and not request.exists()
    assert_untouched(tmp_path, codedir, secrets_dir)


def test_a_failed_restart_is_reported_after_the_secret_is_written(
    tmp_path, codedir, manifest, secrets_dir, systemctl
):
    (tmp_path / "systemctl.exit").write_text("1")
    request = write_request(tmp_path, {"name": "thingsboard_access_token", "value": VALUE})
    result = run_job(request, systemctl, manifest, secrets_dir)
    assert result.returncode == 1
    assert (secrets_dir / "thingsboard_access_token").read_text() == VALUE + "\n"
    assert node_red_env(codedir) == f"A=1\nTM_THINGSBOARD_ACCESS_TOKEN={VALUE}\nB=2\n"
    assert "failed: restart of node-red-tm.service exited 1; the secret is written" in result.stdout.splitlines()
    assert "restarted" not in result.stdout
    assert not request.exists()
    assert VALUE not in result.stdout + result.stderr


def test_a_failed_restart_still_restarts_the_other_units(tmp_path, codedir, manifest, secrets_dir, systemctl):
    (tmp_path / "systemctl.exit").write_text("5")
    request = write_request(tmp_path, {"name": "plate_recognizer_token", "value": "pr-placeholder-0003"})
    result = run_job(request, systemctl, manifest, secrets_dir)
    assert result.returncode == 1
    assert calls(tmp_path) == [["restart", "plate-recognizer.service"], ["restart", "node-red-tm.service"]]
    lines = result.stdout.splitlines()
    assert "failed: restart of plate-recognizer.service exited 5; the secret is written" in lines
    assert "failed: restart of node-red-tm.service exited 5; the secret is written" in lines


def test_refuses_a_secret_whose_env_file_is_missing(tmp_path, codedir, manifest, secrets_dir, systemctl):
    (codedir / "plate-recognizer" / "plate-recognizer.env").unlink()
    request = write_request(tmp_path, {"name": "plate_recognizer_token", "value": "pr-placeholder-0004"})
    result = run_job(request, systemctl, manifest, secrets_dir)
    assert result.returncode == 1
    assert result.stdout.startswith("refused: ") and "isn't installed" in result.stdout
    assert (secrets_dir / "plate_recognizer_token").read_text() == ""
    assert node_red_env(codedir) == NODE_RED_ENV
    assert calls(tmp_path) == [] and not request.exists()


def test_refuses_a_symlinked_env_file_and_leaves_its_target(tmp_path, codedir, manifest, secrets_dir, systemctl):
    target = tmp_path / "elsewhere.env"
    target.write_text(PLATE_RECOGNIZER_ENV)
    env = codedir / "plate-recognizer" / "plate-recognizer.env"
    env.unlink()
    env.symlink_to(target)
    request = write_request(tmp_path, {"name": "plate_recognizer_token", "value": "pr-placeholder-0005"})
    result = run_job(request, systemctl, manifest, secrets_dir)
    assert result.returncode == 1 and result.stdout.startswith("refused: ")
    assert target.read_text() == PLATE_RECOGNIZER_ENV and env.is_symlink()
    assert (secrets_dir / "plate_recognizer_token").read_text() == ""
    assert node_red_env(codedir) == NODE_RED_ENV
    assert calls(tmp_path) == [] and not request.exists()


def test_refuses_an_env_file_reached_through_a_symlinked_directory(
    tmp_path, codedir, manifest, secrets_dir, systemctl
):
    real = tmp_path / "real-node-red-tm"
    (codedir / "node-red-tm").rename(real)
    (codedir / "node-red-tm").symlink_to(real)
    request = write_request(tmp_path, {"name": "thingsboard_access_token", "value": VALUE})
    result = run_job(request, systemctl, manifest, secrets_dir)
    assert result.returncode == 1 and result.stdout.startswith("refused: ")
    assert (real / "node-red-tm.env").read_text() == NODE_RED_ENV
    assert (secrets_dir / "thingsboard_access_token").read_text() == ""
    assert calls(tmp_path) == []


def test_follows_a_code_directory_that_is_a_link_to_the_code_owners_directory(
    tmp_path, codedir, secrets_dir, systemctl
):
    """A code directory moved to other storage and linked back: its parent is root's, so only root can swap the link."""
    link = tmp_path / "linked-code"
    link.symlink_to(codedir)
    data = {**json.loads(FIXTURE_MANIFEST.read_text()), "codeowner": me(), "codedir": str(link)}
    manifest = tmp_path / "linked-manifest.json"
    manifest.write_text(json.dumps(data))
    request = write_request(tmp_path, {"name": "thingsboard_access_token", "value": VALUE})
    result = run_job(request, systemctl, manifest, secrets_dir)
    assert result.returncode == 0, result.stdout + result.stderr
    assert node_red_env(codedir) == f"A=1\nTM_THINGSBOARD_ACCESS_TOKEN={VALUE}\nB=2\n"


def test_refuses_a_code_directory_the_code_owner_does_not_own(monkeypatch, codedir):
    # The jobs directory must be the code owner's too, so a whole run can't name another owner: test the walk alone.
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    job = load_job_module()
    other = os.getuid() + 1
    with pytest.raises(job.Refused, match="the code directory isn't the code owner's"):
        job.check_env_files(str(codedir), other, [("node-red-tm/node-red-tm.env", "TM_THINGSBOARD_ACCESS_TOKEN")])
    with pytest.raises(job.Refused, match="the code directory isn't the code owner's"):
        job.set_env_line(str(codedir), other, "node-red-tm/node-red-tm.env", "TM_THINGSBOARD_ACCESS_TOKEN", VALUE)
    assert node_red_env(codedir) == NODE_RED_ENV
    job.check_env_files(str(codedir), os.getuid(), [("node-red-tm/node-red-tm.env", "TM_THINGSBOARD_ACCESS_TOKEN")])


def test_refuses_a_hardlinked_env_file(tmp_path, codedir, manifest, secrets_dir, systemctl):
    env = codedir / "node-red-tm" / "node-red-tm.env"
    other = tmp_path / "other.env"
    os.link(env, other)
    request = write_request(tmp_path, {"name": "thingsboard_access_token", "value": VALUE})
    result = run_job(request, systemctl, manifest, secrets_dir)
    assert result.returncode == 1 and result.stdout.startswith("refused: ")
    assert other.read_text() == NODE_RED_ENV and env.read_text() == NODE_RED_ENV
    assert (secrets_dir / "thingsboard_access_token").read_text() == ""


def test_refuses_an_env_file_that_is_not_a_regular_file(tmp_path, codedir, manifest, secrets_dir, systemctl):
    env = codedir / "node-red-tm" / "node-red-tm.env"
    env.unlink()
    os.mkfifo(env)
    request = write_request(tmp_path, {"name": "thingsboard_access_token", "value": VALUE})
    result = run_job(request, systemctl, manifest, secrets_dir)  # must not block waiting for a writer
    assert result.returncode == 1 and result.stdout.startswith("refused: ")
    assert (secrets_dir / "thingsboard_access_token").read_text() == ""


def test_refuses_a_group_writable_secrets_dir(tmp_path, codedir, manifest, secrets_dir, systemctl):
    secrets_dir.chmod(0o770)
    request = write_request(tmp_path, {"name": "thingsboard_access_token", "value": VALUE})
    result = run_job(request, systemctl, manifest, secrets_dir)
    assert result.returncode == 1 and result.stdout.startswith("refused: ")
    assert_untouched(tmp_path, codedir, secrets_dir)
    assert not request.exists()


def test_refuses_a_secrets_dir_reached_through_a_symlink(tmp_path, codedir, manifest, secrets_dir, systemctl):
    link = tmp_path / "linked-secrets"
    link.symlink_to(secrets_dir)
    request = write_request(tmp_path, {"name": "thingsboard_access_token", "value": VALUE})
    result = run_job(request, systemctl, manifest, link)
    assert result.returncode == 1 and result.stdout.startswith("refused: ")
    assert_untouched(tmp_path, codedir, secrets_dir)


def test_keeps_the_env_files_owner_and_mode(tmp_path, codedir, manifest, secrets_dir, systemctl):
    env = codedir / "node-red-tm" / "node-red-tm.env"
    env.chmod(0o600)
    before = env.stat()
    request = write_request(tmp_path, {"name": "thingsboard_access_token", "value": VALUE})
    assert run_job(request, systemctl, manifest, secrets_dir).returncode == 0
    after = env.stat()
    assert (stat.S_IMODE(after.st_mode), after.st_uid, after.st_gid) == (0o600, before.st_uid, before.st_gid)
    assert after.st_ino != before.st_ino  # replaced, not written in place


def test_a_missing_manifest_leaves_the_request(tmp_path, codedir, secrets_dir, systemctl):
    # Without the manifest the jobs directory's owner can't be checked, so the request is left for tm-control to clear.
    request = write_request(tmp_path, {"name": "thingsboard_access_token", "value": VALUE})
    result = run_job(request, systemctl, tmp_path / "no-manifest.json", secrets_dir)
    assert result.returncode == 1 and result.stdout.startswith("refused: ")
    assert_untouched(tmp_path, codedir, secrets_dir)
    assert request.exists()


def test_refuses_a_symlink_and_leaves_its_target(tmp_path, codedir, manifest, secrets_dir, systemctl, jobs_dir):
    target = tmp_path / "elsewhere.json"
    target.write_text(json.dumps({"name": "thingsboard_access_token", "value": VALUE}))
    link = jobs_dir / "set-secret.json"
    link.symlink_to(target)
    result = run_job(link, systemctl, manifest, secrets_dir)
    assert result.returncode == 1
    assert_untouched(tmp_path, codedir, secrets_dir)
    assert not link.is_symlink() and target.exists()


def test_refuses_a_hardlinked_request(tmp_path, codedir, manifest, secrets_dir, systemctl):
    request = write_request(tmp_path, {"name": "thingsboard_access_token", "value": VALUE})
    other = tmp_path / "other-name.json"
    os.link(request, other)
    result = run_job(request, systemctl, manifest, secrets_dir)
    assert result.returncode == 1
    assert_untouched(tmp_path, codedir, secrets_dir)
    assert not request.exists() and other.exists()  # only the request's own name is deleted


def test_refuses_a_jobs_directory_reached_through_a_symlink(tmp_path, codedir, manifest, secrets_dir, systemctl):
    request = write_request(tmp_path, {"name": "thingsboard_access_token", "value": VALUE})
    link = tmp_path / "linked-jobs"
    link.symlink_to(request.parent)
    result = run_job(link / request.name, systemctl, manifest, secrets_dir)
    assert result.returncode == 1
    assert_untouched(tmp_path, codedir, secrets_dir)
    assert request.exists()  # an untrusted directory: nothing in it is touched


def load_job_module():
    loader = importlib.machinery.SourceFileLoader("tm_job_set_secret", str(JOB))
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    loader.exec_module(module)
    return module


def test_root_ignores_systemctl_from_the_environment(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "dont_write_bytecode", True)  # no __pycache__ beside the job, which tmsetup installs
    job = load_job_module()
    planted = str(tmp_path / "planted-systemctl")
    monkeypatch.setenv("SYSTEMCTL", planted)
    monkeypatch.setattr(job.os, "geteuid", lambda: 0)
    assert job.systemctl_binary() == "/usr/bin/systemctl"
    monkeypatch.setattr(job.os, "geteuid", lambda: 1000)
    assert job.systemctl_binary() == planted


def test_the_table_matches_the_api(monkeypatch):
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    job = load_job_module()
    assert tuple(job.SECRETS) == ENTERED_SECRETS
    for name, secret in job.SECRETS.items():
        assert secret["pattern"] == VALUE_PATTERNS[name], name


def test_the_restart_lists_match_the_api(monkeypatch):
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    job = load_job_module()
    assert tuple(job.SECRETS) == tuple(ENTERED)
    for name, secret in job.SECRETS.items():
        assert tuple(secret["restart"]) == ENTERED[name].restarts, name
