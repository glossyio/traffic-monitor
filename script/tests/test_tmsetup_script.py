"""tmsetup.sh itself: it refuses to run as root before it changes anything.

The root case runs directly when the suite runs as root, or as root in a user namespace (unshare) when the machine
allows that; otherwise it's skipped. -T would print the tags and exit 2, so a guard that let root through shows.
"""

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
    assert runs[0].strip() == "if sudo /usr/local/bin/tm-control card --unclaimed-only > /dev/tty; then"
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
