"""The Cameras page's reference picture: POST /api/v1/cameras/{name}/reference takes Frigate's current frame twice
(plain and with zone outlines) and holds both in memory under a ticket; GET .../{ticket}/clean.jpg and zones.jpg show
them; GET .../{ticket}/package gives the zip; DELETE drops them.

claimed_client runs in fake mode: the fake Frigate (fake.frigate_answer) has picam_h265 and oak_ave_tele, and its
frames are the two drawn fixtures, reference_clean.jpg and reference_zones.jpg. The claim made the first place from
the seeded config.yml (45.0, -122.0).
"""

import importlib
import io
import json
import logging
import sqlite3
import zipfile
from pathlib import Path

import pytest

from tests.jpegs import jpeg
from tests.test_api_cameras import ADMIN, JSON_HEADERS, NEUTRAL, ORIGIN, VIEWER, add, frigate_says, token  # noqa: F401
from tm_control import fake
from tm_control.adapters import frigate
from tm_control.adapters.nodered import NodeRedError
from tm_control.core.auth import Users
from tm_control.modules.cameras.reference import References
from tm_control.modules.location.places import Places

cameras_router = importlib.import_module("tm_control.modules.cameras.router")

FIXTURES = Path(__file__).parent / "fixtures"
CLEAN = (FIXTURES / "reference_clean.jpg").read_bytes()
ZONED = (FIXTURES / "reference_zones.jpg").read_bytes()
NO_PICTURE = "Frigate has no live picture from this camera right now. Check the camera on the Status page, then try again."
EXPIRED = "These pictures are no longer held on the device. Take them again."


@pytest.fixture
def admin(claimed_client, login):
    login(claimed_client, *ADMIN)
    return claimed_client


def take(client, name="picam_h265"):
    return client.post(f"/api/v1/cameras/{name}/reference", headers=JSON_HEADERS)


def taken(client, name="picam_h265") -> dict:
    r = take(client, name)
    assert r.status_code == 200, r.text
    return r.json()


def base(found, name="picam_h265") -> str:
    return f"/api/v1/cameras/{name}/reference/{found['ticket']}"


def package(client, found, location, name="picam_h265"):
    return client.get(f"{base(found, name)}/package", params={"location": "true" if location else "false"})


def files(response) -> dict[str, bytes]:
    archive = zipfile.ZipFile(io.BytesIO(response.content))
    return {name: archive.read(name) for name in archive.namelist()}


def data(client, found, location) -> dict:
    r = package(client, found, location)
    assert r.status_code == 200, r.text
    return json.loads(files(r)[f"{found['stem']}.json"])


def error(response) -> tuple[int, str, str]:
    body = response.json()["error"]
    return response.status_code, body["code"], body["message"]


def audit_rows(client):
    with sqlite3.connect(client.app.state.state.path) as con:
        return con.execute(
            "SELECT action, detail FROM audit WHERE action LIKE 'camera.reference%' ORDER BY id").fetchall()


def in_use(client) -> dict:
    r = client.get("/api/v1/surveys")
    assert r.status_code == 200, r.text
    state = r.json()
    return next(s for s in state["surveys"] if s["id"] == state["in_use"])


def deploy_new_place(client, lat, lon) -> str:
    r = client.post("/api/v1/surveys", json={"description": "Main St by the bakery", "lat": lat, "lon": lon,
                                             "headings": []}, headers=ORIGIN)
    assert r.status_code == 201, r.text
    survey_id = r.json()["id"]
    r = client.post(f"/api/v1/surveys/{survey_id}/deploy", json={"headings": []}, headers=ORIGIN)
    assert r.status_code == 200, r.text
    return survey_id


