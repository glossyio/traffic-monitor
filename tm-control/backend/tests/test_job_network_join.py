"""The Wi-Fi join root job, run as a script against the fake nmcli, iw, and busctl (fixtures/).

fixtures/run_job.py runs it with a non-root euid, so the stand-ins (NMCLI, IW, BUSCTL, TM_SYS_NET, the test's manifest,
run directory, and lock) are used even when the suite runs as root. The `world` fixture builds a unit: a manifest
naming the test's own user, a 0700 jobs directory, a fake /sys/class/net with a built-in radio, the fake nmcli's
hotspot profile, up, a fake iw that hears HomeNet, the fake busctl with no checkpoint, and an address and a DNS server
for HomeNet. TM_JOIN_PROBE stands in for the internet probe. The countdown after a passed test is 1 s unless a test
says otherwise, so a run that passes goes on to the switch. All names and passwords are placeholders.
"""

import fcntl
import importlib.machinery
import importlib.util
import json
import os
import pwd
import signal
import socket
import struct
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

import pytest

JOB = Path(__file__).resolve().parents[2] / "jobs" / "tm-job-network-join"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
RUNNER = FIXTURES / "run_job.py"
NMCLI = FIXTURES / "fake_nmcli.py"
IW = FIXTURES / "fake_iw.py"
BUSCTL = FIXTURES / "fake_busctl.py"
FIXTURE_MANIFEST = FIXTURES / "manifest.json"
UUID_A = "11111111-1111-4111-8111-111111111111"
PASSWORD = "placeholder-pass-1"
HOTSPOT = {
    "802-11-wireless.mode": "ap",
    "802-11-wireless.ssid": "TM-AB12",
    "802-11-wireless-security.key-mgmt": "wpa-psk",
    "802-11-wireless-security.psk": "placeholder-pass-9",
    "connection.autoconnect": "yes",
    "connection.autoconnect-priority": "-100",
}
NEW = {"ssid": "HomeNet", "password": PASSWORD}


def uuid_of(name):
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, name))


class World:
    def __init__(self, tmp_path):
        self.tmp = tmp_path
        self.jobs = tmp_path / "jobs"
        self.jobs.mkdir()
        self.jobs.chmod(0o700)
        self.manifest = tmp_path / "manifest.json"
        me = pwd.getpwuid(os.getuid()).pw_name
        self.manifest.write_text(json.dumps({**json.loads(FIXTURE_MANIFEST.read_text()), "codeowner": me}))
        self.run_dir = tmp_path / "run"
        self.lock = self.run_dir / "network.lock"
        self.lock_wait = "10"
        self.return_wait = "0.3"
        self.checkpoint_wait = "0.5"
        self.countdown = "1"
        self.probe = "reachable"
        self.iw = {"scan": ["HomeNet"], "fail": [], "hang": []}
        self.nmcli = {"profiles": {"tm-hotspot": dict(HOTSPOT)}, "active": ["tm-hotspot"], "radio": "enabled",
                      "fail": [], "ip4": {"HomeNet": {"address": "192.168.1.57/24", "dns": ["192.168.1.1"]}}}
        self.busctl = {"checkpoints": {}, "fail": []}
        self.radio("built-in")

    def radio(self, kind):
        """A fake /sys/class/net/wlan0: a built-in (SDIO) radio, or a USB adapter."""
        net = self.tmp / "sys" / "class" / "net"
        subprocess.run(["rm", "-rf", str(self.tmp / "sys")], check=True)
        (net / "wlan0" / "device").mkdir(parents=True)
        (net / "wlan0" / "wireless").mkdir()
        bus = self.tmp / "sys" / "bus" / ("usb" if kind == "usb" else "sdio")
        bus.mkdir(parents=True)
        (net / "wlan0" / "device" / "subsystem").symlink_to(bus)
        self.sys_net = net

    def hear(self, names):
        self.iw["scan"] = list(names)

    def up_fails(self, name, how="fail", after=None):
        """`connection up` on the profile fails as `how` says; with `after`, only once it has worked that often."""
        self.nmcli.setdefault("up", {})[name] = how
        if after is not None:
            self.nmcli.setdefault("up_then_fail", {})[name] = after

    def busctl_fails(self, method):
        self.busctl["fail"].append(method)

    def saved(self, name, **props):
        """A saved Wi-Fi network (infrastructure, autoconnect on); returns its uuid."""
        self.nmcli["profiles"][name] = {"802-11-wireless.ssid": name, "connection.uuid": uuid_of(name), **props}
        return uuid_of(name)

    def write_request(self, body):
        path = self.jobs / "network-join.json"
        path.write_text(body if isinstance(body, str) else json.dumps(body))
        path.chmod(0o600)
        return path

    def prepare(self, body):
        self.request = self.write_request(body)
        (self.tmp / "nmcli.json").write_text(json.dumps(self.nmcli))
        (self.tmp / "iw.json").write_text(json.dumps(self.iw))
        (self.tmp / "busctl.json").write_text(json.dumps(self.busctl))
        for log in ("nmcli.log", "iw.log", "busctl.log"):
            (self.tmp / log).unlink(missing_ok=True)
        env = {
            "PATH": os.environ["PATH"],
            "TM_CONTROL_MANIFEST": str(self.manifest),
            "NMCLI": str(NMCLI),
            "IW": str(IW),
            "BUSCTL": str(BUSCTL),
            "TM_SYS_NET": str(self.sys_net),
            "TM_NETWORK_RUN_DIR": str(self.run_dir),
            "TM_NETWORK_LOCK": str(self.lock),
            "TM_NETWORK_LOCK_WAIT": self.lock_wait,
            "TM_JOIN_RETURN_WAIT": self.return_wait,
            "TM_JOIN_CHECKPOINT_WAIT": self.checkpoint_wait,
            "TM_JOIN_COUNTDOWN": self.countdown,
            "TM_JOIN_PROBE": self.probe,
            "FAKE_NMCLI_STATE": str(self.tmp / "nmcli.json"),
            "FAKE_NMCLI_LOG": str(self.tmp / "nmcli.log"),
            "FAKE_IW_STATE": str(self.tmp / "iw.json"),
            "FAKE_IW_LOG": str(self.tmp / "iw.log"),
            "FAKE_BUSCTL_STATE": str(self.tmp / "busctl.json"),
            "FAKE_BUSCTL_LOG": str(self.tmp / "busctl.log"),
        }
        return [sys.executable, "-I", str(RUNNER), str(JOB), str(self.request)], env

    def run(self, body):
        argv, env = self.prepare(body)
        return subprocess.run(argv, env=env, capture_output=True, text=True, timeout=60)

    def start(self, body):
        """The job in its own process group, still running."""
        argv, env = self.prepare(body)
        return subprocess.Popen(argv, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                start_new_session=True)

    def counting(self, body, countdown="30"):
        """The job started with a long countdown, once it is counting down."""
        self.countdown = countdown
        job = self.start(body)
        if not wait_for(lambda: self.state()["stage"] == "countdown"):
            os.killpg(job.pid, signal.SIGKILL)
            pytest.fail("the job never started counting down: " + "".join(job.communicate(timeout=10)))
        return job

    def control(self, word):
        (self.run_dir / "network-join.control").write_text(word)

    def finish(self, job):
        stdout, stderr = job.communicate(timeout=30)
        return subprocess.CompletedProcess(job.args, job.returncode, stdout, stderr)

    def keep(self):
        """The next run starts from the fakes' state as this one left it."""
        self.nmcli = self.nm()
        self.busctl = json.loads((self.tmp / "busctl.json").read_text())

    def lines(self, name):
        path = self.tmp / name
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def log(self):
        return self.lines("nmcli.log")

    def calls(self, verb):
        return sum(1 for call in self.log() if verb in call)

    def busctl_calls(self):
        """The methods called, in order (the property read isn't a call)."""
        return [call[6] for call in self.lines("busctl.log") if call[2] == "call"]

    def busctl_log(self):
        return self.lines("busctl.log")

    def iw_calls(self):
        return self.lines("iw.log")

    def nm(self):
        return json.loads((self.tmp / "nmcli.json").read_text())

    def active(self):
        return self.nm()["active"]

    def profiles(self):
        return list(self.nm()["profiles"])

    def profile(self, name):
        return self.nm()["profiles"][name]

    def uuid(self, name):
        return self.profile(name)["connection.uuid"]

    def unsaved(self):
        return self.nm().get("unsaved", [])

    def state_path(self):
        return self.run_dir / "network-join.json"

    def state(self):
        return json.loads(self.state_path().read_text())

    def retry_path(self):
        return self.run_dir / "network-retry.json"

    def retry_state(self):
        return json.loads(self.retry_path().read_text())

    def adds(self):
        return [call for call in self.log() if "add" in call]

    def modifies(self):
        return [call for call in self.log() if "modify" in call]


