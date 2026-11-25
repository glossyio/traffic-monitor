"""tm-control migrate's deployment steps on Node-RED's config.yml. The installer's pass (--node-red-config) adds
deployment.database_precision and removes the per-sensor lat/lon that the location being per unit made meaningless;
it never touches a bearing. Node-RED's start (--node-red-headings) turns an old bearing into a heading_deg and does
nothing else. Migrate never opens state.sqlite; the printed lines name keys and sensors, never a value."""

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
    assert "    heading_deg: 0\n    database_precision: '2'\n\nsensors:" in new  # quoted, after the heading, blank line kept
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
        "    heading_deg: 0\n", "    heading_deg: 0\n    survey_id: 0123abcd-si  # the place\n"
    )
    config_yml.write_text(text)
    assert migrate.run_node_red(config_yml, secrets_dir) == 0
    assert "    survey_id: 0123abcd-si  # the place\n    database_precision: '2'\n\nsensors:" in config_yml.read_text()


def test_migrate_keeps_a_precision_the_file_has(config_yml, secrets_dir, capsys):
    text = config_yml.read_text().replace("    heading_deg: 0\n", "    heading_deg: 0\n    database_precision: 'none'\n")
    config_yml.write_text(text)
    assert migrate.run_node_red(config_yml, secrets_dir) == 0
    assert output(capsys) == f"tm-control migrate: {config_yml}: up to date\n"
    assert config_yml.read_text() == text


def test_migrate_leaves_a_file_without_a_deployment_block_alone(config_yml, secrets_dir, capsys):
    text = config_yml.read_text().replace("deployment:\n    lat: 45.0\n    lon: -122.0\n    heading_deg: 0\n\n", "")
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
        config_yml, "            deployment:\n                lat: 45.0\n                lon: -122.0\n                heading_deg: 90\n"
    )
    assert migrate.run_node_red(config_yml, secrets_dir) == 0

    config = data(config_yml.read_text())
    assert config["sensors"]["cameras"]["picam_h265"]["deployment"] == {"heading_deg": 90}
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
    with_sensor_coordinates(config_yml, f"            deployment:\n                {block}\n                heading_deg: 270\n")
    assert migrate.run_node_red(config_yml, secrets_dir) == 0
    assert data(config_yml.read_text())["sensors"]["cameras"]["picam_h265"]["deployment"] == {"heading_deg": 270}
    capsys.readouterr()
    assert migrate.run_node_red(config_yml, secrets_dir) == 0
    assert output(capsys) == f"tm-control migrate: {config_yml}: up to date\n"


def test_migrate_converts_a_sensor_deployment_with_only_a_bearing(config_yml, capsys):
    with_sensor_coordinates(config_yml, "            deployment:\n                bearing: 'e'\n")
    assert migrate.run_node_red_headings(config_yml) == 0
    config = data(config_yml.read_text())
    assert config["sensors"]["cameras"]["picam_h265"]["deployment"] == {"heading_deg": 90}
    assert f"converted {SENSOR_PATH}.deployment.bearing to heading_deg" in output(capsys)
    assert migrate.run_node_red_headings(config_yml) == 0
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


def test_importing_migrate_does_not_import_the_modules_package_or_the_web_dependencies():
    """Migrate runs as root after the secret files are written; an import failure in any module, or in the web
    dependencies (pydantic comes in with the manifest), must not reach it."""
    code = "\n".join([
        "import sys, tm_control.core.migrate",
        "forbidden = ('tm_control.modules', 'tm_control.core.manifest', 'pydantic', 'fastapi')",
        "sys.exit(any(name == f or name.startswith(f + '.') for name in sys.modules for f in forbidden))",
    ])
    package_root = Path(migrate.__file__).resolve().parents[2]
    env = {**os.environ, "PYTHONPATH": str(package_root)}
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env)
    assert done.returncode == 0, done.stderr


# The placeholder host the old template shipped: a unit that never set a server shouldn't show it as "your own".
PLACEHOLDER_HOST = "tb.server.com"
OTHER_HOST = "tb.example.invalid"


def host_config(tmp_path, host="tb.server.com", enabled="false", comment=""):
    path = tmp_path / "config.yml"
    path.write_text(
        f"thingsboard:\n    enabled: {enabled}\n    host: {host}{comment}\n    protocol: https\n\n"
        "deployment:\n    lat: 45.0\n    lon: -122.0\n    heading_deg: 0\n    database_precision: '2'\n"
    )
    return path


