"""/api/v1/cameras: the Cameras page, for admins only. GET lists sensors.cameras against Frigate's cameras and the
unit's radars. cameras_state is also what every write answers with, so the page needs no second request."""

from fastapi import APIRouter, Depends, Request

from tm_control import fake
from tm_control.adapters import frigate
from tm_control.adapters.nodered import NodeRedError
from tm_control.core.auth import User
from tm_control.modules.apps import probes
from tm_control.modules.apps.contracts import env_radar_names
from tm_control.modules.auth.deps import require_admin
from tm_control.modules.cameras.state import CamerasState, RadarOut, compare
from tm_control.modules.location.access import load_config

router = APIRouter(prefix="/cameras", tags=["cameras"])


def _frigate_cameras(app_state) -> tuple[str, dict | None]:
    """("ok", Frigate's cameras) when Frigate answers with a usable config, else ("down" or "safe_mode", None)."""
    settings = app_state.settings
    config = fake.frigate_answer(settings)[0] if settings.fake else frigate.config()
    if config is None:
        return "down", None
    if probes.frigate_safe_mode(config):
        return "safe_mode", None
    return "ok", probes.mapping(config.get("cameras"))


def _port_states(app_state) -> dict:
    """Node-RED's reading of each radar, by name; {} when it doesn't answer."""
    try:
        return probes.mapping(app_state.nodered.report().get("radars"))
    except NodeRedError:
        return {}


def cameras_state(request: Request) -> CamerasState:
    app_state = request.app.state
    config = load_config(app_state)
    state, cameras = _frigate_cameras(app_state)
    in_config, ports = config.radars(), _port_states(app_state)
    radars = []
    for name in env_radar_names(app_state.manifest):
        port_open = probes.mapping(ports.get(name)).get("port_open")
        radars.append(RadarOut(
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
