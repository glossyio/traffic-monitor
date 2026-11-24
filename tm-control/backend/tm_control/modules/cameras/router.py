"""/api/v1/cameras: the Cameras page, for admins only. GET lists sensors.cameras against Frigate's cameras and the
unit's radars. cameras_state is also what every write answers with, so the page needs no second request.

Each write holds app.state.reconcile_lock, reads config.yml and Frigate's cameras again, refuses with 409
cameras_changed when they no longer match what the admin confirmed, edits config.yml, then (for a re-key) the places
store, and records an audit row. The one write that goes to Frigate instead, its detection switch, holds the same
lock and leaves config.yml alone. Frigate's camera name is never logged, audited, or put in an error message: audit rows
carry the sensors.cameras key only.

The reference picture (POST /cameras/{name}/reference) reads Frigate twice for the camera's current frame, plain and
with its zone outlines, and holds both in memory under a ticket (app.state.references, reference.py) for the admin who
took them: the pictures shown are the pictures saved. It writes nothing, so it holds no lock. GET
.../{ticket}/clean.jpg and zones.jpg show them, GET .../{ticket}/package gives the zip (the pictures, the data file,
and the drawing, built in memory), and DELETE drops them. No picture, ticket, or point reaches the disk, a log line, an
audit row, or an error message. The device doesn't check the pictures for people: the dialog's note makes that the
admin's job.
"""

import time
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, Field

from tm_control import fake
from tm_control.adapters import frigate
from tm_control.adapters.nodered import NodeRedError
from tm_control.core.auth import Audit, User
from tm_control.core.errors import ApiError
from tm_control.modules.apps import probes
from tm_control.modules.apps.contracts import env_radar_names
from tm_control.modules.auth.deps import require_admin
from tm_control.modules.cameras import reference
from tm_control.modules.cameras.names import is_neutral, new_name
from tm_control.modules.cameras.state import CameraRadar, CameraRow, CamerasState, compare, frigate_now
from tm_control.modules.cameras.zones import ZoneFacts, detect_size, distance_unit, zone_facts
from tm_control.modules.location.access import config_error, load_config, save_config
from tm_control.modules.location.config import ConfigError, NodeRedConfig
from tm_control.modules.location.places import Places

router = APIRouter(prefix="/cameras", tags=["cameras"])


def _port_states(app_state) -> dict:
    """Node-RED's reading of each radar, by name; {} when it doesn't answer."""
    try:
        return probes.mapping(app_state.nodered.report().get("radars"))
    except NodeRedError:
        return {}


def cameras_state(request: Request) -> CamerasState:
    app_state = request.app.state
    config = load_config(app_state)
    state, cameras = frigate_now(app_state)
    in_config, ports = config.radars(), _port_states(app_state)
    radars = []
    for name in env_radar_names(app_state.manifest):
        port_open = probes.mapping(ports.get(name)).get("port_open")
        radars.append(CameraRadar(
            name=name,
            in_config=name in in_config,
            enabled=in_config.get(name, False),
            port_open=port_open if isinstance(port_open, bool) else None,
        ))
    return CamerasState(
        frigate=state,
        plates=app_state.manifest.options.get("plate_recognizer") is True,
        rows=compare(config.cameras(), cameras, in_config),
        radars=radars,
    )


@router.get("", response_model=CamerasState)
def list_cameras(request: Request, admin: User = Depends(require_admin)) -> CamerasState:
    return cameras_state(request)


# Writes

NAME_MAX = 200  # a bound on what a body may carry, not a rule about Frigate's names


class CameraAdd(BaseModel):
    frigate_camera: str = Field(min_length=1, max_length=NAME_MAX)
    enabled: bool
    camera_radar: str | None = Field(default=None, max_length=NAME_MAX)
    plate_recognizer: bool | None = None  # None writes no plate_recognizer key


class CameraSettings(BaseModel):
    enabled: bool
    camera_radar: str | None = Field(default=None, max_length=NAME_MAX)  # None removes the key
    plate_recognizer: bool | None = None  # None leaves the key as it is


class CameraPoint(BaseModel):
    to: str = Field(min_length=1, max_length=NAME_MAX)


class CameraDetection(BaseModel):
    enabled: bool


def _changed() -> ApiError:
    return ApiError(409, "cameras_changed", "Frigate's cameras or config.yml changed. Reload the page and try again.")


def _unavailable() -> ApiError:
    return ApiError(
        409, "frigate_unavailable",
        "Frigate isn't answering, so its cameras can't be compared. Try again when it is running.",
    )


