"""Frigate's current frame for a camera (latest.jpg), through its API on 127.0.0.1; and httpjson.get_with_headers, which
reads an answer's headers as well as its body."""

import http.server
import socket
import threading

import pytest

from tests.jpegs import jpeg
from tm_control.adapters import frigate, httpjson

JPEG = jpeg(1536, 864)
IMAGE = {"content-type": "image/jpeg", "cache-control": "no-store"}


@pytest.fixture
def answering(monkeypatch):
    """Patch httpjson.get_with_headers to record each call as (url, headers, timeout) and answer what the test gives;
    returns the list of calls."""

    def setup(answer):
        calls = []

        def get_with_headers(url, headers=None, timeout=None):
            calls.append((url, headers, timeout))
            return answer

        monkeypatch.setattr(httpjson, "get_with_headers", get_with_headers)
        return calls

    return setup


def test_latest_frame_asks_for_the_frame_at_quality_95_past_the_cache(answering):
    calls = answering((200, JPEG, IMAGE))
    assert frigate.latest_frame("oak ave/tele") == frigate.Frame(JPEG, False)
    url, headers, timeout = calls[0]
    assert url == "http://127.0.0.1:5000/api/oak%20ave%2Ftele/latest.jpg?quality=95"
    assert headers == {"X-Cache-Bypass": "1"} and timeout == frigate.FRAME_TIMEOUT == 10


def test_latest_frame_with_zones_adds_zones_1(answering):
    calls = answering((200, JPEG, IMAGE))
    frigate.latest_frame("picam_h265", zones=True)
    assert calls[0][0].endswith("/picam_h265/latest.jpg?quality=95&zones=1")


def test_an_older_frame_is_marked_offline(answering):
    answering((200, JPEG, IMAGE | {"x-frigate-offline": "true"}))
    assert frigate.latest_frame("picam_h265") == frigate.Frame(JPEG, True)


@pytest.mark.parametrize("answer", [
    (None, None, {}),                                        # Frigate didn't answer
    (404, b'{"success": false}', {"content-type": "application/json"}),
    (200, b'{"success": false}', {"content-type": "application/json"}),
    (200, b"GIF89a", IMAGE),                                 # says JPEG, isn't one
    (200, None, IMAGE),                                      # longer than the adapter reads
])
def test_anything_but_a_jpeg_is_no_frame(answering, answer):
    answering(answer)
    assert frigate.latest_frame("picam_h265") is None


# get_with_headers against a real server


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(203)
        self.send_header("X-Frigate-Offline", "true")
        self.send_header("Content-Type", "image/jpeg")
        self.end_headers()
        self.wfile.write(JPEG)

    def log_message(self, *args):
        pass


@pytest.fixture
def http_app():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def test_get_with_headers_answers_the_status_the_body_and_lower_case_headers(http_app):
    status, body, headers = httpjson.get_with_headers(f"{http_app}/api/x/latest.jpg")
    assert (status, body) == (203, JPEG)
    assert headers["x-frigate-offline"] == "true" and headers["content-type"] == "image/jpeg"


def test_get_with_headers_from_a_closed_port_is_nothing():
    with socket.create_server(("127.0.0.1", 0)) as spare:
        port = spare.getsockname()[1]
    assert httpjson.get_with_headers(f"http://127.0.0.1:{port}/") == (None, None, {})


def test_get_with_headers_reaches_only_loopback():
    with pytest.raises(ValueError):
        httpjson.get_with_headers("http://example.com/")
