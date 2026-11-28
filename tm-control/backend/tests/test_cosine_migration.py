"""tm-control migrate --node-red-cosine: Node-RED's start moves a hand-set ^/ angle out of a radar's
opt_api_commands_array into its typed key (cosine_inbound_deg / cosine_outbound_deg), so an old config.yml keeps its
correction. The printed lines and warnings name key paths, never a value."""

import json
import re
import shutil
from pathlib import Path

import pytest
from ruamel.yaml import YAML

from tm_control.core import migrate

FIXTURES = Path(__file__).resolve().parent / "fixtures"
RADAR = "TM_RADAR_SERIAL_PORT_00"
LIST_PATH = f"sensors.radars.{RADAR}.opt_api_commands_array"
OLD_LINE = "            opt_api_commands_array: '[\"^/+0.00\\n\", \"^/-0.00\\n\"]'\n"  # backslash-n, two characters


def data(text):
    return YAML(typ="safe", pure=True).load(text)


def radar_of(path):
    return data(Path(path).read_text())["sensors"]["radars"][RADAR]


def output(capsys):
    captured = capsys.readouterr()
    return captured.out + captured.err


def printed_without_paths(capsys, config):
    """What was printed with the config's path and any backup's name taken out, so a check that a value isn't in it
    can't be failed by a temp directory's number or the backup's timestamp."""
    text = output(capsys).replace(str(config), "<config>")
    return re.sub(r"\(backup: [^)]*\)", "(backup: <name>)", text)


def backups(config):
    return list(config.parent.glob("config.yml.*.bak"))


def config_with(tmp_path, entries, enabled="true", quote="'"):
    """A config.yml whose one radar holds this list of commands (a Python list, written as the template does)."""
    text = (FIXTURES / "node_red_config_ok.yml").read_text()
    written = json.dumps(entries).replace("'", "''") if quote == "'" else json.dumps(entries)
    line = f"            opt_api_commands_array: {quote}{written}{quote}\n"
    assert "            opt_api_commands_array: '[]'\n" in text
    text = text.replace("            opt_api_commands_array: '[]'\n", line)
    text = text.replace("            enabled: true\n            opt_api", f"            enabled: {enabled}\n            opt_api")
    path = tmp_path / "config.yml"
    path.write_text(text)
    return path


@pytest.fixture
def old_template(tmp_path):
    path = tmp_path / "config.yml"
    shutil.copy(FIXTURES / "node_red_config_old_template.yml", path)
    assert OLD_LINE in path.read_text()
    return path


@pytest.mark.parametrize("text, expected", [
    ("^/+20.0\n", ("inbound", 20.0)),
    (" ^/-0.00\n", ("outbound", 0.0)),
    ("^/+12.34", ("inbound", 12.3)),
    ("^/+12.35", ("inbound", 12.3)),  # the double 12.35 is just under the tie
    ("^/+0.05", ("inbound", 0.1)),  # the double 0.05 is just over it
    ("^/-89", ("outbound", 89.0)),
    ("^/-89.04", ("outbound", 89.0)),
    ("^/+89.96", ("inbound", None)),  # rounds to 90 first
    ("^/+95", ("inbound", None)),
    ("^/+abc", ("inbound", None)),
    ("^/+", ("inbound", None)),
    ("^/+-5", ("inbound", None)),
    ("^/+1e1", ("inbound", None)),
    ("^/+nan", ("inbound", None)),
    ("^/+inf", ("inbound", None)),
    ("^/20", (None, None)),
    ("^/", (None, None)),
    ("R>5\n", None),
    ("", None),
    ("  \t", None),
    ("x^/+20", None),
])
def test_cosine_command(text, expected):
    assert migrate.cosine_command(text) == expected


def test_the_limit_is_one_value_for_both_readers():
    from tm_control.modules.location import mounting

    assert migrate.COSINE_MAX_DEG == 89.0
    assert mounting.COSINE_MAX_DEG is migrate.COSINE_MAX_DEG
    assert mounting.cosine_command is migrate.cosine_command


