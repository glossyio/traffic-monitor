import ast
from pathlib import Path

import pytest

import tm_control
from tm_control.core.auth import Device
from tm_control.core.state import State
from tm_control.modules.location.mounting import Mounting
from tm_control.modules.location.places import Places, SensorHeading

HEADINGS = [SensorHeading(sensor_type="cameras", sensor_name="picam_h265", heading_deg=0),
            SensorHeading(sensor_type="radars", sensor_name="TM_RADAR_SERIAL_PORT_00", heading_deg=None)]


@pytest.fixture
def state(tmp_path):
    state = State(tmp_path / "state.sqlite")
    state.migrate()
    return state


@pytest.fixture
def places(state):
    return Places(state)


def _create(places, survey_id, status="planned", now=None, headings=(), lat=None, lon=None):
    return places.create(survey_id, "a note", lat, lon, list(headings), "ui", status, None, now=now)


def test_create_and_list_order(places):
    _create(places, "00000001-si", "planned", now=1000)
    _create(places, "00000002-si", "planned", now=2000)
    _create(places, "00000003-si", "in_use", now=500)
    _create(places, "00000004-si", "used", now=100)
    places.set_point("00000004-si", 45.0, -122.0, now=3000)  # most recently updated used place
    _create(places, "00000005-si", "used", now=200)
    ids = [s.id for s in places.list()]
    assert ids == ["00000003-si", "00000002-si", "00000001-si", "00000004-si", "00000005-si"]
    assert places.in_use().id == "00000003-si"
    assert places.get("00000002-si").status == "planned"
    assert places.get("ffffffff-si") is None


def test_located_lists_the_places_the_device_has_been_at_with_a_location(places):
    _create(places, "00000001-si", "in_use", now=500, lat=45.0, lon=-122.0)
    _create(places, "00000002-si", "used", now=100, lat=45.0, lon=-122.0)
    _create(places, "00000003-si", "used", now=200)
    _create(places, "00000004-si", "planned", now=300, lat=45.0, lon=-122.0)
    assert [s.id for s in places.located()] == ["00000001-si", "00000002-si"]


def test_only_one_place_is_in_use(places):
    _create(places, "00000001-si", "in_use", now=100)
    _create(places, "00000002-si", "planned", now=200)
    with pytest.raises(ValueError):
        _create(places, "00000003-si", "in_use", now=300)
    places.set_in_use("00000002-si", now=400)
    assert places.get("00000001-si").status == "used"
    assert places.get("00000002-si").status == "in_use"
    assert [s.status for s in places.list()].count("in_use") == 1


def test_set_in_use_refuses_an_unknown_place(places):
    _create(places, "00000001-si", "in_use", now=100)
    with pytest.raises(ValueError):
        places.set_in_use("ffffffff-si", now=200)
    assert places.in_use().id == "00000001-si"
    assert places.get("00000001-si").updated_at == places.get("00000001-si").created_at
    places.set_in_use("00000001-si", now=300)  # the place already in use: nothing changes
    assert places.in_use().id == "00000001-si"


def test_headings_round_trip(places, state):
    created = _create(places, "00000001-si", headings=HEADINGS)
    assert created.headings == HEADINGS
    assert places.get("00000001-si").headings == HEADINGS
    places.set_heading("00000001-si", "cameras", "picam_h265", 225)
    places.set_heading("00000001-si", "radars", "TM_RADAR_SERIAL_PORT_00", 0)
    got = places.get("00000001-si").headings
    assert [h.heading_deg for h in got] == [225, 0]
    assert [h.sensor_name for h in got] == ["picam_h265", "TM_RADAR_SERIAL_PORT_00"]
    places.set_heading("00000001-si", "cameras", "picam_h265", None)  # blank is NULL in the store
    places.set_heading("00000001-si", "airquality_monitors", "sensorname01", 90)  # a new sensor goes last
    assert [(h.sensor_name, h.heading_deg) for h in places.get("00000001-si").headings] == [
        ("picam_h265", None), ("TM_RADAR_SERIAL_PORT_00", 0), ("sensorname01", 90),
    ]
    stored = state.connect().execute("SELECT heading_deg FROM survey_sensors ORDER BY rowid").fetchall()
    assert [row["heading_deg"] for row in stored] == [None, 0, 90]


def test_location_round_trips_and_may_be_absent(places):
    _create(places, "00000001-si", lat=45.52252, lon=-122.6912)
    _create(places, "00000002-si")
    assert (places.get("00000001-si").lat, places.get("00000001-si").lon) == (45.52252, -122.6912)
    assert (places.get("00000002-si").lat, places.get("00000002-si").lon) == (None, None)


