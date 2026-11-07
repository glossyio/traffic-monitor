"""The Location page's API: /api/v1/surveys (places, deploy, corrections, precision, CSV import).

claimed_client runs in fake mode: its config.yml is the seeded copy of fixtures/node_red_config_ok.yml (45.0, -122.0,
a camera and a radar facing 'n', no survey_id), and its Node-RED is fake.FakeNodeRed, which runs the deployment
engine's rules in memory. Nothing here logs or audits a coordinate or a description
(test_no_coordinate_in_any_log_line).
"""

import importlib
import logging
import sqlite3

import pytest
from ruamel.yaml import YAML

from tm_control.adapters.nodered import NodeRedError
from tm_control.core.auth import Users
from tm_control.modules.location.places import Places

BASE = "http://tm-test.local"
ORIGIN = {"Origin": BASE}
JSON_HEADERS = {**ORIGIN, "Content-Type": "application/json"}  # the cross-site check wants JSON on every non-GET
ADMIN = ("admin", "correct horse 1")
VIEWER = ("viewer", "viewer pass 1")
CAMERA = ("cameras", "picam_h265")
RADAR = ("radars", "TM_RADAR_SERIAL_PORT_00")
MAIN_ST = "Main St by the school"
# The module, not the APIRouter the package's __init__ binds to the same name.
surveys_router = importlib.import_module("tm_control.modules.location.router")


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    """Deploy polls Node-RED for up to 20 s; the fake applies a write at once, so a test never needs to wait."""
    monkeypatch.setattr(surveys_router, "POLL_INTERVAL", 0.0)
    monkeypatch.setattr(surveys_router, "DEPLOY_TIMEOUT", 0.0)


@pytest.fixture
def admin(claimed_client, login):
    login(claimed_client, *ADMIN)
    return claimed_client


def places(client) -> dict:
    r = client.get("/api/v1/surveys")
    assert r.status_code == 200, r.text
    return r.json()


def survey(state: dict, survey_id: str) -> dict:
    return next(s for s in state["surveys"] if s["id"] == survey_id)


def file_data(client) -> dict:
    return YAML(typ="safe", pure=True).load(client.app.state.config_path.read_text())


def backups(client) -> list:
    path = client.app.state.config_path
    return sorted(p.name for p in path.parent.glob(f"{path.name}.*.bak"))


def bearing(sensor, value):
    return {"sensor_type": sensor[0], "sensor_name": sensor[1], "bearing": value}


def create(client, description=MAIN_ST, lat=45.52252, lon=-122.6912, bearings=()):
    r = client.post(
        "/api/v1/surveys",
        json={"description": description, "lat": lat, "lon": lon, "bearings": list(bearings)},
        headers=ORIGIN,
    )
    assert r.status_code == 201, r.text
    return r.json()


def deploy(client, survey_id, bearings=()):
    r = client.post(f"/api/v1/surveys/{survey_id}/deploy", json={"bearings": list(bearings)}, headers=ORIGIN)
    assert r.status_code == 200, r.text
    return r.json()


def rows(client, survey_id):
    r = client.get(f"/api/v1/surveys/{survey_id}/deployments")
    assert r.status_code == 200, r.text
    return r.json()["deployments"]


def first_place(client) -> str:
    state = places(client)
    assert state["in_use"] is not None
    return state["in_use"]


def audit_rows(client):
    with sqlite3.connect(client.app.state.state.path) as con:
        return con.execute("SELECT action, detail FROM audit WHERE action LIKE 'survey.%' ORDER BY id").fetchall()


def test_surveys_needs_an_admin(claimed_client, login):
    assert claimed_client.get("/api/v1/surveys").status_code == 401
    Users(claimed_client.app.state.state).create(*VIEWER, "viewer")
    login(claimed_client, *VIEWER)
    assert claimed_client.get("/api/v1/surveys").status_code == 403
    r = claimed_client.post("/api/v1/surveys", json={"bearings": []}, headers=ORIGIN)
    assert r.status_code == 403
    assert claimed_client.get("/api/v1/surveys/00000000-si/deployments").status_code == 403