def test_a_take_answers_the_legend_and_holds_the_pictures(admin):
    place = in_use(admin)
    found = taken(admin)
    assert (found["camera"], found["survey_id"], found["width"], found["height"]) == (
        "picam_h265", place["id"], 1536, 864)
    assert found["expires_in"] == 600 and found["unit"] == "m"
    assert found["people"] == "none"  # the fake Node-RED lists a car
    assert found["has_location"] is True
    assert found["stem"].startswith(f"tm-reference_{place['id']}_picam_h265_")
    assert [zone["key"] for zone in found["zones"]][:4] == ["zone_capture", "zone_far", "zone_near", "zone_radar"]
    assert found["zones"][0]["color"] == "#7035b0" and found["zones"][4]["drawn"] is False   # zone_lane_bus: {}
    for picture, fixture in (("clean.jpg", CLEAN), ("zones.jpg", ZONED)):
        shown = admin.get(f"{base(found)}/{picture}")
        assert shown.status_code == 200 and shown.content == fixture
        assert shown.headers["content-type"] == "image/jpeg" and shown.headers["cache-control"] == "no-store"


def test_an_unknown_picture_name_is_a_422(admin):
    found = taken(admin)
    assert admin.get(f"{base(found)}/other.jpg").status_code in (404, 422)


def test_the_package_is_the_zip_of_what_was_shown(admin):
    found = taken(admin)
    r = package(admin, found, location=False)
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    assert r.headers["content-disposition"] == f'attachment; filename="{found["stem"]}.zip"'
    assert r.headers["cache-control"] == "no-store"
    archive = files(r)
    assert list(archive) == [f"{found['stem']}_clean.jpg", f"{found['stem']}_zones.jpg", f"{found['stem']}.json",
                             f"{found['stem']}_zones.svg"]
    assert archive[f"{found['stem']}_clean.jpg"] == CLEAN and archive[f"{found['stem']}_zones.jpg"] == ZONED
    written = json.loads(archive[f"{found['stem']}.json"])
    assert written["location"] is None and written["frigate_version"] == fake.FAKE_FRIGATE_VERSION
    assert written["traffic_monitor_version"] == admin.app.state.manifest.tm_version


def test_the_package_needs_the_location_choice(admin):
    found = taken(admin)
    assert admin.get(f"{base(found)}/package").status_code == 422


# The place


def test_the_place_in_use_its_point_and_the_cameras_open_deployment(admin):
    survey_id = deploy_new_place(admin, 45.52252, -122.6912)
    found = taken(admin)
    assert found["survey_id"] == survey_id and found["has_location"] is True
    written = data(admin, found, location=True)
    assert written["location"] == {"lat": 45.52252, "lon": -122.6912}
    open_ids = [row["id"] for row in admin.app.state.nodered.rows
                if (row["sensorType"], row["sensorName"]) == ("cameras", "picam_h265")
                and row["entryEndDateTime"] is None]
    assert written["deployment_id"] in open_ids and written["survey_id"] == survey_id


def test_node_red_not_answering_leaves_out_the_deployment(admin, monkeypatch):
    def silent(survey_id):
        raise NodeRedError("unreachable")

    monkeypatch.setattr(admin.app.state.nodered, "deployments", silent)
    found = taken(admin)
    assert data(admin, found, location=True)["deployment_id"] is None


def test_a_place_with_no_coordinates_has_no_location(admin):
    deploy_new_place(admin, None, None)
    found = taken(admin)
    assert found["has_location"] is False
    assert data(admin, found, location=True)["location"] is None


def test_no_place_in_use(admin, monkeypatch):
    monkeypatch.setattr(Places, "in_use", lambda self: None)
    found = taken(admin)
    assert found["survey_id"] is None and found["has_location"] is False
    assert found["stem"].startswith("tm-reference_no-place_picam_h265_")
    written = data(admin, found, location=True)
    assert (written["survey_id"], written["deployment_id"], written["location"]) == (None, None, None)


# Refusals: nothing kept, nothing audited


def refused(client, expected, name="picam_h265"):
    r = take(client, name)
    assert (r.status_code, r.json()["error"]["code"]) == expected, r.text
    assert len(client.app.state.references) == 0 and audit_rows(client) == []
    return r


def test_an_unknown_entry_is_a_404(admin):
    refused(admin, (404, "not_found"), name="no_such_camera")


