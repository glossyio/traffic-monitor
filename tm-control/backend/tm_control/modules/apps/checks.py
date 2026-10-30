"""The apps check group: Frigate and its cameras, Node-RED with its config.yml and database schema, go2rtc's camera
streams, and the MQTT broker's login.

Details name cameras, zones, streams, and radars, never a URL, an input path, or another config value.
"""

import re
from pathlib import Path

from tm_control.adapters import mqtt
from tm_control.core.checks import Check, CheckGroup, Context, Fix
from tm_control.modules.apps import probes
from tm_control.modules.services.units import restart_fix

MIGRATION = re.compile(r"(\d{4})_.*\.sql")
STREAM = re.compile(r":8554/([^?#]+)")  # a go2rtc stream in a Frigate input path: rtsp://*:*@host...:8554/<name>
ERRORS_SHOWN = 3
MESSAGE_MAX = 200
DIAGNOSTICS = Fix(kind="link", href="/device", text="Diagnostics")
SEE_DIAGNOSTICS = "if it keeps stopping, download the diagnostics on the Device page"
RERUN_NODE_RED = "Re-run the installer with tmsetup.sh -t node-red-tm"
MIGRATE_JOURNAL = "sudo journalctl -u node-red-tm | grep tmdb-migrate"


def listed(names, conjunction: str = "and") -> str:
    names = list(names)
    if len(names) <= 2:
        return f" {conjunction} ".join(names)
    return f"{', '.join(names[:-1])}, {conjunction} {names[-1]}"


def plural(count: int, word: str) -> str:
    return f"{count} {word}" if count == 1 else f"{count} {word}s"


