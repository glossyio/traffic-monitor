import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from tm_control.app import create_app
from tm_control.cli import main
from tm_control.core.auth import Device, SetupCode
from tm_control.core.state import State

BACKEND_DIR = Path(__file__).resolve().parents[1]


def test_migrate_command_updates_the_file(frigate_config):
    assert main(["migrate", "--frigate-config", str(frigate_config)]) == 0
    assert "{FRIGATE_GO2RTC_RTSP_USER}" in frigate_config.read_text()


def test_migrate_requires_the_frigate_config_option():
    with pytest.raises(SystemExit) as exit_info:
        main(["migrate"])
    assert exit_info.value.code == 2


def test_runs_as_a_module(frigate_config):
    result = subprocess.run(
        [sys.executable, "-m", "tm_control", "migrate", "--dry-run", "--frigate-config", str(frigate_config)],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(BACKEND_DIR)},
    )
    assert result.returncode == 0, result.stderr
    assert "would update 1 camera input(s)" in result.stdout


@pytest.fixture
def fake_env(tmp_path, monkeypatch):
    """Fake mode with its state in tmp_path/.tm-control-fake, as a laptop in the repo root would have it."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TM_CONTROL_FAKE", "1")
    for name in ("TM_CONTROL_STATE_DIR", "TM_CONTROL_RUNTIME_DIR", "STATE_DIRECTORY", "RUNTIME_DIRECTORY"):
        monkeypatch.delenv(name, raising=False)
    return tmp_path / ".tm-control-fake" / "state"


def printed_setup_code(output):
    match = re.search(r"Setup code: ([A-Z0-9]{4}-[A-Z0-9]{4})", output)
    assert match, output
    return match.group(1)


def test_fake_reset_refuses_outside_fake_mode(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("TM_CONTROL_FAKE", raising=False)
    monkeypatch.setenv("TM_CONTROL_STATE_DIR", str(tmp_path / "state"))
    assert main(["fake-reset"]) == 2
    assert "TM_CONTROL_FAKE=1" in capsys.readouterr().err
    assert not (tmp_path / "state").exists()


def test_fake_reset_unclaims_and_prints_a_code_that_claims(fake_env, capsys):
    assert main(["fake-reset"]) == 0
    state = State(fake_env / "state.sqlite")
    Device(state).claim("owner", "owner pass 12", "1")
    capsys.readouterr()  # the first reset's code

    assert main(["fake-reset"]) == 0
    code = printed_setup_code(capsys.readouterr().out)
    device = Device(State(fake_env / "state.sqlite"))
    assert not device.is_claimed()
    assert SetupCode.verify_code(device.setup_code_hash(), code)


def test_dump_openapi_prints_the_apps_document_without_device_files(tmp_path, monkeypatch, capsys, settings):
    """No secrets, manifest, or state directory needed, so it runs on a dev machine outside fake mode."""
    monkeypatch.delenv("TM_CONTROL_FAKE", raising=False)
    monkeypatch.setenv("TM_CONTROL_STATE_DIR", str(tmp_path / "missing-state"))
    monkeypatch.setenv("TM_CONTROL_SECRETS_DIR", str(tmp_path / "missing-secrets"))
    assert main(["dump-openapi"]) == 0
    assert json.loads(capsys.readouterr().out) == create_app(settings).openapi()
    assert not (tmp_path / "missing-state").exists()
