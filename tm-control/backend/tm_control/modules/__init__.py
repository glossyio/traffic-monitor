"""tm-control's feature modules. Each one adds a Module to MODULES; create_app mounts their routers."""

from dataclasses import dataclass

from fastapi import APIRouter

from tm_control.core.checks import CheckGroup


@dataclass(frozen=True)
class Module:
    id: str
    router: APIRouter  # mounted under /api/v1
    root_router: APIRouter | None = None  # mounted at the app root, for the few non-API paths such as GET /logout
    check_groups: tuple[CheckGroup, ...] = ()  # in the status report, in MODULES order


# The modules import Module from here, so they come after it.
from tm_control.modules import account, auth, jobs, services, setup, status, system  # noqa: E402

MODULES: list[Module] = [
    auth.module,
    setup.module,
    account.module,
    jobs.module,
    status.module,
    services.module,
    system.module,
]
