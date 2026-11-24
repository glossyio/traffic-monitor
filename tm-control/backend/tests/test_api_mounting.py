"""The Mounting form's API: GET and PUT /api/v1/surveys/{survey_id}/mounting.

claimed_client runs in fake mode (see test_api_surveys.py): a camera and its radar, facing 0 from the top-level block,
and fake.FakeNodeRed, whose open rows count as having recorded traffic once they are RECORDS_AFTER seconds old. The
`recorded` and `not_recorded` fixtures set that to 0 and to never.
"""

import logging
import math

import pytest

from tm_control.adapters.nodered import NodeRedError
from tm_control.core.auth import Users
from tm_control.fake import FakeNodeRed
from tm_control.modules.location import config as location_config
from tm_control.modules.location import reconcile
from tm_control.modules.location.places import Places

from test_api_surveys import (  # noqa: F401  (no_waiting and admin are fixtures)
    CAMERA,
    ORIGIN,
    RADAR,
    VIEWER,
    admin,
    audit_rows,
    backups,
    create,
    deploy,
    file_data,
    first_place,
    no_waiting,
    rows,
)

FIVE = ("heading_deg", "pitch_deg", "height_m", "view_distance_m", "mount")
POLE = {"heading_deg": 0, "pitch_deg": 15.0, "height_m": 3.66, "measured": "pitch", "mount": "pole"}
POLE_DISTANCE = 13.66  # 3.66 m / tan(15 degrees)
AIR = ("airquality_monitors", "sensorname01")  # in the fixture, but not enabled


@pytest.fixture
def recorded(monkeypatch):
    monkeypatch.setattr(FakeNodeRed, "RECORDS_AFTER", 0)


@pytest.fixture
def not_recorded(monkeypatch):
    monkeypatch.setattr(FakeNodeRed, "RECORDS_AFTER", math.inf)


def url(survey_id):
    return f"/api/v1/surveys/{survey_id}/mounting"


def item(sensor, **values):
    return {"sensor_type": sensor[0], "sensor_name": sensor[1], **values}


def mounting(client, survey_id) -> dict:
    r = client.get(url(survey_id))
    assert r.status_code == 200, r.text
    return r.json()


def put(client, survey_id, sensors, moved=None, dry_run=False):
    return client.put(
        url(survey_id), json={"sensors": sensors, "moved": moved, "dry_run": dry_run}, headers=ORIGIN
    )


def saved(client, survey_id, sensors, moved=None) -> dict:
    r = put(client, survey_id, sensors, moved)
    assert r.status_code == 200, r.text
    assert r.json()["saved"] is True
    return r.json()


def of(sensors: list[dict], sensor) -> dict:
    return next(s for s in sensors if (s["sensor_type"], s["sensor_name"]) == sensor)


def open_row(client, survey_id, sensor) -> dict:
    found = [
        row for row in rows(client, survey_id)
        if (row["sensor_type"], row["sensor_name"]) == sensor and row["ended"] is None
    ]
    assert len(found) == 1
    return found[0]


def block(client, sensor) -> dict:
    return file_data(client)["sensors"][sensor[0]][sensor[1]].get("deployment") or {}


def store(client, survey_id) -> dict:
    return {(m.sensor_type, m.sensor_name): m for m in Places(client.app.state.state).mountings(survey_id)}


def corrections(client):
    con = client.app.state.state.connect()
    try:
        found = con.execute(
            "SELECT survey_id, deployment_id, field, old_value, new_value, reason FROM survey_corrections"
        ).fetchall()
    finally:
        con.close()
    return [tuple(row) for row in found]


def snapshot(client, survey_id):
    """Everything a save could change: the file's bytes and backups, the store, Node-RED's rows, the audit log."""
    return (
        client.app.state.config_path.read_bytes(),
        backups(client),
        store(client, survey_id),
        rows(client, survey_id),
        audit_rows(client),
        corrections(client),
    )


def five(row: dict) -> list:
    return [row[key] for key in FIVE]


def fill_camera(client, survey_id) -> dict:
    """A first fill of the camera's mounting (no change counts, so nothing is asked)."""
    return saved(client, survey_id, [item(CAMERA, **POLE)])


# Reading


def test_mounting_needs_an_admin(claimed_client, login):
    in_use = Places(claimed_client.app.state.state).in_use()
    survey_id = in_use.id if in_use else "00000000-si"
    assert claimed_client.get(url(survey_id)).status_code == 401
    Users(claimed_client.app.state.state).create(*VIEWER, "viewer")
    login(claimed_client, *VIEWER)
    assert claimed_client.get(url(survey_id)).status_code == 403
    assert put(claimed_client, survey_id, [item(CAMERA, **POLE)]).status_code == 403


def test_mounting_of_a_place_not_in_use_is_refused(admin):
    first_place(admin)
    planned = create(admin)
    for r in (admin.get(url(planned["id"])), put(admin, planned["id"], [item(CAMERA, **POLE)], dry_run=True)):
        assert r.status_code == 409 and r.json()["error"]["code"] == "not_in_use"
    for r in (admin.get(url("00000000-si")), put(admin, "00000000-si", [])):
        assert r.status_code == 404
    assert admin.get(url("not-an-id")).status_code == 404


