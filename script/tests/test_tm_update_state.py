"""tm-update's state file: replaced whole, one run's record, stages with their times."""

import json
import os
import re

import pytest
from tm_update_support import COMMIT, handover, installed, make_world

from tm_update import state as state_module
from tm_update.state import REASONS, STAGES, Failed, State, clear_marker, write_marker

ISO = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ")


@pytest.fixture
def world(tmp_path):
    paths, tree = make_world(tmp_path)
    paths.update_dir.mkdir(parents=True)
    return paths, tree


def test_the_stage_ids_and_reasons_are_the_contract():
    assert STAGES == ("prepare", "images", "restore_point", "switch", "reboot", "health", "cleanup")
    assert REASONS == ("busy", "needs_manual_update", "addon_needs_installer", "reboot_pending", "low_space",
                       "no_internet", "hardware_needs_installer", "settings_need_attention", "prepare_failed",
                       "build_failed", "switch_failed", "health_failed")


def test_a_new_run_starts_with_the_contracts_keys(world):
    paths, _ = world
    state = State.open(handover(paths), installed(), "0.8.0")
    assert state.data == {
        "schema": 1, "run_id": "20261125T101500Z-abc", "channel": "stable",
        "from": {"version": "0.7.1", "commit": "b" * 40},
        "to": {"version": "0.8.0", "commit": COMMIT, "tag": "v0.8.0"},
        "stage": None, "stages": [], "result": None, "reason": None, "detail": None, "boot_id": None,
        "reboot": None, "restore_point": None, "tmdb_backup": None, "switch_attempts": 0,
    }


def test_the_file_is_replaced_whole_and_never_seen_half_written(world, monkeypatch):
    paths, _ = world
    state = State.open(handover(paths), installed(), "0.8.0")
    state.begin("prepare")
    before = paths.state.read_text()
    seen = []
    real_replace = os.replace

    def spy(source, target):
        # at the moment of the swap the old file is still whole, and the new one is complete beside it
        assert paths.state.read_text() == before
        assert os.path.dirname(source) == os.path.dirname(target)
        assert json.loads(open(source).read())["stages"][0]["finished_at"]
        seen.append(source)
        real_replace(source, target)

    monkeypatch.setattr(state_module.os, "replace", spy)
    state.finish("prepare")
    assert len(seen) == 1
    monkeypatch.undo()
    state.begin("images")
    assert json.loads(paths.state.read_text())["stage"] == "images"
    assert (paths.state.stat().st_mode & 0o777) == 0o644
    assert [p.name for p in paths.update_dir.iterdir()] == ["state.json"]


def test_a_stage_gets_its_times(world):
    paths, _ = world
    state = State.open(handover(paths), installed(), "0.8.0")
    state.begin("prepare")
    row = state.data["stages"][0]
    assert row["id"] == "prepare" and ISO.fullmatch(row["started_at"]) and row["finished_at"] is None
    assert state.data["stage"] == "prepare"
    state.finish("prepare")
    assert ISO.fullmatch(state.data["stages"][0]["finished_at"])


def test_an_unknown_stage_is_refused(world):
    paths, _ = world
    state = State.open(handover(paths), installed(), "0.8.0")
    with pytest.raises(ValueError):
        state.begin("sleep")


def test_a_state_file_of_this_run_is_carried_on_with_its_earlier_stages(world):
    paths, _ = world
    first = State.open(handover(paths), installed(), "0.8.0")
    first.begin("prepare")
    first.finish("prepare")
    first.set(restore_point="x", switch_attempts=1)
    again = State.open(handover(paths), installed(), "0.8.0")
    assert [row["id"] for row in again.data["stages"]] == ["prepare"]
    assert again.data["restore_point"] == "x" and again.data["switch_attempts"] == 1


def test_a_state_file_the_caller_started_is_carried_on_with_its_own_stages(world):
    paths, _ = world
    paths.state.write_text(json.dumps({"schema": 1, "run_id": "20261125T101500Z-abc", "channel": "stable",
                                       "stages": [{"id": "fetch", "started_at": "2026-11-25T10:15:00Z",
                                                   "finished_at": "2026-11-25T10:15:09Z"}]}))
    state = State.open(handover(paths), installed(), "0.8.0")
    assert state.data["stages"][0]["id"] == "fetch"
    assert state.data["to"]["commit"] == COMMIT
    assert state.data["switch_attempts"] == 0


@pytest.mark.parametrize(("key", "value"), [
    ("switch_attempts", None), ("switch_attempts", "1"), ("switch_attempts", True), ("switch_attempts", -1),
    ("switch_attempts", 1.0), ("boot_id", 5), ("boot_id", ["b"]), ("restore_point", 5), ("restore_point", {}),
    ("tmdb_backup", False), ("tmdb_backup", ["t"]), ("reboot", "yes"), ("reboot", 1), ("stage", 5),
    ("stage", ["prepare"])])
