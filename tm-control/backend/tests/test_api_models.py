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
    assert set(document) == {"detector", "frigate_answers", "frigate_safe_mode", "default", "running", "models",
                             "labels"}
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


def test_the_form_names_the_model_when_a_name_is_given(seeded, settings, login):
    login(seeded, *ADMIN)
    assert put(seeded, "named.tflite", b"\x04" * 64).status_code == 201
    r = post_sidecar(seeded, "named.tflite", FORM | {"name": "  Placeholder model  "})
    assert r.status_code == 201, r.text
    assert r.json()["title"] == "Placeholder model"
    written = json.loads((fake.model_cache(settings) / "named.tflite.json").read_text())
    assert written["name"] == "Placeholder model"
    assert set(written) == {"name", "type", "supportedDetectors", "width", "height", "inputShape", "pixelFormat",
                            "labelMap"}  # nothing Frigate doesn't define
    assert put(seeded, "other.tflite", b"\x05" * 64).status_code == 201
    assert post_sidecar(seeded, "other.tflite", FORM | {"name": "   "}).status_code == 422
    assert post_sidecar(seeded, "other.tflite", FORM | {"name": "x" * 65}).status_code == 422
    assert not (fake.model_cache(settings) / "other.tflite.json").exists()


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
    assert (r.status_code, message(r)) == (422, "The archive can't be read.")
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


MIB = 1024 * 1024


def drive(app, path, headers, chunks):
    """Run one PUT through the ASGI app with the body in chunks, as nginx streams an upload. Returns the response's
    status and the events in order: ("receive", n) as chunk n is handed over, ("send", type) for each message sent."""
    import asyncio

    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "PUT", "scheme": "http",
        "path": path, "raw_path": path.encode(), "root_path": "", "query_string": b"",
        "server": ("tm-test.local", 80), "client": ("127.0.0.1", 50000),
        "headers": [(name.lower().encode(), value.encode()) for name, value in headers.items()],
    }
    events, sent, given = [], [], 0

    async def receive():
        nonlocal given
        if given == len(chunks):
            events.append(("receive", "disconnect"))
            return {"type": "http.disconnect"}
        given += 1
        events.append(("receive", given))
        return {"type": "http.request", "body": chunks[given - 1], "more_body": given < len(chunks)}

    async def send(message):
        events.append(("send", message["type"]))
        sent.append(message)

    asyncio.run(app(scope, receive, send))
    return sent[0]["status"], events


def upload_headers(cookie=None, origin=True, length=None):
    headers = {"Host": "tm-test.local", "Content-Type": "application/octet-stream"}
    if origin:
        headers["Origin"] = ORIGIN
    if cookie:
        headers["Cookie"] = f"tm_session={cookie}"
    if length is not None:
        headers["Content-Length"] = str(length)
    return headers


@pytest.mark.parametrize(("who", "name", "chunks", "declare", "origin", "status"), [
    (None, "x.tflite", [b"\x01" * 1024] * 5, True, True, 401),  # signed out
    ("viewer", "x.tflite", [b"\x01" * 1024] * 5, True, True, 403),
    ("admin", "x.tflite", [b"\x01" * 1024] * 5, True, False, 403),  # the cross-site check: no Origin
    ("admin", "mine.tflite", [b"\x01" * 1024] * 5, True, True, 409),  # the name is in use
    ("admin", "big.tflite.json", [b" " * MIB] * 3, True, True, 413),  # over the sidecar cap by Content-Length
    ("admin", "big.tflite.json", [b" " * MIB] * 4, False, True, 413),  # over the cap partway through the body
])
def test_a_refused_upload_reads_the_whole_body_before_answering(
        seeded, settings, login, who, name, chunks, declare, origin, status):
    """nginx streams an upload to tm-control unbuffered; an answer sent before the body is read makes it a 502."""
    cookie = None
    if who == "viewer":
        Users(seeded.app.state.state).create(*VIEWER, "viewer")
        cookie = login(seeded, *VIEWER)
    elif who == "admin":
        cookie = login(seeded, *ADMIN)
    length = sum(len(chunk) for chunk in chunks) if declare else None
    answer, events = drive(seeded.app, f"{URL}/upload/{name}", upload_headers(cookie, origin, length), chunks)
    assert answer == status
    start = events.index(("send", "http.response.start"))
    assert [event for event in events[:start] if event[0] == "receive"] == [
        ("receive", n) for n in range(1, len(chunks) + 1)]
    assert cache_names(settings) == SEEDED


def test_an_accepted_upload_is_not_read_twice(seeded, settings, login):
    cookie = login(seeded, *ADMIN)
    chunks = [b"\x01" * 1024] * 3
    answer, events = drive(seeded.app, f"{URL}/upload/new.tflite", upload_headers(cookie, length=3072), chunks)
    assert answer == 201
    assert ("receive", "disconnect") not in events
    assert (fake.model_cache(settings) / "new.tflite").read_bytes() == b"\x01" * 3072


