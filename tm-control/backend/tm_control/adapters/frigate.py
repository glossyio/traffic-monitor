"""Frigate's API inside the pod, on its unauthenticated port 5000 (published on 127.0.0.1 only), and its config.yml as
the host has it.

Each API function returns None when Frigate doesn't answer, times out, or answers something else than expected.
/api/config masks the credentials in camera input paths (rtsp://*:*@...).
"""

import json
import re
from pathlib import Path
from urllib.parse import quote

from tm_control.adapters import httpjson
from tm_control.adapters.yamlfile import ConfigRead, read_config

BASE = "http://127.0.0.1:5000/api"
VERSION = re.compile(r"[0-9A-Za-z.+_-]{1,64}")  # such as 0.18.1-cf67f08
SAVE_TIMEOUT = 30  # seconds: Frigate validates the whole config before it writes the file


def version() -> str | None:
    """Frigate's version, such as "0.18.1-cf67f08": /api/version answers plain text."""
    status, body = httpjson.get(f"{BASE}/version")
    if status != 200 or body is None:
        return None
    text = body.decode("utf-8", errors="replace").strip().strip('"')
    return text if VERSION.fullmatch(text) else None


# Frigate's nginx keeps each GET under /api/ for 5 seconds, and serves the old answer while it fetches a new one; this
# header makes it ask Frigate now
FRESH = {"X-Cache-Bypass": "1"}


def _object(path: str, headers: dict[str, str] | None = None) -> dict | None:
    status, body = httpjson.get_json(f"{BASE}/{path}", headers)
    return body if status == 200 and isinstance(body, dict) else None


def config() -> dict | None:
    """The config Frigate runs with, resolved: cameras.<name>.enabled, .detect.enabled, .ffmpeg.inputs[].path, .zones,
    detectors. Read past Frigate's API cache, so a switch set a moment ago (set_detect, or Frigate's live view) shows."""
    return _object("config", FRESH)


def stats() -> dict | None:
    """cameras.<name>.camera_fps and detectors.<name>.inference_speed and .pid, among others."""
    return _object("stats")


def config_raw() -> str | None:
    """config.yml's text as Frigate reads it from its own disk: /api/config/raw answers it as a JSON string."""
    status, body = httpjson.get_json(f"{BASE}/config/raw")
    return body if status == 200 and isinstance(body, str) else None


def save_config(text: str, timeout: float = SAVE_TIMEOUT) -> tuple[int | None, str | None]:
    """Have Frigate validate text as its whole config and, when it's valid, write it to config.yml without
    restarting. Returns the status and the answer's message (a refusal's says why); None for each that's missing.
    Waits up to timeout seconds: a config with a plus:// model path holds the answer until Frigate has downloaded it."""
    status, body = httpjson.post(
        f"{BASE}/config/save?save_option=saveonly", text.encode("utf-8"), "text/plain", timeout=timeout
    )
    try:
        answer = json.loads(body) if body is not None else None
    except (ValueError, RecursionError):
        answer = None
    message = answer.get("message") if isinstance(answer, dict) else None
    return status, message if isinstance(message, str) else None


def set_detect(camera: str, on: bool) -> bool:
    """Turn object detection on or off for one camera, as the switch in Frigate's live view does: at once, with no
    restart, and Frigate keeps the setting across restarts (in .runtime_state.json beside its config). Turning it on
    also turns on motion detection. Whether Frigate took it."""
    status, body = httpjson.post(
        f"{BASE}/camera/{quote(camera, safe='')}/set/detect", json.dumps({"value": "ON" if on else "OFF"}).encode(),
        "application/json", method="PUT",
    )
    try:
        answer = json.loads(body) if body is not None else None
    except (ValueError, RecursionError):
        answer = None
    return status == 200 and isinstance(answer, dict) and answer.get("success") is True


def config_file(codedir) -> ConfigRead:
    """<codedir>/frigate/config/config.yml as the host has it, which is what Frigate reads when it starts. Never
    raises."""
    return read_config(Path(codedir) / "frigate" / "config" / "config.yml")