def _camera_off() -> ApiError:
    return ApiError(409, "camera_off", "This camera is turned off in Frigate. Turn it on in Frigate first.")


def _not_found() -> ApiError:
    return ApiError(404, "not_found", "There is no such camera.")


def _compared(app_state, config: NodeRedConfig) -> list[CameraRow]:
    """The page's rows against Frigate now; 409 frigate_unavailable while Frigate gives no cameras to compare."""
    cameras = frigate_now(app_state)[1]
    if cameras is None:
        raise _unavailable()
    return compare(config.cameras(), cameras, config.radars())


def _exists(config: NodeRedConfig, name: str) -> None:
    if not any(entry.name == name for entry in config.cameras()):
        raise _not_found()


def _entry(rows: list[CameraRow], name: str) -> CameraRow:
    for row in rows:
        if row.name == name:
            return row
    raise _not_found()


def _unpointed(rows: list[CameraRow], frigate_camera: str) -> bool:
    """Whether Frigate has this camera and no entry points at it."""
    return any(row.name is None and row.frigate_camera == frigate_camera for row in rows)


def _check_radar(app_state, config: NodeRedConfig, radar: str | None) -> None:
    if radar is not None and not (radar in env_radar_names(app_state.manifest) and radar in config.radars()):
        raise ApiError(
            422, "validation", "Choose a radar that config.yml lists, or no radar.", detail={"field": "camera_radar"}
        )


def _edit(edit, *args) -> None:
    """Run a NodeRedConfig edit; a camera or name that vanished or appeared is 409, a file it can't edit is 500."""
    try:
        edit(*args)
    except (KeyError, ValueError):
        raise _changed() from None
    except ConfigError as error:
        raise config_error(error) from None


def _save(app_state, config: NodeRedConfig, must_change: bool = True) -> None:
    if not save_config(app_state, config) and must_change:
        raise config_error(ConfigError("changed"))


@router.post("", response_model=CamerasState)
def add_camera(body: CameraAdd, request: Request, admin: User = Depends(require_admin)) -> CamerasState:
    """Add an entry under a new neutral name for a Frigate camera that no entry points at."""
    app_state = request.app.state
    with app_state.reconcile_lock:
        config = load_config(app_state)
        rows = _compared(app_state, config)
        if not _unpointed(rows, body.frigate_camera):
            raise _changed()
        _check_radar(app_state, config, body.camera_radar)
        name = new_name(row.name for row in rows if row.name is not None)
        _edit(
            config.add_camera, name, body.frigate_camera, body.enabled, body.camera_radar, body.plate_recognizer
        )
        _save(app_state, config)
    Audit(app_state.state).record(admin.id, "camera.add", name)
    app_state.setup_poster.wake()
    return cameras_state(request)


@router.put("/{name}", response_model=CamerasState)
def set_camera(
    name: str, body: CameraSettings, request: Request, admin: User = Depends(require_admin)
) -> CamerasState:
    """Set an entry's record, radar, and plates settings. Frigate isn't asked: these don't depend on it."""
    app_state = request.app.state
    with app_state.reconcile_lock:
        config = load_config(app_state)
        _exists(config, name)
        _check_radar(app_state, config, body.camera_radar)
        _edit(config.set_camera, name, body.enabled, body.camera_radar, body.plate_recognizer)
        _save(app_state, config, must_change=False)  # the same settings again is not a conflict
    Audit(app_state.state).record(admin.id, "camera.update", name)
    app_state.setup_poster.wake()
    return cameras_state(request)


@router.post("/{name}/frigate-camera", response_model=CamerasState)
def point_camera(
    name: str, body: CameraPoint, request: Request, admin: User = Depends(require_admin)
) -> CamerasState:
    """Point an entry whose Frigate camera is gone at a Frigate camera no entry points at. Nothing else changes."""
    app_state = request.app.state
    with app_state.reconcile_lock:
        config = load_config(app_state)
        _exists(config, name)
        rows = _compared(app_state, config)
        if _entry(rows, name).in_frigate != "absent" or not _unpointed(rows, body.to):
            raise _changed()
        _edit(config.point_camera, name, body.to)
        _save(app_state, config)
    Audit(app_state.state).record(admin.id, "camera.point", name)
    app_state.setup_poster.wake()
    return cameras_state(request)


