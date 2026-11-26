"""The Software update API: GET /update, POST /update/check, POST /update/start, and GET /update/log.

The device cases run against a state file under the settings' update_dir, the units replaced by the `units` fixture
(run.systemd), GitHub's three adapter functions replaced by `github`, and a stub for the jobs the starts ask for. The
last case runs fake mode. Commits are placeholders.
"""

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_api_system_info import host  # noqa: F401  (the diagnostics case's synthetic host)

from tm_control.adapters import github
from tm_control.adapters.github import GithubError
from tm_control.modules.system import diagnostics as diagnostics_module
from tm_control.modules.update import router as router_module
from tm_control.modules.update import run as runs
from tm_control.modules.update.run import JOB_UNIT, RESUME_UNIT

URL = "/api/v1/update"
ORIGIN = {"Origin": "http://tm-test.local"}
ADMIN, ADMIN_PASSWORD = "admin", "correct horse 1"
VIEWER, VIEWER_PASSWORD = "viewer", "viewer pass 1"
FIXTURES = Path(__file__).parent / "fixtures"
INSTALLED = "0" * 40  # the fixture manifest's commit
OFFERED = "2" * 40
STARTED_AT = datetime(2026, 11, 26, 12, 0, 0, tzinfo=timezone.utc)
RUN_ID = "20261126T120000Z"


class Units:
    """The two units as systemctl shows them: ActiveState and ExecMainStatus for each, and the journals' lines."""

    def __init__(self):
        self.shown = {JOB_UNIT: {"ActiveState": "inactive", "ExecMainStatus": "0"},
                      RESUME_UNIT: {"ActiveState": "inactive", "ExecMainStatus": "0"}}
        self.tails = {JOB_UNIT: ["job line"], RESUME_UNIT: ["resume line"]}
        self.asked = []

    def show_unit(self, name, properties):
        self.asked.append(name)
        return {key: self.shown[name].get(key, "") for key in properties}

    def journal_tail(self, unit, lines):
        self.asked.append((unit, lines))
        return self.tails[unit]


@pytest.fixture(autouse=True)
def units(monkeypatch):
    units = Units()
    monkeypatch.setattr(runs, "systemd", units)
    return units


class Github:
    """GitHub's answers about the repository, from the three functions the offer asks."""

    def __init__(self):
        self.status, self.ahead_by = "ahead", 12
        self.release = {"tag": "v0.8.1", "published_at": "2026-11-20T10:00:00Z"}
        self.commit = OFFERED
        self.error = None
        self.asked = []

    def latest_release(self, repo):
        self.asked.append(("release", repo))
        if self.error:
            raise self.error
        return self.release

    def commit_id(self, repo, ref):
        self.asked.append(("commit", repo, ref))
        if self.error:
            raise self.error
        return self.commit

    def compare(self, repo, base, head):
        self.asked.append(("compare", repo, base, head))
        if self.error:
            raise self.error
        return {"status": self.status, "ahead_by": self.ahead_by}


@pytest.fixture
def online(monkeypatch):
    online = Github()
    for name in ("latest_release", "commit_id", "compare"):
        monkeypatch.setattr(github, name, getattr(online, name))
    return online


@pytest.fixture
def offline(monkeypatch):
    """GitHub's functions raise if called."""

    def refuse(*args, **kwargs):
        raise AssertionError("the control app went online")

    for name in ("latest_release", "commit_id", "compare"):
        monkeypatch.setattr(github, name, refuse)


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(router_module, "_clock", clock)
    monkeypatch.setattr(router_module, "_now", lambda: STARTED_AT)
    return clock


class Jobs:
    """The jobs a device client's runner was asked to start, in place of starting any, and the status each reads as."""

    def __init__(self):
        self.started = []
        self.status = "running"

    def start(self, name, request, user_id):
        self.started.append((name, request, user_id))
        return SimpleNamespace(id="job-1")

    def get(self, job_id):
        return SimpleNamespace(id=job_id, status=self.status)


@pytest.fixture
def jobs(device_client):
    jobs = Jobs()
    device_client.app.state.jobs.start = jobs.start
    device_client.app.state.jobs.get = jobs.get
    return jobs


def state_of(name):
    return json.loads((FIXTURES / f"update_state_{name}.json").read_text())


