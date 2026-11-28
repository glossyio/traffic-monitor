"""tm-update's clean-up after a healthy switch: the image tags and old images it removes while Podman's build cache
stays, the check that every build still comes from the cache, and the folders and logs it removes."""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from tm_update_support import (COMMIT, OLD_COMMIT, RUN, Device, FakeRun, completed, handover, installed, make_world,
                               one_row_per_name)

from tm_update import cleanup, cli, playbook, proc
from tm_update.cli import Context
from tm_update.state import State

ROLE_VARS = Path(__file__).resolve().parents[1] / "ansible" / "roles" / "tmsetup" / "vars" / "main.yml"

FRIGATE_BASE = "ghcr.io/blakeblackshear/frigate:0.18.2@sha256:" + "f2" * 32
DEBIAN_BASE = "docker.io/library/debian:bookworm-slim@sha256:" + "d1" * 32
NODE_RED_BASE = "docker.io/nodered/node-red:5.0.10@sha256:" + "e1" * 32
NODE_BASE = "docker.io/library/node:22.23.4-alpine@sha256:" + "c1" * 32
NGINX_BASE = "docker.io/library/nginx:1.29.3@sha256:" + "a1" * 32

CONTAINERFILES = {
    "frigate-tm": (f"FROM {DEBIAN_BASE} AS build-ffmpeg\nRUN make\n\nFROM {FRIGATE_BASE}\n"
                   "COPY --from=build-ffmpeg /usr/local/bin/ffmpeg /usr/bin/ffmpeg\n"),
    "node-red-tm": f"FROM {NODE_RED_BASE}\nCOPY data/package.json /data/\n",
    # A FROM that names an earlier stage is not a base, in any letter case
    "revproxy": (f"FROM --platform=linux/arm64 {NODE_BASE} AS ui\nRUN npm ci\nfrom UI as again\nRUN true\n"
                 f"FROM {NGINX_BASE}\nCOPY --from=ui /ui/dist /usr/share/nginx/ui\n"),
}
TAGS = {"frigate-tm": "0.18.2", "node-red-tm": "latest", "revproxy": "latest"}
STAGES = {"frigate-tm": ["build-ffmpeg"], "node-red-tm": [], "revproxy": ["ui"]}
BASE_IDS = {FRIGATE_BASE: "frigatebase2", DEBIAN_BASE: "debian2", NODE_RED_BASE: "nodered5", NODE_BASE: "node22",
            NGINX_BASE: "nginx129"}

IMAGES = [
    {"Id": "frigate2", "Names": ["localhost/frigate-tm:0.18.2", "localhost/frigate-tm:prepare-0123456"]},
    {"Id": "frigate1", "Names": ["localhost/frigate-tm:0.18.1"]},
    {"Id": "ffmpeg2", "Names": ["localhost/frigate-tm:stage-build-ffmpeg"]},
    {"Id": "ffmpegold", "Names": ["localhost/frigate-tm:stage-old"]},
    {"Id": "nodered", "Names": ["localhost/node-red-tm:latest", "localhost/node-red-tm:prepare-0123456"]},
    {"Id": "revproxy", "Names": ["localhost/revproxy:latest", "localhost/revproxy:prepare-0123456"]},
    {"Id": "ui2", "Names": ["localhost/revproxy:stage-ui"]},
    {"Id": "pause", "Names": ["localhost/podman-pause:5.4.2-1"]},
    {"Id": "other", "Names": ["localhost/other:0.1", "localhost/other:prepare-0123456"]},
    {"Id": "ubuntu", "Names": ["docker.io/library/ubuntu:24.04"]},
    {"Id": "frigatebase2", "Names": ["ghcr.io/blakeblackshear/frigate:0.18.2"],
     "RepoDigests": ["ghcr.io/blakeblackshear/frigate@sha256:" + "f2" * 32]},
    {"Id": "frigatebase1", "Names": ["ghcr.io/blakeblackshear/frigate:0.18.1"]},
    {"Id": "debian2", "Names": None, "RepoDigests": ["docker.io/library/debian@sha256:" + "d1" * 32]},
    {"Id": "debian1", "Names": [], "RepoDigests": ["docker.io/library/debian@sha256:" + "d0" * 32]},
    {"Id": "nodered5", "Names": ["docker.io/nodered/node-red:5.0.10"]},
    {"Id": "node22", "Names": ["docker.io/library/node:22.23.4-alpine"]},
    {"Id": "nginx129", "Names": ["docker.io/library/nginx:1.29.3"]},
    {"Id": 7, "Names": ["localhost/frigate-tm:0.17.0"]},
    "not an image",
]

