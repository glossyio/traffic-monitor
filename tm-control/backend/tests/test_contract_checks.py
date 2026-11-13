"""The configuration checks: the names that config.yml and Frigate's config must agree on (CLAUDE.md, "Cross-component
name contracts"), and the deployment values."""

import pytest

from frigate_log import (
    CRASH_LOOP_TAIL,
    DETECTOR_MESSAGE,
    MODEL_ID,
    NO_KEY_LINE,
    ORDERLY_EXIT_LINE,
    REFUSED_KEY_LINE,
    SAFE_MODE_LINES,
    SHUTDOWN_LAST_LINE,
    TRACEBACK_TAIL,
    crash_loop_tail,
    shutdown_lines,
    shutdown_tail,
    validation_block,
)
from placeholders import PLACEHOLDER_KEY
from tm_control.adapters import systemd
from tm_control.adapters.systemd import AutomaticRestart
from tm_control.core.checks import Fix, run_group
from tm_control.core.manifest import FrigateInfo
from tm_control.core.secrets import FRIGATE_PLUS_API_KEY, THINGSBOARD_ACCESS_TOKEN
from tm_control.modules.apps import checks as apps_checks
from tm_control.modules.apps import contracts, probes
from tm_control.modules.services import units

FRIGATE_CONFIG = "http://127.0.0.1:5000/api/config"  # what the `apps` fixture answers (conftest.FakeApps)
FRIGATE_VERSION = "http://127.0.0.1:5000/api/version"


def config_group(apps):
    group = run_group(contracts.GROUP, apps.context())
    assert group.title == "Configuration"
    return {check.id: check for check in group.checks}


def config_group_with(apps, preset: dict):
    """The configuration group, with some probes' results set beforehand (the fixture's Context has no settings, so
    a check that reaches systemd or the journal would fail)."""
    context = apps.context()
    context.probes.update(preset)
    group = run_group(contracts.GROUP, context)
    return {check.id: check for check in group.checks}


def test_cameras_match(apps):
    checks = config_group(apps)
    assert list(checks) == [
        "config.cameras", "config.zones", "config.radars", "config.deployment", "config.thingsboard",
        "config.frigate_plus",
    ]
    assert [c.title for c in checks.values()] == [
        "Cameras in config.yml", "Zones", "Radar names", "Location", "ThingsBoard upload", "Frigate+",
    ]
    assert {c.id: c.status for c in checks.values()} == dict.fromkeys(checks, "ok")


NEUTRAL = "camera_1_3fa9c2"


def point_at(apps, key, frigate_camera, **fields):
    """Make config.yml's only camera entry `key`, pointing at `frigate_camera` (the key itself when None)."""

    def rename(data):
        entry = data["sensors"]["cameras"].pop("picam_h265")
        if frigate_camera:
            entry["frigate_camera"] = frigate_camera
        data["sensors"]["cameras"][key] = entry | fields

    apps.edit_config_yml(rename)


def test_cameras_match_through_frigate_camera(apps):
    point_at(apps, NEUTRAL, "picam_h265")
    check = config_group(apps)["config.cameras"]
    assert (check.status, check.fix) == ("ok", None)
    assert check.detail == f"{NEUTRAL} (picam_h265) is in Frigate and enabled in config.yml."
    assert config_group(apps)["config.zones"].status == "ok"


def test_record_off_is_a_warning_not_an_error(apps):
    apps.edit_config_yml(lambda data: data["sensors"]["cameras"]["picam_h265"].update(enabled=False))
    check = config_group(apps)["config.cameras"]
    assert check.status == "warn"
    assert check.fix == contracts.CAMERAS_LINK
    assert check.detail == (
        "Events from picam_h265 are not recorded: Database capture is off for it in config.yml. Turn it on if you "
        "want them."
    )


def test_detection_off_in_frigate_is_a_warning_with_the_link(apps):
    apps.edit_json(FRIGATE_CONFIG, lambda config: config["cameras"]["picam_h265"]["detect"].update(enabled=False))
    check = config_group(apps)["config.cameras"]
    assert check.status == "warn"
    assert check.fix == contracts.CAMERAS_LINK
    assert check.detail == (
        "Events from picam_h265 are not recorded: Frigate's detection is off for it. Turn Frigate detection on if "
        "you want them."
    )


def test_detection_off_doesnt_matter_while_database_capture_is_off(apps):
    apps.edit_json(FRIGATE_CONFIG, lambda config: config["cameras"]["picam_h265"]["detect"].update(enabled=False))
    apps.edit_config_yml(lambda data: data["sensors"]["cameras"]["picam_h265"].update(enabled=False))
    assert config_group(apps)["config.cameras"].status == "ok"  # nothing is detected, so nothing is dropped


def test_a_renamed_camera_is_an_error_with_the_link(apps):
    """#249: the camera was renamed in Frigate but not in config.yml."""

    def rename(config):
        config["cameras"]["front_street"] = config["cameras"].pop("picam_h265")

    apps.edit_json(FRIGATE_CONFIG, rename)
    check = config_group(apps)["config.cameras"]
    assert check.status == "error"
    assert check.fix == contracts.CAMERAS_LINK
    assert "front_street" in check.detail and "not recorded" in check.detail


def test_a_frigate_camera_that_is_off_is_not_an_error(apps):
    apps.edit_json(FRIGATE_CONFIG, lambda config: config["cameras"].update(
        oak_ave_tele=dict(config["cameras"]["picam_h265"], enabled=False)
    ))
    assert config_group(apps)["config.cameras"].status == "ok"


def test_a_duplicate_frigate_camera_is_an_error(apps):
    apps.edit_config_yml(lambda data: data["sensors"]["cameras"].update(
        {NEUTRAL: {"frigate_camera": "picam_h265", "enabled": True}}
    ))
    check = config_group(apps)["config.cameras"]
    assert check.status == "error"
    assert check.fix == contracts.CAMERAS_LINK
    # The dump in edit_config_yml sorts keys, so the neutral name comes first in the file
    assert f"{NEUTRAL} and picam_h265 both point at Frigate's camera picam_h265" in check.detail
    assert "only camera_1_3fa9c2, the first, is used" in check.detail
    assert config_group(apps)["config.zones"].status == "ok"  # the duplicate's zones aren't reported twice


