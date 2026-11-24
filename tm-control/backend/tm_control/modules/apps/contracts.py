"""The configuration check group: the names that Frigate's config and Node-RED's config.yml must agree on, which
fail silently when they don't (CLAUDE.md, "Cross-component name contracts"), the deployment's location values, the
ThingsBoard upload's settings, what the unit shares, and whether the Frigate+ key and model are paired.

Details name cameras, the zones the flows expect, radars, config.yml keys, and a Frigate+ model's id, never another
config value (the Sharing check never names the server or a notice version). Other zone names, which an operator typed,
are counted and never quoted, because details go into Copy diagnostics. Log lines are quoted only as
checks.validation_messages and checks.traceback_last_line give them, redacted: Frigate's validation messages when it
starts in safe mode, and the last exception in its journal whenever Frigate doesn't answer.
"""

import os
import re
import stat
from pathlib import Path
from urllib.parse import quote

from tm_control.core.checks import Check, CheckGroup, Context, Fix
from tm_control.core.secrets import FRIGATE_PLUS_API_KEY, THINGSBOARD_ACCESS_TOKEN
from tm_control.modules.apps import probes
from tm_control.modules.apps.checks import REFUSED_KEY, listed, quoted, traceback_last_line, validation_messages
from tm_control.modules.location.config import (
    camera_entries,
    read_deployment,
    read_sharing,
    sends_public_map,
    sharing_ignored,
    sharing_kind,
)
from tm_control.modules.location.coordinates import exact
from tm_control.modules.location.places import Places
from tm_control.modules.sharing.consents import MAINTAINER, PRE_CONSENT, Consents, target_key

ZONES = ("zone_capture", "zone_near", "zone_far", "zone_radar")  # the zone names the flows expect
DIRECTION_ZONES = ("zone_near", "zone_far")
CAMERAS_LINK = Fix(kind="link", href="/cameras", text="Open the Cameras page")
DETECTION_LINK = Fix(kind="link", href="/detection", text="Open the Detection page")
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


def _label(name: str, frigate_camera: str) -> str:
    """The sensors.cameras key, with Frigate's name in brackets when it differs. The checks are shown behind the login,
    so they may name Frigate's cameras; Copy diagnostics replaces those names."""
    return name if name == frigate_camera else f"{name} ({frigate_camera})"


def _compared(read, frigate: dict | None):
    """The Cameras page's rows, with their issues, for config.yml's entries and sensors.radars and Frigate's cameras
    (None when they aren't needed: the radar issues don't depend on Frigate)."""
    # Imported here: the cameras package imports this module (its router needs env_radar_names).
    from tm_control.modules.cameras.state import compare

    radars = {name: _enabled(radar) for name, radar in _sensors(read.data, "radars").items()}
    cameras = probes.mapping(frigate.get("cameras")) if frigate is not None else None
    return compare(camera_entries(read.data), cameras, radars)


def _codes(row) -> set[str]:
    return {issue.code for issue in row.issues}


def frigate_zones_link(frigate_camera: str) -> Fix:
    """Frigate's masks and zones settings, opened at this camera, as Frigate's own UI links there."""
    return Fix(kind="link", href=f"/frigate/settings?page=masksAndZones&camera={quote(frigate_camera, safe='')}",
               text="Edit its zones in Frigate", external=True)


