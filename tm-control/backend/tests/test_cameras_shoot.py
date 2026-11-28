"""shoot: one take of a camera's two frames, read from Frigate, shared by the reference picture's dialog and what keeps
pictures on the device. It answers a Shot, or raises NoShot with one of five codes; it logs and audits nothing. The
fake Frigate's frames are the two drawn fixtures."""

import logging
import sqlite3
from pathlib import Path

import pytest

from tests.test_api_cameras import ADMIN, frigate_says
from tm_control import fake
from tm_control.adapters import frigate
from tm_control.modules.cameras.reference import Shot
from tm_control.modules.cameras.shoot import NoShot, shoot
from tm_control.modules.location.places import Places

FIXTURES = Path(__file__).parent / "fixtures"
CLEAN = (FIXTURES / "reference_clean.jpg").read_bytes()
ZONED = (FIXTURES / "reference_zones.jpg").read_bytes()
CAR = {"label": "car", "stationary": True}


@pytest.fixture
def admin(claimed_client, login):
    login(claimed_client, *ADMIN)
    return claimed_client


def count_audit(client) -> int:
    with sqlite3.connect(client.app.state.state.path) as con:
        return con.execute("SELECT COUNT(*) FROM audit").fetchone()[0]


def test_a_shot_holds_what_the_take_held(admin):
    app_state = admin.app.state
    assert admin.get("/api/v1/surveys").status_code == 200  # the claim's first place is made when the page first asks
    place = Places(app_state.state).in_use()
    shot = shoot(app_state, "picam_h265")
    assert type(shot) is Shot
    assert (shot.camera, shot.survey_id, shot.point) == ("picam_h265", place.id, (place.lat, place.lon))
    assert (shot.clean, shot.zones_picture) == (CLEAN, ZONED)
    assert shot.clean_at <= shot.zones_at
    assert (shot.width, shot.height, shot.unit) == (1536, 864, "m")
    assert [zone.key for zone in shot.zones][:4] == ["zone_capture", "zone_far", "zone_near", "zone_radar"]
    assert shot.objects["person"] is False and shot.objects["checked"] is True  # the fake Node-RED lists a car
    assert shot.tm_version == app_state.manifest.tm_version
    assert shot.frigate_version == fake.FAKE_FRIGATE_VERSION
    assert shot.deployment_id is not None


def test_a_shot_without_a_place_has_none(admin, monkeypatch):
    monkeypatch.setattr(Places, "in_use", lambda self: None)
    shot = shoot(admin.app.state, "picam_h265")
    assert (shot.survey_id, shot.point, shot.deployment_id) == (None, None, None)


def refusal(admin, name="picam_h265") -> str:
    with pytest.raises(NoShot) as raised:
        shoot(admin.app.state, name)
    return raised.value.code


def no_cameras(monkeypatch, admin):
    config = fake.frigate_answer(admin.app.state.settings)[0]
    del config["cameras"]["picam_h265"]
    frigate_says(monkeypatch, config)


def camera_off(monkeypatch, admin):
    config = fake.frigate_answer(admin.app.state.settings)[0]
    config["cameras"]["picam_h265"]["enabled"] = False
    frigate_says(monkeypatch, config)


def not_sending(monkeypatch, admin):
    real = fake.frigate_stats(admin.app.state.settings)
    monkeypatch.setattr(fake, "frigate_stats", lambda settings: real | {"cameras": {}})


def old_zones_frame(monkeypatch, admin):
    monkeypatch.setattr(
        fake, "frigate_frame",
        lambda settings, camera, zones: frigate.Frame(ZONED, True) if zones else frigate.Frame(CLEAN, False))


@pytest.mark.parametrize("case, code", [
    (lambda monkeypatch, admin: None, "not_found"),  # the name below has no entry
    (lambda monkeypatch, admin: frigate_says(monkeypatch, None), "unavailable"),
    (no_cameras, "changed"),
    (camera_off, "camera_off"),
    (not_sending, "no_picture"),
    (old_zones_frame, "no_picture"),
])
def test_a_refusal_is_a_code(admin, monkeypatch, case, code):
    case(monkeypatch, admin)
    assert refusal(admin, "no_such_camera" if code == "not_found" else "picam_h265") == code


def test_the_questions_come_before_the_first_frame_and_after_the_second(admin, monkeypatch):
    order = []
    real = fake.frigate_frame

    def frigate_frame(settings, camera, zones):
        order.append("zones" if zones else "clean")
        return real(settings, camera, zones)

    monkeypatch.setattr(fake, "frigate_frame", frigate_frame)
    monkeypatch.setattr(admin.app.state.nodered, "tracked", lambda camera: order.append("ask") or [CAR])
    shoot(admin.app.state, "picam_h265")
    assert order == ["ask", "clean", "zones", "ask"]


def test_shoot_logs_and_audits_nothing(admin, caplog):
    before = count_audit(admin)
    with caplog.at_level(logging.DEBUG):
        shoot(admin.app.state, "picam_h265")
        with pytest.raises(NoShot):
            shoot(admin.app.state, "no_such_camera")
    assert caplog.records == [] and count_audit(admin) == before
