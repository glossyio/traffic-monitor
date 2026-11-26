import json
import os
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from tm_control.app import create_app
from tm_control.cli import main
from tm_control.core import migrate
from tm_control.core.auth import Device, SetupCode
from tm_control.core.secrets import ENTERED_SECRETS
from tm_control.core.state import State

from placeholders import PLACEHOLDER_KEY

BACKEND_DIR = Path(__file__).resolve().parents[1]


def test_migrate_command_updates_the_file(frigate_config):
    assert main(["migrate", "--frigate-config", str(frigate_config)]) == 0
    assert "{FRIGATE_GO2RTC_RTSP_USER}" in frigate_config.read_text()


def test_migrate_requires_a_config_option(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(["migrate"])
    assert exit_info.value.code == 2
    err = capsys.readouterr().err
    for option in ("--frigate-config", "--node-red-config", "--node-red-headings", "--node-red-cosine",
                   "--plate-recognizer-env", "--frigate-env"):
        assert option in err


def node_red_config(tmp_path, token="tb-placeholder-401"):
    path = tmp_path / "node-red-config.yml"
    path.write_text(f"thingsboard:\n    enabled: false\n    access_token: {token}\n")
    return path


def entered_secrets_dir(tmp_path):
    path = tmp_path / "secrets"
    path.mkdir()
    for name in ENTERED_SECRETS:
        (path / name).write_text("")
    return path


def test_migrate_node_red_config_moves_the_tokens(tmp_path, capsys):
    config, secrets = node_red_config(tmp_path), entered_secrets_dir(tmp_path)
    assert main(["migrate", "--node-red-config", str(config), "--secrets-dir", str(secrets)]) == 0
    assert (secrets / "thingsboard_access_token").read_text() == "tb-placeholder-401\n"
    assert "access_token" not in config.read_text()
    assert "tb-placeholder-401" not in capsys.readouterr().out


def test_migrate_node_red_headings_alone_converts_a_bearing_and_reads_no_secrets(tmp_path, monkeypatch, capsys):
    """Node-RED's start runs it as the code owner, who can't read the secrets directory."""
    monkeypatch.setenv("TM_CONTROL_SECRETS_DIR", str(tmp_path / "no-such-secrets"))

    def refuse(*args, **kwargs):
        raise AssertionError("--node-red-headings has no secrets to move")

    monkeypatch.setattr(migrate, "_read_secret", refuse)
    config = tmp_path / "config.yml"
    config.write_text("deployment:\n    bearing: 'e'\n")
    assert main(["migrate", "--node-red-headings", str(config)]) == 0
    assert config.read_text() == "deployment:\n    heading_deg: 90\n"
    assert "converted deployment.bearing to heading_deg" in capsys.readouterr().out


def test_migrate_node_red_headings_dry_run_writes_nothing(tmp_path, capsys):
    config = tmp_path / "config.yml"
    config.write_text("deployment:\n    bearing: 'e'\n")
    assert main(["migrate", "--node-red-headings", str(config), "--dry-run"]) == 0
    assert config.read_text() == "deployment:\n    bearing: 'e'\n"
    assert capsys.readouterr().out == f"tm-control migrate: {config}: would convert deployment.bearing to heading_deg\n"


def test_migrate_node_red_cosine_alone_moves_an_angle_and_reads_no_secrets(tmp_path, monkeypatch, capsys):
    """Node-RED's start runs it as the code owner, who can't read the secrets directory."""
    monkeypatch.setenv("TM_CONTROL_SECRETS_DIR", str(tmp_path / "no-such-secrets"))

    def refuse(*args, **kwargs):
        raise AssertionError("--node-red-cosine has no secrets to move")

    monkeypatch.setattr(migrate, "_read_secret", refuse)
    config = tmp_path / "config.yml"
    config.write_text("sensors:\n    radars:\n        R0:\n            enabled: true\n"
                      "            opt_api_commands_array: '[\"^/+12.5\\n\"]'\n")
    assert main(["migrate", "--node-red-cosine", str(config)]) == 0
    assert config.read_text() == ("sensors:\n    radars:\n        R0:\n            enabled: true\n"
                                  "            cosine_inbound_deg: 12.5\n            opt_api_commands_array: '[]'\n")
    assert "R0.opt_api_commands_array" in capsys.readouterr().out


def test_migrate_node_red_cosine_dry_run_writes_nothing(tmp_path, capsys):
    config = tmp_path / "config.yml"
    text = "sensors:\n    radars:\n        R0:\n            opt_api_commands_array: '[\"^/+12.5\\n\"]'\n"
    config.write_text(text)
    assert main(["migrate", "--node-red-cosine", str(config), "--dry-run"]) == 0
    assert config.read_text() == text
    assert capsys.readouterr().out.startswith(f"tm-control migrate: {config}: would ")


def test_migrate_node_red_cosine_calls_the_step_with_its_path_and_the_dry_run(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(migrate, "run_node_red_cosine", lambda path, dry_run=False: calls.append((path, dry_run)) or 0)
    assert main(["migrate", "--node-red-cosine", str(tmp_path / "config.yml"), "--dry-run"]) == 0
    assert calls == [(tmp_path / "config.yml", True)]


def test_migrate_node_red_cosine_runs_after_the_headings_step_when_given_with_it(tmp_path, monkeypatch):
    order = []
    monkeypatch.setattr(migrate, "run_node_red_headings", lambda path, dry_run=False: order.append("headings") or 0)
    monkeypatch.setattr(migrate, "run_node_red_cosine", lambda path, dry_run=False: order.append("cosine") or 0)
    path = str(tmp_path / "config.yml")
    assert main(["migrate", "--node-red-cosine", path, "--node-red-headings", path]) == 0
    assert order == ["headings", "cosine"]


def test_migrate_plate_recognizer_env_moves_the_values(tmp_path, monkeypatch):
    """--secrets-dir defaults to TM_CONTROL_SECRETS_DIR, as the web app's setting does."""
    secrets = entered_secrets_dir(tmp_path)
    monkeypatch.setenv("TM_CONTROL_SECRETS_DIR", str(secrets))
    env = tmp_path / "plate-recognizer.env"
    env.write_text("TOKEN=pr-placeholder-402\nLICENSE_KEY=pr-placeholder-403\nWORKERS=2\n")
    assert main(["migrate", "--plate-recognizer-env", str(env)]) == 0
    assert (secrets / "plate_recognizer_token").read_text() == "pr-placeholder-402\n"
    assert (secrets / "plate_recognizer_license_key").read_text() == "pr-placeholder-403\n"


def test_migrate_frigate_env_moves_the_key(tmp_path, capsys):
    secrets = entered_secrets_dir(tmp_path)
    env = tmp_path / "frigate.env"
    env.write_text(f"FRIGATE_RTSP_PASSWORD=rtsp-placeholder-405\nPLUS_API_KEY={PLACEHOLDER_KEY}\n")
    assert main(["migrate", "--frigate-env", str(env), "--secrets-dir", str(secrets)]) == 0
    assert (secrets / "frigate_plus_api_key").read_text() == PLACEHOLDER_KEY + "\n"
    captured = capsys.readouterr()
    assert captured.out == f"tm-control migrate: {env}: moved PLUS_API_KEY to the secrets files\n"
    assert PLACEHOLDER_KEY.split(":")[1] not in captured.out + captured.err


def test_migrate_secrets_dir_defaults_to_the_devices(monkeypatch):
    monkeypatch.delenv("TM_CONTROL_SECRETS_DIR", raising=False)
    seen = {}
    monkeypatch.setattr(migrate, "run_plate_recognizer_env",
                        lambda path, secrets_dir, dry_run=False: seen.setdefault("dir", secrets_dir) and 0)
    assert main(["migrate", "--plate-recognizer-env", "/nonexistent/plate-recognizer.env"]) == 0
    assert seen["dir"] == Path("/etc/traffic-monitor/secrets")


def test_migrate_runs_every_config_given(frigate_config, tmp_path, capsys):
    """In the order Frigate config, Node-RED, Plate Recognizer, Frigate env; each runs even when one before it fails,
    and the exit code is the highest."""
    secrets = entered_secrets_dir(tmp_path)
    env = tmp_path / "plate-recognizer.env"
    env.write_text("TOKEN=pr-placeholder-404\nLICENSE_KEY=\n")
    frigate_env = tmp_path / "frigate.env"
    frigate_env.write_text(f"PLUS_API_KEY={PLACEHOLDER_KEY}\n")
    code = main(["migrate", "--frigate-config", str(frigate_config), "--node-red-config", str(tmp_path / "missing.yml"),
                 "--plate-recognizer-env", str(env), "--frigate-env", str(frigate_env), "--secrets-dir", str(secrets)])
    assert code == 1
    captured = capsys.readouterr()
    assert f"ERROR reading {tmp_path / 'missing.yml'}" in captured.err
    lines = captured.out.splitlines()
    assert [line.split(": ")[1] for line in lines] == [str(frigate_config), str(env), str(frigate_env)]
    assert "{FRIGATE_GO2RTC_RTSP_USER}" in frigate_config.read_text()
    assert (secrets / "plate_recognizer_token").read_text() == "pr-placeholder-404\n"
    assert (secrets / "frigate_plus_api_key").read_text() == PLACEHOLDER_KEY + "\n"


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


def test_serve_hides_tickets_in_the_access_log(monkeypatch, settings):
    import logging

    import uvicorn

    from tm_control.core.settings import Settings
    from tm_control.modules.cameras.reference import HideTickets

    access = logging.getLogger("uvicorn.access")
    monkeypatch.setattr(access, "filters", [])
    monkeypatch.setattr(Settings, "from_env", classmethod(lambda cls: settings))
    monkeypatch.setattr(uvicorn, "run", lambda *args, **kwargs: None)
    assert main(["serve"]) == 0
    assert [type(f) for f in access.filters] == [HideTickets]


def _serve_with(monkeypatch, settings):
    """Run serve with uvicorn and the app's poster replaced; the list records the order of the poster's start and
    the server's run."""
    import uvicorn

    from tm_control import app as app_module
    from tm_control.core.settings import Settings

    started = []
    poster = SimpleNamespace(start=lambda: started.append("poster"))
    fake_app = SimpleNamespace(state=SimpleNamespace(setup_poster=poster))
    monkeypatch.setattr(Settings, "from_env", classmethod(lambda cls: settings))
    monkeypatch.setattr(app_module, "create_app", lambda given: fake_app)
    monkeypatch.setattr(uvicorn, "run", lambda *args, **kwargs: started.append("run"))
    assert main(["serve"]) == 0
    return started


def test_serve_starts_the_setup_poster_on_a_device_before_the_server_runs(monkeypatch, settings):
    import dataclasses

    assert _serve_with(monkeypatch, dataclasses.replace(settings, fake=False)) == ["poster", "run"]


def test_serve_does_not_start_the_setup_poster_in_fake_mode(monkeypatch, settings):
    assert _serve_with(monkeypatch, settings) == ["run"]
