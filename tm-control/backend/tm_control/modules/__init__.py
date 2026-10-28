"""tm-control's feature modules. Each one adds a Module to MODULES; create_app mounts their routers."""

from dataclasses import dataclass

from fastapi import APIRouter


@dataclass(frozen=True)
class Module:
    id: str
    router: APIRouter  # mounted under /api/v1
    root_router: APIRouter | None = None  # mounted at the app root, for the few non-API paths such as GET /logout


MODULES: list[Module] = []
