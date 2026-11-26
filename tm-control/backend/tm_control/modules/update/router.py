"""The Software update API: what is installed and what the last check found, a check against GitHub (the one place
this app goes online for an update), the start of an update, and the run's log. Admins only.

GET /update never goes online and never fails because GitHub or systemd can't be asked: it reads the state file, the two
units, and what this app kept in memory (the last check's offer, and the start it made). POST /update/start accepts
only the offer the last check made, if it is ahead, or a retry of the last run's target. The root job does its own
checks again; the ones here are the page's.

In fake mode every route asks `app.state.fake_update` instead of the files, the units, and GitHub.
"""

import math
import re
import threading
import time
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from tm_control.adapters.github import GithubError
from tm_control.core.auth import Audit, User
from tm_control.core.checks import Check
from tm_control.core.errors import ApiError
from tm_control.modules.auth.deps import require_admin
from tm_control.modules.system import diagnostics
from tm_control.modules.update import logs
from tm_control.modules.update import offer as offers
from tm_control.modules.update import run as runs
from tm_control.modules.update.checks import before_start
from tm_control.modules.update.offer import Offer
from tm_control.modules.update.run import JOB_UNIT, RESUME_UNIT, Run
from tm_control.modules.update.source import repo_of

router = APIRouter(prefix="/update", tags=["update"])

CHECK_SPACING = 60  # seconds between two checks of GitHub
LOG_LINES = 400
LOG_CAP = 512 * 1024  # bytes read from the log's end
JOURNAL_LINES = 50
BUSY = "75"  # the job's exit status when another update holds the lock

_clock = time.monotonic
_COMMIT = re.compile(r"[0-9a-f]{40}")
_TAG = re.compile(r"v[0-9]{1,9}\.[0-9]{1,9}\.[0-9]{1,9}")
_CODE = re.compile(r"[a-z0-9_]{1,50}")
_CHANNELS = ("stable", "development")

STALE_MESSAGE = "That isn't the version the last check found. Check again."
RUNNING_MESSAGE = "An update is already running."
NOT_READY_MESSAGE = "This unit can't be updated yet. The checks say why."
NO_SOURCE_MESSAGE = "This unit doesn't record where its updates come from, so it can't look for one."
OFFLINE_MESSAGE = "GitHub could not be reached. Check the unit's internet connection and try again."
ANSWER_MESSAGE = "GitHub gave an answer this version doesn't understand. Try again later."
LIMITED_MESSAGE = "GitHub is limiting requests from this network. Try again later."
TOO_SOON_MESSAGE = "A check was made a moment ago. Wait a little before checking again."


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Installed(BaseModel):
    version: str
    channel: str
    commit: str
    modified: bool
    source_known: bool


class Started(BaseModel):
    run_id: str
    status: Literal["starting", "failed"]
    reason: str | None  # failed: "busy" (another update holds the lock) or "error"


class Target(BaseModel):
    channel: str
    commit: str


class UpdateState(BaseModel):
    installed: Installed
    offer: Offer | None
    checks: list[Check]
    can_start: bool
    run: Run | None
    started: Started | None
    retry: Target | None


class CheckRequest(BaseModel):
    channel: Literal["stable", "development"]


class StartRequest(BaseModel):
    channel: Literal["stable", "development"]
    commit: str = Field(pattern=r"^[0-9a-f]{40}$")


class UpdateLog(BaseModel):
    run_id: str | None
    job: list[str]
    log: list[str]


class Memory:
    """What the app keeps between requests, in memory only: the last check's offer, when it was made, and the start
    this app made with the job's row, until the run's own state file takes over."""

    def __init__(self):
        self.lock = threading.RLock()
        self.offer: Offer | None = None
        self.last_check: float | None = None
        self.started: Started | None = None
        self.job_id: str | None = None


# Reading the run


def _read(app_state) -> Run | None:
    fake = app_state.fake_update
    return fake.run() if fake is not None else runs.read(app_state)


def _last_target(run: Run | None) -> tuple[Target, str | None] | None:
    """The last run's target and the tag the job will want for it, when the run didn't get there and names both."""
    if run is None or run.status not in ("failed", "interrupted", "cut_off"):
        return None
    if run.channel not in _CHANNELS or not _COMMIT.fullmatch(run.to_commit or ""):
        return None
    if run.channel == "stable":
        if not _TAG.fullmatch(run.to_tag or ""):
            return None
        return Target(channel=run.channel, commit=run.to_commit), run.to_tag
    return Target(channel=run.channel, commit=run.to_commit), None


def _finish_row(app_state, run: Run | None) -> None:
    """Write `update.finished` for a run that ended, once: the first request that sees it ended writes it."""
    if run is None or run.status not in ("ok", "failed") or not logs.plain_id(run.run_id):
        return
    detail = f"{run.run_id} ok"
    if run.status == "failed":
        detail = f"{run.run_id} failed" + (f" {run.reason}" if run.reason and _CODE.fullmatch(run.reason) else "")
    prefix = f"{run.run_id} "
    with app_state.update_memory.lock:
        con = app_state.state.connect()
        try:
            found = con.execute(
                "SELECT 1 FROM audit WHERE action = 'update.finished' AND substr(detail, 1, ?) = ? LIMIT 1",
                (len(prefix), prefix),
            ).fetchone()
        finally:
            con.close()
        if found is None:
            Audit(app_state.state).record(None, "update.finished", detail)


def _exit_status() -> str:
    try:
        return runs.systemd.show_unit(JOB_UNIT, ["ExecMainStatus"]).get("ExecMainStatus", "")
    except (RuntimeError, OSError):
        return ""


