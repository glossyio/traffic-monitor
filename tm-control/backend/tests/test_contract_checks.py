"""The configuration checks: the names that config.yml and Frigate's config must agree on (CLAUDE.md, "Cross-component
name contracts"), and the deployment values."""

import pytest

from tm_control.core.checks import run_group
from tm_control.core.secrets import THINGSBOARD_ACCESS_TOKEN
from tm_control.modules.apps import contracts

FRIGATE_CONFIG = "http://127.0.0.1:5000/api/config"  # what the `apps` fixture answers (conftest.FakeApps)
FRIGATE_VERSION = "http://127.0.0.1:5000/api/version"


def config_group(apps):
    group = run_group(contracts.GROUP, apps.context())
    assert group.title == "Configuration"
    return {check.id: check for check in group.checks}


def test_cameras_match(apps):
    checks = config_group(apps)
    assert list(checks) == [
        "config.cameras", "config.zones", "config.radars", "config.deployment", "config.thingsboard",
    ]
    assert [c.title for c in checks.values()] == [
        "Cameras in config.yml", "Zones", "Radar names", "Location", "ThingsBoard upload",
    ]
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
    assert checks["config.thingsboard"].status == "ok"


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
    assert "without zone_near and zone_far, events get a direction only from the radar (#243)" in check.detail


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


# ThingsBoard upload. The fixture's thingsboard block is the template's: enabled false, a host, protocol http.

HOST = "tb.example.invalid"  # the fixture's host, which no detail may show
MISSING_TOKEN = "The upload is on in config.yml, but no access token is set, so Node-RED keeps it off."


def thingsboard_check(apps):
    check = config_group(apps)["config.thingsboard"]
    assert HOST not in check.detail and "example.invalid" not in check.detail
    return check


def edit_thingsboard(apps, **values):
    apps.edit_config_yml(lambda data: data["thingsboard"].update(values))


def test_thingsboard_off_is_ok(apps):
    check = thingsboard_check(apps)
    assert check.status == "ok" and check.detail == "The upload is off." and check.fix is None


def test_thingsboard_on_without_a_token_is_a_warning_with_a_link(apps):
    edit_thingsboard(apps, enabled=True)
    check = thingsboard_check(apps)
    assert check.status == "warn" and check.detail == MISSING_TOKEN
    assert check.fix is not None
    assert (check.fix.kind, check.fix.text, check.fix.href) == ("link", "Set the token", "/device#tokens-and-keys")


def test_thingsboard_on_with_a_token_is_ok(apps):
    edit_thingsboard(apps, enabled=True)
    apps.secrets.entered[THINGSBOARD_ACCESS_TOKEN] = "tb-placeholder-8"
    check = thingsboard_check(apps)
    assert check.status == "ok" and check.detail == "The upload is on, with a token set."
    assert "placeholder" not in check.detail


def _put(data, key, value):
    parent, child = key.rsplit(".", 1)
    section = data
    for part in parent.split("."):
        section = section.setdefault(part, {})
    section[child] = value


@pytest.mark.parametrize("key", ["thingsboard.access_token", "addons.plate_recognizer.token"])
@pytest.mark.parametrize("value", ["tb-placeholder-9", None, ""])
def test_a_secret_left_in_config_yml_is_a_warning(apps, key, value):
    apps.edit_config_yml(lambda data: _put(data, key, value))
    check = thingsboard_check(apps)
    assert check.status == "warn"
    assert check.detail == (
        f"config.yml still holds {key}, which nothing reads. Remove it; the value is set on the Device page."
    )
    assert "placeholder" not in check.detail and check.fix is None


def _drop_host(data):
    del data["thingsboard"]["host"]


@pytest.mark.parametrize(
    "edit, status, key",
    [
        (lambda data: (data["thingsboard"].update(enabled=True), _drop_host(data)), "error", "thingsboard.host"),
        (lambda data: data["thingsboard"].update(enabled=True, host="  "), "error", "thingsboard.host"),
        (lambda data: data["thingsboard"].update(protocol="ftp"), "error", "thingsboard.protocol"),
        (lambda data: data["thingsboard"].update(protocol="mqtt"), "error", "thingsboard.protocol"),
        (lambda data: data["thingsboard"].update(protocol=None), "error", "thingsboard.protocol"),
        (lambda data: data["thingsboard"].update(enabled="yes"), "error", "thingsboard.enabled"),
        (lambda data: data["thingsboard"].update(host="https://x.example.invalid"), "warn", "thingsboard.host"),
        (lambda data: data["thingsboard"].update(host="HTTP://x.example.invalid"), "warn", "thingsboard.host"),
        (lambda data: data["thingsboard"].update(protocol="https"), "ok", None),
        (lambda data: data["thingsboard"].pop("protocol"), "ok", None),  # Node-RED defaults to https
        (lambda data: data["thingsboard"].pop("host"), "ok", None),  # off, so the host isn't needed
        (lambda data: data.pop("thingsboard"), "ok", None),
        (lambda data: data.update(thingsboard="not a mapping"), "ok", None),
    ],
)
def test_thingsboard_block_values(apps, edit, status, key):
    apps.edit_config_yml(edit)
    check = thingsboard_check(apps)
    assert check.status == status, check.detail
    if key:
        assert key in check.detail
    assert "ftp" not in check.detail and "yes" not in check.detail and "x.example" not in check.detail


def test_two_warnings_are_joined_in_one_detail(apps):
    edit_thingsboard(apps, enabled=True, access_token="tb-placeholder-10")
    check = thingsboard_check(apps)
    assert check.status == "warn"
    assert check.detail == (
        "config.yml still holds thingsboard.access_token, which nothing reads. Remove it; the value is set on the "
        f"Device page. {MISSING_TOKEN}"
    )
    assert check.fix is not None and check.fix.href == "/device#tokens-and-keys"  # kept, since the missing token is among them
    assert "placeholder" not in check.detail


def test_errors_outrank_warnings(apps):
    edit_thingsboard(apps, enabled="yes", protocol="ftp", access_token="tb-placeholder-11")
    check = thingsboard_check(apps)
    assert check.status == "error"
    assert "thingsboard.enabled" in check.detail and "thingsboard.protocol" in check.detail
    assert check.fix is None
