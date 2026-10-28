"""go2rtc's API on the host, 127.0.0.1:1984."""

from tm_control.adapters import httpjson

STREAMS_URL = "http://127.0.0.1:1984/api/streams"


def streams() -> dict | None:
    """Each stream's producers and consumers, by stream name; None when go2rtc doesn't answer.

    A producer that isn't running is listed with its source URL only; a running one also has its connection's
    details (medias, receivers, bytes_recv).
    """
    status, body = httpjson.get_json(STREAMS_URL)
    return body if status == 200 and isinstance(body, dict) else None