@pytest.fixture
def world(tmp_path):
    return World(tmp_path)


def wait_for(condition, seconds=20):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            if condition():
                return True
        except (OSError, ValueError, KeyError):
            pass
        time.sleep(0.05)
    return False


def load_job():
    loader = importlib.machinery.SourceFileLoader("tm_job_network_join", str(JOB))
    spec = importlib.util.spec_from_loader("tm_job_network_join", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def test_the_job_is_executable():
    assert os.access(JOB, os.X_OK)


def test_a_test_that_passes_reports_the_address_and_comes_back(world):
    job = world.counting(NEW)
    try:
        state = world.state()
        assert (state["stage"], state["joined"], state["address"], state["internet"]) == (
            "countdown", True, "192.168.1.57", "reachable")
        assert world.active() == ["tm-hotspot"] and world.busctl_calls() == [
            "GetDeviceByIpIface", "CheckpointCreate", "CheckpointRollback"]
        assert (state["ssid"], state["saved"], state["before"], state["reason"]) == (
            "HomeNet", False, "tm-hotspot", None)
        assert state["uuid"] == world.uuid("HomeNet")
        assert isinstance(state["switch_monotonic"], float) and state["finished_at"] is None
        assert world.state_path().stat().st_mode & 0o777 == 0o644
    finally:
        world.control("switch")
        result = world.finish(job)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip().splitlines()[-4:] == ["back where it was", "the test passed", "counting down",
                                                      "switched"]
    assert sorted(path.name for path in world.run_dir.iterdir()) == ["network-join.json", "network.lock"]
    assert "HomeNet" not in result.stdout + result.stderr and "192.168" not in result.stdout + result.stderr


def test_the_checkpoint_calls_are_exactly_these(world):
    world.run(NEW)
    calls = [call for call in world.busctl_log() if call[2] == "call"]
    head = ["--system", "--json=short", "call", "org.freedesktop.NetworkManager", "/org/freedesktop/NetworkManager",
            "org.freedesktop.NetworkManager"]
    assert calls == [
        [*head, "GetDeviceByIpIface", "s", "wlan0"],
        [*head, "CheckpointCreate", "aouu", "1", "/org/freedesktop/NetworkManager/Devices/3", "90", "0"],
        [*head, "CheckpointRollback", "o", "/org/freedesktop/NetworkManager/Checkpoint/1"],
    ]


def test_the_profile_under_test_is_in_memory_with_autoconnect_off_and_the_built_in_mac(world):
    job = world.counting(NEW)
    try:
        assert "HomeNet" in world.unsaved() and world.profile("HomeNet")["connection.autoconnect"] == "no"
        assert world.profile("HomeNet")["802-11-wireless-security.psk"] == PASSWORD
    finally:
        world.control("cancel")
        result = world.finish(job)
    assert result.returncode == 0, result.stdout + result.stderr
    [add] = world.adds()
    assert add[:4] == ["connection", "add", "save", "no"]
    pairs = dict(zip(add[4::2], add[5::2]))
    assert pairs == {
        "type": "wifi", "connection.id": "HomeNet", "connection.uuid": world.state()["uuid"],
        "connection.interface-name": "wlan0", "connection.autoconnect": "no", "802-11-wireless.ssid": "HomeNet",
        "802-11-wireless.cloned-mac-address": "permanent", "802-11-wireless-security.key-mgmt": "wpa-psk",
        "802-11-wireless-security.psk": "***"}
    assert ["--wait", "45", "connection", "up", "uuid", world.state()["uuid"]] in world.log()


@pytest.mark.parametrize("case", ["passes", "fails", "add-fails", "no-checkpoint", "busy"])
def test_the_password_is_in_no_output_and_no_state_file(world, case):
    world.saved("Depot")
    if case == "fails":
        world.up_fails("HomeNet")
    elif case == "add-fails":
        world.nmcli["fail"].append("add")  # the fake's error quotes the whole command line, password included
    elif case == "no-checkpoint":
        world.busctl_fails("CheckpointCreate")
    elif case == "busy":
        world.lock.parent.mkdir()
        world.lock_wait = "0.2"
        held = open(world.lock, "w")
        fcntl.flock(held, fcntl.LOCK_EX)
    result = world.run(NEW)
    if case == "busy":
        held.close()
    assert PASSWORD not in result.stdout + result.stderr
    for path in world.run_dir.iterdir():
        assert PASSWORD not in path.read_text()
    assert "password" not in world.state()


def test_the_request_is_deleted_before_the_test_starts(world):
    world.nmcli["up_delay"] = {"HomeNet": 0.5}
    job = world.start(NEW)
    try:
        assert wait_for(lambda: world.state()["stage"] == "testing")
        assert not world.request.exists() and list(world.jobs.iterdir()) == []
    finally:
        job.communicate(timeout=30)
    assert job.returncode == 0


def test_a_network_that_is_not_heard_is_never_tested(world):
    world.hear([])
    result = world.run(NEW)
    assert result.returncode == 0, result.stdout + result.stderr
    assert world.state()["reason"] == "not_in_range" and world.calls("add") == 0 and world.busctl_calls() == []
    assert world.state()["stage"] == "failed" and world.state()["finished_at"].endswith("+00:00")
    assert result.stdout.strip().splitlines()[-1] == "the network isn't in range"
    assert world.calls("up") == 0 and world.active() == ["tm-hotspot"]


def test_a_scan_that_fails_does_not_stop_the_test(world):
    world.iw["fail"] = ["scan"]
    result = world.run(NEW)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "the scan failed (iw exit status 240)" in result.stdout.splitlines()
    assert world.state()["stage"] == "joined" and world.calls("up") == 2


def test_a_join_that_fails_deletes_the_profile_and_comes_back(world):
    world.up_fails("HomeNet")
    result = world.run(NEW)
    assert result.returncode == 0, result.stdout + result.stderr
    assert world.state()["reason"] == "not_joined" and "HomeNet" not in world.profiles()
    assert world.active() == ["tm-hotspot"]
    assert world.state()["stage"] == "failed" and world.state()["joined"] is False
    assert world.busctl_calls()[-1] == "CheckpointRollback"
    assert result.stdout.strip().splitlines()[-1] == "the test failed (nmcli exit status 4)"
    assert "HomeNet" not in result.stdout + result.stderr  # the fake's error names it
    assert not world.retry_path().exists()


def test_a_network_that_gives_no_address_is_its_own_reason(world):
    world.up_fails("HomeNet", "timeout")
    world.nmcli["device_states"] = {"HomeNet": 70}
    result = world.run(NEW)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (world.state()["stage"], world.state()["reason"]) == ("failed", "no_address")
    assert "HomeNet" not in world.profiles() and world.active() == ["tm-hotspot"]
    assert result.stdout.strip().splitlines()[-1] == "the test failed (nmcli exit status 3)"


def test_a_timeout_on_another_state_is_not_joined(world):
    world.up_fails("HomeNet", "timeout")
    world.nmcli["device_states"] = {"HomeNet": 50}
    result = world.run(NEW)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (world.state()["stage"], world.state()["reason"]) == ("failed", "not_joined")
    assert world.active() == ["tm-hotspot"]


def test_a_test_from_a_saved_network_returns_to_it(world):
    world.saved("Depot")
    world.nmcli["active"] = ["Depot"]
    job = world.counting(NEW)
    assert world.state()["before"] == "Depot" and world.active() == ["Depot"]
    world.control("cancel")
    result = world.finish(job)
    assert result.returncode == 0, result.stdout + result.stderr
    assert world.active() == ["Depot"] and world.calls("up") == 1


def test_a_radio_that_does_not_come_back_is_brought_back(world):
    world.busctl_fails("CheckpointRollback")
    job = world.counting(NEW)
    world.control("cancel")
    result = world.finish(job)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "the rollback failed (busctl exit status 1)" in result.stdout.splitlines()
    ups = [call for call in world.log() if "up" in call]
    assert ups[-1] == ["--wait", "45", "connection", "up", "uuid", uuid_of("tm-hotspot")] and len(ups) == 2
    assert world.active() == ["tm-hotspot"] and world.state()["stage"] == "cancelled"
    assert "back where it was" in result.stdout.splitlines()


def test_a_radio_that_still_does_not_come_back_is_an_error(world):
    world.nmcli["device_state"] = 30  # the device reads as disconnected whatever the rollback did
    world.up_fails("tm-hotspot")
    result = world.run(NEW)
    assert result.returncode == 1
    assert result.stdout.strip().splitlines()[-1] == "failed: come back (the Wi-Fi did not come back)"
    assert (world.state()["stage"], world.state()["reason"]) == ("failed", "error")
    assert "HomeNet" not in world.profiles() and world.calls("modify") == 0


def test_an_idle_radio_is_left_idle(world):
    world.nmcli["active"] = []
    job = world.counting(NEW)
    world.control("cancel")
    result = world.finish(job)
    assert result.returncode == 0, result.stdout + result.stderr
    assert world.state()["before"] is None and world.active() == [] and world.calls("up") == 1


def test_no_checkpoint_no_test(world):
    world.busctl_fails("CheckpointCreate")
    result = world.run(NEW)
    assert result.returncode == 1 and world.calls("up") == 0 and world.state()["reason"] == "error"
    assert world.state()["stage"] == "failed" and world.calls("add") == 0
    assert result.stdout.strip().splitlines()[-1] == "failed: make the checkpoint (busctl exit status 1)"
    assert "HomeNet" not in result.stdout + result.stderr


def test_an_add_that_fails_still_comes_back_and_ends_as_an_error(world):
    world.nmcli["fail"].append("add")
    result = world.run(NEW)
    assert result.returncode == 1
    assert result.stdout.strip().splitlines()[-1] == "failed: add the network (nmcli exit status 4)"
    assert world.busctl_calls() == ["GetDeviceByIpIface", "CheckpointCreate", "CheckpointRollback"]
    assert (world.state()["stage"], world.state()["reason"]) == ("failed", "error")
    assert world.active() == ["tm-hotspot"]


def test_an_address_that_cannot_be_read_still_comes_back_and_ends_as_an_error(world):
    world.nmcli["fail_fields"] = ["IP4.ADDRESS"]
    result = world.run(NEW)
    assert result.returncode == 1
    assert result.stdout.strip().splitlines()[-1] == "failed: read the address (nmcli exit status 4)"
    assert world.busctl_calls() == ["GetDeviceByIpIface", "CheckpointCreate", "CheckpointRollback"]
    assert (world.state()["stage"], world.state()["reason"]) == ("failed", "error")
    assert world.active() == ["tm-hotspot"] and "HomeNet" not in world.profiles()


def test_a_retry_file_that_cannot_be_written_ends_as_an_error_after_coming_back(world):
    home = world.saved("HomeNet")
    world.up_fails("HomeNet")
    (world.run_dir / "network-retry.json").mkdir(parents=True)  # a rename onto a directory fails
    result = world.run({"uuid": home})
    assert result.returncode == 1
    assert result.stdout.strip().splitlines()[-1] == "failed: record the result (IsADirectoryError)"
    assert "back where it was" in result.stdout.splitlines()
    assert (world.state()["stage"], world.state()["reason"]) == ("failed", "error")
    assert world.active() == ["tm-hotspot"] and "HomeNet" in world.profiles()


def test_a_saved_network_is_tested_with_its_own_profile(world):
    home = world.saved("HomeNet")
    result = world.run({"uuid": home})
    assert result.returncode == 0, result.stdout + result.stderr
    assert world.calls("add") == 0 and ["--wait", "45", "connection", "up", "uuid", home] in world.log()
    state = world.state()
    assert (state["stage"], state["ssid"], state["uuid"], state["saved"]) == ("joined", "HomeNet", home, True)
    assert "HomeNet" in world.profiles() and world.active() == ["HomeNet"]


def test_a_saved_network_that_fails_is_kept_and_gets_a_failure_on_record(world):
    home = world.saved("HomeNet")
    world.up_fails("HomeNet")
    world.run_dir.mkdir()
    other = {"name": "Depot", "failures": 2, "last_failure": 1000.5}
    world.retry_path().write_text(json.dumps({"networks": {UUID_A: other},
                                              "last_run": {"at": "2026-11-11T00:00:00+00:00", "outcome": "joined"}}))
    before = time.time()
    result = world.run({"uuid": home})
    assert result.returncode == 0, result.stdout + result.stderr
    assert "HomeNet" in world.profiles() and world.state()["reason"] == "not_joined"
    retry = world.retry_state()
    entry = retry["networks"][home]
    assert (entry["name"], entry["failures"]) == ("HomeNet", 1)
    assert isinstance(entry["last_failure"], float) and before <= entry["last_failure"] <= time.time()
    assert retry["networks"][UUID_A] == other and retry["last_run"]["outcome"] == "joined"
    assert world.retry_path().stat().st_mode & 0o777 == 0o644
    world.keep()
    world.run({"uuid": home})
    assert world.retry_state()["networks"][home]["failures"] == 2


def test_a_saved_network_that_gives_no_address_gets_a_failure_on_record(world):
    home = world.saved("HomeNet")
    world.up_fails("HomeNet", "timeout")
    world.nmcli["device_states"] = {"HomeNet": 70}
    result = world.run({"uuid": home})
    assert result.returncode == 0, result.stdout + result.stderr
    assert world.state()["reason"] == "no_address" and world.retry_state()["networks"][home]["failures"] == 1


def test_a_saved_network_that_passes_loses_its_failure_on_record(world):
    home = world.saved("HomeNet")
    world.run_dir.mkdir()
    other = {"name": "Depot", "failures": 1, "last_failure": 1000.5}
    world.retry_path().write_text(json.dumps({
        "networks": {home: {"name": "HomeNet", "failures": 2, "last_failure": 900.0}, UUID_A: other},
        "last_run": {"at": "2026-11-11T00:00:00+00:00", "outcome": "join-failed"}}))
    result = world.run({"uuid": home})
    assert result.returncode == 0, result.stdout + result.stderr
    assert world.retry_state() == {"networks": {UUID_A: other},
                                   "last_run": {"at": "2026-11-11T00:00:00+00:00", "outcome": "join-failed"}}


def test_a_hidden_saved_network_is_tested_without_being_heard(world):
    home = world.saved("HomeNet", **{"802-11-wireless.hidden": "yes"})
    world.hear([])
    result = world.run({"uuid": home})
    assert result.returncode == 0, result.stdout + result.stderr
    assert world.state()["stage"] == "joined" and world.calls("up") == 2


def test_a_saved_network_that_is_not_heard_is_never_tested(world):
    home = world.saved("HomeNet")
    world.hear(["Other"])
    result = world.run({"uuid": home})
    assert result.returncode == 0 and world.state()["reason"] == "not_in_range"
    assert world.busctl_calls() == [] and world.calls("up") == 0 and world.state()["ssid"] == "HomeNet"
    assert not world.retry_path().exists()


@pytest.mark.parametrize("target", ["the hotspot", "an Ethernet profile", "the network in use", "a uuid nobody has"])
def test_only_another_saved_wifi_network_can_be_tested_by_uuid(world, target):
    if target == "the hotspot":
        value = uuid_of("tm-hotspot")
    elif target == "an Ethernet profile":
        world.nmcli["profiles"]["Wired connection 1"] = {"connection.type": "802-3-ethernet",
                                                         "connection.uuid": uuid_of("Wired connection 1")}
        value = uuid_of("Wired connection 1")
    elif target == "the network in use":
        value = world.saved("Depot")
        world.nmcli["active"] = ["Depot"]
    else:
        value = UUID_A
    result = world.run({"uuid": value})
    assert result.returncode == 1 and result.stdout.startswith("refused: ")
    assert len(result.stdout.strip().splitlines()) == 1
    assert (world.state()["stage"], world.state()["reason"]) == ("failed", "error")
    assert world.calls("up") == 0 and world.calls("add") == 0 and world.calls("delete") == 0
    assert world.busctl_calls() == [] and world.iw_calls() == []
    assert value not in result.stdout


def test_a_held_lock_ends_as_busy_without_touching_the_radio(world):
    world.lock.parent.mkdir()
    world.lock_wait = "0.2"
    with open(world.lock, "w") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        result = world.run(NEW)
    assert result.returncode == 0 and result.stdout.strip() == "the Wi-Fi is busy"
    state = world.state()
    assert (state["stage"], state["reason"], state["ssid"], state["saved"]) == ("failed", "busy", "HomeNet", False)
    assert world.log() == [] and world.busctl_log() == [] and world.iw_calls() == []
    assert not world.request.exists()


def test_a_busy_run_leaves_a_dead_runs_state_for_the_next_one(world):
    world.run_dir.mkdir()
    dead = json.dumps({"stage": "testing", "ssid": "Other", "uuid": UUID_A, "saved": False, "before": "tm-hotspot",
                       "joined": None, "reason": None, "address": None, "internet": None, "switch_monotonic": None,
                       "finished_at": None})
    world.state_path().write_text(dead)
    world.lock_wait = "0.2"
    with open(world.lock, "w") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        result = world.run(NEW)
    assert result.returncode == 0 and result.stdout.strip() == "the Wi-Fi is busy"
    assert world.state_path().read_text() == dead


def test_a_run_killed_mid_test_is_cleaned_up_by_the_next_run(world):
    world.nmcli["up_delay"] = {"HomeNet": 30}
    job = world.start(NEW)
    try:
        assert wait_for(lambda: world.state()["stage"] == "testing" and "HomeNet" in world.nm()["profiles"]
                        and any("up" in call for call in world.log()))
    finally:
        os.killpg(job.pid, signal.SIGKILL)
        job.communicate(timeout=10)
    first = world.state()
    assert first["stage"] == "testing" and "HomeNet" in world.profiles()
    assert len(json.loads((world.tmp / "busctl.json").read_text())["checkpoints"]) == 1

    world.keep()
    world.nmcli["active"] = [first["ssid"]]  # where the radio is while the dead run's checkpoint is pending
    world.hear(["HomeNet", "Office"])
    world.nmcli["ip4"]["Office"] = {"address": "192.168.2.20/24", "dns": ["192.168.2.1"]}
    result = world.run({"ssid": "Office", "password": "placeholder-pass-2"})
    assert result.returncode == 0, result.stdout + result.stderr
    assert "rolled back what an earlier run left" in result.stdout.splitlines()
    assert "HomeNet" not in world.profiles() and world.state()["ssid"] == "Office"
    assert world.state()["stage"] == "joined" and world.state()["before"] == "tm-hotspot"
    assert world.busctl_calls() == ["CheckpointRollback", "GetDeviceByIpIface", "CheckpointCreate",
                                    "CheckpointRollback"]
    assert world.active() == ["Office"]


def test_a_checkpoint_a_dead_run_left_is_rolled_back_first(world):
    dead_uuid = str(uuid.uuid4())
    world.nmcli["profiles"]["HomeNet"] = {"802-11-wireless.ssid": "HomeNet", "connection.uuid": dead_uuid,
                                          "connection.autoconnect": "no"}
    world.nmcli["unsaved"] = ["HomeNet"]
    world.nmcli["active"] = ["HomeNet"]
    world.busctl = {"checkpoints": {"/org/freedesktop/NetworkManager/Checkpoint/6": {"active": ["tm-hotspot"]}},
                    "next": 7, "fail": []}
    world.run_dir.mkdir()
    world.state_path().write_text(json.dumps({
        "stage": "testing", "ssid": "HomeNet", "uuid": dead_uuid, "saved": False, "before": "tm-hotspot",
        "joined": None, "reason": None, "address": None, "internet": None, "switch_monotonic": None,
        "finished_at": None}))
    (world.run_dir / "network-join.control").write_text("cancel")
    result = world.run(NEW)
    assert result.returncode == 0, result.stdout + result.stderr
    lines = result.stdout.strip().splitlines()
    assert lines[0] == "rolled back what an earlier run left"
    calls = [call for call in world.busctl_log() if call[2] == "call"]
    assert calls[0][6:] == ["CheckpointRollback", "o", "/org/freedesktop/NetworkManager/Checkpoint/6"]
    assert world.busctl_calls()[1:] == ["GetDeviceByIpIface", "CheckpointCreate", "CheckpointRollback"]
    assert ["connection", "delete", "uuid", dead_uuid] in world.log()
    assert world.log().index(["connection", "delete", "uuid", dead_uuid]) < world.log().index(world.adds()[0])
    state = world.state()
    assert state["stage"] == "joined" and state["uuid"] != dead_uuid and state["before"] == "tm-hotspot"
    assert not (world.run_dir / "network-join.control").exists()


def test_a_rollback_of_what_an_earlier_run_left_that_fails_stops_at_the_checkpoint(world):
    world.busctl = {"checkpoints": {"/org/freedesktop/NetworkManager/Checkpoint/6": {"active": ["tm-hotspot"]}},
                    "next": 7, "fail": ["CheckpointRollback"]}
    result = world.run(NEW)
    assert result.returncode == 1
    assert result.stdout.strip().splitlines()[-1] == "failed: make the checkpoint (busctl exit status 1)"
    assert world.calls("up") == 0 and world.calls("add") == 0
    assert (world.state()["stage"], world.state()["reason"]) == ("failed", "error")


def test_a_finished_result_is_not_cleaned_up(world):
    old_uuid = world.saved("Depot", **{"connection.autoconnect": "no"})
    world.run_dir.mkdir()
    world.state_path().write_text(json.dumps({
        "stage": "failed", "ssid": "Depot", "uuid": old_uuid, "saved": False, "before": "tm-hotspot",
        "joined": False, "reason": "not_joined", "address": None, "internet": None, "switch_monotonic": None,
        "finished_at": "2026-11-11T00:00:00+00:00"}))
    result = world.run(NEW)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Depot" in world.profiles() and world.calls("delete") == 0


def test_no_test_on_a_radio_that_is_off_or_a_usb_adapter(world):
    world.nmcli["radio"] = "disabled"
    result = world.run(NEW)
    assert result.returncode == 1 and result.stdout.strip() == "refused: the Wi-Fi radio is switched off"
    assert (world.state()["stage"], world.state()["reason"]) == ("failed", "error")
    assert world.iw_calls() == [] and world.busctl_calls() == [] and world.calls("up") == 0

    world.nmcli["radio"] = "enabled"
    world.radio("usb")
    result = world.run(NEW)
    assert result.returncode == 1 and result.stdout.strip() == "refused: the unit has no built-in Wi-Fi radio"
    assert world.iw_calls() == [] and world.busctl_calls() == [] and world.calls("up") == 0


@pytest.mark.parametrize("request_", [
    {}, {"ssid": "HomeNet"}, {"password": "placeholder-pass-1"}, {"ssid": "HomeNet", "password": "short12"},
    {"ssid": "a" * 33, "password": "placeholder-pass-1"}, {"ssid": "Home\nNet", "password": "placeholder-pass-1"},
    {"ssid": "HomeNet", "password": "placeholder-pass-1", "uuid": UUID_A}, {"uuid": "tm-hotspot"},
    {"ssid": "HomeNet", "password": "pässwörd-1"}, {"ssid": "é" * 17, "password": "placeholder-pass-1"},
    {"ssid": "", "password": "placeholder-pass-1"}, {"ssid": "HomeNet", "password": "x" * 64},
    {"ssid": 5, "password": "placeholder-pass-1"}, {"uuid": "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA"},
    {"action": "join"}])
def test_a_request_is_refused_unless_it_is_exactly_one_of_the_two_forms(world, request_):
    result = world.run(request_)
    assert result.returncode == 1 and result.stdout.startswith("refused: ")
    assert len(result.stdout.strip().splitlines()) == 1
    assert world.log() == [] and world.iw_calls() == [] and world.busctl_log() == []
    assert not world.request.exists() and not world.state_path().exists()
    for value in request_.values():
        if isinstance(value, str) and len(value.strip()) >= 4:
            assert value.strip() not in result.stdout + result.stderr


@pytest.mark.parametrize("body", ["not json", "[1, 2]", json.dumps({"ssid": "x" * 5000, "password": PASSWORD})])
def test_a_request_that_is_not_a_small_json_object_is_refused(world, body):
    result = world.run(body)
    assert result.returncode == 1 and result.stdout.startswith("refused: ")
    assert world.log() == [] and not world.request.exists()


def test_the_request_must_be_tm_controls_own_plain_file(world):
    target = world.tmp / "elsewhere.json"
    target.write_text(json.dumps(NEW))
    argv, env = world.prepare(NEW)
    link = world.jobs / "network-join.json"
    link.unlink()
    link.symlink_to(target)
    result = subprocess.run(argv, env=env, capture_output=True, text=True, timeout=60)
    assert result.returncode == 1 and result.stdout.startswith("refused: ")
    assert world.log() == [] and target.exists() and not link.is_symlink()


def test_a_jobs_directory_others_can_write_is_not_trusted(world):
    world.jobs.chmod(0o777)
    result = world.run(NEW)
    assert result.returncode == 1 and result.stdout.startswith("refused: ")
    assert world.log() == []


def test_a_name_with_spaces_at_its_ends_and_a_colon_is_one_argument(world):
    world.hear(["\\x20Home:Net\\x20"])  # iw writes a space at either end of a name as \x20
    world.nmcli["ip4"][" Home:Net "] = {"address": "192.168.1.57/24", "dns": ["192.168.1.1"]}
    result = world.run({"ssid": " Home:Net ", "password": " placeholder pass "})
    assert result.returncode == 0, result.stdout + result.stderr
    [add] = world.adds()
    pairs = dict(zip(add[4::2], add[5::2]))
    assert pairs["connection.id"] == " Home:Net " and pairs["802-11-wireless.ssid"] == " Home:Net "
    assert world.profile(" Home:Net ")["802-11-wireless-security.psk"] == " placeholder pass "
    assert world.state()["ssid"] == " Home:Net " and world.state()["stage"] == "joined"
    assert "Home" not in result.stdout + result.stderr


def test_the_lock_is_free_after_a_run(world):
    world.run(NEW)
    with open(world.lock) as file:
        fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)