def _started(app_state, run: Run | None) -> Started | None:
    """The start this app made, as it stands: dropped once the run's own state file is here or the job carried an
    older run on; failed once the job's row failed with no run of ours (busy when the job found the lock held)."""
    memory = app_state.update_memory
    with memory.lock:
        started = memory.started
        if started is None:
            return None
        if run is not None and run.run_id == started.run_id:
            memory.started = None
            return None
        if started.status == "failed":
            return started
        try:
            job = app_state.jobs.get(memory.job_id)
        except (RuntimeError, OSError):
            return started  # the unit can't be asked now; the next request tries again
        status = job.status if job is not None else None
        if status == "succeeded":
            memory.started = None
            return None
        if status == "failed":
            reason = "busy" if _exit_status() == BUSY else "error"
            memory.started = started = Started(run_id=started.run_id, status="failed", reason=reason)
        return started


def _state(app_state) -> UpdateState:
    run = _read(app_state)
    _finish_row(app_state, run)
    manifest = app_state.manifest
    checks = before_start(manifest, run)
    last = _last_target(run)
    return UpdateState(
        installed=Installed(
            version=manifest.tm_version, channel=manifest.update.channel, commit=manifest.git.commit,
            modified=manifest.git.modified, source_known=repo_of(manifest) is not None,
        ),
        offer=app_state.update_memory.offer,
        checks=checks,
        can_start=not any(check.status == "error" for check in checks),
        run=run,
        started=_started(app_state, run),
        retry=last[0] if last else None,
    )


# The routes


@router.get("", response_model=UpdateState)
def get_update(request: Request, admin: User = Depends(require_admin)) -> UpdateState:
    return _state(request.app.state)


@router.post("/check", response_model=UpdateState)
def check_for_update(body: CheckRequest, request: Request, admin: User = Depends(require_admin)) -> UpdateState:
    """Ask GitHub what the channel offers. A refusal to ask, and each of GitHub's troubles, is an answer with a code."""
    app_state = request.app.state
    memory = app_state.update_memory
    repo = repo_of(app_state.manifest)
    if repo is None:
        raise ApiError(409, "no_source", NO_SOURCE_MESSAGE)
    with memory.lock:
        now = _clock()
        if memory.last_check is not None and now - memory.last_check < CHECK_SPACING:
            wait = math.ceil(CHECK_SPACING - (now - memory.last_check))
            raise ApiError(429, "rate_limited", TOO_SOON_MESSAGE, headers={"Retry-After": str(wait)})
        memory.last_check = now
    manifest = app_state.manifest
    try:
        if app_state.fake_update is not None:
            found = app_state.fake_update.check(body.channel, _now())
        else:
            found = offers.check(repo, manifest.git.commit, manifest.tm_version, body.channel, _now())
    except GithubError as error:
        if error.kind == "rate_limited":
            wait = error.retry_after if error.retry_after else CHECK_SPACING
            raise ApiError(429, "rate_limited", LIMITED_MESSAGE, headers={"Retry-After": str(wait)}) from None
        if error.kind == "offline":
            raise ApiError(502, "github_unreachable", OFFLINE_MESSAGE) from None
        raise ApiError(502, "github_answer", ANSWER_MESSAGE) from None
    memory.offer = found
    Audit(app_state.state).record(admin.id, "update.check", f"{found.channel} {found.relation}")
    return _state(app_state)


@router.post("/start", status_code=202, response_model=UpdateState)
def start_update(body: StartRequest, request: Request, admin: User = Depends(require_admin)) -> UpdateState:
    """Start the update job for the offer the last check made, or for the last run's target (Try again)."""
    app_state = request.app.state
    memory = app_state.update_memory
    run = _read(app_state)
    with memory.lock:
        found = memory.offer
        if found is not None and found.relation == "ahead" and (found.channel, found.commit) == (
            body.channel, body.commit
        ):
            tag = found.tag
        else:
            last = _last_target(run)
            if last is None or (last[0].channel, last[0].commit) != (body.channel, body.commit):
                raise ApiError(409, "stale_check", STALE_MESSAGE)
            tag = last[1]
        if run is not None and run.status == "running":
            raise ApiError(409, "update_running", RUNNING_MESSAGE)
        if any(check.status == "error" for check in before_start(app_state.manifest, run)):
            raise ApiError(409, "not_ready", NOT_READY_MESSAGE)
        run_id = _now().strftime("%Y%m%dT%H%M%SZ")
        request_body = {"run_id": run_id, "channel": body.channel, "commit": body.commit, "tag": tag}
        job = app_state.jobs.start("update", request_body, admin.id)
        memory.started, memory.job_id = Started(run_id=run_id, status="starting", reason=None), job.id
        Audit(app_state.state).record(admin.id, "update.start", f"{body.channel} {body.commit[:7]}")
        if app_state.fake_update is not None:
            app_state.fake_update.start(run_id, body.channel, body.commit, tag, found)
    return _state(app_state)


@router.get("/log", response_model=UpdateLog)
def get_log(request: Request, admin: User = Depends(require_admin)) -> UpdateLog:
    """The two units' last journal lines and the run's own log's last lines, redacted as the diagnostics are."""
    app_state = request.app.state
    fake = app_state.fake_update
    if fake is not None:
        return fake.log()
    run = runs.read(app_state)
    run_id = run.run_id if run is not None and logs.plain_id(run.run_id) else None
    job = [
        line for unit in (JOB_UNIT, RESUME_UNIT) for line in runs.systemd.journal_tail(unit, JOURNAL_LINES) or []
    ]
    log = logs.run_log(app_state.settings.update_dir, run_id, LOG_LINES, LOG_CAP)
    return UpdateLog(
        run_id=run_id,
        job=diagnostics.redacted(app_state, job),
        log=diagnostics.redacted(app_state, log),
    )