def cameras_in_config(context: Context) -> list[Check]:
    """Every Frigate camera that is on, with detection not off, has a sensors.cameras entry that points at it (by
    frigate_camera, else by its key), no two entries point at the same camera, and an entry that records is paired with
    a camera that detects. An entry whose Database capture is off is flagged only while Frigate detects on its camera,
    and not at all when its camera is gone or turned off: nothing is recorded from it, so nothing is dropped. With no
    camera having both switches on, the check passes."""

    def check(status, detail, fix=None):
        return [Check(id="config.cameras", title="Cameras in config.yml", status=status, detail=detail, fix=fix)]

    read = probes.config_yml(context)
    if read.data is None:
        return check("unknown", f"{CONFIG_YML_PROBLEM[read.problem]}, so its cameras can't be compared with Frigate's.")
    frigate = probes.frigate_config(context)
    if frigate is None:
        return check("unknown", "Frigate isn't answering, so its cameras can't be compared with config.yml.")
    if probes.frigate_safe_mode(frigate):
        return check("unknown", "Frigate is in safe mode, with no cameras, so its cameras can't be compared with "
                                "config.yml; see the Frigate check under Apps.")
    rows = _compared(read, frigate)
    errors, warnings, gone, recorded = [], [], [], []
    for row in rows:
        codes = _codes(row)
        if row.name is None:
            if "not_paired" in codes:
                errors.append(f"Events from Frigate's camera {row.frigate_camera} are not recorded: no entry under "
                              "sensors.cameras points at it. Add it, or point an entry at it.")
            continue
        label = _label(row.name, row.frigate_camera)
        if "duplicate" in codes:
            errors.append(f"{row.duplicate_of} and {row.name} both point at Frigate's camera {row.frigate_camera}; "
                          f"only {row.duplicate_of}, the first, is used. Remove {row.name} or point it at another "
                          "camera.")
        elif "capture_off" in codes:
            warnings.append(f"Events from {label} are not recorded: Database capture is off for it in config.yml. "
                            "Turn it on if you want them.")
        elif "detect_off" in codes:
            warnings.append(f"Events from {label} are not recorded: Frigate's detection is off for it. Turn Frigate "
                            "detection on if you want them.")
        elif "gone" in codes or "camera_off" in codes:
            gone.append(label)
        elif row.in_frigate == "on" and row.enabled:
            recorded.append(label)
    if gone:
        warnings.append(f"config.yml enables {listed(gone)}, which Frigate doesn't have as an enabled camera. Point "
                        f"{'it' if len(gone) == 1 else 'each'} at the right Frigate camera, remove it, or turn it off.")
    if errors:
        return check("error", " ".join(errors), CAMERAS_LINK)
    if warnings:
        return check("warn", " ".join(warnings), CAMERAS_LINK)
    if not recorded:
        if not any(row.in_frigate == "on" for row in rows):
            return check("ok", "Frigate has no enabled camera to compare.")
        return check("ok", "No camera is recorded, and no events are dropped: none has both Frigate detection and "
                           "Database capture on.")
    return check("ok", f"{listed(recorded)} {'is' if len(recorded) == 1 else 'are'} in Frigate and enabled in "
                       "config.yml.")


def zones(context: Context) -> list[Check]:
    """Each camera enabled in both has the zones the flows expect in Frigate, turned on."""

    def check(status, detail, fix=None):
        return [Check(id="config.zones", title="Zones", status=status, detail=detail, fix=fix)]

    read = probes.config_yml(context)
    if read.data is None:
        return check("unknown", f"{CONFIG_YML_PROBLEM[read.problem]}, so the cameras' zones can't be checked.")
    frigate = probes.frigate_config(context)
    if frigate is None:
        return check("unknown", "Frigate isn't answering, so the cameras' zones can't be checked.")
    if probes.frigate_safe_mode(frigate):
        return check("unknown", "Frigate is in safe mode, with no cameras, so the cameras' zones can't be checked; see "
                                "the Frigate check under Apps.")
    problems, cameras, any_missing, off_count = [], [], False, 0
    for row in _compared(read, frigate):
        # A duplicate's Frigate camera is its first entry's, which is checked there
        if "zones" not in _codes(row):
            continue
        cameras.append(row.frigate_camera)
        missing, off = row.zones_missing or [], row.zones_off or []
        any_missing, off_count = any_missing or bool(missing), off_count + len(off)
        parts = []
        if missing:
            parts.append(f"has no {listed(missing, 'or')} in Frigate")
        if off:
            parts.append(f"has {listed(off)} turned off {'there' if missing else 'in Frigate'}")
        problem = f"Camera {_label(row.name, row.frigate_camera)} {', and '.join(parts)}"
        if any(zone in missing + off for zone in DIRECTION_ZONES):
            problem += "; without zone_near and zone_far, events get a direction only from the radar"
        problems.append(f"{problem}.")
    if problems:
        if any_missing and off_count:
            fix = "Draw the missing zones in Frigate, named exactly as listed, and turn the others back on."
        elif any_missing:
            fix = "Draw the missing zones in Frigate, named exactly as listed."
        else:
            fix = f"Turn {'it' if off_count == 1 else 'them'} back on in Frigate."
        # Zones are drawn in Frigate: one camera's link opens its zones there; the Cameras page marks each of several
        link = frigate_zones_link(cameras[0]) if len(cameras) == 1 else CAMERAS_LINK
        return check("warn", " ".join(problems) + " " + fix, link)
    return check("ok", f"Each enabled camera has {listed(ZONES)}, turned on.")


