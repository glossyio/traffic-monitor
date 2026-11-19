"""A camera's reference pictures: the tickets that hold them in memory, the JPEG size read from their bytes, the file
names, and the data file."""

import base64
import io
import json
import logging
import zipfile
from pathlib import Path
from xml.etree import ElementTree

import pytest

from tests.jpegs import jpeg
from tests.test_cameras_zones import CAMERA
from tm_control.modules.cameras.reference import (
    HideTickets, Reference, References, caption, data_file, jpeg_size, package, stem,
)
from tm_control.modules.cameras.svg import reference_svg
from tm_control.modules.cameras.zones import ZoneFacts, zone_facts

FIXTURES = Path(__file__).parent / "fixtures"
RADAR_FACTS = zone_facts(CAMERA)[0]


def reference(**changes) -> Reference:
    """A Reference from made-up values; the clean picture's time is 2026-11-18 18:30:05 UTC."""
    values = dict(
        ticket="made-up-ticket", user_id=1, camera="camera_1_3fa9c2", survey_id="3f9a1c2e-si",
        point=(45.5231, -122.6765), deployment_id="1795026000000-1a2b3c4d-d",
        clean=jpeg(1536, 864), zones_picture=jpeg(1536, 864)[:-2] + b"zones\xff\xd9",
        clean_at=1795026605.0, zones_at=1795026606.0, width=1536, height=864, unit="m",
        zones=[zone_facts(CAMERA)[0]], tm_version="0.8.0", frigate_version="0.18.2-abc1234",
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


# The SVG and the zip

NS = {"svg": "http://www.w3.org/2000/svg"}


def drawing(zones, width=1536, height=864):
    return ElementTree.fromstring(reference_svg(jpeg(width, height), width, height, zones, "m", "a caption"))


def test_the_svg_carries_the_clean_frame_and_one_outline_per_drawn_zone():
    off = RADAR_FACTS.model_copy(update={"key": "zone_off", "enabled": False, "drawn": False})
    root = drawing([RADAR_FACTS, off])
    assert root.get("viewBox") == f"0 0 1536 {864 + 62 + 40 * 2 + 44}"
    image = root.find("svg:image", NS)
    assert base64.b64decode(image.get("href").removeprefix("data:image/jpeg;base64,")) == jpeg(1536, 864)
    assert (image.get("width"), image.get("height")) == ("1536", "864")
    [polygon] = root.findall("svg:polygon", NS)
    assert polygon.get("points").split()[0] == "260,422" and polygon.get("stroke") == "#40a05c"
    text = " ".join(node.text or "" for node in root.iter("{http://www.w3.org/2000/svg}text"))
    assert "A–B 12 m, B–C 7.3 m, C–D 12 m, D–A 7.3 m" in " ".join(root.itertext())
    assert "off in Frigate, not drawn" in " ".join(root.itertext()) and "zone_radar" in text


def test_the_svg_names_the_caption_in_its_title_and_strip():
    root = drawing([RADAR_FACTS])
    assert root.find("svg:title", NS).text == "a caption"
    assert any(node.text == "a caption" for node in root.iter("{http://www.w3.org/2000/svg}text"))


def test_zone_names_on_the_picture_are_not_bold():
    """Bold names with their white halo ran together on a real picture; the corner letters stay bold."""
    root = drawing([RADAR_FACTS])
    [name] = [node for node in root.iter("{http://www.w3.org/2000/svg}text") if node.text == "zone_radar"]
    assert name.get("class") == "halo" and name.get("font-weight") is None


def test_the_halo_behind_the_labels_is_thin():
    """A 6 px white halo made the labels chunky on a real picture; 3 px at the base width keeps them readable."""
    assert drawing([RADAR_FACTS]).find("svg:style", NS).text.count("stroke-width: 3px;") == 1
    assert drawing([RADAR_FACTS], 3072, 1728).find("svg:style", NS).text.count("stroke-width: 6px;") == 1


def test_a_key_with_markup_stays_text():
    key = '<script>alert(1)</script>&"\'é'
    root = drawing([RADAR_FACTS.model_copy(update={"key": key})])
    assert root.find(".//svg:script", NS) is None
    assert sum(node.text == key for node in root.iter()) >= 1


def test_a_caption_with_markup_stays_text():
    root = ElementTree.fromstring(reference_svg(jpeg(1536, 864), 1536, 864, [RADAR_FACTS], "m", "<b>&amp;"))
    assert root.find("svg:title", NS).text == "<b>&amp;"


def test_only_zones_with_side_lengths_get_corner_letters():
    plain = RADAR_FACTS.model_copy(update={"key": "zone_capture", "distances": [], "sides": []})
    assert len(drawing([RADAR_FACTS, plain]).findall("svg:circle", NS)) == 4
    assert len(drawing([plain, plain]).findall("svg:circle", NS)) == 8   # none has lengths: every four-cornered zone


def test_names_on_top_of_each_other_step_apart():
    twin = RADAR_FACTS.model_copy(update={"key": "zone_twin"})
    names = [n for n in drawing([RADAR_FACTS, twin]).iter("{http://www.w3.org/2000/svg}text")
             if n.text in ("zone_radar", "zone_twin") and n.get("class") == "halo"]
    assert abs(float(names[0].get("y")) - float(names[1].get("y"))) >= 34


def test_sizes_follow_the_frames_width():
    root = drawing([RADAR_FACTS], width=768, height=432)
    assert root.get("viewBox") == f"0 0 768 {432 + (62 + 40 + 44) // 2}"
    assert root.find("svg:polygon", NS).get("stroke-width") == "2"


def test_the_feet_unit_is_written_after_each_length():
    root = ElementTree.fromstring(reference_svg(jpeg(1536, 864), 1536, 864, [RADAR_FACTS], "ft", "c"))
    assert "A–B 12 ft, B–C 7.3 ft" in " ".join(root.itertext())


def test_a_zone_with_no_colour_or_no_corners_doesnt_break_the_drawing():
    bare = ZoneFacts(key="zone_lane_bus", color=None, enabled=True, drawn=False, corners=[], distances=[], sides=[],
                     inertia=None, loitering_time=None, speed_threshold=None, objects=[], filters={})
    root = drawing([bare, RADAR_FACTS.model_copy(update={"color": None})])
    assert root.find("svg:polygon", NS).get("stroke") == "#888888" and "no outline" in " ".join(root.itertext())


def test_the_caption():
    assert caption(reference()) == (
        "Traffic Monitor reference picture  ·  place 3f9a1c2e-si  ·  camera camera_1_3fa9c2  ·  2026-11-18 18:30:05 UTC")
    assert "place none" in caption(reference(survey_id=None))


def test_the_zip_holds_the_four_files_from_the_same_bytes():
    kept = reference()
    archive = zipfile.ZipFile(io.BytesIO(package(kept, with_location=True)))
    name = "tm-reference_3f9a1c2e-si_camera_1_3fa9c2_20261118T183005Z"
    assert archive.namelist() == [f"{name}_clean.jpg", f"{name}_zones.jpg", f"{name}.json", f"{name}_zones.svg"]
    assert archive.read(f"{name}_clean.jpg") == kept.clean and archive.read(f"{name}_zones.jpg") == kept.zones_picture
    assert json.loads(archive.read(f"{name}.json")) == data_file(kept, with_location=True)
    assert archive.read(f"{name}.json").endswith(b"}\n")
    assert archive.getinfo(f"{name}.json").date_time == (2026, 11, 18, 18, 30, 4)   # a zip's times are in 2 s steps
    assert [info.compress_type for info in archive.infolist()] == [
        zipfile.ZIP_STORED, zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED, zipfile.ZIP_DEFLATED]
    assert all(info.external_attr >> 16 == 0o100644 for info in archive.infolist())
    ElementTree.fromstring(archive.read(f"{name}_zones.svg"))


def test_the_zip_without_the_location_holds_it_nowhere():
    data = package(reference(), with_location=False)
    archive = zipfile.ZipFile(io.BytesIO(data))
    assert all(b"45.5231" not in archive.read(name) for name in archive.namelist())


def access_record(path: str) -> logging.LogRecord:
    """A record as uvicorn's access log makes one: client, method, path with its query, HTTP version, status."""
    return logging.LogRecord(
        "uvicorn.access", logging.INFO, __file__, 0, '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1:50000", "GET", path, "1.1", 200), None,
    )


@pytest.mark.parametrize(("path", "shown"), [
    ("/api/v1/cameras/camera_1_3fa9c2/reference/made-up-ticket/clean.jpg",
     "/api/v1/cameras/camera_1_3fa9c2/reference/-/clean.jpg"),
    ("/api/v1/cameras/camera_1_3fa9c2/reference/made-up-ticket/package?location=true",
     "/api/v1/cameras/camera_1_3fa9c2/reference/-/package?location=true"),
    ("/api/v1/cameras/camera_1_3fa9c2/reference/made-up-ticket", "/api/v1/cameras/camera_1_3fa9c2/reference/-"),
    ("/api/v1/cameras/reference/reference/made-up-ticket/zones.jpg",
     "/api/v1/cameras/reference/reference/-/zones.jpg"),
    ("/api/v1/cameras/camera_1_3fa9c2/reference", "/api/v1/cameras/camera_1_3fa9c2/reference"),
    ("/api/v1/status", "/api/v1/status"),
])
def test_the_access_log_shows_no_ticket(path, shown):
    record = access_record(path)
    assert HideTickets().filter(record) is True
    assert record.getMessage() == f'127.0.0.1:50000 - "GET {shown} HTTP/1.1" 200'
    assert "made-up-ticket" not in record.getMessage()


def test_hiding_tickets_leaves_other_records_alone():
    record = logging.LogRecord("x", logging.INFO, __file__, 0, "plain %s", ("words",), None)
    assert HideTickets().filter(record) is True and record.getMessage() == "plain words"
    bare = logging.LogRecord("x", logging.INFO, __file__, 0, "no arguments", None, None)
    assert HideTickets().filter(bare) is True and bare.getMessage() == "no arguments"
