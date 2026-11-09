"""The MQTT broker (Aedes, inside Node-RED): whether port 1883 is open to the network, and whether the broker turns
away a client without a login.

The pod publishes 1883 on 127.0.0.1, and also to the LAN when node-red-tm.env sets a broker login, which the broker
then enforces (tasks/mqtt_broker.yml). Neither function raises.
"""

import socket
import time

from tm_control.adapters.command import run

CLIENT_ID = "tm-control-check"
KEEPALIVE = 30  # seconds
SS_TIMEOUT = 4  # seconds; a status probe
SS_MAX_OUTPUT = 65536
LOOPBACK = ("127.", "[::1]", "[::ffff:127.")


def _field(text: str) -> bytes:
    data = text.encode()
    return len(data).to_bytes(2, "big") + data


def connect_packet(client_id: str = CLIENT_ID) -> bytes:
    """An MQTT 3.1.1 CONNECT with a clean session and no user name or password."""
    body = _field("MQTT") + bytes([4, 0x02]) + KEEPALIVE.to_bytes(2, "big") + _field(client_id)
    length, encoded = len(body), b""
    while True:
        length, digit = divmod(length, 128)
        encoded += bytes([digit | (0x80 if length else 0)])
        if not length:
            break
    return b"\x10" + encoded + body


def anonymous_connect_refused(host: str = "127.0.0.1", port: int = 1883, timeout: float = 3) -> bool | None:
    """True when the broker refuses a client without a login (CONNACK return code 4 or 5), False when it accepts
    one (0), None when it doesn't answer with a CONNACK within timeout seconds or answers anything else."""
    deadline = time.monotonic() + timeout
    try:
        with socket.create_connection((host, port), timeout=timeout) as connection:
            connection.sendall(connect_packet())
            reply = b""
            while len(reply) < 4:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                connection.settimeout(remaining)
                chunk = connection.recv(4 - len(reply))
                if not chunk:
                    return None  # closed without a CONNACK
                reply += chunk
            if reply[0] != 0x20 or reply[1] != 2:
                return None
            if reply[3] == 0:
                try:
                    connection.sendall(b"\xe0\x00")  # DISCONNECT, so the broker doesn't log a lost client
                except OSError:
                    pass  # a courtesy: the broker has already accepted a client without a login
                return False
            return True if reply[3] in (4, 5) else None
    except Exception:
        return None


def port_1883_open_to_network() -> bool | None:
    """Whether a socket listens on port 1883 on an address other than loopback; None when ss fails.

    Under tm-control's sandbox ss can't open a netlink socket; it says so on stderr and reads /proc instead.
    """
    try:
        result = run(["ss", "-ltnH"], timeout=SS_TIMEOUT, max_output=SS_MAX_OUTPUT)
    except Exception:
        return None
    if result.timed_out or result.returncode != 0:
        return None
    for line in result.stdout.splitlines():
        fields = line.split()
        if len(fields) < 4:
            continue
        address, _, port = fields[3].rpartition(":")
        address = address.split("%", 1)[0]  # 127.0.0.1%lo: bound to an interface
        if port == "1883" and not address.startswith(LOOPBACK):
            return True
    return False
