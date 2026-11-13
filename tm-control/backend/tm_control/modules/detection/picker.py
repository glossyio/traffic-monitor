"""Which detector Frigate runs and which model it runs, from Frigate's own answer when it gives one and from
config.yml when it doesn't; and the write half, which makes Frigate run another model.

A model is used by replacing config.yml's top-level `model:` section. Frigate's config API writes it when Frigate
answers, after it has validated the whole config; when Frigate doesn't answer, the file is edited on disk. Either way
the rest of the file, its comments included, stays as it was, and the caller restarts frigate.service.
"""

import copy
import io
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.error import CommentMark, YAMLError
from ruamel.yaml.tokens import CommentToken

from tm_control.adapters import frigate
from tm_control.adapters.yamlfile import ConcurrentEditError, ConfigRead, RoundTripFile, _round_trip_yaml
from tm_control.modules.apps import probes
from tm_control.modules.apps.checks import redact
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


# The write half

FRIGATE_HEADER = "Your configuration is invalid."  # the first of the two lines before Frigate's validation errors
REFUSAL_MAX = 500  # characters of Frigate's refusal that are shown
INSTALLER_KEYS = ("model_type", "width", "height", "path", "labelmap_path")  # the installer template's order


class UseError(Exception):
    """Why a model can't be used, as the API answers it."""

    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def model_section(model: Model) -> dict:
    """The `model:` section that makes Frigate run the model: a Frigate+ pair by its plus:// path, which Frigate
    resolves with the sidecar itself; a local pair with what its sidecar says, in the keys Frigate's ModelConfig
    admits (it forbids any other)."""
    if model.kind == "frigate_plus":
        return {"path": f"plus://{model.name}"}
    sidecar = model.sidecar
    section = {
        "path": f"{CACHE_PREFIX}{model.name}",
        "width": sidecar.width,
        "height": sidecar.height,
        "input_tensor": sidecar.input_shape,
        "input_pixel_format": sidecar.pixel_format,
        "model_type": sidecar.type,
    }
    if sidecar.input_dtype is not None:
        section["input_dtype"] = sidecar.input_dtype
    section["labelmap"] = dict(enumerate(sidecar.labels))
    return section


def default_section(detector: str, installer: InstallerDefault | None) -> dict | None:
    """The installer's section, in its template's key order, for a Coral; None (no `model:` at all, so Frigate's own
    default) for any other detector, or when the installer gave none."""
    if detector != "edgetpu" or installer is None:
        return None
    section = installer.section
    ordered = {key: section[key] for key in INSTALLER_KEYS if key in section}
    return ordered | {key: value for key, value in section.items() if key not in ordered}


def _commented(value):
    """A section as ruamel's round-trip types, which can carry the comment that follows it."""
    if isinstance(value, dict):
        return CommentedMap((key, _commented(item)) for key, item in value.items())
    if isinstance(value, list):
        return CommentedSeq(_commented(item) for item in value)
    return value


def _end_of(holder, key) -> tuple:
    """Where ruamel keeps what follows holder[key]'s block (the blank lines and comments before the next key): on the
    innermost last entry of its last mapping or sequence. Returns that container, its key or index, and the slot of
    its comment entry that holds the token."""
    while True:
        value = holder[key]
        if isinstance(value, CommentedMap) and value:
            holder, key = value, next(reversed(value))
        elif isinstance(value, CommentedSeq) and value:
            holder, key = value, len(value) - 1
        else:
            return holder, key, 0 if isinstance(holder, CommentedSeq) else 2


def _token_at(end) -> CommentToken | None:
    holder, key, slot = end
    entry = holder.ca.items.get(key)
    return entry[slot] if entry and len(entry) > slot else None


def _split(token: CommentToken | None) -> tuple[str, str]:
    """A trailing token as the end of its own line (with the comment on it, if any) and what follows that line."""
    line, newline, after = (token.value if token is not None else "").partition("\n")
    return line + newline, after


def _put(end, line: str, after: str) -> None:
    """Make the entry at `end` end its line with `line` (a comment, or nothing) and then `after`. An existing token is
    copied, so an end-of-line comment keeps its column."""
    holder, key, slot = end
    old = _token_at(end)
    value = (line or "\n") + after
    entry = holder.ca.items.setdefault(key, [None, None, None, None])
    entry.extend([None] * (slot + 1 - len(entry)))
    if value == "\n":
        entry[slot] = None
    elif old is not None:
        entry[slot] = copy.copy(old)
        entry[slot].value = value
    else:
        entry[slot] = CommentToken(value, CommentMark(0), None)


