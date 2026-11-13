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
    assert row.zones_missing == [] and row.zones_off == []


def test_zones_off_lists_the_zones_frigate_has_turned_off():
    zones = ZONES | {"zone_near": {"enabled": False}, "zone_far": {"enabled": True}, "zone_radar": {"enabled": False}}
    [row] = compare([entry("main_st")], {"main_st": {"zones": zones}})
    assert row.zones_missing == [] and row.zones_off == ["zone_near", "zone_radar"]


def test_a_missing_zone_isnt_also_off():
    [row] = compare([entry("main_st")], {"main_st": {"zones": {"zone_capture": {"enabled": False}}}})
    assert row.zones_missing == ["zone_near", "zone_far", "zone_radar"] and row.zones_off == ["zone_capture"]


def test_a_camera_that_is_off_in_frigate_is_off_not_absent():
    [row] = compare([entry("main_st")], {"main_st": {"enabled": False, "zones": ZONES}})
    assert row.in_frigate == "off" and row.neutral is False and row.zones_missing == []


def test_an_entry_whose_camera_is_gone_is_absent():
    [row] = compare([entry("camera_1_3fa9c2", "oak_ave_wide")], {"oak_ave_tele": {}})[:1]
    assert row.in_frigate == "absent" and row.zones_missing is None and row.zones_off is None


def test_a_frigate_camera_no_entry_points_at_is_a_row_without_a_name():
    frigate = {"main_st": {}, "oak_ave_tele": {"enabled": True}}
    rows = compare([entry("main_st")], frigate)
    assert [(r.name, r.frigate_camera, r.in_frigate) for r in rows] == [
        ("main_st", "main_st", "on"), (None, "oak_ave_tele", "on"),
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


def test_a_frigate_camera_that_is_off_and_that_no_entry_points_at_is_left_out():
    rows = compare([entry("main_st")], {"main_st": {}, "oak_ave_wide": {"enabled": False}})
    assert [r.frigate_camera for r in rows] == ["main_st"]


def test_detect_is_whether_frigate_detects_objects_on_the_camera_now():
    frigate = {
        "a": {"enabled": True, "detect": {"enabled": True}},
        "b": {"enabled": True, "detect": {"enabled": False}},
        "c": {"enabled": False, "detect": {"enabled": True}},  # a camera that is off detects nothing
        "d": {"enabled": True},  # no detect section to read
        "e": {"enabled": True, "detect": {"enabled": True}},  # no entry points at it
    }
    rows = compare([entry(n) for n in "abcd"] + [entry("gone_1", "gone")], frigate)
    assert [(r.frigate_camera, r.detect) for r in rows] == [
        ("a", True), ("b", False), ("c", False), ("d", None), ("gone", None), ("e", True),
    ]


def test_detect_is_unknown_while_frigate_gives_no_cameras():
    [row] = compare([entry("main_st")], None)
    assert row.detect is None


# Each row's issues: the per-camera judgements of the config.cameras, config.zones, and config.radars checks


def issues(row):
    return [(issue.level, issue.code) for issue in row.issues]


ON = {"enabled": True, "detect": {"enabled": True}, "zones": ZONES}


def test_a_row_in_step_has_no_issues():
    [row] = compare([entry("main_st", radar="R0")], {"main_st": ON}, {"R0": True})
    assert issues(row) == []


def test_a_frigate_camera_no_entry_points_at_is_an_error():
    rows = compare([entry("main_st")], {"main_st": ON, "oak_ave_tele": ON})
    assert issues(rows[1]) == [("error", "not_paired")]


def test_a_frigate_camera_no_entry_points_at_with_detection_off_has_no_issue():
    """Nothing is detected, so nothing is dropped: the row is listed, to add or point at, with no issue."""
    rows = compare([entry("main_st")], {"main_st": ON, "oak_ave_tele": ON | {"detect": {"enabled": False}}})
    assert rows[1].name is None and rows[1].in_frigate == "on" and rows[1].detect is False
    assert issues(rows[1]) == []


def test_a_duplicate_is_an_error_and_nothing_else():
    rows = compare([entry("a_1", "main_st"), entry("b_2", "main_st")], {"main_st": ON | {"zones": {}}})
    assert issues(rows[1]) == [("error", "duplicate")]
    assert issues(rows[0]) == [("warn", "zones")]


def test_capture_off_is_a_warning_unless_detection_is_off_too():
    [row] = compare([entry("main_st", enabled=False)], {"main_st": ON})
    assert issues(row) == [("warn", "capture_off")]
    [row] = compare([entry("main_st", enabled=False)], {"main_st": ON | {"detect": {"enabled": False}}})
    assert issues(row) == []


def test_detection_off_while_capturing_is_a_warning():
    [row] = compare([entry("main_st")], {"main_st": ON | {"detect": {"enabled": False}}})
    assert issues(row) == [("warn", "detect_off")]


def test_an_enabled_entry_whose_camera_is_gone_or_off_is_a_warning():
    [row] = compare([entry("main_st")], {})
    assert issues(row) == [("warn", "gone")]
    [row] = compare([entry("main_st")], {"main_st": ON | {"enabled": False}})
    assert issues(row) == [("warn", "camera_off")]
    [row] = compare([entry("main_st", enabled=False)], {})
    assert issues(row) == []  # an entry that is off and gone records nothing either way


def test_zones_missing_or_off_are_one_warning_for_a_captured_camera():
    zones = {"zone_capture": {}, "zone_near": {"enabled": False}, "zone_far": {}}
    [row] = compare([entry("main_st")], {"main_st": ON | {"zones": zones}})
    assert issues(row) == [("warn", "zones")]
    [row] = compare([entry("main_st", enabled=False)], {"main_st": ON | {"zones": zones}})
    assert issues(row) == [("warn", "capture_off")]  # zones of a camera that isn't captured don't matter


def test_a_radar_that_isnt_enabled_is_a_warning_even_while_frigate_is_down():
    entries = [entry("a_1", radar="R0"), entry("b_2", radar="R1"), entry("c_3", radar="R9"), entry("d_4", enabled=False,
                                                                                                    radar="R1")]
    rows = compare(entries, None, {"R0": True, "R1": False})
    assert [issues(row) for row in rows] == [[], [("warn", "radar")], [("warn", "radar")], []]


def test_radars_unknown_means_no_radar_issue():
    [row] = compare([entry("main_st", radar="R9")], {"main_st": ON})
    assert issues(row) == []


def test_frigate_down_gives_no_frigate_issue():
    [row] = compare([entry("main_st")], None)
    assert issues(row) == []
