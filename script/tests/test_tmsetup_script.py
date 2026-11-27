"""tmsetup.sh itself: it refuses to run as root before it changes anything.

The root case runs directly when the suite runs as root, or as root in a user namespace (unshare) when the machine
allows that; otherwise it's skipped. -T would print the tags and exit 2, so a guard that let root through shows.
"""

import fcntl
import os
import re
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


@pytest.mark.skipif(os.geteuid() == 0, reason="runs as a normal user")
def test_a_wifi_country_must_be_two_letters(tmp_path):
    result = run(["bash", str(SCRIPT), "-w", "USA", "-T"], tmp_path)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "Invalid Wi-Fi country: USA" in result.stdout
    assert "Valid Tags" not in result.stdout


@pytest.mark.skipif(os.geteuid() == 0, reason="runs as a normal user")
def test_a_two_letter_wifi_country_is_accepted(tmp_path):
    result = run(["bash", str(SCRIPT), "-w", "gb", "-T"], tmp_path)
    assert result.returncode == 2 and "Valid Tags" in result.stdout


@pytest.mark.skipif(os.geteuid() == 0, reason="runs as a normal user")
def test_usage_lists_the_wifi_country_option(tmp_path):
    result = run(["bash", str(SCRIPT), "-h"], tmp_path)
    assert "-w CODE" in result.stdout


def script_code_lines():
    """The script's lines without comments or blank lines."""
    return [line for line in SCRIPT.read_text().splitlines() if line.strip() and not line.strip().startswith("#")]


def test_the_card_goes_to_the_terminal_not_the_log():
    """The script copies everything it prints to ~/tmsetup-*.log (exec > >(tee ...)), so the card, which holds the
    hotspot password and the setup code, may only be written straight to /dev/tty."""
    lines = [line for line in script_code_lines() if not line.strip().startswith("printf")]  # messages aren't runs
    runs = [line for line in lines if "tm-control card" in line]
    assert len(runs) == 1, runs
    # the redirect is made inside sudo (sudo's pty puts the terminal in raw mode), not by this shell
    assert runs[0].strip() == "if sudo sh -c 'exec /usr/local/bin/tm-control card --unclaimed-only > /dev/tty'; then"
    for line in lines:
        # nothing assigns from the command, pipes it, or sends it anywhere else
        if "tm-control" in line and " card" in line:
            assert "$(" not in line and "`" not in line and "|" not in line and "tee" not in line, line
            assert "2>&1" not in line and ">>" not in line and "<<<" not in line, line
    assert not any(re.search(r"=\s*\$\(.*tm-control", line) for line in lines)
    assert not any("tm-control" in line and "card" in line and "${_LOGFILE}" in line for line in lines)


def test_the_card_is_shown_only_after_a_successful_local_run():
    text = SCRIPT.read_text()
    local = text[text.index("_tmsetup_local(){"):text.index("_tmsetup_remote(){")]
    assert '_print_result "${_EXIT_STATUS}"' in local
    shown = local.index("_show_card")
    assert local.index('_print_result "${_EXIT_STATUS}"') < shown
    assert 'if [[ "${_EXIT_STATUS}" -eq 0 ]]; then' in local[shown - 120:shown]
    assert "_show_card" not in text[text.index("_tmsetup_remote(){"):]  # remote runs print no card
    function = text[text.index("_show_card() {"):text.index("_tmsetup_local(){")]
    assert "/usr/local/bin/tm-control" in function and "( : > /dev/tty )" in function
    assert "Show the card any time with: sudo tm-control card" in function
    assert "was shown on the terminal and is not in this log" in function


def test_a_successful_remote_run_says_how_to_show_the_card_without_showing_it():
    text = SCRIPT.read_text()
    remote = text[text.index("_tmsetup_remote(){"):text.index("### Start of MAIN")]
    printed = remote.index("Show the card any time with: sudo tm-control card on the device.")
    assert remote.index('_print_result "${_EXIT_STATUS}"') < printed
    assert 'if [[ "${_EXIT_STATUS}" -eq 0 ]]; then' in remote[printed - 200:printed]
    # a pointer only: the remote branch never runs the card, over ssh or otherwise
    assert "_show_card" not in remote
    assert not [line for line in remote.splitlines() if "tm-control card" in line and "printf" not in line]


def _finish_log_function():
    text = SCRIPT.read_text()
    start = text.index("_finish_log() {")
    return text[start:text.index("\n}\n", start) + 3]


