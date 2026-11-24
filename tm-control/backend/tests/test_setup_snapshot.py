"""What the setup snapshot holds: the facts of the device and of each camera, in the shape Node-RED's validator takes,
and when a snapshot can't be completed."""

import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tm_control.adapters.yamlfile import ConfigRead
from tm_control.core.manifest import load_manifest
from tm_control.modules.detection.inventory import InstallerDefault, inventory
from tm_control.modules.setup_history import snapshot
from tm_control.modules.setup_history.snapshot import (
    CAMERA_FACTS, DEVICE_FACTS, INCOMPLETE, TEXT_MAX, camera_facts, device_facts, flagged, gather,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SIDECAR = json.loads((FIXTURES / "model_sidecar.json").read_text())
PLUS_ID = SIDECAR["id"]
INSTALLER_FILE = "installer_int8_edgetpu.tflite"
EMPTY = (None, [], {})


@pytest.fixture
def manifest():
    return load_manifest(FIXTURES / "manifest.json")


@pytest.fixture
def cache(tmp_path):
    path = tmp_path / "model_cache"
    path.mkdir()
    return path


def pair(cache, file, **changes):
    document = SIDECAR | changes
    (cache / file).write_bytes(file.encode() * 100)
    (cache / f"{file}.json").write_text(json.dumps(document))
    return hashlib.sha256(file.encode() * 100).hexdigest()


def installer():
    return InstallerDefault(section={"path": f"/config/model_cache/{INSTALLER_FILE}"}, file=INSTALLER_FILE,
                            labels_file=None)


def frigate_config(path=None, **model):
    """A Frigate /api/config with one detector, whose model section holds `path` and the other keys."""
    section = ({"path": path} if path else {}) | model
    return {"detectors": {"coral": {"type": "edgetpu", "model": section}}, "cameras": {}}


def facts(manifest, cache, config, installer_=None, version="0.18.1-cf67f08", file=None):
    file = file if file is not None else ConfigRead(None, "missing")
    models = inventory(cache, installer_, "edgetpu")
    return device_facts(manifest, version, config, file, models, installer_)


CAMERA = {
    "name": "oak_ave",
    "friendly_name": "Oak Ave by the school",
    "ffmpeg": {"inputs": [{"path": "rtsp://user:pw@10.0.0.9/stream"}]},
    "detect": {"width": 1536, "height": 864, "fps": 10, "stationary": {"interval": 50, "threshold": 50}},
    "objects": {"track": ["person", "car"]},
}


# the pure functions: a camera

def test_camera_facts_has_exactly_the_listed_keys():
    found = camera_facts({}, None)
    assert tuple(found) == CAMERA_FACTS
    assert all(value in EMPTY for value in found.values())
    assert CAMERA_FACTS == (
        "detect_width", "detect_height", "detect_fps", "stationary_threshold", "stationary_interval", "lens_hfov",
        "labels_tracked", "thresholds", "zones", "masks", "profile",
    )


def test_device_facts_has_exactly_the_listed_keys(manifest):
    found = device_facts(manifest, "", {}, ConfigRead(None, "missing"), [], None)
    assert tuple(found) == DEVICE_FACTS
    assert DEVICE_FACTS == (
        "tm_version", "tm_commit", "frigate_version", "unit_system", "detector", "model_id", "model_file",
        "model_sha256", "model_kind", "model_title", "model_trained_at", "model_base", "model_type", "model_width",
        "model_height", "labels_available",
    )
    assert found["tm_version"] == "0.7.1-test"
    assert found["frigate_version"] is None
    assert found["labels_available"] in EMPTY


def test_camera_facts_reads_detect_and_stationary():
    found = camera_facts(CAMERA, None)
    assert [found[key] for key in CAMERA_FACTS[:5]] == [1536, 864, 10, 50, 50]
    assert found["lens_hfov"] is None


def test_a_whole_number_is_an_integer_and_nothing_else_is_a_number():
    detect = {"width": 1536.0, "height": 864, "fps": 10.0, "stationary": {"interval": 50.5, "threshold": True}}
    found = camera_facts({"detect": detect}, None)
    assert found["detect_fps"] == 10 and isinstance(found["detect_fps"], int)
    assert found["stationary_interval"] is None
    assert found["stationary_threshold"] is None
    text = camera_facts({"detect": {"fps": "10", "stationary": {"interval": float("inf")}}}, None)
    assert text["detect_fps"] is None and text["stationary_interval"] is None


def test_camera_facts_sorts_what_has_no_order():
    zone = {"coordinates": "0.1,0.1,0.9,0.1,0.9,0.9", "distances": ["5.0", "2.0", "3.0"], "objects": ["person", "car"]}
    camera = {"objects": {"track": ["person", "car", "car"]}, "zones": {"zone_b": zone, "zone_a": {}}}
    found = camera_facts(camera, None)
    assert found["labels_tracked"] == ["car", "person"]
    assert [item["key"] for item in found["zones"]] == ["zone_a", "zone_b"]
    assert found["zones"][1]["objects"] == ["car", "person"]
    assert found["zones"][1]["distances"] == [5.0, 2.0, 3.0]
    assert found["zones"][1]["corners"] == [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9]]


