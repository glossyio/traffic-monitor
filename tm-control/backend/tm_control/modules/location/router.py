"""/api/v1/surveys: the Location page's places, for admins only.

GET lists the places (after reconcile.ensure has brought the store and config.yml into step). An admin can plan a
place (POST), edit or delete one, deploy one (write it and its sensors' headings into Node-RED's config.yml, then wait
for Node-RED to start the deployments), correct a used place's location or one deployment's heading, set or clear a
place's time zone, read and save how each sensor is mounted at the place in use (asking "Did the unit move or turn?"
when it matters), change the precision tmdb stores coordinates at, export the places with their exact coordinates and
zones, start a database copy that holds them (a one-time download link; Node-RED makes the copy), and import planned
places from CSV.

Every write to config.yml or the places store holds app.state.reconcile_lock, so a GET's reconcile never sees half of
one. config.yml is written before the store, so a refused or failed save leaves both as they were. No coordinate,
description, or reason is logged, audited, or put in an error message: audit rows carry the survey id (and the
deployment id, or the precision) only; a mounting correction's row adds the values it changed among the five, and a
zone change's the old and new zone, which identify no place. A zone appears in no log line or error message. A zone
is stored trimmed and only when the device lists it (the Date and time page's list). The mounting rules are
mounting.py's; this module only calls them.
"""

import csv
import io
import logging
import math
import re
import secrets
import time
from functools import cache
from time import sleep
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel, Field

from tm_control.adapters import network, timedate
from tm_control.adapters.nodered import NodeRedError
from tm_control.core.auth import DOWNLOAD_PATH, DOWNLOAD_TOKEN, Audit, User
from tm_control.core.errors import ApiError
from tm_control.core.manifest import MapInfo
from tm_control.modules.auth.deps import client_ip, require_admin
from tm_control.modules.location import reconcile
from tm_control.modules.location.access import config_error, load_config, save_config
from tm_control.modules.location.config import DEFAULT_PRECISION, SENSOR_TYPES, ConfigError, NodeRedConfig
from tm_control.modules.location.coordinates import (
    DEPLOYMENT_ID,
    SURVEY_ID,
    exact,
    new_survey_id,
    point_centre,
    stored,
    valid_heading,
)
from tm_control.modules.location.mounting import (
    FIELDS,
    MOUNTS,
    Change,
    Mount,
    Mounting,
    MountingError,
    SensorKey,
    checked,
    review,
)
from tm_control.modules.location.mounting import read as read_mounting
from tm_control.modules.location.places import Places, SensorHeading, Survey
from tm_control.modules.location.region import LatLon, region
from tm_control.modules.location.zones import ZONE_MAX, read_zone
from tm_control.modules.time.router import _clock, _timezones

log = logging.getLogger(__name__)

router = APIRouter(prefix="/surveys", tags=["location"])

POLL_INTERVAL = 1.0  # seconds between asks for a deploy's new rows
DEPLOY_TIMEOUT = 20.0  # how long a deploy waits for them (decision 6; nginx's read timeout is 60 s)
TEXT_MAX = 200
SENSOR_NAME_MAX = 64
HEADING_TEXT = "a whole number from 0 to 359"
ZONE_COLUMN = "timezone"  # the places CSV's column for a place's zone, after lon
CSV_HEADING_TEXT = f"{HEADING_TEXT}, a compass point (n, ne, e, se, s, sw, w, nw), or blank"
_DIGITS = re.compile(r"[0-9]{1,3}", re.ASCII)  # at most three, so int() never meets a string too long for it

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


class MapSources(BaseModel):
    """Where the browser gets the map; null is off (the install's setting is empty or not https)."""

    style_url: str | None
    region: LatLon | None = None  # where the map opens with no place to start from: the time zone's city


class PlacesState(BaseModel):
    precision: Literal["none", "1", "2"]
    in_use: str | None
    sensors: list[SensorHeading]  # the enabled sensors in config.yml, each with its heading there
    sharing: Literal["none", "data", "exact"]  # what the upload sends: nothing, data, or data and the exact location
    surveys: list[SurveyOut]
    unassigned: Unassigned | None
    reconcile: Literal["done", "waiting_nodered", "config_unreadable"]
    nodered: bool  # whether Node-RED answered the usage counts
    map: MapSources
    clock_timezone: str | None  # the device clock's zone, which a place's needn't match; None when it can't be read


class SurveyIn(BaseModel):
    description: str | None = Field(default=None, max_length=TEXT_MAX)
    lat: float | None = None
    lon: float | None = None
    headings: list[SensorHeading] = Field(default_factory=list, max_length=32)
    # One the device lists; null or blank is none. POST without the key is none; PATCH without it keeps the stored zone.
    timezone: str | None = Field(default=None, max_length=ZONE_MAX)


class TimezoneIn(BaseModel):
    timezone: str | None = Field(max_length=ZONE_MAX)  # required: a name the device lists, or null (or blank) to clear


class DeployIn(BaseModel):
    headings: list[SensorHeading] = Field(default_factory=list, max_length=32)


class DeploymentOut(BaseModel):
    id: str
    started: int | None
    ended: int | None
    lat: float | None
    lon: float | None
    heading_deg: int | None
    pitch_deg: float | None
    height_m: float | None
    view_distance_m: float | None
    mount: str | None
    sensor_type: str
    sensor_name: str
    location_precision: int | None


class DeploymentsOut(BaseModel):
    deployments: list[DeploymentOut]


