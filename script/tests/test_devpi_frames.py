"""frame_sizes_on_pi() in the device tests' helpers, against a small local server that answers Frigate's config and its
latest.jpg: the line's shape, the two requests it makes, and that no camera name or picture byte comes out."""

import importlib.util
import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, unquote, urlsplit

import pytest

DEVPI_CHECKS = Path(__file__).resolve().parents[1] / "devpi" / "tests" / "devpi_checks.py"
_spec = importlib.util.spec_from_file_location("devpi_checks_frames_under_test", DEVPI_CHECKS)
devpi_checks = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(devpi_checks)

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tm-control" / "backend" / "tests"))
from jpegs import jpeg  # noqa: E402

# Names with a space and a slash, which must be quoted in the path and which must not come out
FRONT = "front door/cam"
BACK = "back yard"
SECRET_NAMES = (FRONT, BACK, "front%20door%2Fcam", "back%20yard", "door", "yard")


class LocalHost:
    """Runs each command on this machine, as testinfra runs it on the Pi, with the port in place of 5000."""

    def __init__(self, port):
        self.port = port
        self.commands = []

    def run(self, command):
        self.commands.append(command)
        assert command.rstrip().endswith(" 5000")
        command = command.rstrip()[: -len(" 5000")] + f" {self.port}"
        result = subprocess.run(["sh", "-c", command], capture_output=True, text=True, timeout=60)
        return SimpleNamespace(command=command, stdout=result.stdout, stderr=result.stderr, rc=result.returncode)


def fake_frigate(config, frames):
    """A server on a free port. `frames` maps (camera, zones) to (status, content type, body, extra headers)."""
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            parts = urlsplit(self.path)
            seen.append((parts.path, parts.query, self.headers.get("X-Cache-Bypass")))
            if parts.path == "/api/config":
                return self.answer(200, "application/json", json.dumps(config).encode(), {})
            camera = unquote(parts.path[len("/api/"):-len("/latest.jpg")])
            query = parse_qs(parts.query)
            zones = query.get("zones") == ["1"]
            if parts.path.endswith("/latest.jpg") and query.get("quality") == ["95"] and (camera, zones) in frames:
                return self.answer(*frames[(camera, zones)])
            return self.answer(404, "text/plain", b"no", {})

        def answer(self, status, content_type, body, extra):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            for key, value in extra.items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, seen


def config_of(*cameras):
    return {"cameras": {name: {"enabled": True, "detect": {"width": w, "height": h}} for name, w, h in cameras}}


def run(config, frames):
    server, seen = fake_frigate(config, frames)
    host = LocalHost(server.server_address[1])
    try:
        return devpi_checks.frame_sizes_on_pi(host), host, seen
    finally:
        server.shutdown()


def test_each_camera_gets_its_two_frames_measured_in_config_order():
    clean_a, zones_a = jpeg(640, 480), jpeg(640, 480) + b"\x00" * 100
    frames = {
        (FRONT, False): (200, "image/jpeg", clean_a, {}),
        (FRONT, True): (200, "image/jpeg", zones_a, {}),
        (BACK, False): (200, "image/jpeg", jpeg(1280, 720), {"X-Frigate-Offline": "true"}),
        (BACK, True): (200, "image/jpeg", jpeg(1280, 720), {}),
    }
    result, host, seen = run(config_of((FRONT, 640, 480), (BACK, 1280, 720)), frames)
    assert result == [
        {"detect": [640, 480],
         "clean": {"status": 200, "type": "image/jpeg", "bytes": len(clean_a), "size": [640, 480], "offline": False},
         "zones": {"status": 200, "type": "image/jpeg", "bytes": len(zones_a), "size": [640, 480], "offline": False}},
        {"detect": [1280, 720],
         "clean": {"status": 200, "type": "image/jpeg", "bytes": len(jpeg(1280, 720)), "size": [1280, 720],
                   "offline": True},
         "zones": {"status": 200, "type": "image/jpeg", "bytes": len(jpeg(1280, 720)), "size": [1280, 720],
                   "offline": False}},
    ]
    # The config is read past Frigate's cache; the adapter's two requests follow, in this order, for each camera
    assert seen[0] == ("/api/config", "", "1")
    assert [(path, query) for path, query, _ in seen[1:]] == [
        ("/api/front%20door%2Fcam/latest.jpg", "quality=95"),
        ("/api/front%20door%2Fcam/latest.jpg", "quality=95&zones=1"),
        ("/api/back%20yard/latest.jpg", "quality=95"),
        ("/api/back%20yard/latest.jpg", "quality=95&zones=1"),
    ]
    # Every request, the frames too, goes past Frigate's cache, as the adapter's do
    assert [bypass for _, _, bypass in seen] == ["1"] * 5
    assert len(host.commands) == 1


