"""Fake mode (TM_CONTROL_FAKE=1), for running and reviewing the control app on a laptop without a Pi.

`tm-control fake-reset` starts the fake device over, unclaimed, and prints its new setup code. `tm-control
dump-openapi` prints the API's OpenAPI document, from which the UI's client is typed (tm-control/ui/src/api/).
Neither needs a device's secrets, manifest, or state.
"""

import copy
import json
import math
import secrets
import shutil
import tempfile
import threading
import time
import uuid as uuid_module
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from tm_control.adapters.command import CommandResult
from tm_control.adapters.nodered import NodeRed, NodeRedError, config_file_path
from tm_control.adapters.yamlfile import ConfigRead
from tm_control.adapters.timedate import Ntp, TimeState
from tm_control.core.auth import Device, SetupCode
from tm_control.core.checks import CheckGroup, Group
from tm_control.core.claim_cli import CommandError
from tm_control.core.settings import EULA_PATH, FAKE_FIXTURES, FAKE_MANIFEST, FAKE_STATUS, Settings
from tm_control.core.state import State

FAKE_RUNNING_MODEL = "running-model"  # the file holding the name of the model the fake Frigate runs
FAKE_DETECT = "frigate-detect.json"  # the fake Frigate's detection switches, {camera: bool}
FAKE_PLUS_ID = "0123456789abcdef0123456789abcdef"  # the fixture sidecar's model id
STATE_FILES = ("state.sqlite", "state.sqlite-wal", "state.sqlite-shm")

# Fake mode's unit states, as systemd.show_units returns them; the others run, so the Services list shows a running,
# a failed, and a starting unit, as the fake status report does.
FAKE_UNIT_STATES = {
    "frigate.service": {"ActiveState": "failed", "SubState": "failed", "NRestarts": "3"},
    "go2rtc_server.service": {"ActiveState": "activating", "SubState": "auto-restart", "NRestarts": "4"},
}


def reset(settings: Settings) -> int:
    """Delete the fake device's state database, create a fresh one, and print a new setup code for it."""
    if not settings.fake:
        raise CommandError("fake-reset only works in fake mode: set TM_CONTROL_FAKE=1.", exit_code=2)
    for name in STATE_FILES:
        (settings.state_dir / name).unlink(missing_ok=True)
    settings.state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    state = State(settings.state_dir / "state.sqlite")
    state.migrate()
    seed_model_cache(settings)
    detect_file(settings).unlink(missing_ok=True)
    config = config_file_path(settings, None)
    for path in [config, *config.parent.glob(f"{config.name}.*.bak")]:
        path.unlink(missing_ok=True)
    seed_config(settings)
    code = SetupCode.generate()
    Device(state).set_setup_code_hash(SetupCode.hash_code(code))
    print(f"Fake device reset in {settings.state_dir}. Setup code: {code}")
    print("Restart `tm-control serve` if it's running, then open the UI's /setup page.")
    return 0


def model_cache(settings: Settings) -> Path:
    """The fake device's model_cache, beside its state directory."""
    return settings.state_dir.parent / "model_cache"


def running_model_file(settings: Settings) -> Path:
    """The file naming the model the fake Frigate runs: empty or missing for Frigate's own default. It's beside
    model_cache, not in it, so it isn't listed as a model."""
    return settings.state_dir.parent / FAKE_RUNNING_MODEL


def seed_model_cache(settings: Settings) -> None:
    """Start the fake device's model_cache over with what a Coral unit shows: the installer's default (zeros, no
    sidecar), the fixture sidecar's Frigate+ pair, and a local model with the same sidecar, which the fake Frigate
    runs the Frigate+ one of."""
    from tm_control.core.manifest import load_manifest
    from tm_control.modules.apps.contracts import installer_model_file

    cache = model_cache(settings)
    cache.mkdir(parents=True, exist_ok=True)
    for entry in cache.iterdir():
        if entry.is_file() or entry.is_symlink():
            entry.unlink()
    installer = installer_model_file(load_manifest(settings.manifest_path))
    if installer is not None:
        (cache / installer).write_bytes(bytes(1024))
    sidecar = (FAKE_FIXTURES / "model_sidecar.json").read_text()
    (cache / FAKE_PLUS_ID).write_bytes(bytes(4096))
    (cache / f"{FAKE_PLUS_ID}.json").write_text(sidecar)
    local = {key: value for key, value in json.loads(sidecar).items() if key != "id"} | {"name": "My model"}
    (cache / "mine.tflite").write_bytes(bytes(2048))
    (cache / "mine.tflite.json").write_text(json.dumps(local, indent=2) + "\n")
    running_model_file(settings).write_text(FAKE_PLUS_ID)


