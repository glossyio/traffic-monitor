import shutil
from pathlib import Path

import pytest
import yaml

from tm_control.adapters.yamlfile import read_config
from tm_control.modules.location.config import (
    ConfigError,
    NodeRedConfig,
    SharingBlock,
    read_deployment,
    sends_public_map,
)
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
    assert deployment.precision == "2"
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
    assert deployment.precision == "2" and deployment.precision_invalid
    assert not deployment.precision_missing  # there, but not a precision: the Status check reports it


def test_deployment_is_lenient_about_bad_coordinates(path):
    path.write_text("deployment:\n    lat: 123\n    lon: east\n")
    deployment = NodeRedConfig(path).deployment()
    assert deployment.lat is None
    assert deployment.lon is None


def test_deployment_without_a_block_is_the_defaults(path):
    path.write_text("sensors: {}\n")
    deployment = NodeRedConfig(path).deployment()
    assert (deployment.survey_id, deployment.lat, deployment.lon, deployment.precision) == (None, None, None, "2")
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


def test_a_blank_bearing_adds_no_block_where_the_sensor_already_reads_blank(path):
    path.write_text("deployment:\n    bearing: ''\nsensors:\n    cameras:\n        cam:\n            enabled: true\n")
    config = NodeRedConfig(path)
    config.set_sensor_bearing("cameras", "cam", "")
    assert config.save() is False
    assert "deployment" not in read_config(path).data["sensors"]["cameras"]["cam"]


def test_a_blank_bearing_overrides_the_top_level_one_with_a_block_of_its_own(path):
    path.write_text("deployment:\n    bearing: 'n'\nsensors:\n    cameras:\n        cam:\n            enabled: true\n")
    config = NodeRedConfig(path)
    config.set_sensor_bearing("cameras", "cam", "")
    assert config.save() is True
    assert read_config(path).data["sensors"]["cameras"]["cam"]["deployment"] == {"bearing": ""}
    assert NodeRedConfig(path).sensors()[0].bearing == ""


def test_a_blank_bearing_is_written_into_a_block_the_sensor_has(path):
    path.write_text(
        "deployment:\n    bearing: ''\nsensors:\n    cameras:\n        cam:\n            enabled: true\n"
        "            deployment:\n                bearing: 'e'\n"
    )
    config = NodeRedConfig(path)
    config.set_sensor_bearing("cameras", "cam", "")
    assert config.save() is True
    assert read_config(path).data["sensors"]["cameras"]["cam"]["deployment"] == {"bearing": ""}


def test_sensor_bearing_follows_the_engine_for_blank_and_invalid(path):
    path.write_text(
        "deployment:\n    bearing: 'N'\n"
        "sensors:\n    cameras:\n"
        "        a:\n            enabled: true\n"
        "        b:\n            enabled: true\n            deployment:\n                bearing:\n"
        "        c:\n            enabled: true\n            deployment:\n                bearing: up\n"
    )
    assert [b.bearing for b in NodeRedConfig(path).sensors()] == ["n", "", ""]


def test_blank_bearings_are_the_missing_and_empty_ones_not_the_invalid(path):
    path.write_text(
        "deployment:\n    bearing: ''\n"
        "sensors:\n    cameras:\n"
        "        a:\n            enabled: true\n"
        "        b:\n            enabled: true\n            deployment:\n                bearing:\n"
        "        c:\n            enabled: true\n            deployment:\n                bearing: up\n"
        "        d:\n            enabled: true\n            deployment:\n                bearing: e\n"
        "        e:\n            enabled: false\n"
    )
    assert NodeRedConfig(path).blank_bearings() == [("cameras", "a"), ("cameras", "b")]


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


# the thingsboard: and sharing: blocks

HOST = "tb.example.invalid"
OTHER_HOST = "other.example.invalid"
CHOSEN = SharingBlock(
    target="own", host=HOST, exact_location=True, public_map="rounded_point", notice_version="own-server"
)


def between(text, first, second):
    """The text from the line `first` up to (not including) the line `second`."""
    start = text.index(first)
    return text[start:text.index(second, start)]