HIT = ("STEP 1/3: FROM docker.io/library/x@sha256:00\nSTEP 2/3: RUN make\n--> Using cache 1111\n"
       "STEP 3/3: COPY a b\n--> Using cache 2222\nCOMMIT\n")
MULTI_STAGE_HIT = ("[1/2] STEP 1/2: FROM docker.io/library/x@sha256:00 AS build-ffmpeg\n[1/2] STEP 2/2: RUN make\n"
                   "--> Using cache 1111\n[2/2] STEP 1/2: FROM docker.io/library/y@sha256:00\n"
                   "[2/2] STEP 2/2: COPY --from=build-ffmpeg a b\n--> Using cache 2222\nCOMMIT\n")
MISS = ("STEP 1/3: FROM docker.io/library/x@sha256:00\nSTEP 2/3: RUN make\n--> Using cache 1111\n"
        "STEP 3/3: COPY a b\n--> 3333\nCOMMIT\n")


class Podman:
    """The answers of a device's Podman: the image list, inspect by reference, build output, and exit statuses."""

    def __init__(self):
        self.images = json.loads(json.dumps(IMAGES))
        self.inspect = dict(BASE_IDS)
        self.inspect.update({f"localhost/{name}:prepare-check": f"check{index}"
                             for index, name in enumerate(TAGS)})
        self.builds = {name: MULTI_STAGE_HIT if name != "node-red-tm" else HIT for name in TAGS}
        self.status = {}  # tuple(argv) -> exit status or an exception

    def __call__(self, call):
        argv = call["argv"]
        answer = self.status.get(tuple(argv))
        if isinstance(answer, BaseException):
            raise answer
        if answer is not None:
            return completed(argv, answer)
        if argv[:2] == ["podman", "images"]:
            return completed(argv, stdout=json.dumps(one_row_per_name(self.images)))
        if argv[:3] == ["podman", "image", "inspect"]:
            if argv[3] in self.inspect:
                return completed(argv, stdout=json.dumps([{"Id": self.inspect[argv[3]]}]))
            return completed(argv, 125, "[]")
        if argv[:2] == ["podman", "build"]:
            name = argv[argv.index("--tag") + 1].split("/")[1].split(":")[0]
            return completed(argv, stdout=self.builds[name])
        return None


@pytest.fixture
def world(tmp_path, monkeypatch):
    paths, tree = make_world(tmp_path)
    hand = handover(paths)
    images = []
    for name, text in CONTAINERFILES.items():
        context = hand.work_dir / "build" / name
        context.mkdir(parents=True)
        (context / "Containerfile").write_text(text)
        images.append({"name": name, "repository": f"localhost/{name}", "tag": TAGS[name],
                       "build_tag": "prepare-0123456", "stages": STAGES[name], "context": str(context)})
    (hand.work_dir / "facts.json").write_text(json.dumps({"tm_control_port": 8090, "images": images}))
    podman = Podman()
    run = FakeRun(podman)
    monkeypatch.setattr(proc, "run", run)
    log = open(tmp_path / "cleanup.log", "a", encoding="utf-8")
    ctx = Context(paths, tree, hand, tmp_path / "handover.json", installed(), State.open(hand, installed(), "0.8.0"),
                  log)
    yield ctx, podman, run
    log.close()


def log_text(ctx):
    ctx.log.flush()
    return Path(ctx.log.name).read_text()


def podman_calls(run, *start):
    return [argv for argv in run.argvs() if argv[:len(start)] == list(start)]


def test_a_throwaway_tag_is_removed_by_image_id_and_full_name(world):
    ctx, podman, run = world
    cleanup.run(ctx)
    untags = podman_calls(run, "podman", "untag")
    for image_id, repository in (("frigate2", "frigate-tm"), ("nodered", "node-red-tm"), ("revproxy", "revproxy")):
        assert ["podman", "untag", image_id, f"localhost/{repository}:prepare-0123456"] in untags
    assert not any("localhost/frigate-tm:prepare-0123456" in argv for argv in podman_calls(run, "podman", "rmi"))