def detect_file(settings: Settings) -> Path:
    return settings.state_dir.parent / FAKE_DETECT


def _detect_switches(settings: Settings) -> dict:
    try:
        switches = json.loads(detect_file(settings).read_text())
    except (OSError, ValueError):
        return {}
    return switches if isinstance(switches, dict) else {}


def set_frigate_detect(settings: Settings, camera: str, on: bool) -> bool:
    """Fake mode's stand-in for frigate.set_detect: the switch is kept beside the fake state and frigate_answer applies
    it. Like Frigate, it takes a camera it has."""
    if camera not in frigate_answer(settings)[0]["cameras"]:
        return False
    switches = _detect_switches(settings) | {camera: on}
    detect_file(settings).write_text(json.dumps(switches))
    return True


def seed_config(settings: Settings) -> Path:
    """Give the fake device Node-RED's config.yml, the fixture's (a camera and a radar, at 45.0, -122.0, with no survey
    id), when it has none; a file already there is kept, with whatever the fake device wrote to it."""
    path = config_file_path(settings, None)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(FAKE_FIXTURES / "node_red_config_ok.yml", path)
        path.chmod(0o640)
    return path


def backup_dir(settings: Settings) -> Path:
    """Where the fake device's tmdb backups would be: beside its state directory, and empty, so fake mode never reads
    a real device's directory."""
    return settings.state_dir.parent / "node-red-tm" / "db" / "backup"


def use_model(settings: Settings, name: str) -> None:
    """Fake mode's stand-in for using a model, which a device does by saving Frigate's config and restarting it: the
    fake Frigate runs `name` from now on (an empty name: Frigate's own default)."""
    running_model_file(settings).write_text(name)


def frigate_answer(settings: Settings) -> tuple[dict, ConfigRead]:
    """The fake Frigate's /api/config, which is the fixture's with the running model's path in the first detector, a
    second camera (oak_ave_tele, a copy of the first), the detection switches set_frigate_detect keeps, and a config.yml
    that is missing. Nothing outside the fake directory is read."""
    config = json.loads((FAKE_FIXTURES / "frigate_api_config.json").read_text())
    try:
        name = running_model_file(settings).read_text().strip()
    except OSError:
        name = ""
    detector = next(iter(config["detectors"].values()))
    model = detector.setdefault("model", {})
    if name:
        model["path"] = f"/config/model_cache/{name}"
    else:
        model.pop("path", None)
    first = next(iter(config["cameras"].values()))  # a camera that no config.yml entry points at, for the Cameras page
    config["cameras"]["oak_ave_tele"] = copy.deepcopy(first) | {"name": "oak_ave_tele"}
    for camera, on in _detect_switches(settings).items():
        if camera in config["cameras"] and isinstance(on, bool):
            config["cameras"][camera].setdefault("detect", {})["enabled"] = on
    return copy.deepcopy(config), ConfigRead(None, "missing")


def show_units(names: list[str], properties: list[str]) -> dict[str, dict[str, str]]:
    """Fake mode's stand-in for systemd.show_units: FAKE_UNIT_STATES, and every other unit running for two hours."""
    running = {
        "LoadState": "loaded",
        "ActiveState": "active",
        "SubState": "running",
        "NRestarts": "0",
        "ActiveEnterTimestamp": f"@{int(time.time()) - 2 * 3600}",
        "InvocationID": "00000000000000000000000000000000",
    }
    states = {name: running | FAKE_UNIT_STATES.get(name, {}) for name in names}
    return {name: {key: values.get(key, "") for key in properties} for name, values in states.items()}