def test_migrates_maintainer_host_is_the_manifests_default_and_the_roles():
    """Migrate keeps its own copy (it may not import the manifest, which needs pydantic); this keeps the three equal."""
    from tm_control.core.manifest import SharingInfo

    role = Path(__file__).resolve().parents[3] / "script/ansible/roles/tmsetup/vars/main.yml"
    roles_host = YAML(typ="safe", pure=True).load(role.read_text())["tmsetup_sharing_maintainer_host"]
    assert migrate.MAINTAINER_HOST == SharingInfo().maintainer_host == roles_host


@pytest.mark.parametrize("value", ["tb.server.com", "'tb.server.com'", '"TB.Server.com"', "HTTPS://TB.SERVER.COM/",
                                   "'http://tb.server.com/'"])
def test_migrate_points_the_placeholder_host_at_the_maintainers_while_the_upload_is_off(
        tmp_path, secrets_dir, capsys, value):
    from tm_control.core.manifest import SharingInfo

    config = host_config(tmp_path, host=value)
    original = config.read_text()
    assert migrate.run_node_red(config, secrets_dir) == 0

    (backup,) = backups(config)
    assert backup.read_text() == original
    assert config.read_text() == original.replace(f"host: {value}\n", f"host: {_quoted_like(value)}\n")
    assert data(config.read_text())["thingsboard"]["host"] == SharingInfo().maintainer_host
    printed = output(capsys)
    assert printed == f"tm-control migrate: {config}: rewrote thingsboard.host (backup: {backup})\n"


def _quoted_like(value):
    from tm_control.core.manifest import SharingInfo

    host = SharingInfo().maintainer_host
    stripped = value.strip()
    return f"{stripped[0]}{host}{stripped[0]}" if stripped[0] in "'\"" else host


def test_migrate_keeps_a_comment_beside_the_rewritten_host(tmp_path, secrets_dir):
    config = host_config(tmp_path, host="'tb.server.com'", comment="  # the server")
    assert migrate.run_node_red(config, secrets_dir) == 0
    (line,) = [l for l in config.read_text().splitlines() if l.startswith("    host:")]
    assert line.startswith("    host: 'tb.roadwaybiome.com'") and line.endswith("# the server")


def test_migrate_leaves_the_placeholder_host_alone_when_the_upload_is_on(tmp_path, secrets_dir, capsys):
    config = host_config(tmp_path, enabled="true")  # its owner chose it
    original = config.read_text()
    assert migrate.run_node_red(config, secrets_dir) == 0
    assert config.read_text() == original
    assert backups(config) == []
    assert output(capsys) == f"tm-control migrate: {config}: up to date\n"


def test_migrate_counts_a_string_enabled_as_off_and_rewrites_the_placeholder_host(tmp_path, secrets_dir):
    config = host_config(tmp_path, enabled="'true'")  # a string, not the boolean true: Node-RED doesn't upload
    assert migrate.run_node_red(config, secrets_dir) == 0
    assert data(config.read_text())["thingsboard"]["host"] == "tb.roadwaybiome.com"
    assert "enabled: 'true'" in config.read_text()


def test_migrate_rewrites_the_placeholder_host_when_there_is_no_enabled_key(tmp_path, secrets_dir):
    config = host_config(tmp_path)
    config.write_text(config.read_text().replace("    enabled: false\n", ""))
    assert migrate.run_node_red(config, secrets_dir) == 0
    assert data(config.read_text())["thingsboard"]["host"] == "tb.roadwaybiome.com"


@pytest.mark.parametrize("host", [OTHER_HOST, "tb.server.com.example.invalid", "tb.server.com:8080", "", "~"])
def test_migrate_leaves_any_other_host_alone(tmp_path, secrets_dir, capsys, host):
    config = host_config(tmp_path, host=host)
    original = config.read_text()
    assert migrate.run_node_red(config, secrets_dir) == 0
    assert config.read_text() == original
    assert backups(config) == []
    assert output(capsys) == f"tm-control migrate: {config}: up to date\n"


