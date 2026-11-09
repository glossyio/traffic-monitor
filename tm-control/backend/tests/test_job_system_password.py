"""The system-password root job, run as a script against a fake chpasswd that records its input.

fixtures/run_job.py runs it with stand-in accounts (pi is uid 1000 unless a test says otherwise) and a non-root euid,
so the fake chpasswd is used even when the suite runs as root.
"""

import importlib.machinery
import importlib.util
import json
import os
import pwd
import subprocess
import sys
from pathlib import Path

import pytest

JOB = Path(__file__).resolve().parents[2] / "jobs" / "tm-job-system-password"
FIXTURE_MANIFEST = Path(__file__).resolve().parent / "fixtures" / "manifest.json"
RUNNER = Path(__file__).resolve().parent / "fixtures" / "run_job.py"
ACCOUNTS = {"pi": 1000}
PASSWORD = "correct horse 1"


def me():
    return pwd.getpwuid(os.getuid()).pw_name


def write_manifest(tmp_path, **changes):
    data = {**json.loads(FIXTURE_MANIFEST.read_text()), **changes}
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(data))
    return path


@pytest.fixture
def manifest(tmp_path):
    """The fixture manifest, with the test's own user as the code owner, who owns tm-control's runtime directory."""
    return write_manifest(tmp_path, codeowner=me())


@pytest.fixture
def jobs_dir(tmp_path):
    path = tmp_path / "jobs"
    path.mkdir()
    path.chmod(0o700)
    return path


@pytest.fixture
def chpasswd(tmp_path):
    """A fake chpasswd that writes its stdin to chpasswd.stdin and exits with the code in chpasswd.exit, if any."""
    fake = tmp_path / "chpasswd"
    fake.write_text(
        "#!/bin/sh\n"
        f"/bin/cat > '{tmp_path}/chpasswd.stdin'\n"
        f"[ -f '{tmp_path}/chpasswd.exit' ] && exit \"$(/bin/cat '{tmp_path}/chpasswd.exit')\"\n"
        "exit 0\n"
    )
    fake.chmod(0o755)
    return fake


def recorded(tmp_path):
    path = tmp_path / "chpasswd.stdin"
    return path.read_text() if path.exists() else None


def write_request(tmp_path, body):
    jobs = tmp_path / "jobs"
    jobs.mkdir(exist_ok=True)
    jobs.chmod(0o700)
    path = jobs / "system-password.json"
    path.write_text(body if isinstance(body, str) else json.dumps(body))
    path.chmod(0o600)
    return path


