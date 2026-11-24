"""What a setup snapshot holds: the facts of the unit (its model, its versions) and of each camera (its detect size,
its zones, its masks), gathered from the same readers the Detection and Cameras pages use.

Only the facts listed in DEVICE_FACTS and CAMERA_FACTS leave this module, and each camera is keyed by its sensors.cameras
key in config.yml. Frigate's name for a camera, an input path, a zone's or mask's friendly_name, its colour, and a
mask's id are never read into the snapshot. Node-RED checks only the type of a zone's or mask's contents, so they are
whitelisted here: built from the listed keys and nothing else.

Values Node-RED's validator would refuse are never sent: a text fact that isn't a string, is empty, or is longer than
TEXT_MAX is None; a whole-number fact is an int or None, never a float. Nothing here logs a camera, a zone, a title,
a profile, or a value.
"""

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from tm_control import fake
from tm_control.adapters import frigate
from tm_control.adapters.yamlfile import ConfigRead
from tm_control.modules.apps import probes
from tm_control.modules.apps.contracts import MODEL_ID
from tm_control.modules.apps.name_check import check_name, check_title
from tm_control.modules.cameras import zones
from tm_control.modules.cameras.state import compare
from tm_control.modules.detection.inventory import InstallerDefault, Model, installer_default, inventory, model_cache_dir
from tm_control.modules.detection.labels import recognised
from tm_control.modules.detection.picker import detector_type, first_detector, running_model
from tm_control.modules.location.config import ConfigError, NodeRedConfig

TEXT_MAX = 128  # a longer text fact is recorded as empty, never cut
DEVICE_FACTS = (
    "tm_version", "tm_commit", "frigate_version", "unit_system", "detector", "model_id", "model_file", "model_sha256",
    "model_kind", "model_title", "model_trained_at", "model_base", "model_type", "model_width", "model_height",
    "labels_available",
)
CAMERA_FACTS = (
    "detect_width", "detect_height", "detect_fps", "stationary_threshold", "stationary_interval", "lens_hfov",
    "labels_tracked", "thresholds", "zones", "masks", "profile",
)
UNIT_SYSTEMS = ("metric", "imperial")


@dataclass(frozen=True)
class Snapshot:
    body: dict  # what is posted: {"complete": False}, or the device's and each camera's facts
    flagged: tuple[str, ...]  # of "model_title" and "profile": a value the name check found looks like a place or person


INCOMPLETE = Snapshot({"complete": False}, ())


# Single values

def _text(value) -> str | None:
    return value if isinstance(value, str) and 0 < len(value) <= TEXT_MAX else None


def _whole(value) -> int | None:
    """A whole number as an int: 10.0 is 10, so a number Frigate writes both ways is one fact; no bool, no fraction."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and math.isfinite(value) and value.is_integer():
        return int(value)
    return None


def _number(value) -> int | float | None:
    """A finite number, whole ones as ints."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return _whole(value) if isinstance(value, float) and value.is_integer() else value


def _names(value) -> list[str]:
    """The strings of a list, sorted and without repeats: a list whose order means nothing."""
    return sorted({item for item in value if isinstance(item, str)}) if isinstance(value, list) else []


# The cameras

def _filters(filters, labels: Iterable[str] | None) -> dict[str, dict]:
    """Each label's FILTER_KEYS numbers (the labels in `labels`, or all), a label with no number left out."""
    found = {}
    for label, numbers in zones.object_filters(filters).items():
        numbers = {key: _number(value) for key, value in numbers.items()}
        if numbers and (labels is None or label in labels):
            found[label] = numbers
    return found


def _zone(zone: zones.ZoneFacts) -> dict:
    return {
        "key": zone.key,
        "enabled": zone.enabled,
        "corners": [[corner.x, corner.y] for corner in zone.corners],
        "distances": list(zone.distances),
        "inertia": zone.inertia,
        "loitering_time": zone.loitering_time,
        "speed_threshold": zone.speed_threshold,
        "objects": sorted(set(zone.objects)),
        "filters": _filters(zone.filters, None),
    }


