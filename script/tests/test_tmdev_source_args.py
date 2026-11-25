"""tmdev.py's source_args(): the commit, branch, and whether it has changes, which an on-Pi deploy hands the installer
for the tree it copied."""

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


def test_a_clean_checkout_says_nothing_about_changes(repo):
    assert not any("tmsetup_source_modified" in arg for arg in tmdev.source_args(repo))


def test_an_edited_tracked_file_is_passed_as_modified(repo):
    (repo / "a.txt").write_text("one\n")
    git(repo, "add", "a.txt")
    git(repo, "commit", "-q", "-m", "add a")
    git(repo, "checkout", "-q", "-b", "dev")
    (repo / "a.txt").write_text("two\n")
    assert tmdev.source_args(repo) == ["-a", f"e tmsetup_source_commit={head(repo)}",
                                       "-a", "e tmsetup_source_branch=dev",
                                       "-a", "e tmsetup_source_modified=true"]


def test_a_new_untracked_file_is_passed_as_modified(repo):
    git(repo, "checkout", "-q", "-b", "dev")
    (repo / "new.txt").write_text("new\n")
    assert tmdev.source_args(repo)[-2:] == ["-a", "e tmsetup_source_modified=true"]


def test_a_new_file_that_git_ignores_is_not_a_change(repo):
    (repo / ".gitignore").write_text("*.log\n")
    git(repo, "add", ".gitignore")
    git(repo, "commit", "-q", "-m", "ignore logs")
    (repo / "x.log").write_text("noise\n")
    assert not any("tmsetup_source_modified" in arg for arg in tmdev.source_args(repo))


def test_a_branch_left_out_still_leaves_modified_after_the_commit(repo):
    git(repo, "checkout", "-q", "-b", "x;y")
    (repo / "new.txt").write_text("new\n")
    assert tmdev.source_args(repo) == ["-a", f"e tmsetup_source_commit={head(repo)}",
                                       "-a", "e tmsetup_source_modified=true"]


@pytest.mark.parametrize("branch", ["x;y", "a$b", "x'y"])
def test_a_branch_with_other_characters_is_left_out(repo, branch):
    git(repo, "checkout", "-q", "-b", branch)
    assert tmdev.source_args(repo) == ["-a", f"e tmsetup_source_commit={head(repo)}"]


def test_a_folder_that_is_no_checkout_gives_nothing(tmp_path):
    assert tmdev.source_args(tmp_path) == []
