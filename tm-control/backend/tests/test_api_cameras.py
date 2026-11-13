"""The Cameras page's API: GET /api/v1/cameras.

claimed_client runs in fake mode: config.yml is the seeded copy of fixtures/node_red_config_ok.yml (camera picam_h265
with radar TM_RADAR_SERIAL_PORT_00, both enabled), and the fake Frigate (fake.frigate_answer) has picam_h265 and
oak_ave_tele. A test makes Frigate silent or in safe mode by patching fake.frigate_answer, the seam the router reads.
"""

import importlib
import logging
import sqlite3

import pytest
from ruamel.yaml import YAML

from tm_control import fake
from tm_control.adapters.nodered import NodeRedError
from tm_control.adapters.yamlfile import ConfigRead
from tm_control.core.auth import Users
from tm_control.modules.cameras import names
from tm_control.modules.location import config as location_config
from tm_control.modules.location.places import Bearing, Places

# The module, not the APIRouter the package's __init__ binds to the same name.
cameras_router = importlib.import_module("tm_control.modules.cameras.router")

BASE = "http://tm-test.local"
ORIGIN = {"Origin": BASE}
JSON_HEADERS = {**ORIGIN, "Content-Type": "application/json"}  # the cross-site check wants JSON on every non-GET
NEUTRAL = "camera_1_3fa9c2"
ADMIN = ("admin", "correct horse 1")
VIEWER = ("viewer", "viewer pass 1")
ZONES = ("zone_capture", "zone_near", "zone_far", "zone_radar")


@pytest.fixture
def admin(claimed_client, login):
    login(claimed_client, *ADMIN)
    return claimed_client


def cameras(client) -> dict:
    r = client.get("/api/v1/cameras")
    assert r.status_code == 200, r.text
    return r.json()


def frigate_says(monkeypatch, config):
    monkeypatch.setattr(fake, "frigate_answer", lambda settings: (config, ConfigRead(None, "missing")))


def test_a_viewer_and_a_signed_out_caller_are_refused(claimed_client, login):
    assert claimed_client.get("/api/v1/cameras").status_code == 401
    Users(claimed_client.app.state.state).create(*VIEWER, "viewer")
    login(claimed_client, *VIEWER)
    r = claimed_client.get("/api/v1/cameras")
    assert r.status_code == 403 and r.json()["error"]["message"] == "Only an admin can do this."


def test_get_lists_the_seeded_camera_and_the_fake_frigates_new_one(admin):
    state = cameras(admin)
    assert state["frigate"] == "ok" and state["plates"] is False
    first, second = state["rows"]
    assert (first["name"], first["frigate_camera"], first["in_frigate"]) == ("picam_h265", "picam_h265", "on")
    assert (first["neutral"], first["enabled"], first["camera_radar"]) == (False, True, "TM_RADAR_SERIAL_PORT_00")
    assert first["zones_missing"] == [] and first["duplicate_of"] is None and first["plate_recognizer"] is False
    assert first["detect"] is True and second["detect"] is True
    assert (second["name"], second["frigate_camera"], second["in_frigate"]) == (None, "oak_ave_tele", "on")
    assert second["neutral"] is None and second["enabled"] is None


def test_rows_carry_the_checks_issues(admin):
    """The page marks what the Status page reports: the fake Frigate's oak_ave_tele has no entry (an error), and a
    camera paired with a radar that config.yml turns off gets no speed (a warning)."""
    path = admin.app.state.config_path
    text = path.read_text()
    assert text.count("enabled: true") >= 2
    data = YAML(typ="safe", pure=True).load(text)
    assert data["sensors"]["radars"]["TM_RADAR_SERIAL_PORT_00"]["enabled"] is True
    first, second = cameras(admin)["rows"]
    assert first["issues"] == [] and second["issues"] == [{"level": "error", "code": "not_paired"}]
    # Turn the radar off by hand, as an operator would
    lines = text.splitlines(keepends=True)
    at = next(i for i, line in enumerate(lines) if line.strip() == "TM_RADAR_SERIAL_PORT_00:")
    lines[at + 1] = lines[at + 1].replace("enabled: true", "enabled: false")
    path.write_text("".join(lines))
    first = cameras(admin)["rows"][0]
    assert first["issues"] == [{"level": "warn", "code": "radar"}]


