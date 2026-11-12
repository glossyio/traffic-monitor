import difflib
import shutil
from pathlib import Path

import pytest

from tm_control.adapters.yamlfile import read_config
from tm_control.modules.cameras.names import is_neutral, new_name
from tm_control.modules.location.config import CameraEntry, ConfigError, NodeRedConfig

FIXTURE = Path(__file__).parent / "fixtures" / "node_red_config_ok.yml"

# The fixture's cameras block, and a three-camera block to put in its place.
ONE_CAMERA = """\
    cameras:
        picam_h265:
            enabled: true
            camera_radar: TM_RADAR_SERIAL_PORT_00

"""
THREE_CAMERAS = """\
    cameras:
        oak_ave_wide:
            frigate_camera: oak_ave_wide
            enabled: true

        # the corner camera
        main_st:
            enabled: true  # on since spring
            camera_radar: TM_RADAR_SERIAL_PORT_00
            deployment:
                bearing: 'n'

        oak_ave_tele:
            enabled: false

"""


def config_text(edit=None) -> str:
    """The fixture's text, shaped by edit (a function of the text)."""
    text = FIXTURE.read_text()
    assert ONE_CAMERA in text
    return text if edit is None else edit(text)


def three_cameras(text: str) -> str:
    return text.replace(ONE_CAMERA, THREE_CAMERAS)


@pytest.fixture
def path(tmp_path):
    target = tmp_path / "config.yml"
    shutil.copy(FIXTURE, target)
    return target


def write(path, edit=None) -> str:
    text = config_text(edit)
    path.write_text(text)
    return text


def edited(path, change) -> str:
    """Load the file, apply change(config), save, and return the saved text."""
    config = NodeRedConfig(path)
    change(config)
    config.save()
    return path.read_text()


def changed_lines(before: str, after: str) -> list[str]:
    """The removed (-) and added (+) lines between two texts."""
    return [
        line
        for line in difflib.unified_diff(before.splitlines(), after.splitlines(), lineterm="", n=0)
        if line[:1] in "+-" and not line.startswith(("+++", "---"))
    ]


def cameras_block(text: str) -> str:
    """The lines from `    cameras:` up to the next sensor type."""
    start = text.index("    cameras:")
    return text[start:text.index("    radars:", start)]


# the neutral name


def test_new_name_counts_up_and_redraws_a_taken_token():
    assert new_name([], token=lambda n: "3fa9c2") == "camera_1_3fa9c2"
    assert new_name(["camera_4_aaaaaa", "main_st"], token=lambda n: "3fa9c2") == "camera_5_3fa9c2"
    tokens = iter(["aaaaaa", "b07e11"])
    # no two cameras share a token
    assert new_name(["camera_1_aaaaaa"], token=lambda n: next(tokens)) == "camera_2_b07e11"


def test_new_name_asks_for_three_bytes():
    asked = []
    existing = ["camera_12_aaaaaa", "camera_3_bbbbbb", "camera_x_cccccc"]
    name = new_name(existing, token=lambda n: asked.append(n) or "0f0f0f")
    assert asked == [3]
    assert name == "camera_13_0f0f0f"
    assert is_neutral(new_name([]))  # the default token is secrets.token_hex


def test_is_neutral():
    assert is_neutral("camera_1_3fa9c2")
    assert is_neutral("camera_10_000000")
    for name in ("camera_1", "camera_0_3fa9c2", "camera_1_3FA9C2", "picam_h265", "xcamera_1_3fa9c2x",
                 "camera_01_3fa9c2", "camera_1_3fa9c2\n", ""):
        assert not is_neutral(name), name


# reading


def test_cameras_reads_the_field_or_the_key(path):
    write(path, lambda text: text.replace(ONE_CAMERA, """\
    cameras:
        camera_1_3fa9c2:
            frigate_camera: oak_ave_wide
            enabled: true
            camera_radar: TM_RADAR_SERIAL_PORT_00
            plate_recognizer: true
        oak_ave_tele:
            frigate_camera: ''
            enabled: 'true'
        camera_2_b07e11:
            frigate_camera: 7
            camera_radar: ''
        main_st:

"""))
    assert NodeRedConfig(path).cameras() == [
        CameraEntry(name="camera_1_3fa9c2", frigate_camera="oak_ave_wide", enabled=True,
                    camera_radar="TM_RADAR_SERIAL_PORT_00", plate_recognizer=True),
        CameraEntry(name="oak_ave_tele", frigate_camera="oak_ave_tele", enabled=False, camera_radar=None,
                    plate_recognizer=False),
        CameraEntry(name="camera_2_b07e11", frigate_camera="camera_2_b07e11", enabled=False, camera_radar=None,
                    plate_recognizer=False),
        CameraEntry(name="main_st", frigate_camera="main_st", enabled=False, camera_radar=None,
                    plate_recognizer=False),
    ]


