"""Keep the places store and Node-RED's config.yml in step.

Once per unit (the device table's surveys_reconciled_at): on a fresh unit with nothing in the file, create the first
place and write its id; on a unit upgraded from a release, import the places the pre-migration tmdb backup holds and
work out which one is in use. Every run after that: follow a hand edit of the file, so a survey_id no place has becomes
a place, and changed coordinates become a correction of the place in use.

Runs at claim, on every GET /surveys, and on every status report (decision 5), always under app_state.reconcile_lock.
Nothing here logs a coordinate, a description, an id, or anything read from a file: only exception class names and
counts.
"""

import logging
import math
import sqlite3
from collections import Counter
from contextlib import closing
from pathlib import Path
from typing import Literal
from urllib.parse import quote

from pydantic import BaseModel

from tm_control.adapters.nodered import NodeRedError
from tm_control.modules.location.config import DEFAULT_PRECISION, ConfigError, Deployment, NodeRedConfig
from tm_control.modules.location.coordinates import exact, new_survey_id, normalize_survey_id
from tm_control.modules.location.places import Bearing, Places, Survey

log = logging.getLogger(__name__)

# What tmdb_migrate.py leaves before migrating: tmdb-v<version>-<UTC stamp>.sqlite. A unit upgraded from a release is
# at version 0; one that ran a development build with the baseline is at 1. Either holds the exact coordinates.
BACKUP_GLOB = "tmdb-v[01]-*.sqlite"
DEFAULT_DESCRIPTION = "First location"
MIN_SCHEMA_VERSION = 2  # tmdb has survey ids from migration 0002 on
_LATEST_MS = 253402300799000  # 9999-12-31T23:59:59Z, beyond which a timestamp can't be formatted


class Outcome(BaseModel):
    """What a run did. imported: places created from the backup on this run; created_default: the first place was
    created on this run; followed: what following the file changed (unknown_id: a place was created for the file's
    survey_id; coordinates: the place in use took the file's coordinates)."""

    state: Literal["done", "waiting_nodered", "config_unreadable"]
    imported: int = 0
    created_default: bool = False
    followed: Literal["none", "unknown_id", "coordinates"] = "none"


class _WaitForNodeRed(Exception):
    """Node-RED didn't answer, or its tmdb isn't migrated yet: the one-time part waits for a later run."""


def backup_dir(manifest) -> Path:
    return Path(manifest.codedir) / "node-red-tm" / "db" / "backup"


def point_text(lat: float | None, lon: float | None) -> str | None:
    """A point as a correction row keeps it: "lat,lon", or None for no location."""
    if lat is None or lon is None:
        return None
    return f"{lat},{lon}"


def _point(lat, lon) -> tuple[float | None, float | None]:
    """The pair at five places, compared as such; (None, None) unless both are set."""
    lat, lon = exact(lat), exact(lon)
    if lat is None or lon is None:
        return None, None
    return lat, lon


def _file_point(deployment: Deployment) -> tuple[float | None, float | None]:
    """The file's point; (None, None) when it has none, or coordinates that aren't a point (coordinates_invalid)."""
    if deployment.coordinates_invalid:
        return None, None
    return _point(deployment.lat, deployment.lon)


def ensure(app_state, user_id: int | None = None) -> Outcome:
    """Reconcile the places store with config.yml (see the module's docstring).

    app_state carries state, manifest, nodered, config_path, and reconcile_lock. user_id becomes created_by on the
    places this creates. A ConfigError from saving config.yml (changed since it was read, or not writable) is raised.
    """
    with app_state.reconcile_lock:
        try:
            config = NodeRedConfig(app_state.config_path)
        except ConfigError:
            return Outcome(state="config_unreadable")
        places = Places(app_state.state)
        imported, created_default = 0, False
        if places.reconciled_at() is None:
            try:
                imported, created_default = _first_run(app_state, places, config, user_id)
            except _WaitForNodeRed:
                return Outcome(state="waiting_nodered")
        followed = _follow(app_state, places, config, user_id)
        return Outcome(state="done", imported=imported, created_default=created_default, followed=followed)


# The one-time part