def test_radars_carry_config_and_port_state(admin, monkeypatch):
    nodered = admin.app.state.nodered
    monkeypatch.setattr(nodered, "report", lambda: {"radars": {"TM_RADAR_SERIAL_PORT_00": {"port_open": True},
                                                                "TM_RADAR_SERIAL_PORT_01": {"port_open": False}}})
    radars = cameras(admin)["radars"]
    assert [r["name"] for r in radars] == [f"TM_RADAR_SERIAL_PORT_0{n}" for n in range(4)]
    assert radars[0] == {"name": "TM_RADAR_SERIAL_PORT_00", "in_config": True, "enabled": True, "port_open": True}
    assert radars[1] == {"name": "TM_RADAR_SERIAL_PORT_01", "in_config": False, "enabled": False, "port_open": False}
    assert radars[2]["port_open"] is None


def test_port_state_is_unknown_when_node_red_does_not_answer(admin, monkeypatch):
    def silent():
        raise NodeRedError("unreachable")

    monkeypatch.setattr(admin.app.state.nodered, "report", silent)
    radars = cameras(admin)["radars"]
    assert radars[0]["enabled"] is True and all(r["port_open"] is None for r in radars)


def test_safe_mode_offers_no_actions(admin, monkeypatch):
    frigate_says(monkeypatch, {"safe_mode": True, "cameras": {}})
    state = cameras(admin)
    assert state["frigate"] == "safe_mode"
    [row] = state["rows"]
    assert (row["name"], row["in_frigate"], row["zones_missing"]) == ("picam_h265", "unknown", None)


def test_frigate_down_still_lists_the_files_cameras(admin, monkeypatch):
    frigate_says(monkeypatch, None)
    state = cameras(admin)
    assert state["frigate"] == "down"
    [row] = state["rows"]
    assert (row["name"], row["in_frigate"], row["enabled"]) == ("picam_h265", "unknown", True)


def test_a_camera_frigate_lost_is_absent_not_unknown(admin, monkeypatch):
    frigate_says(monkeypatch, {"cameras": {"oak_ave_tele": {"enabled": True, "zones": {z: {} for z in ZONES}}}})
    first, second = cameras(admin)["rows"]
    assert first["in_frigate"] == "absent" and second["frigate_camera"] == "oak_ave_tele"


def test_plates_follow_the_manifest(admin):
    admin.app.state.manifest.options["plate_recognizer"] = True
    assert cameras(admin)["plates"] is True


def test_an_unreadable_config_is_a_500_config_error(admin):
    admin.app.state.config_path.write_text("sensors: [unclosed\n")
    r = admin.get("/api/v1/cameras")
    assert r.status_code == 500 and r.json()["error"]["code"] == "config_error"


# Writes


@pytest.fixture
def token(monkeypatch):
    """The six hex characters of the neutral names the test draws, in order: 3fa9c2 first."""
    drawn = iter(["3fa9c2", "b07e11", "c44d90", "0a1b2c"])
    monkeypatch.setattr(cameras_router, "new_name", lambda existing: names.new_name(existing, lambda n: next(drawn)))


def file_data(client) -> dict:
    return YAML(typ="safe", pure=True).load(client.app.state.config_path.read_text())


def file_cameras(client) -> dict:
    return file_data(client)["sensors"]["cameras"]


def backups(client) -> list:
    path = client.app.state.config_path
    return sorted(p.name for p in path.parent.glob(f"{path.name}.*.bak"))


def rekey(client, old, new):
    """Rename an entry's key in the seeded file, so the Frigate camera it named has no entry and the entry's own
    camera is gone from Frigate."""
    path = client.app.state.config_path
    text = path.read_text()
    assert f"        {old}:\n" in text
    path.write_text(text.replace(f"        {old}:\n", f"        {new}:\n"))
    client.app.state.nodered.after_config_write()  # the watch node notices a hand edit


def audit_rows(client):
    with sqlite3.connect(client.app.state.state.path) as con:
        return con.execute("SELECT action, detail FROM audit WHERE action LIKE 'camera.%' ORDER BY id").fetchall()


def open_rows(client, name):
    return [r for r in client.app.state.nodered.rows
            if r["sensorType"] == "cameras" and r["sensorName"] == name and r["entryEndDateTime"] is None]


def all_rows(client, name):
    return [r for r in client.app.state.nodered.rows if r["sensorType"] == "cameras" and r["sensorName"] == name]


