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


# Uploads, the bare-file form's sidecar, and Delete. Every write test also checks that no temporary name is left.

ORIGIN = "http://tm-test.local"
WRITE_HEADERS = {"Origin": ORIGIN, "Content-Type": "application/json"}
FORM = {
    "model_type": "yolo-generic", "width": 320, "height": 320, "input_tensor": "nhwc", "input_pixel_format": "rgb",
    "labels": ["car", "truck"],
}


def put(client, name, data, content_type="application/octet-stream", headers=None):
    headers = {"Content-Type": content_type, "Origin": ORIGIN, **(headers or {})}
    return client.put(f"{URL}/upload/{name}", content=data, headers=headers)


def post_sidecar(client, name, form=FORM):
    return client.post(f"{URL}/{name}/sidecar", json=form, headers=WRITE_HEADERS)


def delete(client, name):
    return client.delete(f"{URL}/{name}", headers=WRITE_HEADERS)


def cache_names(settings) -> list[str]:
    return sorted(path.name for path in fake.model_cache(settings).iterdir())


def sidecar_bytes(**changes) -> bytes:
    record = json.loads((FIXTURES / "model_sidecar.json").read_text())
    record.pop("id")
    record.pop("verifiedCounts")
    return json.dumps(record | changes).encode()


def message(r) -> str:
    return r.json()["error"]["message"]


SEEDED = sorted([INSTALLER_FILE, PLUS_ID, f"{PLUS_ID}.json", "mine.tflite", "mine.tflite.json"])


def test_upload_a_sidecar_then_its_model_completes_the_pair(seeded, settings, login):
    login(seeded, *ADMIN)
    r = put(seeded, "new.tflite.json", sidecar_bytes(name="New one"))
    assert r.status_code == 201, r.text
    first = r.json()
    assert (first["name"], first["kind"], first["title"], first["complete"]) == (
        "new.tflite", "local", "New one", False)
    assert [file["name"] for file in first["files"]] == ["new.tflite.json"]
    r = put(seeded, "new.tflite", b"\x01" * 100)
    assert r.status_code == 201, r.text
    second = r.json()
    assert (second["name"], second["kind"], second["complete"], second["usable"]) == (
        "new.tflite", "local", True, True)
    assert [(file["name"], file["size"]) for file in second["files"]][0] == ("new.tflite", 100)
    assert "new.tflite" in [model["name"] for model in models_of(seeded)["models"]]
    assert cache_names(settings) == sorted(SEEDED + ["new.tflite", "new.tflite.json"])
    assert (fake.model_cache(settings) / "new.tflite").read_bytes() == b"\x01" * 100


def test_upload_a_bare_model_then_the_form_writes_a_sidecar(seeded, settings, login):
    login(seeded, *ADMIN)
    r = put(seeded, "bare.tflite", b"\x02" * 64)
    assert r.status_code == 201, r.text
    assert (r.json()["complete"], r.json()["usable"]) == (False, None)
    assert post_sidecar(seeded, "bare.tflite", FORM | {"width": 0}).status_code == 422
    assert post_sidecar(seeded, "bare.tflite", FORM | {"labels": []}).status_code == 422
    assert post_sidecar(seeded, "bare.tflite", FORM | {"labels": ["x" * 65]}).status_code == 422
    assert post_sidecar(seeded, "bare.tflite", FORM | {"model_type": ""}).status_code == 422
    assert cache_names(settings) == sorted(SEEDED + ["bare.tflite"])
    r = post_sidecar(seeded, "bare.tflite", FORM | {"input_dtype": "int"})
    assert r.status_code == 201, r.text
    model = r.json()
    assert (model["complete"], model["usable"], model["kind"], model["detectors"]) == (True, True, "local", ["edgetpu"])
    assert (model["title"], model["width"], model["type"]) == ("bare.tflite", 320, "yolo-generic")
    written = json.loads((fake.model_cache(settings) / "bare.tflite.json").read_text())
    assert written == {
        "name": "bare.tflite", "type": "yolo-generic", "supportedDetectors": ["edgetpu"], "width": 320, "height": 320,
        "inputShape": "nhwc", "pixelFormat": "rgb", "inputDataType": "int", "labelMap": {"0": "car", "1": "truck"},
    }
    r = post_sidecar(seeded, "bare.tflite")
    assert (r.status_code, message(r)) == (409, "The model already has a sidecar.")
    assert post_sidecar(seeded, "missing.tflite").status_code == 404
    assert post_sidecar(seeded, "%2E%2E").status_code == 422
    r = post_sidecar(seeded, INSTALLER_FILE)  # it has no sidecar, and the inventory would never read one
    assert (r.status_code, message(r)) == (409, "That's the installer's model.")
    put(seeded, "plain.tflite", b"\x03")
    post_sidecar(seeded, "plain.tflite")
    assert "inputDataType" not in json.loads((fake.model_cache(settings) / "plain.tflite.json").read_text())
    assert cache_names(settings) == sorted(SEEDED + ["bare.tflite", "bare.tflite.json", "plain.tflite",
                                                     "plain.tflite.json"])


