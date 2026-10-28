"""Frigate's API inside the pod, on its unauthenticated port 5000 (published on 127.0.0.1 only).

Each function returns None when Frigate doesn't answer, times out, or answers something else than expected.
/api/config masks the credentials in camera input paths (rtsp://*:*@...).
"""

import re

from tm_control.adapters import httpjson

BASE = "http://127.0.0.1:5000/api"
VERSION = re.compile(r"[0-9A-Za-z.+_-]{1,64}")  # such as 0.18.1-cf67f08


def version() -> str | None:
    """Frigate's version, such as "0.18.1-cf67f08": /api/version answers plain text."""
    status, body = httpjson.get(f"{BASE}/version")
    if status != 200 or body is None:
        return None
    text = body.decode("utf-8", errors="replace").strip().strip('"')
    return text if VERSION.fullmatch(text) else None


def _object(path: str) -> dict | None:
    status, body = httpjson.get_json(f"{BASE}/{path}")
    return body if status == 200 and isinstance(body, dict) else None


def config() -> dict | None:
    """The config Frigate runs with, resolved: cameras.<name>.enabled, .ffmpeg.inputs[].path, .zones, detectors."""
    return _object("config")


def stats() -> dict | None:
    """cameras.<name>.camera_fps and detectors.<name>.inference_speed and .pid, among others."""
    return _object("stats")