def test_an_entry_whose_camera_is_gone_is_a_warning_with_the_link(apps):
    point_at(apps, NEUTRAL, "main_st")
    apps.edit_config_yml(lambda data: data["sensors"]["cameras"].update(picam_h265={"enabled": True}))
    check = config_group(apps)["config.cameras"]
    assert check.status == "warn"
    assert check.fix == contracts.CAMERAS_LINK
    assert f"{NEUTRAL} (main_st)" in check.detail
    assert "doesn't have as an enabled camera" in check.detail


def test_an_error_beats_a_warning(apps):
    apps.edit_config_yml(lambda data: data["sensors"]["cameras"].update(side_street={"enabled": True}))
    apps.edit_json(FRIGATE_CONFIG, lambda config: config["cameras"].update(
        oak_ave_tele=dict(config["cameras"]["picam_h265"])
    ))
    check = config_group(apps)["config.cameras"]
    assert check.status == "error" and check.fix == contracts.CAMERAS_LINK
    assert "oak_ave_tele" in check.detail


def test_a_config_camera_frigate_doesnt_have_is_a_warning(apps):
    apps.edit_config_yml(lambda data: data["sensors"]["cameras"].update(side_street={"enabled": True}))
    check = config_group(apps)["config.cameras"]
    assert check.status == "warn"
    assert check.fix == contracts.CAMERAS_LINK
    assert "side_street" in check.detail


def test_cameras_and_zones_are_unknown_when_frigate_is_down(apps):
    apps.answers[FRIGATE_VERSION] = (None, None)
    checks = config_group(apps)
    assert checks["config.cameras"].status == "unknown"
    assert checks["config.zones"].status == "unknown"
    assert checks["config.radars"].status == "ok"
    assert checks["config.deployment"].status == "ok"
    assert checks["config.thingsboard"].status == "ok"


def test_cameras_and_zones_are_unknown_in_safe_mode(apps):
    """Bench A5: an empty camera list isn't a renamed camera (the fixture's config.yml still enables picam_h265)."""
    safe_mode(apps)
    apps.edit_json(FRIGATE_CONFIG, lambda config: config.update(cameras={}))
    checks = config_group_with(apps, {probes.FRIGATE_JOURNAL: SAFE_MODE_LINES})
    assert (checks["config.cameras"].status, checks["config.cameras"].detail) == (
        "unknown",
        "Frigate is in safe mode, with no cameras, so its cameras can't be compared with config.yml; see the Frigate "
        "check under Apps.",
    )
    assert (checks["config.zones"].status, checks["config.zones"].detail) == (
        "unknown",
        "Frigate is in safe mode, with no cameras, so the cameras' zones can't be checked; see the Frigate check under "
        "Apps.",
    )
    assert checks["config.frigate_plus"].detail == "Frigate+ isn't in use."


def test_every_check_is_unknown_when_config_yml_has_a_yaml_error(apps):
    apps.config_yml.write_text("sensors:\n  cameras: [unclosed\n")
    safe_mode(apps)  # config.yml's problem is still the one named (review focus 5)
    checks = config_group(apps)
    # The Frigate+ check reads Frigate's config.yml only, which has no plus:// model, and no key is set.
    frigate_plus = checks.pop("config.frigate_plus")
    assert (frigate_plus.status, frigate_plus.detail) == ("ok", "Frigate+ isn't in use.")
    assert {c.status for c in checks.values()} == {"unknown"}
    assert checks["config.cameras"].detail == (
        "config.yml has a YAML error, so its cameras can't be compared with Frigate's."
    )
    assert checks["config.zones"].detail == "config.yml has a YAML error, so the cameras' zones can't be checked."
    assert all("unclosed" not in c.detail for c in checks.values())


def test_missing_zones_name_the_direction_problem(apps):
    def drop(config):
        zones = config["cameras"]["picam_h265"]["zones"]
        del zones["zone_near"], zones["zone_far"]

    apps.edit_json(FRIGATE_CONFIG, drop)
    check = config_group(apps)["config.zones"]
    assert check.status == "warn"
    assert check.fix == contracts.frigate_zones_link("picam_h265")
    assert "zone_near" in check.detail and "zone_far" in check.detail and "picam_h265" in check.detail
    assert "without zone_near and zone_far, events get a direction only from the radar (#243)" in check.detail


def test_a_zone_turned_off_in_frigate_is_a_warning(apps):
    """Frigate 0.18 can turn a zone off, in its config or from the live view; an event then never enters it."""
    apps.edit_json(FRIGATE_CONFIG, lambda config: config["cameras"]["picam_h265"]["zones"]["zone_capture"].update(
        enabled=False
    ))
    check = config_group(apps)["config.zones"]
    assert check.status == "warn"
    assert check.fix == contracts.frigate_zones_link("picam_h265")
    assert check.detail == "Camera picam_h265 has zone_capture turned off in Frigate. Turn it back on in Frigate."


def test_zones_of_one_camera_link_to_its_zones_in_frigate(apps):
    """Zones are drawn in Frigate: the link opens Frigate's masks and zones settings at that camera."""
    point_at(apps, NEUTRAL, "picam_h265")
    apps.edit_json(FRIGATE_CONFIG, lambda config: config["cameras"]["picam_h265"]["zones"].pop("zone_radar"))
    check = config_group(apps)["config.zones"]
    assert check.fix == Fix(
        kind="link", href="/frigate/settings?page=masksAndZones&camera=picam_h265", text="Edit its zones in Frigate",
        external=True,
    )
    assert check.fix.external is True  # another app's page, not one of tm-control's


