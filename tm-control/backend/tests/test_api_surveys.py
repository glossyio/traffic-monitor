"""The Location page's API: /api/v1/surveys (places, deploy, corrections, precision, CSV import).

claimed_client runs in fake mode: its config.yml is the seeded copy of fixtures/node_red_config_ok.yml (45.0, -122.0,
a camera and a radar facing 0, no survey_id), and its Node-RED is fake.FakeNodeRed, which runs the deployment
engine's rules in memory. Nothing here logs or audits a coordinate or a description
(test_no_coordinate_in_any_log_line).
"""

import importlib
import logging
import re
import sqlite3

import pytest
from ruamel.yaml import YAML

from tm_control.adapters.nodered import NodeRedError
from tm_control.adapters.redact import REDACTED, redact
from tm_control.core.auth import Users
from tm_control.core.manifest import MapInfo
from tm_control.modules.location import region as region_module
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


@pytest.fixture(autouse=True)
def zone_table(monkeypatch, tmp_path):
    """The time-zone tables the region is read from: small ones of our own, not the machine's tzdata."""
    path = tmp_path / "zone1970.tab"
    path.write_text(
        "US\t+340308-1181434\tAmerica/Los_Angeles\tPacific\nGB,GG,IM,JE\t+513030-0000731\tEurope/London\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(region_module, "ZONE_TAB", path)
    all_zones = tmp_path / "zone.tab"
    all_zones.write_text("NL\t+5222+00454\tEurope/Amsterdam\n", encoding="utf-8")
    monkeypatch.setattr(region_module, "ZONE_TAB_ALL", all_zones)


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


def heading(sensor, value):
    return {"sensor_type": sensor[0], "sensor_name": sensor[1], "heading_deg": value}


def create(client, description=MAIN_ST, lat=45.52252, lon=-122.6912, headings=()):
    r = client.post(
        "/api/v1/surveys",
        json={"description": description, "lat": lat, "lon": lon, "headings": list(headings)},
        headers=ORIGIN,
    )
    assert r.status_code == 201, r.text
    return r.json()


def deploy(client, survey_id, headings=()):
    r = client.post(f"/api/v1/surveys/{survey_id}/deploy", json={"headings": list(headings)}, headers=ORIGIN)
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
    r = claimed_client.post("/api/v1/surveys", json={"headings": []}, headers=ORIGIN)
    assert r.status_code == 403
    assert claimed_client.get("/api/v1/surveys/00000000-si/deployments").status_code == 403


def test_claim_created_the_first_place_from_the_fixture(admin):
    state = places(admin)
    assert state["reconcile"] == "done"
    assert state["nodered"] is True
    assert state["precision"] == "2"  # the fixture has none: the default
    assert state["sharing"] == "none"
    assert state["sensors"] == [heading(CAMERA, 0), heading(RADAR, 0)]
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


STYLE = "https://tiles.openfreemap.org/styles/liberty"
LOS_ANGELES = {"lat": 34.05, "lon": -118.24}  # fake mode's time zone and Wi-Fi country (US), as the table has them
SOURCES = {"style_url": STYLE, "region": LOS_ANGELES}


def map_style(client, style):
    """Swap the manifest's map section, as a device installed with other settings would have it."""
    manifest = client.app.state.manifest
    client.app.state.manifest = manifest.model_copy(update={"map": MapInfo(style)})


def test_places_name_the_map_sources(admin):
    assert places(admin)["map"] == SOURCES


def test_precision_answers_with_the_map_sources(admin):
    r = admin.put("/api/v1/surveys/precision", json={"precision": "1"}, headers=ORIGIN)
    assert r.status_code == 200, r.text
    assert r.json()["map"] == SOURCES


@pytest.mark.parametrize("style", ["", "http://tiles.example.invalid/style", "ftp://x"])
def test_a_map_source_that_is_not_https_is_off(admin, style):
    map_style(admin, style)
    assert places(admin)["map"] == {"style_url": None, "region": None}


def test_no_map_means_no_region(admin):
    map_style(admin, "")
    assert places(admin)["map"]["region"] is None


@pytest.mark.parametrize("country", ["", None, "GB"])
def test_a_country_that_is_not_the_zones_gives_no_region(admin, country):
    admin.app.state.fake_network.country = country
    assert places(admin)["map"]["region"] is None


def test_a_zone_the_table_lacks_gives_no_region(admin):
    admin.app.state.fake_clock.timezone = "Etc/UTC"
    assert places(admin)["map"]["region"] is None


def test_a_zone_only_the_second_table_lists_gives_its_region(admin):
    admin.app.state.fake_clock.timezone = "Europe/Amsterdam"
    admin.app.state.fake_network.country = "NL"
    assert places(admin)["map"]["region"] == {"lat": 52.37, "lon": 4.9}


def test_places_say_what_is_shared(admin):
    """sharing is none with the upload off, data with it on, and exact with the exact location chosen for its server."""
    from tm_control.core.secrets import THINGSBOARD_ACCESS_TOKEN

    admin.app.state.secrets.entered[THINGSBOARD_ACCESS_TOKEN] = "tb-placeholder-0001"
    version = admin.app.state.notice.version
    choice = {"target": "maintainer", "enabled": True, "exact_location": False, "public_map": "none",
              "notice_version": version}
    assert places(admin)["sharing"] == "none"
    assert admin.put("/api/v1/sharing", json=choice, headers=ORIGIN).status_code == 200
    assert places(admin)["sharing"] == "data"
    choice["exact_location"] = True
    assert admin.put("/api/v1/sharing", json=choice, headers=ORIGIN).status_code == 200
    assert places(admin)["sharing"] == "exact"


def test_create_a_planned_place_and_list_order(admin):
    in_use = first_place(admin)
    first = create(admin, "First planned", headings=[heading(CAMERA, 90)])
    second = create(admin, None, None, None)
    assert first["status"] == "planned" and first["source"] == "ui"
    assert first["headings"] == [heading(CAMERA, 90)]
    assert (first["stored_lat"], first["stored_lon"]) == (45.52, -122.69)
    assert first["deployment_count"] == 0 and first["first_used"] is None
    assert second["lat"] is None and second["stored_lat"] is None and second["description"] is None
    listed = [s["id"] for s in places(admin)["surveys"]]
    # In use first, then the planned ones (newest first, but both were made within the same second)
    assert listed[0] == in_use and set(listed[1:]) == {first["id"], second["id"]}
    assert ("survey.create", first["id"]) in audit_rows(admin)


def test_create_refuses_a_bad_pair(admin):
    r = admin.post("/api/v1/surveys", json={"lat": 91, "lon": -122.0, "headings": []}, headers=ORIGIN)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation"
    assert "lat" in r.json()["error"]["message"]
    r = admin.post("/api/v1/surveys", json={"lat": 45.0, "headings": []}, headers=ORIGIN)
    assert r.status_code == 422
    r = admin.post("/api/v1/surveys", json={"headings": [heading(CAMERA, 360)]}, headers=ORIGIN)
    assert r.status_code == 422
    assert r.json()["error"]["message"] == "A heading is a whole number from 0 to 359, or blank."
    assert r.json()["error"]["detail"] == {"field": "headings"}
    r = admin.post("/api/v1/surveys", json={"description": "x" * 201, "headings": []}, headers=ORIGIN)
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
        json={"description": "Renamed", "lat": None, "lon": None, "headings": [heading(RADAR, 180)]},
        headers=ORIGIN,
    )
    assert r.status_code == 200, r.text
    assert r.json()["description"] == "Renamed" and r.json()["lat"] is None
    assert r.json()["headings"] == [heading(RADAR, 180)]
    r = admin.patch(f"/api/v1/surveys/{in_use}", json={"headings": []}, headers=ORIGIN)
    assert r.status_code == 409 and r.json()["error"]["code"] == "not_planned"
    assert admin.patch("/api/v1/surveys/0000000g-si", json={"headings": []}, headers=ORIGIN).status_code == 404
    assert admin.patch("/api/v1/surveys/00000000-si", json={"headings": []}, headers=ORIGIN).status_code == 404


