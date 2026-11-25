"""Survey ids, config.yml normalising, and coordinate rounding and parsing for the Location page.

Two roundings, on purpose. Typed input (exact, parse_pair) is quantised to five places half away from zero on its
decimal text, because someone typing 45.522525 means that decimal. What tmdb holds (stored) is the exact coordinates
rounded to the survey's precision the way SQLite's ROUND and the engine's Number(value.toFixed(places)) do it: half away
from zero on the binary double, so 2.675 at two places is 2.67, not 2.68. Nothing here logs a coordinate or puts one in an error message; messages name the field or the problem.
"""

import math
import re
import secrets
from collections.abc import Mapping
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

SURVEY_ID = re.compile(r"^[0-9a-f]{8}-si$")
DEPLOYMENT_ID = re.compile(r"^\d+-[0-9a-f]{8}-d$")
POINTS = ("n", "ne", "e", "se", "s", "sw", "w", "nw")
HEADING_MAX = 359
PRECISIONS = ("none", "1", "2")
EXACT_PLACES = 5

_RANGES = {"lat": 90, "lon": 180}
# Digits with an optional leading sign and an optional fraction: no exponent, no decimal comma, no "nan" or "inf".
_NUMBER = r"[+-]?(?:\d+(?:\.\d+)?|\.\d+)"
_NUMBER_RE = re.compile(_NUMBER, re.ASCII)
_PAIR_RE = re.compile(rf"\s*({_NUMBER})(?:\s*,\s*|\s+)({_NUMBER})\s*", re.ASCII)


def new_survey_id() -> str:
    return secrets.token_hex(4) + "-si"


def normalize_survey_id(value) -> str | None:
    """The lower-cased survey id, or None when `value` isn't one (as the flows' init config defaults do)."""
    if value is None or isinstance(value, bool):
        return None
    text = str(value).lower()
    return text if SURVEY_ID.fullmatch(text) else None


def is_coarser(precision: str, than: str) -> bool:
    """Whether precision stores less of the location than `than`. Both must be one of PRECISIONS."""
    return PRECISIONS.index(precision) < PRECISIONS.index(than)


def normalize_precision(value) -> str | None:
    """`none`, `1` or `2` from what config.yml may hold (1, "1", "NONE", 2.0); None for anything else."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        text = str(int(value)) if float(value).is_integer() else ""
    elif isinstance(value, str):
        text = value.lower()
    else:
        return None
    return text if text in PRECISIONS else None


def valid_heading(value) -> bool:
    """Whether value is a heading: an int (not a bool) from 0 to HEADING_MAX."""
    return type(value) is int and 0 <= value <= HEADING_MAX


def point_centre(point) -> int | None:
    """The heading at the centre of a compass point, after trimming and lower-casing; None for anything that isn't
    one of POINTS."""
    if not isinstance(point, str):
        return None
    text = point.strip().lower()
    return POINTS.index(text) * 45 if text in POINTS else None


def compass_point(heading_deg: int) -> str:
    """The point a heading belongs to: 0 to 22 is n, 23 to 67 ne, 68 to 112 e, and so on round to 338 to 359, n."""
    return POINTS[int(((heading_deg + 22.5) % 360) // 45)]


def facing(heading_deg: int | None) -> str:
    """A heading with its point, "NE (40°)"; "" for no heading."""
    if heading_deg is None:
        return ""
    return f"{compass_point(heading_deg).upper()} ({heading_deg}°)"


def read_heading(block) -> int | None:
    """The heading a deployment block in config.yml gives, as Node-RED's init config defaults reads it.

    A usable heading_deg (a whole number from 0 to 359; 40.0 counts as 40, since JavaScript can't tell them apart) is
    the heading. When heading_deg is missing, None or '', the centre of the block's old `bearing` is, if it is one of
    the eight points. Anything else, and a block that isn't a mapping, gives None. Never raises.
    """
    if not isinstance(block, Mapping):
        return None
    heading = block.get("heading_deg")
    if heading is None or heading == "":
        return point_centre(block.get("bearing"))
    if isinstance(heading, float) and heading.is_integer():
        heading = int(heading)
    elif isinstance(heading, int) and not isinstance(heading, bool):
        heading = int(heading)  # the round-trip loader's ScalarInt, which valid_heading's strict check refuses
    return heading if valid_heading(heading) else None


def round_half_away(value, places: int) -> float:
    """Round the binary double `value` to `places` decimals, halves away from zero, as SQLite's ROUND does.

    This is what `stored()` must match, so it works on the double's exact value, not its decimal text: 0.25 at one
    place gives 0.3, but 2.675 (held a hair below 2.675) at two places gives 2.67.
    """
    rounded = Decimal(float(value)).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
    return float(rounded) + 0.0  # + 0.0 turns -0.0 into 0.0


def _quantize_typed(value) -> float:
    """Quantise typed input to five places, half away from zero, on its decimal text (45.522525 gives 45.52253)."""
    quantized = Decimal(str(value)).quantize(Decimal(1).scaleb(-EXACT_PLACES), rounding=ROUND_HALF_UP)
    return float(quantized) + 0.0


def exact(value, kind: str | None = None) -> float | None:
    """A number or numeric string quantised to five places on its decimal text; "" and None give None.

    Raises ValueError for anything else (booleans, NaN, infinity, text), and, for kind "lat" or "lon", for a value out
    of range. The message names the field, never the value.
    """
    field = kind or "value"
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError(f"{field} must be a number")
    if isinstance(value, str):
        value = value.strip()
        if value == "":
            return None
        if not _NUMBER_RE.fullmatch(value):
            raise ValueError(f"{field} must be a number")
    elif isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"{field} must be a finite number")
    try:
        result = _quantize_typed(value)
    except InvalidOperation:
        raise ValueError(f"{field} is out of range") from None
    limit = _RANGES.get(kind) if kind else None
    if limit is not None and abs(result) > limit:
        raise ValueError(f"{field} is out of range")
    return result


def stored(lat, lon, precision: str) -> tuple[float | None, float | None]:
    """What tmdb would hold for these exact coordinates: both None for `none` or when either is missing."""
    if precision not in PRECISIONS:
        raise ValueError("precision must be none, 1 or 2")
    if precision == "none" or lat is None or lon is None:
        return None, None
    places = int(precision)
    return round_half_away(lat, places), round_half_away(lon, places)


def parse_pair(text) -> tuple[float, float]:
    """Parse a pasted "lat, lon" (a comma with optional spaces, or spaces alone) into quantised, range-checked floats."""
    if not isinstance(text, str):
        raise ValueError("coordinates must be text")
    match = _PAIR_RE.fullmatch(text)
    if match is None:
        raise ValueError("coordinates must be two numbers: latitude, longitude")
    lat, lon = match.groups()
    return exact(lat, "lat"), exact(lon, "lon")
