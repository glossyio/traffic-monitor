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

from . import health, playbook, proc, restore, switch
from . import installed as installed_module
from .handover import CONTRACT, Handover, HandoverError, load
from .installed import Installed, Refusal, check_before_prepare
from .paths import Paths
from .state import Failed, State, clear_marker

# The reason a stage's failure takes when nothing more exact is known
STAGE_REASON = {"prepare": "prepare_failed", "images": "build_failed", "restore_point": "prepare_failed",
                "switch": "switch_failed", "reboot": "switch_failed", "health": "health_failed"}
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
    vars_file: "Path | None" = None
    # CLOCK_MONOTONIC (µs) just before this process stopped the units; 0 when no switch ran in this boot's process
    switch_monotonic_usec: int = 0


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
    restore.keep_newest(ctx.paths, just_made=folder)
    ctx.state.set(restore_point=str(folder))
    ctx.state.finish("restore_point")


def _switch(ctx: Context) -> bool:
    """The switch, and the restart it may want. True: the health check is next. False: the device is restarting, and
    tm-update resume carries the run on."""
    ctx.state.begin("switch")
    _say(ctx.log, "stage switch")
    switch.run(ctx)
    ctx.state.finish("switch")
    if not switch.wants_reboot(ctx.handover):
        ctx.state.set(reboot=False)
        return True
    ctx.state.begin("reboot")
    _say(ctx.log, "stage reboot")
    ctx.state.set(reboot=True, boot_id=switch.boot_id(ctx.paths))
    switch.restart(ctx)
    return False


def _health(ctx: Context) -> None:
    ctx.state.begin("health")
    _say(ctx.log, "stage health")
    health.wait(ctx, since_monotonic_usec=ctx.switch_monotonic_usec)
    health.record_tmdb_backup(ctx)
    ctx.state.finish("health")


def _after_health(ctx: Context) -> None:
    """What follows a healthy switch before the run ends ok: the one place for the clean-up stage, for a run and for
    a resumed one."""


def _from_the_switch(ctx: Context) -> bool:
    if not _switch(ctx):
        return False
    _health(ctx)
    _after_health(ctx)
    return True


def _stages(ctx: Context) -> bool:
    """Every stage of a run, in order. False when the run was handed over to a restart."""
    _run_prepare_half(ctx, "prepare", ["stage"])
    _run_prepare_half(ctx, "images", ["images"])
    _restore_point(ctx)
    return _from_the_switch(ctx)


def _carry_on(ctx: Context, stage: str) -> bool:
    """The rest of a run a restart cut off at this stage. The cut-off stage's row is closed and the stage begins
    again. False when the run was handed over to a restart again."""
    if stage == "reboot":
        ctx.state.finish("reboot")
        _health(ctx)
        _after_health(ctx)
        return True
    if stage == "switch":
        ctx.state.finish("switch")
        attempts = ctx.state.data["switch_attempts"]
        if attempts >= switch.ATTEMPTS:
            switch.start_again(ctx)
            raise Failed("switch_failed", f"{attempts} attempts")
        return _from_the_switch(ctx)
    if stage == "health":
        ctx.state.finish("health")
        _health(ctx)
        _after_health(ctx)
        return True
    if stage == "cleanup":
        ctx.state.finish("cleanup")
        _after_health(ctx)
        return True
    # Nothing in use changed before the switch, and the run can't know what it was doing
    raise Failed(STAGE_REASON.get(stage, "prepare_failed"), "cut off before the switch")


def _fail(state: State, log, failure: Failed, paths: Paths) -> int:
    """End the run as failed. No marker outlives a run that ended."""
    _say(log, f"failed: {failure.reason}" + (f" ({failure.detail})" if failure.detail else ""))
    state.end("failed", failure.reason, failure.detail)
    clear_marker(paths)
    _complain(failure.reason)
    return 1


