"""tm-update's command line: run, and resume (which carries a run on after a restart)."""

import argparse
import fcntl
import grp
import json
import os
import re
import shutil
import subprocess
import sys
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import IO

from . import installed as installed_module
from . import playbook, proc, restore
from .handover import CONTRACT, Handover, HandoverError, load
from .installed import Installed, Refusal, check_before_prepare
from .paths import Paths
from .state import Failed, State

# The reason a stage's failure takes when nothing more exact is known
STAGE_REASON = {"prepare": "prepare_failed", "images": "build_failed", "restore_point": "prepare_failed"}
_BUILD_TAG = re.compile(r"localhost/[^\s:]+:prepare-[^\s:]+")
_IMAGE_ID = re.compile(r"[A-Za-z0-9]{1,100}")


@dataclass
class Context:
    """What every stage is handed."""

    paths: Paths
    tree: Path
    handover: Handover
    handover_path: Path
    installed: Installed
    state: State
    log: IO[str]
    venv: "Path | None" = None


def _say(log, text: str) -> None:
    log.write(datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") + " " + text + "\n")
    log.flush()


def _complain(text: str) -> None:
    print("tm-update: " + text, file=sys.stderr)


def _make_dir(path: Path) -> None:
    """A folder this command creates is root's and open to read (0755), whatever the umask."""
    if not path.is_dir():
        path.mkdir(parents=True, exist_ok=True)
        path.chmod(0o755)


def _open_file(path: Path, flags: int, mode: int) -> int:
    """Open a file, creating it with exactly this mode when it is new and never replacing one that is there."""
    try:
        fd = os.open(path, flags | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, mode)
        os.fchmod(fd, mode)
        return fd
    except FileExistsError:
        return os.open(path, flags | os.O_CLOEXEC)


def _open_log(path: Path) -> IO[str]:
    _make_dir(path.parent)
    return os.fdopen(_open_file(path, os.O_WRONLY | os.O_APPEND, 0o640), "a", encoding="utf-8")


def _give_log_to_group(log: IO[str], group: str) -> None:
    try:
        os.fchown(log.fileno(), -1, grp.getgrnam(group).gr_gid)
    except (OSError, KeyError):
        _say(log, "the log keeps its own group")


def _take_lock(paths: Paths) -> "int | None":
    """The run lock tmsetup.sh takes too. The descriptor stays open for the rest of the run; None when it is held."""
    _make_dir(paths.update_dir)
    fd = _open_file(paths.lock, os.O_RDONLY, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        return None
    return fd


def _read_update_json(tree: Path) -> "tuple[list, str]":
    try:
        data = json.loads((tree / "script" / "update.json").read_text(encoding="utf-8"))
        contracts, version = data["contracts"], data["tm_version"]
    except (OSError, ValueError, KeyError, TypeError):
        raise ValueError("the tree has no readable script/update.json") from None
    # bool is a kind of int and 1.0 equals 1, so neither may pass for the number 1
    if (not isinstance(contracts, list) or not all(type(number) is int for number in contracts)
            or not isinstance(version, str) or not version):
        raise ValueError("script/update.json is not valid")
    return contracts, version


def _clear_leftovers(ctx: Context) -> None:
    """What a run that died left: other runs' work folders and the throwaway image tags of earlier builds."""
    log = ctx.log
    work_root = ctx.paths.work_root
    if work_root.is_dir():
        for entry in work_root.iterdir():
            if entry.name == ctx.handover.run_id:
                continue
            try:
                if entry.is_symlink() or not entry.is_dir():
                    entry.unlink()
                else:
                    shutil.rmtree(entry)
                _say(log, "removed the work folder of an earlier run")
            except OSError:
                _say(log, "could not remove the work folder of an earlier run")
    try:
        listing = proc.run(["podman", "images", "--format", "json"], timeout=120)
        images = json.loads(listing.stdout) if listing.returncode == 0 else []
    except (OSError, ValueError, subprocess.TimeoutExpired):
        _say(log, "could not list the images")
        return
    if not isinstance(images, list):
        return
    for image in images:
        if not isinstance(image, dict) or not isinstance(image.get("Id"), str):
            continue
        names = image.get("Names")
        if not isinstance(names, list) or not _IMAGE_ID.fullmatch(image["Id"]):
            continue
        for name in names:
            if isinstance(name, str) and _BUILD_TAG.fullmatch(name):
                # Always with the image id: untag with one argument takes every name off the image
                try:
                    proc.run(["podman", "untag", image["Id"], name], log=log, timeout=120)
                except (OSError, subprocess.TimeoutExpired):
                    _say(log, "could not remove an image tag of an earlier build")


def _prepare_work_dir(ctx: Context) -> None:
    # The settings dry run reads <work>/check-venv as the code owner, so nothing on the way is 0700
    _make_dir(ctx.paths.work_root)
    _make_dir(ctx.handover.work_dir)


def _run_prepare_half(ctx: Context, stage: str, tags: "list[str]") -> None:
    default = STAGE_REASON[stage]
    ctx.state.begin(stage)
    _say(ctx.log, f"stage {stage}")
    if ctx.venv is None:
        ctx.venv = playbook.ensure_venv(ctx.tree, ctx.paths, ctx.log)
    vars_file = playbook.write_vars(ctx.handover, ctx.installed, ctx.tree, update_mode=True)
    status = playbook.run_playbook(ctx.venv, ctx.tree, "update_prepare.yml", vars_file, ctx.handover, ctx.log,
                                   tags=tags)
    if status != 0:
        raise Failed(playbook.reason_from(ctx.handover, default), f"playbook exit status {status}")
    ctx.state.finish(stage)


def _restore_point(ctx: Context) -> None:
    ctx.state.begin("restore_point")
    _say(ctx.log, "stage restore_point")
    tree = ctx.paths.src_root / ctx.installed.commit
    folder = restore.make(ctx.installed, ctx.handover, ctx.paths, tree if tree.is_dir() else None)
    restore.keep_newest(ctx.paths)
    ctx.state.set(restore_point=str(folder))
    ctx.state.finish("restore_point")


def _stages(ctx: Context) -> None:
    _run_prepare_half(ctx, "prepare", ["stage"])
    _run_prepare_half(ctx, "images", ["images"])
    _restore_point(ctx)


def _fail(state: State, log, failure: Failed) -> int:
    _say(log, f"failed: {failure.reason}" + (f" ({failure.detail})" if failure.detail else ""))
    state.end("failed", failure.reason, failure.detail)
    _complain(failure.reason)
    return 1


def _run(paths: Paths, tree: Path, handover: Handover, handover_path: Path, to_version: str, log) -> int:
    lock = _take_lock(paths)
    if lock is None:
        # The state file belongs to the run that holds the lock
        _say(log, "busy")
        _complain("busy")
        return 1
    try:
        installed = None
        refusal = None
        try:
            installed = installed_module.read(paths)
        except Refusal as error:
            refusal = error
        state = State.open(handover, installed, to_version)
        if refusal is not None:
            return _fail(state, log, refusal)
        _give_log_to_group(log, installed.codegroup)
        ctx = Context(paths, tree, handover, handover_path, installed, state, log)
        try:
            _clear_leftovers(ctx)
            _prepare_work_dir(ctx)
            check_before_prepare(installed, paths)
            _stages(ctx)
        except Failed as failure:
            return _fail(state, log, failure)
        except Exception as error:
            traceback.print_exc(file=log)
            log.flush()
            default = STAGE_REASON.get(state.data["stage"], "prepare_failed")
            return _fail(state, log, Failed(default, f"unexpected {type(error).__name__}"))
        _say(log, "done")
        state.end("ok")
        return 0
    finally:
        os.close(lock)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tm-update", description="Install the tree this command lives in.")
    commands = parser.add_subparsers(dest="command", required=True, metavar="{run,resume}")
    run = commands.add_parser("run", help="install this tree")
    run.add_argument("--contract", type=int, required=True, help="the hand-over contract number (1)")
    run.add_argument("--handover", type=Path, required=True, help="the hand-over file")
    resume = commands.add_parser("resume", help="carry a run on after a restart")
    resume.add_argument("--contract", type=int, default=CONTRACT, help="the hand-over contract number (1)")
    resume.add_argument("--handover", type=Path, required=True, help="the hand-over file")
    return parser


def main(argv: "list[str] | None" = None, *, paths: "Paths | None" = None, tree: "Path | None" = None,
         is_root=None) -> int:
    """0: ended ok; 1: ended failed (or busy); 2: no usable hand-over, or not root."""
    args = _parser().parse_args(argv)
    paths = paths or Paths()
    tree = tree or Path(__file__).resolve().parents[2]
    if not (is_root or (lambda: os.geteuid() == 0))():
        _complain("this command must run as root")
        return 2
    try:
        handover = load(args.handover, paths)
        contracts, to_version = _read_update_json(tree)
    except (HandoverError, ValueError) as error:
        _complain(str(error))
        return 2
    if args.contract != CONTRACT or args.contract not in contracts:
        _complain("this tree does not accept that contract")
        return 2
    if args.command == "resume":
        _complain("resume is not available yet")
        return 1
    try:
        log = _open_log(handover.log_path)
    except OSError:
        _complain("the log can't be opened")
        return 1
    try:
        return _run(paths, tree, handover, args.handover, to_version, log)
    except Exception as error:
        traceback.print_exc(file=log)
        _complain(f"unexpected {type(error).__name__}")
        return 1
    finally:
        log.close()