def _first_run(app_state, places: Places, config: NodeRedConfig, user_id) -> tuple[int, bool]:
    """Returns (places imported, whether the default place was created). Raises _WaitForNodeRed."""
    deployment = config.deployment()
    # Coordinates that don't parse still mean the file had a location: such a unit may be an upgraded one.
    no_location = _file_point(deployment) == (None, None) and not deployment.coordinates_invalid
    if not places.list() and deployment.survey_id is None and no_location:
        survey_id = new_survey_id()
        config.set_survey_id(survey_id)  # only the id: the operator's lat and lon text stays as it is
        if deployment.precision_missing:
            config.set_precision(DEFAULT_PRECISION)
        config.save()
        _create_in_use(places, survey_id, DEFAULT_DESCRIPTION, (None, None), config.sensors(), "default", user_id)
        places.mark_reconciled()
        return 0, True

    _check_nodered(app_state.nodered)
    imported = _import_backup(app_state, places, user_id)
    _put_in_use(places, config, deployment, user_id)
    places.mark_reconciled()
    return imported, False


def _check_nodered(nodered) -> None:
    try:
        report = nodered.report()
    except NodeRedError:
        raise _WaitForNodeRed from None
    version = report.get("schema_version")
    if isinstance(version, bool) or not isinstance(version, int) or version < MIN_SCHEMA_VERSION:
        raise _WaitForNodeRed


def _import_backup(app_state, places: Places, user_id) -> int:
    """Create a used place for each survey the backup's rows belong to, but not one already in the store (a run that
    failed part-way is finished by the next; the reconciled flag stops it after that); the number created."""
    # create_app sets backup_dir (fake mode's is beside its state); else the manifest's codedir says where it is.
    path = _newest_backup(getattr(app_state, "backup_dir", None) or backup_dir(app_state.manifest))
    rows = _read_backup(path) if path is not None else None
    if not rows:
        return 0
    try:
        usage, owner = _surveys_and_rows(app_state.nodered)
    except NodeRedError:
        raise _WaitForNodeRed from None

    points: dict[str, Counter] = {}  # survey id -> how many rows hold each point
    for deployment_id, point in rows:
        survey_id = owner.get(deployment_id)
        if survey_id is not None:
            points.setdefault(survey_id, Counter())[point] += 1

    created = 0
    for survey_id, survey in usage.items():
        if survey_id not in points or places.get(survey_id) is not None:
            continue
        # The rows of one survey share a point by construction (migration 0002); should they not, the most common one,
        # and of equals the first met.
        point = max(points[survey_id].items(), key=lambda item: item[1])[0]
        first, last = _seconds(survey.get("first_start")), _seconds(survey.get("last_end"))
        first = last if first is None else first
        last = first if last is None else last  # a survey still open: its first use, not now
        places.create(
            survey_id, None, point[0], point[1], [], "imported_backup", "used", user_id, now=first, updated_now=last
        )
        created += 1
    if created:
        log.info("imported %d places from the tmdb backup", created)
    return created


def _newest_backup(directory: Path) -> Path | None:
    try:
        found = [path for path in directory.glob(BACKUP_GLOB) if path.is_file()]
    except OSError as error:  # a directory tm-control may not list
        log.warning("skipping the tmdb backup: %s", type(error).__name__)
        return None
    # tmdb-v<version>-<stamp>.sqlite: the stamp (%Y%m%dT%H%M%SZ) orders them whatever the version
    return max(found, key=lambda path: (path.name.split("-", 2)[2], path.name), default=None)


def _read_backup(path: Path) -> list[tuple[str, tuple[float, float]]] | None:
    """(deployment id, exact point) for each row with both coordinates; None when the file can't be read as a tmdb
    with a deployment table holding lat and lon. Opened read-only and immutable: tm-control never writes tmdb."""
    uri = f"file:{quote(str(path))}?mode=ro&immutable=1"
    try:
        with closing(sqlite3.connect(uri, uri=True)) as con:
            found = con.execute(
                "SELECT id, lat, lon FROM deployment WHERE lat IS NOT NULL AND lon IS NOT NULL"
            ).fetchall()
    except sqlite3.Error as error:
        log.warning("skipping the tmdb backup: %s", type(error).__name__)
        return None
    rows = []
    for deployment_id, lat, lon in found:
        try:
            point = (exact(lat, "lat"), exact(lon, "lon"))
        except ValueError:
            continue  # text or out of range: migration 0002 gave such a row no survey id either
        if isinstance(deployment_id, str) and None not in point:
            rows.append((deployment_id, point))
    return rows