def test_a_new_units_mounting_is_empty(admin):
    in_use = first_place(admin)
    state = mounting(admin, in_use)
    assert state["nodered"] is True
    assert [(m["key"], m["height_m"], m["pitch_deg"]) for m in state["mounts"]] == [
        ("tripod", 2.13, 15.0), ("pole", 3.66, 15.0), ("window", 4.88, 15.0),
    ]
    camera, radar = state["sensors"]  # the enabled ones: the camera, then its radar
    for found, sensor in ((camera, CAMERA), (radar, RADAR)):
        assert (found["sensor_type"], found["sensor_name"]) == sensor
        assert five(found) == [0, None, None, None, None]  # the top-level heading, copied down
        assert found["measured"] is None
        assert found["deployment_id"] == open_row(admin, in_use, sensor)["id"]
        assert found["recorded"] is False  # opened just now
    assert camera["camera"] is None and camera["same_as_camera"] is False
    assert radar["camera"] == "picam_h265" and radar["same_as_camera"] is True


def test_mounting_lists_cameras_with_their_radars_then_the_rest(admin):
    in_use = first_place(admin)
    path = admin.app.state.config_path
    text = path.read_text()
    text = text.replace(
        "    radars:\n",
        "        second:\n            enabled: true\n            camera_radar: TM_RADAR_SERIAL_PORT_01\n\n"
        "    radars:\n        TM_RADAR_SERIAL_PORT_02:\n            enabled: true\n"
        "        TM_RADAR_SERIAL_PORT_01:\n            enabled: true\n",
    ).replace("sensorname01:\n            enabled: false", "sensorname01:\n            enabled: true")
    path.write_text(text)
    names = [(s["sensor_name"], s["camera"]) for s in mounting(admin, in_use)["sensors"]]
    assert names == [
        ("picam_h265", None), ("TM_RADAR_SERIAL_PORT_00", "picam_h265"),
        ("second", None), ("TM_RADAR_SERIAL_PORT_01", "second"),
        ("TM_RADAR_SERIAL_PORT_02", None), ("sensorname01", None),
    ]


def test_mounting_reads_a_hand_edit(admin):
    in_use = first_place(admin)
    path = admin.app.state.config_path
    camera = "            camera_radar: TM_RADAR_SERIAL_PORT_00\n"
    radar = "            enabled: true\n            opt_api_commands_array"
    path.write_text(
        path.read_text()
        .replace(camera, camera + "            deployment:\n                heading_deg: 90\n"
                 "                pitch_deg: 15\n                height_m: 3.66\n"
                 "                view_distance_m: 13.66\n                mount: pole\n")
        .replace(radar, "            enabled: true\n            deployment:\n                height_m: 4\n"
                 "                view_distance_m: 20\n            opt_api_commands_array")
    )
    camera_found, radar_found = mounting(admin, in_use)["sensors"]
    assert five(camera_found) == [90, 15.0, 3.66, 13.66, "pole"]
    assert camera_found["measured"] == "pitch"  # the store has no say: the file has a tilt
    assert five(radar_found) == [0, None, 4.0, 20.0, None]
    assert radar_found["measured"] == "distance"  # no tilt, a distance
    assert radar_found["same_as_camera"] is False
    # the hand edit started new deployments, which the answer names
    assert camera_found["deployment_id"] == open_row(admin, in_use, CAMERA)["id"]


def test_a_hand_typed_mount_can_be_sent_back(admin, recorded):
    """A mount key typed into config.yml that isn't one of the usual three passes as it is; any other is refused."""
    in_use = first_place(admin)
    path = admin.app.state.config_path
    camera = "            camera_radar: TM_RADAR_SERIAL_PORT_00\n"
    path.write_text(path.read_text().replace(
        camera, camera + "            deployment:\n                heading_deg: 0\n                mount: roof_rack\n"))
    found = of(mounting(admin, in_use)["sensors"], CAMERA)
    assert found["mount"] == "roof_rack"
    keys = ("sensor_type", "sensor_name", *FIVE, "measured", "same_as_camera")
    sent = [{key: s[key] for key in keys} for s in mounting(admin, in_use)["sensors"]]
    before = snapshot(admin, in_use)
    r = put(admin, in_use, sent, dry_run=True)
    assert r.status_code == 200, r.text
    assert r.json()["changes"] == [] and of(r.json()["sensors"], CAMERA)["mount"] == "roof_rack"
    assert snapshot(admin, in_use) == before
    r = put(admin, in_use, [item(CAMERA, heading_deg=0, mount="van_roof")], dry_run=True)
    assert r.status_code == 422 and r.json()["error"]["detail"]["field"] == "mount"
    saved(admin, in_use, [item(CAMERA, heading_deg=0, mount=None)])
    assert "mount" not in block(admin, CAMERA)
    r = put(admin, in_use, [item(CAMERA, heading_deg=0, mount="roof_rack")], dry_run=True)
    assert r.status_code == 422  # the file no longer holds it


def test_a_radar_can_send_back_the_hand_typed_mount_of_its_camera(admin, recorded):
    """same_as_camera gives the radar the camera's hand-typed key; unticking the box sends those values as the radar's
    own, which must pass as they did, though the file holds no key for the radar yet."""
    in_use = first_place(admin)
    path = admin.app.state.config_path
    camera = "            camera_radar: TM_RADAR_SERIAL_PORT_00\n"
    path.write_text(path.read_text().replace(
        camera, camera + "            deployment:\n                heading_deg: 0\n                mount: roof_rack\n"))
    r = put(admin, in_use, [item(RADAR, same_as_camera=True)], dry_run=True)
    assert r.status_code == 200, r.text
    assert of(r.json()["sensors"], RADAR)["mount"] == "roof_rack"
    r = put(admin, in_use, [item(RADAR, heading_deg=0, mount="roof_rack")], dry_run=True)
    assert r.status_code == 200, r.text
    assert of(r.json()["sensors"], RADAR)["mount"] == "roof_rack"
    r = put(admin, in_use, [item(RADAR, heading_deg=0, mount="van_roof")], dry_run=True)
    assert r.status_code == 422 and r.json()["error"]["detail"]["field"] == "mount"


