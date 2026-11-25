"""tm-update's switch: what is stopped, in what order, what a failure starts again, and a restart the update needs."""

import json
import subprocess
from pathlib import Path

import pytest
from tm_update_support import BOOT, COMMIT, RUN, Device, handover, make_world

from tm_update import installed as installed_module, switch
from tm_update.switch import STARTED_AFTER_A_FAILURE, STOPPED_FIRST, wants_reboot

STOP = ["systemctl", "stop", *STOPPED_FIRST]
STARTS = [["systemctl", "start", unit] for unit in STARTED_AFTER_A_FAILURE]


@pytest.fixture
def device(tmp_path, monkeypatch):
    return Device(tmp_path, monkeypatch)


def test_the_units_are_the_ones_the_plan_names():
    assert STOPPED_FIRST == ("traffic-monitor.service", "tm-control.service")
    assert STARTED_AFTER_A_FAILURE == ("tm-control.service", "traffic-monitor.service", "revproxy.service")


def test_the_marker_is_written_before_anything_is_stopped(device):
    seen = {}
    answer = device.run.answer

    def look(call):
        if call["argv"][:2] == ["systemctl", "stop"]:
            seen["marker"] = json.loads(device.paths.resume.read_text())
            seen["attempts"] = device.state()["switch_attempts"]
        return answer(call)

    device.run.answer = look
    assert device.main() == 0
    assert seen["marker"] == {"contract": 1, "tree": str(device.tree), "handover": str(device.handover_path)}
    assert seen["attempts"] == 1


def test_the_pod_and_the_control_app_are_stopped_before_the_installer_runs(device):
    assert device.main() == 0
    events = [event for event in device.events
              if event[0] == "systemctl" or (event[0] == "playbook" and event[1] == "setup.yml")]
    assert events.index(STOP) < events.index(("playbook", "setup.yml", ()))
    assert device.systemctl_calls("stop") == [STOP]
    assert device.systemctl_calls("start") == [] and device.systemctl_calls("reboot") == []
    # Everything before the stop is Prepare's: the switch is the first stage that touches a running unit
    assert [e for e in device.events[:device.events.index(STOP)] if e[0] == "systemctl"] == []


def test_too_little_room_for_the_database_copy_ends_before_anything_is_stopped(device, monkeypatch):
    db = device.paths.root / "opt" / "traffic-monitor" / "node-red-tm" / "db"
    (db / "tmdb.sqlite").write_bytes(b"x" * 5_000_000)
    code = device.paths.root / "opt" / "traffic-monitor"
    monkeypatch.setattr(installed_module, "_free_bytes",
                        lambda path: 1_000_000 if Path(path) == code else 10**12)
    assert device.main() == 1
    state = device.state()
    assert (state["result"], state["reason"], state["stage"]) == ("failed", "low_space", "switch")
    assert state["detail"] == "1 MB free, 6 MB needed"
    assert state["switch_attempts"] == 0
    assert not device.paths.resume.exists()
    assert device.systemctl_calls("stop") == [] and device.systemctl_calls("start") == []
    assert ("setup.yml", ()) not in device.stages


@pytest.mark.parametrize(("setup_rc", "detail"), [
    (2, "playbook exit status 2"),
    (-9, "playbook exit status -9"),
    (OSError("gone"), "unexpected OSError"),
])
def test_a_failed_installer_starts_the_three_services_and_ends_as_switch_failed(device, setup_rc, detail):
    device.setup_rc = setup_rc
    assert device.main() == 1
    assert device.systemctl_calls("start") == STARTS
    assert device.events.index(STOP) < device.events.index(STARTS[0])
    state = device.state()
    assert (state["result"], state["reason"], state["stage"], state["detail"]) == (
        "failed", "switch_failed", "switch", detail)
    assert not device.paths.resume.exists()
    assert device.systemctl_calls("reboot") == []
    assert "gone" not in device.paths.state.read_text()


def test_a_stop_that_fails_starts_the_three_services_and_never_runs_the_installer(device):
    device.systemctl[("stop",)] = 5
    assert device.main() == 1
    assert ("setup.yml", ()) not in device.stages
    assert device.systemctl_calls("start") == STARTS
    assert device.state()["reason"] == "switch_failed"
    assert not device.paths.resume.exists()