def test_the_default_zeros_are_dropped(old_template, capsys):
    original = old_template.read_text()
    assert migrate.run_node_red_cosine(old_template) == 0
    # the fixture's empty slots have a trailing space, which any round trip drops
    expected = original.replace(OLD_LINE, "            opt_api_commands_array: '[]'\n")
    assert old_template.read_text() == re.sub(r"[ \t]+\n", "\n", expected)
    radar = radar_of(old_template)
    assert "cosine_inbound_deg" not in radar and "cosine_outbound_deg" not in radar
    assert radar["opt_api_commands_array"] == "[]"
    assert len(backups(old_template)) == 1
    printed = output(capsys)
    assert f"{old_template}: " in printed and "(backup: " in printed

    assert migrate.run_node_red_cosine(old_template) == 0
    assert output(capsys) == f"tm-control migrate: {old_template}: up to date\n"
    assert len(backups(old_template)) == 1


def test_a_hand_set_angle_moves_into_its_key(old_template):
    old_template.write_text(old_template.read_text().replace(OLD_LINE, OLD_LINE.replace("+0.00", "+12.50")))
    assert migrate.run_node_red_cosine(old_template) == 0
    assert radar_of(old_template) == {"enabled": True, "cosine_inbound_deg": 12.5, "opt_api_commands_array": "[]"}
    assert ("            enabled: true\n            cosine_inbound_deg: 12.5\n"
            "            opt_api_commands_array: '[]'\n") in old_template.read_text()


def test_an_integral_angle_is_written_with_one_decimal_and_inbound_comes_before_outbound(tmp_path):
    config = config_with(tmp_path, ["^/-20\n", "^/+30\n"])
    assert migrate.run_node_red_cosine(config) == 0
    assert ("            enabled: true\n            cosine_inbound_deg: 30.0\n            cosine_outbound_deg: 20.0\n"
            "            opt_api_commands_array: '[]'\n") in config.read_text()


def test_the_keys_go_at_the_end_of_a_radar_with_no_enabled_key(tmp_path):
    config = config_with(tmp_path, ["^/+12.5\n"])
    config.write_text(config.read_text().replace("            enabled: true\n            opt_api", "            opt_api"))
    assert migrate.run_node_red_cosine(config) == 0
    assert radar_of(config) == {"opt_api_commands_array": "[]", "cosine_inbound_deg": 12.5}
    assert ("            opt_api_commands_array: '[]'\n            cosine_inbound_deg: 12.5\n") in config.read_text()


def test_a_blank_key_that_is_there_takes_the_angle_in_place(tmp_path):
    config = config_with(tmp_path, ["^/+12.5\n"])
    config.write_text(config.read_text().replace(
        "            enabled: true\n            opt_api", "            enabled: true\n            cosine_inbound_deg:\n            opt_api"))
    assert migrate.run_node_red_cosine(config) == 0
    assert radar_of(config) == {"enabled": True, "cosine_inbound_deg": 12.5, "opt_api_commands_array": "[]"}
    assert config.read_text().count("cosine_inbound_deg") == 1


def test_other_commands_stay_in_order(tmp_path):
    config = config_with(tmp_path, ["OL", "^/+12.5\n", "R>3\n", "  ^/-0.0\n", "OM"])
    assert migrate.run_node_red_cosine(config) == 0
    radar = radar_of(config)
    assert json.loads(radar["opt_api_commands_array"]) == ["OL", "R>3\n", "OM"]
    assert radar["cosine_inbound_deg"] == 12.5 and "cosine_outbound_deg" not in radar
    assert "'[\"OL\", \"R>3\\n\", \"OM\"]'" in config.read_text()


def test_the_last_of_two_entries_for_one_direction_counts(tmp_path):
    config = config_with(tmp_path, ["^/+12.5\n", "OL", "^/+30\n"])
    assert migrate.run_node_red_cosine(config) == 0
    radar = radar_of(config)
    assert radar["cosine_inbound_deg"] == 30.0
    assert json.loads(radar["opt_api_commands_array"]) == ["OL"]


def test_a_later_zero_is_the_last_entry_and_leaves_no_key(tmp_path):
    config = config_with(tmp_path, ["^/+12.5\n", "^/+0\n"])
    assert migrate.run_node_red_cosine(config) == 0
    radar = radar_of(config)
    assert "cosine_inbound_deg" not in radar
    assert radar["opt_api_commands_array"] == "[]"


def test_an_entry_beside_a_set_key_is_removed_and_the_key_kept(tmp_path, capsys):
    config = config_with(tmp_path, ["^/+30.5\n", "^/-5\n"])
    config.write_text(config.read_text().replace(
        "            enabled: true\n            opt_api",
        "            enabled: true\n            cosine_inbound_deg: 12.5\n            opt_api"))
    assert migrate.run_node_red_cosine(config) == 0
    radar = radar_of(config)
    assert radar["cosine_inbound_deg"] == 12.5  # kept
    assert radar["cosine_outbound_deg"] == 5.0  # the blank one takes its entry
    assert radar["opt_api_commands_array"] == "[]"
    printed = printed_without_paths(capsys, config)
    assert "moved" in printed and "removed" in printed  # something was printed to check
    assert "30.5" not in printed