def test_as_root_the_test_settings_are_ignored(monkeypatch):
    job = load_job()
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    for name in ("NMCLI", "IW", "BUSCTL", "TM_SYS_NET", "TM_NETWORK_RUN_DIR", "TM_NETWORK_LOCK",
                 "TM_NETWORK_LOCK_WAIT", "TM_JOIN_RETURN_WAIT", "TM_JOIN_CHECKPOINT_WAIT", "TM_JOIN_COUNTDOWN",
                 "TM_JOIN_PROBE"):
        monkeypatch.setenv(name, "/elsewhere")
    assert job.trusted("BUSCTL", job.BUSCTL) == "/usr/bin/busctl"
    assert job.trusted("TM_NETWORK_RUN_DIR", job.RUN_DIR) == "/run/traffic-monitor"
    assert job.trusted("TM_JOIN_PROBE", "") == ""
    assert job.trusted_seconds("TM_JOIN_RETURN_WAIT", job.RETURN_WAIT) == 15
    monkeypatch.setenv("TM_JOIN_COUNTDOWN", "1")
    assert job.trusted_seconds("TM_JOIN_COUNTDOWN", job.COUNTDOWN) == 300


def test_the_fixed_values():
    job = load_job()
    assert (job.JOIN_WAIT, job.CHECKPOINT_TIMEOUT, job.RETURN_WAIT, job.PROBE_TIMEOUT) == (45, 90, 15, 10)
    assert (job.STATE_FILE, job.RETRY_FILE, job.NAME_MAX_BYTES) == ("network-join.json", "network-retry.json", 32)
    assert (job.COUNTDOWN, job.CONTROL_FILE) == (300, "network-join.control")
    assert job.REQUEST == "/run/tm-control/jobs/network-join.json"


