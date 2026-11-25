"""FakeNodeRed, fake mode's and the API tests' Node-RED: its deployment engine reads how each sensor is mounted from
config.yml and compares it as the flows' "deployment engine" does, and its endpoints for a mounting answer, and refuse,
as the real ones do."""

import time

import pytest

from tm_control.adapters.nodered import NodeRedError
from tm_control.fake import FakeNodeRed
from tm_control.modules.location.config import NodeRedConfig
from tm_control.modules.location.mounting import Mounting

SURVEY = "0000000a-si"
CONFIG = f"""deployment:
    lat: 45.0
    lon: -122.0
    heading_deg: 0
    survey_id: {SURVEY}

sensors:
    cameras:
        cam:
            enabled: true
    radars:
        rad:
            enabled: true
    airquality_monitors:
        air:
            enabled: true
"""


@pytest.fixture
def path(tmp_path):
    target = tmp_path / "config.yml"
    target.write_text(CONFIG)
    return target


@pytest.fixture
def fake(path):
    return FakeNodeRed(path)


def mounting(name="cam", sensor_type="cameras", **values):
    return Mounting(sensor_type=sensor_type, sensor_name=name, **values)


def write(path, fake, *mountings):
    config = NodeRedConfig(path)
    for each in mountings:
        config.set_sensor_mounting(each.sensor_type, each.sensor_name, each)
    assert config.save()
    fake.after_config_write()


def open_rows(fake, name="cam"):
    return [row for row in fake.rows if row["sensorName"] == name and row["entryEndDateTime"] is None]


def closed_rows(fake, name="cam"):
    return [row for row in fake.rows if row["sensorName"] == name and row["entryEndDateTime"] is not None]


FIVE = ("heading_deg", "pitch_deg", "height_m", "view_distance_m", "mount")


def test_rows_carry_the_five(fake):
    row = open_rows(fake)[0]
    assert [row[key] for key in FIVE] == [0, None, None, None, None]


def test_fake_engine_starts_a_deployment_on_a_mounting_change(path, fake):
    first = open_rows(fake)[0]
    radar = open_rows(fake, "rad")[0]
    write(path, fake, mounting(heading_deg=0, pitch_deg=15.0, height_m=3.66, mount="pole"))
    now = open_rows(fake)
    assert len(now) == 1 and now[0]["id"] != first["id"]
    assert [now[0][key] for key in FIVE] == [0, 15.0, 3.66, None, "pole"]
    assert len(closed_rows(fake)) == 1 and closed_rows(fake)[0]["id"] == first["id"]
    assert open_rows(fake, "rad") == [radar]  # a sensor that didn't change keeps its row
    for key, value in (("pitch_deg", 20.0), ("height_m", 4.0), ("view_distance_m", 9.5), ("mount", "tripod")):
        before = open_rows(fake)[0]["id"]
        write(path, fake, mounting(**{**{"heading_deg": 0, "pitch_deg": 15.0, "height_m": 3.66, "mount": "pole"},
                                      key: value}))
        assert open_rows(fake)[0]["id"] != before, key
        write(path, fake, mounting(heading_deg=0, pitch_deg=15.0, height_m=3.66, mount="pole"))


NO_SURVEY = CONFIG.replace(f"    survey_id: {SURVEY}\n", "")


def test_fake_engine_adopts_a_row_from_before_any_survey_when_mounted_the_same(tmp_path):
    bare = tmp_path / "bare.yml"
    bare.write_text(NO_SURVEY)
    fake = FakeNodeRed(bare)
    row = open_rows(fake)[0]
    assert row["survey_id"] is None
    bare.write_text(CONFIG)
    fake.after_config_write()
    assert open_rows(fake)[0] is row and row["survey_id"] == SURVEY  # the same mounting: adopted in place


def test_fake_engine_starts_a_new_deployment_rather_than_adopt_a_row_mounted_another_way(tmp_path):
    bare = tmp_path / "bare.yml"
    bare.write_text(NO_SURVEY)
    fake = FakeNodeRed(bare)
    row = open_rows(fake)[0]
    bare.write_text(CONFIG.replace(
        "cam:\n            enabled: true",
        "cam:\n            enabled: true\n            deployment:\n                heading_deg: 0\n"
        "                height_m: 2.5",
    ))
    fake.after_config_write()
    assert row["entryEndDateTime"] is not None and row["survey_id"] is None
    assert open_rows(fake)[0]["survey_id"] == SURVEY and open_rows(fake)[0]["height_m"] == 2.5