def test_camera_facts_zone_shape():
    zone = {
        "enabled": False, "coordinates": "0.542,0.429,0.402,0.383,0.1,0.507,0.207,0.593", "distances": [],
        "inertia": 3, "loitering_time": 0, "speed_threshold": None, "objects": ["car"],
        "filters": {"car": {"min_area": 100, "mask": "0,0,1,1,0,1", "name": "x"}},
        "friendly_name": "Oak Ave", "color": [1, 2, 3],
    }
    [found] = camera_facts({"zones": {"zone_far": zone}}, None)["zones"]
    assert tuple(found) == (
        "key", "enabled", "corners", "distances", "inertia", "loitering_time", "speed_threshold", "objects", "filters",
    )
    assert found == {
        "key": "zone_far", "enabled": False,
        "corners": [[0.542, 0.429], [0.402, 0.383], [0.1, 0.507], [0.207, 0.593]], "distances": [], "inertia": 3,
        "loitering_time": 0, "speed_threshold": None, "objects": ["car"], "filters": {"car": {"min_area": 100.0}},
    }


def test_camera_facts_thresholds_are_the_tracked_labels_filters():
    car = {"min_area": 100, "max_area": 2000.5, "min_ratio": 0.1, "max_ratio": 9, "threshold": 0.7, "min_score": 0.5,
           "mask": {"m": {"coordinates": "0,0,1,0,1,1"}}, "extra": 1}
    camera = {"objects": {"track": ["car"], "filters": {"car": car, "dog": {"min_area": 1}}}}
    found = camera_facts(camera, None)["thresholds"]
    assert found == {"car": {"min_area": 100, "max_area": 2000.5, "min_ratio": 0.1, "max_ratio": 9,
                             "threshold": 0.7, "min_score": 0.5}}
    assert list(found["car"]) == ["min_area", "max_area", "min_ratio", "max_ratio", "threshold", "min_score"]


def test_camera_facts_masks():
    motion = {
        "m1": {"friendly_name": "12 Oak St drive", "enabled": True, "coordinates": "0,0,1,0,1,1"},
        "m2": None,
        "m3": {"enabled": False, "coordinates": "0,0,1,1"},
        "m4": {"enabled": False, "coordinates": "0.5,0.5,0.6,0.5,0.6,0.6"},
    }
    camera = {
        "motion": {"mask": motion},
        "objects": {
            "mask": {"o1": {"coordinates": "0.2,0.2,0.3,0.2,0.3,0.3"}},
            "filters": {"car": {"mask": {"f1": {"enabled": True, "coordinates": "0,0,0.5,0,0.5,0.5"}}},
                        "person": {"mask": {"f2": None}}, "bus": {}},
        },
    }
    found = camera_facts(camera, None)["masks"]
    assert found == {
        "motion": [
            {"enabled": True, "corners": [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0]]},
            {"enabled": False, "corners": [[0.5, 0.5], [0.6, 0.5], [0.6, 0.6]]},
        ],
        "objects": [{"enabled": True, "corners": [[0.2, 0.2], [0.3, 0.2], [0.3, 0.3]]}],
        "object_filters": {"car": [{"enabled": True, "corners": [[0.0, 0.0], [0.5, 0.0], [0.5, 0.5]]}]},
    }
    assert "m1" not in json.dumps(found) and "Oak" not in json.dumps(found)


