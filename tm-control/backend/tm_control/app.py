"""The tm-control web app: the FastAPI app behind nginx on 127.0.0.1:8090 (`tm-control serve`)."""

from fastapi import FastAPI, Request

from tm_control import modules
from tm_control.core.auth import Backoff, NodeRedToken, Sessions
from tm_control.core.csrf import CsrfMiddleware
from tm_control.core.errors import install_error_handlers
from tm_control.core.manifest import load_manifest
from tm_control.core.secrets import NAMES, FakeSecrets, Secrets
from tm_control.core.settings import Settings
from tm_control.core.state import State
from tm_control.modules.setup.eula import load_eula

API_PREFIX = "/api/v1"


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the app. A bad state, secret, manifest, or EULA fails it at startup, not on the first request."""
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
    eula = load_eula(settings.eula_path)

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
    app.state.eula = eula
    app.state.sessions = Sessions(secrets.session_key)
    app.state.nr_token = NodeRedToken(secrets.node_red_token_key)
    app.state.login_backoff = Backoff()
    app.state.claim_backoff = Backoff()  # wrong setup codes, per IP; kept apart so neither holds up the other
    install_error_handlers(app)
    app.add_middleware(CsrfMiddleware)

    @app.get(f"{API_PREFIX}/health")
    def health(request: Request):
        return {"status": "ok", "version": request.app.state.manifest.tm_version}

    for module in modules.MODULES:
        app.include_router(module.router, prefix=API_PREFIX)
        if module.root_router is not None:
            app.include_router(module.root_router)
    return app