# "\u0663" is ARABIC-INDIC DIGIT THREE, a digit float() reads but the radar has no use for
@pytest.mark.parametrize("entry", ["^/+95\n", "^/+abc\n", "^/20\n", "^/+\u0663\n"])
def test_an_entry_that_does_not_parse_is_left_with_a_warning(tmp_path, capsys, entry):
    config = config_with(tmp_path, [entry])
    original = config.read_text()
    assert migrate.run_node_red_cosine(config) == 0
    assert config.read_text() == original
    assert backups(config) == []
    captured = capsys.readouterr()
    warnings = [line for line in captured.err.splitlines() if "WARNING" in line]
    assert len(warnings) == 1
    assert LIST_PATH in warnings[0]
    assert entry.strip() not in (captured.out + captured.err).replace(str(config), "<config>")
    assert "up to date" in captured.out


def test_an_entry_that_does_not_parse_does_not_stop_the_others(tmp_path, capsys):
    config = config_with(tmp_path, ["^/+abc\n", "^/-12.5\n", "OL"])
    assert migrate.run_node_red_cosine(config) == 0
    radar = radar_of(config)
    assert radar["cosine_outbound_deg"] == 12.5
    assert json.loads(radar["opt_api_commands_array"]) == ["^/+abc\n", "OL"]
    assert output(capsys).count("WARNING") == 1


def test_a_list_that_is_not_json_is_left_with_a_warning(tmp_path, capsys):
    config = config_with(tmp_path, [])
    config.write_text(config.read_text().replace("opt_api_commands_array: '[]'", "opt_api_commands_array: 'not ^/+5 json'"))
    original = config.read_text()
    assert migrate.run_node_red_cosine(config) == 0
    assert config.read_text() == original
    printed = output(capsys)
    assert printed.count("WARNING") == 1 and LIST_PATH in printed
    assert "not ^/+5 json" not in printed


@pytest.mark.parametrize("value", ["{\"a\": 1}", "[\"OL\", 5]", "5"])
def test_a_json_value_that_is_not_a_list_of_text_is_left_with_a_warning(tmp_path, capsys, value):
    config = config_with(tmp_path, [])
    config.write_text(config.read_text().replace("opt_api_commands_array: '[]'", f"opt_api_commands_array: '{value}'"))
    original = config.read_text()
    assert migrate.run_node_red_cosine(config) == 0
    assert config.read_text() == original
    assert output(capsys).count("WARNING") == 1


@pytest.mark.parametrize("line", ["opt_api_commands_array:", "opt_api_commands_array: ''"])
def test_a_blank_list_is_up_to_date_and_silent(tmp_path, capsys, line):
    config = config_with(tmp_path, [])
    config.write_text(config.read_text().replace("opt_api_commands_array: '[]'", line))
    assert migrate.run_node_red_cosine(config) == 0
    assert output(capsys) == f"tm-control migrate: {config}: up to date\n"


def test_a_radar_with_no_extra_commands_is_up_to_date(tmp_path, capsys):
    config = config_with(tmp_path, [])
    config.write_text(config.read_text().replace("            opt_api_commands_array: '[]'\n", ""))
    original = config.read_text()
    assert migrate.run_node_red_cosine(config) == 0
    assert config.read_text() == original
    assert output(capsys) == f"tm-control migrate: {config}: up to date\n"
    assert backups(config) == []


def test_a_file_with_no_radars_is_up_to_date(tmp_path, capsys):
    config = tmp_path / "config.yml"
    config.write_text("deployment:\n    heading_deg: 0\n")
    assert migrate.run_node_red_cosine(config) == 0
    assert output(capsys) == f"tm-control migrate: {config}: up to date\n"


def test_an_entry_with_nothing_under_it_is_skipped(tmp_path):
    config = config_with(tmp_path, ["^/+12.5\n"])
    config.write_text(config.read_text().replace(
        "    airquality_monitors:", "        TM_RADAR_SERIAL_PORT_01:\n\n    airquality_monitors:"))
    assert migrate.run_node_red_cosine(config) == 0
    assert radar_of(config)["cosine_inbound_deg"] == 12.5


