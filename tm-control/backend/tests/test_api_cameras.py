"""The Cameras page's API: GET /api/v1/cameras.

claimed_client runs in fake mode: config.yml is the seeded copy of fixtures/node_red_config_ok.yml (camera picam_h265
with radar TM_RADAR_SERIAL_PORT_00, both enabled), and the fake Frigate (fake.frigate_answer) has picam_h265 and
oak_ave_tele. A test makes Frigate silent or in safe mode by patching fake.frigate_answer, the seam the router reads.
"""

import pytest

from tm_control import fake
from tm_control.adapters.nodered import NodeRedError
from tm_control.adapters.yamlfile import ConfigRead
from tm_control.core.auth import Users

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
    assert (second["name"], second["frigate_camera"], second["in_frigate"]) == (None, "oak_ave_tele", "on")
    assert second["neutral"] is None and second["enabled"] is None


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
