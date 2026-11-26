"""The launcher that carries a cut-off update on (jobs/tm-update-resume), run as a script against a temporary root.

The tree's script/tm-update is a stub that records its argv, and systemctl is a stub that records its own.
"""

import importlib.machinery
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))

from job_update_world import RUNNER  # noqa: E402

LAUNCHER = Path(__file__).resolve().parents[2] / "jobs" / "tm-update-resume"
COMMIT = "0123456789abcdef0123456789abcdef01234567"
TREE = f"/var/lib/traffic-monitor/src/{COMMIT}"
HANDOVER = "/var/lib/traffic-monitor/update/work/20261125T101500Z/handover.json"
UNITS = ["tm-control.service", "traffic-monitor.service", "revproxy.service"]

TM_UPDATE = """#!{python}
import json, os, sys
with open(os.path.join(os.environ["TM_UPDATE_ROOT"], "tm-update-ran.json"), "w") as out:
    json.dump(sys.argv[1:], out)
"""
SYSTEMCTL = """#!{python}
import json, sys
with open({log!r}, "a") as out:
    out.write(json.dumps(sys.argv[1:]) + "\\n")
sys.exit({status})
"""


class Device:
    def __init__(self, tmp_path):
        self.tmp = tmp_path
        self.root = tmp_path / "root"
        self.update = self.root / "var/lib/traffic-monitor/update"
        self.marker = self.update / "resume.json"
        self.calls = tmp_path / "systemctl-calls"
        self.update.mkdir(parents=True)

    def tree(self, commit=COMMIT, program=True):
        path = self.root / "var/lib/traffic-monitor/src" / commit
        (path / "script").mkdir(parents=True)
        if program:
            (path / "script/tm-update").write_text(TM_UPDATE.format(python=sys.executable))
            (path / "script/tm-update").chmod(0o755)
        return path

    def handover(self, device_path=HANDOVER):
        path = self.root / device_path.lstrip("/")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}")
        return path

    def good(self):
        self.tree()
        self.handover()
        return {"contract": 1, "tree": TREE, "handover": HANDOVER}

    def mark(self, marker):
        self.marker.write_text(marker if isinstance(marker, str) else json.dumps(marker))

    def systemctl(self, status=0):
        path = self.tmp / "systemctl"
        path.write_text(SYSTEMCTL.format(python=sys.executable, log=str(self.calls), status=status))
        path.chmod(0o755)
        return path

    def run(self, status=0):
        environment = {"TM_UPDATE_ROOT": str(self.root), "TM_UPDATE_SYSTEMCTL": str(self.systemctl(status))}
        return subprocess.run([sys.executable, "-I", str(RUNNER), str(LAUNCHER)], env=environment,
                              capture_output=True, text=True, timeout=60)

    def ran(self):
        path = self.root / "tm-update-ran.json"
        return json.loads(path.read_text()) if path.exists() else None

    def systemctl_calls(self):
        return [json.loads(line) for line in self.calls.read_text().splitlines()] if self.calls.exists() else []


@pytest.fixture
def device(tmp_path):
    return Device(tmp_path)


def test_the_launcher_is_executable():
    assert os.access(LAUNCHER, os.X_OK)
    assert LAUNCHER.read_text().startswith("#!/usr/bin/python3\n")


def test_with_no_marker_it_does_nothing_and_exits_0(device):
    result = device.run()
    assert result.returncode == 0, result.stdout + result.stderr
    assert len(result.stdout.strip().splitlines()) == 1
    assert device.ran() is None and device.systemctl_calls() == []


def test_a_good_marker_becomes_the_trees_tm_update_resume(device):
    device.mark(device.good())
    result = device.run()
    assert result.returncode == 0, result.stdout + result.stderr
    assert device.ran() == ["resume", "--handover", str(device.root / HANDOVER.lstrip("/"))]
    assert device.marker.exists()
    assert device.systemctl_calls() == []


