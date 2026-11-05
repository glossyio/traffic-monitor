"""The configuration check group: the names that Frigate's config and Node-RED's config.yml must agree on, which
fail silently when they don't (CLAUDE.md, "Cross-component name contracts"), the deployment's location values, the
ThingsBoard upload's settings, and whether the Frigate+ key and model are paired.

Details name cameras, zones, radars, config.yml keys, and a Frigate+ model's id, never another config value. Log lines
are quoted only as checks.validation_messages and checks.traceback_last_line give them, redacted: Frigate's validation
messages when it starts in safe mode, and the last exception in its journal whenever Frigate doesn't answer.
"""

import math
import os
import re
import stat
from pathlib import Path

from tm_control.core.checks import Check, CheckGroup, Context, Fix
from tm_control.core.secrets import FRIGATE_PLUS_API_KEY, THINGSBOARD_ACCESS_TOKEN
from tm_control.modules.apps import probes
from tm_control.modules.apps.checks import REFUSED_KEY, listed, quoted, traceback_last_line, validation_messages

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
    if probes.frigate_safe_mode(frigate):
        return check("unknown", "Frigate is in safe mode, with no cameras, so its cameras can't be compared with "
                                "config.yml; see the Frigate check under Apps.")
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
    if probes.frigate_safe_mode(frigate):
        return check("unknown", "Frigate is in safe mode, with no cameras, so the cameras' zones can't be checked; see "
                                "the Frigate check under Apps.")
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
    """Each radar under sensors.radars is named as in node-red-tm.env, and each enabled camera's camera_radar is
    enabled."""

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
    return check("ok", "Each radar in config.yml is named as in node-red-tm.env, and each camera's radar is enabled.")


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


# config.yml keys that held a secret before the secrets moved to their own files. Nothing reads them now.
FORMER_SECRET_KEYS = (("thingsboard", "access_token"), ("addons", "plate_recognizer", "token"))
THINGSBOARD_PROTOCOLS = ("http", "https")  # what the flows upload with; init-config turns https into http


def _has_key(data: dict, path: tuple[str, ...]) -> bool:
    section = data
    for part in path[:-1]:
        section = probes.mapping(section.get(part))
    return path[-1] in section


def thingsboard(context: Context) -> list[Check]:
    """The thingsboard block holds values init-config uploads with, the access token is set when the upload is on, and
    no secret is left in config.yml. Never shows the host or a secret."""

    def check(status, detail, fix=None):
        return [Check(id="config.thingsboard", title="ThingsBoard upload", status=status, detail=detail, fix=fix)]

    read = probes.config_yml(context)
    if read.data is None:
        return check("unknown", f"{CONFIG_YML_PROBLEM[read.problem]}, so its ThingsBoard settings can't be checked.")
    block = probes.mapping(read.data.get("thingsboard"))
    enabled = block.get("enabled")
    on = enabled is True
    host = block.get("host")

    errors = []
    if enabled is not None and not isinstance(enabled, bool):
        errors.append("thingsboard.enabled isn't true or false, so Node-RED keeps the upload off. Set it to true or "
                      "false.")
    if on and (host is None or str(host).strip() == ""):
        errors.append("The upload is on in config.yml, but thingsboard.host is empty, so Node-RED keeps it off. Put "
                      "the server's hostname in host.")
    if "protocol" in block and block["protocol"] not in THINGSBOARD_PROTOCOLS:
        errors.append("thingsboard.protocol isn't http or https, so Node-RED doesn't upload. Set it to http or https.")
    if errors:
        return check("error", " ".join(errors))

    warnings = [
        f"config.yml still holds {'.'.join(path)}, which nothing reads. Remove it; the value is set on the Device "
        "page."
        for path in FORMER_SECRET_KEYS
        if _has_key(read.data, path)
    ]
    missing_token = on and not context.secrets.is_set(THINGSBOARD_ACCESS_TOKEN)
    if missing_token:
        warnings.append("The upload is on in config.yml, but no access token is set, so Node-RED keeps it off.")
    if isinstance(host, str) and host.lower().startswith(("http://", "https://")):
        warnings.append("thingsboard.host starts with a scheme, so the protocol key is ignored for it. Put only the "
                        "hostname in host.")
    if warnings:
        fix = Fix(kind="link", text="Set the token", href="/device#tokens-and-keys") if missing_token else None
        return check("warn", " ".join(warnings), fix)
    return check("ok", "The upload is on, with a token set." if on else "The upload is off.")


# Frigate+

PLUS_SCHEME = "plus://"
MODEL_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")  # what a Frigate+ model id may be, and a safe file name in model_cache
# tmsetup_frigate_coral_model_file in the role's vars/main.yml: the model the installer downloads and sets for a Coral
CORAL_MODEL_FILE = "yolov9-s-relu6-tpumax_512_int8_edgetpu.tflite"
DETECTOR_TYPE = re.compile(r"Model does not support detector type of ([\w-]+)")
FRIGATE_CONFIG_PROBLEM = {
    "missing": "Frigate's config.yml is missing",
    "unreadable": "Frigate's config.yml can't be read",
    "invalid": "Frigate's config.yml has a YAML error",
}
SET_THE_KEY = Fix(kind="link", text="Set the key", href="/device#tokens-and-keys")
# How to get out of a Frigate that stops while it fetches a Frigate+ model it can't have
WAYS_OUT = (
    "enter the right key on the Device page, copy the model's two files into Frigate's model_cache directory, or put "
    "the installer's model section back in Frigate's config.yml over SSH, then restart Frigate"
)


