"""The configuration checks: the names that config.yml and Frigate's config must agree on (CLAUDE.md, "Cross-component
name contracts"), and the deployment values."""

import pytest

from tm_control.core.checks import run_group
from tm_control.modules.apps import contracts

FRIGATE_CONFIG = "http://127.0.0.1:5000/api/config"  # what the `apps` fixture answers (conftest.FakeApps)
FRIGATE_VERSION = "http://127.0.0.1:5000/api/version"


def config_group(apps):
    group = run_group(contracts.GROUP, apps.context())
    assert group.title == "Configuration"
    return {check.id: check for check in group.checks}


def test_cameras_match(apps):
    checks = config_group(apps)
    assert list(checks) == ["config.cameras", "config.zones", "config.radars", "config.deployment"]
    assert [c.title for c in checks.values()] == ["Cameras in config.yml", "Zones", "Radar names", "Location"]
    assert {c.id: c.status for c in checks.values()} == dict.fromkeys(checks, "ok")


def test_disabled_camera_is_an_error(apps):
    apps.edit_config_yml(lambda data: data["sensors"]["cameras"]["picam_h265"].update(enabled=False))
    check = config_group(apps)["config.cameras"]
    assert check.status == "error"
    assert "events from picam_h265 are not recorded" in check.detail.lower()


def test_a_renamed_camera_is_an_error(apps):
    """#249: the camera was renamed in Frigate but not in config.yml."""

    def rename(config):
        config["cameras"]["front_street"] = config["cameras"].pop("picam_h265")

    apps.edit_json(FRIGATE_CONFIG, rename)
    check = config_group(apps)["config.cameras"]
    assert check.status == "error"
    assert "front_street" in check.detail and "not recorded" in check.detail


def test_a_config_camera_frigate_doesnt_have_is_a_warning(apps):
    apps.edit_config_yml(lambda data: data["sensors"]["cameras"].update(side_street={"enabled": True}))
    check = config_group(apps)["config.cameras"]
    assert check.status == "warn"
    assert "side_street" in check.detail


def test_cameras_and_zones_are_unknown_when_frigate_is_down(apps):
    apps.answers[FRIGATE_VERSION] = (None, None)
    checks = config_group(apps)
    assert checks["config.cameras"].status == "unknown"
    assert checks["config.zones"].status == "unknown"
    assert checks["config.radars"].status == "ok"
    assert checks["config.deployment"].status == "ok"


def test_every_check_is_unknown_when_config_yml_has_a_yaml_error(apps):
    apps.config_yml.write_text("sensors:\n  cameras: [unclosed\n")
    checks = config_group(apps)
    assert {c.status for c in checks.values()} == {"unknown"}
    assert all("unclosed" not in c.detail for c in checks.values())


def test_missing_zones_name_the_direction_problem(apps):
    def drop(config):
        zones = config["cameras"]["picam_h265"]["zones"]
        del zones["zone_near"], zones["zone_far"]

    apps.edit_json(FRIGATE_CONFIG, drop)
    check = config_group(apps)["config.zones"]
    assert check.status == "warn"
    assert "zone_near" in check.detail and "zone_far" in check.detail and "picam_h265" in check.detail
    assert "without zone_near and zone_far, events get no direction (#243)" in check.detail


def test_a_missing_capture_zone_is_a_warning_without_the_direction_note(apps):
    apps.edit_json(FRIGATE_CONFIG, lambda config: config["cameras"]["picam_h265"]["zones"].pop("zone_capture"))
    check = config_group(apps)["config.zones"]
    assert check.status == "warn"
    assert "zone_capture" in check.detail and "#243" not in check.detail


def test_zones_of_a_camera_disabled_in_config_yml_arent_checked(apps):
    def disable(data):
        data["sensors"]["cameras"]["picam_h265"]["enabled"] = False

    apps.edit_config_yml(disable)
    apps.edit_json(FRIGATE_CONFIG, lambda config: config["cameras"]["picam_h265"]["zones"].clear())
    assert config_group(apps)["config.zones"].status == "ok"