def _masks(container) -> list[dict]:
    """The masks of one `mask` section, each as {"enabled", "corners"}, sorted by their corners. A section is a mapping
    of mask id to mask (the id is dropped); an older Frigate's one mask, as a string or list, counts as one. A mask
    that is null or has fewer than three corners is left out."""
    if isinstance(container, Mapping):
        entries = list(container.values())
    elif isinstance(container, (str, list)):
        entries = [container]
    else:
        entries = []
    found = []
    for entry in entries:
        if isinstance(entry, Mapping):
            enabled, coordinates = entry.get("enabled") is not False, entry.get("coordinates")
        else:
            enabled, coordinates = True, entry
        corners = [[corner.x, corner.y] for corner in zones.corners(coordinates)]
        if corners:
            found.append({"enabled": enabled, "corners": corners})
    return sorted(found, key=lambda mask: (mask["corners"], mask["enabled"]))


def _all_masks(camera: Mapping) -> dict:
    objects = probes.mapping(camera.get("objects"))
    motion = _masks(probes.mapping(camera.get("motion")).get("mask"))
    general = _masks(objects.get("mask"))
    per_label = {}
    for label, section in probes.mapping(objects.get("filters")).items():
        masks = _masks(probes.mapping(section).get("mask"))
        if isinstance(label, str) and masks:
            per_label[label] = masks
    if not (motion or general or per_label):
        return {}
    return {"motion": motion, "objects": general, "object_filters": per_label}


def camera_facts(camera: Mapping, active_profile: str | None) -> dict:
    """One camera's facts from its section of Frigate's /api/config, in CAMERA_FACTS' order. lens_hfov is always None
    here: a later change fills it. profile is the active profile's key when this camera defines that profile."""
    camera = probes.mapping(camera)
    detect = probes.mapping(camera.get("detect"))
    stationary = probes.mapping(detect.get("stationary"))
    size = zones.detect_size(camera)
    tracked = _names(probes.mapping(camera.get("objects")).get("track"))
    profile = active_profile if active_profile is not None and active_profile in probes.mapping(
        camera.get("profiles")) else None
    return {
        "detect_width": size[0] if size else None,
        "detect_height": size[1] if size else None,
        "detect_fps": _whole(detect.get("fps")),
        "stationary_threshold": _whole(stationary.get("threshold")),
        "stationary_interval": _whole(stationary.get("interval")),
        "lens_hfov": None,
        "labels_tracked": tracked,
        "thresholds": _filters(probes.mapping(camera.get("objects")).get("filters"), set(tracked)),
        "zones": sorted((_zone(zone) for zone in zones.zone_facts(camera)), key=lambda zone: zone["key"]),
        "masks": _all_masks(camera),
        "profile": _text(profile),
    }


# The device

def _model_entry(running, models: list[Model]) -> Model | None:
    """The inventory's entry for the running model: the one it names; for Frigate's own default, which Frigate runs
    with no path set, the inventory's frigate_default entry when it has one."""
    if running.name is not None:
        return next((model for model in models if model.name == running.name), None)
    if running.kind == "frigate_default" and running.path is None:
        return next((model for model in models if model.kind == "frigate_default"), None)
    return None


def _model_section(frigate_config: Mapping | None) -> dict:
    """The first detector's model section, else the top-level one: what Frigate says the running model is."""
    for section in (first_detector(dict(frigate_config or {})), probes.mapping(frigate_config)):
        found = probes.mapping(section.get("model"))
        if found:
            return found
    return {}


