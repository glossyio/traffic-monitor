"""tm-update's hand-over file (contract 1): every value is checked for its type before it is used."""

import json

import pytest
from tm_update_support import handover_dict, make_world

from tm_update import handover as handover_module
from tm_update.handover import HandoverError, load

KEYS = ["contract", "run_id", "channel", "commit", "tag", "from_version", "work_dir", "state_path", "log_path"]


def write(tmp_path, data):
    path = tmp_path / "handover.json"
    path.write_text(data if isinstance(data, str) else json.dumps(data))
    return path


@pytest.fixture
def paths(tmp_path):
    return make_world(tmp_path)[0]


def test_a_good_hand_over_loads(tmp_path, paths):
    loaded = load(write(tmp_path, handover_dict(paths)), paths)
    assert loaded.run_id == "20261125T101500Z-abc"
    assert loaded.channel == "stable"
    assert loaded.tag == "v0.8.0"
    assert loaded.work_dir == paths.work_root / loaded.run_id
    assert loaded.state_path == paths.state


def test_a_null_tag_is_allowed(tmp_path, paths):
    assert load(write(tmp_path, handover_dict(paths, tag=None)), paths).tag is None


def test_the_development_channel_is_allowed(tmp_path, paths):
    assert load(write(tmp_path, handover_dict(paths, channel="development")), paths).channel == "development"


def test_an_unknown_key_is_ignored(tmp_path, paths):
    assert load(write(tmp_path, {**handover_dict(paths), "later": 1}), paths).commit == "a" * 40


@pytest.mark.parametrize("change", [{"commit": None}, {"commit": "HEAD"}, {"commit": 1}, {"commit": "A" * 40},
                                    {"commit": "a" * 39}, {"channel": "beta"}, {"contract": 2}, {"contract": "1"},
                                    {"contract": True}, {"work_dir": "/tmp/x"}, {"work_dir": 5}, {"run_id": "../x"},
                                    {"run_id": "a\n"}, {"run_id": "x" * 65}, {"tag": 3}, {"from_version": None},
                                    {"state_path": "relative/state.json"}, {"log_path": ["x"]}])
def test_a_hand_over_with_a_wrong_value_is_refused(tmp_path, paths, change):
    with pytest.raises(HandoverError) as error:
        load(write(tmp_path, handover_dict(paths, **change)), paths)
    key = next(iter(change))
    assert key in str(error.value)
    for value in change.values():
        if isinstance(value, str) and key != "contract":
            assert value not in str(error.value)


@pytest.mark.parametrize("key", KEYS)
def test_a_missing_key_is_refused(tmp_path, paths, key):
    data = handover_dict(paths)
    del data[key]
    with pytest.raises(HandoverError) as error:
        load(write(tmp_path, data), paths)
    assert key in str(error.value)


def test_paths_outside_the_updates_folder_are_refused(tmp_path, paths):
    for key in ("work_dir", "state_path", "log_path"):
        with pytest.raises(HandoverError):
            load(write(tmp_path, handover_dict(paths, **{key: str(tmp_path / "elsewhere")})), paths)


def test_a_path_that_leaves_the_folder_through_dot_dot_is_refused(tmp_path, paths):
    sneaky = str(paths.update_dir / "work" / ".." / ".." / "restore")
    for key in ("work_dir", "state_path", "log_path"):
        with pytest.raises(HandoverError):
            load(write(tmp_path, handover_dict(paths, **{key: sneaky})), paths)


def test_the_updates_folder_itself_is_not_a_work_folder(tmp_path, paths):
    with pytest.raises(HandoverError):
        load(write(tmp_path, handover_dict(paths, work_dir=str(paths.update_dir))), paths)


@pytest.mark.parametrize("text", ["", "not json", "[]", "5", "null"])
def test_a_file_that_is_not_a_json_object_is_refused(tmp_path, paths, text):
    with pytest.raises(HandoverError):
        load(write(tmp_path, text), paths)


def test_a_missing_file_is_refused(tmp_path, paths):
    with pytest.raises(HandoverError):
        load(tmp_path / "nothing.json", paths)


def test_the_module_names_contract_1():
    assert handover_module.CONTRACT == 1
