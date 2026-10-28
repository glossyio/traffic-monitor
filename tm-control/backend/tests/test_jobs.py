import json
import stat
from datetime import datetime

import pytest

from tm_control.adapters import systemd
from tm_control.adapters.command import CommandResult
from tm_control.core.errors import ApiError
from tm_control.core.jobs import JOB_NAMES, FakeJobRunner, JobRunner
from tm_control.core.state import State

UNIT = "tm-job-system-password.service"
REQUEST = {"username": "pi", "password": "placeholder pass 1"}
OK = CommandResult(0, "", "", False)


class FakeSystemd:
    """The three systemd adapter functions, over one unit whose state the test sets, recording the calls."""

    def __init__(self):
        self.unit = {"ActiveState": "inactive", "Result": "success", "InvocationID": ""}
        self.start_result = OK
        self.started = []
        self.journal = []  # (invocation id, message)
        self.journal_calls = []

    def start_unit(self, name):
        self.started.append(name)
        return self.start_result

    def show_unit(self, name, properties):
        assert name == UNIT
        return {p: self.unit.get(p, "") for p in properties}

    def journal_lines(self, unit, since, limit=200, invocation_id=None):
        self.journal_calls.append((unit, since, limit, invocation_id))
        return [message for invocation, message in self.journal if invocation == invocation_id][:limit]

    def set(self, invocation, active, result="success"):
        self.unit = {"InvocationID": invocation, "ActiveState": active, "Result": result}


@pytest.fixture
def fake_systemd():
    return FakeSystemd()


@pytest.fixture
def state(settings):
    settings.state_dir.mkdir(parents=True)
    state = State(settings.state_dir / "state.sqlite")
    state.migrate()
    return state


@pytest.fixture
def runner(settings, state, fake_systemd):
    return JobRunner(settings, state, fake_systemd)


def request_file(settings):
    return settings.runtime_dir / "jobs" / "system-password.json"


def finish_script(settings):
    """What the root job does last: delete its request."""
    request_file(settings).unlink()


def job_rows(state):
    con = state.connect()
    try:
        return [dict(row) for row in con.execute("SELECT * FROM jobs ORDER BY requested_at")]
    finally:
        con.close()


def test_start_writes_a_private_request_and_starts_the_unit(settings, state, runner, fake_systemd):
    job = runner.start("system-password", REQUEST, user_id=None)
    path = request_file(settings)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert json.loads(path.read_text()) == REQUEST
    assert fake_systemd.started == [UNIT]
    assert job.name == "system-password" and job.status == "queued" and job.finished_at is None and job.log == []
    assert datetime.fromisoformat(job.requested_at).utcoffset() is not None
    [row] = job_rows(state)
    assert row["id"] == job.id and row["status"] == "queued" and row["name"] == "system-password"


def test_second_start_while_the_request_exists_is_409(settings, runner, fake_systemd):
    runner.start("system-password", REQUEST, user_id=None)
    with pytest.raises(ApiError) as caught:
        runner.start("system-password", REQUEST, user_id=None)
    assert caught.value.status == 409 and caught.value.code == "job_running"
    assert fake_systemd.started == [UNIT]
    assert request_file(settings).exists()  # the first job's request stays for its run


@pytest.mark.parametrize("active", ["activating", "active"])
def test_start_while_the_unit_runs_is_409_and_leaves_no_request(settings, runner, fake_systemd, active):
    fake_systemd.set("run-a", active)
    with pytest.raises(ApiError) as caught:
        runner.start("system-password", REQUEST, user_id=None)
    assert caught.value.status == 409 and caught.value.code == "job_running"
    assert not request_file(settings).exists() and fake_systemd.started == []


def test_status_follows_the_unit(settings, state, runner, fake_systemd):
    job = runner.start("system-password", REQUEST, user_id=None)
    assert runner.get(job.id).status == "queued"
    fake_systemd.set("run-b", "activating")
    assert runner.get(job.id).status == "running"
    finish_script(settings)
    fake_systemd.set("run-b", "inactive", "success")
    done = runner.get(job.id)
    assert done.status == "succeeded" and done.finished_at is not None
    assert job_rows(state)[0]["status"] == "succeeded"

    job = runner.start("system-password", REQUEST, user_id=None)
    fake_systemd.set("run-c", "failed", "exit-code")
    assert runner.get(job.id).status == "failed"


