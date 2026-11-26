"""The update repository's name (tmsetup_update_repo, the manifest's update.repo) is read in four places, and each
applies one rule: text, owner/name with 1 to 100 characters of letters, digits, dot, underscore, and hyphen in each
part, nothing else, and neither part made only of dots."""

import importlib.machinery
import importlib.util
import sys

import pytest
from test_tm_control_install import check_passes
from tmsetup_render import REPO

sys.path.insert(0, str(REPO / "script"))
sys.path.insert(0, str(REPO / "tm-control" / "backend"))

from tm_control.core.manifest import UpdateInfo  # noqa: E402
from tm_control.modules.update.source import repo_of as control_repo_of  # noqa: E402

from tm_update.installed import Refusal, _repository as installed_repository  # noqa: E402

GOOD = ["glossyio/traffic-monitor", "a-b/c.d_e", "a/" + "b" * 100, "a" * 100 + "/b", "x/.hidden", "a.b/c"]
BAD = ["glossyio", "a/b/c", "https://github.com/a/b", "a/b ", " a/b", "a/..", "./b", "a/" + "b" * 101,
       "a" * 101 + "/b", "a/b\n", "", 12, None, ["a/b"], "a/.", "../b", "/b", "a/"]
JOB = REPO / "tm-control" / "jobs" / "tm-job-update"


def the_roles_check(value):
    return check_passes(tmsetup_update_repo=value)


def tm_updates_reader(value):
    try:
        return installed_repository({"repo": value}) == value
    except Refusal:
        return False


def the_jobs_reader(value):
    loader = importlib.machinery.SourceFileLoader("tm_job_update_under_test", str(JOB))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    try:
        return module.repo_of({"update": {"repo": value, "channel": "stable"}}) == value
    except module.Refused:
        return False


def the_control_apps_reader(value):
    class Loaded:
        update = UpdateInfo(repo=value, channel="stable")

    found = control_repo_of(Loaded())
    return found is not None and found == value


READERS = [
    the_roles_check,
    tm_updates_reader,
    the_jobs_reader,
    the_control_apps_reader,
]


@pytest.mark.parametrize("reader", READERS)
def test_every_reader_accepts_the_good_names_and_refuses_the_bad_ones(reader):
    assert [name for name in GOOD if not reader(name)] == []
    assert [name for name in BAD if reader(name)] == []