class DeployOut(BaseModel):
    deployed_at: int  # ms, taken before config.yml was written
    reloaded: bool  # whether Node-RED was seen to start the deployments
    deployments: list[DeploymentOut]  # the place's open deployments
    previous: list[SensorKey]  # after a move: the sensors whose values from the place's last use wait to be confirmed


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


class HeadingCorrection(BaseModel):
    heading_deg: Annotated[int, Field(strict=True)] | None  # whole degrees from 0 to 359; null for none
    reason: str | None = Field(default=None, max_length=TEXT_MAX)


class PreviousMounting(BaseModel):
    """What was last saved for a sensor at the place, beside its heading. A move there records none of it; it is
    offered until a save writes that sensor."""

    pitch_deg: float | None
    height_m: float | None
    view_distance_m: float | None
    measured: Literal["pitch", "distance"] | None
    mount: str | None


class SensorMounting(Mounting):
    camera: str | None  # for a radar: the first enabled camera whose camera_radar names it
    same_as_camera: bool  # camera is set and the radar's five equal that camera's
    deployment_id: str | None  # its open deployment row; None when Node-RED has none or didn't answer
    recorded: bool | None  # whether that row has recorded traffic; None when Node-RED can't say
    previous: PreviousMounting | None  # the place's last values waiting to be confirmed; None when none wait


class MountingState(BaseModel):
    sensors: list[SensorMounting]  # cameras, each followed by its radar; then other radars; then the rest
    mounts: list[Mount]
    nodered: bool  # whether Node-RED answered


class SensorMountingIn(Mounting):
    same_as_camera: bool = False  # take the five and measured from this radar's camera


class MountingIn(BaseModel):
    sensors: list[SensorMountingIn] = Field(max_length=32)  # a sensor left out keeps its values
    moved: bool | None = None  # the answer to "Did the unit move or turn?"
    dry_run: bool = True


class MountingOut(BaseModel):
    saved: bool
    sensors: list[SensorMounting]  # as stored after a save, or as they would be
    changes: list[Change]
    ask: bool
    suggested: Literal["moved", "measured"] | None
    new_deployments: list[SensorKey]
    reloaded: bool | None  # after a save that starts deployments: whether Node-RED was seen to


class DatabaseCopyOut(BaseModel):
    url: str  # a one-time /storefiles link to the copy
    places: int  # how many places' exact locations the copy holds


class ImportIn(BaseModel):
    csv: str = Field(max_length=65536)
    dry_run: bool = True


class ImportRow(BaseModel):
    line: int
    description: str | None
    lat: float | None
    lon: float | None
    headings: list[SensorHeading]
    timezone: str | None


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
    sensor_type, sensor_name = str(row.get("sensorType") or ""), str(row.get("sensorName") or "")
    mounted = read_mounting(sensor_type, sensor_name, row)  # the four as the file's are read: within limits, else None
    return DeploymentOut(
        id=row["id"],
        started=_int(row.get("entryStartDateTime")),
        ended=_int(row.get("entryEndDateTime")),
        lat=number("lat"),
        lon=number("lon"),
        heading_deg=row["heading_deg"] if valid_heading(row.get("heading_deg")) else None,
        pitch_deg=mounted.pitch_deg,
        height_m=mounted.height_m,
        view_distance_m=mounted.view_distance_m,
        mount=mounted.mount,
        sensor_type=sensor_type,
        sensor_name=sensor_name,
        location_precision=_int(precision) if precision is not None else None,
    )


def _deployments(rows: list[dict]) -> list[DeploymentOut]:
    return [found for found in map(_deployment, rows) if found is not None]


def _map_sources(info: MapInfo) -> MapSources:
    """The map's address, off unless it is https."""
    style = info.style_url if info.style_url.startswith("https://") else None
    return MapSources(style_url=style)


def _clock_zone(app_state) -> str | None:
    """The device clock's time zone (fake mode's own, as the Time page does); None when it can't be read."""
    state = app_state.fake_clock.show() if app_state.settings.fake else timedate.show()
    return state.timezone if state else None


def _region(app_state, zone: str | None) -> LatLon | None:
    """The device's region, from the clock's time zone and the Wi-Fi country (fake mode's own)."""
    country = app_state.fake_network.country if app_state.settings.fake else network.wifi_country()
    return region(zone, country)


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
    clock_zone = _clock_zone(app_state)
    sources = _map_sources(app_state.manifest.map)
    if sources.style_url:  # a region is of no use without a map
        sources.region = _region(app_state, clock_zone)
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
        map=sources,
        clock_timezone=clock_zone,
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


def _heading(value) -> int | None:
    if value is not None and not valid_heading(value):
        raise _invalid(f"A heading is {HEADING_TEXT}, or blank.", "headings")
    return value


def _headings(given: list[SensorHeading]) -> list[SensorHeading]:
    """The headings checked, each sensor once, each sensor type one the file can have."""
    found, seen = [], set()
    for item in given:
        key = (item.sensor_type, item.sensor_name)
        if item.sensor_type not in SENSOR_TYPES or not 0 < len(item.sensor_name) <= SENSOR_NAME_MAX:
            raise _invalid("A heading names a sensor type and a sensor.", "headings")
        if key in seen:
            raise _invalid("A sensor has more than one heading.", "headings")
        seen.add(key)
        _heading(item.heading_deg)
        found.append(item)
    return found


def _description(value: str | None) -> str | None:
    text = (value or "").strip()
    return text or None