@pytest.mark.parametrize("config", [None, {"safe_mode": True, "cameras": {}}])
def test_frigate_silent_or_in_safe_mode(admin, monkeypatch, config):
    frigate_says(monkeypatch, config)
    refused(admin, (409, "frigate_unavailable"))


def test_the_entrys_camera_gone_from_frigate(admin, monkeypatch):
    config = fake.frigate_answer(admin.app.state.settings)[0]
    del config["cameras"]["picam_h265"]
    frigate_says(monkeypatch, config)
    refused(admin, (409, "cameras_changed"))


def test_the_camera_off_in_frigate(admin, monkeypatch):
    config = fake.frigate_answer(admin.app.state.settings)[0]
    config["cameras"]["picam_h265"]["enabled"] = False
    frigate_says(monkeypatch, config)
    r = refused(admin, (409, "camera_off"))
    assert r.json()["error"]["message"] == "This camera is turned off in Frigate. Turn it on in Frigate first."


def test_no_detect_size(admin, monkeypatch):
    config = fake.frigate_answer(admin.app.state.settings)[0]
    del config["cameras"]["picam_h265"]["detect"]["width"]
    frigate_says(monkeypatch, config)
    refused(admin, (409, "no_picture"))


@pytest.mark.parametrize("stats", [
    lambda s: s | {"cameras": {"picam_h265": s["cameras"]["picam_h265"] | {"camera_fps": 0}}},
    lambda s: s | {"cameras": {}},
    lambda s: None,
])
def test_a_camera_that_isnt_sending(admin, monkeypatch, stats):
    real = fake.frigate_stats(admin.app.state.settings)
    monkeypatch.setattr(fake, "frigate_stats", lambda settings: stats(real))
    r = refused(admin, (409, "no_picture"))
    assert r.json()["error"]["message"] == NO_PICTURE


def frames(monkeypatch, clean, zoned):
    monkeypatch.setattr(fake, "frigate_frame", lambda settings, camera, zones: zoned if zones else clean)


@pytest.mark.parametrize("clean, zoned", [
    (None, frigate.Frame(ZONED, False)),                                  # no clean frame
    (frigate.Frame(CLEAN, False), frigate.Frame(ZONED, True)),            # the zones frame is an older one
    (frigate.Frame(jpeg(640, 360), False), frigate.Frame(ZONED, False)),  # Frigate's error picture, as the take sees it
    (frigate.Frame(CLEAN, False), None),
])
def test_a_frame_that_isnt_live_is_refused(admin, monkeypatch, clean, zoned):
    frames(monkeypatch, clean, zoned)
    refused(admin, (409, "no_picture"))


# Frigate's own name for the camera


def test_frigate_is_asked_by_its_own_name_which_no_answer_or_file_holds(admin, monkeypatch, token):
    assert add(admin).status_code == 200  # oak_ave_tele, under NEUTRAL
    asked = []
    real = fake.frigate_frame

    def frigate_frame(settings, camera, zones):
        asked.append(camera)
        return real(settings, camera, zones)

    monkeypatch.setattr(fake, "frigate_frame", frigate_frame)
    r = take(admin, NEUTRAL)
    assert r.status_code == 200, r.text
    assert asked == ["oak_ave_tele", "oak_ave_tele"] and "oak_ave_tele" not in r.text
    found = r.json()
    shown = package(admin, found, location=True, name=NEUTRAL)
    assert shown.status_code == 200
    assert all(b"oak_ave_tele" not in content for content in files(shown).values())


def test_no_zone_display_name_or_place_description_in_any_file(admin):
    deploy_new_place(admin, 45.52252, -122.6912)
    found = taken(admin)
    archive = files(package(admin, found, location=True))
    for content in archive.values():
        assert b"Bus lane (north)" not in content and b"Main St by the bakery" not in content


# Tickets


