"""One take of a camera's two frames: the reading of Frigate that the reference picture's dialog and everything that
keeps pictures on the device share.

`shoot` asks Node-RED what Frigate is tracking, takes Frigate's current frame plain and with its zone outlines, asks
again, and answers a Shot (reference.py); or it raises NoShot, whose `code` says why there is no take, or the
ApiError that `load_config` raises when config.yml can't be read, so a caller catches both. It reads the place in
use. It logs nothing and audits nothing: a caller decides what to do with the answer and what to record.
"""

import time

from tm_control import fake
from tm_control.adapters import frigate
from tm_control.adapters.nodered import NodeRedError
from tm_control.modules.apps import probes
from tm_control.modules.cameras import people, reference
from tm_control.modules.cameras.state import compare
from tm_control.modules.cameras.zones import detect_size, distance_unit, zone_facts
from tm_control.modules.location.access import load_config
from tm_control.modules.location.places import Places


class NoShot(Exception):
    """There is no take. `code` is `not_found` (no such camera entry), `unavailable` (Frigate isn't answering or is in
    safe mode), `changed` (Frigate's cameras and config.yml no longer agree), `camera_off` (the camera is turned off in
    Frigate), or `no_picture` (Frigate has no live picture from the camera). The message holds nothing."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _live(frame, size: tuple[int, int]) -> bytes:
    """The frame's bytes when it is the camera's current frame at the detect size; Frigate's error picture comes with
    a 200 and no header, so its size is what gives it away."""
    if frame is None or frame.offline or reference.jpeg_size(frame.data) != size:
        raise NoShot("no_picture")
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


def shoot(app_state, name: str) -> reference.Shot:
    """Take the camera's (a `sensors.cameras` key) current frame from Frigate, plain and with its zone outlines.
    Raises NoShot, or an ApiError when config.yml can't be read."""
    settings = app_state.settings
    config = load_config(app_state)
    if not any(entry.name == name for entry in config.cameras()):
        raise NoShot("not_found")
    whole = fake.frigate_answer(settings)[0] if settings.fake else frigate.config()
    if whole is None or probes.frigate_safe_mode(whole):
        raise NoShot("unavailable")
    cameras = probes.mapping(whole.get("cameras"))
    row = next((row for row in compare(config.cameras(), cameras, config.radars()) if row.name == name), None)
    if row is None:
        raise NoShot("not_found")
    if row.in_frigate == "absent" or row.duplicate_of is not None:
        raise NoShot("changed")
    if row.in_frigate == "off":
        raise NoShot("camera_off")
    camera = probes.mapping(cameras.get(row.frigate_camera))
    size = detect_size(camera)
    if size is None:
        raise NoShot("no_picture")
    stats = fake.frigate_stats(settings) if settings.fake else frigate.stats()
    if not _sending(stats, row.frigate_camera):
        raise NoShot("no_picture")

    def frame(zones: bool):
        if settings.fake:
            return fake.frigate_frame(settings, row.frigate_camera, zones)
        return frigate.latest_frame(row.frigate_camera, zones=zones)

    before = people.ask(app_state.nodered, name)
    clean = _live(frame(False), size)
    clean_at = time.time()
    zones_picture = _live(frame(True), size)
    zones_at = time.time()
    after = people.ask(app_state.nodered, name) if before is not None else None
    objects = people.facts(before, after)

    mounting = next((m for m in config.mountings() if (m.sensor_type, m.sensor_name) == ("cameras", name)), None)
    place = Places(app_state.state).in_use()
    point = (place.lat, place.lon) if place and place.lat is not None and place.lon is not None else None
    return reference.Shot(
        camera=name,
        survey_id=place.id if place else None,
        point=point,
        deployment_id=_open_deployment(app_state, place.id, name) if place else None,
        pose=reference.pose_of(mounting),
        clean=clean,
        zones_picture=zones_picture,
        clean_at=clean_at,
        zones_at=zones_at,
        width=size[0],
        height=size[1],
        unit=distance_unit(whole),
        zones=zone_facts(camera),
        objects=objects,
        tm_version=app_state.manifest.tm_version,
        frigate_version=fake.FAKE_FRIGATE_VERSION if settings.fake else frigate.version(),
    )