def _surveys_and_rows(nodered) -> tuple[dict[str, dict], dict[str, str]]:
    """Node-RED's usage by survey id (in its order; the group of rows with no survey id left out), and each
    deployment id's survey id. Raises NodeRedError."""
    usage: dict[str, dict] = {}
    owner: dict[str, str] = {}
    for survey in nodered.usage():
        survey_id = normalize_survey_id(survey.get("survey_id"))
        if survey_id is None or survey_id in usage:
            continue
        usage[survey_id] = survey
        for row in nodered.deployments(survey_id):
            if isinstance(row.get("id"), str):
                owner.setdefault(row["id"], survey_id)
    return usage, owner


def _seconds(ms) -> float | None:
    """Epoch milliseconds as Node-RED answers them, in seconds; None for anything else."""
    if isinstance(ms, bool) or not isinstance(ms, (int, float)) or not math.isfinite(ms):
        return None
    return ms / 1000 if 0 <= ms <= _LATEST_MS else None


def _put_in_use(places: Places, config: NodeRedConfig, deployment: Deployment, user_id) -> None:
    """Put in use the place the file names, or else the one at the file's point, or else a new one from the file; the
    file names it afterwards."""
    if deployment.survey_id is not None:
        if places.get(deployment.survey_id) is not None:
            places.set_in_use(deployment.survey_id)
        else:
            _create_from_file(places, config, deployment, deployment.survey_id, user_id)
        return
    point = _file_point(deployment)
    match = _at_point(places, point) if point != (None, None) else None
    survey_id = match.id if match is not None else new_survey_id()
    # The file first: if saving fails, the store is unchanged and the next run starts over. Only the id is written.
    config.set_survey_id(survey_id)
    config.save()
    if match is not None:
        places.set_in_use(match.id)
    else:
        _create_from_file(places, config, deployment, survey_id, user_id)


def _at_point(places: Places, point) -> Survey | None:
    """A place at this point at five places: an imported one first, else any."""
    found = [place for place in places.list() if _point(place.lat, place.lon) == point]
    imported = [place for place in found if place.source == "imported_backup"]
    return (imported or found or [None])[0]


def _create_from_file(places: Places, config: NodeRedConfig, deployment: Deployment, survey_id: str, user_id) -> None:
    point = _file_point(deployment)  # no point when the file's coordinates aren't one
    _create_in_use(places, survey_id, None, point, config.sensors(), "imported_config", user_id)


def _create_in_use(places: Places, survey_id: str, description, point, bearings: list[Bearing], source, user_id):
    # Created planned, then put in use, so the place in use before (if any) becomes used.
    places.create(survey_id, description, point[0], point[1], bearings, source, "planned", user_id)
    places.set_in_use(survey_id)


# Every run


def _follow(app_state, places: Places, config: NodeRedConfig, user_id) -> str:
    deployment = config.deployment()
    followed = "none"
    if deployment.survey_id is not None:
        named = places.get(deployment.survey_id)
        if named is None:
            _create_from_file(places, config, deployment, deployment.survey_id, user_id)
            followed = "unknown_id"
        elif named.status != "in_use":
            # A deploy by hand, as the page's would be: the file takes that place's point (blank when it has none);
            # neither place's point changes, and Node-RED re-rounds nothing. The file first, as in _put_in_use.
            config.set_place(named.id, named.lat, named.lon)
            config.save()
            places.set_in_use(named.id)
            return followed

    current = places.in_use()
    if current is None or deployment.coordinates_invalid:
        return followed  # coordinates that aren't a point are a typo to fix, not a move: the Status check reports them
    old, new = _point(current.lat, current.lon), _file_point(deployment)
    if old == new:
        return followed
    places.set_point(current.id, new[0], new[1])
    places.record_correction(current.id, None, "location", point_text(*old), point_text(*new), None, "config", None)
    if new != (None, None):
        try:
            app_state.nodered.correct_location(current.id, new[0], new[1])
        except NodeRedError as error:
            log.warning("re-rounding the place's rows in Node-RED failed: %s", type(error).__name__)
    return "coordinates"
