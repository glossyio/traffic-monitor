"""The clean-up after a healthy switch.

In this order: the throwaway image tags go; then the tags in our image repositories that no build unit and no stage
rule names; then dangling images (the stage tags Prepare made keep the first stage of each two-stage build, so the
build cache stays); then base images of earlier versions that nothing uses. Then each image is built once more from
the staged folders, to check every step still comes from the cache (a miss rebuilds it now, while the internet is
likely there, not at the next boot), in the update's slice with its low weights. Last, the older source trees,
Ansible venvs, and run logs. The work folder goes after the run has ended (remove_work_folder).

The update is already healthy: a step that fails is logged and noted, and the next step runs. Nothing here raises.
"""

import json
import re
import shutil
import subprocess
import traceback
from dataclasses import dataclass
from pathlib import Path

from . import playbook, proc
from .switch import say

SLICE = "tm-update.slice"  # tmsetup_update_slice: Prepare's builds run there
SLICE_PROPERTIES = ("CPUWeight=20", "IOWeight=20")  # tmsetup_update_slice_properties
CHECK_TAG = "prepare-check"
LOGS_KEPT = 10
_LIST_TIMEOUT = 120
_REMOVE_TIMEOUT = 300
_BUILD_TIMEOUT = 3600  # a miss rebuilds Frigate's ffmpeg, which takes minutes
_IMAGE_ID = re.compile(r"[A-Za-z0-9]{1,100}")
_NAME = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")
_TAG = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}")
_THROWAWAY = re.compile(r"prepare-[^\s:/]+")
_COMMIT = re.compile(r"[0-9a-f]{40}")
_STEP = re.compile(r"STEP \d+/\d+:")
_FROM_STEP = re.compile(r"STEP \d+/\d+: FROM")


@dataclass(frozen=True)
class Image:
    """One image of `podman images`: its id, its names (repository:tag), and its repository digests."""

    id: str
    names: "tuple[str, ...]"
    digests: "tuple[str, ...]"


@dataclass(frozen=True)
class Built:
    """One image an update builds, from facts.json."""

    name: str
    repository: str
    tag: str
    stages: "tuple[str, ...]"
    context: Path


class _StepFailed(Exception):
    """A step that couldn't finish, for a reason it has already logged."""


def _texts(value: object) -> "tuple[str, ...]":
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, str) and item and not item.startswith("-"))


def list_images(log) -> "list[Image] | None":
    """`podman images`, type-checked, each image once. None when it can't be listed."""
    try:
        listing = proc.run(["podman", "images", "--format", "json"], timeout=_LIST_TIMEOUT)
        images = json.loads(listing.stdout) if listing.returncode == 0 else None
    except (OSError, ValueError, TypeError, subprocess.SubprocessError):
        images = None
    if not isinstance(images, list):
        say(log, "could not list the images")
        return None
    # Podman lists an image once for each of its names, so one image can be several rows with the same id
    found: "dict[str, Image]" = {}
    for image in images:
        if not isinstance(image, dict) or not isinstance(image.get("Id"), str) or not _IMAGE_ID.fullmatch(image["Id"]):
            continue
        names, digests = _texts(image.get("Names")), _texts(image.get("RepoDigests"))
        earlier = found.get(image["Id"])
        if earlier is not None:
            names = earlier.names + tuple(name for name in names if name not in earlier.names)
            digests = earlier.digests + tuple(digest for digest in digests if digest not in earlier.digests)
        found[image["Id"]] = Image(image["Id"], names, digests)
    return list(found.values())


def untag(image_id: str, name: str, log) -> bool:
    """Take one name off an image. Always with the image id: `podman untag <name>` alone takes every name off it."""
    try:
        return proc.run(["podman", "untag", image_id, name], log=log, timeout=_REMOVE_TIMEOUT).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _split(name: str) -> "tuple[str, str | None]":
    """repository:tag, without a digest. The tag is None when the name has none."""
    name = name.split("@", 1)[0]
    head, colon, tag = name.rpartition(":")
    if colon and "/" not in tag:
        return head, tag
    return name, None