def test_claim_created_the_first_place_from_the_fixture(admin):
    state = places(admin)
    assert state["reconcile"] == "done"
    assert state["nodered"] is True
    assert state["precision"] == "1"
    assert state["sharing"] == "none"
    assert state["sensors"] == [bearing(CAMERA, "n"), bearing(RADAR, "n")]
    assert len(state["surveys"]) == 1
    place = state["surveys"][0]
    assert place["id"] == state["in_use"]
    assert place["status"] == "in_use"
    assert place["source"] == "imported_config"
    assert (place["lat"], place["lon"]) == (45.0, -122.0)
    assert (place["stored_lat"], place["stored_lon"]) == (45.0, -122.0)
    assert place["imported"] is False
    # The fake engine adopted the two open rows it started with, so the place has them and nothing is unassigned.
    assert place["open_count"] == 2 and place["deployment_count"] == 2
    assert isinstance(place["first_used"], int)
    assert state["unassigned"] is None
    assert file_data(admin)["deployment"]["survey_id"] == place["id"]


def test_create_a_planned_place_and_list_order(admin):
    in_use = first_place(admin)
    first = create(admin, "First planned", bearings=[bearing(CAMERA, " E ")])
    second = create(admin, None, None, None)
    assert first["status"] == "planned" and first["source"] == "ui"
    assert first["bearings"] == [bearing(CAMERA, "e")]
    assert (first["stored_lat"], first["stored_lon"]) == (45.5, -122.7)
    assert first["deployment_count"] == 0 and first["first_used"] is None
    assert second["lat"] is None and second["stored_lat"] is None and second["description"] is None
    listed = [s["id"] for s in places(admin)["surveys"]]
    # In use first, then the planned ones (newest first, but both were made within the same second)
    assert listed[0] == in_use and set(listed[1:]) == {first["id"], second["id"]}
    assert ("survey.create", first["id"]) in audit_rows(admin)


def test_create_refuses_a_bad_pair(admin):
    r = admin.post("/api/v1/surveys", json={"lat": 91, "lon": -122.0, "bearings": []}, headers=ORIGIN)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation"
    assert "lat" in r.json()["error"]["message"]
    r = admin.post("/api/v1/surveys", json={"lat": 45.0, "bearings": []}, headers=ORIGIN)
    assert r.status_code == 422
    r = admin.post("/api/v1/surveys", json={"bearings": [bearing(CAMERA, "north")]}, headers=ORIGIN)
    assert r.status_code == 422
    r = admin.post("/api/v1/surveys", json={"description": "x" * 201, "bearings": []}, headers=ORIGIN)
    assert r.status_code == 422
    assert len(places(admin)["surveys"]) == 1


def test_create_quantises_to_five_places(admin):
    place = create(admin, lat="45.522525", lon=-122.6912)
    assert place["lat"] == 45.52253


def test_patch_edits_only_a_planned_place(admin):
    in_use = first_place(admin)
    planned = create(admin)
    r = admin.patch(
        f"/api/v1/surveys/{planned['id']}",
        json={"description": "Renamed", "lat": None, "lon": None, "bearings": [bearing(RADAR, "s")]},
        headers=ORIGIN,
    )
    assert r.status_code == 200, r.text
    assert r.json()["description"] == "Renamed" and r.json()["lat"] is None
    assert r.json()["bearings"] == [bearing(RADAR, "s")]
    r = admin.patch(f"/api/v1/surveys/{in_use}", json={"bearings": []}, headers=ORIGIN)
    assert r.status_code == 409 and r.json()["error"]["code"] == "not_planned"
    assert admin.patch("/api/v1/surveys/0000000g-si", json={"bearings": []}, headers=ORIGIN).status_code == 404
    assert admin.patch("/api/v1/surveys/00000000-si", json={"bearings": []}, headers=ORIGIN).status_code == 404


