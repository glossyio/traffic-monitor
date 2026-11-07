"""GET /models: the detector, the model Frigate runs, the model_cache inventory, and the two label lists.

claimed_client is fake mode, whose model_cache is the seeded one under the test's temporary directory; device_client
runs the real code paths, with Frigate not answering and the code directory under tmp_path.
"""

import json
import shutil
from pathlib import Path

import pytest

from tm_control import fake
from tm_control.core.auth import Users

FIXTURES = Path(__file__).resolve().parent / "fixtures"
PLUS_ID = "0123456789abcdef0123456789abcdef"
INSTALLER_FILE = "yolov9-s-relu6-tpumax_512_int8_edgetpu.tflite"
VIEWER = ("viewer", "viewer pass 1")
ADMIN = ("admin", "correct horse 1")
URL = "/api/v1/models"


@pytest.fixture
def seeded(claimed_client, settings):
    fake.seed_model_cache(settings)
    return claimed_client


def models_of(client):
    r = client.get(URL)
    assert r.status_code == 200, r.text
    return r.json()


def test_get_models_is_for_viewers_and_admins_and_not_for_the_signed_out(seeded, login):
    assert seeded.get(URL).status_code == 401
    Users(seeded.app.state.state).create(*VIEWER, "viewer")
    login(seeded, *VIEWER)
    assert seeded.get(URL).status_code == 200
    login(seeded, *ADMIN)
    assert seeded.get(URL).status_code == 200


def test_get_models_lists_the_seeded_pairs_with_running_and_usable(seeded, login):
    login(seeded, *ADMIN)
    state = models_of(seeded)
    assert state["detector"] == "edgetpu" and state["frigate_answers"] is True
    assert state["default"] == "installer_default"
    assert state["running"] == {"name": PLUS_ID, "kind": "frigate_plus", "source": "frigate"}
    models = state["models"]
    assert [model["name"] for model in models] == [INSTALLER_FILE, PLUS_ID, "mine.tflite"]
    default, plus, mine = models
    assert default["kind"] == "installer_default" and default["title"] == INSTALLER_FILE
    assert (default["usable"], default["deletable"], default["running"], default["complete"]) == (
        None, False, False, True)
    assert [file["size"] for file in default["files"]] == [1024]
    assert default["detectors"] == [] and default["type"] is None and default["problem"] is None
    assert plus["kind"] == "frigate_plus" and plus["title"] == "Test site yolov9"
    assert (plus["usable"], plus["running"], plus["deletable"], plus["complete"]) == (True, True, False, True)
    assert plus["detectors"] == ["edgetpu"] and plus["type"] == "yolo-generic"
    assert (plus["width"], plus["height"], plus["trained_at"]) == (320, 320, "2026-10-01T12:00:00Z")
    assert [(file["name"], file["size"]) for file in plus["files"]][0] == (PLUS_ID, 4096)
    assert plus["files"][1]["name"] == f"{PLUS_ID}.json"
    assert all(len(file["sha256"]) == 64 for file in plus["files"])
    assert (mine["kind"], mine["title"], mine["usable"], mine["running"], mine["deletable"]) == (
        "local", "My model", True, False, True)
    assert set(plus) == {
        "name", "kind", "title", "trained_at", "type", "detectors", "width", "height", "files", "complete",
        "running", "usable", "deletable", "problem",
    }
    assert state["labels"]["recognised"] == ["person", "bicycle", "car"]
    assert state["labels"]["source"] == "sidecar"
    assert state["labels"]["tracked"] == ["bicycle", "person", "car", "bus", "motorcycle", "dog"]


def test_get_models_follows_the_running_model_file(seeded, settings, login):
    login(seeded, *ADMIN)
    running = fake.running_model_file(settings)
    running.write_text(INSTALLER_FILE)  # as a use of the installer's default would
    state = models_of(seeded)
    assert state["running"] == {"name": INSTALLER_FILE, "kind": "installer_default", "source": "frigate"}
    assert [model["running"] for model in state["models"]] == [True, False, False]
    assert state["labels"] == {"recognised": None, "source": None, "tracked": state["labels"]["tracked"]}
    running.write_text("")
    state = models_of(seeded)
    assert state["running"] == {"name": None, "kind": "frigate_default", "source": "frigate"}
    assert not any(model["running"] for model in state["models"])
    running.unlink()
    assert models_of(seeded)["running"]["kind"] == "frigate_default"


def test_get_models_never_carries_verified_counts(seeded, login):
    login(seeded, *ADMIN)
    text = seeded.get(URL).text
    assert "verifiedCounts" not in text and "verified_counts" not in text
    assert "front_door_cam" not in text


def test_get_models_without_a_cache_lists_nothing(claimed_client, login):
    login(claimed_client, *ADMIN)
    state = models_of(claimed_client)
    assert state["models"] == [] and state["running"]["kind"] == "frigate_default"


