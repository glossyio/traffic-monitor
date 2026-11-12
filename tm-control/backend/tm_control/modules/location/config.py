"""The Location and Cameras pages' view of Node-RED's config.yml: the deployment keys and sensors they read, and the
place, precision, per-sensor bearings, and sensors.cameras entries they write in place.

Writes go through RoundTripFile (comments, key order, and quoting kept; a backup beside the file; an atomic replace).
Nothing here puts a coordinate, or any of the file's text, in an error: ConfigError carries a code, and for invalid
YAML the line and column.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.error import CommentMark, MarkedYAMLError, YAMLError
from ruamel.yaml.scalarstring import ScalarString, SingleQuotedScalarString
from ruamel.yaml.tokens import CommentToken

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


@dataclass(frozen=True)
class CameraEntry:
    """One sensors.cameras entry, read as Node-RED reads it."""

    name: str  # the key
    frigate_camera: str  # the field when it is a non-empty string, else the key
    enabled: bool  # enabled is True
    camera_radar: str | None  # a non-empty string, else None
    plate_recognizer: bool  # plate_recognizer is True


def camera_entries(data: Mapping) -> list[CameraEntry]:
    """Every sensors.cameras entry of a parsed config.yml, in file order. An entry that isn't a mapping (`main_st:` with
    nothing under it) reads as the defaults: Frigate's name is the key, and it is off."""
    found = []
    for name, entry in _mapping(_mapping(data.get("sensors")).get("cameras")).items():
        entry = _mapping(entry)
        field, radar = entry.get("frigate_camera"), entry.get("camera_radar")
        found.append(CameraEntry(
            name=str(name),
            frigate_camera=str(field) if isinstance(field, str) and field != "" else str(name),
            enabled=entry.get("enabled") is True,
            camera_radar=str(radar) if isinstance(radar, str) and radar != "" else None,
            plate_recognizer=entry.get("plate_recognizer") is True,
        ))
    return found


# Comments and blank lines, as ruamel keeps them. The text after a mapping's last line (a blank line, the comment above
# the next key) is stored in the trailing comment of the deepest last scalar inside it, after that scalar's own end of
# line. The helpers below move that text when an edit changes which scalar is last.


def _last_leaf(owner, key):
    """(container, key, index) of the comment slot that holds the text after owner[key]: the deepest last item of a
    block mapping or sequence, else the key itself."""
    container, index = owner, key
    while True:
        value = container[index]
        if not isinstance(value, (CommentedMap, CommentedSeq)) or not value or value.fa.flow_style():
            return container, index, 2 if isinstance(container, CommentedMap) else 0
        container, index = value, (list(value.keys())[-1] if isinstance(value, CommentedMap) else len(value) - 1)


def _split_after(owner, key) -> tuple[list | None, int, str, str]:
    """The comment slot after owner[key] (its list and index; None when it has none), and its text split into the last
    line's own end of line (and end-of-line comment) and the text after it."""
    container, index, slot = _last_leaf(owner, key)
    comments = container.ca.items.get(index)
    if not comments or comments[slot] is None:
        return None, slot, "", ""
    own, newline, after = comments[slot].value.partition("\n")
    return comments, slot, own + newline, after


def _text_after(owner, key) -> str:
    return _split_after(owner, key)[3]


def _take_after(owner, key) -> str:
    """Remove and return the text after owner[key]'s last line (its own end-of-line comment stays)."""
    comments, slot, own, after = _split_after(owner, key)
    if comments is not None:
        if own.strip():
            comments[slot].value = own
        else:
            comments[slot] = None
    return after


def _put_after(owner, key, text: str) -> None:
    """Put text after owner[key]'s last line, after what is there already."""
    if not text:
        return
    container, index, slot = _last_leaf(owner, key)
    comments = container.ca.items.setdefault(index, [None, None, None, None])
    if comments[slot] is None:
        comments[slot] = CommentToken("\n" + text, CommentMark(0), None)
    else:
        own = comments[slot].value
        comments[slot].value = (own if own.endswith("\n") else own + "\n") + text


def _lines(text: str) -> list[str]:
    return text.splitlines(keepends=True)


def _is_comment(line: str) -> bool:
    return line.lstrip().startswith("#")


def _drop_trailing(lines: list[str], test) -> list[str]:
    while lines and test(lines[-1]):
        lines = lines[:-1]
    return lines


def _blank_line(line: str) -> bool:
    return not line.strip()