def test_mounting_without_nodered_still_lists(admin, monkeypatch):
    in_use = first_place(admin)

    def unreachable(*args):
        raise NodeRedError("unreachable")

    monkeypatch.setattr(admin.app.state.nodered, "deployments", unreachable)
    monkeypatch.setattr(admin.app.state.nodered, "recorded", unreachable)
    state = mounting(admin, in_use)
    assert state["nodered"] is False
    assert [(s["sensor_name"], s["deployment_id"], s["recorded"]) for s in state["sensors"]] == [
        ("picam_h265", None, None), ("TM_RADAR_SERIAL_PORT_00", None, None),
    ]


# Dry run


def test_a_dry_run_writes_nothing(admin, recorded):
    in_use = first_place(admin)
    before = snapshot(admin, in_use)
    r = put(admin, in_use, [item(CAMERA, **POLE)], dry_run=True)
    assert r.status_code == 200, r.text
    answer = r.json()
    assert answer["saved"] is False and answer["reloaded"] is None
    assert five(of(answer["sensors"], CAMERA)) == [0, 15.0, 3.66, POLE_DISTANCE, "pole"]
    assert {(c["field"], c["counts"]) for c in answer["changes"]} == {
        ("pitch_deg", False), ("height_m", False), ("mount", False),
    }
    assert answer["ask"] is False and answer["new_deployments"] == []
    assert snapshot(admin, in_use) == before
    # a change that counts is answered too, and still nothing is written
    fill_camera(admin, in_use)
    before = snapshot(admin, in_use)
    r = put(admin, in_use, [item(CAMERA, **{**POLE, "heading_deg": 90})], dry_run=True)
    assert r.status_code == 200, r.text
    assert r.json()["ask"] is True and r.json()["suggested"] == "moved"
    assert snapshot(admin, in_use) == before


def test_a_dry_run_works_out_the_distance(admin):
    in_use = first_place(admin)
    sent = {**POLE, "view_distance_m": 999.0}  # the greyed one: whatever was sent for it is worked out
    r = put(admin, in_use, [item(CAMERA, **sent)], dry_run=True)
    assert r.status_code == 200, r.text
    assert of(r.json()["sensors"], CAMERA)["view_distance_m"] == POLE_DISTANCE
    by_distance = {"height_m": 3.66, "view_distance_m": 13.72, "measured": "distance"}
    r = put(admin, in_use, [item(CAMERA, **by_distance)], dry_run=True)
    assert r.status_code == 200, r.text
    found = of(r.json()["sensors"], CAMERA)
    assert (found["pitch_deg"], found["view_distance_m"], found["measured"]) == (14.9, 13.72, "distance")


@pytest.mark.parametrize("values, field", [
    ({"pitch_deg": 91.0, "measured": "pitch"}, "pitch_deg"),
    ({"pitch_deg": "40", "measured": "pitch"}, "pitch_deg"),
    ({"heading_deg": True}, "heading_deg"),
    ({"heading_deg": 360}, "heading_deg"),
    ({"height_m": 100.5}, "height_m"),
    ({"view_distance_m": 1200.0, "measured": "distance"}, "view_distance_m"),
    ({"mount": "ladder"}, "mount"),
    ({"pitch_deg": 15.0}, "pitch_deg"),  # a tilt with no measured one
    ({"measured": "tilt"}, "measured"),
    ({"same_as_camera": "yes"}, "same_as_camera"),
])
def test_a_dry_run_names_the_field_it_refuses(admin, values, field):
    in_use = first_place(admin)
    before = snapshot(admin, in_use)
    for dry_run in (True, False):
        r = put(admin, in_use, [item(CAMERA, **values)], dry_run=dry_run)
        assert r.status_code == 422, r.text
        error = r.json()["error"]
        assert error["code"] == "validation"
        assert error["detail"] == {"field": field, "index": 0}
        assert str(values[field]) not in error["message"]  # no value in the answer
    assert snapshot(admin, in_use) == before


def test_a_refused_body_names_its_field(admin):
    in_use = first_place(admin)
    for body, field in (({"sensors": "x"}, "sensors"), ({"sensors": [], "moved": "maybe"}, "moved"), ({}, "sensors")):
        r = admin.put(url(in_use), json=body, headers=ORIGIN)
        assert r.status_code == 422, r.text
        assert r.json()["error"]["code"] == "validation"
        assert r.json()["error"]["detail"] == {"field": field}
    r = admin.put(url(in_use), json={"sensors": [item(CAMERA)] * 33}, headers=ORIGIN)
    assert r.status_code == 422 and r.json()["error"]["detail"] == {"field": "sensors"}


# First fill