def test_a_stale_failure_before_the_new_run_starts_is_queued(settings, runner, fake_systemd):
    fake_systemd.set("run-a", "failed", "exit-code")  # an earlier run's outcome
    job = runner.start("system-password", REQUEST, user_id=None)
    assert runner.get(job.id).status == "queued"
    fake_systemd.set("run-b", "inactive", "success")
    assert runner.get(job.id).status == "succeeded"


def test_a_finished_job_keeps_its_outcome_when_later_runs_differ(settings, runner, fake_systemd):
    job = runner.start("system-password", REQUEST, user_id=None)
    fake_systemd.set("run-b", "inactive", "success")
    finished = runner.get(job.id)
    finish_script(settings)
    runner.start("system-password", REQUEST, user_id=None)
    fake_systemd.set("run-c", "failed", "exit-code")
    again = runner.get(job.id)
    assert again.status == "succeeded" and again.finished_at == finished.finished_at


def test_an_unpolled_job_gets_its_own_outcome_when_the_next_one_starts(settings, runner, fake_systemd):
    first = runner.start("system-password", REQUEST, user_id=None)
    fake_systemd.set("run-b", "inactive", "success")  # it ran, and nobody asked
    finish_script(settings)
    second = runner.start("system-password", REQUEST, user_id=None)
    fake_systemd.set("run-c", "failed", "exit-code")
    assert runner.get(first.id).status == "succeeded"
    assert runner.get(second.id).status == "failed"


def test_a_job_that_never_ran_fails_when_the_next_one_starts(settings, runner, fake_systemd):
    fake_systemd.set("run-a", "inactive", "success")
    first = runner.start("system-password", REQUEST, user_id=None)
    finish_script(settings)  # gone without a run, as when tm-control's runtime directory is emptied
    runner.start("system-password", REQUEST, user_id=None)
    assert runner.get(first.id).status == "failed"


def test_log_comes_from_the_journal_since_the_request(settings, runner, fake_systemd):
    job = runner.start("system-password", REQUEST, user_id=None)
    fake_systemd.journal = [("run-a", "an earlier run"), ("run-b", "password set for pi")]
    assert runner.get(job.id).log == [] and fake_systemd.journal_calls == []  # queued: no run to read
    fake_systemd.set("run-b", "inactive", "success")
    assert runner.get(job.id).log == ["password set for pi"]
    since = f"@{int(datetime.fromisoformat(job.requested_at).timestamp())}"
    assert fake_systemd.journal_calls[-1] == (UNIT, since, 200, "run-b")


def test_a_failed_start_removes_the_request_and_records_the_job(settings, state, runner, fake_systemd):
    fake_systemd.start_result = CommandResult(1, "", "Access denied: secret detail", False)
    with pytest.raises(ApiError) as caught:
        runner.start("system-password", REQUEST, user_id=None)
    assert caught.value.status == 500 and caught.value.code == "internal"
    assert "secret detail" not in caught.value.message
    assert not request_file(settings).exists()
    [row] = job_rows(state)
    assert row["status"] == "failed" and row["finished_at"] is not None

    fake_systemd.start_result = CommandResult(-9, "", "", True)  # a timeout fails the same way
    with pytest.raises(ApiError):
        runner.start("system-password", REQUEST, user_id=None)
    assert not request_file(settings).exists()


def test_unknown_job_name_is_refused(settings, runner):
    assert JOB_NAMES == {"system-password"}
    with pytest.raises(ValueError):
        runner.start("reboot", {}, user_id=None)
    assert not (settings.runtime_dir / "jobs" / "reboot.json").exists()


def test_unknown_job_id_is_none(runner):
    assert runner.get("no-such-job") is None


