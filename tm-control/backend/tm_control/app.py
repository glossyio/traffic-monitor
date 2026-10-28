"""The tm-control web app: the FastAPI app behind nginx on 127.0.0.1:8090 (`tm-control serve`)."""

from fastapi import FastAPI, Request

from tm_control import modules
from tm_control.core.errors import install_error_handlers
from tm_control.core.manifest import load_manifest
from tm_control.core.secrets import NAMES, FakeSecrets, Secrets
from tm_control.core.settings import Settings
from tm_control.core.state import State

API_PREFIX = "/api/v1"


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the app. Fails at startup, not on the first request, if the state, a secret, or the manifest is bad."""
    settings = settings or Settings.from_env()
    settings.state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    state = State(settings.state_dir / "state.sqlite")
    state.migrate()
    if settings.fake:
        secrets = FakeSecrets()
    else:
        secrets = Secrets(settings.secrets_dir)
        for name in NAMES:
            secrets.read(name)
    manifest = load_manifest(settings.manifest_path)

    # The interactive docs only in fake mode; `app.openapi()` works either way.
    app = FastAPI(
        title="tm-control",
        version=manifest.tm_version,
        openapi_url=f"{API_PREFIX}/openapi.json" if settings.fake else None,
        docs_url=f"{API_PREFIX}/docs" if settings.fake else None,
        redoc_url=None,
    )
    app.state.settings = settings
    app.state.state = state
    app.state.secrets = secrets
    app.state.manifest = manifest
    install_error_handlers(app)

    @app.get(f"{API_PREFIX}/health")
    def health(request: Request):
        return {"status": "ok", "version": request.app.state.manifest.tm_version}

    for module in modules.MODULES:
        app.include_router(module.router, prefix=API_PREFIX)
        if module.root_router is not None:
            app.include_router(module.root_router)
    return app
