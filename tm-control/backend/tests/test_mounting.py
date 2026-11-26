"""The mounting rules: tilt and distance from each other, the usual mounts, which changes count, the question, and the
answer chosen in advance. Only the fixtures' coordinates-free values appear here."""

import math

import pytest
from pydantic import ValidationError
from ruamel.yaml.scalarfloat import ScalarFloat
from ruamel.yaml.scalarint import ScalarInt

from tm_control.modules.location import mounting as m

CAMERA = ("cameras", "picam_h265")
RADAR = ("radars", "TM_RADAR_SERIAL_PORT_00")


def mounting(key=CAMERA, **values) -> m.Mounting:
    return m.Mounting(sensor_type=key[0], sensor_name=key[1], **values)


def raw_mounting(key=CAMERA, **values) -> m.Mounting:
    """A Mounting built without validation, as a caller that skipped pydantic's checks would hand over."""
    return m.Mounting.model_construct(sensor_type=key[0], sensor_name=key[1], **values)


# --- tilt and distance from each other -------------------------------------------------------------------------


@pytest.mark.parametrize("height, tilt, distance", [(2.13, 15, 7.95), (3.66, 15, 13.66), (4.88, 15, 18.21)])
def test_distance_from_tilt(height, tilt, distance):
    given = m.checked(mounting(height_m=height, pitch_deg=tilt, measured="pitch"))
    assert (given.pitch_deg, given.view_distance_m) == (float(tilt), distance)


def test_tilt_from_distance():
    given = m.checked(mounting(height_m=3.66, view_distance_m=13.72, measured="distance"))
    assert (given.pitch_deg, given.view_distance_m) == (14.9, 13.72)


def test_the_edges_of_the_two_conversions():
    assert m.checked(mounting(height_m=2.13, pitch_deg=90, measured="pitch")).view_distance_m == 0.0
    assert m.checked(mounting(height_m=2.13, pitch_deg=0, measured="pitch")).view_distance_m is None
    assert m.checked(mounting(height_m=2.13, view_distance_m=0, measured="distance")).pitch_deg == 90.0
    # a result over 1,000 m is none
    assert m.checked(mounting(height_m=2.13, pitch_deg=0.1, measured="pitch")).view_distance_m is None


def test_without_a_height_only_the_measured_one_is_kept():
    tilt = m.checked(mounting(pitch_deg=15, view_distance_m=7.95, measured="pitch"))
    assert (tilt.pitch_deg, tilt.view_distance_m, tilt.height_m) == (15.0, None, None)
    distance = m.checked(mounting(pitch_deg=15, view_distance_m=7.95, measured="distance"))
    assert (distance.pitch_deg, distance.view_distance_m) == (None, 7.95)


def test_an_empty_measured_value_empties_both():
    for measured in ("pitch", "distance"):
        given = m.checked(mounting(height_m=2.13, pitch_deg=15 if measured == "distance" else None,
                                   view_distance_m=7.95 if measured == "pitch" else None, measured=measured))
        assert (given.measured, given.pitch_deg, given.view_distance_m) == (None, None, None)
        assert given.height_m == 2.13


def test_checked_rounds():
    given = m.checked(mounting(height_m=2.134, pitch_deg=14.96, measured="pitch"))
    assert (given.height_m, given.pitch_deg) == (2.13, 15.0)
    level = m.checked(mounting(height_m=2.13, pitch_deg=-0.04, measured="pitch")).pitch_deg
    assert level == 0.0 and math.copysign(1.0, level) == 1.0  # 0, never -0.0 in config.yml


def test_the_limit_is_checked_on_the_rounded_value():
    """90.04 is kept as 90.0; 0.004 rounds to 0 and a height of 0 is refused (ruling R7)."""
    assert m.checked(mounting(pitch_deg=90.04, measured="pitch")).pitch_deg == 90.0
    assert m.checked(mounting(pitch_deg=-0.04, measured="pitch")).pitch_deg == 0.0
    assert m.checked(mounting(height_m=100.004)).height_m == 100.0
    with pytest.raises(m.MountingError) as raised:
        m.checked(mounting(height_m=0.004))
    assert raised.value.field == "height_m"