def test_migrate_leaves_a_config_without_a_host_alone(tmp_path, secrets_dir, capsys):
    config = tmp_path / "config.yml"
    config.write_text("thingsboard:\n    enabled: false\n\ndeployment:\n    heading_deg: 0\n    database_precision: '2'\n")
    original = config.read_text()
    assert migrate.run_node_red(config, secrets_dir) == 0
    assert config.read_text() == original
    assert output(capsys) == f"tm-control migrate: {config}: up to date\n"


def test_a_second_run_has_nothing_to_do_for_the_host(tmp_path, secrets_dir, capsys):
    config = host_config(tmp_path)
    assert migrate.run_node_red(config, secrets_dir) == 0
    capsys.readouterr()
    after_first = config.read_text()
    assert migrate.run_node_red(config, secrets_dir) == 0
    assert config.read_text() == after_first
    assert len(backups(config)) == 1
    assert output(capsys) == f"tm-control migrate: {config}: up to date\n"


def test_migrate_dry_run_reports_the_host_step_and_writes_nothing(tmp_path, secrets_dir, capsys):
    config = host_config(tmp_path)
    original = config.read_text()
    assert migrate.run_node_red(config, secrets_dir, dry_run=True) == 0
    assert config.read_text() == original
    assert backups(config) == []
    assert output(capsys) == f"tm-control migrate: {config}: would rewrite thingsboard.host\n"


def test_migrate_prints_no_host_value(tmp_path, secrets_dir, capsys):
    config = host_config(tmp_path, host="HTTPS://TB.SERVER.COM/")
    for dry_run in (True, False):
        migrate.run_node_red(config, secrets_dir, dry_run=dry_run)
    printed = output(capsys).lower()
    assert "server.com" not in printed and "roadwaybiome" not in printed


def test_the_migrate_host_rule_matches_the_sharing_normaliser():
    from tm_control.modules.sharing.consents import normalize_host

    for value in ["tb.server.com", " HTTPS://TB.SERVER.COM/ ", "http://tb.server.com", "tb.server.com//", "x", "", None, 5]:
        assert migrate._normalized_host(value) == normalize_host(value)


# The old bearing key: one of the eight compass points becomes its centre, in the key's place and with its comment.
OLD_TOP = "deployment:\n    lat: 45.0\n    lon: -122.0\n    heading_deg: 0\n"
OLD_CAMERA = "            camera_radar: TM_RADAR_SERIAL_PORT_00\n"


def old_bearings(config_yml, top, camera=None, precision=True):
    """The fixture with its top-level heading replaced by `top` (the text of one or more lines, 4 spaces in), and a
    sensor deployment block with `camera` under the camera. database_precision is in the file unless precision is
    False, so the bearing's conversion is the only step."""
    text = config_yml.read_text().replace("    heading_deg: 0\n", top + ("    database_precision: '2'\n" if precision else ""))
    if camera is not None:
        text = text.replace(OLD_CAMERA, OLD_CAMERA + "            deployment:\n" + camera)
    config_yml.write_text(text)
    return text


def test_migrate_writes_heading_deg_in_place_of_bearing(config_yml, capsys):
    original = old_bearings(
        config_yml, "    bearing: 'ne'  # the road faces this way\n    survey_id: 0123abcd-si\n",
        "                bearing: ' SW '  # this camera\n",
    )
    assert migrate.run_node_red_headings(config_yml) == 0

    new = config_yml.read_text()
    assert new == original.replace("bearing: 'ne'  # the road", "heading_deg: 45  # the road").replace(
        "bearing: ' SW '  # this camera", "heading_deg: 225  # this camera"
    )
    config = data(new)
    assert config["deployment"]["heading_deg"] == 45 and "bearing" not in config["deployment"]
    camera = config["sensors"]["cameras"]["picam_h265"]["deployment"]
    assert camera == {"heading_deg": 225}
    printed = output(capsys)
    assert "converted deployment.bearing to heading_deg" in printed
    assert f"converted {SENSOR_PATH}.deployment.bearing to heading_deg" in printed
    (backup,) = backups(config_yml)
    assert backup.read_text() == original
    assert "'ne'" not in printed and "SW" not in printed


@pytest.mark.parametrize("blank", ["''", "", '""'])
def test_migrate_converts_a_blank_bearing_to_a_blank_heading(config_yml, blank):
    old_bearings(config_yml, f"    bearing: {blank}  # none yet\n")
    assert migrate.run_node_red_headings(config_yml) == 0
    new = config_yml.read_text()
    assert "    heading_deg:  # none yet\n" in new
    assert data(new)["deployment"]["heading_deg"] is None and "bearing" not in new


