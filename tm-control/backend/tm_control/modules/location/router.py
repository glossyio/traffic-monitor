"""/api/v1/surveys: the Location page's places, for admins only.

GET lists the places (after reconcile.ensure has brought the store and config.yml into step). An admin can plan a
place (POST), edit or delete one, deploy one (write it and its bearings into Node-RED's config.yml, then wait for
Node-RED to start the deployments), correct a used place's location or one deployment's bearing, change the precision
tmdb stores coordinates at, and import planned places from CSV.

Every write to config.yml or the places store holds app.state.reconcile_lock, so a GET's reconcile never sees half of
one. config.yml is written before the store, so a refused or failed save leaves both as they were. No coordinate,
description, or reason is logged, audited, or put in an error message: audit rows carry the survey id (and the
deployment id, or the precision) only.
"""

import csv
import io
import logging
import math
import time
from time import sleep
from typing import Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field

from tm_control.adapters.nodered import NodeRedError
from tm_control.core.auth import Audit, User
from tm_control.core.errors import ApiError
from tm_control.modules.auth.deps import require_admin
from tm_control.modules.location import reconcile
from tm_control.modules.location.access import config_error, load_config, save_config
from tm_control.modules.location.config import DEFAULT_PRECISION, SENSOR_TYPES, ConfigError, NodeRedConfig
from tm_control.modules.location.coordinates import (
    DEPLOYMENT_ID,
    SURVEY_ID,
    exact,
    new_survey_id,
    normalize_bearing,
    stored,
)
from tm_control.modules.location.places import Bearing, Places, Survey

log = logging.getLogger(__name__)

router = APIRouter(prefix="/surveys", tags=["location"])

POLL_INTERVAL = 1.0  # seconds between asks for a deploy's new rows
DEPLOY_TIMEOUT = 20.0  # how long a deploy waits for them (decision 6; nginx's read timeout is 60 s)
TEXT_MAX = 200
SENSOR_NAME_MAX = 64
BEARING_TEXT = "one of n, s, e, w, ne, nw, se, sw, or blank"

NODERED_MESSAGES = {
    "unreachable": "Node-RED didn't answer.",
    "refused": "Node-RED refused tm-control: the internal token doesn't match; re-run tmsetup.sh -t node-red-tm.",
}


# Models


class SurveyOut(Survey):
    stored_lat: float | None  # lat and lon as tmdb stores them at the device's precision
    stored_lon: float | None
    first_used: int | None  # ms: the first deployment's start
    last_used: int | None  # ms: the latest end of a closed deployment
    open_count: int
    deployment_count: int
    imported: bool  # created from the pre-migration tmdb backup


class Unassigned(BaseModel):
    """The deployment rows recorded before any place was: counted, not listed."""

    deployment_count: int
    first_start: int | None
    last_end: int | None


class PlacesState(BaseModel):
    precision: Literal["none", "1", "2"]
    in_use: str | None
    sensors: list[Bearing]  # the enabled sensors in config.yml, each with its bearing there
    sharing: Literal["data", "none"]
    surveys: list[SurveyOut]
    unassigned: Unassigned | None
    reconcile: Literal["done", "waiting_nodered", "config_unreadable"]
    nodered: bool  # whether Node-RED answered the usage counts


class SurveyIn(BaseModel):
    description: str | None = Field(default=None, max_length=TEXT_MAX)
    lat: float | None = None
    lon: float | None = None
    bearings: list[Bearing] = Field(default_factory=list, max_length=32)


class DeployIn(BaseModel):
    bearings: list[Bearing] = Field(default_factory=list, max_length=32)


class DeploymentOut(BaseModel):
    id: str
    started: int | None
    ended: int | None
    lat: float | None
    lon: float | None
    bearing: str
    sensor_type: str
    sensor_name: str
    location_precision: int | None


class DeploymentsOut(BaseModel):
    deployments: list[DeploymentOut]


