"""tm-update's reading of the installed manifest, and the refusals that come before anything changes."""

import grp
import json
import os
import re
from pathlib import Path

import pytest
from tm_update_support import OLD_COMMIT, installed, make_world, manifest

from tm_update import installed as installed_module
from tm_update.installed import (
    OPTIONS_KEPT_IN_FILES,
    OPTIONS_PASSED_BACK,
    OPTIONS_REFUSED,
    Refusal,
    check_before_prepare,
    check_database_space,
    read,
    space_needed,
)
from tm_update.state import Failed

MISSING = object()
NOT_JSON = object()
TMSETUP = Path(__file__).resolve().parents[1] / "tmsetup.sh"


def world(tmp_path, data):
    paths, _ = make_world(tmp_path, with_manifest=False)
    if data is MISSING:
        return paths
    if data is NOT_JSON:
        paths.manifest.write_text("{not json")
    else:
        paths.manifest.write_text(json.dumps(data))
    return paths


def reason_of(call, *args):
    with pytest.raises(Refusal) as error:
        call(*args)
    return error.value


def test_a_good_manifest_is_read(tmp_path):
    paths = world(tmp_path, manifest())
    result = read(paths)
    assert (result.tm_version, result.commit, result.installing_user) == ("0.7.1", OLD_COMMIT, "pi")
    assert result.codedir == Path("/opt/traffic-monitor") and result.codeowner == "tmadmin"
    assert result.repo == "example/traffic-monitor-test" and result.plate_recognizer is False


def test_the_group_is_the_one_that_owns_the_code_folder_on_disk(tmp_path):
    paths = world(tmp_path, manifest())
    expected = grp.getgrgid(os.stat(paths.root / "opt" / "traffic-monitor").st_gid).gr_name
    assert read(paths).codegroup == expected


@pytest.mark.parametrize("data", [MISSING, NOT_JSON, [], {"installing_user": "root"}, {"installing_user": ""},
                                  {"installing_user": 5}, {"installing_user": None}, {"codedir": None},
                                  {"codedir": "relative"}, {"codedir": "/opt/../etc"}, {"codeowner": ""},
                                  {"tm_version": 7}, {"git": {"commit": 5}}, {"git": "x"}, {"git": {}},
                                  {"options": []}, {"options": {"plate_recognizer": "yes"}},
                                  {"update": {"repo": 5}}, {"update": "x"}])
def test_a_manifest_the_update_cannot_trust_means_a_manual_update(tmp_path, data):
    if isinstance(data, dict):
        data = manifest(**data)
    error = reason_of(read, world(tmp_path, data))
    assert error.reason == "needs_manual_update"
    assert isinstance(error, Failed)


@pytest.mark.parametrize("repo", ["..", "owner/..", "./x", "a/b/c", "a b/c", "owner/", "/x", "x", "a/.", "a/b\n", ""])
def test_a_repository_that_is_not_plain_owner_and_name_means_a_manual_update(tmp_path, repo):
    error = reason_of(read, world(tmp_path, manifest(update={"repo": repo})))
    assert error.reason == "needs_manual_update"


@pytest.mark.parametrize("repo", ["glossyio/traffic-monitor", "a.b/c_d-e", "x/.hidden"])
def test_an_ordinary_repository_is_kept(tmp_path, repo):
    assert read(world(tmp_path, manifest(update={"repo": repo}))).repo == repo


def test_a_manifest_from_before_the_update_block_still_reads(tmp_path):
    data = manifest()
    del data["update"]
    del data["options"]
    result = read(world(tmp_path, data))
    assert result.repo is None and result.plate_recognizer is False


def test_a_missing_code_folder_means_a_manual_update(tmp_path):
    paths = world(tmp_path, manifest(codedir="/srv/elsewhere"))
    assert reason_of(read, paths).reason == "needs_manual_update"


def test_the_addon_is_refused_by_its_option_or_by_its_unit_file(tmp_path):
    paths = world(tmp_path, manifest(options={"plate_recognizer": True}))
    assert read(paths).plate_recognizer is True
    assert reason_of(check_before_prepare, installed(plate_recognizer=True), paths).reason == "addon_needs_installer"
    paths = world(tmp_path / "b", manifest())
    paths.plate_recognizer_unit.parent.mkdir(parents=True)
    paths.plate_recognizer_unit.write_text("[Container]\n")
    assert reason_of(check_before_prepare, installed(), paths).reason == "addon_needs_installer"
    assert read(paths).plate_recognizer is True


def test_every_installer_option_is_in_exactly_one_of_the_three_lists():
    text = TMSETUP.read_text()
    names = re.search(r"declare -a _VALID_CUSTOM_VARS=\(([^)]*)\)", text).group(1)
    valid = re.findall(r'"([a-z_]+)"', names)
    listed = [*OPTIONS_PASSED_BACK, *OPTIONS_KEPT_IN_FILES, *OPTIONS_REFUSED]
    assert sorted(listed) == sorted(valid)
    assert len(set(listed)) == len(listed)


def test_a_waiting_restart_is_refused(tmp_path, monkeypatch):
    paths = world(tmp_path, manifest())
    monkeypatch.setattr(installed_module, "_free_bytes", lambda path: 10**12)
    paths.reboot_required.parent.mkdir(parents=True)
    paths.reboot_required.write_text("*** System restart required ***\n")
    assert reason_of(check_before_prepare, installed(), paths).reason == "reboot_pending"


def test_space_needed_is_8_gb_plus_1_2_times_the_database():
    assert space_needed(2_500_000_000) == 11_000_000_000
    assert space_needed(0) == 8_000_000_000
    assert space_needed(1) == 8_000_000_002


def test_too_little_space_reports_both_numbers(tmp_path, monkeypatch):
    paths = world(tmp_path, manifest())
    (paths.root / "opt" / "traffic-monitor" / "node-red-tm" / "db" / "tmdb.sqlite").write_bytes(b"x" * 1000)
    monkeypatch.setattr(installed_module, "_free_bytes", lambda path: 7_500_000_000)
    error = reason_of(check_before_prepare, installed(), paths)
    assert error.reason == "low_space"
    assert error.detail == "7500 MB free, 8000 MB needed"


def test_enough_space_passes(tmp_path, monkeypatch):
    paths = world(tmp_path, manifest())
    monkeypatch.setattr(installed_module, "_free_bytes", lambda path: 8_000_000_000)
    check_before_prepare(installed(), paths)


def test_the_database_space_check_wants_1_2_times_the_database(tmp_path, monkeypatch):
    db = tmp_path / "db"
    (db / "node-red-tm" / "db").mkdir(parents=True)
    (db / "node-red-tm" / "db" / "tmdb.sqlite").write_bytes(b"x" * 1000)
    seen = []
    monkeypatch.setattr(installed_module, "_free_bytes", lambda path: seen.append(path) or 1199)
    error = reason_of(check_database_space, installed(codedir=db))
    assert error.reason == "low_space" and error.detail == "0 MB free, 0 MB needed"
    monkeypatch.setattr(installed_module, "_free_bytes", lambda path: 1200)
    check_database_space(installed(codedir=db))
    assert seen


def test_a_database_that_is_missing_counts_as_empty(tmp_path, monkeypatch):
    paths = world(tmp_path, manifest())
    monkeypatch.setattr(installed_module, "_free_bytes", lambda path: 8_000_000_000)
    check_before_prepare(installed(), paths)
