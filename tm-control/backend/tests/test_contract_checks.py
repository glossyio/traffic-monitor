"""The configuration checks: the names that config.yml and Frigate's config must agree on (CLAUDE.md, "Cross-component
name contracts"), and the deployment values."""

from pathlib import Path

import pytest
from ruamel.yaml import YAML

from frigate_log import (
    CRASH_LOOP_TAIL,
    DETECTOR_MESSAGE,
    MODEL_ID,
    NO_KEY_LINE,
    REFUSED_KEY_LINE,
    SAFE_MODE_LINES,
    TRACEBACK_TAIL,
    crash_loop_tail,
    validation_block,
)
from placeholders import PLACEHOLDER_KEY
from tm_control.adapters import systemd
from tm_control.core.checks import Fix, run_group
from tm_control.core.secrets import FRIGATE_PLUS_API_KEY, THINGSBOARD_ACCESS_TOKEN
from tm_control.modules.apps import checks as apps_checks
from tm_control.modules.apps import contracts, probes
from tm_control.modules.services import units

REPO = Path(__file__).resolve().parents[3]

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
    # The Frigate+ check reads Frigate's config.yml only, which has no plus:// model, and no key is set.
    frigate_plus = checks.pop("config.frigate_plus")
    assert (frigate_plus.status, frigate_plus.detail) == ("ok", "Frigate+ isn't in use.")
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


# Frigate+


CORAL_PATH = "/config/model_cache/yolov9-s-relu6-tpumax_512_int8_edgetpu.tflite"  # the installer's, as rendered
SET_THE_KEY = Fix(kind="link", text="Set the key", href="/device#tokens-and-keys")


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


def frigate_stopped(apps, journal):
    """Frigate doesn't answer, systemd is restarting it, and its journal is `journal`."""
    apps.answers[FRIGATE_VERSION] = (None, None)
    states = {"frigate.service": {"ActiveState": "activating", "SubState": "auto-restart", "NRestarts": "3",
                                  "ActiveEnterTimestamp": "", "InvocationID": ""}}
    return {units.SHOW_UNITS: states, probes.FRIGATE_JOURNAL: journal}


def test_the_installers_model_file_matches_the_role():
    role_vars = YAML(typ="safe", pure=True).load(REPO / "script/ansible/roles/tmsetup/vars/main.yml")
    assert contracts.CORAL_MODEL_FILE == role_vars["tmsetup_frigate_coral_model_file"]


def test_frigate_plus_not_in_use_is_ok(apps):
    check = frigate_plus_check(apps)
    assert (check.status, check.detail, check.fix) == ("ok", "Frigate+ isn't in use.", None)
    with_model(apps, CORAL_PATH)
    assert frigate_plus_check(apps).detail == "Frigate+ isn't in use."


def warning_naming(which):
    return (
        "A Frigate+ key is set, so snapshots can be submitted from Frigate's Explore page, but Frigate runs "
        f"{which} rather than a Frigate+ model. Once a model is trained, pick it under Settings, System, Detectors "
        "and model in Frigate, or set model.path to plus://<model id> in its configuration editor."
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
        f"device, so Frigate can't download it. Set the key, or copy {MODEL_ID} and {MODEL_ID}.json into Frigate's "
        "model_cache directory."
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


def test_a_plus_model_and_frigate_stopped_with_a_traceback_is_an_error(apps):
    set_key(apps)
    with_model(apps, f"plus://{MODEL_ID}")
    check = frigate_plus_check(apps, **frigate_stopped(apps, TRACEBACK_TAIL))
    assert check.status == "error"
    assert check.detail == (
        'Frigate isn\'t running, and its log ends with: Exception: {"message":"Unauthorized"}. If it stopped while '
        f"fetching the Frigate+ model {MODEL_ID}, check the key on the Device page and the model id in Frigate's "
        "config, and that the device is online; a model's files copied into model_cache need no download."
    )


def test_a_plus_model_and_frigate_silent_is_unknown(apps):
    set_key(apps)
    with_model(apps, f"plus://{MODEL_ID}")
    unknown = f"Frigate isn't answering, so whether it loaded the Frigate+ model {MODEL_ID} is unknown."
    # Stopped, but without a traceback in its journal
    check = frigate_plus_check(apps, **frigate_stopped(apps, TRACEBACK_TAIL[-2:]))
    assert (check.status, check.detail) == ("unknown", unknown)
    # Running as systemd sees it, but not answering: its journal isn't read
    preset = frigate_stopped(apps, TRACEBACK_TAIL)
    preset[units.SHOW_UNITS]["frigate.service"].update(ActiveState="active", SubState="running")
    check = frigate_plus_check(apps, **preset)
    assert (check.status, check.detail) == ("unknown", unknown)


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


def test_a_podman_or_systemd_error_line_is_not_the_traceback():
    """podman prints a bare "Error: ..." when the unit stops a container that's gone; that isn't Frigate's exception."""
    podman = ('2026-11-04T10:00:02+0000 tm-test podman[901]: Error: no container with name or ID "frigate" found: no '
              "such container")
    assert apps_checks.traceback_last_line(TRACEBACK_TAIL + [podman]) == 'Exception: {"message":"Unauthorized"}'
    assert apps_checks.traceback_last_line([podman]) is None
    assert contracts.plus_model_id(f"plus://{MODEL_ID}") == MODEL_ID
    assert contracts.plus_model_id("plus://../x") is None
    assert contracts.plus_model_id(CORAL_PATH) is None
