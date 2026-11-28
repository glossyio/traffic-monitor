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


def one_row_per_name(images):
    """`podman images --format json` as Podman 5.4.2 prints it: an image with three names is three rows, each with the
    same id and all three names."""
    rows = []
    for image in images:
        names = image.get("Names") if isinstance(image, dict) else None
        rows.extend([image] * (len(names) if isinstance(names, list) and names else 1))
    return rows


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


BOOT = "11111111-2222-3333-4444-555555555555"
OTHER_BOOT = "99999999-8888-7777-6666-555555555555"
SWITCH_USEC = 5_000_000
SLICE_STOP = ["systemctl", "stop", "tm-update.slice"]


class FakeClock:
    """health's clock and sleep: time moves only when the check sleeps."""

    def __init__(self):
        self.now = 1000.0
        self.slept = []

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


class Device:
    """A device under a temporary root, the calls that would reach it recorded, and main() run against it.

    events holds every outside command (its argv) and every playbook run (("playbook", name, tags)) in order."""

    def __init__(self, tmp_path, monkeypatch, **world):
        from tm_update import cli, health, installed as installed_module, playbook, proc, switch

        self._cli = cli
        self.paths, self.tree = make_world(tmp_path, **world)
        self.handover_path = tmp_path / "handover.json"
        self.handover_path.write_text(json.dumps(handover_dict(self.paths)))
        self.work = self.paths.work_root / RUN
        self.stages = []
        self.events = []
        self.playbook_rc = {}
        self.images = []
        self.when_a_stage_starts = None
        # The switch: setup.yml's exit status (or an exception it raises), the restart flag it leaves, and a function
        # it calls (to make a database copy, say)
        self.setup_rc = 0
        self.reboot_flag = None
        self.during_setup = None
        self.flag_before_setup = []
        # systemctl: (verb, unit) -> exit status or an exception; is-active answers; tm-control's start time
        self.systemctl = {}
        self.unit_state = {}
        self.tm_control_entered = 10**15
        self.state_at_reboot = None
        self.log_at_reboot = None
        self.endpoint_status = 200
        self.endpoint_urls = []
        self.time = FakeClock()
        self.paths.boot_id.parent.mkdir(parents=True)
        self.paths.boot_id.write_text(BOOT + "\n")
        self.run = FakeRun(self._answer)
        monkeypatch.setattr(proc, "run", self.run)
        monkeypatch.setattr(installed_module, "_free_bytes", lambda path: 10**12)
        monkeypatch.setattr(playbook, "ensure_venv", self._ensure_venv)
        monkeypatch.setattr(playbook, "run_playbook", self._run_playbook)
        monkeypatch.setattr(switch, "_monotonic_usec", lambda: SWITCH_USEC)
        monkeypatch.setattr(health, "_clock", self.time.clock)
        monkeypatch.setattr(health, "_sleep", self.time.sleep)
        monkeypatch.setattr(health, "_get_status", self._get_status)

    def _answer(self, call):
        argv = call["argv"]
        self.events.append(argv)
        if argv[:2] == ["podman", "images"]:
            return completed(argv, stdout=json.dumps(one_row_per_name(self.images)))
        if argv[:2] == ["systemctl", "is-active"]:
            state = self.unit_state.get(argv[2], "active")
            return completed(argv, 0 if state == "active" else 3, state + "\n")
        if argv[:2] == ["systemctl", "show"]:
            return completed(argv, stdout=f"{self.tm_control_entered}\n")
        if argv == ["systemctl", "reboot"]:
            self.state_at_reboot = json.loads(self.paths.state.read_text())
            self.log_at_reboot = self.log()
        if argv[0] == "systemctl":
            key = (argv[1], argv[-1]) if len(argv) == 3 else (argv[1],)
            answer = self.systemctl.get(key, 0)
            if isinstance(answer, BaseException):
                raise answer
            return completed(argv, answer)
        return None

    def _get_status(self, port):
        self.endpoint_urls.append(port)
        return self.endpoint_status

    def _ensure_venv(self, tree, paths, log):
        if self.when_a_stage_starts:
            self.when_a_stage_starts()
        self.stages.append("venv")
        return paths.venv_root / "ansible-test"

    def _run_playbook(self, venv, tree, name, vars_file, handover, log, tags=None, *, timeout):
        self.stages.append((name, tuple(tags or ())))
        self.events.append(("playbook", name, tuple(tags or ())))
        assert (handover.work_dir / "reason").parent.is_dir()
        if name == "setup.yml":
            return self._setup(handover)
        key = tuple(tags or ())
        if key == ("stage",):
            (handover.work_dir / "facts.json").write_text(json.dumps({"tm_control_port": 8090, "images": []}))
        if isinstance(self.playbook_rc.get(key), BaseException):
            raise self.playbook_rc[key]
        if self.playbook_rc.get(key):
            reason = self.playbook_rc[key]
            if isinstance(reason, str):
                (handover.work_dir / "reason").write_text(reason + "\n")
            return 1
        return 0

    def _setup(self, handover):
        flag = handover.work_dir / "reboot-required"
        self.flag_before_setup.append(flag.read_text() if flag.exists() else None)
        if self.during_setup:
            self.during_setup()
        if isinstance(self.setup_rc, BaseException):
            raise self.setup_rc
        if self.setup_rc == 0:
            data = json.loads(self.paths.manifest.read_text())
            data["git"]["commit"] = handover.commit
            self.paths.manifest.write_text(json.dumps(data))
        if self.reboot_flag is not None:
            flag.write_text(self.reboot_flag)
        return self.setup_rc

    def main(self, *args, is_root=True):
        argv = list(args) or ["run", "--contract", "1", "--handover", str(self.handover_path)]
        return self._cli.main(argv, paths=self.paths, tree=self.tree, is_root=lambda: is_root)

    def resume(self):
        return self.main("resume", "--handover", str(self.handover_path))

    def state(self):
        return json.loads(self.paths.state.read_text())

    def log(self):
        path = self.paths.log_dir / (RUN + ".log")
        return path.read_text() if path.exists() else ""

    def systemctl_calls(self, verb):
        return [argv for argv in self.run.argvs() if argv[:2] == ["systemctl", verb]]

    def unit_stops(self):
        """The stops of units, without the stop of the update's slice that every run begins with."""
        return [argv for argv in self.systemctl_calls("stop") if argv != SLICE_STOP]
