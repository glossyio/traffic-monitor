import importlib
import re
import socket
import sqlite3
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from ruamel.yaml import YAML

from tm_control.adapters import command, sysinfo, systemd
from tm_control.adapters.command import CommandResult
from tm_control.adapters.redact import redact
from tm_control.core.secrets import DEVICE_SECRETS, NAMES
from tm_control.modules import MODULES
from tm_control.modules.services.units import units_for
from tm_control.modules.system import diagnostics as diagnostics_module

BASE = "http://tm-test.local"
ORIGIN = {"Origin": BASE}
ADMIN = ("admin", "correct horse 1")
VIEWER = ("viewer", "viewer pass 1")
REPO = Path(__file__).resolve().parents[3]
GIB = 2**30
MIB = 2**20
SERIAL = "10000000abcdef01"
THROTTLED = sysinfo.throttled  # the real reader, before the host fixture replaces it
SYSTEM_ROUTER = importlib.import_module("tm_control.modules.system.router")  # the package's `router` is the APIRouter
INSTALLED = [
    "traffic-monitor.service",
    "frigate.service",
    "node-red-tm.service",
    "go2rtc_server.service",
    "revproxy.service",
    "tm-control.service",
]


class Host:
    """The sysinfo readings a test sets; every function of tm_control.adapters.sysinfo answers from here."""

    def __init__(self, codedir):
        self.codedir = codedir
        self.model = "Raspberry Pi 5 Model B Rev 1.0"
        self.os_release = "Debian GNU/Linux 13 (trixie)"
        self.kernel = "6.12.47+rpt-rpi-2712"
        self.uptime_seconds = 3600
        self.memory = {"total": 8 * GIB, "available": 6 * GIB}
        self.free = {"/": 20 * GIB, codedir: 20 * GIB}
        self.filesystems = {"/": 1, codedir: 1}
        self.soc_temperature_c = 52.5
        self.throttled = {"raw": "0x0", "now": [], "since_boot": []}
        self.time_state = ["Timezone=America/Los_Angeles", "NTP=yes", "NTPSynchronized=yes"]
        self.journal = lambda unit, lines: [f"2026-10-28T09:12:30-0700 tm {unit}: line {n}" for n in range(3)]
        self.journal_calls = []

    def disk(self, path):
        free = self.free.get(path)
        if free is None:
            return None
        return {"path": path, "total": 32 * GIB, "used": 32 * GIB - free, "free": free}

    def value(self, name):
        value = getattr(self, name)
        if isinstance(value, Exception):
            raise value
        return value


@pytest.fixture(autouse=True)
def env_files_read(monkeypatch, tmp_path):
    """The code directories diagnostics reads .env files from. Only a test's own tmp_path is allowed, so no test reads
    a real install's files (the fixture manifest's codedir is the device's)."""
    seen = []
    read = diagnostics_module.env_secret_values

    def guarded(codedir):
        seen.append(Path(codedir))
        assert Path(codedir).is_relative_to(tmp_path), f"a test read .env files under {codedir}"
        return read(codedir)

    monkeypatch.setattr(diagnostics_module, "env_secret_values", guarded)
    return seen


@pytest.fixture
def host(monkeypatch, device_client, tmp_path):
    """Synthetic host readings for device_client, whose manifest codedir is moved to an empty tmp_path/code."""
    codedir = tmp_path / "code"
    codedir.mkdir()
    app_state = device_client.app.state
    app_state.manifest = app_state.manifest.model_copy(update={"codedir": str(codedir)})
    host = Host(str(codedir))
    for name in ("model", "os_release", "kernel", "uptime_seconds", "memory", "soc_temperature_c", "throttled",
                 "time_state"):
        monkeypatch.setattr(sysinfo, name, lambda name=name: host.value(name))
    monkeypatch.setattr(sysinfo, "disk", host.disk)
    monkeypatch.setattr(sysinfo, "filesystem", lambda path: host.filesystems.get(path))

    def journal_tail(unit, lines):
        host.journal_calls.append((unit, lines))
        return host.journal(unit, lines)

    def show_units(names, properties):
        running = {"LoadState": "loaded", "ActiveState": "active", "SubState": "running", "NRestarts": "0"}
        return {name: {key: running.get(key, "") for key in properties} for name in names}

    monkeypatch.setattr(systemd, "journal_tail", journal_tail)
    monkeypatch.setattr(systemd, "show_units", show_units)
    monkeypatch.setattr(SYSTEM_ROUTER, "read_serial", lambda: SERIAL)
    return host