def test_a_first_fill_corrects_the_open_row(admin, recorded):
    in_use = first_place(admin)
    before = {row["id"] for row in rows(admin, in_use)}
    answer = fill_camera(admin, in_use)
    assert answer["ask"] is False and answer["suggested"] is None and answer["new_deployments"] == []
    assert answer["reloaded"] is None
    assert {row["id"] for row in rows(admin, in_use)} == before  # corrected in place, no new deployment
    row = open_row(admin, in_use, CAMERA)
    assert five(row) == [0, 15.0, 3.66, POLE_DISTANCE, "pole"]
    assert of(answer["sensors"], CAMERA)["deployment_id"] == row["id"]
    found = block(admin, CAMERA)
    assert [found.get(key) for key in FIVE] == [0, 15.0, 3.66, POLE_DISTANCE, "pole"]
    kept = store(admin, in_use)[CAMERA]
    assert [getattr(kept, key) for key in FIVE] == [0, 15.0, 3.66, POLE_DISTANCE, "pole"]
    assert kept.measured == "pitch"
    assert ("survey.mounting", in_use) in audit_rows(admin)
    assert corrections(admin) == []  # the heading didn't change
    detail = next(detail for action, detail in audit_rows(admin) if action == "survey.correct_mounting")
    assert detail.startswith(f"{in_use} {row['id']} ")
    assert "pitch_deg none>15.0" in detail and "height_m none>3.66" in detail and "mount none>pole" in detail
    # GET reads it back, measured included
    camera = of(mounting(admin, in_use)["sensors"], CAMERA)
    assert five(camera) == [0, 15.0, 3.66, POLE_DISTANCE, "pole"] and camera["measured"] == "pitch"


# The question


def test_a_change_with_traffic_needs_the_answer(admin, recorded):
    in_use = first_place(admin)
    fill_camera(admin, in_use)
    before = snapshot(admin, in_use)
    r = put(admin, in_use, [item(CAMERA, **{**POLE, "height_m": 4.0})])
    assert r.status_code == 409 and r.json()["error"]["code"] == "answer_needed"
    assert snapshot(admin, in_use) == before
    r = put(admin, in_use, [item(CAMERA, **{**POLE, "height_m": 4.0})], dry_run=True)
    assert r.json()["ask"] is True and r.json()["suggested"] == "moved"  # 0.34 m


def test_an_unknown_recorded_asks(admin, not_recorded, monkeypatch):
    in_use = first_place(admin)
    fill_camera(admin, in_use)

    def unreachable(*args):
        raise NodeRedError("unreachable")

    monkeypatch.setattr(admin.app.state.nodered, "recorded", unreachable)
    sent = [item(CAMERA, **{**POLE, "height_m": 3.7})]
    r = put(admin, in_use, sent, dry_run=True)
    assert r.status_code == 200, r.text
    assert r.json()["ask"] is True and r.json()["suggested"] == "measured"
    assert of(r.json()["sensors"], CAMERA)["recorded"] is None
    r = put(admin, in_use, sent)
    assert r.status_code == 409 and r.json()["error"]["code"] == "answer_needed"


def test_a_change_without_traffic_is_corrected_in_place(admin, not_recorded):
    in_use = first_place(admin)
    fill_camera(admin, in_use)
    before = {row["id"] for row in rows(admin, in_use)}
    answer = saved(admin, in_use, [item(CAMERA, **{**POLE, "heading_deg": 180, "height_m": 5.0})])
    assert answer["ask"] is False and answer["new_deployments"] == []
    assert {row["id"] for row in rows(admin, in_use)} == before
    assert five(open_row(admin, in_use, CAMERA))[:3] == [180, 15.0, 5.0]
    assert block(admin, CAMERA)["heading_deg"] == 180
    assert corrections(admin) == [(in_use, open_row(admin, in_use, CAMERA)["id"], "heading_deg", "0", "180", None)]


def test_moved_starts_a_new_deployment(admin, recorded):
    in_use = first_place(admin)
    fill_camera(admin, in_use)
    old_camera, old_radar = open_row(admin, in_use, CAMERA), open_row(admin, in_use, RADAR)
    changed = {**POLE, "heading_deg": 90, "height_m": 4.88}
    answer = saved(admin, in_use, [item(CAMERA, **changed)], moved=True)
    assert answer["new_deployments"] == [{"sensor_type": "cameras", "sensor_name": "picam_h265"}]
    assert answer["reloaded"] is True
    closed = next(row for row in rows(admin, in_use) if row["id"] == old_camera["id"])
    assert closed["ended"] is not None and five(closed) == five(old_camera)  # closed with its old values
    new = open_row(admin, in_use, CAMERA)
    assert new["id"] != old_camera["id"] and new["started"] >= closed["started"]
    assert five(new) == [90, 15.0, 4.88, 18.21, "pole"]
    assert of(answer["sensors"], CAMERA)["deployment_id"] == new["id"]
    assert of(answer["sensors"], CAMERA)["recorded"] is False  # started by this save, so nothing yet
    assert open_row(admin, in_use, RADAR)["id"] == old_radar["id"]  # the radar had no change
    assert corrections(admin) == []  # nothing was corrected in place
    assert [action for action, _ in audit_rows(admin)].count("survey.correct_mounting") == 1  # the fill's


def test_measured_corrects_in_place_and_records_it(admin, recorded):
    in_use = first_place(admin)
    fill_camera(admin, in_use)
    row = open_row(admin, in_use, CAMERA)
    changed = {**POLE, "heading_deg": 10, "height_m": 3.7}
    r = put(admin, in_use, [item(CAMERA, **changed)], dry_run=True)
    assert r.json()["ask"] is True and r.json()["suggested"] == "measured"
    answer = saved(admin, in_use, [item(CAMERA, **changed)], moved=False)
    assert answer["new_deployments"] == []
    after = open_row(admin, in_use, CAMERA)
    assert after["id"] == row["id"]
    assert five(after) == [10, 15.0, 3.7, 13.81, "pole"]
    assert (in_use, row["id"], "heading_deg", "0", "10", None) in corrections(admin)
    details = [detail for action, detail in audit_rows(admin) if action == "survey.correct_mounting"]
    assert details[-1] == f"{in_use} {row['id']} height_m 3.66>3.7 view_distance_m 13.66>13.81"
    assert audit_rows(admin).count(("survey.mounting", in_use)) == 2