# The countdown and the switch.

def test_the_countdown_ends_in_a_switch(world):
    result = world.run({"ssid": "HomeNet", "password": "placeholder-pass-1"})
    assert result.returncode == 0, result.stdout + result.stderr
    assert world.state()["stage"] == "joined" and world.active() == ["HomeNet"]
    profile = world.profile("HomeNet")
    assert profile["connection.autoconnect"] == "yes" and "HomeNet" not in world.unsaved()
    state = world.state()
    assert (state["joined"], state["address"], state["saved"]) == (True, "192.168.1.57", True)
    assert state["finished_at"].endswith("+00:00")
    assert world.log()[-3:-1] == [
        ["connection", "modify", "uuid", state["uuid"], "connection.autoconnect", "yes",
         "connection.autoconnect-priority", "1"],
        ["--wait", "45", "connection", "up", "uuid", state["uuid"]]]
    assert result.stdout.strip().splitlines()[-2:] == ["counting down", "switched"]


def test_the_deadline_is_on_the_monotonic_clock(world):
    job = world.counting(NEW)
    try:
        deadline = world.state()["switch_monotonic"]
        assert abs(deadline - (time.monotonic() + 30)) < 1
        assert world.active() == ["tm-hotspot"] and world.calls("modify") == 0
    finally:
        world.control("cancel")
        world.finish(job)