def write_state(settings, state):
    settings.update_dir.mkdir(parents=True, exist_ok=True)
    (settings.update_dir / "state.json").write_text(json.dumps(state))


def write_log(settings, run_id, text):
    folder = settings.update_dir / "log"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{run_id}.log").write_text(text)


def stable_state(**changes):
    state = state_of("running")
    state.update(changes)
    return state


def admin(client, login):
    login(client, ADMIN, ADMIN_PASSWORD)
    return client


def get(client):
    r = client.get(URL)
    assert r.status_code == 200, r.text
    return r.json()


def check(client, channel="stable"):
    return client.post(f"{URL}/check", json={"channel": channel}, headers=ORIGIN)


def start(client, channel="stable", commit=OFFERED):
    return client.post(f"{URL}/start", json={"channel": channel, "commit": commit}, headers=ORIGIN)


def audit_rows(settings, action=None):
    con = sqlite3.connect(settings.state_dir / "state.sqlite")
    try:
        rows = con.execute("SELECT action, detail, user_id FROM audit ORDER BY id").fetchall()
    finally:
        con.close()
    return [row for row in rows if action is None or row[0] == action]


def ids(checks):
    return [c["id"] for c in checks]


def test_a_viewer_gets_403_on_all_four_routes(device_client, login, offline, jobs):
    login(device_client, VIEWER, VIEWER_PASSWORD)
    assert device_client.get(URL).status_code == 403
    assert check(device_client).status_code == 403
    assert start(device_client).status_code == 403
    assert device_client.get(f"{URL}/log").status_code == 403
    assert jobs.started == []


def test_get_never_goes_online(device_client, login, offline):
    admin(device_client, login)
    body = get(device_client)
    assert body["offer"] is None and body["run"] is None and body["started"] is None and body["retry"] is None
    assert body["can_start"] is True


def test_get_tells_what_is_installed_and_that_a_changed_copy_was(device_client, login, offline):
    admin(device_client, login)
    body = get(device_client)
    assert body["installed"] == {
        "version": "0.7.1-test", "channel": "development", "commit": INSTALLED, "modified": False,
        "source_known": True,
    }
    assert body["checks"] == []
    app_state = device_client.app.state
    git = app_state.manifest.git.model_copy(update={"modified": True})
    app_state.manifest = app_state.manifest.model_copy(update={"git": git})
    body = get(device_client)
    assert body["installed"]["modified"] is True
    assert [(c["id"], c["status"]) for c in body["checks"]] == [("update.modified", "warn")]
    assert body["can_start"] is True


def test_no_recorded_source_is_an_error_check(device_client, login, offline):
    admin(device_client, login)
    app_state = device_client.app.state
    update = app_state.manifest.update.__class__(repo="", channel="stable")
    app_state.manifest = app_state.manifest.model_copy(update={"update": update})
    body = get(device_client)
    assert body["installed"]["source_known"] is False
    assert [(c["id"], c["status"]) for c in body["checks"]] == [("update.source", "error")]
    assert body["can_start"] is False


def test_a_check_keeps_its_offer_and_writes_an_audit_row(device_client, login, online, settings):
    admin(device_client, login)
    r = check(device_client)
    assert r.status_code == 200, r.text
    offer = r.json()["offer"]
    assert (offer["channel"], offer["relation"], offer["commit"], offer["tag"], offer["version"]) == (
        "stable", "ahead", OFFERED, "v0.8.1", "0.8.1")
    assert offer["ahead_by"] == 12 and offer["checked_at"]
    assert ("compare", "example/traffic-monitor-test", INSTALLED, OFFERED) in online.asked
    online.asked.clear()
    assert get(device_client)["offer"] == offer
    assert online.asked == []
    rows = audit_rows(settings, "update.check")
    assert [(action, detail) for action, detail, _ in rows] == [("update.check", "stable ahead")]
    assert isinstance(rows[0][2], int)


def test_a_second_check_within_a_minute_is_429_with_the_wait(device_client, login, online, clock):
    admin(device_client, login)
    assert check(device_client).status_code == 200
    asked = len(online.asked)
    clock.now += 45
    r = check(device_client, "development")
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "rate_limited"
    assert r.headers["Retry-After"] == "15"
    assert len(online.asked) == asked
    clock.now += 15
    assert check(device_client, "development").status_code == 200