class DeployOut(BaseModel):
    deployed_at: int  # ms, taken before config.yml was written
    reloaded: bool  # whether Node-RED was seen to start the deployments
    deployments: list[DeploymentOut]  # the place's open deployments


class EventsOut(BaseModel):
    event_count: int
    first_event: int | None  # Unix seconds
    last_event: int | None


class PrecisionIn(BaseModel):
    precision: Literal["none", "1", "2"]
    round_stored: bool = False  # also lower the precision of every row already stored


class LocationCorrection(BaseModel):
    lat: float
    lon: float
    reason: str | None = Field(default=None, max_length=TEXT_MAX)


class BearingCorrection(BaseModel):
    bearing: str = Field(max_length=16)
    reason: str | None = Field(default=None, max_length=TEXT_MAX)


class ImportIn(BaseModel):
    csv: str = Field(max_length=65536)
    dry_run: bool = True


class ImportRow(BaseModel):
    line: int
    description: str | None
    lat: float | None
    lon: float | None
    bearings: list[Bearing]


class ImportProblem(BaseModel):
    line: int
    message: str


class ImportOut(BaseModel):
    rows: list[ImportRow]
    errors: list[ImportProblem]
    created: list[str]


# Errors


def _nodered_error(error: NodeRedError, message: str | None = None) -> ApiError:
    text = NODERED_MESSAGES.get(error.code, "Node-RED answered an error.")
    return ApiError(502, "nodered_error", f"{message} {text}" if message else text)


def _invalid(message: str, field: str | None = None) -> ApiError:
    return ApiError(422, "validation", message, detail={"field": field} if field else None)


# Reading


def _finite(value) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def _int(value) -> int | None:
    return int(value) if _finite(value) else None


def _place(app_state, survey_id: str) -> Survey:
    """The place by id; 404 for an id that isn't one or no place has."""
    survey_id = survey_id.lower()
    found = Places(app_state.state).get(survey_id) if SURVEY_ID.fullmatch(survey_id) else None
    if found is None:
        raise ApiError(404, "not_found", "There is no such place.")
    return found


def _usage(app_state) -> tuple[dict, dict | None, bool]:
    """Node-RED's usage by survey id, the group with no survey id, and whether Node-RED answered."""
    try:
        groups = app_state.nodered.usage()
    except NodeRedError:
        return {}, None, False
    by_id, unassigned = {}, None
    for group in groups:
        survey_id = group.get("survey_id")
        if survey_id is None:
            unassigned = group
        elif isinstance(survey_id, str):
            by_id[survey_id.lower()] = group
    return by_id, unassigned, True


def _survey_out(survey: Survey, precision: str, usage: dict) -> SurveyOut:
    group = usage.get(survey.id, {})
    stored_lat, stored_lon = stored(survey.lat, survey.lon, precision)
    return SurveyOut(
        **survey.model_dump(),
        stored_lat=stored_lat,
        stored_lon=stored_lon,
        first_used=_int(group.get("first_start")),
        last_used=_int(group.get("last_end")),
        open_count=_int(group.get("open_count")) or 0,
        deployment_count=_int(group.get("deployment_count")) or 0,
        imported=survey.source == "imported_backup",
    )


def _one(app_state, survey: Survey, ask_nodered: bool = True) -> SurveyOut:
    """One place as the API answers it, with Node-RED's counts when asked and it answers."""
    try:
        precision = NodeRedConfig(app_state.config_path).deployment().precision
    except ConfigError:
        precision = DEFAULT_PRECISION
    usage = _usage(app_state)[0] if ask_nodered else {}
    return _survey_out(survey, precision, usage)


def _deployment(row: dict) -> DeploymentOut | None:
    """A Node-RED deployment row in the API's shape; None for one without an id."""
    if not isinstance(row.get("id"), str):
        return None

    def number(key):
        value = row.get(key)
        return float(value) if _finite(value) else None

    precision = row.get("location_precision")
    return DeploymentOut(
        id=row["id"],
        started=_int(row.get("entryStartDateTime")),
        ended=_int(row.get("entryEndDateTime")),
        lat=number("lat"),
        lon=number("lon"),
        bearing=row["bearing"] if isinstance(row.get("bearing"), str) else "",
        sensor_type=str(row.get("sensorType") or ""),
        sensor_name=str(row.get("sensorName") or ""),
        location_precision=_int(precision) if precision is not None else None,
    )


