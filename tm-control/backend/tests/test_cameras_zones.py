"""zone_facts: what Frigate's /api/config holds for each of a camera's zones, whitelisted and in any shape Frigate or a
person left it; detect_size and distance_unit."""

import pytest

from tm_control.modules.cameras.zones import corners, detect_size, distance_unit, object_filters, zone_facts

RADAR = {
    "coordinates": "0.169,0.489,0.451,0.358,0.821,0.528,0.472,0.796", "color": [92, 160, 64],
    "distances": ["12.0", "7.3", "12.0", "7.3"], "inertia": 3, "loitering_time": 0, "speed_threshold": None,
    "objects": ["car"], "filters": {"car": {"min_area": 500}}, "friendly_name": "Oak Ave by the school",
}
CAMERA = {"detect": {"width": 1536, "height": 864}, "zones": {"zone_radar": RADAR}}


def test_a_zone_with_side_lengths():
    [zone] = zone_facts(CAMERA)
    assert (zone.key, zone.color, zone.enabled, zone.drawn) == ("zone_radar", "#40a05c", True, True)
    assert [(c.letter, c.x, c.y) for c in zone.corners] == [
        ("A", 0.169, 0.489), ("B", 0.451, 0.358), ("C", 0.821, 0.528), ("D", 0.472, 0.796)]
    assert zone.distances == [12.0, 7.3, 12.0, 7.3]
    assert [(s.start, s.end, s.length) for s in zone.sides] == [
        ("A", "B", 12.0), ("B", "C", 7.3), ("C", "D", 12.0), ("D", "A", 7.3)]
    assert (zone.inertia, zone.loitering_time, zone.speed_threshold) == (3, 0, None)
    assert zone.objects == ["car"] and zone.filters == {"car": {"min_area": 500}}


def test_frigates_name_for_a_zone_is_never_copied():
    assert "Oak Ave" not in zone_facts(CAMERA)[0].model_dump_json()


def test_a_zones_filters_keep_only_the_size_ratio_and_score_keys():
    filters = {
        "car": {"min_area": 500, "max_area": 0.5, "min_ratio": 0.4, "max_ratio": 2, "threshold": 0.7, "min_score": 0.5,
                "friendly_name": "Oak Ave by the school", "mask": "0,0,1,1", "raw_mask": {"a": 1}},
        "bus": {"friendly_name": {"nested": "Oak Ave"}, "min_area": True},
        "bike": "text",
        7: {"min_area": 1},
    }
    [zone] = zone_facts({"zones": {"z": RADAR | {"filters": filters}}})
    assert zone.filters == {
        "car": {"min_area": 500, "max_area": 0.5, "min_ratio": 0.4, "max_ratio": 2, "threshold": 0.7,
                "min_score": 0.5},
        "bus": {},
    }
    assert "Oak Ave" not in zone.model_dump_json()


@pytest.mark.parametrize("coordinates, corners", [
    (["0.1,0.2", "0.3,0.4", "0.5,0.6"], [(0.1, 0.2), (0.3, 0.4), (0.5, 0.6)]),   # a list
    # Frigate's API gives fractions, above 1 or below 0 where the zone runs past the frame's edge (a bench unit's
    # zone_near, whose config.yml has pixel points past the frame)
    ("1.1,0.804,0.882,0.652,0.279,0.873,0.537,1.137",
     [(1.1, 0.804), (0.882, 0.652), (0.279, 0.873), (0.537, 1.137)]),
    ("-0.05,0.2,0.3,0.4,0.5,0.6", [(-0.05, 0.2), (0.3, 0.4), (0.5, 0.6)]),
    ("0.1,0.2,0.3,0.4", []),                                                     # two points
    ("0.1,0.2,0.3,0.4,0.5", []),                                                 # an odd count
    ("0.1,0.2,0.3,nan,0.5,0.6", []), ("a,b,c,d,e,f", []), (None, []), (7, []),
])
def test_corners(coordinates, corners):
    [zone] = zone_facts({"detect": {"width": 1536, "height": 864}, "zones": {"z": {"coordinates": coordinates}}})
    assert [(c.x, c.y) for c in zone.corners] == corners and zone.drawn is bool(corners)


def test_corners_need_no_detect_size():
    corners = zone_facts({"zones": {"z": {"coordinates": "1.1,0.804,0.882,0.652,0.279,0.873"}}})[0].corners
    assert [(c.x, c.y) for c in corners] == [(1.1, 0.804), (0.882, 0.652), (0.279, 0.873)]


def test_a_zone_that_is_off_is_listed_and_not_drawn():
    [zone] = zone_facts({"zones": {"z": RADAR | {"enabled": False}}})
    assert (zone.enabled, zone.drawn, len(zone.corners)) == (False, False, 4)


@pytest.mark.parametrize("value", [{}, None, "text", [1, 2]])
def test_a_zone_in_an_odd_shape_is_still_listed(value):
    [zone] = zone_facts({"zones": {"zone_lane_bus": value}})
    assert (zone.key, zone.color, zone.enabled, zone.corners, zone.sides, zone.filters) == (
        "zone_lane_bus", None, True, [], [], {})


@pytest.mark.parametrize("color", [None, [1, 2], [1, 2, 256], ["a", "b", "c"], "red", [1.5, 2, 3]])
def test_an_odd_colour_is_none(color):
    assert zone_facts({"zones": {"z": {"color": color}}})[0].color is None


def test_lengths_are_listed_by_side_only_with_one_per_corner():
    triangle = RADAR | {"coordinates": "0.1,0.1,0.9,0.1,0.5,0.9"}
    [zone] = zone_facts({"zones": {"z": triangle}})
    assert zone.distances == [12.0, 7.3, 12.0, 7.3] and zone.sides == []


def test_thirty_corners_are_lettered_past_z():
    points = ",".join(f"0.{i:02d},0.5" for i in range(30))
    letters = [c.letter for c in zone_facts({"zones": {"z": {"coordinates": points}}})[0].corners]
    assert letters[25:28] == ["Z", "AA", "AB"] and len(set(letters)) == 30


@pytest.mark.parametrize("camera", [{}, {"zones": None}, {"zones": ["a"]}, {"zones": "text"}])
def test_no_zones(camera):
    assert zone_facts(camera) == []


def test_detect_size_and_distance_unit():
    assert detect_size(CAMERA) == (1536, 864)
    assert detect_size({"detect": {"width": 0, "height": 864}}) is None and detect_size({}) is None
    assert distance_unit({"ui": {"unit_system": "imperial"}}) == "ft"
    assert distance_unit({"ui": {"unit_system": "metric"}}) == "m" and distance_unit({}) == "m"


def test_corners_and_object_filters_are_public_and_give_what_a_zone_holds():
    [zone] = zone_facts({"zones": {"z": RADAR}})
    assert corners(RADAR["coordinates"]) == zone.corners
    assert [(c.x, c.y) for c in corners(["0.1,0.2", "0.3,0.4", "0.5,0.6"])] == [(0.1, 0.2), (0.3, 0.4), (0.5, 0.6)]
    assert corners("0.1,0.2") == [] and corners(None) == []
    assert object_filters(RADAR["filters"]) == zone.filters == {"car": {"min_area": 500}}
    assert object_filters({"car": {"min_area": 500, "colour": "x", "threshold": "high"}, "bus": 3}) == {
        "car": {"min_area": 500}}
    assert object_filters(None) == {}