def test_deploy_writes_the_file_and_starts_deployments(admin):
    old = first_place(admin)
    place = create(admin, bearings=[bearing(CAMERA, "e")])
    result = deploy(admin, place["id"])
    assert result["reloaded"] is True
    started = result["deployments"]
    assert len(started) == 2
    assert all(row["started"] >= result["deployed_at"] and row["ended"] is None for row in started)
    by_sensor = {(row["sensor_type"], row["sensor_name"]): row for row in started}
    assert by_sensor[CAMERA]["bearing"] == "e" and by_sensor[RADAR]["bearing"] == "n"
    assert all(row["lat"] == 45.5 and row["lon"] == -122.7 and row["location_precision"] == 1 for row in started)
    assert {row["id"] for row in rows(admin, place["id"])} == set(by_sensor[s]["id"] for s in (CAMERA, RADAR))

    data = file_data(admin)
    assert data["deployment"]["survey_id"] == place["id"]
    assert (data["deployment"]["lat"], data["deployment"]["lon"]) == (45.52252, -122.6912)
    assert data["sensors"]["cameras"]["picam_h265"]["deployment"]["bearing"] == "e"
    assert data["sensors"]["radars"]["TM_RADAR_SERIAL_PORT_00"]["deployment"]["bearing"] == "n"
    assert data["deployment"]["bearing"] == "n"  # the top-level default stays

    state = places(admin)
    assert state["in_use"] == place["id"]
    assert survey(state, old)["status"] == "used"
    assert survey(state, old)["open_count"] == 0 and survey(state, old)["last_used"] is not None
    assert survey(state, place["id"])["bearings"] == [bearing(CAMERA, "e"), bearing(RADAR, "n")]
    assert ("survey.deploy", place["id"]) in audit_rows(admin)


