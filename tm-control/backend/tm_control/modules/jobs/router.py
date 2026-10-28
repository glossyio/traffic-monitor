"""GET /jobs/{id}: a root job's status and the lines its run logged (core/jobs.py). Admins only."""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Request

from tm_control.core.auth import User
from tm_control.core.errors import ApiError
from tm_control.core.jobs import Job
from tm_control.modules.auth.deps import require_admin

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("/{job_id}", response_model=Job)
def get_job(job_id: Annotated[str, Path(max_length=64)], request: Request, admin: User = Depends(require_admin)):
    job = request.app.state.jobs.get(job_id)
    if job is None:
        raise ApiError(404, "not_found", "There is no such job.")
    return job