def test_radar_name_must_be_an_env_name(apps):
    apps.edit_config_yml(lambda data: data["sensors"]["radars"].update(front_radar={"enabled": True}))
    check = config_group(apps)["config.radars"]
    assert check.status == "error"
    assert "front_radar" in check.detail
    assert "TM_RADAR_SERIAL_PORT_00" in check.detail  # names what it should be


@pytest.mark.parametrize("name", ["TM_RADAR_SERIAL_PORT_04", "tm_radar_serial_port_00", "TM_RADAR_SERIAL_PORT_0"])
def test_radar_names_outside_the_env_names_are_errors(apps, name):
    apps.edit_config_yml(lambda data: data["sensors"]["radars"].update({name: {"enabled": False}}))
    assert config_group(apps)["config.radars"].status == "error"


def test_camera_radar_must_name_an_enabled_radar(apps):
    """#255: a camera paired with a radar that isn't enabled has its events dropped."""
    apps.edit_config_yml(lambda data: data["sensors"]["radars"]["TM_RADAR_SERIAL_PORT_00"].update(enabled=False))
    check = config_group(apps)["config.radars"]
    assert check.status == "error"
    assert (
        "camera picam_h265 is paired with radar TM_RADAR_SERIAL_PORT_00, which isn't enabled; "
        "its events are dropped (#255)"
    ) in check.detail.replace("Camera", "camera")


def test_camera_radar_naming_a_radar_not_in_config_yml_is_an_error(apps):
    apps.edit_config_yml(lambda data: data["sensors"]["cameras"]["picam_h265"].update(
        camera_radar="TM_RADAR_SERIAL_PORT_02"
    ))
    check = config_group(apps)["config.radars"]
    assert check.status == "error" and "TM_RADAR_SERIAL_PORT_02" in check.detail


def test_a_camera_without_a_radar_is_fine(apps):
    apps.edit_config_yml(lambda data: data["sensors"]["cameras"]["picam_h265"].pop("camera_radar"))
    assert config_group(apps)["config.radars"].status == "ok"


@pytest.mark.parametrize(
    "deployment, status, key",
    [
        ({"lat": 91, "lon": 10, "bearing": "n"}, "error", "deployment.lat"),
        ({"lat": -90, "lon": 180.5, "bearing": "n"}, "error", "deployment.lon"),
        ({"lat": "45.1", "lon": 10, "bearing": "n"}, "error", "deployment.lat"),
        ({"lat": True, "lon": 10, "bearing": "n"}, "error", "deployment.lat"),
        ({"lat": 45, "lon": 10, "bearing": "north"}, "error", "deployment.bearing"),
        ({"lat": 45, "lon": 10, "bearing": 90}, "error", "deployment.bearing"),
        ({"lat": 45, "lon": 10, "bearing": ""}, "ok", None),
        ({"lat": 45, "lon": 10, "bearing": "SW"}, "ok", None),  # Node-RED lowercases it
        ({"lat": None, "lon": None, "bearing": ""}, "ok", None),  # as installed, before a location is set
        ({"lat": -90, "lon": -180, "bearing": "se"}, "ok", None),
    ],
)
def test_deployment_values(apps, deployment, status, key):
    apps.edit_config_yml(lambda data: data.update(deployment=deployment))
    check = config_group(apps)["config.deployment"]
    assert check.status == status, check.detail
    if key:
        assert key in check.detail
        value = deployment[key.removeprefix("deployment.")]
        if isinstance(value, str):
            assert value not in check.detail  # names the key, not its value
        assert "91" not in check.detail and "180.5" not in check.detail


def test_deployment_missing_is_ok(apps):
    apps.edit_config_yml(lambda data: data.pop("deployment"))
    assert config_group(apps)["config.deployment"].status == "ok"