def device_with_codedir(client, tmp_path, config=None, coral=True):
    """device_client with the code directory under tmp_path and Frigate's config.yml there, with the fixture pair in
    the model cache; returns the code directory."""
    codedir = tmp_path / "codedir"
    update = {"codedir": str(codedir)}
    manifest = client.app.state.manifest
    if not coral:
        update["frigate"] = manifest.frigate.model_copy(update={"coral_model": None})
    client.app.state.manifest = manifest.model_copy(update=update)
    frigate = codedir / "frigate" / "config"
    (frigate / "model_cache").mkdir(parents=True)
    if config is not None:
        (frigate / "config.yml").write_text(config)
    shutil.copy(FIXTURES / "model_sidecar.json", frigate / "model_cache" / f"{PLUS_ID}.json")
    (frigate / "model_cache" / PLUS_ID).write_bytes(bytes(4096))
    return codedir


PLUS_CONFIG = f"model:\n  path: plus://{PLUS_ID}\ndetectors:\n  coral:\n    type: edgetpu\n    device: usb\n"


def test_get_models_without_frigate_falls_back_to_the_file(device_client, login, tmp_path):
    device_with_codedir(device_client, tmp_path, PLUS_CONFIG)
    login(device_client, *ADMIN)
    state = models_of(device_client)
    assert state["frigate_answers"] is False
    assert state["detector"] == "edgetpu"
    assert state["running"] == {"name": PLUS_ID, "kind": "frigate_plus", "source": "config_file"}
    assert state["labels"] == {"recognised": ["person", "bicycle", "car"], "source": "sidecar", "tracked": []}
    assert [model["name"] for model in state["models"]] == [PLUS_ID]  # no installer file in the cache
    assert state["models"][0]["running"] is True and state["models"][0]["usable"] is True
    assert state["default"] == "installer_default"


def test_default_is_what_the_default_route_would_apply_here(device_client, login, tmp_path):
    login(device_client, *ADMIN)
    codedir = device_with_codedir(device_client, tmp_path)  # no config.yml yet
    state = models_of(device_client)
    assert (state["detector"], state["default"], state["running"]["kind"]) == (None, None, None)
    assert state["models"][0]["usable"] is None
    config = codedir / "frigate" / "config" / "config.yml"
    config.write_text("detectors:\n  cpu:\n    type: cpu\n")
    state = models_of(device_client)
    assert (state["detector"], state["default"]) == ("cpu", "frigate_default")
    assert state["models"][0]["usable"] is False  # the pair's sidecar supports only edgetpu
    config.write_text("mqtt:\n  enabled: false\n")  # no detectors: Frigate's own CPU detector
    assert (models_of(device_client)["detector"], models_of(device_client)["default"]) == ("cpu", "frigate_default")
    config.write_text("detectors:\n  h:\n    type: hailo8l\n")
    assert models_of(device_client)["default"] == "frigate_default"
    config.write_text(PLUS_CONFIG)
    assert models_of(device_client)["default"] == "installer_default"


def test_default_is_frigates_when_the_manifest_has_no_coral_section(device_client, login, tmp_path):
    device_with_codedir(device_client, tmp_path, PLUS_CONFIG, coral=False)
    login(device_client, *ADMIN)
    state = models_of(device_client)
    assert (state["detector"], state["default"]) == ("edgetpu", "frigate_default")


def test_a_cache_that_cannot_be_opened_lists_nothing(device_client, login, tmp_path):
    codedir = device_with_codedir(device_client, tmp_path, PLUS_CONFIG)
    shutil.rmtree(codedir / "frigate" / "config" / "model_cache")
    login(device_client, *ADMIN)
    state = models_of(device_client)
    assert state["models"] == [] and state["running"]["name"] == PLUS_ID


def test_the_models_answer_is_json_with_no_sidecar_fields_beyond_the_listed(seeded, login):
    login(seeded, *ADMIN)
    document = json.loads(seeded.get(URL).text)
    assert set(document) == {"detector", "frigate_answers", "default", "running", "models", "labels"}
    assert set(document["running"]) == {"name", "kind", "source"}
    assert set(document["labels"]) == {"recognised", "source", "tracked"}


def test_fake_reset_seeds_the_cache_again_and_drops_other_files(settings):
    cache = fake.model_cache(settings)
    cache.mkdir(parents=True)
    (cache / "stale.tflite").write_bytes(b"x")
    assert fake.reset(settings) == 0
    assert sorted(path.name for path in cache.iterdir()) == sorted(
        [INSTALLER_FILE, PLUS_ID, f"{PLUS_ID}.json", "mine.tflite", "mine.tflite.json"])
    assert (cache / INSTALLER_FILE).stat().st_size == 1024
    assert fake.running_model_file(settings).read_text() == PLUS_ID
    assert not fake.running_model_file(settings).is_relative_to(cache)
