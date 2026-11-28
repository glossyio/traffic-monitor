"""A device and a stand-in for GitHub, for tm-job-update's tests (tests/test_job_update.py and
script/tests/test_update_job_contract.py).

The device is a temporary root (TM_UPDATE_ROOT) with a manifest whose code owner is the test's own user, a jobs
folder, and the update's folders. The stand-in is a local bare repository (TM_UPDATE_REMOTE): main with the tags
v0.8.0 and v0.8.1 (and an annotated tag, vnotes), dev one commit ahead of main, and a side commit that only the tag
v0.9.0 reaches. Each tree holds
a stub script/tm-update that records its argv and whether the run lock was free, and a script/update.json.

The job runs through run_job.py, which reports a non-root euid, so the test seams are honoured even when the suite
runs as root. No test reaches the network: the only remote is the local repository, and the recording git refuses
an https fetch without running one.
"""

import json
import os
import pwd
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

JOB = Path(__file__).resolve().parents[3] / "jobs" / "tm-job-update"
RUNNER = Path(__file__).resolve().parent / "run_job.py"
REAL_GIT = shutil.which("git") or "/usr/bin/git"
RUN_ID = "20261125T101500Z"
REPO_NAME = "example/traffic-monitor-test"

STUB = """#!{python}
import fcntl, json, os, sys
root = os.environ["TM_UPDATE_ROOT"]
fd = os.open(os.path.join(root, "var/lib/traffic-monitor/update/lock"), os.O_RDONLY)
try:
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    free = True
except BlockingIOError:
    free = False
with open(os.path.join(root, "tm-update-ran.json"), "w") as out:
    json.dump({{"argv": sys.argv[1:], "lock_free": free,
               "tree": os.path.dirname(os.path.dirname(os.path.abspath(__file__)))}}, out)
"""

LAUNCHER_STUB = """#!{python}
import json, os, sys
with open(os.path.join(os.environ["TM_UPDATE_ROOT"], "launcher-ran.json"), "w") as out:
    json.dump(sys.argv[1:], out)
"""

# Logs each call's argv and environment, then runs the real git; an https fetch is refused without running.
RECORDING_GIT = """#!{python}
import json, os, sys
with open({log!r}, "a") as out:
    out.write(json.dumps({{"argv": sys.argv[1:], "env": dict(os.environ)}}) + "\\n")
if "fetch" in sys.argv and any(arg.startswith("https://") for arg in sys.argv):
    sys.exit(128)
os.execv({git!r}, [{git!r}] + sys.argv[1:])
"""

GIT_ENV = {"PATH": "/usr/bin:/bin", "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.invalid", "GIT_COMMITTER_NAME": "Test",
           "GIT_COMMITTER_EMAIL": "test@example.invalid"}


def me():
    return pwd.getpwuid(os.getuid()).pw_name


def git(cwd, *args):
    result = subprocess.run([REAL_GIT, "-c", "init.defaultBranch=main", *args], cwd=cwd, env=GIT_ENV,
                            capture_output=True, text=True, timeout=60, check=True)
    return result.stdout.strip()


def update_json(version, **changes):
    data = {"contracts": [1], "tm_version": version, "tmdb_schema": 11, "state_schema": 7}
    data.update(changes)
    return json.dumps(data)


def tree(version, changes=None):
    files = {"script/tm-update": STUB.format(python=sys.executable), "script/update.json": update_json(version),
             "README": f"version {version}\n"}
    files.update(changes or {})
    return files


def commit(work, files, message):
    for entry in work.iterdir():
        if entry.name != ".git":
            shutil.rmtree(entry) if entry.is_dir() else entry.unlink()
    for name, text in files.items():
        if text is None:
            continue
        path = work / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        path.chmod(0o755 if name == "script/tm-update" else 0o644)
    git(work, "add", "-A")
    git(work, "commit", "-q", "--allow-empty", "-m", message)
    return git(work, "rev-parse", "HEAD")


