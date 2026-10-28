import dataclasses
import shutil
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
def device_client(settings):
    """A client for an app built as on a device (fake=False), so its real code paths run; patch what they call.

    Its secrets are synthetic files (test-<name>-value) and its manifest the fixture's. The device is claimed by
    admin/correct horse 1 and has a viewer, viewer/viewer pass 1; log in with `login`. Not logged in.
    """
    settings = dataclasses.replace(settings, fake=False)
    settings.secrets_dir.mkdir(mode=0o700, parents=True)
    for name in NAMES:
        path = settings.secrets_dir / name
        path.write_text(f"test-{name}-value\n")
        path.chmod(0o600)
    client = TestClient(create_app(settings), base_url="http://tm-test.local")
    state = client.app.state.state
    Device(state).claim(ADMIN, ADMIN_PASSWORD, load_eula(settings.eula_path).version)
    Users(state).create(VIEWER, VIEWER_PASSWORD, "viewer")
    return client
