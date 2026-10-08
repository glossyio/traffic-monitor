#!/usr/bin/env python3
"""Deploy to dev Pis, run commands on them, and record PR checks in the local run log.

Hosts and their connection details come from the dev-Pi inventory, and every deploy,
command, and check lands in the run log (see devlog.py and README.md). Run it with the
repo's dev venv, from any directory:

    .venv/bin/python script/devpi/tmdev.py pi-login
    .venv/bin/python script/devpi/tmdev.py hosts
    .venv/bin/python script/devpi/tmdev.py deploy tm-dev-01 -- -t revproxy
    .venv/bin/python script/devpi/tmdev.py run tm-dev-01 -- systemctl is-active frigate.service
"""

import argparse
import collections
import json
import os
import re
import shlex
import subprocess
import sys
import time
from contextlib import nullcontext
from pathlib import Path

import devlog
from devlog import DevPiError

SSH_OPTIONS = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=10"]
# On-Pi deploys copy the working tree here (relative to the login's home), minus git-ignored
# files and what tmsetup.sh doesn't use; docs/ alone is about 34 MB.
ON_PI_DIR = "tm-src"
ON_PI_EXCLUDES = ["/.git", "/.venv", "/docs", "/static"]
STATUSES = ("pass", "fail", "manual", "skip")
# The Pi login tmdev uses: key-only, with passwordless sudo, separate from the owner's account.
DEFAULT_LOGIN = "tmdev"
DEFAULT_KEY = "tm_dev"
LOGIN_NAME = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
PUBLIC_KEY = re.compile(r"^(ssh-|ecdsa-|sk-)\S+ \S+")


def log(message):
    print(f"tmdev: {message}", file=sys.stderr, flush=True)


def get_host(name):
    hosts = devlog.load_hosts()
    if name not in hosts:
        raise DevPiError(f"unknown host {name!r}; the inventory has: {', '.join(hosts)}")
    return hosts[name]


def ssh_command(name, hostvars):
    """Return the ssh argv (without a remote command) and the user@host destination for an inventory host."""
    options = list(SSH_OPTIONS)
    if key := hostvars.get("ansible_ssh_private_key_file"):
        options += ["-i", str(Path(key).expanduser())]
    if port := hostvars.get("ansible_port"):
        options += ["-p", str(port)]
    host = hostvars.get("ansible_host", name)
    user = hostvars.get("ansible_user")
    return ["ssh", *options], f"{user}@{host}" if user else host


def stream(argv, save_to=None, shell=False, cwd=None):
    """Run argv, echo its redacted output, optionally save that output too, and return the exit code."""
    with (subprocess.Popen(argv, shell=shell, executable="/bin/bash" if shell else None, cwd=cwd,
                           stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           text=True, errors="replace") as proc,
          open(save_to, "w") if save_to else nullcontext() as saved):
        for line in proc.stdout:
            line = devlog.redact(line)
            sys.stdout.write(line)
            sys.stdout.flush()
            if saved:
                saved.write(line)
    return proc.returncode


def source_tree(path):
    """A checkout to deploy or check instead of this one: the top of a git work tree with script/tmsetup.sh."""
    path = Path(path).expanduser().resolve()
    top = subprocess.run(["git", "-C", str(path), "rev-parse", "--show-toplevel"],
                         capture_output=True, text=True).stdout.strip()
    if not top or Path(top) != path or not (path / "script" / "tmsetup.sh").is_file():
        raise DevPiError(f"{path} isn't the top of a traffic-monitor checkout (a git work tree with script/tmsetup.sh)")
    return path


# --- PR checks -------------------------------------------------------------------------------

def active_marker():
    return devlog.log_dir() / "active-check"


def active_check():
    marker = active_marker()
    if not marker.exists():
        return None
    directory = devlog.log_dir() / marker.read_text().strip()
    if not (directory / "meta.json").exists():
        marker.unlink()
        return None
    return devlog.Run.load(directory)


def check_source():
    """The open check's --src checkout, or None."""
    run = active_check()
    return Path(run.meta["src"]) if run and run.meta.get("src") else None