def _deployments(rows: list[dict]) -> list[DeploymentOut]:
    return [found for found in map(_deployment, rows) if found is not None]


def _state(request: Request, admin: User) -> PlacesState:
    app_state = request.app.state
    try:
        outcome = reconcile.ensure(app_state, admin.id)
    except ConfigError as error:
        raise config_error(error) from None
    precision, sensors, sharing = DEFAULT_PRECISION, [], "none"
    try:
        config = NodeRedConfig(app_state.config_path)
    except ConfigError:
        pass  # reconcile says config_unreadable; the places are listed all the same
    else:
        precision, sensors, sharing = config.deployment().precision, config.sensors(), config.sharing()
    usage, unassigned, answered = _usage(app_state)
    places = Places(app_state.state)
    current = places.in_use()
    return PlacesState(
        precision=precision,
        in_use=current.id if current else None,
        sensors=sensors,
        sharing=sharing,
        surveys=[_survey_out(survey, precision, usage) for survey in places.list()],
        unassigned=None if unassigned is None else Unassigned(
            deployment_count=_int(unassigned.get("deployment_count")) or 0,
            first_start=_int(unassigned.get("first_start")),
            last_end=_int(unassigned.get("last_end")),
        ),
        reconcile=outcome.state,
        nodered=answered,
    )


# Checking input


def _pair(lat, lon) -> tuple[float | None, float | None]:
    """The pair quantised to five places; 422 naming the field for one that isn't a coordinate or a half-blank pair."""
    try:
        lat, lon = exact(lat, "lat"), exact(lon, "lon")
    except ValueError as error:
        raise _invalid(f"{error}.", str(error).split()[0]) from None
    if (lat is None) != (lon is None):
        raise _invalid("Enter both lat and lon, or neither.", "lon" if lon is None else "lat")
    return lat, lon


def _bearing(value) -> str:
    bearing = normalize_bearing(value)
    if bearing is None:
        raise _invalid(f"A bearing is {BEARING_TEXT}.", "bearings")
    return bearing


def _bearings(given: list[Bearing]) -> list[Bearing]:
    """The bearings normalised, each sensor once, each sensor type one the file can have."""
    found, seen = [], set()
    for item in given:
        key = (item.sensor_type, item.sensor_name)
        if item.sensor_type not in SENSOR_TYPES or not 0 < len(item.sensor_name) <= SENSOR_NAME_MAX:
            raise _invalid("A bearing names a sensor type and a sensor.", "bearings")
        if key in seen:
            raise _invalid("A sensor has more than one bearing.", "bearings")
        seen.add(key)
        found.append(item.model_copy(update={"bearing": _bearing(item.bearing)}))
    return found


def _description(value: str | None) -> str | None:
    text = (value or "").strip()
    return text or None


# Routes. The fixed paths (precision, import) come before any /{survey_id} path that could take them.


@router.get("", response_model=PlacesState)
def list_places(request: Request, admin: User = Depends(require_admin)):
    """The places, after the store and config.yml are brought into step. Node-RED not answering isn't an error here:
    the places are listed with no counts and `nodered` false."""
    return _state(request, admin)


@router.post("", status_code=201, response_model=SurveyOut)
def create_place(body: SurveyIn, request: Request, admin: User = Depends(require_admin)):
    """Plan a place."""
    app_state = request.app.state
    lat, lon = _pair(body.lat, body.lon)
    bearings = _bearings(body.bearings)
    survey_id = new_survey_id()
    with app_state.reconcile_lock:
        survey = Places(app_state.state).create(
            survey_id, _description(body.description), lat, lon, bearings, "ui", "planned", admin.id
        )
    Audit(app_state.state).record(admin.id, "survey.create", survey_id)
    return _one(app_state, survey, ask_nodered=False)


