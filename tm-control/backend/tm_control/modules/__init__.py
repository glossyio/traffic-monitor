"""tm-control's feature modules. Each one adds a Module to MODULES; create_app mounts their routers."""

from dataclasses import dataclass

from fastapi import APIRouter


@dataclass(frozen=True)
class Module:
    id: str
    router: APIRouter  # mounted under /api/v1
    root_router: APIRouter | None = None  # mounted at the app root, for the few non-API paths such as GET /logout


# The modules import Module from here, so they come after it.
from tm_control.modules import auth  # noqa: E402

MODULES: list[Module] = [auth.module]