def test_the_requesting_user_is_recorded(state, runner):
    con = state.connect()
    with con:
        con.execute(
            "INSERT INTO users (username, password_hash, role, created_at) VALUES ('admin', 'x', 'admin', 'now')"
        )
    con.close()
    runner.start("system-password", REQUEST, user_id=1)
    assert job_rows(state)[0]["requested_by"] == 1


def test_jobs_keep_the_invocation_columns(state):
    con = state.connect()
    columns = {row["name"] for row in con.execute("PRAGMA table_info(jobs)")}
    con.close()
    assert {"prior_invocation", "invocation"} <= columns


def test_fake_runner_succeeds_at_once_and_leaves_no_request(settings, state):
    runner = FakeJobRunner(settings, state)
    job = runner.start("system-password", REQUEST, user_id=None)
    assert job.status == "succeeded" and job.finished_at is not None
    assert runner.get(job.id).log == ["fake: system-password done"]
    assert runner.last_request == REQUEST
    assert list((settings.runtime_dir / "jobs").iterdir()) == []
    assert runner.start("system-password", REQUEST, user_id=None).status == "succeeded"  # no 409 from a leftover
    with pytest.raises(ValueError):
        runner.start("reboot", {}, user_id=None)


# The adapter: argv lists, and parsing systemctl's and journalctl's output.


def fake_run(monkeypatch, result):
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        return result

    monkeypatch.setattr(systemd, "run", run)
    return calls


def test_start_unit_does_not_wait_for_the_job(monkeypatch):
    calls = fake_run(monkeypatch, OK)
    assert systemd.start_unit(UNIT) == OK
    assert calls == [["systemctl", "start", "--no-block", UNIT]]


def test_show_unit_reads_the_named_properties(monkeypatch):
    output = "Result=success\nActiveState=inactive\nInvocationID=0123abcd\nExtra=a=b\n"
    calls = fake_run(monkeypatch, CommandResult(0, output, "", False))
    shown = systemd.show_unit(UNIT, ["ActiveState", "Result", "InvocationID", "Missing"])
    assert shown == {"ActiveState": "inactive", "Result": "success", "InvocationID": "0123abcd", "Missing": ""}
    argv = calls[0]
    assert argv[:2] == ["systemctl", "show"] and argv[-1] == UNIT
    assert "--property=ActiveState,Result,InvocationID,Missing" in argv


def test_show_unit_fails_loudly(monkeypatch):
    fake_run(monkeypatch, CommandResult(1, "", "Failed to connect to bus", False))
    with pytest.raises(RuntimeError):
        systemd.show_unit(UNIT, ["ActiveState"])


def test_journal_lines_keeps_this_runs_messages(monkeypatch):
    entries = [
        {"MESSAGE": "from another run", "_SYSTEMD_INVOCATION_ID": "run-a"},
        {"MESSAGE": "password set for pi", "_SYSTEMD_INVOCATION_ID": "run-b"},
        {"MESSAGE": [104, 105, 255], "_SYSTEMD_INVOCATION_ID": "run-b"},  # journald's form for bytes that aren't UTF-8
        {"MESSAGE": None, "_SYSTEMD_INVOCATION_ID": "run-b"},  # a field too large to show
        {"_SYSTEMD_INVOCATION_ID": "run-b"},
    ]
    output = "\n".join(json.dumps(entry) for entry in entries) + '\n{"MESSAGE": "cut o'
    calls = fake_run(monkeypatch, CommandResult(0, output, "", False))
    assert systemd.journal_lines(UNIT, "@1700000000", invocation_id="run-b") == ["password set for pi", "hi�"]
    argv = calls[0]
    assert argv[0] == "journalctl" and argv[argv.index("-u") + 1] == UNIT
    assert argv[argv.index("--since") + 1] == "@1700000000" and "--output=json" in argv
    assert systemd.journal_lines(UNIT, "@1700000000", limit=1) == ["from another run"]


def test_journal_lines_is_empty_when_journalctl_fails(monkeypatch):
    fake_run(monkeypatch, CommandResult(1, "", "No journal files were opened", False))
    assert systemd.journal_lines(UNIT, "@1700000000") == []
