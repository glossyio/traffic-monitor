"""Host services and the Traffic Monitor pod: running, built, and not crash-looping; and what tm-control may do."""

import json
import re
import shlex

import pytest
from devpi_checks import RESTARTING_UNITS, require_pii_free, role_vars

CORE_UNITS = [
    "go2rtc_server.service",
    "traffic-monitor.service",
    "frigate.service",
    "node-red-tm.service",
    "revproxy.service",
    "tm-control.service",
    "NetworkManager.service",
    "sysstat.service",
]


@pytest.mark.parametrize("unit", CORE_UNITS)
def test_unit_active(host, unit):
    state = host.run(f"systemctl is-active {unit}").stdout.strip()
    assert state == "active", f"{unit} is {state}"


def test_image_builds_succeeded(host):
    listing = host.check_output("systemctl list-units --all --plain --no-legend '*-build.service'")
    units = [line.split()[0] for line in listing.splitlines() if line.strip()]
    assert units, "no *-build.service units found"
    results = {unit: host.check_output(f"systemctl show -p Result --value {unit}") for unit in units}
    failed = {unit: result for unit, result in results.items() if result != "success"}
    assert not failed, f"image builds that didn't succeed: {failed}"


@pytest.mark.parametrize("unit", RESTARTING_UNITS)
def test_no_crash_restarts(host, unit):
    restarts = int(host.check_output(f"systemctl show -p NRestarts --value {unit}"))
    assert restarts == 0, f"{unit} restarted itself {restarts} times since it was last started"


def test_plate_recognizer_absent_on_pii_free_unit(host, expect):
    require_pii_free(expect)
    assert not host.file("/etc/containers/systemd/plate-recognizer.container").exists, (
        "plate-recognizer is installed on a unit marked pii_free; its database may hold plate reads")


def test_ui_build_unit_finished(host):
    """The revproxy image, which builds tm-control's UI, was built by its Quadlet build unit, which then stays
    active (exited)."""
    output = host.check_output("systemctl show -p ActiveState -p SubState revproxy-build.service")
    state = dict(line.split("=", 1) for line in output.splitlines() if "=" in line)
    found = (state.get("ActiveState"), state.get("SubState"))
    assert found == ("active", "exited"), f"revproxy-build.service is {found}"


# tm-control runs as the code owner, and polkit lets that user start, stop, and restart only the units in
# tmsetup_tm_control_polkit (vars/main.yml; templates/tm-control/50-traffic-monitor.rules.j2). The checks below try
# two things off that list. Each is harmless if polkit wrongly allows it:
# - starting sysstat-collect.service records one sysstat sample, as its timer does every 10 minutes;
# - systemd-run starts a transient unit, as root, that runs /bin/true and does nothing.
OFF_THE_LIST_UNIT = "sysstat-collect.service"
OFF_THE_LIST = {
    "start-a-unit-off-the-list": f"systemctl --no-ask-password start {OFF_THE_LIST_UNIT}",
    "start-a-transient-unit": "systemd-run --no-ask-password --quiet /bin/true",
}
# systemd's refusal: polkit said no, or it wanted a password that --no-ask-password doesn't ask for
REFUSED = re.compile(r"access denied|interactive authentication required", re.IGNORECASE)


@pytest.mark.parametrize("command", OFF_THE_LIST.values(), ids=OFF_THE_LIST.keys())
def test_polkit_keeps_tm_control_to_its_units(host, codeowner, command):
    if codeowner == "root":
        pytest.skip("the code owner is root, which polkit doesn't limit")
    assert OFF_THE_LIST_UNIT not in role_vars()["tmsetup_tm_control_polkit"]["units"]
    # Otherwise systemctl would fail for the missing unit, and the refusal wouldn't show polkit's rule
    load_state = host.check_output(f"systemctl show -p LoadState --value {OFF_THE_LIST_UNIT}")
    assert load_state == "loaded", f"{OFF_THE_LIST_UNIT} is {load_state}; pick another unit off the list"
    result = host.run(f"sudo -n -u {shlex.quote(codeowner)} {command}")
    refused = result.rc != 0 and REFUSED.search(result.stderr) is not None
    assert refused, f"as {codeowner}, `{command}` exited {result.rc}: {result.stderr.strip()[:200]}"


def test_pid1_logs_how_each_start_job_ended(host):
    """tm-control learns how a root job ended from PID 1's journal entry for the end of the job unit's start job,
    which carries INVOCATION_ID, JOB_TYPE, and JOB_RESULT (tm_control/core/jobs.py); a finished job unit is unloaded,
    so systemctl no longer shows it. Read-only: this reads the entry for tm-control.service's own current run, rather
    than starting the job unit, which would change a password."""
    invocation = host.check_output("systemctl show -p InvocationID --value tm-control.service")
    assert invocation, "tm-control.service has no invocation ID; is it running?"
    with host.sudo():
        output = host.check_output(
            "journalctl -b -u tm-control.service -o json --output-fields=INVOCATION_ID,JOB_TYPE,JOB_RESULT,_PID "
            "--no-pager | grep -F JOB_RESULT | tail -n 50")
    entries = [json.loads(line) for line in output.splitlines() if line.strip()]
    ended = [(entry.get("_PID"), entry.get("JOB_TYPE"), entry.get("JOB_RESULT"))
             for entry in entries if entry.get("INVOCATION_ID") == invocation]
    assert ended == [("1", "start", "done")], (
        f"PID 1's job-end entries for tm-control.service's current run (pid, type, result): {ended}; "
        f"{len(entries)} job-end entries this boot")