def test_other_requests_are_not_read_by_the_drain(seeded, login):
    """A refusal elsewhere is left as it was: nothing reads a body the app didn't."""
    answer, events = drive(seeded.app, "/api/v1/secrets/x", upload_headers(), [b"{}"])
    assert answer in (401, 403, 404, 405)
    assert events[0] == ("send", "http.response.start")


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


# Archives in, packages out.


def zip_of(files: dict[str, bytes]) -> bytes:
    import io
    import zipfile

    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return out.getvalue()


def package_of(client, name):
    return client.get(f"{URL}/{name}/package")


def packages(settings) -> list[str]:
    directory = settings.state_dir / "packages"
    return sorted(path.name for path in directory.iterdir()) if directory.exists() else []


def test_upload_a_zip_package_and_download_it_back(seeded, settings, login):
    import hashlib
    import io
    import zipfile

    login(seeded, *ADMIN)
    model, sidecar = b"\x05" * 300, sidecar_bytes(name="Zipped")
    sums = "".join(f"{hashlib.sha256(data).hexdigest()}  {name}\n" for name, data in (
        ("z.tflite", model), ("z.tflite.json", sidecar))).encode()
    r = put(seeded, "z.zip", zip_of({"z.tflite": model, "z.tflite.json": sidecar, "SHA256SUMS": sums}))
    assert r.status_code == 201, r.text
    assert (r.json()["name"], r.json()["complete"], r.json()["title"]) == ("z.tflite", True, "Zipped")
    assert cache_names(settings) == sorted(SEEDED + ["z.tflite", "z.tflite.json"])  # the archive's temp is gone
    r = package_of(seeded, "z.tflite")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/zip"
    assert r.headers["content-disposition"] == 'attachment; filename="z.tflite.zip"'
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        assert zf.namelist() == ["z.tflite", "z.tflite.json", "SHA256SUMS"]
        assert (zf.read("z.tflite"), zf.read("z.tflite.json"), zf.read("SHA256SUMS")) == (model, sidecar, sums)
    assert packages(settings) == []  # removed once it was sent
    assert stat_mode(settings.state_dir / "packages") == 0o700
    delete(seeded, "z.tflite")
    r = put(seeded, "again.tgz", tgz_of({}))  # an empty tar.gz has no pair
    assert (r.status_code, message(r)) == (422, "The archive has no model file and sidecar pair.")
    assert cache_names(settings) == SEEDED


def stat_mode(path) -> int:
    import stat

    return stat.S_IMODE(path.stat().st_mode)


def tgz_of(files: dict[str, bytes]) -> bytes:
    import io
    import tarfile

    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w:gz") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return out.getvalue()


def test_a_package_uploads_back_after_its_model_is_deleted(seeded, settings, login):
    login(seeded, *ADMIN)
    package = package_of(seeded, "mine.tflite")
    assert package.status_code == 200
    stored = (fake.model_cache(settings) / "mine.tflite").read_bytes()
    assert delete(seeded, "mine.tflite").status_code == 204
    r = put(seeded, "mine.tgz", b"")  # not gzip
    assert r.status_code == 422
    r = put(seeded, "mine.zip", package.content)
    assert r.status_code == 201, r.text
    assert (r.json()["name"], r.json()["complete"]) == ("mine.tflite", True)
    assert (fake.model_cache(settings) / "mine.tflite").read_bytes() == stored
    r = put(seeded, "mine.zip", package.content)  # never over the model now there
    assert (r.status_code, message(r)) == (409, "A model named mine.tflite is already on the device; delete it first.")
    assert cache_names(settings) == SEEDED


def test_a_tgz_whose_bytes_are_not_gzip_is_refused(seeded, settings, login):
    login(seeded, *ADMIN)
    r = put(seeded, "m.tgz", b"PK\x03\x04" + zip_of({"m.tflite": b"x"}))
    assert (r.status_code, message(r)) == (422, "The file isn't a tar.gz archive.")
    r = put(seeded, "m.tgz", b"\x1f\x8b\x08\x00" + b"\x00" * 60)  # gzip's magic, then no gzip stream
    assert (r.status_code, message(r)) == (422, "The archive can't be read.")
    r = put(seeded, "m.tar.gz", tgz_of({"m.tflite": b"x", "m.tflite.json": sidecar_bytes(), "a": b"", "b": b""}))
    assert (r.status_code, message(r)) == (422, "The archive holds more than a model, its sidecar, and SHA256SUMS.")
    r = put(seeded, "m.tar.gz", tgz_of({"../m.tflite": b"x", "m.tflite.json": sidecar_bytes()}))
    assert (r.status_code, message(r)) == (422, "An archive member has a path, or isn't a plain file.")
    r = put(seeded, "m.tar.gz", tgz_of({"m.tflite": b"x", "m.tflite.json": sidecar_bytes(), "SHA256SUMS": b"0" * 64}))
    assert (r.status_code, message(r)) == (422, "SHA256SUMS doesn't match the files.")
    r = put(seeded, "m.tar.gz", tgz_of({INSTALLER_FILE: b"x", f"{INSTALLER_FILE}.json": sidecar_bytes()}))
    assert r.status_code == 409  # the installer's file is in the cache
    assert cache_names(settings) == SEEDED