def test_the_mount_is_checked_against_the_mounts_given():
    assert m.checked(mounting(mount="pole")).mount == "pole"
    other = (m.Mount(key="roof", title="Roof", height_m=9.0, pitch_deg=30.0),)
    assert m.checked(mounting(mount="roof"), other).mount == "roof"
    with pytest.raises(m.MountingError):
        m.checked(mounting(mount="pole"), other)


def test_the_mount_the_file_holds_passes_as_it_is():
    """A key typed into config.yml by hand that isn't one of the usual mounts can be sent back, and only that one."""
    assert m.checked(mounting(mount="roof_rack"), keep="roof_rack").mount == "roof_rack"
    assert m.checked(mounting(mount="pole"), keep="roof_rack").mount == "pole"
    assert m.checked(mounting(), keep="roof_rack").mount is None
    for keep in (None, "roof_rack"):
        with pytest.raises(m.MountingError) as raised:
            m.checked(mounting(mount="van_roof"), keep=keep)
        assert raised.value.field == "mount"


def test_the_usual_mounts():
    assert [(x.key, x.title, x.height_m, x.pitch_deg) for x in m.MOUNTS] == [
        ("tripod", "Tripod beside the road", 2.13, 15.0),
        ("pole", "Pole or sign post", 3.66, 15.0),
        ("window", "Upstairs window over an intersection", 4.88, 15.0),
    ]


# --- the strict reader for the API -----------------------------------------------------------------------------

AIR = ("airquality_monitors", "aq_1")
REFUSED = [
    ("heading_deg", 360), ("heading_deg", -1), ("heading_deg", 40.5), ("heading_deg", True),
    ("pitch_deg", 90.06), ("pitch_deg", -0.06), ("pitch_deg", True), ("pitch_deg", "15"),
    ("pitch_deg", float("nan")), ("pitch_deg", math.inf),
    ("height_m", 0), ("height_m", 0.004), ("height_m", 100.006), ("height_m", False), ("height_m", "2.13"),
    ("height_m", -2.0),
    ("view_distance_m", -0.006), ("view_distance_m", 1000.006), ("view_distance_m", True),
    ("view_distance_m", "7.95"), ("view_distance_m", 1e30),
    ("mount", "bench"), ("mount", ""), ("mount", "Pole"), ("mount", 5),
    ("measured", "height"), ("measured", ""),
]


@pytest.mark.parametrize("field, value", REFUSED)
def test_checked_refuses(field, value):
    values = {"height_m": 3.66, "pitch_deg": 15.0, "measured": "pitch", **{field: value}}
    if field == "view_distance_m":
        values["measured"] = "distance"
    with pytest.raises(m.MountingError) as raised:
        m.checked(raw_mounting(**values))
    assert raised.value.field == field
    if str(value) not in ("", "0"):  # the sentences hold a 0 and the empty text, whatever the value
        assert repr(value) not in str(raised.value) and str(value) not in str(raised.value)


@pytest.mark.parametrize("field, value", [("pitch_deg", 12.5), ("view_distance_m", 9.0)])
def test_a_tilt_or_distance_needs_measured(field, value):
    with pytest.raises(m.MountingError) as raised:
        m.checked(mounting(height_m=3.66, **{field: value}))
    assert raised.value.field == field
    assert str(value) not in str(raised.value)


@pytest.mark.parametrize("field, value", [("pitch_deg", 15.0), ("height_m", 3.0), ("view_distance_m", 8.0),
                                          ("mount", "pole"), ("measured", "pitch")])
def test_an_air_quality_monitor_has_a_heading_only(field, value):
    with pytest.raises(m.MountingError) as raised:
        m.checked(mounting(AIR, heading_deg=40, **{field: value}))
    assert raised.value.field == field
    assert m.checked(mounting(AIR, heading_deg=40)).heading_deg == 40