def system_info(disk_paths: list[str]) -> dict:
    """Fake mode's host readings, as the sysinfo adapter returns them: a Pi 5 up for two days, its storage 87% used
    (as the fake status report says), each disk path on the same card."""
    total, free = 58 * 2**30, int(7.5 * 2**30)
    return {
        "model": "Raspberry Pi 5 Model B Rev 1.0",
        "os": "Debian GNU/Linux 13 (trixie)",
        "kernel": "6.12.47+rpt-rpi-2712",
        "uptime_seconds": 2 * 86400 + 3 * 3600,
        "memory": {"total": 8 * 2**30, "available": int(5.5 * 2**30)},
        "disks": [{"path": path, "total": total, "used": total - free, "free": free} for path in disk_paths],
        "soc_temperature_c": 52.7,
        "throttled": {"raw": "0x0", "now": [], "since_boot": []},
    }


def time_state() -> list[str]:
    """Fake mode's stand-in for timedatectl show, in FakeClock's starting time zone."""
    now = time.strftime("%a %Y-%m-%d %H:%M:%S UTC", time.gmtime())
    return [
        "Timezone=Etc/UTC",
        "LocalRTC=no",
        "CanNTP=yes",
        "NTP=yes",
        "NTPSynchronized=yes",
        f"TimeUSec={now}",
        f"RTCTimeUSec={now}",
    ]


class FakeClock:
    """Fake mode's stand-in for the timedate adapter, kept in memory so the Date and time page sees its own changes.
    NTP starts on and synchronized; the time is the laptop's, shown in the fake time zone; nothing is set."""

    TIMEZONES = [
        "America/Los_Angeles",
        "America/New_York",
        "Asia/Tokyo",
        "Australia/Sydney",
        "Etc/UTC",
        "Europe/Berlin",
        "Europe/London",
        "Pacific/Auckland",
    ]

    def __init__(self):
        self.timezone = "Etc/UTC"
        self.ntp = True

    def show(self) -> TimeState:
        try:
            now = datetime.now(ZoneInfo(self.timezone))
        except ZoneInfoNotFoundError:  # a laptop without the tz database
            now = datetime.now().astimezone()
        return TimeState(
            device_time=now.isoformat(timespec="seconds"),
            timezone=self.timezone,
            ntp=Ntp(enabled=self.ntp, synchronized=self.ntp, available=True),
            rtc_time=None,
        )

    def now(self) -> datetime:
        return datetime.now().astimezone()

    def list_timezones(self) -> list[str]:
        return list(self.TIMEZONES)

    def set_timezone(self, name: str) -> CommandResult:
        self.timezone = name
        return CommandResult(0, "", "", False)

    def set_ntp(self, enabled: bool) -> CommandResult:
        self.ntp = enabled
        return CommandResult(0, "", "", False)

    def set_time(self, when: datetime) -> CommandResult:
        return CommandResult(0, "", "", False)