def test_a_new_network_goes_above_every_saved_one(world):
    world.saved("Depot", **{"connection.autoconnect-priority": "0"})
    world.saved("Office", **{"connection.autoconnect-priority": "3"})
    world.saved("Spare", **{"connection.autoconnect-priority": "9", "connection.autoconnect": "no"})
    result = world.run(NEW)
    assert result.returncode == 0, result.stdout + result.stderr
    assert world.profile("HomeNet")["connection.autoconnect-priority"] == "4"
    assert world.profile("Office")["connection.autoconnect-priority"] == "3"  # the others are left as they are
    assert world.profile("tm-hotspot")["connection.autoconnect-priority"] == "-100"


def test_switch_now_ends_the_countdown_early(world):
    job = world.counting(NEW)
    started = time.monotonic()
    world.control("switch")
    result = world.finish(job)
    assert time.monotonic() - started < 3
    assert result.returncode == 0, result.stdout + result.stderr
    assert world.state()["stage"] == "joined" and world.active() == ["HomeNet"]
    assert not (world.run_dir / "network-join.control").exists()


def test_cancel_deletes_the_profile_and_leaves_the_hotspot(world):
    job = world.counting(NEW)
    started = time.monotonic()
    world.control("cancel")
    result = world.finish(job)
    assert time.monotonic() - started < 3
    assert result.returncode == 0, result.stdout + result.stderr
    assert world.state()["stage"] == "cancelled" and world.state()["finished_at"].endswith("+00:00")
    assert "HomeNet" not in world.profiles() and world.active() == ["tm-hotspot"]
    assert world.calls("modify") == 0
    assert result.stdout.strip().splitlines()[-1] == "cancelled"
    assert not (world.run_dir / "network-join.control").exists()


