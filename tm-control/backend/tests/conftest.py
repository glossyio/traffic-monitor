import dataclasses
import json
import shutil
import signal
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

FIXTURES = Path(__file__).resolve().parent / "fixtures"

# These need BACKEND_DIR on sys.path.
from fastapi.testclient import TestClient  # noqa: E402

import tm_control  # noqa: E402
from tm_control.app import create_app  # noqa: E402
from tm_control.core.auth import Device, SetupCode, Users  # noqa: E402
from tm_control.core.secrets import NAMES  # noqa: E402
from tm_control.core.settings import Settings  # noqa: E402
from tm_control.modules.setup.eula import load_eula  # noqa: E402


@pytest.fixture
def prompt():
    """Fail a test that blocks for more than five seconds, as opening a FIFO without a writer would."""

    def expired(signum, frame):
        pytest.fail("blocked for five seconds")  # not an OSError, which the code under test may catch

    previous = signal.signal(signal.SIGALRM, expired)
    signal.alarm(5)
    yield
    signal.alarm(0)
    signal.signal(signal.SIGALRM, previous)


@pytest.fixture(params=["frigate_config_v0.17.yml", "frigate_config_v0.18.yml"])
def frigate_config(request, tmp_path):
    """A copy of Frigate's config.yml as tmsetup rendered it before go2rtc RTSP credentials (synthetic).

    v0.17 is from before Frigate 0.18 (#220), with a Coral USB; v0.18 is from after, with the CPU detector (#222).
    """
    (tmp_path / "config").mkdir()
    path = tmp_path / "config" / "config.yml"
    shutil.copy(FIXTURES / request.param, path)
    path.chmod(0o640)
    return path


@pytest.fixture
def settings(tmp_path):
    """Settings for an isolated backend: temp state and runtime dirs, fake secrets, the fixture manifest."""
    return Settings(
        state_dir=tmp_path / "state",
        runtime_dir=tmp_path / "run",
        secrets_dir=tmp_path / "secrets",
        manifest_path=FIXTURES / "manifest.json",
        host="127.0.0.1",
        port=0,
        fake=True,
        eula_path=Path(tm_control.__file__).parent / "modules" / "setup" / "EULA.md",
        setup_code_file=tmp_path / "etc" / "setup-code",
        network_run_dir=tmp_path / "network-run",
    )


@pytest.fixture
def client(settings):
    return TestClient(create_app(settings), base_url="http://tm-test.local")


ORIGIN = "http://tm-test.local"  # what a browser on the client's base URL sends; TestClient sends no Origin itself
ADMIN, ADMIN_PASSWORD = "admin", "correct horse 1"
VIEWER, VIEWER_PASSWORD = "viewer", "viewer pass 1"


@pytest.fixture
def claimed_client(client, settings):
    """The client, after its device was claimed by admin/correct horse 1 with the current EULA. Not logged in."""
    Device(client.app.state.state).claim(ADMIN, ADMIN_PASSWORD, load_eula(settings.eula_path).version)
    return client


@pytest.fixture
def setup_code(client):
    """A new setup code whose hash the client's unclaimed device holds, as tmsetup's set-setup-code leaves it."""
    code = SetupCode.generate()
    Device(client.app.state.state).set_setup_code_hash(SetupCode.hash_code(code))
    return code


@pytest.fixture
def login():
    """login(client, username, password) logs the client in (its cookie jar keeps the cookie) and returns the cookie."""

    def login(client, username, password):
        r = client.post(
            "/api/v1/auth/login", json={"username": username, "password": password}, headers={"Origin": ORIGIN}
        )
        assert r.status_code == 200, r.text
        return r.cookies["tm_session"]

    return login


@pytest.fixture
def device_client(settings, monkeypatch):
    """A client for an app built as on a device (fake=False), so its real code paths run; patch what they call.

    Its secrets are synthetic files (test-<name>-value) and its manifest the fixture's. The device is claimed by
    admin/correct horse 1 and has a viewer, viewer/viewer pass 1; log in with `login`. Not logged in.

    The apps (Frigate, Node-RED, go2rtc, the broker) don't answer a GET or a POST and config.yml is missing, so a
    status report doesn't reach whatever runs on this machine's ports or read its files; the `apps` fixture answers
    for them.
    Likewise the hardware: no USB ids or PCI listing, device paths, unit files, kernel modules, media devices, or
    node-red-tm.env (test_hardware_checks.FakeHardware stands in for them). timedatectl fails, so the time check is
    unknown (test_api_time.FakeTimedatectl stands in for it). nmcli and iw fail, so the network checks are unknown
    (test_network_checks.FakeNetwork stands in for them).
    """
    from tm_control.adapters import hardware, httpjson, mqtt, network, nodered, timedate
    from tm_control.adapters.command import CommandResult

    monkeypatch.setattr(httpjson, "get", lambda url, headers=None, timeout=None: (None, None))
    monkeypatch.setattr(httpjson, "post", lambda url, body, content_type, headers=None, timeout=None: (None, None))
    monkeypatch.setattr(mqtt, "run", lambda argv, **kwargs: CommandResult(1, "", "", False))
    monkeypatch.setattr(nodered, "config", lambda codedir: nodered.ConfigRead(None, "missing"))
    monkeypatch.setattr(hardware, "run", lambda argv, **kwargs: CommandResult(1, "", "", False))
    monkeypatch.setattr(hardware, "path_exists", lambda path: False)
    monkeypatch.setattr(hardware, "USB_DEVICES", settings.state_dir / "no-usb")
    monkeypatch.setattr(hardware, "UNIT_DIR", settings.state_dir / "no-units")
    monkeypatch.setattr(hardware, "PROC_MODULES", settings.state_dir / "no-modules")
    monkeypatch.setattr(hardware, "MEDIA_DEVICES", settings.state_dir / "no-media")
    monkeypatch.setattr(hardware, "radar_ports", lambda codedir: None)
    monkeypatch.setattr(timedate, "run", lambda argv, **kwargs: CommandResult(1, "", "", False))
    monkeypatch.setattr(network, "run", lambda argv, **kwargs: CommandResult(1, "", "", False))
    monkeypatch.setattr(network, "radio_kind", lambda device, sys_net=None: "builtin")
    settings = dataclasses.replace(settings, fake=False)
    settings.secrets_dir.mkdir(mode=0o700, parents=True)
    for name in NAMES:
        path = settings.secrets_dir / name
        path.write_text(f"test-{name}-value\n")
        path.chmod(0o600)
    client = TestClient(create_app(settings), base_url="http://tm-test.local")
    # Node-RED's config.yml and the tmdb backups as on a device would be under the manifest's codedir, which a status
    # report's reconcile reads: point them at paths that don't exist instead.
    client.app.state.config_path = settings.state_dir.parent / "no-node-red" / "config.yml"
    client.app.state.backup_dir = settings.state_dir.parent / "no-backup"
    state = client.app.state.state
    Device(state).claim(ADMIN, ADMIN_PASSWORD, load_eula(settings.eula_path).version)
    Users(state).create(VIEWER, VIEWER_PASSWORD, "viewer")
    return client


