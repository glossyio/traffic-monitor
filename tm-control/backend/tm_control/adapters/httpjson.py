"""HTTP reads from the apps on this device (Frigate, Node-RED, go2rtc): a GET to 127.0.0.1 with a short timeout.

Neither function raises when the app doesn't answer, times out, or answers something unreadable; they return None
in place of what's missing.
"""

import json
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlsplit

TIMEOUT = 3  # seconds for the connection and for each read
MAX_BODY = 8 * 1024 * 1024  # bytes; a longer answer counts as none

# Without proxies: these requests stay on loopback, and a proxy from the environment must never see them or a token.
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _body(response) -> bytes | None:
    data = response.read(MAX_BODY + 1)
    return data if len(data) <= MAX_BODY else None


def get(
    url: str, headers: dict[str, str] | None = None, timeout: float | None = None
) -> tuple[int | None, bytes | None]:
    """The HTTP status and body of a GET, an error status's included; (None, None) when nothing answered in time.

    Raises ValueError for a URL that isn't on 127.0.0.1: that's a mistake in the caller, not an app's state.
    """
    if urlsplit(url).hostname != "127.0.0.1":
        raise ValueError("tm-control reads the apps on 127.0.0.1 only")
    request = urllib.request.Request(url, headers=dict(headers or {}))
    try:
        with _OPENER.open(request, timeout=TIMEOUT if timeout is None else timeout) as response:
            return response.status, _body(response)
    except urllib.error.HTTPError as error:
        try:
            return error.code, _body(error)
        except Exception:
            return error.code, None
    except Exception:
        return None, None


def get_json(url: str, headers: dict[str, str] | None = None, timeout: float | None = None) -> tuple[int | None, Any]:
    """get's status and its body parsed as JSON, or None for a body that isn't JSON."""
    status, body = get(url, headers, timeout)
    if body is None:
        return status, None
    try:
        return status, json.loads(body)
    except (ValueError, RecursionError):
        return status, None
