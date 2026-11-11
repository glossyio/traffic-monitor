"""The network root job, run as a script against the fake nmcli (fixtures/fake_nmcli.py).

fixtures/run_job.py runs it with a non-root euid, so the stand-ins (NMCLI, TM_SYS_NET, the test's manifest, secrets
directory, and lock) are used even when the suite runs as root. The `world` fixture builds a unit: a manifest naming
the test's own user, a 0700 jobs directory, a 0750 secrets directory holding the hotspot password file, a fake
/sys/class/net with a built-in radio, a run directory, a fake iw (fixtures/fake_iw.py) that hears the recorded scan
in fixtures/iw_scan.txt, the fake busctl (fixtures/fake_busctl.py) with no checkpoint, and the fake nmcli's hotspot
profile, up. All names and passwords are placeholders.
"""

import fcntl
import importlib.machinery
import importlib.util
import json
import os
import pwd
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

from tm_control.modules.network.router import NAME_MAX_BYTES, NAME_PATTERN, PASSWORD_PATTERN

JOB = Path(__file__).resolve().parents[2] / "jobs" / "tm-job-network"
RUNNER = Path(__file__).resolve().parent / "fixtures" / "run_job.py"
NMCLI = Path(__file__).resolve().parent / "fixtures" / "fake_nmcli.py"
IW = Path(__file__).resolve().parent / "fixtures" / "fake_iw.py"
BUSCTL = Path(__file__).resolve().parent / "fixtures" / "fake_busctl.py"
IW_SCAN = Path(__file__).resolve().parent / "fixtures" / "iw_scan.txt"
FIXTURE_MANIFEST = Path(__file__).resolve().parent / "fixtures" / "manifest.json"
UUID_A = "11111111-1111-4111-8111-111111111111"
OLD_PASSWORD = "placeholder-pass-1"
NEW_PASSWORD = "placeholder-pass-2"
HOTSPOT = {
    "802-11-wireless.mode": "ap",
    "802-11-wireless.ssid": "TM-AB12",
    "802-11-wireless.hidden": "no",
    "802-11-wireless-security.key-mgmt": "wpa-psk",
    "802-11-wireless-security.psk": OLD_PASSWORD,
    "connection.autoconnect": "yes",
}
WPA2 = {
    "802-11-wireless-security.key-mgmt": "wpa-psk",
    "802-11-wireless-security.proto": "rsn",
    "802-11-wireless-security.pairwise": "ccmp",
    "802-11-wireless-security.group": "ccmp",
}


class World:
    def __init__(self, tmp_path):
        self.tmp = tmp_path
        self.jobs = tmp_path / "jobs"
        self.jobs.mkdir()
        self.jobs.chmod(0o700)
        self.secrets = tmp_path / "secrets"
        self.secrets.mkdir()
        self.secrets.chmod(0o750)
        (self.secrets / "hotspot_password").write_text(OLD_PASSWORD)
        (self.secrets / "hotspot_password").chmod(0o640)
        self.manifest = tmp_path / "manifest.json"
        me = pwd.getpwuid(os.getuid()).pw_name
        self.manifest.write_text(json.dumps({**json.loads(FIXTURE_MANIFEST.read_text()), "codeowner": me}))
        self.run_dir = tmp_path / "run"
        self.lock = self.run_dir / "network.lock"
        self.nmcli = NMCLI
        self.lock_wait = "10"
        self.return_wait = "0.2"
        self.scan_retry_wait = "0.1"
        self.scan_timeout = None
        self.iw = {"scan_text": IW_SCAN.read_text(), "fail": [], "fail_once": [], "hang": []}
        self.state = {"profiles": {"tm-hotspot": dict(HOTSPOT)}, "active": ["tm-hotspot"], "radio": "enabled",
                      "fail": []}
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

    def fail(self, verb):
        self.state["fail"].append(verb)

    def saved(self, name, **props):
        """A saved Wi-Fi network (infrastructure, autoconnect on, priority 0); returns its uuid. The keywords are
        autoconnect, priority, mode, and type (connection.type)."""
        names = {"autoconnect": "connection.autoconnect", "priority": "connection.autoconnect-priority",
                 "mode": "802-11-wireless.mode", "type": "connection.type"}
        value = str(uuid.uuid5(uuid.NAMESPACE_DNS, name))
        self.state["profiles"][name] = {"802-11-wireless.ssid": name, "connection.uuid": value,
                                        **{names[key]: str(item) for key, item in props.items()}}
        return value

    def write_request(self, body):
        path = self.jobs / "network.json"
        path.write_text(body if isinstance(body, str) else json.dumps(body))
        path.chmod(0o600)
        return path

    def run(self, body=None, request=None):
        if request is None:
            request = self.write_request(body)
        (self.tmp / "nmcli.json").write_text(json.dumps(self.state))
        (self.tmp / "nmcli.log").unlink(missing_ok=True)
        (self.tmp / "iw.json").write_text(json.dumps(self.iw))
        (self.tmp / "iw.log").unlink(missing_ok=True)
        (self.tmp / "busctl.json").write_text(json.dumps(self.busctl))
        (self.tmp / "busctl.log").unlink(missing_ok=True)
        env = {
            "PATH": os.environ["PATH"],
            "NMCLI": str(self.nmcli),
            "TM_CONTROL_MANIFEST": str(self.manifest),
            "TM_CONTROL_SECRETS_DIR": str(self.secrets),
            "TM_SYS_NET": str(self.sys_net),
            "TM_NETWORK_LOCK": str(self.lock),
            "TM_NETWORK_LOCK_WAIT": self.lock_wait,
            "FAKE_NMCLI_STATE": str(self.tmp / "nmcli.json"),
            "FAKE_NMCLI_LOG": str(self.tmp / "nmcli.log"),
            "IW": str(IW),
            "FAKE_IW_STATE": str(self.tmp / "iw.json"),
            "FAKE_IW_LOG": str(self.tmp / "iw.log"),
            "BUSCTL": str(BUSCTL),
            "FAKE_BUSCTL_STATE": str(self.tmp / "busctl.json"),
            "FAKE_BUSCTL_LOG": str(self.tmp / "busctl.log"),
            "TM_NETWORK_RUN_DIR": str(self.run_dir),
            "TM_NETWORK_RETURN_WAIT": self.return_wait,
            "TM_NETWORK_SCAN_RETRY_WAIT": self.scan_retry_wait,
            **({"TM_NETWORK_SCAN_TIMEOUT": self.scan_timeout} if self.scan_timeout else {}),
        }
        self.request = request
        return subprocess.run([sys.executable, "-I", str(RUNNER), str(JOB), str(request)], env=env,
                              capture_output=True, text=True, timeout=60)

    def log(self):
        path = self.tmp / "nmcli.log"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def calls(self, verb):
        return sum(1 for call in self.log() if verb in call)

    def iw_calls(self):
        path = self.tmp / "iw.log"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def scan(self):
        return json.loads((self.run_dir / "network-scan.json").read_text())

    def join_state(self, stage, **changes):
        """A join job's state file at `stage` (a new network, HomeNet, from the hotspot)."""
        self.run_dir.mkdir(exist_ok=True)
        state = {"stage": stage, "ssid": "HomeNet", "uuid": UUID_A, "saved": False, "before": "tm-hotspot",
                 "joined": None, "reason": None, "address": None, "internet": None, "switch_monotonic": None,
                 "finished_at": None, **changes}
        (self.run_dir / "network-join.json").write_text(json.dumps(state))

    def control(self):
        path = self.run_dir / "network-join.control"
        return path.read_text() if path.exists() else None

    def busctl_calls(self):
        path = self.tmp / "busctl.log"
        lines = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
        return [call[6] for call in lines if call[2] == "call"]

    def modifies(self):
        return [call for call in self.log() if "modify" in call]

    def nm(self):
        return json.loads((self.tmp / "nmcli.json").read_text())

    def profile(self):
        return self.nm()["profiles"]["tm-hotspot"]

    def password_file(self):
        return (self.secrets / "hotspot_password").read_text()