def audit_rows(client):
    con = sqlite3.connect(client.app.state.settings.state_dir / "state.sqlite")
    try:
        return [tuple(row) for row in con.execute("SELECT action, detail FROM audit ORDER BY id")]
    finally:
        con.close()


def add_viewer(client):
    from tm_control.core.auth import Users

    Users(client.app.state.state).create(*VIEWER, "viewer")


def device_checks(client):
    r = client.post("/api/v1/status/rescan", json={}, headers=ORIGIN)
    assert r.status_code == 200, r.text
    (group,) = [g for g in r.json()["groups"] if g["id"] == "device"]
    assert group["title"] == "Device"
    return {check["id"]: check for check in group["checks"]}


# Device info


def test_the_system_module_has_the_device_group_and_comes_last_for_now():
    ids = [m.id for m in MODULES]
    assert ids[ids.index("services") + 1] == "system"
    (system,) = [m for m in MODULES if m.id == "system"]
    assert [g.id for g in system.check_groups] == ["device"]


def test_system_info_for_a_viewer(device_client, login, host):
    login(device_client, *VIEWER)
    r = device_client.get("/api/v1/system/info")
    assert r.status_code == 200, r.text
    assert r.json() == {
        "hostname": socket.gethostname(),
        "serial": SERIAL,
        "model": "Raspberry Pi 5 Model B Rev 1.0",
        "os": "Debian GNU/Linux 13 (trixie)",
        "kernel": "6.12.47+rpt-rpi-2712",
        "uptime_seconds": 3600,
        "memory": {"total": 8 * GIB, "available": 6 * GIB},
        "disks": [
            {"path": "/", "total": 32 * GIB, "used": 12 * GIB, "free": 20 * GIB},
            {"path": host.codedir, "total": 32 * GIB, "used": 12 * GIB, "free": 20 * GIB},
        ],
        "tm": {
            "version": "0.7.1-test",
            "commit": "0000000000000000000000000000000000000000",
            "branch": "test",
            "installing_user": "pi",
        },
        "components": {
            "frigate": "0.18.1",
            "node_red": "5.0.8",
            "go2rtc": "v1.9.14",
            "nginx": "1.31.0",
            "hailo": "4.21.0",
        },
        "soc_temperature_c": 52.5,
        "throttled": {"raw": "0x0", "now": [], "since_boot": []},
    }


def test_system_info_in_fake_mode(claimed_client, login, monkeypatch):
    def no_run(argv, **kwargs):
        raise AssertionError(f"fake mode ran {argv}")

    monkeypatch.setattr("tm_control.adapters.sysinfo.run", no_run)
    add_viewer(claimed_client)
    login(claimed_client, *VIEWER)
    r = claimed_client.get("/api/v1/system/info")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["hostname"] == "tm-fake" != socket.gethostname()
    assert body["serial"] == "0000000012345678"
    assert body["model"].startswith("Raspberry Pi 5")
    assert [d["path"] for d in body["disks"]] == ["/", "/opt/traffic-monitor"]
    assert body["throttled"]["raw"] == "0x0"


def test_system_info_tolerates_missing_sources(device_client, login, host):
    for name in ("model", "os_release", "kernel", "uptime_seconds", "memory", "soc_temperature_c", "throttled"):
        setattr(host, name, None)
    host.free = {}
    login(device_client, *VIEWER)
    r = device_client.get("/api/v1/system/info")
    assert r.status_code == 200, r.text
    body = r.json()
    for key in ("model", "os", "kernel", "uptime_seconds", "memory", "soc_temperature_c", "throttled"):
        assert body[key] is None, key
    assert body["disks"] == []

    host.throttled = sysinfo.NeedsVideoGroup()
    r = device_client.get("/api/v1/system/info")
    assert r.status_code == 200 and r.json()["throttled"] is None