@pytest.mark.parametrize("block, expected", [
    ("enabled: 'true'\nhost: tb.example.invalid", {"enabled": False}),
    ("enabled: true\nhost: tb.example.invalid", {"enabled": True, "protocol": "https", "port": None}),
    ("enabled: true\nhost: '  tb.example.invalid  '\nprotocol: http\nport: 8080",
     {"host": HOST, "protocol": "http", "port": 8080}),
    ("enabled: true\nhost: https://tb.example.invalid", {"host": "https://" + HOST, "host_has_scheme": True}),
    ("enabled: true\nhost: HTTP://tb.example.invalid", {"host_has_scheme": True}),
    ("enabled: true\nhost: tb.example.invalid", {"host_has_scheme": False}),
    ("enabled: true\nhost: '   '", {"host": None, "host_has_scheme": False}),
    ("enabled: true\nhost: 42", {"host": None}),
    ("enabled: true\nhost: tb.example.invalid\nprotocol: ftp", {"protocol": "https"}),
    ("enabled: true\nhost: tb.example.invalid\nport: '8080'", {"port": 8080}),
    ("enabled: true\nhost: tb.example.invalid\nport: '  8080'", {"port": None}),
    ("enabled: true\nhost: tb.example.invalid\nport: '80a'", {"port": None}),
    ("enabled: true\nhost: tb.example.invalid\nport: '0'", {"port": None}),
    ("enabled: true\nhost: tb.example.invalid\nport: '65536'", {"port": None}),
    ("enabled: true\nhost: tb.example.invalid\nport: 70000", {"port": None}),
    ("enabled: true\nhost: tb.example.invalid\nport: true", {"port": None}),
    ("", {"enabled": False, "host": None, "protocol": "https", "port": None}),
], ids=["enabled-string", "defaults", "trimmed", "scheme-in-host", "scheme-in-any-case", "no-scheme", "blank-host",
        "number-host", "unknown-protocol", "quoted-port", "port-with-space", "port-with-letters", "quoted-port-zero",
        "quoted-port-out-of-range", "port-out-of-range", "boolean-port", "no-values"])
def test_upload_reads_the_block_leniently(tmp_path, block, expected):
    indented = "".join("    " + line + "\n" for line in block.splitlines())
    target = tmp_path / "config.yml"
    target.write_text("thingsboard:\n" + indented if block else "thingsboard:\n")
    upload = NodeRedConfig(target).upload()
    for name, value in expected.items():
        assert getattr(upload, name) == value, name


@pytest.mark.parametrize("protocol", ["http", "https", None])
@pytest.mark.parametrize("scheme, expected", [
    ("http://", "http"), ("HTTP://", "http"), ("https://", "https"), ("HTTPS://", "https"), ("", None),
])
def test_a_host_with_a_scheme_decides_the_protocol_as_node_red_builds_the_url(tmp_path, scheme, expected, protocol):
    """Node-RED keeps a host's own scheme and ignores `protocol` then; without one the protocol (https by default)."""
    target = tmp_path / "config.yml"
    lines = ["enabled: true", f"host: {scheme}tb.example.invalid"] + ([f"protocol: {protocol}"] if protocol else [])
    target.write_text("thingsboard:\n" + "".join(f"    {line}\n" for line in lines))
    upload = NodeRedConfig(target).upload()
    assert upload.host_has_scheme is (scheme != "")
    assert upload.protocol == (expected or protocol or "https")


def test_upload_without_a_block_is_off(tmp_path):
    target = tmp_path / "config.yml"
    target.write_text("deployment:\n    lat: 45.0\n")
    upload = NodeRedConfig(target).upload()
    assert upload.enabled is False and upload.host is None and upload.port is None


def test_set_upload_keeps_comments_and_writes_the_port_only_when_given(path):
    config = NodeRedConfig(path)
    config.set_upload(True, OTHER_HOST, "https", None)
    assert config.save() is True
    text = path.read_text()
    assert text.startswith(
        f"thingsboard:\n    enabled: true\n    host: {OTHER_HOST}\n    protocol: https\n    # port: 8080\n\ndeployment:"
    )
    assert "port" not in read_config(path).data["thingsboard"]

    config = NodeRedConfig(path)
    config.set_upload(True, OTHER_HOST, "http", 8080)
    config.save()
    text = path.read_text()
    assert f"    protocol: http\n    # port: 8080\n    port: 8080\n\ndeployment:" in text
    upload = NodeRedConfig(path).upload()
    assert (upload.host, upload.protocol, upload.port) == (OTHER_HOST, "http", 8080)

    config = NodeRedConfig(path)
    config.set_upload(False, OTHER_HOST, "http", None)
    config.save()
    text = path.read_text()
    assert "    enabled: false\n    host: other.example.invalid\n    protocol: http\n    # port: 8080\n\ndeployment:" in text
    assert len(backups(path)) >= 1