def _known_zone(text: str, listed) -> bool:
    """Whether trimmed, non-blank text is a zone the device lists (`listed()` reads the list, the Date and time page's;
    a list that can't be read is that page's 500) and has a zone's shape, which config.yml needs to take it back."""
    return text in listed() and read_zone(text) == text


def _zone(app_state, value: str | None) -> str | None:
    """A zone from a request, as the store keeps it: trimmed, a blank one none, and 422 naming the field (never the
    value) for one the device doesn't list."""
    text = (value or "").strip()
    if not text:
        return None
    if not _known_zone(text, lambda: _timezones(_clock(app_state))):
        raise _invalid("The device doesn't know that time zone.", "timezone")
    return text


# Routes. The fixed paths (precision, export, import) come before any /{survey_id} path that could take them.


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
    headings = _headings(body.headings)
    zone = _zone(app_state, body.timezone)
    survey_id = new_survey_id()
    with app_state.reconcile_lock:
        survey = Places(app_state.state).create(
            survey_id, _description(body.description), lat, lon, headings, "ui", "planned", admin.id, timezone=zone
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


@router.get("/export", response_class=Response)
def export_places(request: Request, admin: User = Depends(require_admin)):
    """The places as a CSV with their exact coordinates (five decimals, empty for a place with none) and no
    description, for an admin to keep or hand to the server's operator. The audit row holds the row count only."""
    app_state = request.app.state
    try:
        reconcile.ensure(app_state, admin.id)
    except ConfigError as error:
        raise config_error(error) from None
    text = io.StringIO()
    writer = csv.writer(text, lineterminator="\r\n")
    writer.writerow(["survey_id", "lat", "lon", "timezone", "status", "created_at", "updated_at"])
    count = 0
    for place in Places(app_state.state).list():
        writer.writerow([
            place.id,
            "" if place.lat is None else f"{place.lat:.5f}",
            "" if place.lon is None else f"{place.lon:.5f}",
            place.timezone or "",
            place.status,
            place.created_at,
            place.updated_at,
        ])
        count += 1
    Audit(app_state.state).record(admin.id, "survey.export", str(count))
    return Response(
        text.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="traffic-monitor-places.csv"',
            "Cache-Control": "no-store",
        },
    )


@router.post("/database-copy", response_model=DatabaseCopyOut)
def database_copy(request: Request, response: Response, admin: User = Depends(require_admin)):
    """Hand Node-RED the exact locations of the places this device has been at (in use or used, with a location),
    and answer with a one-time /storefiles link to a copy of the database that holds them in a table of its own.

    The control app never opens the database; Node-RED makes the copy when the link is fetched. A planned place is
    never sent. The audit row, the log, and every message hold the count only: no coordinate, ticket, or link.
    """
    app_state = request.app.state
    try:
        reconcile.ensure(app_state, admin.id)
    except ConfigError as error:
        raise config_error(error) from None
    places = [
        {"survey_id": place.id, "lat": place.lat, "lon": place.lon} for place in Places(app_state.state).located()
    ]
    if not places:
        raise ApiError(
            409,
            "no_exact_locations",
            "No place this device has been at has an exact location, so a copy would hold nothing more than the "
            "download without the box ticked.",
        )
    ticket = secrets.token_hex(16)
    try:
        app_state.nodered.keep_exact_copy(ticket, places)
    except NodeRedError as error:
        raise _nodered_error(error, "The copy wasn't started.") from None
    files = f"tmdb-exact-{ticket}"
    # Always with a token: a browser with a session never spends it, and Android's downloader, which has none, needs it.
    token = app_state.download_grants.issue(admin, client_ip(request), files, time.monotonic())
    Audit(app_state.state).record(admin.id, "survey.database_copy", str(len(places)))
    response.headers["Cache-Control"] = "no-store"
    return {"url": f"{DOWNLOAD_PATH}?files={files}&{DOWNLOAD_TOKEN}={token}", "places": len(places)}


@router.post("/import", response_model=ImportOut)
def import_places(body: ImportIn, request: Request, admin: User = Depends(require_admin)):
    """Check a CSV of planned places (description,lat,lon, then a column per sensor holding its heading, and a
    `timezone` column anywhere after lon) and, unless dry_run, create them all, or none when any line is refused (422
    with the problems in detail)."""
    app_state = request.app.state
    sensors = load_config(app_state).sensors()
    rows, errors = _parse_csv(body.csv, sensors, cache(lambda: _timezones(_clock(app_state))))
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
            places.create(
                survey_id, row.description, row.lat, row.lon, row.headings, "csv", "planned", admin.id,
                timezone=row.timezone,
            )
            created.append(survey_id)
    audit = Audit(app_state.state)
    for survey_id in created:
        audit.record(admin.id, "survey.import", survey_id)
    return ImportOut(rows=rows, errors=[], created=created)