@pytest.mark.parametrize("sent", [5000, -1, True, "x", float("nan"), [1]])
def test_the_unmeasured_one_is_ignored_whatever_was_sent(sent):
    """Ruling R10: no type check, no limit check, nothing raised for the one that is worked out."""
    tilt = m.checked(raw_mounting(height_m=2.13, pitch_deg=15.0, view_distance_m=sent, measured="pitch"))
    assert (tilt.pitch_deg, tilt.view_distance_m) == (15.0, 7.95)
    distance = m.checked(raw_mounting(height_m=3.66, pitch_deg=sent, view_distance_m=13.72, measured="distance"))
    assert (distance.pitch_deg, distance.view_distance_m) == (14.9, 13.72)
    # with no height there is nothing to work out, and the junk is still ignored
    assert m.checked(raw_mounting(pitch_deg=15.0, view_distance_m=sent, measured="pitch")).view_distance_m is None


def test_the_measured_one_keeps_every_check():
    with pytest.raises(m.MountingError) as raised:
        m.checked(raw_mounting(height_m=2.13, pitch_deg=91.0, view_distance_m=5.0, measured="pitch"))
    assert raised.value.field == "pitch_deg"
    with pytest.raises(m.MountingError) as raised:
        m.checked(raw_mounting(height_m=2.13, pitch_deg=15.0, view_distance_m=1000.06, measured="distance"))
    assert raised.value.field == "view_distance_m"


def test_a_heading_alone_is_kept():
    given = m.checked(mounting(heading_deg=359))
    assert (given.heading_deg, given.pitch_deg, given.height_m, given.view_distance_m, given.mount) == (
        359, None, None, None, None)


def test_the_model_refuses_what_pydantic_would_coerce():
    for field, value in (("heading_deg", "40"), ("pitch_deg", "15"), ("height_m", True), ("pitch_deg", True)):
        with pytest.raises(ValidationError):
            mounting(**{field: value})


# --- read, the lenient reader of config.yml's block --------------------------------------------------------------

GIVEN_MOUNTING = {"pitch_deg": 14.94, "height_m": 2.134, "view_distance_m": 7.951, "mount": "tripod"}
KEPT_MOUNTING = {"pitch_deg": 14.9, "height_m": 2.13, "view_distance_m": 7.95, "mount": "tripod"}
BAD_MOUNTING = [("pitch_deg", 91), ("pitch_deg", -1), ("pitch_deg", "15"), ("pitch_deg", True), ("height_m", 0),
                ("height_m", 101), ("height_m", "2"), ("view_distance_m", -1), ("view_distance_m", 1001),
                ("mount", "Tripod!"), ("mount", "m" * 33), ("mount", 5)]
NONE = dict.fromkeys(("pitch_deg", "height_m", "view_distance_m", "mount"))


def read_values(raw) -> dict:
    read = m.read(*CAMERA, raw)
    assert (read.sensor_type, read.sensor_name, read.measured) == (*CAMERA, None)
    return {key: getattr(read, key) for key in ("pitch_deg", "height_m", "view_distance_m", "mount")}


@pytest.mark.parametrize("given, expected", [
    ({}, NONE),
    (dict.fromkeys(NONE), NONE),
    (dict.fromkeys(NONE, ""), NONE),
    (GIVEN_MOUNTING, KEPT_MOUNTING),
    *[({**GIVEN_MOUNTING, key: bad}, {**KEPT_MOUNTING, key: None}) for key, bad in BAD_MOUNTING],
])
def test_read_drops_what_the_flows_drop(given, expected):
    assert read_values({"heading_deg": 40, **given}) == expected


@pytest.mark.parametrize("key, value", [("pitch_deg", 0), ("pitch_deg", 90), ("height_m", 0.01), ("height_m", 100),
                                        ("view_distance_m", 0), ("view_distance_m", 1000)])
def test_read_limits_are_inclusive(key, value):
    assert read_values({key: value})[key] == value


def test_read_takes_the_heading_as_the_flows_do():
    assert m.read(*CAMERA, {"heading_deg": 40}).heading_deg == 40
    assert m.read(*CAMERA, {"heading_deg": 40.0}).heading_deg == 40
    assert m.read(*CAMERA, {"heading_deg": ""}).heading_deg is None
    assert m.read(*CAMERA, {"heading_deg": None, "bearing": " NE "}).heading_deg == 45
    assert m.read(*CAMERA, {"heading_deg": 360}).heading_deg is None
    assert m.read(*CAMERA, {"heading_deg": True}).heading_deg is None