def _qualified(repository: str) -> str:
    """A repository as Podman lists it: a short Docker Hub name gets its registry, and library/ when it has no
    namespace."""
    first, slash, _ = repository.partition("/")
    if not slash:
        return "docker.io/library/" + repository
    if "." in first or ":" in first or first == "localhost":
        return repository
    return "docker.io/" + repository


def _repository(reference: str) -> str:
    return _qualified(_split(reference)[0])


def _note(log, notes: "list[str]", note: str) -> None:
    say(log, f"clean-up note: {note}")
    notes.append(note)


def _step(log, notes: "list[str]", name: str, body):
    """Run one step. A step that fails is logged and noted (step_failed:<name>), and None is returned."""
    try:
        return body()
    except _StepFailed:
        pass
    except Exception as error:
        traceback.print_exc(file=log)
        log.flush()
        say(log, f"clean-up step {name}: unexpected {type(error).__name__}")
    _note(log, notes, f"step_failed:{name}")
    return None


def _built(ctx) -> "list[Built]":
    """facts.json's images, each value checked. Raises _StepFailed when they can't be used."""
    try:
        data = json.loads((ctx.handover.work_dir / "facts.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = None
    images = data.get("images") if isinstance(data, dict) else None
    built = [_one_built(ctx, entry) for entry in images] if isinstance(images, list) else [None]
    if None in built:
        say(ctx.log, "facts.json can't be used; the images are left as they are")
        raise _StepFailed
    return built


def _one_built(ctx, entry: object) -> "Built | None":
    if not isinstance(entry, dict):
        return None
    name, tag, stages, context = (entry.get(key) for key in ("name", "tag", "stages", "context"))
    if not (isinstance(name, str) and _NAME.fullmatch(name) and entry.get("repository") == "localhost/" + name
            and isinstance(tag, str) and _TAG.fullmatch(tag) and isinstance(stages, list)
            and all(isinstance(stage, str) and _TAG.fullmatch(stage) for stage in stages)
            and isinstance(context, str) and Path(context) == ctx.handover.work_dir / "build" / name):
        return None
    return Built(name, "localhost/" + name, tag, tuple(stages), Path(context))


def _settle_tags(log, notes: "list[str]", built: "list[Built]") -> None:
    """Untag the throwaway tags in our repositories, then remove each other tag there that no build unit and no stage
    rule names."""
    images = list_images(log)
    if images is None:
        raise _StepFailed
    named = {image.repository: {image.tag} | {f"stage-{stage}" for stage in image.stages} for image in built}
    throwaway, unnamed = [], []
    for image in images:
        for name in image.names:
            repository, tag = _split(name)
            if repository not in named or tag is None:
                continue
            if _THROWAWAY.fullmatch(tag):
                throwaway.append((image.id, name))
            elif tag not in named[repository]:
                unnamed.append(name)
    for image_id, name in throwaway:
        if not untag(image_id, name, log):
            _note(log, notes, f"kept:{name}")
    for name in unnamed:
        _remove(log, notes, name)


def _remove(log, notes: "list[str]", what: str) -> None:
    """podman rmi, never forced: an image still in use stays, and that is noted, not a failure."""
    try:
        status = proc.run(["podman", "rmi", what], log=log, timeout=_REMOVE_TIMEOUT).returncode
    except (OSError, subprocess.SubprocessError) as error:
        say(log, f"podman rmi: {type(error).__name__}")
        status = None
    if status != 0:
        _note(log, notes, f"kept:{what}")


def _prune(log) -> None:
    status = proc.run(["podman", "image", "prune", "-f"], log=log, timeout=_REMOVE_TIMEOUT).returncode
    if status != 0:
        say(log, f"podman image prune ended with status {status}")
        raise _StepFailed


def _base_references(built: "list[Built]") -> "list[str]":
    """The images the FROM lines of the staged Containerfiles name. A FROM that names an earlier stage, scratch, or a
    build argument is not a base."""
    references = []
    for image in built:
        stages = set()
        for line in (image.context / "Containerfile").read_text(encoding="utf-8").splitlines():
            words = line.split()
            if not words or words[0].upper() != "FROM":
                continue
            words = [word for word in words[1:] if not word.startswith("--")]
            if not words:
                continue
            reference = words[0]
            if reference.lower() not in stages and reference.lower() != "scratch" and "$" not in reference:
                references.append(reference)
            if len(words) >= 3 and words[1].upper() == "AS":
                stages.add(words[2].lower())
    return list(dict.fromkeys(references))


def _inspect_id(reference: str) -> "str | None":
    try:
        result = proc.run(["podman", "image", "inspect", reference], timeout=_LIST_TIMEOUT)
        data = json.loads(result.stdout) if result.returncode == 0 else None
    except (OSError, ValueError, TypeError, subprocess.SubprocessError):
        return None
    if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], dict):
        return None
    image_id = data[0].get("Id")
    return image_id if isinstance(image_id, str) and _IMAGE_ID.fullmatch(image_id) else None