def test_an_archive_with_the_installers_name_is_refused_when_its_file_is_gone(seeded, settings, login):
    login(seeded, *ADMIN)
    (fake.model_cache(settings) / INSTALLER_FILE).unlink()
    r = put(seeded, "m.tar.gz", tgz_of({INSTALLER_FILE: b"x", f"{INSTALLER_FILE}.json": sidecar_bytes()}))
    assert (r.status_code, message(r)) == (422, "That name isn't allowed.")
    assert INSTALLER_FILE not in cache_names(settings)


def test_a_member_over_its_cap_is_a_413(seeded, settings, login):
    import io
    import tarfile

    login(seeded, *ADMIN)
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w:gz") as tar:
        info = tarfile.TarInfo("m.tflite.json")
        info.size = 3 * 1024 * 1024
        header = info.tobuf(tar.format, tar.encoding, tar.errors)  # the header alone, no 3 MB behind it
        tar.fileobj.write(header)
        tar.offset += len(header)
    r = put(seeded, "m.tgz", out.getvalue())
    assert (r.status_code, message(r)) == (413, "An archive member is larger than its cap.")
    assert cache_names(settings) == SEEDED


def test_a_package_of_an_incomplete_pair_is_404(seeded, settings, login):
    login(seeded, *ADMIN)
    put(seeded, "bare.tflite", b"\x01")
    put(seeded, "half.tflite.json", sidecar_bytes())
    (fake.model_cache(settings) / "broken.tflite").write_bytes(b"\x01")
    (fake.model_cache(settings) / "broken.tflite.json").write_bytes(b"not json")
    for name in ("bare.tflite", "half.tflite", "broken.tflite", INSTALLER_FILE, "missing.tflite"):
        r = package_of(seeded, name)
        assert r.status_code == 404, name
    assert package_of(seeded, "%2E%2E").status_code == 422
    assert packages(settings) == []


def test_only_admins_download_a_package_and_the_download_is_audited(seeded, settings, login):
    import sqlite3

    assert package_of(seeded, PLUS_ID).status_code == 401
    Users(seeded.app.state.state).create(*VIEWER, "viewer")
    login(seeded, *VIEWER)
    assert package_of(seeded, PLUS_ID).status_code == 403
    login(seeded, *ADMIN)
    assert package_of(seeded, PLUS_ID).status_code == 200
    put(seeded, "a.zip", zip_of({"a.tflite": b"\x01", "a.tflite.json": sidecar_bytes()}))
    admin = Users(seeded.app.state.state).by_username("admin")
    con = sqlite3.connect(settings.state_dir / "state.sqlite")
    try:
        rows = con.execute(
            "SELECT user_id, action, detail FROM audit WHERE action LIKE 'models.%' ORDER BY id").fetchall()
    finally:
        con.close()
    assert rows == [(admin.id, "models.download", PLUS_ID), (admin.id, "models.upload", "a.tflite")]


def test_a_package_that_cannot_be_built_leaves_no_file(seeded, settings, login, monkeypatch):
    from tm_control.modules.detection import package

    login(seeded, *ADMIN)

    def broken(dir_fd, name, out):
        out.write(b"partial")
        raise OSError("read failed")

    monkeypatch.setattr(package, "write_package", broken)
    r = package_of(seeded, "mine.tflite")
    assert (r.status_code, message(r)) == (500, "The model's files can't be read.")
    assert packages(settings) == []
    monkeypatch.setattr("os.statvfs", lambda path: type("S", (), {"f_frsize": 4096, "f_bavail": 1000})())
    r = package_of(seeded, "mine.tflite")
    assert (r.status_code, message(r)) == (507, "The device would have less than 512 MB free.")


# Use: make Frigate run a model, or the installer's default. Fake mode writes the running-model file; a device saves
# through Frigate's config API, or edits config.yml when Frigate doesn't answer, then restarts frigate.service.

FRIGATE_RESTART = ["systemctl", "restart", "--no-block", "frigate.service"]
RESTARTING = "Frigate is restarting; try again in a minute."
FRIGATE_HEADER_LINES = (
    "Your configuration is invalid.\nSee the official documentation at docs.frigate.video.\n"
)