@pytest.mark.parametrize("block", ["", "    cameras:\n\n", "    cameras: {}\n\n", "    cameras: []\n\n"])
def test_cameras_is_empty_without_a_cameras_mapping(path, block):
    write(path, lambda text: text.replace(ONE_CAMERA, block))
    assert NodeRedConfig(path).cameras() == []


def test_radars_reads_each_radars_enabled(path):
    write(path, lambda text: text.replace(
        "            opt_api_commands_array: '[\"^/+0.00\\n\", \"^/-0.00\\n\"]'\n",
        "            opt_api_commands_array: '[\"^/+0.00\\n\", \"^/-0.00\\n\"]'\n"
        "        TM_RADAR_SERIAL_PORT_01:\n            enabled: false\n        TM_RADAR_SERIAL_PORT_02:\n",
    ))
    assert NodeRedConfig(path).radars() == {
        "TM_RADAR_SERIAL_PORT_00": True, "TM_RADAR_SERIAL_PORT_01": False, "TM_RADAR_SERIAL_PORT_02": False,
    }
    write(path, lambda text: text.replace("    radars:\n", "    old_radars:\n"))
    assert NodeRedConfig(path).radars() == {}


# adding


def test_add_camera_writes_the_entry_in_key_order(path):
    saved = edited(
        path, lambda c: c.add_camera("camera_1_3fa9c2", "oak_ave_tele", True, "TM_RADAR_SERIAL_PORT_00", False)
    )
    assert cameras_block(saved) == """\
    cameras:
        picam_h265:
            enabled: true
            camera_radar: TM_RADAR_SERIAL_PORT_00
        camera_1_3fa9c2:
            frigate_camera: oak_ave_tele
            enabled: true
            camera_radar: TM_RADAR_SERIAL_PORT_00
            plate_recognizer: false

"""
    saved = edited(path, lambda c: c.add_camera("camera_2_b07e11", "main_st", False, None, None))
    assert cameras_block(saved).endswith("""\
            plate_recognizer: false
        camera_2_b07e11:
            frigate_camera: main_st
            enabled: false

""")


def test_add_camera_keeps_a_blank_line_between_entries_when_the_file_has_them(path):
    write(path, three_cameras)
    saved = edited(path, lambda c: c.add_camera("camera_1_3fa9c2", "picam_h265", True, None, None))
    assert cameras_block(saved) == THREE_CAMERAS.replace("""\
            enabled: false

""", """\
            enabled: false

        camera_1_3fa9c2:
            frigate_camera: picam_h265
            enabled: true

""")


def test_add_camera_quotes_a_frigate_name_yaml_would_read_as_a_number(path):
    saved = edited(path, lambda c: c.add_camera("camera_1_3fa9c2", "1", True, None, None))
    assert "            frigate_camera: '1'\n" in saved
    assert read_config(path).data["sensors"]["cameras"]["camera_1_3fa9c2"]["frigate_camera"] == "1"