def zone_names(context: Context) -> list[Check]:
    """No zone of a recorded camera has a name that looks like an address or a person's name: a zone's name is saved
    with every event that enters it. The detail counts such names and never quotes one; the Cameras page shows them."""

    def check(status, detail, fix=None):
        return [Check(id="config.zone_names", title="Zone names", status=status, detail=detail, fix=fix)]

    read = probes.config_yml(context)
    if read.data is None:
        return check("unknown", f"{CONFIG_YML_PROBLEM[read.problem]}, so the zone names can't be checked.")
    frigate = probes.frigate_config(context)
    if frigate is None:
        return check("unknown", "Frigate isn't answering, so the zone names can't be checked.")
    if probes.frigate_safe_mode(frigate):
        return check("unknown", "Frigate is in safe mode, with no cameras, so the zone names can't be checked; see the "
                                "Frigate check under Apps.")
    count, cameras = 0, []
    for row in _compared(read, frigate):
        if "zone_names" not in _codes(row):
            continue
        count += sum(zone.check == "pattern" for zone in row.zone_names or [])
        cameras.append(_label(row.name, row.frigate_camera))
    if not count:
        return check("ok", "No zone name looks like an address or a person's name.")
    one = count == 1
    return check(
        "warn",
        f"{count} zone {'name' if one else 'names'} on {'camera' if len(cameras) == 1 else 'cameras'} "
        f"{listed(cameras)} {'looks' if one else 'look'} like an address or a person's name. A zone's name is saved "
        "with every event that enters it and shared with the data. The Cameras page shows which; rename "
        f"{'it' if one else 'them'} in Frigate.",
        CAMERAS_LINK,
    )


def setup_names(context: Context) -> list[Check]:
    """The running model's title and the active profile's name don't look like an address or a person's name: both are
    saved in the database, and shared with the data. The detail says which and never quotes either; it is read from the
    setup poster's summary, never from the snapshot itself."""

    def check(status, detail, fix=None):
        return [Check(id="config.setup_names", title="Model and profile names", status=status, detail=detail, fix=fix)]

    setup = context.setup
    if not isinstance(setup, dict) or setup.get("gathered") is not True:
        return check("unknown", "The setup hasn't been read yet.")
    flagged = setup.get("flagged") or []
    sentences = []
    if "model_title" in flagged:
        sentences.append("The running model's title looks like an address or a person's name. It is saved in the "
                         "database.")
    if "profile" in flagged:
        sentences.append("Frigate's active profile has a name that looks like an address or a person's name. It is "
                         "saved in the database.")
    if not sentences:
        return check("ok", "The running model's title and the active profile's name don't look like an address or a "
                           "person's name.")
    fix = DETECTION_LINK if "model_title" in flagged else None
    return check("warn", " ".join(sentences), fix)


def radar_names(context: Context) -> list[Check]:
    """Each radar under sensors.radars is named as in node-red-tm.env, and each enabled camera's camera_radar is
    enabled: a camera paired with a radar that is missing or off still records, but gets no speed or direction from
    one."""

    def check(status, detail, fix=None):
        return [Check(id="config.radars", title="Radar names", status=status, detail=detail, fix=fix)]

    read = probes.config_yml(context)
    if read.data is None:
        return check("unknown", f"{CONFIG_YML_PROBLEM[read.problem]}, so its radar names can't be checked.")
    names = env_radar_names(context.manifest)
    configured = _sensors(read.data, "radars")
    errors = []
    unknown = [name for name in configured if name not in names]
    if unknown:
        if len(unknown) == 1:
            errors.append(f"{unknown[0]} under sensors.radars isn't a radar's name, so Node-RED doesn't read it.")
        else:
            errors.append(f"{listed(unknown)} under sensors.radars aren't radars' names, so Node-RED doesn't read "
                          "them.")
        errors.append(f"Name each radar {listed(names, 'or')}, as in node-red-tm.env.")
    unpaired = [
        f"Camera {_label(row.name, row.frigate_camera)} is paired with radar {row.camera_radar}, which isn't "
        "enabled; it gets no speed or direction from a radar."
        for row in _compared(read, None)
        if "radar" in _codes(row)
    ]
    if unpaired:
        unpaired.append("Enable that radar under sensors.radars, or pair the camera with an enabled one.")
    # The link is for the camera pairing; a radar's name is fixed in config.yml
    fix = CAMERAS_LINK if unpaired else None
    if errors:
        return check("error", " ".join(errors + unpaired), fix)
    if unpaired:
        return check("warn", " ".join(unpaired), fix)
    return check("ok", "Each radar in config.yml is named as in node-red-tm.env, and each camera's radar is enabled.")


