"""An update's status as the control app works it out: the state file, the two units, the resume marker, and this
boot's id. The units and the files are stood in for; no test reads the machine's own update folder."""

import copy
import dataclasses
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tm_control.core.manifest import Manifest, UpdateInfo
from tm_control.core.settings import Settings
from tm_control.modules.update import checks, run
from tm_control.modules.update.run import derive

FIXTURES = Path(__file__).parent / "fixtures"
BOOT = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
OTHER_BOOT = "ffffffff-bbbb-4ccc-8ddd-eeeeeeeeeeee"


def fixture(name):
    return json.loads((FIXTURES / f"update_state_{name}.json").read_text())


def stopped(stage, **keys):
    """A run's file as it is left when the run is cut off: running, in `stage`, with no result."""
    state = fixture("running")
    state["stage"] = stage
    state["stages"].append({"id": stage, "started_at": "2026-11-26T10:30:00Z", "finished_at": None})
    state.update(keys)
    return state


STATES = {
    "running": lambda: fixture("running"),
    "ok": lambda: fixture("ok"),
    "failed": lambda: fixture("failed"),
    "switch": lambda: stopped("switch"),
    "reboot": lambda: stopped("reboot", boot_id=BOOT),
}


@pytest.mark.parametrize(
    ("file", "unit_running", "marker", "same_boot", "status"),
    [
        (None, False, False, False, None),
        (None, True, False, False, "running"),
        ("running", True, False, False, "running"),
        ("running", False, False, False, "interrupted"),
        ("switch", False, True, False, "cut_off"),
        ("switch", False, False, False, "interrupted"),
        ("reboot", False, True, True, "running"),
        ("reboot", False, True, False, "cut_off"),
        ("ok", False, False, False, "ok"),
        ("failed", False, False, False, "failed"),
        ("failed", True, False, False, "running"),
    ],
)
def test_the_runs_status_comes_from_the_file_the_units_and_the_marker(file, unit_running, marker, same_boot, status):
    state = STATES[file]() if file else None
    boot = BOOT if same_boot else OTHER_BOOT
    found = derive(state, unit_running=unit_running, marker=marker, boot_id=boot)
    assert (found.status if found else None) == status


def test_a_run_that_is_going_shows_what_the_file_holds():
    found = derive(fixture("running"), unit_running=True, marker=False, boot_id=BOOT)
    assert found.readable is True
    assert (found.run_id, found.channel) == ("20261126T101500Z", "stable")
    assert (found.from_version, found.from_commit) == ("0.8.0", "1" * 40)
    assert (found.to_version, found.to_commit, found.to_tag) == ("0.8.1", "2" * 40, "v0.8.1")
    assert found.stage == "images"
    assert [(s.id, s.started_at, s.finished_at) for s in found.stages] == [
        ("prepare", "2026-11-26T10:15:02Z", "2026-11-26T10:20:40Z"),
        ("images", "2026-11-26T10:20:41Z", None),
    ]
    assert (found.reason, found.detail, found.restore_point, found.finished_at) == (None, None, None, None)


def test_an_ended_run_shows_its_reason_and_when_it_ended():
    found = derive(fixture("failed"), unit_running=False, marker=False, boot_id=BOOT)
    assert (found.status, found.reason, found.detail) == ("failed", "build_failed", "frigate")
    assert found.to_tag is None
    assert found.finished_at == "2026-11-26T10:30:00Z"  # the last stage's finish: the file has no end time
    done = derive(fixture("ok"), unit_running=False, marker=False, boot_id=BOOT)
    assert (done.status, done.reason, done.finished_at) == ("ok", None, "2026-11-26T10:48:20Z")


def test_a_running_unit_over_an_ended_runs_file_shows_none_of_that_run():
    for name in ("ok", "failed"):
        found = derive(fixture(name), unit_running=True, marker=False, boot_id=BOOT)
        assert found.status == "running"
        assert found.readable is True
        assert found.stages == []
        assert found.reason is None and found.detail is None
        assert found.to_commit is None and found.to_version is None and found.to_tag is None
        assert found.run_id is None and found.restore_point is None and found.finished_at is None


def test_a_later_versions_file_is_an_update_that_is_running_or_not_readable():
    later = fixture("later_version")
    going = derive(later, unit_running=True, marker=False, boot_id=BOOT)
    assert going.status == "running"
    assert going.readable is False
    assert going.stages == [] and going.to_commit is None and going.run_id is None
    assert derive(later, unit_running=False, marker=True, boot_id=BOOT) is None


def test_unknown_stage_ids_and_reason_codes_pass_through():
    state = fixture("failed")
    state["stage"] = "polish"
    state["stages"][1]["id"] = "polish"
    state["reason"] = "a_code_from_a_later_version"
    found = derive(state, unit_running=False, marker=False, boot_id=BOOT)
    assert found.status == "failed"
    assert found.stage == "polish"
    assert found.stages[1].id == "polish"
    assert found.reason == "a_code_from_a_later_version"