def device_facts(
    manifest, frigate_version: str, frigate_config: Mapping, config_file: ConfigRead, models: list[Model],
    installer: InstallerDefault | None,
) -> dict:
    """The unit's facts, in DEVICE_FACTS' order: the versions, the detector, and the running model, from the same calls
    the Detection page makes. The model's type and size are Frigate's own answer, so a default model has them too."""
    frigate_config = probes.mapping(frigate_config)
    running = running_model(frigate_config, config_file, installer, models)
    entry = _model_entry(running, models)
    sidecar = entry.sidecar if entry is not None else None
    file = running.name if running.name is not None else entry.name if entry is not None else None
    stored = next((item for item in entry.files if item.name == entry.name), None) if entry is not None else None
    labels, _ = recognised(frigate_config, running, models, installer)
    section = _model_section(frigate_config)
    unit = probes.mapping(frigate_config.get("ui")).get("unit_system")
    model_id = sidecar.id if sidecar is not None and sidecar.id and MODEL_ID.fullmatch(sidecar.id) else None
    return {
        "tm_version": _text(manifest.tm_version),
        "tm_commit": _text(manifest.git.commit),
        "frigate_version": _text(frigate_version),
        "unit_system": unit if unit in UNIT_SYSTEMS else None,
        "detector": _text(detector_type(frigate_config, config_file)),
        "model_id": _text(model_id),
        "model_file": _text(file),
        "model_sha256": _text(stored.sha256) if stored is not None else None,
        "model_kind": _text(running.kind),
        "model_title": _text(sidecar.name) if sidecar is not None else None,
        "model_trained_at": _text(sidecar.trained_at) if sidecar is not None else None,
        "model_base": _text(sidecar.base_model) if sidecar is not None else None,
        "model_type": _text(section.get("model_type")),
        "model_width": _whole(section.get("width")),
        "model_height": _whole(section.get("height")),
        "labels_available": _names(labels),
    }


def flagged(device: dict, profiles: Iterable[str]) -> tuple[str, ...]:
    """Which recorded values look like an address or a person's name: "model_title" by the title rule, "profile" by the
    zone-name rule (at the pattern level only) for any of the profile keys a row holds."""
    found = []
    title = device.get("model_title")
    if isinstance(title, str) and check_title(title) == "pattern":
        found.append("model_title")
    if any(check_name(profile) == "pattern" for profile in profiles):
        found.append("profile")
    return tuple(found)


# Gathering

def _frigate_answers(app_state) -> tuple[str, dict, str | None, ConfigRead] | None:
    """Frigate's version, running config, active profile, and config.yml; None at the first thing that can't be read
    (Frigate not answering, safe mode, or no word on the active profile), without asking for the rest."""
    settings, manifest = app_state.settings, app_state.manifest
    if settings.fake:
        config, config_file = fake.frigate_answer(settings)
        return fake.FAKE_FRIGATE_VERSION, config, None, config_file
    version = frigate.version()
    if version is None:
        return None
    config = frigate.config()
    if config is None or probes.frigate_safe_mode(config):
        return None
    answered, profile = frigate.active_profile()
    if not answered:
        return None
    return version, config, profile, frigate.config_file(Path(manifest.codedir))


def _gather(app_state) -> Snapshot:
    found = _frigate_answers(app_state)
    if found is None:
        return INCOMPLETE
    version, config, profile, config_file = found
    try:
        entries = NodeRedConfig(app_state.config_path).cameras()
    except ConfigError:
        return INCOMPLETE
    settings, manifest = app_state.settings, app_state.manifest
    codedir = settings.state_dir.parent if settings.fake else Path(manifest.codedir)
    installer = installer_default(manifest, codedir)
    detector = detector_type(config, config_file)
    models = inventory(model_cache_dir(settings, manifest), installer, detector)
    device = device_facts(manifest, version, config, config_file, models, installer)
    frigate_cameras = probes.mapping(config.get("cameras"))
    cameras = {}
    for row in compare(entries, frigate_cameras):
        if row.name is not None and row.duplicate_of is None and row.in_frigate in ("on", "off"):
            cameras[row.name] = camera_facts(frigate_cameras.get(row.frigate_camera), profile)
    profiles = {camera["profile"] for camera in cameras.values() if camera["profile"] is not None}
    return Snapshot({"complete": True, "device": device, "cameras": cameras}, flagged(device, profiles))


def gather(app_state) -> Snapshot:
    """The snapshot of the unit now, or INCOMPLETE when it can't be made whole: Frigate doesn't answer, runs in safe
    mode, or doesn't say which profile is active, or config.yml can't be read. Never raises, so the thread that calls
    it keeps going; nothing about what went wrong is kept, since it could name a camera."""
    try:
        return _gather(app_state)
    except Exception:  # noqa: BLE001: a gather that fails for any reason is an incomplete one
        return INCOMPLETE
