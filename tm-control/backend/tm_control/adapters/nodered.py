"""Node-RED's state: its internal status endpoint (127.0.0.1:1880, in the flows' tm-control status group), and its
config.yml as the host has it.

Neither function raises.
"""

from pathlib import Path

from tm_control.adapters import httpjson
from tm_control.adapters.yamlfile import ConfigRead, read_config  # ConfigRead: what config() returns, named here too

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


def config(codedir) -> ConfigRead:
    """config.yml parsed, or why it couldn't be; nothing of the file's content is kept when it doesn't parse."""
    return read_config(config_path(codedir))
