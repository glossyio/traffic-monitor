"""Shared set-up for the tm-update tests: the package on sys.path, a device's folders under a temporary root, and a
stand-in for the one function that runs outside commands."""

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1]
if str(SCRIPT) not in sys.path:
    sys.path.insert(0, str(SCRIPT))

from tm_update.handover import Handover  # noqa: E402
from tm_update.installed import Installed  # noqa: E402
from tm_update.paths import Paths  # noqa: E402

COMMIT = "a" * 40
OLD_COMMIT = "b" * 40
RUN = "20261125T101500Z-abc"


def manifest(**changes):
    data = {
        "manifest_version": 1,
        "tm_version": "0.7.1",
        "git": {"commit": OLD_COMMIT, "branch": "main", "modified": False},
        "installing_user": "pi",
        "codedir": "/opt/traffic-monitor",
        "codeowner": "tmadmin",
        "components": {},
        "options": {"plate_recognizer": False},
        "update": {"repo": "example/traffic-monitor-test", "channel": "stable"},
    }
    data.update(changes)
    return data


def installed(**changes):
    values = dict(tm_version="0.7.1", commit=OLD_COMMIT, installing_user="pi", codedir=Path("/opt/traffic-monitor"),
                  codeowner="tmadmin", codegroup="tmadmin", repo="example/traffic-monitor-test",
                  plate_recognizer=False)
    values.update(changes)
    return Installed(**values)


def handover_dict(paths, **changes):
    data = {
        "contract": 1,
        "run_id": RUN,
        "channel": "stable",
        "commit": COMMIT,
        "tag": "v0.8.0",
        "from_version": "0.7.1",
        "work_dir": str(paths.work_root / RUN),
        "state_path": str(paths.state),
        "log_path": str(paths.log_dir / (RUN + ".log")),
    }
    data.update(changes)
    return data


def handover(paths, **changes):
    values = dict(run_id=RUN, channel="stable", commit=COMMIT, tag="v0.8.0", from_version="0.7.1",
                  work_dir=paths.work_root / RUN, state_path=paths.state, log_path=paths.log_dir / (RUN + ".log"))
    values.update(changes)
    return Handover(**values)


def make_world(tmp_path, *, manifest_data=None, with_manifest=True):
    """A device under tmp_path: the manifest and the code folder, plus a tree with update.json and the lock."""
    paths = Paths(root=tmp_path / "root")
    codedir = paths.root / "opt" / "traffic-monitor"
    (codedir / "node-red-tm" / "db").mkdir(parents=True)
    paths.manifest.parent.mkdir(parents=True)
    if with_manifest:
        paths.manifest.write_text(json.dumps(manifest() if manifest_data is None else manifest_data))
    tree = tmp_path / "tree"
    (tree / "script").mkdir(parents=True)
    (tree / "script" / "update.json").write_text(json.dumps(
        {"contracts": [1], "tm_version": "0.8.0", "tmdb_schema": 10, "state_schema": 5}))
    (tree / "script" / "requirements.lock").write_text("ansible==1 \\\n    --hash=sha256:00\n")
    return paths, tree


class FakeRun:
    """Replaces proc.run: records every call and answers from a function, which gets the argv."""

    def __init__(self, answer=None):
        self.calls = []
        self.answer = answer

    def __call__(self, argv, *, env=None, log=None, check=False, timeout=None, cwd=None):
        self.calls.append({"argv": [str(a) for a in argv], "env": env, "log": log, "check": check,
                           "timeout": timeout, "cwd": cwd})
        result = self.answer(self.calls[-1]) if self.answer else None
        if result is None:
            result = subprocess.CompletedProcess(argv, 0, "", "")
        return result

    def argvs(self):
        return [call["argv"] for call in self.calls]


def completed(argv, rc=0, stdout=""):
    return subprocess.CompletedProcess(argv, rc, stdout, "")
