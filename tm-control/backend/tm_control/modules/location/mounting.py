"""How a sensor is mounted: the five facts, the limits on them, tilt and distance worked out from each other, the usual
mounts, which changes count, whether to ask "Did the unit move or turn?", and the answer chosen in advance.

This module holds every one of those rules and does no I/O. The flows check the same limits on what they read from
config.yml ("init config defaults" and the validator of a mounting correction), pinned against this table by a test in
script/tests. The compass and the heading's own rules are coordinates.py's. Every rounding is half away from zero on the
double's exact value (the flows' `Number(value.toFixed(places))`), and a limit is checked on the rounded value, so what
is stored always satisfies it. No value is put in an error message; MountingError.field names the one refused.
"""

import math
import re
from collections.abc import Mapping
from decimal import InvalidOperation
from typing import Literal

from pydantic import BaseModel, ConfigDict

from tm_control.core.migrate import COSINE_MAX_DEG, cosine_command  # noqa: F401  (the one definition; see migrate)
from tm_control.modules.location.coordinates import read_heading, round_half_away, valid_heading

FIELDS = ("heading_deg", "pitch_deg", "height_m", "view_distance_m", "mount")
PITCH_MAX = 90.0
HEIGHT_MAX_M = 100.0
VIEW_DISTANCE_MAX_M = 1000.0
MOUNT_KEY = re.compile(r"^[a-z0-9_]{1,32}$")
MOVED_HEADING_DEG = 20
MOVED_HEIGHT_M = 0.3
MOVED_PITCH_DEG = 5.0
AIR_QUALITY = "airquality_monitors"

# Each number's decimal places, what it must be, and the sentence that says so (the flows' texts).
_LIMITS = {
    "pitch_deg": (1, lambda value: 0 <= value <= PITCH_MAX, "isn't a number from 0 to 90"),
    "height_m": (2, lambda value: 0 < value <= HEIGHT_MAX_M, "isn't a number above 0 and at most 100"),
    "view_distance_m": (2, lambda value: 0 <= value <= VIEW_DISTANCE_MAX_M, "isn't a number from 0 to 1000"),
}


class Mount(BaseModel):
    key: str
    title: str
    height_m: float
    pitch_deg: float


MOUNTS = (
    Mount(key="tripod", title="Tripod beside the road", height_m=2.13, pitch_deg=15.0),
    Mount(key="pole", title="Pole or sign post", height_m=3.66, pitch_deg=15.0),
    Mount(key="window", title="Upstairs window over an intersection", height_m=4.88, pitch_deg=15.0),
)


class Mounting(BaseModel):
    """One sensor's five facts. Strict, so '40' and True are never taken for numbers."""

    model_config = ConfigDict(strict=True)

    sensor_type: str
    sensor_name: str
    heading_deg: int | None = None
    pitch_deg: float | None = None
    height_m: float | None = None
    view_distance_m: float | None = None
    measured: Literal["pitch", "distance"] | None = None
    mount: str | None = None


class MountingError(ValueError):
    """A value refused. `field` is its name; the message is a sentence with no value in it."""

    def __init__(self, field: str, message: str):
        super().__init__(f"{field} {message}")
        self.field = field


class Change(BaseModel):
    sensor_type: str
    sensor_name: str
    field: str
    counts: bool


class SensorKey(BaseModel):
    sensor_type: str
    sensor_name: str


class Review(BaseModel):
    changes: list[Change]
    ask: bool
    suggested: Literal["moved", "measured"] | None
    new_deployments: list[SensorKey]


def _rounded(value, places: int) -> float | None:
    """`value` rounded to `places`, or None when it isn't a finite int or float (a bool, text, NaN, and so on)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        if not math.isfinite(value):
            return None
        return round_half_away(value, places)
    except (OverflowError, InvalidOperation):
        return None  # too large to round: it is outside every limit anyway


def _settled(key: str, value) -> float | None:
    """The value rounded when it is within the key's limits, else None."""
    places, within, _ = _LIMITS[key]
    rounded = _rounded(value, places)
    return rounded if rounded is not None and within(rounded) else None