def test_podman_lists_an_image_once_for_each_of_its_names():
    rows = one_row_per_name(IMAGES)
    assert [row["Id"] for row in rows if isinstance(row, dict) and row["Id"] == "frigate2"] == ["frigate2"] * 2
    assert len(rows) > len(IMAGES)


def test_an_image_listed_once_for_each_name_is_one_image(world):
    ctx, podman, run = world
    images = cleanup.list_images(ctx.log)
    assert [image.id for image in images].count("frigate2") == 1
    frigate = next(image for image in images if image.id == "frigate2")
    assert frigate.names == ("localhost/frigate-tm:0.18.2", "localhost/frigate-tm:prepare-0123456")
    assert len({image.id for image in images}) == len(images)


def test_no_command_is_issued_twice_and_each_throwaway_tag_is_untagged_once(world):
    ctx, podman, run = world
    notes = cleanup.run(ctx)
    commands = [tuple(argv) for argv in run.argvs() if argv[:2] != ["podman", "images"]]
    assert len(commands) == len(set(commands))
    for image_id, repository in (("frigate2", "frigate-tm"), ("nodered", "node-red-tm"), ("revproxy", "revproxy")):
        assert commands.count(("podman", "untag", image_id, f"localhost/{repository}:prepare-0123456")) == 1
    assert not [note for note in notes if note.startswith("kept:")]
    for old in ("localhost/frigate-tm:0.18.1", "localhost/frigate-tm:stage-old"):
        assert commands.count(("podman", "rmi", old)) == 1
    for old_base in ("frigatebase1", "debian1"):
        assert commands.count(("podman", "rmi", old_base)) == 1


def test_no_command_untags_with_a_single_argument(world):
    ctx, podman, run = world
    # Every listed image carries throwaway names, and the cache check leaves its own tag
    for image in podman.images:
        if isinstance(image, dict) and isinstance(image.get("Names"), list):
            image["Names"] = image["Names"] + [n.rsplit(":", 1)[0] + ":prepare-abcdef0" for n in image["Names"]
                                                if n.startswith("localhost/")]
    cleanup.run(ctx)
    untags = podman_calls(run, "podman", "untag")
    assert untags
    assert all(len(argv) == 4 and not argv[2].startswith("localhost/") and ":" in argv[3] for argv in untags)


def test_tags_no_build_unit_and_no_stage_names_are_removed(world):
    ctx, podman, run = world
    cleanup.run(ctx)
    removed = [argv[2] for argv in podman_calls(run, "podman", "rmi")]
    assert "localhost/frigate-tm:0.18.1" in removed and "localhost/frigate-tm:stage-old" in removed
    for kept in ("localhost/frigate-tm:0.18.2", "localhost/frigate-tm:stage-build-ffmpeg",
                 "localhost/node-red-tm:latest", "localhost/revproxy:latest", "localhost/revproxy:stage-ui"):
        assert all(kept not in argv for argv in run.argvs())
    for other in ("localhost/podman-pause:5.4.2-1", "localhost/other:0.1", "localhost/other:prepare-0123456",
                  "pause", "other", "localhost/frigate-tm:0.17.0"):
        assert all(other not in argv for argv in run.argvs())
    assert ["podman", "rmi", "localhost/frigate-tm:0.18.1"] in run.argvs()
    assert all("--force" not in argv and "-f" not in argv for argv in podman_calls(run, "podman", "rmi"))


def test_dangling_images_are_pruned_after_the_tags_are_settled(world):
    ctx, podman, run = world
    cleanup.run(ctx)
    argvs = run.argvs()
    prune = argvs.index(["podman", "image", "prune", "-f"])
    assert argvs.count(["podman", "image", "prune", "-f"]) == 1
    settled = [i for i, argv in enumerate(argvs) if argv[:2] == ["podman", "untag"] and "prepare-0123456" in argv[3]]
    settled += [i for i, argv in enumerate(argvs) if argv[:2] == ["podman", "rmi"] and argv[2].startswith("localhost/")]
    bases = [i for i, argv in enumerate(argvs) if argv in (["podman", "rmi", "frigatebase1"],
                                                            ["podman", "rmi", "debian1"])]
    assert settled and bases
    assert max(settled) < prune < min(bases)
    # The old bases are found in a listing made after the prune
    listings = [i for i, argv in enumerate(argvs) if argv[:2] == ["podman", "images"]]
    assert any(prune < i < min(bases) for i in listings)


