"""Where the Location page's map opens when there is no place to start from: the device's region.

The region is the city of the device's time zone, read from the Pi's own time-zone data (the tables `zone1970.tab` and,
for the names it merged away, `zone.tab`), so nothing leaves the device and no boundary data is needed. The zone may be
nobody's choice for this device (the image's or the imager's, until the Date and time page or the installer's `-z` sets
one), which is why the city counts only when the Wi-Fi country is known and is one of the countries the zone's row
lists; otherwise the map opens on the whole world. A unit left on a zone and Wi-Fi country that agree opens over that
zone's city until its zone is set on the Date and time page.
Anything unreadable, missing, or malformed gives no region and raises nothing.
"""

import logging
import re
from pathlib import Path

from pydantic import BaseModel

log = logging.getLogger(__name__)

ZONE_TAB = Path("/usr/share/zoneinfo/zone1970.tab")  # merged zones: one row for each group of countries
ZONE_TAB_ALL = Path("/usr/share/zoneinfo/zone.tab")  # one row per country, with the names zone1970.tab merged away
PLACES = 2  # decimal places kept: a city, not a street

# ISO 6709 as zone1970.tab writes it: ±DDMM±DDDMM or ±DDMMSS±DDDMMSS
_ISO_6709 = re.compile(r"([+-])(\d{2})(\d{2})(\d{2})?([+-])(\d{3})(\d{2})(\d{2})?", re.ASCII)


class LatLon(BaseModel):
    lat: float
    lon: float


def parse_iso_6709(text: str) -> LatLon | None:
    """The coordinates as decimal degrees rounded to two places, or None when `text` isn't a valid ISO 6709 pair."""
    match = _ISO_6709.fullmatch(text)
    if match is None:
        return None
    lat_sign, lat_d, lat_m, lat_s, lon_sign, lon_d, lon_m, lon_s = match.groups()
    values = []
    for sign, degrees, minutes, seconds, limit in (
        (lat_sign, lat_d, lat_m, lat_s, 90),
        (lon_sign, lon_d, lon_m, lon_s, 180),
    ):
        if int(minutes) >= 60 or int(seconds or 0) >= 60:
            return None
        value = int(degrees) + int(minutes) / 60 + int(seconds or 0) / 3600
        if value > limit:
            return None
        values.append(-value if sign == "-" else value)
    return LatLon(lat=round(values[0], PLACES) + 0.0, lon=round(values[1], PLACES) + 0.0)


def _row(path: Path, timezone: str, country: str) -> tuple[bool, LatLon | None]:
    """Whether the table lists `timezone`, and its city when `country` is one of the row's countries."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        log.warning("The time-zone table couldn't be read")
        return False, None
    for line in text.splitlines():
        if line.startswith("#"):
            continue
        columns = line.split("\t")
        if len(columns) < 3 or columns[2] != timezone:
            continue
        if country.upper() not in columns[0].split(","):
            return True, None
        return True, parse_iso_6709(columns[1])
    return False, None


def region(
    timezone: str | None, country: str | None, path: Path | None = None, fallback: Path | None = None
) -> LatLon | None:
    """The city of `timezone`, only if `country` (the Wi-Fi country, "" when unset) is one of that zone's countries.

    `zone1970.tab` answers first; a zone it doesn't list is looked up in `zone.tab`. Without `fallback`, that is
    `zone.tab` beside `path` when `path` is given, else the Pi's own.
    """
    if not timezone or not country:
        return None
    if fallback is None:
        fallback = path.with_name("zone.tab") if path else ZONE_TAB_ALL
    found, city = _row(path or ZONE_TAB, timezone, country)
    if found:
        return city
    return _row(fallback, timezone, country)[1]
