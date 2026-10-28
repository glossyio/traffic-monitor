"""tmsetup.sh itself: it refuses to run as root before it changes anything.

The root case runs directly when the suite runs as root, or as root in a user namespace (unshare) when the machine
allows that; otherwise it's skipped. -T would print the tags and exit 2, so a guard that let root through shows.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "tmsetup.sh"


def run(argv, home):
    env = {"HOME": str(home), "PATH": os.environ.get("PATH", "/usr/bin:/bin")}
    return subprocess.run(argv, env=env, capture_output=True, text=True, timeout=30, check=False)


def as_root(home):
    """tmsetup.sh -T run as uid 0, or None when this machine can't do that."""
    if os.geteuid() == 0:
        return run(["bash", str(SCRIPT), "-T"], home)
    if shutil.which("unshare") is None:
        return None
    result = run(["unshare", "--user", "--map-root-user", "bash", str(SCRIPT), "-T"], home)
    if "Valid Tags" not in result.stdout and "normal user" not in result.stdout:
        return None  # unshare itself was refused
    return result


def test_refuses_to_run_as_root_before_changing_anything(tmp_path):
    result = as_root(tmp_path)
    if result is None:
        pytest.skip("can't run as root here (not root, and no user namespaces)")
    assert result.returncode == 1, result.stdout + result.stderr
    assert "Run tmsetup.sh as your normal user (the one you log in with)" in result.stdout
    assert "Valid Tags" not in result.stdout
    assert list(tmp_path.iterdir()) == []  # no ~/.tmsetup, no log


@pytest.mark.skipif(os.geteuid() == 0, reason="runs as a normal user")
def test_a_normal_user_gets_past_the_root_check(tmp_path):
    result = run(["bash", str(SCRIPT), "-T"], tmp_path)
    assert result.returncode == 2 and "Valid Tags" in result.stdout
    assert "normal user" not in result.stdout