def distance_from_tilt(height_m: float | None, pitch_deg: float | None) -> float | None:
    """Along the ground to the centre of the view, `height / tan(tilt)` to two places. None with no height, with a
    tilt of 0 (the centre is at the horizon), or when the result is over 1,000."""
    if height_m is None or pitch_deg is None or pitch_deg == 0:
        return None
    distance = round_half_away(height_m / math.tan(math.radians(pitch_deg)), 2)
    return distance if distance <= VIEW_DISTANCE_MAX_M else None


def tilt_from_distance(height_m: float | None, view_distance_m: float | None) -> float | None:
    """The tilt below level, `atan2(height, distance)` in degrees to one place; 90 when the distance is 0. None with
    no height."""
    if height_m is None or view_distance_m is None:
        return None
    return round_half_away(math.degrees(math.atan2(height_m, view_distance_m)), 1)


def read(sensor_type: str, sensor_name: str, raw: Mapping) -> Mounting:
    """A sensor's `deployment` mapping as "init config defaults" settles it, as the control app sees it. Each of the
    three numbers is rounded and kept when within its limits, the mount when it is a key, and anything else, or blank,
    is None. The heading is read as coordinates.read_heading does. `measured` is None: the file doesn't say. Never
    raises."""
    block = raw if isinstance(raw, Mapping) else {}
    numbers = {key: _settled(key, block.get(key)) for key in _LIMITS}
    mount = block.get("mount")
    return Mounting(
        sensor_type=sensor_type,
        sensor_name=sensor_name,
        heading_deg=read_heading(block),
        mount=mount if isinstance(mount, str) and MOUNT_KEY.fullmatch(mount) else None,
        **numbers,
    )


def checked(given: Mounting, mounts: tuple[Mount, ...] = MOUNTS, keep: str | None = None) -> Mounting:
    """What the API may save: each value within item 1's limits (checked on the rounded value, which is returned), the
    mount one of `mounts` or `keep` (the key config.yml already holds for this sensor, which may be any the file
    allows), a tilt or distance only with `measured`, and the unmeasured one of the two worked out from the measured
    one and the height, whatever was sent for it. A measured value that is empty empties both and `measured`. An
    air-quality monitor has a heading and nothing else. Raises MountingError."""
    heading = given.heading_deg
    if heading is not None and not valid_heading(heading):
        raise MountingError("heading_deg", "isn't a whole number from 0 to 359")
    if given.sensor_type == AIR_QUALITY:
        for field in FIELDS[1:] + ("measured",):
            if getattr(given, field) is not None:
                raise MountingError(field, "isn't recorded for an air-quality monitor")
        return Mounting(sensor_type=given.sensor_type, sensor_name=given.sensor_name, heading_deg=heading)

    if given.measured not in ("pitch", "distance", None):
        raise MountingError("measured", "must be pitch or distance")
    if given.mount is not None and given.mount != keep and given.mount not in {mount.key for mount in mounts}:
        raise MountingError("mount", "isn't one of the usual mounts")
    measured = given.measured
    if measured is None:
        for key in ("pitch_deg", "view_distance_m"):
            if getattr(given, key) is not None:
                raise MountingError(key, "needs the tilt or the distance named as the measured one")
    # the height and the measured one of tilt and distance are checked; the other is worked out and never looked at
    numbers = {}
    for key in ("pitch_deg", "height_m", "view_distance_m"):
        if key == {"pitch": "view_distance_m", "distance": "pitch_deg"}.get(measured):
            continue
        value = getattr(given, key)
        numbers[key] = None if value is None else _settled(key, value)
        if value is not None and numbers[key] is None:
            raise MountingError(key, _LIMITS[key][2])
    pitch, height, distance = numbers.get("pitch_deg"), numbers.get("height_m"), numbers.get("view_distance_m")
    if measured == "pitch":
        distance = distance_from_tilt(height, pitch)
        measured = None if pitch is None else measured
    elif measured == "distance":
        pitch = tilt_from_distance(height, distance)
        measured = None if distance is None else measured
    if measured is None:
        pitch, distance = None, None
    return Mounting(
        sensor_type=given.sensor_type,
        sensor_name=given.sensor_name,
        heading_deg=heading,
        pitch_deg=pitch,
        height_m=height,
        view_distance_m=distance,
        measured=measured,
        mount=given.mount,
    )