def add(client, **body):
    body = {"frigate_camera": "oak_ave_tele", "enabled": True, "camera_radar": None, "plate_recognizer": None} | body
    return client.post("/api/v1/cameras", json=body, headers=ORIGIN)


def detection(client, name, enabled):
    return client.put(f"/api/v1/cameras/{name}/frigate-detection", json={"enabled": enabled}, headers=ORIGIN)


def error_code(response) -> str:
    return response.json()["error"]["code"]


def test_add_assigns_a_neutral_name_and_points_it(admin, token):
    r = add(admin, camera_radar="TM_RADAR_SERIAL_PORT_00")
    assert r.status_code == 200, r.text
    assert file_cameras(admin)[NEUTRAL] == {
        "frigate_camera": "oak_ave_tele", "enabled": True, "camera_radar": "TM_RADAR_SERIAL_PORT_00",
    }
    assert list(file_cameras(admin)) == ["picam_h265", NEUTRAL]
    rows = r.json()["rows"]  # the answer is the page's whole new state
    assert [(row["name"], row["frigate_camera"]) for row in rows] == [
        ("picam_h265", "picam_h265"), (NEUTRAL, "oak_ave_tele"),
    ]
    assert rows[1]["neutral"] is True and rows[1]["in_frigate"] == "on"
    assert len(open_rows(admin, NEUTRAL)) == 1  # the fake Node-RED reloaded the file and started a deployment
    assert len(backups(admin)) == 1


def test_add_writes_the_plates_key_only_when_given(admin, token, monkeypatch):
    assert add(admin).status_code == 200
    assert "plate_recognizer" not in file_cameras(admin)[NEUTRAL]
    config = fake.frigate_answer(admin.app.state.settings)[0]
    config["cameras"]["oak_ave_wide"] = dict(config["cameras"]["picam_h265"])
    frigate_says(monkeypatch, config)
    assert add(admin, frigate_camera="oak_ave_wide", plate_recognizer=False).status_code == 200
    assert file_cameras(admin)["camera_2_b07e11"]["plate_recognizer"] is False


def test_add_refuses_a_camera_an_entry_already_points_at(admin):
    before = admin.app.state.config_path.read_text()
    r = add(admin, frigate_camera="picam_h265")
    assert r.status_code == 409 and error_code(r) == "cameras_changed"
    assert r.json()["error"]["message"] == "Frigate's cameras or config.yml changed. Reload the page and try again."
    assert add(admin, frigate_camera="not_a_camera").status_code == 409
    assert admin.app.state.config_path.read_text() == before and backups(admin) == []


def test_add_refuses_a_radar_the_unit_does_not_have(admin):
    r = add(admin, camera_radar="TM_RADAR_SERIAL_PORT_01")  # the unit's, but not under sensors.radars
    assert r.status_code == 422 and r.json()["error"]["detail"] == {"field": "camera_radar"}
    assert add(admin, camera_radar="oak_ave_radar").status_code == 422
    assert backups(admin) == []


def test_put_sets_the_three_settings(admin):
    admin.app.state.manifest.options["plate_recognizer"] = True
    r = admin.put(
        "/api/v1/cameras/picam_h265",
        json={"enabled": False, "camera_radar": "TM_RADAR_SERIAL_PORT_00", "plate_recognizer": True},
        headers=ORIGIN,
    )
    assert r.status_code == 200, r.text
    assert file_cameras(admin)["picam_h265"] == {
        "enabled": False, "camera_radar": "TM_RADAR_SERIAL_PORT_00", "plate_recognizer": True,
    }
    row = r.json()["rows"][0]
    assert (row["enabled"], row["plate_recognizer"]) == (False, True)


def test_put_with_no_radar_removes_the_key(admin):
    r = admin.put("/api/v1/cameras/picam_h265", json={"enabled": True, "camera_radar": None}, headers=ORIGIN)
    assert r.status_code == 200, r.text
    assert file_cameras(admin)["picam_h265"] == {"enabled": True}
    assert r.json()["rows"][0]["camera_radar"] is None


def test_put_refuses_a_radar_the_file_doesnt_have(admin):
    before = admin.app.state.config_path.read_text()
    for radar in ("TM_RADAR_SERIAL_PORT_01", "TM_RADAR_SERIAL_PORT_09", "sensorname01"):
        r = admin.put("/api/v1/cameras/picam_h265", json={"enabled": True, "camera_radar": radar}, headers=ORIGIN)
        assert r.status_code == 422 and error_code(r) == "validation", radar
        assert r.json()["error"]["detail"] == {"field": "camera_radar"}
    assert admin.app.state.config_path.read_text() == before and backups(admin) == []


