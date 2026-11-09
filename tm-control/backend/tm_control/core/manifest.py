"""The install manifest, /etc/traffic-monitor/manifest.json: facts tmsetup records about the install.

tmsetup writes it (templates/tm-control/manifest.json.j2); tm-control only reads it. Unknown keys are ignored, so a
newer tmsetup can add fields.
"""

from pathlib import Path

from pydantic import BaseModel, ValidationError


class GitInfo(BaseModel):
    commit: str
    branch: str


class Probes(BaseModel):
    detectors: dict
    radar_paths: list[str]
    hevc_device: str


class Homepage(BaseModel):
    font: str
    colors: dict[str, str]


class Manifest(BaseModel):
    manifest_version: int
    tm_version: str
    git: GitInfo
    installing_user: str
    codedir: str
    codeowner: str
    components: dict[str, str]
    options: dict[str, bool]
    revproxy_locations: list[str]
    probes: Probes
    homepage: Homepage


class ManifestError(RuntimeError):
    """The manifest is missing or invalid. The message has the path and the reason, never the file's content."""


def _reason(error):
    """Where and how validation failed, without the input values pydantic would otherwise print."""
    return "; ".join(
        f"{'.'.join(str(part) for part in item['loc']) or 'document'}: {item['msg']}"
        for item in error.errors(include_url=False, include_input=False, include_context=False)
    )


def load_manifest(path) -> Manifest:
    path = Path(path)
    try:
        text = path.read_bytes()
    except OSError as error:
        raise ManifestError(f"cannot read the manifest {path}: {error.strerror or type(error).__name__}") from None
    try:
        return Manifest.model_validate_json(text)
    except ValidationError as error:
        # from None: the chained ValidationError would print the values in a traceback
        raise ManifestError(f"the manifest {path} is not valid: {_reason(error)}") from None
