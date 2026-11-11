"""The Location page's view of Node-RED's config.yml: the deployment keys and enabled sensors it reads, and the place,
precision, and per-sensor bearings it writes in place.

Writes go through RoundTripFile (comments, key order, and quoting kept; a backup beside the file; an atomic replace).
Nothing here puts a coordinate, or any of the file's text, in an error: ConfigError carries a code, and for invalid
YAML the line and column.
"""

from collections.abc import Mapping
from pathlib import Path
from typing import Literal

from pydantic import BaseModel
from ruamel.yaml.comments import CommentedMap
from ruamel.yaml.error import MarkedYAMLError, YAMLError
from ruamel.yaml.scalarstring import SingleQuotedScalarString

from tm_control.adapters import nodered
from tm_control.adapters.yamlfile import ConcurrentEditError, ConfigRead, blank_line_after, put_after
from tm_control.modules.location.coordinates import (
    PRECISIONS,
    exact,
    normalize_bearing,
    normalize_precision,
    normalize_survey_id,
)
from tm_control.modules.location.places import Bearing

SENSOR_TYPES = ("cameras", "radars", "airquality_monitors")
DEFAULT_PRECISION = "2"  # what the engine uses when database_precision is missing or invalid


class ConfigError(Exception):
    """Why config.yml couldn't be loaded or saved: missing, unreadable, invalid (not YAML, or not a mapping), changed
    (edited after it was loaded), or write_failed. Never carries the file's text."""

    def __init__(self, code: str, line: int | None = None, column: int | None = None):
        super().__init__(code)
        self.code = code
        self.line = line
        self.column = column


class Deployment(BaseModel):
    survey_id: str | None
    lat: float | None
    lon: float | None
    precision: str
    survey_id_invalid: bool
    precision_invalid: bool
    precision_missing: bool  # database_precision absent or blank (precision is then the default)
    # A lat or lon that is there but isn't a number in range, or only one of the two: lat and lon are then not a
    # point to follow or match, though the file has something in them.
    coordinates_invalid: bool


def _blank(value) -> bool:
    return value is None or value == ""


def _blank_coordinate(value) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "")


def _coordinate(value, kind: str) -> float | None:
    try:
        return exact(value, kind)
    except ValueError:
        return None


def _precision(value) -> str | None:
    # The engine compares the text exactly, so an upper-case string is not a precision there; a number is.
    if isinstance(value, str) and value != value.lower():
        return None
    return normalize_precision(value)


def _parse_deployment(data: Mapping) -> Deployment:
    block = data.get("deployment")
    if not isinstance(block, Mapping):
        block = {}
    raw_id = block.get("survey_id")
    survey_id = normalize_survey_id(raw_id)
    raw_precision = block.get("database_precision")
    precision = _precision(raw_precision)
    raw_lat, raw_lon = block.get("lat"), block.get("lon")
    lat, lon = _coordinate(raw_lat, "lat"), _coordinate(raw_lon, "lon")
    lat_blank, lon_blank = _blank_coordinate(raw_lat), _blank_coordinate(raw_lon)
    return Deployment(
        survey_id=survey_id,
        lat=lat,
        lon=lon,
        precision=precision or DEFAULT_PRECISION,
        survey_id_invalid=not _blank(raw_id) and survey_id is None,
        precision_invalid=not _blank(raw_precision) and precision is None,
        precision_missing=_blank(raw_precision),
        coordinates_invalid=(
            (not lat_blank and lat is None) or (not lon_blank and lon is None) or lat_blank != lon_blank
        ),
    )


def read_deployment(read: ConfigRead) -> Deployment | None:
    """The deployment keys from a file already read with read_config; None when it couldn't be read.

    Lenient, like Node-RED's own defaults: a missing or invalid value reads as None (coordinates) or the default
    (precision), with the survey id and precision flagged invalid. The Status check reports bad coordinates from the
    raw file, not from here.
    """
    if read.data is None:
        return None
    return _parse_deployment(read.data)


def _mapping(value) -> Mapping:
    return value if isinstance(value, Mapping) else {}