def test_a_key_of_the_wrong_type_in_a_state_file_the_caller_started_is_not_carried_on(world, key, value):
    paths, _ = world
    fresh = State.open(handover(paths, run_id="fresh"), installed(), "0.8.0").data
    paths.state.write_text(json.dumps({"schema": 1, "run_id": "20261125T101500Z-abc", "channel": "stable",
                                       "stages": [], key: value}))
    state = State.open(handover(paths), installed(), "0.8.0")
    assert state.data[key] == fresh[key]
    assert json.loads(paths.state.read_text())[key] == fresh[key]


def test_a_state_file_the_caller_started_keeps_its_own_stage_ids_and_good_values(world):
    paths, _ = world
    rows = [{"id": "fetch", "started_at": "2026-11-25T10:15:00Z", "finished_at": "2026-11-25T10:15:09Z"},
            {"id": "verify", "started_at": "2026-11-25T10:15:09Z", "finished_at": None}]
    paths.state.write_text(json.dumps({"schema": 1, "run_id": "20261125T101500Z-abc", "channel": "stable",
                                       "stage": "verify", "stages": rows, "boot_id": None, "reboot": False,
                                       "restore_point": "r", "tmdb_backup": None, "switch_attempts": 0}))
    data = State.open(handover(paths), installed(), "0.8.0").data
    assert data["stage"] == "verify" and data["stages"] == rows
    assert (data["reboot"], data["restore_point"], data["switch_attempts"]) == (False, "r", 0)


def test_a_state_file_of_another_run_is_started_over(world):
    paths, _ = world
    other = State.open(handover(paths, run_id="other"), installed(), "0.8.0")
    other.begin("prepare")
    state = State.open(handover(paths), installed(), "0.8.0")
    assert state.data["stages"] == [] and state.data["run_id"] == "20261125T101500Z-abc"


@pytest.mark.parametrize("text", ["not json", "[]", json.dumps({"run_id": 5}),
                                  json.dumps({"run_id": "20261125T101500Z-abc", "stages": "x"})])
def test_a_state_file_that_cannot_be_read_is_started_over(world, text):
    paths, _ = world
    paths.state.write_text(text)
    assert State.open(handover(paths), installed(), "0.8.0").data["stages"] == []


def test_ending_a_run_records_result_reason_and_detail_and_closes_the_stage(world):
    paths, _ = world
    state = State.open(handover(paths), installed(), "0.8.0")
    state.begin("images")
    state.end("failed", "build_failed", "frigate-tm")
    data = json.loads(paths.state.read_text())
    assert (data["result"], data["reason"], data["detail"]) == ("failed", "build_failed", "frigate-tm")
    assert ISO.fullmatch(data["stages"][0]["finished_at"])


def test_ending_ok_has_no_reason(world):
    paths, _ = world
    state = State.open(handover(paths), installed(), "0.8.0")
    state.end("ok")
    assert (state.data["result"], state.data["reason"], state.data["detail"]) == ("ok", None, None)


@pytest.mark.parametrize("args", [("sleeping",), ("failed", "because"), ("failed", None), ("ok", "busy")])
def test_a_result_or_reason_outside_the_contract_is_refused(world, args):
    paths, _ = world
    with pytest.raises(ValueError):
        State.open(handover(paths), installed(), "0.8.0").end(*args)


def test_a_detail_is_one_short_line(world):
    paths, _ = world
    state = State.open(handover(paths), installed(), "0.8.0")
    state.end("failed", "build_failed", "line one\nline two " + "x" * 500)
    assert "\n" not in state.data["detail"] and len(state.data["detail"]) <= 200


def test_only_the_listed_keys_can_be_set(world):
    paths, _ = world
    state = State.open(handover(paths), installed(), "0.8.0")
    state.set(restore_point="p", tmdb_backup="t", reboot=True, boot_id="b", switch_attempts=2)
    assert state.data["reboot"] is True
    with pytest.raises(ValueError):
        state.set(result="ok")


def test_a_state_without_an_installed_manifest_takes_the_version_the_caller_gave(world):
    paths, _ = world
    state = State.open(handover(paths, from_version="0.8.0"), None, "0.8.0")
    assert state.data["from"] == {"version": "0.8.0", "commit": None}
    state.end("failed", "needs_manual_update")
    assert json.loads(paths.state.read_text())["reason"] == "needs_manual_update"


def test_failed_carries_its_reason_and_detail():
    error = Failed("low_space", "10 MB free")
    assert (error.reason, error.detail) == ("low_space", "10 MB free")
    with pytest.raises(ValueError):
        Failed("whatever")


def test_the_resume_marker_is_written_and_cleared(world, tmp_path):
    paths, tree = world
    write_marker(paths, tree, tmp_path / "h.json")
    assert json.loads(paths.resume.read_text()) == {"contract": 1, "tree": str(tree), "handover": str(tmp_path / "h.json")}
    clear_marker(paths)
    assert not paths.resume.exists()
    clear_marker(paths)