def test_set_upload_keeps_the_quoting_of_a_value_it_changes(path):
    path.write_text("thingsboard:\n    enabled: true\n    host: 'tb.example.invalid'  # the server\n    protocol: http\n")
    config = NodeRedConfig(path)
    config.set_upload(True, OTHER_HOST, "http", None)
    config.save()
    assert "    host: 'other.example.invalid' # the server\n" in path.read_text()  # ruamel keeps one space


def test_set_upload_creates_the_block_first_when_it_is_missing(path):
    path.write_text("deployment:\n    lat: 45.0\n    lon: -122.0\n")
    config = NodeRedConfig(path)
    config.set_upload(True, HOST, "https", 443)
    config.save()
    assert path.read_text().startswith("thingsboard:\n    enabled: true\n    host: tb.example.invalid\n")
    upload = NodeRedConfig(path).upload()
    assert (upload.enabled, upload.host, upload.protocol, upload.port) == (True, HOST, "https", 443)
    assert read_config(path).data["deployment"]["lat"] == 45.0


@pytest.mark.parametrize("protocol, port", [("ftp", None), ("http", 0), ("http", 65536), ("http", True)])
def test_set_upload_refuses_a_value_that_is_not_one(path, protocol, port):
    with pytest.raises(ValueError):
        NodeRedConfig(path).set_upload(True, HOST, protocol, port)


def test_sharing_block_is_none_without_the_key_and_all_off_for_a_non_mapping(path):
    assert NodeRedConfig(path).sharing_block() is None
    for text in ("sharing:\n", "sharing: []\n", "sharing: 3\n", "sharing: [maintainer]\n"):
        path.write_text(text)
        assert NodeRedConfig(path).sharing_block() == SharingBlock()


@pytest.mark.parametrize("block, expected", [
    ({"exact_location": "true"}, SharingBlock()),
    ({"exact_location": True}, SharingBlock(exact_location=True)),
    ({"public_map": "block"}, SharingBlock()),
    ({"public_map": "rounded_point"}, SharingBlock(public_map="rounded_point")),
    ({"target": "everyone"}, SharingBlock()),
    ({"target": "maintainer"}, SharingBlock(target="maintainer")),
    ({"notice_version": 3}, SharingBlock()),
    ({"notice_version": ""}, SharingBlock()),
    ({"notice_version": "2026-11"}, SharingBlock(notice_version="2026-11")),
    ({"host": "HTTPS://TB.Example.invalid/"}, SharingBlock(host=HOST)),
    ({"host": 42}, SharingBlock()),
    ({"host": "   "}, SharingBlock()),
])
def test_sharing_block_reads_as_node_red_does(path, block, expected):
    path.write_text(yaml.safe_dump({"sharing": block}))
    assert NodeRedConfig(path).sharing_block() == expected


def test_set_sharing_creates_the_block_after_thingsboard_and_keeps_the_blank_lines(path):
    config = NodeRedConfig(path)
    config.set_sharing(CHOSEN)
    assert config.save() is True
    text = path.read_text()
    assert between(text, "thingsboard:", "deployment:") == (
        "thingsboard:\n    enabled: false\n    host: tb.example.invalid\n    protocol: http\n    # port: 8080\n"
        "\n"
        "sharing:\n"
        "    # Written by the control app's Sharing page. A choice made here isn't recorded: use the page.\n"
        "    target: own\n"
        "    host: tb.example.invalid\n"
        "    exact_location: true\n"
        "    public_map: rounded_point\n"
        "    notice_version: 'own-server'\n"
        "\n"
    )
    assert NodeRedConfig(path).sharing_block() == CHOSEN


def test_set_sharing_writes_none_as_empty_keys(path):
    config = NodeRedConfig(path)
    config.set_sharing(SharingBlock())
    config.save()
    text = path.read_text()
    assert "    target:\n    host:\n    exact_location: false\n    public_map: none\n    notice_version:\n\ndeployment:" in text
    assert read_config(path).data["sharing"] == {
        "target": None, "host": None, "exact_location": False, "public_map": "none", "notice_version": None
    }
    assert NodeRedConfig(path).sharing_block() == SharingBlock()


