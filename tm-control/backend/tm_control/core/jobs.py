"""Root jobs: privileged work that tm-control asks for and a fixed, root-owned systemd unit does.

To run job <name>, tm-control writes the request to <runtime_dir>/jobs/<name>.json (0600) and starts
tm-job-<name>.service, which polkit allows. The unit's script (tm-control/jobs/, installed root-owned) checks the
request, does its one thing, and deletes the request. A job's status comes from the unit (systemctl show) and the
journal, its log from the journal; the jobs table keeps the record, so a job outlives a restart of tm-control.

Telling runs apart: the job units are oneshots, so ActiveState and Result describe the unit's latest run, and right
after a start is queued they still describe the run before. Every run gets a new InvocationID. start() records the
unit's InvocationID from before it starts the unit (prior_invocation); a run with a different id is the job's own,
because only one job of a name is ever in flight: start() holds a lock, the request file is created with O_EXCL and
removed only by the job's run (or as stale, below), start() refuses (409) while the unit is running, and it settles
every earlier unfinished job of the name before it starts the next.

systemd unloads an inactive unit that nothing references, and the run's state goes with it: after a successful run,
systemctl show reports no InvocationID (a failed unit stays loaded). So when the unit doesn't show the job's run, the
journal decides: PID 1 logs the end of each start job with INVOCATION_ID and JOB_RESULT ("done" for success). The first
such entry since the request whose id is neither prior_invocation nor an earlier job's run is the job's own. Without
one, the job is still queued (or running, once a run was seen).

The run's InvocationID is kept (invocation) to read the run's log. A row's status only moves forward (queued, running,
then succeeded or failed), and the first terminal status is written with finished_at (the time tm-control first saw
it), so a later run never rewrites an older job. tm-control needs to read the system journal (the systemd-journal
group) to see a successful job finish.
"""

import json
import logging
import os
import threading
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
# The statuses a row may move to each status from: never backwards, and a final status is written once.
_MOVES_FROM = {"queued": ("queued",), "running": _UNFINISHED, "succeeded": _UNFINISHED, "failed": _UNFINISHED}
_PROPERTIES = ["InvocationID", "ActiveState", "Result"]
_RUNNING_STATES = {"activating", "active", "deactivating", "reloading"}
_ALREADY_RUNNING = "That job is already running. Wait for it to finish."


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


