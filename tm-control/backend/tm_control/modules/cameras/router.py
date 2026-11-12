"""/api/v1/cameras: the Cameras page, for admins only. GET lists sensors.cameras against Frigate's cameras and the
unit's radars. cameras_state is also what every write answers with, so the page needs no second request.

Each write holds app.state.reconcile_lock, reads config.yml and Frigate's cameras again, refuses with 409
cameras_changed when they no longer match what the admin confirmed, edits config.yml, then (for a re-key) the places
store, and records an audit row. Frigate's camera name is never logged, audited, or put in an error message: audit rows
carry the sensors.cameras key only.
"""

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from tm_control.adapters.nodered import NodeRedError
from tm_control.core.auth import Audit, User
from tm_control.core.errors import ApiError
from tm_control.modules.apps import probes
from tm_control.modules.apps.contracts import env_radar_names
from tm_control.modules.auth.deps import require_admin
from tm_control.modules.cameras.names import is_neutral, new_name
from tm_control.modules.cameras.state import CameraRadar, CameraRow, CamerasState, compare, frigate_now
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
        rows=compare(config.cameras(), cameras),
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


def _changed() -> ApiError:
    return ApiError(409, "cameras_changed", "Frigate's cameras or config.yml changed. Reload the page and try again.")


def _unavailable() -> ApiError:
    return ApiError(
        409, "frigate_unavailable",
        "Frigate isn't answering, so its cameras can't be compared. Try again when it is running.",
    )


def _not_found() -> ApiError:
    return ApiError(404, "not_found", "There is no such camera.")


def _compared(app_state, config: NodeRedConfig) -> list[CameraRow]:
    """The page's rows against Frigate now; 409 frigate_unavailable while Frigate gives no cameras to compare."""
    cameras = frigate_now(app_state)[1]
    if cameras is None:
        raise _unavailable()
    return compare(config.cameras(), cameras)


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
    return cameras_state(request)