@pytest.mark.parametrize(
    ("kind", "status", "code"),
    [("offline", 502, "github_unreachable"), ("refused", 502, "github_answer"),
     ("not_found", 502, "github_answer"), ("rate_limited", 429, "rate_limited")],
)
def test_githubs_troubles_are_answers_not_errors(device_client, login, online, settings, kind, status, code):
    admin(device_client, login)
    online.error = GithubError(kind, 90 if kind == "rate_limited" else None)
    r = check(device_client)
    assert r.status_code == status
    assert r.json()["error"]["code"] == code
    if kind == "rate_limited":
        assert r.headers["Retry-After"] == "90"
    assert get(device_client)["offer"] is None
    assert audit_rows(settings, "update.check") == []


def test_a_check_with_no_usable_source_is_409_and_asks_nothing(device_client, login, offline):
    admin(device_client, login)
    app_state = device_client.app.state
    update = app_state.manifest.update.__class__(repo="not a repo", channel="stable")
    app_state.manifest = app_state.manifest.model_copy(update={"update": update})
    r = check(device_client)
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "no_source"


def test_a_check_for_another_channel_is_refused_by_the_schema(device_client, login, offline):
    admin(device_client, login)
    assert check(device_client, "nightly").status_code == 422
    assert start(device_client, commit="ABC").status_code == 422


def test_a_start_must_be_the_offer_or_the_retry(device_client, login, online, jobs):
    admin(device_client, login)
    assert start(device_client).status_code == 409  # no check yet
    assert check(device_client).status_code == 200
    for channel, commit in (("stable", "3" * 40), ("development", OFFERED)):
        r = start(device_client, channel, commit)
        assert r.status_code == 409 and r.json()["error"]["code"] == "stale_check", (channel, commit)
    assert jobs.started == []


@pytest.mark.parametrize("relation", ["identical", "behind", "diverged"])
def test_an_offer_that_is_not_ahead_cannot_be_started(device_client, login, online, jobs, relation):
    admin(device_client, login)
    online.status = relation
    assert check(device_client).status_code == 200
    r = start(device_client)
    assert r.status_code == 409 and r.json()["error"]["code"] == "stale_check"
    assert jobs.started == []


def test_a_start_writes_the_four_key_request_and_nothing_else(device_client, login, online, jobs, settings):
    admin(device_client, login)
    check(device_client, "stable")
    r = start(device_client)
    assert r.status_code == 202, r.text
    assert len(jobs.started) == 1
    name, request, user_id = jobs.started[0]
    assert (name, request) == (
        "update", {"run_id": RUN_ID, "channel": "stable", "commit": OFFERED, "tag": "v0.8.1"})
    assert r.json()["started"] == {"run_id": RUN_ID, "status": "starting", "reason": None}
    assert audit_rows(settings, "update.start") == [("update.start", "stable 2222222", user_id)]
    assert "tag" not in json.dumps(audit_rows(settings))


def test_a_development_start_carries_no_tag(device_client, login, online, jobs, clock):
    admin(device_client, login)
    check(device_client, "development")
    assert start(device_client, "development").status_code == 202
    assert jobs.started[0][1] == {"run_id": RUN_ID, "channel": "development", "commit": OFFERED, "tag": None}


def test_a_start_while_a_run_is_running_is_409(device_client, login, online, jobs, units, settings):
    admin(device_client, login)
    check(device_client)
    units.shown[JOB_UNIT]["ActiveState"] = "active"
    write_state(settings, state_of("running"))
    r = start(device_client)
    assert r.status_code == 409 and r.json()["error"]["code"] == "update_running"
    assert jobs.started == []
    body = get(device_client)
    assert body["run"]["status"] == "running" and body["can_start"] is False


def test_a_start_with_the_addon_is_409_not_ready(device_client, login, online, jobs):
    admin(device_client, login)
    check(device_client)
    app_state = device_client.app.state
    app_state.manifest = app_state.manifest.model_copy(update={"options": {"plate_recognizer": True}})
    assert "update.addon" in ids(get(device_client)["checks"])
    r = start(device_client)
    assert r.status_code == 409 and r.json()["error"]["code"] == "not_ready"
    assert jobs.started == []