def test_read_takes_the_round_trip_loaders_numbers():
    given = {"heading_deg": ScalarInt(40), "pitch_deg": ScalarFloat(14.94), "height_m": ScalarInt(3)}
    read = m.read(*CAMERA, given)
    assert (read.heading_deg, read.pitch_deg, read.height_m) == (40, 14.9, 3.0)


def test_read_never_raises():
    for raw in (None, [], "x", 5, {"pitch_deg": float("nan"), "height_m": math.inf, "view_distance_m": 1e300},
                {"height_m": float("-inf"), "mount": ["pole"]}, {"mount": "pole\n"}):
        read = m.read(*CAMERA, raw)
        assert (read.pitch_deg, read.height_m, read.view_distance_m, read.mount) == (None,) * 4


def test_read_does_not_trim_or_lower_case_the_mount():
    """Ruling R8: the key is taken as written, and a trailing newline is no key."""
    for mount in ("Tripod", " tripod", "tripod\n"):
        assert m.read(*CAMERA, {"mount": mount}).mount is None
    assert m.read(*CAMERA, {"mount": "roof_2"}).mount == "roof_2"


def test_read_rounds_on_the_exact_value():
    """90.05, 100.005 and 1000.005 are held a hair below the half, so they round back inside their limits; 0.005 is a
    hair above, so a height of it is 0.01; 90.06 and 100.006 round outside."""
    assert read_values({"pitch_deg": 90.05})["pitch_deg"] == 90.0
    assert read_values({"pitch_deg": 90.06})["pitch_deg"] is None
    assert read_values({"height_m": 100.005})["height_m"] == 100.0
    assert read_values({"height_m": 100.006})["height_m"] is None
    assert read_values({"view_distance_m": 1000.005})["view_distance_m"] == 1000.0
    assert read_values({"view_distance_m": 1000.006})["view_distance_m"] is None
    assert read_values({"height_m": 0.005})["height_m"] == 0.01
    assert read_values({"height_m": 0.004})["height_m"] is None
    assert read_values({"pitch_deg": -0.04})["pitch_deg"] == 0.0


# --- a turn ----------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("old, new, expected", [(350, 10, 20), (10, 350, 20), (45, 90, 45), (45, 40, 5), (0, 180, 180),
                                                (0, 0, 0), (90, 270, 180), (None, 40, None), (40, None, None),
                                                (None, None, None)])
def test_a_turn_is_the_smaller_angle(old, new, expected):
    assert m.turn(mounting(heading_deg=old), mounting(heading_deg=new)) == expected


# --- which changes count, the question, and the answer chosen in advance ---------------------------------------


def review(old, new, recorded=None, moved=None):
    return m.review([old] if isinstance(old, m.Mounting) else old, [new] if isinstance(new, m.Mounting) else new,
                    recorded or {}, moved)


def changes(result):
    return [(c.sensor_name, c.field, c.counts) for c in result.changes]


def test_filling_an_empty_value_does_not_count():
    result = review(mounting(), mounting(heading_deg=40, height_m=2.13, pitch_deg=15.0, measured="pitch",
                                         view_distance_m=7.95, mount="tripod"))
    assert [(c.field, c.counts) for c in result.changes] == [
        ("heading_deg", False), ("pitch_deg", False), ("height_m", False), ("mount", False)]
    assert result.ask is False and result.suggested is None


def test_the_mount_never_counts():
    result = review(mounting(mount="pole"), mounting(mount="tripod"))
    assert changes(result) == [(CAMERA[1], "mount", False)]
    assert result.ask is False
    assert changes(review(mounting(mount="pole"), mounting())) == [(CAMERA[1], "mount", False)]