FRIGATE_API = "http://127.0.0.1:5000/api"
NODE_RED_STATUS = "http://127.0.0.1:1880/tm-internal/status"
GO2RTC_STREAMS = "http://127.0.0.1:1984/api/streams"


class FakeApps:
    """The apps on a device as the apps adapters see them, from the synthetic fixtures: each URL's HTTP answer, ss's
    listening sockets, and a code directory with Node-RED's and Frigate's config.yml and the tmdb migrations.

    Change `answers` (URL -> (status, body bytes), or (None, None) for no answer), `ss`, the files, or
    `secrets.entered`, then call `context()` for a new report's Context. `requests` lists every (url, headers) asked
    for.
    """

    def __init__(self, codedir: Path):
        from tm_control.core.secrets import FakeSecrets

        self.codedir = codedir
        self.secrets = FakeSecrets()
        self.answers = {
            f"{FRIGATE_API}/version": (200, b"0.18.1-cf67f08"),
            f"{FRIGATE_API}/config": (200, (FIXTURES / "frigate_api_config.json").read_bytes()),
            f"{FRIGATE_API}/stats": (200, (FIXTURES / "frigate_api_stats.json").read_bytes()),
            NODE_RED_STATUS: (200, (FIXTURES / "nodered_status.json").read_bytes()),
            GO2RTC_STREAMS: (200, (FIXTURES / "go2rtc_streams.json").read_bytes()),
        }
        self.requests: list[tuple[str, dict]] = []
        self.ss = "LISTEN 0      4096       127.0.0.1:1883      0.0.0.0:*\n"
        self.config_yml = codedir / "node-red-tm" / "config" / "config.yml"
        self.config_yml.parent.mkdir(parents=True)
        shutil.copy(FIXTURES / "node_red_config_ok.yml", self.config_yml)
        self.frigate_config_yml = codedir / "frigate" / "config" / "config.yml"  # the CPU detector's: no model section
        self.frigate_config_yml.parent.mkdir(parents=True)
        shutil.copy(FIXTURES / "frigate_config_v0.18.yml", self.frigate_config_yml)
        self.migrations = codedir / "node-red-tm" / "schema" / "migrations"
        self.migrations.mkdir(parents=True)
        (self.migrations / "0001_baseline.sql").write_text("-- synthetic\n")

    def get(self, url, headers=None, timeout=None):
        self.requests.append((url, dict(headers or {})))
        return self.answers.get(url, (None, None))

    def json(self, url, value):
        self.answers[url] = (200, json.dumps(value).encode())

    def edit_json(self, url, edit):
        """Answer url with its current JSON body after edit(body) changed it in place."""
        body = json.loads(self.answers[url][1])
        edit(body)
        self.json(url, body)

    def edit_config_yml(self, edit):
        """Rewrite config.yml after edit(data) changed its parsed content in place."""
        from ruamel.yaml import YAML

        yaml = YAML(typ="safe", pure=True)
        data = yaml.load(self.config_yml.read_text())
        edit(data)
        with self.config_yml.open("w") as handle:
            yaml.dump(data, handle)

    def asked(self, url) -> int:
        return sum(1 for asked, _ in self.requests if asked == url)

    def context(self, state=None):
        from tm_control.core.checks import Context
        from tm_control.core.manifest import load_manifest

        manifest = load_manifest(FIXTURES / "manifest.json").model_copy(update={"codedir": str(self.codedir)})
        return Context(settings=None, manifest=manifest, secrets=self.secrets, state=state)


@pytest.fixture
def apps(tmp_path, monkeypatch):
    """FakeApps in place of the apps adapters' HTTP reads and ss; the MQTT probe itself isn't replaced."""
    from tm_control.adapters import httpjson, mqtt
    from tm_control.adapters.command import CommandResult

    fake = FakeApps(tmp_path / "codedir")
    monkeypatch.setattr(httpjson, "get", fake.get)
    monkeypatch.setattr(mqtt, "run", lambda argv, **kwargs: CommandResult(0, fake.ss, "", False))
    return fake