def turn(old: Mounting, new: Mounting) -> int | None:
    """The size of a turn: the smaller angle between two headings, 350 to 10 being 20. None when a side has none."""
    if old.heading_deg is None or new.heading_deg is None:
        return None
    angle = abs(old.heading_deg - new.heading_deg) % 360
    return min(angle, 360 - angle)


def _listed_tilt_or_distance(old: Mounting, new: Mounting) -> str:
    """Of the tilt and the distance, the one a review lists: the new measured one, else the old one's, else the tilt."""
    measured = new.measured or old.measured
    return "view_distance_m" if measured == "distance" else "pitch_deg"


def _difference(before: float | None, after: float | None) -> float:
    return 0.0 if before is None or after is None else round(abs(after - before), 6)


def _is_large(field: str, old: Mounting, new: Mounting) -> bool:
    """Whether a counting change of the heading or the height is big enough for the answer to start as "moved or
    turned". Clearing a value has no size."""
    if field == "heading_deg":
        angle = turn(old, new)
        return angle is not None and angle >= MOVED_HEADING_DEG
    return _difference(old.height_m, new.height_m) >= MOVED_HEIGHT_M


def review(
    old: list[Mounting],
    new: list[Mounting],
    recorded: Mapping[tuple[str, str], bool | None],
    moved: bool | None,
) -> Review:
    """Which values changed, whether the question is asked, the answer chosen in advance, and where a new deployment
    starts if the answer is "moved or turned".

    A change counts when a value that was set is changed or cleared: the heading, the height, or the measured one of
    the tilt and the distance. Filling in an empty value doesn't count, and the mount never does. The one worked out
    is never listed, but a tilt that moved 5 degrees or more, however it came about, makes "moved" the answer. The
    question is asked when a sensor has a change that counts and `recorded` doesn't say False for it (False is nothing
    recorded; True, None, or no key all count as something).
    """
    before = {(mounting.sensor_type, mounting.sensor_name): mounting for mounting in old}
    changes: list[Change] = []
    counting: list[tuple[str, str]] = []
    large = False
    for after in new:
        key = (after.sensor_type, after.sensor_name)
        was = before.get(key)
        if was is None:
            continue
        listed_tilt_or_distance = _listed_tilt_or_distance(was, after)
        for field in FIELDS:
            if field in ("pitch_deg", "view_distance_m") and field != listed_tilt_or_distance:
                continue
            if getattr(was, field) == getattr(after, field):
                continue
            counts = field != "mount" and getattr(was, field) is not None
            changes.append(Change(sensor_type=key[0], sensor_name=key[1], field=field, counts=counts))
            if counts:
                if key not in counting:
                    counting.append(key)
                if field in ("heading_deg", "height_m"):
                    large = large or _is_large(field, was, after)
        # the tilt, measured or worked out from a measured distance, whatever changed it: the camera's aim moved
        if key in counting and _difference(was.pitch_deg, after.pitch_deg) >= MOVED_PITCH_DEG:
            large = True
    ask = any(recorded.get(key) is not False for key in counting)
    suggested = None if not ask else ("moved" if large else "measured")
    started = [SensorKey(sensor_type=key[0], sensor_name=key[1]) for key in counting] if moved is True else []
    return Review(changes=changes, ask=ask, suggested=suggested, new_deployments=started)