def run_job(request_path, chpasswd, manifest, accounts=ACCOUNTS):
    env = {"CHPASSWD": str(chpasswd), "TM_CONTROL_MANIFEST": str(manifest), "TEST_ACCOUNTS": json.dumps(accounts)}
    return subprocess.run(
        [sys.executable, "-I", str(RUNNER), str(JOB), str(request_path)],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_the_job_is_executable():
    assert os.access(JOB, os.X_OK)


def test_sets_the_password_for_the_installing_user(tmp_path, chpasswd, manifest):
    request = write_request(tmp_path, {"username": "pi", "password": PASSWORD})
    result = run_job(request, chpasswd, manifest)
    assert result.returncode == 0, result.stdout + result.stderr
    assert recorded(tmp_path) == f"pi:{PASSWORD}\n"
    assert not request.exists()
    assert "password set for pi" in result.stdout
    assert PASSWORD not in result.stdout + result.stderr


@pytest.mark.parametrize(
    "request_body",
    [
        {"username": "root", "password": "x" * 12},
        {"username": "pi", "password": "short"},
        {"username": "pi", "password": "x" * 257},
        {"username": "pi", "password": "x" * 12, "extra": 1},
        {"username": "pi"},
        {"username": "pi", "password": 1234567890123},
        {"username": "pi", "password": "a\nb" + "x" * 10},
        {"username": "pi", "password": "a\rb" + "x" * 10},
        {"username": "pi", "password": "a\x00b" + "x" * 10},
        {"username": "pi", "password": "\ud800" + "x" * 12},
        ["pi", "x" * 12],
        "not json",
        "",
    ],
)
def test_refuses_bad_requests_and_deletes_them(tmp_path, chpasswd, manifest, request_body):
    request = write_request(tmp_path, request_body)
    result = run_job(request, chpasswd, manifest)
    assert result.returncode == 1
    assert recorded(tmp_path) is None
    assert not request.exists()
    assert result.stdout.strip()  # a reason
    password = request_body.get("password") if isinstance(request_body, dict) else None
    if isinstance(password, str):
        assert "x" * 10 not in result.stdout + result.stderr
        if password.isprintable():
            assert password not in result.stdout + result.stderr


def test_refuses_an_oversized_request(tmp_path, chpasswd, manifest):
    request = write_request(tmp_path, {"username": "pi", "password": PASSWORD, "pad": "x" * 5000})
    result = run_job(request, chpasswd, manifest)
    assert result.returncode == 1 and recorded(tmp_path) is None and not request.exists()


def test_refuses_a_symlink_and_leaves_its_target(tmp_path, chpasswd, manifest, jobs_dir):
    target = tmp_path / "elsewhere.json"
    target.write_text(json.dumps({"username": "pi", "password": PASSWORD}))
    link = jobs_dir / "system-password.json"
    link.symlink_to(target)
    result = run_job(link, chpasswd, manifest)
    assert result.returncode == 1 and recorded(tmp_path) is None
    assert not link.is_symlink() and target.exists()


def test_refuses_a_request_that_is_not_a_regular_file(tmp_path, chpasswd, manifest, jobs_dir):
    fifo = jobs_dir / "system-password.json"
    os.mkfifo(fifo)
    result = run_job(fifo, chpasswd, manifest)  # must not block waiting for a writer
    assert result.returncode == 1 and recorded(tmp_path) is None and not fifo.exists()


def test_refuses_a_request_that_is_a_directory(tmp_path, chpasswd, manifest, jobs_dir):
    directory = jobs_dir / "system-password.json"
    directory.mkdir()
    result = run_job(directory, chpasswd, manifest)
    assert result.returncode == 1 and recorded(tmp_path) is None and "password set" not in result.stdout


def test_refuses_a_hardlinked_request(tmp_path, chpasswd, manifest):
    request = write_request(tmp_path, {"username": "pi", "password": PASSWORD})
    other = tmp_path / "other-name.json"
    os.link(request, other)
    result = run_job(request, chpasswd, manifest)
    assert result.returncode == 1 and recorded(tmp_path) is None
    assert not request.exists() and other.exists()  # only the request's own name is deleted


def test_refuses_a_jobs_directory_reached_through_a_symlink(tmp_path, chpasswd, manifest):
    request = write_request(tmp_path, {"username": "pi", "password": PASSWORD})
    link = tmp_path / "linked-jobs"
    link.symlink_to(request.parent)
    result = run_job(link / request.name, chpasswd, manifest)
    assert result.returncode == 1 and recorded(tmp_path) is None
    assert request.exists()  # an untrusted directory: nothing in it is touched


def test_refuses_a_group_writable_jobs_directory(tmp_path, chpasswd, manifest):
    request = write_request(tmp_path, {"username": "pi", "password": PASSWORD})
    request.parent.chmod(0o770)
    result = run_job(request, chpasswd, manifest)
    assert result.returncode == 1 and recorded(tmp_path) is None and request.exists()


def test_refuses_a_jobs_directory_with_another_owner(tmp_path, chpasswd):
    other = "root" if os.getuid() != 0 else "nobody"
    request = write_request(tmp_path, {"username": "pi", "password": PASSWORD})
    result = run_job(request, chpasswd, write_manifest(tmp_path, codeowner=other))
    assert result.returncode == 1 and recorded(tmp_path) is None and request.exists()


def test_refuses_an_installing_user_that_is_not_a_plain_username(tmp_path, chpasswd):
    request = write_request(tmp_path, {"username": "pi:0", "password": PASSWORD})
    result = run_job(request, chpasswd, write_manifest(tmp_path, codeowner=me(), installing_user="pi:0"))
    assert result.returncode == 1 and recorded(tmp_path) is None


@pytest.mark.parametrize(
    ("user", "accounts"),
    [
        ("root", ACCOUNTS),  # an install run as root
        ("toor", {**ACCOUNTS, "toor": 0}),  # root under another name
    ],
)
def test_refuses_a_root_account_even_as_the_installing_user(tmp_path, chpasswd, user, accounts):
    request = write_request(tmp_path, {"username": user, "password": PASSWORD})
    result = run_job(request, chpasswd, write_manifest(tmp_path, codeowner=me(), installing_user=user), accounts)
    assert result.returncode == 1 and recorded(tmp_path) is None and not request.exists()
    assert f"refused: {user} is a root account (uid 0)" in result.stdout
    assert "password set" not in result.stdout and PASSWORD not in result.stdout + result.stderr


def test_refuses_an_installing_user_with_no_account(tmp_path, chpasswd):
    request = write_request(tmp_path, {"username": "nosuchuser", "password": PASSWORD})
    manifest = write_manifest(tmp_path, codeowner=me(), installing_user="nosuchuser")
    result = run_job(request, chpasswd, manifest, accounts={})
    assert result.returncode == 1 and recorded(tmp_path) is None and not request.exists()
    assert "refused: there is no account nosuchuser on this device" in result.stdout
    assert PASSWORD not in result.stdout + result.stderr


def test_missing_request_is_an_error(tmp_path, chpasswd, manifest, jobs_dir):
    result = run_job(jobs_dir / "system-password.json", chpasswd, manifest)
    assert result.returncode == 1 and recorded(tmp_path) is None
    assert result.stdout.strip()


def test_a_missing_manifest_is_an_error(tmp_path, chpasswd):
    request = write_request(tmp_path, {"username": "pi", "password": PASSWORD})
    result = run_job(request, chpasswd, tmp_path / "no-manifest.json")
    # Without the manifest the directory's owner can't be checked, so the request is left for tm-control to clear.
    assert result.returncode == 1 and recorded(tmp_path) is None


def test_a_chpasswd_failure_is_reported(tmp_path, chpasswd, manifest):
    (tmp_path / "chpasswd.exit").write_text("3")
    request = write_request(tmp_path, {"username": "pi", "password": PASSWORD})
    result = run_job(request, chpasswd, manifest)
    assert result.returncode == 1 and not request.exists()
    assert "password set" not in result.stdout and PASSWORD not in result.stdout + result.stderr


def load_job_module():
    loader = importlib.machinery.SourceFileLoader("tm_job_system_password", str(JOB))
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    loader.exec_module(module)
    return module


def test_root_ignores_chpasswd_from_the_environment(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "dont_write_bytecode", True)  # no __pycache__ beside the job, which tmsetup installs
    job = load_job_module()
    planted = str(tmp_path / "planted-chpasswd")
    monkeypatch.setenv("CHPASSWD", planted)
    monkeypatch.setattr(job.os, "geteuid", lambda: 0)
    assert job.chpasswd_binary() == "/usr/sbin/chpasswd"
    monkeypatch.setattr(job.os, "geteuid", lambda: 1000)
    assert job.chpasswd_binary() == planted