def test_moved_corrects_the_sensors_whose_change_does_not_count(admin, recorded):
    in_use = first_place(admin)
    fill_camera(admin, in_use)
    camera, radar = open_row(admin, in_use, CAMERA), open_row(admin, in_use, RADAR)
    sent = [
        item(CAMERA, **{**POLE, "heading_deg": 90}),
        item(RADAR, heading_deg=0, height_m=2.13, pitch_deg=15.0, measured="pitch", mount="tripod"),
    ]
    answer = saved(admin, in_use, sent, moved=True)
    assert answer["new_deployments"] == [{"sensor_type": "cameras", "sensor_name": "picam_h265"}]
    assert open_row(admin, in_use, CAMERA)["id"] != camera["id"]
    radar_after = open_row(admin, in_use, RADAR)
    assert radar_after["id"] == radar["id"]  # a first fill: corrected in place
    assert five(radar_after) == [0, 15.0, 2.13, 7.95, "tripod"]


# Which sensors


def test_same_as_camera_copies_the_cameras_values(admin, not_recorded):
    in_use = first_place(admin)
    answer = saved(admin, in_use, [item(CAMERA, **POLE), item(RADAR, same_as_camera=True, height_m=1.0)])
    radar = of(answer["sensors"], RADAR)
    assert five(radar) == [0, 15.0, 3.66, POLE_DISTANCE, "pole"] and radar["measured"] == "pitch"
    assert radar["same_as_camera"] is True
    assert of(mounting(admin, in_use)["sensors"], RADAR)["same_as_camera"] is True
    # the radar alone takes the camera's values as they are now
    saved(admin, in_use, [item(RADAR, height_m=1.0)])
    assert of(mounting(admin, in_use)["sensors"], RADAR)["same_as_camera"] is False
    saved(admin, in_use, [item(RADAR, same_as_camera=True)])
    radar = of(mounting(admin, in_use)["sensors"], RADAR)
    assert five(radar) == [0, 15.0, 3.66, POLE_DISTANCE, "pole"] and radar["measured"] == "pitch"
    assert [block(admin, RADAR).get(key) for key in FIVE] == [0, 15.0, 3.66, POLE_DISTANCE, "pole"]


def test_same_as_camera_needs_a_camera(admin):
    in_use = first_place(admin)
    r = put(admin, in_use, [item(CAMERA, same_as_camera=True)], dry_run=True)
    assert r.status_code == 422 and r.json()["error"]["detail"] == {"field": "same_as_camera", "index": 0}
    path = admin.app.state.config_path
    path.write_text(path.read_text().replace("            camera_radar: TM_RADAR_SERIAL_PORT_00\n", ""))
    assert of(mounting(admin, in_use)["sensors"], RADAR)["camera"] is None
    r = put(admin, in_use, [item(CAMERA, **POLE), item(RADAR, same_as_camera=True)], dry_run=True)
    assert r.status_code == 422 and r.json()["error"]["detail"] == {"field": "same_as_camera", "index": 1}


def test_a_sensor_left_out_keeps_its_values(admin, not_recorded):
    in_use = first_place(admin)
    radar_values = {"heading_deg": 0, "height_m": 2.13, "pitch_deg": 15.0, "measured": "pitch", "mount": "tripod"}
    saved(admin, in_use, [item(CAMERA, **POLE), item(RADAR, **radar_values)])
    answer = saved(admin, in_use, [item(CAMERA, **{**POLE, "height_m": 4.0})])
    assert five(of(answer["sensors"], RADAR)) == [0, 15.0, 2.13, 7.95, "tripod"]
    assert [block(admin, RADAR).get(key) for key in FIVE] == [0, 15.0, 2.13, 7.95, "tripod"]
    assert store(admin, in_use)[RADAR].measured == "pitch"


def forget(client, survey_id, sensor) -> None:
    """Remove a sensor's store row, as a place the upgrade import put in use has it."""
    con = client.app.state.state.connect()
    try:
        con.execute(
            "DELETE FROM survey_sensors WHERE survey_id = ? AND sensor_type = ? AND sensor_name = ?",
            (survey_id, *sensor),
        )
        con.commit()
    finally:
        con.close()


def test_a_sensor_left_out_is_not_written(admin, not_recorded):
    in_use = first_place(admin)
    forget(admin, in_use, RADAR)
    assert RADAR not in store(admin, in_use) and block(admin, RADAR) == {}
    radar_row = open_row(admin, in_use, RADAR)
    answer = saved(admin, in_use, [item(CAMERA, **POLE)])
    assert five(of(answer["sensors"], RADAR)) == [0, None, None, None, None]  # still read from the top level
    assert block(admin, RADAR) == {}
    assert RADAR not in store(admin, in_use)
    assert open_row(admin, in_use, RADAR) == radar_row
    assert five(open_row(admin, in_use, CAMERA)) == [0, 15.0, 3.66, POLE_DISTANCE, "pole"]