@pytest.mark.parametrize("how", ["failed", "interrupted", "cut_off"])
def test_try_again_is_offered_for_the_last_runs_target_and_accepted_without_a_check(
    device_client, login, offline, jobs, settings, how
):
    admin(device_client, login)
    state = stable_state()
    if how == "failed":
        state.update(result="failed", reason="build_failed")
    elif how == "cut_off":
        state["stage"] = "switch"
        settings.update_dir.mkdir(parents=True, exist_ok=True)
        (settings.update_dir / "resume.json").write_text("{}")
    write_state(settings, state)
    body = get(device_client)
    assert body["run"]["status"] == how
    assert body["retry"] == {"channel": "stable", "commit": OFFERED}
    r = start(device_client)
    assert r.status_code == 202, r.text
    assert jobs.started[0][1] == {"run_id": RUN_ID, "channel": "stable", "commit": OFFERED, "tag": "v0.8.1"}
    assert start(device_client, "development", OFFERED).status_code == 409


def test_there_is_nothing_to_retry_after_a_run_that_worked_or_that_names_no_target(device_client, login, offline, settings):
    admin(device_client, login)
    write_state(settings, state_of("ok"))
    assert get(device_client)["retry"] is None
    write_state(settings, stable_state(result="failed", to={"version": None, "commit": "unknown", "tag": None}))
    assert get(device_client)["retry"] is None
    # a stable run's retry needs the release tag the job will ask for
    write_state(settings, stable_state(result="failed", to={"version": None, "commit": OFFERED, "tag": None}))
    assert get(device_client)["retry"] is None


def test_a_unit_running_over_an_older_runs_final_file_has_no_retry_and_no_finished_row(
    device_client, login, offline, units, settings
):
    admin(device_client, login)
    write_state(settings, state_of("failed"))
    units.shown[JOB_UNIT]["ActiveState"] = "activating"
    body = get(device_client)
    assert body["run"]["status"] == "running" and body["run"]["run_id"] is None
    assert body["retry"] is None
    assert audit_rows(settings, "update.finished") == []


def test_a_start_the_job_refused_as_busy_says_so(device_client, login, online, jobs, units):
    admin(device_client, login)
    check(device_client)
    assert start(device_client).status_code == 202
    assert get(device_client)["started"]["status"] == "starting"
    jobs.status = "failed"
    units.shown[JOB_UNIT]["ExecMainStatus"] = "75"
    assert get(device_client)["started"] == {"run_id": RUN_ID, "status": "failed", "reason": "busy"}
    units.shown[JOB_UNIT]["ExecMainStatus"] = "1"
    assert get(device_client)["started"]["reason"] == "busy"  # said once, kept


def test_a_start_the_job_failed_otherwise_says_error(device_client, login, online, jobs, units):
    admin(device_client, login)
    check(device_client)
    start(device_client)
    jobs.status = "failed"
    units.shown[JOB_UNIT]["ExecMainStatus"] = "1"
    assert get(device_client)["started"] == {"run_id": RUN_ID, "status": "failed", "reason": "error"}


def test_started_is_dropped_when_the_state_file_is_the_runs_own(device_client, login, online, jobs, units, settings):
    admin(device_client, login)
    check(device_client)
    start(device_client)
    write_state(settings, stable_state(run_id=RUN_ID))
    units.shown[JOB_UNIT]["ActiveState"] = "active"
    body = get(device_client)
    assert body["started"] is None and body["run"]["run_id"] == RUN_ID


def test_started_is_dropped_when_the_job_carried_an_older_run_on(device_client, login, online, jobs, units, settings):
    admin(device_client, login)
    check(device_client)
    start(device_client)
    write_state(settings, state_of("ok"))
    jobs.status = "succeeded"
    body = get(device_client)
    assert body["started"] is None
    assert body["run"]["run_id"] == "20261126T101500Z"


def test_started_stays_while_the_unit_runs_over_an_older_final_file(device_client, login, online, jobs, units, settings):
    admin(device_client, login)
    check(device_client)
    start(device_client)
    write_state(settings, state_of("ok"))
    units.shown[JOB_UNIT]["ActiveState"] = "activating"
    assert get(device_client)["started"]["status"] == "starting"