def test_each_service_is_started_even_when_starting_another_fails(device):
    device.setup_rc = 1
    device.systemctl[("start", "tm-control.service")] = OSError("no systemctl")
    device.systemctl[("start", "traffic-monitor.service")] = 1
    device.systemctl[("start", "revproxy.service")] = subprocess.TimeoutExpired(["systemctl"], 1)
    assert device.main() == 1
    assert device.systemctl_calls("start") == STARTS
    state = device.state()
    assert (state["result"], state["reason"], state["detail"]) == ("failed", "switch_failed", "playbook exit status 1")
    assert not device.paths.resume.exists()


def test_a_wanted_restart_is_recorded_before_it_is_asked_for(device):
    device.reboot_flag = "1"
    assert device.main() == 0
    assert device.systemctl_calls("reboot") == [["systemctl", "reboot"]]
    at_reboot = device.state_at_reboot
    assert (at_reboot["stage"], at_reboot["reboot"], at_reboot["boot_id"], at_reboot["result"]) == (
        "reboot", True, BOOT, None)
    assert [row["id"] for row in at_reboot["stages"]][-2:] == ["switch", "reboot"]
    assert "reboot" in device.log_at_reboot
    assert device.state() == at_reboot  # nothing changes after the request
    assert json.loads(device.paths.resume.read_text())["handover"] == str(device.handover_path)
    assert device.systemctl_calls("is-active") == [] and device.systemctl_calls("start") == []


def test_a_failed_restart_request_starts_the_three_services_and_ends_as_switch_failed(device):
    device.reboot_flag = "1"
    device.systemctl[("reboot",)] = 1
    assert device.main() == 1
    assert device.systemctl_calls("start") == STARTS
    state = device.state()
    assert (state["reason"], state["stage"], state["detail"]) == ("switch_failed", "reboot", "restart request")
    assert not device.paths.resume.exists()


@pytest.mark.parametrize("flag", [None, "0", "0\n"])
def test_a_reboot_flag_of_0_or_no_flag_goes_straight_to_health(device, flag):
    device.reboot_flag = flag
    assert device.main() == 0
    assert device.systemctl_calls("reboot") == []
    state = device.state()
    assert [row["id"] for row in state["stages"]][-2:] == ["switch", "health"]
    assert state["reboot"] is False and state["boot_id"] is None
    assert device.systemctl_calls("is-active")


def test_a_stale_reboot_flag_is_reset_before_the_installer_runs(device):
    device.work.mkdir(parents=True)
    (device.work / "reboot-required").write_text("1")
    assert device.main() == 0
    assert device.flag_before_setup == ["0"]
    assert device.systemctl_calls("reboot") == []


def test_the_installer_is_setup_yml_in_update_mode_with_the_work_folders_flag(device, monkeypatch):
    seen = []
    from tm_update import playbook
    real = playbook.write_vars

    def spy(hand, installed, tree, *, update_mode):
        seen.append(update_mode)
        return real(hand, installed, tree, update_mode=update_mode)

    monkeypatch.setattr(playbook, "write_vars", spy)
    assert device.main() == 0
    assert seen[-1] is True
    data = json.loads((device.work / "vars.json").read_text())
    assert data["tmsetup_reboot_touch_file"] == str(device.work / "reboot-required")


@pytest.mark.parametrize(("text", "wanted"), [(None, False), ("0", False), ("0\n", False), ("1", True),
                                              ("", True), ("yes", True)])
def test_wants_reboot_is_anything_but_0_in_the_flag(tmp_path, text, wanted):
    paths, _ = make_world(tmp_path)
    hand = handover(paths)
    hand.work_dir.mkdir(parents=True)
    if text is not None:
        (hand.work_dir / "reboot-required").write_text(text)
    assert wants_reboot(hand) is wanted


def test_the_role_writes_a_flag_that_wants_reboot_reads_as_a_restart():
    handler = (Path(__file__).resolve().parents[1] / "ansible" / "roles" / "tmsetup" / "handlers"
               / "reboot_handler.yml").read_text()
    assert "dest: \"{{ tmsetup_reboot_touch_file }}\"" in handler and "content: '1'" in handler


def test_the_monotonic_clock_is_the_one_systemd_stamps_in_microseconds():
    import time
    before = time.clock_gettime_ns(time.CLOCK_MONOTONIC) // 1000
    value = switch._monotonic_usec()
    assert isinstance(value, int) and before <= value <= before + 10_000_000


def test_the_switch_and_the_run_take_the_new_commit_from_the_hand_over(device):
    assert device.main() == 0
    assert json.loads(device.paths.manifest.read_text())["git"]["commit"] == COMMIT
    assert (device.paths.work_root / RUN).is_dir()
