import io
import os
import pwd
import re
import sqlite3
import stat

import pytest

from tm_control.cli import main
from tm_control.core.auth import Device, SetupCode, Users
from tm_control.core.state import State

CODE = re.compile(r"Setup code: ([A-HJ-NP-Z2-9]{4}-[A-HJ-NP-Z2-9]{4})$", re.MULTILINE)

# The as_root tests drop to the state directory's owner, which is the test's own user. When the suite really runs as
# root that owner is root, and the CLI rightly refuses a root-owned state directory, so those tests can't run.
needs_a_non_root_owner = pytest.mark.skipif(
    os.geteuid() == 0, reason="the test's state directory is root's, which the CLI refuses as root"
)


@pytest.fixture
def cli_env(settings, monkeypatch):
    """The environment the CLI reads its Settings from, pointing at the test's state dir and setup-code file.

    The CLI runs as a normal user (the code owner) unless a test says otherwise, even when the suite runs as root.
    """
    monkeypatch.setattr(os, "geteuid", lambda: 1000)
    monkeypatch.delenv("STATE_DIRECTORY", raising=False)
    monkeypatch.setenv("TM_CONTROL_STATE_DIR", str(settings.state_dir))
    monkeypatch.setenv("TM_CONTROL_SETUP_CODE_FILE", str(settings.setup_code_file))
    settings.setup_code_file.parent.mkdir()
    return settings


@pytest.fixture
def as_root(cli_env, monkeypatch):
    """Pretend to be root: record the privilege drop instead of making it, with whether the state existed then."""
    calls = []
    state_file = cli_env.state_dir / "state.sqlite"
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    monkeypatch.setattr(os, "setgroups", lambda groups: calls.append(("setgroups", groups)))
    monkeypatch.setattr(os, "setgid", lambda gid: calls.append(("setgid", gid)))

    def setuid(uid):
        calls.append(("setuid", uid))
        calls.append(("state existed", state_file.exists()))
        calls.append(("code file existed", cli_env.setup_code_file.exists()))

    monkeypatch.setattr(os, "setuid", setuid)
    cli_env.state_dir.mkdir(mode=0o700)
    return calls


def me():
    return pwd.getpwuid(os.getuid())


def device(settings):
    """The device in the CLI's state, created and migrated as the service would."""
    settings.state_dir.mkdir(mode=0o700, exist_ok=True)
    state = State(settings.state_dir / "state.sqlite")
    state.migrate()
    return Device(state)


def stdin(monkeypatch, text):
    monkeypatch.setattr("sys.stdin", io.StringIO(text))


def test_claim_status_reports_unclaimed_then_claimed(cli_env, capsys):
    assert main(["claim-status"]) == 0  # before the service has ever run: the state is created and migrated
    assert capsys.readouterr().out == "unclaimed\n"
    device(cli_env).claim("admin", "correct horse 1", "1")
    assert main(["claim-status"]) == 0
    assert capsys.readouterr().out == "claimed\n"


@needs_a_non_root_owner
@pytest.mark.parametrize("command", ["claim-status", "set-setup-code"])
def test_state_commands_run_as_root_drop_to_the_state_dirs_owner_first(as_root, monkeypatch, capsys, command):
    stdin(monkeypatch, "ABCD-EFGH\n")
    assert main([command]) == 0
    assert as_root == [
        ("setgroups", []),
        ("setgid", me().pw_gid),
        ("setuid", me().pw_uid),
        ("state existed", False),
        ("code file existed", False),
    ]


def test_state_commands_refuse_a_root_owned_state_dir(as_root, monkeypatch, capsys):
    monkeypatch.setenv("TM_CONTROL_STATE_DIR", "/")
    assert main(["claim-status"]) == 1
    assert "owned by root" in capsys.readouterr().err
    assert as_root == []


def test_state_commands_refuse_a_missing_state_dir_as_root(as_root, cli_env, monkeypatch, capsys):
    monkeypatch.setenv("TM_CONTROL_STATE_DIR", str(cli_env.state_dir / "missing"))
    assert main(["claim-status"]) == 1
    assert "doesn't exist" in capsys.readouterr().err
    assert as_root == [] and not (cli_env.state_dir / "missing").exists()


