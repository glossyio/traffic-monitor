"""What an update (script/tm-update) leaves on a device.

Each test skips on a device that has never run an update, which is one with no state file. Nothing here starts an
update, and nothing reads a secret: the restore point is listed, never opened. See docs/development/software-update.md
for the files and what the clean-up leaves.
"""

import json
import re

import pytest
from devpi_checks import read_root_file, role_vars

UPDATE_DIR = role_vars()["tmsetup_update_dir"]
STATE = f"{UPDATE_DIR}/state.json"
RESUME_MARKER = f"{UPDATE_DIR}/resume.json"
RESTORE_ROOT = "/var/lib/traffic-monitor/restore"
MANIFEST = f"{role_vars()['tmsetup_etc_dir']}/manifest.json"
THROWAWAY_TAG = re.compile(r"localhost/[^/:]+:prepare-.+")


@pytest.fixture(scope="module")
def update_state(usable_host):
    """The state file of the last update, parsed; skips when the device has never run one."""
    if not usable_host.file(STATE).exists:
        pytest.skip(f"no {STATE}: this device has never run an update")
    try:
        state = json.loads(read_root_file(usable_host, STATE))
    except ValueError:
        pytest.fail(f"{STATE} isn't JSON")
    assert isinstance(state, dict), f"{STATE} isn't a JSON object"
    return state


def finished_ok(state):
    if state.get("result") != "ok":
        pytest.skip(f"the last update's result is {state.get('result')!r}, not 'ok'")


def image_names(host):
    """Every name (repository:tag) of every image in the rootful Podman storage."""
    with host.sudo():
        images = json.loads(host.check_output("podman images --format json"))
    return [name for image in images for name in (image.get("Names") or [])]


def test_no_throwaway_tag_is_left(host, update_state):
    """After a run that ended ok, no image has a throwaway tag (localhost/<name>:prepare-<commit>, or the clean-up's
    own prepare-check). A run that failed or is still going may leave them: the next run removes them."""
    if update_state.get("result") != "ok":
        pytest.skip(f"the last update's result is {update_state.get('result')!r}; its throwaway tags go when a run "
                    "ends ok or the next run starts")
    left = sorted(name for name in image_names(host) if THROWAWAY_TAG.fullmatch(name))
    assert not left, f"throwaway image tags left after an update that ended ok: {left}"


def test_every_first_stage_has_its_tag_after_an_update(host, update_state):
    """After an update that ended ok, each first stage of a two-stage build has its stage tag
    (localhost/<name>:stage-<stage>), so `podman image prune` doesn't take the build cache. The images and stages are
    the checkout's tmsetup_update_images, which is what the update's tree named when this checkout is what's deployed."""
    finished_ok(update_state)
    names = set(image_names(host))
    wanted = [f"localhost/{image['name']}:stage-{stage}"
              for image in role_vars()["tmsetup_update_images"] for stage in image["stages"]]
    assert wanted, "tmsetup_update_images names no stage; this test has nothing to check"
    missing = [tag for tag in wanted if tag not in names]
    assert not missing, f"stage tags missing: {missing}"


def test_the_last_updates_commit_is_the_manifests(host, update_state):
    """After an update that ended ok, the manifest names the commit the update installed, and says its tree had no
    changes (an update's tree comes from `git archive`). A later install, which rewrites the manifest, skips this."""
    finished_ok(update_state)
    with host.sudo():
        manifest_time = int(host.check_output(f"stat -c %Y {MANIFEST}"))
        state_time = int(host.check_output(f"stat -c %Y {STATE}"))
    if manifest_time > state_time:
        pytest.skip("the manifest was written after the last update ended, by a later install")
    manifest = json.loads(read_root_file(host, MANIFEST))
    git = manifest.get("git") or {}
    commit = (update_state.get("to") or {}).get("commit")
    problems = []
    if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit):
        problems.append("the state file's to.commit isn't a full commit id")
    elif git.get("commit") != commit:
        problems.append("the manifest's git.commit isn't the state file's to.commit")
    if git.get("modified") is not False:
        problems.append(f"the manifest's git.modified is {git.get('modified')!r}, not false")
    assert not problems, "; ".join(problems)


def test_no_resume_marker_outlives_a_finished_run(host, update_state):
    """A run that ended, ok or failed, leaves no resume.json: a restart would otherwise start tm-update again."""
    if update_state.get("result") not in ("ok", "failed"):
        pytest.skip(f"the last update's result is {update_state.get('result')!r}; a run in progress or handed over "
                    "to a restart keeps its marker")
    assert not host.file(RESUME_MARKER).exists, f"{RESUME_MARKER} is there, but the run ended"


def test_the_restore_point_is_roots_alone(host, update_state):
    """The restore point holds secrets, so its folder, each restore point in it, and each one's restore.json are
    root's alone (0700 for the folders, 0600 for the list). It lists them with find and never reads one."""
    if update_state.get("restore_point") is None:
        pytest.skip("the last update ended before it saved a restore point")
    with host.sudo():
        root = host.check_output(f"stat -c '%a %U %G' {RESTORE_ROOT}")
        found = host.check_output(f"find {RESTORE_ROOT} -mindepth 1 -maxdepth 2 "
                                  r"-printf '%P\t%y\t%m\t%u\t%g\n'")
    problems = []
    if root != "700 root root":
        problems.append(f"{RESTORE_ROOT} is {root!r}, not '700 root root'")
    rows = [line.split("\t") for line in found.splitlines() if line.strip()]
    rows = [row for row in rows if not row[0].split("/")[0].endswith(".partial")]  # one being made
    folders = [row for row in rows if "/" not in row[0]]
    if not folders:
        problems.append("the folder holds no restore point")
    for path, kind, mode, owner, group in rows:
        depth = path.count("/")
        if depth == 0 and (kind, mode, owner, group) != ("d", "700", "root", "root"):
            problems.append(f"restore point {path}: {kind} {mode} {owner}:{group}, not a 700 root:root folder")
        elif depth == 1 and path.endswith("/restore.json") and (kind, mode, owner, group) != ("f", "600", "root",
                                                                                              "root"):
            problems.append(f"{path}: {kind} {mode} {owner}:{group}, not a 600 root:root file")
        elif depth == 1 and kind == "d" and mode != "700":
            problems.append(f"{path}: folder mode {mode}, not 700")
    assert not problems, "; ".join(problems)