def test_add_camera_creates_a_missing_cameras_block(path):
    loaded = write(path, lambda text: text.replace(ONE_CAMERA, ""))
    saved = edited(path, lambda c: c.add_camera("camera_1_3fa9c2", "oak_ave_wide", True, None, None))
    assert changed_lines(loaded, saved) == [
        "+",
        "+    cameras:",
        "+        camera_1_3fa9c2:",
        "+            frigate_camera: oak_ave_wide",
        "+            enabled: true",
    ]
    assert saved.endswith(  # at the end of sensors, a blank line above it as between the others
        "            mqtt_topic_incoming: readings\n\n    cameras:\n        camera_1_3fa9c2:\n"
        "            frigate_camera: oak_ave_wide\n            enabled: true\n"
    )

    loaded = write(path, lambda text: text.replace(ONE_CAMERA, "    cameras:\n\n"))
    saved = edited(path, lambda c: c.add_camera("camera_1_3fa9c2", "oak_ave_wide", True, None, None))
    assert changed_lines(loaded, saved) == [
        "+        camera_1_3fa9c2:",
        "+            frigate_camera: oak_ave_wide",
        "+            enabled: true",
    ]
    assert cameras_block(saved) == """\
    cameras:
        camera_1_3fa9c2:
            frigate_camera: oak_ave_wide
            enabled: true

"""

    write(path, lambda text: text.replace(ONE_CAMERA, "    cameras: {}\n\n"))
    saved = edited(path, lambda c: c.add_camera("camera_1_3fa9c2", "oak_ave_wide", True, None, None))
    assert cameras_block(saved) == """\
    cameras:
        camera_1_3fa9c2:
            frigate_camera: oak_ave_wide
            enabled: true

"""

    path.write_text("thingsboard:\n    enabled: false\n\nsensors:\n\ndeployment:\n    lat:\n")
    saved = edited(path, lambda c: c.add_camera("camera_1_3fa9c2", "oak_ave_wide", True, None, None))
    assert saved == """\
thingsboard:
    enabled: false

sensors:
    cameras:
        camera_1_3fa9c2:
            frigate_camera: oak_ave_wide
            enabled: true

deployment:
    lat:
"""

    path.write_text("thingsboard:\n    enabled: false\n")
    saved = edited(path, lambda c: c.add_camera("camera_1_3fa9c2", "oak_ave_wide", True, None, None))
    assert saved == """\
thingsboard:
    enabled: false
sensors:
    cameras:
        camera_1_3fa9c2:
            frigate_camera: oak_ave_wide
            enabled: true
"""


def test_add_camera_refuses_a_taken_name_and_a_block_that_isnt_a_mapping(path):
    config = NodeRedConfig(path)
    with pytest.raises(ValueError):
        config.add_camera("picam_h265", "oak_ave_wide", True, None, None)
    write(path, lambda text: text.replace(ONE_CAMERA, "    cameras: [picam_h265]\n\n"))
    with pytest.raises(ConfigError):
        NodeRedConfig(path).add_camera("camera_1_3fa9c2", "oak_ave_wide", True, None, None)


# settings


def test_set_camera_removes_camera_radar_for_none_and_leaves_plates_for_none(path):
    write(path, three_cameras)
    loaded = path.read_text()
    saved = edited(path, lambda c: c.set_camera("main_st", False, None, None))
    assert changed_lines(loaded, saved) == [
        "-            enabled: true  # on since spring",
        "-            camera_radar: TM_RADAR_SERIAL_PORT_00",
        "+            enabled: false # on since spring",  # the comment keeps its column
    ]

    loaded = saved
    saved = edited(path, lambda c: c.set_camera("main_st", True, "TM_RADAR_SERIAL_PORT_00", True))
    assert changed_lines(loaded, saved) == [
        "-            enabled: false # on since spring",
        "+            enabled: true  # on since spring",
        "+            camera_radar: TM_RADAR_SERIAL_PORT_00",
        "+            plate_recognizer: true",
    ]

    loaded = saved
    saved = edited(path, lambda c: c.set_camera("main_st", True, "TM_RADAR_SERIAL_PORT_00", None))
    assert saved == loaded  # plates left as they were
    saved = edited(path, lambda c: c.set_camera("main_st", True, None, None))
    assert changed_lines(loaded, saved) == ["-            camera_radar: TM_RADAR_SERIAL_PORT_00"]
    assert "plate_recognizer: true" in saved


def test_set_camera_keeps_the_blank_line_when_the_last_key_goes_or_comes(path):
    loaded = path.read_text()
    saved = edited(path, lambda c: c.set_camera("picam_h265", True, None, None))
    assert cameras_block(saved) == "    cameras:\n        picam_h265:\n            enabled: true\n\n"
    saved = edited(path, lambda c: c.set_camera("picam_h265", True, "TM_RADAR_SERIAL_PORT_00", None))
    assert saved == loaded
    saved = edited(path, lambda c: c.set_camera("picam_h265", True, "TM_RADAR_SERIAL_PORT_00", False))
    assert cameras_block(saved) == ONE_CAMERA.replace("_00\n", "_00\n            plate_recognizer: false\n")