def test_update_planned(places):
    _create(places, "00000001-si", headings=HEADINGS)
    updated = places.update_planned("00000001-si", "new note", 45.0, -122.0, HEADINGS[:1])
    assert (updated.description, updated.lat, updated.lon) == ("new note", 45.0, -122.0)
    assert updated.headings == HEADINGS[:1]
    assert places.get("00000001-si") == updated


def test_update_planned_refuses_a_used_place(places):
    _create(places, "00000001-si", "used")
    _create(places, "00000002-si", "in_use")
    for survey_id in ("00000001-si", "00000002-si"):
        with pytest.raises(ValueError):
            places.update_planned(survey_id, "x", None, None, [])
    with pytest.raises(ValueError):
        places.update_planned("ffffffff-si", "x", None, None, [])


def test_set_point_changes_the_location_only(places):
    _create(places, "00000001-si", "in_use", now=100, headings=HEADINGS)
    places.set_point("00000001-si", 45.52252, -122.6912, now=200)
    survey = places.get("00000001-si")
    assert (survey.lat, survey.lon) == (45.52252, -122.6912)
    assert survey.headings == HEADINGS
    assert survey.updated_at > survey.created_at
    places.set_point("00000001-si", None, None)
    assert (places.get("00000001-si").lat, places.get("00000001-si").lon) == (None, None)


def test_delete_refuses_the_place_in_use(places):
    _create(places, "00000001-si", "in_use")
    with pytest.raises(ValueError):
        places.delete("00000001-si")
    assert places.get("00000001-si") is not None


def test_delete_removes_its_headings_and_corrections(places, state):
    _create(places, "00000001-si", "used", headings=HEADINGS)
    places.record_correction("00000001-si", "1-0123abcd-d", "heading_deg", "0", "180", None, "ui", None)
    places.delete("00000001-si")
    assert places.get("00000001-si") is None
    con = state.connect()
    assert con.execute("SELECT count(*) FROM survey_sensors").fetchone()[0] == 0
    assert con.execute("SELECT count(*) FROM survey_corrections").fetchone()[0] == 0


def test_correction_rows_keep_old_and_new_values(places, state):
    _create(places, "00000001-si", "in_use")
    places.record_correction(
        "00000001-si", "1-0123abcd-d", "location", "45.0,-122.0", "45.52252,-122.6912", None, "ui", None, now=1000
    )
    row = state.connect().execute("SELECT * FROM survey_corrections").fetchone()
    assert (row["survey_id"], row["deployment_id"], row["field"]) == ("00000001-si", "1-0123abcd-d", "location")
    assert (row["old_value"], row["new_value"], row["reason"]) == ("45.0,-122.0", "45.52252,-122.6912", None)
    assert (row["source"], row["user_id"], row["at"]) == ("ui", None, "1970-01-01T00:16:40+00:00")


def test_reconciled_flag_starts_unset(places, state):
    assert places.reconciled_at() is None
    places.mark_reconciled(now=1000)
    assert places.reconciled_at() == "1970-01-01T00:16:40+00:00"
    assert Device(state)  # the flag lives in the device table, beside the claim state
    row = state.connect().execute("SELECT value FROM device WHERE key = 'surveys_reconciled_at'").fetchone()
    assert row["value"] == "1970-01-01T00:16:40+00:00"


def test_create_can_set_updated_at_apart_from_created_at(places):
    """An imported place keeps its survey's first and last use as created_at and updated_at."""
    created = places.create("00000001-si", None, None, None, [], "imported_backup", "used", None,
                            now=1000, updated_now=2000)
    assert (created.created_at, created.updated_at) == ("1970-01-01T00:16:40+00:00", "1970-01-01T00:33:20+00:00")
    assert _create(places, "00000002-si", now=1000).updated_at == "1970-01-01T00:16:40+00:00"