def test_zones_of_several_cameras_link_to_the_cameras_page(apps):
    def edit(config):
        config["cameras"]["oak_ave_tele"] = dict(config["cameras"]["picam_h265"], zones={})
        config["cameras"]["picam_h265"]["zones"].pop("zone_radar")

    apps.edit_json(FRIGATE_CONFIG, edit)
    apps.edit_config_yml(lambda data: data["sensors"]["cameras"].update(
        {NEUTRAL: {"frigate_camera": "oak_ave_tele", "enabled": True}}
    ))
    check = config_group(apps)["config.zones"]
    assert check.status == "warn" and check.fix == contracts.CAMERAS_LINK


def test_missing_and_turned_off_zones_are_named_together(apps):
    def edit(config):
        zones = config["cameras"]["picam_h265"]["zones"]
        del zones["zone_radar"]
        zones["zone_near"]["enabled"] = False

    apps.edit_json(FRIGATE_CONFIG, edit)
    check = config_group(apps)["config.zones"]
    assert check.status == "warn"
    assert check.detail == (
        "Camera picam_h265 has no zone_radar in Frigate, and has zone_near turned off there; without zone_near and "
        "zone_far, events get a direction only from the radar (#243). Draw the missing zones in Frigate, named "
        "exactly as listed, and turn the others back on."
    )


def test_zones_are_checked_through_frigate_camera(apps):
    point_at(apps, NEUTRAL, "picam_h265")
    apps.edit_json(FRIGATE_CONFIG, lambda config: config["cameras"]["picam_h265"]["zones"].pop("zone_radar"))
    check = config_group(apps)["config.zones"]
    assert check.status == "warn"
    assert check.fix == contracts.frigate_zones_link("picam_h265")
    assert f"Camera {NEUTRAL} (picam_h265) has no zone_radar in Frigate" in check.detail


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


def test_a_missing_or_disabled_radar_is_a_warning_with_the_link(apps):
    point_at(apps, NEUTRAL, "picam_h265")
    apps.edit_config_yml(lambda data: data["sensors"]["radars"]["TM_RADAR_SERIAL_PORT_00"].update(enabled=False))
    check = config_group(apps)["config.radars"]
    assert (check.status, check.fix) == ("warn", contracts.CAMERAS_LINK)
    assert (
        f"Camera {NEUTRAL} (picam_h265) is paired with radar TM_RADAR_SERIAL_PORT_00, which isn't enabled; it gets no "
        "speed or direction from a radar."
    ) in check.detail
    assert "dropped" not in check.detail and "#255" not in check.detail


def test_camera_radar_naming_a_radar_not_in_config_yml_is_a_warning(apps):
    apps.edit_config_yml(lambda data: data["sensors"]["cameras"]["picam_h265"].update(
        camera_radar="TM_RADAR_SERIAL_PORT_02"
    ))
    check = config_group(apps)["config.radars"]
    assert check.status == "warn" and "TM_RADAR_SERIAL_PORT_02" in check.detail
    assert check.fix == contracts.CAMERAS_LINK


def test_a_radar_name_error_beats_the_pairing_warning(apps):
    apps.edit_config_yml(lambda data: data["sensors"]["radars"].update(front_radar={"enabled": True}))
    apps.edit_config_yml(lambda data: data["sensors"]["radars"]["TM_RADAR_SERIAL_PORT_00"].update(enabled=False))
    check = config_group(apps)["config.radars"]
    assert check.status == "error" and "front_radar" in check.detail


def test_a_camera_without_a_radar_is_fine(apps):
    apps.edit_config_yml(lambda data: data["sensors"]["cameras"]["picam_h265"].pop("camera_radar"))
    assert config_group(apps)["config.radars"].status == "ok"


