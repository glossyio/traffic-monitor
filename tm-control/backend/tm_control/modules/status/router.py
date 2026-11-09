"""GET /status, the report of every module's check groups (any user), and POST /status/rescan (admins), which runs
the checks again instead of returning the cached report."""

from fastapi import APIRouter, Depends, Request

from tm_control.core.auth import Audit, User
from tm_control.core.checks import Report
from tm_control.modules.auth.deps import current_user, require_admin

router = APIRouter(prefix="/status", tags=["status"])


@router.get("", response_model=Report)
def status(request: Request, user: User = Depends(current_user)):
    return request.app.state.status.report()


@router.post("/rescan", response_model=Report)
def rescan(request: Request, admin: User = Depends(require_admin)):
    Audit(request.app.state.state).record(admin.id, "status.rescan")
    return request.app.state.status.report(force=True)
