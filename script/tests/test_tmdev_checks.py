"""tmdev.py's PR checks: one open check per host, so sessions on different bench units don't block or leak into each
other, and the run log's indexes appended under a lock.

Every test points TM_DEV_LOG_DIR and TM_DEV_INVENTORY at its own temporary folder and never reaches a Pi: commands
run on this machine, and the inventory and the deploy itself are stand-ins.
"""

import fcntl
import importlib.util
import json
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
from required_tools import needs

DEVPI = Path(__file__).resolve().parents[1] / "devpi"
sys.path.insert(0, str(DEVPI))  # for tmdev's own `import devlog`
_spec = importlib.util.spec_from_file_location("tmdev_checks_under_test", DEVPI / "tmdev.py")
tmdev = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tmdev)
devlog = tmdev.devlog

pytestmark = needs("git")

HOSTS = {"bench-a": {}, "bench-b": {}}


@pytest.fixture(autouse=True)
def log(tmp_path, monkeypatch):
    """A run log and an inventory of this test's own; the inventory's hosts come from a stand-in for ansible-inventory."""
    folder = tmp_path / "log"
    monkeypatch.setenv("TM_DEV_LOG_DIR", str(folder))
    inventory = tmp_path / "dev-pis.yml"
    inventory.write_text("tm_dev:\n  hosts:\n    bench-a: {}\n    bench-b: {}\n")
    monkeypatch.setenv("TM_DEV_INVENTORY", str(inventory))
    monkeypatch.setattr(devlog, "load_hosts", lambda: dict(HOSTS))
    assert devlog.log_dir() == folder.resolve()
    return folder.resolve()


@pytest.fixture
def ssh_here(monkeypatch):
    """`run <host>` runs its command with bash on this machine instead of over ssh."""
    monkeypatch.setattr(tmdev, "ssh_command", lambda name, hostvars: (["bash", "-c"], 'eval "$0"'))


@pytest.fixture
def deploys(monkeypatch):
    """Record which checkout each deploy would install, without running tmsetup.sh."""
    seen = []

    def deploy_remote(name, hostvars, src, tmsetup_args, log_file):
        seen.append((name, Path(src)))
        return 0

    monkeypatch.setattr(tmdev, "deploy_remote", deploy_remote)
    return seen


def checkout(path):
    """A git work tree with script/tmsetup.sh, which is what --src must be."""
    (path / "script").mkdir(parents=True)
    (path / "script" / "tmsetup.sh").write_text("#!/bin/bash\n")
    for args in (["init", "-q"], ["add", "."], ["commit", "-q", "-m", "start"]):
        subprocess.run(["git", "-C", str(path), "-c", "user.name=Test", "-c", "user.email=test@example.invalid", *args],
                       check=True, capture_output=True)
    return path.resolve()


@pytest.fixture
def src_a(tmp_path):
    return checkout(tmp_path / "src-a")


@pytest.fixture
def src_b(tmp_path):
    return checkout(tmp_path / "src-b")


def tm(*argv):
    return tmdev.main([str(arg) for arg in argv])


def start(host, *extra):
    assert tm("check", "start", "--host", host, "--title", f"check on {host}", *extra) == 0
    return run_dir(host)


def marker(log, host):
    return log / f"active-check-{host}"


def run_dir(host):
    folder = devlog.log_dir()
    return folder / marker(folder, host).read_text().strip()


def commands(directory):
    path = directory / "commands.log"
    return path.read_text() if path.exists() else ""


def log_rows(log):
    return [line for line in (log / "LOG.md").read_text().splitlines() if line.startswith("| 20")]


# --- several checks, one per host ----------------------------------------------------------------

def test_two_hosts_each_hold_an_open_check(log):
    a, b = start("bench-a"), start("bench-b")
    assert a != b
    assert json.loads((a / "meta.json").read_text())["host"] == "bench-a"
    assert json.loads((b / "meta.json").read_text())["host"] == "bench-b"
    assert not (log / "active-check").exists()


def test_a_second_check_on_the_same_host_is_refused(log, capsys):
    a = start("bench-a")
    assert tm("check", "start", "--host", "bench-a", "--title", "again") == 2
    assert "bench-a" in capsys.readouterr().err
    assert run_dir("bench-a") == a
    assert len(list((log / "runs").iterdir())) == 1


def test_local_is_a_host_of_its_own(log):
    start("bench-a")
    local = start("local")
    assert json.loads((local / "meta.json").read_text())["host"] == "local"


def test_run_on_a_host_logs_into_that_hosts_check(ssh_here):
    a, b = start("bench-a"), start("bench-b")
    assert tm("run", "bench-b", "--", "echo", "on-b") == 0
    assert tm("run", "bench-a", "--", "echo", "on-a") == 0
    assert "echo on-b" in commands(b) and "echo on-a" not in commands(b)
    assert "echo on-a" in commands(a) and "echo on-b" not in commands(a)
    assert (b / "cmd-001.out").read_text() == "on-b\n"