@pytest.fixture
def systemctl(monkeypatch):
    from test_api_services import FakeSystemctl

    fake_systemctl = FakeSystemctl()
    monkeypatch.setattr("tm_control.adapters.systemd.run", fake_systemctl)
    return fake_systemctl


def use(client, name):
    return client.post(f"{URL}/{name}/use", json={}, headers=WRITE_HEADERS)


def never_applied(*args, **kwargs):
    raise AssertionError("picker.apply was called")


def use_rows(settings):
    import sqlite3

    con = sqlite3.connect(settings.state_dir / "state.sqlite")
    try:
        return [row[0] for row in con.execute("SELECT detail FROM audit WHERE action = 'models.use' ORDER BY id")]
    finally:
        con.close()


def test_use_a_model_answers_202_and_queues_a_restart(seeded, settings, login, monkeypatch):
    from tm_control.modules.detection import picker

    login(seeded, *ADMIN)
    monkeypatch.setattr(picker, "apply", never_applied)  # fake mode only rewrites the running-model file
    r = use(seeded, "mine.tflite")
    assert r.status_code == 202, r.text
    assert r.json() == {"name": "mine.tflite", "applied": "frigate", "restarts": ["frigate.service"]}
    assert fake.running_model_file(settings).read_text() == "mine.tflite"
    state = models_of(seeded)
    assert state["running"] == {"name": "mine.tflite", "kind": "local", "source": "frigate"}
    assert use(seeded, "mine.tflite").status_code == 202  # the running model again: Frigate just restarts
    assert use(seeded, PLUS_ID).json()["name"] == PLUS_ID
    assert models_of(seeded)["running"]["kind"] == "frigate_plus"


def write_pair(cache: Path, name: str, **changes):
    (cache / name).write_bytes(b"\x01")
    (cache / f"{name}.json").write_bytes(sidecar_bytes(**changes))


def test_a_model_for_another_detector_is_refused_before_any_write(seeded, settings, login, monkeypatch):
    from tm_control.modules.detection import picker

    login(seeded, *ADMIN)
    monkeypatch.setattr(picker, "apply", never_applied)
    write_pair(fake.model_cache(settings), "h.tflite", supportedDetectors=["hailo8l"])
    r = use(seeded, "h.tflite")
    assert (r.status_code, r.json()["error"]["code"]) == (422, "wrong_detector")
    assert message(r) == "This model is built for hailo8l; this device detects with edgetpu."
    assert fake.running_model_file(settings).read_text() == PLUS_ID
    (fake.model_cache(settings) / "bare.tflite").write_bytes(b"\x01")
    r = use(seeded, "bare.tflite")
    assert (r.status_code, message(r)) == (422, "This model is missing its sidecar.")
    assert use_rows(settings) == []


class DeviceFrigate:
    """Frigate's API on a device as httpjson sees it: /api/config from the fixture, /api/config/raw with `raw`, and
    /api/config/save answering `save`; `raw = None` is a Frigate that doesn't answer at all."""

    def __init__(self, raw, save=(200, {"success": True, "message": "Config successfully saved."}), config=None):
        self.raw = raw
        self.save = save
        self.config = config  # /api/config's answer in place of the fixture's
        self.posts = []

    def get(self, url, headers=None, timeout=None):
        if self.raw is None:
            return None, None
        if url == "http://127.0.0.1:5000/api/config":
            if self.config is not None:
                return 200, json.dumps(self.config).encode()
            return 200, (FIXTURES / "frigate_api_config.json").read_bytes()
        if url == "http://127.0.0.1:5000/api/config/raw":
            return 200, json.dumps(self.raw).encode()
        return None, None

    def post(self, url, body, content_type, headers=None, timeout=None):
        self.posts.append((url, body.decode(), content_type))
        if self.raw is None:
            return None, None
        status, answer = self.save
        return status, json.dumps(answer).encode()


@pytest.fixture
def frigate_api(monkeypatch):
    def answering(raw, **kwargs):
        from tm_control.adapters import httpjson

        api = DeviceFrigate(raw, **kwargs)
        monkeypatch.setattr(httpjson, "get", api.get)
        monkeypatch.setattr(httpjson, "post", api.post)
        return api

    return answering


def yaml_of(text):
    from ruamel.yaml import YAML

    return YAML(typ="safe", pure=True).load(text)


def backups_of(config: Path) -> list[str]:
    return sorted(path.name for path in config.parent.glob("config.yml.*.bak"))