def _base_id(reference: str) -> "str | None":
    """The id of the image a base reference names; a reference pinned by digest is tried by its digest alone too."""
    image_id = _inspect_id(reference)
    if image_id is None and "@" in reference:
        image_id = _inspect_id(_split(reference)[0] + "@" + reference.split("@", 1)[1])
    return image_id


def _remove_old_bases(log, notes: "list[str]", built: "list[Built]") -> None:
    """Remove each image in a repository the Containerfiles build from that no current FROM line names. Nothing is
    removed unless every current base is known."""
    try:
        references = _base_references(built)
    except (OSError, ValueError):
        say(log, "a staged Containerfile can't be read; the base images are left as they are")
        raise _StepFailed from None
    current = set()
    for reference in references:
        image_id = _base_id(reference)
        if image_id is None:
            say(log, "a current base image can't be found; the base images are left as they are")
            raise _StepFailed
        current.add(image_id)
    repositories = {_repository(reference) for reference in references}
    ours = {image.repository for image in built}
    images = list_images(log)
    if images is None:
        raise _StepFailed
    for image in images:
        held = {_repository(name) for name in image.names + image.digests}
        if image.id in current or not held & repositories or held & ours:
            continue
        _remove(log, notes, image.id)


def _count(output: str) -> "tuple[int, int]":
    """A build's steps (FROM lines not counted) and the cache hits among them."""
    steps = hits = 0
    for line in output.splitlines():
        if _STEP.search(line) and not _FROM_STEP.search(line):
            steps += 1
        elif "Using cache" in line:
            hits += 1
    return steps, hits


def _check_cache(log, notes: "list[str]", built: "list[Built]") -> None:
    """Build each image once more, as Prepare built it, under a throwaway tag, and note each that missed the cache."""
    for image in built:
        check = f"{image.repository}:{CHECK_TAG}"
        argv = ["podman", "build", "--pull=missing", f"--cgroup-parent={SLICE}", "--tag", check,
                "--file", "Containerfile", str(image.context)]
        try:
            result = proc.run(argv, timeout=_BUILD_TIMEOUT, cwd=image.context)
        except (OSError, subprocess.SubprocessError) as error:
            say(log, f"the cache check of {image.name}: {type(error).__name__}")
            result = None
        if result is not None:
            for text in (result.stdout, result.stderr):
                if isinstance(text, str) and text:
                    log.write(text if text.endswith("\n") else text + "\n")
            log.flush()
        if result is None or result.returncode != 0:
            _note(log, notes, f"check_failed:{image.name}")
        else:
            steps, hits = _count(result.stdout if isinstance(result.stdout, str) else "")
            say(log, f"the cache check of {image.name}: {hits} of {steps} steps from the cache")
            if hits < steps:
                _note(log, notes, f"cache_rebuilt:{image.name}")
        image_id = _inspect_id(check)
        if image_id is not None and not untag(image_id, check, log):
            _note(log, notes, f"kept:{check}")


def _remove_paths(log, entries) -> bool:
    """Remove each folder (or a link or file in its place). False when any of them stays."""
    removed = True
    for entry in entries:
        try:
            if entry.is_symlink() or not entry.is_dir():
                entry.unlink()
            else:
                shutil.rmtree(entry)
            say(log, f"removed {entry}")
        except OSError as error:
            say(log, f"could not remove {entry}: {type(error).__name__}")
            removed = False
    return removed