def require_active():
    run = active_check()
    if run is None:
        raise DevPiError("no check is open; start one with: tmdev.py check start --host HOST --title TEXT")
    return run


def latest_items(run):
    """Checklist items in first-recorded order; recording an item again replaces its status."""
    path = run.dir / "items.jsonl"
    items = {}
    if path.exists():
        for line in path.read_text().splitlines():
            item = json.loads(line)
            items[item["item"]] = item
    return list(items.values())


def write_checklist(run):
    meta = run.meta
    title = (f"PR {meta['pr']} check" if meta["pr"] else "Check") + f": {meta['title']}"
    lines = [
        f"# {title}",
        "",
        f"- Host: {meta['host']}",
        f"- Run directory: {run.dir}",
        f"- Code: {devlog.code_label(meta['code'])} ({meta['code']['worktree']})",
        *([f"- Tools: {devlog.code_label(meta['tool'])} ({meta['tool']['worktree']})"] if meta.get("tool") else []),
        f"- Opened: {meta['started']}" + (f", closed: {meta['finished']}" if meta.get("finished") else ""),
        f"- Last deploy to this host when the check opened: {devlog.deploy_label(meta.get('deploy'))}",
    ]
    if meta.get("deploy_at_close") not in (None, meta.get("deploy")):
        lines.append(f"- Last deploy when it closed: {devlog.deploy_label(meta['deploy_at_close'])}")
    if meta.get("result"):
        lines.append(f"- Result: **{meta['result']}**")
    lines += ["", "| # | Item | Status | Evidence | Note |", "|---|---|---|---|---|"]
    for number, item in enumerate(latest_items(run), 1):
        cells = [str(number), item["item"], item["status"].upper(), ", ".join(item["evidence"]), item["note"]]
        lines.append("| " + " | ".join(cell.replace("|", "\\|") for cell in cells) + " |")
    lines += ["", "In the run directory, commands.log lists each command with its exit code, "
                  "and cmd-NNN.out holds its output."]
    (run.dir / "checklist.md").write_text("\n".join(lines) + "\n")


def check_start(args):
    if (run := active_check()) is not None:
        raise DevPiError(f"a check is already open ({run.dir}); end it first")
    if args.host != "local":
        get_host(args.host)
    src = source_tree(args.src) if args.src else None
    run = devlog.Run.start("check", args.host, pr=args.pr, code=devlog.code_state(src) if src else None,
                           src=str(src) if src else None, title=args.title, deploy=devlog.last_deploy(args.host))
    active_marker().write_text(str(run.dir.relative_to(devlog.log_dir())))
    write_checklist(run)
    log(f"check open: {run.dir}")
    return 0


def check_item(args):
    run = require_active()
    missing = [name for name in args.evidence if not (run.dir / f"{name}.out").exists()]
    if missing:
        raise DevPiError(f"no such command output in this check: {', '.join(missing)}")
    record = {"time": devlog.stamp(devlog.utc_now()), "item": args.text, "status": args.status,
              "evidence": args.evidence, "note": args.note}
    with open(run.dir / "items.jsonl", "a") as items:
        items.write(json.dumps(record) + "\n")
    write_checklist(run)
    return 0


def check_status(args):
    run = require_active()
    write_checklist(run)
    print((run.dir / "checklist.md").read_text(), end="")
    return 0


def check_end(args):
    run = require_active()
    items = latest_items(run)
    counts = collections.Counter(item["status"] for item in items)
    if counts["fail"]:
        result, ok = f"fail ({counts['fail']} of {len(items)})", False
    elif counts["manual"]:
        result, ok = f"pending ({counts['manual']} manual)", False
    elif not items:
        result, ok = "no items", False
    elif not counts["pass"]:
        result, ok = f"nothing passed ({counts['skip']} skipped)", False
    else:
        result, ok = f"pass ({counts['pass']} passed, {counts['skip']} skipped)", True
    run.meta["deploy_at_close"] = devlog.last_deploy(run.meta["host"])
    run.finish(result, ok)
    write_checklist(run)
    active_marker().unlink()
    print((run.dir / "checklist.md").read_text(), end="")
    return 0 if ok else 1