def test_migrate_leaves_a_bearing_it_cannot_read_and_warns_by_key(config_yml, capsys):
    original = old_bearings(config_yml, "    bearing: sideways\n", "                bearing: 90\n")
    assert migrate.run_node_red_headings(config_yml) == 0
    assert config_yml.read_text() == original and backups(config_yml) == []
    printed = output(capsys)
    for path in ("deployment.bearing", f"{SENSOR_PATH}.deployment.bearing"):
        assert f"WARNING {config_yml}: {path} isn't one of the eight compass points" in printed
    shown = printed.replace(str(config_yml), "")  # pytest's temporary path can hold any digits, such as 90
    assert "sideways" not in shown and "90" not in shown
    assert "up to date" in printed


def test_migrate_removes_a_bearing_beside_a_heading(config_yml, capsys):
    original = old_bearings(
        config_yml, "    heading_deg: 100\n    bearing: sideways\n", "                heading_deg: 40\n                bearing: 'n'\n"
    )
    assert migrate.run_node_red_headings(config_yml) == 0
    config = data(config_yml.read_text())
    assert config["deployment"]["heading_deg"] == 100 and "bearing" not in config["deployment"]
    assert config["sensors"]["cameras"]["picam_h265"]["deployment"] == {"heading_deg": 40}
    printed = output(capsys)
    assert "removed deployment.bearing, which sits beside heading_deg" in printed
    assert "WARNING" not in printed and "sideways" not in printed
    assert backups(config_yml)[0].read_text() == original


@pytest.mark.parametrize("blank", ["", "''", "null"])
def test_migrate_gives_a_blank_heading_the_centre_of_a_bearing_beside_it(config_yml, blank):
    """As Node-RED reads such a block: a blank heading_deg takes its bearing's centre."""
    old_bearings(config_yml, f"    heading_deg: {blank}\n    bearing: ' W'\n")
    assert migrate.run_node_red_headings(config_yml) == 0
    config = data(config_yml.read_text())
    assert config["deployment"]["heading_deg"] == 270 and "bearing" not in config["deployment"]


def test_migrate_removes_a_blank_bearing_beside_a_blank_heading(config_yml):
    old_bearings(config_yml, "    heading_deg:\n    bearing: ''\n")
    assert migrate.run_node_red_headings(config_yml) == 0
    config = data(config_yml.read_text())
    assert config["deployment"]["heading_deg"] is None and "bearing" not in config["deployment"]


def test_migrate_converts_a_disabled_sensors_bearing_too(config_yml):
    text = config_yml.read_text().replace(
        "            enabled: false\n", "            enabled: false\n            deployment:\n                bearing: 's'\n"
    )
    config_yml.write_text(text)
    assert migrate.run_node_red_headings(config_yml) == 0
    sensor = data(config_yml.read_text())["sensors"]["airquality_monitors"]["sensorname01"]
    assert sensor["deployment"] == {"heading_deg": 180}


def test_migrate_twice_changes_nothing(config_yml, capsys):
    old_bearings(config_yml, "    bearing: 'e'\n", "                bearing: 'w'\n")
    assert migrate.run_node_red_headings(config_yml) == 0
    capsys.readouterr()
    converted = config_yml.read_text()
    assert migrate.run_node_red_headings(config_yml) == 0
    assert output(capsys) == f"tm-control migrate: {config_yml}: up to date\n"
    assert config_yml.read_text() == converted and len(backups(config_yml)) == 1


def test_migrate_dry_run_says_what_it_would_do(config_yml, capsys):
    original = old_bearings(config_yml, "    bearing: 'e'\n", "                bearing: 'w'\n")
    assert migrate.run_node_red_headings(config_yml, dry_run=True) == 0
    assert output(capsys) == (
        f"tm-control migrate: {config_yml}: would convert deployment.bearing to heading_deg, "
        f"convert {SENSOR_PATH}.deployment.bearing to heading_deg\n"
    )
    assert config_yml.read_text() == original and backups(config_yml) == []


