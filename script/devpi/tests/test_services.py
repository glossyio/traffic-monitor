"""Host services and the Traffic Monitor pod: running, built, and not crash-looping; and what tm-control may do."""

import json
import re
import shlex

import pytest
from devpi_checks import (API, RESTARTING_UNITS, podman_events, request_from_this_machine, require_pii_free,
                          role_vars, session, tm_login_or_none)

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


def test_build_units_run_the_throwaway_podman_command_first(host):
    listing = host.check_output("systemctl list-units --all --plain --no-legend '*-build.service'")
    units = [line.split()[0] for line in listing.splitlines() if line.strip()]
    assert units, "no *-build.service units found"
    command = role_vars()["tmsetup_podman_refresh_command"]
    shown = {unit: host.check_output(f"systemctl show -p ExecStartPre {unit}") for unit in units}
    missing = [unit for unit, line in shown.items() if f"argv[]={command} ; ignore_errors=yes" not in line]
    assert not missing, f"build units without 'ExecStartPre=-{command}': {missing}"


def test_no_image_build_did_the_boots_podman_refresh(host):
    """Only the Podman command that does a boot's state refresh can crash as in #268, so it must never be a build."""
    refreshes = podman_events(host, "refresh")
    if not refreshes:
        pytest.skip("this boot's Podman refresh is no longer in the journal")
    builds = [entry["_SYSTEMD_UNIT"] for entry in refreshes if " build " in f"{entry['_CMDLINE']} "]
    assert not builds, f"this boot's Podman refresh ran in an image build: {builds}"


@pytest.mark.parametrize("unit", RESTARTING_UNITS)
def test_no_crash_restarts(host, unit):
    restarts = int(host.check_output(f"systemctl show -p NRestarts --value {unit}"))
    assert restarts == 0, f"{unit} restarted itself {restarts} times since it was last started"


def test_plate_recognizer_absent_on_pii_free_unit(host, expect):
    require_pii_free(expect)
    assert not host.file("/etc/containers/systemd/plate-recognizer.container").exists, (
        "plate-recognizer is installed on a unit marked pii_free; its database may hold plate reads")


SET_SECRET_UNIT = "tm-job-set-secret.service"


def test_set_secret_job_unit_is_static(host):
    """The set-secret job's unit is static (never enabled, so it runs only when tm-control starts it through polkit),
    and runs the job's root-owned copy, which only root can change."""
    state = host.check_output(f"systemctl show -p UnitFileState --value {SET_SECRET_UNIT}")
    assert state == "static", f"{SET_SECRET_UNIT}'s UnitFileState is {state!r}"
    script = f"{role_vars()['tmsetup_libexec_dir']}/tm-job-set-secret"
    assert script in host.check_output(f"systemctl show -p ExecStart --value {SET_SECRET_UNIT}"), (
        f"{SET_SECRET_UNIT} doesn't run {script}")
    job = host.file(script)
    found = (job.is_file, job.user, job.group, oct(job.mode)) if job.exists else "missing"
    assert found == (True, "root", "root", "0o755"), f"{script} (regular file, owner, group, mode): {found}"


def test_ui_build_unit_finished(host):
    """The revproxy image, which builds tm-control's UI, was built by its Quadlet build unit. The unit doesn't remain
    active after it exits, so this checks its last run: it ran, exited 0, and systemd counted it a success."""
    output = host.check_output(
        "systemctl show -p Result -p ExecMainStatus -p ExecMainExitTimestamp revproxy-build.service")
    state = dict(line.split("=", 1) for line in output.splitlines() if "=" in line)
    assert state.get("ExecMainExitTimestamp"), "revproxy-build.service hasn't run since boot"
    found = (state.get("Result"), state.get("ExecMainStatus"))
    assert found == ("success", "0"), f"revproxy-build.service's last run (result, exit status) is {found}"


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


# The polkit actions tm-control uses (tmsetup_tm_control_polkit's actions), asked as the code owner. None of these
# changes anything: logind's Can* methods only answer what polkit would say, and set-ntp gets the current value.
# CanHalt is the control: halting isn't on the list, so polkit would ask for a password ("challenge").
LOGIND_CAN = "busctl call org.freedesktop.login1 /org/freedesktop/login1 org.freedesktop.login1.Manager {}"
LOGIND_EXPECTED = {"CanReboot": 's "yes"', "CanPowerOff": 's "yes"', "CanHalt": 's "challenge"'}


