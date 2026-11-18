"""A camera's reference pictures: the tickets that hold them in memory, the JPEG size read from their bytes, the file
names, and the data file."""

import json
from pathlib import Path

import pytest

from tests.jpegs import jpeg
from tests.test_cameras_zones import CAMERA
from tm_control.modules.cameras.reference import Reference, References, data_file, jpeg_size, stem
from tm_control.modules.cameras.zones import zone_facts

FIXTURES = Path(__file__).parent / "fixtures"


def reference(**changes) -> Reference:
    """A Reference from made-up values; the clean picture's time is 2026-11-18 18:30:05 UTC."""
    values = dict(
        ticket="made-up-ticket", user_id=1, camera="camera_1_3fa9c2", survey_id="3f9a1c2e-si",
        point=(45.5231, -122.6765), deployment_id="1795026000000-1a2b3c4d-d",
        clean=jpeg(1536, 864), zones_picture=jpeg(1536, 864)[:-2] + b"zones\xff\xd9",
        clean_at=1795026605.0, zones_at=1795026606.0, width=1536, height=864, unit="m",
        zones=[zone_facts(CAMERA)[0]], people="none", tm_version="0.8.0", frigate_version="0.18.2-abc1234",
        expires=1000.0,
    )
    return Reference(**values | changes)


FIELDS = {key: value for key, value in vars(reference()).items() if key not in ("ticket", "expires")}


def test_a_ticket_answers_its_user_until_it_expires():
    store = References()
    kept = store.keep(100.0, **FIELDS)
    assert store.get(kept.ticket, kept.user_id, 100.0 + 599.9) is kept
    assert store.get(kept.ticket, kept.user_id, 100.0 + 600.0) is None
    assert store.get(kept.ticket, kept.user_id + 1, 100.0) is None
    assert store.get("no-such-ticket", kept.user_id, 100.0) is None


def test_a_new_take_drops_the_users_earlier_one_and_the_store_holds_two():
    store = References()
    first = store.keep(0.0, **FIELDS)
    second = store.keep(1.0, **FIELDS)
    assert store.get(first.ticket, first.user_id, 2.0) is None and len(store) == 1
    for user_id in (2, 3):
        store.keep(3.0, **FIELDS | {"user_id": user_id})
    assert len(store) == 2 and store.get(second.ticket, second.user_id, 4.0) is None


def test_an_expired_ticket_is_dropped_by_the_next_take():
    store = References()
    store.keep(0.0, **FIELDS)
    store.keep(700.0, **FIELDS | {"user_id": 2})
    assert len(store) == 1


def test_drop_forgets_only_the_owners_ticket():
    store = References()
    kept = store.keep(0.0, **FIELDS)
    store.drop(kept.ticket, kept.user_id + 1)
    assert len(store) == 1
    store.drop(kept.ticket, kept.user_id)
    assert len(store) == 0


@pytest.mark.parametrize("data, size", [
    (jpeg(1536, 864), (1536, 864)), (jpeg(1, 65535), (1, 65535)),
    (b"", None), (b"\xff\xd8", None), (b"GIF89a" + bytes(20), None), (jpeg(1536, 864)[:24], None),
    (b"\xff\xd8\xff\xe0\x00\x02" * 3, None),
])
def test_jpeg_size(data, size):
    assert jpeg_size(data) == size


@pytest.mark.xfail(strict=True, reason="the two drawn fixtures come with the routes")
def test_jpeg_size_reads_the_two_drawn_fixtures():
    for name in ("reference_clean.jpg", "reference_zones.jpg"):
        assert jpeg_size((FIXTURES / name).read_bytes()) == (1536, 864)


def test_the_stem_names_the_place_the_camera_and_the_time():
    assert stem(reference()) == "tm-reference_3f9a1c2e-si_camera_1_3fa9c2_20261118T183005Z"
    assert stem(reference(survey_id=None)) == "tm-reference_no-place_camera_1_3fa9c2_20261118T183005Z"
    assert stem(reference(camera="../oak ave<1>é")) == "tm-reference_3f9a1c2e-si____oak_ave_1___20261118T183005Z"


def test_the_data_file():
    found = data_file(reference(), with_location=True)
    assert list(found) == ["format", "format_version", "survey_id", "camera", "deployment_id", "location", "pictures",
                           "traffic_monitor_version", "frigate_version", "detect", "distance_unit", "zones"]
    assert (found["format"], found["format_version"]) == ("traffic-monitor-reference", 1)
    assert (found["survey_id"], found["camera"]) == ("3f9a1c2e-si", "camera_1_3fa9c2")
    assert found["deployment_id"] == "1795026000000-1a2b3c4d-d"
    assert found["location"] == {"lat": 45.5231, "lon": -122.6765}
    assert found["pictures"]["clean"] == {
        "file": "tm-reference_3f9a1c2e-si_camera_1_3fa9c2_20261118T183005Z_clean.jpg",
        "taken_at": "2026-11-18T18:30:05Z"}
    assert found["pictures"]["zones"] == {
        "file": "tm-reference_3f9a1c2e-si_camera_1_3fa9c2_20261118T183005Z_zones.jpg",
        "taken_at": "2026-11-18T18:30:06Z"}
    assert found["pictures"]["drawing"] == {"file": "tm-reference_3f9a1c2e-si_camera_1_3fa9c2_20261118T183005Z_zones.svg"}
    assert (found["traffic_monitor_version"], found["frigate_version"]) == ("0.8.0", "0.18.2-abc1234")
    assert found["detect"] == {"width": 1536, "height": 864} and found["distance_unit"] == "m"
    assert found["zones"][0]["sides"][0] == {"start": "A", "end": "B", "length": 12.0}
    json.dumps(found)  # nothing in it that JSON can't hold


def test_unknowns_are_null():
    found = data_file(reference(survey_id=None, deployment_id=None, frigate_version=None), with_location=True)
    assert (found["survey_id"], found["deployment_id"], found["frigate_version"]) == (None, None, None)


def test_the_location_is_left_out_on_request_and_when_there_is_none():
    assert data_file(reference(), with_location=False)["location"] is None
    assert data_file(reference(point=None), with_location=True)["location"] is None
    assert "45.5231" not in json.dumps(data_file(reference(), with_location=False))
