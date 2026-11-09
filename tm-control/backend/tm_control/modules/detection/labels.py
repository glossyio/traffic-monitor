"""The two label lists the Detection page shows: what the running model recognises, and what the device tracks."""

import os
import stat
from pathlib import Path

from tm_control.modules.apps import probes
from tm_control.modules.detection.inventory import LABEL_KEY, InstallerDefault, Model
from tm_control.modules.detection.picker import Running, first_detector

LABELS_FILE_MAX = 1024 * 1024
UNKNOWN = "unknown"  # what Frigate pads its merged label map with (74 of a stock Coral unit's 91 entries); not an object


def _objects(labels) -> list[str]:
    return [label for label in labels if label != UNKNOWN]


def _labelmap(config: dict | None) -> list[str] | None:
    """The objects in the first detector's model.labelmap (the top-level one if the detector has none), in index order;
    None for a missing, empty, or malformed one, or one with no objects."""
    for section in (first_detector(config), probes.mapping(config)):
        labelmap = probes.mapping(section.get("model")).get("labelmap")
        if not isinstance(labelmap, dict) or not labelmap:
            continue
        if all(LABEL_KEY.fullmatch(str(key)) and isinstance(label, str) for key, label in labelmap.items()):
            labels = _objects(label for _, label in sorted(labelmap.items(), key=lambda item: int(item[0])))
            if labels:
                return labels
    return None


def _labels_file(path: Path) -> list[str] | None:
    """A labels file's lines, one label each with blank lines dropped; None when it can't be read as a regular file
    (a link is refused) or is over the cap."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_NOCTTY | os.O_CLOEXEC)
    except OSError:
        return None
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return None
        data = os.read(fd, LABELS_FILE_MAX + 1)
    except OSError:
        return None
    finally:
        os.close(fd)
    if len(data) > LABELS_FILE_MAX:
        return None
    try:
        lines = [line.strip() for line in data.decode("utf-8").splitlines()]
    except UnicodeDecodeError:
        return None
    return _objects(line for line in lines if line) or None


def _installer_labels(installer: InstallerDefault | None) -> list[str] | None:
    """The installer's labels file, as its model is known to recognise."""
    return _labels_file(installer.labels_file) if installer is not None and installer.labels_file is not None else None


def of_model(model: Model, installer: InstallerDefault | None) -> list[str] | None:
    """What one model recognises, whether or not it runs: its sidecar's labels in label-map index order, the labels
    file for the installer's model, and None for a file that says nothing about it."""
    if model.sidecar is not None:
        return _objects(model.sidecar.labels)
    return _installer_labels(installer) if model.kind == "installer_default" else None


def recognised(
    frigate_config: dict | None, running: Running, models: list[Model], installer: InstallerDefault | None
) -> tuple[list[str] | None, str | None]:
    """What the running model recognises and where that came from: Frigate's own label map, else the running model's
    sidecar, else, for the installer's default, its labels file, which answers even when its model file is gone."""
    labels = _labelmap(frigate_config)
    if labels is not None:
        return labels, "frigate"
    model = next((model for model in models if model.name == running.name), None)
    if model is not None and model.sidecar is not None:
        return of_model(model, installer), "sidecar"
    if running.kind == "installer_default":
        labels = _installer_labels(installer)
        if labels is not None:
            return labels, "labels_file"
    return None, None


def tracked(frigate_config: dict | None) -> list[str]:
    """The object types Frigate tracks: the top-level objects.track, then each camera's entries not yet listed."""
    config = probes.mapping(frigate_config)
    seen: list[str] = []
    lists = [probes.mapping(config.get("objects")).get("track")]
    cameras = config.get("cameras")
    if isinstance(cameras, dict):
        lists += [probes.mapping(probes.mapping(camera).get("objects")).get("track") for camera in cameras.values()]
    for entries in lists:
        for entry in entries if isinstance(entries, list) else []:
            if isinstance(entry, str) and entry not in seen:
                seen.append(entry)
    return seen