def test_system_info_needs_a_login(device_client, host):
    assert device_client.get("/api/v1/system/info").status_code == 401


# The sysinfo adapter


def test_sysinfo_readers(tmp_path, monkeypatch):
    (tmp_path / "model").write_bytes(b"Raspberry Pi 5 Model B Rev 1.0\x00")
    (tmp_path / "os-release").write_text('NAME="Debian GNU/Linux"\nPRETTY_NAME="Debian GNU/Linux 13 (trixie)"\n')
    (tmp_path / "uptime").write_text("12345.67 45678.90\n")
    (tmp_path / "meminfo").write_text("MemTotal:        8241232 kB\nMemFree:  100 kB\nMemAvailable:    6123456 kB\n")
    (tmp_path / "temp").write_text("52500\n")
    monkeypatch.setattr(sysinfo, "MODEL_PATH", tmp_path / "model")
    monkeypatch.setattr(sysinfo, "OS_RELEASE_PATH", tmp_path / "os-release")
    monkeypatch.setattr(sysinfo, "UPTIME_PATH", tmp_path / "uptime")
    monkeypatch.setattr(sysinfo, "MEMINFO_PATH", tmp_path / "meminfo")
    monkeypatch.setattr(sysinfo, "THERMAL_PATH", tmp_path / "temp")
    assert sysinfo.model() == "Raspberry Pi 5 Model B Rev 1.0"
    assert sysinfo.os_release() == "Debian GNU/Linux 13 (trixie)"
    assert sysinfo.uptime_seconds() == 12345
    assert sysinfo.memory() == {"total": 8241232 * 1024, "available": 6123456 * 1024}
    assert sysinfo.soc_temperature_c() == 52.5
    assert isinstance(sysinfo.kernel(), str)
    usage = sysinfo.disk(str(tmp_path))
    assert usage["path"] == str(tmp_path) and usage["total"] >= usage["free"] > 0
    assert sysinfo.filesystem(str(tmp_path)) == tmp_path.stat().st_dev


def test_sysinfo_readers_return_none_on_failure(tmp_path, monkeypatch):
    for name in ("MODEL_PATH", "OS_RELEASE_PATH", "UPTIME_PATH", "MEMINFO_PATH", "THERMAL_PATH"):
        monkeypatch.setattr(sysinfo, name, tmp_path / "missing")
    assert sysinfo.model() is None
    assert sysinfo.os_release() is None
    assert sysinfo.uptime_seconds() is None
    assert sysinfo.memory() is None
    assert sysinfo.soc_temperature_c() is None
    assert sysinfo.disk(str(tmp_path / "missing")) is None
    assert sysinfo.filesystem(str(tmp_path / "missing")) is None
    (tmp_path / "garbage").write_text("not a number\nMemTotal: lots\n")
    for name in ("UPTIME_PATH", "MEMINFO_PATH", "THERMAL_PATH"):
        monkeypatch.setattr(sysinfo, name, tmp_path / "garbage")
    assert sysinfo.uptime_seconds() is None
    assert sysinfo.memory() is None
    assert sysinfo.soc_temperature_c() is None


class FakeRun:
    def __init__(self, result=None, error=None):
        self.result, self.error, self.calls = result, error, []

    def __call__(self, argv, **kwargs):
        self.calls.append((list(argv), kwargs))
        if self.error:
            raise self.error
        return self.result


def test_throttled_parses_the_flags(monkeypatch):
    fake = FakeRun(CommandResult(0, "throttled=0x50005\n", "", False))
    monkeypatch.setattr(sysinfo, "run", fake)
    assert sysinfo.throttled() == {
        "raw": "0x50005",
        "now": ["under-voltage", "throttled"],
        "since_boot": ["under-voltage", "throttled"],
    }
    (argv, kwargs) = fake.calls[0]
    assert argv == ["vcgencmd", "get_throttled"]
    assert 0 < kwargs["timeout"] <= 4 and kwargs["max_output"] <= 65536
    fake.result = CommandResult(0, "throttled=0xf000a\n", "", False)
    assert sysinfo.throttled() == {
        "raw": "0xf000a",
        "now": ["frequency-capped", "soft-temperature-limit"],
        "since_boot": ["under-voltage", "frequency-capped", "throttled", "soft-temperature-limit"],
    }