def test_uploads_refuse_bad_names_existing_names_oversize_and_json_bodies(seeded, settings, login, monkeypatch):
    login(seeded, *ADMIN)
    for name in ("..%2Fx", "%2E%2E", "a%2Fb", ".hidden", ".json", "a.json.json", "-x", "x" * 129):
        r = put(seeded, name, b"abc")
        assert (r.status_code, message(r)) == (422, "That name isn't allowed."), name
    assert put(seeded, "../x", b"abc").status_code in (404, 405)  # httpx sends /api/v1/models/x: no such route
    for name in ("mine.tflite", "mine.tflite.json", PLUS_ID, f"{PLUS_ID}.json", INSTALLER_FILE):
        r = put(seeded, name, b"abc")
        base = name.removesuffix(".json")
        assert (r.status_code, message(r)) == (409, f"A model named {base} is already on the device; delete it first.")
    r = put(seeded, f"{INSTALLER_FILE}.json", sidecar_bytes())
    assert (r.status_code, message(r)) == (422, "That name isn't allowed.")
    r = put(seeded, "big.tflite", b"abc", headers={"Content-Length": str(101 * 1024 * 1024)})
    assert (r.status_code, message(r)) == (413, "The file is larger than 100 MB.")
    r = put(seeded, "big.zip", b"PK\x03\x04", headers={"Content-Length": str(101 * 1024 * 1024)})
    assert r.status_code == 413
    r = put(seeded, "big.tflite.json", b"{}", headers={"Content-Length": str(3 * 1024 * 1024)})
    assert (r.status_code, message(r)) == (413, "The sidecar is larger than 2 MB.")
    r = put(seeded, "chunked.tflite.json", iter([b" " * (2 * 1024 * 1024), b"{}"]))  # no Content-Length
    assert (r.status_code, message(r)) == (413, "The sidecar is larger than 2 MB.")
    r = put(seeded, "short.tflite", b"abc", headers={"Content-Length": "10"})
    assert (r.status_code, message(r)) == (400, "The body ended before Content-Length.")
    r = put(seeded, "empty.tflite", b"")
    assert (r.status_code, message(r)) == (422, "The file is empty.")
    r = put(seeded, "text.tflite", b"abc", content_type="text/plain")
    assert r.status_code == 403
    r = put(seeded, "m.zip", b"PK\x03\x04rest")
    assert (r.status_code, message(r)) == (422, "Archives aren't accepted yet")
    r = put(seeded, "m.zip", b"\x1f\x8brest")
    assert (r.status_code, message(r)) == (422, "The file isn't a zip archive.")
    r = put(seeded, "m.tgz", b"PK\x03\x04rest")
    assert (r.status_code, message(r)) == (422, "The file isn't a tar.gz archive.")
    r = put(seeded, "m.tar.gz", b"\x1f")
    assert (r.status_code, message(r)) == (422, "The file isn't a tar.gz archive.")
    monkeypatch.setattr("os.statvfs", lambda path: type("S", (), {"f_frsize": 4096, "f_bavail": 1000})())
    r = put(seeded, "full.tflite", b"abc")
    assert (r.status_code, message(r)) == (507, "The device would have less than 512 MB free.")
    assert cache_names(settings) == SEEDED  # no temporary name left behind, and nothing placed