def bad_markers(device):
    good = device.good()
    device.handover("/var/lib/traffic-monitor/update/other/handover.json")
    device.tree("f" * 40)
    device.tree("a" * 40, program=False)
    link = device.root / "var/lib/traffic-monitor/update/work/link.json"
    link.symlink_to(device.root / "var/lib/traffic-monitor/update/other/handover.json")
    tree_link = device.root / "var/lib/traffic-monitor/src" / ("b" * 40)
    tree_link.symlink_to(device.root / "var/lib/traffic-monitor/src" / ("f" * 40))
    return {
        "not JSON": "{",
        "not an object": "[]",
        "contract 2": dict(good, contract=2),
        "contract true": dict(good, contract=True),
        "contract 1.0": '{"contract": 1.0, "tree": "%s", "handover": "%s"}' % (TREE, HANDOVER),
        "tree outside src": dict(good, tree="/tmp/" + COMMIT),
        "tree with ..": dict(good, tree=f"/var/lib/traffic-monitor/src/../src/{COMMIT}"),
        "tree trailing part": dict(good, tree=TREE + "/script"),
        "tree short id": dict(good, tree="/var/lib/traffic-monitor/src/0123456"),
        "tree upper case": dict(good, tree="/var/lib/traffic-monitor/src/" + COMMIT.upper()),
        "tree without tm-update": dict(good, tree="/var/lib/traffic-monitor/src/" + "a" * 40),
        "tree is a link": dict(good, tree="/var/lib/traffic-monitor/src/" + "b" * 40),
        "tree not text": dict(good, tree=5),
        "handover outside work": dict(good, handover="/var/lib/traffic-monitor/update/other/handover.json"),
        "handover with ..": dict(good, handover="/var/lib/traffic-monitor/update/work/../other/handover.json"),
        "handover is the folder": dict(good, handover="/var/lib/traffic-monitor/update/work"),
        "handover missing": dict(good, handover="/var/lib/traffic-monitor/update/work/none/handover.json"),
        "handover links out": dict(good, handover="/var/lib/traffic-monitor/update/work/link.json"),
        "handover not text": dict(good, handover=None),
        "a key missing": {"contract": 1, "tree": TREE},
    }


@pytest.mark.parametrize("name", [
    "not JSON", "not an object", "contract 2", "contract true", "contract 1.0", "tree outside src", "tree with ..",
    "tree trailing part", "tree short id", "tree upper case", "tree without tm-update", "tree is a link",
    "tree not text", "handover outside work", "handover with ..", "handover is the folder", "handover missing",
    "handover links out", "handover not text", "a key missing"])
def test_an_unusable_marker_is_set_aside_the_services_start_and_it_exits_2(device, name):
    device.mark(bad_markers(device)[name])
    result = device.run()
    assert result.returncode == 2, result.stdout + result.stderr
    assert device.ran() is None
    assert not device.marker.exists()
    assert (device.update / "resume.json.unusable").exists()
    assert device.systemctl_calls() == [["start", "--no-block", *UNITS]]
    assert COMMIT not in result.stdout and "handover" not in result.stdout


def test_an_older_unusable_marker_is_replaced_and_a_failing_systemctl_still_exits_2(device):
    (device.update / "resume.json.unusable").write_text("old")
    device.mark("{")
    result = device.run(status=1)
    assert result.returncode == 2, result.stdout + result.stderr
    assert (device.update / "resume.json.unusable").read_text() == "{"
    assert not device.marker.exists()


def test_a_missing_systemctl_still_exits_2(device):
    device.mark("{")
    environment = {"TM_UPDATE_ROOT": str(device.root), "TM_UPDATE_SYSTEMCTL": str(device.tmp / "no-such-systemctl")}
    result = subprocess.run([sys.executable, "-I", str(RUNNER), str(LAUNCHER)], env=environment,
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 2, result.stdout + result.stderr
    assert (device.update / "resume.json.unusable").exists()


def test_a_tm_update_that_cannot_start_counts_as_unusable(device):
    device.mark(device.good())
    program = device.root / TREE.lstrip("/") / "script/tm-update"
    program.write_text("#!/nonexistent/interpreter\n")
    result = device.run()
    assert result.returncode == 2, result.stdout + result.stderr
    assert (device.update / "resume.json.unusable").exists()
    assert device.systemctl_calls() == [["start", "--no-block", *UNITS]]


def test_root_ignores_the_test_seams(monkeypatch, tmp_path):
    loader = importlib.machinery.SourceFileLoader("tm_update_resume_under_test", str(LAUNCHER))
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    loader.exec_module(module)
    monkeypatch.setenv("TM_UPDATE_ROOT", str(tmp_path))
    monkeypatch.setenv("TM_UPDATE_SYSTEMCTL", str(tmp_path / "systemctl"))
    monkeypatch.setattr(module.os, "geteuid", lambda: 0)
    assert module.rooted(module.RESUME) == "/var/lib/traffic-monitor/update/resume.json"
    assert module.trusted("TM_UPDATE_SYSTEMCTL", "systemctl") == "systemctl"
    monkeypatch.setattr(module.os, "geteuid", lambda: 1000)
    assert module.rooted(module.RESUME) == str(tmp_path / "var/lib/traffic-monitor/update/resume.json")
    assert module.trusted("TM_UPDATE_SYSTEMCTL", "systemctl") == str(tmp_path / "systemctl")