@pytest.mark.parametrize(
    "result",
    [
        CommandResult(255, "", "Can't open device file: /dev/vcio_gencmd\n", False),
        CommandResult(255, "Can't open device file: /dev/vcio_gencmd\n", "", False),
        CommandResult(1, "", "open: Permission denied\n", False),
    ],
)
def test_throttled_without_the_video_group(monkeypatch, result):
    monkeypatch.setattr(sysinfo, "run", FakeRun(result))
    with pytest.raises(sysinfo.NeedsVideoGroup):
        sysinfo.throttled()


@pytest.mark.parametrize(
    "fake",
    [
        FakeRun(error=FileNotFoundError(2, "No such file or directory")),
        FakeRun(CommandResult(-9, "", "", True)),
        FakeRun(CommandResult(0, "something else\n", "", False)),
        FakeRun(CommandResult(1, "", "VCHI initialization failed\n", False)),
    ],
)
def test_throttled_is_none_on_other_failures(monkeypatch, fake):
    monkeypatch.setattr(sysinfo, "run", fake)
    assert sysinfo.throttled() is None


def test_time_state_reads_timedatectl(monkeypatch):
    fake = FakeRun(CommandResult(0, "Timezone=UTC\nNTP=yes\n", "", False))
    monkeypatch.setattr(sysinfo, "run", fake)
    assert sysinfo.time_state() == ["Timezone=UTC", "NTP=yes"]
    assert fake.calls[0][0] == ["timedatectl", "show"] and fake.calls[0][1]["timeout"] <= 4
    fake.result = CommandResult(1, "", "Failed", False)
    assert sysinfo.time_state() is None
    monkeypatch.setattr(sysinfo, "run", FakeRun(error=FileNotFoundError()))
    assert sysinfo.time_state() is None


def test_journal_tail_reads_the_last_lines(monkeypatch):
    fake = FakeRun(CommandResult(0, "line one\nline two\n", "", False))
    monkeypatch.setattr(systemd, "run", fake)
    assert systemd.journal_tail("frigate.service", 50) == ["line one", "line two"]
    argv, kwargs = fake.calls[0]
    assert argv == ["journalctl", "-u", "frigate.service", "-n", "50", "--no-pager", "-o", "short-iso"]
    assert kwargs["max_output"] <= 1024 * 1024
    fake.result = CommandResult(1, "", "Failed", False)
    assert systemd.journal_tail("frigate.service", 50) is None
    monkeypatch.setattr(systemd, "run", FakeRun(error=FileNotFoundError()))
    assert systemd.journal_tail("frigate.service", 50) is None


def test_journal_tail_drops_the_line_the_output_cap_cut(monkeypatch):
    """The runner keeps the first max_output bytes, so a secret can be cut in two; its first part, which no value
    matches, mustn't reach the diagnostics text."""
    secret = "s3cr3t-0123456789abcdef"
    output = f"first line\nconnecting with {secret} failed\nlast line\n"
    monkeypatch.setattr(systemd, "JOURNAL_TAIL_MAX_OUTPUT", output.index(secret) + 6)

    def run(argv, **kwargs):  # the real runner and its cap, on printf instead of journalctl
        return command.run(["printf", "%s", output], timeout=kwargs["timeout"], max_output=kwargs["max_output"])

    monkeypatch.setattr(systemd, "run", run)
    lines = systemd.journal_tail("frigate.service", 50)
    assert lines == ["first line", systemd.JOURNAL_CUT]
    assert "s3cr3t" not in redact("\n".join(lines), [secret])


# The device checks


def test_device_checks_when_healthy(device_client, login, host):
    login(device_client, *ADMIN)
    checks = device_checks(device_client)
    assert list(checks) == ["device.storage", "device.memory", "device.temperature", "device.power"]
    assert all(check["status"] == "ok" for check in checks.values()), checks
    assert checks["device.storage"]["title"] == "Storage on /"