def test_cancel_keeps_a_saved_network(world):
    home = world.saved("HomeNet", **{"connection.autoconnect-priority": "2"})
    job = world.counting({"uuid": home})
    world.control("cancel")
    result = world.finish(job)
    assert result.returncode == 0, result.stdout + result.stderr
    assert world.state()["stage"] == "cancelled" and world.calls("delete") == 0
    assert world.profile("HomeNet")["connection.autoconnect-priority"] == "2"
    assert world.active() == ["tm-hotspot"]


def test_a_cancel_that_arrived_during_the_test_is_honoured_when_the_hotspot_is_back(world):
    world.nmcli["up_delay"] = {"HomeNet": 1}
    world.countdown = "30"
    job = world.start(NEW)
    try:
        assert wait_for(lambda: world.state()["stage"] == "testing" and world.calls("up") == 1)
        world.control("cancel")
    finally:
        result = world.finish(job)
    assert result.returncode == 0, result.stdout + result.stderr
    assert world.state()["stage"] == "cancelled" and "HomeNet" not in world.profiles()
    assert world.calls("modify") == 0 and world.active() == ["tm-hotspot"]


def test_a_new_password_replaces_the_saved_profile_at_the_switch(world):
    old = world.saved("HomeNet 1", **{"802-11-wireless.ssid": "HomeNet"})
    other = world.saved("Depot")
    result = world.run(NEW)
    assert result.returncode == 0, result.stdout + result.stderr
    assert ["connection", "delete", "uuid", old] in world.log()
    assert world.log().index(world.modifies()[0]) < world.log().index(["connection", "delete", "uuid", old])
    assert "HomeNet 1" not in world.profiles() and other in [world.uuid(name) for name in world.profiles()]
    assert world.state()["stage"] == "joined" and world.active() == ["HomeNet"]