def test_the_installer_pass_places_database_precision_after_a_bearing_it_leaves(config_yml, secrets_dir):
    """After survey_id when there is one, else after the heading, else after the bearing that the start then converts
    in place, so the precision ends up after the heading."""
    old_bearings(config_yml, "    bearing: 'se'\n", precision=False)
    assert migrate.run_node_red(config_yml, secrets_dir) == 0
    assert "    bearing: 'se'\n    database_precision: '2'\n\nsensors:" in config_yml.read_text()
    assert migrate.run_node_red_headings(config_yml) == 0
    assert "    heading_deg: 135\n    database_precision: '2'\n\nsensors:" in config_yml.read_text()

    shutil.copy(FIXTURES / "node_red_config_ok.yml", config_yml)
    old_bearings(config_yml, "    bearing: 'se'\n    survey_id: 0123abcd-si\n", precision=False)
    assert migrate.run_node_red(config_yml, secrets_dir) == 0
    assert "    survey_id: 0123abcd-si\n    database_precision: '2'\n" in config_yml.read_text()


def test_migrate_places_database_precision_in_a_freshly_rendered_file(config_yml, secrets_dir):
    assert "bearing" not in config_yml.read_text()
    assert migrate.run_node_red(config_yml, secrets_dir) == 0
    assert "    heading_deg: 0\n    database_precision: '2'\n" in config_yml.read_text()


def test_migrates_compass_points_are_the_location_modules():
    """Migrate may not import the modules package (see the import test above), so it keeps its own copy."""
    from tm_control.modules.location import coordinates

    assert migrate.COMPASS_POINTS == coordinates.POINTS


# The installer's pass never touches a bearing. The rule: the installer pass may not change a key that a running engine
# compares. It runs while the old Node-RED is still up, and that Node-RED's config watch (5ffb7c9c38b8c5b0, in v0.7.1
# and dev before the heading) re-reads config.yml and compares each block's bearing (and survey_id) with the open
# deployment row: a change there closes the row and starts another. Node-RED's own start converts the bearing, with
# no flows running (--node-red-headings, the ExecStartPre in node-red-tm.container.j2).
EVERY_KIND_OF_BEARING = (
    "    bearing: 'ne'\n",  # convert
    "                heading_deg:\n                bearing: 'w'\n",  # fill
)


def every_kind_of_bearing(config_yml):
    """Convert (top level), fill (camera), remove (radar), unreadable (air quality), with database_precision in place,
    so a bearing is all there is to change."""
    old_bearings(config_yml, *EVERY_KIND_OF_BEARING)
    text = config_yml.read_text().replace(
        "            opt_api_commands_array:",
        "            deployment:\n                heading_deg: 40\n                bearing: 'n'\n            opt_api_commands_array:",
    ).replace(
        "            enabled: false\n", "            enabled: false\n            deployment:\n                bearing: sideways\n"
    )
    config_yml.write_text(text)
    return text


def test_the_installer_pass_leaves_every_kind_of_bearing_alone(config_yml, secrets_dir, capsys):
    original = every_kind_of_bearing(config_yml)
    assert migrate.run_node_red(config_yml, secrets_dir) == 0
    assert config_yml.read_text() == original and backups(config_yml) == []
    assert output(capsys) == f"tm-control migrate: {config_yml}: up to date\n"  # and no warning either


def test_the_installer_pass_does_its_other_steps_and_keeps_every_bearing_line(config_yml, secrets_dir, capsys):
    original = every_kind_of_bearing(config_yml).replace("    database_precision: '2'\n", "")
    config_yml.write_text(original)
    text = config_yml.read_text().replace(
        "                heading_deg:\n                bearing: 'w'\n",
        "                lat: 45.0\n                lon: -122.0\n                heading_deg:\n                bearing: 'w'\n",
    )
    config_yml.write_text(text)
    assert migrate.run_node_red(config_yml, secrets_dir) == 0
    new = config_yml.read_text()
    assert data(new)["deployment"]["database_precision"] == "2"
    assert "lat" not in data(new)["sensors"]["cameras"]["picam_h265"]["deployment"]
    assert [line for line in new.splitlines() if "bearing" in line] == [
        line for line in text.splitlines() if "bearing" in line
    ]
    printed = output(capsys)
    assert "bearing" not in printed and "WARNING" not in printed


