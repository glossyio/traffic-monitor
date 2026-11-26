"""The update job, run as a script against a temporary root and a local bare repository (fixtures/job_update_world.py).

It reads a hostile request, fetches the recorded repository into a mirror, checks the request against that fetch,
unpacks the tree, and hands over to the tree's own script/tm-update, which the stub here records.
"""

import fcntl
import importlib.machinery
import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))

from job_update_world import JOB, REPO_NAME, RUN_ID, World, set_user_version, update_json  # noqa: E402

SYSTEM_PATH = "/usr/sbin:/usr/bin:/sbin:/bin"
FRESH_KEYS = {"schema", "run_id", "channel", "from", "to", "stage", "stages", "result", "reason", "detail", "boot_id",
              "reboot", "restore_point", "tmdb_backup", "switch_attempts"}


@pytest.fixture
def world(tmp_path):
    return World(tmp_path)


def failed_with(world, result, reason):
    assert result.returncode == 1, result.stdout + result.stderr
    state = world.state()
    assert (state["result"], state["reason"]) == ("failed", reason), state
    assert all(row["finished_at"] for row in state["stages"])
    return state


def nothing_unpacked(world, commit):
    assert world.ran() is None
    assert not (world.src / commit).exists()
    assert not (world.src / (commit + ".partial")).exists()
    assert not (world.update_dir / "work" / RUN_ID).exists()


def test_the_job_is_executable():
    assert os.access(JOB, os.X_OK)
    assert JOB.read_text().startswith("#!/usr/bin/python3\n")


@pytest.mark.parametrize("change", [
    "missing key", "extra key", "run_id ../x", "channel beta", "commit HEAD", "commit None", "tag 3", "not JSON",
    "a list"])
def test_a_request_that_is_not_the_four_keys_of_the_right_types_ends_64_and_is_deleted(world, change):
    good = {"run_id": RUN_ID, "channel": "development", "commit": world.ids["dev"], "tag": None}
    bodies = {
        "missing key": {k: v for k, v in good.items() if k != "tag"},
        "extra key": dict(good, url="https://example.invalid/x.git"),
        "run_id ../x": dict(good, run_id="../x"),
        "channel beta": dict(good, channel="beta"),
        "commit HEAD": dict(good, commit="HEAD"),
        "commit None": dict(good, commit=None),
        "tag 3": dict(good, tag=3),
        "not JSON": "{",
        "a list": "[]",
    }
    body = bodies[change]
    request = world.request(body if isinstance(body, str) else json.dumps(body))
    result = world.run(request)
    assert result.returncode == 64, result.stdout + result.stderr
    assert not request.exists()
    assert len(result.stdout.strip().splitlines()) == 1
    assert not world.state_path.exists()
    assert not (world.src / "repo.git").exists()


@pytest.mark.parametrize("manifest", ["not JSON", "codeowner 5"])
def test_a_manifest_that_names_no_code_owner_ends_64(world, manifest):
    if manifest == "not JSON":
        world.manifest_path.write_text("{")
    else:
        world.write_manifest(codeowner=5)
    result = world.run()
    assert result.returncode == 64, result.stdout + result.stderr
    assert len(result.stdout.strip().splitlines()) == 1
    assert not world.state_path.exists()


def test_a_request_from_another_owner_or_through_a_link_ends_64(world):
    request = world.request()
    link = world.jobs / "link.json"
    link.symlink_to(request)
    assert world.run(link).returncode == 64
    assert world.ran() is None