def check_reopen(args):
    if (run := active_check()) is not None:
        raise DevPiError(f"a check is already open ({run.dir}); end it first")
    directory = devlog.log_dir() / "runs" / Path(args.run_dir).name
    run = devlog.Run.load(directory)
    if run.meta["kind"] != "check":
        raise DevPiError(f"{directory} is a {run.meta['kind']} run, not a check")
    active_marker().write_text(str(directory.relative_to(devlog.log_dir())))
    log(f"check reopened: {directory}; ending it again adds a new row to the log")
    return 0


# --- Pi login --------------------------------------------------------------------------------

def public_key_path(key):
    """The .pub file for a key given as a name in ~/.ssh (tm_dev) or as a path to either half of the pair."""
    path = Path("~/.ssh", key) if "/" not in key else Path(key)
    path = path.expanduser()
    # Never read the private half: point at the .pub file next to it.
    return path if path.suffix == ".pub" else path.with_name(path.name + ".pub")


def read_public_key(path):
    """The one-line OpenSSH public key in path, which must be a .pub file."""
    try:
        key = path.read_text().strip()
    except OSError as exc:
        raise DevPiError(f"can't read {path}: {exc.strerror}") from exc
    if "PRIVATE KEY" in key or "\n" in key or not PUBLIC_KEY.match(key):
        raise DevPiError(f"{path} doesn't hold a single OpenSSH public key")
    return key


def cloud_init_user(login, key):
    return f"""\
# Add this entry to the users: list in user-data on the card's boot partition, after
# Raspberry Pi Imager writes the card and before the Pi's first boot. Match the other
# entries' indentation, and keep a single users: list.
  - name: {login}
    shell: /bin/bash
    lock_passwd: true
    ssh_authorized_keys:
      - {json.dumps(key)}
    sudo: ALL=(ALL) NOPASSWD:ALL
"""


def shell_setup(login, key):
    staged = f"/tmp/090-{login}"
    return f"""\
# Run these on the Pi, logged in as your own account; sudo asks for your password.
sudo useradd --create-home --shell /bin/bash {login}
echo {shlex.quote(f"{login} ALL=(ALL) NOPASSWD: ALL")} > {staged}
sudo visudo -cf {staged} && sudo install -m 440 -o root -g root {staged} /etc/sudoers.d/090-{login}
rm {staged}
sudo install -d -m 700 -o {login} -g {login} /home/{login}/.ssh
echo {shlex.quote(key)} | sudo tee /home/{login}/.ssh/authorized_keys >/dev/null
sudo chown {login}:{login} /home/{login}/.ssh/authorized_keys
sudo chmod 600 /home/{login}/.ssh/authorized_keys
"""


def cmd_pi_login(args):
    """Print the setup for a key-only Pi login with passwordless sudo: a cloud-init user, or shell commands."""
    login, key = DEFAULT_LOGIN, DEFAULT_KEY
    if args.host:
        hostvars = get_host(args.host)
        login = hostvars.get("ansible_user", login)
        key = hostvars.get("ansible_ssh_private_key_file", key)
    login = args.login or login
    if not LOGIN_NAME.match(login):
        raise DevPiError(f"{login!r} isn't a valid login name")
    key = read_public_key(public_key_path(args.key or key))
    print(shell_setup(login, key) if args.shell else cloud_init_user(login, key), end="")
    return 0


# --- commands --------------------------------------------------------------------------------

def cmd_hosts(args):
    for name, hostvars in devlog.load_hosts().items():
        expect = hostvars.get("tm_expect", {})
        _, destination = ssh_command(name, hostvars)
        print(f"{name}  {destination}  pii_free={expect.get('pii_free', False)}"
              f"  ai={expect.get('ai_coprocessor', '?')}  radars={len(expect.get('radars') or [])}"
              f"  cameras={len(expect.get('cameras') or [])}  environmental={len(expect.get('environmental') or [])}")
    return 0