def test_a_save_that_changes_no_sensor_it_names_writes_nothing(admin, recorded):
    in_use = first_place(admin)
    fill_camera(admin, in_use)
    forget(admin, in_use, RADAR)
    before = snapshot(admin, in_use)
    answer = saved(admin, in_use, [item(CAMERA, **POLE)])
    assert answer["changes"] == []
    assert snapshot(admin, in_use) == before


def test_a_sensor_left_out_keeps_the_store_row_it_has(admin, not_recorded):
    in_use = first_place(admin)
    path = admin.app.state.config_path
    marker = "            opt_api_commands_array"
    assert marker in path.read_text()
    path.write_text(
        path.read_text().replace(marker, "            deployment:\n                heading_deg: 90\n" + marker, 1)
    )
    assert of(mounting(admin, in_use)["sensors"], RADAR)["heading_deg"] == 90  # a hand edit, which the store never saw
    assert store(admin, in_use)[RADAR].heading_deg == 0
    saved(admin, in_use, [item(CAMERA, **POLE)])
    assert store(admin, in_use)[RADAR].heading_deg == 0
    assert block(admin, RADAR) == {"heading_deg": 90}


def test_a_named_sensor_with_no_store_row_gets_one(admin, not_recorded):
    """What the form's Save does for a radar it sends unticked and unchanged."""
    in_use = first_place(admin)
    forget(admin, in_use, RADAR)
    radar_row = open_row(admin, in_use, RADAR)
    saved(admin, in_use, [item(CAMERA, **POLE), item(RADAR, heading_deg=0)])
    assert block(admin, RADAR).get("heading_deg") == 0
    assert store(admin, in_use)[RADAR].heading_deg == 0
    assert open_row(admin, in_use, RADAR)["id"] == radar_row["id"]


POLE_PREVIOUS = {"pitch_deg": 15.0, "height_m": 3.66, "view_distance_m": POLE_DISTANCE, "measured": "pitch",
                 "mount": "pole"}


def returned(client) -> str:
    """The first place with the camera's pole values saved, a deploy to a second place, and one back: the camera's
    values wait to be confirmed."""
    first = first_place(client)
    fill_camera(client, first)
    deploy(client, create(client)["id"])
    deploy(client, first)
    assert of(mounting(client, first)["sensors"], CAMERA)["previous"] == POLE_PREVIOUS
    return first


def as_given(found: dict) -> dict:
    """A sensor as GET gave it, sent back: the five and measured."""
    return {key: found[key] for key in ("sensor_type", "sensor_name", *FIVE, "measured")}


def test_saving_the_previous_values_records_them_and_asks_nothing(admin, recorded):
    in_use = returned(admin)
    row = open_row(admin, in_use, CAMERA)
    previous = of(mounting(admin, in_use)["sensors"], CAMERA)["previous"]
    sent = item(CAMERA, heading_deg=0, **{k: v for k, v in previous.items() if k != "view_distance_m"})
    check = put(admin, in_use, [sent], dry_run=True).json()
    assert check["ask"] is False and of(check["sensors"], CAMERA)["previous"] == POLE_PREVIOUS  # nothing written yet
    answer = saved(admin, in_use, [sent])
    assert answer["ask"] is False
    assert of(answer["sensors"], CAMERA)["previous"] is None
    after = open_row(admin, in_use, CAMERA)
    assert after["id"] == row["id"] and five(after) == [0, 15.0, 3.66, POLE_DISTANCE, "pole"]
    assert [block(admin, CAMERA).get(key) for key in FIVE] == [0, 15.0, 3.66, POLE_DISTANCE, "pole"]
    found = of(mounting(admin, in_use)["sensors"], CAMERA)
    assert five(found) == [0, 15.0, 3.66, POLE_DISTANCE, "pole"] and found["measured"] == "pitch"
    assert found["previous"] is None


def test_a_sensor_sent_empty_keeps_its_previous_values(admin, recorded):
    in_use = returned(admin)
    before = snapshot(admin, in_use)
    answer = saved(admin, in_use, [as_given(found) for found in mounting(admin, in_use)["sensors"]])
    assert answer["changes"] == []
    assert snapshot(admin, in_use) == before
    assert of(answer["sensors"], CAMERA)["previous"] == POLE_PREVIOUS
    assert of(mounting(admin, in_use)["sensors"], CAMERA)["previous"] == POLE_PREVIOUS


def test_saving_other_values_drops_the_previous_ones(admin, recorded):
    in_use = returned(admin)
    tripod = {"heading_deg": 0, "pitch_deg": 15.0, "height_m": 2.13, "measured": "pitch", "mount": "tripod"}
    answer = saved(admin, in_use, [item(CAMERA, **tripod)])
    assert answer["ask"] is False  # empty values filled in
    found = of(mounting(admin, in_use)["sensors"], CAMERA)
    assert five(found) == [0, 15.0, 2.13, 7.95, "tripod"] and found["previous"] is None
    assert store(admin, in_use)[CAMERA].height_m == 2.13


def test_correct_heading_keeps_the_previous_values(admin, recorded):
    in_use = returned(admin)
    row = open_row(admin, in_use, CAMERA)
    r = admin.post(
        f"/api/v1/surveys/{in_use}/deployments/{row['id']}/heading", json={"heading_deg": 90}, headers=ORIGIN
    )
    assert r.status_code == 200, r.text
    found = of(mounting(admin, in_use)["sensors"], CAMERA)
    assert five(found) == [90, None, None, None, None] and found["previous"] == POLE_PREVIOUS
    assert store(admin, in_use)[CAMERA].height_m == 3.66
    assert [block(admin, CAMERA).get(key) for key in FIVE] == [90, None, None, None, None]