def test_put_leaves_plates_alone_for_null(admin):
    path = admin.app.state.config_path
    path.write_text(path.read_text().replace("enabled: true\n            camera_radar", "plate_recognizer: true\n"
                                             "            enabled: true\n            camera_radar", 1))
    r = admin.put(
        "/api/v1/cameras/picam_h265",
        json={"enabled": False, "camera_radar": "TM_RADAR_SERIAL_PORT_00", "plate_recognizer": None},
        headers=ORIGIN,
    )
    assert r.status_code == 200, r.text
    assert file_cameras(admin)["picam_h265"]["plate_recognizer"] is True
    assert file_cameras(admin)["picam_h265"]["enabled"] is False


def test_put_works_while_frigate_is_down_and_with_the_same_settings(admin, monkeypatch):
    frigate_says(monkeypatch, None)
    same = {"enabled": True, "camera_radar": "TM_RADAR_SERIAL_PORT_00"}
    r = admin.put("/api/v1/cameras/picam_h265", json=same, headers=ORIGIN)
    assert r.status_code == 200 and r.json()["frigate"] == "down"
    assert backups(admin) == []  # nothing changed, nothing written


def test_put_for_a_camera_not_in_the_file_is_404(admin):
    r = admin.put("/api/v1/cameras/camera_9_aaaaaa", json={"enabled": True}, headers=ORIGIN)
    assert r.status_code == 404 and error_code(r) == "not_found"


def test_point_changes_only_frigate_camera_and_starts_no_deployment(admin):
    rekey(admin, "picam_h265", "main_st")  # main_st's Frigate camera is gone; picam_h265 has no entry
    [before] = open_rows(admin, "main_st")
    r = admin.post("/api/v1/cameras/main_st/frigate-camera", json={"to": "picam_h265"}, headers=ORIGIN)
    assert r.status_code == 200, r.text
    assert file_cameras(admin)["main_st"] == {
        "frigate_camera": "picam_h265", "enabled": True, "camera_radar": "TM_RADAR_SERIAL_PORT_00",
    }
    assert open_rows(admin, "main_st") == [before]  # the same open row, not a new deployment
    assert len(all_rows(admin, "main_st")) == 1
    first = r.json()["rows"][0]
    assert (first["name"], first["frigate_camera"], first["in_frigate"]) == ("main_st", "picam_h265", "on")


def test_point_at_a_camera_another_entry_took_is_refused(admin):
    rekey(admin, "picam_h265", "main_st")
    assert add(admin, frigate_camera="picam_h265").status_code == 200  # another admin took it first
    before = admin.app.state.config_path.read_text()
    backed = backups(admin)
    r = admin.post("/api/v1/cameras/main_st/frigate-camera", json={"to": "picam_h265"}, headers=ORIGIN)
    assert r.status_code == 409 and error_code(r) == "cameras_changed"
    assert admin.app.state.config_path.read_text() == before and backups(admin) == backed


def test_point_is_refused_while_the_entrys_camera_is_still_in_frigate(admin, monkeypatch):
    before = admin.app.state.config_path.read_text()
    r = admin.post("/api/v1/cameras/picam_h265/frigate-camera", json={"to": "oak_ave_tele"}, headers=ORIGIN)
    assert r.status_code == 409 and error_code(r) == "cameras_changed"
    config = fake.frigate_answer(admin.app.state.settings)[0]  # Off is a second camera, not a rename
    config["cameras"]["picam_h265"]["enabled"] = False
    frigate_says(monkeypatch, config)
    r = admin.post("/api/v1/cameras/picam_h265/frigate-camera", json={"to": "oak_ave_tele"}, headers=ORIGIN)
    assert r.status_code == 409 and error_code(r) == "cameras_changed"
    assert admin.app.state.config_path.read_text() == before


def test_point_for_a_camera_not_in_the_file_is_404(admin):
    r = admin.post("/api/v1/cameras/camera_9_aaaaaa/frigate-camera", json={"to": "oak_ave_tele"}, headers=ORIGIN)
    assert r.status_code == 404 and error_code(r) == "not_found"