def test_a_ticket_under_another_name_or_unknown_or_dropped_is_expired(admin, monkeypatch, token):
    found = taken(admin)
    wrong = [
        f"/api/v1/cameras/oak_ave_tele/reference/{found['ticket']}",
        "/api/v1/cameras/picam_h265/reference/made-up-ticket",
    ]
    for prefix in wrong:
        for path in (f"{prefix}/clean.jpg", f"{prefix}/package?location=false"):
            assert error(admin.get(path)) == (404, "reference_expired", EXPIRED)
    assert admin.delete(base(found), headers=JSON_HEADERS).status_code == 204
    assert admin.delete(base(found), headers=JSON_HEADERS).status_code == 204
    assert error(admin.get(f"{base(found)}/zones.jpg"))[1] == "reference_expired"
    assert error(package(admin, found, location=False))[1] == "reference_expired"


def test_pictures_expire(admin, monkeypatch):
    monkeypatch.setattr(References, "TTL", 0.0)
    found = taken(admin)
    assert error(admin.get(f"{base(found)}/clean.jpg"))[1] == "reference_expired"
    assert error(package(admin, found, location=False))[1] == "reference_expired"


def test_a_second_take_drops_the_first(admin):
    first = taken(admin)
    second = taken(admin)
    assert error(admin.get(f"{base(first)}/clean.jpg"))[1] == "reference_expired"
    assert admin.get(f"{base(second)}/clean.jpg").status_code == 200


# Audit and logs


def test_audit_rows_carry_the_key_and_no_log_holds_a_ticket_point_or_frigate_name(admin, caplog, token):
    caplog.set_level(logging.DEBUG)
    deploy_new_place(admin, 45.52252, -122.6912)
    assert add(admin).status_code == 200  # oak_ave_tele, under NEUTRAL
    caplog.clear()
    found = taken(admin, NEUTRAL)
    assert package(admin, found, location=True, name=NEUTRAL).status_code == 200
    assert package(admin, found, location=False, name=NEUTRAL).status_code == 200
    assert admin.get(f"{base(found, NEUTRAL)}/clean.jpg").status_code == 200
    assert admin.delete(base(found, NEUTRAL), headers=JSON_HEADERS).status_code == 204
    assert audit_rows(admin) == [
        ("camera.reference", NEUTRAL),
        ("camera.reference_saved_with_location", NEUTRAL),
        ("camera.reference_saved", NEUTRAL),
    ]
    app_records = [record for record in caplog.records if record.name != "httpx"]  # httpx: the test's own client
    assert app_records
    for record in app_records:
        message = record.getMessage()
        assert found["ticket"] not in message and "oak_ave_tele" not in message
        assert "45.52252" not in message and "122.6912" not in message


def test_a_500_on_the_package_logs_the_route_not_the_ticket(admin, caplog, monkeypatch):
    def broken(held, with_location):
        raise RuntimeError("placeholder-internal-detail")

    monkeypatch.setattr(cameras_router.reference, "package", broken)
    found = taken(admin)
    caplog.set_level(logging.DEBUG, logger="tm_control.core.errors")
    with pytest.raises(RuntimeError):  # the test client re-raises after the handler has logged
        package(admin, found, location=False)
    logged = [record.getMessage() for record in caplog.records if record.name == "tm_control.core.errors"]
    assert logged == ["500 RuntimeError on /cameras/{name}/reference/{ticket}/package"]


def test_the_location_box_without_a_point_is_audited_as_saved(admin):
    deploy_new_place(admin, None, None)
    found = taken(admin)
    assert package(admin, found, location=True).status_code == 200
    assert audit_rows(admin) == [("camera.reference", "picam_h265"), ("camera.reference_saved", "picam_h265")]


# Roles


def test_a_viewer_and_a_signed_out_caller_are_refused(claimed_client, login):
    prefix = "/api/v1/cameras/picam_h265/reference"

    def calls():
        return [
            claimed_client.post(prefix, headers=JSON_HEADERS),
            claimed_client.get(f"{prefix}/made-up-ticket/clean.jpg"),
            claimed_client.get(f"{prefix}/made-up-ticket/package?location=false"),
            claimed_client.delete(f"{prefix}/made-up-ticket", headers=JSON_HEADERS),
        ]

    assert [r.status_code for r in calls()] == [401] * 4
    Users(claimed_client.app.state.state).create(*VIEWER, "viewer")
    login(claimed_client, *VIEWER)
    assert [r.status_code for r in calls()] == [403] * 4
    assert len(claimed_client.app.state.references) == 0