def duration(seconds: int) -> str:
    if seconds < 60:
        return "less than a minute"
    if seconds < 3600:
        return plural(seconds // 60, "minute")
    if seconds < 86400:
        return plural(seconds // 3600, "hour")
    return plural(seconds // 86400, "day")


def newest_migration(codedir) -> int | None:
    """The highest NNNN among <codedir>/node-red-tm/schema/migrations/NNNN_*.sql: the schema version this install's
    tmdb_migrate.py brings the database to."""
    try:
        names = [path.name for path in (Path(codedir) / "node-red-tm" / "schema" / "migrations").iterdir()]
    except OSError:
        return None
    numbers = [int(match[1]) for name in names if (match := MIGRATION.fullmatch(name))]
    return max(numbers, default=None)


# Frigate


def frigate(context: Context) -> list[Check]:
    def check(status, detail, fix=None):
        return [Check(id="apps.frigate.reachable", title="Frigate", status=status, detail=detail, fix=fix)]

    version = probes.frigate_version(context)
    if version is None:
        return check("error", f"Frigate isn't answering. Restart it; {SEE_DIAGNOSTICS}.",
                     restart_fix("frigate.service"))
    expected = context.manifest.components.get("frigate")
    if expected and version.split("-", 1)[0] != expected:
        return check("warn", f"Frigate {version} is running, but this install expects {expected}. "
                             "Run the installer (tmsetup.sh) again to rebuild it.")
    return check("ok", f"Frigate {version} is running.")


def cameras(context: Context) -> list[Check]:
    """Each camera enabled in Frigate gets frames (camera_fps above 0)."""

    def check(status, detail, fix=None):
        return [Check(id="apps.frigate.cameras", title="Cameras", status=status, detail=detail, fix=fix)]

    stats, config = probes.frigate_stats(context), probes.frigate_config(context)
    if stats is None or config is None:
        return check("unknown", "Frigate isn't answering, so its cameras can't be checked.")
    names = list(probes.frigate_cameras(config))
    if not names:
        return check("warn", "Frigate has no enabled camera, so nothing is counted. Enable one in Frigate's config.")
    stats_cameras = probes.mapping(stats.get("cameras"))

    def fps(name):
        value = probes.mapping(stats_cameras.get(name)).get("camera_fps")
        return value if isinstance(value, (int, float)) and not isinstance(value, bool) else 0

    stalled = [name for name in names if not fps(name) > 0]
    if stalled:
        return check(
            "error",
            f"Frigate gets no frames from {listed(stalled)}. Restart Frigate; if that doesn't help, check the "
            "camera and the Camera streams check.",
            restart_fix("frigate.service"),
        )
    return check("ok", f"Frigate gets frames from {listed(names)}.")


# Node-RED


def node_red(context: Context) -> list[Check]:
    def check(status, detail, fix=None):
        return [Check(id="apps.nodered.reachable", title="Node-RED", status=status, detail=detail, fix=fix)]

    code, body = probes.nodered_status(context)
    if code is None:
        return check("error", f"Node-RED isn't answering. Restart it; {SEE_DIAGNOSTICS}.",
                     restart_fix("node-red-tm.service"))
    if code == 401:
        return check("error", f"Node-RED is running, but the internal token doesn't match. {RERUN_NODE_RED}.")
    if code != 200 or body is None:
        return check("error", f"Node-RED answered, but not with its status. {RERUN_NODE_RED}.")
    uptime = body.get("uptime_seconds")
    if isinstance(uptime, int) and not isinstance(uptime, bool):
        return check("ok", f"Node-RED up {duration(max(0, uptime))}.")
    return check("ok", "Node-RED is answering.")


def _message(text) -> str:
    """One of Node-RED's config errors, on one line and not too long."""
    line = " ".join(str(text).split())
    return line if len(line) <= MESSAGE_MAX else f"{line[:MESSAGE_MAX - 1]}…"


def node_red_configuration(context: Context) -> list[Check]:
    """config.yml parses on the host, and Node-RED loaded it without errors."""

    def check(status, detail):
        return [Check(id="apps.nodered.config", title="Node-RED configuration", status=status, detail=detail)]

    read = probes.config_yml(context)
    if read.problem == "missing":
        return check("error", f"config.yml is missing. {RERUN_NODE_RED} to write a new one.")
    if read.problem == "invalid":
        where = f"line {read.line}, column {read.column}" if read.line is not None else "it isn't a YAML mapping"
        return check("error", f"config.yml has a YAML error: {where}. Correct it; until then Node-RED keeps the "
                              "settings it loaded before.")
    body = probes.nodered_report(context)
    if body is None:
        return check("unknown", "Node-RED didn't give its status, so it's unknown whether it loaded config.yml.")
    errors = probes.mapping(body.get("config")).get("errors")
    errors = [_message(error) for error in errors] if isinstance(errors, list) else []
    if not errors:
        return check("ok", "Node-RED loaded config.yml without errors.")
    shown = "; ".join(errors[:ERRORS_SHOWN])
    if len(errors) > ERRORS_SHOWN:
        shown += f"; and {len(errors) - ERRORS_SHOWN} more"
    return check("warn", f"Node-RED reported {plural(len(errors), 'problem')} loading config.yml: {shown}. "
                         "Correct config.yml; Node-RED reads it again when it's saved.")


def database_schema(context: Context) -> list[Check]:
    """Node-RED's database is at the schema version of this install's newest migration."""

    def check(status, detail, fix=None):
        return [Check(id="apps.nodered.schema", title="Database schema", status=status, detail=detail, fix=fix)]

    body = probes.nodered_report(context)
    if body is None:
        return check("unknown", "Node-RED didn't give its status, so the database's schema version is unknown.")
    version = body.get("schema_version")
    if not isinstance(version, int) or isinstance(version, bool):
        return check("unknown", "Node-RED couldn't read the database's schema version. Download the diagnostics on "
                                "the Device page to see why.", DIAGNOSTICS)
    newest = newest_migration(context.manifest.codedir)
    if newest is None:
        return check("unknown", "This install's schema migrations couldn't be read. "
                                "Run the installer (tmsetup.sh) again.")
    if version < newest:
        return check("error", f"The database schema is behind ({version} of {newest}), so Node-RED can't write new "
                              f"data. See why with {MIGRATE_JOURNAL}, or in the diagnostics.", DIAGNOSTICS)
    if version > newest:
        return check("warn", f"The database schema (version {version}) is newer than this install (version "
                             f"{newest}). Install the Traffic Monitor version that updated it.")
    return check("ok", f"Schema version {version}, as this install expects.")


# go2rtc


def _running(producer) -> bool:
    """go2rtc lists a producer that isn't running with its source URL only."""
    return isinstance(producer, dict) and any(key != "url" for key in producer)


def _read(stream) -> bool:
    """go2rtc lists the stream's readers under consumers; null or empty means nobody, Frigate included, reads it."""
    return bool(probes.mapping(stream).get("consumers"))


def camera_streams(context: Context) -> list[Check]:
    """Each go2rtc stream that a camera enabled in Frigate reads has a reader (Frigate itself; a `/feeds` viewer also
    counts) and a running source. Without a reader go2rtc never starts an `exec:` source, so the reader is judged
    first."""

    def check(status, detail, fix=None):
        return [Check(id="apps.go2rtc.streams", title="Camera streams", status=status, detail=detail, fix=fix)]

    restart = restart_fix("go2rtc_server.service")
    streams = probes.go2rtc_streams(context)
    if streams is None:
        return check("error", "go2rtc isn't answering, so the cameras get no video. Restart it.", restart)
    config = probes.frigate_config(context)
    if config is None:
        return check("unknown", "Frigate isn't answering, so the streams its cameras read can't be listed.")
    reads: dict[str, str] = {}  # stream -> the first camera that reads it
    for camera_name, camera in probes.frigate_cameras(config).items():
        for stream_input in probes.mapping(camera.get("ffmpeg")).get("inputs") or []:
            match = STREAM.search(str(probes.mapping(stream_input).get("path", "")))
            if match:
                reads.setdefault(match[1], camera_name)
    if not reads:
        return check("ok", "No camera in Frigate reads a go2rtc stream.")
    problems = []
    frigates = False  # a stream Frigate reads has no reader, so its capture stopped
    for stream, camera_name in reads.items():
        if stream not in streams:
            problems.append(f"go2rtc has no stream {stream}, which camera {camera_name} reads")
        elif not _read(streams[stream]):
            problems.append(f"Frigate isn't reading stream {stream} for camera {camera_name}, so it gets no video")
            frigates = True
        elif not any(_running(p) for p in probes.mapping(streams[stream]).get("producers") or []):
            problems.append(f"stream {stream} for camera {camera_name} has no running source")
    if problems:
        detail = "; ".join(problems)
        detail = f"{detail[0].upper()}{detail[1:]}"
        if frigates:
            return check("error", f"{detail}. Restart Frigate; if that doesn't help, download the diagnostics on "
                                  "the Device page.", restart_fix("frigate.service"))
        return check("error", f"{detail}. Restart go2rtc; if that doesn't help, check the camera and its cable.",
                     restart)
    return check("ok", f"{'Stream' if len(reads) == 1 else 'Streams'} {listed(reads)} running.")


# The MQTT broker


def mqtt_broker(context: Context) -> list[Check]:
    """While port 1883 is open to the network, the broker turns away clients without a login."""

    def check(status, detail, fix=None):
        return [Check(id="apps.broker.login", title="MQTT broker", status=status, detail=detail, fix=fix)]

    open_to_network = mqtt.port_1883_open_to_network()
    if open_to_network is None:
        return check("unknown", "The listening ports couldn't be read, so the broker's login couldn't be checked.")
    if not open_to_network:
        return check("ok", "Broker on this device only: port 1883 isn't open to the network.")
    refused = mqtt.anonymous_connect_refused()
    if refused is None:
        return check("unknown", "Port 1883 is open to the network, but the broker didn't answer, so its login "
                                "couldn't be checked.")
    if refused:
        return check("ok", "Login enforced on the network port: the broker turns away clients without one.")
    return check(
        "error",
        "The broker accepts clients without a login while port 1883 is open to the network. Restart Node-RED so it "
        "loads the login from node-red-tm.env; if it still accepts them, re-run the installer with tmsetup.sh "
        "-t node-red-tm.",
        restart_fix("node-red-tm.service"),
    )


GROUP = CheckGroup(
    "apps", "Apps", [frigate, cameras, node_red, node_red_configuration, database_schema, camera_streams, mqtt_broker]
)