def test_masks_are_sorted_by_their_corners():
    camera = {"motion": {"mask": {
        "z": {"coordinates": "0.5,0.5,0.6,0.5,0.6,0.6"}, "a": {"coordinates": "0.1,0.1,0.2,0.1,0.2,0.2"},
    }}}
    corners = [mask["corners"][0] for mask in camera_facts(camera, None)["masks"]["motion"]]
    assert corners == [[0.1, 0.1], [0.5, 0.5]]


def test_camera_facts_profile():
    camera = {"profiles": {"night": {}, "day": {}}}
    assert camera_facts(camera, "night")["profile"] == "night"
    assert camera_facts({"profiles": {"day": {}}}, "night")["profile"] is None
    assert camera_facts({}, "night")["profile"] is None
    assert camera_facts(camera, None)["profile"] is None


def test_nothing_typed_as_a_display_name_is_kept():
    camera = CAMERA | {
        "zones": {"zone_far": {"friendly_name": "Oak Ave north", "color": [1, 2, 3],
                               "coordinates": "0.1,0.1,0.9,0.1,0.9,0.9"}},
        "motion": {"mask": {"mask_1": {"friendly_name": "Oak Ave drive", "coordinates": "0,0,1,0,1,1"}}},
    }
    text = json.dumps(camera_facts(camera, None))
    for word in ("Oak", "rtsp", "10.0.0.9", "friendly_name", "color", "oak_ave", "mask_1", "school"):
        assert word not in text


# the pure functions: the device

@pytest.mark.parametrize("case", ["plus", "local", "installer", "frigate_default", "frigate_default_cpu"])
def test_device_facts_for_each_kind_of_model(manifest, cache, case):
    if case == "plus":
        digest = pair(cache, PLUS_ID)
        found = facts(manifest, cache, frigate_config(f"plus://{PLUS_ID}"))
        expected = (PLUS_ID, PLUS_ID, digest, "frigate_plus")
    elif case == "local":
        digest = pair(cache, "mine.tflite", id="not an id!")
        found = facts(manifest, cache, frigate_config("/config/model_cache/mine.tflite"))
        expected = (None, "mine.tflite", digest, "local")
    elif case == "installer":
        (cache / INSTALLER_FILE).write_bytes(b"installer model")
        found = facts(manifest, cache, frigate_config(f"/config/model_cache/{INSTALLER_FILE}"), installer())
        assert found["model_title"] is None and found["model_base"] is None
        assert (found["model_id"], found["model_file"], found["model_kind"]) == (None, INSTALLER_FILE,
                                                                               "installer_default")
        assert found["model_sha256"] == hashlib.sha256(b"installer model").hexdigest()
        return
    elif case == "frigate_default":
        (cache / "yolov6n.hef").write_bytes(b"hef")
        config = {"detectors": {"hailo": {"type": "hailo8l"}}, "cameras": {}}
        models = inventory(cache, None, "hailo8l")
        found = device_facts(manifest, "0.18.1", config, ConfigRead(None, "missing"), models, None)
        assert (found["model_id"], found["model_file"], found["model_kind"]) == (None, "yolov6n.hef", "frigate_default")
        assert found["model_sha256"] == hashlib.sha256(b"hef").hexdigest()
        return
    else:
        config = {"detectors": {"cpu": {"type": "cpu"}}, "cameras": {}}
        found = device_facts(manifest, "0.18.1", config, ConfigRead(None, "missing"), [], None)
        assert found["model_kind"] == "frigate_default"
        for key in ("model_file", "model_sha256", "model_id", "model_title", "model_trained_at", "model_base"):
            assert found[key] is None
        return
    assert (found["model_id"], found["model_file"], found["model_sha256"], found["model_kind"]) == expected
    assert found["model_title"] == SIDECAR["name"]
    assert found["model_trained_at"] == SIDECAR["trainDate"]
    assert found["model_base"] == SIDECAR["baseModel"]
    assert found["detector"] == "edgetpu"
    assert found["labels_available"] == ["bicycle", "car", "person"]