@pytest.fixture
def world(tmp_path):
    return World(tmp_path)


def test_the_job_is_executable():
    assert os.access(JOB, os.X_OK)


def test_a_new_name_is_set_and_a_hotspot_that_is_up_restarts(world):
    result = world.run({"action": "hotspot", "name": "TM-ROAD"})
    assert result.returncode == 0 and "restarted the hotspot" in result.stdout, result.stdout + result.stderr
    assert world.profile()["802-11-wireless.ssid"] == "TM-ROAD"
    assert world.calls("modify") == 1 and world.calls("up") == 1
    assert world.log()[-1] == ["--wait", "30", "connection", "up", "id", "tm-hotspot"]
    assert world.calls("down") == 0  # the restart is `connection up` alone
    assert world.nm()["active"] == ["tm-hotspot"]


def test_a_change_while_the_hotspot_is_down_waits_for_its_next_start(world):
    world.state["active"] = []
    result = world.run({"action": "hotspot", "hidden": True})
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip().splitlines()[-1] == "saved; the change applies when the hotspot next starts"
    assert world.profile()["802-11-wireless.hidden"] == "yes"
    assert world.calls("up") == 0 and world.nm()["active"] == []


def test_the_password_goes_to_the_file_first_then_the_profile(world):
    """A wrapper around the fake records, at the moment of `modify`, whether the file already held the new password."""
    seen = world.tmp / "seen-at-modify.json"
    wrapper = world.tmp / "nmcli-wrapper"
    wrapper.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "if 'modify' in sys.argv:\n"
        f"    path = {str(world.secrets / 'hotspot_password')!r}\n"
        f"    with open({str(seen)!r}, 'w') as file:\n"
        f"        json.dump({{'new': open(path).read() == {NEW_PASSWORD!r}, 'mtime': os.stat(path).st_mtime_ns}}, file)\n"
        f"os.execv({sys.executable!r}, [{sys.executable!r}, {str(NMCLI)!r}, *sys.argv[1:]])\n"
    )
    wrapper.chmod(0o755)
    world.nmcli = wrapper
    before = (world.secrets / "hotspot_password").stat().st_mtime_ns
    result = world.run({"action": "hotspot", "password": NEW_PASSWORD})
    assert result.returncode == 0, result.stdout + result.stderr
    at_modify = json.loads(seen.read_text())
    assert at_modify["new"] is True and at_modify["mtime"] != before
    assert world.password_file() == NEW_PASSWORD
    assert (world.secrets / "hotspot_password").stat().st_mode & 0o777 == 0o640
    assert world.profile()["802-11-wireless-security.psk"] == NEW_PASSWORD
    assert "restarted the hotspot" in result.stdout
    assert NEW_PASSWORD not in result.stdout + result.stderr
    assert OLD_PASSWORD not in result.stdout + result.stderr
    assert sorted(path.name for path in world.secrets.iterdir()) == ["hotspot_password"]  # no temporary file left


def test_a_password_on_an_open_hotspot_makes_it_wpa2(world):
    open_profile = {key: value for key, value in HOTSPOT.items() if not key.startswith("802-11-wireless-security")}
    world.state["profiles"]["tm-hotspot"] = open_profile
    (world.secrets / "hotspot_password").write_text("")
    result = world.run({"action": "hotspot", "password": NEW_PASSWORD})
    assert result.returncode == 0, result.stdout + result.stderr
    assert world.calls("modify") == 1
    profile = world.profile()
    assert {key: profile[key] for key in WPA2} == WPA2
    assert profile["802-11-wireless-security.psk"] == NEW_PASSWORD
    modify = world.modifies()[0]
    for key in [*WPA2, "802-11-wireless-security.psk"]:
        assert key in modify
    assert world.password_file() == NEW_PASSWORD