def test_a_disconnect_mid_body_leaves_nothing(seeded, settings, login):
    """Driven as ASGI, since TestClient can't drop a connection: a part of the body, then http.disconnect."""
    import asyncio

    cookie = login(seeded, *ADMIN)
    path = f"{URL}/upload/gone.tflite"
    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "PUT", "scheme": "http",
        "path": path, "raw_path": path.encode(), "root_path": "", "query_string": b"",
        "server": ("tm-test.local", 80), "client": ("127.0.0.1", 50000),
        "headers": [
            (b"host", b"tm-test.local"), (b"origin", ORIGIN.encode()), (b"content-type", b"application/octet-stream"),
            (b"content-length", b"10"), (b"cookie", f"tm_session={cookie}".encode()),
        ],
    }
    messages = [{"type": "http.request", "body": b"abc", "more_body": True}, {"type": "http.disconnect"}]
    sent = []

    async def receive():
        return messages.pop(0) if messages else {"type": "http.disconnect"}

    async def send(event):
        sent.append(event)

    asyncio.run(seeded.app(scope, receive, send))
    assert sent[0]["status"] == 400
    assert cache_names(settings) == SEEDED


def test_a_sidecar_that_does_not_parse_is_refused_and_removed(seeded, settings, login):
    login(seeded, *ADMIN)
    r = put(seeded, "bad.tflite.json", b"not json")
    assert (r.status_code, message(r)) == (422, "The sidecar isn't a JSON object.")
    record = json.loads(sidecar_bytes())
    record.pop("labelMap")
    r = put(seeded, "bad.tflite.json", json.dumps(record).encode())
    assert (r.status_code, message(r)) == (422, "The sidecar lacks labelMap.")
    assert cache_names(settings) == SEEDED


def test_viewers_cannot_upload_or_delete(seeded, settings, login):
    assert put(seeded, "x.tflite", b"abc").status_code == 401
    assert delete(seeded, "mine.tflite").status_code == 401
    Users(seeded.app.state.state).create(*VIEWER, "viewer")
    login(seeded, *VIEWER)
    assert put(seeded, "x.tflite", b"abc").status_code == 403
    assert put(seeded, "x.tflite.json", sidecar_bytes()).status_code == 403
    assert post_sidecar(seeded, "mine.tflite").status_code == 403
    assert delete(seeded, "mine.tflite").status_code == 403
    assert cache_names(settings) == SEEDED


def test_delete_removes_both_files_and_refuses_the_running_and_installers(seeded, settings, login):
    login(seeded, *ADMIN)
    assert delete(seeded, "mine.tflite").status_code == 204
    assert "mine.tflite" not in [model["name"] for model in models_of(seeded)["models"]]
    assert cache_names(settings) == sorted([INSTALLER_FILE, PLUS_ID, f"{PLUS_ID}.json"])
    r = delete(seeded, "mine.tflite")
    assert (r.status_code, message(r)) == (404, "There is no such model.")
    r = delete(seeded, PLUS_ID)
    assert (r.status_code, message(r)) == (409, "That model is running; use another model first.")
    r = delete(seeded, INSTALLER_FILE)
    assert (r.status_code, message(r)) == (409, "That's the installer's model.")
    assert delete(seeded, "%2E%2E").status_code == 422
    assert delete(seeded, "mine.tflite.json").status_code == 422  # a model is deleted by its name, not a half's
    put(seeded, "half.tflite.json", sidecar_bytes())
    assert delete(seeded, "half.tflite").status_code == 204  # a sidecar alone is deleted too
    cache = fake.model_cache(settings)
    (cache / "dir.tflite").mkdir()
    (cache / "link.tflite").symlink_to(cache / PLUS_ID)
    assert delete(seeded, "dir.tflite").status_code == 404  # only regular files are a model's
    assert delete(seeded, "link.tflite").status_code == 404
    assert (cache / "dir.tflite").is_dir() and (cache / PLUS_ID).exists()
    fake.running_model_file(settings).write_text("")  # Frigate's own default runs
    assert delete(seeded, PLUS_ID).status_code == 204
    assert sorted(path.name for path in cache.iterdir()) == sorted([INSTALLER_FILE, "dir.tflite", "link.tflite"])