def test_a_sensor_that_is_not_enabled_is_refused(admin):
    in_use = first_place(admin)
    for sent, index in (
        ([item(AIR, heading_deg=90)], 0),
        ([item(("cameras", "nowhere"), heading_deg=90)], 0),
        ([item(("gauges", "picam_h265"), heading_deg=90)], 0),
        ([item(CAMERA, heading_deg=90), item(CAMERA, heading_deg=10)], 1),  # named twice
    ):
        r = put(admin, in_use, sent, dry_run=True)
        assert r.status_code == 422, r.text
        assert r.json()["error"]["code"] == "validation"
        assert r.json()["error"]["detail"] == {"field": "sensor_name", "index": index}


def test_an_air_quality_monitor_has_a_heading_only(admin):
    in_use = first_place(admin)
    path = admin.app.state.config_path
    path.write_text(path.read_text().replace("sensorname01:\n            enabled: false",
                                             "sensorname01:\n            enabled: true"))
    r = put(admin, in_use, [item(AIR, heading_deg=90, height_m=2.0)], dry_run=True)
    assert r.status_code == 422 and r.json()["error"]["detail"] == {"field": "height_m", "index": 0}
    answer = saved(admin, in_use, [item(AIR, heading_deg=90)], moved=False)  # Node-RED can't say if it recorded
    assert five(of(answer["sensors"], AIR)) == [90, None, None, None, None]
    assert block(admin, AIR)["heading_deg"] == 90


# Failure


def test_a_save_without_nodered_changes_nothing(admin, monkeypatch):
    in_use = first_place(admin)
    before = snapshot(admin, in_use)

    def unreachable(*args):
        raise NodeRedError("unreachable")

    monkeypatch.setattr(admin.app.state.nodered, "deployments", unreachable)
    r = put(admin, in_use, [item(CAMERA, **POLE)])
    assert r.status_code == 502 and r.json()["error"]["code"] == "nodered_error"
    monkeypatch.undo()
    assert snapshot(admin, in_use) == before


def test_a_failed_correction_puts_the_corrected_rows_back(admin, not_recorded, monkeypatch):
    in_use = first_place(admin)
    before = snapshot(admin, in_use)
    nodered = admin.app.state.nodered
    real = nodered.correct_mounting
    sent = []

    def second_fails(deployment_id, values):
        sent.append(deployment_id)
        if len(sent) == 2:
            raise NodeRedError("database_error", 500)
        real(deployment_id, values)

    monkeypatch.setattr(nodered, "correct_mounting", second_fails)
    radar_values = {"heading_deg": 0, "height_m": 2.13, "pitch_deg": 15.0, "measured": "pitch"}
    r = put(admin, in_use, [item(CAMERA, **POLE), item(RADAR, **radar_values)])
    monkeypatch.undo()
    assert r.status_code == 502
    assert sent[2:] == sent[:2]  # both put back: the camera's, and the radar's, whose call failed
    assert snapshot(admin, in_use) == before


def test_a_correction_that_fails_after_node_red_applied_it_is_put_back(admin, not_recorded, monkeypatch, caplog):
    """A timeout can come after Node-RED changed the row, so the row whose call failed is put back too."""
    in_use = first_place(admin)
    before = snapshot(admin, in_use)
    radar = open_row(admin, in_use, RADAR)
    nodered = admin.app.state.nodered
    real = nodered.correct_mounting
    sent = []

    def applied_then_timed_out(deployment_id, values):
        sent.append(deployment_id)
        real(deployment_id, values)
        if deployment_id == radar["id"] and len(sent) == 2:
            raise NodeRedError("unreachable")

    monkeypatch.setattr(nodered, "correct_mounting", applied_then_timed_out)
    radar_values = {"heading_deg": 0, "height_m": 2.13, "pitch_deg": 15.0, "measured": "pitch"}
    with caplog.at_level(logging.WARNING):
        r = put(admin, in_use, [item(CAMERA, **POLE), item(RADAR, **radar_values)])
    monkeypatch.undo()
    assert r.status_code == 502
    assert radar["id"] in sent[2:]  # its own put-back
    assert five(open_row(admin, in_use, RADAR)) == five(radar)
    assert snapshot(admin, in_use) == before  # the rows, the file, the store, and the audit log as they were


def test_a_refused_file_puts_the_rows_back(admin, not_recorded, monkeypatch, caplog):
    in_use = first_place(admin)
    row = open_row(admin, in_use, CAMERA)
    real_save = location_config.NodeRedConfig.save

    def edited_first(self):
        path = admin.app.state.config_path
        path.write_text(path.read_text() + "\n# edited by hand\n")
        return real_save(self)

    monkeypatch.setattr(location_config.NodeRedConfig, "save", edited_first)
    r = put(admin, in_use, [item(CAMERA, **POLE)])
    monkeypatch.undo()
    assert r.status_code == 409 and r.json()["error"]["code"] == "config_changed"
    # The hand edit makes Node-RED read the file again while the row is corrected, so it may start a deployment, as
    # the fake's does here; either way the row holds its old values again, and the new one the file's.
    after = next(found for found in rows(admin, in_use) if found["id"] == row["id"])
    assert five(after) == five(row)
    assert five(open_row(admin, in_use, CAMERA)) == five(row)
    assert "deployment" not in file_data(admin)["sensors"]["cameras"]["picam_h265"]
    assert store(admin, in_use)[CAMERA].height_m is None
    assert ("survey.mounting", in_use) not in audit_rows(admin)


