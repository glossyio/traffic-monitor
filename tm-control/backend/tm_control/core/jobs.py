"""Root jobs: privileged work that tm-control asks for and a fixed, root-owned systemd unit does.

To run job <name>, tm-control writes the request to <runtime_dir>/jobs/<name>.json (0600) and starts
tm-job-<name>.service, which polkit allows. The unit's script (tm-control/jobs/, installed root-owned) checks the
request, does its one thing, and deletes the request. A job's status comes from the unit (systemctl show) and its log
from the journal; the jobs table keeps the record, so a job outlives a restart of tm-control.

Telling runs apart: the job units are oneshots, so ActiveState and Result describe the unit's latest run, and right
after a start is queued they still describe the run before. Every run gets a new InvocationID. start() records the
unit's InvocationID from before it starts the unit (prior_invocation), and the job stays queued until the unit shows
a different one. That next run is the job's own, because only one job of a name is ever in flight: the request file is
created with O_EXCL and removed only by the job's run, start() refuses (409) while it exists or the unit is running,
and start() settles every earlier unfinished job of the name before it starts the next. The run's InvocationID is kept
(invocation) to read the run's log, and the first terminal status is written to the row with finished_at (the time
tm-control first saw it), so a later run never rewrites an older job.
"""

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from tm_control.core.errors import ApiError
from tm_control.core.settings import Settings
from tm_control.core.state import State

log = logging.getLogger(__name__)

JOB_NAMES = {"system-password"}
LOG_LIMIT = 200  # journal lines per job

Status = Literal["queued", "running", "succeeded", "failed"]
_UNFINISHED = ("queued", "running")
_PROPERTIES = ["InvocationID", "ActiveState", "Result"]
_RUNNING_STATES = {"activating", "active", "deactivating", "reloading"}


class Job(BaseModel):
    id: str
    name: str
    status: Status
    requested_at: str
    finished_at: str | None
    log: list[str]


def unit_name(name: str) -> str:
    return f"tm-job-{name}.service"


def _check_name(name: str) -> None:
    if name not in JOB_NAMES:
        raise ValueError(f"there is no job named {name!r}")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _since(requested_at: str) -> str:
    """journalctl's --since for a job: the second it was requested, as @<unix seconds>."""
    return f"@{int(datetime.fromisoformat(requested_at).timestamp())}"


