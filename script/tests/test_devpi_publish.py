"""publish_on_pi() in the device tests' helpers, against a fake broker on this machine: the MQTT packets it sends."""

import importlib.util
import json
import socket
import subprocess
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

DEVPI_CHECKS = Path(__file__).resolve().parents[1] / "devpi" / "tests" / "devpi_checks.py"
_spec = importlib.util.spec_from_file_location("devpi_checks_under_test", DEVPI_CHECKS)
devpi_checks = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(devpi_checks)


class LocalHost:
    """Runs each command on this machine, as testinfra runs it on the Pi."""

    def run(self, command):
        result = subprocess.run(["sh", "-c", command], capture_output=True, text=True, timeout=30)
        return SimpleNamespace(stdout=result.stdout, stderr=result.stderr, rc=result.returncode)


def packets(data):
    """Split a byte stream into MQTT packets: (packet type, body)."""
    found = []
    while data:
        kind, index, length, shift = data[0] >> 4, 1, 0, 0
        while True:
            digit = data[index]
            length |= (digit & 0x7F) << shift
            index, shift = index + 1, shift + 7
            if not digit & 0x80:
                break
        found.append((kind, data[index:index + length]))
        data = data[index + length:]
    return found


def fake_broker(connack_code):
    """A one-connection broker on a free port: answers CONNECT with this code, and keeps every byte it gets."""
    server = socket.create_server(("127.0.0.1", 0))
    received = bytearray()

    def serve():
        connection, _ = server.accept()
        with connection:
            connection.settimeout(10)
            received.extend(connection.recv(4096))  # the CONNECT
            connection.sendall(bytes([0x20, 2, 0, connack_code]))
            while chunk := connection.recv(65536):
                received.extend(chunk)
        server.close()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    return server.getsockname()[1], received, thread


def test_publish_sends_one_qos_0_message_and_disconnects():
    port, received, thread = fake_broker(0)
    payload = {"type": "end", "after": {"id": "1.0-tmdev0", "label": "tmdev_check", "note": "quotes ' \" and $x"}}
    devpi_checks.publish_on_pi(LocalHost(), "frigate/events", payload, port=port)
    thread.join(10)
    [(connect, _), (publish, body), (disconnect, _)] = packets(bytes(received))
    assert (connect, publish, disconnect) == (1, 3, 14)
    topic_length = int.from_bytes(body[:2], "big")
    assert body[2:2 + topic_length] == b"frigate/events"
    assert json.loads(body[2 + topic_length:]) == payload


def test_publish_raises_with_the_code_when_the_broker_refuses():
    port, _, thread = fake_broker(5)
    with pytest.raises(AssertionError, match="CONNACK 5"):
        devpi_checks.publish_on_pi(LocalHost(), "frigate/events", {"type": "end"}, port=port)
    thread.join(10)
