"""The Wi-Fi retry root script, run as a script against a fake nmcli and a fake iw (fixtures/).

fixtures/run_job.py runs it with a non-root euid, so the NMCLI, IW, TM_SYS_NET and TM_NOW stand-ins are used even when
the suite runs as root. world() builds a device (a fake /sys/class/net, the fake nmcli's profiles and the fake iw's
stations and scan), runs the job once, and returns what it did. Calls to world() in one test share the job's state
file, so a test can run the timer more than once; the device is built again each time. All names here are placeholders.
"""

import fcntl
import importlib.machinery
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

JOB = Path(__file__).resolve().parents[2] / "jobs" / "tm-network-retry"
RUNNER = Path(__file__).resolve().parent / "fixtures" / "run_job.py"
NMCLI = Path(__file__).resolve().parent / "fixtures" / "fake_nmcli.py"
IW = Path(__file__).resolve().parent / "fixtures" / "fake_iw.py"
UUID = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"
THIRD = "33333333-3333-4333-8333-333333333333"
EDGE = 1e-6  # last_failure is a float: a run "exactly" at a boundary must be a hair past it, or (s + 300) - s can come out under 300
PHONE = "02:aa:bb:cc:dd:ee"
HOTSPOT = {"802-11-wireless.mode": "ap", "connection.autoconnect": "yes", "connection.autoconnect-priority": "-100"}


def load_job():
    loader = importlib.machinery.SourceFileLoader("tm_network_retry", str(JOB))
    spec = importlib.util.spec_from_loader("tm_network_retry", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def saved(uuid=UUID, **props):
    """A saved Wi-Fi network: infrastructure mode, autoconnect on, priority 0, never used."""
    return {"connection.uuid": uuid, **props}


def world(tmp_path, now=1000, profiles=None, active=("tm-hotspot",), stations=(), scan=("Home",), radio="enabled",
          join=None, device_state=None, sys_net="wifi", hotspot=HOTSPOT, state_text=None, ap_fails=False,
          iw_fail=(), join_delay=0, hold_lock=False, lock_path=None):
    """Run the job once. join="fail" makes every saved network refuse to connect, after join_delay seconds; sys_net is
    wifi, usb or none. hold_lock=True has the test hold the network lock for the whole run, as a network job would;
    lock_path names the lock when another job's test shares it."""
    profiles = {"Home": saved()} if profiles is None else dict(profiles)
    if hotspot is not None:
        profiles["tm-hotspot"] = dict(hotspot)
    sys_dir = tmp_path / "sys"
    wlan = sys_dir / "class" / "net" / "wlan0"
    if wlan.exists() or wlan.is_symlink():
        subprocess.run(["rm", "-rf", str(sys_dir)], check=True)
    if sys_net != "none":
        (wlan / "device").mkdir(parents=True)
        bus = sys_dir / "bus" / ("usb" if sys_net == "usb" else "sdio")
        bus.mkdir(parents=True)
        (wlan / "device" / "subsystem").symlink_to(bus)
        if sys_net == "wifi" or sys_net == "usb":
            (wlan / "wireless").mkdir()
    nm_state = {"profiles": profiles, "active": list(active), "radio": radio, "fail": ["up"] if ap_fails else [],
                "up": {name: "fail" for name in profiles if join == "fail" and name != "tm-hotspot"},
                "up_delay": {name: join_delay for name in profiles if name != "tm-hotspot"}}
    if device_state:
        nm_state["device_state"] = device_state
    (tmp_path / "nmcli.json").write_text(json.dumps(nm_state))
    (tmp_path / "iw.json").write_text(json.dumps({"stations": list(stations), "scan": list(scan), "fail": list(iw_fail)}))
    for log in ("nmcli.log", "iw.log"):
        (tmp_path / log).unlink(missing_ok=True)
    retry_state = tmp_path / "retry.json"
    lock_path = lock_path or tmp_path / "lock" / "network.lock"
    if state_text is not None:
        retry_state.write_text(state_text)
    env = {
        "PATH": os.environ["PATH"], "NMCLI": str(NMCLI), "IW": str(IW), "TM_SYS_NET": str(sys_dir / "class" / "net"),
        "TM_NETWORK_STATE": str(retry_state), "TM_NETWORK_LOCK": str(lock_path), "TM_NOW": str(now), "TM_HOTSPOT_WAIT": "0",
        "TM_WIFI_DEVICE": "wlan0", "TM_HOTSPOT_PROFILE": "tm-hotspot",
        "FAKE_NMCLI_STATE": str(tmp_path / "nmcli.json"), "FAKE_NMCLI_LOG": str(tmp_path / "nmcli.log"),
        "FAKE_IW_STATE": str(tmp_path / "iw.json"), "FAKE_IW_LOG": str(tmp_path / "iw.log"),
    }
    held = None
    if hold_lock:
        lock_path.parent.mkdir(exist_ok=True)
        held = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o644)
        fcntl.flock(held, fcntl.LOCK_EX)
    try:
        result = subprocess.run([sys.executable, "-I", str(RUNNER), str(JOB)], env=env, capture_output=True, text=True,
                                timeout=30)
    finally:
        if held is not None:
            os.close(held)

    def calls(name):
        path = tmp_path / name
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    return SimpleNamespace(
        code=result.returncode, stdout=result.stdout, stderr=result.stderr, outcome=result.stdout.strip(),
        log=calls("nmcli.log"), iw=calls("iw.log"),
        state=json.loads(retry_state.read_text()) if retry_state.exists() else None, state_path=retry_state,
        active=json.loads((tmp_path / "nmcli.json").read_text())["active"], lock_path=lock_path,
    )