def test_a_password_the_profile_already_has_on_another_security_still_makes_it_wpa2(world):
    world.state["profiles"]["tm-hotspot"]["802-11-wireless-security.key-mgmt"] = "sae"
    result = world.run({"action": "hotspot", "password": OLD_PASSWORD})
    assert result.returncode == 0, result.stdout + result.stderr
    assert world.profile()["802-11-wireless-security.key-mgmt"] == "wpa-psk"


def test_a_profile_that_will_not_change_puts_the_old_password_back(world):
    world.fail("modify")
    result = world.run({"action": "hotspot", "password": NEW_PASSWORD})
    assert result.returncode == 1 and world.password_file() == OLD_PASSWORD
    assert "placeholder-pass" not in result.stdout + result.stderr  # the fake's error quotes the argv
    assert result.stdout.strip().splitlines()[-1] == "failed: change the profile (nmcli exit status 4)"
    assert "the settings are saved" not in result.stdout
    assert world.profile()["802-11-wireless-security.psk"] == OLD_PASSWORD
    assert world.calls("up") == 0
    assert sorted(path.name for path in world.secrets.iterdir()) == ["hotspot_password"]


def test_a_restart_that_fails_says_the_settings_are_saved(world):
    world.state["up"] = {"tm-hotspot": "fail"}
    result = world.run({"action": "hotspot", "name": "TM-ROAD"})
    assert result.returncode == 1
    assert result.stdout.strip().splitlines()[-1] == (
        "failed: restart the hotspot (nmcli exit status 4); the settings are saved")
    assert "TM-ROAD" not in result.stdout + result.stderr  # nmcli's error text, which quotes the name, isn't printed
    assert world.profile()["802-11-wireless.ssid"] == "TM-ROAD"
    assert world.calls("up") == 2


def test_a_restart_that_fails_once_is_tried_again(world):
    world.state["up"] = {"tm-hotspot": "fail-once"}
    result = world.run({"action": "hotspot", "name": "TM-ROAD"})
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip().splitlines()[-1] == "restarted the hotspot"
    assert world.calls("up") == 2 and world.nm()["active"] == ["tm-hotspot"]


def test_a_restart_that_fails_twice_still_counts_when_the_hotspot_is_up(world):
    world.state["up"] = {"tm-hotspot": "fail-started"}
    result = world.run({"action": "hotspot", "name": "TM-ROAD"})
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip().splitlines()[-1] == "restarted the hotspot"
    assert world.calls("up") == 2


def test_a_hidden_only_change_restarts_a_hotspot_that_is_up(world):
    result = world.run({"action": "hotspot", "hidden": True})
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip().splitlines()[-1] == "restarted the hotspot"
    assert world.profile()["802-11-wireless.hidden"] == "yes"
    assert world.calls("modify") == 1 and world.calls("up") == 1


def test_a_password_the_profile_has_but_the_file_lacks_is_written_to_the_file(world):
    """The file is the source of truth: it gets the password, and the profile, which already has it, isn't restarted."""
    world.state["profiles"]["tm-hotspot"]["802-11-wireless-security.psk"] = NEW_PASSWORD
    result = world.run({"action": "hotspot", "password": NEW_PASSWORD})
    assert result.returncode == 0, result.stdout + result.stderr
    assert world.password_file() == NEW_PASSWORD
    assert world.calls("modify") == 1 and world.calls("up") == 0
    assert world.profile()["802-11-wireless-security.psk"] == NEW_PASSWORD
    assert "placeholder-pass" not in result.stdout + result.stderr


def test_turning_it_off_stops_it_starting_and_takes_it_down(world):
    result = world.run({"action": "hotspot", "enabled": False})
    assert result.returncode == 0, result.stdout + result.stderr
    assert "turned the hotspot off" in result.stdout
    assert world.profile()["connection.autoconnect"] == "no"
    assert world.calls("down") == 1 and world.calls("up") == 0
    assert world.nm()["active"] == []


def test_turning_it_off_while_it_is_down_takes_nothing_down(world):
    world.state["active"] = []
    result = world.run({"action": "hotspot", "enabled": False, "name": "TM-ROAD"})
    assert result.returncode == 0 and "turned the hotspot off" in result.stdout
    assert world.calls("down") == 0 and world.calls("up") == 0


def test_turning_it_on_switches_the_radio_on_and_starts_it_when_idle(world):
    world.state["profiles"]["tm-hotspot"]["connection.autoconnect"] = "no"
    world.state["active"] = []
    world.state["radio"] = "disabled"
    result = world.run({"action": "hotspot", "enabled": True})
    assert result.returncode == 0, result.stdout + result.stderr
    assert "turned the hotspot on" in result.stdout
    assert world.profile()["connection.autoconnect"] == "yes"
    assert ["radio", "wifi", "on"] in world.log()
    assert world.nm()["radio"] == "enabled"
    assert world.calls("up") == 1 and world.nm()["active"] == ["tm-hotspot"]


def test_turning_it_on_counts_the_hotspot_that_networkmanager_started_itself(world):
    world.state["profiles"]["tm-hotspot"]["connection.autoconnect"] = "no"
    world.state["active"] = []
    world.state["up"] = {"tm-hotspot": "fail-started"}
    result = world.run({"action": "hotspot", "enabled": True})
    assert result.returncode == 0, result.stdout + result.stderr
    assert "turned the hotspot on" in result.stdout and "failed" not in result.stdout
    assert world.calls("up") == 1 and world.nm()["active"] == ["tm-hotspot"]


def test_turning_it_on_leaves_a_joined_network_alone(world):
    world.state["profiles"]["Home"] = {"802-11-wireless.ssid": "Home"}
    world.state["profiles"]["tm-hotspot"]["connection.autoconnect"] = "no"
    world.state["active"] = ["Home"]
    result = world.run({"action": "hotspot", "enabled": True})
    assert result.returncode == 0, result.stdout + result.stderr
    assert "turned the hotspot on" in result.stdout
    assert world.profile()["connection.autoconnect"] == "yes"
    assert world.calls("up") == 0 and world.nm()["active"] == ["Home"]