def test_deploy_writes_the_file_and_starts_deployments(admin):
    old = first_place(admin)
    place = create(admin, headings=[heading(CAMERA, 90)])
    result = deploy(admin, place["id"])
    assert result["reloaded"] is True
    started = result["deployments"]
    assert len(started) == 2
    assert all(row["started"] >= result["deployed_at"] and row["ended"] is None for row in started)
    by_sensor = {(row["sensor_type"], row["sensor_name"]): row for row in started}
    assert by_sensor[CAMERA]["heading_deg"] == 90 and by_sensor[RADAR]["heading_deg"] == 0
    assert all(row["lat"] == 45.52 and row["lon"] == -122.69 and row["location_precision"] == 2 for row in started)
    assert {row["id"] for row in rows(admin, place["id"])} == set(by_sensor[s]["id"] for s in (CAMERA, RADAR))

    data = file_data(admin)
    assert data["deployment"]["survey_id"] == place["id"]
    assert (data["deployment"]["lat"], data["deployment"]["lon"]) == (45.52252, -122.6912)
    assert data["sensors"]["cameras"]["picam_h265"]["deployment"]["heading_deg"] == 90
    assert data["sensors"]["radars"]["TM_RADAR_SERIAL_PORT_00"]["deployment"]["heading_deg"] == 0
    assert data["deployment"]["heading_deg"] == 0  # the top-level default stays

    state = places(admin)
    assert state["in_use"] == place["id"]
    assert survey(state, old)["status"] == "used"
    assert survey(state, old)["open_count"] == 0 and survey(state, old)["last_used"] is not None
    assert survey(state, place["id"])["headings"] == [heading(CAMERA, 90), heading(RADAR, 0)]
    assert ("survey.deploy", place["id"]) in audit_rows(admin)


