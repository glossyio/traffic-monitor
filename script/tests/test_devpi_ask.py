"""ask_frigate_on_pi() in the device tests' helpers, against a fake broker on this machine: the MQTT packets it sends,
and how it reads an answer that is long or arrives in pieces."""

import importlib.util
import json
import socket
import subprocess
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

DEVPI_CHECKS = Path(__file__).resolve().parents[1] / "devpi" / "tests" / "devpi_checks.py"
_spec = importlib.util.spec_from_file_location("devpi_checks_ask_under_test", DEVPI_CHECKS)
devpi_checks = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(devpi_checks)

WAIT_TOPIC = b"frigate/camera_activity"


class LocalHost:
    """Runs each command on this machine, as testinfra runs it on the Pi, with the port in place of 1883."""

    def __init__(self, port):
        self.port = port
        self.commands = []

    def run(self, command):
        self.commands.append(command)
        command = command.replace(" 1883 ", f" {self.port} ", 1)
        result = subprocess.run(["sh", "-c", command], capture_output=True, text=True, timeout=60)
        return SimpleNamespace(stdout=result.stdout, stderr=result.stderr, rc=result.returncode)


def remaining(length):
    encoded = b""
    while True:
        length, digit = divmod(length, 128)
        encoded += bytes([digit | (0x80 if length else 0)])
        if not length:
            return encoded


def publish(topic, payload):
    body = len(topic).to_bytes(2, "big") + topic + payload
    return b"\x30" + remaining(len(body)) + body


def read_packet(connection):
    def take(count):
        data = b""
        while len(data) < count:
            chunk = connection.recv(count - len(data))
            if not chunk:
                raise ConnectionError("closed")
            data += chunk
        return data

    first = take(1)[0]
    length, shift = 0, 0
    while True:
        digit = take(1)[0]
        length |= (digit & 0x7F) << shift
        shift += 7
        if not digit & 0x80:
            break
    return first, take(length)


def fake_broker(answer=None, connack_code=0, stale=None, chunk=None):
    """A one-connection broker on a free port. `answer` is the bytes it sends in reply to the client's PUBLISH (in
    pieces of `chunk` bytes when given); `stale` is a message it sends on the topic before the SUBACK.
    `seen` holds what the client sent."""
    server = socket.create_server(("127.0.0.1", 0))
    seen = {}

    def serve():
        connection, _ = server.accept()
        with connection:
            connection.settimeout(20)
            first, body = read_packet(connection)
            seen["connect"] = (first, body)
            connection.sendall(bytes([0x20, 2, 0, connack_code]))
            if connack_code:
                return
            first, body = read_packet(connection)
            seen["subscribe"] = (first, body)
            if stale is not None:
                connection.sendall(publish(WAIT_TOPIC, stale))
            connection.sendall(bytes([0x90, 3]) + body[:2] + b"\x00")
            first, body = read_packet(connection)
            seen["publish"] = (first, body)
            if answer is not None:
                data = publish(WAIT_TOPIC, answer)
                for start in range(0, len(data), chunk or len(data)):
                    connection.sendall(data[start:start + (chunk or len(data))])
                    if chunk:
                        time.sleep(0.001)
            try:
                seen["after"] = read_packet(connection)
            except (ConnectionError, TimeoutError, OSError):
                pass
        server.close()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    return server.getsockname()[1], seen, thread


def connect_fields(body):
    """The CONNECT packet's fields: (protocol level, flags, client id, user, password)."""
    assert body[:6] == b"\x00\x04MQTT"
    level, flags, rest = body[6], body[7], body[10:]
    fields = []
    while rest:
        size = int.from_bytes(rest[:2], "big")
        fields.append(rest[2:2 + size].decode())
        rest = rest[2 + size:]
    return (level, flags, *fields)


ANSWER = {
    "cam_a": {"motion": 0, "objects": [{"label": "car"}, {"label": "person"}], "config": {"detect": True, "enabled": True}},
    "cam_b": {"motion": 0, "objects": [], "config": {"detect": False}},
    "cam_c": {"motion": 0},
    "cam_d": {"objects": "none", "config": {"detect": "yes"}},
    "cam_e": "not an object",
}
SUMMARY = {
    "cam_a": {"objects": 2, "detect": True},
    "cam_b": {"objects": 0, "detect": False},
    "cam_c": {"objects": None, "detect": None},
    "cam_d": {"objects": None, "detect": None},
    "cam_e": {"objects": None, "detect": None},
}


def ask(port, login=("", ""), wait=5):
    host = LocalHost(port)
    return devpi_checks.ask_frigate_on_pi(host, login, wait=wait), host