@router.post("/{name}/neutral-name", response_model=CamerasState)
def neutral_name(name: str, request: Request, admin: User = Depends(require_admin)) -> CamerasState:
    """Re-key an entry to a new neutral name, and move its bearings in every place to the new name."""
    app_state = request.app.state
    with app_state.reconcile_lock:
        config = load_config(app_state)
        _exists(config, name)
        rows = _compared(app_state, config)
        if is_neutral(name):
            raise _changed()
        new = new_name(row.name for row in rows if row.name is not None)
        _edit(config.rename_camera, name, new)
        _save(app_state, config)
        Places(app_state.state).rename_sensor("cameras", name, new)  # config.yml first, the store second
    Audit(app_state.state).record(admin.id, "camera.neutral_name", new)
    app_state.setup_poster.wake()
    return cameras_state(request)


@router.put("/{name}/frigate-detection", response_model=CamerasState)
def set_detection(
    name: str, body: CameraDetection, request: Request, admin: User = Depends(require_admin)
) -> CamerasState:
    """Turn Frigate's object detection on or off for an entry's camera, with Frigate's live switch (no restart; Frigate
    keeps it). config.yml isn't changed."""
    app_state = request.app.state
    settings = app_state.settings
    with app_state.reconcile_lock:
        config = load_config(app_state)
        _exists(config, name)
        row = _entry(_compared(app_state, config), name)
        if row.in_frigate == "absent":
            raise _changed()
        if row.in_frigate == "off":
            raise _camera_off()
        if settings.fake:
            taken = fake.set_frigate_detect(settings, row.frigate_camera, body.enabled)
        else:
            taken = frigate.set_detect(row.frigate_camera, body.enabled)
        if not taken:
            raise ApiError(
                502, "frigate_error", "Frigate didn't take the change. Try again, or use Frigate's own switch."
            )
    Audit(app_state.state).record(admin.id, "camera.detection_on" if body.enabled else "camera.detection_off", name)
    return cameras_state(request)


@router.delete("/{name}", response_model=CamerasState)
def remove_camera(name: str, request: Request, admin: User = Depends(require_admin)) -> CamerasState:
    """Remove an entry whose Frigate camera is gone, or that duplicates an earlier entry's."""
    app_state = request.app.state
    with app_state.reconcile_lock:
        config = load_config(app_state)
        _exists(config, name)
        row = _entry(_compared(app_state, config), name)
        if row.in_frigate != "absent" and row.duplicate_of is None:
            raise _changed()
        _edit(config.remove_camera, name)
        _save(app_state, config)
    Audit(app_state.state).record(admin.id, "camera.remove", name)
    app_state.setup_poster.wake()
    return cameras_state(request)


# Reference picture


class ReferenceOut(BaseModel):
    ticket: str
    expires_in: int  # seconds the pictures are held: 600
    stem: str  # the zip's name without ".zip"
    camera: str
    survey_id: str | None
    taken_at: str  # the clean picture's, as in the data file
    width: int
    height: int
    unit: Literal["m", "ft"]
    zones: list[ZoneFacts]
    has_location: bool  # the place in use has a point, so the box can be ticked


PICTURE_BODY = {200: {"description": "The picture", "content": {"image/jpeg": {"schema": {"type": "string",
                                                                                         "format": "binary"}}}}}
ZIP_BODY = {200: {"description": "The zip", "content": {"application/zip": {"schema": {"type": "string",
                                                                                      "format": "binary"}}}}}
NO_STORE = {"Cache-Control": "no-store"}


def _no_picture() -> ApiError:
    return ApiError(
        409, "no_picture",
        "Frigate has no live picture from this camera right now. Check the camera on the Status page, then try again.",
    )


def _expired() -> ApiError:
    return ApiError(404, "reference_expired", "These pictures are no longer held on the device. Take them again.")


def _live(frame, size: tuple[int, int]) -> bytes:
    """The frame's bytes when it is the camera's current frame at the detect size; Frigate's error picture comes with
    a 200 and no header, so its size is what gives it away."""
    if frame is None or frame.offline or reference.jpeg_size(frame.data) != size:
        raise _no_picture()
    return frame.data


def _sending(stats, camera: str) -> bool:
    fps = probes.mapping(probes.mapping(probes.mapping(stats).get("cameras")).get(camera)).get("camera_fps")
    return isinstance(fps, (int, float)) and not isinstance(fps, bool) and fps > 0


def _open_deployment(app_state, survey_id: str, name: str) -> str | None:
    """The id of the camera's open deployment row at the place; None when Node-RED doesn't answer or has none."""
    try:
        rows = app_state.nodered.deployments(survey_id)
    except NodeRedError:
        return None
    found = None
    for row in rows:
        if (row.get("sensorType"), row.get("sensorName")) == ("cameras", name) and not row.get("entryEndDateTime"):
            found = row.get("id")
    return found if isinstance(found, str) else None