def test_run_on_a_host_without_a_check_never_uses_another_hosts(log, ssh_here):
    a = start("bench-a")
    assert tm("run", "bench-b", "--", "echo", "on-b") == 0
    assert commands(a) == ""
    [adhoc] = (log / "adhoc").iterdir()
    assert "echo on-b" in commands(adhoc)


def test_deploy_takes_src_and_pr_from_its_own_hosts_check(log, deploys, src_a, src_b):
    start("bench-a", "--src", src_a, "--pr", 11)
    start("bench-b", "--src", src_b, "--pr", 22)
    assert tm("deploy", "bench-b") == 0
    assert tm("deploy", "bench-a") == 0
    assert deploys == [("bench-b", src_b), ("bench-a", src_a)]
    rows = [json.loads(line) for line in (log / "runs.jsonl").read_text().splitlines()]
    assert [(row["host"], row["pr"]) for row in rows] == [("bench-b", 22), ("bench-a", 11)]


def test_deploy_to_a_host_without_a_check_deploys_this_checkout(log, deploys, src_a):
    start("bench-a", "--src", src_a, "--pr", 11)
    assert tm("deploy", "bench-b") == 0
    assert deploys == [("bench-b", devlog.REPO_ROOT)]
    [row] = [json.loads(line) for line in (log / "runs.jsonl").read_text().splitlines()]
    assert row["pr"] is None


def test_deploy_src_and_pr_options_still_win(log, deploys, src_a, src_b):
    start("bench-a", "--src", src_a, "--pr", 11)
    assert tm("deploy", "bench-a", "--src", src_b, "--pr", 33) == 0
    assert deploys == [("bench-a", src_b)]
    [row] = [json.loads(line) for line in (log / "runs.jsonl").read_text().splitlines()]
    assert row["pr"] == 33


# --- --host when two or more are open ------------------------------------------------------------

@pytest.mark.parametrize("argv", [
    ["check", "item", "an item", "pass"],
    ["check", "status"],
    ["check", "end"],
    ["run", "local", "--", "true"],
])
def test_with_two_open_these_need_host_and_list_the_open_checks(argv, capsys):
    a, b = start("bench-a"), start("bench-b")
    capsys.readouterr()
    assert tm(*argv) == 2
    err = capsys.readouterr().err
    assert "--host" in err
    assert "bench-a" in err and str(a) in err
    assert "bench-b" in err and str(b) in err
    assert not (a / "items.jsonl").exists() and not (b / "items.jsonl").exists()
    assert commands(a) == commands(b) == ""
    assert run_dir("bench-a") == a and run_dir("bench-b") == b


def test_with_two_open_host_picks_the_check_for_item_status_and_end(log, capsys):
    a, b = start("bench-a"), start("bench-b")
    assert tm("check", "item", "on b", "pass", "--host", "bench-b") == 0
    assert "on b" in (b / "items.jsonl").read_text()
    assert not (a / "items.jsonl").exists()
    capsys.readouterr()
    assert tm("check", "status", "--host", "bench-b") == 0
    assert "on b" in capsys.readouterr().out
    assert tm("check", "end", "--host", "bench-b") == 0
    assert not marker(log, "bench-b").exists()
    assert run_dir("bench-a") == a
    assert json.loads((b / "meta.json").read_text())["result"].startswith("pass")


def test_run_local_with_host_logs_into_that_check_and_runs_in_its_src(src_a, src_b):
    a = start("bench-a", "--src", src_a)
    b = start("bench-b", "--src", src_b)
    assert tm("run", "local", "--host", "bench-b", "--", "pwd") == 0
    assert (b / "cmd-001.out").read_text() == f"{src_b}\n"
    assert commands(a) == ""
    assert f"local:{src_b}" in commands(b)


def test_host_naming_no_open_check_is_an_error(capsys):
    start("bench-a")
    assert tm("check", "status", "--host", "bench-b") == 2
    err = capsys.readouterr().err
    assert "bench-b" in err and "bench-a" in err


def test_run_takes_host_only_for_local(ssh_here, capsys):
    start("bench-a")
    assert tm("run", "bench-b", "--host", "bench-a", "--", "true") == 2
    assert "local" in capsys.readouterr().err


# --- one check open: as before -------------------------------------------------------------------

def test_with_one_check_open_nothing_needs_host(log, src_a, capsys):
    a = start("bench-a", "--src", src_a, "--pr", 7)
    assert tm("run", "local", "--", "pwd") == 0
    assert (a / "cmd-001.out").read_text() == f"{src_a}\n"
    assert tm("check", "item", "it works", "pass", "--evidence", "cmd-001") == 0
    capsys.readouterr()
    assert tm("check", "status") == 0
    assert "it works" in capsys.readouterr().out
    assert tm("check", "end") == 0
    assert not marker(log, "bench-a").exists()
    [row] = log_rows(log)
    assert "| check | bench-a |" in row and "| 7 |" in row