def test_device_checks_thresholds(device_client, login, host, monkeypatch):
    login(device_client, *ADMIN)

    host.free["/"] = 1 * GIB
    assert device_checks(device_client)["device.storage"]["status"] == "warn"
    host.free["/"] = 100 * MIB
    storage = device_checks(device_client)["device.storage"]
    assert storage["status"] == "error" and "100 MB" in storage["detail"]

    host.memory = {"total": 8 * GIB, "available": 150 * MIB}
    assert device_checks(device_client)["device.memory"]["status"] == "warn"

    host.soc_temperature_c = 84.0
    assert device_checks(device_client)["device.temperature"]["status"] == "warn"
    host.soc_temperature_c = 85.0
    assert device_checks(device_client)["device.temperature"]["status"] == "error"

    # The real parser behind the check, from vcgencmd's output
    monkeypatch.setattr(sysinfo, "throttled", THROTTLED)
    monkeypatch.setattr(sysinfo, "run", FakeRun(CommandResult(0, "throttled=0x50005\n", "", False)))
    power = device_checks(device_client)["device.power"]
    assert power["status"] == "error"
    assert "under-voltage" in power["detail"].lower() and "throttled" in power["detail"].lower()
    assert "power supply" in power["detail"]

    monkeypatch.setattr(sysinfo, "run", FakeRun(CommandResult(0, "throttled=0x50000\n", "", False)))
    assert device_checks(device_client)["device.power"]["status"] == "warn"

    error = CommandResult(255, "", "Can't open device file: /dev/vcio_gencmd\n", False)
    monkeypatch.setattr(sysinfo, "run", FakeRun(error))
    power = device_checks(device_client)["device.power"]
    assert power["status"] == "unknown" and "video group" in power["detail"]

    monkeypatch.setattr(sysinfo, "run", FakeRun(error=FileNotFoundError()))
    power = device_checks(device_client)["device.power"]
    assert power["status"] == "unknown" and "video group" not in power["detail"]


def test_device_checks_when_readings_are_missing(device_client, login, host):
    host.free = {}
    host.memory = None
    host.soc_temperature_c = None
    host.throttled = None
    login(device_client, *ADMIN)
    checks = device_checks(device_client)
    assert [check["status"] for check in checks.values()] == ["unknown"] * 4


def test_storage_shows_the_codedir_only_on_another_filesystem(device_client, login, host):
    login(device_client, *ADMIN)
    assert "device.storage.codedir" not in device_checks(device_client)
    host.filesystems[host.codedir] = 2
    host.free[host.codedir] = 1 * GIB
    checks = device_checks(device_client)
    codedir = checks["device.storage.codedir"]
    assert codedir["title"] == f"Storage on {host.codedir}" and codedir["status"] == "warn"
    assert list(checks).index("device.storage.codedir") == 1


def test_a_failing_device_check_is_titled_by_its_name(device_client, login, host):
    host.memory = RuntimeError("boom")
    login(device_client, *ADMIN)
    checks = device_checks(device_client)
    assert checks["device.memory"]["status"] == "unknown"
    assert checks["device.memory"]["title"] == "Memory"


# Diagnostics


def diagnostics(client):
    return client.get("/api/v1/system/diagnostics")


def test_diagnostics_is_admin_only_and_an_attachment(device_client, login, host):
    login(device_client, *VIEWER)
    r = diagnostics(device_client)
    assert r.status_code == 403 and r.json()["error"]["code"] == "forbidden"
    assert host.journal_calls == []

    login(device_client, *ADMIN)
    r = diagnostics(device_client)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "text/plain; charset=utf-8"
    disposition = r.headers["content-disposition"]
    assert re.fullmatch(r'attachment; filename="tm-diagnostics-[A-Za-z0-9.-]+-\d{8}-\d{6}\.txt"', disposition)
    assert r.headers["cache-control"] == "no-store"


def test_diagnostics_needs_a_login(device_client, host):
    assert diagnostics(device_client).status_code == 401