def test_a_base_no_containerfile_names_any_more_is_removed_without_force(world):
    ctx, podman, run = world
    cleanup.run(ctx)
    base_removals = [argv for argv in podman_calls(run, "podman", "rmi") if not argv[2].startswith("localhost/")]
    assert base_removals == [["podman", "rmi", "frigatebase1"], ["podman", "rmi", "debian1"]]
    # Every base reference of the three Containerfiles was asked for, and none was a stage
    inspected = [argv[3] for argv in podman_calls(run, "podman", "image", "inspect")]
    assert set(BASE_IDS) <= set(inspected)
    assert not any(ref.lower() in ("ui", "build-ffmpeg") for ref in inspected)


def test_a_base_whose_reference_with_its_tag_is_not_found_is_looked_up_by_its_digest(world):
    ctx, podman, run = world
    del podman.inspect[FRIGATE_BASE]
    podman.inspect["ghcr.io/blakeblackshear/frigate@sha256:" + "f2" * 32] = "frigatebase2"
    cleanup.run(ctx)
    assert ["podman", "rmi", "frigatebase2"] not in run.argvs()
    assert ["podman", "rmi", "frigatebase1"] in run.argvs()


def test_no_base_is_removed_when_a_current_one_cannot_be_named(world):
    ctx, podman, run = world
    del podman.inspect[DEBIAN_BASE]
    notes = cleanup.run(ctx)
    assert [argv for argv in podman_calls(run, "podman", "rmi") if not argv[2].startswith("localhost/")] == []
    assert "step_failed:bases" in notes


def test_no_base_is_removed_when_a_containerfile_cannot_be_read(world):
    ctx, podman, run = world
    (ctx.handover.work_dir / "build" / "revproxy" / "Containerfile").unlink()
    notes = cleanup.run(ctx)
    assert [argv for argv in podman_calls(run, "podman", "rmi") if not argv[2].startswith("localhost/")] == []
    assert "step_failed:bases" in notes


def test_an_image_in_a_repository_we_never_build_from_is_left_alone(world):
    ctx, podman, run = world
    podman.images.append({"Id": "otherpause", "Names": ["localhost/podman-pause:5.3.0-1"]})
    cleanup.run(ctx)
    for image_id in ("ubuntu", "pause", "otherpause", "other"):
        assert all(image_id not in argv for argv in run.argvs())
    assert all("docker.io/library/ubuntu:24.04" not in argv for argv in run.argvs())


def test_a_base_still_in_use_is_kept_and_noted(world):
    ctx, podman, run = world
    podman.status[("podman", "rmi", "frigatebase1")] = 2
    notes = cleanup.run(ctx)
    assert "kept:frigatebase1" in notes
    assert ["podman", "rmi", "debian1"] in run.argvs()
    assert "kept:frigatebase1" in log_text(ctx)


def test_each_image_is_built_once_more_and_a_miss_is_noted(world):
    ctx, podman, run = world
    podman.builds["revproxy"] = MISS
    notes = cleanup.run(ctx)
    builds = [call for call in run.calls if call["argv"][:2] == ["podman", "build"]]
    expected = []
    for name in TAGS:
        context = ctx.handover.work_dir / "build" / name
        expected.append((["podman", "build", "--pull=missing", "--cgroup-parent=tm-update.slice", "--tag",
                          f"localhost/{name}:prepare-check", "--file", "Containerfile", str(context)], context))
    assert [(call["argv"], Path(call["cwd"])) for call in builds] == expected
    assert [note for note in notes if note.startswith("cache_rebuilt:")] == ["cache_rebuilt:revproxy"]
    for index, name in enumerate(TAGS):
        assert ["podman", "untag", f"check{index}", f"localhost/{name}:prepare-check"] in run.argvs()
    assert all(argv[-1] != f"localhost/{name}:prepare-check" or argv[:2] != ["podman", "rmi"]
               for argv in run.argvs() for name in TAGS)
    # The output reaches the log; the state holds none of it
    assert "--> 3333" in log_text(ctx)
    assert "3333" not in ctx.paths.state.read_text()
    # The check comes after the old bases and before the folders
    argvs = run.argvs()
    assert argvs.index(["podman", "rmi", "debian1"]) < argvs.index(builds[0]["argv"])