def test_the_model_hash_is_the_files_not_the_sidecars(manifest, cache):
    pair(cache, "mine.tflite")
    found = facts(manifest, cache, frigate_config("/config/model_cache/mine.tflite"))
    sidecar_hash = hashlib.sha256((cache / "mine.tflite.json").read_bytes()).hexdigest()
    assert found["model_sha256"] != sidecar_hash


def test_device_facts_type_and_size_come_from_frigate(manifest, cache):
    config = frigate_config(model_type="yolo-generic", width=512, height=480)
    config["model"] = {"model_type": "ssd", "width": 300, "height": 300}
    found = facts(manifest, cache, config)
    assert (found["model_type"], found["model_width"], found["model_height"]) == ("yolo-generic", 512, 480)
    top = {"detectors": {"cpu": {"type": "cpu"}}, "model": {"model_type": "ssd", "width": 300, "height": 300.0}}
    found = facts(manifest, cache, top)
    assert (found["model_type"], found["model_width"], found["model_height"]) == ("ssd", 300, 300)
    assert isinstance(found["model_height"], int)
    odd = frigate_config(model_type=5, width=True, height="512")
    found = facts(manifest, cache, odd)
    assert (found["model_type"], found["model_width"], found["model_height"]) == (None, None, None)


def test_device_facts_versions_and_unit(manifest, cache):
    pair(cache, "mine.tflite", labelMap={"0": "person", "1": "bicycle", "2": "car", "3": "unknown"})
    config = frigate_config("/config/model_cache/mine.tflite") | {"ui": {"unit_system": "imperial"}}
    found = facts(manifest, cache, config, version="0.18.2-abc")
    assert found["tm_version"] == "0.7.1-test"
    assert found["tm_commit"] == "0" * 40
    assert found["frigate_version"] == "0.18.2-abc"
    assert found["unit_system"] == "imperial"
    assert found["labels_available"] == ["bicycle", "car", "person"]
    for unit in ("metric", "imperial"):
        assert facts(manifest, cache, config | {"ui": {"unit_system": unit}})["unit_system"] == unit
    for odd in ({"unit_system": "furlongs"}, {"unit_system": 3}, "ui", None):
        assert facts(manifest, cache, config | {"ui": odd})["unit_system"] is None


def test_a_long_text_is_left_out(manifest, cache):
    pair(cache, "mine.tflite", name="x" * (TEXT_MAX + 1))
    found = facts(manifest, cache, frigate_config("/config/model_cache/mine.tflite"))
    assert found["model_title"] is None
    pair(cache, "yours.tflite", name="x" * TEXT_MAX)
    found = facts(manifest, cache, frigate_config("/config/model_cache/yours.tflite"))
    assert found["model_title"] == "x" * TEXT_MAX
    assert camera_facts({"profiles": {"p" * 129: {}}}, "p" * 129)["profile"] is None


def test_an_empty_or_odd_text_is_none(manifest, cache):
    pair(cache, "mine.tflite", name="")
    found = facts(manifest, cache, frigate_config("/config/model_cache/mine.tflite", model_type=""))
    assert found["model_title"] is None and found["model_type"] is None