def test_neutral_name_rekeys_moves_the_bearings_and_starts_a_deployment(admin, token):
    places = Places(admin.app.state.state)
    places.create("00000001-si", "a note", None, None, [Bearing(sensor_type="cameras", sensor_name="picam_h265",
                  bearing="n")], "ui", "planned", None)
    [old_row] = open_rows(admin, "picam_h265")
    r = admin.post("/api/v1/cameras/picam_h265/neutral-name", headers=JSON_HEADERS)
    assert r.status_code == 200, r.text
    assert list(file_cameras(admin)) == [NEUTRAL]
    assert file_cameras(admin)[NEUTRAL] == {
        "frigate_camera": "picam_h265", "enabled": True, "camera_radar": "TM_RADAR_SERIAL_PORT_00",
    }
    assert [b.sensor_name for b in places.get("00000001-si").bearings] == [NEUTRAL]
    assert old_row["entryEndDateTime"] is not None and open_rows(admin, "picam_h265") == []
    assert len(open_rows(admin, NEUTRAL)) == 1
    row = r.json()["rows"][0]
    assert (row["name"], row["frigate_camera"], row["neutral"], row["in_frigate"]) == (
        NEUTRAL, "picam_h265", True, "on")


def test_neutral_name_refuses_a_neutral_name_and_a_missing_camera(admin, token):
    assert admin.post("/api/v1/cameras/picam_h265/neutral-name", headers=JSON_HEADERS).status_code == 200
    before = admin.app.state.config_path.read_text()
    r = admin.post(f"/api/v1/cameras/{NEUTRAL}/neutral-name", headers=JSON_HEADERS)
    assert r.status_code == 409 and error_code(r) == "cameras_changed"
    assert admin.post("/api/v1/cameras/picam_h265/neutral-name", headers=JSON_HEADERS).status_code == 404
    assert admin.app.state.config_path.read_text() == before


def test_remove_only_for_a_gone_or_duplicate_entry(admin):
    r = admin.delete("/api/v1/cameras/picam_h265", headers=JSON_HEADERS)  # its Frigate camera is there
    assert r.status_code == 409 and error_code(r) == "cameras_changed"
    assert "picam_h265" in file_cameras(admin)
    # a duplicate: a second entry naming the same Frigate camera as an earlier one
    path = admin.app.state.config_path
    config = location_config.NodeRedConfig(path)
    config.add_camera("main_st", "picam_h265", True, None, None)
    assert config.save()
    r = admin.delete("/api/v1/cameras/main_st", headers=JSON_HEADERS)
    assert r.status_code == 200, r.text
    assert list(file_cameras(admin)) == ["picam_h265"]
    assert admin.delete("/api/v1/cameras/picam_h265", headers=JSON_HEADERS).status_code == 409  # the first one stays
    # an entry whose Frigate camera is gone
    rekey(admin, "picam_h265", "oak_ave_wide")
    r = admin.delete("/api/v1/cameras/oak_ave_wide", headers=JSON_HEADERS)
    assert r.status_code == 200, r.text
    assert file_data(admin)["sensors"]["cameras"] is None
    assert [row["name"] for row in r.json()["rows"]] == [None, None]  # both of Frigate's cameras have no entry now
    assert admin.delete("/api/v1/cameras/oak_ave_wide", headers=JSON_HEADERS).status_code == 404


def test_remove_is_refused_while_frigate_is_down(admin, monkeypatch):
    frigate_says(monkeypatch, None)
    before = admin.app.state.config_path.read_text()
    r = admin.delete("/api/v1/cameras/picam_h265", headers=JSON_HEADERS)
    assert r.status_code == 409 and error_code(r) == "frigate_unavailable"
    assert r.json()["error"]["message"] == (
        "Frigate isn't answering, so its cameras can't be compared. Try again when it is running.")
    frigate_says(monkeypatch, {"safe_mode": True, "cameras": {}})  # safe mode lists no cameras: not "all gone"
    assert admin.delete("/api/v1/cameras/picam_h265", headers=JSON_HEADERS).status_code == 409
    assert admin.post("/api/v1/cameras/picam_h265/neutral-name", headers=JSON_HEADERS).status_code == 409
    assert add(admin).status_code == 409
    assert admin.post("/api/v1/cameras/picam_h265/frigate-camera", json={"to": "x"}, headers=ORIGIN).status_code == 409
    assert admin.app.state.config_path.read_text() == before and backups(admin) == []