@router.put("/precision", response_model=PlacesState)
def set_precision(body: PrecisionIn, request: Request, admin: User = Depends(require_admin)):
    """Write database_precision into config.yml (Node-RED re-rounds the open rows to a coarser one), and with
    round_stored also lower every row already stored."""
    app_state = request.app.state
    with app_state.reconcile_lock:
        config = load_config(app_state)
        config.set_precision(body.precision)
        save_config(app_state, config)
        # Now, not at the next reconcile: on a file that lost its survey id, that run would put the old one back.
        Places(app_state.state).keep_precision(body.precision)
    Audit(app_state.state).record(admin.id, "survey.precision", body.precision)
    if body.round_stored:
        try:
            app_state.nodered.set_precision(body.precision)
        except NodeRedError as error:
            raise _nodered_error(
                error, "config.yml now has the new precision, but the stored rows weren't changed."
            ) from None
    return _state(request, admin)


@router.post("/import", response_model=ImportOut)
def import_places(body: ImportIn, request: Request, admin: User = Depends(require_admin)):
    """Check a CSV of planned places (description,lat,lon, then a column per sensor holding its bearing) and, unless
    dry_run, create them all, or none when any line is refused (422 with the problems in detail)."""
    app_state = request.app.state
    sensors = load_config(app_state).sensors()
    rows, errors = _parse_csv(body.csv, sensors)
    if body.dry_run:
        return ImportOut(rows=rows, errors=errors, created=[])
    if errors:
        raise ApiError(
            422, "validation", "Some lines can't be imported; nothing was created.",
            detail=[problem.model_dump() for problem in errors],
        )
    created = []
    with app_state.reconcile_lock:
        places = Places(app_state.state)
        for row in rows:
            survey_id = new_survey_id()
            places.create(survey_id, row.description, row.lat, row.lon, row.bearings, "csv", "planned", admin.id)
            created.append(survey_id)
    audit = Audit(app_state.state)
    for survey_id in created:
        audit.record(admin.id, "survey.import", survey_id)
    return ImportOut(rows=rows, errors=[], created=created)


@router.patch("/{survey_id}", response_model=SurveyOut)
def edit_place(survey_id: str, body: SurveyIn, request: Request, admin: User = Depends(require_admin)):
    """Edit a planned place (409 not_planned for one in use or used: correct those instead)."""
    app_state = request.app.state
    lat, lon = _pair(body.lat, body.lon)
    bearings = _bearings(body.bearings)
    with app_state.reconcile_lock:
        place = _place(app_state, survey_id)
        if place.status != "planned":
            raise ApiError(409, "not_planned", "Only a planned place can be edited. Correct a used place instead.")
        survey = Places(app_state.state).update_planned(
            place.id, _description(body.description), lat, lon, bearings
        )
    Audit(app_state.state).record(admin.id, "survey.update", place.id)
    return _one(app_state, survey, ask_nodered=False)


@router.delete("/{survey_id}", status_code=204, response_class=Response)
def delete_place(survey_id: str, request: Request, admin: User = Depends(require_admin)):
    """Delete a place and its corrections (409 in_use for the place in use). Node-RED's rows keep its id."""
    app_state = request.app.state
    with app_state.reconcile_lock:
        place = _place(app_state, survey_id)
        if place.status == "in_use":
            raise ApiError(409, "in_use", "The place in use can't be deleted. Deploy another place first.")
        Places(app_state.state).delete(place.id)
    Audit(app_state.state).record(admin.id, "survey.delete", place.id)
    return Response(status_code=204)