@router.patch("/{survey_id}", response_model=SurveyOut)
def edit_place(survey_id: str, body: SurveyIn, request: Request, admin: User = Depends(require_admin)):
    """Edit a planned place (409 not_planned for one in use or used: correct those instead). The body replaces the
    place's description, point, and headings; a body without `timezone` keeps its zone (null or blank clears it)."""
    app_state = request.app.state
    lat, lon = _pair(body.lat, body.lon)
    headings = _headings(body.headings)
    zone_sent = "timezone" in body.model_fields_set  # absent, not null: a form that doesn't show the zone keeps it
    zone = _zone(app_state, body.timezone) if zone_sent else None
    with app_state.reconcile_lock:
        place = _place(app_state, survey_id)
        if place.status != "planned":
            raise ApiError(409, "not_planned", "Only a planned place can be edited. Correct a used place instead.")
        survey = Places(app_state.state).update_planned(
            place.id, _description(body.description), lat, lon, headings, zone if zone_sent else place.timezone
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
    """Put the place in use: its id, point, zone (blank for none), and each enabled sensor's heading into config.yml (a
    sensor the body leaves out takes the place's stored heading, else the file's), then wait for Node-RED to start the
    deployments. Moving to another place also removes each sensor's other four from the file, at a place used before
    as at a new one: the store keeps the values last saved there, and `previous` names the sensors whose values wait to
    be confirmed by a mounting save.

    Node-RED not answering isn't an error: the file is written, and `reloaded` is false. The reconcile runs first (see
    _reconciled), so a file tmsetup.sh -f reset gets its precision back before the deploy writes the id beside it."""
    app_state = request.app.state
    _reconciled(app_state, admin)
    with app_state.reconcile_lock:
        place = _place(app_state, survey_id)
        config = load_config(app_state)
        enabled = {(s.sensor_type, s.sensor_name): s.heading_deg for s in config.sensors()}
        named = {}
        for item in _headings(body.headings):
            key = (item.sensor_type, item.sensor_name)
            if key not in enabled:
                raise _invalid("A heading names a sensor that isn't enabled in config.yml.", "headings")
            named[key] = item.heading_deg
        kept = {(h.sensor_type, h.sensor_name): h.heading_deg for h in place.headings}
        chosen = {key: named.get(key, kept.get(key, current)) for key, current in enabled.items()}
        switching = config.deployment().survey_id != place.id  # which rows to wait for
        moving = place.status != "in_use"  # the unit goes to another place
        waiting = {key: heading for key, heading in chosen.items() if switching or heading != enabled[key]}

        deployed_at = int(time.time() * 1000)
        config.set_place(place.id, place.lat, place.lon)
        config.set_timezone(place.timezone)  # in the same save, so the new rows carry it from their start
        for (sensor_type, sensor_name), heading in chosen.items():
            config.set_sensor_heading(sensor_type, sensor_name, heading)
            if moving:
                config.set_sensor_mounting(sensor_type, sensor_name, None)  # a move records none of the four
        save_config(app_state, config)  # the file first: a refused save leaves the store as it was
        places = Places(app_state.state)
        places.set_in_use(place.id)
        for (sensor_type, sensor_name), heading in chosen.items():
            places.set_heading(place.id, sensor_type, sensor_name, heading)
        previous = [
            SensorKey(sensor_type=each.sensor_type, sensor_name=each.sensor_name)
            for each in places.unconfirmed(place.id) if _key(each) in chosen
        ] if moving else []
    Audit(app_state.state).record(admin.id, "survey.deploy", place.id)
    reloaded, rows = _wait_for_rows(app_state.nodered, place.id, waiting, deployed_at)
    return DeployOut(deployed_at=deployed_at, reloaded=reloaded, deployments=rows, previous=previous)


def _wait_for_rows(nodered, survey_id: str, waiting: dict, deployed_at: int) -> tuple[bool, list[DeploymentOut]]:
    """Ask Node-RED for the place's rows until every sensor in `waiting` (sensor -> the heading deployed) has its row
    (see _poll_rows).

    A sensor's row is an open one of this place with that heading that started at or after deployed_at, or one Node-RED
    adopted: a row open from before any survey takes the survey's id and keeps its start (the engine's rule 4)."""

    def arrived(rows: list[DeploymentOut]) -> bool:
        started = _started(rows, deployed_at)
        facing = {_key(row): row.heading_deg for row in rows}
        return all(key in started or (key in facing and facing[key] == heading) for key, heading in waiting.items())

    return _poll_rows(nodered, survey_id, arrived)


def _started(rows: list[DeploymentOut], since: int) -> set[tuple[str, str]]:
    """The sensors with a row that started at or after `since` (ms)."""
    return {_key(row) for row in rows if row.started is not None and row.started >= since}


def _poll_rows(nodered, survey_id: str, arrived) -> tuple[bool, list[DeploymentOut]]:
    """Ask Node-RED for the place's open rows until `arrived(rows)`, for up to DEPLOY_TIMEOUT; stop at once when
    Node-RED doesn't answer. Returns whether they arrived (and Node-RED answered), and the open rows as last seen."""
    deadline = time.monotonic() + DEPLOY_TIMEOUT
    rows: list[DeploymentOut] = []
    while True:
        try:
            rows = [row for row in _deployments(nodered.deployments(survey_id)) if row.ended is None]
        except NodeRedError as error:
            if error.code == "unreachable" or time.monotonic() >= deadline:
                return False, []
        else:
            if arrived(rows):
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
    and the rows didn't; correcting again with the same pair re-rounds them. The reconcile runs first (see
    _reconciled), and for the place in use a file that no longer names it by the time the lock is held is refused (409
    config_changed)."""
    app_state = request.app.state
    lat, lon = _pair(body.lat, body.lon)
    _reconciled(app_state, admin)
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
            if config.deployment().survey_id != place.id:
                # writing the id into that file would start deployments without the place's values
                raise _not_the_place(config)
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


@router.put("/{survey_id}/timezone", response_model=SurveyOut)
def set_place_timezone(survey_id: str, body: TimezoneIn, request: Request, admin: User = Depends(require_admin)):
    """Set or clear (null) a place's time zone, whatever its status: config.yml for the place in use, the store (with
    an audit row naming the old and new zone, when it changed), and every one of Node-RED's rows of a place that has
    been used, ended ones too. A change starts no deployment. A 502 means the store and the file changed and the rows
    didn't; saving the same zone again rewrites them. The reconcile runs first (see _reconciled), and for the place in
    use a file that no longer names it by the time the lock is held is refused (409 config_changed)."""
    app_state = request.app.state
    _reconciled(app_state, admin)
    with app_state.reconcile_lock:
        place = _place(app_state, survey_id)
        zone = _zone(app_state, body.timezone)
        if place.status == "in_use":
            config = load_config(app_state)
            if config.deployment().survey_id != place.id:
                raise _not_the_place(config)
            config.set_timezone(zone)
            save_config(app_state, config)  # first, so the follow step never sees the store ahead of the file
        places = Places(app_state.state)
        if zone != place.timezone:
            places.set_timezone(place.id, zone)
            Audit(app_state.state).record(
                admin.id, "survey.timezone", f"{place.id} {_value_text(place.timezone)}>{_value_text(zone)}"
            )
        if place.status != "planned":
            try:
                app_state.nodered.set_timezone(place.id, zone)  # also when unchanged: saving again heals the rows
            except NodeRedError as error:
                raise _nodered_error(
                    error, "The place's time zone changed, but its stored rows weren't updated. Save it again."
                ) from None
        survey = places.get(place.id)
    return _one(app_state, survey)


@router.post("/{survey_id}/deployments/{deployment_id}/heading", response_model=DeploymentOut)
def correct_heading(
    survey_id: str, deployment_id: str, body: HeadingCorrection, request: Request,
    admin: User = Depends(require_admin),
):
    """Correct which way one deployment's sensor faced. For an open deployment of the place in use, the place's heading
    and config.yml's change too, after Node-RED's row, so Node-RED doesn't start a new deployment. Refused (502) while
    Node-RED doesn't answer (decision 12)."""
    app_state = request.app.state
    heading = _heading(body.heading_deg)
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
            app_state.nodered.correct_heading(row.id, heading)
        except NodeRedError as error:
            raise _nodered_error(error) from None
        places = Places(app_state.state)
        if open_here:
            try:
                _write_heading(app_state, row, heading)
            except ApiError:
                _put_row_back(app_state.nodered, row)
                raise
            places.set_heading(place.id, row.sensor_type, row.sensor_name, heading)
        places.record_correction(
            place.id, row.id, "heading_deg", _heading_text(row.heading_deg), _heading_text(heading),
            _description(body.reason), "ui", admin.id,
        )
    Audit(app_state.state).record(admin.id, "survey.correct_heading", f"{place.id} {row.id}")
    return row.model_copy(update={"heading_deg": heading})