class FakeNetwork:
    """Fake mode's hotspot, kept in memory so the Network page sees its own changes. `hotspot` is what GET /network
    shows (it starts on and secured); the password is kept apart and never part of that answer."""

    def __init__(self):
        self.hotspot = {
            "enabled": True,
            "active": True,
            "name": "TM-AB12",
            "hidden": False,
            "security": "wpa2",
            "address": "10.42.0.1",
        }
        self.password: str | None = "ABCD-EFGH-JKLM"
        self.saved: list[dict] = [
            {
                "uuid": "11111111-1111-4111-8111-111111111111", "name": "Home", "in_use": False, "automatic": True,
                "hidden": False, "in_range": True, "could_not_join": False,
            },
            {
                "uuid": "22222222-2222-4222-8222-222222222222", "name": "Depot", "in_use": False, "automatic": True,
                "hidden": False, "in_range": False, "could_not_join": False,
            },
        ]
        self.nearby: list[dict] = [
            {"name": "Home", "signal": 82, "security": "password"},
            {"name": "Cafe", "signal": 64, "security": "password"},
            {"name": "Guest", "signal": 41, "security": "open"},
            {"name": "Office", "signal": 30, "security": "password"},
            {"name": "Neighbour", "signal": 18, "security": "wpa3"},
        ]
        self.scanned: float | None = None  # time.monotonic() of the last scan
        self.join: dict | None = None  # the join job's state file, as tm-job-network-join writes it

    def apply(self, change: dict) -> None:
        """Set what a job request names: for the hotspot, enabled, name, hidden, and password; for the saved Wi-Fi
        networks, an `action` of scan, forget, or order; for a join, switch-now or cancel."""
        action = change.get("action")
        if action == "switch-now":
            self.switch()
        elif action == "cancel":
            self.cancel()
        elif action == "scan":
            self.scanned = time.monotonic()
        elif action == "forget":
            self.saved = [n for n in self.saved if n["uuid"] != change["uuid"]]
        elif action == "order":
            rank = {uuid: i for i, uuid in enumerate(change["uuids"])}
            automatic = sorted((n for n in self.saved if n["uuid"] in rank), key=lambda n: rank[n["uuid"]])
            self.saved = automatic + [n for n in self.saved if n["uuid"] not in rank]
        if "enabled" in change:
            self.hotspot["enabled"] = self.hotspot["active"] = change["enabled"]
        if "name" in change:
            self.hotspot["name"] = change["name"]
        if "hidden" in change:
            self.hotspot["hidden"] = change["hidden"]
        if "password" in change:
            self.password = change["password"]
            self.hotspot["security"] = "wpa2"

    COUNTDOWN = 300  # seconds

    def start_join(self, name: str, password: str | None, saved: bool) -> None:
        """A join to `name`: the password `wrong-password` ends as failed (not_joined) and `no-address-pass` as failed
        (no_address); anything else passes the test and counts down. No password is kept."""
        before = "tm-hotspot" if self.hotspot["active"] else next((n["name"] for n in self.saved if n["in_use"]), None)
        uuid = next((n["uuid"] for n in self.saved if n["name"] == name), None) if saved else None
        self.join = {
            "stage": "countdown", "ssid": name, "uuid": uuid, "saved": saved, "before": before, "joined": True,
            "reason": None, "address": "192.168.1.80", "internet": "reachable",
            "switch_monotonic": time.monotonic() + self.COUNTDOWN, "finished_at": None,
        }
        reason = {"wrong-password": "not_joined", "no-address-pass": "no_address"}.get(password)
        if reason is not None:
            self.join.update(
                stage="failed", joined=False, reason=reason, address=None, internet=None, switch_monotonic=None,
                finished_at=self._now(),
            )

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    def read_join(self) -> dict | None:
        """The join's state; a countdown that has run out has switched."""
        join = self.join
        if join is not None and join["stage"] == "countdown" and time.monotonic() >= join["switch_monotonic"]:
            self.switch()
        return self.join

    def switch(self) -> None:
        """Switch now: the network is saved, first in the order and in use, and the hotspot is down."""
        join = self.join
        if join is None or join["stage"] != "countdown":
            return
        name = join["ssid"]
        known = next((n for n in self.saved if n["name"] == name), None)
        if known is None:
            known = {
                "uuid": str(uuid_module.uuid4()), "name": name, "in_use": False, "automatic": True,
                "hidden": False, "in_range": True, "could_not_join": False,
            }
        for n in self.saved:
            n["in_use"] = False
        known.update(in_use=True, in_range=True, could_not_join=False)
        self.saved = [known] + [n for n in self.saved if n is not known]
        self.hotspot["active"] = False
        join.update(stage="joined", saved=True, uuid=known["uuid"], switch_monotonic=None, finished_at=self._now())

    def cancel(self) -> None:
        """Cancel a countdown (the result stays to be dismissed), or dismiss a finished join."""
        if self.join is not None and self.join["stage"] == "countdown":
            self.join.update(stage="cancelled", switch_monotonic=None, finished_at=self._now())
        else:
            self.join = None


def journal_tail(unit: str, lines: int) -> list[str]:
    """Fake mode's stand-in for systemd.journal_tail: a few ordinary lines."""
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(time.time() - 2 * 3600))
    return [
        f"{stamp} tm-fake systemd[1]: Starting {unit}...",
        f"{stamp} tm-fake systemd[1]: Started {unit}.",
    ][-lines:]


def status_groups(path: Path = FAKE_STATUS) -> list[CheckGroup]:
    """Fake mode's check groups: the fixture's groups, which between them show every status and kind of fix."""
    groups = [Group.model_validate(group) for group in json.loads(path.read_text())["groups"]]
    return [CheckGroup(group.id, group.title, [_fixed_checks(group)]) for group in groups]


def _fixed_checks(group: Group):
    def checks(context):
        return [check.model_copy(deep=True) for check in group.checks]

    checks.__name__ = group.id
    return checks


