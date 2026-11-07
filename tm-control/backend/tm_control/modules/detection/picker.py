"""Which detector Frigate runs and which model it runs, from Frigate's own answer when it gives one and from
config.yml when it doesn't."""

from dataclasses import dataclass
from typing import Literal

from tm_control.adapters.yamlfile import ConfigRead
from tm_control.modules.apps import probes
from tm_control.modules.apps.contracts import plus_model_id
from tm_control.modules.detection.inventory import CONFIG_PREFIX, InstallerDefault, Model

CACHE_PREFIX = f"{CONFIG_PREFIX}model_cache/"  # where Frigate's container sees model_cache


@dataclass(frozen=True)
class Running:
    name: str | None  # the file's name when the model is one in model_cache
    kind: Literal["frigate_plus", "local", "installer_default", "frigate_default"] | None  # None when unknown
    path: str | None  # the model path as Frigate's container has it; None when none is set
    source: Literal["frigate", "config_file"] | None  # who said so; None when neither could


def first_detector(config: dict | None) -> dict:
    """The first detector's section of a config; empty when there is none."""
    detectors = probes.mapping(probes.mapping(config).get("detectors"))
    return probes.mapping(next(iter(detectors.values()), None))


def detector_type(frigate_config: dict | None, config_file: ConfigRead) -> str | None:
    """The first detector's type: Frigate's answer if it names one, else config.yml's, else "cpu" for a readable
    config.yml with no detector (Frigate then runs its own CPU detector); None when neither can be read."""
    kind = first_detector(frigate_config).get("type")
    if isinstance(kind, str) and kind:
        return kind
    if config_file.data is None:
        return None
    kind = first_detector(config_file.data).get("type")
    return kind if isinstance(kind, str) and kind else "cpu"


def _configured_path(config: dict) -> str | None:
    """model.path: the first detector's, else the top-level one; a plus://<id> path read as the file it becomes."""
    for section in (first_detector(config), config):
        path = probes.mapping(section.get("model")).get("path")
        if isinstance(path, str) and path:
            model_id = plus_model_id(path)
            return f"{CACHE_PREFIX}{model_id}" if model_id else path
    return None


def running_model(
    frigate_config: dict | None, config_file: ConfigRead, installer: InstallerDefault | None, models: list[Model]
) -> Running:
    """The model Frigate runs, from its answer, else from config.yml. A path directly under model_cache names a model:
    the installer's file is the installer's default, one in the inventory has that entry's kind, any other is local.
    No path, or one elsewhere, is Frigate's own default."""
    if frigate_config is not None:
        config, source = frigate_config, "frigate"
    elif config_file.data is not None:
        config, source = config_file.data, "config_file"
    else:
        return Running(None, None, None, None)
    path = _configured_path(config)
    rest = path[len(CACHE_PREFIX):] if path and path.startswith(CACHE_PREFIX) else ""
    if not rest or "/" in rest:
        return Running(None, "frigate_default", path, source)
    if installer is not None and rest == installer.file:
        return Running(rest, "installer_default", path, source)
    kinds = {model.name: model.kind for model in models}
    return Running(rest, kinds.get(rest, "local"), path, source)