def _heading_text(heading_deg: int | None) -> str | None:
    """A heading as a correction row keeps it: the degrees as text, or NULL for none."""
    return None if heading_deg is None else str(heading_deg)


def _write_heading(app_state, row: DeploymentOut, heading_deg: int | None) -> None:
    """The sensor's heading into config.yml, read now so an edit made while Node-RED answered isn't a conflict. A sensor
    no longer in the file has nothing to change: only the row and the place do."""
    config = load_config(app_state)
    try:
        config.set_sensor_heading(row.sensor_type, row.sensor_name, heading_deg)
    except KeyError:
        return
    except ConfigError as error:
        raise config_error(error) from None
    save_config(app_state, config)


def _put_row_back(nodered, row: DeploymentOut) -> None:
    """The file refused the heading, so the row keeps its old one, and a retry records the real old value. Best effort:
    the refusal is what the caller answers."""
    try:
        nodered.correct_heading(row.id, row.heading_deg)
    except NodeRedError as error:
        log.warning("putting a deployment's heading back in Node-RED failed: %s", type(error).__name__)


# Mounting


def _key(item) -> tuple[str, str]:
    return (item.sensor_type, item.sensor_name)


def _refused(message: str, field: str, index: int | None = None) -> ApiError:
    """422 `validation` naming the field refused and, for a sensor of the body, its index in `sensors`."""
    detail = {"field": field} if index is None else {"field": field, "index": index}
    return ApiError(422, "validation", message, detail=detail)


def _refused_body(error: RequestValidationError) -> ApiError:
    """A body pydantic refused, answered as the route's own refusals are: the first error's field, never its value."""
    errors = error.errors()
    where = list(errors[0]["loc"])[1:] if errors else []  # after "body"
    names = [part for part in where if isinstance(part, str)]
    if not names:
        return ApiError(422, "validation", "The request is not valid.")
    index = where[1] if where[0] == "sensors" and len(where) > 1 and isinstance(where[1], int) else None
    return _refused(f"{names[-1]} isn't valid.", names[-1], index)


class _NamedRefusals(APIRoute):
    """A route whose refused body answers like its own refusals (see _refused_body), not with pydantic's list."""

    def get_route_handler(self):
        handler = super().get_route_handler()

        async def named(request):
            try:
                return await handler(request)
            except RequestValidationError as error:
                raise _refused_body(error) from None

        return named


def _in_use(app_state, survey_id: str) -> Survey:
    place = _place(app_state, survey_id)
    if place.status != "in_use":
        raise ApiError(409, "not_in_use", "Only the place in use has a mounting to read or save. Deploy it first.")
    return place


def _reconciled(app_state, admin: User) -> None:
    """Bring the store and config.yml into step first, as GET /surveys does: a file tmsetup.sh -f reset gets the
    place's id, headings, and mounting back before a mounting route reads it. Takes the lock itself."""
    try:
        reconcile.ensure(app_state, admin.id)
    except ConfigError as error:
        raise config_error(error) from None