def test_deploy_body_bearings_win_and_are_checked(admin):
    first_place(admin)
    place = create(admin, bearings=[bearing(CAMERA, "e")])
    r = admin.post(
        f"/api/v1/surveys/{place['id']}/deploy",
        json={"bearings": [bearing(("cameras", "not_in_the_file"), "n")]},
        headers=ORIGIN,
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation"
    r = admin.post(f"/api/v1/surveys/{place['id']}/deploy", json={"bearings": [bearing(CAMERA, "up")]}, headers=ORIGIN)
    assert r.status_code == 422
    assert file_data(admin)["deployment"]["survey_id"] != place["id"]

    result = deploy(admin, place["id"], [bearing(CAMERA, "sw"), bearing(RADAR, "")])
    by_sensor = {(row["sensor_type"], row["sensor_name"]): row["bearing"] for row in result["deployments"]}
    assert by_sensor == {CAMERA: "sw", RADAR: ""}
    assert file_data(admin)["sensors"]["radars"]["TM_RADAR_SERIAL_PORT_00"]["deployment"]["bearing"] == ""


def test_deploy_the_same_place_again_changes_nothing(admin):
    place = create(admin, bearings=[bearing(CAMERA, "e")])
    first = deploy(admin, place["id"])
    before = backups(admin)
    again = deploy(admin, place["id"])
    assert again["reloaded"] is True
    assert {row["id"] for row in again["deployments"]} == {row["id"] for row in first["deployments"]}
    assert backups(admin) == before


def test_deploy_without_nodered_says_not_reloaded(admin, monkeypatch):
    place = create(admin)
    nodered = admin.app.state.nodered

    def unreachable(survey_id):
        raise NodeRedError("unreachable")

    monkeypatch.setattr(nodered, "deployments", unreachable)
    r = admin.post(f"/api/v1/surveys/{place['id']}/deploy", json={"bearings": []}, headers=ORIGIN)
    assert r.status_code == 200, r.text
    assert r.json()["reloaded"] is False
    assert r.json()["deployments"] == []
    assert file_data(admin)["deployment"]["survey_id"] == place["id"]


def test_deploy_waits_for_the_rows(admin, monkeypatch):
    """Rows that appear on the third poll are waited for; the poll sleeps between asks."""
    monkeypatch.setattr(surveys_router, "DEPLOY_TIMEOUT", 60.0)
    first_place(admin)
    place = create(admin)
    nodered = admin.app.state.nodered
    real = nodered.deployments
    asked, slept = [], []

    def late(survey_id):
        asked.append(survey_id)
        return real(survey_id) if len(asked) >= 3 else []

    monkeypatch.setattr(nodered, "deployments", late)
    monkeypatch.setattr(surveys_router, "sleep", slept.append)
    result = deploy(admin, place["id"])
    assert result["reloaded"] is True and len(result["deployments"]) == 2
    assert len(asked) == 3 and len(slept) == 2


def test_deploy_before_any_survey_counts_the_adopted_rows(admin):
    """Before reconcile has written a survey id (Node-RED was down then), the open rows have none; deploying makes
    Node-RED adopt them (same bearing), so they keep their start and still count as reloaded."""
    started = {row["id"] for row in admin.app.state.nodered.rows}
    place = Places(admin.app.state.state).create(
        "0123abcd-si", None, 45.52252, -122.6912, [], "ui", "planned", None
    )
    result = deploy(admin, place.id)
    assert result["reloaded"] is True
    assert {row["id"] for row in result["deployments"]} == started


def test_deploy_unknown_place_is_404(admin):
    assert admin.post("/api/v1/surveys/00000000-si/deploy", json={"bearings": []}, headers=ORIGIN).status_code == 404


def test_precision_rewrite_rounds_the_open_rows_and_optionally_all(admin):
    old = first_place(admin)
    place = create(admin)
    deploy(admin, place["id"])
    r = admin.put("/api/v1/surveys/precision", json={"precision": "2"}, headers=ORIGIN)
    assert r.status_code == 200, r.text
    assert r.json()["precision"] == "2"
    assert file_data(admin)["deployment"]["database_precision"] == "2"
    # A finer precision changes no row; the next deployment takes it.
    assert all(row["location_precision"] == 1 for row in rows(admin, place["id"]))

    r = admin.put("/api/v1/surveys/precision", json={"precision": "none", "round_stored": True}, headers=ORIGIN)
    assert r.status_code == 200, r.text
    assert r.json()["precision"] == "none"
    assert survey(r.json(), place["id"])["stored_lat"] is None
    assert "database_precision: 'none'" in admin.app.state.config_path.read_text()
    for survey_id in (old, place["id"]):
        assert all(row["lat"] is None and row["lon"] is None for row in rows(admin, survey_id))
    assert ("survey.precision", "none") in audit_rows(admin)


def test_precision_without_round_stored_rounds_only_the_open_rows(admin):
    old = first_place(admin)
    place = create(admin)
    deploy(admin, place["id"])
    r = admin.put("/api/v1/surveys/precision", json={"precision": "none"}, headers=ORIGIN)
    assert r.status_code == 200
    assert all(row["lat"] is None for row in rows(admin, place["id"]))  # open: re-rounded by the engine
    assert all(row["lat"] == 45.0 for row in rows(admin, old))  # closed: kept


def test_precision_nodered_failure_after_the_write_is_502(admin, monkeypatch):
    first_place(admin)

    def unreachable(precision):
        raise NodeRedError("unreachable")

    monkeypatch.setattr(admin.app.state.nodered, "set_precision", unreachable)
    r = admin.put("/api/v1/surveys/precision", json={"precision": "2", "round_stored": True}, headers=ORIGIN)
    assert r.status_code == 502
    assert r.json()["error"]["code"] == "nodered_error"
    assert "config.yml" in r.json()["error"]["message"]
    assert file_data(admin)["deployment"]["database_precision"] == "2"
    r = admin.put("/api/v1/surveys/precision", json={"precision": "3"}, headers=ORIGIN)
    assert r.status_code == 422


def test_correct_location_rounds_the_rows_and_records_it(admin):
    in_use = first_place(admin)
    r = admin.post(
        f"/api/v1/surveys/{in_use}/location",
        json={"lat": 45.52252, "lon": -122.6912, "reason": "Measured on site"},
        headers=ORIGIN,
    )
    assert r.status_code == 200, r.text
    assert (r.json()["lat"], r.json()["lon"]) == (45.52252, -122.6912)
    assert all((row["lat"], row["lon"]) == (45.5, -122.7) for row in rows(admin, in_use))
    data = file_data(admin)["deployment"]
    assert (data["lat"], data["lon"]) == (45.52252, -122.6912)
    places_store = Places(admin.app.state.state)
    with sqlite3.connect(places_store.state.path) as con:
        found = con.execute("SELECT field, old_value, new_value, reason, source FROM survey_corrections").fetchall()
    assert found == [("location", "45.0,-122.0", "45.52252,-122.6912", "Measured on site", "ui")]
    # The follow step sees the file and the store agree: no correction of its own.
    places(admin)
    with sqlite3.connect(places_store.state.path) as con:
        assert con.execute("SELECT COUNT(*) FROM survey_corrections").fetchone()[0] == 1
    assert ("survey.correct_location", in_use) in audit_rows(admin)

    planned = create(admin)
    r = admin.post(f"/api/v1/surveys/{planned['id']}/location", json={"lat": 45.0, "lon": -122.0}, headers=ORIGIN)
    assert r.status_code == 409 and r.json()["error"]["code"] == "not_used"


def test_correct_location_of_a_used_place_leaves_the_file(admin):
    old = first_place(admin)
    place = create(admin)
    deploy(admin, place["id"])
    r = admin.post(f"/api/v1/surveys/{old}/location", json={"lat": 45.52252, "lon": -122.6912}, headers=ORIGIN)
    assert r.status_code == 200, r.text
    assert all((row["lat"], row["lon"]) == (45.5, -122.7) for row in rows(admin, old))
    assert file_data(admin)["deployment"]["survey_id"] == place["id"]


def test_correct_location_nodered_failure_is_502_and_keeps_the_change(admin, monkeypatch):
    in_use = first_place(admin)

    def unreachable(survey_id, lat, lon):
        raise NodeRedError("unreachable")

    monkeypatch.setattr(admin.app.state.nodered, "correct_location", unreachable)
    r = admin.post(f"/api/v1/surveys/{in_use}/location", json={"lat": 45.52252, "lon": -122.6912}, headers=ORIGIN)
    assert r.status_code == 502
    assert r.json()["error"]["code"] == "nodered_error"
    assert survey(places(admin), in_use)["lat"] == 45.52252
    assert file_data(admin)["deployment"]["lat"] == 45.52252


def test_correct_location_refuses_a_bad_pair(admin):
    in_use = first_place(admin)
    r = admin.post(f"/api/v1/surveys/{in_use}/location", json={"lat": 45.0, "lon": 181}, headers=ORIGIN)
    assert r.status_code == 422 and "lon" in r.json()["error"]["message"]


def test_correct_bearing_on_an_open_row_updates_the_file(admin):
    in_use = first_place(admin)
    camera_row = next(row for row in rows(admin, in_use) if row["sensor_type"] == "cameras")
    url = f"/api/v1/surveys/{in_use}/deployments/{camera_row['id']}/bearing"
    r = admin.post(url, json={"bearing": "SW", "reason": "Compass check"}, headers=ORIGIN)
    assert r.status_code == 200, r.text
    assert r.json()["bearing"] == "sw" and r.json()["id"] == camera_row["id"]
    after = next(row for row in rows(admin, in_use) if row["id"] == camera_row["id"])
    assert after["bearing"] == "sw" and after["ended"] is None  # the same deployment, not a new one
    assert len(rows(admin, in_use)) == 2
    assert file_data(admin)["sensors"]["cameras"]["picam_h265"]["deployment"]["bearing"] == "sw"
    place = survey(places(admin), in_use)
    assert bearing(CAMERA, "sw") in place["bearings"]
    assert ("survey.correct_bearing", f"{in_use} {camera_row['id']}") in audit_rows(admin)


def test_correct_bearing_on_a_closed_row_leaves_the_file(admin):
    old = first_place(admin)
    place = create(admin)
    deploy(admin, place["id"])
    closed = next(row for row in rows(admin, old) if row["sensor_type"] == "cameras")
    assert closed["ended"] is not None
    before = admin.app.state.config_path.read_text()
    r = admin.post(f"/api/v1/surveys/{old}/deployments/{closed['id']}/bearing", json={"bearing": "s"}, headers=ORIGIN)
    assert r.status_code == 200, r.text
    assert next(row for row in rows(admin, old) if row["id"] == closed["id"])["bearing"] == "s"
    assert admin.app.state.config_path.read_text() == before
    assert all(b["bearing"] == "n" for b in survey(places(admin), old)["bearings"])


def test_correct_bearing_refusals(admin, monkeypatch):
    in_use = first_place(admin)
    row = rows(admin, in_use)[0]
    base = f"/api/v1/surveys/{in_use}/deployments"
    assert admin.post(f"{base}/not-an-id/bearing", json={"bearing": "s"}, headers=ORIGIN).status_code == 404
    assert admin.post(f"{base}/1-00000000-d/bearing", json={"bearing": "s"}, headers=ORIGIN).status_code == 404
    assert admin.post(f"{base}/{row['id']}/bearing", json={"bearing": "up"}, headers=ORIGIN).status_code == 422

    def unreachable(survey_id):
        raise NodeRedError("unreachable")

    monkeypatch.setattr(admin.app.state.nodered, "deployments", unreachable)
    r = admin.post(f"{base}/{row['id']}/bearing", json={"bearing": "s"}, headers=ORIGIN)
    assert r.status_code == 502
    assert r.json()["error"]["message"] == "Node-RED didn't answer."


def test_delete_refuses_the_place_in_use_and_removes_a_used_one(admin):
    old = first_place(admin)
    place = create(admin)
    r = admin.delete(f"/api/v1/surveys/{old}", headers=JSON_HEADERS)
    assert r.status_code == 409 and r.json()["error"]["code"] == "in_use"
    deploy(admin, place["id"])
    r = admin.delete(f"/api/v1/surveys/{old}", headers=JSON_HEADERS)
    assert r.status_code == 204
    assert [s["id"] for s in places(admin)["surveys"]] == [place["id"]]
    assert admin.delete(f"/api/v1/surveys/{old}", headers=JSON_HEADERS).status_code == 404
    assert ("survey.delete", old) in audit_rows(admin)


def test_deployments_and_events(admin):
    in_use = first_place(admin)
    assert len(rows(admin, in_use)) == 2
    r = admin.get(f"/api/v1/surveys/{in_use}/events")
    assert r.status_code == 200
    assert r.json() == {"event_count": 0, "first_event": None, "last_event": None}
    assert admin.get("/api/v1/surveys/00000000-si/events").status_code == 404
    assert admin.get("/api/v1/surveys/bad/deployments").status_code == 404


def test_places_without_nodered_still_list(admin, monkeypatch):
    in_use = first_place(admin)

    def unreachable():
        raise NodeRedError("unreachable")

    monkeypatch.setattr(admin.app.state.nodered, "usage", unreachable)
    state = places(admin)
    assert state["nodered"] is False
    assert survey(state, in_use)["deployment_count"] == 0


def test_rows_with_no_survey_are_counted(admin):
    in_use = first_place(admin)
    nodered = admin.app.state.nodered
    nodered.rows.append({
        "id": "1-00000000-d", "entryStartDateTime": 1, "entryEndDateTime": 2, "lat": None, "lon": None,
        "bearing": "", "sensorType": "radars", "sensorName": "TM_RADAR_SERIAL_PORT_00", "survey_id": None,
        "location_precision": None,
    })
    state = places(admin)
    assert state["unassigned"] == {"deployment_count": 1, "first_start": 1, "last_end": 2}
    assert survey(state, in_use)["deployment_count"] == 2


def test_a_file_changed_by_hand_while_a_write_runs_is_409(admin, monkeypatch):
    from tm_control.modules.location import config as location_config

    first_place(admin)
    place = create(admin)
    real_save = location_config.NodeRedConfig.save

    def edited_first(self):
        path = admin.app.state.config_path
        path.write_text(path.read_text() + "\n# edited by hand\n")
        return real_save(self)

    monkeypatch.setattr(location_config.NodeRedConfig, "save", edited_first)
    before = backups(admin)
    r = admin.post(f"/api/v1/surveys/{place['id']}/deploy", json={"bearings": []}, headers=ORIGIN)
    assert r.status_code == 409 and r.json()["error"]["code"] == "config_changed"
    assert backups(admin) == before
    monkeypatch.undo()
    assert survey(places(admin), place["id"])["status"] == "planned"


IMPORT_CSV = "description,lat,lon,picam_h265\nMain St,45.52252,-122.69120,n\nNo location,,,\n"


def test_import_previews_then_creates(admin):
    first_place(admin)
    r = admin.post("/api/v1/surveys/import", json={"csv": IMPORT_CSV}, headers=ORIGIN)
    assert r.status_code == 200, r.text
    preview = r.json()
    assert preview["errors"] == [] and preview["created"] == []
    assert preview["rows"] == [
        {"line": 2, "description": "Main St", "lat": 45.52252, "lon": -122.6912, "bearings": [bearing(CAMERA, "n")]},
        {"line": 3, "description": "No location", "lat": None, "lon": None, "bearings": []},
    ]
    assert len(places(admin)["surveys"]) == 1

    r = admin.post("/api/v1/surveys/import", json={"csv": IMPORT_CSV, "dry_run": False}, headers=ORIGIN)
    assert r.status_code == 200, r.text
    created = r.json()["created"]
    assert len(created) == 2
    state = places(admin)
    assert [survey(state, i)["source"] for i in created] == ["csv", "csv"]
    assert [survey(state, i)["status"] for i in created] == ["planned", "planned"]
    assert survey(state, created[0])["bearings"] == [bearing(CAMERA, "n")]


@pytest.mark.parametrize("line, message", [
    ("Bad,45,52252,-122.69120,n", "lon"),
    ("Bad,45.52252,-122.69120,north", "bearing"),
    ("Bad,45.52252,,n", "both"),
])
def test_import_refuses_a_bad_line_and_creates_nothing(admin, line, message):
    first_place(admin)
    text = IMPORT_CSV + line + "\n"
    r = admin.post("/api/v1/surveys/import", json={"csv": text}, headers=ORIGIN)
    assert r.status_code == 200
    errors = r.json()["errors"]
    assert [e["line"] for e in errors] == [4]
    assert message in errors[0]["message"]
    assert "45" not in errors[0]["message"] and "Bad" not in errors[0]["message"]
    r = admin.post("/api/v1/surveys/import", json={"csv": text, "dry_run": False}, headers=ORIGIN)
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation"
    assert r.json()["error"]["detail"] == errors
    assert len(places(admin)["surveys"]) == 1


def test_import_needs_the_header_and_known_sensors(admin):
    r = admin.post("/api/v1/surveys/import", json={"csv": "name,lat,lon\nA,,\n"}, headers=ORIGIN)
    assert r.status_code == 200
    assert r.json()["errors"][0]["line"] == 1
    r = admin.post("/api/v1/surveys/import", json={"csv": "description,lat,lon,nope\nA,,,n\n"}, headers=ORIGIN)
    assert r.json()["errors"][0]["line"] == 1 and "Column 4 " in r.json()["errors"][0]["message"]
    r = admin.post("/api/v1/surveys/import", json={"csv": "description,lat,lon,picam_h265,cameras.picam_h265\n"},
                   headers=ORIGIN)
    assert "Column 5 " in r.json()["errors"][0]["message"]
    text = "description,lat,lon,radars.TM_RADAR_SERIAL_PORT_00\nA,,,se\n"
    r = admin.post("/api/v1/surveys/import", json={"csv": text}, headers=ORIGIN)
    assert r.json()["errors"] == [] and r.json()["rows"][0]["bearings"] == [bearing(RADAR, "se")]


def test_no_coordinate_in_any_log_line(admin, caplog, monkeypatch):
    caplog.set_level(logging.DEBUG)
    in_use = first_place(admin)
    place = create(admin, MAIN_ST, bearings=[bearing(CAMERA, "e")])
    deploy(admin, place["id"])
    admin.post(f"/api/v1/surveys/{place['id']}/location", json={"lat": 45.52252, "lon": -122.6912,
               "reason": "Secret reason"}, headers=ORIGIN)
    row = rows(admin, place["id"])[0]
    admin.post(f"/api/v1/surveys/{place['id']}/deployments/{row['id']}/bearing", json={"bearing": "w",
               "reason": "Secret reason"}, headers=ORIGIN)
    admin.put("/api/v1/surveys/precision", json={"precision": "2", "round_stored": True}, headers=ORIGIN)
    admin.post("/api/v1/surveys/import", json={"csv": IMPORT_CSV, "dry_run": False}, headers=ORIGIN)
    admin.post("/api/v1/surveys/import", json={"csv": IMPORT_CSV + "Bad,45,52252,,\n", "dry_run": False},
               headers=ORIGIN)
    admin.post("/api/v1/surveys", json={"lat": 91, "lon": -122.0, "bearings": []}, headers=ORIGIN)
    admin.delete(f"/api/v1/surveys/{in_use}", headers=JSON_HEADERS)

    def unreachable(*args):
        raise NodeRedError("unreachable")

    monkeypatch.setattr(admin.app.state.nodered, "correct_location", unreachable)
    admin.post(f"/api/v1/surveys/{place['id']}/location", json={"lat": 45.0, "lon": -122.0}, headers=ORIGIN)
    places(admin)
    assert caplog.records
    for record in caplog.records:
        message = record.getMessage()
        for needle in ("45.5", "-122.6", "45.0", "-122.0", MAIN_ST, "Secret reason", "Main St"):
            assert needle not in message
    for action, detail in audit_rows(admin):
        for needle in ("45.", "122.", MAIN_ST, "Main St", "Secret"):  # ids hold no dot
            assert needle not in (detail or "")


def test_fake_mode_seeds_config_yml_once_and_reset_seeds_it_again(settings, capsys):
    from tm_control import fake
    from tm_control.adapters.nodered import config_file_path

    path = fake.seed_config(settings)
    assert path == config_file_path(settings, None)
    fixture = (fake.FAKE_FIXTURES / "node_red_config_ok.yml").read_text()
    assert path.read_text() == fixture
    path.write_text(fixture + "# kept\n")
    (path.parent / f"{path.name}.20261107T000000Z.bak").write_text("old")
    fake.seed_config(settings)
    assert path.read_text().endswith("# kept\n")
    assert fake.reset(settings) == 0
    assert path.read_text() == fixture
    assert [p.name for p in path.parent.iterdir()] == ["config.yml"]
    capsys.readouterr()  # the setup code reset prints


def test_fake_nodered_follows_a_hand_edit_of_the_file(admin):
    """Like the watch node: a change to config.yml is applied on the fake's next call, with no after_config_write."""
    in_use = first_place(admin)
    path = admin.app.state.config_path
    path.write_text(path.read_text().replace("bearing: 'n'", "bearing: 'w'", 1))
    found = rows(admin, in_use)
    assert len(found) == 4 and sorted(row["bearing"] for row in found if row["ended"] is None) == ["w", "w"]