def test_with_no_check_open_item_says_how_to_start_one(capsys):
    assert tm("check", "item", "x", "pass") == 2
    assert "check start" in capsys.readouterr().err


def test_reopen_refuses_only_a_host_that_has_a_check_open(log):
    a = start("bench-a")
    assert tm("check", "end") == 1  # no items: not a pass, but closed
    b = start("bench-b")
    start("bench-a")
    assert tm("check", "reopen", a.name) == 2
    assert tm("check", "end", "--host", "bench-b") == 1
    assert tm("check", "end", "--host", "bench-a") == 1
    start("bench-b")
    assert tm("check", "reopen", a.name) == 0
    assert run_dir("bench-a") == a
    assert b.exists()


# --- the old global marker -----------------------------------------------------------------------

def legacy_check(log, host, src=None):
    """A check opened by the old tmdev: its run directory and the one global marker."""
    run = devlog.Run.start("check", host, title="old check", src=str(src) if src else None, deploy=None)
    (log / "active-check").write_text(str(run.dir.relative_to(log)))
    return run.dir


def test_an_old_marker_is_the_open_check_of_the_host_its_meta_names(log, ssh_here, deploys, src_a, capsys):
    old = legacy_check(log, "bench-a", src=src_a)
    assert tm("run", "bench-a", "--", "echo", "hi") == 0
    assert "echo hi" in commands(old)
    assert tm("deploy", "bench-a") == 0
    assert deploys == [("bench-a", src_a)]
    capsys.readouterr()
    assert tm("check", "status") == 0
    assert "old check" in capsys.readouterr().out
    assert (log / "active-check").exists()


def test_an_old_marker_does_not_block_another_host(log):
    old = legacy_check(log, "bench-a")
    start("bench-b")
    assert (log / "active-check").read_text() == str(old.relative_to(log))
    assert not marker(log, "bench-a").exists()


def test_start_on_the_old_markers_host_refuses_and_leaves_the_old_marker(log):
    """The old marker stays where the old tmdev that wrote it can still see its check."""
    old = legacy_check(log, "bench-a")
    assert tm("check", "start", "--host", "bench-a", "--title", "new") == 2
    assert (log / "active-check").read_text() == str(old.relative_to(log))
    assert not marker(log, "bench-a").exists()
    assert len(list((log / "runs").iterdir())) == 1


def test_reopen_on_the_old_markers_host_refuses_and_leaves_the_old_marker(log):
    closed = start("bench-a")
    assert tm("check", "end") == 1
    old = legacy_check(log, "bench-a")
    assert tm("check", "reopen", closed.name) == 2
    assert (log / "active-check").read_text() == str(old.relative_to(log))
    assert not marker(log, "bench-a").exists()
    assert "finished" in json.loads((closed / "meta.json").read_text())


def test_end_closes_the_old_markers_check(log):
    old = legacy_check(log, "bench-a")
    assert tm("check", "item", "x", "pass") == 0
    assert tm("check", "end") == 0
    assert not (log / "active-check").exists()
    assert not marker(log, "bench-a").exists()
    assert (old / "checklist.md").exists()
    [row] = log_rows(log)
    assert "| check | bench-a |" in row


def test_end_leaves_an_old_marker_that_names_another_run(log):
    a = start("bench-a")
    old = legacy_check(log, "bench-a")
    assert tm("check", "end", "--host", "bench-a") == 1
    assert not marker(log, "bench-a").exists()
    assert (log / "active-check").read_text() == str(old.relative_to(log))
    assert "finished" in json.loads((a / "meta.json").read_text())
    assert "finished" not in json.loads((old / "meta.json").read_text())


def test_an_old_marker_counts_among_the_open_checks(log, capsys):
    old = legacy_check(log, "bench-a")
    start("bench-b")
    capsys.readouterr()
    assert tm("check", "status") == 2
    err = capsys.readouterr().err
    assert "bench-a" in err and str(old) in err and "bench-b" in err


# --- the indexes' lock ---------------------------------------------------------------------------