def test_a_check_build_that_fails_is_noted_and_the_others_still_run(world):
    ctx, podman, run = world
    argv = ["podman", "build", "--pull=missing", "--cgroup-parent=tm-update.slice", "--tag",
            "localhost/frigate-tm:prepare-check", "--file", "Containerfile",
            str(ctx.handover.work_dir / "build" / "frigate-tm")]
    podman.status[tuple(argv)] = subprocess.TimeoutExpired(argv, 1)
    notes = cleanup.run(ctx)
    assert "check_failed:frigate-tm" in notes
    assert len(podman_calls(run, "podman", "build")) == 3


def test_the_slice_and_its_weights_are_the_ones_prepare_builds_in():
    text = ROLE_VARS.read_text()
    (line,) = re.findall(r"^tmsetup_update_slice: (\S+)$", text, re.MULTILINE)
    assert cleanup.SLICE == line
    (block,) = re.findall(r"^tmsetup_update_slice_properties:\n((?:  - \S+\n)+)", text, re.MULTILINE)
    assert cleanup.SLICE_PROPERTIES == tuple(re.findall(r"- (\S+)", block))


SET_WEIGHTS = ["systemctl", "set-property", "--runtime", "tm-update.slice", "CPUWeight=20", "IOWeight=20"]


def test_the_slice_gets_its_weights_again_before_the_check_builds(world):
    # A restart between the switch and the clean-up drops the runtime weights Prepare gave the slice
    ctx, podman, run = world
    cleanup.run(ctx)
    argvs = run.argvs()
    assert argvs.count(SET_WEIGHTS) == 1
    first_check = next(i for i, argv in enumerate(argvs) if argv[:2] == ["podman", "build"])
    assert argvs.index(SET_WEIGHTS) == first_check - 1


@pytest.mark.parametrize("problem", [1, OSError("no systemctl")])
def test_a_failing_set_property_is_noted_and_the_check_still_runs(world, problem):
    ctx, podman, run = world
    podman.status[tuple(SET_WEIGHTS)] = problem
    notes = cleanup.run(ctx)
    assert "step_failed:slice" in notes
    assert len(podman_calls(run, "podman", "build")) == 3


def _folders(ctx):
    src, venv, logs = ctx.paths.src_root, ctx.paths.venv_root, ctx.paths.log_dir
    for name in (COMMIT, OLD_COMMIT, "c" * 40, "0123456789" * 4, "C" * 40, "notes"):
        (src / name).mkdir(parents=True)
    (src / ("d" * 40)).write_text("a file, not a tree")
    current = playbook.venv_path(ctx.tree / "script" / "requirements.lock", ctx.paths)
    for name in (current.name, "ansible-000000000000", "ansible-111111111111", "other-env"):
        (venv / name / "bin").mkdir(parents=True)
    logs.mkdir(parents=True)
    older = [f"2026110{day}T000000Z-x{n}.log" for day in range(1, 7) for n in (1, 2)]  # 12, all older than this run
    for age, name in enumerate(reversed(older)):
        (logs / name).write_text("x")
        os.utime(logs / name, (1_700_000_000 - age * 60, 1_700_000_000 - age * 60))
    (logs / (RUN + ".log")).write_text("this run")
    (logs / "README").write_text("not a run log")
    return current, older


def test_the_work_folder_older_trees_older_venvs_and_older_logs_go(world):
    ctx, podman, run = world
    current, older = _folders(ctx)
    cleanup.run(ctx)
    src = ctx.paths.src_root
    assert sorted(entry.name for entry in src.iterdir()) == sorted([COMMIT, OLD_COMMIT, "C" * 40, "notes", "d" * 40])
    assert sorted(entry.name for entry in ctx.paths.venv_root.iterdir()) == sorted([current.name, "other-env"])
    logs = sorted(entry.name for entry in ctx.paths.log_dir.iterdir())
    # The ten newest stay, this run's among them
    assert logs == sorted(older[-9:] + [RUN + ".log", "README"])
    # The work folder goes once the run has ended (remove_work_folder, from cli), not in the clean-up
    assert ctx.handover.work_dir.is_dir()
    cleanup.remove_work_folder(ctx.paths, ctx.handover, ctx.log)
    assert not ctx.handover.work_dir.exists() and ctx.paths.work_root.is_dir()


def test_this_runs_log_stays_whatever_its_name(world, tmp_path):
    ctx, podman, run = world
    _folders(ctx)
    for n in range(12):
        (ctx.paths.log_dir / f"2099010{n % 10}T00000{n // 10}Z-later.log").write_text("x")
    cleanup.run(ctx)
    logs = [entry.name for entry in ctx.paths.log_dir.iterdir() if entry.name.endswith(".log")]
    assert len(logs) == 10 and RUN + ".log" in logs