def test_set_sharing_at_the_end_of_a_file_without_thingsboard(path):
    path.write_text("deployment:\n    lat: 45.0\n    lon: -122.0\n\nsensors:\n    cameras:\n        cam:\n            enabled: true\n")
    config = NodeRedConfig(path)
    config.set_sharing(CHOSEN)
    config.save()
    data = read_config(path).data
    assert list(data) == ["deployment", "sensors", "sharing"]
    assert NodeRedConfig(path).sharing_block() == CHOSEN


def test_set_sharing_after_a_last_thingsboard_block_leaves_a_blank_line(path):
    path.write_text("deployment:\n    lat: 45.0\n\nthingsboard:\n    enabled: false\n")
    config = NodeRedConfig(path)
    config.set_sharing(CHOSEN)
    config.save()
    assert "thingsboard:\n    enabled: false\n\nsharing:\n" in path.read_text()
    assert NodeRedConfig(path).sharing_block() == CHOSEN
    path.write_text("thingsboard:\n    enabled: false\n")
    config = NodeRedConfig(path)
    config.set_sharing(CHOSEN)
    config.save()
    assert path.read_text().startswith("thingsboard:\n    enabled: false\n\nsharing:\n")


def test_set_sharing_fills_a_sharing_key_with_nothing_under_it(path):
    path.write_text(path.read_text().replace("deployment:", "sharing:\n\ndeployment:", 1))
    config = NodeRedConfig(path)
    config.set_sharing(CHOSEN)
    config.save()
    assert list(read_config(path).data)[:3] == ["thingsboard", "sharing", "deployment"]
    assert NodeRedConfig(path).sharing_block() == CHOSEN
    assert "notice_version: 'own-server'\n\ndeployment:" in path.read_text()


def test_set_sharing_twice_changes_only_values(path):
    first = NodeRedConfig(path)
    first.set_sharing(CHOSEN)
    first.save()
    written = path.read_text()

    again = NodeRedConfig(path)
    again.set_sharing(CHOSEN)
    assert again.save() is False
    assert path.read_text() == written

    change = NodeRedConfig(path)
    change.set_sharing(CHOSEN.model_copy(update={"exact_location": False, "public_map": "none"}))
    assert change.save() is True
    assert path.read_text() == written.replace("exact_location: true", "exact_location: false").replace(
        "public_map: rounded_point", "public_map: none"
    )


SHARING_KEYS = ["target", "host", "exact_location", "public_map", "notice_version"]


@pytest.mark.parametrize("text", [
    "    exact_location: true\n",
    "    notice_version: old\n    target: maintainer\n",
    "    public_map: none\n    notice_version: old\n    exact_location: false\n    host: x.example.invalid\n"
    "    target: own\n",
    "    notice_version: old\n    public_map: rounded_point  # kept\n    unknown: 1\n",
], ids=["partial", "shuffled-two", "reversed", "with-extra-key"])
def test_set_sharing_puts_the_keys_in_order_whatever_the_block_had(path, text):
    path.write_text("thingsboard:\n    enabled: false\n\nsharing:\n    # my note\n" + text + "\ndeployment:\n    lat: 45.0\n")
    config = NodeRedConfig(path)
    config.set_sharing(CHOSEN)
    assert config.save() is True
    loaded = read_config(path).data
    assert list(loaded["sharing"])[:5] == SHARING_KEYS
    assert loaded["deployment"] == {"lat": 45.0}
    assert NodeRedConfig(path).sharing_block() == CHOSEN
    written = path.read_text()
    assert "    # my note\n    target:" in written
    assert "\n\ndeployment:\n" in written
    if "# kept" in text:
        assert any(line.startswith("    public_map: rounded_point") and "# kept" in line for line in written.splitlines())
    again = NodeRedConfig(path)
    again.set_sharing(CHOSEN)
    assert again.save() is False
    assert path.read_text() == written