def test_an_append_to_the_indexes_waits_for_another_sessions_lock(log):
    run = devlog.Run.start("deploy", "bench-a")
    with open(log / "log.lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        finisher = threading.Thread(target=run.finish, args=("pass", True))
        finisher.start()
        time.sleep(0.5)
        assert finisher.is_alive()
        assert not (log / "LOG.md").exists() and not (log / "runs.jsonl").exists()
        fcntl.flock(lock, fcntl.LOCK_UN)
    finisher.join(10)
    assert not finisher.is_alive()
    assert len(log_rows(log)) == 1
    assert len((log / "runs.jsonl").read_text().splitlines()) == 1


def in_thread(*argv):
    """Run tm(*argv) in a thread; returns the thread and a list that gets its exit code."""
    result = []
    worker = threading.Thread(target=lambda: result.append(tm(*argv)))
    worker.start()
    return worker, result


def open_elsewhere(log, host):
    """Another session's check on host: its run directory and host's marker."""
    run = devlog.Run.start("check", host, title="other session", deploy=None)
    tmdev.write_marker(marker(log, host), run)
    return run.dir


def test_start_holds_the_lock_from_its_check_to_its_marker(log):
    with open(log / "log.lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        worker, result = in_thread("check", "start", "--host", "bench-a", "--title", "racer")
        time.sleep(0.5)
        assert worker.is_alive()
        other = open_elsewhere(log, "bench-a")
        fcntl.flock(lock, fcntl.LOCK_UN)
    worker.join(10)
    assert not worker.is_alive()
    assert result == [2]
    assert list((log / "runs").iterdir()) == [other]
    assert run_dir("bench-a") == other


def test_reopen_holds_the_lock_from_its_check_to_its_marker(log):
    closed = start("bench-a")
    assert tm("check", "end") == 1
    with open(log / "log.lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        worker, result = in_thread("check", "reopen", closed.name)
        time.sleep(0.5)
        assert worker.is_alive()
        other = open_elsewhere(log, "bench-a")
        fcntl.flock(lock, fcntl.LOCK_UN)
    worker.join(10)
    assert not worker.is_alive()
    assert result == [2]
    assert run_dir("bench-a") == other
    assert "finished" in json.loads((closed / "meta.json").read_text())


def test_two_sessions_appending_at_once_leave_whole_rows_and_one_header(log, tmp_path):
    script = tmp_path / "finish_many.py"
    script.write_text(
        "import sys\n"
        f"sys.path.insert(0, {str(DEVPI)!r})\n"
        "import devlog\n"
        "for n in range(15):\n"
        "    devlog.Run.start('deploy', sys.argv[1]).finish('pass', True)\n")
    workers = [subprocess.Popen([sys.executable, str(script), host]) for host in ("bench-a", "bench-b")]
    assert [worker.wait(120) for worker in workers] == [0, 0]
    text = (log / "LOG.md").read_text()
    assert text.count("# Dev-Pi run log") == 1
    rows = log_rows(log)
    assert len(rows) == 30 and all(row.endswith("/) |") for row in rows)
    index = [json.loads(line) for line in (log / "runs.jsonl").read_text().splitlines()]
    assert sorted(row["host"] for row in index) == ["bench-a"] * 15 + ["bench-b"] * 15


def test_a_marker_caught_empty_mid_write_is_left_in_place(log):
    """An old tmdev writes its marker in place, so another session can read it empty for a moment."""
    (log / "active-check").write_text("")
    marker(log, "bench-b").write_text("")
    assert tmdev.open_checks() == {}
    assert (log / "active-check").exists() and marker(log, "bench-b").exists()


def test_a_marker_whose_run_is_gone_is_dropped_and_no_run_directory_is_removed(log):
    a = start("bench-a")
    marker(log, "bench-b").write_text("runs/no-such-run")
    assert set(tmdev.open_checks()) == {"bench-a"}
    assert not marker(log, "bench-b").exists()
    assert a.exists()


# --- files two sessions can write at once --------------------------------------------------------

def test_meta_is_replaced_whole_so_a_failed_save_leaves_the_old_one(log, monkeypatch):
    a = start("bench-a")
    before = (a / "meta.json").read_text()
    run = devlog.Run.load(a)
    run.meta["title"] = "changed"

    def fail(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(devlog.os, "replace", fail)
    with pytest.raises(OSError):
        run.save()
    assert (a / "meta.json").read_text() == before
    monkeypatch.undo()
    run.save()
    assert json.loads((a / "meta.json").read_text())["title"] == "changed"
    assert not list(a.glob(".meta.json.*"))


def test_a_check_whose_meta_cannot_be_read_is_an_error_naming_its_run(log, capsys):
    a = start("bench-a")
    (a / "meta.json").write_text('{"kind": "check", "ho')
    assert tm("check", "status") == 2
    assert a.name in capsys.readouterr().err


def test_run_never_overwrites_another_sessions_output(ssh_here):
    a = start("bench-a")
    (a / "cmd-002.out").write_text("another session's output\n")
    assert tm("run", "bench-a", "--", "echo", "mine") == 0
    assert (a / "cmd-002.out").read_text() == "another session's output\n"
    assert (a / "cmd-003.out").read_text() == "mine\n"
    assert "cmd-003" in commands(a)