def test_only_the_running_tree_stays_when_the_one_before_is_unknown(world):
    ctx, podman, run = world
    ctx.state._data["from"]["commit"] = None
    _folders(ctx)
    cleanup.run(ctx)
    assert sorted(entry.name for entry in ctx.paths.src_root.iterdir()) == sorted([COMMIT, "C" * 40, "notes",
                                                                                   "d" * 40])


def test_no_tree_is_removed_when_the_commit_was_installed_again(world):
    # A switch that failed late left the manifest naming the new commit, so which tree came before is unknown
    ctx, podman, run = world
    ctx.state._data["from"]["commit"] = COMMIT
    _folders(ctx)
    cleanup.run(ctx)
    assert sorted(entry.name for entry in ctx.paths.src_root.iterdir()) == sorted(
        [COMMIT, OLD_COMMIT, "c" * 40, "0123456789" * 4, "C" * 40, "notes", "d" * 40])


def test_the_ten_newest_logs_are_chosen_by_time_not_by_name(world):
    ctx, podman, run = world
    logs = ctx.paths.log_dir
    logs.mkdir(parents=True)
    names = [f"run-{letter}.log" for letter in "abcdefghijkl"]  # 12; the later the name, the older the file
    for age, name in enumerate(reversed(names)):
        (logs / name).write_text("x")
        os.utime(logs / name, (1_700_000_000 + age * 60, 1_700_000_000 + age * 60))
    (logs / (RUN + ".log")).write_text("this run")
    os.utime(logs / (RUN + ".log"), (1_600_000_000, 1_600_000_000))  # even an old clock keeps this run's log
    cleanup.run(ctx)
    kept = sorted(entry.name for entry in logs.iterdir())
    assert kept == sorted(names[:9] + [RUN + ".log"])


def test_no_venv_is_removed_when_the_current_one_cannot_be_named(world):
    ctx, podman, run = world
    _folders(ctx)
    (ctx.tree / "script" / "requirements.lock").unlink()
    notes = cleanup.run(ctx)
    assert len(list(ctx.paths.venv_root.iterdir())) == 4
    assert "step_failed:venvs" in notes


@pytest.mark.parametrize("facts", ["", "[]", '{"images": "x"}', '{"images": [{"name": 5}]}',
                                   '{"images": [{"name": "revproxy", "repository": "localhost/revproxy", '
                                   '"tag": "latest", "build_tag": "prepare-0123456", "stages": ["ui"], '
                                   '"context": "/elsewhere"}]}'])
def test_facts_that_cannot_be_used_skip_the_images_but_not_the_folders(world, facts):
    ctx, podman, run = world
    (ctx.handover.work_dir / "facts.json").write_text(facts)
    _folders(ctx)
    notes = cleanup.run(ctx)
    assert run.argvs() == []
    assert "step_failed:facts" in notes
    assert not (ctx.paths.src_root / ("c" * 40)).exists()
    assert not (ctx.paths.venv_root / "ansible-000000000000").exists()


def test_a_failing_step_does_not_fail_the_cleanup(world, monkeypatch):
    ctx, podman, run = world
    _folders(ctx)
    podman.status[("podman", "images", "--format", "json")] = OSError("podman is gone")
    podman.status[("podman", "image", "prune", "-f")] = subprocess.TimeoutExpired(["podman"], 1)
    real_rmtree = shutil.rmtree

    def rmtree(path, *args, **kwargs):
        if Path(path).name == "c" * 40:
            raise PermissionError("busy")
        return real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(cleanup.shutil, "rmtree", rmtree)
    notes = cleanup.run(ctx)
    assert "step_failed:prune" in notes and "step_failed:trees" in notes
    # Later steps still ran
    assert podman_calls(run, "podman", "build")
    assert not (ctx.paths.venv_root / "ansible-000000000000").exists()
    assert "PermissionError" in log_text(ctx)


