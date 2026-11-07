import shutil
from pathlib import Path

import pytest

from tm_control.adapters.yamlfile import read_config
from tm_control.modules.location.config import ConfigError, NodeRedConfig, read_deployment
from tm_control.modules.location.places import Bearing

FIXTURE = Path(__file__).parent / "fixtures" / "node_red_config_ok.yml"
SURVEY = "3f9a1c2e-si"


@pytest.fixture
def path(tmp_path):
    target = tmp_path / "config.yml"
    shutil.copy(FIXTURE, target)
    return target


def backups(path):
    return list(path.parent.glob("config.yml.*.bak"))


def test_deployment_reads_the_fixture(path):
    deployment = NodeRedConfig(path).deployment()
    assert deployment.survey_id is None
    assert deployment.lat == 45.0
    assert deployment.lon == -122.0
    assert deployment.precision == "1"
    assert not deployment.survey_id_invalid
    assert not deployment.precision_invalid
    assert deployment.precision_missing


def test_deployment_normalises_quoted_and_upper_case_values(path):
    path.write_text(
        "deployment:\n    lat: '45.52252'\n    lon: '-122.6912'\n    survey_id: 3F9A1C2E-SI\n    database_precision: 2\n"
    )
    deployment = NodeRedConfig(path).deployment()
    assert deployment.lat == 45.52252
    assert deployment.lon == -122.6912
    assert deployment.survey_id == SURVEY
    assert deployment.precision == "2"
    assert not deployment.precision_missing


def test_deployment_flags_invalid_values(path):
    path.write_text("deployment:\n    survey_id: nope\n    database_precision: '3'\n")
    deployment = NodeRedConfig(path).deployment()
    assert deployment.survey_id is None and deployment.survey_id_invalid
    assert deployment.precision == "1" and deployment.precision_invalid
    assert not deployment.precision_missing  # there, but not a precision: the Status check reports it


def test_deployment_is_lenient_about_bad_coordinates(path):
    path.write_text("deployment:\n    lat: 123\n    lon: east\n")
    deployment = NodeRedConfig(path).deployment()
    assert deployment.lat is None
    assert deployment.lon is None


def test_deployment_without_a_block_is_the_defaults(path):
    path.write_text("sensors: {}\n")
    deployment = NodeRedConfig(path).deployment()
    assert (deployment.survey_id, deployment.lat, deployment.lon, deployment.precision) == (None, None, None, "1")
    assert not deployment.survey_id_invalid and not deployment.precision_invalid


def test_read_deployment_works_on_an_already_read_file(path):
    assert read_deployment(read_config(path)).lat == 45.0
    assert read_deployment(read_config(path.parent / "nope.yml")) is None


def test_sensors_lists_enabled_ones_with_the_copied_down_bearing(path):
    config = NodeRedConfig(path)
    assert config.sensors() == [
        Bearing(sensor_type="cameras", sensor_name="picam_h265", bearing="n"),
        Bearing(sensor_type="radars", sensor_name="TM_RADAR_SERIAL_PORT_00", bearing="n"),
    ]
    config.set_sensor_bearing("cameras", "picam_h265", "e")
    assert config.sensors()[0].bearing == "e"


def test_sensor_bearing_follows_the_engine_for_blank_and_invalid(path):
    path.write_text(
        "deployment:\n    bearing: 'N'\n"
        "sensors:\n    cameras:\n"
        "        a:\n            enabled: true\n"
        "        b:\n            enabled: true\n            deployment:\n                bearing:\n"
        "        c:\n            enabled: true\n            deployment:\n                bearing: up\n"
    )
    assert [b.bearing for b in NodeRedConfig(path).sensors()] == ["n", "", ""]


def test_sharing_reads_thingsboard_enabled(path):
    assert NodeRedConfig(path).sharing() == "none"
    path.write_text(path.read_text().replace("enabled: false\n    host", "enabled: true\n    host", 1))
    assert NodeRedConfig(path).sharing() == "data"


def test_set_place_writes_the_id_and_coordinates_and_keeps_comments(path):
    config = NodeRedConfig(path)
    config.set_place("3F9A1C2E-SI", 45.52252, -122.6912)
    assert config.save() is True
    text = path.read_text()
    assert "    # port: 8080" in text
    assert f"    survey_id: {SURVEY}\n\nsensors:" in text  # above the blank line that ended the block
    assert "    lat: 45.52252" in text and "    lon: -122.6912" in text
    deployment = NodeRedConfig(path).deployment()
    assert (deployment.survey_id, deployment.lat, deployment.lon) == (SURVEY, 45.52252, -122.6912)
    assert len(backups(path)) == 1