def test_turning_it_on_leaves_a_radio_that_is_joining_alone(world):
    world.state["profiles"]["tm-hotspot"]["connection.autoconnect"] = "no"
    world.state["active"] = []
    world.state["device_state"] = 50
    result = world.run({"action": "hotspot", "enabled": True})
    assert result.returncode == 0, result.stdout + result.stderr
    assert world.calls("up") == 0


def test_a_usb_adapter_never_gets_the_hotspot_started(world):
    world.radio("usb")
    world.state["profiles"]["tm-hotspot"]["connection.autoconnect"] = "no"
    world.state["active"] = []
    world.state["radio"] = "disabled"
    result = world.run({"action": "hotspot", "enabled": True})
    assert result.returncode == 0, result.stdout + result.stderr
    assert world.profile()["connection.autoconnect"] == "yes"
    assert world.calls("modify") == 1 and world.calls("up") == 0 and world.calls("radio") == 0
    assert "saved; the change applies when the hotspot next starts" in result.stdout


def test_values_already_set_change_nothing_and_restart_nothing(world):
    result = world.run({"action": "hotspot", "enabled": True, "name": "TM-AB12", "password": OLD_PASSWORD,
                        "hidden": False})
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "nothing to change"
    assert world.calls("modify") == 0 and world.calls("up") == 0 and world.calls("down") == 0
    assert world.password_file() == OLD_PASSWORD
    assert OLD_PASSWORD not in result.stdout + result.stderr


@pytest.mark.parametrize("request_", [
    {"action": "forget"}, {"action": "hotspot"}, {"action": "hotspot", "name": "x", "extra": 1},
    {"action": "hotspot", "enabled": "yes"}, {"action": "hotspot", "name": "a" * 33},
    {"action": "hotspot", "name": "TM\n1"}, {"action": "hotspot", "password": "short12"},
    {"action": "hotspot", "password": "x" * 64}, {"name": "TM-ROAD"},
    {"action": "hotspot", "hidden": None}, {"action": "hotspot", "name": "é" * 17},
    {"action": "hotspot", "name": " TM"}, {"action": "hotspot", "password": " placeholder-pass-3"}])
def test_a_request_is_refused_unless_it_is_exactly_a_hotspot_change(world, request_):
    result = world.run(request_)
    assert result.returncode == 1 and result.stdout.startswith("refused: ")
    assert len(result.stdout.strip().splitlines()) == 1
    assert world.log() == [] and not world.request.exists()
    assert world.password_file() == OLD_PASSWORD
    for value in request_.values():
        if isinstance(value, str) and value not in ("hotspot", "forget") and len(value.strip()) >= 4:
            assert value.strip() not in result.stdout + result.stderr


@pytest.mark.parametrize("body", ["not json", "[1, 2]", json.dumps({"action": "hotspot", "name": "x" * 5000})])
def test_a_request_that_is_not_a_small_json_object_is_refused(world, body):
    result = world.run(body)
    assert result.returncode == 1 and result.stdout.startswith("refused: ")
    assert world.log() == [] and not world.request.exists()


def test_the_request_must_be_tm_controls_own_plain_file(world):
    target = world.tmp / "elsewhere.json"
    target.write_text(json.dumps({"action": "hotspot", "name": "TM-ROAD"}))
    link = world.jobs / "network.json"
    link.symlink_to(target)
    result = world.run(request=link)
    assert result.returncode == 1 and result.stdout.startswith("refused: ")
    assert world.log() == [] and target.exists() and not link.is_symlink()

    request = world.write_request({"action": "hotspot", "name": "TM-ROAD"})
    second = world.tmp / "second-link.json"
    os.link(request, second)
    result = world.run(request=request)
    assert result.returncode == 1 and result.stdout.startswith("refused: ")
    assert world.log() == [] and second.exists() and not request.exists()
    assert world.profile()["802-11-wireless.ssid"] == "TM-AB12"


def test_a_jobs_directory_others_can_write_is_not_trusted(world):
    world.jobs.chmod(0o777)
    result = world.run({"action": "hotspot", "name": "TM-ROAD"})
    assert result.returncode == 1 and result.stdout.startswith("refused: ")
    assert world.log() == []


def test_a_missing_profile_is_refused(world):
    del world.state["profiles"]["tm-hotspot"]
    world.state["active"] = []
    result = world.run({"action": "hotspot", "name": "TM-ROAD"})
    assert result.returncode == 1
    assert result.stdout.strip() == "refused: there is no hotspot profile; run the installer"
    assert world.calls("modify") == 0 and not world.request.exists()


@pytest.mark.parametrize("case", ["done", "nothing", "refused", "no-profile", "modify-fails", "restart-fails"])
def test_the_request_is_deleted_whatever_happens(world, case):
    body = {"action": "hotspot", "name": "TM-ROAD"}
    if case == "nothing":
        body = {"action": "hotspot", "name": "TM-AB12"}
    elif case == "refused":
        body = {"action": "hotspot", "name": ""}
    elif case == "no-profile":
        del world.state["profiles"]["tm-hotspot"]
    elif case == "modify-fails":
        world.fail("modify")
    elif case == "restart-fails":
        world.state["up"] = {"tm-hotspot": "fail"}
    result = world.run(body)
    assert result.returncode == (0 if case in ("done", "nothing") else 1), result.stdout + result.stderr
    assert not world.request.exists()
    assert list(world.jobs.iterdir()) == []


def test_a_held_lock_refuses_after_the_wait(world):
    world.lock.parent.mkdir()
    world.lock_wait = "0.2"
    with open(world.lock, "w") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        result = world.run({"action": "hotspot", "enabled": False})
    assert result.returncode == 1
    assert result.stdout.strip() == "refused: the unit is trying a saved network right now; try again in a minute"
    assert world.log() == [] and not world.request.exists()
    assert world.profile()["connection.autoconnect"] == "yes"


def test_the_lock_is_made_when_missing_and_free_after_a_run(world):
    result = world.run({"action": "hotspot", "name": "TM-ROAD"})
    assert result.returncode == 0, result.stdout + result.stderr
    assert world.lock.parent.stat().st_mode & 0o777 == 0o755
    with open(world.lock) as file:
        fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)