def test_a_saved_network_is_not_deleted_as_its_own_duplicate(world):
    home = world.saved("HomeNet")
    result = world.run({"uuid": home})
    assert result.returncode == 0, result.stdout + result.stderr
    assert world.calls("delete") == 0 and world.state()["stage"] == "joined"


def test_a_switch_that_fails_brings_back_the_hotspot_and_starts_the_wait(world):
    world.up_fails("HomeNet", after=1)  # "up_then_fail": the test's up works, the switch's fails
    before = time.time()
    result = world.run(NEW)
    assert result.returncode == 0, result.stdout + result.stderr
    assert world.state()["stage"] == "switch_failed" and world.active() == ["tm-hotspot"]
    assert world.profile("HomeNet")["connection.autoconnect"] == "yes"  # still saved
    assert "HomeNet" not in world.unsaved()
    entry = world.retry_state()["networks"][world.uuid("HomeNet")]
    assert (entry["name"], entry["failures"]) == ("HomeNet", 1) and before <= entry["last_failure"] <= time.time()
    assert world.log()[-1] == ["--wait", "45", "connection", "up", "uuid", uuid_of("tm-hotspot")]
    assert result.stdout.strip().splitlines()[-1] == "the switch failed (nmcli exit status 4)"


def test_a_switch_whose_up_fails_while_networkmanager_joined_by_itself_counts(world):
    world.up_fails("HomeNet", "fail-started", after=1)
    result = world.run(NEW)
    assert result.returncode == 0, result.stdout + result.stderr
    assert world.state()["stage"] == "joined" and world.active() == ["HomeNet"]
    assert not world.retry_path().exists()


def test_the_lock_is_held_through_the_countdown(world):
    job = world.counting(NEW)
    try:
        with open(world.lock) as file, pytest.raises(BlockingIOError):
            fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    finally:
        world.control("cancel")
        world.finish(job)


def test_a_run_killed_while_switching_leaves_a_saved_profile_the_next_run_keeps(world):
    world.nmcli["up_delay"] = {"HomeNet": 2}
    world.countdown = "0.2"
    job = world.start(NEW)
    try:
        assert wait_for(lambda: world.state()["stage"] == "switching" and world.calls("up") == 2)
    finally:
        os.killpg(job.pid, signal.SIGKILL)
        job.communicate(timeout=10)
    assert world.state()["saved"] is True
    assert "HomeNet" not in world.unsaved() and world.profile("HomeNet")["connection.autoconnect"] == "yes"
    world.keep()
    world.nmcli["up_delay"] = {}
    world.hear(["HomeNet", "Office"])
    world.nmcli["ip4"]["Office"] = {"address": "192.168.2.20/24", "dns": ["192.168.2.1"]}
    result = world.run({"ssid": "Office", "password": "placeholder-pass-2"})
    assert result.returncode == 0, result.stdout + result.stderr
    assert "HomeNet" in world.profiles() and world.calls("delete") == 0