def test_asks_on_the_topic_and_gives_each_cameras_counts():
    port, seen, thread = fake_broker(json.dumps(ANSWER).encode())
    cameras, _ = ask(port)
    thread.join(10)
    assert cameras == SUMMARY
    assert connect_fields(seen["connect"][1]) == (4, 0x02, "tmdev-ask")
    assert seen["connect"][0] >> 4 == 1
    assert seen["subscribe"][0] == 0x82
    sub = seen["subscribe"][1]
    assert sub[2:4] == len(WAIT_TOPIC).to_bytes(2, "big") and sub[4:4 + len(WAIT_TOPIC)] == WAIT_TOPIC
    assert sub[-1] == 0  # QoS 0
    assert seen["publish"] == (0x30, b"\x00\x11frigate/onConnect")
    assert seen["after"][0] == 0xE0


def test_the_login_goes_on_standard_input_and_into_the_connect_packet():
    port, seen, thread = fake_broker(b"{}")
    password = "p'a\"ss $x `y` \\z"
    cameras, host = ask(port, ("user'name", password))
    thread.join(10)
    assert cameras == {}
    assert connect_fields(seen["connect"][1]) == (4, 0xC2, "tmdev-ask", "user'name", password)
    [command] = host.commands
    # In the here-document that is standard input, and quoted so the shell reads nothing in it; not an argument.
    head, _, tail = command.partition("<<'TMDEV_LOGIN_END'\n")
    assert "user'name" not in head and password not in head
    assert tail == f"user'name\n{password}\nTMDEV_LOGIN_END\n"


def test_a_user_without_a_password_sets_only_the_user_flag():
    port, seen, thread = fake_broker(b"{}")
    ask(port, ("someone", ""))
    thread.join(10)
    assert connect_fields(seen["connect"][1]) == (4, 0x82, "tmdev-ask", "someone")


@pytest.mark.parametrize("padding", [20, 200, 20_000, 2_200_000])
def test_a_long_answer_in_small_pieces_is_read_whole(padding):
    """A remaining length of one, two, three, and four bytes, the PUBLISH arriving in pieces."""
    answer = {**ANSWER, "pad": {"objects": [], "config": {"detect": True}, "note": "x" * padding}}
    data = json.dumps(answer).encode()
    port, _, thread = fake_broker(data, chunk=1000 if padding < 1_000_000 else 100_000)
    cameras, _ = ask(port)
    thread.join(20)
    assert cameras == {**SUMMARY, "pad": {"objects": 0, "detect": True}}
    assert len(data) > {20: 0, 200: 0, 20_000: 16_384, 2_200_000: 2_097_152}[padding]


def test_a_packet_cut_inside_its_header_is_read():
    port, _, thread = fake_broker(json.dumps(ANSWER).encode(), chunk=1)
    cameras, _ = ask(port)
    thread.join(20)
    assert cameras == SUMMARY


def test_a_message_that_is_not_json_or_not_an_object_has_no_cameras():
    for answer in (b"not json", b"[1, 2]", b"3"):
        port, _, thread = fake_broker(answer)
        cameras, _ = ask(port)
        thread.join(10)
        assert cameras == {}


def test_no_answer_gives_none_after_the_wait():
    port, seen, thread = fake_broker(None)
    started = time.monotonic()
    cameras, _ = ask(port, wait=1)
    elapsed = time.monotonic() - started
    thread.join(10)
    assert cameras is None
    assert elapsed < 10
    assert seen["after"][0] == 0xE0


def test_a_message_before_the_suback_is_not_the_answer():
    port, _, thread = fake_broker(None, stale=json.dumps(ANSWER).encode())
    cameras, _ = ask(port, wait=1)
    thread.join(10)
    assert cameras is None


def test_a_qos_1_delivery_has_a_packet_id_before_the_payload():
    data = json.dumps(ANSWER).encode()
    server = socket.create_server(("127.0.0.1", 0))

    def serve():
        connection, _ = server.accept()
        with connection:
            read_packet(connection)
            connection.sendall(bytes([0x20, 2, 0, 0]))
            _, body = read_packet(connection)
            connection.sendall(bytes([0x90, 3]) + body[:2] + b"\x00")
            read_packet(connection)
            body = len(WAIT_TOPIC).to_bytes(2, "big") + WAIT_TOPIC + b"\x00\x07" + data
            connection.sendall(b"\x32" + remaining(len(body)) + body)
            try:
                read_packet(connection)
            except (ConnectionError, TimeoutError, OSError):
                pass
        server.close()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    cameras, _ = ask(server.getsockname()[1])
    thread.join(10)
    assert cameras == SUMMARY


def test_raises_with_the_code_when_the_broker_refuses():
    port, _, thread = fake_broker(None, connack_code=5)
    with pytest.raises(AssertionError, match="CONNACK 5"):
        ask(port)
    thread.join(10)


def test_a_login_with_a_line_break_is_refused_before_anything_runs():
    with pytest.raises(AssertionError, match="line break"):
        devpi_checks.ask_frigate_on_pi(LocalHost(1), ("a\nb", "c"))


def test_a_broker_that_is_not_there_fails_with_the_last_line_of_the_error():
    with pytest.raises(AssertionError, match="asking the Pi's broker failed"):
        ask(1)