def test_fake_correct_mounting_then_the_file_starts_none(path, fake):
    row = open_rows(fake)[0]
    fake.correct_mounting(row["id"], {
        "heading_deg": 40, "pitch_deg": 15.0, "height_m": 3.66, "view_distance_m": 13.66, "mount": "pole",
    })
    assert [row[key] for key in FIVE] == [40, 15.0, 3.66, 13.66, "pole"]
    count = len(fake.rows)
    write(path, fake, mounting(heading_deg=40, pitch_deg=15.0, height_m=3.66, view_distance_m=13.66, mount="pole"))
    assert len(fake.rows) == count and open_rows(fake)[0] is row  # the file now says what the row says


def test_fake_correct_mounting_clears_and_rounds_like_the_flows(fake):
    row = open_rows(fake)[0]
    fake.correct_mounting(row["id"], {
        "heading_deg": 40.0, "pitch_deg": 15.04, "height_m": 3.666, "view_distance_m": 90.04, "mount": None,
    })
    assert [row[key] for key in FIVE] == [40, 15.0, 3.67, 90.04, None]
    fake.correct_mounting(row["id"], dict.fromkeys(FIVE))
    assert [row[key] for key in FIVE] == [None] * 5


def test_fake_recorded_follows_the_rows_age(fake):
    now = int(time.time() * 1000)
    camera, radar, air = open_rows(fake)[0], open_rows(fake, "rad")[0], open_rows(fake, "air")[0]
    assert FakeNodeRed.RECORDS_AFTER == 30.0
    assert fake.recorded(SURVEY) == {camera["id"]: False, radar["id"]: False, air["id"]: None}
    camera["entryStartDateTime"] = now - 31_000
    radar["entryStartDateTime"] = now - 29_000
    air["entryStartDateTime"] = now - 3_600_000  # an air-quality monitor is never known to have recorded
    assert fake.recorded(SURVEY) == {camera["id"]: True, radar["id"]: False, air["id"]: None}
    camera["entryEndDateTime"] = now  # only open rows are listed
    assert camera["id"] not in fake.recorded(SURVEY)
    assert fake.recorded("ffffffff-si") == {}
    with pytest.raises(NodeRedError) as raised:
        fake.recorded("nope")
    assert raised.value.code == "bad_request"


GOOD = {"heading_deg": 40, "pitch_deg": 15.0, "height_m": 3.66, "view_distance_m": 13.66, "mount": "pole"}


@pytest.mark.parametrize("key, value", [
    ("heading_deg", 360), ("heading_deg", -1), ("heading_deg", 40.5), ("heading_deg", "40"), ("heading_deg", True),
    ("pitch_deg", -0.1), ("pitch_deg", 90.06), ("pitch_deg", "15"), ("pitch_deg", True),
    ("height_m", 0), ("height_m", 0.004), ("height_m", 100.01), ("height_m", "3"), ("height_m", False),
    ("view_distance_m", -1), ("view_distance_m", 1000.01), ("view_distance_m", "12"),
    ("mount", "Pole"), ("mount", " pole"), ("mount", ""), ("mount", "a" * 33), ("mount", 5), ("mount", ["pole"]),
])
def test_fake_correct_mounting_refuses_what_the_flows_refuse(fake, key, value):
    row = open_rows(fake)[0]
    with pytest.raises(NodeRedError) as raised:
        fake.correct_mounting(row["id"], {**GOOD, key: value})
    assert (raised.value.code, raised.value.status) == ("bad_request", 400)
    assert [row[key] for key in FIVE] == [0, None, None, None, None]  # nothing was changed


def test_fake_correct_mounting_refuses_a_missing_key_a_bad_id_and_a_body_that_is_not_a_mapping(fake):
    row = open_rows(fake)[0]
    for body in ({key: value for key, value in GOOD.items() if key != "mount"}, None, [], "x"):
        with pytest.raises(NodeRedError):
            fake.correct_mounting(row["id"], body)
    for deployment_id in ("", "nope", None, 7):
        with pytest.raises(NodeRedError):
            fake.correct_mounting(deployment_id, GOOD)


def test_fake_correct_mounting_accepts_the_limits_themselves(fake):
    row = open_rows(fake)[0]
    for values in (
        {"heading_deg": 0, "pitch_deg": 0, "height_m": 0.01, "view_distance_m": 0, "mount": "a"},
        {"heading_deg": 359, "pitch_deg": 90, "height_m": 100, "view_distance_m": 1000, "mount": "a" * 32},
    ):
        fake.correct_mounting(row["id"], values)
        assert [row[key] for key in FIVE] == list(values.values())


def test_the_report_has_the_database_size(fake):
    report = fake.report()
    assert report["database_bytes"] == FakeNodeRed.DATABASE_BYTES == 734_003_200
    assert list(report)[:3] == ["status", "schema_version", "database_bytes"]