LOCATION_LINK = Fix(kind="link", href="/location", text="Open the Location page")


def _coordinate_problems(deployment: dict) -> list[str]:
    """Which of deployment.lat and .lon isn't a number in range (numeric strings count), else, when only one is set,
    that they go together. Names the keys, never a value."""
    problems = []
    for key, limit in (("lat", 90), ("lon", 180)):
        try:
            exact(deployment.get(key), key)
        except ValueError:
            problems.append(f"deployment.{key} isn't a number from -{limit} to {limit}")
    if not problems:
        blank = [deployment.get(key) is None or str(deployment.get(key)).strip() == "" for key in ("lat", "lon")]
        if blank[0] != blank[1]:
            problems.append("deployment.lat and deployment.lon must be set together, or both left empty")
    return problems


def _bearing_ok(value) -> bool:
    """Node-RED's init config defaults lower-cases a bearing and looks it up as it is, with no trim: empty is fine,
    ' n' and a run of spaces are not."""
    return value is None or value == "" or (isinstance(value, str) and value.lower() in BEARINGS)


def _sensor_deployments(data: dict) -> list[tuple[str, dict, bool]]:
    """(path, the sensor's own deployment block, whether the sensor is enabled) for every sensor that has one."""
    found = []
    for sensor_type, sensors in probes.mapping(data.get("sensors")).items():
        for name, sensor in probes.mapping(sensors).items():
            sensor = probes.mapping(sensor)
            if isinstance(sensor.get("deployment"), dict):
                found.append((f"sensors.{sensor_type}.{name}.deployment", sensor["deployment"], _enabled(sensor)))
    return found


def location(context: Context) -> list[Check]:
    """The deployment block holds values Node-RED accepts (coordinates, bearings, survey id, stored precision), no
    sensor carries its own coordinates, and the survey id in the file is a place this device has. Never shows a
    value."""

    def check(status, detail, fix=None):
        return [Check(id="config.deployment", title="Location", status=status, detail=detail, fix=fix)]

    read = probes.config_yml(context)
    if read.data is None:
        return check("unknown", f"{CONFIG_YML_PROBLEM[read.problem]}, so its location can't be checked.")
    deployment = probes.mapping(read.data.get("deployment"))
    settings = read_deployment(read)
    problems = _coordinate_problems(deployment)
    bearing_message = "isn't one of " + ", ".join(BEARINGS) + ", or empty"
    if not _bearing_ok(deployment.get("bearing")):
        problems.append(f"deployment.bearing {bearing_message}")
    if settings.survey_id_invalid:
        problems.append("deployment.survey_id isn't a survey id (8 hex characters and -si)")
    meanwhile = ""
    if settings.precision_invalid:
        problems.append("deployment.database_precision isn't none, 1, or 2")
        # Node-RED compares the text exactly (no case folding), so it stores the default instead
        meanwhile = " Until then, Node-RED stores the default, about 1 km."
    ignored = []
    for path, own, enabled in _sensor_deployments(read.data):
        if enabled and not _bearing_ok(own.get("bearing")):
            problems.append(f"{path}.bearing {bearing_message}")
        ignored += [f"{path}.{key}" for key in ("lat", "lon") if key in own]
    if problems:
        fix = "Correct it, or leave it empty." if len(problems) == 1 else "Correct them, or leave them empty."
        return check("error", f"In config.yml, {'; '.join(problems)}. {fix}{meanwhile}")

    warnings = []
    if ignored:
        warnings.append(f"In config.yml, {listed(ignored)} {'is' if len(ignored) == 1 else 'are'} ignored; the "
                        "location is per unit; tmsetup removes it.")
    if context.state is not None:
        places = Places(context.state)
        if places.reconciled_at() is None:
            warnings.append("This device's places haven't been set up yet.")
        elif settings.survey_id is not None and places.get(settings.survey_id) is None:
            warnings.append("deployment.survey_id names a place this device doesn't have.")
    if warnings:
        return check("warn", " ".join(warnings), LOCATION_LINK)
    if settings.survey_id is not None:
        return check("ok", f"Place {settings.survey_id} is in use at precision {settings.precision}.")
    if deployment.get("lat") in (None, "") and deployment.get("lon") in (None, ""):
        return check("ok", "No location is set.")
    return check("ok", "The location's values are valid.")