def test_a_changed_file_is_a_409_and_nothing_is_written(admin, monkeypatch):
    real_save = location_config.NodeRedConfig.save

    def edited_first(self):
        path = admin.app.state.config_path
        path.write_text(path.read_text() + "\n# edited by hand\n")
        return real_save(self)

    monkeypatch.setattr(location_config.NodeRedConfig, "save", edited_first)
    r = add(admin)
    assert r.status_code == 409 and error_code(r) == "config_changed"
    r = admin.put("/api/v1/cameras/picam_h265", json={"enabled": False}, headers=ORIGIN)
    assert r.status_code == 409 and error_code(r) == "config_changed"
    monkeypatch.undo()
    assert "frigate_camera" not in admin.app.state.config_path.read_text() and backups(admin) == []
    assert audit_rows(admin) == []


def test_an_entry_shared_through_an_alias_is_a_500_config_error(admin):
    path = admin.app.state.config_path
    text = path.read_text()
    assert "        picam_h265:\n" in text and "    radars:\n" in text
    text = text.replace("        picam_h265:\n", "        picam_h265: &cam\n").replace(
        "    radars:\n", "        main_st: *cam\n\n    radars:\n", 1)
    path.write_text(text)
    r = admin.put("/api/v1/cameras/picam_h265", json={"enabled": False}, headers=ORIGIN)
    assert r.status_code == 500 and error_code(r) == "config_error"
    assert path.read_text() == text and backups(admin) == [] and audit_rows(admin) == []


def test_every_write_is_audited_with_the_key_only(admin, token, monkeypatch):
    assert add(admin).status_code == 200
    assert admin.put("/api/v1/cameras/picam_h265", json={"enabled": False}, headers=ORIGIN).status_code == 200
    assert detection(admin, "picam_h265", False).status_code == 200
    rekey(admin, "picam_h265", "main_st")
    assert admin.post("/api/v1/cameras/main_st/frigate-camera", json={"to": "picam_h265"},
                      headers=ORIGIN).status_code == 200
    assert admin.post("/api/v1/cameras/main_st/neutral-name", headers=JSON_HEADERS).status_code == 200
    config = fake.frigate_answer(admin.app.state.settings)[0]
    del config["cameras"]["oak_ave_tele"]  # the first entry's Frigate camera is gone
    frigate_says(monkeypatch, config)
    assert admin.delete(f"/api/v1/cameras/{NEUTRAL}", headers=JSON_HEADERS).status_code == 200
    assert audit_rows(admin) == [
        ("camera.add", NEUTRAL),
        ("camera.update", "picam_h265"),
        ("camera.detection_off", "picam_h265"),
        ("camera.point", "main_st"),
        ("camera.neutral_name", "camera_2_b07e11"),
        ("camera.remove", NEUTRAL),
    ]


def test_no_frigate_name_in_any_log_line_or_audit_row(admin, caplog, token):
    caplog.set_level(logging.DEBUG)
    assert add(admin).status_code == 200  # oak_ave_tele
    rekey(admin, "picam_h265", "main_st")
    assert admin.post("/api/v1/cameras/main_st/frigate-camera", json={"to": "picam_h265"},
                      headers=ORIGIN).status_code == 200
    assert admin.post("/api/v1/cameras/main_st/neutral-name", headers=JSON_HEADERS).status_code == 200
    assert detection(admin, NEUTRAL, False).status_code == 200
    r = admin.post("/api/v1/cameras/main_st/frigate-camera", json={"to": "oak_ave_tele"}, headers=ORIGIN)
    assert r.status_code == 404 and "oak_ave_tele" not in r.text
    assert add(admin, frigate_camera="oak_ave_tele").status_code == 409
    assert caplog.records
    for record in caplog.records:
        assert "oak_ave_tele" not in record.getMessage() and "picam_h265" not in record.getMessage()
    for action, detail in audit_rows(admin):
        assert "oak_ave_tele" not in detail and "picam_h265" not in detail
    # nor in an error message
    r = add(admin, frigate_camera="oak_ave_tele")
    assert "oak_ave_tele" not in r.text