def test_the_script_waits_for_the_logs_tee_before_it_exits():
    """ssh -t hangs up when the script exits and kills tee before it writes the last lines."""
    text = SCRIPT.read_text()
    assert text.index('exec > >(tee -i "${_LOGFILE}")') < text.index("_LOG_TEE_PID=$!") < text.index("trap _finish_log EXIT")
    assert len(re.findall(r"^\s*trap\b", text, re.M)) == 1
    function = _finish_log_function()
    assert "local status=$?" in function and "exec >&- 2>&-" in function
    assert 'wait "${_LOG_TEE_PID}"' in function and 'exit "${status}"' in function


@pytest.mark.parametrize("code", [0, 3])
def test_the_last_lines_reach_the_log_and_the_exit_status_is_kept(tmp_path, code):
    log = tmp_path / "run.log"
    snippet = f"""set -e
{_finish_log_function()}
exec > >(sleep 0.3; tee -i "{log}")
_LOG_TEE_PID=$!
exec 2>&1
trap _finish_log EXIT
printf "first\\n"
printf "last line\\n"
exit {code}
"""
    shown = tmp_path / "shown.txt"
    with shown.open("w") as out:  # a file, not a pipe: run() returns when bash does, not when tee does
        result = subprocess.run(["bash", "-c", snippet], stdout=out, stderr=subprocess.STDOUT, timeout=30, check=False)
    # read at once: the delayed tee has had to be waited for
    assert result.returncode == code
    assert log.read_text() == "first\nlast line\n"
    assert shown.read_text() == "first\nlast line\n"


def test_both_install_paths_install_ansible_from_the_hashed_lock():
    installs = [line.strip() for line in script_code_lines() if "pip3 install" in line]
    assert installs == ['pip3 install --require-hashes -r "${script_dir}/requirements.lock" || return 1'] * 2


@pytest.mark.skipif(os.geteuid() == 0, reason="runs as a normal user")
def test_a_remote_run_from_an_old_python_says_so_and_makes_nothing(tmp_path):
    """The lock was made for Python 3.13 and Ansible 14 needs 3.12; an older python3 stops the run before a venv."""
    fake = tmp_path / "bin"
    fake.mkdir()
    python = fake / "python3"
    python.write_text("#!/bin/sh\nif [ \"$1\" = -c ]; then echo 3.11; exit 0; fi\nexit 1\n")
    python.chmod(0o755)
    home = tmp_path / "home"
    home.mkdir()
    env = {"HOME": str(home), "PATH": f"{fake}:{os.environ.get('PATH', '/usr/bin:/bin')}"}
    result = subprocess.run(["bash", str(SCRIPT), "-y", "-H", "192.0.2.1"], env=env, capture_output=True, text=True,
                            timeout=30, check=False)
    output = result.stdout + result.stderr
    assert result.returncode == 1, output
    assert "Python 3.12 or later" in output and "3.11" in output
    assert not (home / ".tmsetup" / "tm_venv").exists()


LOCK_MESSAGE = "Another install or update is running on this device. Wait for it to finish, then run tmsetup.sh again."


def take_run_lock_function():
    """_take_run_lock cut out of the script by its text: from its first line to the closing brace at column 0."""
    text = SCRIPT.read_text()
    start = text.index("_take_run_lock() {")
    end = text.index("\n}\n", start) + 3
    return text[start:end]


def fake_sudo(tmp_path):
    """A sudo that runs its arguments, first on PATH, so the create step needs no password."""
    fake = tmp_path / "bin"
    fake.mkdir(exist_ok=True)
    sudo = fake / "sudo"
    sudo.write_text('#!/bin/sh\nexec "$@"\n')
    sudo.chmod(0o755)
    return {"PATH": f"{fake}:{os.environ.get('PATH', '/usr/bin:/bin')}", "HOME": str(tmp_path)}


def run_take_run_lock(tmp_path, lock, after="", **kwargs):
    snippet = f"{take_run_lock_function()}\n_take_run_lock '{lock}'\nstatus=$?\n{after}\nexit $status"
    return subprocess.run(["bash", "-c", snippet], env=fake_sudo(tmp_path), text=True, timeout=10, check=False, **kwargs)


def test_a_free_lock_is_taken_and_held_while_the_shell_lives(tmp_path):
    lock = tmp_path / "update" / "lock"
    proc = subprocess.Popen(
        ["bash", "-c", f"{take_run_lock_function()}\n_take_run_lock '{lock}' || exit 1\necho held\nsleep 30"],
        env=fake_sudo(tmp_path), stdout=subprocess.PIPE, text=True)
    try:
        assert proc.stdout.readline() == "held\n"
        with lock.open() as other:
            with pytest.raises(BlockingIOError):
                fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
    finally:
        proc.kill()
        proc.wait()
        proc.stdout.close()
    with lock.open() as other:
        fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)  # the kernel let go when the shell ended