def test_a_failed_put_back_is_logged_by_class(admin, not_recorded, monkeypatch, caplog):
    in_use = first_place(admin)
    row = open_row(admin, in_use, CAMERA)
    nodered = admin.app.state.nodered
    real = nodered.correct_mounting
    real_save = location_config.NodeRedConfig.save
    sent = []

    def first_works(deployment_id, values):
        sent.append(deployment_id)
        if len(sent) > 1:
            raise NodeRedError("unreachable")
        real(deployment_id, values)

    def edited_first(self):
        path = admin.app.state.config_path
        path.write_text(path.read_text() + "\n# edited by hand\n")
        return real_save(self)

    monkeypatch.setattr(nodered, "correct_mounting", first_works)
    monkeypatch.setattr(location_config.NodeRedConfig, "save", edited_first)
    with caplog.at_level(logging.WARNING):
        r = put(admin, in_use, [item(CAMERA, **POLE)])
    monkeypatch.undo()
    assert r.status_code == 409
    assert sent == [row["id"], row["id"]]
    assert "NodeRedError" in caplog.text and row["id"] not in caplog.text and "3.66" not in caplog.text


def reset_as_tmsetup_leaves_it(client, deployed: str, survey_id: str) -> None:
    """The file as tmsetup.sh -f leaves it: no survey id, a blank top-level heading, no sensor's deployment block.
    `deployed` is the file as it was after the first Deploy here, before any mounting."""
    assert f"survey_id: {survey_id}\n" in deployed and "heading_deg: 0\n" in deployed
    client.app.state.config_path.write_text(
        deployed.replace(f"survey_id: {survey_id}\n", "survey_id:\n").replace("heading_deg: 0\n", "heading_deg:\n")
    )


def test_a_save_into_a_reset_file_brings_the_place_back_first(admin, recorded):
    """A save sent before anything else ran the reconcile after tmsetup.sh -f must not read the reset file as what
    is mounted: the reconcile puts the id and the five back first, and then nothing differs."""
    in_use = first_place(admin)
    deployed = admin.app.state.config_path.read_text()
    fill_camera(admin, in_use)
    rows_before, store_before, audit_before = rows(admin, in_use), store(admin, in_use), audit_rows(admin)
    reset_as_tmsetup_leaves_it(admin, deployed, in_use)
    answer = saved(admin, in_use, [])
    assert answer["changes"] == []
    assert rows(admin, in_use) == rows_before
    assert store(admin, in_use) == store_before
    assert audit_rows(admin) == audit_before
    assert file_data(admin)["deployment"]["survey_id"] == in_use
    found = block(admin, CAMERA)
    assert [found.get(key) for key in FIVE] == [0, 15.0, 3.66, POLE_DISTANCE, "pole"]


def test_a_reset_file_reads_as_the_place_left_it(admin, recorded):
    in_use = first_place(admin)
    deployed = admin.app.state.config_path.read_text()
    fill_camera(admin, in_use)
    reset_as_tmsetup_leaves_it(admin, deployed, in_use)
    camera = of(mounting(admin, in_use)["sensors"], CAMERA)
    assert five(camera) == [0, 15.0, 3.66, POLE_DISTANCE, "pole"] and camera["measured"] == "pitch"


def test_a_save_refuses_a_file_that_no_longer_names_the_place(admin, recorded, monkeypatch):
    """A reset between the reconcile and the save's lock: the file no longer names the place, so nothing is saved."""
    in_use = first_place(admin)
    deployed = admin.app.state.config_path.read_text()
    fill_camera(admin, in_use)
    reset_as_tmsetup_leaves_it(admin, deployed, in_use)
    monkeypatch.setattr(reconcile, "ensure", lambda *args, **kwargs: None)
    before = snapshot(admin, in_use)
    r = put(admin, in_use, [])
    assert r.status_code == 409 and r.json()["error"]["code"] == "config_changed"
    assert snapshot(admin, in_use) == before


def test_a_save_says_where_to_look_when_the_files_survey_id_is_not_an_id(admin, recorded):
    """The reconcile leaves a survey_id that isn't an id alone, so reloading can't help: the answer says so."""
    in_use = first_place(admin)
    path = admin.app.state.config_path
    path.write_text(path.read_text().replace(f"survey_id: {in_use}\n", "survey_id: main street\n"))
    before = snapshot(admin, in_use)
    r = put(admin, in_use, [])
    assert r.status_code == 409 and r.json()["error"]["code"] == "config_changed"
    message = r.json()["error"]["message"]
    assert "survey_id isn't a survey id" in message and "Status page" in message and "Reload" not in message
    assert "main street" not in message
    assert snapshot(admin, in_use) == before


def test_saving_the_same_values_writes_nothing(admin, recorded):
    in_use = first_place(admin)
    fill_camera(admin, in_use)
    before = snapshot(admin, in_use)
    keys = ("sensor_type", "sensor_name", *FIVE, "measured", "same_as_camera")
    sent = [{key: s[key] for key in keys} for s in mounting(admin, in_use)["sensors"]]
    answer = saved(admin, in_use, sent)
    assert answer["changes"] == [] and answer["ask"] is False and answer["reloaded"] is None
    assert snapshot(admin, in_use) == before