def _old_trees(ctx) -> "list[Path]":
    """Source trees but the running one and the one installed before it. Only folders named by a commit id."""
    keep = {ctx.handover.commit}
    before = ctx.state.data.get("from")
    commit = before.get("commit") if isinstance(before, dict) else None
    if isinstance(commit, str) and _COMMIT.fullmatch(commit):
        keep.add(commit)
    tree = Path(ctx.tree).resolve()
    if tree.parent == ctx.paths.src_root.resolve():
        keep.add(tree.name)
    if not ctx.paths.src_root.is_dir():
        return []
    return sorted(entry for entry in ctx.paths.src_root.iterdir()
                  if _COMMIT.fullmatch(entry.name) and entry.name not in keep
                  and entry.is_dir() and not entry.is_symlink())


def _old_venvs(ctx) -> "list[Path]":
    """Ansible venvs but the one this tree's lock names."""
    keep = {playbook.venv_path(Path(ctx.tree) / "script" / "requirements.lock", ctx.paths).name}
    if ctx.venv is not None:
        keep.add(Path(ctx.venv).name)
    if not ctx.paths.venv_root.is_dir():
        return []
    return sorted(entry for entry in ctx.paths.venv_root.iterdir()
                  if entry.name.startswith("ansible-") and entry.name not in keep)


def _old_logs(ctx) -> "list[Path]":
    """Run logs but the ten newest by name. This run's log is never removed and counts as one of the ten."""
    if not ctx.paths.log_dir.is_dir():
        return []
    mine = ctx.handover.log_path.name
    logs = sorted(entry for entry in ctx.paths.log_dir.iterdir()
                  if entry.name.endswith(".log") and entry.name != mine and entry.is_file()
                  and not entry.is_symlink())
    keep = LOGS_KEPT - 1 if ctx.handover.log_path.parent == ctx.paths.log_dir else LOGS_KEPT
    return logs[:max(len(logs) - keep, 0)]


def remove_work_folder(paths, handover, log) -> None:
    """Remove this run's work folder, <work_root>/<run_id>, once the run has ended. Never raises: a folder that stays
    is removed by the next run's clearing of leftovers."""
    work = paths.work_root / handover.run_id
    try:
        if handover.work_dir != work:
            say(log, "the work folder is not <work_root>/<run_id>; it is left as it is")
            return
        if work.exists() or work.is_symlink():
            _remove_paths(log, [work])
    except Exception as error:
        say(log, f"could not remove the work folder: {type(error).__name__}")


def _give_the_slice_its_weights(log) -> None:
    """The weights Prepare gave the slice are runtime properties, which a restart drops."""
    status = proc.run(["systemctl", "set-property", "--runtime", SLICE, *SLICE_PROPERTIES], log=log,
                      timeout=_LIST_TIMEOUT).returncode
    if status != 0:
        say(log, f"systemctl set-property ended with status {status}")
        raise _StepFailed


def _folders(log, notes: "list[str]", name: str, entries) -> None:
    if not _remove_paths(log, entries):
        _note(log, notes, f"step_failed:{name}")


def run(ctx) -> "list[str]":
    """Clean up after a healthy switch. Returns the notes it logged: cache_rebuilt:<name>, check_failed:<name>,
    kept:<image>, step_failed:<step>."""
    log = ctx.log
    notes: "list[str]" = []
    built = _step(log, notes, "facts", lambda: _built(ctx))
    if built:
        _step(log, notes, "tags", lambda: _settle_tags(log, notes, built))
        _step(log, notes, "prune", lambda: _prune(log))
        _step(log, notes, "bases", lambda: _remove_old_bases(log, notes, built))
        _step(log, notes, "slice", lambda: _give_the_slice_its_weights(log))
        _step(log, notes, "cache", lambda: _check_cache(log, notes, built))
    elif built is not None:
        say(log, "facts.json lists no images; the images are left as they are")
    for name, entries in (("trees", _old_trees), ("venvs", _old_venvs), ("logs", _old_logs)):
        _step(log, notes, name, lambda name=name, entries=entries: _folders(log, notes, name, entries(ctx)))
    return notes
