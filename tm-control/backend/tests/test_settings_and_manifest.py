import dataclasses
import json
from pathlib import Path

import pytest

from tm_control.adapters.command import run
from tm_control.app import create_app
from tm_control.core.manifest import ManifestError, load_manifest
from tm_control.core.secrets import DEVICE_SECRETS, NAMES, NODE_RED_INTERNAL_TOKEN, FakeSecrets, MissingSecret, Secrets
from tm_control.core.settings import Settings

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def test_settings_default_to_the_device_paths():
    s = Settings.from_env({})
    assert s.state_dir == Path("/var/lib/tm-control")
    assert s.runtime_dir == Path("/run/tm-control")
    assert s.secrets_dir == Path("/etc/traffic-monitor/secrets")
    assert s.manifest_path == Path("/etc/traffic-monitor/manifest.json")
    assert s.setup_code_file == Path("/etc/traffic-monitor/setup-code")
    assert (s.host, s.port) == ("127.0.0.1", 8090)
    assert not s.fake


def test_settings_follow_systemd_directories():
    s = Settings.from_env({"STATE_DIRECTORY": "/x", "RUNTIME_DIRECTORY": "/y"})
    assert (s.state_dir, s.runtime_dir) == (Path("/x"), Path("/y"))


def test_settings_variables_override_systemd_directories():
    s = Settings.from_env(
        {
            "STATE_DIRECTORY": "/x",
            "TM_CONTROL_STATE_DIR": "/a",
            "RUNTIME_DIRECTORY": "/y",
            "TM_CONTROL_RUNTIME_DIR": "/b",
            "TM_CONTROL_SECRETS_DIR": "/c",
            "TM_CONTROL_MANIFEST": "/d/manifest.json",
            "TM_CONTROL_BIND": "0.0.0.0:9000",
            "TM_CONTROL_SETUP_CODE_FILE": "/e/setup-code",
        }
    )
    assert (s.state_dir, s.runtime_dir, s.secrets_dir) == (Path("/a"), Path("/b"), Path("/c"))
    assert s.setup_code_file == Path("/e/setup-code")
    assert s.manifest_path == Path("/d/manifest.json")
    assert (s.host, s.port) == ("0.0.0.0", 9000)


@pytest.mark.parametrize("bind", ["8090", "127.0.0.1:", "127.0.0.1:http"])
def test_settings_reject_a_bad_bind(bind):
    with pytest.raises(ValueError, match="TM_CONTROL_BIND"):
        Settings.from_env({"TM_CONTROL_BIND": bind})


def test_fake_mode_flag():
    assert Settings.from_env({"TM_CONTROL_FAKE": "1"}).fake
    assert not Settings.from_env({"TM_CONTROL_FAKE": "0"}).fake


def test_fake_mode_defaults_to_the_fixture_manifest():
    assert Settings.from_env({"TM_CONTROL_FAKE": "1"}).manifest_path == FIXTURES / "manifest.json"
    s = Settings.from_env({"TM_CONTROL_FAKE": "1", "TM_CONTROL_MANIFEST": "/d/manifest.json"})
    assert s.manifest_path == Path("/d/manifest.json")


def test_fake_mode_keeps_its_state_under_the_current_directory(tmp_path, monkeypatch):
    """A laptop has no /var/lib/tm-control or /run/tm-control; fake mode uses ./.tm-control-fake/, which git ignores."""
    monkeypatch.chdir(tmp_path)
    s = Settings.from_env({"TM_CONTROL_FAKE": "1"})
    assert s.state_dir == tmp_path / ".tm-control-fake" / "state"
    assert s.runtime_dir == tmp_path / ".tm-control-fake" / "run"
    assert s.setup_code_file == tmp_path / ".tm-control-fake" / "setup-code"


def test_fake_mode_still_follows_the_directory_variables():
    s = Settings.from_env({"TM_CONTROL_FAKE": "1", "TM_CONTROL_STATE_DIR": "/a", "TM_CONTROL_RUNTIME_DIR": "/b"})
    assert (s.state_dir, s.runtime_dir) == (Path("/a"), Path("/b"))


def test_manifest_fixture_loads():
    m = load_manifest(FIXTURES / "manifest.json")
    assert m.installing_user == "pi" and "frigate.conf" in m.revproxy_locations
    assert m.tm_version == "0.7.1-test" and m.git.branch == "test"
    assert m.probes.hevc_device == "/dev/rpi-hevc-dec" and len(m.probes.radar_paths) == 4
    assert m.homepage.colors["background"] == "#0C1120"


