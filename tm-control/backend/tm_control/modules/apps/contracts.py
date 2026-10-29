"""The configuration check group: the names that Frigate's config and Node-RED's config.yml must agree on, which
fail silently when they don't (CLAUDE.md, "Cross-component name contracts"), and the deployment's location values.

Details name cameras, zones, radars, and config.yml keys, never another config value.
"""

import math

from tm_control.core.checks import Check, CheckGroup, Context
from tm_control.modules.apps import probes
from tm_control.modules.apps.checks import listed

ZONES = ("zone_capture", "zone_near", "zone_far", "zone_radar")  # the zone names the flows expect
DIRECTION_ZONES = ("zone_near", "zone_far")
BEARINGS = ("n", "s", "e", "w", "ne", "nw", "se", "sw")
CONFIG_YML_PROBLEM = {
    "missing": "config.yml is missing",
    "unreadable": "tm-control can't read config.yml",
    "invalid": "config.yml has a YAML error",
}


def env_radar_names(manifest) -> list[str]:
    """The radars' names: node-red-tm.env's TM_RADAR_SERIAL_PORT_0N, one for each of the install's radar paths."""
    return [f"TM_RADAR_SERIAL_PORT_{index:02d}" for index in range(len(manifest.probes.radar_paths))]


def _sensors(data: dict, kind: str) -> dict[str, dict]:
    section = probes.mapping(probes.mapping(data.get("sensors")).get(kind))
    return {str(name): probes.mapping(value) for name, value in section.items()}


def _enabled(sensor: dict) -> bool:
    return sensor.get("enabled") is True


def cameras_in_config(context: Context) -> list[Check]:
    """Every camera enabled in Frigate is enabled under sensors.cameras in config.yml, by the same name."""

    def check(status, detail):
        return [Check(id="config.cameras", title="Cameras in config.yml", status=status, detail=detail)]

    read = probes.config_yml(context)
    if read.data is None:
        return check("unknown", f"{CONFIG_YML_PROBLEM[read.problem]}, so its cameras can't be compared with Frigate's.")
    frigate = probes.frigate_config(context)
    if frigate is None:
        return check("unknown", "Frigate isn't answering, so its cameras can't be compared with config.yml.")
    in_frigate = probes.frigate_cameras(frigate)
    configured = _sensors(read.data, "cameras")
    problems = []
    for name in in_frigate:
        if name not in configured:
            problems.append(f"Events from {name} are not recorded: config.yml has no sensors.cameras.{name}.")
        elif not _enabled(configured[name]):
            problems.append(f"Events from {name} are not recorded: it isn't enabled in config.yml.")
    if problems:
        return check("error", " ".join(problems) + " Add or enable each Frigate camera under sensors.cameras in "
                                                   "config.yml, by the same name.")
    extra = [name for name, camera in configured.items() if _enabled(camera) and name not in in_frigate]
    if extra:
        return check("warn", f"config.yml enables {listed(extra)}, which Frigate doesn't have as an enabled camera. "
                             "Rename it to match Frigate's camera, or disable it.")
    if not in_frigate:
        return check("ok", "Frigate has no enabled camera to compare.")
    return check("ok", f"{listed(in_frigate)} {'is' if len(in_frigate) == 1 else 'are'} in Frigate and enabled in "
                       "config.yml.")


