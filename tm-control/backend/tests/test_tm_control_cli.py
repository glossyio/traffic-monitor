import os
import subprocess
import sys
from pathlib import Path

import pytest

from tm_control.cli import main

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