def test_manifest_error_names_the_path_not_the_content(tmp_path):
    path = tmp_path / "manifest.json"
    path.write_text("password: x\n")
    with pytest.raises(ManifestError) as error:
        load_manifest(path)
    assert str(path) in str(error.value)
    assert "password" not in str(error.value)
    assert error.value.__cause__ is None and error.value.__suppress_context__


def test_manifest_error_for_a_bad_field_names_the_field_not_the_value(tmp_path):
    doc = json.loads((FIXTURES / "manifest.json").read_text())
    doc["manifest_version"] = "secret-looking-value"
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(doc))
    with pytest.raises(ManifestError) as error:
        load_manifest(path)
    assert "manifest_version" in str(error.value)
    assert "secret-looking-value" not in str(error.value)


def test_missing_manifest_names_the_path(tmp_path):
    with pytest.raises(ManifestError, match="nope.json"):
        load_manifest(tmp_path / "nope.json")


def test_missing_secret_names_only_the_secret(tmp_path):
    with pytest.raises(MissingSecret) as error:
        Secrets(tmp_path).session_key
    assert error.value.name == "tm_control_session_key"
    assert "tm_control_session_key" in str(error.value)
    assert str(tmp_path) not in str(error.value)


def test_secrets_are_read_with_whitespace_stripped(tmp_path):
    (tmp_path / "frigate_proxy_secret").write_text("placeholder-value\n")
    (tmp_path / "node_red_token_key").write_text("  \n")
    secrets = Secrets(tmp_path)
    assert secrets.frigate_proxy_secret == "placeholder-value"
    with pytest.raises(MissingSecret):
        secrets.node_red_token_key


def test_secrets_require_the_internal_token(settings):
    """tm-control reads Node-RED's /tm-internal/status with node_red_internal_token, so it doesn't start without it,
    and diagnostics redacts it with the other device secrets."""
    assert NODE_RED_INTERNAL_TOKEN == "node_red_internal_token"
    assert NODE_RED_INTERNAL_TOKEN in NAMES and NODE_RED_INTERNAL_TOKEN in DEVICE_SECRETS
    settings = dataclasses.replace(settings, fake=False)
    settings.secrets_dir.mkdir(parents=True)
    for name in NAMES:
        if name != NODE_RED_INTERNAL_TOKEN:
            (settings.secrets_dir / name).write_text(f"test-{name}-value\n")
    with pytest.raises(MissingSecret) as error:
        create_app(settings)
    assert error.value.name == NODE_RED_INTERNAL_TOKEN
    (settings.secrets_dir / NODE_RED_INTERNAL_TOKEN).write_text("test-internal-token-value\n")
    assert Secrets(settings.secrets_dir).node_red_internal_token == "test-internal-token-value"
    create_app(settings)


def test_fake_secrets_are_fixed_strings():
    assert FakeSecrets().session_key == FakeSecrets().session_key
    assert len({FakeSecrets().session_key, FakeSecrets().frigate_proxy_secret, FakeSecrets().node_red_token_key}) == 3


def test_command_runner_caps_output_and_times_out():
    r = run(["sh", "-c", "yes | head -c 100000"], max_output=1000)
    assert r.returncode == 0 and not r.timed_out
    assert 1000 < len(r.stdout) <= 1000 + 40
    r2 = run(["sleep", "5"], timeout=0.2)
    assert r2.timed_out


def test_command_runner_passes_input_and_keeps_stderr():
    r = run(["sh", "-c", "cat; echo oops >&2; exit 3"], input=b"hello")
    assert (r.returncode, r.stdout, r.stderr, r.timed_out) == (3, "hello", "oops\n", False)


def test_command_runner_refuses_a_command_string():
    with pytest.raises(TypeError):
        run("echo hi")


def test_command_runner_adds_to_the_environment(monkeypatch):
    monkeypatch.setenv("TM_TEST_KEPT", "kept")
    r = run(["sh", "-c", 'printf "%s %s" "$TZ" "$TM_TEST_KEPT"'], env={"TZ": "UTC"})
    assert (r.returncode, r.stdout) == (0, "UTC kept")
    monkeypatch.setenv("TZ", "Europe/Berlin")
    assert run(["sh", "-c", 'printf "%s" "$TZ"']).stdout == "Europe/Berlin"
