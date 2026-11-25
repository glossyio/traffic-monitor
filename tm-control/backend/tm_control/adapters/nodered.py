"""Node-RED's state: its /tm-internal/ endpoints (127.0.0.1:1880, in the flows' init-config tab), and its config.yml
as the host has it.

status() and config() never raise. The NodeRed client's methods raise NodeRedError, which carries a code and the HTTP
status and never what was sent or answered, because that can hold a survey's coordinates.
"""

import json
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import quote, urlencode

from tm_control.adapters import httpjson
from tm_control.adapters.yamlfile import (  # ConfigRead: what config() returns, named here too
    ConfigRead,
    RoundTripFile,
    read_config,
)

BASE = "http://127.0.0.1:1880/tm-internal"
STATUS_URL = f"{BASE}/status"
TOKEN_HEADER = "X-TM-Internal-Token"
MOUNTING_KEYS = ("heading_deg", "pitch_deg", "height_m", "view_distance_m", "mount")  # what a correction carries


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


def config_file_path(settings, manifest) -> Path:
    """Node-RED's config.yml: beside the fake state directory in fake mode, else under the manifest's codedir."""
    if settings.fake:
        return settings.state_dir.parent / "node-red-tm" / "config" / "config.yml"
    return config_path(manifest.codedir)


def open_config(path) -> RoundTripFile:
    """config.yml for a round-trip edit, in the file's own 4-space indent."""
    return RoundTripFile(path, mapping_indent=4)


class NodeRedError(RuntimeError):
    """Why a call to /tm-internal/ failed. code: unreachable (no answer), refused (401), bad_request (400),
    database_error (500), or unexpected (any other status, or an answer that isn't the JSON expected)."""

    def __init__(self, code: str, status: int | None = None):
        super().__init__(code)
        self.code = code
        self.status = status


_CODES = {401: "refused", 400: "bad_request", 500: "database_error"}


class NodeRed:
    """The /tm-internal/ endpoints, called with the internal token."""

    def __init__(self, token: str):
        self._token = token

    def _call(self, method: str, path: str, query: dict | None = None, body: dict | None = None):
        url = BASE + path + (f"?{urlencode(query)}" if query else "")
        headers = {TOKEN_HEADER: self._token}
        if method == "GET":
            status, data = httpjson.get(url, headers)
        else:
            status, data = httpjson.post(url, json.dumps(body).encode(), "application/json", headers)
        if status is None:
            raise NodeRedError("unreachable")
        if not 200 <= status < 300:
            raise NodeRedError(_CODES.get(status, "unexpected"), status)
        if not data:
            return None
        try:
            return json.loads(data)
        except (ValueError, RecursionError):
            raise NodeRedError("unexpected", status) from None

    def _object(self, path: str, query: dict | None = None) -> dict:
        value = self._call("GET", path, query)
        if not isinstance(value, dict):
            raise NodeRedError("unexpected")
        return value

    def _rows(self, path: str, key: str, query: dict | None = None) -> list[dict]:
        rows = self._object(path, query).get(key)
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            raise NodeRedError("unexpected")
        return rows

    def report(self) -> dict:
        """The status body."""
        return self._object("/status")

    def deployments(self, survey_id: str) -> list[dict]:
        return self._rows("/deployments", "deployments", {"survey_id": survey_id})

    def usage(self) -> list[dict]:
        return self._rows("/surveys/usage", "surveys")

    def events(self, survey_id: str) -> dict:
        return self._object(f"/surveys/{quote(survey_id, safe='')}/events")

    def set_precision(self, precision: str) -> None:
        self._call("POST", "/deployments/precision", body={"precision": precision})

    def correct_location(self, survey_id: str, lat: float, lon: float) -> None:
        self._call("POST", f"/surveys/{quote(survey_id, safe='')}/location", body={"lat": lat, "lon": lon})

    def correct_heading(self, deployment_id: str, heading_deg: int | None) -> None:
        """Rewrite one deployment row's heading (whole degrees from 0 to 359, or None for none)."""
        self._call(
            "POST", f"/deployments/{quote(deployment_id, safe='')}/heading", body={"heading_deg": heading_deg}
        )

    def correct_mounting(self, deployment_id: str, values: Mapping) -> None:
        """Rewrite one deployment row's heading, tilt, height, view distance, and mount in place; a value of None clears
        it. `values` must hold all five (a KeyError for a missing one, so a left-out key is never sent as a clear);
        anything else in it is not sent."""
        self._call(
            "POST",
            f"/deployments/{quote(deployment_id, safe='')}/mounting",
            body={key: values[key] for key in MOUNTING_KEYS},
        )

    def recorded(self, survey_id: str) -> dict[str, bool | None]:
        """For each open deployment of the survey: whether it has recorded traffic (True or False), or None when
        Node-RED can't say (a sensor type with no rule)."""
        found = self._object(f"/surveys/{quote(survey_id, safe='')}/recorded").get("deployments")
        if not isinstance(found, dict) or not all(value is None or isinstance(value, bool) for value in found.values()):
            raise NodeRedError("unexpected")
        return dict(found)

    def keep_exact_copy(self, ticket: str, places: list[dict]) -> None:
        """Hand Node-RED the exact locations of places for one database copy, under a ticket it keeps for ten minutes."""
        self._call("POST", "/database/exact-copy", body={"ticket": ticket, "places": places})

    def post_setup(self, body: dict) -> None:
        """Hand Node-RED a setup snapshot (the control app's setup history); it answers 200 with {"changed": n}, the number of rows it opened."""
        self._call("POST", "/setup", body=body)

    def after_config_write(self) -> None:
        """Called after config.yml is saved. Node-RED's watch node re-reads the file by itself, so this does nothing;
        a test double overrides it to apply the change."""