@router.post("/{survey_id}/deploy", response_model=DeployOut)
def deploy_place(survey_id: str, body: DeployIn, request: Request, admin: User = Depends(require_admin)):
    """Put the place in use: its id, point, and each enabled sensor's bearing into config.yml (a sensor the body leaves
    out takes the place's stored bearing, else the file's), then wait for Node-RED to start the deployments.

    Node-RED not answering isn't an error: the file is written, and `reloaded` is false."""
    app_state = request.app.state
    with app_state.reconcile_lock:
        place = _place(app_state, survey_id)
        config = load_config(app_state)
        enabled = {(s.sensor_type, s.sensor_name): s.bearing for s in config.sensors()}
        named = {}
        for item in _bearings(body.bearings):
            key = (item.sensor_type, item.sensor_name)
            if key not in enabled:
                raise _invalid("A bearing names a sensor that isn't enabled in config.yml.", "bearings")
            named[key] = item.bearing
        kept = {(b.sensor_type, b.sensor_name): b.bearing for b in place.bearings}
        chosen = {key: named.get(key, kept.get(key, current)) for key, current in enabled.items()}
        switching = config.deployment().survey_id != place.id
        waiting = {key: bearing for key, bearing in chosen.items() if switching or bearing != enabled[key]}

        deployed_at = int(time.time() * 1000)
        config.set_place(place.id, place.lat, place.lon)
        for (sensor_type, sensor_name), bearing in chosen.items():
            config.set_sensor_bearing(sensor_type, sensor_name, bearing)
        save_config(app_state, config)  # the file first: a refused save leaves the store as it was
        places = Places(app_state.state)
        places.set_in_use(place.id)
        for (sensor_type, sensor_name), bearing in chosen.items():
            places.set_bearing(place.id, sensor_type, sensor_name, bearing)
    Audit(app_state.state).record(admin.id, "survey.deploy", place.id)
    reloaded, rows = _wait_for_rows(app_state.nodered, place.id, waiting, deployed_at)
    return DeployOut(deployed_at=deployed_at, reloaded=reloaded, deployments=rows)


def _wait_for_rows(nodered, survey_id: str, waiting: dict, deployed_at: int) -> tuple[bool, list[DeploymentOut]]:
    """Ask Node-RED for the place's rows until every sensor in `waiting` (sensor -> the bearing deployed) has its row,
    for up to DEPLOY_TIMEOUT; stop at once when Node-RED doesn't answer. Returns whether they all appeared (and Node-RED
    answered), and the place's open rows as last seen.

    A sensor's row is an open one of this place with that bearing that started at or after deployed_at, or one Node-RED
    adopted: a row open from before any survey takes the survey's id and keeps its start (the engine's rule 4)."""
    deadline = time.monotonic() + DEPLOY_TIMEOUT
    rows: list[DeploymentOut] = []
    while True:
        try:
            rows = [row for row in _deployments(nodered.deployments(survey_id)) if row.ended is None]
        except NodeRedError as error:
            if error.code == "unreachable" or time.monotonic() >= deadline:
                return False, []
        else:
            started = {
                (row.sensor_type, row.sensor_name) for row in rows
                if row.started is not None and row.started >= deployed_at
            }
            facing = {(row.sensor_type, row.sensor_name): row.bearing.strip().lower() for row in rows}
            if all(key in started or facing.get(key) == bearing for key, bearing in waiting.items()):
                return True, rows
            if time.monotonic() >= deadline:
                return False, rows
        sleep(POLL_INTERVAL)


@router.get("/{survey_id}/deployments", response_model=DeploymentsOut)
def place_deployments(survey_id: str, request: Request, admin: User = Depends(require_admin)):
    """The place's deployments, oldest first."""
    app_state = request.app.state
    place = _place(app_state, survey_id)
    try:
        rows = app_state.nodered.deployments(place.id)
    except NodeRedError as error:
        raise _nodered_error(error) from None
    return DeploymentsOut(deployments=_deployments(rows))


@router.get("/{survey_id}/events", response_model=EventsOut)
def place_events(survey_id: str, request: Request, admin: User = Depends(require_admin)):
    """How many events the place's deployments recorded, and when the first and last began."""
    app_state = request.app.state
    place = _place(app_state, survey_id)
    try:
        found = app_state.nodered.events(place.id)
    except NodeRedError as error:
        raise _nodered_error(error) from None
    return EventsOut(
        event_count=_int(found.get("event_count")) or 0,
        first_event=_int(found.get("first_event")),
        last_event=_int(found.get("last_event")),
    )