def test_rename_sensor_moves_every_places_heading(places, state):
    radar = SensorHeading(sensor_type="radars", sensor_name="main_st", heading_deg=90)  # another type, the same name
    _create(places, "00000001-si", "used", now=100, headings=[*HEADINGS, radar])
    _create(places, "00000002-si", "in_use", now=200, headings=HEADINGS)
    taken = SensorHeading(sensor_type="cameras", sensor_name="camera_1_3fa9c2", heading_deg=270)
    _create(places, "00000003-si", "planned", now=300, headings=[taken, *HEADINGS])
    places.rename_sensor("cameras", "picam_h265", "camera_1_3fa9c2")
    renamed = SensorHeading(sensor_type="cameras", sensor_name="camera_1_3fa9c2", heading_deg=0)
    assert places.get("00000001-si").headings == [renamed, HEADINGS[1], radar]  # same order, other types untouched
    assert places.get("00000002-si").headings == [renamed, HEADINGS[1]]
    assert places.get("00000003-si").headings == [taken, HEADINGS[1]]  # already had the new name: that row stays
    places.rename_sensor("cameras", "oak_ave_wide", "camera_2_b07e11")  # nothing under the old name: nothing changes
    assert places.get("00000002-si").headings == [renamed, HEADINGS[1]]


def test_rename_sensor_to_the_same_name_changes_nothing(places):
    _create(places, "00000001-si", "used", now=100, headings=HEADINGS)
    places.rename_sensor("cameras", "picam_h265", "picam_h265")
    assert places.get("00000001-si").headings == HEADINGS


def _mounting(name="picam_h265", sensor_type="cameras", **values):
    return Mounting(sensor_type=sensor_type, sensor_name=name, **values)


POLE = {"heading_deg": 40, "pitch_deg": 15.0, "height_m": 3.66, "view_distance_m": 13.66, "measured": "pitch",
        "mount": "pole"}


def test_set_mounting_inserts_and_updates(places, state):
    _create(places, "00000001-si", "in_use", headings=HEADINGS)
    places.set_mounting("00000001-si", _mounting(**POLE))  # a sensor with a row: its heading and the five change
    places.set_mounting("00000001-si", _mounting("main_st", "radars", heading_deg=90, height_m=2.13))  # no row yet
    rows = state.connect().execute(
        "SELECT sensor_name, heading_deg, pitch_deg, height_m, view_distance_m, measured, mount "
        "FROM survey_sensors ORDER BY rowid"
    ).fetchall()
    assert [tuple(row) for row in rows] == [
        ("picam_h265", 40, 15.0, 3.66, 13.66, "pitch", "pole"),
        ("TM_RADAR_SERIAL_PORT_00", None, None, None, None, None, None),
        ("main_st", 90, None, 2.13, None, None, None),
    ]
    places.set_mounting("00000001-si", _mounting(heading_deg=41))  # a second save replaces what the first stored
    assert [tuple(row) for row in state.connect().execute(
        "SELECT heading_deg, pitch_deg, height_m, view_distance_m, measured, mount FROM survey_sensors "
        "WHERE sensor_name = 'picam_h265'"
    )] == [(41, None, None, None, None, None)]
    assert [(h.sensor_name, h.heading_deg) for h in places.get("00000001-si").headings] == [
        ("picam_h265", 41), ("TM_RADAR_SERIAL_PORT_00", None), ("main_st", 90),
    ]


def test_mountings_lists_a_places_rows(places):
    _create(places, "00000001-si", "in_use", headings=HEADINGS)
    _create(places, "00000002-si", "planned", headings=HEADINGS[:1])
    places.set_mounting("00000001-si", _mounting(**POLE))
    places.set_mounting("00000002-si", _mounting(heading_deg=200, mount="tripod"))
    assert places.mountings("00000001-si") == [
        _mounting(**POLE), _mounting("TM_RADAR_SERIAL_PORT_00", "radars"),
    ]
    assert places.mountings("00000002-si") == [_mounting(heading_deg=200, mount="tripod")]
    assert places.mountings("ffffffff-si") == []


def test_renaming_a_sensor_keeps_its_mounting(places):
    _create(places, "00000001-si", "used", headings=HEADINGS)
    places.set_mounting("00000001-si", _mounting(**POLE))
    places.rename_sensor("cameras", "picam_h265", "camera_1_3fa9c2")
    assert places.mountings("00000001-si")[0] == _mounting("camera_1_3fa9c2", **POLE)


def test_editing_a_planned_place_still_replaces_its_headings(places):
    """Its sensors' headings are replaced as before; a sensor that stays keeps what was stored beside its heading."""
    _create(places, "00000001-si", headings=HEADINGS)
    places.set_mounting("00000001-si", _mounting(**POLE))
    kept = [SensorHeading(sensor_type="cameras", sensor_name="picam_h265", heading_deg=250),
            SensorHeading(sensor_type="radars", sensor_name="main_st", heading_deg=10)]
    updated = places.update_planned("00000001-si", "new note", None, None, kept)
    assert updated.headings == kept
    assert places.mountings("00000001-si") == [
        _mounting(**{**POLE, "heading_deg": 250}), _mounting("main_st", "radars", heading_deg=10),
    ]


