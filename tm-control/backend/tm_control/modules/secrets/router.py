"""GET /secrets, POST /secrets/{name}, and DELETE /secrets/{name}: the entered secrets an admin types in on the Device
page. Setting or removing one starts the set-secret root job, which writes the secret's file, rewrites the env lines
that carry it, and restarts the units that read them; the UI polls GET /jobs/{id} for the outcome.

No value is ever logged, audited, or answered: GET says only whether a secret is set and, for the tokens, its last four
characters, and a refusal names the rule, not what was sent.
"""

import re
from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Request
from pydantic import BaseModel, Field

from tm_control.core.auth import Audit, User
from tm_control.core.errors import ApiError
from tm_control.core.secrets import (
    FRIGATE_PLUS_API_KEY,
    PLATE_RECOGNIZER_LICENSE_KEY,
    PLATE_RECOGNIZER_TOKEN,
    THINGSBOARD_ACCESS_TOKEN,
    VALUE_PATTERNS,
)
from tm_control.modules.auth.deps import require_admin

router = APIRouter(prefix="/secrets", tags=["secrets"])


@dataclass(frozen=True)
class EnteredSecret:
    title: str
    pattern: re.Pattern  # the whole value must match
    shows_ending: bool  # whether GET /secrets shows the value's last four characters
    message: str  # the pattern in words, for a refused value
    restarts: tuple[str, ...]  # the units the job restarts, in order; the job's own table must agree
    option: str | None  # the manifest option that installs what reads it; None for always


PLATE_RECOGNIZER_MESSAGE = "A Plate Recognizer value is 1 to 256 printable characters with no spaces."

# In the order the Device page lists them.
ENTERED: dict[str, EnteredSecret] = {
    THINGSBOARD_ACCESS_TOKEN: EnteredSecret(
        title="ThingsBoard access token",
        pattern=re.compile(VALUE_PATTERNS[THINGSBOARD_ACCESS_TOKEN]),
        shows_ending=True,
        message="A ThingsBoard access token is 1 to 256 letters, digits, dots, dashes, underscores, or tildes.",
        restarts=("node-red-tm.service",),
        option=None,
    ),
    FRIGATE_PLUS_API_KEY: EnteredSecret(
        title="Frigate+ API key",
        pattern=re.compile(VALUE_PATTERNS[FRIGATE_PLUS_API_KEY]),
        shows_ending=True,
        message=(
            "A Frigate+ API key is 36 characters, a colon, and 40 lowercase letters or digits, as Frigate+ shows it."
        ),
        restarts=("frigate.service",),
        option=None,
    ),
    PLATE_RECOGNIZER_TOKEN: EnteredSecret(
        title="Plate Recognizer API token",
        pattern=re.compile(VALUE_PATTERNS[PLATE_RECOGNIZER_TOKEN]),
        shows_ending=True,
        message=PLATE_RECOGNIZER_MESSAGE,
        restarts=("plate-recognizer.service", "node-red-tm.service"),
        option="plate_recognizer",
    ),
    PLATE_RECOGNIZER_LICENSE_KEY: EnteredSecret(
        title="Plate Recognizer license key",
        pattern=re.compile(VALUE_PATTERNS[PLATE_RECOGNIZER_LICENSE_KEY]),
        shows_ending=False,
        message=PLATE_RECOGNIZER_MESSAGE,
        restarts=("plate-recognizer.service",),
        option="plate_recognizer",
    ),
}


class SecretState(BaseModel):
    name: str
    title: str
    set: bool
    ends_with: str | None  # the last four characters, for a secret that shows them, is set, and is 12 or more long
    restarts: list[str]


class SecretsState(BaseModel):
    secrets: list[SecretState]


class SecretValue(BaseModel):
    value: str = Field(max_length=1024)


def _available(app_state, secret: EnteredSecret) -> bool:
    return secret.option is None or bool(app_state.manifest.options.get(secret.option, False))


def _entered(app_state, name: str) -> EnteredSecret:
    """The secret by name, if this install has what reads it; 404 otherwise, the same for a name that isn't one."""
    secret = ENTERED.get(name)
    if secret is None or not _available(app_state, secret):
        raise ApiError(404, "not_found", "There is no such secret.")
    return secret


def _start(request: Request, admin: User, name: str, value: str, action: str) -> dict:
    app_state = request.app.state
    job = app_state.jobs.start("set-secret", {"name": name, "value": value}, admin.id)
    Audit(app_state.state).record(admin.id, action, detail=name)
    if app_state.settings.fake:
        app_state.secrets.entered[name] = value  # so the page shows the change, as the job's file write would
    return {"id": job.id}


@router.get("", response_model=SecretsState)
def get_secrets(request: Request, admin: User = Depends(require_admin)):
    app_state = request.app.state
    secrets = app_state.secrets
    states = []
    for name, secret in ENTERED.items():
        if not _available(app_state, secret):
            continue
        is_set = secrets.is_set(name)
        states.append(SecretState(
            name=name,
            title=secret.title,
            set=is_set,
            ends_with=secrets.ends_with(name) if secret.shows_ending and is_set else None,
            restarts=list(secret.restarts),
        ))
    return SecretsState(secrets=states)


@router.post("/{name}", status_code=202)
def set_secret(
    name: Annotated[str, Path(max_length=64)], body: SecretValue, request: Request,
    admin: User = Depends(require_admin),
):
    """Start the job that writes the secret and restarts what reads it."""
    secret = _entered(request.app.state, name)
    if not body.value.strip():
        raise ApiError(422, "validation", "Enter a value, or leave this as it is.")
    if secret.pattern.fullmatch(body.value) is None:
        raise ApiError(422, "validation", secret.message)
    return _start(request, admin, name, body.value, "secrets.set")


@router.delete("/{name}", status_code=202)
def remove_secret(name: Annotated[str, Path(max_length=64)], request: Request, admin: User = Depends(require_admin)):
    """Start the job that empties the secret's file and restarts what reads it. For one not set, the job still writes
    the empty value and its env lines and restarts the units."""
    _entered(request.app.state, name)
    return _start(request, admin, name, "", "secrets.removed")