def test_set_setup_code_stores_a_hash_and_never_prints_the_code(cli_env, capsys, monkeypatch):
    stdin(monkeypatch, "abcd-efgh\n")
    assert main(["set-setup-code"]) == 0
    out, err = capsys.readouterr()
    assert out == "stored\n" and "ABCD" not in out + err and "abcd" not in out + err
    assert SetupCode.verify_code(device(cli_env).setup_code_hash(), "ABCD-EFGH")


@pytest.mark.parametrize("text", ["ABCD-EFG1\n", "ABCD-EFGO\n", "ABCD-EF\n", "ABCD-EFGHJ\n", "\n", ""])
def test_set_setup_code_rejects_a_malformed_code_without_echoing_it(cli_env, capsys, monkeypatch, text):
    stdin(monkeypatch, text)
    assert main(["set-setup-code"]) == 1
    out, err = capsys.readouterr()
    assert out == "" and "8 characters" in err
    if text.strip():
        assert text.strip() not in err
    assert device(cli_env).setup_code_hash() is None


def test_set_setup_code_on_a_claimed_device_exits_3(cli_env, capsys, monkeypatch):
    device(cli_env).claim("admin", "correct horse 1", "1")
    stdin(monkeypatch, "ABCD-EFGH\n")
    assert main(["set-setup-code"]) == 3
    assert capsys.readouterr().out == "claimed\n"
    assert device(cli_env).setup_code_hash() is None


def test_reset_admin_refuses_without_root(cli_env, monkeypatch, capsys):
    assert main(["reset-admin"]) == 2
    assert "root" in capsys.readouterr().err
    assert not cli_env.setup_code_file.exists()


@needs_a_non_root_owner
def test_reset_admin_as_root_writes_the_file_then_unclaims(as_root, cli_env, tmp_path, capsys):
    claimed = device(cli_env).claim("admin", "correct horse 1", "1")
    code_file = tmp_path / "elsewhere"
    assert main(["reset-admin", "--setup-code-file", str(code_file)]) == 0
    out = capsys.readouterr().out
    code = CODE.search(out).group(1)
    assert out.startswith(f"Device unclaimed. Setup code: {code}\n") and "/setup" in out
    assert stat.S_IMODE(code_file.stat().st_mode) == 0o600
    assert code_file.read_text().strip() == code
    assert not cli_env.setup_code_file.exists()
    assert as_root[:3] == [("setgroups", []), ("setgid", me().pw_gid), ("setuid", me().pw_uid)]
    assert ("code file existed", False) in as_root  # the env's default path; the option's file was written first

    assert not device(cli_env).is_claimed()
    assert SetupCode.verify_code(device(cli_env).setup_code_hash(), code)
    assert Users(State(cli_env.state_dir / "state.sqlite")).get(claimed.id) is None
    con = sqlite3.connect(cli_env.state_dir / "state.sqlite")
    assert con.execute("SELECT user_id, action FROM audit").fetchall() == [(None, "reset-admin")]
    con.close()


@needs_a_non_root_owner
def test_reset_admin_writes_the_file_before_dropping_privileges(as_root, cli_env, capsys):
    assert main(["reset-admin"]) == 0
    assert ("code file existed", True) in as_root
    assert CODE.search(capsys.readouterr().out).group(1) == cli_env.setup_code_file.read_text().strip()


@needs_a_non_root_owner
def test_reset_admin_makes_an_existing_code_file_private(as_root, cli_env, capsys):
    cli_env.setup_code_file.write_text("OLDC-ODE2 and more text than a code\n")
    cli_env.setup_code_file.chmod(0o644)
    assert main(["reset-admin"]) == 0
    assert stat.S_IMODE(cli_env.setup_code_file.stat().st_mode) == 0o600
    assert cli_env.setup_code_file.read_text() == CODE.search(capsys.readouterr().out).group(1) + "\n"


def test_reset_admin_with_a_root_owned_state_dir_writes_nothing(as_root, cli_env, monkeypatch, capsys):
    monkeypatch.setenv("TM_CONTROL_STATE_DIR", "/")
    assert main(["reset-admin"]) == 1
    assert "owned by root" in capsys.readouterr().err
    assert not cli_env.setup_code_file.exists() and as_root == []