def test_flagged():
    assert flagged({"model_title": "Oak St bikes"}, []) == ("model_title",)
    assert flagged({"model_title": None}, ["1420_oak_st"]) == ("profile",)
    assert flagged({"model_title": "Oak St bikes"}, ["1420_oak_st"]) == ("model_title", "profile")
    assert flagged({"model_title": "yolov9 512"}, ["night", "day"]) == ()
    assert flagged({"model_title": None}, []) == ()
    assert flagged({}, []) == ()


# gather

def write_config(path, entries):
    lines = ["sensors:", "    cameras:"]
    for key, fields in entries.items():
        lines.append(f"        {key}:")
        lines += [f"            {name}: {value}" for name, value in fields.items()] or ["            enabled: false"]
    path.write_text("\n".join(lines) + "\n")


@pytest.fixture
def world(tmp_path, manifest, monkeypatch):
    """A device whose Frigate answers: two Frigate cameras, a model cache, and a config.yml."""
    manifest = manifest.model_copy(update={"codedir": str(tmp_path)})
    cache = tmp_path / "frigate" / "config" / "model_cache"
    cache.mkdir(parents=True)
    pair(cache, PLUS_ID)
    config_path = tmp_path / "config.yml"
    write_config(config_path, {
        "cam_a": {"frigate_camera": "oak_ave", "enabled": "true"},
        "cam_dup": {"frigate_camera": "oak_ave", "enabled": "true"},
        "cam_gone": {"frigate_camera": "not_there", "enabled": "true"},
        "cam_off": {"frigate_camera": "side", "enabled": "false"},
    })
    answers = {
        "version": "0.18.1-cf67f08",
        "config": frigate_config(f"plus://{PLUS_ID}") | {"cameras": {
            "oak_ave": copy.deepcopy(CAMERA) | {"profiles": {"night": {}}},
            "side": {"detect": {"width": 640, "height": 480, "fps": 5}},
            "unpointed": {"detect": {"width": 320, "height": 240, "fps": 5}},
        }},
        "profile": (True, None),
    }
    calls = []

    def answer(name):
        def read(*args):
            calls.append(name)
            return answers[name]
        return read

    monkeypatch.setattr(snapshot.frigate, "version", answer("version"))
    monkeypatch.setattr(snapshot.frigate, "config", answer("config"))
    monkeypatch.setattr(snapshot.frigate, "active_profile", answer("profile"))
    monkeypatch.setattr(snapshot.frigate, "config_file", lambda codedir: ConfigRead(None, "missing"))
    state = SimpleNamespace(settings=SimpleNamespace(fake=False, state_dir=tmp_path / "state"), manifest=manifest,
                            config_path=config_path)
    return SimpleNamespace(state=state, answers=answers, calls=calls, config_path=config_path, tmp=tmp_path)


def test_gather_builds_a_complete_snapshot(world):
    found = gather(world.state)
    assert found.flagged == ()
    body = found.body
    assert body["complete"] is True
    assert tuple(body["device"]) == DEVICE_FACTS
    assert body["device"]["model_id"] == PLUS_ID
    assert all(tuple(camera) == CAMERA_FACTS for camera in body["cameras"].values())
    json.dumps(body, allow_nan=False)


@pytest.mark.parametrize("case", ["no_version", "no_config", "safe_mode", "profile_unknown", "config_yml_unreadable"])
def test_gather_is_incomplete_when_frigate_or_the_config_cant_be_read(world, case):
    if case == "no_version":
        world.answers["version"] = None
    elif case == "no_config":
        world.answers["config"] = None
    elif case == "safe_mode":
        world.answers["config"] = {"safe_mode": True, "detectors": {"cpu": {"type": "cpu"}}, "cameras": {}}
    elif case == "profile_unknown":
        world.answers["profile"] = (False, None)
    else:
        world.config_path.write_text("sensors: [unclosed\n")
    assert gather(world.state) is INCOMPLETE
    assert INCOMPLETE.body == {"complete": False} and INCOMPLETE.flagged == ()