def test_clearing_a_value_counts():
    old = mounting(heading_deg=40, height_m=2.13, pitch_deg=15.0, measured="pitch", view_distance_m=7.95)
    result = review(old, mounting())
    assert [(c.field, c.counts) for c in result.changes] == [
        ("heading_deg", True), ("pitch_deg", True), ("height_m", True)]
    assert result.ask is True


def test_nothing_recorded_does_not_ask():
    old, new = mounting(heading_deg=40), mounting(heading_deg=90)
    result = review(old, new, {CAMERA: False})
    assert changes(result) == [(CAMERA[1], "heading_deg", True)]
    assert result.ask is False and result.suggested is None


@pytest.mark.parametrize("recorded", [True, None])
def test_an_unknown_recorded_asks(recorded):
    old, new = mounting(heading_deg=40), mounting(heading_deg=90)
    assert review(old, new, {CAMERA: recorded}).ask is True
    assert review(old, new, {}).ask is True


def test_the_question_is_asked_per_sensor():
    """A counting change where nothing was recorded asks nothing, even beside a sensor whose row has traffic."""
    old = [mounting(heading_deg=40), mounting(RADAR, heading_deg=40)]
    new = [mounting(heading_deg=90), mounting(RADAR, heading_deg=40)]
    result = review(old, new, {CAMERA: False, RADAR: True})
    assert changes(result) == [(CAMERA[1], "heading_deg", True)]
    assert result.ask is False and result.suggested is None


def test_a_save_that_changes_nothing_that_counts_does_not_ask():
    result = review(mounting(heading_deg=40), mounting(heading_deg=40, height_m=2.13))
    assert result.ask is False


@pytest.mark.parametrize("old, new, suggested", [
    (dict(heading_deg=40), dict(heading_deg=59), "measured"),
    (dict(heading_deg=40), dict(heading_deg=60), "moved"),
    (dict(heading_deg=350), dict(heading_deg=9), "measured"),
    (dict(heading_deg=350), dict(heading_deg=10), "moved"),
    (dict(height_m=2.13), dict(height_m=2.42), "measured"),
    (dict(height_m=2.13), dict(height_m=2.43), "moved"),
    (dict(height_m=2.2), dict(height_m=2.5), "moved"),
    (dict(height_m=2.5), dict(height_m=2.2), "moved"),
    (dict(pitch_deg=15.0, measured="pitch"), dict(pitch_deg=19.9, measured="pitch"), "measured"),
    (dict(pitch_deg=15.0, measured="pitch"), dict(pitch_deg=20.0, measured="pitch"), "moved"),
    (dict(pitch_deg=20.0, measured="pitch"), dict(pitch_deg=15.0, measured="pitch"), "moved"),
    # a measured distance: the tilt worked out from it is what is sized
    (dict(height_m=2.13, view_distance_m=7.95, measured="distance"),
     dict(height_m=2.13, view_distance_m=7.0, measured="distance"), "measured"),
    (dict(height_m=2.13, view_distance_m=7.95, measured="distance"),
     dict(height_m=2.13, view_distance_m=5.0, measured="distance"), "moved"),
    # a distance changed with no tilt on either side
    (dict(view_distance_m=7.95, measured="distance"), dict(view_distance_m=30.0, measured="distance"), "measured"),
], ids=lambda value: str(value)[:30])
def test_the_answer_chosen(old, new, suggested):
    def worked(values):
        return m.checked(mounting(**values)) if "measured" in values else mounting(**values)
    result = review(worked(old), worked(new))
    assert result.ask is True
    assert result.suggested == suggested


def distance_measured(height, distance):
    return m.checked(mounting(height_m=height, view_distance_m=distance, measured="distance"))


def test_a_worked_out_tilt_is_sized_whatever_changed_it():
    """Ruling R12: with a measured distance a height change under 0.3 m that moves the tilt 5 degrees or more is
    "moved"; one that moves it less is "measured"."""
    small = review(distance_measured(2.0, 2.0), distance_measured(2.25, 2.0))
    assert distance_measured(2.0, 2.0).pitch_deg == 45.0 and distance_measured(2.25, 2.0).pitch_deg == 48.4
    assert small.ask is True and small.suggested == "measured"
    large = review(distance_measured(1.0, 1.0), distance_measured(1.25, 1.0))
    assert distance_measured(1.25, 1.0).pitch_deg == 51.3
    assert [(c.field, c.counts) for c in large.changes] == [("height_m", True)]
    assert large.suggested == "moved"