@pytest.mark.parametrize("value", ["[]", "3", "[maintainer]", "{}", "yes"])
def test_set_sharing_replaces_a_value_that_is_not_a_mapping(path, value):
    path.write_text(f"thingsboard:\n    enabled: false\n\nsharing: {value}\n\ndeployment:\n    lat: 45.0\n")
    config = NodeRedConfig(path)
    config.set_sharing(CHOSEN)
    assert config.save() is True
    loaded = read_config(path).data
    assert list(loaded) == ["thingsboard", "sharing", "deployment"]
    assert list(loaded["sharing"]) == SHARING_KEYS
    assert NodeRedConfig(path).sharing_block() == CHOSEN
    assert "notice_version: 'own-server'\n\ndeployment:\n" in path.read_text()


@pytest.mark.parametrize("value", ["[]", "3", "[a]", "yes"])
def test_set_upload_refuses_a_thingsboard_that_is_not_a_mapping(path, value):
    path.write_text(f"thingsboard: {value}\n")
    with pytest.raises(ConfigError) as wrong:
        NodeRedConfig(path).set_upload(True, HOST, "https", None)
    assert wrong.value.code == "invalid"


def test_set_sharing_keeps_a_comment_a_person_added(path):
    first = NodeRedConfig(path)
    first.set_sharing(CHOSEN)
    first.save()
    path.write_text(path.read_text().replace("public_map: rounded_point", "public_map: rounded_point  # on"))
    config = NodeRedConfig(path)
    config.set_sharing(CHOSEN.model_copy(update={"host": OTHER_HOST}))
    config.save()
    text = path.read_text()
    assert "    public_map: rounded_point  # on\n" in text
    assert f"    host: {OTHER_HOST}\n" in text


def test_sharing_is_exact_only_for_the_host_the_choice_was_made_for(path):
    def make(enabled, upload_host, block):
        config = NodeRedConfig(path)
        config.set_upload(enabled, upload_host, "https", None)
        config.set_sharing(block)
        config.save()
        return NodeRedConfig(path).sharing()

    assert make(False, HOST, CHOSEN) == "none"
    assert make(True, HOST, CHOSEN) == "exact"
    assert make(True, "HTTPS://TB.Example.invalid/", CHOSEN) == "exact"
    assert make(True, OTHER_HOST, CHOSEN) == "data"
    assert make(True, HOST, CHOSEN.model_copy(update={"exact_location": False})) == "data"
    assert make(True, HOST, CHOSEN.model_copy(update={"host": None})) == "data"
    # the exact location goes only over https: a protocol of http, or a host written with http://, withholds it
    assert make(True, "http://tb.example.invalid", CHOSEN) == "data"
    assert make(True, "HTTP://tb.example.invalid", CHOSEN) == "data"


MAP = CHOSEN.model_copy(update={"target": "maintainer", "exact_location": False})


def test_the_public_map_is_sent_only_for_the_maintainers_host_the_choice_was_made_for(path):
    def make(enabled, upload_host, block):
        config = NodeRedConfig(path)
        config.set_upload(enabled, upload_host, "https", None)
        config.save()
        upload = NodeRedConfig(path).upload()
        return sends_public_map(upload, block)

    assert make(True, HOST, MAP) is True
    assert make(True, "HTTPS://TB.Example.invalid/", MAP) is True
    assert make(True, HOST, None) is False
    assert make(False, HOST, MAP) is False
    assert make(True, HOST, MAP.model_copy(update={"public_map": "none"})) is False
    assert make(True, HOST, MAP.model_copy(update={"target": "own"})) is False
    assert make(True, HOST, MAP.model_copy(update={"target": None})) is False
    assert make(True, OTHER_HOST, MAP) is False  # chosen for another server
    assert make(True, HOST, MAP.model_copy(update={"host": None})) is False


def test_sharing_is_data_when_the_file_has_no_sharing_block(path):
    config = NodeRedConfig(path)
    config.set_upload(True, HOST, "https", None)
    config.save()
    assert NodeRedConfig(path).sharing() == "data"


def test_the_saved_file_loads_as_node_red_would(path):
    config = NodeRedConfig(path)
    config.set_upload(True, HOST, "https", None)
    config.set_sharing(CHOSEN)
    config.save()
    loaded = yaml.safe_load(path.read_text())
    assert loaded["sharing"] == {
        "target": "own",
        "host": HOST,
        "exact_location": True,
        "public_map": "rounded_point",
        "notice_version": "own-server",
    }
    assert loaded["thingsboard"]["enabled"] is True
    assert loaded["deployment"]["lat"] == 45.0