def sensor_blocks(config):
    """{path: (bearing, survey_id)} for the top-level deployment block and each sensor's own, a missing key as None."""
    found = {"deployment": config.get("deployment") or {}}
    for sensor_type, named in (config.get("sensors") or {}).items():
        for name, sensor in (named or {}).items():
            if isinstance((sensor or {}).get("deployment"), dict):
                found[f"sensors.{sensor_type}.{name}"] = sensor["deployment"]
    return {path: (block.get("bearing", "missing"), block.get("survey_id", "missing")) for path, block in found.items()}


@pytest.mark.parametrize("fixture", ["node_red_config_v071_bearing.yml", "node_red_config_dev_bearing.yml"])
def test_the_installer_pass_changes_no_key_a_running_engine_compares(tmp_path, secrets_dir, fixture):
    """The guard for the rule above, on a file shaped like v0.7.1's and one like dev's before the heading: the pass
    still has work to do on each (the old placeholder host, the empty token, the stored precision, a sensor's own
    lat/lon), and every bearing and survey_id stays as it was."""
    config = tmp_path / "config.yml"
    shutil.copy(FIXTURES / fixture, config)
    before = config.read_text()
    assert migrate.run_node_red(config, secrets_dir) == 0
    assert config.read_text() != before  # it did change something
    assert sensor_blocks(data(config.read_text())) == sensor_blocks(data(before))


# Node-RED's start: --node-red-headings changes the bearings and nothing else.
def test_the_start_converts_every_kind_of_bearing(config_yml, capsys):
    original = every_kind_of_bearing(config_yml)
    assert migrate.run_node_red_headings(config_yml) == 0
    config = data(config_yml.read_text())
    assert config["deployment"]["heading_deg"] == 45 and "bearing" not in config["deployment"]
    assert config["sensors"]["cameras"]["picam_h265"]["deployment"] == {"heading_deg": 270}
    assert config["sensors"]["radars"]["TM_RADAR_SERIAL_PORT_00"]["deployment"] == {"heading_deg": 40}
    assert config["sensors"]["airquality_monitors"]["sensorname01"]["deployment"] == {"bearing": "sideways"}
    printed = output(capsys)
    assert (
        "WARNING {}: sensors.airquality_monitors.sensorname01.deployment.bearing isn't one of the eight compass "
        "points".format(config_yml)
    ) in printed
    assert "sideways" not in printed
    (backup,) = backups(config_yml)
    assert backup.read_text() == original
    assert f"(backup: {backup})" in printed


@pytest.mark.parametrize("fixture", ["node_red_config_v071_bearing.yml", "node_red_config_dev_bearing.yml"])
def test_the_start_does_none_of_the_installers_steps(tmp_path, fixture, capsys):
    """The host, the token, the precision, and a sensor's own lat/lon are the installer pass's; only bearings change."""
    config = tmp_path / "config.yml"
    shutil.copy(FIXTURES / fixture, config)
    before = data(config.read_text())
    assert migrate.run_node_red_headings(config) == 0
    after = data(config.read_text())
    for block in [after["deployment"], *[
        sensor.get("deployment") or {} for named in after["sensors"].values() for sensor in named.values()
    ]]:
        block.pop("heading_deg", None)
        block.pop("bearing", None)
    for block in [before["deployment"], *[
        sensor.get("deployment") or {} for named in before["sensors"].values() for sensor in named.values()
    ]]:
        block.pop("heading_deg", None)
        block.pop("bearing", None)
    assert after == before
    assert "database_precision" not in output(capsys)


def test_the_start_has_nothing_to_do_on_a_file_with_no_bearing(config_yml, capsys):
    """Even when the installer's steps are due (no database_precision here): they aren't the start's."""
    text = config_yml.read_text()
    assert migrate.run_node_red_headings(config_yml) == 0
    assert output(capsys) == f"tm-control migrate: {config_yml}: up to date\n"
    assert config_yml.read_text() == text and backups(config_yml) == []


def test_the_start_reads_no_secrets(config_yml, monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("the start's step has no secrets to move")

    monkeypatch.setattr(migrate, "_read_secret", refuse)
    monkeypatch.setattr(migrate, "_write_secret", refuse)
    every_kind_of_bearing(config_yml)
    assert migrate.run_node_red_headings(config_yml) == 0


def test_the_start_reports_a_file_it_cannot_read(tmp_path, capsys):
    assert migrate.run_node_red_headings(tmp_path / "missing.yml") == 1
    assert f"ERROR reading {tmp_path / 'missing.yml'}" in output(capsys)