def test_diagnostics_sections(device_client, login, host):
    login(device_client, *ADMIN)
    text = diagnostics(device_client).text
    headings = re.findall(r"^== (.+) ==$", text, re.MULTILINE)
    assert headings == ["Device", "Date and time", "Status", "Services", "Manifest"] + [
        f"Journal: {unit} (last 50 lines)" for unit in INSTALLED
    ]
    assert sorted(unit for unit, _ in host.journal_calls) == sorted(INSTALLED)  # tm-control.service once
    assert all(lines == 50 for _, lines in host.journal_calls)
    assert [u.unit for u in units_for(device_client.app.state.manifest)] == INSTALLED
    assert '"model": "Raspberry Pi 5 Model B Rev 1.0"' in text
    assert "Timezone=America/Los_Angeles" in text
    assert "Storage on /" in text
    assert "frigate.service" in text.split("== Services ==")[1].split("== Manifest ==")[0]
    assert '"installing_user": "pi"' in text
    assert "tm frigate.service: line 2" in text


def test_diagnostics_says_when_a_journal_cannot_be_read(device_client, login, host):
    host.journal = lambda unit, lines: None
    host.time_state = None
    login(device_client, *ADMIN)
    r = diagnostics(device_client)
    assert r.status_code == 200
    assert "couldn't be read" in r.text


def test_diagnostics_keeps_the_hostname_safe(device_client, login, host, monkeypatch):
    monkeypatch.setattr(socket, "gethostname", lambda: 'bad host"/\r\nX: y')
    login(device_client, *ADMIN)
    r = diagnostics(device_client)
    assert r.status_code == 200
    assert 'filename="tm-diagnostics-badhostXy-' in r.headers["content-disposition"]
    assert "Device: badhostXy\n" in r.text


def test_diagnostics_never_contains_a_secret_value(device_client, login, host):
    secrets_dir = device_client.app.state.settings.secrets_dir
    for name in DEVICE_SECRETS:
        if name not in NAMES:
            (secrets_dir / name).write_text(f"test-{name}-value\n")
    values = [device_client.app.state.secrets.read(name) for name in DEVICE_SECRETS]
    assert len(values) == len(DEVICE_SECRETS) == 5
    planted = [f"connecting with {value} failed" for value in values]
    planted += ["TM_MQTT_BROKER_PASSWORD=hunter2", "Setup code: ABCD-EFGH", 'auth {"token": "tb-token-1"}']
    host.journal = lambda unit, lines: planted
    login(device_client, *ADMIN)
    r = diagnostics(device_client)
    assert r.status_code == 200
    for value in values + ["hunter2", "ABCD-EFGH", "tb-token-1"]:
        assert value not in r.text, value
    assert "<redacted>" in r.text
    assert "TM_MQTT_BROKER_PASSWORD=<redacted>" in r.text


def test_diagnostics_skips_a_secret_it_cannot_read(device_client, login, host):
    (device_client.app.state.settings.secrets_dir / "go2rtc_rtsp_password").unlink(missing_ok=True)
    login(device_client, *ADMIN)
    assert diagnostics(device_client).status_code == 200


def test_diagnostics_in_fake_mode_redacts_the_fake_secrets(claimed_client, login, monkeypatch):
    def no_run(argv, **kwargs):
        raise AssertionError(f"fake mode ran {argv}")

    monkeypatch.setattr("tm_control.adapters.sysinfo.run", no_run)
    monkeypatch.setattr("tm_control.adapters.systemd.run", no_run)
    values = [claimed_client.app.state.secrets.read(name) for name in DEVICE_SECRETS]
    monkeypatch.setattr("tm_control.fake.journal_tail", lambda unit, lines: [f"leaked {value}" for value in values])
    login(claimed_client, *ADMIN)
    r = diagnostics(claimed_client)
    assert r.status_code == 200, r.text
    assert "Device: tm-fake\n" in r.text
    for value in values:
        assert value not in r.text
    assert "leaked <redacted>" in r.text