def test_the_script_prints_one_line_with_no_camera_name():
    server, _ = fake_frigate(config_of((FRONT, 64, 48)), {
        (FRONT, False): (200, "image/jpeg", jpeg(64, 48), {}),
        (FRONT, True): (200, "image/jpeg", jpeg(64, 48), {}),
    })
    try:
        command = f"python3 -c {devpi_checks.shlex.quote(devpi_checks.PI_FRAME_SIZES)} {server.server_address[1]}"
        result = subprocess.run(["sh", "-c", command], capture_output=True, text=True, timeout=60)
    finally:
        server.shutdown()
    assert result.returncode == 0 and result.stderr == ""
    assert result.stdout.count("\n") == 1 and result.stdout.endswith("\n")
    for name in SECRET_NAMES:
        assert name not in result.stdout
    assert json.loads(result.stdout)[0]["detect"] == [64, 48]
    # Nothing of a picture comes out: no start-of-image marker's bytes, and no key but the six that were asked for
    assert "JFIF" not in result.stdout and "\\xff" not in result.stdout
    [camera] = json.loads(result.stdout)
    assert set(camera) == {"detect", "clean", "zones"}
    assert set(camera["clean"]) == {"status", "type", "bytes", "size", "offline"}


def test_a_frame_that_is_not_a_jpeg_or_not_an_answer_has_its_status_and_no_size():
    frames = {
        (FRONT, False): (503, "text/plain", b"busy", {}),
        (FRONT, True): (200, "image/jpeg", b"\xff\xd8\xff\xd9", {}),  # a JPEG with no frame header
        (BACK, False): (200, "text/html", b"<html>", {}),
        # (BACK, True) is a 404 from the server
    }
    result, _, _ = run(config_of((FRONT, 640, 480), (BACK, 640, 480)), frames)
    assert result[0]["clean"] == {"status": 503, "type": "text/plain", "bytes": 4, "size": None, "offline": False}
    assert result[0]["zones"] == {"status": 200, "type": "image/jpeg", "bytes": 4, "size": None, "offline": False}
    assert result[1]["clean"] == {"status": 200, "type": "text/html", "bytes": 6, "size": None, "offline": False}
    assert result[1]["zones"]["status"] == 404


def test_the_size_is_read_from_the_frame_header_past_other_segments():
    """A comment segment and a progressive frame header (0xC2) between the start and the size; a DHT (0xC4) is not one."""
    body = (b"\xff\xd8" + b"\xff\xfe\x00\x06abcd" + b"\xff\xc4\x00\x04\x00\x00"
            + b"\xff\xc2\x00\x0b\x08" + (1080).to_bytes(2, "big") + (1920).to_bytes(2, "big") + b"\x01\x01\x11\x00"
            + b"\xff\xd9")
    frames = {(FRONT, False): (200, "image/jpeg", body, {}), (FRONT, True): (200, "image/jpeg", body, {})}
    result, _, _ = run(config_of((FRONT, 1920, 1080)), frames)
    assert result[0]["clean"]["size"] == [1920, 1080]
    assert result[0]["clean"]["bytes"] == len(body)


def test_a_server_that_is_not_there_gives_a_failure_with_no_name():
    with pytest.raises(AssertionError, match="measuring Frigate's frames failed"):
        devpi_checks.frame_sizes_on_pi(LocalHost(1))


def test_no_cameras_is_an_empty_list():
    result, _, _ = run({"cameras": {}}, {})
    assert result == []