def test_set_camera_fills_in_an_empty_entry(path):
    write(path, lambda text: text.replace(ONE_CAMERA, "    cameras:\n        main_st:\n\n        oak_ave_tele:\n"
                                                      "            enabled: false\n\n"))
    saved = edited(path, lambda c: c.set_camera("main_st", True, "TM_RADAR_SERIAL_PORT_00", None))
    assert cameras_block(saved) == """\
    cameras:
        main_st:
            enabled: true
            camera_radar: TM_RADAR_SERIAL_PORT_00

        oak_ave_tele:
            enabled: false

"""


def test_set_camera_refuses_a_camera_that_isnt_there(path):
    config = NodeRedConfig(path)
    with pytest.raises(KeyError):
        config.set_camera("oak_ave_wide", True, None, None)
    with pytest.raises(KeyError):
        config.point_camera("oak_ave_wide", "main_st")
    with pytest.raises(KeyError):
        config.rename_camera("oak_ave_wide", "camera_1_3fa9c2")
    with pytest.raises(KeyError):
        config.remove_camera("oak_ave_wide")
    assert config.save() is False


# pointing


def test_point_camera_changes_one_line(path):
    loaded = write(path, three_cameras)
    saved = edited(path, lambda c: c.point_camera("oak_ave_wide", "oak_ave_wide_2"))
    assert changed_lines(loaded, saved) == [
        "-            frigate_camera: oak_ave_wide",
        "+            frigate_camera: oak_ave_wide_2",
    ]


def test_point_camera_adds_the_field_first_when_the_entry_has_none(path):
    loaded = write(path, three_cameras)
    saved = edited(path, lambda c: c.point_camera("main_st", "oak_ave_mid"))
    assert changed_lines(loaded, saved) == ["+            frigate_camera: oak_ave_mid"]
    assert "        main_st:\n            frigate_camera: oak_ave_mid\n            enabled: true" in saved


def test_point_camera_keeps_the_fields_quoting(path):
    loaded = write(path, lambda text: three_cameras(text).replace(
        "frigate_camera: oak_ave_wide", "frigate_camera: 'oak_ave_wide'"))
    saved = edited(path, lambda c: c.point_camera("oak_ave_wide", "oak_ave_east"))
    assert changed_lines(loaded, saved) == [
        "-            frigate_camera: 'oak_ave_wide'",
        "+            frigate_camera: 'oak_ave_east'",
    ]


# renaming


def test_rename_camera_keeps_place_comments_and_subkeys(path):
    loaded = write(path, three_cameras)
    saved = edited(path, lambda c: c.rename_camera("main_st", "camera_1_3fa9c2"))
    assert changed_lines(loaded, saved) == [
        "-        main_st:",
        "+        camera_1_3fa9c2:",
        "+            frigate_camera: main_st",
    ]
    assert cameras_block(saved) == """\
    cameras:
        oak_ave_wide:
            frigate_camera: oak_ave_wide
            enabled: true

        # the corner camera
        camera_1_3fa9c2:
            frigate_camera: main_st
            enabled: true  # on since spring
            camera_radar: TM_RADAR_SERIAL_PORT_00
            deployment:
                bearing: 'n'

        oak_ave_tele:
            enabled: false

"""
    names = [entry.name for entry in NodeRedConfig(path).cameras()]
    assert names == ["oak_ave_wide", "camera_1_3fa9c2", "oak_ave_tele"]


def test_rename_camera_keeps_an_existing_frigate_camera(path):
    loaded = write(path, three_cameras)
    saved = edited(path, lambda c: c.rename_camera("oak_ave_wide", "camera_1_3fa9c2"))
    assert changed_lines(loaded, saved) == ["-        oak_ave_wide:", "+        camera_1_3fa9c2:"]


@pytest.mark.parametrize(("field", "written"), [("''", "'oak_ave_wide'"), ("7", "oak_ave_wide")])
def test_rename_camera_replaces_a_field_that_names_no_camera(path, field, written):
    loaded = write(
        path, lambda text: three_cameras(text).replace("frigate_camera: oak_ave_wide", f"frigate_camera: {field}")
    )
    saved = edited(path, lambda c: c.rename_camera("oak_ave_wide", "camera_1_3fa9c2"))
    assert changed_lines(loaded, saved) == [
        "-        oak_ave_wide:",
        f"-            frigate_camera: {field}",
        "+        camera_1_3fa9c2:",
        f"+            frigate_camera: {written}",  # in the field's quoting
    ]


