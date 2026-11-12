import pytest

from tm_control.core.auth import Device
from tm_control.core.state import State
from tm_control.modules.location.places import Bearing, Places

BEARINGS = [Bearing(sensor_type="cameras", sensor_name="picam_h265", bearing="n"),
            Bearing(sensor_type="radars", sensor_name="TM_RADAR_SERIAL_PORT_00", bearing="")]


@pytest.fixture
def state(tmp_path):
    state = State(tmp_path / "state.sqlite")
    state.migrate()
    return state


@pytest.fixture
def places(state):
    return Places(state)


def _create(places, survey_id, status="planned", now=None, bearings=(), lat=None, lon=None):
    return places.create(survey_id, "a note", lat, lon, list(bearings), "ui", status, None, now=now)


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


def test_bearings_round_trip(places):
    created = _create(places, "00000001-si", bearings=BEARINGS)
    assert created.bearings == BEARINGS
    assert places.get("00000001-si").bearings == BEARINGS
    places.set_bearing("00000001-si", "cameras", "picam_h265", "sw")
    got = places.get("00000001-si").bearings
    assert [b.bearing for b in got] == ["sw", ""]
    assert [b.sensor_name for b in got] == ["picam_h265", "TM_RADAR_SERIAL_PORT_00"]


def test_location_round_trips_and_may_be_absent(places):
    _create(places, "00000001-si", lat=45.52252, lon=-122.6912)
    _create(places, "00000002-si")
    assert (places.get("00000001-si").lat, places.get("00000001-si").lon) == (45.52252, -122.6912)
    assert (places.get("00000002-si").lat, places.get("00000002-si").lon) == (None, None)


def test_update_planned(places):
    _create(places, "00000001-si", bearings=BEARINGS)
    updated = places.update_planned("00000001-si", "new note", 45.0, -122.0, BEARINGS[:1])
    assert (updated.description, updated.lat, updated.lon) == ("new note", 45.0, -122.0)
    assert updated.bearings == BEARINGS[:1]
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
    _create(places, "00000001-si", "in_use", now=100, bearings=BEARINGS)
    places.set_point("00000001-si", 45.52252, -122.6912, now=200)
    survey = places.get("00000001-si")
    assert (survey.lat, survey.lon) == (45.52252, -122.6912)
    assert survey.bearings == BEARINGS
    assert survey.updated_at > survey.created_at
    places.set_point("00000001-si", None, None)
    assert (places.get("00000001-si").lat, places.get("00000001-si").lon) == (None, None)


def test_delete_refuses_the_place_in_use(places):
    _create(places, "00000001-si", "in_use")
    with pytest.raises(ValueError):
        places.delete("00000001-si")
    assert places.get("00000001-si") is not None


def test_delete_removes_its_bearings_and_corrections(places, state):
    _create(places, "00000001-si", "used", bearings=BEARINGS)
    places.record_correction("00000001-si", "1-0123abcd-d", "bearing", "n", "s", None, "ui", None)
    places.delete("00000001-si")
    assert places.get("00000001-si") is None
    con = state.connect()
    assert con.execute("SELECT count(*) FROM survey_bearings").fetchone()[0] == 0
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


def test_rename_sensor_moves_every_places_bearing(places, state):
    radar = Bearing(sensor_type="radars", sensor_name="main_st", bearing="e")  # another type, the same name
    _create(places, "00000001-si", "used", now=100, bearings=[*BEARINGS, radar])
    _create(places, "00000002-si", "in_use", now=200, bearings=BEARINGS)
    taken = Bearing(sensor_type="cameras", sensor_name="camera_1_3fa9c2", bearing="w")
    _create(places, "00000003-si", "planned", now=300, bearings=[taken, *BEARINGS])
    places.rename_sensor("cameras", "picam_h265", "camera_1_3fa9c2")
    renamed = Bearing(sensor_type="cameras", sensor_name="camera_1_3fa9c2", bearing="n")
    assert places.get("00000001-si").bearings == [renamed, BEARINGS[1], radar]  # same order, other types untouched
    assert places.get("00000002-si").bearings == [renamed, BEARINGS[1]]
    assert places.get("00000003-si").bearings == [taken, BEARINGS[1]]  # already had the new name: that row stays
    places.rename_sensor("cameras", "oak_ave_wide", "camera_2_b07e11")  # nothing under the old name: nothing changes
    assert places.get("00000002-si").bearings == [renamed, BEARINGS[1]]


def test_rename_sensor_to_the_same_name_changes_nothing(places):
    _create(places, "00000001-si", "used", now=100, bearings=BEARINGS)
    places.rename_sensor("cameras", "picam_h265", "picam_h265")
    assert places.get("00000001-si").bearings == BEARINGS