def _set(entry: CommentedMap, key: str, value, after: tuple[str, ...]) -> None:
    """Set key in place, keeping its comment and a string's quoting; a new key goes after the first of `after` that
    the entry has, else first."""
    if key in entry:
        old = entry[key]
        if isinstance(old, ScalarString) and isinstance(value, str):
            value = type(old)(value)
        entry[key] = value
        return
    keys = list(entry.keys())
    position = next((keys.index(name) + 1 for name in after if name in entry), 0)
    entry.insert(position, key, value)


def _remove(entry: CommentedMap, key: str) -> None:
    if key in entry:
        del entry[key]
        entry.ca.items.pop(key, None)


def _append(owner: CommentedMap, key, value, holder=None) -> None:
    """Add key at the end of owner. It takes the text that ended owner (the blank line before the next block, and
    any comment above it), and when owner's last two keys have a blank line between them, its new last two do too.
    holder: (parent, key) for owner, where the text is when owner is empty."""
    keys = list(owner.keys())
    if keys:
        after = _take_after(owner, keys[-1])
    elif holder is not None:
        after = _take_after(*holder)
    else:
        after = ""
    if not keys:
        owner.fa.set_block_style()  # an empty mapping reads as {}
    owner[key] = value
    _put_after(owner, key, after)
    if len(keys) >= 2:
        before = (owner.ca.items.get(keys[-1]) or [None, None])[1] or []
        if _text_after(owner, keys[-2]).startswith("\n") or (before and _blank_line(before[0].value)):
            _put_after(owner, keys[-1], "\n")


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

    def cameras(self) -> list[CameraEntry]:
        return camera_entries(self._file.data)

    def radars(self) -> dict[str, bool]:
        """Each sensors.radars entry's name, and whether it is on."""
        radars = _mapping(_mapping(self._file.data.get("sensors")).get("radars"))
        return {str(name): _mapping(radar).get("enabled") is True for name, radar in radars.items()}

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

    def _camera(self, name: str) -> tuple[CommentedMap, object]:
        """sensors.cameras and the key that reads as name. Raises KeyError for a camera that isn't in the file."""
        sensors = self._file.data.get("sensors")
        cameras = sensors.get("cameras") if isinstance(sensors, CommentedMap) else None
        if isinstance(cameras, CommentedMap):
            for key in cameras:
                if str(key) == name:
                    return cameras, key
        raise KeyError(name)

    @staticmethod
    def _entry(cameras: CommentedMap, key) -> CommentedMap:
        """An entry to edit; one with nothing under it (`main_st:`) becomes an empty mapping."""
        entry = cameras[key]
        if entry is None:
            entry = cameras[key] = CommentedMap()
        elif not isinstance(entry, CommentedMap):
            raise ConfigError("invalid")
        return entry

    def add_camera(
        self, name: str, frigate_camera: str, enabled: bool, camera_radar: str | None, plate_recognizer: bool | None
    ) -> None:
        """Add sensors.cameras.<name> at the end of the block, creating the block (at the end of sensors) and sensors
        (at the end of the file) when they are missing. None writes no camera_radar or plate_recognizer key.

        Raises ValueError when name is already a camera."""
        entry = CommentedMap()
        entry["frigate_camera"] = frigate_camera
        entry["enabled"] = enabled
        if camera_radar is not None:
            entry["camera_radar"] = camera_radar
        if plate_recognizer is not None:
            entry["plate_recognizer"] = plate_recognizer
        data = self._file.data
        sensors = data.get("sensors")
        if sensors is None and "sensors" not in data:
            _append(data, "sensors", CommentedMap([("cameras", CommentedMap([(name, entry)]))]))
            return
        if sensors is None:
            sensors = data["sensors"] = CommentedMap()
        elif not isinstance(sensors, CommentedMap):
            raise ConfigError("invalid")
        cameras = sensors.get("cameras")
        if cameras is None and "cameras" not in sensors:
            _append(sensors, "cameras", CommentedMap([(name, entry)]), holder=(data, "sensors"))
            return
        if cameras is None:
            cameras = sensors["cameras"] = CommentedMap()
        elif not isinstance(cameras, CommentedMap):
            raise ConfigError("invalid")
        if any(str(key) == name for key in cameras):
            raise ValueError("a camera already has that name")
        _append(cameras, name, entry, holder=(sensors, "cameras"))

    def set_camera(self, name: str, enabled: bool, camera_radar: str | None, plate_recognizer: bool | None) -> None:
        """Set a camera's enabled, camera_radar (None removes the key), and plate_recognizer (None leaves the key as it
        is). A key the entry doesn't have yet is added in the order add_camera writes them.

        Raises KeyError for a camera that isn't in the file."""
        cameras, key = self._camera(name)
        entry = self._entry(cameras, key)
        after = _take_after(cameras, key)
        _set(entry, "enabled", enabled, ("frigate_camera",))
        if camera_radar is None:
            _remove(entry, "camera_radar")
        else:
            _set(entry, "camera_radar", camera_radar, ("enabled",))
        if plate_recognizer is not None:
            _set(entry, "plate_recognizer", plate_recognizer, ("camera_radar", "enabled"))
        _put_after(cameras, key, after)

    def point_camera(self, name: str, frigate_camera: str) -> None:
        """Set a camera's frigate_camera, as the entry's first key when it has none.

        Raises KeyError for a camera that isn't in the file."""
        cameras, key = self._camera(name)
        self._point(cameras, key, frigate_camera)

    def _point(self, cameras: CommentedMap, key, frigate_camera: str) -> None:
        entry = self._entry(cameras, key)
        after = _take_after(cameras, key)
        _set(entry, "frigate_camera", frigate_camera, ())
        _put_after(cameras, key, after)

    def rename_camera(self, old: str, new: str) -> None:
        """Re-key a camera in place: its position, the comments on and above it, and every key under it stay. When
        the entry has no frigate_camera (or one that names no camera: empty, or not a string), it gets frigate_camera:
        <old> as its first key, so that it still names the Frigate camera it named.

        Raises KeyError for a camera that isn't in the file, ValueError when new is already a camera."""
        cameras, key = self._camera(old)
        if any(str(other) == new for other in cameras):
            raise ValueError("a camera already has that name")
        if cameras[key] is not None and not isinstance(cameras[key], CommentedMap):
            raise ConfigError("invalid")
        position = list(cameras.keys()).index(key)
        comments = cameras.ca.items.pop(key, None)
        entry = cameras.pop(key)
        cameras.insert(position, new, entry)
        if comments is not None:
            cameras.ca.items[new] = comments
        field = entry.get("frigate_camera") if entry is not None else None
        if not isinstance(field, str) or field == "":
            self._point(cameras, new, str(key))

    def remove_camera(self, name: str) -> None:
        """Remove a camera with the comment directly above it. The blank lines around it close up as the file has them
        between its other entries, and the text after it (a blank line, the comment above what comes next) stays.

        Raises KeyError for a camera that isn't in the file."""
        cameras, key = self._camera(name)
        sensors = self._file.data["sensors"]
        keys = list(cameras.keys())
        position = keys.index(key)
        after = _take_after(cameras, key)
        cameras.ca.items.pop(key, None)  # its own line's comments, and any kept before its key
        del cameras[key]
        if position > 0:
            # The text between the entry above and this one ends with this one's comment: drop that, and the blank
            # lines then left at its end, and keep what came after this one.
            previous = keys[position - 1]
            between = _drop_trailing(_drop_trailing(_lines(_take_after(cameras, previous)), _is_comment), _blank_line)
            _put_after(cameras, previous, "".join(between) + after)
            return
        # The first entry's comment is kept with the cameras key, as the lines before the block's first key (the block
        # holds the same list).
        slot = sensors.ca.items.setdefault("cameras", [None, None, None, None])
        if slot[3] is None:
            slot[3] = []
        above = slot[3]
        while above and _is_comment(above[-1].value):
            above.pop()
        if not cameras:
            # `cameras:` with nothing under it, as a person would leave it (an empty mapping would print as {}, after
            # the text that follows it)
            sensors["cameras"] = None
            if not any(_is_comment(token.value) for token in above):
                above.clear()
            _put_after(sensors, "cameras", after)
            return
        # The comment that was above the next entry moves up with it; the blank line between them goes.
        lines = _drop_trailing(_drop_trailing(_lines(after)[::-1], _blank_line)[::-1], _blank_line)
        above.extend(
            CommentToken(line.lstrip(" "), CommentMark(len(line) - len(line.lstrip(" "))), None) for line in lines
        )
        following = cameras.ca.items.get(keys[1])
        if following is not None and following[1]:
            while following[1] and _blank_line(following[1][0].value):
                following[1].pop(0)

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
