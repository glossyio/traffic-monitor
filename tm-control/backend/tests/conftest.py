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
from tm_control.core.auth import Device  # noqa: E402
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
    )


@pytest.fixture
def client(settings):
    return TestClient(create_app(settings), base_url="http://tm-test.local")


ORIGIN = "http://tm-test.local"  # what a browser on the client's base URL sends; TestClient sends no Origin itself
ADMIN, ADMIN_PASSWORD = "admin", "correct horse 1"


@pytest.fixture
def claimed_client(client, settings):
    """The client, after its device was claimed by admin/correct horse 1 with the current EULA. Not logged in."""
    Device(client.app.state.state).claim(ADMIN, ADMIN_PASSWORD, load_eula(settings.eula_path).version)
    return client


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