def cmd_run(args):
    """Run a command on a dev Pi, or on this machine with host 'local', and log it.

    The log goes to the open check if there is one, otherwise to adhoc/<date>/. A local command
    runs in the open check's --src checkout if it has one, otherwise in the current directory.
    """
    command = " ".join(args.extra)
    if not command:
        raise DevPiError("no command given; put it after --, e.g. tmdev.py run tm-dev-01 -- uptime")
    cwd = None
    if args.host == "local":
        cwd = check_source() or os.getcwd()
        where, argv, shell = f"local:{cwd}", command, True
    else:
        ssh, destination = ssh_command(args.host, get_host(args.host))
        where, argv, shell = args.host, [*ssh, destination, command], False
    check = active_check()
    directory = check.dir if check else devlog.log_dir() / "adhoc" / f"{devlog.utc_now():%Y-%m-%d}"
    directory.mkdir(parents=True, exist_ok=True)
    name = f"cmd-{len(list(directory.glob('cmd-*.out'))) + 1:03d}"
    started, clock = devlog.utc_now(), time.monotonic()
    code = stream(argv, directory / f"{name}.out", shell, cwd)
    with open(directory / "commands.log", "a") as commands:
        commands.write(f"{name}  {devlog.stamp(started)}  {where}  exit={code}  {time.monotonic() - clock:.1f}s\n"
                       f"    $ {devlog.redact(command)}\n")
    log(f"{name}: exit {code}, output saved in {directory / name}.out")
    return code


def deploy_remote(name, hostvars, src, tmsetup_args, log_file):
    """Run src's tmsetup.sh against the Pi over SSH, using the inventory's connection details."""
    argv = ["bash", str(src / "script" / "tmsetup.sh"), "-y", "-L", str(log_file),
            "-H", hostvars.get("ansible_host", name)]
    if user := hostvars.get("ansible_user"):
        argv += ["-l", user]
    if key := hostvars.get("ansible_ssh_private_key_file"):
        argv += ["-a", f"-private-key={Path(key).expanduser()}"]
    if port := hostvars.get("ansible_port"):
        argv += ["-a", f"e ansible_port={port}"]
    if codedir := hostvars.get("tmsetup_codedir"):
        argv += ["-d", codedir]
    return stream(argv + tmsetup_args)


def deploy_on_pi(name, hostvars, src, tmsetup_args, log_file):
    """Copy the src working tree to ~/tm-src on the Pi and run tmsetup.sh there, as a local install."""
    ssh, destination = ssh_command(name, hostvars)
    rsync = ["rsync", "-a", "--delete", "--filter=:- .gitignore", *(f"--exclude={path}" for path in ON_PI_EXCLUDES),
             "-e", shlex.join(ssh), f"{src}/", f"{destination}:{ON_PI_DIR}/"]
    code = stream(rsync, log_file.with_name("rsync.log"))
    if code:
        log(f"rsync to {name} failed with exit {code}")
        return code
    if codedir := hostvars.get("tmsetup_codedir"):
        tmsetup_args = ["-d", codedir, *tmsetup_args]
    remote = f"cd {ON_PI_DIR} && bash script/tmsetup.sh -y {shlex.join(tmsetup_args)}"
    return stream([*ssh, destination, remote], log_file)


def cmd_deploy(args):
    """Deploy --src, else the open check's --src, else this checkout; --pr defaults to the open check's."""
    hostvars = get_host(args.host)
    check = active_check()
    src = source_tree(args.src) if args.src else check_source() or devlog.REPO_ROOT
    pr = args.pr or (check.meta["pr"] if check else None)
    run = devlog.Run.start("deploy", args.host, pr=pr, code=devlog.code_state(src),
                           mode="on-pi" if args.on_pi else "remote", tmsetup_args=args.extra,
                           previous_deploy=devlog.last_deploy(args.host))
    log(f"deploying {devlog.code_label(run.meta['code'])} to {args.host} ({run.meta['mode']}); log: {run.dir}")
    deploy = deploy_on_pi if args.on_pi else deploy_remote
    code = deploy(args.host, hostvars, src, args.extra, run.dir / "tmsetup.log")
    run.finish("pass" if code == 0 else f"fail (exit {code})", code == 0)
    log(f"deploy {run.meta['result']}; logged in {run.dir}")
    return code