def openapi_document() -> dict:
    """The app's OpenAPI document, from an app built in fake mode with throwaway state."""
    from tm_control.app import create_app  # here, like cli.py's imports, so `migrate` doesn't need FastAPI

    with tempfile.TemporaryDirectory(prefix="tm-control-openapi-") as tmp:
        root = Path(tmp)
        settings = Settings(
            state_dir=root / "state",
            runtime_dir=root / "run",
            secrets_dir=root / "secrets",
            manifest_path=FAKE_MANIFEST,
            host="127.0.0.1",
            port=0,
            fake=True,
            eula_path=EULA_PATH,
            setup_code_file=root / "setup-code",
        )
        return create_app(settings).openapi()


class FakeNodeRed(NodeRed):
    """Fake mode's Node-RED: the /tm-internal/ endpoints over deployment rows kept in memory, and the deployment
    engine's rules (the flows' "deployment engine" function) run on them whenever config.yml changes.

    Like the watch node, it notices a change to the file by itself (on its next call), so reconcile's writes and hand
    edits are applied too; after_config_write applies one at once. It starts as Node-RED does, by running the engine
    once, so the seeded file's sensors have open rows with no survey id, which the engine adopts once the file names a
    survey. Events are never recorded: a survey's event count is always 0.
    """

    SCHEMA_VERSION = 2

    def __init__(self, config_path: Path):
        super().__init__("fake")
        self.config_path = Path(config_path)
        self.rows: list[dict] = []
        self._lock = threading.RLock()
        self._seen = None  # the file's (inode, size, mtime) when the engine last ran
        self._deployment = None  # config.yml's deployment keys as last read (the engine's global.config.deployment)
        self._watch()

    # the watch node and the engine

    def _signature(self):
        try:
            found = self.config_path.stat()
        except OSError:
            return None
        return (found.st_ino, found.st_size, found.st_mtime_ns)

    def _watch(self, force: bool = False) -> None:
        with self._lock:
            signature = self._signature()
            if signature is not None and (force or signature != self._seen):
                self._seen = signature
                self._reload()

    def after_config_write(self) -> None:
        self._watch(force=True)

    def _reload(self) -> None:
        from tm_control.modules.location.config import ConfigError, NodeRedConfig

        try:
            config = NodeRedConfig(self.config_path)
        except ConfigError:
            return  # as init-config: a file that doesn't load leaves the previous config in place
        self._deployment = config.deployment()
        self._engine(self._deployment, config.sensors(), config.listed_sensors())

    def _engine(self, place, sensors, listed) -> None:
        from tm_control.modules.location.coordinates import round_half_away

        places = {"none": None, "1": 1, "2": 2}[place.precision]
        now = int(time.time() * 1000)

        def location(lat, lon, digits):
            if lat is None or lon is None or digits is None:
                return {"lat": None, "lon": None, "location_precision": None}
            return {
                "lat": round_half_away(lat, digits), "lon": round_half_away(lon, digits), "location_precision": digits,
            }

        def fineness(digits):
            return 0 if digits is None else digits

        stored = location(place.lat, place.lon, places)

        def insert(sensor, survey_id, bearing):
            row = {
                "id": f"{now}-{secrets.token_hex(4)}-d", "entryStartDateTime": now, "entryEndDateTime": None,
                **stored, "bearing": bearing, "sensorType": sensor.sensor_type, "sensorName": sensor.sensor_name,
                "survey_id": survey_id,
            }
            self.rows.append(row)

        for sensor in sensors:
            open_rows = sorted(
                (row for row in self.rows if row["entryEndDateTime"] is None
                 and (row["sensorType"], row["sensorName"]) == (sensor.sensor_type, sensor.sensor_name)),
                key=lambda row: row["entryStartDateTime"], reverse=True,
            )
            want_survey, want_bearing = place.survey_id, sensor.bearing
            for older in open_rows[1:]:  # 1. one open row per sensor
                older["entryEndDateTime"] = now
            row = open_rows[0] if open_rows else None
            if row is None:  # 2. no open row
                insert(sensor, want_survey, want_bearing)
                continue
            same_bearing = (row["bearing"] or "").strip().lower() == want_bearing
            if want_survey is not None and row["survey_id"] is None and same_bearing:  # 4. adopt
                row.update(stored, survey_id=want_survey)
            elif want_survey is not None and (row["survey_id"] != want_survey or not same_bearing):  # 5. new
                row["entryEndDateTime"] = now
                insert(sensor, want_survey, want_bearing)
            elif fineness(row["location_precision"]) > fineness(places):  # 3 and 6: kept, a coarser one re-rounds
                row.update(location(row["lat"], row["lon"], places))

        if listed is not None:  # 7. a sensor the file no longer lists, on or off, ends its deployment
            for row in self.rows:
                if row["entryEndDateTime"] is None and (row["sensorType"], row["sensorName"]) not in listed:
                    row["entryEndDateTime"] = now

    # the endpoints

    @staticmethod
    def _check_survey(survey_id) -> None:
        from tm_control.modules.location.coordinates import SURVEY_ID

        if not isinstance(survey_id, str) or not SURVEY_ID.fullmatch(survey_id):
            raise NodeRedError("bad_request", 400)

    def report(self) -> dict:
        self._watch()
        place = self._deployment
        return {
            "status": "ok",
            "schema_version": self.SCHEMA_VERSION,
            "config": {"loaded_at": None, "errors": []},
            "deployment": {
                "survey_id": place.survey_id if place else None,
                "database_precision": place.precision if place else "2",
            },
        }

    def deployments(self, survey_id: str) -> list[dict]:
        self._check_survey(survey_id)
        self._watch()
        with self._lock:
            found = [dict(row) for row in self.rows if row["survey_id"] == survey_id]
        return sorted(found, key=lambda row: row["entryStartDateTime"])

    def usage(self) -> list[dict]:
        self._watch()
        groups: dict = {}
        with self._lock:
            for row in self.rows:
                groups.setdefault(row["survey_id"], []).append(row)
        answer = []
        for survey_id in sorted(groups, key=lambda key: (key is not None, key or "")):  # NULL first, as SQLite
            rows = groups[survey_id]
            ends = [row["entryEndDateTime"] for row in rows if row["entryEndDateTime"] is not None]
            answer.append({
                "survey_id": survey_id,
                "first_start": min(row["entryStartDateTime"] for row in rows),
                "last_end": max(ends) if ends else None,
                "open_count": sum(row["entryEndDateTime"] is None for row in rows),
                "deployment_count": len(rows),
            })
        return answer

    def events(self, survey_id: str) -> dict:
        self._check_survey(survey_id)
        return {"survey_id": survey_id, "event_count": 0, "first_event": None, "last_event": None}

    def set_precision(self, precision: str) -> None:
        from tm_control.modules.location.coordinates import round_half_away

        if precision not in ("none", "1", "2"):
            raise NodeRedError("bad_request", 400)
        self._watch()
        with self._lock:
            for row in self.rows:
                if precision == "none":
                    if row["lat"] is not None or row["lon"] is not None:
                        row.update(lat=None, lon=None, location_precision=None)
                elif row["location_precision"] is not None and row["location_precision"] > int(precision):
                    digits = int(precision)
                    row.update(
                        lat=None if row["lat"] is None else round_half_away(row["lat"], digits),
                        lon=None if row["lon"] is None else round_half_away(row["lon"], digits),
                        location_precision=digits,
                    )

    def correct_location(self, survey_id: str, lat: float, lon: float) -> None:
        from tm_control.modules.location.coordinates import round_half_away

        self._check_survey(survey_id)
        for value, limit in ((lat, 90), (lon, 180)):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) \
                    or abs(value) > limit:
                raise NodeRedError("bad_request", 400)
        self._watch()
        with self._lock:
            for row in self.rows:
                if row["survey_id"] == survey_id and row["location_precision"] is not None:
                    digits = row["location_precision"]
                    row.update(lat=round_half_away(lat, digits), lon=round_half_away(lon, digits))

    def correct_bearing(self, deployment_id: str, bearing: str) -> None:
        from tm_control.modules.location.coordinates import BEARINGS, DEPLOYMENT_ID

        bearing = bearing.lower() if isinstance(bearing, str) else None
        if not isinstance(deployment_id, str) or not DEPLOYMENT_ID.fullmatch(deployment_id) \
                or (bearing != "" and bearing not in BEARINGS):
            raise NodeRedError("bad_request", 400)
        self._watch()
        with self._lock:
            for row in self.rows:
                if row["id"] == deployment_id:
                    row["bearing"] = bearing