@pytest.mark.parametrize("bad", ["[]", '{"stages": 5}', '{"stages": [3]}', '{"to": "x"}', '{"run_id": 9}', "not json"])
@pytest.mark.parametrize("unit_running", [False, True])
def test_a_file_of_the_wrong_shape_never_raises(bad, unit_running):
    try:
        state = json.loads(bad)
    except ValueError:
        state = None
    found = derive(state, unit_running=unit_running, marker=False, boot_id=BOOT)
    if unit_running:
        assert found.status == "running" and found.readable is False
    else:
        assert found is None


@pytest.mark.parametrize(
    "change",
    [
        {"run_id": 9}, {"channel": ["stable"]}, {"from": "x"}, {"from": {"version": 1, "commit": 2}},
        {"to": [1]}, {"to": {"version": {}, "commit": True, "tag": 4}}, {"stage": 7}, {"stages": 5},
        {"stages": [3, None, "x", {"id": 4}, {"started_at": "t"}]}, {"stages": [{"id": "a", "started_at": 5, "finished_at": []}]},
        {"reason": 4, "detail": {}}, {"restore_point": 5}, {"result": 5}, {"boot_id": 5},
    ],
)
@pytest.mark.parametrize("unit_running", [False, True])
def test_a_wrong_value_in_a_file_that_has_the_right_schema_becomes_nothing(change, unit_running):
    state = fixture("running")
    state.update(change)
    found = derive(state, unit_running=unit_running, marker=True, boot_id=BOOT)
    assert found.readable is True
    assert found.status == ("running" if unit_running else "cut_off")
    assert all(isinstance(row.id, str) for row in found.stages)
    for name in ("run_id", "channel", "stage", "reason", "detail", "restore_point"):
        assert getattr(found, name) is None or isinstance(getattr(found, name), str)


def test_a_source_the_job_could_not_read_leaves_the_installed_commit_unknown():
    for value in (None, "unknown"):
        state = fixture("failed")
        state["from"] = {"version": None, "commit": value}
        found = derive(state, unit_running=False, marker=False, boot_id=BOOT)
        assert found.status == "failed"
        assert found.from_commit is None
        assert found.from_version is None


@pytest.mark.parametrize(
    ("held", "name"),
    [
        ("/var/lib/traffic-monitor/restore/20261126T104130Z-1111111", "20261126T104130Z-1111111"),
        ("/var/lib/traffic-monitor/restore/20261126T104130Z-1111111/", "20261126T104130Z-1111111"),
        ("20261126T104130Z-1111111", "20261126T104130Z-1111111"),
        ("", None), ("/", None), (".", None), ("..", None), ("/var/lib/..", None), ("a/.", None), (None, None), (5, None),
    ],
)
def test_the_restore_point_is_given_by_name_only(held, name):
    state = fixture("ok")
    state["restore_point"] = held
    found = derive(state, unit_running=False, marker=False, boot_id=BOOT)
    assert found.restore_point == name
    assert "/" not in (found.restore_point or "")


# Reading the run: the file, the two units, the marker, and the boot id

class Units:
    """The two units' ActiveState, by name; a name in `broken` can't be asked."""

    def __init__(self, **active):
        self.active = {run.JOB_UNIT: "inactive", run.RESUME_UNIT: "inactive"}
        self.active.update({{"job": run.JOB_UNIT, "resume": run.RESUME_UNIT}[key]: value for key, value in active.items()})
        self.broken = set()

    def show_unit(self, name, properties):
        if name in self.broken:
            raise RuntimeError("systemctl show failed")
        assert properties == ["ActiveState"]
        return {"ActiveState": self.active[name]}


@pytest.fixture
def world(tmp_path, monkeypatch, settings):
    """An app state whose update folder is a temporary one, units stopped, no marker, and a boot id."""
    units = Units()
    monkeypatch.setattr(run, "systemd", units)
    boot = tmp_path / "boot_id"
    boot.write_text(BOOT + "\n")
    monkeypatch.setattr(run, "BOOT_ID", boot)
    folder = tmp_path / "update"
    folder.mkdir()
    app_state = SimpleNamespace(settings=dataclasses.replace(settings, update_dir=folder))
    return SimpleNamespace(app_state=app_state, folder=folder, units=units, boot=boot)


def test_the_run_is_read_from_the_file_in_the_update_folder(world):
    (world.folder / "state.json").write_text(json.dumps(fixture("ok")))
    found = run.read(world.app_state)
    assert (found.status, found.run_id) == ("ok", "20261126T101500Z")


@pytest.mark.parametrize("content", [None, "not json", "[]", "\x00", json.dumps({"schema": 2})])
def test_no_file_or_an_unreadable_one_with_nothing_running_is_no_run(world, content):
    if content is not None:
        (world.folder / "state.json").write_text(content)
    assert run.read(world.app_state) is None


