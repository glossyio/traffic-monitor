"""tm-job-update and tm-update agree: the job's paths are tm-update's, tm-update accepts the hand-over the job writes,
and carries on the state file the job started. The job runs against the test world of
tm-control/backend/tests/fixtures/job_update_world.py (a temporary root and a local bare repository)."""

import ast
import importlib.machinery
import importlib.util
import json
import sys

import pytest
from tmsetup_render import REPO

sys.path.insert(0, str(REPO / "script"))

from tm_update import handover as handover_module  # noqa: E402
from tm_update.paths import Paths  # noqa: E402
from tm_update.state import State, _fresh  # noqa: E402

JOBS = REPO / "tm-control" / "jobs"
JOB = JOBS / "tm-job-update"
LAUNCHER = JOBS / "tm-update-resume"


def load(path, name):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


@pytest.fixture
def world(tmp_path):
    return load(REPO / "tm-control" / "backend" / "tests" / "fixtures" / "job_update_world.py",
                "job_update_world").World(tmp_path)


def test_the_jobs_paths_are_tm_updates():
    job = load(JOB, "tm_job_update_paths")
    paths = Paths()
    assert job.LOCK == str(paths.lock)
    assert job.STATE == str(paths.state)
    assert job.RESUME == str(paths.resume)
    assert job.WORK == str(paths.work_root)
    assert job.LOG == str(paths.log_dir)
    assert job.SRC == str(paths.src_root)
    assert job.TM_CONTROL_STATE == str(paths.tm_control_state)
    assert job.MANIFEST == str(paths.manifest)


def test_tm_update_accepts_the_hand_over_the_job_writes(world):
    result = world.run()
    assert result.returncode == 0, result.stdout + result.stderr
    loaded = handover_module.load(world.handover_path(), Paths(root=world.root))
    assert (loaded.run_id, loaded.channel, loaded.commit, loaded.tag) == (
        "20261125T101500Z", "development", world.ids["dev"], None)
    assert loaded.from_version == "0.8.0"


def test_tm_update_carries_on_the_state_the_job_started(world):
    result = world.run()
    assert result.returncode == 0, result.stdout + result.stderr
    loaded = handover_module.load(world.handover_path(), Paths(root=world.root))
    written = json.loads(world.state_path.read_text())
    assert set(written) == set(_fresh(loaded, None, None))
    state = State.open(loaded, None, "0.8.2-dev")
    state.begin("prepare")
    rows = json.loads(world.state_path.read_text())["stages"]
    assert [row["id"] for row in rows] == ["fetch", "verify", "prepare"]
    assert rows[:2] == written["stages"]


@pytest.mark.parametrize("script", [
    JOB, LAUNCHER])
def test_the_job_and_the_launcher_import_only_the_standard_library(script):
    tree = ast.parse(script.read_text())
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "no relative import"
            names.add(node.module.split(".")[0])
    assert names
    assert names <= set(sys.stdlib_module_names)