def test_a_stop_during_the_test_comes_back_at_once(world):
    world.nmcli["up_delay"] = {"HomeNet": 30}
    job = world.start(NEW)
    try:
        assert wait_for(lambda: world.state()["stage"] == "testing" and world.calls("up") == 1)
    finally:
        started = time.monotonic()
        job.send_signal(signal.SIGTERM)
        result = world.finish(job)
    assert time.monotonic() - started < 5
    assert result.returncode == 1
    assert result.stdout.strip().splitlines()[-1] == "failed: test the network (stopped)"
    assert "back where it was" in result.stdout.splitlines()
    assert (world.state()["stage"], world.state()["reason"]) == ("failed", "error")
    assert world.busctl_calls()[-1] == "CheckpointRollback"
    assert "HomeNet" not in world.profiles() and world.active() == ["tm-hotspot"]


def test_a_stop_during_the_countdown_ends_like_a_cancel(world):
    job = world.counting(NEW)
    started = time.monotonic()
    job.send_signal(signal.SIGTERM)
    result = world.finish(job)
    assert time.monotonic() - started < 3
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip().splitlines()[-2:] == ["stopped during the countdown", "cancelled"]
    assert world.state()["stage"] == "cancelled" and "HomeNet" not in world.profiles()
    assert world.active() == ["tm-hotspot"] and world.calls("modify") == 0


# The internet probe.

ANSWER_WITH_A_CNAME_THEN_AN_A = (
    struct.pack("!HHHHHH", 0x1234, 0x8180, 1, 2, 0, 0)
    + b"\x12connectivity-check\x06ubuntu\x03com\x00" + struct.pack("!HH", 1, 1)
    + b"\xc0\x0c" + struct.pack("!HHIH", 5, 1, 60, 6) + b"\x03cdn\xc0\x1f"  # a CNAME to cdn.ubuntu.com
    + b"\xc0\x3b" + struct.pack("!HHIH", 1, 1, 60, 4) + bytes([192, 0, 2, 10])  # its A record
)


def test_the_dns_question_and_its_answer():
    join = load_job()
    packet = join.dns_question("connectivity-check.ubuntu.com", 0x1234)
    assert packet[:2] == b"\x12\x34" and b"\x12connectivity-check\x06ubuntu\x03com\x00" in packet
    assert packet[-4:] == b"\x00\x01\x00\x01"  # type A, class IN
    assert join.dns_address(ANSWER_WITH_A_CNAME_THEN_AN_A, 0x1234) == "192.0.2.10"
    assert join.dns_address(ANSWER_WITH_A_CNAME_THEN_AN_A, 0x9999) is None and join.dns_address(b"\x00", 0x1234) is None
    assert join.dns_address(ANSWER_WITH_A_CNAME_THEN_AN_A[:-2], 0x1234) is None  # cut short
    no_answer = struct.pack("!HHHHHH", 0x1234, 0x8183, 1, 0, 0, 0) + ANSWER_WITH_A_CNAME_THEN_AN_A[12:47]
    assert join.dns_address(no_answer, 0x1234) is None


def test_only_a_204_means_the_internet_is_reachable():
    join = load_job()
    assert join.http_verdict(b"HTTP/1.1 204 No Content") == "reachable"
    assert join.http_verdict(b"HTTP/1.1 200 OK") == "sign_in_page"
    assert join.http_verdict(b"HTTP/1.0 302 Found") == "sign_in_page"


class Servers:
    """A local DNS server that drops the first `drop` questions and answers the rest with 127.0.0.1, and a web
    server that answers every request with `status`."""

    def __init__(self, drop=1, status=b"HTTP/1.1 204 No Content"):
        self.questions = 0
        self.udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp.bind(("127.0.0.1", 0))
        self.tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.tcp.bind(("127.0.0.1", 0))
        self.tcp.listen(4)
        self.requests = []
        self.drop, self.status = drop, status
        threading.Thread(target=self.dns, daemon=True).start()
        threading.Thread(target=self.web, daemon=True).start()

    def dns(self):
        while True:
            try:
                packet, peer = self.udp.recvfrom(512)
            except OSError:
                return
            self.questions += 1
            if self.questions <= self.drop:
                continue
            question = packet[12:]
            header = packet[:2] + struct.pack("!HHHHH", 0x8180, 1, 1, 0, 0)
            answer = b"\xc0\x0c" + struct.pack("!HHIH", 1, 1, 60, 4) + bytes([127, 0, 0, 1])
            self.udp.sendto(header + question + answer, peer)

    def web(self):
        while True:
            try:
                connection, _ = self.tcp.accept()
            except OSError:
                return
            with connection:
                self.requests.append(connection.recv(1024))
                connection.sendall(self.status + b"\r\nContent-Length: 0\r\n\r\n")

    def close(self):
        self.udp.close()
        self.tcp.close()


def test_the_probe_asks_the_dns_server_again_after_no_answer():
    join = load_job()
    servers = Servers(drop=1)
    try:
        started = time.monotonic()
        verdict = join.probe(None, ["127.0.0.1"], dns_port=servers.udp.getsockname()[1],
                             http_port=servers.tcp.getsockname()[1])
        assert verdict == "reachable" and servers.questions == 2
        assert time.monotonic() - started < join.PROBE_TIMEOUT
        assert servers.requests[0].startswith(b"GET / HTTP/1.1\r\n")
        assert b"Host: connectivity-check.ubuntu.com\r\n" in servers.requests[0]
        assert b"Connection: close\r\n" in servers.requests[0]
    finally:
        servers.close()


def test_the_probe_says_sign_in_page_or_not_reachable():
    join = load_job()
    servers = Servers(drop=0, status=b"HTTP/1.1 200 OK")
    try:
        assert join.probe(None, ["127.0.0.1"], dns_port=servers.udp.getsockname()[1],
                          http_port=servers.tcp.getsockname()[1]) == "sign_in_page"
    finally:
        servers.close()
    servers = Servers(drop=2)
    try:
        assert join.probe(None, ["127.0.0.1"], dns_port=servers.udp.getsockname()[1],
                          http_port=servers.tcp.getsockname()[1]) == "not_reachable"
        assert servers.questions == 2
    finally:
        servers.close()
    assert join.probe(None, []) == "not_reachable" and join.probe(None, ["not an address"]) == "not_reachable"