def _not_the_place(config: NodeRedConfig) -> ApiError:
    """409 config_changed for a file that no longer names the place in use: reset again since the reconcile, or, when
    its survey_id isn't an id (which the reconcile leaves alone, so reloading can't help), where to look."""
    if config.deployment().survey_id_invalid:
        return ApiError(
            409, "config_changed",
            "config.yml's deployment.survey_id isn't a survey id. The Status page's Location check says what to fix.",
        )
    return config_error(ConfigError("changed"))


def _radar_cameras(config: NodeRedConfig) -> dict[tuple[str, str], str]:
    """Each radar an enabled camera names in camera_radar -> the first such camera."""
    found: dict[tuple[str, str], str] = {}
    for camera in config.cameras():
        if camera.enabled and camera.camera_radar is not None:
            found.setdefault(("radars", camera.camera_radar), camera.name)
    return found


def _stored(app_state, survey_id: str) -> tuple[dict, dict]:
    """The place's store rows by sensor as saved for this use, where a row whose other four wait to be confirmed (after
    a move) counts as its heading alone; and those rows as stored, which `previous` offers."""
    places = Places(app_state.state)
    waiting = {_key(each): each for each in places.unconfirmed(survey_id)}
    kept = {
        _key(each): Mounting(sensor_type=each.sensor_type, sensor_name=each.sensor_name, heading_deg=each.heading_deg)
        if _key(each) in waiting else each
        for each in places.mountings(survey_id)
    }
    return kept, waiting


def _with_measured(found: Mounting, kept: Mounting | None) -> Mounting:
    """The file's values with `measured`: the store's when the file holds that one, else the tilt when the file has
    one, else the distance when it has one."""
    holds = {"pitch": found.pitch_deg is not None, "distance": found.view_distance_m is not None}
    if kept is not None and kept.measured is not None and holds[kept.measured]:
        measured = kept.measured
    else:
        measured = next((name for name, held in holds.items() if held), None)
    return found.model_copy(update={"measured": measured})


def _current(config: NodeRedConfig, kept: dict, cameras: dict) -> list[Mounting]:
    """Every enabled sensor as config.yml has it (with `measured`): cameras, each followed by its radar; then the other
    radars; then the rest, each in the file's order."""
    found = [_with_measured(each, kept.get(_key(each))) for each in config.mountings()]
    radar_of = {camera: radar for radar, camera in cameras.items()}
    by_key = {_key(each): each for each in found}
    ordered = []
    for each in found:
        if each.sensor_type == "cameras":
            ordered.append(each)
            radar = by_key.get(radar_of.get(each.sensor_name))
            if radar is not None:
                ordered.append(radar)
    placed = {_key(each) for each in ordered}
    ordered += [each for each in found if each.sensor_type == "radars" and _key(each) not in placed]
    ordered += [each for each in found if each.sensor_type not in ("cameras", "radars")]
    return ordered


def _open_rows(rows: list[DeploymentOut]) -> dict[tuple[str, str], DeploymentOut]:
    """Each sensor's open row (the latest started, should Node-RED have more than one)."""
    open_rows = sorted((row for row in rows if row.ended is None), key=lambda row: row.started or 0)
    return {_key(row): row for row in open_rows}


def _described(
    found: list[Mounting], cameras: dict, open_rows: dict, recorded: dict, waiting: dict
) -> list[SensorMounting]:
    """The sensors as the API answers them: each radar's camera and whether it is mounted as that camera is, each
    sensor's open row and whether it has recorded traffic, and the values that wait to be confirmed (see _stored)."""
    by_key = {_key(each): each for each in found}
    described = []
    for each in found:
        camera = cameras.get(_key(each))
        source = by_key.get(("cameras", camera)) if camera is not None else None
        row = open_rows.get(_key(each))
        described.append(SensorMounting(
            **each.model_dump(),
            camera=camera,
            same_as_camera=source is not None and all(getattr(each, f) == getattr(source, f) for f in FIELDS),
            deployment_id=row.id if row is not None else None,
            recorded=recorded.get(row.id) if row is not None else None,
            previous=_previous(waiting.get(_key(each))),
        ))
    return described


def _previous(stored: Mounting | None) -> PreviousMounting | None:
    if stored is None:
        return None
    return PreviousMounting(**stored.model_dump(include=set(PreviousMounting.model_fields)))


def _requested(given: list[SensorMountingIn], now: list[Mounting], cameras: dict) -> list[Mounting]:
    """Every enabled sensor as the body would leave it, in `now`'s order: a sensor the body names as mounting.checked
    settles it, or with its camera's five and `measured` (the camera's item in the body, else its values now) when
    same_as_camera; any other as it is now. 422 for a sensor that isn't enabled or is named twice, for same_as_camera
    on a sensor with no camera, and for a value mounting.checked refuses; the mount the file holds for the sensor, or
    for a radar its camera's (which same_as_camera copies), passes whatever its key."""
    by_key = {_key(each): each for each in now}
    sent: dict[tuple[str, str], tuple[int, SensorMountingIn]] = {}
    for index, item in enumerate(given):
        key = _key(item)
        if key not in by_key:
            raise _refused("A sensor isn't enabled in config.yml.", "sensor_name", index)
        if key in sent:
            raise _refused("A sensor is named more than once.", "sensor_name", index)
        if item.same_as_camera and key not in cameras:
            raise _refused("Only a radar an enabled camera names can be mounted as it is.", "same_as_camera", index)
        sent[key] = (index, item)
    settled: dict[tuple[str, str], Mounting] = {}
    for key, (index, item) in sent.items():
        if not item.same_as_camera:
            camera_mount = by_key[("cameras", cameras[key])].mount if key in cameras else None
            keep = camera_mount if item.mount == camera_mount else by_key[key].mount
            try:
                settled[key] = checked(item, keep=keep)  # a key typed into the file passes as it is
            except MountingError as error:
                raise _refused(f"{error}.", error.field, index) from None
    for key, (_, item) in sent.items():
        if item.same_as_camera:
            camera = ("cameras", cameras[key])
            source = settled.get(camera, by_key[camera])
            settled[key] = source.model_copy(update={"sensor_type": key[0], "sensor_name": key[1]})
    return [settled.get(_key(each), each) for each in now]