def cmd_log(args):
    root = devlog.log_dir()
    if args.path:
        print(root)
        return 0
    path = root / "LOG.md"
    if not path.exists():
        print(f"No runs logged yet in {root}")
        return 0
    lines = path.read_text().splitlines()
    table = lines.index(devlog.LOG_TABLE.splitlines()[0])
    rows = lines[table + 2:]
    print("\n".join(lines[table:table + 2] + rows[-args.n:]))
    print(f"\n{len(rows)} runs in {path}\nThe Run column is relative to {root}/")
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    extra = []
    if "--" in argv:
        cut = argv.index("--")
        argv, extra = argv[:cut], argv[cut + 1:]

    parser = argparse.ArgumentParser(description="Deploy to dev Pis, run commands on them, and log PR checks.")
    commands = parser.add_subparsers(dest="command", required=True)
    pi_login = commands.add_parser("pi-login",
                                   help="print the setup for a Pi's tmdev login (cloud-init entry, or --shell)")
    pi_login.add_argument("host", nargs="?", help="take the login and key from this inventory host")
    pi_login.add_argument("--login", help=f"login name (default: the host's ansible_user, else {DEFAULT_LOGIN})")
    pi_login.add_argument("--key", metavar="NAME|PATH",
                          help=f"SSH key: a name in ~/.ssh, or a path; its .pub file is used "
                               f"(default: the host's key, else {DEFAULT_KEY})")
    pi_login.add_argument("--shell", action="store_true", help="print shell commands for a Pi that's already running")
    commands.add_parser("hosts", help="list the dev Pis in the inventory")
    deploy = commands.add_parser("deploy",
                                 help="run a checkout's tmsetup.sh for a dev Pi; tmsetup.sh options go after --")
    deploy.add_argument("host")
    deploy.add_argument("--src", metavar="DIR",
                        help="checkout to deploy (default: the open check's --src, else this checkout)")
    deploy.add_argument("--on-pi", action="store_true",
                        help=f"copy the working tree to ~/{ON_PI_DIR} on the Pi and run tmsetup.sh there")
    deploy.add_argument("--pr", type=int, help="PR number to show in the log (default: the open check's)")
    run = commands.add_parser("run", help="run a command and log it; the command goes after --")
    run.add_argument("host", help="inventory host name, or 'local' for this machine")
    check = commands.add_parser("check", help="record a PR check (start, item, status, end, reopen)")
    actions = check.add_subparsers(dest="action", required=True)
    start = actions.add_parser("start", help="open a check; later run commands are logged in it")
    start.add_argument("--host", required=True, help="inventory host name, or 'local' for off-device checks")
    start.add_argument("--pr", type=int)
    start.add_argument("--title", required=True)
    start.add_argument("--src", metavar="DIR",
                       help="checkout under test, e.g. a worktree of the PR's branch (default: this checkout); "
                            "deploys and local commands in the check use it")
    item = actions.add_parser("item", help="record a checklist item; recording it again replaces its status")
    item.add_argument("text")
    item.add_argument("status", choices=STATUSES, help="'manual' means waiting on the developer")
    item.add_argument("--evidence", nargs="+", default=[], metavar="cmd-NNN", help="commands that show the result")
    item.add_argument("--note", default="")
    actions.add_parser("status", help="show the open check's checklist")
    actions.add_parser("end", help="close the check and add its row to the log")
    reopen = actions.add_parser("reopen", help="reopen a closed check, e.g. to record manual results")
    reopen.add_argument("run_dir")
    show = commands.add_parser("log", help="show the newest rows of the run log")
    show.add_argument("-n", type=int, default=20, help="number of rows (default 20)")
    show.add_argument("--path", action="store_true", help="print the log directory and exit")
    args = parser.parse_args(argv)
    args.extra = extra

    handlers = {"pi-login": cmd_pi_login, "hosts": cmd_hosts, "deploy": cmd_deploy, "run": cmd_run,
                "log": cmd_log,
                "check": lambda a: {"start": check_start, "item": check_item, "status": check_status,
                                    "end": check_end, "reopen": check_reopen}[a.action](a)}
    try:
        return handlers[args.command](args)
    except DevPiError as exc:
        log(f"ERROR: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
