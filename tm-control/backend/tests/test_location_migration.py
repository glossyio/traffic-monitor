"""tm-control migrate's deployment steps on Node-RED's config.yml: add deployment.database_precision, and remove the
per-sensor lat/lon that the location being per unit made meaningless. Migrate runs as root and never opens
state.sqlite; the printed lines name keys and sensors, never a value."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from ruamel.yaml import YAML

from tm_control.core import migrate
from tm_control.core.secrets import ENTERED_SECRETS

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SENSOR_PATH = "sensors.cameras.picam_h265"


def data(text):
    return YAML(typ="safe", pure=True).load(text)


def output(capsys):
    captured = capsys.readouterr()
    return captured.out + captured.err


@pytest.fixture
def secrets_dir(tmp_path):
    path = tmp_path / "secrets"
    path.mkdir()
    for name in ENTERED_SECRETS:
        (path / name).write_text("")
    return path


@pytest.fixture
def config_yml(tmp_path):
    path = tmp_path / "config.yml"
    shutil.copy(FIXTURES / "node_red_config_ok.yml", path)
    return path


def backups(config):
    return list(config.parent.glob("config.yml.*.bak"))


def test_migrate_adds_database_precision_once(config_yml, secrets_dir, capsys):
    original = config_yml.read_text()
    assert migrate.run_node_red(config_yml, secrets_dir) == 0

    new = config_yml.read_text()
    assert "    bearing: 'n'\n    database_precision: '2'\n\nsensors:" in new  # quoted, after bearing, blank line kept
    expected = data(original)
    expected["deployment"]["database_precision"] = "2"
    assert data(new) == expected
    printed = output(capsys)
    assert f"{config_yml}: added deployment.database_precision (backup: " in printed
    assert len(backups(config_yml)) == 1

    assert migrate.run_node_red(config_yml, secrets_dir) == 0
    assert output(capsys) == f"tm-control migrate: {config_yml}: up to date\n"
    assert config_yml.read_text() == new
    assert len(backups(config_yml)) == 1


def test_migrate_puts_database_precision_after_survey_id(config_yml, secrets_dir):
    text = config_yml.read_text().replace(
        "    bearing: 'n'\n", "    bearing: 'n'\n    survey_id: 0123abcd-si  # the place\n"
    )
    config_yml.write_text(text)
    assert migrate.run_node_red(config_yml, secrets_dir) == 0
    assert "    survey_id: 0123abcd-si  # the place\n    database_precision: '2'\n\nsensors:" in config_yml.read_text()


def test_migrate_keeps_a_precision_the_file_has(config_yml, secrets_dir, capsys):
    text = config_yml.read_text().replace("    bearing: 'n'\n", "    bearing: 'n'\n    database_precision: 'none'\n")
    config_yml.write_text(text)
    assert migrate.run_node_red(config_yml, secrets_dir) == 0
    assert output(capsys) == f"tm-control migrate: {config_yml}: up to date\n"
    assert config_yml.read_text() == text


def test_migrate_leaves_a_file_without_a_deployment_block_alone(config_yml, secrets_dir, capsys):
    text = config_yml.read_text().replace("deployment:\n    lat: 45.0\n    lon: -122.0\n    bearing: 'n'\n\n", "")
    assert "deployment:" not in text
    config_yml.write_text(text)
    assert migrate.run_node_red(config_yml, secrets_dir) == 0
    assert output(capsys) == f"tm-control migrate: {config_yml}: up to date\n"
    assert config_yml.read_text() == text


def with_sensor_coordinates(config_yml, block):
    text = config_yml.read_text().replace(
        "            camera_radar: TM_RADAR_SERIAL_PORT_00\n",
        "            camera_radar: TM_RADAR_SERIAL_PORT_00\n" + block,
    )
    config_yml.write_text(text)
    return text


def test_migrate_removes_per_sensor_coordinates_and_names_the_sensor(config_yml, secrets_dir, capsys):
    with_sensor_coordinates(
        config_yml, "            deployment:\n                lat: 45.0\n                lon: -122.0\n                bearing: 'e'\n"
    )
    assert migrate.run_node_red(config_yml, secrets_dir) == 0

    config = data(config_yml.read_text())
    assert config["sensors"]["cameras"]["picam_h265"]["deployment"] == {"bearing": "e"}
    assert config["deployment"]["lat"] == 45.0  # the top-level location stays
    printed = output(capsys)
    assert f"removed lat/lon under {SENSOR_PATH}.deployment; the location is per unit" in printed
    assert "45.0" not in printed and "-122.0" not in printed  # with the sign: the backup's name has a time stamp


def test_migrate_prunes_a_deployment_block_the_removal_empties(config_yml, secrets_dir, capsys):
    with_sensor_coordinates(config_yml, "            deployment:\n                lat: 45.0\n                lon: -122.0\n")
    assert migrate.run_node_red(config_yml, secrets_dir) == 0

    camera = data(config_yml.read_text())["sensors"]["cameras"]["picam_h265"]
    assert camera == {"enabled": True, "camera_radar": "TM_RADAR_SERIAL_PORT_00"}  # the sensor itself stays
    assert "removed lat/lon under" in output(capsys)


@pytest.mark.parametrize("block", ["lat: 45.0", "lon: -122.0", "lat:\n                lon:"])
def test_migrate_removes_either_key_alone(config_yml, secrets_dir, block, capsys):
    with_sensor_coordinates(config_yml, f"            deployment:\n                {block}\n                bearing: 'w'\n")
    assert migrate.run_node_red(config_yml, secrets_dir) == 0
    assert data(config_yml.read_text())["sensors"]["cameras"]["picam_h265"]["deployment"] == {"bearing": "w"}
    capsys.readouterr()
    assert migrate.run_node_red(config_yml, secrets_dir) == 0
    assert output(capsys) == f"tm-control migrate: {config_yml}: up to date\n"


def test_migrate_ignores_a_sensor_deployment_with_only_a_bearing(config_yml, secrets_dir, capsys):
    text = with_sensor_coordinates(config_yml, "            deployment:\n                bearing: 'e'\n")
    migrate.run_node_red(config_yml, secrets_dir)
    capsys.readouterr()
    after_precision = config_yml.read_text()
    assert after_precision.replace("    database_precision: '2'\n", "") == text
    assert migrate.run_node_red(config_yml, secrets_dir) == 0
    assert output(capsys) == f"tm-control migrate: {config_yml}: up to date\n"


def test_migrate_dry_run_reports_both_steps_and_writes_nothing(config_yml, secrets_dir, capsys):
    with_sensor_coordinates(config_yml, "            deployment:\n                lat: 45.0\n                lon: -122.0\n")
    before = config_yml.read_text()
    assert migrate.run_node_red(config_yml, secrets_dir, dry_run=True) == 0
    printed = output(capsys)
    assert "would add deployment.database_precision, remove lat/lon under" in printed
    assert config_yml.read_text() == before and backups(config_yml) == []


def test_migrate_never_opens_the_state_database(config_yml, secrets_dir, monkeypatch):
    from tm_control.core import state

    def refuse(*args, **kwargs):
        raise AssertionError("migrate must not touch state.sqlite")

    monkeypatch.setattr(state.State, "connect", refuse)
    monkeypatch.setattr(state.State, "migrate", refuse)
    assert migrate.run_node_red(config_yml, secrets_dir) == 0


def test_importing_migrate_does_not_import_the_modules_package():
    """Migrate runs as root after the secret files are written; an import failure in any module must not reach it."""
    code = "\n".join([
        "import sys, tm_control.core.migrate",
        "sys.exit(any(name.startswith('tm_control.modules') for name in sys.modules))",
    ])
    package_root = Path(migrate.__file__).resolve().parents[2]
    env = {**os.environ, "PYTHONPATH": str(package_root)}
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env)
    assert done.returncode == 0, done.stderr