def test_a_missing_lock_file_and_its_folders_are_created_readable_by_everyone(tmp_path):
    lock = tmp_path / "var" / "update" / "lock"
    result = run_take_run_lock(tmp_path, lock, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert [oct(path.stat().st_mode & 0o777) for path in (lock.parent.parent, lock.parent, lock)] == [
        "0o755", "0o755", "0o644"]


def test_a_held_lock_stops_the_run_with_the_reason(tmp_path):
    lock = tmp_path / "lock"
    lock.touch()
    with lock.open() as holder:
        fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = run_take_run_lock(tmp_path, lock, capture_output=True)
    assert result.returncode == 1
    assert result.stdout.strip() == LOCK_MESSAGE
    assert result.stderr == ""


def test_creating_the_lock_file_never_replaces_it(tmp_path):
    """The create step opens for appending; a replaced file would be a different lock, and a second run would pass."""
    lock = tmp_path / "lock"
    lock.touch()
    inode = lock.stat().st_ino
    function = take_run_lock_function()
    create = re.findall(r"sudo sh -c '([^']*)' sh ", function)
    assert len(create) == 1 and ": >> " in create[0] and not re.search(r"\b(install|cp|mv)\b", create[0])
    with lock.open() as holder:
        fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
        # the function's own create step, run on the existing file the way the function runs it (through sudo)
        done = subprocess.run(["sudo", "sh", "-c", create[0], "sh", str(lock.parent), str(lock)],
                              env=fake_sudo(tmp_path), capture_output=True, text=True, timeout=10, check=False)
        assert done.returncode == 0, done.stderr
        assert lock.stat().st_ino == inode
        result = run_take_run_lock(tmp_path, lock, capture_output=True)
    assert result.returncode == 1
    assert result.stdout.strip() == LOCK_MESSAGE
    assert lock.stat().st_ino == inode


def test_a_lock_that_cannot_be_made_or_opened_says_so_not_that_another_run_holds_it(tmp_path):
    fake = tmp_path / "bin"
    fake.mkdir()
    sudo = fake / "sudo"
    sudo.write_text("#!/bin/sh\nexit 1\n")
    sudo.chmod(0o755)
    env = {"PATH": f"{fake}:{os.environ.get('PATH', '/usr/bin:/bin')}", "HOME": str(tmp_path)}
    lock = tmp_path / "update" / "lock"
    snippet = f"{take_run_lock_function()}\n_take_run_lock '{lock}'\nexit $?"
    result = subprocess.run(["bash", "-c", snippet], env=env, capture_output=True, text=True, timeout=10, check=False)
    assert result.returncode == 1
    assert result.stdout.strip() == f"Could not create the installer's lock file {lock}."
    # a lock file that exists but can't be opened
    lock = tmp_path / "unreadable"
    lock.touch()
    lock.chmod(0)
    if os.geteuid() != 0:
        snippet = f"{take_run_lock_function()}\n_take_run_lock '{lock}'\nexit $?"
        result = subprocess.run(["bash", "-c", snippet], env=env, capture_output=True, text=True, timeout=10,
                                check=False)
        assert result.returncode == 1
        assert result.stdout.strip() == f"Could not open the installer's lock file {lock}."


def test_a_local_run_takes_the_lock_after_the_sudo_check_and_before_anything_is_asked_or_installed():
    lines = [line.strip() for line in script_code_lines()]
    assert "_RUN_LOCK=/var/lib/traffic-monitor/update/lock" in lines
    start = lines.index("_tmsetup_local(){ # Installation on localhost only")
    body = lines[start:]
    sudo_check = next(i for i, line in enumerate(body) if "sudo -n true" in line)
    take = body.index('_take_run_lock "${_RUN_LOCK}" || return 1')
    confirm = next(i for i, line in enumerate(body) if line.startswith('_confirm_cont "Are you sure'))
    wifi = body.index("_ask_wifi_country")
    ansible = next(i for i, line in enumerate(body) if line.startswith('_install_ansible_local "'))
    assert sudo_check < take < confirm < wifi < ansible
    assert sum("_take_run_lock" in line and "()" not in line for line in lines) == 1  # a remote run takes none


def test_the_usage_text_names_no_default_time_zone(tmp_path):
    result = run(["bash", str(SCRIPT), "-h"], tmp_path)
    assert '-z TIMEZONE' in result.stdout
    assert "America/Los_Angeles" not in result.stdout
    assert "left as it is unless given" in result.stdout