def test_rename_camera_fills_in_an_empty_entry_and_keeps_its_comment(path):
    loaded = write(path, lambda text: text.replace(
        ONE_CAMERA, "    cameras:\n        main_st:  # spare\n\n        oak_ave_tele:\n            enabled: false\n\n"
    ))
    saved = edited(path, lambda c: c.rename_camera("main_st", "camera_1_3fa9c2"))
    assert cameras_block(saved) == """\
    cameras:
        camera_1_3fa9c2: # spare
            frigate_camera: main_st

        oak_ave_tele:
            enabled: false

"""
    assert len(changed_lines(loaded, saved)) == 3


def test_rename_camera_refuses_a_taken_name(path):
    write(path, three_cameras)
    config = NodeRedConfig(path)
    with pytest.raises(ValueError):
        config.rename_camera("main_st", "oak_ave_tele")
    assert config.save() is False


# removing


def test_remove_camera_takes_its_comment_and_leaves_the_blank_line_layout(path):
    write(path, three_cameras)
    saved = edited(path, lambda c: c.remove_camera("main_st"))
    assert cameras_block(saved) == """\
    cameras:
        oak_ave_wide:
            frigate_camera: oak_ave_wide
            enabled: true

        oak_ave_tele:
            enabled: false

"""
    saved = edited(path, lambda c: c.remove_camera("oak_ave_tele"))
    assert cameras_block(saved) == """\
    cameras:
        oak_ave_wide:
            frigate_camera: oak_ave_wide
            enabled: true

"""


@pytest.mark.parametrize("comment", ["", "        # the wide one\n"])
def test_remove_camera_first_hands_the_next_ones_comment_up(path, comment):
    write(path, lambda text: three_cameras(text).replace(
        "    cameras:\n        oak_ave_wide:\n", f"    cameras:\n{comment}        oak_ave_wide:\n"))
    saved = edited(path, lambda c: c.remove_camera("oak_ave_wide"))
    assert cameras_block(saved) == """\
    cameras:
        # the corner camera
        main_st:
            enabled: true  # on since spring
            camera_radar: TM_RADAR_SERIAL_PORT_00
            deployment:
                bearing: 'n'

        oak_ave_tele:
            enabled: false

"""


def test_remove_the_only_camera_leaves_an_empty_block(path):
    saved = edited(path, lambda c: c.remove_camera("picam_h265"))
    assert cameras_block(saved) == "    cameras:\n\n"
    assert NodeRedConfig(path).cameras() == []
    saved = edited(path, lambda c: c.add_camera("camera_1_3fa9c2", "picam_h265", True, None, None))
    assert cameras_block(saved) == """\
    cameras:
        camera_1_3fa9c2:
            frigate_camera: picam_h265
            enabled: true

"""


# the whole file


def test_the_edited_file_still_loads_in_safe_mode(path):
    write(path, three_cameras)

    def change(config):
        config.add_camera("camera_1_3fa9c2", "picam_h265", True, None, True)
        config.rename_camera("main_st", "camera_2_b07e11")
        config.point_camera("oak_ave_wide", "oak_ave_west")
        config.set_camera("camera_2_b07e11", False, None, False)
        config.remove_camera("oak_ave_tele")

    edited(path, change)
    read = read_config(path)
    assert read.problem is None
    assert read.data["sensors"]["cameras"] == {
        "oak_ave_wide": {"frigate_camera": "oak_ave_west", "enabled": True},
        "camera_2_b07e11": {
            "frigate_camera": "main_st", "enabled": False, "deployment": {"bearing": "n"}, "plate_recognizer": False,
        },
        "camera_1_3fa9c2": {"frigate_camera": "picam_h265", "enabled": True, "plate_recognizer": True},
    }
    assert read.data["sensors"]["radars"]["TM_RADAR_SERIAL_PORT_00"]["enabled"] is True
    assert read.data["deployment"] == {"lat": 45.0, "lon": -122.0, "bearing": "n"}


def test_an_entry_that_isnt_a_mapping_is_not_edited(path):
    write(path, lambda text: text.replace("        picam_h265:\n", "        main_st: true\n        picam_h265:\n"))
    config = NodeRedConfig(path)
    assert config.cameras()[0] == CameraEntry(name="main_st", frigate_camera="main_st", enabled=False,
                                              camera_radar=None, plate_recognizer=False)
    for edit in (lambda: config.set_camera("main_st", True, None, None), lambda: config.point_camera("main_st", "x"),
                 lambda: config.rename_camera("main_st", "camera_1_3fa9c2")):
        with pytest.raises(ConfigError):
            edit()
    assert config.save() is False
