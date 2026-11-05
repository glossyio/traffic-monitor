"""The apps' state, read at most once per status report through the Context's probe memo, for every check group that
needs it: Frigate's version, config, stats, config.yml, and journal, Node-RED's status, config.yml, and go2rtc's
streams.

A Frigate that doesn't answer its version isn't asked for its config or stats, so a hung Frigate costs the report one
timeout, not three.
"""

from tm_control.adapters import frigate, go2rtc, nodered, systemd
from tm_control.adapters.yamlfile import ConfigRead
from tm_control.core.checks import Context
from tm_control.modules.services.units import RUNNING, active_since, restarts, unit_states

FRIGATE_VERSION = "frigate.version"
FRIGATE_CONFIG = "frigate.config"
FRIGATE_STATS = "frigate.stats"
FRIGATE_CONFIG_FILE = "frigate.config_file"
FRIGATE_JOURNAL = "frigate.journal"
FRIGATE_UNIT = "frigate.service"
JOURNAL_LINES = 400  # enough for Frigate's config validation block, and for the end of a traceback
NODERED_STATUS = "nodered.status"
CONFIG_YML = "nodered.config_yml"
GO2RTC_STREAMS = "go2rtc.streams"


def frigate_version(context: Context) -> str | None:
    return context.probe(FRIGATE_VERSION, lambda: frigate.version())


def frigate_config(context: Context) -> dict | None:
    return context.probe(FRIGATE_CONFIG, lambda: frigate.config() if frigate_version(context) else None)


def frigate_stats(context: Context) -> dict | None:
    return context.probe(FRIGATE_STATS, lambda: frigate.stats() if frigate_version(context) else None)


def frigate_config_file(context: Context) -> ConfigRead:
    """Frigate's config.yml as the host has it; .data is None when it's missing, unreadable, or not valid YAML."""
    return context.probe(FRIGATE_CONFIG_FILE, lambda: frigate.config_file(context.manifest.codedir))


def frigate_journal(context: Context) -> list[str]:
    """Frigate's journal: while its unit runs, the messages of the current run from a minute before it started (the
    whole last hour when systemd gives no start time); otherwise the journal's last lines, where a run that stopped
    left its traceback. [] when the journal can't be read.

    A unit that systemd restarted after failures counts as running only while Frigate answers: in a crash loop the
    unit is active between crashes, and the run that failed is in the tail, not in the current invocation. Without
    restarts the current run is read even before Frigate answers, as while it starts up.

    Checks quote only what checks.validation_messages and checks.traceback_last_line pick from it, redacted.
    """

    def read() -> list[str]:
        values = unit_states(context).get(FRIGATE_UNIT)
        if values is not None and values.get("ActiveState") in RUNNING and (
            restarts(values) == 0 or frigate_version(context) is not None
        ):
            started = active_since(values)
            since = f"@{int(started.timestamp()) - 60}" if started else "-1h"
            return systemd.journal_lines(FRIGATE_UNIT, since, JOURNAL_LINES, values.get("InvocationID") or None)
        return systemd.journal_tail(FRIGATE_UNIT, JOURNAL_LINES) or []

    return context.probe(FRIGATE_JOURNAL, read)


def nodered_status(context: Context) -> tuple[int | None, dict | None]:
    """(HTTP status, body) of Node-RED's /tm-internal/status; (None, None) when it doesn't answer."""
    return context.probe(NODERED_STATUS, lambda: nodered.status(context.secrets.node_red_internal_token))


def nodered_report(context: Context) -> dict | None:
    """Node-RED's status when it answered with it (a 200); None when it didn't answer, refused the token, or failed."""
    code, body = nodered_status(context)
    return body if code == 200 else None


def config_yml(context: Context) -> ConfigRead:
    """config.yml as the host has it; .data is None when it's missing, unreadable, or not valid YAML."""
    return context.probe(CONFIG_YML, lambda: nodered.config(context.manifest.codedir))


def go2rtc_streams(context: Context) -> dict | None:
    return context.probe(GO2RTC_STREAMS, lambda: go2rtc.streams())


def mapping(value) -> dict:
    """value when it's a mapping, else an empty one: for reading sections of configs that a person edits."""
    return value if isinstance(value, dict) else {}


def frigate_safe_mode(config) -> bool:
    """Frigate's config says it started in safe mode: its config didn't validate, so it runs with no cameras."""
    return mapping(config).get("safe_mode") is True


def frigate_cameras(config: dict) -> dict[str, dict]:
    """The cameras in Frigate's config that are enabled there, by name."""
    cameras = {str(name): mapping(camera) for name, camera in mapping(config.get("cameras")).items()}
    return {name: camera for name, camera in cameras.items() if camera.get("enabled", True) is not False}
