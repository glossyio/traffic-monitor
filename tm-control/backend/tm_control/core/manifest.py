"""The install manifest, /etc/traffic-monitor/manifest.json: facts tmsetup records about the install.

tmsetup writes it (templates/tm-control/manifest.json.j2); tm-control only reads it. Unknown keys are ignored, so a
newer tmsetup can add fields.
"""

from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ValidationError, field_validator


class GitInfo(BaseModel):
    commit: str
    branch: str
    modified: bool = False  # the installed tree had changes git could see; older manifests say nothing


class Probes(BaseModel):
    detectors: dict
    radar_paths: list[str]
    hevc_device: str


class Homepage(BaseModel):
    font: str
    colors: dict[str, str]


class FrigateInfo(BaseModel):
    coral_model: dict | None = None  # the model section the installer gives Frigate on a device with a Coral


@dataclass(frozen=True)
class NetworkInfo:
    """The hotspot's fixed values (tmsetup_wifi_device, tmsetup_hotspot_profile, tmsetup_hotspot_address)."""

    wifi_device: str = "wlan0"
    hotspot_profile: str = "tm-hotspot"
    hotspot_address: str = "10.42.0.1"


@dataclass(frozen=True)
class SharingInfo:
    """The maintainer's upload server (tmsetup_sharing_maintainer_host) and whether the public map choice is live."""

    maintainer_host: str = "tb.roadwaybiome.com"
    public_map_live: bool = False


@dataclass(frozen=True)
class MapInfo:
    """Where a browser gets the Location page's map (tmsetup_map_style_url). Empty means off; the device itself
    fetches nothing."""

    style_url: str = ""


@dataclass(frozen=True)
class UpdateInfo:
    """The GitHub repository the install came from (tmsetup_update_repo) and its channel: stable for a release,
    development for a version ending in -dev. The channel stays text, so a word a later version adds still loads."""

    repo: str = "glossyio/traffic-monitor"
    channel: str = "stable"


class Manifest(BaseModel):
    manifest_version: int
    tm_version: str
    git: GitInfo
    installing_user: str
    codedir: str
    codeowner: str
    components: dict[str, str]
    options: dict[str, bool]
    frigate: FrigateInfo = FrigateInfo()
    network: NetworkInfo = NetworkInfo()
    sharing: SharingInfo = SharingInfo()
    map: MapInfo = MapInfo()
    update: UpdateInfo = UpdateInfo()
    revproxy_locations: list[str]
    probes: Probes
    homepage: Homepage

    @field_validator("update", mode="before")
    @classmethod
    def _usable_update(cls, value):
        """A block that isn't an object, or whose repo or channel isn't text, becomes an unknown source (empty repo),
        so the control app still starts and the Software update page says the source is unknown."""
        if isinstance(value, dict) and all(isinstance(value.get(key, ""), str) for key in ("repo", "channel")):
            return value
        return {"repo": "", "channel": "stable"}


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