def test_update_finished_is_written_once_per_run(device_client, login, offline, settings):
    admin(device_client, login)
    write_state(settings, state_of("ok"))
    get(device_client)
    get(device_client)
    assert audit_rows(settings, "update.finished") == [("update.finished", "20261126T101500Z ok", None)]
    state = state_of("failed")
    state["run_id"] = "20261127T090000Z"
    write_state(settings, state)
    get(device_client)
    get(device_client)
    assert audit_rows(settings, "update.finished") == [
        ("update.finished", "20261126T101500Z ok", None),
        ("update.finished", "20261127T090000Z failed build_failed", None),
    ]


def test_a_run_that_has_not_ended_writes_no_finished_row(device_client, login, offline, settings, units):
    admin(device_client, login)
    units.shown[JOB_UNIT]["ActiveState"] = "active"
    write_state(settings, state_of("running"))
    get(device_client)
    assert audit_rows(settings, "update.finished") == []


def test_the_log_is_redacted_and_capped(device_client, login, offline, settings, units, monkeypatch):
    admin(device_client, login)
    monkeypatch.setattr(diagnostics_module, "camera_names", lambda app_state: {"back_yard_cam"})
    secret = device_client.app.state.secrets.read("node_red_token_key")
    write_state(settings, state_of("ok"))
    lines = [f"line {n} {'x' * 600}" for n in range(1000)]
    lines[-1] = f"last {secret} on back_yard_cam"
    write_log(settings, "20261126T101500Z", "\n".join(lines) + "\n")
    units.tails[JOB_UNIT] = [f"job {secret}"]
    body = device_client.get(f"{URL}/log").json()
    assert body["run_id"] == "20261126T101500Z"
    assert len(body["log"]) == 400
    assert body["log"][0].startswith("line 600 ")
    assert body["log"][-1] == "last <redacted> on <redacted>"
    assert body["job"] == ["job <redacted>", "resume line"]
    assert (JOB_UNIT, 50) in units.asked and (RESUME_UNIT, 50) in units.asked
    assert secret not in json.dumps(body)


def test_a_huge_log_is_read_from_its_end_only(device_client, login, offline, settings):
    admin(device_client, login)
    write_state(settings, state_of("ok"))
    write_log(settings, "20261126T101500Z", ("a" * 99 + "\n") * 20000 + "the end\n")  # 2 MB
    body = device_client.get(f"{URL}/log").json()
    assert len(body["log"]) == 400 and body["log"][-1] == "the end"
    assert all(line == "a" * 99 for line in body["log"][:-1])


@pytest.mark.parametrize("run_id", ["../state", "a/b", "", "x" * 65, "run id", 5])
def test_a_run_id_that_is_not_a_plain_name_reads_no_file(device_client, login, offline, settings, run_id):
    admin(device_client, login)
    state = state_of("ok")
    state["run_id"] = run_id
    write_state(settings, state)
    (settings.update_dir / "log").mkdir()
    (settings.update_dir / "state.log").write_text("not for you\n")
    (settings.update_dir / "log" / "..log").write_text("not for you\n")
    assert device_client.get(f"{URL}/log").json()["log"] == []


def test_a_missing_log_or_state_is_an_empty_answer(device_client, login, offline, settings):
    admin(device_client, login)
    body = device_client.get(f"{URL}/log").json()
    assert body == {"run_id": None, "job": ["job line", "resume line"], "log": []}
    write_state(settings, state_of("ok"))
    assert device_client.get(f"{URL}/log").json()["log"] == []


def test_a_log_that_is_a_link_is_not_followed(device_client, login, offline, settings):
    admin(device_client, login)
    write_state(settings, state_of("ok"))
    (settings.update_dir / "log").mkdir()
    (settings.update_dir / "elsewhere").write_text("secret place\n")
    (settings.update_dir / "log" / "20261126T101500Z.log").symlink_to(settings.update_dir / "elsewhere")
    assert device_client.get(f"{URL}/log").json()["log"] == []