def test_switching_the_measured_one_and_changing_its_number_counts():
    old = m.checked(mounting(height_m=2.13, pitch_deg=62.0, measured="pitch"))  # distance 1.13
    new = m.checked(mounting(height_m=2.13, view_distance_m=2.0, measured="distance"))  # tilt 46.8
    result = review(old, new)
    assert [(c.field, c.counts) for c in result.changes] == [("view_distance_m", True)]
    assert result.ask is True and result.suggested == "moved"
    near = m.checked(mounting(height_m=2.13, view_distance_m=1.2, measured="distance"))  # tilt 60.6
    assert review(old, near).suggested == "measured"


def test_a_small_and_a_large_change_together_suggest_moved():
    result = review(mounting(heading_deg=40, height_m=2.13), mounting(heading_deg=41, height_m=3.0))
    assert result.suggested == "moved"


def test_moved_starts_deployments_only_where_a_change_counts():
    old = [mounting(heading_deg=40), mounting(RADAR, heading_deg=0)]
    new = [mounting(heading_deg=80), mounting(RADAR, heading_deg=0, height_m=3.0)]
    result = review(old, new, moved=True)
    assert result.new_deployments == [m.SensorKey(sensor_type="cameras", sensor_name="picam_h265")]
    assert changes(result) == [("picam_h265", "heading_deg", True), ("TM_RADAR_SERIAL_PORT_00", "height_m", False)]


@pytest.mark.parametrize("moved", [False, None])
def test_measured_starts_none(moved):
    result = review(mounting(heading_deg=40), mounting(heading_deg=80), moved=moved)
    assert result.new_deployments == []


def test_no_change_is_an_empty_review():
    same = mounting(heading_deg=40, height_m=2.13, pitch_deg=15.0, measured="pitch", view_distance_m=7.95, mount="pole")
    result = review(same, same.model_copy(), moved=True)
    assert (result.changes, result.ask, result.suggested, result.new_deployments) == ([], False, None, [])


def test_a_sensor_in_only_one_side_is_skipped():
    result = review([mounting(heading_deg=40)], [mounting(RADAR, heading_deg=90)], moved=True)
    assert (result.changes, result.ask, result.new_deployments) == ([], False, [])


def test_tilt_and_distance_are_listed_once():
    old = m.checked(mounting(height_m=2.13, pitch_deg=15.0, measured="pitch"))
    new = m.checked(mounting(height_m=2.13, pitch_deg=25.0, measured="pitch"))
    assert [c.field for c in review(old, new).changes] == ["pitch_deg"]
    old = m.checked(mounting(height_m=2.13, view_distance_m=7.95, measured="distance"))
    new = m.checked(mounting(height_m=2.13, view_distance_m=9.0, measured="distance"))
    assert [c.field for c in review(old, new).changes] == ["view_distance_m"]


def test_a_cleared_measured_names_the_olds():
    old = m.checked(mounting(height_m=2.13, view_distance_m=7.95, measured="distance"))
    result = review(old, mounting(height_m=2.13))
    assert [(c.field, c.counts) for c in result.changes] == [("view_distance_m", True)]
    # neither names one: the tilt
    result = review(mounting(pitch_deg=15.0), mounting(pitch_deg=20.0, view_distance_m=9.0))
    assert [c.field for c in result.changes] == ["pitch_deg"]


def test_choosing_the_other_as_measured_is_not_a_change():
    old = m.checked(mounting(height_m=2.13, pitch_deg=62.0, measured="pitch"))
    assert old.view_distance_m == 1.13
    new = m.checked(mounting(height_m=2.13, view_distance_m=1.13, measured="distance"))
    assert new.pitch_deg == 62.1
    result = review(old, new, {CAMERA: True})
    assert result.changes == [] and result.ask is False and result.suggested is None