def test_a_viewer_is_refused_every_write(claimed_client, login):
    Users(claimed_client.app.state.state).create(*VIEWER, "viewer")
    login(claimed_client, *VIEWER)
    before = claimed_client.app.state.config_path.read_text()
    calls = [
        claimed_client.post("/api/v1/cameras", json={"frigate_camera": "oak_ave_tele", "enabled": True},
                            headers=ORIGIN),
        claimed_client.put("/api/v1/cameras/picam_h265", json={"enabled": False}, headers=ORIGIN),
        claimed_client.post("/api/v1/cameras/picam_h265/frigate-camera", json={"to": "oak_ave_tele"}, headers=ORIGIN),
        claimed_client.post("/api/v1/cameras/picam_h265/neutral-name", headers=JSON_HEADERS),
        claimed_client.delete("/api/v1/cameras/picam_h265", headers=JSON_HEADERS),
        claimed_client.put("/api/v1/cameras/picam_h265/frigate-detection", json={"enabled": False}, headers=ORIGIN),
    ]
    assert [r.status_code for r in calls] == [403] * 6
    assert claimed_client.app.state.config_path.read_text() == before


# Frigate's detection switch, and Frigate cameras that are off


def with_camera(monkeypatch, client, name, **fields):
    config = fake.frigate_answer(client.app.state.settings)[0]
    config["cameras"][name] = dict(config["cameras"]["picam_h265"]) | fields
    frigate_says(monkeypatch, config)


def test_a_frigate_camera_that_is_off_and_unpaired_is_not_listed_and_cant_be_added(admin, monkeypatch, token):
    with_camera(monkeypatch, admin, "main_st", enabled=False)
    assert [row["frigate_camera"] for row in cameras(admin)["rows"]] == ["picam_h265", "oak_ave_tele"]
    r = add(admin, frigate_camera="main_st")
    assert r.status_code == 409 and error_code(r) == "cameras_changed"


def test_a_new_camera_with_detection_off_has_no_issue_and_can_be_added(admin, monkeypatch, token):
    with_camera(monkeypatch, admin, "main_st", detect={"enabled": False})
    row = cameras(admin)["rows"][-1]
    assert (row["name"], row["frigate_camera"], row["detect"], row["issues"]) == (None, "main_st", False, [])
    assert add(admin, frigate_camera="main_st").status_code == 200


def test_detection_switches_frigates_live_switch_and_leaves_config_yml_alone(admin):
    before = admin.app.state.config_path.read_text()
    r = detection(admin, "picam_h265", False)
    assert r.status_code == 200, r.text
    assert r.json()["rows"][0]["detect"] is False  # the answer is the page's whole new state
    assert cameras(admin)["rows"][0]["detect"] is False
    assert detection(admin, "picam_h265", True).json()["rows"][0]["detect"] is True
    assert admin.app.state.config_path.read_text() == before and backups(admin) == []
    assert audit_rows(admin) == [("camera.detection_off", "picam_h265"), ("camera.detection_on", "picam_h265")]


def test_detection_asks_frigate_by_its_own_name(admin, monkeypatch, token):
    asked = []
    monkeypatch.setattr(fake, "set_frigate_detect", lambda settings, camera, on: asked.append((camera, on)) or True)
    assert add(admin).status_code == 200
    assert detection(admin, NEUTRAL, False).status_code == 200
    assert asked == [("oak_ave_tele", False)]


def test_detection_needs_frigate(admin, monkeypatch):
    frigate_says(monkeypatch, None)
    r = detection(admin, "picam_h265", False)
    assert r.status_code == 409 and error_code(r) == "frigate_unavailable"


def test_detection_of_a_camera_frigate_lost_is_refused(admin, monkeypatch):
    rekey(admin, "picam_h265", "main_st")
    r = detection(admin, "main_st", False)
    assert r.status_code == 409 and error_code(r) == "cameras_changed"


def test_detection_of_a_camera_that_is_off_in_frigate_is_refused(admin, monkeypatch):
    with_camera(monkeypatch, admin, "picam_h265", enabled=False)
    r = detection(admin, "picam_h265", True)
    assert r.status_code == 409 and error_code(r) == "camera_off"
    assert "picam_h265" not in r.json()["error"]["message"]


def test_a_refusal_from_frigate_is_a_502_and_not_audited(admin, monkeypatch):
    monkeypatch.setattr(fake, "set_frigate_detect", lambda settings, camera, on: False)
    r = detection(admin, "picam_h265", False)
    assert r.status_code == 502 and error_code(r) == "frigate_error"
    assert "picam_h265" not in r.text
    assert audit_rows(admin) == []


def test_detection_of_an_unknown_entry_is_a_404(admin):
    assert detection(admin, "nope", False).status_code == 404