def _five(item) -> tuple:
    return tuple(getattr(item, field) for field in FIELDS)


def _differs(new: Mounting, old: Mounting | None) -> bool:
    """Whether any of the five or `measured` differs; a sensor with no stored row has none of them."""
    if old is None:
        old = Mounting(sensor_type=new.sensor_type, sensor_name=new.sensor_name)
    return _five(new) != _five(old) or new.measured != old.measured


def _value_text(value) -> str:
    return "none" if value is None else str(value)


def _correction_detail(survey_id: str, row: DeploymentOut, new: Mounting) -> str:
    """The audit detail of a row corrected in place: the place, the row, and each of the other four it changed, as
    `name old>new`. The heading has its correction row."""
    changed = [
        f"{field} {_value_text(getattr(row, field))}>{_value_text(getattr(new, field))}"
        for field in FIELDS[1:]
        if getattr(row, field) != getattr(new, field)
    ]
    return " ".join([survey_id, row.id, *changed])


def _put_rows_back(nodered, corrected: list[tuple[DeploymentOut, Mounting]]) -> None:
    """The save failed after these rows were corrected, so each gets its old values back. Best effort: the failure is
    what the caller answers."""
    for row, _ in corrected:
        try:
            nodered.correct_mounting(row.id, {field: getattr(row, field) for field in FIELDS})
        except NodeRedError as error:
            log.warning("putting a deployment's mounting back in Node-RED failed: %s", type(error).__name__)


@router.get("/{survey_id}/mounting", response_model=MountingState)
def place_mounting(survey_id: str, request: Request, admin: User = Depends(require_admin)):
    """How each enabled sensor is mounted at the place in use, as config.yml has it (with which of tilt and distance
    was measured, from the store), each sensor's `previous`, and the usual mounts. Node-RED not answering isn't an
    error: `nodered` is false and no sensor has a deployment or a recorded."""
    app_state = request.app.state
    _reconciled(app_state, admin)
    place = _in_use(app_state, survey_id)
    config = load_config(app_state)
    cameras = _radar_cameras(config)
    kept, waiting = _stored(app_state, place.id)
    found = _current(config, kept, cameras)
    try:
        open_rows = _open_rows(_deployments(app_state.nodered.deployments(place.id)))
        recorded = app_state.nodered.recorded(place.id)
    except NodeRedError:
        return MountingState(sensors=_described(found, cameras, {}, {}, waiting), mounts=list(MOUNTS), nodered=False)
    return MountingState(
        sensors=_described(found, cameras, open_rows, recorded, waiting), mounts=list(MOUNTS), nodered=True
    )