@router.post("/{survey_id}/location", response_model=SurveyOut)
def correct_location(survey_id: str, body: LocationCorrection, request: Request, admin: User = Depends(require_admin)):
    """Correct where a used or in-use place was: the store (with a correction row), config.yml for the place in use,
    and Node-RED's rows, re-rounded to the precision each was stored at. A 502 means the store and the file changed
    and the rows didn't; correcting again with the same pair re-rounds them."""
    app_state = request.app.state
    lat, lon = _pair(body.lat, body.lon)
    with app_state.reconcile_lock:
        place = _place(app_state, survey_id)
        if place.status == "planned":
            raise ApiError(409, "not_used", "A planned place hasn't been used yet. Edit it instead.")
        if place.lat is None or place.lon is None:
            raise ApiError(
                409, "no_location", "This place has no location to correct. Plan a new place with one and deploy it."
            )
        if place.status == "in_use":
            config = load_config(app_state)
            config.set_place(place.id, lat, lon)
            save_config(app_state, config)  # first, so the follow step never sees the store ahead of the file
        places = Places(app_state.state)
        if (place.lat, place.lon) != (lat, lon):
            places.set_point(place.id, lat, lon)
            places.record_correction(
                place.id, None, "location", reconcile.point_text(place.lat, place.lon),
                reconcile.point_text(lat, lon), _description(body.reason), "ui", admin.id,
            )
        Audit(app_state.state).record(admin.id, "survey.correct_location", place.id)
        try:
            app_state.nodered.correct_location(place.id, lat, lon)
        except NodeRedError as error:
            raise _nodered_error(
                error, "The place's location changed, but its stored rows weren't re-rounded. Correct it again."
            ) from None
        survey = places.get(place.id)
    return _one(app_state, survey)


@router.post("/{survey_id}/deployments/{deployment_id}/bearing", response_model=DeploymentOut)
def correct_bearing(
    survey_id: str, deployment_id: str, body: BearingCorrection, request: Request,
    admin: User = Depends(require_admin),
):
    """Correct which way one deployment's sensor faced. For an open deployment of the place in use, the place's bearing
    and config.yml's change too, after Node-RED's row, so Node-RED doesn't start a new deployment. Refused (502) while
    Node-RED doesn't answer (decision 12)."""
    app_state = request.app.state
    bearing = _bearing(body.bearing)
    if not DEPLOYMENT_ID.fullmatch(deployment_id):
        raise ApiError(404, "not_found", "There is no such deployment.")
    with app_state.reconcile_lock:
        place = _place(app_state, survey_id)
        try:
            rows = _deployments(app_state.nodered.deployments(place.id))
        except NodeRedError as error:
            raise _nodered_error(error) from None
        row = next((found for found in rows if found.id == deployment_id), None)
        if row is None:
            raise ApiError(404, "not_found", "There is no such deployment.")
        open_here = row.ended is None and place.status == "in_use"
        try:
            app_state.nodered.correct_bearing(row.id, bearing)
        except NodeRedError as error:
            raise _nodered_error(error) from None
        places = Places(app_state.state)
        if open_here:
            try:
                _write_bearing(app_state, row, bearing)
            except ApiError:
                _put_row_back(app_state.nodered, row)
                raise
            places.set_bearing(place.id, row.sensor_type, row.sensor_name, bearing)
        places.record_correction(
            place.id, row.id, "bearing", row.bearing, bearing, _description(body.reason), "ui", admin.id
        )
    Audit(app_state.state).record(admin.id, "survey.correct_bearing", f"{place.id} {row.id}")
    return row.model_copy(update={"bearing": bearing})