@pytest.mark.parametrize("answers", [True, False])
def test_a_model_for_another_detector_is_refused_on_a_device(
        device_client, login, tmp_path, systemctl, frigate_api, answers):
    codedir = device_with_codedir(device_client, tmp_path, PLUS_CONFIG)
    config = codedir / "frigate" / "config" / "config.yml"
    write_pair(config.parent / "model_cache", "h.tflite", supportedDetectors=["hailo8l", "rknn"])
    api = frigate_api(PLUS_CONFIG if answers else None)
    login(device_client, *ADMIN)
    r = use(device_client, "h.tflite")
    assert (r.status_code, r.json()["error"]["code"]) == (422, "wrong_detector")
    assert message(r) == "This model is built for hailo8l, rknn; this device detects with edgetpu."
    assert api.posts == [] and config.read_text() == PLUS_CONFIG and backups_of(config) == []
    assert systemctl.restarts() == []


def test_use_on_a_device_saves_through_frigate_then_restarts_it(
        device_client, settings, login, tmp_path, systemctl, frigate_api):
    codedir = device_with_codedir(device_client, tmp_path, PLUS_CONFIG)
    config = codedir / "frigate" / "config" / "config.yml"
    write_pair(config.parent / "model_cache", "mine.tflite")
    api = frigate_api(PLUS_CONFIG)
    login(device_client, *ADMIN)
    r = use(device_client, "mine.tflite")
    assert r.status_code == 202, r.text
    assert r.json() == {"name": "mine.tflite", "applied": "frigate", "restarts": ["frigate.service"]}
    ((url, body, content_type),) = api.posts
    assert url == "http://127.0.0.1:5000/api/config/save?save_option=saveonly" and content_type == "text/plain"
    saved = yaml_of(body)
    assert saved["model"]["path"] == "/config/model_cache/mine.tflite"
    assert saved["model"]["labelmap"] == {0: "person", 1: "bicycle", 2: "car"}
    assert saved["detectors"] == yaml_of(PLUS_CONFIG)["detectors"]
    assert config.read_text() == PLUS_CONFIG  # Frigate writes its own file
    assert systemctl.restarts() == [FRIGATE_RESTART]
    assert use_rows(device_client.app.state.settings) == ["mine.tflite"]


def test_use_on_a_device_edits_the_file_when_frigate_is_down(
        device_client, login, tmp_path, systemctl, frigate_api):
    codedir = device_with_codedir(device_client, tmp_path, PLUS_CONFIG)
    config = codedir / "frigate" / "config" / "config.yml"
    write_pair(config.parent / "model_cache", "mine.tflite")
    api = frigate_api(None)
    login(device_client, *ADMIN)
    r = use(device_client, "mine.tflite")
    assert r.status_code == 202, r.text
    assert r.json()["applied"] == "file"
    assert api.posts == []
    assert yaml_of(config.read_text())["model"]["path"] == "/config/model_cache/mine.tflite"
    assert len(backups_of(config)) == 1
    assert systemctl.restarts() == [FRIGATE_RESTART]


def test_frigates_refusal_writes_nothing_and_restarts_nothing(
        device_client, login, tmp_path, systemctl, frigate_api):
    from placeholders import PLACEHOLDER_KEY

    codedir = device_with_codedir(device_client, tmp_path, PLUS_CONFIG)
    config = codedir / "frigate" / "config" / "config.yml"
    write_pair(config.parent / "model_cache", "mine.tflite")
    refusal = FRIGATE_HEADER_LINES + f"Line 3: model -> input_tensor - Input should be 'nchw' {PLACEHOLDER_KEY}\n"
    frigate_api(PLUS_CONFIG, save=(400, {"success": False, "message": refusal}))
    login(device_client, *ADMIN)
    r = use(device_client, "mine.tflite")
    assert (r.status_code, r.json()["error"]["code"]) == (422, "frigate_refused")
    assert message(r) == "Frigate refused the config: Line 3: model -> input_tensor - Input should be 'nchw' <key>"
    assert PLACEHOLDER_KEY not in r.text and "docs.frigate.video" not in r.text
    assert config.read_text() == PLUS_CONFIG and backups_of(config) == []
    assert systemctl.restarts() == []
    assert use_rows(device_client.app.state.settings) == []


def test_use_default_puts_the_installers_section_back(seeded, settings, login, monkeypatch):
    from tm_control.modules.detection import picker

    login(seeded, *ADMIN)
    monkeypatch.setattr(picker, "apply", never_applied)
    r = use(seeded, "default")
    assert r.status_code == 202, r.text
    assert r.json() == {"name": "default", "applied": "frigate", "restarts": ["frigate.service"]}
    assert fake.running_model_file(settings).read_text() == INSTALLER_FILE
    assert models_of(seeded)["running"]["kind"] == "installer_default"
    fake.running_model_file(settings).write_text("mine.tflite")
    r = use(seeded, INSTALLER_FILE)  # the installer's file is the default
    assert r.status_code == 202 and r.json()["name"] == "default"
    assert fake.running_model_file(settings).read_text() == INSTALLER_FILE

    # a detector the installer's model isn't for: Frigate's own default, an empty file
    answer = fake.frigate_answer

    def cpu_answer(settings):
        config, config_file = answer(settings)
        config["detectors"] = {"cpu": {"type": "cpu"}}
        return config, config_file

    monkeypatch.setattr(fake, "frigate_answer", cpu_answer)
    assert use(seeded, "default").status_code == 202
    assert fake.running_model_file(settings).read_text() == ""