def test_the_writes_need_the_json_content_type(admin):
    assert admin.post("/api/v1/cameras/picam_h265/reference", headers=ORIGIN).status_code == 403
    found = taken(admin)
    assert admin.delete(base(found), headers=ORIGIN).status_code == 403
    assert admin.get(f"{base(found)}/clean.jpg").status_code == 200


def test_a_refused_delete_logs_no_ticket(admin, caplog):
    found = taken(admin)
    caplog.set_level(logging.DEBUG)
    assert admin.delete(base(found)).status_code == 403  # no Origin, no JSON content type
    for record in caplog.records:
        if record.name != "httpx":  # httpx: the test's own client
            assert found["ticket"] not in record.getMessage()
    logged = [record.getMessage() for record in caplog.records if record.name == "tm_control.core.csrf"]
    assert logged == ["403 cross-site check (not JSON or a byte stream) on DELETE"]
    assert admin.get(f"{base(found)}/clean.jpg").status_code == 200


# The pose


def write_pose(client, lines: str):
    """Put mounting keys under the seeded camera's `deployment:` block, as an operator's hand edit would."""
    path = client.app.state.config_path
    text = path.read_text()
    marker = "        picam_h265:\n"
    assert text.count(marker) == 1
    path.write_text(text.replace(marker, marker + lines, 1))
    client.app.state.nodered.after_config_write()


def test_a_reference_takes_the_pose_from_the_file(admin):
    write_pose(admin, "            deployment:\n                heading_deg: 40\n                height_m: 3.66\n"
                      "                pitch_deg: 15\n                mount: pole\n")
    written = data(admin, taken(admin), location=False)
    assert written["pose"] == {"heading_deg": 40, "pitch_deg": 15.0, "height_m": 3.66, "view_distance_m": None,
                               "mount": "pole", "hfov_deg": None}
    zip_files = files(package(admin, taken(admin), location=False))
    svg = next(content for name, content in zip_files.items() if name.endswith(".svg")).decode()
    assert "facing NE (40°)" in svg


def test_a_camera_with_no_mounting_has_a_null_pose_and_no_facing(admin):
    path = admin.app.state.config_path   # the seeded file's top-level block holds a heading; take it out
    text = path.read_text()
    assert text.count("    heading_deg: 0\n") == 1
    path.write_text(text.replace("    heading_deg: 0\n", ""))
    admin.app.state.nodered.after_config_write()
    zip_files = files(package(admin, taken(admin), location=False))
    written = next(json.loads(content) for name, content in zip_files.items() if name.endswith(".json"))
    assert written["pose"] is None and "pose" in written
    svg = next(content for name, content in zip_files.items() if name.endswith(".svg")).decode()
    assert "facing" not in svg


# The people check: what Frigate was tracking, asked of Node-RED by the camera's key

CAR = {"label": "car", "stationary": True}
WALKER = {"label": "person", "stationary": False}


def tracking(admin, monkeypatch, *answers):
    """Make Node-RED answer each question in turn: a list, None, or an error to raise. Returns the keys it was asked."""
    asked, remaining = [], list(answers)

    def tracked(camera):
        asked.append(camera)
        answer = remaining.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(admin.app.state.nodered, "tracked", tracked)
    return asked


def test_a_take_with_nobody_tracked(admin, monkeypatch):
    asked = tracking(admin, monkeypatch, [CAR], [CAR])
    found = taken(admin)
    assert found["people"] == "none" and asked == ["picam_h265", "picam_h265"]
    assert data(admin, found, location=False)["objects"] == {
        "checked": True, "before": [CAR], "after": [CAR], "person": False}