class NodeRedConfig:
    """config.yml loaded for reading and editing. Edit with the set_* methods, then save()."""

    def __init__(self, path: Path):
        self._path = Path(path)
        self._blank_to_move = None  # the blank line to hand to a new deployment block's last key at save time
        try:
            self._file = nodered.open_config(self._path)
        except FileNotFoundError:
            raise ConfigError("missing") from None
        except (OSError, UnicodeDecodeError):
            raise ConfigError("unreadable") from None
        except MarkedYAMLError as error:
            mark = error.problem_mark or error.context_mark
            if mark is None:
                raise ConfigError("invalid") from None
            raise ConfigError("invalid", mark.line + 1, mark.column + 1) from None
        except YAMLError:
            raise ConfigError("invalid") from None
        if not isinstance(self._file.data, CommentedMap):
            raise ConfigError("invalid")

    # reading

    def deployment(self) -> Deployment:
        """The deployment keys, leniently: see read_deployment."""
        return _parse_deployment(self._file.data)

    def sensors(self) -> list[Bearing]:
        """Every enabled sensor with its bearing as the engine copies it down: the sensor's own deployment.bearing
        when that key is there, else the top-level one; "" when blank or invalid."""
        data = self._file.data
        top = normalize_bearing(_mapping(data.get("deployment")).get("bearing"))
        found = []
        for sensor_type in SENSOR_TYPES:
            for name, sensor in _mapping(_mapping(data.get("sensors")).get(sensor_type)).items():
                if not isinstance(sensor, Mapping) or sensor.get("enabled") is not True:
                    continue
                own = sensor.get("deployment")
                if isinstance(own, Mapping) and "bearing" in own:
                    bearing = normalize_bearing(own["bearing"])
                else:
                    bearing = top
                found.append(Bearing(sensor_type=sensor_type, sensor_name=str(name), bearing=bearing or ""))
        return found

    def listed_sensors(self) -> set[tuple[str, str]] | None:
        """(type, name) of every sensor the file lists under any type, on or off; None when `sensors` isn't a mapping,
        and the engine then ends no deployment."""
        sensors = self._file.data.get("sensors")
        if not isinstance(sensors, Mapping):
            return None
        return {(str(sensor_type), str(name)) for sensor_type, block in sensors.items() for name in _mapping(block)}

    def blank_bearings(self) -> list[tuple[str, str]]:
        """(type, name) of every enabled sensor whose bearing, as the engine copies it down, is missing or empty; an
        invalid one, which sensors() also reads as "", isn't blank."""
        data = self._file.data
        top = _mapping(data.get("deployment")).get("bearing")
        found = []
        for sensor_type in SENSOR_TYPES:
            for name, sensor in _mapping(_mapping(data.get("sensors")).get(sensor_type)).items():
                if not isinstance(sensor, Mapping) or sensor.get("enabled") is not True:
                    continue
                own = sensor.get("deployment")
                value = own["bearing"] if isinstance(own, Mapping) and "bearing" in own else top
                if _blank(value):
                    found.append((sensor_type, str(name)))
        return found

    def sharing(self) -> Literal["data", "none"]:
        """"data" when ThingsBoard uploads are enabled."""
        return "data" if _mapping(self._file.data.get("thingsboard")).get("enabled") is True else "none"

    # editing

    def _deployment_block(self) -> CommentedMap:
        """The top-level deployment block, created (after thingsboard when that is there, else at the end) when it is
        missing or empty."""
        data = self._file.data
        block = data.get("deployment")
        if isinstance(block, CommentedMap):
            return block
        if block is not None:
            raise ConfigError("invalid")
        block = CommentedMap()
        if "deployment" in data:
            data["deployment"] = block
        elif "thingsboard" in data:
            position = list(data.keys()).index("thingsboard") + 1
            data.insert(position, "deployment", block)
            above = data["thingsboard"]
            if isinstance(above, CommentedMap) and above and position < len(data) - 1:
                self._blank_to_move = (above, list(above.keys())[-1], block)
        else:
            data["deployment"] = block
        return block

    def set_place(self, survey_id: str | None, lat: float | None, lon: float | None) -> None:
        """Write deployment.survey_id (lower case) and lat and lon; None leaves a key empty (`lat:`)."""
        if survey_id is not None and normalize_survey_id(survey_id) is None:
            raise ValueError("survey_id must be a survey id")
        lat = exact(lat, "lat")
        lon = exact(lon, "lon")
        block = self._deployment_block()
        put_after(block, "lat", lat)
        put_after(block, "lon", lon, after="lat")
        put_after(block, "survey_id", None if survey_id is None else survey_id.lower(), after="bearing")

    def set_survey_id(self, survey_id: str) -> None:
        """Write deployment.survey_id (lower case) alone, leaving lat and lon as the file has them."""
        if normalize_survey_id(survey_id) is None:
            raise ValueError("survey_id must be a survey id")
        put_after(self._deployment_block(), "survey_id", survey_id.lower(), after="bearing")

    def set_precision(self, precision: str) -> None:
        if precision not in PRECISIONS:
            raise ValueError("precision must be none, 1 or 2")
        block = self._deployment_block()
        put_after(block, "database_precision", SingleQuotedScalarString(precision), after="survey_id")

    def set_sensor_bearing(self, sensor_type: str, sensor_name: str, bearing: str) -> None:
        """Write sensors.<type>.<name>.deployment.bearing, creating the sensor's deployment block when it has none and
        the bearing says something the top-level one doesn't.

        Raises KeyError for a sensor that isn't in the file.
        """
        bearing = normalize_bearing(bearing)
        if bearing is None:
            raise ValueError("bearing must be a compass point or empty")
        if sensor_type not in SENSOR_TYPES:
            raise KeyError(sensor_type)
        sensors = _mapping(_mapping(self._file.data.get("sensors")).get(sensor_type))
        sensor = sensors.get(sensor_name)
        if not isinstance(sensor, CommentedMap):
            raise KeyError(sensor_name)
        block = sensor.get("deployment")
        if block is None:
            if bearing == "" and _blank(_mapping(self._file.data.get("deployment")).get("bearing")):
                return  # it reads blank already (the engine copies the top-level bearing down): no block to add
            block = CommentedMap()
            last = list(sensor.keys())[-1] if sensor else None
            sensor["deployment"] = block
            block["bearing"] = None
            blank_line_after(sensor, last, block, "bearing", move=True)
        elif not isinstance(block, CommentedMap):
            raise ConfigError("invalid")
        block["bearing"] = SingleQuotedScalarString(bearing)

    def save(self) -> bool:
        """Write the file when the edits changed it. True when it did (a backup is beside it); False, and nothing
        written, when it is as it was loaded."""
        if self._blank_to_move is not None:
            owner, key, block = self._blank_to_move
            self._blank_to_move = None
            if block:
                blank_line_after(owner, key, block, list(block.keys())[-1], move=False)
        try:
            return self._file.save() is not None
        except ConcurrentEditError:
            raise ConfigError("changed") from None
        except OSError:
            raise ConfigError("write_failed") from None