def test_use_default_on_a_device_writes_the_installers_section_or_none(
        device_client, login, tmp_path, systemctl, frigate_api):
    codedir = device_with_codedir(device_client, tmp_path, PLUS_CONFIG)
    config = codedir / "frigate" / "config" / "config.yml"
    (config.parent / "model_cache" / INSTALLER_FILE).write_bytes(bytes(1024))
    frigate_api(None)
    login(device_client, *ADMIN)
    r = use(device_client, "default")
    assert r.status_code == 202, r.text
    assert r.json() == {"name": "default", "applied": "file", "restarts": ["frigate.service"]}
    model = yaml_of(config.read_text())["model"]
    assert list(model) == ["model_type", "width", "height", "path", "labelmap_path"]
    assert model["path"] == f"/config/model_cache/{INSTALLER_FILE}"
    config.write_text("detectors:\n  cpu:\n    type: cpu\nmodel:\n  path: /config/model_cache/mine.tflite\n")
    for backup in backups_of(config):  # a backup's name has the second it was made in
        (config.parent / backup).unlink()
    assert use(device_client, "default").status_code == 202
    assert yaml_of(config.read_text()) == {"detectors": {"cpu": {"type": "cpu"}}}
    assert systemctl.restarts() == [FRIGATE_RESTART, FRIGATE_RESTART]
    config.unlink()  # neither Frigate nor the file says what detects
    r = use(device_client, "default")
    assert (r.status_code, r.json()["error"]["code"]) == (409, "detector_unknown")
    assert len(systemctl.restarts()) == 2


@pytest.mark.parametrize("state", ["activating", "deactivating"])
def test_use_is_409_while_frigate_restarts(device_client, login, tmp_path, systemctl, frigate_api, state):
    codedir = device_with_codedir(device_client, tmp_path, PLUS_CONFIG)
    config = codedir / "frigate" / "config" / "config.yml"
    api = frigate_api(PLUS_CONFIG)
    systemctl.units = {"frigate.service": {"ActiveState": state}}
    login(device_client, *ADMIN)
    for name in (PLUS_ID, "default"):
        r = use(device_client, name)
        assert (r.status_code, r.json()["error"]["code"], message(r)) == (409, "restarting", RESTARTING)
    assert api.posts == [] and config.read_text() == PLUS_CONFIG and systemctl.restarts() == []
    systemctl.units = {}
    assert use(device_client, PLUS_ID).status_code == 202
    systemctl.timed_out = {"frigate.service"}  # systemd can't say: the use goes ahead, and its restart is queued
    assert use(device_client, PLUS_ID).status_code == 202
    assert len(systemctl.restarts()) == 2


def test_use_is_admin_only_and_unknown_names_are_404(seeded, settings, login):
    assert use(seeded, "mine.tflite").status_code == 401
    Users(seeded.app.state.state).create(*VIEWER, "viewer")
    login(seeded, *VIEWER)
    assert use(seeded, "mine.tflite").status_code == 403
    assert use(seeded, "default").status_code == 403
    login(seeded, *ADMIN)
    r = use(seeded, "nothing.tflite")
    assert (r.status_code, message(r)) == (404, "There is no such model.")
    assert use(seeded, "a.json").status_code == 422
    assert use(seeded, ".hidden").status_code == 422
    assert fake.running_model_file(settings).read_text() == PLUS_ID


def test_use_audits_the_name_and_default(seeded, settings, login):
    login(seeded, *ADMIN)
    use(seeded, "mine.tflite")
    use(seeded, "default")
    use(seeded, INSTALLER_FILE)
    use(seeded, "nothing.tflite")  # refused: no row
    assert use_rows(settings) == ["mine.tflite", "default", "default"]


INSTALLER_MISSING = "The installer's model file isn't on the device."


def test_the_installers_default_needs_its_file(device_client, login, tmp_path, systemctl, frigate_api):
    codedir = device_with_codedir(device_client, tmp_path, PLUS_CONFIG)  # edgetpu, no installer's file in the cache
    config = codedir / "frigate" / "config" / "config.yml"
    api = frigate_api(PLUS_CONFIG)
    login(device_client, *ADMIN)
    for name in ("default", INSTALLER_FILE):
        r = use(device_client, name)
        assert (r.status_code, r.json()["error"]["code"], message(r)) == (409, "installer_missing", INSTALLER_MISSING)
    (config.parent / "model_cache" / INSTALLER_FILE).mkdir()  # not a regular file
    assert use(device_client, "default").status_code == 409
    assert api.posts == [] and config.read_text() == PLUS_CONFIG and systemctl.restarts() == []
    assert use_rows(device_client.app.state.settings) == []
    (config.parent / "model_cache" / INSTALLER_FILE).rmdir()
    (config.parent / "model_cache" / INSTALLER_FILE).write_bytes(bytes(1024))
    assert use(device_client, "default").status_code == 202
    assert yaml_of(api.posts[0][1])["model"]["path"] == f"/config/model_cache/{INSTALLER_FILE}"


