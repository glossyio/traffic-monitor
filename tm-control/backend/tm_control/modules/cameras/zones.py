"""What Frigate holds for each of a camera's zones, read from /api/config: the facts a reference picture's data file and
drawing carry, and nothing else.

Only the keys listed in zone_facts are read; a zone's friendly_name, and any key Frigate adds later, are never copied.
Every value may be missing or in an odd shape (a person edits Frigate's config), and each zone is still listed.
"""

import math
from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel

from tm_control.modules.apps.probes import mapping

FALLBACK_COLOR = "#888888"  # drawn for a zone Frigate gave no colour


class Corner(BaseModel):
    letter: str  # A, B, C ... in stored order
    x: float  # fractions of the detect frame, from its top-left corner
    y: float


class Side(BaseModel):
    start: str  # a corner's letter
    end: str  # the next corner's letter; the last side ends at A
    length: float


class ZoneFacts(BaseModel):
    key: str
    color: str | None  # "#rrggbb"; None when Frigate gave none
    enabled: bool
    drawn: bool  # on, with at least three corners: outlined in the zones picture and the SVG
    corners: list[Corner]
    distances: list[float]  # as entered in Frigate, in Frigate's order; [] when none
    sides: list[Side]  # the same lengths by side; [] unless there is one length per corner
    inertia: int | None
    loitering_time: int | None
    speed_threshold: float | None
    objects: list[str]
    filters: dict


def corner_letter(index: int) -> str:
    """A to Z, then AA, AB, and so on, as spreadsheet columns go."""
    letters = ""
    index += 1
    while index:
        index, rest = divmod(index - 1, 26)
        letters = chr(ord("A") + rest) + letters
    return letters


def _integer(value) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _number(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def detect_size(camera: Mapping) -> tuple[int, int] | None:
    """The camera's detect width and height, when both are positive integers."""
    detect = mapping(mapping(camera).get("detect"))
    width, height = _integer(detect.get("width")), _integer(detect.get("height"))
    return (width, height) if width and height and width > 0 and height > 0 else None


def distance_unit(config: Mapping) -> Literal["m", "ft"]:
    """Frigate's unit for zone distances: feet when its UI is set to imperial units, else metres."""
    return "ft" if mapping(mapping(config).get("ui")).get("unit_system") == "imperial" else "m"


def _color(value) -> str | None:
    """Frigate's colour as #rrggbb: /api/config gives three integers in blue, green, red order, as its drawing code
    uses them."""
    if not isinstance(value, list) or len(value) != 3:
        return None
    if any(_integer(part) is None or not 0 <= part <= 255 for part in value):
        return None
    blue, green, red = value
    return f"#{red:02x}{green:02x}{blue:02x}"


def _floats(parts: list) -> list[float] | None:
    """Each part as a finite float, or None when any isn't one."""
    found = []
    for part in parts:
        try:
            number = float(part)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(number):
            return None
        found.append(number)
    return found


def _corners(value, size: tuple[int, int] | None) -> list[Corner]:
    """coordinates as a string "x,y,x,y,..." or a list of "x,y" strings. Fractions of the detect frame; values above 1
    are pixels, divided by the detect width or height."""
    if isinstance(value, str):
        parts = value.split(",")
    elif isinstance(value, list) and all(isinstance(point, str) for point in value):
        parts = [part for point in value for part in point.split(",")]
    else:
        return []
    numbers = _floats(parts)
    if numbers is None or len(numbers) % 2 or len(numbers) < 6:
        return []
    if any(number > 1 for number in numbers):
        if size is None:
            return []
        width, height = size
        numbers = [number / (width if i % 2 == 0 else height) for i, number in enumerate(numbers)]
    return [Corner(letter=corner_letter(i // 2), x=numbers[i], y=numbers[i + 1]) for i in range(0, len(numbers), 2)]


def _distances(value) -> list[float]:
    """Frigate's distances, a list of strings ("12.0") or one comma-separated string, as floats."""
    if isinstance(value, str):
        value = value.split(",")
    if not isinstance(value, list):
        return []
    return _floats(value) or []


def _sides(corners: list[Corner], distances: list[float]) -> list[Side]:
    if not corners or len(distances) != len(corners):
        return []
    return [
        Side(start=corner.letter, end=corners[(i + 1) % len(corners)].letter, length=distances[i])
        for i, corner in enumerate(corners)
    ]


def _zone(key: str, value, size: tuple[int, int] | None) -> ZoneFacts:
    zone = mapping(value)
    enabled = zone.get("enabled") is not False
    corners = _corners(zone.get("coordinates"), size)
    distances = _distances(zone.get("distances"))
    objects = zone.get("objects")
    return ZoneFacts(
        key=key,
        color=_color(zone.get("color")),
        enabled=enabled,
        drawn=enabled and len(corners) >= 3,
        corners=corners,
        distances=distances,
        sides=_sides(corners, distances),
        inertia=_integer(zone.get("inertia")),
        loitering_time=_integer(zone.get("loitering_time")),
        speed_threshold=_number(zone.get("speed_threshold")),
        objects=[name for name in objects if isinstance(name, str)] if isinstance(objects, list) else [],
        filters=mapping(zone.get("filters")),
    )


def zone_facts(camera: Mapping) -> list[ZoneFacts]:
    """One ZoneFacts per zone of a camera in Frigate's /api/config, in Frigate's order."""
    zones = mapping(camera).get("zones")
    if not isinstance(zones, dict):
        return []
    size = detect_size(camera)
    return [_zone(str(key), value, size) for key, value in zones.items()]
