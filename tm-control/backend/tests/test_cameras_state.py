"""compare: the file's sensors.cameras entries against Frigate's cameras, in one place for the page and the checks."""

from tm_control.modules.cameras.state import compare
from tm_control.modules.location.config import CameraEntry

ZONES = {zone: {} for zone in ("zone_capture", "zone_near", "zone_far", "zone_radar")}


def entry(name, frigate_camera=None, enabled=True, radar=None, plates=False):
    return CameraEntry(name, frigate_camera or name, enabled, radar, plates)


def test_an_entry_in_step_with_frigate():
    rows = compare([entry("camera_1_3fa9c2", "oak_ave_wide", radar="TM_RADAR_SERIAL_PORT_00")],
                   {"oak_ave_wide": {"enabled": True, "zones": ZONES}})
    [row] = rows
    assert (row.name, row.frigate_camera, row.in_frigate) == ("camera_1_3fa9c2", "oak_ave_wide", "on")
    assert row.neutral is True and row.duplicate_of is None
    assert (row.enabled, row.camera_radar, row.plate_recognizer) == (True, "TM_RADAR_SERIAL_PORT_00", False)
    assert row.zones_missing == []


def test_a_camera_that_is_off_in_frigate_is_off_not_absent():
    [row] = compare([entry("main_st")], {"main_st": {"enabled": False, "zones": ZONES}})
    assert row.in_frigate == "off" and row.neutral is False and row.zones_missing == []


def test_an_entry_whose_camera_is_gone_is_absent():
    [row] = compare([entry("camera_1_3fa9c2", "oak_ave_wide")], {"oak_ave_tele": {}})[:1]
    assert row.in_frigate == "absent" and row.zones_missing is None


def test_a_frigate_camera_no_entry_points_at_is_a_row_without_a_name():
    frigate = {"main_st": {}, "oak_ave_tele": {"enabled": True}, "oak_ave_wide": {"enabled": False}}
    rows = compare([entry("main_st")], frigate)
    assert [(r.name, r.frigate_camera, r.in_frigate) for r in rows] == [
        ("main_st", "main_st", "on"), (None, "oak_ave_tele", "on"), (None, "oak_ave_wide", "off"),
    ]
    unpointed = rows[1]
    assert (unpointed.neutral, unpointed.duplicate_of, unpointed.enabled) == (None, None, None)
    assert (unpointed.camera_radar, unpointed.plate_recognizer) == (None, None)
    assert unpointed.zones_missing == ["zone_capture", "zone_near", "zone_far", "zone_radar"]


def test_a_second_entry_for_the_same_camera_is_a_duplicate_of_the_first():
    rows = compare([entry("camera_1_3fa9c2", "oak_ave_wide"), entry("main_st", "oak_ave_wide")], {"oak_ave_wide": {}})
    assert [(r.name, r.duplicate_of) for r in rows] == [("camera_1_3fa9c2", None), ("main_st", "camera_1_3fa9c2")]
    assert [r.in_frigate for r in rows] == ["on", "on"]


def test_zones_missing_lists_what_frigate_lacks():
    [row] = compare([entry("main_st")], {"main_st": {"zones": {"zone_capture": {}, "zone_radar": {}}}})
    assert row.zones_missing == ["zone_near", "zone_far"]


def test_zones_of_odd_shapes_count_as_missing():
    [row] = compare([entry("main_st")], {"main_st": {"zones": None}})
    assert row.zones_missing == ["zone_capture", "zone_near", "zone_far", "zone_radar"]


def test_without_frigates_cameras_every_entry_is_unknown_and_nothing_is_added():
    rows = compare([entry("main_st"), entry("camera_1_3fa9c2", "oak_ave_wide", enabled=False)], None)
    assert [(r.name, r.in_frigate, r.zones_missing) for r in rows] == [
        ("main_st", "unknown", None), ("camera_1_3fa9c2", "unknown", None),
    ]
    assert rows[1].enabled is False


def test_frigate_with_no_cameras_is_absent_not_unknown():
    [row] = compare([entry("main_st")], {})
    assert row.in_frigate == "absent"


def test_a_duplicate_is_still_found_while_frigate_is_down():
    rows = compare([entry("a_1", "oak_ave_wide"), entry("b_2", "oak_ave_wide")], None)
    assert [r.duplicate_of for r in rows] == [None, "a_1"]
