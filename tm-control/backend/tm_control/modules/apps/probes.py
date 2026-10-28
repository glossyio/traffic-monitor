"""The apps' state, read at most once per status report through the Context's probe memo, for every check group that
needs it: Frigate's version, config, and stats, Node-RED's status, config.yml, and go2rtc's streams.

A Frigate that doesn't answer its version isn't asked for its config or stats, so a hung Frigate costs the report one
timeout, not three.
"""

from tm_control.adapters import frigate, go2rtc, nodered
from tm_control.core.checks import Context

FRIGATE_VERSION = "frigate.version"
FRIGATE_CONFIG = "frigate.config"
FRIGATE_STATS = "frigate.stats"
NODERED_STATUS = "nodered.status"
CONFIG_YML = "nodered.config_yml"
GO2RTC_STREAMS = "go2rtc.streams"


def frigate_version(context: Context) -> str | None:
    return context.probe(FRIGATE_VERSION, lambda: frigate.version())


def frigate_config(context: Context) -> dict | None:
    return context.probe(FRIGATE_CONFIG, lambda: frigate.config() if frigate_version(context) else None)


def frigate_stats(context: Context) -> dict | None:
    return context.probe(FRIGATE_STATS, lambda: frigate.stats() if frigate_version(context) else None)


def nodered_status(context: Context) -> tuple[int | None, dict | None]:
    """(HTTP status, body) of Node-RED's /tm-internal/status; (None, None) when it doesn't answer."""
    return context.probe(NODERED_STATUS, lambda: nodered.status(context.secrets.node_red_internal_token))


def nodered_report(context: Context) -> dict | None:
    """Node-RED's status when it answered with it (a 200); None when it didn't answer, refused the token, or failed."""
    code, body = nodered_status(context)
    return body if code == 200 else None


def config_yml(context: Context) -> nodered.ConfigRead:
    """config.yml as the host has it; .data is None when it's missing, unreadable, or not valid YAML."""
    return context.probe(CONFIG_YML, lambda: nodered.config(context.manifest.codedir))


def go2rtc_streams(context: Context) -> dict | None:
    return context.probe(GO2RTC_STREAMS, lambda: go2rtc.streams())


def mapping(value) -> dict:
    """value when it's a mapping, else an empty one: for reading sections of configs that a person edits."""
    return value if isinstance(value, dict) else {}


def frigate_cameras(config: dict) -> dict[str, dict]:
    """The cameras in Frigate's config that are enabled there, by name."""
    cameras = {str(name): mapping(camera) for name, camera in mapping(config.get("cameras")).items()}
    return {name: camera for name, camera in cameras.items() if camera.get("enabled", True) is not False}