def test_a_held_lock_ends_75_and_leaves_the_state_file_alone(world):
    world.write_state(run_id="20261101T000000Z", result="failed", reason="busy")
    before = world.state_path.read_bytes()
    fd = os.open(world.update_dir / "lock", os.O_RDONLY | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = world.run()
    finally:
        os.close(fd)
    assert result.returncode == 75, result.stdout + result.stderr
    assert len(result.stdout.strip().splitlines()) == 1
    assert world.state_path.read_bytes() == before
    assert not (world.src / "repo.git").exists()


def test_with_a_resume_marker_the_launcher_runs_and_no_run_starts(world):
    world.write_state(run_id="20261101T000000Z", stage="switch", result=None)
    before = world.state_path.read_bytes()
    (world.update_dir / "resume.json").write_text("{}")
    world.launcher()
    request = world.request()
    result = world.run(request)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads((world.root / "launcher-ran.json").read_text()) == []
    assert not request.exists()
    assert world.state_path.read_bytes() == before
    assert not (world.src / "repo.git").exists()
    assert world.ran() is None


def test_a_good_development_request_hands_over_to_the_trees_tm_update(world):
    result = world.run()
    assert result.returncode == 0, result.stdout + result.stderr
    commit = world.ids["dev"]
    handover = world.handover_path()
    ran = world.ran()
    assert ran["argv"] == ["run", "--contract", "1", "--handover", str(handover)]
    assert ran["lock_free"] is True
    assert ran["tree"] == str(world.src / commit)
    assert not (world.src / (commit + ".partial")).exists()
    data = json.loads(handover.read_text())
    assert data == {
        "contract": 1, "run_id": RUN_ID, "channel": "development", "commit": commit, "tag": None,
        "from_version": "0.8.0", "work_dir": str(world.update_dir / "work" / RUN_ID),
        "state_path": str(world.state_path), "log_path": str(world.update_dir / "log" / (RUN_ID + ".log")),
    }
    assert handover.stat().st_mode & 0o777 == 0o644
    state = world.state()
    assert set(state) == FRESH_KEYS
    assert world.state_path.stat().st_mode & 0o777 == 0o644
    assert [row["id"] for row in state["stages"]] == ["fetch", "verify"]
    assert all(row["started_at"] and row["finished_at"] for row in state["stages"])
    assert state["stage"] == "verify"
    assert state["result"] is None and state["reason"] is None
    assert state["from"] == {"version": "0.8.0", "commit": world.ids["v080"]}
    assert state["to"] == {"version": "0.8.2-dev", "commit": commit, "tag": None}
    assert state["run_id"] == RUN_ID and state["channel"] == "development" and state["switch_attempts"] == 0
    # The tree is as git archive made it, with modes from umask 022, and git's output is never one of the job's lines
    assert (world.src / commit / "README").stat().st_mode & 0o777 == 0o644
    assert (world.src / commit / "script" / "tm-update").stat().st_mode & 0o777 == 0o755
    assert (world.src / "repo.git").is_dir()
    assert (world.update_dir / "lock").stat().st_mode & 0o777 == 0o644


def test_a_good_stable_request_needs_its_tag(world):
    world.write_manifest(update={"repo": REPO_NAME, "channel": "stable"})
    refused = world.run(world.request(channel="stable", commit=world.ids["v081"], tag=None))
    failed_with(world, refused, "stale_check")
    nothing_unpacked(world, world.ids["v081"])
    result = world.run(world.request(channel="stable", commit=world.ids["v081"], tag="v0.8.1"))
    assert result.returncode == 0, result.stdout + result.stderr
    assert world.ran()["argv"][:3] == ["run", "--contract", "1"]
    state = world.state()
    assert state["to"] == {"version": "0.8.1", "commit": world.ids["v081"], "tag": "v0.8.1"}
    assert json.loads(world.handover_path().read_text())["tag"] == "v0.8.1"


CASES = [
    ("commit not on dev", "stale_check"), ("commit not in the mirror", "stale_check"),
    ("commit an annotated tag's id", "stale_check"),
    ("tag on development", "stale_check"), ("tag not a version", "stale_check"),
    ("tag names another commit", "stale_check"), ("tag not on main", "stale_check"),
    ("target behind installed", "not_forward"), ("target is installed, last run ok", "not_forward"),
    ("target is installed, no last run", "not_forward"), ("target is installed, last run to another commit",
                                                         "not_forward"),
    ("installed unknown, development", "not_forward"), ("installed unknown, stable, same version", "not_forward"),
    ("installed not in the mirror, stable, older version", None),
    ("no script/tm-update", "target_not_updatable"), ("no script/update.json", "target_not_updatable"),
    ("update.json not JSON", "target_not_updatable"), ("update.json a list", "target_not_updatable"),
    ("update.json without tm_version", "target_not_updatable"),
    ("update.json tmdb_schema text", "target_not_updatable"),
    ("tag v0.8.1 but tm_version 0.8.2", "target_not_updatable"), ("contracts [2]", "needs_manual_update"),
    ("contracts ['1']", "needs_manual_update"), ("contracts [true]", "needs_manual_update"),
    ("contracts 1", "needs_manual_update"),
    ("tmdb user_version above tmdb_schema", "schema_newer"),
    ("state.sqlite user_version above state_schema", "schema_newer"),
    ("manifest repo 'a/..'", "needs_manual_update"), ("manifest without update", "needs_manual_update"),
    ("manifest codedir None", "needs_manual_update"), ("manifest codedir with ..", "needs_manual_update"),
    ("manifest without tm_version", "needs_manual_update"), ("manifest git.commit HEAD", "needs_manual_update"),
    ("remote missing", "fetch_failed"),
]
TREE_CHANGES = {
    "no script/tm-update": {"dev": {"script/tm-update": None}},
    "no script/update.json": {"dev": {"script/update.json": None}},
    "update.json not JSON": {"dev": {"script/update.json": "{"}},
    "update.json a list": {"dev": {"script/update.json": "[1]"}},
    "update.json without tm_version": {"dev": {"script/update.json": json.dumps({"contracts": [1], "tmdb_schema": 11,
                                                                                "state_schema": 7})}},
    "update.json tmdb_schema text": {"dev": {"script/update.json": update_json("0.8.2-dev", tmdb_schema="11")}},
    "tag v0.8.1 but tm_version 0.8.2": {"v081": {"script/update.json": update_json("0.8.2")}},
    "contracts [2]": {"dev": {"script/update.json": update_json("0.8.2-dev", contracts=[2])}},
    "contracts ['1']": {"dev": {"script/update.json": update_json("0.8.2-dev", contracts=["1"])}},
    "contracts [true]": {"dev": {"script/update.json": update_json("0.8.2-dev", contracts=[True])}},
    "contracts 1": {"dev": {"script/update.json": update_json("0.8.2-dev", contracts=1)}},
}


def stable(world, name, tag):
    world.write_manifest(update={"repo": REPO_NAME, "channel": "stable"})
    return world.request(channel="stable", commit=world.ids[name], tag=tag)


def arrange(world, case):
    """The request for a case, after setting up the device for it. The default is development to dev's head."""
    ids = world.ids
    if case == "commit not on dev":
        return world.request(commit=ids["side"])
    if case == "commit not in the mirror":
        return world.request(commit="c" * 40)
    if case == "commit an annotated tag's id":
        return world.request(commit=ids["annotated"])
    if case == "tag on development":
        return world.request(tag="v0.8.2")
    if case == "tag not a version":
        return stable(world, "v081", "v0.8.1^{tree}")
    if case == "tag names another commit":
        return stable(world, "v081", "v0.8.0")
    if case == "tag not on main":
        return stable(world, "side", "v0.9.0")
    if case == "target behind installed":
        world.install("v081", "0.8.1")
        return world.request(commit=ids["v080"])
    if case.startswith("target is installed"):
        world.install("dev", "0.8.2-dev")
        if case.endswith("last run ok"):
            world.write_state(run_id="20261101T000000Z", to={"commit": ids["dev"]}, result="ok")
        if case.endswith("another commit"):
            world.write_state(run_id="20261101T000000Z", to={"commit": ids["v081"]}, result="failed")
        return world.request()
    if case == "installed unknown, development":
        world.install("unknown", "0.8.0")
        return world.request()
    if case == "installed unknown, stable, same version":
        world.install("unknown", "0.8.1")
        return stable(world, "v081", "v0.8.1")
    if case == "installed not in the mirror, stable, older version":
        world.install("d" * 40, "0.8.0")
        return stable(world, "v081", "v0.8.1")
    if case == "tag v0.8.1 but tm_version 0.8.2":
        return stable(world, "v081", "v0.8.1")
    if case == "tmdb user_version above tmdb_schema":
        set_user_version(world.codedir / "node-red-tm/db/tmdb.sqlite", 12)
        set_user_version(world.root / "var/lib/tm-control/state.sqlite", 7)
    if case == "state.sqlite user_version above state_schema":
        set_user_version(world.codedir / "node-red-tm/db/tmdb.sqlite", 11)
        set_user_version(world.root / "var/lib/tm-control/state.sqlite", 8)
    if case == "manifest repo 'a/..'":
        world.write_manifest(update={"repo": "a/..", "channel": "development"})
    if case == "manifest without update":
        del world.manifest["update"]
        world.write_manifest()
    if case == "manifest codedir None":
        world.write_manifest(codedir=None)
    if case == "manifest codedir with ..":
        world.write_manifest(codedir="/opt/../etc")
    if case == "manifest without tm_version":
        del world.manifest["tm_version"]
        world.write_manifest()
    if case == "manifest git.commit HEAD":
        world.write_manifest(git={"commit": "HEAD", "branch": "main", "modified": False})
    if case == "remote missing":
        world.remote = world.tmp / "no-such-remote.git"
    return world.request()


@pytest.mark.parametrize(("case", "reason"), CASES)
def test_each_refusal_takes_its_code_changes_nothing_and_exits_1(tmp_path, case, reason):
    world = World(tmp_path, TREE_CHANGES.get(case))
    request = arrange(world, case)
    target = json.loads(request.read_text())["commit"]
    result = world.run(request)
    if reason is None:  # the one allowed case in the table, beside its refused neighbours
        assert result.returncode == 0, result.stdout + result.stderr
        assert world.ran() is not None
        return
    state = failed_with(world, result, reason)
    nothing_unpacked(world, target)
    assert state["run_id"] == RUN_ID and state["to"]["commit"] == target
    assert set(state) == FRESH_KEYS
    assert state["detail"] is None or (isinstance(state["detail"], str) and len(state["detail"]) <= 200)
    assert not request.exists()


@pytest.mark.parametrize("last_result", ["failed", None])
def test_the_same_commit_runs_again_only_after_a_run_to_it_that_did_not_end_ok(world, last_result):
    world.install("dev", "0.8.2-dev")
    world.write_state(run_id="20261101T000000Z", to={"commit": world.ids["dev"]}, result=last_result,
                      reason="switch_failed" if last_result else None)
    result = world.run()
    assert result.returncode == 0, result.stdout + result.stderr
    assert world.ran()["argv"][:3] == ["run", "--contract", "1"]
    assert world.state()["from"] == {"version": "0.8.2-dev", "commit": world.ids["dev"]}


def test_an_installed_commit_git_does_not_know_is_compared_by_version_on_stable(world):
    world.install("unknown", "0.8.0-dev")
    result = world.run(stable(world, "v080", "v0.8.0"))
    assert result.returncode == 0, result.stdout + result.stderr
    assert world.state()["from"] == {"version": "0.8.0-dev", "commit": None}
    world.install("unknown", "0.8.1")
    failed_with(world, world.run(stable(world, "v081", "v0.8.1")), "not_forward")


def test_a_half_made_tree_and_a_stale_work_folder_are_replaced(world):
    commit = world.ids["dev"]
    for folder in (world.src / (commit + ".partial"), world.src / commit, world.update_dir / "work" / RUN_ID):
        folder.mkdir(parents=True)
        (folder / "left-behind").write_text("x")
    result = world.run()
    assert result.returncode == 0, result.stdout + result.stderr
    assert not (world.src / (commit + ".partial")).exists()
    assert not (world.src / commit / "left-behind").exists()
    assert (world.src / commit / "script" / "update.json").is_file()
    assert not (world.update_dir / "work" / RUN_ID / "left-behind").exists()
    assert world.handover_path().is_file()


def test_unknown_keys_in_update_json_are_ignored(tmp_path):
    world = World(tmp_path, {"dev": {"script/update.json": update_json("0.8.2-dev", later_key={"a": 1})}})
    result = world.run()
    assert result.returncode == 0, result.stdout + result.stderr
    assert world.state()["to"]["version"] == "0.8.2-dev"


def git_options(argv):
    """The -c settings before git's subcommand."""
    settings = []
    for index, arg in enumerate(argv):
        if arg == "-c":
            settings.append(argv[index + 1])
    return settings


SETTINGS = ["protocol.allow=never", "protocol.https.allow=always", "http.followRedirects=false",
            "http.lowSpeedLimit=1000", "http.lowSpeedTime=60", "transfer.fsckObjects=true", "core.hooksPath=/dev/null",
            "gc.auto=0"]


def test_git_never_follows_a_redirect_reads_no_config_and_uses_only_https(world):
    result = world.run(git=world.recording_git())
    assert result.returncode == 0, result.stdout + result.stderr
    calls = world.git_calls()
    assert any("init" in call["argv"] for call in calls)
    assert any("fetch" in call["argv"] for call in calls)
    assert any("archive" in call["argv"] for call in calls)
    for call in calls:
        settings = git_options(call["argv"])
        assert settings[:len(SETTINGS)] == SETTINGS
        # The test seam's local repository needs git's file transport, and nothing else is added
        assert settings[len(SETTINGS):] == ["protocol.file.allow=always"]
        env = call["env"]
        assert env["GIT_CONFIG_GLOBAL"] == "/dev/null"
        assert env["GIT_CONFIG_NOSYSTEM"] == "1"
        assert env["GIT_TERMINAL_PROMPT"] == "0"
        assert env["PATH"] == SYSTEM_PATH
        assert not {key for key in env if key.startswith("GIT_")} - {
            "GIT_CONFIG_GLOBAL", "GIT_CONFIG_NOSYSTEM", "GIT_TERMINAL_PROMPT"}
        assert "TM_UPDATE_ROOT" not in env and "TM_CONTROL_MANIFEST" not in env
    fetch = next(call["argv"] for call in calls if "fetch" in call["argv"])
    assert fetch[fetch.index("fetch"):] == [
        "fetch", "--no-tags", "--prune", "--force", str(world.remote), "+refs/heads/main:refs/heads/main",
        "+refs/heads/dev:refs/heads/dev", "+refs/tags/v*:refs/tags/v*"]


def test_no_address_comes_from_the_request(world):
    request = world.request(json.dumps({"run_id": RUN_ID, "channel": "development", "commit": world.ids["dev"],
                                        "tag": None, "url": str(world.remote)}))
    assert world.run(request, remote=False, git=world.recording_git()).returncode == 64
    assert world.git_calls() == []
    # Without the test seam the address is GitHub's, from the manifest's repository alone (the recording git refuses
    # the fetch, so nothing reaches the network)
    result = world.run(remote=False, git=world.recording_git())
    failed_with(world, result, "fetch_failed")
    fetch = next(call["argv"] for call in world.git_calls() if "fetch" in call["argv"])
    assert f"https://github.com/{REPO_NAME}.git" in fetch
    assert not any(str(world.remote) in arg for call in world.git_calls() for arg in call["argv"])
    assert "protocol.file.allow=always" not in sum((call["argv"] for call in world.git_calls()), [])


def test_the_repository_rule_is_a_function_of_the_manifest():
    spec = importlib.util.spec_from_loader("tm_job_update_rule", importlib.machinery.SourceFileLoader(
        "tm_job_update_rule", str(JOB)))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.repo_of({"update": {"repo": REPO_NAME}}) == REPO_NAME
    for manifest in ({}, {"update": None}, {"update": {"repo": "a/.."}}):
        with pytest.raises(module.Refused) as refused:
            module.repo_of(manifest)
        assert refused.value.code == "needs_manual_update"