@pytest.mark.parametrize("before, after", [([CAR, WALKER], [CAR]), ([CAR], [WALKER])])
def test_a_person_in_either_list_is_seen(admin, monkeypatch, before, after):
    tracking(admin, monkeypatch, before, after)
    found = taken(admin)
    assert found["people"] == "seen"
    assert data(admin, found, location=False)["objects"] == {
        "checked": True, "before": before, "after": after, "person": True}


def test_no_list_is_unchecked_and_the_second_question_is_not_asked(admin, monkeypatch):
    asked = tracking(admin, monkeypatch, None)
    found = taken(admin)
    assert found["people"] == "unchecked" and len(asked) == 1
    assert data(admin, found, location=False)["objects"] == {
        "checked": False, "before": None, "after": None, "person": None}


@pytest.mark.parametrize("code", ["unreachable", "refused", "unexpected"])
def test_node_red_failing_is_unchecked_and_the_take_still_works(admin, monkeypatch, code):
    tracking(admin, monkeypatch, NodeRedError(code))
    r = take(admin)
    assert r.status_code == 200, r.text
    found = r.json()
    assert found["people"] == "unchecked"
    assert admin.get(f"{base(found)}/clean.jpg").content == CLEAN
    assert admin.get(f"{base(found)}/zones.jpg").content == ZONED


def test_the_second_question_failing(admin, monkeypatch):
    tracking(admin, monkeypatch, [CAR], NodeRedError("unreachable"))
    found = taken(admin)
    assert found["people"] == "unchecked"
    assert data(admin, found, location=False)["objects"] == {
        "checked": False, "before": [CAR], "after": None, "person": None}
    tracking(admin, monkeypatch, [WALKER], NodeRedError("unreachable"))
    found = taken(admin)
    assert found["people"] == "seen"
    assert data(admin, found, location=False)["objects"]["person"] is True


def test_the_questions_come_before_the_first_frame_and_after_the_second(admin, monkeypatch):
    order = []
    real = fake.frigate_frame

    def frigate_frame(settings, camera, zones):
        order.append("zones" if zones else "clean")
        return real(settings, camera, zones)

    monkeypatch.setattr(fake, "frigate_frame", frigate_frame)
    nodered = admin.app.state.nodered
    monkeypatch.setattr(nodered, "tracked", lambda camera: order.append("ask") or [CAR])
    taken(admin)
    assert order == ["ask", "clean", "zones", "ask"]


def test_node_red_is_asked_by_the_key(admin, monkeypatch, token):
    assert add(admin).status_code == 200  # oak_ave_tele, under NEUTRAL
    asked = tracking(admin, monkeypatch, [CAR], [CAR])
    assert taken(admin, NEUTRAL)["people"] == "none"
    assert asked == [NEUTRAL, NEUTRAL]


def test_a_refused_take_asks_nothing(admin, monkeypatch):
    asked = tracking(admin, monkeypatch)
    real = fake.frigate_stats(admin.app.state.settings)
    monkeypatch.setattr(fake, "frigate_stats", lambda settings: real | {"cameras": {}})
    refused(admin, (409, "no_picture"))
    assert asked == []


def test_a_cameras_detection_switched_off_is_unchecked(admin):
    assert fake.set_frigate_detect(admin.app.state.settings, "picam_h265", False)
    assert taken(admin)["people"] == "unchecked"
    assert fake.set_frigate_detect(admin.app.state.settings, "picam_h265", True)
    assert taken(admin)["people"] == "none"


def test_no_object_reaches_a_log_line_or_an_audit_row(admin, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    zebra = {"label": "zebra", "stationary": False}
    admin.app.state.nodered.tracked_objects = [zebra]
    caplog.clear()
    found = taken(admin)
    assert package(admin, found, location=False).status_code == 200
    assert found["people"] == "none"
    for record in caplog.records:
        assert "zebra" not in record.getMessage() and "zebra" not in str(record.args)
    assert audit_rows(admin) == [("camera.reference", "picam_h265"), ("camera.reference_saved", "picam_h265")]