def load_job():
    loader = importlib.machinery.SourceFileLoader("tm_job_network", str(JOB))
    spec = importlib.util.spec_from_loader("tm_job_network", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def test_as_root_the_unit_names_the_manifest_and_secrets_but_not_the_test_settings(monkeypatch):
    job = load_job()
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    for name in ("TM_CONTROL_MANIFEST", "TM_CONTROL_SECRETS_DIR", "NMCLI", "TM_SYS_NET", "TM_NETWORK_LOCK",
                 "TM_NETWORK_LOCK_WAIT"):
        monkeypatch.setenv(name, "/elsewhere")
    assert job.manifest_path() == "/elsewhere" and job.secrets_dir_path() == "/elsewhere"
    assert job.trusted("NMCLI", job.NMCLI) == "/usr/bin/nmcli"
    assert job.trusted("TM_SYS_NET", job.SYS_NET) == "/sys/class/net"
    assert job.trusted("TM_NETWORK_LOCK", job.LOCK) == "/run/traffic-monitor/network.lock"
    assert job.trusted("TM_NETWORK_LOCK_WAIT", str(job.LOCK_WAIT)) == "10"
    monkeypatch.delenv("TM_CONTROL_MANIFEST")
    monkeypatch.delenv("TM_CONTROL_SECRETS_DIR")
    assert job.manifest_path() == "/etc/traffic-monitor/manifest.json"
    assert job.secrets_dir_path() == "/etc/traffic-monitor/secrets"


def test_the_rules_are_the_same_as_tm_controls():
    job = load_job()
    assert job.NAME_MAX_BYTES == NAME_MAX_BYTES
    assert job.NAME_PATTERN == NAME_PATTERN
    assert job.PASSWORD_PATTERN == PASSWORD_PATTERN


def test_the_scrubber_hides_the_longer_password_first_and_escaped_forms():
    job = load_job()
    nm = job.Nmcli("nmcli")
    nm.hide("abc12345", "abc12345678", "pa:ss\\word")
    text = nm.scrub("abc12345678 then pa\\:ss\\\\word then pa:ss\\word")
    assert "abc" not in text and "678" not in text and "ss" not in text


# The scan, forget, and order actions.


def scan_block(ssid="placeholder-x", signal="-65.00 dBm", capability="ESS Privacy (0x1031)", suites=None,
               section="RSN"):
    """One BSS block in iw's layout. `suites` is the text after `Authentication suites:`; None leaves the section out.
    `ssid` None leaves out the SSID line, as this iw does for a hidden network."""
    lines = ["BSS 02:00:00:00:00:99(on wlan0)", "\tfreq: 2412.0", f"\tcapability: {capability}", f"\tsignal: {signal}"]
    if ssid is not None:
        lines.append(f"\tSSID: {ssid}")
    if suites is not None:
        lines += [f"\t{section}:\t * Version: 1", "\t\t * Group cipher: CCMP",
                  f"\t\t * Authentication suites: {suites}", "\t\t * Capabilities: 1-PTKSA-RC (0x0000)"]
    return "\n".join(lines) + "\n"


def test_a_scan_writes_what_it_heard_strongest_first(world):
    result = world.run({"action": "scan"})
    # the fixture's hidden network is left out
    assert result.returncode == 0 and "heard 4 networks" in result.stdout, result.stdout + result.stderr
    scan = world.scan()
    assert [n["security"] for n in scan["networks"]] == ["password", "password", "enterprise", "open"]
    assert [n["signal"] for n in scan["networks"]] == [96, 68, 60, 40]
    assert scan["networks"][0] == {"ssid": "placeholder-1", "signal": 96, "security": "password"}  # -52 dBm
    assert isinstance(scan["monotonic"], float) and scan["at"].endswith("+00:00")
    assert world.iw_calls() == [["dev", "wlan0", "scan"]]
    assert (world.run_dir / "network-scan.json").stat().st_mode & 0o777 == 0o644
    assert sorted(path.name for path in world.run_dir.iterdir()) == ["network-scan.json", "network.lock"]
    assert "placeholder" not in result.stdout + result.stderr  # a heard name is data, never printed


def test_a_scan_reads_names_with_escapes_whole():
    # iw writes a byte it can't print as \xNN (a backslash as \x5c); a colon and a space at the end are the name's
    text = scan_block(ssid="Caf\\xc3\\xa9: 2\\x5c ", suites="PSK")
    assert load_job().parse_scan(text) == [{"ssid": "Caf\u00e9: 2\\ ", "signal": 70, "security": "password"}]


def test_a_name_that_is_empty_or_only_nul_bytes_or_missing_is_left_out():
    job = load_job()
    text = (scan_block(ssid="") + scan_block(ssid="\\x00\\x00\\x00") + scan_block(ssid=None, suites="PSK")
            + scan_block(ssid="placeholder-1"))
    assert [n["ssid"] for n in job.parse_scan(text)] == ["placeholder-1"]
    assert job.parse_scan("") == [] and job.parse_scan("not a scan\n") == []


def test_a_mixed_wpa2_wpa3_network_counts_as_a_password_network():
    assert load_job().parse_scan(scan_block(suites="PSK SAE"))[0]["security"] == "password"
    assert load_job().parse_scan(scan_block(suites="FT/PSK", section="WPA"))[0]["security"] == "password"


def test_a_wpa3_only_network_is_wpa3_and_wep_is_other():
    job = load_job()
    assert job.parse_scan(scan_block(suites="SAE"))[0]["security"] == "wpa3"
    assert job.parse_scan(scan_block(suites="IEEE 802.1X"))[0]["security"] == "enterprise"
    assert job.parse_scan(scan_block(suites="OWE"))[0]["security"] == "other"
    wep = scan_block(capability="ESS Privacy (0x0011)")  # Privacy and no suites
    assert job.parse_scan(wep)[0]["security"] == "other"
    assert job.parse_scan(scan_block(capability="ESS (0x0001)"))[0]["security"] == "open"


def test_a_suite_outside_rsn_and_wpa_is_not_a_security_suite():
    text = scan_block(capability="ESS (0x0001)") + "\tWPS:\t * Version: 1.0\n\t\t * Authentication suites: PSK\n"
    # a suite under WPS is no suite, and nothing says Privacy
    assert load_job().parse_scan(text)[0]["security"] == "open"


def test_the_signal_becomes_a_number_from_0_to_100():
    job = load_job()
    for dbm, number in (("-52.00 dBm", 96), ("-30.00 dBm", 100), ("-10.00 dBm", 100), ("-100.00 dBm", 0),
                        ("-120.00 dBm", 0), ("-67.50 dBm", 64)):
        assert job.parse_scan(scan_block(signal=dbm))[0]["signal"] == number
    assert job.parse_scan(scan_block(signal="unknown"))[0]["signal"] == 0


def test_one_name_on_several_access_points_counts_once_with_its_best_signal():
    job = load_job()
    text = (scan_block(ssid="placeholder-1", signal="-80.00 dBm", suites="SAE")
            + scan_block(ssid="placeholder-1", signal="-60.00 dBm", suites="SAE")
            + scan_block(ssid="placeholder-1", signal="-70.00 dBm", suites="PSK"))
    assert job.parse_scan(text) == [{"ssid": "placeholder-1", "signal": 80, "security": "password"}]
    text = (scan_block(ssid="placeholder-1", signal="-80.00 dBm", suites="SAE")
            + scan_block(ssid="placeholder-1", signal="-60.00 dBm", suites="SAE"))
    assert job.parse_scan(text) == [{"ssid": "placeholder-1", "signal": 80, "security": "wpa3"}]


def test_a_scan_keeps_at_most_100_networks(world):
    world.iw["scan_text"] = "".join(
        scan_block(ssid=f"placeholder-{i}", signal=f"-{40 + i % 50}.00 dBm") for i in range(130))
    result = world.run({"action": "scan"})
    assert result.returncode == 0 and "heard 100 networks" in result.stdout, result.stdout + result.stderr
    signals = [n["signal"] for n in world.scan()["networks"]]
    assert len(signals) == 100 and signals == sorted(signals, reverse=True)


def test_a_scan_with_one_network_says_so(world):
    world.iw["scan_text"] = scan_block(ssid="placeholder-1")
    result = world.run({"action": "scan"})
    assert result.stdout.strip() == "heard 1 network"


def test_a_scan_that_fails_once_is_tried_again(world):
    world.iw["fail_once"] = ["scan"]
    result = world.run({"action": "scan"})
    assert result.returncode == 0 and "heard 4 networks" in result.stdout, result.stdout + result.stderr
    assert world.iw_calls() == [["dev", "wlan0", "scan"]] * 2


def test_a_scan_that_fails_or_hangs_leaves_the_old_result(world):
    world.run_dir.mkdir()
    old = world.run_dir / "network-scan.json"
    old.write_text('{"networks": []}')
    world.iw["fail"] = ["scan"]
    result = world.run({"action": "scan"})
    assert result.returncode == 1 and result.stdout.strip() == "failed: scan (iw exit status 240)"
    assert len(world.iw_calls()) == 2  # tried once more
    assert old.read_text() == '{"networks": []}'
    assert sorted(path.name for path in world.run_dir.iterdir()) == ["network-scan.json", "network.lock"]

    world.iw = {**world.iw, "fail": [], "hang": ["scan"]}
    world.scan_timeout = "0.5"
    result = world.run({"action": "scan"})
    assert result.returncode == 1 and result.stdout.strip() == "failed: scan (iw timed out)"
    assert len(world.iw_calls()) == 1  # a hang is not tried again
    assert old.read_text() == '{"networks": []}'


def test_the_retry_shares_the_time_limit_of_the_first_try(world):
    world.iw["fail"] = ["scan"]
    world.scan_timeout = "0.05"  # shorter than the wait before the second try
    result = world.run({"action": "scan"})
    assert result.returncode == 1 and result.stdout.strip() == "failed: scan (iw exit status 240)"
    assert len(world.iw_calls()) == 1


def test_no_scan_on_a_radio_that_is_off_or_a_usb_adapter(world):
    world.state["radio"] = "disabled"
    result = world.run({"action": "scan"})
    assert result.returncode == 1 and result.stdout.strip() == "refused: the Wi-Fi radio is switched off"
    assert world.iw_calls() == [] and not (world.run_dir / "network-scan.json").exists()

    world.state["radio"] = "enabled"
    world.radio("usb")
    result = world.run({"action": "scan"})
    assert result.returncode == 1 and result.stdout.strip() == "refused: the unit has no built-in Wi-Fi radio"
    assert world.iw_calls() == [] and world.log() == []


def test_forgetting_a_saved_network_deletes_its_profile(world):
    home = world.saved("Home")
    result = world.run({"action": "forget", "uuid": home})
    assert result.returncode == 0 and result.stdout.strip() == "forgot the network", result.stdout + result.stderr
    assert world.calls("delete") == 1 and ["connection", "delete", "uuid", home] in world.log()
    assert list(world.nm()["profiles"]) == ["tm-hotspot"] and world.nm()["active"] == ["tm-hotspot"]
    assert world.calls("up") == 0 and world.calls("down") == 0 and world.calls("modify") == 0
    assert "Home" not in result.stdout + result.stderr


def test_forgetting_the_network_in_use_starts_the_hotspot(world):
    home = world.saved("Home")
    world.state["active"] = ["Home"]
    result = world.run({"action": "forget", "uuid": home})
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip().splitlines() == ["forgot the network", "started the hotspot"]
    assert world.calls("delete") == 1 and world.calls("up") == 1
    assert ["--wait", "30", "connection", "up", "id", "tm-hotspot"] in world.log()
    assert world.nm()["active"] == ["tm-hotspot"]


def test_forgetting_the_network_in_use_with_the_hotspot_off_leaves_the_radio_idle(world):
    home = world.saved("Home")
    world.state["active"] = ["Home"]
    world.state["profiles"]["tm-hotspot"]["connection.autoconnect"] = "no"
    result = world.run({"action": "forget", "uuid": home})
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip().splitlines() == ["forgot the network", "the hotspot is off, so the Wi-Fi is idle"]
    assert world.calls("up") == 0 and world.nm()["active"] == []


def test_forgetting_another_network_while_on_a_network_leaves_the_device_alone(world):
    home, work = world.saved("Home"), world.saved("Work")
    world.state["active"] = ["Home"]
    result = world.run({"action": "forget", "uuid": work})
    assert result.returncode == 0 and result.stdout.strip() == "forgot the network"
    assert world.calls("up") == 0 and world.nm()["active"] == ["Home"] and home


def test_a_failed_start_of_the_hotspot_after_forgetting_says_the_network_is_gone(world):
    home = world.saved("Home")
    world.state["active"] = ["Home"]
    world.state["up"] = {"tm-hotspot": "fail"}
    result = world.run({"action": "forget", "uuid": home})
    assert result.returncode == 1
    assert result.stdout.strip().splitlines()[-1] == (
        "failed: start the hotspot (nmcli exit status 4); the network is forgotten")
    assert "Home" not in world.nm()["profiles"]


@pytest.mark.parametrize("target", ["tm-hotspot", "Wired connection 1"])
def test_only_a_wifi_client_profile_can_be_forgotten(world, target):
    if target != "tm-hotspot":
        world.state["profiles"][target] = {"connection.type": "802-3-ethernet"}
    value = str(uuid.uuid5(uuid.NAMESPACE_DNS, target))
    result = world.run({"action": "forget", "uuid": value})
    assert result.returncode == 1
    assert result.stdout.strip() == "refused: only a saved Wi-Fi network can be forgotten"
    assert world.calls("delete") == 0 and target in world.nm()["profiles"]


def test_a_network_that_is_already_gone_is_refused(world):
    result = world.run({"action": "forget", "uuid": UUID_A})
    assert result.returncode == 1 and result.stdout.strip() == "refused: that network isn't saved any more"
    assert world.calls("delete") == 0 and UUID_A not in result.stdout


def test_an_order_numbers_the_networks_from_the_count_down_to_one(world):
    a, b, c = world.saved("A"), world.saved("B"), world.saved("C")
    world.state["profiles"]["tm-hotspot"]["connection.autoconnect-priority"] = "-100"
    result = world.run({"action": "order", "uuids": [c, a, b]})
    assert result.returncode == 0 and result.stdout.strip() == "ordered 3 networks", result.stdout + result.stderr
    profiles = world.nm()["profiles"]
    assert [profiles[name]["connection.autoconnect-priority"] for name in ("C", "A", "B")] == ["3", "2", "1"]
    assert profiles["tm-hotspot"]["connection.autoconnect-priority"] == "-100"
    assert world.calls("modify") == 3 and world.calls("up") == 0


def test_an_order_changes_only_the_profiles_that_differ(world):
    a, b, c = world.saved("A", priority=3), world.saved("B", priority=2), world.saved("C", priority=7)
    result = world.run({"action": "order", "uuids": [a, c, b]})  # A stays 3; C 2; B 1
    assert result.returncode == 0 and result.stdout.strip() == "ordered 3 networks"
    assert len(world.modifies()) == 2
    profiles = world.nm()["profiles"]
    assert [profiles[name]["connection.autoconnect-priority"] for name in ("A", "C", "B")] == ["3", "2", "1"]
    world.state = world.nm()  # the next run starts from where this one ended
    result = world.run({"action": "order", "uuids": [a, c, b]})
    assert result.stdout.strip() == "nothing to change" and world.modifies() == []


def test_an_order_leaves_out_the_networks_that_do_not_start_by_themselves(world):
    a, b = world.saved("A"), world.saved("B", autoconnect="no")
    result = world.run({"action": "order", "uuids": [a]})
    assert result.returncode == 0 and result.stdout.strip() == "ordered 1 network"
    assert world.nm()["profiles"]["A"]["connection.autoconnect-priority"] == "1"
    result = world.run({"action": "order", "uuids": [a, b]})
    assert result.returncode == 1 and result.stdout.strip() == "refused: the saved networks changed; reload the page"


def test_an_order_that_misses_a_saved_network_is_refused(world):
    a, b = world.saved("A"), world.saved("B")
    for uuids in ([a], [a, b, UUID_A], [a, UUID_A]):
        result = world.run({"action": "order", "uuids": uuids})
        assert result.returncode == 1
        assert result.stdout.strip() == "refused: the saved networks changed; reload the page"
        assert world.modifies() == []


@pytest.mark.parametrize("request_", [
    {"action": "scan", "extra": 1}, {"action": "forget"}, {"action": "forget", "uuid": "tm-hotspot"},
    {"action": "forget", "uuid": UUID_A, "name": "x"},
    {"action": "forget", "uuid": "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA"},
    {"action": "forget", "uuid": 5}, {"action": "order", "uuids": []},
    {"action": "order", "uuids": [UUID_A, UUID_A]}, {"action": "order", "uuids": "all"},
    {"action": "order", "uuids": [UUID_A, 5]}, {"action": "order", "uuids": [UUID_A], "extra": 1},
    {"action": "order", "uuids": [str(uuid.UUID(int=i, version=4)) for i in range(65)]},
    {"action": "join"}, {"action": ["scan"]}, {"action": "cancel", "uuid": UUID_A},
    {"action": "switch-now", "now": True}])
def test_a_request_outside_its_actions_form_is_refused(world, request_):
    world.join_state("countdown")
    result = world.run(request_)
    assert result.returncode == 1 and result.stdout.startswith("refused: ")
    assert len(result.stdout.strip().splitlines()) == 1
    assert world.log() == [] and world.iw_calls() == [] and not world.request.exists()
    assert world.control() is None and (world.run_dir / "network-join.json").exists()
    for value in request_.values():
        if isinstance(value, str) and value not in ("scan", "forget", "order", "join", "cancel",
                                                    "switch-now") and len(value) >= 4:
            assert value not in result.stdout + result.stderr


@pytest.mark.parametrize("request_", [{"action": "scan"}, {"action": "forget", "uuid": UUID_A},
                                      {"action": "order", "uuids": [UUID_A]}])
def test_each_new_action_waits_for_the_lock(world, request_):
    world.lock.parent.mkdir()
    world.lock_wait = "0.2"
    with open(world.lock, "w") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        result = world.run(request_)
    assert result.returncode == 1
    assert result.stdout.strip() == "refused: the unit is trying a saved network right now; try again in a minute"
    assert world.log() == [] and world.iw_calls() == [] and not world.request.exists()


# Switch now and Cancel, for the join job (tm-job-network-join).

def test_switch_now_writes_the_control_file_during_a_countdown(world):
    world.join_state("countdown", joined=True, switch_monotonic=1000.0)
    result = world.run({"action": "switch-now"})
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "asked the join to switch now"
    assert world.control() == "switch"
    assert (world.run_dir / "network-join.control").stat().st_mode & 0o777 == 0o644
    assert world.log() == [] and not world.request.exists()


@pytest.mark.parametrize("stage", [None, "testing", "joined", "cancelled", "switching"])
def test_switch_now_without_a_countdown_is_refused(world, stage):
    if stage:
        world.join_state(stage)
    result = world.run({"action": "switch-now"})
    assert result.returncode == 1 and result.stdout.strip() == "refused: there is no countdown to end"
    assert world.control() is None


@pytest.mark.parametrize("stage", ["testing", "countdown", "switching"])
def test_cancel_during_a_join_writes_the_control_file(world, stage):
    world.join_state(stage)
    with open(world.lock, "w") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        result = world.run({"action": "cancel"})
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "asked the join to cancel"
    assert world.control() == "cancel" and (world.run_dir / "network-join.json").exists()
    assert world.log() == [] and world.busctl_calls() == []


@pytest.mark.parametrize("held", [False, True])
def test_cancel_on_a_finished_join_clears_the_result(world, held):
    world.saved("HomeNet")
    world.join_state("failed", uuid=world.state["profiles"]["HomeNet"]["connection.uuid"], reason="not_joined")
    (world.run_dir / "network-join.control").write_text("cancel")
    lock = open(world.lock, "w")
    if held:
        fcntl.flock(lock, fcntl.LOCK_EX)
    try:
        result = world.run({"action": "cancel"})
    finally:
        lock.close()
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "cleared the result"
    assert not (world.run_dir / "network-join.json").exists() and world.control() is None
    assert world.calls("delete") == 0 and "HomeNet" in world.nm()["profiles"]


def test_cancel_after_a_join_that_died_deletes_what_it_left(world):
    dead = world.saved("HomeNet", autoconnect="no")
    world.join_state("testing", uuid=dead)
    (world.run_dir / "network-join.control").write_text("switch")
    result = world.run({"action": "cancel"})
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "cleared the result"
    assert ["connection", "delete", "uuid", dead] in world.log() and "HomeNet" not in world.nm()["profiles"]
    assert not (world.run_dir / "network-join.json").exists() and world.control() is None
    with open(world.lock) as file:
        fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)