def test_the_running_model_cannot_be_deleted_even_when_frigate_is_down(device_client, login, tmp_path):
    codedir = device_with_codedir(device_client, tmp_path, PLUS_CONFIG)  # config.yml names plus://<id>
    login(device_client, *ADMIN)
    r = delete(device_client, PLUS_ID)
    assert (r.status_code, message(r)) == (409, "That model is running; use another model first.")
    cache = codedir / "frigate" / "config" / "model_cache"
    assert sorted(path.name for path in cache.iterdir()) == [PLUS_ID, f"{PLUS_ID}.json"]
    (codedir / "frigate" / "config" / "config.yml").write_text("model: [broken\n")  # nobody can say what runs
    r = delete(device_client, PLUS_ID)
    assert (r.status_code, message(r)) == (409, "What Frigate runs can't be told now; try again when Frigate answers.")
    (codedir / "frigate" / "config" / "config.yml").write_text("detectors:\n  cpu:\n    type: cpu\n")
    assert delete(device_client, PLUS_ID).status_code == 204
    assert list(cache.iterdir()) == []


def test_uploads_on_a_device_write_into_frigates_model_cache(device_client, login, tmp_path):
    codedir = device_with_codedir(device_client, tmp_path, PLUS_CONFIG)
    login(device_client, *ADMIN)
    r = put(device_client, "dev.tflite", b"\x04" * 10)
    assert r.status_code == 201, r.text
    cache = codedir / "frigate" / "config" / "model_cache"
    assert (cache / "dev.tflite").read_bytes() == b"\x04" * 10
    r = post_sidecar(device_client, "dev.tflite")
    assert r.status_code == 201 and r.json()["complete"] is True
    assert json.loads((cache / "dev.tflite.json").read_text())["supportedDetectors"] == ["edgetpu"]


def test_the_form_needs_to_know_the_detector(device_client, login, tmp_path):
    codedir = device_with_codedir(device_client, tmp_path)  # no config.yml, Frigate silent: the detector is unknown
    login(device_client, *ADMIN)
    assert put(device_client, "dev.tflite", b"\x04").status_code == 201
    r = post_sidecar(device_client, "dev.tflite")
    assert (r.status_code, message(r)) == (
        409, "The device's detector can't be told now; try again when Frigate answers.")
    assert not (codedir / "frigate" / "config" / "model_cache" / "dev.tflite.json").exists()


def test_audit_rows_name_the_model(seeded, settings, login):
    import sqlite3

    login(seeded, *ADMIN)
    put(seeded, "a.tflite.json", sidecar_bytes())
    put(seeded, "a.tflite", b"\x01")
    put(seeded, "b.tflite", b"\x01")
    post_sidecar(seeded, "b.tflite")
    delete(seeded, "a.tflite")
    put(seeded, "mine.tflite", b"\x01")  # refused: no row
    admin = Users(seeded.app.state.state).by_username("admin")
    con = sqlite3.connect(settings.state_dir / "state.sqlite")
    try:
        rows = con.execute(
            "SELECT user_id, action, detail FROM audit WHERE action LIKE 'models.%' ORDER BY id").fetchall()
    finally:
        con.close()
    assert rows == [
        (admin.id, "models.upload", "a.tflite.json"),
        (admin.id, "models.upload", "a.tflite"),
        (admin.id, "models.upload", "b.tflite"),
        (admin.id, "models.sidecar", "b.tflite"),
        (admin.id, "models.delete", "a.tflite"),
    ]