def _device_with_images(tmp_path, monkeypatch):
    """A whole run whose Prepare stages the three images and whose Podman lists the images above."""
    device = Device(tmp_path, monkeypatch)
    device.images = json.loads(json.dumps(IMAGES))
    real = device._run_playbook

    def with_images(venv, tree, name, vars_file, hand, log, tags=None, *, timeout):
        status = real(venv, tree, name, vars_file, hand, log, tags, timeout=timeout)
        if tags == ["stage"]:
            images = []
            for image, text in CONTAINERFILES.items():
                context = hand.work_dir / "build" / image
                context.mkdir(parents=True)
                (context / "Containerfile").write_text(text)
                images.append({"name": image, "repository": f"localhost/{image}", "tag": TAGS[image],
                               "build_tag": "prepare-0123456", "stages": STAGES[image], "context": str(context)})
            (hand.work_dir / "facts.json").write_text(json.dumps({"tm_control_port": 8090, "images": images}))
        return status

    monkeypatch.setattr(playbook, "run_playbook", with_images)
    return device


def test_no_command_of_a_whole_run_untags_with_a_single_argument(tmp_path, monkeypatch):
    device = _device_with_images(tmp_path, monkeypatch)
    assert device.main() == 0
    untags = [argv for argv in device.run.argvs() if argv[:2] == ["podman", "untag"]]
    # The dead run's tags first, then the clean-up's: each with the image id and one full name
    assert len(untags) >= 4 and all(len(argv) == 4 and ":" in argv[3] for argv in untags)
    assert device.state()["result"] == "ok"


@pytest.mark.parametrize("breaks", ["a step", "the whole clean-up"])
def test_a_failing_step_does_not_fail_the_update(tmp_path, monkeypatch, breaks):
    device = _device_with_images(tmp_path, monkeypatch)
    if breaks == "a step":
        answer = device.run.answer

        def broken(call):
            if call["argv"][:3] == ["podman", "image", "prune"]:
                raise OSError("podman is gone")
            return answer(call)

        device.run.answer = broken
    else:
        def boom(ctx):
            raise RuntimeError("clean-up trouble")

        monkeypatch.setattr(cleanup, "run", boom)
    assert device.main() == 0
    state = device.state()
    assert (state["result"], state["reason"], state["detail"]) == ("ok", None, None)
    assert [row["id"] for row in state["stages"]][-2:] == ["health", "cleanup"]
    assert all(row["finished_at"] for row in state["stages"])
    assert not device.paths.resume.exists()
    assert not device.work.exists()
    log = device.log()
    assert ("OSError" if breaks == "a step" else "RuntimeError") in log
    if breaks == "a step":
        assert ["podman", "image", "prune", "-f"] in device.run.argvs()


def test_a_run_cleans_up_once_after_the_health_check(tmp_path, monkeypatch):
    device = Device(tmp_path, monkeypatch)
    seen = []
    monkeypatch.setattr(cleanup, "run", lambda ctx: seen.append(ctx.handover.run_id) or [])
    assert device.main() == 0
    assert seen == [RUN]


@pytest.mark.parametrize("command", ["run", "resume"])
def test_the_work_folder_goes_after_the_run_has_ended(tmp_path, monkeypatch, command):
    device = Device(tmp_path, monkeypatch)
    if command == "resume":
        from test_tm_update_cli import _cut_off
        _cut_off(device, "cleanup", boot_id="99999999-8888-7777-6666-555555555555")
    seen = []
    real_rmtree = shutil.rmtree

    def rmtree(path, *args, **kwargs):
        if Path(path) == device.work:
            seen.append((json.loads(device.paths.state.read_text())["result"], device.paths.resume.exists()))
        return real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(cleanup.shutil, "rmtree", rmtree)
    assert (device.main() if command == "run" else device.resume()) == 0
    assert seen == [("ok", False)]
    assert not device.work.exists() and device.paths.work_root.is_dir()


def test_a_work_folder_that_will_not_go_does_not_change_the_end(tmp_path, monkeypatch):
    device = Device(tmp_path, monkeypatch)
    real_rmtree = shutil.rmtree

    def rmtree(path, *args, **kwargs):
        if Path(path) == device.work:
            raise PermissionError("busy")
        return real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(cleanup.shutil, "rmtree", rmtree)
    assert device.main() == 0
    assert device.state()["result"] == "ok" and device.work.is_dir()
    assert "PermissionError" in device.log()


def test_a_failed_run_keeps_its_work_folder(tmp_path, monkeypatch):
    device = Device(tmp_path, monkeypatch)
    device.unit_state["frigate.service"] = "failed"
    assert device.main() == 1
    assert device.work.is_dir()