def _remove(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def _outcome(unit: dict[str, str]) -> Status:
    """The status of the run the unit shows. An unknown ActiveState counts as still running, never as finished."""
    active = unit["ActiveState"]
    if active == "failed":
        return "failed"
    if active == "inactive":
        return "succeeded" if unit["Result"] == "success" else "failed"
    return "running"


def _derive(row, unit: dict[str, str]) -> tuple[Status, str | None]:
    """An unfinished job's status and its run's InvocationID, from its row and the unit's properties now."""
    current = unit["InvocationID"]
    if not current or current == row["prior_invocation"]:
        return "queued", None  # the unit still shows the run from before the request
    if row["invocation"] and row["invocation"] != current:
        # The job's run ended unseen and another run began. tm-control never does that (see the module docstring);
        # someone started the unit by hand. Its outcome is lost, so don't report it as a success.
        return "failed", row["invocation"]
    return _outcome(unit), current


def _job(row, log_lines: list[str]) -> Job:
    return Job(
        id=row["id"],
        name=row["name"],
        status=row["status"],
        requested_at=row["requested_at"],
        finished_at=row["finished_at"],
        log=log_lines,
    )


class JobRunner:
    """Starts jobs and reports on them. `systemd` is the adapter module tm_control.adapters.systemd, or a stand-in."""

    def __init__(self, settings: Settings, state: State, systemd):
        self.state = state
        self.systemd = systemd
        self.jobs_dir = settings.runtime_dir / "jobs"

    # The state database

    def _row(self, job_id: str):
        con = self.state.connect()
        try:
            return con.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        finally:
            con.close()

    def _write(self, sql: str, params: tuple) -> None:
        con = self.state.connect()
        try:
            with con:
                con.execute(sql, params)
        finally:
            con.close()

    def _insert(self, name, user_id, status, prior_invocation, finished: bool) -> str:
        job_id = uuid.uuid4().hex
        now = _now()
        self._write(
            "INSERT INTO jobs (id, name, requested_by, requested_at, finished_at, status, prior_invocation)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (job_id, name, user_id, now, now if finished else None, status, prior_invocation),
        )
        return job_id

    def _record(self, job_id: str, status: Status, invocation: str | None) -> None:
        """Write what get() derived, unless the row already holds a final status."""
        self._write(
            "UPDATE jobs SET status = ?, invocation = coalesce(invocation, ?), finished_at = ?"
            " WHERE id = ? AND status IN ('queued', 'running')",
            (status, invocation, None if status in _UNFINISHED else _now(), job_id),
        )

    def _settle(self, name: str, unit: dict[str, str]) -> None:
        """Give each unfinished job of `name` its final status, while the unit shows no run in progress.

        A job whose run the unit never showed didn't run (its request was lost, or the start was refused), so it failed.
        """
        con = self.state.connect()
        try:
            rows = con.execute(
                "SELECT id, prior_invocation, invocation FROM jobs WHERE name = ? AND status IN ('queued', 'running')",
                (name,),
            ).fetchall()
        finally:
            con.close()
        for row in rows:
            status, invocation = _derive(row, unit)
            self._record(row["id"], "failed" if status in _UNFINISHED else status, invocation)

    # The request file

    def _write_request(self, name: str, request: dict) -> Path:
        """Create the job's request file, 0600. 409 `job_running` if it exists: that job hasn't run yet."""
        self.jobs_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        path = self.jobs_dir / f"{name}.json"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
        try:
            fd = os.open(path, flags, 0o600)
        except FileExistsError:
            raise ApiError(409, "job_running", "That job is already running. Wait for it to finish.") from None
        try:
            with os.fdopen(fd, "wb") as file:
                file.write(json.dumps(request).encode())
        except BaseException:
            _remove(path)
            raise
        return path

    # The API

    def start(self, name: str, request: dict, user_id: int | None) -> Job:
        """Write the request and start the job's unit. The request file, made with O_EXCL, is the job's lock."""
        _check_name(name)
        unit = unit_name(name)
        path = self._write_request(name, request)
        try:
            shown = self.systemd.show_unit(unit, _PROPERTIES)
            if shown["ActiveState"] in _RUNNING_STATES:
                raise ApiError(409, "job_running", "That job is already running. Wait for it to finish.")
            self._settle(name, shown)
            job_id = self._insert(name, user_id, "queued", shown["InvocationID"], finished=False)
        except BaseException:
            _remove(path)
            raise

        try:
            result = self.systemd.start_unit(unit)
            started = result.returncode == 0 and not result.timed_out
        except OSError as error:  # no systemctl
            log.error("starting %s failed: %s", unit, type(error).__name__)
            started = False
        else:
            if not started:
                reason = "timed out" if result.timed_out else f"exit status {result.returncode}"
                log.error("starting %s failed (%s): %s", unit, reason, result.stderr.strip()[:500])
        if not started:
            _remove(path)  # or every later start would be refused as already running
            self._record(job_id, "failed", None)
            raise ApiError(500, "internal", "The job could not be started. tm-control's log has the details.")
        return _job(self._row(job_id), [])

    def get(self, job_id: str) -> Job | None:
        row = self._row(job_id)
        if row is None:
            return None
        unit = unit_name(row["name"])
        if row["status"] in _UNFINISHED:
            status, invocation = _derive(row, self.systemd.show_unit(unit, _PROPERTIES))
            if status != row["status"] or invocation != row["invocation"]:
                self._record(job_id, status, invocation)
                row = self._row(job_id)
        invocation = row["invocation"]
        if invocation is None:
            return _job(row, [])  # no run of its own yet, or none ever
        return _job(row, self.systemd.journal_lines(unit, _since(row["requested_at"]), LOG_LIMIT, invocation))


class FakeJobRunner(JobRunner):
    """Fake mode, with no systemd: writes the request as the real runner does, removes it as the real job would, and
    succeeds at once. The last request is kept in memory (last_request) for tests."""

    def __init__(self, settings: Settings, state: State):
        super().__init__(settings, state, systemd=None)
        self.last_request: dict | None = None

    def start(self, name: str, request: dict, user_id: int | None) -> Job:
        _check_name(name)
        path = self._write_request(name, request)
        try:
            self.last_request = json.loads(path.read_bytes())
        finally:
            _remove(path)
        return self.get(self._insert(name, user_id, "succeeded", None, finished=True))

    def get(self, job_id: str) -> Job | None:
        row = self._row(job_id)
        return None if row is None else _job(row, [f"fake: {row['name']} done"])
