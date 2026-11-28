"""The control app and tm-job-update agree on what passes between them: the request the control app writes is one the
job accepts, the job's held-lock status is the one the control app reads as busy, both name the same files under the
update folder, and they share the tag and commit rules and the order of versions. The job imports nothing, so it
repeats each of these; this ties the two copies together."""

import importlib.machinery
import importlib.util
import sys
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from tmsetup_render import REPO

sys.path.insert(0, str(REPO / "tm-control" / "backend"))

from tm_control.adapters import github  # noqa: E402
from tm_control.core.jobs import JobRunner  # noqa: E402
from tm_control.core.manifest import Manifest  # noqa: E402
from tm_control.core.settings import Settings  # noqa: E402
from tm_control.modules.update import logs, offer  # noqa: E402
from tm_control.modules.update import router as router_module  # noqa: E402
from tm_control.modules.update import run as runs  # noqa: E402
from tm_control.modules.update.offer import Offer  # noqa: E402

JOB = REPO / "tm-control" / "jobs" / "tm-job-update"
MANIFEST = REPO / "tm-control" / "backend" / "tests" / "fixtures" / "manifest.json"
NOW = datetime(2026, 11, 26, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def job():
    """The job as a module, loaded as script/tests/test_update_job_contract.py loads it, with no bytecode left."""
    loader = importlib.machinery.SourceFileLoader("tm_job_update_control_app", str(JOB))
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    was, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = was
    return module


def settings():
    return Settings.from_env({"TM_CONTROL_BIND": "127.0.0.1:8090"})


def the_request_the_router_writes(monkeypatch, channel, tag):
    """POST /update/start's request for an offer on the channel, as the router builds it, with nothing else run."""
    commit = "2" * 40
    found = Offer(channel=channel, relation="ahead", version=tag and tag[1:], commit=commit, tag=tag,
                  released_at=None, ahead_by=None, checked_at="2026-11-26T12:00:00Z")
    started = []

    class Jobs:
        def start(self, name, request, user_id):
            started.append((name, request))
            return SimpleNamespace(id="job-1")

        def get(self, job_id):
            return SimpleNamespace(id=job_id, status="running")

    memory = router_module.Memory()
    memory.offer = found
    app_state = SimpleNamespace(fake_update=None, update_memory=memory, jobs=Jobs(), state=None,
                                manifest=Manifest.model_validate_json(MANIFEST.read_text()))
    monkeypatch.setattr(router_module, "_read", lambda app_state: None)
    monkeypatch.setattr(router_module, "_now", lambda: NOW)
    monkeypatch.setattr(router_module, "Audit", lambda state: SimpleNamespace(record=lambda *args: None))
    body = router_module.StartRequest(channel=channel, commit=commit)
    router_module.start_update(body, SimpleNamespace(app=SimpleNamespace(state=app_state)), SimpleNamespace(id=1))
    [(name, request)] = started
    assert name == "update"
    return request


@pytest.mark.parametrize(("channel", "tag"), [("stable", "v0.8.1"), ("development", None)])
def test_the_request_the_control_app_writes_passes_the_jobs_check(job, monkeypatch, channel, tag):
    request = the_request_the_router_writes(monkeypatch, channel, tag)
    assert job.check_request(request) == request


def test_the_jobs_held_lock_status_is_what_the_control_app_reads_as_busy(job):
    assert router_module.BUSY == str(job.HELD)


def test_the_control_app_reads_the_files_the_job_writes(job):
    folder = settings().update_dir
    assert str(folder) == job.UPDATE
    assert str(folder / runs.STATE_FILE) == job.STATE
    assert str(folder / runs.MARKER_FILE) == job.RESUME
    assert str(folder / logs.LOG_FOLDER) == job.LOG


def test_the_job_reads_its_request_where_the_job_runner_writes_it(job):
    assert str(JobRunner(settings(), state=None, systemd=None).jobs_dir / "update.json") == job.REQUEST


def test_the_tag_and_commit_rules_are_the_same_text(job):
    for tag in (router_module._TAG, offer._TAG):
        assert tag.pattern == job.TAG.pattern
    for commit in (router_module._COMMIT, offer._COMMIT, github._COMMIT):
        assert commit.pattern == job.COMMIT.pattern
    assert router_module.StartRequest.model_fields["commit"].metadata[0].pattern == f"^{job.COMMIT.pattern}$"


VERSIONS = ["0.7.1", "0.8.0-dev", "0.8.0", "0.8.1-dev", "0.8.1", "0.8.10", "0.9.0-dev", "0.9.0", "1.0.0", "10.0.0"]
NOT_VERSIONS = ["", "0.8", "v0.8.0", "0.8.0-rc1", "0.8.0-dev2", " 0.8.0", "0.8.0\n", "a.b.c", "1234567890.0.0"]


def test_the_control_app_orders_versions_as_the_job_does(job):
    shuffled = VERSIONS[::-1][3:] + VERSIONS[::-1][:3]
    assert sorted(shuffled, key=offer._version_key) == VERSIONS
    assert sorted(shuffled, key=job.version_key) == VERSIONS
    for older in VERSIONS:
        for newer in VERSIONS:
            assert (offer._version_key(older) < offer._version_key(newer)) == (
                job.version_key(older) < job.version_key(newer)), (older, newer)
    for value in NOT_VERSIONS:
        assert not offer._version_key(value) and not job.version_key(value), value