def as_code_owner(host, codeowner, command):
    return host.run(f"sudo -n runuser -u {shlex.quote(codeowner)} -- {command}")


def test_polkit_allows_only_the_listed_actions(host, codeowner):
    """The code owner may reboot, power off, and set NTP, and nothing more of logind's: halting still needs a password.
    test_polkit_keeps_tm_control_to_its_units checks the units."""
    if codeowner == "root":
        pytest.skip("the code owner is root, which polkit doesn't limit")
    assert "org.freedesktop.login1.halt" not in role_vars()["tmsetup_tm_control_polkit"]["actions"]
    found = {method: as_code_owner(host, codeowner, LOGIND_CAN.format(method)).stdout.strip()
             for method in LOGIND_EXPECTED}
    assert found == LOGIND_EXPECTED, f"logind's answers to {codeowner}"
    ntp = "true" if host.check_output("timedatectl show -p NTP --value") == "yes" else "false"
    result = as_code_owner(host, codeowner, f"timedatectl --no-ask-password set-ntp {ntp}")
    assert result.rc == 0, (
        f"as {codeowner}, timedatectl set-ntp {ntp} exited {result.rc}: {result.stderr.strip()[:200]}")


def test_tm_control_has_the_video_group(request, host, address):
    """tm-control runs with the video group, which vcgencmd needs to read the firmware's power and throttling flags,
    so the Device page shows them."""
    groups = host.check_output("systemctl show -p SupplementaryGroups --value tm-control.service").split()
    assert "video" in groups, f"tm-control.service's SupplementaryGroups are {groups}"
    login = tm_login_or_none(request)
    if login is None:
        pytest.skip("tm-control.service has the video group; reading GET /system/info's throttled needs "
                    "tm_control_login in the inventory")
    answer = request_from_this_machine(address, f"{API}/system/info", cookie=session(address, *login))
    info = answer.json() if answer.status == 200 else None
    assert isinstance(info, dict), f"GET {API}/system/info answered {answer.status}"
    assert info.get("throttled") is not None, f"GET {API}/system/info has no throttled flags: vcgencmd failed"


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


def test_tm_control_may_write_the_two_config_directories(host, codedir):
    """tm-control.service's sandbox is read-only apart from its own directories, Frigate's config directory (the
    Detection page's model_cache and config.yml) and Node-RED's (the config.yml the Location page writes)."""
    paths = host.check_output("systemctl show -p ReadWritePaths --value tm-control.service").split()
    expected = [f"{codedir}/frigate/config", f"{codedir}/node-red-tm/config"]
    assert sorted(paths) == sorted(expected), f"tm-control.service's ReadWritePaths are {paths}, not {expected}"


# A 2 MB body, over nginx's default 1 MB limit, sent from the Pi to nginx on port 80 with no session and no Origin
# header, and the Host header the other tests send. curl's default Expect: 100-continue stays: nginx checks the size
# from the headers and refuses before any body is sent. Nothing in the body is a secret, and no request is let
# through to change anything.
BODY_MB = 2
PUT_BODY = ("head -c {size} /dev/zero | curl -s -o /dev/null -w '%{{http_code}}' --max-time 30 -X PUT "
            "-H {host_header} -H 'Content-Type: application/octet-stream' --data-binary @- http://localhost{path}")


def put_two_megabytes(host, address, path):
    return host.run(PUT_BODY.format(size=BODY_MB * 1024 * 1024, host_header=shlex.quote(f"Host: {address}"),
                                    path=path)).stdout.strip()


def test_model_uploads_are_proxied_with_the_larger_limit(host, address):
    """nginx lets a model upload's body through up to 100 MB, and keeps its default 1 MB limit for every other API
    path. Without a session or an Origin header, a 2 MB upload reaches tm-control, whose cross-site check answers 403,
    where nginx's own limit would have answered 413; the same body to the secrets path is stopped by nginx."""
    found = (put_two_megabytes(host, address, f"{API}/models/upload/x.tflite"),
             put_two_megabytes(host, address, f"{API}/secrets/x"))
    assert found == ("403", "413"), (
        f"a 2 MB PUT to {API}/models/upload/x.tflite and to {API}/secrets/x answered {found}, not (403, 413)")