def replace_model_section(doc, section: dict | None) -> None:
    """Set the top-level `model:` of a round-trip loaded config to section, in place, keeping the blank lines and
    comments that came after the old section before the next key:

    - replacing the one there;
    - inserting one after `detectors` (at the end without one), with what followed `detectors` moved after it and a
      blank line before it;
    - or deleting it when section is None, with what followed it moved to the end of the key before it.

    Nothing else changes."""
    keys = list(doc)
    if section is None:
        if "model" not in doc:
            return
        _, after = _split(_token_at(_end_of(doc, "model")))
        index = keys.index("model")
        del doc["model"]
        if index > 0:
            previous = _end_of(doc, keys[index - 1])
            line, before = _split(_token_at(previous))
            _put(previous, line, after if after and not before.strip() else before + after)
        return
    new = _commented(section)
    if "model" in doc:
        _, after = _split(_token_at(_end_of(doc, "model")))
        doc["model"] = new
        _put(_end_of(doc, "model"), "", after)
        return
    position = keys.index("detectors") + 1 if "detectors" in keys else len(keys)
    previous = _end_of(doc, keys[position - 1]) if position > 0 else None
    line, after = _split(_token_at(previous)) if previous is not None else ("", "")
    doc.insert(position, "model", new)
    if position < len(keys):  # a key follows: what came before it now follows model, with a blank line at least
        if previous is not None and after:
            _put(previous, line, "\n")
        _put(_end_of(doc, "model"), "", after or "\n")


def refusal_lines(message: str) -> str:
    """What Frigate said is wrong, fit to show: its validation errors without the two header lines, or a traceback's
    last line for its other refusals; each line redacted, joined with "; ", and cut to REFUSAL_MAX characters."""
    lines = [line.strip() for line in str(message).splitlines()]
    if lines and lines[0].startswith(FRIGATE_HEADER):
        lines = lines[2:]
    else:  # a traceback: its last line names the exception
        lines = [line for line in lines if line][-1:]
    text = "; ".join(redact(line) for line in lines if line)  # redacted line by line, so a cut can't split a key
    return text if len(text) <= REFUSAL_MAX else f"{text[:REFUSAL_MAX - 1]}…"


def _not_a_mapping() -> UseError:
    return UseError(409, "config_invalid", "Frigate's config.yml isn't a YAML mapping, so its model can't be set.")


def _set_model(doc, section: dict | None) -> None:
    """replace_model_section on a parsed config, unless a detector sets its own model: Frigate runs that one over the
    top-level section, so the edit would change nothing."""
    if not isinstance(doc, CommentedMap):
        raise _not_a_mapping()
    for name, detector in probes.mapping(doc.get("detectors")).items():
        if probes.mapping(probes.mapping(detector).get("model")).get("path"):
            raise UseError(409, "detector_model", f"Frigate's config sets a model inside detectors.{name}; remove it "
                                                  "in Frigate's config editor first.")
    replace_model_section(doc, section)


def edited(text: str, section: dict | None) -> str:
    """config.yml's text with its top-level `model:` set to section (None removes it), the rest as it was. Raises
    UseError."""
    yaml = _round_trip_yaml(2)
    try:
        doc = yaml.load(text)
    except YAMLError:
        raise _not_a_mapping() from None
    _set_model(doc, section)
    out = io.StringIO()
    yaml.dump(doc, out)
    return out.getvalue()


def _save_through_frigate(text: str, section: dict | None) -> None:
    new_text = edited(text, section)
    status, message = frigate.save_config(new_text)
    if status == 200:
        return
    if status == 400:
        lines = refusal_lines(message) if message else ""
        raise UseError(422, "frigate_refused", f"Frigate refused the config: {lines}" if lines else
                       "Frigate refused the config.")
    if status is None:
        # Frigate validates, writes the file, then answers: a save that took too long may be on disk already. The file
        # then holds exactly the text that was sent, which is what counts as saved; otherwise nothing changed.
        if frigate.config_raw() == new_text:
            return
        raise UseError(502, "frigate_error",
                       "Frigate didn't answer the save; its config may or may not have changed. Try again.")
    raise UseError(502, "frigate_error", f"Frigate answered {status} to the save.")


def _edit_file(path: Path, section: dict | None) -> None:
    try:
        file = RoundTripFile(path)
        _set_model(file.data, section)
        file.save()
    except YAMLError:
        raise _not_a_mapping() from None
    except (ConcurrentEditError, OSError) as error:
        name = type(error).__name__
        raise UseError(500, "config_write", f"Frigate's config.yml couldn't be written: {name}") from None


def apply(section: dict | None, codedir) -> Literal["frigate", "file"]:
    """Set Frigate's `model:` to section (None removes it): through Frigate's config API when Frigate answers, which
    validates the whole config before it writes the file; otherwise in <codedir>/frigate/config/config.yml, with a
    backup. Never restarts Frigate. Raises UseError."""
    text = frigate.config_raw()
    if text is not None:
        _save_through_frigate(text, section)
        return "frigate"
    _edit_file(Path(codedir) / "frigate" / "config" / "config.yml", section)
    return "file"


def check_usable(model: Model, detector: str | None) -> None:
    """Raise UseError unless the model has its sidecar and file and is built for the device's detector."""
    sidecar = model.sidecar
    if sidecar is None:
        raise UseError(422, "incomplete", "This model is missing its sidecar.")
    if detector is None:
        raise UseError(409, "detector_unknown",
                       "Frigate's detector type can't be determined, so a model can't be checked against it.")
    if detector not in sidecar.detectors:
        built_for = ", ".join(sidecar.detectors)
        raise UseError(422, "wrong_detector",
                       f"This model is built for {built_for}; this device detects with {detector}.")
    if not model.complete:
        raise UseError(422, "incomplete", "This model's file is missing or can't be read.")
