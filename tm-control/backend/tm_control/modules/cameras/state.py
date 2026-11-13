"""The one comparison of Frigate's cameras with config.yml's sensors.cameras entries, for the Cameras page and for the
Status checks, so the two can't disagree.

Frigate's cameras are read from its running config, which carries the switches in Frigate's live view as they are now:
"off" is `enabled: false` there, and `detect` is whether Frigate detects objects on the camera. A Frigate camera that is
off and that no entry points at is left out: it gives no events, so there is nothing to pair. A Frigate that doesn't
answer, or runs in safe mode with no cameras, gives no cameras (None), and then nothing can be said about an entry:
every one is "unknown", never "absent".
"""

from typing import Literal

from pydantic import BaseModel

from tm_control import fake
from tm_control.adapters import frigate
from tm_control.modules.apps import probes
from tm_control.modules.apps.contracts import ZONES
from tm_control.modules.cameras.names import is_neutral
from tm_control.modules.location.config import CameraEntry


class CameraRow(BaseModel):
    name: str | None  # the sensors.cameras key; None for a Frigate camera no entry points at
    frigate_camera: str
    in_frigate: Literal["on", "off", "absent", "unknown"]  # "unknown" while Frigate is down or in safe mode
    detect: bool | None  # Frigate detects objects on it now: on, with detect.enabled; None when that can't be read
    neutral: bool | None  # is_neutral(name); None when name is None
    duplicate_of: str | None  # the earlier key that names the same Frigate camera
    enabled: bool | None  # the entry's enabled; None for a Frigate camera no entry points at
    camera_radar: str | None
    plate_recognizer: bool | None
    zones_missing: list[str] | None  # of ZONES; None when the camera isn't in Frigate
    zones_off: list[str] | None  # of ZONES, there but turned off (Frigate 0.18's zone enabled); None as zones_missing


class CameraRadar(BaseModel):
    name: str
    in_config: bool  # has an entry under sensors.radars
    enabled: bool
    port_open: bool | None  # Node-RED's reading; None when it didn't say


class CamerasState(BaseModel):
    frigate: Literal["ok", "down", "safe_mode"]
    plates: bool  # the Plate Recognizer add-on is installed
    rows: list[CameraRow]
    radars: list[CameraRadar]  # the unit's radars, in the order of node-red-tm.env


def _zones_missing(camera: dict) -> list[str]:
    zones = probes.mapping(camera.get("zones"))
    return [zone for zone in ZONES if zone not in zones]


def _zones_off(camera: dict) -> list[str]:
    """The zones Frigate has but has turned off, in its config or from the live view: an event never enters one."""
    zones = probes.mapping(camera.get("zones"))
    return [zone for zone in ZONES if zone in zones and probes.mapping(zones[zone]).get("enabled") is False]


def _in_frigate(camera: dict | None) -> Literal["on", "off", "absent"]:
    if camera is None:
        return "absent"
    return "off" if camera.get("enabled") is False else "on"


def _detect(camera: dict | None) -> bool | None:
    if camera is None:
        return None
    if camera.get("enabled") is False:
        return False
    enabled = probes.mapping(camera.get("detect")).get("enabled")
    return enabled if isinstance(enabled, bool) else None


def compare(entries: list[CameraEntry], frigate_cameras: dict[str, dict] | None) -> list[CameraRow]:
    """A row for each entry in file order, then one for each Frigate camera that is on and that no entry points at, in
    Frigate's order. frigate_cameras is Frigate's config `cameras` by name, or None when Frigate gave none to
    compare."""
    known = frigate_cameras is not None
    cameras = {str(name): probes.mapping(camera) for name, camera in (frigate_cameras or {}).items()}
    rows, first_for = [], {}
    for entry in entries:
        camera = cameras.get(entry.frigate_camera)
        rows.append(CameraRow(
            name=entry.name,
            frigate_camera=entry.frigate_camera,
            in_frigate=_in_frigate(camera) if known else "unknown",
            detect=_detect(camera),
            neutral=is_neutral(entry.name),
            duplicate_of=first_for.get(entry.frigate_camera),
            enabled=entry.enabled,
            camera_radar=entry.camera_radar,
            plate_recognizer=entry.plate_recognizer,
            zones_missing=_zones_missing(camera) if camera is not None else None,
            zones_off=_zones_off(camera) if camera is not None else None,
        ))
        first_for.setdefault(entry.frigate_camera, entry.name)
    for name, camera in cameras.items():
        if name not in first_for and _in_frigate(camera) == "on":
            rows.append(CameraRow(
                name=None,
                frigate_camera=name,
                in_frigate="on",
                detect=_detect(camera),
                neutral=None,
                duplicate_of=None,
                enabled=None,
                camera_radar=None,
                plate_recognizer=None,
                zones_missing=_zones_missing(camera),
                zones_off=_zones_off(camera),
            ))
    return rows


def frigate_now(app_state) -> tuple[Literal["ok", "down", "safe_mode"], dict | None]:
    """("ok", Frigate's cameras) when Frigate answers with a usable config, else ("down" or "safe_mode", None)."""
    settings = app_state.settings
    config = fake.frigate_answer(settings)[0] if settings.fake else frigate.config()
    if config is None:
        return "down", None
    if probes.frigate_safe_mode(config):
        return "safe_mode", None
    return "ok", probes.mapping(config.get("cameras"))