def save_mounting(survey_id: str, body: MountingIn, request: Request, admin: User = Depends(require_admin)):
    """Check (dry_run) or save how the sensors are mounted at the place in use; a sensor the body leaves out keeps its
    values, and nothing is written for it: not its row, its block in config.yml, or its stored mounting. The answer
    lists what changed, whether "Did the unit move or turn?" must be answered (409 answer_needed for a save without
    `moved`), the answer chosen in advance, and which sensors would start a new deployment.

    A save corrects the open row of each sensor whose change is corrected in place, then writes config.yml, then the
    store, so Node-RED starts a deployment only for a sensor that moved. A refused correction or file save puts the
    rows already corrected back. A sensor the save writes has its stored values confirmed, so its `previous` is null
    from then on. A save is refused (502) while Node-RED doesn't answer; a dry run then answers with every sensor's
    recorded unknown. The reconcile runs first (see _reconciled), and a save whose file no longer names
    the place by the time it holds the lock is refused (409 config_changed)."""
    app_state = request.app.state
    _reconciled(app_state, admin)
    with app_state.reconcile_lock:
        place = _in_use(app_state, survey_id)
        config = load_config(app_state)
        if not body.dry_run and config.deployment().survey_id != place.id:
            # the file's values aren't the place's, so saving them would empty it
            raise _not_the_place(config)
        cameras = _radar_cameras(config)
        kept, waiting = _stored(app_state, place.id)
        old = _current(config, kept, cameras)
        new = _requested(body.sensors, old, cameras)
        try:
            open_rows = _open_rows(_deployments(app_state.nodered.deployments(place.id)))
        except NodeRedError as error:
            if not body.dry_run:
                raise _nodered_error(error) from None
            open_rows = {}
        try:
            recorded = app_state.nodered.recorded(place.id)
        except NodeRedError:
            recorded = {}  # every sensor unknown
        found = review(old, new, {key: recorded.get(row.id) for key, row in open_rows.items()}, body.moved)
        answer = {
            "changes": found.changes, "ask": found.ask, "suggested": found.suggested,
            "new_deployments": found.new_deployments, "reloaded": None,
        }
        if body.dry_run:
            return MountingOut(saved=False, sensors=_described(new, cameras, open_rows, recorded, waiting), **answer)
        if found.ask and body.moved is None:
            raise ApiError(
                409, "answer_needed", "Say whether the unit moved or turned, or was measured better, and save again."
            )
        before = {_key(each): each for each in old}
        named = {_key(item) for item in body.sensors}
        written = [
            each for each in new
            if _key(each) in named and (_differs(each, before[_key(each)]) or _differs(each, kept.get(_key(each))))
        ]
        if not written:
            return MountingOut(saved=True, sensors=_described(new, cameras, open_rows, recorded, waiting), **answer)

        starting = {_key(each) for each in found.new_deployments}
        saved_at = int(time.time() * 1000)
        corrected: list[tuple[DeploymentOut, Mounting]] = []
        for each in written:
            row = open_rows.get(_key(each))
            if _key(each) in starting or row is None or _five(row) == _five(each):
                continue
            try:
                app_state.nodered.correct_mounting(row.id, each.model_dump())
            except NodeRedError as error:
                # this row too: the call may have failed after Node-RED changed it (a timeout)
                _put_rows_back(app_state.nodered, [*corrected, (row, each)])
                raise _nodered_error(error) from None
            corrected.append((row, each))
        try:
            for each in written:
                config.set_sensor_mounting(each.sensor_type, each.sensor_name, each)
            save_config(app_state, config)  # before the store: a refused save leaves the store as it was
        except (ConfigError, ApiError) as error:
            _put_rows_back(app_state.nodered, corrected)
            if isinstance(error, ConfigError):
                raise config_error(error) from None
            raise
        places = Places(app_state.state)
        for each in written:
            places.set_mounting(place.id, each)  # confirms what was waiting
            waiting.pop(_key(each), None)
        for row, each in corrected:
            if row.heading_deg != each.heading_deg:
                places.record_correction(
                    place.id, row.id, "heading_deg", _heading_text(row.heading_deg), _heading_text(each.heading_deg),
                    None, "ui", admin.id,
                )
    audit = Audit(app_state.state)
    audit.record(admin.id, "survey.mounting", place.id)
    for row, each in corrected:
        audit.record(admin.id, "survey.correct_mounting", _correction_detail(place.id, row, each))
    if starting:
        answer["reloaded"], latest = _poll_rows(
            app_state.nodered, place.id, lambda rows: starting <= _started(rows, saved_at)
        )
        if latest:
            open_rows = _open_rows(latest)
            # a row this save started has recorded nothing yet; `recorded` was read before it, by the old ids
            recorded = {**recorded, **{
                row.id: False for key, row in open_rows.items()
                if key in starting and row.started is not None and row.started >= saved_at
            }}
    return MountingOut(saved=True, sensors=_described(new, cameras, open_rows, recorded, waiting), **answer)


router.add_api_route(
    "/{survey_id}/mounting", save_mounting, methods=["PUT"], response_model=MountingOut,
    route_class_override=_NamedRefusals,
)


# CSV import


def _sensor_columns(fields: list[str], sensors: list[SensorHeading]) -> tuple[dict, list[str]]:
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


def _parse_csv(text: str, sensors: list[SensorHeading], zones) -> tuple[list[ImportRow], list[ImportProblem]]:
    """The places a CSV describes and, by line, what is wrong with the rest; one problem per line, naming the column,
    never the value. A column headed exactly `timezone` after lon is the place's zone, never a sensor's; `zones()` is
    the device's list, read only when a line has a zone."""
    reader = csv.DictReader(io.StringIO(text))
    try:
        header = [field.strip() for field in (reader.fieldnames or [])]
    except csv.Error:
        return [], [ImportProblem(line=1, message="The first line isn't a CSV header.")]
    if header[:3] != ["description", "lat", "lon"]:
        return [], [ImportProblem(line=1, message="The first line must start with description,lat,lon.")]
    zone_columns = [index for index, field in enumerate(header) if index >= 3 and field == ZONE_COLUMN]
    if len(zone_columns) > 1:
        return [], [ImportProblem(line=1, message=f"Column {zone_columns[1] + 1} is a second timezone column.")]
    columns, unknown = _sensor_columns([field for field in header[3:] if field != ZONE_COLUMN], sensors)
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
                rows.append(_import_row(line, record, columns, zones))
            except ValueError as error:
                errors.append(ImportProblem(line=line, message=str(error)))
    except csv.Error:
        errors.append(ImportProblem(line=reader.line_num, message="This line isn't valid CSV."))
    return rows, errors


def _import_row(line: int, record: dict, columns: dict, zones) -> ImportRow:
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
    headings = []
    for column, (sensor_type, sensor_name) in columns.items():
        text = (record.get(column) or "").strip()
        if not text:
            continue
        heading = point_centre(text)
        if heading is None and _DIGITS.fullmatch(text) and valid_heading(int(text)):
            heading = int(text)
        if heading is None:
            raise ValueError(f"The heading for {column} must be {CSV_HEADING_TEXT}.")
        headings.append(SensorHeading(sensor_type=sensor_type, sensor_name=sensor_name, heading_deg=heading))
    zone = (record.get(ZONE_COLUMN) or "").strip() or None
    if zone is not None and not _known_zone(zone, zones):
        raise ValueError("The time zone isn't one the device knows.")
    if record.get(None):
        raise ValueError("This line has more values than the header has columns.")
    return ImportRow(line=line, description=description, lat=lat, lon=lon, headings=headings, timezone=zone)