# config.yml keys that held a secret before the secrets moved to their own files. Nothing reads them now.
FORMER_SECRET_KEYS = (("thingsboard", "access_token"), ("addons", "plate_recognizer", "token"))
# The page where each of them is set now
FORMER_SECRET_PAGES = {("thingsboard", "access_token"): "Sharing", ("addons", "plate_recognizer", "token"): "Device"}
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
        f"config.yml still holds {'.'.join(path)}, which nothing reads. Remove it; the value is set on the "
        f"{FORMER_SECRET_PAGES[path]} page."
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
        fix = Fix(kind="link", text="Set the token", href="/sharing#token") if missing_token else None
        return check("warn", " ".join(warnings), fix)
    return check("ok", "The upload is on, with a token set." if on else "The upload is off.")


# Sharing

SHARING_LINK = Fix(kind="link", href="/sharing", text="Review sharing")
SHARING_REVIEW = (
    "This device's upload was turned on without a choice on the Sharing page. It shares data with the location as the "
    "database stores it. Review the choices."
)
SHARING_NOTICE = "The sharing notice has changed. Read it and save your choices again."
SHARING_NOTICE_UNREAD = "No one has read the sharing notice yet. Read it and save your choices again."
SHARING_IGNORED = "config.yml's sharing block has a value the device ignores. Save the Sharing page to rewrite it."
SHARING_WORDS = {
    "none": "Not sharing.",
    "data": "Sharing data, with the location as the database stores it.",
    "exact": "Sharing data and the exact location.",
}


def _notice_warning(context: Context, upload, consents: Consents) -> str | None:
    """The warning for a unit whose upload is on for the maintainer's server and whose latest granted Share data isn't
    under the current notice; None when it is, or when this check doesn't apply. A pre-consent share, or none at all,
    means no one has read the notice yet; an older version means it changed. A pre-consent share is never under the
    current notice: reviewing a share found on doesn't read it, so only saving the page clears this."""
    if context.notice_version is None or not upload.enabled:
        return None
    if target_key(upload.host, context.manifest.sharing.maintainer_host) != MAINTAINER:
        return None
    share = consents.latest(MAINTAINER).get("share_data")
    if share is None or not share.granted or share.notice_version == PRE_CONSENT:
        return SHARING_NOTICE_UNREAD
    return SHARING_NOTICE if share.notice_version != context.notice_version else None


def sharing(context: Context) -> list[Check]:
    """What the unit shares with the server it uploads to, and whether the Sharing page needs a look: the share began
    before the choices were recorded (the review flag), the maintainer's notice has changed since the choice, or
    config.yml's sharing block holds a value the device ignores. Never shows the server, a notice version, or a
    note. Without the state database the flag and the notice are skipped."""

    def check(status, detail, fix=None):
        return [Check(id="config.sharing", title="Sharing", status=status, detail=detail, fix=fix)]

    read = probes.config_yml(context)
    shared = read_sharing(read)
    if shared is None:
        return check("unknown", f"{CONFIG_YML_PROBLEM[read.problem]}, so its sharing settings can't be checked.")
    upload, block = shared
    warnings = []
    if context.state is not None:
        consents = Consents(context.state)
        if consents.review_needed():
            warnings.append(SHARING_REVIEW)
        elif notice := _notice_warning(context, upload, consents):
            warnings.append(notice)
    if sharing_ignored(read.data):
        warnings.append(SHARING_IGNORED)
    if warnings:
        return check("warn", " ".join(warnings), SHARING_LINK)
    kind = sharing_kind(upload, block)
    detail = SHARING_WORDS[kind]
    if sends_public_map(upload, block):
        detail += " The public map is on."
    return check("ok", detail)


# Frigate+

PLUS_SCHEME = "plus://"
MODEL_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")  # what a Frigate+ model id may be, and a safe file name in model_cache
DETECTOR_TYPE = re.compile(r"Model does not support detector type of ([\w-]+)")
FRIGATE_CONFIG_PROBLEM = {
    "missing": "Frigate's config.yml is missing",
    "unreadable": "Frigate's config.yml can't be read",
    "invalid": "Frigate's config.yml has a YAML error",
}
SET_THE_KEY = Fix(kind="link", text="Set the key", href="/detection#frigate-plus")
CHOOSE_A_MODEL = Fix(kind="link", text="Choose a model", href="/detection#frigate-plus-model")
# How to get out of a Frigate that stops while it fetches a Frigate+ model it can't have
WAYS_OUT = (
    "enter the right key on the Detection page, upload the model's two files there, or choose Use the installer's "
    "model on the Detection page, which works while Frigate is down"
)