def test_gather_is_incomplete_when_config_yml_is_missing(world):
    world.config_path.unlink()
    assert gather(world.state) == INCOMPLETE


def test_gather_stops_at_the_first_read_that_fails(world):
    world.answers["version"] = None
    gather(world.state)
    assert world.calls == ["version"]


def test_gather_does_not_raise(world, monkeypatch):
    def broken(*args):
        raise RuntimeError("boom")

    monkeypatch.setattr(snapshot.frigate, "version", broken)
    assert gather(world.state) == INCOMPLETE


def test_gather_keys_cameras_by_config_key(world):
    body = gather(world.state).body
    assert set(body["cameras"]) == {"cam_a", "cam_off"}
    assert body["cameras"]["cam_a"]["detect_width"] == 1536
    text = json.dumps(body)
    for name in ("oak_ave", "not_there", "unpointed", "rtsp", "10.0.0.9", "Oak Ave", "friendly_name"):
        assert name not in text


def test_gather_includes_an_entry_that_is_off(world):
    camera = gather(world.state).body["cameras"]["cam_off"]
    assert camera["detect_width"] == 640 and camera["detect_fps"] == 5


def test_gather_gives_a_camera_frigate_lacks_no_row(world):
    world.answers["config"]["cameras"].pop("side")
    assert set(gather(world.state).body["cameras"]) == {"cam_a"}


def test_gather_flags_only_profiles_in_use(world):
    world.answers["profile"] = (True, "1420_oak_st")
    assert gather(world.state).flagged == ()  # no camera defines it: no row holds it
    assert all(camera["profile"] is None for camera in gather(world.state).body["cameras"].values())
    world.answers["config"]["cameras"]["oak_ave"]["profiles"] = {"1420_oak_st": {}}
    found = gather(world.state)
    assert found.flagged == ("profile",)
    assert found.body["cameras"]["cam_a"]["profile"] == "1420_oak_st"
    world.answers["profile"] = (True, "night")
    world.answers["config"]["cameras"]["oak_ave"]["profiles"] = {"night": {}}
    assert gather(world.state).flagged == ()


def test_gather_flags_a_model_title_that_looks_like_an_address(world):
    cache = world.tmp / "frigate" / "config" / "model_cache"
    pair(cache, PLUS_ID, name="1420 Oak St")
    found = gather(world.state)
    assert found.flagged == ("model_title",)
    assert found.body["device"]["model_title"] == "1420 Oak St"


def test_gather_reorders_nothing_a_person_could_reorder(world):
    first = gather(world.state).body
    camera = world.answers["config"]["cameras"]["oak_ave"]
    camera["objects"]["track"].reverse()
    camera["zones"] = {"zone_b": {}, "zone_a": {}}
    again = gather(world.state).body
    assert again["cameras"]["cam_a"]["labels_tracked"] == first["cameras"]["cam_a"]["labels_tracked"]
    assert [zone["key"] for zone in again["cameras"]["cam_a"]["zones"]] == ["zone_a", "zone_b"]


def test_gather_in_fake_mode_reads_the_fake_frigate(settings, monkeypatch):
    from tm_control import fake
    from tm_control.app import create_app

    def refuse(*args, **kwargs):
        raise AssertionError("an adapter was called")

    for name in ("version", "config", "active_profile", "config_file"):
        monkeypatch.setattr(snapshot.frigate, name, refuse)
    app = create_app(settings)
    found = gather(app.state)
    body = found.body
    assert body["complete"] is True
    assert tuple(body["device"]) == DEVICE_FACTS
    assert body["device"]["frigate_version"] == fake.FAKE_FRIGATE_VERSION
    assert body["device"]["tm_version"] == "0.7.1-test"
    assert body["device"]["detector"] == "edgetpu"
    assert body["cameras"], "the fake config.yml's entry is paired with the fake Frigate's camera"
    assert all(camera["profile"] is None for camera in body["cameras"].values())
    assert "Bus lane" not in json.dumps(body)