def test_diagnostics_redacts_the_env_file_values(device_client, login, host, env_files_read):
    codedir = Path(host.codedir)
    (codedir / "node-red-tm").mkdir()
    (codedir / "frigate").mkdir()
    (codedir / "node-red-tm" / "node-red-tm.env").write_text(
        "# Broker login\n"
        "\n"
        "TM_MQTT_BROKER_USER=tm\n"
        "TM_MQTT_BROKER_PASSWORD=broker-pw-123\n"
        "NODE_RED_CREDENTIAL_SECRET='cred-secret-456'\n"
        "TM_NR_TOKEN_KEY=nr-token-key-789\n"
        "SOME_KEY=abc\n"
    )
    (codedir / "frigate" / "frigate.env").write_text("FRIGATE_GO2RTC_RTSP_PASSWORD=rtsp-pw-012\nTZ=UTC\n")
    # plate-recognizer.env is missing: skipped
    host.journal = lambda unit, lines: [
        "Connection to mqtt://tm:broker-pw-123@localhost:1883 failed",
        "credential cred-secret-456 and key nr-token-key-789 and rtsp://frigate:rtsp-pw-012@host:8554/x",
        "user tm, abc stays",
    ]
    login(device_client, *ADMIN)
    text = diagnostics(device_client).text
    for value in ("broker-pw-123", "cred-secret-456", "nr-token-key-789", "rtsp-pw-012"):
        assert value not in text, value
    assert "mqtt://tm:<redacted>@localhost:1883" in text
    assert "user tm, abc stays" in text  # not a secret's key, or too short to redact safely
    assert env_files_read == [codedir]


def test_frigate_env_defaults_do_not_hide_the_secret_after_a_key(device_client, login, host):
    """frigate.env as installed has FRIGATE_RTSP_PASSWORD=password, so "password" is a value to redact; it mustn't
    break the key pattern that catches the real secret."""
    (Path(host.codedir) / "frigate").mkdir()
    (Path(host.codedir) / "frigate" / "frigate.env").write_text(
        "FRIGATE_RTSP_PASSWORD=password\nFRIGATE_MQTT_PASSWORD=mqtt_pass\n"
    )
    host.journal = lambda unit, lines: ["password=hunter2", '{"password": "hunter2"}', "mqtt_password: hunter2"]
    login(device_client, *ADMIN)
    text = diagnostics(device_client).text
    assert "hunter2" not in text
    assert "<redacted>" in text


def test_diagnostics_tests_read_no_real_env_files(device_client, login, host, env_files_read, tmp_path):
    login(device_client, *ADMIN)
    assert diagnostics(device_client).status_code == 200
    assert env_files_read and all(path.is_relative_to(tmp_path) for path in env_files_read)


def test_device_secrets_match_the_role():
    role_vars = YAML(typ="safe", pure=True).load(REPO / "script/ansible/roles/tmsetup/vars/main.yml")
    assert list(DEVICE_SECRETS) == role_vars["tmsetup_secret_names"]
    assert set(NAMES) <= set(DEVICE_SECRETS)


# Reboot and power off


def recording(app, events):
    """The app, wrapped so that each response's start is recorded in `events` as it's sent."""

    async def wrapped(scope, receive, send):
        async def send_and_record(message):
            if message["type"] == "http.response.start":
                events.append(("response", message["status"]))
            await send(message)

        await app(scope, receive, send_and_record)

    return wrapped


LOGIND = ["busctl", "call", "org.freedesktop.login1", "/org/freedesktop/login1", "org.freedesktop.login1.Manager"]
POWER = [
    ("reboot", ["systemctl", "reboot"], "CanReboot", "system.reboot"),
    ("power-off", ["systemctl", "poweroff"], "CanPowerOff", "system.power_off"),
]


class Logind:
    """Stands in for command.run: answers logind's Can* from `answer` and records every argv."""

    def __init__(self, answer=CommandResult(0, 's "yes"\n', "", False), systemctl_rc=0, events=None):
        self.answer, self.systemctl_rc = answer, systemctl_rc
        self.events = [] if events is None else events

    def __call__(self, argv, **kwargs):
        self.events.append(("run", list(argv)))
        if argv[:1] == ["busctl"]:
            assert 0 < kwargs["timeout"] <= 4
            if isinstance(self.answer, Exception):
                raise self.answer
            return self.answer
        return CommandResult(self.systemctl_rc, "", "synthetic-stderr-detail" if self.systemctl_rc else "", False)

    def queued(self):
        return [argv for kind, argv in self.events if kind == "run" and argv[0] == "systemctl"]