def ups(result):
    """The profile each `connection up` asked for, as written on the command line."""
    return [call[call.index("up") + 1:][-1] for call in result.log if "up" in call]


def test_a_run_while_a_network_job_holds_the_lock_does_nothing(tmp_path):
    result = world(tmp_path, active=(), hold_lock=True)
    assert (result.code, result.outcome) == (0, "locked")
    assert result.log == [] and result.iw == []
    assert result.state is None


def test_the_lock_is_free_again_after_a_run(tmp_path):
    result = world(tmp_path, active=())
    assert (result.code, result.outcome) == (0, "hotspot-started")
    fd = os.open(result.lock_path, os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    finally:
        os.close(fd)


def test_an_idle_radio_gets_the_hotspot(tmp_path):
    result = world(tmp_path, active=())
    assert (result.code, result.outcome) == (0, "hotspot-started")
    assert result.log[-1][-5:] == ["--wait", "30", "connection", "up", "tm-hotspot"]
    assert result.active == ["tm-hotspot"]
    assert result.iw == []  # nothing is scanned when the hotspot is only being started


def test_a_hotspot_turned_off_is_left_off(tmp_path):
    result = world(tmp_path, active=(), hotspot={**HOTSPOT, "connection.autoconnect": "no"})
    assert (result.code, result.outcome) == (0, "hotspot-off")
    assert ups(result) == [] and result.active == []


def test_a_hotspot_that_will_not_start_is_an_error(tmp_path):
    result = world(tmp_path, active=(), ap_fails=True)
    assert result.code == 1 and result.stdout == ""
    assert "hotspot" in result.stderr


def test_a_radio_on_a_saved_network_is_left_alone(tmp_path):
    result = world(tmp_path, active=("Home",), stations=(PHONE,))
    assert (result.code, result.outcome) == (0, "on-network")
    assert result.iw == [] and ups(result) == []


def test_a_radio_still_joining_is_left_alone(tmp_path):
    result = world(tmp_path, active=("Home",), device_state=50)
    assert result.outcome == "busy"
    assert result.iw == [] and ups(result) == []


def test_a_radio_that_is_off_is_left_off(tmp_path):
    result = world(tmp_path, active=(), radio="disabled")
    assert (result.code, result.outcome) == (0, "radio-off")
    assert result.iw == [] and ups(result) == []


def test_a_network_that_works_again_is_forgotten_when_the_radio_is_on_it(tmp_path):
    seed = {"networks": {UUID: {"name": "Home", "failures": 2, "last_failure": 900.0}}}
    result = world(tmp_path, active=("Home",), state_text=json.dumps(seed))
    assert result.outcome == "on-network"
    assert result.state["networks"] == {}


def test_nothing_is_scanned_or_switched_while_a_phone_is_joined(tmp_path):
    result = world(tmp_path, stations=(PHONE,))
    assert (result.code, result.outcome) == (0, "phone-joined")
    assert result.iw == [["dev", "wlan0", "station", "dump"]]
    assert ups(result) == [] and result.active == ["tm-hotspot"]


def test_a_station_list_that_cannot_be_read_is_not_an_empty_one(tmp_path):
    result = world(tmp_path, iw_fail=("station",))
    assert (result.code, result.outcome) == (0, "stations-unknown")
    assert ups(result) == [] and result.active == ["tm-hotspot"]


def test_a_scan_that_fails_leaves_the_hotspot_alone(tmp_path):
    result = world(tmp_path, iw_fail=("scan",))
    assert (result.code, result.outcome.split(" (")[0]) == (0, "scan-failed")
    assert ups(result) == [] and result.active == ["tm-hotspot"]


def test_a_saved_network_in_range_is_joined_when_nobody_is_on_the_hotspot(tmp_path):
    result = world(tmp_path)
    assert (result.code, result.outcome) == (0, "joined")
    assert result.iw == [["dev", "wlan0", "station", "dump"], ["dev", "wlan0", "scan"]]
    assert result.log[-1][-5:] == ["45", "connection", "up", "uuid", UUID]
    assert result.active == ["Home"]
    assert result.state["networks"] == {}
    assert result.state["last_run"]["outcome"] == "joined"


def test_the_saved_order_decides_between_two_in_range(tmp_path):
    profiles = {
        "Old": saved(UUID, **{"connection.timestamp": "500"}),
        "New": saved(OTHER, **{"connection.timestamp": "900"}),
        "Preferred": saved(THIRD, **{"connection.autoconnect-priority": "5", "connection.timestamp": "1"}),
    }
    scan = ("Old", "New", "Preferred")
    assert ups(world(tmp_path, profiles=profiles, scan=scan)) == [THIRD]  # priority first
    assert ups(world(tmp_path, profiles=profiles, scan=("Old", "New"))) == [OTHER]  # then the newer use
    assert ups(world(tmp_path, profiles=profiles, scan=("Old",))) == [UUID]


def test_a_saved_hidden_network_is_tried_blind(tmp_path):
    profiles = {"Quiet": saved(UUID, **{"802-11-wireless.hidden": "yes"})}
    result = world(tmp_path, profiles=profiles, scan=("Somebody else",))
    assert result.outcome == "joined" and ups(result) == [UUID]


def test_a_saved_network_out_of_range_is_not_tried(tmp_path):
    result = world(tmp_path, scan=("Somebody else", ""))
    assert (result.code, result.outcome) == (0, "nothing-in-range")
    assert ups(result) == [] and result.active == ["tm-hotspot"]
    assert result.iw[-1] == ["dev", "wlan0", "scan"]


def test_a_network_is_found_by_the_name_it_broadcasts(tmp_path):
    profiles = {"Garage": saved(UUID, **{"802-11-wireless.ssid": "Garage 2.4"})}
    assert world(tmp_path, profiles=profiles, scan=("Garage",)).outcome == "nothing-in-range"
    assert world(tmp_path, profiles=profiles, scan=("Garage 2.4",)).outcome == "joined"


def test_only_wifi_client_profiles_that_connect_by_themselves_are_tried(tmp_path):
    profiles = {
        "Off": saved(UUID, **{"connection.autoconnect": "no"}),
        "Wired": saved(OTHER, **{"connection.type": "802-3-ethernet"}),
        "Other hotspot": saved(THIRD, **{"802-11-wireless.mode": "ap"}),
    }
    result = world(tmp_path, profiles=profiles, scan=("Off", "Wired", "Other hotspot"))
    assert (result.outcome, ups(result)) == ("nothing-to-try", [])
    assert [call for call in result.iw if "scan" in call] == []


def test_a_failed_join_backs_off_and_the_hotspot_returns(tmp_path):
    def stamp(result):
        return result.state["networks"][UUID]["last_failure"]  # now plus the little the fakes took

    first = world(tmp_path, now=1000, join="fail")
    assert first.outcome == "join-failed" and first.state["networks"][UUID]["failures"] == 1
    assert first.state["networks"][UUID]["name"] == "Home" and 1000 <= stamp(first) < 1030
    assert first.log[-1][-3:] == ["connection", "up", "tm-hotspot"]
    assert first.active == ["tm-hotspot"]
    quiet = world(tmp_path, now=stamp(first) + 299)
    assert quiet.outcome == "nothing-to-try" and quiet.iw == [["dev", "wlan0", "station", "dump"]]  # no scan
    assert ups(quiet) == []
    second = world(tmp_path, now=stamp(first) + 300 + EDGE, join="fail")
    assert second.outcome == "join-failed" and second.state["networks"][UUID]["failures"] == 2
    assert world(tmp_path, now=stamp(second) + 899).outcome == "nothing-to-try"
    third = world(tmp_path, now=stamp(second) + 900 + EDGE, join="fail")
    assert third.state["networks"][UUID]["failures"] == 3
    assert world(tmp_path, now=stamp(third) + 3599).outcome == "nothing-to-try"
    fourth = world(tmp_path, now=stamp(third) + 3600 + EDGE, join="fail")  # the third wait is 3600 s, and so is every later one
    assert fourth.state["networks"][UUID]["failures"] == 4
    assert world(tmp_path, now=stamp(fourth) + 3599).outcome == "nothing-to-try"
    assert world(tmp_path, now=stamp(fourth) + 3600 + EDGE).outcome == "joined"


def test_the_backoff_counts_from_when_the_join_failed_not_from_when_the_run_began(tmp_path):
    first = world(tmp_path, now=1000, join="fail", join_delay=2)  # the attempt takes the hotspot away for a while
    stamped = first.state["networks"][UUID]["last_failure"]
    assert 1002 <= stamped < 1030
    quiet = world(tmp_path, now=1000 + 300)  # the next timer run: the wait since the failure is under 300 s
    assert quiet.outcome == "nothing-to-try" and ups(quiet) == []
    assert world(tmp_path, now=stamped + 300 + EDGE, join="fail").outcome == "join-failed"  # the one after tries again


def test_a_scan_that_fails_says_why_after_the_outcome(tmp_path):
    result = world(tmp_path, iw_fail=("scan",))
    assert result.stdout == "scan-failed (iw exit 240: command failed: Device or resource busy (-16))\n"
    assert result.state["last_run"]["outcome"] == "scan-failed"


def test_a_failed_join_is_one_join_per_run(tmp_path):
    profiles = {"Home": saved(UUID, **{"connection.timestamp": "9"}), "Work": saved(OTHER)}
    result = world(tmp_path, profiles=profiles, scan=("Home", "Work"), join="fail")
    assert result.outcome == "join-failed" and ups(result) == [UUID, "tm-hotspot"]
    assert list(result.state["networks"]) == [UUID]
    # the next run, a minute later, tries the other network rather than waiting for the first one
    assert ups(world(tmp_path, now=1060, profiles=profiles, scan=("Home", "Work"))) == [OTHER]


def test_a_join_that_works_clears_the_backoff(tmp_path):
    failed = world(tmp_path, now=1000, join="fail")
    result = world(tmp_path, now=failed.state["networks"][UUID]["last_failure"] + 300 + EDGE)
    assert result.outcome == "joined" and result.state["networks"] == {}


def test_a_network_that_is_no_longer_saved_is_forgotten(tmp_path):
    world(tmp_path, now=1000, join="fail")
    result = world(tmp_path, now=1100, profiles={"Work": saved(OTHER)}, scan=())
    assert result.state["networks"] == {}


def test_a_usb_adapter_named_wlan0_never_gets_the_hotspot(tmp_path):
    result = world(tmp_path, sys_net="usb", active=())
    assert (result.code, result.outcome) == (0, "usb-radio")
    assert result.log == [] and result.iw == []


def test_a_unit_without_a_radio_does_nothing(tmp_path):
    result = world(tmp_path, sys_net="none", active=())
    assert (result.code, result.outcome) == (0, "no-radio")
    assert result.log == [] and result.iw == []


def test_a_garbled_state_file_is_started_over(tmp_path):
    for text in ("{not json", "[]", '{"networks": []}', '{"networks": {"x": {"failures": "many"}}}'):
        result = world(tmp_path, state_text=text)
        assert (result.code, result.outcome) == (0, "joined"), text
        assert result.state["networks"] == {} and result.state["last_run"]["outcome"] == "joined"


def test_a_missing_hotspot_profile_is_an_error(tmp_path):
    result = world(tmp_path, hotspot=None, active=())
    assert result.code == 1 and result.stdout == ""
    assert "no hotspot profile; run the installer" in result.stderr
    assert ups(result) == []


def test_the_last_run_is_recorded_in_a_state_file_anyone_can_read(tmp_path):
    result = world(tmp_path, now=1_800_000_000, stations=(PHONE,))
    assert result.state["last_run"] == {"at": "2027-01-15T08:00:00+00:00", "outcome": "phone-joined"}
    assert result.state_path.stat().st_mode & 0o777 == 0o644
    assert [path.name for path in tmp_path.iterdir() if path.name.startswith(".retry")] == []


def test_no_call_asks_networkmanager_for_secrets(tmp_path):
    runs = [world(tmp_path, join="fail"), world(tmp_path, now=5000), world(tmp_path, stations=(PHONE,)),
            world(tmp_path, active=("Home",)), world(tmp_path, active=())]
    for run in runs:
        for call in run.log:
            assert "-s" not in call and "--show-secrets" not in call, call
            assert not any(word.endswith("psk") for word in call), call


def test_the_wait_follows_the_failure_count():
    job = load_job()
    assert job.BACKOFF == (300, 900, 3600) and job.JOIN_WAIT == 45
    assert job.due(None, 0)
    entry = {"name": "Home", "failures": 1, "last_failure": 1000.0}
    assert not job.due(entry, 1299) and job.due(entry, 1300)
    entry["failures"] = 2
    assert not job.due(entry, 1899) and job.due(entry, 1900)
    for failures in (3, 4, 40):
        entry["failures"] = failures
        assert not job.due(entry, 4599) and job.due(entry, 4600)


def test_a_clock_that_went_backwards_does_not_freeze_a_network(tmp_path):
    job = load_job()
    assert job.due({"name": "Home", "failures": 3, "last_failure": 5000.0}, 100)


def test_a_failure_the_join_job_recorded_makes_the_retry_wait(tmp_path):
    from test_job_network_join import NEW, World as JoinWorld

    unit = tmp_path / "join"
    unit.mkdir()
    join = JoinWorld(unit)
    join.up_fails("HomeNet", after=1)  # the test joins; the switch fails
    job = join.counting(NEW)
    try:
        held = world(tmp_path, scan=("HomeNet",), lock_path=join.lock)
        assert (held.code, held.outcome) == (0, "locked") and held.log == [] and held.state is None
    finally:
        join.control("switch")
        assert join.finish(job).returncode == 0
    assert join.state()["stage"] == "switch_failed"
    home = join.uuid("HomeNet")
    recorded = join.retry_path().read_text()
    stamp = json.loads(recorded)["networks"][home]["last_failure"]
    profiles = {"HomeNet": saved(home)}
    waiting = world(tmp_path, now=stamp + 299, profiles=profiles, scan=("HomeNet",), state_text=recorded)
    assert waiting.outcome == "nothing-to-try" and ups(waiting) == []
    assert waiting.state["networks"][home]["failures"] == 1
    later = world(tmp_path, now=stamp + 300 + EDGE, profiles=profiles, scan=("HomeNet",))
    assert later.outcome == "joined" and ups(later) == [home]