def test_set_place_keeps_the_templates_deployment_block_comments(path):
    path.write_text(
        "deployment:\n    lat: 45.0\n    lon: -122.0\n    bearing: 'n'\n"
        "    # a hand-written note\n"
        "    survey_id:  # names the place\n"
        "    database_precision: '1'  # none, 1, or 2 decimal places\n"
        "\nsensors: {}\n"
    )
    config = NodeRedConfig(path)
    config.set_place(SURVEY, 45.52252, -122.6912)
    config.set_precision("2")
    config.save()
    text = path.read_text()
    assert "# a hand-written note" in text
    assert "# names the place" in text
    assert "# none, 1, or 2 decimal places" in text
    deployment = NodeRedConfig(path).deployment()
    assert (deployment.survey_id, deployment.precision) == (SURVEY, "2")


def test_set_place_keeps_a_comment_inside_the_deployment_block(path):
    path.write_text(path.read_text().replace("    bearing: 'n'\n", "    # keep me\n    bearing: 'n'\n", 1))
    config = NodeRedConfig(path)
    config.set_place(SURVEY, 45.52252, -122.6912)
    config.save()
    assert "    # keep me\n    bearing: 'n'" in path.read_text()


def test_set_place_with_no_location_writes_empty_coordinates(path):
    config = NodeRedConfig(path)
    config.set_place(SURVEY, None, None)
    config.save()
    text = path.read_text()
    assert "    lat:\n" in text and "    lon:\n" in text
    data = read_config(path).data
    assert data["deployment"]["lat"] is None and data["deployment"]["lon"] is None
    deployment = NodeRedConfig(path).deployment()
    assert (deployment.lat, deployment.lon) == (None, None)


def test_set_precision_writes_a_quoted_string(path):
    config = NodeRedConfig(path)
    config.set_precision("none")
    config.save()
    assert NodeRedConfig(path).deployment().precision == "none"
    assert read_config(path).data["deployment"]["database_precision"] == "none"


def test_deploy_creates_missing_deployment_blocks(path):
    path.write_text(
        "thingsboard:\n    enabled: false\n    # port: 8080\n\n"
        "sensors:\n    cameras:\n        picam_h265:\n            enabled: true\n"
    )
    config = NodeRedConfig(path)
    config.set_place(SURVEY, 45.52252, -122.6912)
    config.set_precision("2")
    config.set_sensor_bearing("cameras", "picam_h265", "sw")
    assert config.save() is True
    data = read_config(path).data
    assert data["deployment"]["survey_id"] == SURVEY
    assert data["deployment"]["lat"] == 45.52252
    assert data["deployment"]["database_precision"] == "2"
    assert data["sensors"]["cameras"]["picam_h265"]["deployment"] == {"bearing": "sw"}
    assert "    # port: 8080" in path.read_text()
    assert NodeRedConfig(path).sensors() == [Bearing(sensor_type="cameras", sensor_name="picam_h265", bearing="sw")]


def test_deploy_creates_a_deployment_block_in_a_file_without_thingsboard(path):
    path.write_text("sensors:\n    cameras:\n        cam:\n            enabled: true\n")
    config = NodeRedConfig(path)
    config.set_place(SURVEY, None, None)
    config.save()
    assert read_config(path).data["deployment"]["survey_id"] == SURVEY


def test_set_sensor_bearing_refuses_an_unknown_sensor(path):
    config = NodeRedConfig(path)
    with pytest.raises(KeyError):
        config.set_sensor_bearing("cameras", "nope", "n")
    with pytest.raises(KeyError):
        config.set_sensor_bearing("radars", "picam_h265", "n")
    with pytest.raises(KeyError):
        config.set_sensor_bearing("wheels", "picam_h265", "n")


def test_concurrent_edit_is_refused(path):
    config = NodeRedConfig(path)
    with path.open("a") as handle:
        handle.write("# edited by hand\n")
    config.set_place(SURVEY, 45.52252, -122.6912)
    with pytest.raises(ConfigError) as error:
        config.save()
    assert error.value.code == "changed"
    assert path.read_text().endswith("# edited by hand\n")
    assert SURVEY not in path.read_text()
    assert backups(path) == []


def test_unchanged_edits_write_nothing(path):
    config = NodeRedConfig(path)
    config.set_precision("1")
    assert config.save() is True
    assert len(backups(path)) == 1
    config.set_precision("1")
    assert config.save() is False
    assert len(backups(path)) == 1