def zones(context: Context) -> list[Check]:
    """Each camera enabled in both has the zones the flows expect in Frigate."""

    def check(status, detail):
        return [Check(id="config.zones", title="Zones", status=status, detail=detail)]

    read = probes.config_yml(context)
    if read.data is None:
        return check("unknown", f"{CONFIG_YML_PROBLEM[read.problem]}, so the cameras' zones can't be checked.")
    frigate = probes.frigate_config(context)
    if frigate is None:
        return check("unknown", "Frigate isn't answering, so the cameras' zones can't be checked.")
    configured = _sensors(read.data, "cameras")
    problems = []
    for name, camera in probes.frigate_cameras(frigate).items():
        if not _enabled(configured.get(name, {})):
            continue
        missing = [zone for zone in ZONES if zone not in probes.mapping(camera.get("zones"))]
        if not missing:
            continue
        problem = f"Camera {name} has no {listed(missing, 'or')} in Frigate"
        if any(zone in missing for zone in DIRECTION_ZONES):
            problem += "; without zone_near and zone_far, events get a direction only from the radar (#243)"
        problems.append(f"{problem}.")
    if problems:
        return check("warn", " ".join(problems) + " Draw the missing zones in Frigate, named exactly as listed.")
    return check("ok", f"Each enabled camera has {listed(ZONES)}.")


def radar_names(context: Context) -> list[Check]:
    """Each radar under sensors.radars has a radar's name, and each enabled camera's camera_radar is enabled."""

    def check(status, detail):
        return [Check(id="config.radars", title="Radar names", status=status, detail=detail)]

    read = probes.config_yml(context)
    if read.data is None:
        return check("unknown", f"{CONFIG_YML_PROBLEM[read.problem]}, so its radar names can't be checked.")
    names = env_radar_names(context.manifest)
    configured = _sensors(read.data, "radars")
    problems = []
    unknown = [name for name in configured if name not in names]
    if unknown:
        if len(unknown) == 1:
            problems.append(f"{unknown[0]} under sensors.radars isn't a radar's name, so Node-RED doesn't read it.")
        else:
            problems.append(f"{listed(unknown)} under sensors.radars aren't radars' names, so Node-RED doesn't read "
                            "them.")
        problems.append(f"Name each radar {listed(names, 'or')}, as in node-red-tm.env.")
    enabled = {name for name, radar in configured.items() if _enabled(radar)}
    unpaired = [
        f"Camera {name} is paired with radar {camera['camera_radar']}, which isn't enabled; its events are dropped "
        "(#255)."
        for name, camera in _sensors(read.data, "cameras").items()
        if _enabled(camera) and camera.get("camera_radar") and str(camera["camera_radar"]) not in enabled
    ]
    if unpaired:
        problems += unpaired + ["Enable that radar under sensors.radars, or pair the camera with an enabled one."]
    if problems:
        return check("error", " ".join(problems))
    return check("ok", "Each radar has a radar's name, and each camera's radar is enabled.")


def _number_in(value, low: float, high: float) -> bool:
    if value is None or value == "":
        return True  # not set yet, as installed
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return math.isfinite(value) and low <= value <= high


def location(context: Context) -> list[Check]:
    """deployment.lat, .lon, and .bearing hold values Node-RED accepts."""

    def check(status, detail):
        return [Check(id="config.deployment", title="Location", status=status, detail=detail)]

    read = probes.config_yml(context)
    if read.data is None:
        return check("unknown", f"{CONFIG_YML_PROBLEM[read.problem]}, so its location can't be checked.")
    deployment = probes.mapping(read.data.get("deployment"))
    problems = []
    if not _number_in(deployment.get("lat"), -90, 90):
        problems.append("deployment.lat isn't a number from -90 to 90")
    if not _number_in(deployment.get("lon"), -180, 180):
        problems.append("deployment.lon isn't a number from -180 to 180")
    bearing = deployment.get("bearing")
    if bearing not in (None, "") and not (isinstance(bearing, str) and bearing.lower() in BEARINGS):
        problems.append(f"deployment.bearing isn't one of {', '.join(BEARINGS)}, or empty")
    if problems:
        fix = "Correct it, or leave it empty." if len(problems) == 1 else "Correct them, or leave them empty."
        return check("error", f"In config.yml, {'; '.join(problems)}. {fix}")
    if deployment.get("lat") in (None, "") and deployment.get("lon") in (None, ""):
        return check("ok", "No location is set.")
    return check("ok", "The location's values are valid.")


GROUP = CheckGroup("config", "Configuration", [cameras_in_config, zones, radar_names, location])
