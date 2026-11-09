"""Node-RED's state: its internal status endpoint (127.0.0.1:1880, in the flows' tm-control status group), and its
config.yml as the host has it.

Neither function raises.
"""

from pathlib import Path
from typing import Literal, NamedTuple

from ruamel.yaml import YAML
from ruamel.yaml.error import MarkedYAMLError

from tm_control.adapters import httpjson

STATUS_URL = "http://127.0.0.1:1880/tm-internal/status"
TOKEN_HEADER = "X-TM-Internal-Token"


def status(token: str) -> tuple[int | None, dict | None]:
    """The HTTP status and the JSON object /tm-internal/status answers; (None, None) when Node-RED doesn't answer.

    401 means the token doesn't match TM_INTERNAL_TOKEN in node-red-tm.env (or that isn't set).
    """
    code, body = httpjson.get_json(STATUS_URL, {TOKEN_HEADER: token})
    return code, body if isinstance(body, dict) else None


def config_path(codedir) -> Path:
    return Path(codedir) / "node-red-tm" / "config" / "config.yml"


class ConfigRead(NamedTuple):
    """config.yml parsed, or why it couldn't be: "missing", "unreadable", or "invalid" (not YAML, or not a mapping).

    For a YAML error, line and column (from 1) say where; nothing of the file's content is kept, since it can hold
    thingsboard.access_token.
    """

    data: dict | None
    problem: Literal["missing", "unreadable", "invalid"] | None
    line: int | None = None
    column: int | None = None


def config(codedir) -> ConfigRead:
    try:
        text = config_path(codedir).read_text(encoding="utf-8")
    except FileNotFoundError:
        return ConfigRead(None, "missing")
    except (OSError, UnicodeDecodeError):
        return ConfigRead(None, "unreadable")
    try:
        data = YAML(typ="safe", pure=True).load(text)
    except MarkedYAMLError as error:
        mark = error.problem_mark or error.context_mark
        if mark is None:
            return ConfigRead(None, "invalid")
        return ConfigRead(None, "invalid", mark.line + 1, mark.column + 1)
    except Exception:
        return ConfigRead(None, "invalid")
    if not isinstance(data, dict):
        return ConfigRead(None, "invalid")
    return ConfigRead(data, None)