def test_setting_what_is_already_there_writes_nothing(path):
    config = NodeRedConfig(path)
    config.set_place(None, 45.0, -122.0)
    config.set_sensor_bearing("cameras", "picam_h265", "e")
    assert config.save() is True
    again = NodeRedConfig(path)
    again.set_sensor_bearing("cameras", "picam_h265", "e")
    assert again.save() is False


def test_errors_carry_a_code_and_no_file_text(tmp_path):
    with pytest.raises(ConfigError) as missing:
        NodeRedConfig(tmp_path / "nope.yml")
    assert missing.value.code == "missing"
    bad = tmp_path / "bad.yml"
    bad.write_text("deployment: [unclosed\n  lat: 45.52252\n")
    with pytest.raises(ConfigError) as invalid:
        NodeRedConfig(bad)
    assert invalid.value.code == "invalid"
    assert "45.52252" not in str(invalid.value)
    notmap = tmp_path / "list.yml"
    notmap.write_text("- 45.52252\n")
    with pytest.raises(ConfigError) as wrong:
        NodeRedConfig(notmap)
    assert wrong.value.code == "invalid"
    assert "45.52252" not in str(wrong.value)


def test_new_blocks_keep_the_blank_lines_between_sections(path):
    path.write_text(
        "thingsboard:\n    enabled: false\n    # port: 8080\n\n"
        "sensors:\n    cameras:\n        cam:\n            enabled: true\n\n"
        "    radars:\n        r:\n            enabled: true\n"
    )
    config = NodeRedConfig(path)
    config.set_place(SURVEY, None, None)
    config.set_sensor_bearing("cameras", "cam", "n")
    config.save()
    text = path.read_text()
    assert "    # port: 8080\n\ndeployment:\n" in text
    assert "database_precision" not in text
    assert "survey_id: 3f9a1c2e-si\n\nsensors:\n" in text
    assert "                bearing: 'n'\n\n    radars:\n" in text


def test_two_saves_back_to_back_both_succeed(path):
    first = NodeRedConfig(path)
    first.set_precision("2")
    assert first.save() is True
    second = NodeRedConfig(path)
    second.set_place(SURVEY, 45.52252, -122.6912)
    assert second.save() is True
    deployment = NodeRedConfig(path).deployment()
    assert (deployment.precision, deployment.survey_id, deployment.lat) == ("2", SURVEY, 45.52252)
    assert len(backups(path)) == 2


def test_set_survey_id_writes_only_the_id(path):
    """Reconcile names the place in the file and leaves the operator's coordinate text as it was, byte for byte."""
    path.write_text(path.read_text().replace("lat: 45.0\n    lon: -122.0\n", "lat: 45.00000\n    lon: '-122,0'\n", 1))
    before = path.read_text()
    config = NodeRedConfig(path)
    config.set_survey_id("3F9A1C2E-SI")
    assert config.save() is True
    after = path.read_text()
    assert after == before.replace("    bearing: 'n'\n", f"    bearing: 'n'\n    survey_id: {SURVEY}\n", 1)
    with pytest.raises(ValueError):
        config.set_survey_id("nope")


def test_set_survey_id_creates_a_missing_deployment_block(path):
    path.write_text("thingsboard:\n    enabled: false\n\nsensors: {}\n")
    config = NodeRedConfig(path)
    config.set_survey_id(SURVEY)
    config.save()
    assert read_config(path).data["deployment"] == {"survey_id": SURVEY}
    assert NodeRedConfig(path).deployment().survey_id == SURVEY


@pytest.mark.parametrize(
    "block, invalid",
    [
        ("lat: 45.0\n    lon: -122.0\n", False),
        ("lat: '45.52252'\n    lon: '-122.6912'\n", False),
        ("lat:\n    lon:\n", False),
        ("lat: ' '\n    lon: ''\n", False),  # blank either way
        ("lat: 45,0\n    lon: -122.0\n", True),  # a decimal comma: text, not a number
        ("lat: 123\n    lon: -122.0\n", True),  # out of range
        ("lat: 45.0\n    lon:\n", True),  # only one of the two
        ("lon: -122.0\n", True),
    ],
)
def test_coordinates_invalid_flags_a_pair_that_isnt_one(path, block, invalid):
    path.write_text(f"deployment:\n    {block}")
    assert NodeRedConfig(path).deployment().coordinates_invalid is invalid
