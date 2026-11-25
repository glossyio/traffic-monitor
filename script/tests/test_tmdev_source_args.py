"""tmdev.py's source_args(): the commit and branch an on-Pi deploy hands the installer for the tree it copied."""

import importlib.util
import re
import subprocess
import sys
from pathlib import Path

import pytest
from required_tools import needs

DEVPI = Path(__file__).resolve().parents[1] / "devpi"
sys.path.insert(0, str(DEVPI))  # for tmdev's own `import devlog`
_spec = importlib.util.spec_from_file_location("tmdev_under_test", DEVPI / "tmdev.py")
tmdev = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tmdev)

pytestmark = needs("git")


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                           *args], check=True, capture_output=True, text=True).stdout.strip()


def head(repo):
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path):
    path = tmp_path / "repo"
    path.mkdir()
    git(path, "init", "-q")
    git(path, "commit", "-q", "--allow-empty", "-m", "start")
    return path


def test_a_checkout_gives_its_commit_and_branch(repo):
    git(repo, "checkout", "-q", "-b", "feature/x/1")
    assert re.fullmatch(r"[0-9a-f]{40}", head(repo))
    assert tmdev.source_args(repo) == ["-a", f"e tmsetup_source_commit={head(repo)}",
                                       "-a", "e tmsetup_source_branch=feature/x/1"]


@pytest.mark.parametrize("branch", ["x;y", "a$b", "x'y"])
def test_a_branch_with_other_characters_is_left_out(repo, branch):
    git(repo, "checkout", "-q", "-b", branch)
    assert tmdev.source_args(repo) == ["-a", f"e tmsetup_source_commit={head(repo)}"]


def test_a_folder_that_is_no_checkout_gives_nothing(tmp_path):
    assert tmdev.source_args(tmp_path) == []