def test_a_file_that_is_not_text_never_raises(world):
    (world.folder / "state.json").write_bytes(b"\xff\xfe{")
    assert run.read(world.app_state) is None


def test_a_file_too_large_to_be_a_state_file_is_not_read(world):
    (world.folder / "state.json").write_text(json.dumps({"schema": 1, "detail": "x" * 2_000_000}))
    assert run.read(world.app_state) is None


@pytest.mark.parametrize("which", ["job", "resume"])
def test_either_unit_running_is_a_run_that_is_going(world, which):
    (world.folder / "state.json").write_text(json.dumps(fixture("running")))
    world.units.active[{"job": run.JOB_UNIT, "resume": run.RESUME_UNIT}[which]] = "activating"
    assert run.read(world.app_state).status == "running"


@pytest.mark.parametrize("state", ["inactive", "failed"])
def test_a_unit_that_is_inactive_or_failed_is_not_running(world, state):
    (world.folder / "state.json").write_text(json.dumps(fixture("running")))
    world.units.active[run.JOB_UNIT] = state
    world.units.active[run.RESUME_UNIT] = state
    assert run.read(world.app_state).status == "interrupted"


@pytest.mark.parametrize("which", ["job", "resume"])
def test_a_unit_that_cannot_be_asked_counts_as_running(world, which):
    world.units.broken.add({"job": run.JOB_UNIT, "resume": run.RESUME_UNIT}[which])
    found = run.read(world.app_state)
    assert found is not None and found.status == "running"


def test_the_marker_is_only_the_exact_file(world):
    (world.folder / "state.json").write_text(json.dumps(stopped("switch")))
    (world.folder / "resume.json.unusable").write_text("{}")
    assert run.read(world.app_state).status == "interrupted"
    (world.folder / "resume.json").write_text("{}")
    assert run.read(world.app_state).status == "cut_off"


def test_a_restart_about_to_happen_is_a_run_that_is_going(world):
    (world.folder / "state.json").write_text(json.dumps(stopped("reboot", boot_id=BOOT)))
    assert run.read(world.app_state).status == "running"
    world.boot.write_text(OTHER_BOOT + "\n")
    assert run.read(world.app_state).status == "interrupted"
    world.boot.unlink()  # this boot's id can't be read: the restart can't be taken to be still to come
    assert run.read(world.app_state).status == "interrupted"


# The settings

def test_the_update_folder_is_a_setting():
    env = {"TM_CONTROL_BIND": "127.0.0.1:8090"}
    assert Settings.from_env(env).update_dir == Path("/var/lib/traffic-monitor/update")
    assert Settings.from_env({**env, "TM_UPDATE_DIR": "/somewhere/update"}).update_dir == Path("/somewhere/update")
    fake = Settings.from_env({**env, "TM_CONTROL_FAKE": "1"})
    assert fake.update_dir == Path.cwd() / ".tm-control-fake" / "update"


# The checks before a start

def manifest(**changes):
    base = json.loads((FIXTURES / "manifest.json").read_text())
    base = copy.deepcopy(base)
    for key, value in changes.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            base[key].update(value)
        else:
            base[key] = value
    return Manifest.model_validate(base)


def the_run(status):
    found = derive(fixture("running"), unit_running=True, marker=False, boot_id=BOOT)
    return found.model_copy(update={"status": status})


def test_a_clean_unit_with_a_source_has_nothing_to_report():
    assert checks.before_start(manifest(update={"repo": "glossyio/traffic-monitor"}), None) == []


def test_each_check_appears_only_when_it_applies_and_in_order():
    everything = manifest(
        update={"repo": ""}, options={"plate_recognizer": True}, git={"commit": "0" * 40, "branch": "x", "modified": True}
    )
    found = checks.before_start(everything, the_run("running"))
    assert [(c.id, c.status) for c in found] == [
        ("update.source", "error"),
        ("update.addon", "error"),
        ("update.running", "error"),
        ("update.modified", "warn"),
    ]
    assert all(c.title and c.detail for c in found)
    only_source = checks.before_start(manifest(update={"repo": "not a repo"}), the_run("failed"))
    assert [c.id for c in only_source] == ["update.source"]
    assert [c.id for c in checks.before_start(manifest(update={"repo": "a/b"}), the_run("ok"))] == []
    assert [c.id for c in checks.before_start(manifest(options={"plate_recognizer": True}), None)] == ["update.addon"]
    modified = manifest(git={"commit": "0" * 40, "branch": "x", "modified": True})
    assert [c.id for c in checks.before_start(modified, None)] == ["update.modified"]


def test_an_unusable_update_block_is_an_unknown_source():
    unusable = manifest(update="nonsense")
    assert unusable.update == UpdateInfo(repo="", channel="stable")
    assert [c.id for c in checks.before_start(unusable, None)] == ["update.source"]