def _unconfirmed(places, survey_id):
    return [(m.sensor_type, m.sensor_name) for m in places.unconfirmed(survey_id)]


def test_putting_a_place_in_use_marks_its_mounting_unconfirmed(places):
    _create(places, "00000001-si", "in_use", headings=HEADINGS)
    places.set_mounting("00000001-si", _mounting(**POLE))
    _create(places, "00000002-si", "planned")
    places.set_in_use("00000002-si")
    assert _unconfirmed(places, "00000001-si") == []  # a place left behind isn't marked
    places.set_in_use("00000001-si")
    assert places.unconfirmed("00000001-si") == [_mounting(**POLE)]  # with the values it holds
    assert places.mountings("00000001-si")[0] == _mounting(**POLE)  # every row as stored


def test_a_row_with_only_a_heading_is_not_marked(places):
    _create(places, "00000001-si", "used", headings=HEADINGS)
    places.set_mounting("00000001-si", _mounting("main_st", "radars", heading_deg=90))
    places.set_in_use("00000001-si")
    assert _unconfirmed(places, "00000001-si") == []


def test_the_place_already_in_use_is_not_marked_again(places):
    _create(places, "00000001-si", "in_use", headings=HEADINGS)
    places.set_mounting("00000001-si", _mounting(**POLE))
    places.set_in_use("00000001-si")
    assert _unconfirmed(places, "00000001-si") == []


def test_saving_a_mounting_confirms_it(places):
    _create(places, "00000001-si", "used", headings=HEADINGS)
    places.set_mounting("00000001-si", _mounting(**POLE))
    places.set_mounting("00000001-si", _mounting("TM_RADAR_SERIAL_PORT_00", "radars", height_m=2.13))
    places.set_in_use("00000001-si")
    assert len(places.unconfirmed("00000001-si")) == 2
    places.set_heading("00000001-si", "cameras", "picam_h265", 200)  # a heading alone leaves the mark
    assert places.unconfirmed("00000001-si")[0] == _mounting(**{**POLE, "heading_deg": 200})
    places.set_mounting("00000001-si", _mounting(**{**POLE, "heading_deg": 200}))
    assert _unconfirmed(places, "00000001-si") == [("radars", "TM_RADAR_SERIAL_PORT_00")]


def test_editing_a_planned_place_keeps_the_mark_with_the_four(places, state):
    _create(places, "00000001-si", headings=HEADINGS)
    places.set_mounting("00000001-si", _mounting(**POLE))
    with state.connect() as con:  # a planned place never has a marked row today; the edit mustn't lose one
        con.execute("UPDATE survey_sensors SET unconfirmed = 1 WHERE sensor_name = 'picam_h265'")
    places.update_planned("00000001-si", "new note", None, None, HEADINGS)
    assert _unconfirmed(places, "00000001-si") == [("cameras", "picam_h265")]


def _annotations(function):
    arguments = function.args
    every = arguments.posonlyargs + arguments.args + arguments.kwonlyargs + [arguments.vararg, arguments.kwarg]
    return [item.annotation for item in every if item is not None and item.annotation] + (
        [function.returns] if function.returns else [])


# Python 3.13 evaluates an annotation when the `def` runs, in the class body, where a method named `list` has replaced
# the builtin: `-> list[X]` in a later method raises TypeError and the control app doesn't start. Python 3.14 evaluates
# lazily and doesn't show it, so the dev venv can't see it by running the code; this reads the source instead.
def _shadowed(tree, where=""):
    """`Class.method reads name` for each annotation that reads a name an earlier method of the same class defines."""
    found = []
    for cls in (node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)):
        defined = set()
        for item in cls.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for annotation in _annotations(item):
                    for name in ast.walk(annotation):
                        if isinstance(name, ast.Name) and name.id in defined:
                            found.append(f"{where}{cls.name}.{item.name} reads `{name.id}`")
                defined.add(item.name)
    return found


def test_the_scan_sees_a_shadowed_annotation():
    source = "class C:\n    def list(self) -> list[int]: ...\n    def other(self) -> list[int]: ...\n"
    assert _shadowed(ast.parse(source)) == ["C.other reads `list`"]


def test_no_method_annotation_reads_an_earlier_method_of_its_class():
    package = Path(tm_control.__file__).parent
    found = []
    for path in sorted(package.rglob("*.py")):
        found += _shadowed(ast.parse(path.read_text()), f"{path.relative_to(package)}: ")
    assert found == []