def _journal_outcome(entries: list[dict], ignore: set[str], run: str | None) -> tuple[Status, str] | None:
    """The outcome of the job's run from PID 1's entry for the end of its start job, if the journal has it.

    The first run not in `ignore` is the job's, or only `run` once the job's run is known.
    """
    for entry in entries:
        invocation = entry.get("INVOCATION_ID")
        result = entry.get("JOB_RESULT")
        if not invocation or not result or invocation in ignore or entry.get("JOB_TYPE", "start") != "start":
            continue
        if run is not None and invocation != run:
            continue
        return ("succeeded" if result == "done" else "failed"), invocation
    return None


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
        self._start_lock = threading.Lock()  # one start at a time: the stale-request check reads, then deletes

    # The state database

    def _row(self, job_id: str):
        con = self.state.connect()
        try:
            return con.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        finally:
            con.close()

    def _rows(self, sql: str, params: tuple) -> list:
        con = self.state.connect()
        try:
            return con.execute(sql, params).fetchall()
        finally:
            con.close()

    def _write(self, sql: str, params: tuple) -> None:
        con = self.state.connect()
        try:
            with con:
                con.execute(sql, params)
        finally:
            con.close()

    def _unfinished(self, name: str) -> list:
        return self._rows("SELECT * FROM jobs WHERE name = ? AND status IN ('queued', 'running')", (name,))

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
        """Write a derived status, if the row's status may move to it (see _MOVES_FROM)."""
        allowed = _MOVES_FROM[status]
        self._write(
            "UPDATE jobs SET status = ?, invocation = coalesce(invocation, ?), finished_at = ?"
            f" WHERE id = ? AND status IN ({', '.join('?' * len(allowed))})",
            (status, invocation, None if status in _UNFINISHED else _now(), job_id, *allowed),
        )

    # Deriving a job's status

    def _derive(self, row, unit: dict[str, str]) -> tuple[Status, str | None]:
        """An unfinished job's status and its run's InvocationID, from the unit's properties now and the journal."""
        current, seen = unit["InvocationID"], row["invocation"]
        if current and current != row["prior_invocation"] and seen in (None, current):
            return _outcome(unit), current  # the unit still holds the job's run
        # The unit shows no run of the job's: not started yet, unloaded after it ended, or (only by hand) followed by
        # another run.
        ignore = {row["prior_invocation"] or ""} | {
            other["invocation"]
            for other in self._rows(
                "SELECT invocation FROM jobs WHERE name = ? AND id != ? AND invocation IS NOT NULL",
                (row["name"], row["id"]),
            )
        }
        entries = self.systemd.journal_entries(unit_name(row["name"]), _since(row["requested_at"]))
        found = _journal_outcome(entries, ignore, seen)
        if found is not None:
            return found
        if seen is not None and current and current != seen:
            return "failed", seen  # another run replaced the job's, and its end isn't in the journal: it's lost
        return ("running", seen) if seen is not None else ("queued", None)

    def _refresh(self, row):
        """The row, after writing what the unit and the journal now say about an unfinished job."""
        if row["status"] not in _UNFINISHED:
            return row
        status, invocation = self._derive(row, self.systemd.show_unit(unit_name(row["name"]), _PROPERTIES))
        if status != row["status"] or invocation != row["invocation"]:
            self._record(row["id"], status, invocation)
            row = self._row(row["id"])
        return row

    def _settle(self, name: str, unit: dict[str, str]) -> None:
        """Give each unfinished job of `name` its final status, while the unit shows no run in progress.

        A job whose run neither the unit nor the journal shows didn't run (its request was lost, or the start was
        refused), so it failed.
        """
        for row in self._unfinished(name):
            status, invocation = self._derive(row, unit)
            self._record(row["id"], "failed" if status in _UNFINISHED else status, invocation)

    # The request file

    def _request_is_stale(self, name: str) -> bool:
        """Whether a request no job will read is left: the unit isn't running and every job of `name` has finished,
        as when a job's script was killed before it could delete its request."""
        shown = self.systemd.show_unit(unit_name(name), _PROPERTIES)
        if shown["ActiveState"] in _RUNNING_STATES:
            return False
        return all(self._refresh(row)["status"] not in _UNFINISHED for row in self._unfinished(name))

    def _create_request(self, name: str, request: dict) -> Path:
        """Create the job's request file, 0600, in a 0700 directory. 409 `job_running` if a job still waits for it."""
        self.jobs_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        path = self.jobs_dir / f"{name}.json"
        try:
            return self._write_request(path, request)
        except FileExistsError:
            if not self._request_is_stale(name):
                raise ApiError(409, "job_running", _ALREADY_RUNNING) from None
        log.warning("removing a stale request for the %s job", name)
        _remove(path)
        try:
            return self._write_request(path, request)
        except FileExistsError:
            raise ApiError(409, "job_running", _ALREADY_RUNNING) from None

    @staticmethod
    def _write_request(path: Path, request: dict) -> Path:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
        fd = os.open(path, flags, 0o600)
        try:
            with os.fdopen(fd, "wb") as file:
                file.write(json.dumps(request).encode())
        except BaseException:
            _remove(path)
            raise
        return path

    # The API

    def start(self, name: str, request: dict, user_id: int | None) -> Job:
        """Write the request and start the job's unit."""
        _check_name(name)
        with self._start_lock:
            return self._start(name, request, user_id)

    def _start(self, name: str, request: dict, user_id: int | None) -> Job:
        unit = unit_name(name)
        path = self._create_request(name, request)
        try:
            shown = self.systemd.show_unit(unit, _PROPERTIES)
            if shown["ActiveState"] in _RUNNING_STATES:
                raise ApiError(409, "job_running", _ALREADY_RUNNING)
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
        row = self._refresh(row)
        invocation = row["invocation"]
        if invocation is None:
            return _job(row, [])  # no run of its own yet, or none ever
        unit = unit_name(row["name"])
        return _job(row, self.systemd.journal_lines(unit, _since(row["requested_at"]), LOG_LIMIT, invocation))


class FakeJobRunner(JobRunner):
    """Fake mode, with no systemd: writes the request as the real runner does, removes it as the real job would, and
    succeeds at once. The last request is kept in memory (last_request) for tests."""

    def __init__(self, settings: Settings, state: State):
        super().__init__(settings, state, systemd=None)
        self.last_request: dict | None = None

    def _request_is_stale(self, name: str) -> bool:
        return False  # the fake removes its own requests; one left over is another start's, still in progress

    def start(self, name: str, request: dict, user_id: int | None) -> Job:
        _check_name(name)
        path = self._create_request(name, request)
        try:
            self.last_request = json.loads(path.read_bytes())
        finally:
            _remove(path)
        return self.get(self._insert(name, user_id, "succeeded", None, finished=True))

    def get(self, job_id: str) -> Job | None:
        row = self._row(job_id)
        return None if row is None else _job(row, [f"fake: {row['name']} done"])