def _write_bearing(app_state, row: DeploymentOut, bearing: str) -> None:
    """The sensor's bearing into config.yml, read now so an edit made while Node-RED answered isn't a conflict. A sensor
    no longer in the file has nothing to change: only the row and the place do."""
    config = load_config(app_state)
    try:
        config.set_sensor_bearing(row.sensor_type, row.sensor_name, bearing)
    except KeyError:
        return
    except ConfigError as error:
        raise config_error(error) from None
    save_config(app_state, config)


def _put_row_back(nodered, row: DeploymentOut) -> None:
    """The file refused the bearing, so the row keeps its old one, and a retry records the real old value. Best effort:
    the refusal is what the caller answers."""
    try:
        nodered.correct_bearing(row.id, row.bearing)
    except NodeRedError as error:
        log.warning("putting a deployment's bearing back in Node-RED failed: %s", type(error).__name__)


# CSV import


def _sensor_columns(fields: list[str], sensors: list[Bearing]) -> tuple[dict, list[str]]:
    """Each sensor column's (sensor_type, sensor_name), from `<type>.<name>` or a `<name>` only one sensor has; and the
    columns that name no enabled sensor."""
    enabled = [(s.sensor_type, s.sensor_name) for s in sensors]
    columns, unknown = {}, []
    for field in fields:
        dotted = tuple(field.split(".", 1))
        if dotted in enabled and dotted not in columns.values():
            columns[field] = dotted
            continue
        matches = [key for key in enabled if key[1] == field]
        if len(matches) == 1 and matches[0] not in columns.values():
            columns[field] = matches[0]
        else:
            unknown.append(field)  # no such sensor, two with that name, or a sensor named twice
    return columns, unknown


def _parse_csv(text: str, sensors: list[Bearing]) -> tuple[list[ImportRow], list[ImportProblem]]:
    """The places a CSV describes and, by line, what is wrong with the rest; one problem per line, naming the column,
    never the value."""
    reader = csv.DictReader(io.StringIO(text))
    try:
        header = [field.strip() for field in (reader.fieldnames or [])]
    except csv.Error:
        return [], [ImportProblem(line=1, message="The first line isn't a CSV header.")]
    if header[:3] != ["description", "lat", "lon"]:
        return [], [ImportProblem(line=1, message="The first line must start with description,lat,lon.")]
    columns, unknown = _sensor_columns(header[3:], sensors)
    if unknown:
        # By position, not by name: a header cell can hold anything, and an error message repeats nothing sent.
        numbers = ", ".join(str(header.index(field) + 1) for field in unknown)
        return [], [ImportProblem(
            line=1, message=f"Column {numbers} doesn't name an enabled sensor (or names one twice).",
        )]
    reader.fieldnames = header
    rows, errors = [], []
    try:
        for record in reader:
            line = reader.line_num
            try:
                rows.append(_import_row(line, record, columns))
            except ValueError as error:
                errors.append(ImportProblem(line=line, message=str(error)))
    except csv.Error:
        errors.append(ImportProblem(line=reader.line_num, message="This line isn't valid CSV."))
    return rows, errors


def _import_row(line: int, record: dict, columns: dict) -> ImportRow:
    """One CSV record as a place; ValueError, with a message that names no value, for one that can't be."""
    try:
        lat, lon = exact(record.get("lat"), "lat"), exact(record.get("lon"), "lon")
    except ValueError as error:
        raise ValueError(f"{error}.") from None
    if (lat is None) != (lon is None):
        raise ValueError("Enter both lat and lon, or neither.")
    description = _description(record.get("description"))
    if description is not None and len(description) > TEXT_MAX:
        raise ValueError(f"The description is longer than {TEXT_MAX} characters.")
    bearings = []
    for column, (sensor_type, sensor_name) in columns.items():
        bearing = normalize_bearing(record.get(column))
        if bearing is None:
            raise ValueError(f"The bearing for {column} must be {BEARING_TEXT}.")
        if bearing:
            bearings.append(Bearing(sensor_type=sensor_type, sensor_name=sensor_name, bearing=bearing))
    if record.get(None):
        raise ValueError("This line has more values than the header has columns.")
    return ImportRow(line=line, description=description, lat=lat, lon=lon, bearings=bearings)