def test_deploy_body_headings_win_and_are_checked(admin):
    first_place(admin)
    place = create(admin, headings=[heading(CAMERA, 90)])
    r = admin.post(
        f"/api/v1/surveys/{place['id']}/deploy",
        json={"headings": [heading(("cameras", "not_in_the_file"), 0)]},
        headers=ORIGIN,
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation"
    r = admin.post(f"/api/v1/surveys/{place['id']}/deploy", json={"headings": [heading(CAMERA, -1)]}, headers=ORIGIN)
    assert r.status_code == 422 and r.json()["error"]["detail"] == {"field": "headings"}
    assert file_data(admin)["deployment"]["survey_id"] != place["id"]

    result = deploy(admin, place["id"], [heading(CAMERA, 225), heading(RADAR, None)])
    by_sensor = {(row["sensor_type"], row["sensor_name"]): row["heading_deg"] for row in result["deployments"]}
    assert by_sensor == {CAMERA: 225, RADAR: None}
    assert file_data(admin)["sensors"]["radars"]["TM_RADAR_SERIAL_PORT_00"]["deployment"]["heading_deg"] is None


def test_deploy_with_blank_headings_adds_no_block_to_the_sensors(admin):
    first_place(admin)
    path = admin.app.state.config_path
    path.write_text(path.read_text().replace("heading_deg: 0", "heading_deg:", 1))
    places(admin)
    place = create(admin, headings=[])
    deploy(admin, place["id"])
    sensors = file_data(admin)["sensors"]
    assert "deployment" not in sensors["cameras"]["picam_h265"]
    assert "deployment" not in sensors["radars"]["TM_RADAR_SERIAL_PORT_00"]
    assert file_data(admin)["deployment"]["survey_id"] == place["id"]


def test_deploy_the_same_place_again_changes_nothing(admin):
    place = create(admin, headings=[heading(CAMERA, 90)])
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
    r = admin.post(f"/api/v1/surveys/{place['id']}/deploy", json={"headings": []}, headers=ORIGIN)
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
    Node-RED adopt them (same heading), so they keep their start and still count as reloaded."""
    started = {row["id"] for row in admin.app.state.nodered.rows}
    place = Places(admin.app.state.state).create(
        "0123abcd-si", None, 45.52252, -122.6912, [], "ui", "planned", None
    )
    result = deploy(admin, place.id)
    assert result["reloaded"] is True
    assert {row["id"] for row in result["deployments"]} == started


def test_deploy_unknown_place_is_404(admin):
    assert admin.post("/api/v1/surveys/00000000-si/deploy", json={"headings": []}, headers=ORIGIN).status_code == 404


def test_precision_rewrite_rounds_the_open_rows_and_optionally_all(admin):
    old = first_place(admin)
    place = create(admin)
    assert admin.put("/api/v1/surveys/precision", json={"precision": "1"}, headers=ORIGIN).status_code == 200
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
    assert all((row["lat"], row["lon"]) == (45.52, -122.69) for row in rows(admin, in_use))
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
    assert all((row["lat"], row["lon"]) == (45.52, -122.69) for row in rows(admin, old))
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


def test_correct_heading_on_an_open_row_updates_the_file(admin):
    in_use = first_place(admin)
    camera_row = next(row for row in rows(admin, in_use) if row["sensor_type"] == "cameras")
    url = f"/api/v1/surveys/{in_use}/deployments/{camera_row['id']}/heading"
    r = admin.post(url, json={"heading_deg": 225, "reason": "Compass check"}, headers=ORIGIN)
    assert r.status_code == 200, r.text
    assert r.json()["heading_deg"] == 225 and r.json()["id"] == camera_row["id"]
    after = next(row for row in rows(admin, in_use) if row["id"] == camera_row["id"])
    assert after["heading_deg"] == 225 and after["ended"] is None  # the same deployment, not a new one
    assert len(rows(admin, in_use)) == 2
    assert file_data(admin)["sensors"]["cameras"]["picam_h265"]["deployment"]["heading_deg"] == 225
    place = survey(places(admin), in_use)
    assert heading(CAMERA, 225) in place["headings"]
    assert ("survey.correct_heading", f"{in_use} {camera_row['id']}") in audit_rows(admin)
    con = admin.app.state.state.connect()
    try:
        found = con.execute("SELECT field, old_value, new_value FROM survey_corrections").fetchall()
    finally:
        con.close()
    assert [tuple(row) for row in found] == [("heading_deg", "0", "225")]


def test_correct_heading_on_a_closed_row_leaves_the_file(admin):
    old = first_place(admin)
    place = create(admin)
    deploy(admin, place["id"])
    closed = next(row for row in rows(admin, old) if row["sensor_type"] == "cameras")
    assert closed["ended"] is not None
    before = admin.app.state.config_path.read_text()
    url = f"/api/v1/surveys/{old}/deployments/{closed['id']}/heading"
    r = admin.post(url, json={"heading_deg": 180}, headers=ORIGIN)
    assert r.status_code == 200, r.text
    assert next(row for row in rows(admin, old) if row["id"] == closed["id"])["heading_deg"] == 180
    assert admin.app.state.config_path.read_text() == before
    assert all(h["heading_deg"] == 0 for h in survey(places(admin), old)["headings"])


def camera_row_of(admin, survey_id):
    return next(row for row in rows(admin, survey_id) if row["sensor_type"] == "cameras")


def correction_rows(client):
    con = client.app.state.state.connect()
    try:
        return con.execute("SELECT field FROM survey_corrections").fetchall()
    finally:
        con.close()


def test_a_hand_edit_while_node_red_rewrites_the_row_is_kept(admin, monkeypatch):
    """config.yml is read after Node-RED's row changed, so an edit made during that call isn't a conflict."""
    in_use = first_place(admin)
    row = camera_row_of(admin, in_use)
    nodered = admin.app.state.nodered
    real = nodered.correct_heading

    def edited_during(deployment_id, new_heading):
        real(deployment_id, new_heading)
        path = admin.app.state.config_path
        path.write_text(path.read_text() + "\n# edited by hand\n")

    monkeypatch.setattr(nodered, "correct_heading", edited_during)
    url = f"/api/v1/surveys/{in_use}/deployments/{row['id']}/heading"
    r = admin.post(url, json={"heading_deg": 225}, headers=ORIGIN)
    monkeypatch.undo()
    assert r.status_code == 200, r.text
    text = admin.app.state.config_path.read_text()
    assert "# edited by hand" in text
    assert file_data(admin)["sensors"]["cameras"]["picam_h265"]["deployment"]["heading_deg"] == 225
    assert len(correction_rows(admin)) == 1


def test_a_file_changed_while_saving_a_heading_puts_the_row_back(admin, monkeypatch):
    """A 409 must leave nothing half done: the row keeps its heading, and a retry records the real old value."""
    from tm_control.modules.location import config as location_config

    in_use = first_place(admin)
    row = camera_row_of(admin, in_use)
    real_save = location_config.NodeRedConfig.save

    def edited_first(self):
        path = admin.app.state.config_path
        path.write_text(path.read_text() + "\n# edited by hand\n")
        return real_save(self)

    monkeypatch.setattr(location_config.NodeRedConfig, "save", edited_first)
    url = f"/api/v1/surveys/{in_use}/deployments/{row['id']}/heading"
    r = admin.post(url, json={"heading_deg": 225}, headers=ORIGIN)
    monkeypatch.undo()
    assert r.status_code == 409 and r.json()["error"]["code"] == "config_changed"
    assert camera_row_of(admin, in_use)["heading_deg"] == row["heading_deg"]
    assert "deployment" not in file_data(admin)["sensors"]["cameras"]["picam_h265"]  # the refused save wrote nothing
    assert correction_rows(admin) == []
    assert ("survey.correct_heading", f"{in_use} {row['id']}") not in audit_rows(admin)
    assert heading(CAMERA, row["heading_deg"]) in survey(places(admin), in_use)["headings"]


def test_an_unreadable_file_after_the_row_changed_puts_the_row_back(admin, monkeypatch):
    in_use = first_place(admin)
    row = camera_row_of(admin, in_use)
    nodered = admin.app.state.nodered
    path = admin.app.state.config_path
    text = path.read_text()
    real = nodered.correct_heading

    def broke_the_file(deployment_id, new_heading):
        real(deployment_id, new_heading)
        monkeypatch.setattr(nodered, "correct_heading", real)  # the revert goes through
        path.write_text("{ not yaml")

    monkeypatch.setattr(nodered, "correct_heading", broke_the_file)
    url = f"/api/v1/surveys/{in_use}/deployments/{row['id']}/heading"
    r = admin.post(url, json={"heading_deg": 225}, headers=ORIGIN)
    path.write_text(text)
    assert r.status_code == 500 and r.json()["error"]["code"] == "config_error"
    assert camera_row_of(admin, in_use)["heading_deg"] == row["heading_deg"]
    assert correction_rows(admin) == []


def test_a_failed_revert_is_logged_by_class_and_still_answers_409(admin, monkeypatch, caplog):
    from tm_control.modules.location import config as location_config

    in_use = first_place(admin)
    row = camera_row_of(admin, in_use)
    nodered = admin.app.state.nodered
    real_save = location_config.NodeRedConfig.save
    real = nodered.correct_heading
    sent = []

    def first_works(deployment_id, new_heading):
        sent.append(new_heading)
        if len(sent) > 1:
            raise NodeRedError("unreachable")
        real(deployment_id, new_heading)

    def edited_first(self):
        path = admin.app.state.config_path
        path.write_text(path.read_text() + "\n# edited by hand\n")
        return real_save(self)

    monkeypatch.setattr(nodered, "correct_heading", first_works)
    monkeypatch.setattr(location_config.NodeRedConfig, "save", edited_first)
    with caplog.at_level(logging.WARNING):
        r = admin.post(
            f"/api/v1/surveys/{in_use}/deployments/{row['id']}/heading", json={"heading_deg": 225}, headers=ORIGIN
        )
    monkeypatch.undo()
    assert r.status_code == 409
    assert sent == [225, row["heading_deg"]]
    assert "NodeRedError" in caplog.text and row["id"] not in caplog.text


def test_correct_heading_refusals(admin, monkeypatch):
    in_use = first_place(admin)
    row = rows(admin, in_use)[0]
    base = f"/api/v1/surveys/{in_use}/deployments"
    assert admin.post(f"{base}/not-an-id/heading", json={"heading_deg": 180}, headers=ORIGIN).status_code == 404
    assert admin.post(f"{base}/1-00000000-d/heading", json={"heading_deg": 180}, headers=ORIGIN).status_code == 404
    r = admin.post(f"{base}/{row['id']}/heading", json={"heading_deg": 360}, headers=ORIGIN)
    assert r.status_code == 422
    assert r.json()["error"]["message"] == "A heading is a whole number from 0 to 359, or blank."
    assert admin.post(f"{base}/{row['id']}/heading", json={"heading_deg": "s"}, headers=ORIGIN).status_code == 422
    assert admin.post(f"{base}/{row['id']}/heading", json={"reason": "no heading"}, headers=ORIGIN).status_code == 422

    def unreachable(survey_id):
        raise NodeRedError("unreachable")

    monkeypatch.setattr(admin.app.state.nodered, "deployments", unreachable)
    r = admin.post(f"{base}/{row['id']}/heading", json={"heading_deg": 180}, headers=ORIGIN)
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
        "heading_deg": None, "sensorType": "radars", "sensorName": "TM_RADAR_SERIAL_PORT_00", "survey_id": None,
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
    r = admin.post(f"/api/v1/surveys/{place['id']}/deploy", json={"headings": []}, headers=ORIGIN)
    assert r.status_code == 409 and r.json()["error"]["code"] == "config_changed"
    assert backups(admin) == before
    monkeypatch.undo()
    assert survey(places(admin), place["id"])["status"] == "planned"


def reset_file(client, survey_id):
    """What tmsetup.sh -f leaves: no survey id, and the template's precision."""
    path = client.app.state.config_path
    text = re.sub(r"database_precision: .*\n", "database_precision: '2'\n", path.read_text())
    path.write_text(text.replace(f"survey_id: {survey_id}\n", "survey_id:\n"))


def test_a_precision_saved_on_the_page_comes_back_after_a_reset(admin):
    in_use = first_place(admin)
    r = admin.put("/api/v1/surveys/precision", json={"precision": "none"}, headers=ORIGIN)
    assert r.status_code == 200, r.text
    reset_file(admin, in_use)
    state = places(admin)
    assert state["precision"] == "none" and state["in_use"] == in_use
    assert file_data(admin)["deployment"]["database_precision"] == "none"
    assert file_data(admin)["deployment"]["survey_id"] == in_use


def test_a_precision_saved_while_the_file_is_reset_is_the_one_kept(admin):
    in_use = first_place(admin)
    assert admin.put("/api/v1/surveys/precision", json={"precision": "none"}, headers=ORIGIN).status_code == 200
    reset_file(admin, in_use)
    r = admin.put("/api/v1/surveys/precision", json={"precision": "1"}, headers=ORIGIN)
    assert r.status_code == 200, r.text
    assert r.json()["precision"] == "1"
    assert file_data(admin)["deployment"]["database_precision"] == "1"


IMPORT_CSV = "description,lat,lon,picam_h265\nMain St,45.52252,-122.69120,n\nNo location,,,\n"


def test_import_previews_then_creates(admin):
    first_place(admin)
    r = admin.post("/api/v1/surveys/import", json={"csv": IMPORT_CSV}, headers=ORIGIN)
    assert r.status_code == 200, r.text
    preview = r.json()
    assert preview["errors"] == [] and preview["created"] == []
    assert preview["rows"] == [
        {"line": 2, "description": "Main St", "lat": 45.52252, "lon": -122.6912, "headings": [heading(CAMERA, 0)]},
        {"line": 3, "description": "No location", "lat": None, "lon": None, "headings": []},
    ]
    assert len(places(admin)["surveys"]) == 1

    r = admin.post("/api/v1/surveys/import", json={"csv": IMPORT_CSV, "dry_run": False}, headers=ORIGIN)
    assert r.status_code == 200, r.text
    created = r.json()["created"]
    assert len(created) == 2
    state = places(admin)
    assert [survey(state, i)["source"] for i in created] == ["csv", "csv"]
    assert [survey(state, i)["status"] for i in created] == ["planned", "planned"]
    assert survey(state, created[0])["headings"] == [heading(CAMERA, 0)]


@pytest.mark.parametrize("line, message", [
    ("Bad,45,52252,-122.69120,n", "lon"),
    ("Bad,45.52252,-122.69120,north", "The heading for picam_h265 must be"),
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
    assert r.json()["errors"] == [] and r.json()["rows"][0]["headings"] == [heading(RADAR, 135)]


def test_the_api_refuses_a_compass_point(admin):
    """The API takes whole numbers only; a compass point is a way to pick one on the page, not a value it sends."""
    first_place(admin)
    place = create(admin)
    url = f"/api/v1/surveys/{place['id']}/deploy"
    for value in ("ne", "45", 45.5, True):
        r = admin.post(url, json={"headings": [heading(CAMERA, value)]}, headers=ORIGIN)
        assert r.status_code == 422 and r.json()["error"]["code"] == "validation", value
        r = admin.post("/api/v1/surveys", json={"headings": [heading(CAMERA, value)]}, headers=ORIGIN)
        assert r.status_code == 422, value
    assert file_data(admin)["deployment"]["survey_id"] != place["id"]


def test_the_csv_takes_a_compass_point_or_degrees(admin):
    first_place(admin)
    text = "description,lat,lon,picam_h265,TM_RADAR_SERIAL_PORT_00\nA,,, NE ,45\nB,,,0,\nC,,,,359\n"
    r = admin.post("/api/v1/surveys/import", json={"csv": text}, headers=ORIGIN)
    assert r.status_code == 200 and r.json()["errors"] == []
    assert [row["headings"] for row in r.json()["rows"]] == [
        [heading(CAMERA, 45), heading(RADAR, 45)], [heading(CAMERA, 0)], [heading(RADAR, 359)],
    ]
    text = ("description,lat,lon,picam_h265,TM_RADAR_SERIAL_PORT_00\nA,,,400,\nB,,,,north\nC,,,45.0,\nD,,,-1,\n"
            f"E,,,{'4' * 5000},\n")  # more digits than Python's int() takes from text
    errors = admin.post("/api/v1/surveys/import", json={"csv": text}, headers=ORIGIN).json()["errors"]
    points = "a whole number from 0 to 359, a compass point (n, ne, e, se, s, sw, w, nw), or blank."
    assert errors == [
        {"line": 2, "message": f"The heading for picam_h265 must be {points}"},
        {"line": 3, "message": f"The heading for TM_RADAR_SERIAL_PORT_00 must be {points}"},
        {"line": 4, "message": f"The heading for picam_h265 must be {points}"},
        {"line": 5, "message": f"The heading for picam_h265 must be {points}"},
        {"line": 6, "message": f"The heading for picam_h265 must be {points}"},
    ]


def test_places_state_lists_each_sensors_heading(admin):
    """Each enabled sensor with its heading as Node-RED reads config.yml: its own block's, else the top level's, and an
    old bearing key's centre in a file not yet converted."""
    first_place(admin)
    path = admin.app.state.config_path
    radar = "        TM_RADAR_SERIAL_PORT_00:\n            enabled: true\n"
    path.write_text(path.read_text().replace(radar, radar + "            deployment:\n                heading_deg: 300\n"))
    assert places(admin)["sensors"] == [heading(CAMERA, 0), heading(RADAR, 300)]
    path.write_text(path.read_text().replace("    heading_deg: 0\n", "    bearing: 'sw'\n", 1))
    assert places(admin)["sensors"] == [heading(CAMERA, 225), heading(RADAR, 300)]


def test_no_coordinate_in_any_log_line(admin, caplog, monkeypatch):
    caplog.set_level(logging.DEBUG)
    in_use = first_place(admin)
    place = create(admin, MAIN_ST, headings=[heading(CAMERA, 90)])
    deploy(admin, place["id"])
    admin.post(f"/api/v1/surveys/{place['id']}/location", json={"lat": 45.52252, "lon": -122.6912,
               "reason": "Secret reason"}, headers=ORIGIN)
    row = rows(admin, place["id"])[0]
    admin.post(f"/api/v1/surveys/{place['id']}/deployments/{row['id']}/heading", json={"heading_deg": 270,
               "reason": "Secret reason"}, headers=ORIGIN)
    admin.put("/api/v1/surveys/precision", json={"precision": "2", "round_stored": True}, headers=ORIGIN)
    admin.post("/api/v1/surveys/import", json={"csv": IMPORT_CSV, "dry_run": False}, headers=ORIGIN)
    admin.post("/api/v1/surveys/import", json={"csv": IMPORT_CSV + "Bad,45,52252,,\n", "dry_run": False},
               headers=ORIGIN)
    admin.post("/api/v1/surveys", json={"lat": 91, "lon": -122.0, "headings": []}, headers=ORIGIN)
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
    path.write_text(path.read_text().replace("heading_deg: 0", "heading_deg: 270", 1))
    found = rows(admin, in_use)
    assert len(found) == 4 and sorted(row["heading_deg"] for row in found if row["ended"] is None) == [270, 270]


@pytest.mark.parametrize("value", [-1, 360, 45.5, "45", "ne", True, False, []])
def test_the_fake_refuses_a_heading_node_red_refuses(admin, value):
    """As the flows' validator: a whole number from 0 to 359 (40.0 is 40 in JavaScript), or null."""
    row = rows(admin, first_place(admin))[0]
    nodered = admin.app.state.nodered
    with pytest.raises(NodeRedError) as refused:
        nodered.correct_heading(row["id"], value)
    assert refused.value.code == "bad_request"
    for taken, stored in ((None, None), (359, 359), (40.0, 40), (0, 0)):
        nodered.correct_heading(row["id"], taken)
        found = next(found for found in nodered.rows if found["id"] == row["id"])["heading_deg"]
        assert found == stored and type(found) is type(stored)
    with pytest.raises(NodeRedError):
        nodered.correct_heading("not-an-id", 0)


def test_the_fake_engine_closes_a_removed_sensors_row(admin):
    """As the flows' engine: a sensor config.yml no longer lists ends its deployment; one listed but off keeps it."""
    in_use = first_place(admin)
    before = {(row["sensor_type"], row["sensor_name"]): row for row in rows(admin, in_use)}
    path = admin.app.state.config_path
    camera = "        picam_h265:\n            enabled: true\n            camera_radar: TM_RADAR_SERIAL_PORT_00\n"
    assert camera in path.read_text()
    path.write_text(path.read_text().replace(camera, ""))  # leaves `cameras:` with nothing under it
    admin.app.state.nodered.after_config_write()
    after = {row["id"]: row for row in rows(admin, in_use)}
    assert set(after) == {row["id"] for row in before.values()}  # no new row starts
    assert after[before[CAMERA]["id"]]["ended"] is not None
    assert after[before[RADAR]["id"]]["ended"] is None

    off = "        TM_RADAR_SERIAL_PORT_00:\n            enabled: true\n"
    assert off in path.read_text()
    path.write_text(path.read_text().replace(off, "        TM_RADAR_SERIAL_PORT_00:\n            enabled: false\n"))
    admin.app.state.nodered.after_config_write()
    assert rows(admin, in_use) == list(after.values())


# The exact-locations file


def export(client):
    return client.get("/api/v1/surveys/export")


def test_export_is_admin_only_and_has_no_description(claimed_client, login):
    login(claimed_client, *ADMIN)
    place = create(claimed_client, MAIN_ST, lat=45.52252, lon=-122.69120)
    r = export(claimed_client)
    assert r.status_code == 200
    assert r.headers["content-type"] == "text/csv; charset=utf-8"
    assert r.headers["content-disposition"] == 'attachment; filename="traffic-monitor-places.csv"'
    lines = r.text.splitlines()
    assert lines[0] == "survey_id,lat,lon,status,created_at,updated_at"
    assert len(lines) == 1 + len(places(claimed_client)["surveys"])
    mine = next(line for line in lines if line.startswith(place["id"] + ","))
    assert mine.startswith(f"{place['id']},45.52252,-122.69120,planned,")
    assert len(mine.split(",")) == 6
    assert "Main St" not in r.text and MAIN_ST not in r.text
    assert ("survey.export", str(len(lines) - 1)) in audit_rows(claimed_client)
    assert "45.52252" not in str([detail for _, detail in audit_rows(claimed_client)])

    claimed_client.cookies.clear()
    assert export(claimed_client).status_code == 401
    Users(claimed_client.app.state.state).create(*VIEWER, "viewer")
    login(claimed_client, *VIEWER)
    assert export(claimed_client).status_code == 403


def test_export_lists_the_places_in_the_lists_order(admin):
    create(admin, "First", lat=45.1, lon=-122.2)
    create(admin, "Second", lat=45.3, lon=-122.4)
    listed = [place["id"] for place in places(admin)["surveys"]]
    body = export(admin).text.splitlines()[1:]
    assert [line.split(",")[0] for line in body] == listed


def test_export_writes_an_empty_pair_for_no_location(admin):
    place = create(admin, "Somewhere", lat=None, lon=None)
    line = next(line for line in export(admin).text.splitlines() if line.startswith(place["id"] + ","))
    assert line.startswith(f"{place['id']},,,planned,")


# The database copy with exact locations

COPY = "/api/v1/surveys/database-copy"
COPY_URL = re.compile(r"^/storefiles\?files=tmdb-exact-([0-9a-f]{32})&tm_token=[A-Za-z0-9_-]+$")


def locate_in_use(client) -> str:
    """The place in use, at the example coordinates."""
    in_use = first_place(client)
    r = client.post(f"/api/v1/surveys/{in_use}/location", json={"lat": 45.52252, "lon": -122.6912}, headers=ORIGIN)
    assert r.status_code == 200, r.text
    return in_use


def used_place(client, survey_id, lat=None, lon=None):
    return Places(client.app.state.state).create(survey_id, None, lat, lon, [], "ui", "used", None)


def test_database_copy_is_admin_only(claimed_client, login):
    nodered = claimed_client.app.state.nodered
    assert claimed_client.post(COPY, headers=JSON_HEADERS).status_code == 401
    Users(claimed_client.app.state.state).create(*VIEWER, "viewer")
    login(claimed_client, *VIEWER)
    assert claimed_client.post(COPY, headers=JSON_HEADERS).status_code == 403
    assert nodered.exact_copies == {}
    assert len(claimed_client.app.state.download_grants) == 0


def test_database_copy_sends_the_located_places_and_answers_a_link(admin):
    in_use = locate_in_use(admin)
    used_place(admin, "aaaaaaaa-si")  # used, no location
    r = admin.post(COPY, headers=JSON_HEADERS)
    assert r.status_code == 200, r.text
    assert r.headers["cache-control"] == "no-store"
    body = r.json()
    assert body["places"] == 1
    found = COPY_URL.match(body["url"])
    assert found, body["url"]
    kept = admin.app.state.nodered.exact_copies
    assert kept == {found.group(1): [{"survey_id": in_use, "lat": 45.52252, "lon": -122.6912}]}
    assert len(admin.app.state.download_grants) == 1


def test_database_copy_sends_a_used_place_too(admin):
    in_use = locate_in_use(admin)
    used_place(admin, "bbbbbbbb-si", 45.0, -122.0)
    assert admin.post(COPY, headers=JSON_HEADERS).json()["places"] == 2
    (sent,) = admin.app.state.nodered.exact_copies.values()
    assert {place["survey_id"] for place in sent} == {in_use, "bbbbbbbb-si"}


def test_database_copy_leaves_out_planned_places(admin):
    in_use = locate_in_use(admin)
    create(admin, lat=45.0, lon=-122.0)
    assert admin.post(COPY, headers=JSON_HEADERS).json()["places"] == 1
    (sent,) = admin.app.state.nodered.exact_copies.values()
    assert [place["survey_id"] for place in sent] == [in_use]


def test_database_copy_needs_a_located_place(admin):
    old = first_place(admin)
    unlocated = create(admin, lat=None, lon=None)
    deploy(admin, unlocated["id"])  # in use with no location; the first place is used now
    with sqlite3.connect(admin.app.state.state.path) as con:
        con.execute("UPDATE surveys SET lat = NULL, lon = NULL WHERE id = ?", (old,))
    create(admin, lat=45.0, lon=-122.0)  # located, but planned
    grants = len(admin.app.state.download_grants)
    r = admin.post(COPY, headers=JSON_HEADERS)
    assert r.status_code == 409 and r.json()["error"]["code"] == "no_exact_locations"
    assert admin.app.state.nodered.exact_copies == {}
    assert len(admin.app.state.download_grants) == grants
    assert not [row for row in audit_rows(admin) if row[0] == "survey.database_copy"]


def test_database_copy_makes_no_link_when_node_red_fails(admin, monkeypatch):
    locate_in_use(admin)

    def unreachable(*args):
        raise NodeRedError("unreachable")

    monkeypatch.setattr(admin.app.state.nodered, "keep_exact_copy", unreachable)
    r = admin.post(COPY, headers=JSON_HEADERS)
    assert r.status_code == 502 and r.json()["error"]["code"] == "nodered_error"
    assert "wasn't started" in r.json()["error"]["message"]
    assert len(admin.app.state.download_grants) == 0
    assert not [row for row in audit_rows(admin) if row[0] == "survey.database_copy"]


def test_the_diagnostics_hide_a_database_copy_links_ticket_and_token(admin):
    """nginx's access log holds the link, and the diagnostics quote that log: redact() must know the name the route
    gives the file."""
    locate_in_use(admin)
    url = admin.post(COPY, headers=JSON_HEADERS).json()["url"]
    ticket = COPY_URL.match(url).group(1)
    out = redact(f'10.42.0.23 - - [15/Nov/2026:08:11:15 +0000] "GET {url} HTTP/1.1" 200 394000', [])
    assert ticket not in out and url.rpartition("=")[2] not in out
    assert f'"GET /storefiles?files=tmdb-exact-{REDACTED}&tm_token={REDACTED} HTTP/1.1" 200' in out


def test_database_copy_audits_the_count_only(admin, caplog):
    caplog.set_level(logging.DEBUG)
    locate_in_use(admin)
    r = admin.post(COPY, headers=JSON_HEADERS)
    assert r.status_code == 200
    ticket = COPY_URL.match(r.json()["url"]).group(1)
    token = r.json()["url"].rpartition("=")[2]
    assert ("survey.database_copy", "1") in audit_rows(admin)
    for action, detail in audit_rows(admin):
        for needle in ("45.", "122.", ticket, token):
            assert needle not in (detail or "")
    assert caplog.records
    for record in caplog.records:
        message = record.getMessage()
        for needle in ("45.5", "-122.6", "45.0", "-122.0", ticket, token):
            assert needle not in message


def test_two_database_copies_get_different_tickets(admin):
    locate_in_use(admin)
    first = admin.post(COPY, headers=JSON_HEADERS).json()["url"]
    second = admin.post(COPY, headers=JSON_HEADERS).json()["url"]
    assert COPY_URL.match(first).group(1) != COPY_URL.match(second).group(1)
    assert len(admin.app.state.nodered.exact_copies) == 2