def test_frigates_own_default_needs_no_file(device_client, login, tmp_path, systemctl, frigate_api):
    codedir = device_with_codedir(device_client, tmp_path, "detectors:\n  cpu:\n    type: cpu\n")
    frigate_api(None)
    login(device_client, *ADMIN)
    assert use(device_client, "default").status_code == 202  # no section to apply, so no file is needed


def test_the_installers_default_needs_its_file_in_fake_mode(seeded, settings, login):
    login(seeded, *ADMIN)
    (fake.model_cache(settings) / INSTALLER_FILE).unlink()
    r = use(seeded, "default")
    assert (r.status_code, r.json()["error"]["code"]) == (409, "installer_missing")
    assert fake.running_model_file(settings).read_text() == PLUS_ID


def test_a_use_is_refused_on_a_device_whose_detector_sets_a_model(
        device_client, login, tmp_path, systemctl, frigate_api):
    detector_model = "detectors:\n  coral:\n    type: edgetpu\n    model:\n      path: /config/model_cache/a\n"
    codedir = device_with_codedir(device_client, tmp_path, detector_model)
    config = codedir / "frigate" / "config" / "config.yml"
    login(device_client, *ADMIN)
    for raw in (detector_model, None):
        api = frigate_api(raw)
        r = use(device_client, PLUS_ID)
        assert (r.status_code, r.json()["error"]["code"]) == (409, "detector_model")
        assert message(r) == ("Frigate's config sets a model inside detectors.coral; remove it in Frigate's config "
                              "editor first.")
        assert api.posts == []
    assert config.read_text() == detector_model and backups_of(config) == [] and systemctl.restarts() == []


# Frigate's own default model file: a Hailo detector with no model path makes Frigate download yolov6n.hef into
# model_cache and run it, so the file is Frigate's built-in model, which nothing here may write or remove.

HAILO_CONFIG = "detectors:\n  hailo8l:\n    type: hailo8l\n    device: PCIe\n"
HAILO_FILE = "yolov6n.hef"
FRIGATES = "That's Frigate's built-in model."


def hailo_device(client, tmp_path, config=HAILO_CONFIG):
    """A device without a Coral whose model_cache holds Frigate's Hailo file beside the fixture pair; returns the
    cache."""
    cache = device_with_codedir(client, tmp_path, config, coral=False) / "frigate" / "config" / "model_cache"
    (cache / HAILO_FILE).write_bytes(bytes(2048))
    return cache


def test_frigates_hailo_file_is_listed_as_its_built_in_model_and_runs(device_client, login, tmp_path):
    hailo_device(device_client, tmp_path)
    login(device_client, *ADMIN)
    state = models_of(device_client)
    assert (state["detector"], state["default"]) == ("hailo8l", "frigate_default")
    assert state["running"] == {"name": None, "kind": "frigate_default", "source": "config_file"}
    assert [model["name"] for model in state["models"]] == [HAILO_FILE, PLUS_ID]
    model = state["models"][0]
    assert (model["kind"], model["title"], model["complete"], model["problem"]) == (
        "frigate_default", HAILO_FILE, True, None)
    assert (model["running"], model["deletable"], model["usable"]) == (True, False, None)
    assert [(file["name"], file["size"]) for file in model["files"]] == [(HAILO_FILE, 2048)]
    assert state["models"][1]["running"] is False


def test_frigates_hailo_file_is_not_running_while_another_model_runs(device_client, login, tmp_path):
    hailo_device(device_client, tmp_path, f"{HAILO_CONFIG}model:\n  path: plus://{PLUS_ID}\n")
    login(device_client, *ADMIN)
    model = models_of(device_client)["models"][0]
    assert (model["kind"], model["running"], model["deletable"]) == ("frigate_default", False, False)
    (tmp_path / "codedir" / "frigate" / "config" / "config.yml").write_text(
        f"{HAILO_CONFIG}model:\n  path: https://example.invalid/other.hef\n")  # Frigate downloads and runs that one
    state = models_of(device_client)
    assert state["running"]["kind"] == "frigate_default" and state["models"][0]["running"] is False