def model_path(config_file) -> str | None:
    """model.path in Frigate's config.yml; None when there's no model section or no path in it."""
    path = probes.mapping(probes.mapping(config_file.data).get("model")).get("path")
    return path if isinstance(path, str) else None


def installer_model_file(manifest) -> str | None:
    """The base name of the model file the installer sets on a device with a Coral; None when the manifest has no
    such section (an older install, or one without the key)."""
    path = (manifest.frigate.coral_model or {}).get("path")
    return path.rsplit("/", 1)[-1] or None if isinstance(path, str) else None


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
    and says when Frigate+ gave no token for the key."""

    def check(status, detail, fix=None):
        return [Check(id="config.frigate_plus", title="Frigate+", status=status, detail=detail, fix=fix)]

    read = probes.frigate_config_file(context)
    if read.data is None:
        return check("unknown", f"{FRIGATE_CONFIG_PROBLEM[read.problem]}, so its model and the Frigate+ key can't be "
                                "compared.")
    path = model_path(read)
    key = context.secrets.is_set(FRIGATE_PLUS_API_KEY)
    installer_file = installer_model_file(context.manifest)
    if not (path or "").startswith(PLUS_SCHEME):
        if not key:
            return check("ok", "Frigate+ isn't in use.")
        if not path:
            which = "Frigate's default model"  # no model section, as on a Hailo or CPU install
        elif installer_file and path.endswith(installer_file):
            which = "the installer's model"
        else:
            which = "a local model"
        return check("warn", "A Frigate+ key is set, so snapshots can be submitted from Frigate's Explore page, but "
                             f"Frigate runs {which} rather than a Frigate+ model. Once a model is trained, use it "
                             "by its ID on the Detection page, under Frigate+, pick it under Settings, System, "
                             "Detectors and model in Frigate, or upload it on the Detection page and choose Use.",
                     CHOOSE_A_MODEL)
    model_id = plus_model_id(path)
    if model_id is None:
        return check("error", "model.path in Frigate's config names a Frigate+ model id with characters a model id "
                              "can't have. Check the id in Frigate's configuration editor.")
    cached = model_cached(context.manifest.codedir, model_id)
    if not cached and not key:
        return check("error", f"Frigate's config names the Frigate+ model {model_id}, but no key is set and the "
                              "model's files aren't on the device, so Frigate can't download it. Set the key, or "
                              f"upload {model_id} and {model_id}.json on the Detection page.", SET_THE_KEY)
    running = probes.frigate_config(context)
    if running is None:
        line = traceback_last_line(probes.frigate_journal(context))
        if line is None:
            return check("unknown", f"Frigate isn't answering, so whether it loaded the Frigate+ model {model_id} is "
                                    "unknown.")
        if cached:
            # Frigate reads a cached model from disk without asking Frigate+, so the fetch isn't what stopped it
            return check("error", f"Frigate isn't answering, and the last error in its log is: {quoted(line)}. The "
                                  f"Frigate+ model {model_id} is on the device, so Frigate didn't stop fetching it; "
                                  "see the Frigate check under Apps.")
        if REFUSED_KEY in line:
            # Frigate raises this for any answer but a token from Frigate+: a wrong key, or Frigate+ unreachable
            return check("error", "Frigate isn't answering: Frigate+ gave Frigate no token for the key when Frigate "
                                  f"fetched the model {model_id}, as happens with a wrong key or when Frigate+ can't "
                                  f"be reached. Its log's last error is: {quoted(line)}. To get Frigate running, "
                                  f"{WAYS_OUT}.", SET_THE_KEY)
        # Another exception shows how Frigate stopped, not why, so the detail doesn't claim the download failed
        return check("error", f"Frigate isn't answering, and the last error in its log is: {quoted(line)}. If it "
                              f"stopped while fetching the Frigate+ model {model_id}, check that the device is "
                              f"online, then {WAYS_OUT}.")
    if probes.frigate_safe_mode(running):
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
    "config",
    "Configuration",
    [cameras_in_config, zones, zone_names, setup_names, radar_names, location, thingsboard, sharing, frigate_plus],
)