def _guarded(ctx: Context, body) -> int:
    """Run body(ctx) and end the run as it leaves it. 0: ended ok, or handed over to a restart; 1: ended failed."""
    try:
        finished = body(ctx)
    except Failed as failure:
        return _fail(ctx.state, ctx.log, failure, ctx.paths)
    except Exception as error:
        traceback.print_exc(file=ctx.log)
        ctx.log.flush()
        default = STAGE_REASON.get(ctx.state.data["stage"], "prepare_failed")
        return _fail(ctx.state, ctx.log, Failed(default, f"unexpected {type(error).__name__}"), ctx.paths)
    if not finished:
        _say(ctx.log, "handed over to a restart")
        return 0
    _say(ctx.log, "done")
    ctx.state.end("ok")
    clear_marker(ctx.paths)
    return 0


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
            return _fail(state, log, refusal, paths)
        _give_log_to_group(log, installed.codegroup)
        ctx = Context(paths, tree, handover, handover_path, installed, state, log)

        def body(ctx: Context) -> bool:
            _clear_leftovers(ctx)
            _prepare_work_dir(ctx)
            check_before_prepare(installed, paths)
            return _stages(ctx)

        return _guarded(ctx, body)
    finally:
        os.close(lock)


class _MarkerError(ValueError):
    pass


def _read_marker(paths: Paths) -> "dict | None":
    """resume.json, type-checked: {"contract": 1, "tree", "handover"}. None when there is none."""
    try:
        data = json.loads(paths.resume.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        raise _MarkerError from None
    if not isinstance(data, dict) or type(data.get("contract")) is not int or data["contract"] != CONTRACT:
        raise _MarkerError
    for key in ("tree", "handover"):
        if not isinstance(data.get(key), str) or not data[key].startswith("/") or "\x00" in data[key]:
            raise _MarkerError
    return data


def _resume(paths: Paths, tree: Path, handover: Handover, handover_path: Path, log) -> int:
    lock = _take_lock(paths)
    if lock is None:
        _say(log, "busy")
        _complain("busy")
        return 1
    try:
        try:
            marker = _read_marker(paths)
        except _MarkerError:
            _say(log, "the resume marker can't be used; removed")
            clear_marker(paths)
            _complain("the resume marker can't be used")
            return 2
        if marker is None:
            _say(log, "nothing to carry on")
            return 0
        if (Path(marker["tree"]).resolve() != tree.resolve()
                or Path(marker["handover"]).resolve() != handover_path.resolve()):
            # It is another run's to carry on: leave it for that one
            _say(log, "the resume marker names another tree or hand-over")
            _complain("the resume marker names another tree or hand-over")
            return 2
        state = State.carry_on(handover)
        if state is None:
            _say(log, "nothing to carry on; the run has ended")
            clear_marker(paths)
            return 0
        stage = state.data["stage"]
        now = switch.boot_id(paths)
        if stage == "reboot" and now is not None and now == state.data["boot_id"]:
            _say(log, "the restart has not happened yet")
            return 0
        try:
            installed = installed_module.read(paths)
        except Refusal as refusal:
            return _fail(state, log, refusal, paths)
        _give_log_to_group(log, installed.codegroup)
        _say(log, f"resume at stage {stage}")
        ctx = Context(paths, tree, handover, handover_path, installed, state, log)
        return _guarded(ctx, lambda ctx: _carry_on(ctx, stage))
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
    """0: ended ok, handed over to a restart, or nothing to carry on; 1: ended failed (or busy); 2: no usable
    hand-over or resume marker, or not root."""
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
    # The marker names the hand-over by this path, for a restart to carry the run on from any folder
    handover_path = Path(os.path.abspath(args.handover))
    try:
        log = _open_log(handover.log_path)
    except OSError:
        _complain("the log can't be opened")
        return 1
    try:
        if args.command == "resume":
            return _resume(paths, tree, handover, handover_path, log)
        return _run(paths, tree, handover, handover_path, to_version, log)
    except Exception as error:
        traceback.print_exc(file=log)
        _complain(f"unexpected {type(error).__name__}")
        return 1
    finally:
        log.close()