@pytest.mark.parametrize("path, argv, method, action", POWER)
def test_reboot_and_power_off_are_admin_only_audited_and_queued(device_client, login, monkeypatch, path, argv,
                                                                method, action):
    events = []
    monkeypatch.setattr(systemd, "run", Logind(events=events))
    client = TestClient(recording(device_client.app, events), base_url=BASE)
    login(client, *VIEWER)
    r = client.post(f"/api/v1/system/{path}", json={}, headers=ORIGIN)
    assert r.status_code == 403 and r.json()["error"]["code"] == "forbidden"
    assert not [event for event in events if event[0] == "run"]

    login(client, *ADMIN)
    events.clear()
    r = client.post(f"/api/v1/system/{path}", json={}, headers=ORIGIN)
    assert r.status_code == 202, r.text
    assert r.json() == {"action": action.removeprefix("system.")}
    assert events == [("run", LOGIND + [method]), ("response", 202), ("run", argv)]
    assert (action, None) in audit_rows(device_client)


@pytest.mark.parametrize("path, argv, method, action", POWER)
@pytest.mark.parametrize(
    "answer",
    [
        CommandResult(0, 's "challenge"\n', "", False),
        CommandResult(0, 's "na"\n', "", False),
        CommandResult(1, "", "Call failed: synthetic-busctl-detail", False),
        CommandResult(-9, "", "", True),
        FileNotFoundError(2, "No such file or directory"),
    ],
)
def test_reboot_and_power_off_refused_while_logind_says_no(device_client, login, monkeypatch, path, argv, method,
                                                           action, answer):
    """An inhibitor (an update, say) or anything but a plain yes: 409 before the 202, nothing queued, no audit."""
    logind = Logind(answer=answer)
    monkeypatch.setattr(systemd, "run", logind)
    login(device_client, *ADMIN)
    r = device_client.post(f"/api/v1/system/{path}", json={}, headers=ORIGIN)
    assert r.status_code == 409, r.text
    error = r.json()["error"]
    assert error["code"] == "conflict"
    assert "try again in a few minutes" in error["message"].lower()
    assert "synthetic-busctl-detail" not in r.text and "challenge" not in r.text
    assert logind.queued() == []
    assert not [row for row in audit_rows(device_client) if row[0] == action]


def test_reboot_needs_a_session(device_client, monkeypatch):
    logind = Logind()
    monkeypatch.setattr(systemd, "run", logind)
    assert device_client.post("/api/v1/system/reboot", json={}, headers=ORIGIN).status_code == 401
    assert logind.events == []


def test_a_failed_reboot_is_logged_without_its_output(device_client, login, monkeypatch, caplog):
    monkeypatch.setattr(systemd, "run", Logind(systemctl_rc=1))
    login(device_client, *ADMIN)
    r = device_client.post("/api/v1/system/reboot", json={}, headers=ORIGIN)
    assert r.status_code == 202
    assert "systemctl reboot failed" in caplog.text
    assert "synthetic-stderr-detail" not in caplog.text


def test_fake_mode_reboots_nothing(claimed_client, login, monkeypatch):
    def no_run(argv, **kwargs):
        raise AssertionError(f"fake mode ran {argv}")

    monkeypatch.setattr(systemd, "run", no_run)
    monkeypatch.setattr(subprocess, "Popen", no_run)
    login(claimed_client, *ADMIN)
    for path, action in (("reboot", "system.reboot"), ("power-off", "system.power_off")):
        r = claimed_client.post(f"/api/v1/system/{path}", json={}, headers=ORIGIN)
        assert r.status_code == 202, r.text
        assert (action, None) in audit_rows(claimed_client)


def test_openapi_declares_the_system_models(client):
    document = client.app.openapi()
    paths = document["paths"]
    info = paths["/api/v1/system/info"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    assert info == {"$ref": "#/components/schemas/SystemInfo"}
    assert "text/plain" in paths["/api/v1/system/diagnostics"]["get"]["responses"]["200"]["content"]
    for path in ("/api/v1/system/reboot", "/api/v1/system/power-off"):
        queued = paths[path]["post"]["responses"]["202"]["content"]["application/json"]["schema"]
        assert queued["$ref"].startswith("#/components/schemas/")
    assert set(document["components"]["schemas"]["SystemInfo"]["properties"]) == {
        "hostname", "serial", "model", "os", "kernel", "uptime_seconds", "memory", "disks", "tm", "components",
        "soc_temperature_c", "throttled",
    }
