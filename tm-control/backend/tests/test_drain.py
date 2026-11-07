"""core/drain.py: on the upload path, the rest of an unread body is read and discarded before the response starts.

Each test runs the middleware around a tiny ASGI app with a receive that hands over a body in chunks and records each
call, and a send that records each message, so the order of the two shows whether the body was read first.
"""

import asyncio

import pytest

from tm_control.core.drain import DrainMiddleware

PREFIX = "/api/v1/models/upload/"


class Peer:
    """The server's side of one request: the body in chunks, then http.disconnect, and every message sent back."""

    def __init__(self, chunks: list[bytes], disconnect_after: int | None = None):
        self.chunks = list(chunks)
        self.disconnect_after = disconnect_after  # hand over this many chunks, then only http.disconnect
        self.events: list[tuple[str, object]] = []
        self.given = 0

    async def receive(self):
        if self.given == self.disconnect_after or self.given == len(self.chunks):
            self.events.append(("receive", "disconnect"))
            return {"type": "http.disconnect"}
        body = self.chunks[self.given]
        self.given += 1
        self.events.append(("receive", self.given))
        return {"type": "http.request", "body": body, "more_body": self.given < len(self.chunks)}

    async def send(self, message):
        self.events.append(("send", message["type"]))

    def receives_before_start(self) -> int:
        start = self.events.index(("send", "http.response.start"))
        return sum(1 for kind, _ in self.events[:start] if kind == "receive")


def answering_app(reads: int = 0, status: int = 403):
    """An app that reads `reads` body messages, then answers `status` with a short body."""

    async def app(scope, receive, send):
        for _ in range(reads):
            await receive()
        await send({"type": "http.response.start", "status": status, "headers": []})
        await send({"type": "http.response.body", "body": b"no"})

    return app


def run(app, peer: Peer, path: str = PREFIX + "m.tflite", scope_type: str = "http", bound: int = 1024):
    scope = {"type": scope_type, "method": "PUT", "path": path}
    asyncio.run(DrainMiddleware(app, prefix=PREFIX, bound=bound)(scope, peer.receive, peer.send))


def test_an_unread_body_is_read_before_the_response_starts():
    peer = Peer([b"a" * 4] * 5)
    run(answering_app(), peer)
    assert peer.given == 5
    assert peer.receives_before_start() == 5
    assert peer.events[-2:] == [("send", "http.response.start"), ("send", "http.response.body")]


def test_a_partly_read_body_has_the_rest_read_before_the_response_starts():
    peer = Peer([b"a" * 4] * 5)
    run(answering_app(reads=2, status=413), peer)
    assert peer.given == 5 and peer.receives_before_start() == 5


def test_a_fully_read_body_is_left_alone():
    peer = Peer([b"a" * 4] * 3)
    run(answering_app(reads=3, status=201), peer)
    assert peer.receives_before_start() == 3  # the app's own three; the middleware asked for nothing more


@pytest.mark.parametrize("path", ["/api/v1/secrets/x", "/api/v1/models/uploadx", "/api/v1/models/m.tflite/sidecar",
                                  "/api/v1/health", "/upload/m.tflite"])
def test_other_paths_pass_through_and_the_middleware_never_reads(path):
    peer = Peer([b"a" * 4] * 3)
    run(answering_app(), peer, path=path)
    assert peer.given == 0 and peer.events[0] == ("send", "http.response.start")


def test_other_scope_types_pass_through():
    peer = Peer([b"a" * 4] * 3)
    run(answering_app(), peer, scope_type="websocket")
    assert peer.given == 0


def test_draining_stops_at_the_bound_and_the_response_still_goes_out():
    peer = Peer([b"a" * 4] * 10)
    run(answering_app(), peer, bound=10)
    assert peer.given == 3  # 4, 8, then 12 bytes: past the bound of 10
    assert peer.events[-2:] == [("send", "http.response.start"), ("send", "http.response.body")]


def test_a_disconnect_while_draining_ends_the_drain_without_error():
    peer = Peer([b"a" * 4] * 5, disconnect_after=2)
    run(answering_app(), peer)
    assert peer.given == 2
    assert peer.events.count(("receive", "disconnect")) == 1  # not asked again after the disconnect
    assert peer.events[-2:] == [("send", "http.response.start"), ("send", "http.response.body")]


def test_a_disconnect_the_app_already_saw_means_no_drain():
    peer = Peer([b"a" * 4] * 5, disconnect_after=1)
    run(answering_app(reads=2, status=400), peer)
    assert peer.events.count(("receive", "disconnect")) == 1