@pytest.mark.parametrize(
    "deployment, status, key",
    [
        ({"lat": 91, "lon": 10, "bearing": "n"}, "error", "deployment.lat"),
        ({"lat": -90, "lon": 180.5, "bearing": "n"}, "error", "deployment.lon"),
        ({"lat": "abc", "lon": 10, "bearing": "n"}, "error", "deployment.lat"),
        ({"lat": 45, "lon": "1e2", "bearing": "n"}, "error", "deployment.lon"),
        ({"lat": 45, "lon": None, "bearing": "n"}, "error", "deployment.lat"),  # one of the pair alone
        ({"lat": True, "lon": 10, "bearing": "n"}, "error", "deployment.lat"),
        ({"lat": 45, "lon": 10, "bearing": "north"}, "error", "deployment.bearing"),
        ({"lat": 45, "lon": 10, "bearing": 90}, "error", "deployment.bearing"),
        ({"lat": 45, "lon": 10, "bearing": " n"}, "error", "deployment.bearing"),  # Node-RED doesn't trim
        ({"lat": 45, "lon": 10, "bearing": "  "}, "error", "deployment.bearing"),
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
        if isinstance(value, str) and len(value.strip()) > 2:  # shorter ones are inside the message
            assert value not in check.detail  # names the key, not its value
        assert "91" not in check.detail and "180.5" not in check.detail


LOCATION_LINK = ("link", "/location", "Open the Location page")
SURVEY_ID = "0123abcd-si"


def location_check(apps, state=None, **deployment):
    apps.edit_config_yml(lambda data: data["deployment"].update(deployment))
    group = run_group(contracts.GROUP, apps.context(state))
    return next(check for check in group.checks if check.id == "config.deployment")


def fix_of(check):
    return None if check.fix is None else (check.fix.kind, check.fix.href, check.fix.text)


def test_location_title_and_id_are_unchanged(apps):
    check = location_check(apps)
    assert (check.id, check.title) == ("config.deployment", "Location")


def test_location_accepts_quoted_coordinates(apps):
    check = location_check(apps, lat="45.52252", lon=" -122.6912 ")
    assert check.status == "ok", check.detail


@pytest.mark.parametrize(
    "deployment, detail",
    [
        ({"survey_id": "nonsense"}, "deployment.survey_id isn't a survey id (8 hex characters and -si)"),
        ({"survey_id": SURVEY_ID, "database_precision": "3"}, "deployment.database_precision isn't none, 1, or 2"),
        ({"database_precision": "NONE"}, "deployment.database_precision isn't none, 1, or 2"),  # R10: no case folding
        ({"database_precision": True}, "deployment.database_precision isn't none, 1, or 2"),
    ],
)
def test_location_rejects_a_bad_survey_id_and_precision(apps, deployment, detail):
    check = location_check(apps, **deployment)
    assert check.status == "error" and detail in check.detail
    for value in ("nonsense", "NONE"):
        assert value not in check.detail  # names the key, not its value


def test_location_says_an_invalid_precision_stores_the_default(apps):
    check = location_check(apps, database_precision="NONE")  # R10: Node-RED doesn't fold case, so it uses '2'
    assert check.detail == (
        "In config.yml, deployment.database_precision isn't none, 1, or 2. Correct it, or leave it empty. Until then,"
        " Node-RED stores the default, about 1 km."
    )


def test_location_says_what_the_default_is_for_after_every_problem(apps):
    check = location_check(apps, database_precision="NONE", bearing="up")
    assert "2; deployment.bearing" in check.detail or "; deployment.database_precision" in check.detail
    assert check.detail.endswith("Correct them, or leave them empty. Until then, Node-RED stores the default, about 1 km.")


@pytest.mark.parametrize(
    "deployment", [{"survey_id": SURVEY_ID.upper()}, {"database_precision": 2}, {"database_precision": "none"}]
)
def test_location_accepts_the_values_the_engine_accepts(apps, deployment):
    assert location_check(apps, **deployment).status == "ok"


def test_location_checks_each_enabled_sensors_own_bearing(apps):
    apps.edit_config_yml(
        lambda data: data["sensors"]["cameras"]["picam_h265"].update(deployment={"bearing": "north"})
    )
    check = location_check(apps)
    assert check.status == "error"
    assert (
        "sensors.cameras.picam_h265.deployment.bearing isn't one of n, s, e, w, ne, nw, se, sw, or empty"
        in check.detail
    )
    assert "north" not in check.detail


@pytest.mark.parametrize("bearing", [" n", "  "])
def test_location_does_not_trim_a_sensors_own_bearing(apps, bearing):
    apps.edit_config_yml(lambda data: data["sensors"]["cameras"]["picam_h265"].update(deployment={"bearing": bearing}))
    check = location_check(apps)
    assert check.status == "error" and "sensors.cameras.picam_h265.deployment.bearing" in check.detail


def test_location_ignores_a_disabled_sensors_bearing(apps):
    apps.edit_config_yml(
        lambda data: data["sensors"]["airquality_monitors"]["sensorname01"].update(deployment={"bearing": "north"})
    )
    assert location_check(apps).status == "ok"


def test_location_warns_about_per_sensor_coordinates(apps):
    apps.edit_config_yml(
        lambda data: data["sensors"]["cameras"]["picam_h265"].update(deployment={"lat": 45.0, "lon": -122.0})
    )
    check = location_check(apps)
    assert check.status == "warn"
    assert "sensors.cameras.picam_h265.deployment.lat" in check.detail
    assert "sensors.cameras.picam_h265.deployment.lon" in check.detail
    assert "ignored; the location is per unit; tmsetup removes it" in check.detail
    assert "45.0" not in check.detail and "122" not in check.detail
    assert fix_of(check) == LOCATION_LINK


def test_location_error_wins_over_a_warning(apps):
    apps.edit_config_yml(lambda data: data["sensors"]["cameras"]["picam_h265"].update(deployment={"lat": 45.0}))
    assert location_check(apps, survey_id="nonsense").status == "error"


@pytest.fixture
def state(tmp_path):
    from tm_control.core.state import State

    state = State(tmp_path / "state.sqlite")
    state.migrate()
    return state


def with_place(state, survey_id=SURVEY_ID, status="in_use"):
    from tm_control.modules.location.places import Places

    places = Places(state)
    places.create(survey_id, "", None, None, [], "ui", status, None, now=1000)
    places.mark_reconciled(now=1000)
    return places


def test_location_links_to_the_page_when_the_file_names_an_unknown_place(apps, state):
    with_place(state, "ffffffff-si")
    check = location_check(apps, state, survey_id=SURVEY_ID)
    assert check.status == "warn"
    assert "deployment.survey_id names a place this device doesn't have" in check.detail
    assert SURVEY_ID not in check.detail
    assert fix_of(check) == LOCATION_LINK


def test_location_links_to_the_page_until_the_places_are_imported(apps, state):
    check = location_check(apps, state)  # a fresh state: reconcile has not run
    assert check.status == "warn"
    assert "haven't been set up yet" in check.detail
    assert fix_of(check) == LOCATION_LINK


def test_location_says_which_place_is_in_use(apps, state):
    with_place(state)
    check = location_check(apps, state, survey_id=SURVEY_ID, database_precision="2")
    assert (check.status, check.detail) == ("ok", f"Place {SURVEY_ID} is in use at precision 2.")
    assert check.fix is None


def test_location_with_no_place_says_no_location_is_set(apps, state):
    with_place(state)
    check = location_check(apps, state, lat=None, lon=None)
    assert (check.status, check.detail) == ("ok", "No location is set.")


def test_location_without_a_state_skips_the_places_check(apps):
    check = location_check(apps, survey_id=SURVEY_ID)  # no State in the Context: nothing to compare with
    assert check.status == "ok"
    assert check.detail == f"Place {SURVEY_ID} is in use at precision 2."  # the fixture has none: the default


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


# Frigate+


CORAL_PATH = "/config/model_cache/yolov9-s-relu6-tpumax_512_int8_edgetpu.tflite"  # the installer's, as rendered
SET_THE_KEY = Fix(kind="link", text="Set the key", href="/detection#frigate-plus")


def frigate_config_file(apps, text: str):
    """Write Frigate's config.yml as the host has it."""
    path = apps.codedir / "frigate" / "config" / "config.yml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def with_model(apps, path: str):
    frigate_config_file(apps, f"mqtt:\n  enabled: true\nmodel:\n  path: {path}\ncameras: {{}}\n")


def cache_model(apps, model_id: str):
    """The two files Frigate downloads for a Frigate+ model, as copied to the device."""
    cache = apps.codedir / "frigate" / "config" / "model_cache"
    cache.mkdir(parents=True, exist_ok=True)
    (cache / model_id).write_bytes(b"synthetic model")
    (cache / f"{model_id}.json").write_text("{}")


def set_key(apps):
    apps.secrets.entered[FRIGATE_PLUS_API_KEY] = PLACEHOLDER_KEY


def safe_mode(apps):
    apps.edit_json(FRIGATE_CONFIG, lambda config: config.update(safe_mode=True))


def frigate_plus_check(apps, **preset):
    return config_group_with(apps, preset)["config.frigate_plus"]


def frigate_stopped(apps, journal, state: dict | None = None):
    """Frigate doesn't answer, its journal is `journal`, and its unit's values are `state` over those of a unit
    systemd is restarting."""
    apps.answers[FRIGATE_VERSION] = (None, None)
    values = {"ActiveState": "activating", "SubState": "auto-restart", "NRestarts": "3", "ActiveEnterTimestamp": "",
              "InvocationID": ""}
    return {units.SHOW_UNITS: {"frigate.service": values | (state or {})}, probes.FRIGATE_JOURNAL: journal}


def test_the_installers_model_comes_from_the_manifest(apps):
    set_key(apps)
    with_model(apps, CORAL_PATH)
    assert frigate_plus_check(apps).detail == warning_naming("the installer's model")
    context = apps.context()
    context.manifest = context.manifest.model_copy(update={"frigate": FrigateInfo(coral_model=None)})
    group = run_group(contracts.GROUP, context)
    assert {c.id: c for c in group.checks}["config.frigate_plus"].detail == warning_naming("a local model")


def test_frigate_plus_not_in_use_is_ok(apps):
    check = frigate_plus_check(apps)
    assert (check.status, check.detail, check.fix) == ("ok", "Frigate+ isn't in use.", None)
    with_model(apps, CORAL_PATH)
    assert frigate_plus_check(apps).detail == "Frigate+ isn't in use."


def warning_naming(which):
    return (
        "A Frigate+ key is set, so snapshots can be submitted from Frigate's Explore page, but Frigate runs "
        f"{which} rather than a Frigate+ model. Once a model is trained, pick it under Settings, System, Detectors "
        "and model in Frigate, or upload it on the Detection page and choose Use."
    )


def test_a_key_without_a_plus_model_is_a_warning_naming_the_installers_model(apps):
    set_key(apps)
    with_model(apps, CORAL_PATH)
    check = frigate_plus_check(apps)
    assert (check.status, check.detail, check.fix) == ("warn", warning_naming("the installer's model"), None)
    assert PLACEHOLDER_KEY not in check.detail


@pytest.mark.parametrize("text", ["cameras: {}\n", "model:\n  width: 320\ncameras: {}\n", 'model:\n  path: ""\n'],
                         ids=["no model section", "no path", "an empty path"])
def test_a_key_without_a_model_path_is_a_warning_naming_frigates_default_model(apps, text):
    """Hailo and CPU installs have no model section, so Frigate runs its built-in default."""
    set_key(apps)
    frigate_config_file(apps, text)
    check = frigate_plus_check(apps)
    assert (check.status, check.detail) == ("warn", warning_naming("Frigate's default model"))


def test_a_key_with_a_local_model_is_a_warning_naming_a_local_model(apps):
    set_key(apps)
    with_model(apps, "/config/model_cache/my_yolo.onnx")
    check = frigate_plus_check(apps)
    assert (check.status, check.detail) == ("warn", warning_naming("a local model"))


@pytest.mark.parametrize("path", ["plus://../x", "plus://", "plus://a b", f"plus://{'a' * 65}"])
def test_a_plus_model_with_a_bad_id_is_an_error(apps, path):
    set_key(apps)
    with_model(apps, f'"{path}"')
    check = frigate_plus_check(apps)
    assert (check.status, check.detail) == (
        "error",
        "model.path in Frigate's config names a Frigate+ model id with characters a model id can't have. Check the "
        "id in Frigate's configuration editor.",
    )


def test_a_plus_model_without_a_key_or_cached_files_is_an_error_with_a_link(apps):
    with_model(apps, f"plus://{MODEL_ID}")
    check = frigate_plus_check(apps)
    assert check.status == "error"
    assert check.detail == (
        f"Frigate's config names the Frigate+ model {MODEL_ID}, but no key is set and the model's files aren't on the "
        f"device, so Frigate can't download it. Set the key, or upload {MODEL_ID} and {MODEL_ID}.json on the Detection "
        "page."
    )
    assert check.fix == SET_THE_KEY


def test_one_cached_file_is_not_the_model(apps):
    with_model(apps, f"plus://{MODEL_ID}")
    cache_model(apps, MODEL_ID)
    (apps.codedir / "frigate" / "config" / "model_cache" / f"{MODEL_ID}.json").unlink()
    assert frigate_plus_check(apps).status == "error"
    assert not contracts.model_cached(apps.codedir, MODEL_ID)


def test_a_cached_plus_model_without_a_key_is_ok_and_says_so(apps):
    with_model(apps, f"plus://{MODEL_ID}")
    cache_model(apps, MODEL_ID)
    check = frigate_plus_check(apps)
    assert (check.status, check.detail) == (
        "ok",
        f"Frigate runs the Frigate+ model {MODEL_ID}. It was loaded from the files on the device; set a key to submit "
        "snapshots.",
    )


def test_a_plus_model_with_a_key_is_ok(apps):
    set_key(apps)
    with_model(apps, f"plus://{MODEL_ID}")
    check = frigate_plus_check(apps)
    assert (check.status, check.detail) == (
        "ok", f"Frigate runs the Frigate+ model {MODEL_ID}. Snapshots can be submitted.",
    )


def test_a_plus_model_frigate_rejected_for_the_detector_names_the_type(apps):
    set_key(apps)
    with_model(apps, f"plus://{MODEL_ID}")
    safe_mode(apps)
    check = frigate_plus_check(apps, **{probes.FRIGATE_JOURNAL: SAFE_MODE_LINES})
    assert (check.status, check.detail) == (
        "error",
        f"Frigate couldn't use the Frigate+ model {MODEL_ID} and started in safe mode, with no cameras: it isn't built "
        "for the edgetpu detector. Pick a model made for edgetpu in Frigate+, then set it in Frigate.",
    )


def test_a_plus_model_frigate_rejected_for_another_reason_quotes_the_message(apps):
    set_key(apps)
    with_model(apps, f"plus://{MODEL_ID}")
    safe_mode(apps)
    lines = validation_block("Value error, The model's labelmap couldn't be read")
    check = frigate_plus_check(apps, **{probes.FRIGATE_JOURNAL: lines})
    assert (check.status, check.detail) == (
        "error",
        f"Frigate couldn't use the model {MODEL_ID} and started in safe mode, with no cameras. Its log says: Value "
        "error, The model's labelmap couldn't be read.",
    )


def test_safe_mode_for_an_unrelated_reason_is_left_to_the_apps_check(apps):
    set_key(apps)
    with_model(apps, f"plus://{MODEL_ID}")
    safe_mode(apps)
    lines = validation_block("Value error, Camera picam_h265 has no zone named zone_far")
    unknown = (
        "unknown",
        f"Frigate's config names the Frigate+ model {MODEL_ID}, but Frigate is in safe mode for another reason; see "
        "the Frigate check under Apps.",
    )
    check = frigate_plus_check(apps, **{probes.FRIGATE_JOURNAL: lines})
    assert (check.status, check.detail) == unknown
    # Nor does it claim the model runs when the journal holds no message at all
    check = frigate_plus_check(apps, **{probes.FRIGATE_JOURNAL: []})
    assert (check.status, check.detail) == unknown


def test_a_refused_key_is_named_with_the_link_while_frigate_crash_loops(apps):
    """Bench A3: the unit is active between crashes, so the check can't gate on ActiveState."""
    set_key(apps)
    with_model(apps, f"plus://{MODEL_ID}")
    active = {"ActiveState": "active", "SubState": "running", "NRestarts": "3"}
    check = frigate_plus_check(apps, **frigate_stopped(apps, CRASH_LOOP_TAIL, active))
    assert check.status == "error" and check.fix == SET_THE_KEY
    assert check.detail == (
        f"Frigate isn't answering: Frigate+ gave Frigate no token for the key when Frigate fetched the model "
        f"{MODEL_ID}, as happens with a wrong key or when Frigate+ can't be reached. Its log's last error is: "
        f"{REFUSED_KEY_LINE}. To get Frigate running, {contracts.WAYS_OUT}."
    )


def test_a_cached_model_is_not_blamed_for_the_stop(apps):
    """With both files on the device, Frigate loads the model without asking Frigate+, so the fetch advice would
    point at the wrong place, even for a stale refused-key line."""
    set_key(apps)
    with_model(apps, f"plus://{MODEL_ID}")
    cache_model(apps, MODEL_ID)
    check = frigate_plus_check(apps, **frigate_stopped(apps, CRASH_LOOP_TAIL))
    assert check.status == "error" and check.fix is None
    assert check.detail == (
        f"Frigate isn't answering, and the last error in its log is: {REFUSED_KEY_LINE}. The Frigate+ model "
        f"{MODEL_ID} is on the device, so Frigate didn't stop fetching it; see the Frigate check under Apps."
    )


def test_another_exception_is_quoted_without_a_claim(apps):
    set_key(apps)
    with_model(apps, f"plus://{MODEL_ID}")
    check = frigate_plus_check(apps, **frigate_stopped(apps, crash_loop_tail(NO_KEY_LINE)))
    assert check.status == "error" and check.fix is None
    assert check.detail == (
        f"Frigate isn't answering, and the last error in its log is: {NO_KEY_LINE}. If it stopped while fetching "
        f"the Frigate+ model {MODEL_ID}, check that the device is online, then {contracts.WAYS_OUT}."
    )


def test_a_crash_loop_without_an_exception_line_is_unknown(apps):
    set_key(apps)
    with_model(apps, f"plus://{MODEL_ID}")
    check = frigate_plus_check(apps, **frigate_stopped(apps, CRASH_LOOP_TAIL[-3:]))  # systemd's lines only
    assert (check.status, check.detail) == (
        "unknown", f"Frigate isn't answering, so whether it loaded the Frigate+ model {MODEL_ID} is unknown.")


def test_frigate_starting_after_a_hand_restart_quotes_nothing(apps):
    """Active, no failure restarts, not answering yet: the journal probe reads this run, which has no traceback."""
    set_key(apps)
    with_model(apps, f"plus://{MODEL_ID}")
    starting = {"ActiveState": "active", "SubState": "running", "NRestarts": "0"}
    check = frigate_plus_check(apps, **frigate_stopped(apps, ["Starting Frigate (0.18.1-cf67f08)"], starting))
    assert check.status == "unknown"


@pytest.mark.parametrize("problem, text", [
    ("missing", None),
    ("invalid", "model: [unclosed\n"),
    ("invalid", "- a list\n"),
    ("unreadable", b"\xff\xfe\x00bad"),
])
def test_a_missing_or_invalid_frigate_config_is_unknown(apps, problem, text):
    set_key(apps)
    if isinstance(text, bytes):
        frigate_config_file(apps, "")
        (apps.codedir / "frigate" / "config" / "config.yml").write_bytes(text)
    elif text is None:
        (apps.codedir / "frigate" / "config" / "config.yml").unlink()
    else:
        frigate_config_file(apps, text)
    check = frigate_plus_check(apps)
    wording = {
        "missing": "Frigate's config.yml is missing",
        "unreadable": "Frigate's config.yml can't be read",
        "invalid": "Frigate's config.yml has a YAML error",
    }[problem]
    assert (check.status, check.detail) == (
        "unknown", f"{wording}, so its model and the Frigate+ key can't be compared.",
    )
    assert "unclosed" not in check.detail


def test_quoted_log_lines_never_hold_a_key(apps):
    """Review focus 4: a key-shaped string in a quoted log line is replaced before the line reaches the page."""
    set_key(apps)
    with_model(apps, f"plus://{MODEL_ID}")
    safe_mode(apps)
    lines = validation_block(f"Value error, model download refused for {PLACEHOLDER_KEY}")
    message_check = frigate_plus_check(apps, **{probes.FRIGATE_JOURNAL: lines})
    traceback = TRACEBACK_TAIL[:3] + [
        f"2026-11-04T10:00:00+0000 tm-test frigate[812]: Exception: bad key {PLACEHOLDER_KEY.upper()} or "
        f"{PLACEHOLDER_KEY}"
    ]
    apps.edit_json(FRIGATE_CONFIG, lambda config: config.update(safe_mode=False))
    traceback_check = frigate_plus_check(apps, **frigate_stopped(apps, traceback))
    for check in (message_check, traceback_check):
        assert check.status == "error"
        assert PLACEHOLDER_KEY not in check.detail and PLACEHOLDER_KEY.upper() not in check.detail
        assert "<key>" in check.detail
        assert "0123456789abcdef" not in check.detail.lower()


def test_a_long_quoted_line_is_cut_after_the_key_is_replaced(apps):
    line = "Message : " + "x" * 190 + PLACEHOLDER_KEY
    (message,) = apps_checks.validation_messages([line])
    assert message == "x" * 190 + "<key>"
    line = "Message : " + "y" * 150 + PLACEHOLDER_KEY + "z" * 100
    (message,) = apps_checks.validation_messages([line])
    assert len(message) == apps_checks.MESSAGE_MAX and message.endswith("…")
    assert "tmdev" not in message and "<key>" in message


def test_the_journal_probe_reads_the_current_run_when_frigate_runs_and_the_tail_when_it_doesnt(apps, monkeypatch):
    calls = []
    monkeypatch.setattr(systemd, "journal_lines",
                        lambda *args: calls.append(("lines", *args)) or ["Message : from this run"])
    monkeypatch.setattr(systemd, "journal_tail", lambda *args: calls.append(("tail", *args)) or None)
    running = {"ActiveState": "active", "SubState": "running", "ActiveEnterTimestamp": "@1700000000",
               "InvocationID": "abc", "NRestarts": "0"}
    answering = apps.answers[FRIGATE_VERSION]

    # Active, never restarted, and not answering yet (still starting): this run's own block
    apps.answers[FRIGATE_VERSION] = (None, None)
    context = apps.context()
    context.probes[units.SHOW_UNITS] = {"frigate.service": running}
    assert probes.frigate_journal(context) == ["Message : from this run"]
    assert probes.frigate_journal(context) == ["Message : from this run"]  # read once per report
    assert calls == [("lines", "frigate.service", "@1699999940", 400, "abc")]

    calls.clear()
    context = apps.context()
    context.probes[units.SHOW_UNITS] = {"frigate.service": dict(running, ActiveEnterTimestamp="", InvocationID="")}
    probes.frigate_journal(context)
    assert calls == [("lines", "frigate.service", "-1h", 400, None)]

    calls.clear()
    context = apps.context()
    context.probes[units.SHOW_UNITS] = {"frigate.service": dict(running, ActiveState="failed", SubState="failed")}
    assert probes.frigate_journal(context) == []  # the journal couldn't be read
    assert calls == [("tail", "frigate.service", 400)]

    # Active with failure restarts and not answering: a crash loop, whose last failed run is in the tail
    calls.clear()
    apps.answers[FRIGATE_VERSION] = (None, None)
    context = apps.context()
    context.probes[units.SHOW_UNITS] = {"frigate.service": dict(running, NRestarts="3")}
    context.probes[f"{units.AUTOMATIC_RESTARTS}.frigate.service"] = [
        AutomaticRestart("1", t) for t in (100.1, 110.1, 120.1)]
    probes.frigate_journal(context)
    assert calls == [("tail", "frigate.service", 400)]

    # Active, not answering yet, and the one restart systemd counted is Frigate's own after a Save & Restart (exit
    # 143): this run's own block, not the run before the save
    calls.clear()
    context = apps.context()
    context.probes[units.SHOW_UNITS] = {"frigate.service": dict(running, NRestarts="1")}
    context.probes[f"{units.AUTOMATIC_RESTARTS}.frigate.service"] = [AutomaticRestart("143", 100.1)]
    assert probes.frigate_journal(context) == ["Message : from this run"]
    assert calls == [("lines", "frigate.service", "@1699999940", 400, "abc")]

    # A crash loop that began with a Save & Restart: the last restart followed a failure, so the tail
    calls.clear()
    context = apps.context()
    context.probes[units.SHOW_UNITS] = {"frigate.service": dict(running, NRestarts="2")}
    context.probes[f"{units.AUTOMATIC_RESTARTS}.frigate.service"] = [
        AutomaticRestart("143", 100.1), AutomaticRestart("1", 200.1)]
    probes.frigate_journal(context)
    assert calls == [("tail", "frigate.service", 400)]

    # Frigate's own restart within RESTART_LOOP_SPACING of the one before it is a loop, not a save, so the run that
    # stopped is in the tail
    calls.clear()
    context = apps.context()
    context.probes[units.SHOW_UNITS] = {"frigate.service": dict(running, NRestarts="2")}
    context.probes[f"{units.AUTOMATIC_RESTARTS}.frigate.service"] = [
        AutomaticRestart("143", 100.1), AutomaticRestart("143", 140.1)]
    probes.frigate_journal(context)
    assert calls == [("tail", "frigate.service", 400)]

    # Restarted, not answering, and PID 1's journal can't tell what the restart followed: the tail, as before
    calls.clear()
    context = apps.context()
    context.probes[units.SHOW_UNITS] = {"frigate.service": dict(running, NRestarts="1")}
    context.probes[f"{units.AUTOMATIC_RESTARTS}.frigate.service"] = None
    probes.frigate_journal(context)
    assert calls == [("tail", "frigate.service", 400)]

    # Active with failure restarts but answering (safe mode after a Save & Restart): this run's own block
    calls.clear()
    apps.answers[FRIGATE_VERSION] = answering  # the fixture's original answer, saved before the first change
    context = apps.context()
    context.probes[units.SHOW_UNITS] = {"frigate.service": dict(running, NRestarts="1")}
    probes.frigate_journal(context)
    assert calls == [("lines", "frigate.service", "@1699999940", 400, "abc")]


def test_the_log_helpers():
    lines = SAFE_MODE_LINES + ["Message : second", "Message :   spaced   out  "]
    assert apps_checks.validation_messages(lines) == [DETECTOR_MESSAGE, "second", "spaced out"]
    assert apps_checks.validation_messages(["no messages here"]) == []
    assert apps_checks.traceback_last_line(TRACEBACK_TAIL) == 'Exception: {"message":"Unauthorized"}'
    assert apps_checks.traceback_last_line(["ValueError: first", "requests.exceptions.HTTPError: 401"]) == (
        "requests.exceptions.HTTPError: 401"
    )
    assert apps_checks.traceback_last_line(["Traceback (most recent call last):", "ErrorHandler: no"]) is None
    assert apps_checks.traceback_last_line(["Exception: bare"]) == "Exception: bare"
    assert apps_checks.REFUSED_KEY in REFUSED_KEY_LINE


def test_the_s6_timestamp_is_stripped_before_the_line_is_matched():
    """On a Pi, Frigate's supervisor stamps each line after journalctl's own prefix (bench A3)."""
    assert apps_checks.traceback_last_line(CRASH_LOOP_TAIL) == REFUSED_KEY_LINE
    assert apps_checks.traceback_last_line(crash_loop_tail(NO_KEY_LINE)) == NO_KEY_LINE
    # journal_lines gives MESSAGE fields: the s6 stamp alone
    assert apps_checks.traceback_last_line([f"2026-11-04 18:07:36.850573607  {NO_KEY_LINE}"]) == NO_KEY_LINE
    stamped_key = f"2026-11-04T18:07:36+0000 tm-test frigate[2201]: 2026-11-04 18:07:36.850573607  Exception: {PLACEHOLDER_KEY}"
    assert apps_checks.traceback_last_line([stamped_key]) == "Exception: <key>"


def test_a_date_inside_a_message_is_not_a_timestamp():
    line = "Exception: expired on 2026-11-04 18:07:36.850573607  at the server"
    # kept whole; redact only puts the line on one line, which closes up the double space
    assert apps_checks.traceback_last_line([line]) == "Exception: expired on 2026-11-04 18:07:36.850573607 at the server"
    # Nor is an ISO time followed by two words and a colon journalctl's prefix, unless it starts the line
    text = "Exception: token expired at 2026-11-04T10:00:00Z see docs: retry later"
    assert apps_checks.traceback_last_line([f"2026-11-04 18:07:36.850573607  {text}"]) == text


def test_a_podman_or_systemd_error_line_is_not_the_traceback():
    """podman prints a bare "Error: ..." when the unit stops a container that's gone; that isn't Frigate's exception."""
    podman = ('2026-11-04T10:00:02+0000 tm-test podman[901]: Error: no container with name or ID "frigate" found: no '
              "such container")
    assert apps_checks.traceback_last_line(TRACEBACK_TAIL + [podman]) == 'Exception: {"message":"Unauthorized"}'
    assert apps_checks.traceback_last_line([podman]) is None
    assert contracts.plus_model_id(f"plus://{MODEL_ID}") == MODEL_ID
    assert contracts.plus_model_id("plus://../x") is None
    assert contracts.plus_model_id(CORAL_PATH) is None


def test_an_orderly_exit_after_the_last_exception_quotes_nothing():
    """Frigate logs two tracebacks of its own while it stops for a Save & Restart (bench 2026-11-05); s6's exit line
    with code 0 follows them, so neither is why Frigate isn't answering. A crash's exit line has a nonzero code."""
    assert apps_checks.traceback_last_line(shutdown_lines()) is None  # the stopping run, while the unit is active
    assert apps_checks.traceback_last_line(shutdown_tail()) is None  # the tail, between the exit and the new run
    killed = "[INFO] Service Frigate exited with code 256 (by signal 15)"
    assert apps_checks.traceback_last_line(shutdown_lines(killed)) is None
    crashed = "[INFO] Service Frigate exited with code 1 (by signal 0)"
    assert apps_checks.traceback_last_line(shutdown_lines(crashed)) == SHUTDOWN_LAST_LINE
    # A run that crashed after the orderly exit of the one before it is quoted
    assert apps_checks.traceback_last_line(shutdown_tail() + CRASH_LOOP_TAIL) == REFUSED_KEY_LINE
    # Another service's exit line, or more than the line itself, doesn't end the search
    nginx = "[INFO] Service NGINX exited with code 0 (by signal 0)"
    assert apps_checks.traceback_last_line(["Exception: bare", nginx]) == "Exception: bare"
    assert apps_checks.traceback_last_line(["Exception: bare", f"{ORDERLY_EXIT_LINE} and more"]) == "Exception: bare"


def test_frigate_stopping_for_its_own_restart_is_unknown(apps):
    """Decision 11: the unit is active while Frigate stops, and in auto-restart just after; neither quotes."""
    set_key(apps)
    with_model(apps, f"plus://{MODEL_ID}")
    stopping = {"ActiveState": "active", "SubState": "running", "NRestarts": "0"}
    unknown = ("unknown", f"Frigate isn't answering, so whether it loaded the Frigate+ model {MODEL_ID} is unknown.")
    check = frigate_plus_check(apps, **frigate_stopped(apps, shutdown_lines(), stopping))
    assert (check.status, check.detail) == unknown
    check = frigate_plus_check(apps, **frigate_stopped(apps, shutdown_tail()))
    assert (check.status, check.detail) == unknown