def test_a_radar_that_is_off_is_converted_too(tmp_path):
    config = config_with(tmp_path, ["^/+12.5\n"], enabled="false")
    assert migrate.run_node_red_cosine(config) == 0
    assert radar_of(config)["cosine_inbound_deg"] == 12.5


def test_each_radar_is_its_own(tmp_path, capsys):
    config = config_with(tmp_path, ["^/+12.5\n"])
    config.write_text(config.read_text().replace(
        "    airquality_monitors:",
        "        TM_RADAR_SERIAL_PORT_01:\n            enabled: true\n"
        "            opt_api_commands_array: '[\"^/-7\\n\"]'\n\n    airquality_monitors:"))
    assert migrate.run_node_red_cosine(config) == 0
    radars = data(config.read_text())["sensors"]["radars"]
    assert radars[RADAR]["cosine_inbound_deg"] == 12.5 and "cosine_outbound_deg" not in radars[RADAR]
    second = radars["TM_RADAR_SERIAL_PORT_01"]
    assert second["cosine_outbound_deg"] == 7.0 and "cosine_inbound_deg" not in second
    assert len(backups(config)) == 1  # saved once


def test_a_double_quoted_list_stays_double_quoted(tmp_path):
    config = config_with(tmp_path, [])
    config.write_text(config.read_text().replace(
        "opt_api_commands_array: '[]'", 'opt_api_commands_array: "[\\"OL\\", \\"^/+12.5\\\\n\\"]"'))
    assert radar_of(config)["opt_api_commands_array"] == '["OL", "^/+12.5\\n"]'
    assert migrate.run_node_red_cosine(config) == 0
    assert 'opt_api_commands_array: "[\\"OL\\"]"\n' in config.read_text()
    assert radar_of(config)["cosine_inbound_deg"] == 12.5


def test_a_single_quote_in_a_kept_command_survives(tmp_path):
    config = config_with(tmp_path, ["it's", "^/+12.5\n"])
    assert migrate.run_node_red_cosine(config) == 0
    assert json.loads(radar_of(config)["opt_api_commands_array"]) == ["it's"]


def test_comments_and_other_keys_are_kept(tmp_path):
    config = config_with(tmp_path, ["^/+12.5\n", "OL"])
    text = config.read_text().replace(
        "            enabled: true\n            opt_api",
        "            enabled: true  # on\n            # the extra commands, sent after ours\n            opt_api")
    text = text.replace("'[\"^/+12.5\\n\", \"OL\"]'\n", "'[\"^/+12.5\\n\", \"OL\"]'  # a note\n")
    config.write_text(text)
    assert migrate.run_node_red_cosine(config) == 0
    after = config.read_text()
    # ruamel keeps a trailing comment in its column, so only the spaces before it differ
    assert re.sub(r"' +# a note", "'  # a note", after) == text.replace(
        "            enabled: true  # on\n            # the extra commands, sent after ours\n"
        "            opt_api_commands_array: '[\"^/+12.5\\n\", \"OL\"]'  # a note\n",
        "            enabled: true  # on\n            cosine_inbound_deg: 12.5\n"
        "            # the extra commands, sent after ours\n"
        "            opt_api_commands_array: '[\"OL\"]'  # a note\n")


def test_a_dry_run_writes_nothing(old_template, capsys):
    original = old_template.read_text()
    assert migrate.run_node_red_cosine(old_template, dry_run=True) == 0
    assert old_template.read_text() == original
    assert backups(old_template) == []
    printed = output(capsys)
    assert printed.startswith(f"tm-control migrate: {old_template}: would ") and "backup" not in printed


def test_no_value_is_printed(tmp_path, capsys):
    config = config_with(tmp_path, ["^/+12.5\n", "^/-34.5\n", "OL-SECRET", "^/+abc\n"])
    assert migrate.run_node_red_cosine(config, dry_run=True) == 0
    assert migrate.run_node_red_cosine(config) == 0
    printed = printed_without_paths(capsys, config)
    assert "<config>" in printed  # the paths were there to take out
    for value in ("12.5", "34.5", "SECRET", "abc"):
        assert value not in printed


def test_a_file_that_is_not_there_is_an_error(tmp_path, capsys):
    assert migrate.run_node_red_cosine(tmp_path / "missing.yml") == 1
    assert "ERROR" in output(capsys)