def make_remote(tmp_path, changes=None):
    """The bare repository and the commit ids by name: v080, v081 (main), dev, side, and annotated
    (the tag object vnotes, not a commit). changes maps a commit's name to
    files that replace (text) or remove (None) the stub tree's."""
    changes = changes or {}
    work = tmp_path / "work-repo"
    work.mkdir()
    git(work, "init", "-q")
    ids = {"v080": commit(work, tree("0.8.0", changes.get("v080")), "0.8.0")}
    git(work, "tag", "v0.8.0")
    ids["v081"] = commit(work, tree("0.8.1", changes.get("v081")), "0.8.1")
    git(work, "tag", "v0.8.1")
    git(work, "tag", "-a", "-m", "notes", "vnotes")
    ids["annotated"] = git(work, "rev-parse", "vnotes")
    git(work, "checkout", "-q", "-b", "dev")
    ids["dev"] = commit(work, tree("0.8.2-dev", changes.get("dev")), "0.8.2-dev")
    git(work, "checkout", "-q", "-b", "side", ids["v080"])
    ids["side"] = commit(work, tree("0.9.0", changes.get("side")), "0.9.0")
    git(work, "tag", "v0.9.0")
    remote = tmp_path / "remote.git"
    git(tmp_path, "init", "-q", "--bare", str(remote))
    git(work, "push", "-q", str(remote), "main", "dev", "v0.8.0", "v0.8.1", "v0.9.0", "vnotes")
    return remote, ids


def set_user_version(path, number):
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.execute(f"PRAGMA user_version = {int(number)}")
    connection.close()


class World:
    def __init__(self, tmp_path, changes=None):
        self.tmp = tmp_path
        self.root = tmp_path / "root"
        self.remote, self.ids = make_remote(tmp_path, changes)
        self.update_dir = self.root / "var/lib/traffic-monitor/update"
        self.src = self.root / "var/lib/traffic-monitor/src"
        self.state_path = self.update_dir / "state.json"
        self.jobs = self.root / "run/tm-control/jobs"
        self.jobs.mkdir(parents=True)
        self.jobs.chmod(0o700)
        self.codedir = self.root / "opt/traffic-monitor"
        (self.codedir / "node-red-tm/db").mkdir(parents=True)
        self.manifest_path = tmp_path / "manifest.json"
        self.manifest = {
            "manifest_version": 1, "tm_version": "0.8.0",
            "git": {"commit": self.ids["v080"], "branch": "main", "modified": False},
            "installing_user": "pi", "codedir": "/opt/traffic-monitor", "codeowner": me(),
            "update": {"repo": REPO_NAME, "channel": "development"},
        }
        self.write_manifest()
        self.git_log = tmp_path / "git-calls.jsonl"

    def write_manifest(self, **changes):
        self.manifest.update(changes)
        self.manifest_path.write_text(json.dumps(self.manifest))

    def install(self, name, version):
        """The manifest names this commit (a name from ids, or a text such as "unknown") and version."""
        git_block = dict(self.manifest["git"], commit=self.ids.get(name, name))
        self.write_manifest(git=git_block, tm_version=version)

    def request(self, body=None, **changes):
        data = {"run_id": RUN_ID, "channel": "development", "commit": self.ids["dev"], "tag": None}
        data.update(changes)
        path = self.jobs / "update.json"
        path.write_text(body if isinstance(body, str) else json.dumps(data if body is None else body))
        path.chmod(0o600)
        return path

    def launcher(self):
        path = self.root / "usr/local/libexec/traffic-monitor/tm-update-resume"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(LAUNCHER_STUB.format(python=sys.executable))
        path.chmod(0o755)
        return path

    def recording_git(self):
        path = self.tmp / "recording-git"
        path.write_text(RECORDING_GIT.format(python=sys.executable, log=str(self.git_log), git=REAL_GIT))
        path.chmod(0o755)
        return path

    def git_calls(self):
        if not self.git_log.exists():
            return []
        return [json.loads(line) for line in self.git_log.read_text().splitlines()]

    def run(self, request=None, remote=True, git=None, **env):
        request = request or self.request()
        environment = {"TM_CONTROL_MANIFEST": str(self.manifest_path), "TM_UPDATE_ROOT": str(self.root)}
        if remote:
            environment["TM_UPDATE_REMOTE"] = str(self.remote)
        if git:
            environment["TM_UPDATE_GIT"] = str(git)
        environment.update(env)
        return subprocess.run([sys.executable, "-I", str(RUNNER), str(JOB), str(request)], env=environment,
                              capture_output=True, text=True, timeout=120)

    def state(self):
        return json.loads(self.state_path.read_text())

    def write_state(self, **values):
        self.update_dir.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(values))

    def ran(self):
        path = self.root / "tm-update-ran.json"
        return json.loads(path.read_text()) if path.exists() else None

    def handover_path(self, run_id=RUN_ID):
        return self.update_dir / "work" / run_id / "handover.json"