@router.post("/{name}/reference", response_model=ReferenceOut)
def take_reference(name: str, request: Request, admin: User = Depends(require_admin)) -> ReferenceOut:
    """Take the camera's current frame from Frigate, plain and with its zone outlines, and hold both in memory."""
    app_state = request.app.state
    settings = app_state.settings
    config = load_config(app_state)
    _exists(config, name)
    whole = fake.frigate_answer(settings)[0] if settings.fake else frigate.config()
    if whole is None or probes.frigate_safe_mode(whole):
        raise _unavailable()
    cameras = probes.mapping(whole.get("cameras"))
    row = _entry(compare(config.cameras(), cameras, config.radars()), name)
    if row.in_frigate == "absent" or row.duplicate_of is not None:
        raise _changed()
    if row.in_frigate == "off":
        raise _camera_off()
    camera = probes.mapping(cameras.get(row.frigate_camera))
    size = detect_size(camera)
    if size is None:
        raise _no_picture()
    stats = fake.frigate_stats(settings) if settings.fake else frigate.stats()
    if not _sending(stats, row.frigate_camera):
        raise _no_picture()

    def frame(zones: bool):
        if settings.fake:
            return fake.frigate_frame(settings, row.frigate_camera, zones)
        return frigate.latest_frame(row.frigate_camera, zones=zones)

    clean = _live(frame(False), size)
    clean_at = time.time()
    zones_picture = _live(frame(True), size)
    zones_at = time.time()

    place = Places(app_state.state).in_use()
    point = (place.lat, place.lon) if place and place.lat is not None and place.lon is not None else None
    kept = app_state.references.keep(
        time.monotonic(),
        user_id=admin.id,
        camera=name,
        survey_id=place.id if place else None,
        point=point,
        deployment_id=_open_deployment(app_state, place.id, name) if place else None,
        clean=clean,
        zones_picture=zones_picture,
        clean_at=clean_at,
        zones_at=zones_at,
        width=size[0],
        height=size[1],
        unit=distance_unit(whole),
        zones=zone_facts(camera),
        tm_version=app_state.manifest.tm_version,
        frigate_version=fake.FAKE_FRIGATE_VERSION if settings.fake else frigate.version(),
    )
    Audit(app_state.state).record(admin.id, "camera.reference", name)
    return ReferenceOut(
        ticket=kept.ticket,
        expires_in=int(app_state.references.TTL),
        stem=reference.stem(kept),
        camera=name,
        survey_id=kept.survey_id,
        taken_at=reference.iso(kept.clean_at),
        width=kept.width,
        height=kept.height,
        unit=kept.unit,
        zones=kept.zones,
        has_location=point is not None,
    )


def _held(request: Request, name: str, ticket: str, admin: User) -> reference.Reference:
    held = request.app.state.references.get(ticket, admin.id, time.monotonic())
    if held is None or held.camera != name:
        raise _expired()
    return held


@router.get("/{name}/reference/{ticket}/package", response_class=Response, responses=ZIP_BODY)
def reference_package(
    name: str, ticket: str, request: Request, location: bool = Query(), admin: User = Depends(require_admin)
) -> Response:
    """The zip of the pictures shown, the data file (with the place's point when location is true and there is one),
    and the drawing."""
    held = _held(request, name, ticket, admin)
    body = reference.package(held, with_location=location)
    with_point = location and held.point is not None
    Audit(request.app.state.state).record(
        admin.id, "camera.reference_saved_with_location" if with_point else "camera.reference_saved", name
    )
    return Response(
        body, media_type="application/zip",
        headers=NO_STORE | {"Content-Disposition": f'attachment; filename="{reference.stem(held)}.zip"'},
    )


@router.get("/{name}/reference/{ticket}/{picture}", response_class=Response, responses=PICTURE_BODY)
def reference_picture(
    name: str, ticket: str, picture: Literal["clean.jpg", "zones.jpg"], request: Request,
    admin: User = Depends(require_admin),
) -> Response:
    """One of the pictures held: the camera's view, or the same view with Frigate's zone outlines."""
    held = _held(request, name, ticket, admin)
    return Response(held.clean if picture == "clean.jpg" else held.zones_picture, media_type="image/jpeg",
                    headers=NO_STORE)


@router.delete("/{name}/reference/{ticket}", status_code=204)
def drop_reference(name: str, ticket: str, request: Request, admin: User = Depends(require_admin)) -> Response:
    """Forget the pictures before their time is up, whether or not they were still held."""
    request.app.state.references.drop(ticket, admin.id)
    return Response(status_code=204)