def test_frigates_hailo_file_cannot_be_deleted_replaced_given_a_sidecar_or_downloaded(device_client, login, tmp_path):
    cache = hailo_device(device_client, tmp_path)
    login(device_client, *ADMIN)
    r = delete(device_client, HAILO_FILE)
    assert (r.status_code, message(r)) == (409, FRIGATES)
    r = post_sidecar(device_client, HAILO_FILE)
    assert (r.status_code, message(r)) == (409, FRIGATES)
    r = put(device_client, f"{HAILO_FILE}.json", sidecar_bytes())
    assert (r.status_code, message(r)) == (422, "That name isn't allowed.")
    assert package_of(device_client, HAILO_FILE).status_code == 404
    (cache / HAILO_FILE).unlink()  # gone, its name is still Frigate's to write
    r = put(device_client, HAILO_FILE, b"\x05")
    assert (r.status_code, message(r)) == (422, "That name isn't allowed.")
    r = put(device_client, "m.tar.gz", tgz_of({HAILO_FILE: b"x", f"{HAILO_FILE}.json": sidecar_bytes()}))
    assert (r.status_code, message(r)) == (422, "That name isn't allowed.")
    assert sorted(path.name for path in cache.iterdir()) == [PLUS_ID, f"{PLUS_ID}.json"]


def test_using_frigates_hailo_file_uses_frigates_default(device_client, login, tmp_path, systemctl, frigate_api):
    cache = hailo_device(device_client, tmp_path, f"{HAILO_CONFIG}model:\n  path: plus://{PLUS_ID}\n")
    config = cache.parent / "config.yml"
    frigate_api(None)
    login(device_client, *ADMIN)
    r = use(device_client, HAILO_FILE)
    assert r.status_code == 202, r.text
    assert r.json() == {"name": "default", "applied": "file", "restarts": ["frigate.service"]}
    assert yaml_of(config.read_text()) == yaml_of(HAILO_CONFIG)
    assert systemctl.restarts() == [FRIGATE_RESTART]


def test_a_file_with_frigates_hailo_name_is_a_local_model_on_a_coral(device_client, login, tmp_path):
    cache = device_with_codedir(device_client, tmp_path, PLUS_CONFIG) / "frigate" / "config" / "model_cache"
    (cache / HAILO_FILE).write_bytes(bytes(2048))
    login(device_client, *ADMIN)
    model = next(model for model in models_of(device_client)["models"] if model["name"] == HAILO_FILE)
    assert (model["kind"], model["complete"], model["deletable"]) == ("local", False, True)
    assert delete(device_client, HAILO_FILE).status_code == 204
    assert put(device_client, HAILO_FILE, b"\x05").status_code == 201


SAFE_MODE_CONFIG = {  # what Frigate's /api/config answers after its config failed to validate
    "safe_mode": True,
    "detectors": {"cpu": {"type": "cpu", "model": {"path": "/cpu_model.tflite", "labelmap": {"0": "person"}}}},
    "model": {"path": "/cpu_model.tflite"},
    "cameras": {},
    "objects": {"track": ["person"]},
}


def test_in_safe_mode_the_page_reads_the_config_file_and_says_so(
        device_client, login, tmp_path, systemctl, frigate_api):
    """Frigate in safe mode runs a stand-in config (a cpu detector, no cameras), not config.yml's, so the detector
    and the running model come from the file, and a Use still goes through Frigate's API, which validates the whole
    config and gets Frigate out of safe mode."""
    codedir = device_with_codedir(device_client, tmp_path, PLUS_CONFIG)
    (codedir / "frigate" / "config" / "model_cache" / INSTALLER_FILE).write_bytes(bytes(1024))
    api = frigate_api(PLUS_CONFIG, config=SAFE_MODE_CONFIG)
    login(device_client, *ADMIN)
    state = models_of(device_client)
    assert (state["frigate_answers"], state["frigate_safe_mode"]) == (True, True)
    assert (state["detector"], state["default"]) == ("edgetpu", "installer_default")
    assert state["running"] == {"name": PLUS_ID, "kind": "frigate_plus", "source": "config_file"}
    assert state["labels"]["source"] == "sidecar"
    by_name = {model["name"]: model for model in state["models"]}
    assert by_name[PLUS_ID]["running"] is True and by_name[PLUS_ID]["usable"] is True
    assert by_name[INSTALLER_FILE]["running"] is False
    r = device_client.post(f"{URL}/default/use", headers=WRITE_HEADERS)
    assert (r.status_code, r.json()["applied"]) == (202, "frigate"), r.text
    assert len(api.posts) == 1 and systemctl.restarts() == [FRIGATE_RESTART]
    assert models_of(device_client)["frigate_safe_mode"] is True  # until Frigate restarts


def test_out_of_safe_mode_the_answer_says_so(seeded, login):
    login(seeded, *ADMIN)
    assert models_of(seeded)["frigate_safe_mode"] is False
