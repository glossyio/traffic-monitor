"""Local run log and dev-Pi inventory access, shared by tmdev.py and the device tests.

Both files this module reads and writes stay on the developer's machine, outside any
git work tree: the inventory names real devices, and the log records what ran on them.

    inventory  $TM_DEV_INVENTORY, default ~/.config/traffic-monitor/dev-pis.yml
    run log    $TM_DEV_LOG_DIR, default ${XDG_STATE_HOME:-~/.local/state}/traffic-monitor/dev-tests/

The log is one directory per run under runs/, plus two indexes with one row per run:
LOG.md for people and runs.jsonl for scripts.
"""

import datetime
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INVENTORY = "~/.config/traffic-monitor/dev-pis.yml"
INVENTORY_GROUP = "tm_dev"
# KEY=value or "key": value pairs whose key looks like a secret; the value is replaced.
SECRET_PAIR = re.compile(
    r"""(?i)(["']?[\w.-]*(?:pass|secret|token|key)[\w.-]*["']?[ \t]*[:=][ \t]*)("[^"]*"|'[^']*'|[^\s;,'"]+)""")
LOG_TABLE = "| When (UTC) | Kind | Host | Code | PR | Result | Run |\n|---|---|---|---|---|---|---|\n"
LOG_HEADER = """# Dev-Pi run log

Location: {root} (on this machine, outside the repo)

One row per deploy, device-test run, and PR check, newest last. The Run column links to
runs/<name>/ in this directory: meta.json plus tmsetup.log (deploy), summary.md (suite),
or checklist.md (check).

""" + LOG_TABLE


class DevPiError(Exception):
    pass


def redact(text):
    return SECRET_PAIR.sub(r"\1<redacted>", text)


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc)


def stamp(moment):
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def outside_git(path, what):
    """Resolve path and refuse it if it's inside a git work tree, so it can't be committed."""
    path = Path(path).expanduser().resolve()
    for parent in (path, *path.parents):
        if (parent / ".git").exists():
            raise DevPiError(f"the {what} ({path}) is inside the git work tree {parent}; move it outside any repo")
    return path


def inventory_path():
    return outside_git(os.environ.get("TM_DEV_INVENTORY") or DEFAULT_INVENTORY, "dev-Pi inventory")


def log_dir():
    base = os.environ.get("TM_DEV_LOG_DIR") or Path(
        os.environ.get("XDG_STATE_HOME") or "~/.local/state", "traffic-monitor", "dev-tests")
    path = outside_git(base, "run log directory")
    (path / "runs").mkdir(parents=True, exist_ok=True)
    path.chmod(0o700)
    return path


def load_hosts():
    """Return {host name: vars} for the tm_dev group, with vars resolved by ansible-inventory."""
    inventory = inventory_path()
    if not inventory.is_file():
        raise DevPiError(f"no dev-Pi inventory at {inventory}; see script/devpi/README.md")
    # Prefer the ansible-inventory next to this interpreter (the dev venv).
    search = os.pathsep.join([str(Path(sys.executable).parent), os.environ.get("PATH", "")])
    command = shutil.which("ansible-inventory", path=search)
    if command is None:
        raise DevPiError("ansible-inventory not found; run this with the dev venv (.venv/bin/python)")
    result = subprocess.run([command, "-i", str(inventory), "--list"],
                            stdin=subprocess.DEVNULL, capture_output=True, text=True)
    if result.returncode:
        raise DevPiError(f"ansible-inventory failed on {inventory}:\n{result.stderr.strip()}")
    data = json.loads(result.stdout)
    hostvars = data.get("_meta", {}).get("hostvars", {})

    def group_hosts(group):
        entry = data.get(group, {})
        names = list(entry.get("hosts", []))
        for child in entry.get("children", []):
            names += group_hosts(child)
        return names

    names = group_hosts(INVENTORY_GROUP)
    if not names:
        raise DevPiError(f"{inventory} has no hosts in the '{INVENTORY_GROUP}' group")
    return {name: hostvars.get(name, {}) for name in names}


def code_state(root=REPO_ROOT):
    """Branch, commit, and uncommitted changes of a checkout; by default, the one this module runs from."""
    def git(*args):
        return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True).stdout.strip()

    changes = git("status", "--short").splitlines()
    return {
        "worktree": str(root),
        "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
        "commit": git("rev-parse", "--short=10", "HEAD"),
        "dirty": bool(changes),
        "changes": changes[:50],
    }


def code_label(code):
    return f"{code['branch']}@{code['commit'][:7]}" + (" +dirty" if code["dirty"] else "")


def read_index():
    path = log_dir() / "runs.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def last_deploy(host):
    """The newest deploy row for host from runs.jsonl, or None."""
    for row in reversed(read_index()):
        if row["kind"] == "deploy" and row["host"] == host:
            return row
    return None


def deploy_label(row):
    """One line about a deploy row, for summaries; says so when none was logged."""
    if row is None:
        return "none logged"
    return f"{row['finished']}, {row['code']}, {row['result']} ({log_dir() / row['run']})"


class Run:
    """One run directory, runs/<UTC time>-<kind>-<host>[-pr<N>]/, holding meta.json and the run's files."""

    def __init__(self, directory, meta):
        self.dir = Path(directory)
        self.meta = meta

    @classmethod
    def start(cls, kind, host, pr=None, code=None, **extra):
        """Create the run directory. code is the code under test (default: this checkout); when it's
        another checkout, the meta also records this one as tool."""
        now = utc_now()
        name = f"{now:%Y%m%dT%H%M%SZ}-{kind}-{host}" + (f"-pr{pr}" if pr else "")
        directory = log_dir() / "runs" / name
        suffix = 1
        while directory.exists():
            suffix += 1
            directory = directory.with_name(f"{name}-{suffix}")
        directory.mkdir()
        tool = code_state()
        code = code or tool
        meta = {"kind": kind, "host": host, "pr": pr, "started": stamp(now), "code": code}
        if code["worktree"] != tool["worktree"]:
            meta["tool"] = tool
        run = cls(directory, {**meta, **extra})
        run.save()
        return run

    @classmethod
    def load(cls, directory):
        directory = Path(directory)
        return cls(directory, json.loads((directory / "meta.json").read_text()))

    def save(self):
        (self.dir / "meta.json").write_text(json.dumps(self.meta, indent=2) + "\n")

    def finish(self, result, ok):
        """Record the outcome and add this run's row to both indexes."""
        self.meta.update(finished=stamp(utc_now()), result=result, ok=ok,
                         code_at_finish=code_state(self.meta["code"]["worktree"]))
        self.save()
        relative = self.dir.relative_to(log_dir())
        row = {key: self.meta.get(key) for key in ("kind", "host", "pr", "started", "finished", "result", "ok")}
        row.update(code=code_label(self.meta["code"]), run=str(relative))
        root = log_dir()
        with open(root / "runs.jsonl", "a") as index:
            index.write(json.dumps(row) + "\n")
        log = root / "LOG.md"
        if not log.exists():
            log.write_text(LOG_HEADER.format(root=root))
        cells = [row["finished"].replace("T", " ")[:16], row["kind"], row["host"], row["code"],
                 str(row["pr"] or ""), row["result"], f"[{relative.name}]({relative}/)"]
        with open(log, "a") as index:
            index.write("| " + " | ".join(cell.replace("|", "\\|") for cell in cells) + " |\n")