def test_diagnostics_holds_the_state_the_log_and_both_journals_redacted(
    device_client, login, host, settings  # noqa: F811
):
    admin(device_client, login)
    secret = device_client.app.state.secrets.read("node_red_token_key")
    state = state_of("ok")
    state["detail"] = f"token={secret}"
    write_state(settings, state)
    write_log(settings, "20261126T101500Z", "\n".join(f"log {n}" for n in range(300)) + f"\nsecret line {secret}\n")
    older = settings.update_dir / "log" / "20260101T000000Z.log"
    older.write_text("older run\n")
    os.utime(older, (1, 1))
    host.journal = lambda unit, lines: [f"{unit} says {secret}"]
    text = device_client.get("/api/v1/system/diagnostics").text
    headings = [h for h in text.split("\n") if h.startswith("== ")]
    assert headings[:8] == [
        "== Device ==", "== Date and time ==", "== Status ==", "== Services ==", "== Manifest ==",
        "== Update state ==", "== Update log (last 200 lines) ==",
        f"== Journal: {JOB_UNIT} (last 50 lines) ==",
    ]
    assert f"== Journal: {RESUME_UNIT} (last 50 lines) ==" in headings
    assert '"run_id": "20261126T101500Z"' in text
    section = text.split("== Update log (last 200 lines) ==")[1].split("\n== ")[0]
    assert "log 299\n" in section and "log 101\n" in section
    assert "log 100\n" not in section and "older run" not in section
    assert "secret line <redacted>" in section
    assert secret not in text
    assert (JOB_UNIT, 50) in host.journal_calls and (RESUME_UNIT, 50) in host.journal_calls


def test_diagnostics_says_so_when_there_is_no_update_to_show(device_client, login, host, settings):  # noqa: F811
    admin(device_client, login)
    text = device_client.get("/api/v1/system/diagnostics").text
    assert "== Update state ==\n(No update state file.)" in text
    assert "== Update log (last 200 lines) ==\n(No update log.)" in text


def test_the_opener_a_test_forgets_to_replace_refuses_to_go_out():
    from urllib.request import Request

    with pytest.raises(AssertionError, match="api.github.com"):
        github._OPENER.open(Request("https://api.github.com/repos/example/x/releases/latest"))


# Fake mode


class FakeTime:
    def __init__(self):
        self.now = 1_800_000_000.0

    def __call__(self):
        return self.now


def test_fake_mode_walks_a_stable_update_to_ok_and_a_development_one_to_build_failed(
    claimed_client, login, offline, monkeypatch, settings, clock
):
    def broken(*args, **kwargs):
        raise FileNotFoundError("no systemctl here")

    monkeypatch.setattr(runs, "systemd", SimpleNamespace(show_unit=broken, journal_tail=broken))
    fake_time = FakeTime()
    monkeypatch.setattr(router_module, "_now", lambda: datetime.fromtimestamp(fake_time.now, timezone.utc))
    claimed_client.app.state.fake_update._clock = fake_time
    admin(claimed_client, login)
    body = get(claimed_client)
    assert body["offer"] is None and body["run"] is None and body["can_start"] is True

    offer = check(claimed_client, "stable").json()["offer"]
    assert (offer["version"], offer["tag"], offer["relation"]) == ("0.8.1", "v0.8.1", "ahead")
    r = start(claimed_client, "stable", offer["commit"])
    assert r.status_code == 202, r.text
    run_id = r.json()["run"]["run_id"]  # the fake run exists at once, so `started` has nothing left to say
    assert r.json()["run"]["status"] == "running" and r.json()["started"] is None
    seen = []
    for _ in range(30):
        body = get(claimed_client)
        seen.append(body["run"]["stage"])
        assert body["started"] is None
        if body["run"]["status"] != "running":
            break
        fake_time.now += 2
    assert body["run"]["status"] == "ok" and body["run"]["run_id"] == run_id
    assert seen[0] == "fetch" and len(set(seen)) > 3
    assert body["started"] is None
    assert [r for r in audit_rows(settings, "update.finished")] == [("update.finished", f"{run_id} ok", None)]
    log = claimed_client.get(f"{URL}/log").json()
    assert log["run_id"] == run_id and log["job"] and log["log"]

    clock.now += 61
    fake_time.now += 3600
    offer = check(claimed_client, "development").json()["offer"]
    assert (offer["relation"], offer["ahead_by"]) == ("ahead", 12)
    start(claimed_client, "development", offer["commit"])
    fake_time.now += 1000
    body = get(claimed_client)
    assert (body["run"]["status"], body["run"]["reason"], body["run"]["stage"]) == ("failed", "build_failed", "images")
    assert body["retry"] == {"channel": "development", "commit": offer["commit"]}
    assert len(audit_rows(settings, "update.finished")) == 2
