"""The system-password root job, run as a script against a fake chpasswd that records its input."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

JOB = Path(__file__).resolve().parents[2] / "jobs" / "tm-job-system-password"
MANIFEST = Path(__file__).resolve().parent / "fixtures" / "manifest.json"
PASSWORD = "correct horse 1"


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
    path = tmp_path / "system-password.json"
    path.write_text(body if isinstance(body, str) else json.dumps(body))
    path.chmod(0o600)
    return path


def run_job(request_path, chpasswd, manifest=MANIFEST):
    env = {"CHPASSWD": str(chpasswd), "TM_CONTROL_MANIFEST": str(manifest)}
    return subprocess.run(
        [sys.executable, "-I", str(JOB), str(request_path)], env=env, capture_output=True, text=True, timeout=30
    )


def test_the_job_is_executable():
    assert os.access(JOB, os.X_OK)


def test_sets_the_password_for_the_installing_user(tmp_path, chpasswd):
    request = write_request(tmp_path, {"username": "pi", "password": PASSWORD})
    result = run_job(request, chpasswd)
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
        ["pi", "x" * 12],
        "not json",
        "",
    ],
)
def test_refuses_bad_requests_and_deletes_them(tmp_path, chpasswd, request_body):
    request = write_request(tmp_path, request_body)
    result = run_job(request, chpasswd)
    assert result.returncode == 1
    assert recorded(tmp_path) is None
    assert not request.exists()
    assert result.stdout.strip()  # a reason
    password = request_body.get("password") if isinstance(request_body, dict) else None
    if isinstance(password, str):
        assert password not in result.stdout + result.stderr
        assert "x" * 10 not in result.stdout + result.stderr


def test_refuses_an_oversized_request(tmp_path, chpasswd):
    request = write_request(tmp_path, {"username": "pi", "password": PASSWORD, "pad": "x" * 5000})
    result = run_job(request, chpasswd)
    assert result.returncode == 1 and recorded(tmp_path) is None and not request.exists()


def test_refuses_a_symlink_and_leaves_its_target(tmp_path, chpasswd):
    target = tmp_path / "elsewhere.json"
    target.write_text(json.dumps({"username": "pi", "password": PASSWORD}))
    link = tmp_path / "system-password.json"
    link.symlink_to(target)
    result = run_job(link, chpasswd)
    assert result.returncode == 1 and recorded(tmp_path) is None
    assert not link.is_symlink() and target.exists()


def test_refuses_a_request_that_is_not_a_regular_file(tmp_path, chpasswd):
    fifo = tmp_path / "system-password.json"
    os.mkfifo(fifo)
    result = run_job(fifo, chpasswd)  # must not block waiting for a writer
    assert result.returncode == 1 and recorded(tmp_path) is None and not fifo.exists()


def test_missing_request_is_an_error(tmp_path, chpasswd):
    result = run_job(tmp_path / "system-password.json", chpasswd)
    assert result.returncode == 1 and recorded(tmp_path) is None
    assert result.stdout.strip()


def test_a_missing_manifest_is_an_error(tmp_path, chpasswd):
    request = write_request(tmp_path, {"username": "pi", "password": PASSWORD})
    result = run_job(request, chpasswd, manifest=tmp_path / "no-manifest.json")
    assert result.returncode == 1 and recorded(tmp_path) is None and not request.exists()


def test_a_chpasswd_failure_is_reported(tmp_path, chpasswd):
    (tmp_path / "chpasswd.exit").write_text("3")
    request = write_request(tmp_path, {"username": "pi", "password": PASSWORD})
    result = run_job(request, chpasswd)
    assert result.returncode == 1 and not request.exists()
    assert "password set" not in result.stdout and PASSWORD not in result.stdout + result.stderr