def model_path(config_file) -> str | None:
    """model.path in Frigate's config.yml; None when there's no model section or no path in it."""
    path = probes.mapping(probes.mapping(config_file.data).get("model")).get("path")
    return path if isinstance(path, str) else None


def plus_model_id(path) -> str | None:
    """The model id in plus://<id> when it's one a model id can be; None for any other path."""
    if not isinstance(path, str) or not path.startswith(PLUS_SCHEME):
        return None
    model_id = path[len(PLUS_SCHEME):]
    return model_id if MODEL_ID.fullmatch(model_id) else None


def _regular_file(path: Path) -> bool:
    try:
        return stat.S_ISREG(os.stat(path, follow_symlinks=False).st_mode)
    except OSError:
        return False


def model_cached(codedir, model_id: str) -> bool:
    """Both files of a Frigate+ model are in model_cache, so Frigate loads it without asking Frigate+ for it."""
    cache = Path(codedir) / "frigate" / "config" / "model_cache"
    return _regular_file(cache / model_id) and _regular_file(cache / f"{model_id}.json")


def _model_problem(messages: list[str], model_id: str) -> str | None:
    """Why Frigate couldn't use the model, from the validation messages it logged before starting in safe mode."""
    for message in messages:
        detector = DETECTOR_TYPE.search(message)
        if detector:
            kind = detector[1]
            return (f"Frigate couldn't use the Frigate+ model {model_id} and started in safe mode, with no cameras: it "
                    f"isn't built for the {kind} detector. Pick a model made for {kind} in Frigate+, then set it in "
                    "Frigate.")
    for message in messages:
        if "model" in message.lower():
            return (f"Frigate couldn't use the model {model_id} and started in safe mode, with no cameras. Its log "
                    f"says: {quoted(message)}.")
    return None


def frigate_plus(context: Context) -> list[Check]:
    """The Frigate+ key and Frigate's model are paired: a key with a plus:// model, or no key and no Frigate+ model.
    For a plus:// model, says whether Frigate could use it. Whenever Frigate doesn't answer, whatever systemd says of
    its unit (a unit restarted after each crash is active between them), quotes the last exception in its journal,
    and names a key that Frigate+ refused."""

    def check(status, detail, fix=None):
        return [Check(id="config.frigate_plus", title="Frigate+", status=status, detail=detail, fix=fix)]

    read = probes.frigate_config_file(context)
    if read.data is None:
        return check("unknown", f"{FRIGATE_CONFIG_PROBLEM[read.problem]}, so its model and the Frigate+ key can't be "
                                "compared.")
    path = model_path(read)
    key = context.secrets.is_set(FRIGATE_PLUS_API_KEY)
    if not (path or "").startswith(PLUS_SCHEME):
        if not key:
            return check("ok", "Frigate+ isn't in use.")
        if not path:
            which = "Frigate's default model"  # no model section, as on a Hailo or CPU install
        elif path.endswith(CORAL_MODEL_FILE):
            which = "the installer's model"
        else:
            which = "a local model"
        return check("warn", "A Frigate+ key is set, so snapshots can be submitted from Frigate's Explore page, but "
                             f"Frigate runs {which} rather than a Frigate+ model. Once a model is trained, pick it "
                             "under Settings, System, Detectors and model in Frigate, or set model.path to "
                             "plus://<model id> in its configuration editor.")
    model_id = plus_model_id(path)
    if model_id is None:
        return check("error", "model.path in Frigate's config names a Frigate+ model id with characters a model id "
                              "can't have. Check the id in Frigate's configuration editor.")
    cached = model_cached(context.manifest.codedir, model_id)
    if not cached and not key:
        return check("error", f"Frigate's config names the Frigate+ model {model_id}, but no key is set and the "
                              "model's files aren't on the device, so Frigate can't download it. Set the key, or copy "
                              f"{model_id} and {model_id}.json into Frigate's model_cache directory.", SET_THE_KEY)
    running = probes.frigate_config(context)
    if running is None:
        line = traceback_last_line(probes.frigate_journal(context))
        if line is None:
            return check("unknown", f"Frigate isn't answering, so whether it loaded the Frigate+ model {model_id} is "
                                    "unknown.")
        if REFUSED_KEY in line:
            return check("error", "Frigate isn't answering: Frigate+ didn't accept the key when Frigate fetched the "
                                  f"model {model_id}. Its log's last error is: {quoted(line)}. To get Frigate running, "
                                  f"{WAYS_OUT}.", SET_THE_KEY)
        # Another exception shows how Frigate stopped, not why, so the detail doesn't claim the download failed
        return check("error", f"Frigate isn't answering, and the last error in its log is: {quoted(line)}. If it "
                              f"stopped while fetching the Frigate+ model {model_id}, check that the device is "
                              f"online, then {WAYS_OUT}.")
    if running.get("safe_mode") is True:
        problem = _model_problem(validation_messages(probes.frigate_journal(context), limit=None), model_id)
        if problem is not None:
            return check("error", problem)
        # Safe mode for another reason: the Apps group's Frigate check reports it. Frigate has no cameras then, so
        # whether the model loads can't be known.
        return check("unknown", f"Frigate's config names the Frigate+ model {model_id}, but Frigate is in safe mode "
                                "for another reason; see the Frigate check under Apps.")
    if key:
        return check("ok", f"Frigate runs the Frigate+ model {model_id}. Snapshots can be submitted.")
    return check("ok", f"Frigate runs the Frigate+ model {model_id}. It was loaded from the files on the device; set a "
                       "key to submit snapshots.")


GROUP = CheckGroup(
    "config", "Configuration", [cameras_in_config, zones, radar_names, location, thingsboard, frigate_plus]
)
