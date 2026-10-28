import dataclasses

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient
from pydantic import BaseModel

from tm_control.app import create_app
from tm_control.cli import main
from tm_control.core.errors import ApiError
from tm_control.core.secrets import MissingSecret
from tm_control.core.state import MIGRATIONS, State
from tm_control.modules import Module


def test_health_reports_the_manifest_version(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200 and r.json() == {"status": "ok", "version": "0.7.1-test"}


def test_errors_use_one_shape(client):
    r = client.get("/api/v1/nope")
    assert r.status_code == 404 and set(r.json()["error"]) == {"code", "message", "detail"}
    assert r.json()["error"]["code"] == "not_found"


def test_method_not_allowed_uses_the_shape(client):
    r = client.post("/api/v1/health", json={}, headers={"Origin": "http://tm-test.local"})  # passes the CSRF check
    assert r.status_code == 405 and r.json()["error"]["code"] == "method_not_allowed"


def test_app_creates_and_migrates_the_state(settings):
    create_app(settings)
    assert State(settings.state_dir / "state.sqlite").version() == len(MIGRATIONS)


def test_app_without_fake_mode_needs_the_secrets(settings):
    with pytest.raises(MissingSecret):
        create_app(dataclasses.replace(settings, fake=False))


def test_module_routers_mount_and_render_errors(settings, monkeypatch):
    class Body(BaseModel):
        password: str

    router, root_router = APIRouter(), APIRouter()

    @router.get("/thing")
    def thing():
        raise ApiError(409, "conflict", "already there", detail={"id": 1})

    @router.post("/thing")
    def make_thing(body: Body):
        return {}

    @root_router.get("/logout")
    def logout():
        return {"bye": True}

    monkeypatch.setattr("tm_control.modules.MODULES", [Module("thing", router, root_router)])
    client = TestClient(create_app(settings), base_url="http://tm-test.local")

    assert client.get("/api/v1/thing").json() == {
        "error": {"code": "conflict", "message": "already there", "detail": {"id": 1}}
    }
    assert client.get("/api/v1/thing").status_code == 409
    assert client.get("/logout").json() == {"bye": True}

    r = client.post(
        "/api/v1/thing",
        json={"password": 12345, "other": "placeholder-password"},
        headers={"Origin": "http://tm-test.local"},
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation"
    assert "placeholder-password" not in r.text and "12345" not in r.text


def test_unhandled_errors_use_the_shape(settings, monkeypatch):
    router = APIRouter()

    @router.get("/boom")
    def boom():
        raise RuntimeError("placeholder-internal-detail")

    monkeypatch.setattr("tm_control.modules.MODULES", [Module("boom", router)])
    client = TestClient(create_app(settings), base_url="http://tm-test.local", raise_server_exceptions=False)
    r = client.get("/api/v1/boom")
    assert r.status_code == 500 and r.json()["error"]["code"] == "internal"
    assert "placeholder-internal-detail" not in r.text


def test_serve_is_a_cli_command():
    with pytest.raises(SystemExit) as e:
        main(["serve", "--help"])
    assert e.value.code == 0