def test_cancel_after_a_join_that_died_keeps_a_saved_network(world):
    home = world.saved("HomeNet")
    world.join_state("switching", uuid=home, saved=True)
    result = world.run({"action": "cancel"})
    assert result.returncode == 0 and result.stdout.strip() == "cleared the result"
    assert world.calls("delete") == 0 and "HomeNet" in world.nm()["profiles"]


def test_cancel_after_a_join_that_died_mid_test_rolls_back_its_checkpoint_first(world):
    dead = world.saved("HomeNet", autoconnect="no")
    world.state["active"] = ["HomeNet"]  # the radio is still on the network under test
    world.busctl = {"checkpoints": {"/org/freedesktop/NetworkManager/Checkpoint/4": {"active": ["tm-hotspot"]}},
                    "next": 5, "fail": []}
    world.join_state("testing", uuid=dead)
    result = world.run({"action": "cancel"})
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip().splitlines() == ["rolled back what the join left", "cleared the result"]
    assert world.busctl_calls() == ["CheckpointRollback"]
    assert world.nm()["active"] == ["tm-hotspot"] and "HomeNet" not in world.nm()["profiles"]
    assert not (world.run_dir / "network-join.json").exists()


def test_a_failed_rollback_on_cancel_is_printed_and_the_clean_up_goes_on(world):
    dead = world.saved("HomeNet", autoconnect="no")
    world.busctl = {"checkpoints": {"/org/freedesktop/NetworkManager/Checkpoint/4": {"active": ["tm-hotspot"]}},
                    "next": 5, "fail": ["CheckpointRollback"]}
    world.join_state("testing", uuid=dead)
    result = world.run({"action": "cancel"})
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip().splitlines() == ["the rollback failed (busctl exit status 1)", "cleared the result"]
    assert "HomeNet" not in world.nm()["profiles"] and not (world.run_dir / "network-join.json").exists()


def test_cancel_with_nothing_to_cancel_is_refused(world):
    result = world.run({"action": "cancel"})
    assert result.returncode == 1 and result.stdout.strip() == "refused: there is nothing to cancel"
    assert world.log() == []


@pytest.mark.parametrize("action", ["switch-now", "cancel"])
def test_neither_control_waits_for_the_lock(world, action):
    world.join_state("countdown")
    world.lock_wait = "10"
    started = time.monotonic()
    with open(world.lock, "w") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        result = world.run({"action": action})
    assert time.monotonic() - started < 1
    assert result.returncode == 0, result.stdout + result.stderr
    assert world.control() == ("switch" if action == "switch-now" else "cancel")
