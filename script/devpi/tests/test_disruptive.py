"""Recovery: the stack comes back after a restart, a reboot, and a reset with no shutdown; the login fails closed and
can be reset; the control app's restart, time, and reboot actions work.

These stop services, reboot or reset the Pi, change its clock or time zone, or reset the unit's tm-control accounts, so
they run only with tmdev.py test --disruptive. Ask the person first. Two of them reboot the Pi, test_reboot_recovers
and test_reboot_from_the_control_app, and test_stack_recovers_after_an_unclean_reset resets it without shutting down.
"""

import hashlib
import io
import json
import re
import shlex
import time
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from devpi_checks import (API, RESTARTING_UNITS, Redacted, db_query, detector_name, entered_secret_states,
                          find_hevc_decoder, frigate_host_devices, pi_now, podman_events, request_from_this_machine,
                          require_pii_free, role_vars, session, status_checks, tm_login_or_none)

pytestmark = pytest.mark.disruptive

TM_CONTROL_PORT = role_vars()["tmsetup_tm_control_port"]
# A unit is active before its app answers; node-red-tm runs tmdb_migrate.py and then boots Node-RED.
# Only the HTTP status is checked.
APPS_UP = [
    ("Frigate API on port 5000", "curl -fsS -o /dev/null --max-time 10 http://localhost:5000/api/version"),
    ("Node-RED on port 1880", "curl -fsS -o /dev/null --max-time 10 http://localhost:1880/"),
    ("nginx on port 80", "curl -fsS -o /dev/null --max-time 10 http://localhost/"),
    (f"tm-control on port {TM_CONTROL_PORT}",
     f"curl -fsS -o /dev/null --max-time 10 http://localhost:{TM_CONTROL_PORT}{API}/health"),
]
RESTART_TIMEOUT_SECONDS = 5 * 60
REBOOT_TIMEOUT_SECONDS = 10 * 60


def not_ready(host):
    """What isn't back yet, or an empty list once every unit is active and Frigate, Node-RED, and nginx answer."""
    try:
        waiting = [unit for unit in RESTARTING_UNITS
                   if host.run(f"systemctl is-active {unit}").stdout.strip() != "active"]
        if not waiting:
            waiting = [app for app, probe in APPS_UP if host.run(probe).rc != 0]
        return waiting
    except RuntimeError:  # testinfra's SSH failure while the Pi reboots
        return ["SSH (the Pi is still booting)"]


def wait_until_ready(host, timeout):
    deadline = time.monotonic() + timeout
    while waiting := not_ready(host):
        assert time.monotonic() < deadline, f"after {timeout // 60} minutes, still waiting on: {waiting}"
        time.sleep(10)


def test_restart_recovers(host):
    with host.sudo():
        host.check_output("systemctl restart traffic-monitor.service")
    wait_until_ready(host, RESTART_TIMEOUT_SECONDS)


def test_reboot_recovers(host):
    host.ansible("reboot", f"reboot_timeout={REBOOT_TIMEOUT_SECONDS}", become=True, check=False)
    wait_until_ready(host, REBOOT_TIMEOUT_SECONDS)


# Through PID 1, a moment later, so the SSH command returns before the Pi goes down without closing the connection.
UNCLEAN_RESET = "systemd-run --on-active=2 /bin/sh -c 'sync; echo b > /proc/sysrq-trigger'"


def unclean_reset(host):
    """Reset the Pi with no shutdown, as a power loss does, and wait until it boots again."""
    before = boot_id(host)
    assert before, "couldn't read the Pi's boot id"
    with host.sudo():
        host.check_output(UNCLEAN_RESET)
    deadline = time.monotonic() + REBOOT_TIMEOUT_SECONDS
    while boot_id(host) in (before, None):
        assert time.monotonic() < deadline, (
            f"the Pi didn't reset and come back within {REBOOT_TIMEOUT_SECONDS // 60} minutes")
        time.sleep(10)


def test_stack_recovers_after_an_unclean_reset(host):
    """A reset with no shutdown leaves the pod's containers in Podman's state, as a power loss does. The next boot's
    refresh removes them, which is where Podman 5.4.2 can crash (#268). The sync keeps the test about Podman's
    leftovers, not about what the SD card loses."""
    unclean_reset(host)
    wait_until_ready(host, REBOOT_TIMEOUT_SECONDS)
    refreshes = podman_events(host, "refresh")
    assert len(refreshes) == 1, refreshes
    removed = [entry for entry in podman_events(host, "remove") if entry["_PID"] == refreshes[0]["_PID"]]
    assert removed, "the refresh removed no containers, so the reset wasn't unclean"
    assert " build " not in f"{refreshes[0]['_CMDLINE']} ", refreshes[0]


# Media numbers are handed out lowest-free, so unbinding the decoder and the ISP back end (which holds two)
# and rebinding them in the right order gives the decoder a different number, as a reboot sometimes does (#231).
DRIVERS = {"rpi-hevc-dec": "1000800000.codec", "pispbe": "1000880000.pisp_be"}
HEVC_SYMLINK = role_vars()["tmsetup_hevc_device"]


def bind(host, driver, action):
    host.check_output(f"echo {DRIVERS[driver]} > /sys/bus/platform/drivers/{driver}/{action}")


def test_frigate_follows_the_decoder_after_its_number_changes(host):
    """After the decoder's /dev/media number changes, the symlink and a restarted Frigate follow it."""
    before = find_hevc_decoder(host)
    with host.sudo():
        # The minors these two drivers hold; the camera front end keeps its own and isn't touched.
        # testinfra runs sudo commands with /bin/sh, which has no brace expansion, so both paths are spelled out.
        freed = sorted(int(line.split(":")[1]) for line in host.check_output(
            "cat /sys/bus/platform/devices/1000800000.codec/media*/dev"
            " /sys/bus/platform/devices/1000880000.pisp_be/media*/dev").splitlines())
        decoder_minor = int(host.check_output("cat /sys/bus/platform/devices/1000800000.codec/media*/dev").split(":")[1])
        try:
            # go2rtc's rpicam-vid holds the ISP; Frigate holds the decoder. Stopped inside the try so they always restart.
            host.check_output("systemctl stop frigate.service go2rtc_server.service")
            bind(host, "rpi-hevc-dec", "unbind")
            bind(host, "pispbe", "unbind")
            # Bound first, a driver takes the lowest freed number. The decoder gets it unless it's the one it had;
            # then the ISP back end goes first and takes the two lowest.
            order = ["pispbe", "rpi-hevc-dec"] if decoder_minor == min(freed) else ["rpi-hevc-dec", "pispbe"]
            for driver in order:
                bind(host, driver, "bind")
            host.check_output("udevadm settle")
        finally:
            for driver in DRIVERS:
                if not host.file(f"/sys/bus/platform/drivers/{driver}/{DRIVERS[driver]}").exists:
                    bind(host, driver, "bind")
            host.check_output("systemctl start go2rtc_server.service frigate.service")
    after = find_hevc_decoder(host)
    assert after != before, f"the decoder is still {before}; the rebind didn't change its number"
    assert host.run(f"readlink -f {HEVC_SYMLINK}").stdout.strip() == after
    wait_until_ready(host, RESTART_TIMEOUT_SECONDS)
    assert after in frigate_host_devices(host), f"Frigate was restarted but got {frigate_host_devices(host)}, not {after}"


def proxy_status(host, address, path):
    # Host header as a browser's would be, so the nginx image's stock default.conf (server_name localhost) doesn't answer.
    # host.run, not check_output: when curl can't connect it exits non-zero and still prints 000.
    return host.run(f"curl -s -o /dev/null -w '%{{http_code}}' --max-time 10 -H 'Host: {address}' "
                    f"http://localhost{path}").stdout.strip()


def admin_session_or_none(request, address):
    """The admin's session cookie when the inventory has tm_control_login and the unit is claimed, otherwise None."""
    login = tm_login_or_none(request)
    if login is None:
        return None
    try:
        return session(address, *login)
    except pytest.skip.Exception:  # unclaimed
        return None


def test_home_page_survives_a_stopped_pod(request, host, address):
    """nginx and tm-control run outside the pod, so with the pod stopped the home page loads and the login check
    still answers: /frigate/ is the login redirect without a session, and with the admin's, Frigate's 502."""
    cookie = admin_session_or_none(request, address)  # before the pod stops, though logging in doesn't need it
    expected = ("200", 502 if cookie else 302)
    try:
        with host.sudo():
            host.check_output("systemctl stop traffic-monitor.service")
        statuses = (proxy_status(host, address, "/"),
                    request_from_this_machine(address, "/frigate/", cookie=cookie).status)
        assert statuses == expected, (f"with the pod stopped, / and /frigate/ "
                                      f"({'with' if cookie else 'without'} a session) answered {statuses}")
    finally:
        with host.sudo():
            host.check_output("systemctl start traffic-monitor.service")
        wait_until_ready(host, RESTART_TIMEOUT_SECONDS)


# Makes the network unit's next start fail once, like the Podman panic in #232; its Restart=on-failure then brings it up.
NETWORK_DROPIN = "/run/systemd/system/tmnet-network.service.d/tmdev-fail-once.conf"
NETWORK_FAILED_ONCE = "/run/tmdev-tmnet-failed-once"
FAIL_ONCE = f'[Service]\nExecStartPre=/bin/sh -c "test -e {NETWORK_FAILED_ONCE} || {{ touch {NETWORK_FAILED_ONCE}; exit 1; }}"\n'


def test_pod_starts_after_its_network_unit_fails_once(host):
    """One failed start of tmnet-network.service, as at boot in #232, doesn't keep the pod down."""
    try:
        # Inside the try, so a setup that fails partway is still undone: each cleanup step is safe to run twice.
        with host.sudo():
            host.check_output("systemctl stop traffic-monitor.service tmnet-network.service")
            host.check_output(f"mkdir -p {NETWORK_DROPIN.rsplit('/', 1)[0]} && rm -f {NETWORK_FAILED_ONCE} "
                              f"&& printf %s {shlex.quote(FAIL_ONCE)} > {NETWORK_DROPIN} && systemctl daemon-reload")
            host.run("systemctl start traffic-monitor.service")  # before #232's fix, a dependency job fails here
        deadline = time.monotonic() + 120
        while host.run("systemctl is-active traffic-monitor.service").stdout.strip() != "active":
            assert time.monotonic() < deadline, "the pod didn't start after tmnet-network.service failed once (#232)"
            time.sleep(5)
        assert host.file(NETWORK_FAILED_ONCE).exists, "the drop-in didn't make tmnet-network.service fail"
    finally:
        with host.sudo():
            host.check_output(f"rm -f {NETWORK_DROPIN} {NETWORK_FAILED_ONCE} && systemctl daemon-reload")
            host.check_output("systemctl start tmnet-network.service traffic-monitor.service")
        wait_until_ready(host, RESTART_TIMEOUT_SECONDS)


# The status of a path through nginx, and how many lines of its page name Cockpit's port 9090. The page names the
# Pi's hostname, so only the two numbers come back.
RESCUE_PAGE = """\
page=$(curl -s --max-time 10 -H {host_header} -w '\\n%{{http_code}}' http://localhost{path})
printf '%s\\n' "$page" | tail -n 1
printf '%s\\n' "$page" | grep -c 9090"""


def test_app_paths_fail_closed_when_tm_control_is_down(host, address):
    """With tm-control stopped, nginx can't check the login, so app paths answer 503 with the rescue page, which
    says to use Cockpit on port 9090, instead of letting anyone in. The home page still loads."""
    host_header = shlex.quote(f"Host: {address}")
    try:
        with host.sudo():
            host.check_output("systemctl stop tm-control.service")
        # A viewer path and an admin path: each auth snippet has its own error_page
        pages = {path: host.run(RESCUE_PAGE.format(host_header=host_header, path=path)).stdout.split()
                 for path in ("/frigate/", "/nr/")}
        home = proxy_status(host, address, "/")
    finally:
        with host.sudo():
            host.check_output("systemctl start tm-control.service")
        wait_until_ready(host, RESTART_TIMEOUT_SECONDS)
    wrong = {path: found for path, found in pages.items()
             if len(found) != 2 or found[0] != "503" or found[1] == "0"}
    assert not wrong, f"with tm-control stopped, (status, lines naming 9090) per path: {wrong}"
    assert home == "200", f"with tm-control stopped, / answered {home}"


CODE = r"[A-Z2-9]{4}-[A-Z2-9]{4}"
SETUP_CODE = re.compile(rf"Setup code: ({CODE})")
SETUP_CODE_FILE = f"{role_vars()['tmsetup_etc_dir']}/setup-code"
CODE_HELP = (f"Its setup code is in {SETUP_CODE_FILE} on the Pi (root only): claim it at /setup with the inventory's "
             "tm_control_login, or run `sudo tm-control reset-admin` for a new code")


def reset_admin(host):
    """Run sudo tm-control reset-admin: (exit code, why it failed or None, the new setup code Redacted or None).

    The command's output holds the code, so the CommandResult and the match are deleted here, before anything can
    fail with them in a local for pytest -l to print.
    """
    with host.sudo():
        result = host.run("tm-control reset-admin")
    rc = result.rc
    found = SETUP_CODE.search(result.stdout) if rc == 0 else None
    problem = None if found else (result.stderr.strip().splitlines() or ["no setup code in its output"])[-1]
    del result
    code = Redacted(found[1], "setup code") if found else None
    del found
    return rc, problem, code


def setup_code_from_file(host):
    """The setup code reset-admin wrote to its root-only file on the Pi, Redacted, or None. Never printed."""
    try:
        with host.sudo():
            result = host.run(f"cat {SETUP_CODE_FILE}")
    except RuntimeError:  # testinfra's SSH failure
        return None
    found = re.fullmatch(CODE, result.stdout.strip()) if result.rc == 0 else None
    del result
    code = Redacted(found[0], "setup code") if found else None
    del found
    return code


def claim_again(host, address, login, version, code):
    """Claim the unit with the inventory's login after reset-admin. Returns None when the unit is claimed afterwards,
    by this claim or because the reset never unclaimed it; otherwise why not, saying whether the unit is unclaimed
    or its state is unknown (the Pi didn't answer), and where the code is.

    Without the code from reset-admin's output (it didn't parse, or SSH dropped), it reads the code file instead.
    """
    if code is None:
        code = setup_code_from_file(host)
    if code is not None:
        username, password = login
        status = request_from_this_machine(address, f"{API}/setup/claim", "POST",
                                           body={"setup_code": code, "username": username, "password": password,
                                                 "eula_version": version}).status
        if status == 201:
            return None
        why = f"claiming with the new setup code answered {status}"
    else:
        why = f"couldn't read the new setup code from reset-admin's output or {SETUP_CODE_FILE}"
    answer = request_from_this_machine(address, f"{API}/setup/status")
    state = answer.json() if answer.status == 200 else None
    if not isinstance(state, dict) or "claimed" not in state:
        return (f"{why}; the unit's state is unknown, because GET {API}/setup/status answered {answer.status}. "
                f"If it's unclaimed: {CODE_HELP}")
    if state["claimed"]:
        return None
    return f"{why}; the unit is unclaimed now. {CODE_HELP}"


def test_reset_admin_then_claim(host, address, expect, tm_login):
    """An operator who lost the admin's password runs sudo tm-control reset-admin: every app path then sends the
    browser to /setup, and the new code claims the unit again.

    It claims with the inventory's tm_control_login, so the admin comes back and the tests after this one still log
    in. Sessions made before it end. Deletes every tm-control account on the unit, so pii_free (bench) units only.
    """
    if not expect["pii_free"]:
        pytest.skip("deletes every tm-control account on the unit; set tm_expect.pii_free: true (bench units only)")
    username, password = tm_login
    # Before anything changes: the login must work, or claiming with it afterwards would fail and leave the unit
    # unclaimed. session() skips while the unit is unclaimed.
    session(address, username, password)
    eula = request_from_this_machine(address, f"{API}/setup/eula")
    found = eula.json() if eula.status == 200 else None
    version = found.get("version") if isinstance(found, dict) else None
    assert version, f"GET {API}/setup/eula answered {eula.status} without a version"

    rc, problem, code = None, None, None
    try:
        rc, problem, code = reset_admin(host)
        redirect = request_from_this_machine(address, "/dashboard/")
    finally:
        # Claimed again even when something above fails. A failure here is the one to report: it replaces any
        # other, because the unit is left without an admin.
        unclaimed = claim_again(host, address, tm_login, version, code)
        if unclaimed:
            pytest.fail(unclaimed, pytrace=False)  # keeps the code file, which the message points to
        with host.sudo():
            host.check_output(f"rm -f {SETUP_CODE_FILE}")  # as tmsetup.sh does once the unit is claimed
    assert (rc, problem) == (0, None), "sudo tm-control reset-admin (exit code, problem); the unit is claimed again"
    assert (redirect.status, redirect.headers.get("Location")) == (302, "/setup"), "/dashboard/ after reset-admin"
    dashboard = request_from_this_machine(address, "/dashboard/", cookie=session(address, username, password))
    assert dashboard.status == 200, f"/dashboard/ with the reclaimed admin's session answered {dashboard.status}"


# --- The control app's actions (tm-control M3) ------------------------------------------------------------------------
# Each test logs in for itself: test_reset_admin_then_claim ends the sessions made before it.

UNIT_RESTART_SECONDS = 120  # a restart queued through the API: the unit stops, then starts with a new InvocationID
INVOCATION_ID = re.compile(r"[0-9a-f]{32}")


def invocation(host, unit):
    return host.check_output(f"systemctl show -p InvocationID --value {unit}")


def not_restarted(host, before, timeout):
    """Wait until each unit in before ({unit: its InvocationID}) is active with another InvocationID, for at most
    timeout seconds; the units that aren't."""
    deadline = time.monotonic() + timeout
    while True:
        waiting = [unit for unit, old in before.items()
                   if host.run(f"systemctl is-active {unit}").stdout.strip() != "active"
                   or invocation(host, unit) in ("", old)]
        if not waiting or time.monotonic() >= deadline:
            return waiting
        time.sleep(5)


def post_time(address, cookie, change):
    """POST /time: (HTTP status, the answer's JSON, or an empty dict when it isn't a 200)."""
    answer = request_from_this_machine(address, f"{API}/time", "POST", cookie, change)
    found = answer.json() if answer.status == 200 else None
    return answer.status, found if isinstance(found, dict) else {}


def test_restart_from_the_control_app(host, address, tm_login):
    """An admin's restart from the Status page restarts the unit, through polkit."""
    cookie = session(address, *tm_login)
    before = {"frigate.service": invocation(host, "frigate.service")}
    answer = request_from_this_machine(address, f"{API}/services/frigate.service/restart", "POST", cookie, {})
    assert answer.status == 202, f"POST {API}/services/frigate.service/restart answered {answer.status}"
    waiting = not_restarted(host, before, UNIT_RESTART_SECONDS)
    wait_until_ready(host, RESTART_TIMEOUT_SECONDS)
    assert not waiting, f"{UNIT_RESTART_SECONDS} s after the restart was queued, {waiting} wasn't active again"


def test_frigate_restarting_itself_stays_ok(host, address, tm_login):
    """Frigate restarts itself when its config is saved, which systemd counts as a restart after a failure. Restarted
    through Frigate's own API, as its Save does, the Services row stays ok and says so. A restart from the control app
    then clears the count, so the unit is as before."""
    cookie = session(address, *tm_login)
    before = {"frigate.service": invocation(host, "frigate.service")}
    try:
        host.check_output("curl -sS -o /dev/null --max-time 10 -X POST http://127.0.0.1:5000/api/restart")
        waiting = not_restarted(host, before, UNIT_RESTART_SECONDS)
        assert not waiting, f"{UNIT_RESTART_SECONDS} s after Frigate's own restart, frigate.service wasn't active again"
        count = host.check_output("systemctl show -p NRestarts --value frigate.service")
        assert count != "0", "systemd didn't count Frigate's own restart, so this test can't check the Services row"
        # The report is cached for 5 seconds, and may be from while Frigate was starting.
        found = wait_for_check(address, cookie, "services.frigate.service", "ok", 30)
        assert found[0] == "ok" and "restarted itself" in (found[1] or ""), (
            f"services.frigate.service after Frigate restarted itself: {found}")
    finally:
        # Put NRestarts back to 0, as a person's restart from the Status page would.
        before = {"frigate.service": invocation(host, "frigate.service")}
        request_from_this_machine(address, f"{API}/services/frigate.service/restart", "POST", cookie, {})
        not_restarted(host, before, UNIT_RESTART_SECONDS)
        wait_until_ready(host, RESTART_TIMEOUT_SECONDS)


TOKEN = "thingsboard_access_token"
# A test value, never a real token: 22 characters, so GET /secrets shows its last four
TOKEN_PLACEHOLDER = "tmdev-placeholder-0001"
KEY = "frigate_plus_api_key"
# A test value, never a real key, in the format Frigate's PlusApi accepts (77 characters): the same placeholder as
# tm-control's tests, which these can't import
KEY_PLACEHOLDER = "tmdev000-0000-0000-0000-000000000001:0123456789abcdef0123456789abcdef01234567"
JOB_POLL_SECONDS = 2
# The job restarts each unit with a 120-second timeout (RESTART_TIMEOUT in tm-job-set-secret), after its file steps, so
# the wait has headroom and a slow restart shows as the job's own result
JOB_WAIT_SECONDS = UNIT_RESTART_SECONDS + 60


def wait_for_job(address, cookie, job_id, timeout):
    """Read GET /jobs/{id} until the job has succeeded or failed, for at most timeout seconds: (its last status, its
    last log lines). The set-secret job never logs a value."""
    deadline = time.monotonic() + timeout
    while True:
        answer = request_from_this_machine(address, f"{API}/jobs/{job_id}", cookie=cookie)
        job = answer.json() if answer.status == 200 else None
        status = job.get("status") if isinstance(job, dict) else f"HTTP {answer.status}"
        if status in ("succeeded", "failed") or time.monotonic() >= deadline:
            return status, (job.get("log") or [])[-5:] if isinstance(job, dict) else []
        time.sleep(JOB_POLL_SECONDS)


def secret_state(address, cookie, name):
    """GET /secrets' (set, ends_with) for one entered secret, or the HTTP status when it can't be read."""
    answer = request_from_this_machine(address, f"{API}/secrets", cookie=cookie)
    found = answer.json() if answer.status == 200 else None
    listed = found.get("secrets") if isinstance(found, dict) else None
    for entry in listed if isinstance(listed, list) else []:
        if entry.get("name") == name:
            return entry.get("set"), entry.get("ends_with")
    return f"HTTP {answer.status}"


def token_state(address, cookie):
    """GET /secrets' (set, ends_with) for the ThingsBoard token, or the HTTP status when it can't be read."""
    return secret_state(address, cookie, TOKEN)


def set_secret(host, address, cookie, name, value, restarts, untouched):
    """Set (or, with "", remove) an entered secret through the control app, as the Device page does, and wait for the
    job and the restart of each unit in restarts; each unit in untouched must keep its InvocationID. Fails with what
    went wrong, naming the secret, never its value."""
    before = {unit: invocation(host, unit) for unit in restarts}
    kept = {unit: invocation(host, unit) for unit in untouched}
    action = f"POST {API}/secrets/{name}" if value else f"DELETE {API}/secrets/{name}"
    if value:
        answer = request_from_this_machine(address, f"{API}/secrets/{name}", "POST", cookie, {"value": value})
    else:
        answer = request_from_this_machine(address, f"{API}/secrets/{name}", "DELETE", cookie)
    started = answer.json() if answer.status == 202 else None
    job_id = started.get("id") if isinstance(started, dict) else None
    assert job_id, f"{action} answered {answer.status}"
    status, log = wait_for_job(address, cookie, job_id, JOB_WAIT_SECONDS)
    assert status == "succeeded", f"{action}: the job is {status} after {JOB_WAIT_SECONDS} s; its log ends {log}"
    waiting = not_restarted(host, before, UNIT_RESTART_SECONDS)
    assert not waiting, f"after {action}, {waiting} hadn't restarted"
    wait_until_ready(host, RESTART_TIMEOUT_SECONDS)
    restarted = [unit for unit, old in kept.items() if invocation(host, unit) != old]
    assert not restarted, f"after {action}, {restarted} restarted, which the job shouldn't touch"


def set_token(host, address, cookie, value):
    """Set (or, with "", remove) the ThingsBoard token through the control app, as the Device page does, and wait for
    the job and Node-RED's restart. Fails with what went wrong."""
    set_secret(host, address, cookie, TOKEN, value, ["node-red-tm.service"], [])


def test_set_and_remove_the_thingsboard_token_from_the_control_app(host, address, expect, codedir, tm_login):
    """An admin's Save on the Device page writes the ThingsBoard token's file and node-red-tm.env's line through the
    set-secret job and restarts Node-RED, and Remove empties both. Uses a placeholder, and leaves the token empty, as a
    pii_free unit has it; skips when a token is already set, since it couldn't put it back. The file and the line are
    compared on the Pi."""
    if not expect["pii_free"]:
        pytest.skip("writes the ThingsBoard token's file and node-red-tm.env; set tm_expect.pii_free: true "
                    "(bench units only)")
    cookie = session(address, *tm_login)
    before = token_state(address, cookie)
    if isinstance(before, tuple) and before[0] is True:
        pytest.skip("a ThingsBoard token is already set and can't be restored; remove it on the Device page first")
    assert before == (False, None), f"GET {API}/secrets before the test: {before}"
    del before
    line = "node-red-tm/node-red-tm.env:TM_THINGSBOARD_ACCESS_TOKEN"
    removed = False
    try:
        set_token(host, address, cookie, TOKEN_PLACEHOLDER)
        states = entered_secret_states(host, codedir, [TOKEN], {TOKEN: TOKEN_PLACEHOLDER})
        assert (states[f"secret {TOKEN}"], states[line]) == ("equal", "equal"), (
            f"after Save, (the file against the placeholder, the env line against the file): {states}")
        assert token_state(address, cookie) == (True, TOKEN_PLACEHOLDER[-4:]), f"GET {API}/secrets after Save"
        set_token(host, address, cookie, "")
        removed = True
        states = entered_secret_states(host, codedir, [TOKEN], {TOKEN: ""})
        assert (states[f"secret {TOKEN}"], states[line]) == ("equal", "equal"), (
            f"after Remove, (the file against empty, the env line against the file): {states}")
        assert token_state(address, cookie) == (False, None), f"GET {API}/secrets after Remove"
    finally:
        if not removed:  # put the token back to empty, even when Save failed partway; a failure here chains
            try:
                set_token(host, address, cookie, "")
            except AssertionError as error:
                raise AssertionError(f"the placeholder token may still be set; remove it on the Device page ({error})")


def test_set_and_remove_the_frigate_plus_key_from_the_control_app(host, address, expect, codedir, tm_login):
    """An admin's Save on the Device page writes the Frigate+ API key's file and frigate.env's PLUS_API_KEY line
    through the set-secret job and restarts Frigate while Node-RED keeps running, and Remove empties both and restarts
    Frigate again. Uses a placeholder in Frigate's key format, so Frigate accepts it; with no plus:// model set and no
    snapshot submitted, Frigate never contacts Frigate+ with it. Leaves the key empty, as a pii_free unit has it; skips
    when a key is already set, since it couldn't put it back. The file and the line are compared on the Pi. Each step
    restarts Frigate, so the unit doesn't count traffic for about a minute each time."""
    if not expect["pii_free"]:
        pytest.skip("writes the Frigate+ API key's file and frigate.env; set tm_expect.pii_free: true "
                    "(bench units only)")
    cookie = session(address, *tm_login)
    before = secret_state(address, cookie, KEY)
    if isinstance(before, tuple) and before[0] is True:
        pytest.skip("a Frigate+ API key is already set and can't be restored; remove it on the Device page first")
    assert before == (False, None), f"GET {API}/secrets before the test: {before}"
    del before
    line = "frigate/frigate.env:PLUS_API_KEY"
    restarts, untouched = ["frigate.service"], ["node-red-tm.service"]
    removed = False
    try:
        set_secret(host, address, cookie, KEY, KEY_PLACEHOLDER, restarts, untouched)
        states = entered_secret_states(host, codedir, [KEY], {KEY: KEY_PLACEHOLDER})
        assert (states[f"secret {KEY}"], states[line]) == ("equal", "equal"), (
            f"after Save, (the file against the placeholder, the env line against the file): {states}")
        assert secret_state(address, cookie, KEY) == (True, KEY_PLACEHOLDER[-4:]), f"GET {API}/secrets after Save"
        set_secret(host, address, cookie, KEY, "", restarts, untouched)
        removed = True
        states = entered_secret_states(host, codedir, [KEY], {KEY: ""})
        assert (states[f"secret {KEY}"], states[line]) == ("equal", "equal"), (
            f"after Remove, (the file against empty, the env line against the file): {states}")
        assert secret_state(address, cookie, KEY) == (False, None), f"GET {API}/secrets after Remove"
    finally:
        if not removed:  # put the key back to empty, even when Save failed partway; a failure here chains
            try:
                set_secret(host, address, cookie, KEY, "", restarts, [])
            except AssertionError as error:
                raise AssertionError(f"the placeholder key may still be set; remove it on the Device page ({error})")


# The Detection page's upload, package, and delete, with a placeholder model that no one uses: 16 bytes would break
# Frigate. The sidecar is the repo's synthetic one, as a local model's: no id, and no per-camera counts, which
# must never reach a device.
FIXTURES = Path(__file__).resolve().parents[3] / "tm-control" / "backend" / "tests" / "fixtures"
SIDECAR_FIXTURE = FIXTURES / "model_sidecar.json"
PLACEHOLDER_MODEL = "tmdev-placeholder.tflite"
PLACEHOLDER_SIDECAR = PLACEHOLDER_MODEL + ".json"
PLACEHOLDER_BYTES = bytes(range(16))
OCTET_STREAM = {"Content-Type": "application/octet-stream"}


def placeholder_sidecar(detector):
    """The fixture's sidecar as a local model's for this detector, serialized."""
    record = json.loads(SIDECAR_FIXTURE.read_text())
    record.pop("id", None)
    record.pop("verifiedCounts", None)
    record["name"] = "tmdev placeholder"
    record["supportedDetectors"] = [detector]
    return json.dumps(record, indent=2).encode()


def listed_models(address, cookie):
    """GET /models' models by name; fails when the list can't be read."""
    answer = request_from_this_machine(address, f"{API}/models", cookie=cookie)
    found = answer.json() if answer.status == 200 else None
    models = found.get("models") if isinstance(found, dict) else None
    assert isinstance(models, list), f"GET {API}/models answered {answer.status}, not a model list"
    return {model.get("name"): model for model in models}


def delete_placeholder(address, cookie):
    """Delete the placeholder model if it's listed, whatever state it's in."""
    if PLACEHOLDER_MODEL in listed_models(address, cookie):
        deleted = request_from_this_machine(address, f"{API}/models/{PLACEHOLDER_MODEL}", "DELETE", cookie)
        assert deleted.status == 204, (f"DELETE {API}/models/{PLACEHOLDER_MODEL} answered {deleted.status}; delete the "
                                       "placeholder on the Detection page")


def test_upload_package_and_delete_a_model_from_the_control_app(host, address, expect, tm_login):
    """An admin uploads a placeholder model's sidecar and then its file, the pair is listed complete and usable for the
    unit's detector, its package is a zip of both files and SHA256SUMS that match what was sent and the listed hashes,
    and deleting it removes it. Frigate is never restarted: the placeholder isn't used. Leaves nothing behind, and
    skips when a placeholder from an earlier run is still listed, which this test didn't make."""
    require_pii_free(expect)
    cookie = session(address, *tm_login)
    if PLACEHOLDER_MODEL in listed_models(address, cookie):
        pytest.skip(f"{PLACEHOLDER_MODEL} is already listed; delete it on the Detection page first")
    detector = detector_name(expect)
    sidecar = placeholder_sidecar(detector)
    frigate = invocation(host, "frigate.service")
    sent = {PLACEHOLDER_MODEL: PLACEHOLDER_BYTES, PLACEHOLDER_SIDECAR: sidecar}
    try:
        for filename in (PLACEHOLDER_SIDECAR, PLACEHOLDER_MODEL):
            uploaded = request_from_this_machine(address, f"{API}/models/upload/{filename}", "PUT", cookie,
                                                 sent[filename], OCTET_STREAM)
            assert uploaded.status == 201, f"PUT {API}/models/upload/{filename} answered {uploaded.status}"
        entry = listed_models(address, cookie).get(PLACEHOLDER_MODEL)
        assert entry is not None, f"{PLACEHOLDER_MODEL} isn't listed after both uploads"
        assert (entry.get("complete"), entry.get("usable")) == (True, True), (
            f"the uploaded pair (complete, usable) for detector {detector}: "
            f"({entry.get('complete')}, {entry.get('usable')}); problem: {entry.get('problem')}")
        digests = {name: hashlib.sha256(data).hexdigest() for name, data in sent.items()}
        listed = {file.get("name"): (file.get("size"), file.get("sha256")) for file in entry.get("files", [])}
        assert listed == {name: (len(data), digests[name]) for name, data in sent.items()}, (
            f"the entry's files (name: size, sha256): {listed}")
        package = request_from_this_machine(address, f"{API}/models/{PLACEHOLDER_MODEL}/package", cookie=cookie)
        assert package.status == 200, f"GET {API}/models/{PLACEHOLDER_MODEL}/package answered {package.status}"
        with zipfile.ZipFile(io.BytesIO(package.body)) as archive:
            members = {name: archive.read(name) for name in archive.namelist()}
        assert sorted(members) == sorted([*sent, "SHA256SUMS"]), f"the package's members: {sorted(members)}"
        assert {name: members[name] for name in sent} == sent, "the package's files differ from what was uploaded"
        sums = dict(reversed(line.split("  ", 1)) for line in members["SHA256SUMS"].decode().splitlines())
        assert sums == digests, f"the package's SHA256SUMS (name: hash) differ from the files': {sums}"
        deleted = request_from_this_machine(address, f"{API}/models/{PLACEHOLDER_MODEL}", "DELETE", cookie)
        assert deleted.status == 204, f"DELETE {API}/models/{PLACEHOLDER_MODEL} answered {deleted.status}"
        assert PLACEHOLDER_MODEL not in listed_models(address, cookie), f"{PLACEHOLDER_MODEL} is still listed"
        assert invocation(host, "frigate.service") == frigate, "frigate.service restarted; nothing here should"
    finally:
        try:
            delete_placeholder(address, cookie)
        except AssertionError as error:
            raise AssertionError(f"the placeholder model may still be there ({error})")


# POST /time's restarting after a new time zone (CONTAINERS in tm_control/modules/time/router.py)
ZONE_UNITS = ["traffic-monitor.service", "revproxy.service"]
TEST_ZONES = ["Pacific/Auckland", "UTC", "America/Los_Angeles"]
# Node-RED starts each log line with its own time, in its container's zone ("28 Oct 14:41:35 - [info] ..."). This keeps
# each such line's journal time, in seconds since the epoch, and Node-RED's time, and nothing else: a line can quote
# the broker password.
NODE_RED_TIMES = r"s/^([0-9]+)\.[0-9]+ .*: [0-9]{1,2} [A-Z][a-z]{2} ([0-9]{2}:[0-9]{2}:[0-9]{2}) - \[.*/\1 \2/p"
CLOCK_SLACK_SECONDS = 60
API_UP_SECONDS = 120  # nginx and tm-control back after a time zone change, before the zone is put back


def device_zone(host):
    return host.check_output("timedatectl show -p Timezone --value")


def other_zone(zone):
    """A test zone whose offset from UTC isn't zone's now, so a container still in zone shows in its log times."""
    now = datetime.now(UTC)
    offset = now.astimezone(ZoneInfo(zone)).utcoffset()
    return next(test_zone for test_zone in TEST_ZONES if now.astimezone(ZoneInfo(test_zone)).utcoffset() != offset)


def node_red_clock_offsets(host, invocation_id, zone):
    """For Node-RED's last log lines in this run of node-red-tm.service: how many seconds the time Node-RED wrote is
    from the journal's time for the line, read in zone."""
    assert INVOCATION_ID.fullmatch(invocation_id), "node-red-tm.service has no invocation ID"
    with host.sudo():
        output = host.check_output(f"journalctl _SYSTEMD_INVOCATION_ID={invocation_id} -o short-unix --no-pager "
                                   f"| sed -nE {shlex.quote(NODE_RED_TIMES)} | tail -n 5")
    offsets = []
    for line in output.splitlines():
        epoch, clock = line.split()
        journal = datetime.fromtimestamp(int(epoch), ZoneInfo(zone))
        hours, minutes, seconds = map(int, clock.split(":"))
        logged = hours * 3600 + minutes * 60 + seconds
        difference = logged - (journal.hour * 3600 + journal.minute * 60 + journal.second)
        offsets.append((difference + 43200) % 86400 - 43200)  # a line logged across midnight
    return offsets


def api_answers(host, address, timeout):
    """Whether tm-control answers through nginx within timeout seconds: all that a request to the API needs. The apps
    in the pod may still be down."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            if proxy_status(host, address, f"{API}/health") == "200":
                return True
        except RuntimeError:  # testinfra's SSH failure
            pass
        if time.monotonic() >= deadline:
            return False
        time.sleep(5)


def restore_zone(host, address, cookie, zone):
    """Put the device's time zone back through the API, as a person would, or, when that fails or the containers don't
    restart, with timedatectl and a restart of the containers. Only then wait for the whole stack: a container that
    didn't come back after the change mustn't keep the zone from being restored."""
    if device_zone(host) == zone:
        return
    restored = False
    if api_answers(host, address, API_UP_SECONDS):
        try:
            before = {unit: invocation(host, unit) for unit in ZONE_UNITS}
            status, _ = post_time(address, cookie, {"timezone": zone})
            if status == 200:
                restored = not not_restarted(host, before, UNIT_RESTART_SECONDS) and device_zone(host) == zone
        except Exception:  # anything that went wrong here: the fallback below does it instead
            restored = False
    if not restored:
        with host.sudo():
            host.check_output(f"timedatectl set-timezone {shlex.quote(zone)}")
            host.check_output("systemctl restart " + " ".join(ZONE_UNITS))
    assert device_zone(host) == zone, "the device's time zone wasn't restored; set it on the Date and time page"
    wait_until_ready(host, RESTART_TIMEOUT_SECONDS)


def test_timezone_change_restarts_the_containers(host, address, tm_login):
    """A new time zone from the Date and time page restarts the pod and nginx, so the containers see it: Node-RED's
    log times match the journal's, read in the new zone. The original zone is put back afterwards, which restarts
    them again."""
    cookie = session(address, *tm_login)
    original = device_zone(host)
    zone = other_zone(original)
    before = {unit: invocation(host, unit) for unit in [*ZONE_UNITS, "node-red-tm.service"]}
    try:
        status, result = post_time(address, cookie, {"timezone": zone})
        assert status == 200, f"POST {API}/time with the time zone {zone} answered {status}"
        restarting = result.get("restarting")
        assert sorted(restarting or []) == sorted(ZONE_UNITS), f"POST {API}/time's restarting is {restarting}"
        waiting = not_restarted(host, before, UNIT_RESTART_SECONDS)
        assert device_zone(host) == zone, f"timedatectl doesn't show {zone}"
        assert not waiting, f"{UNIT_RESTART_SECONDS} s after the time zone changed, {waiting} hadn't restarted"
        wait_until_ready(host, RESTART_TIMEOUT_SECONDS)
        offsets = node_red_clock_offsets(host, invocation(host, "node-red-tm.service"), zone)
        assert offsets, "Node-RED has logged no line with its own time since it restarted"
        assert all(abs(offset) <= CLOCK_SLACK_SECONDS for offset in offsets), (
            f"Node-RED's log times are {offsets} s from the journal's read in {zone}: its container is in another zone")
    finally:
        restore_zone(host, address, cookie, original)


TIME_AHEAD_SECONDS = 120
TIME_SLACK_SECONDS = 5
FEED_BACK_SECONDS = 90  # Frigate's restart, then its first frames from go2rtc


NTP_READ_SECONDS = 10


def iso(epoch):
    return datetime.fromtimestamp(epoch, UTC).isoformat()


def ntp_enabled(address, cookie):
    """Whether GET /time shows NTP on within NTP_READ_SECONDS."""
    deadline = time.monotonic() + NTP_READ_SECONDS
    while True:
        answer = request_from_this_machine(address, f"{API}/time", cookie=cookie)
        state = answer.json() if answer.status == 200 else None
        if isinstance(state, dict) and (state.get("ntp") or {}).get("enabled") is True:
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(2)


def test_set_time_from_the_api(host, address, expect, tm_login):
    """With NTP off, the time an admin sets from the browser becomes the device's. The test sets it 2 minutes ahead,
    which restarts Frigate, waits for the feed to be back, then sets it back, which restarts nothing, and turns NTP on
    again; a unit with a time source then resyncs."""
    if not expect["pii_free"]:
        pytest.skip("changes the device's clock; set tm_expect.pii_free: true (bench units only)")
    cookie = session(address, *tm_login)
    answer = request_from_this_machine(address, f"{API}/time", cookie=cookie)
    state = answer.json() if answer.status == 200 else None
    assert isinstance(state, dict), f"GET {API}/time answered {answer.status}"
    if (state.get("ntp") or {}).get("enabled") is not True:
        pytest.skip("NTP is off on this unit; the test turns it off and back on")
    moved = fell_back = False
    back = None  # the step back's restarting, when it answered 200
    try:
        status, _ = post_time(address, cookie, {"ntp": False})
        assert status == 200, f"POST {API}/time turning NTP off answered {status}"
        before = {"frigate.service": invocation(host, "frigate.service")}
        target = int(pi_now(host)) + TIME_AHEAD_SECONDS
        status, result = post_time(address, cookie, {"time": iso(target)})
        moved = status == 200
        assert status == 200, f"POST {API}/time with a time answered {status}"
        assert result.get("time_kept_from_ntp") is False, "with NTP off, the device kept its own time"
        off = pi_now(host) - target
        assert abs(off) <= TIME_SLACK_SECONDS, f"the Pi's clock is {off:.0f} s from the time that was set"
        assert result.get("restarting") == ["frigate.service"], "a 2-minute step ahead should restart Frigate"
        waiting = not_restarted(host, before, UNIT_RESTART_SECONDS)
        assert not waiting, f"{UNIT_RESTART_SECONDS} s after the clock moved ahead, frigate.service hadn't restarted"
        for check_id in ("apps.go2rtc.streams", "apps.frigate.cameras"):
            found = wait_for_check(address, cookie, check_id, "ok", FEED_BACK_SECONDS)
            assert found[0] == "ok", f"{check_id} {FEED_BACK_SECONDS} s after Frigate restarted: {found}"
    finally:
        # Each step runs even when the one before it fails. Whether NTP is back on is the Pi's word, not the API's.
        try:
            if moved:  # back to about the right time, for a unit without a time source
                status, result = post_time(address, cookie, {"time": iso(int(pi_now(host)) - TIME_AHEAD_SECONDS)})
                if status == 200:
                    back = result.get("restarting")
        finally:
            try:
                post_time(address, cookie, {"ntp": True})
            finally:
                if host.run("timedatectl show -p NTP --value").stdout.strip() != "yes":
                    with host.sudo():
                        host.check_output("timedatectl set-ntp true")
                    fell_back = True
    assert not fell_back, f"POST {API}/time didn't turn NTP back on; it was turned on with timedatectl"
    assert ntp_enabled(address, cookie), f"GET {API}/time doesn't show NTP on {NTP_READ_SECONDS} s after it was"
    assert back in (None, []), f"setting the clock back restarted {back}"


# Clears node-red-tm.service's ExecStartPre, which is only tmdb_migrate.py, for the next start, so Node-RED runs on a
# database that the migration hasn't brought up to date, as after a failed one. Without it, the migration would run again
# from version 0, fail on a migration that isn't idempotent (0002's ADD COLUMN), and Node-RED wouldn't start. So the test
# sets user_version back itself, and if it's cut off, that has to be done by hand.
SKIP_MIGRATION = "/run/systemd/system/node-red-tm.service.d/tmdev-skip-migration.conf"
SKIP_MIGRATION_CONF = "[Service]\nExecStartPre=\n"
NODE_RED_DB = "node-red-tm/db/tmdb.sqlite"
SET_USER_VERSION = ("import sqlite3, sys; con = sqlite3.connect(sys.argv[1], isolation_level=None); "
                    "con.execute('PRAGMA user_version = %d' % int(sys.argv[2])); con.close()")
SCHEMA_TIMEOUT_SECONDS = 180  # Node-RED's start, then its first status
STATUS_POLL_SECONDS = 6  # GET /status is cached for 5 seconds


def set_user_version(host, codeowner, codedir, version):
    """Set tmdb.sqlite's user_version as the code owner, who owns it. Only while node-red-tm.service is stopped."""
    host.check_output(f"sudo -n runuser -u {shlex.quote(codeowner)} -- python3 -c {shlex.quote(SET_USER_VERSION)} "
                      f"{shlex.quote(f'{codedir}/{NODE_RED_DB}')} {int(version)}")


def wait_for_check(address, cookie, check_id, wanted, timeout):
    """Read the status report until check_id has the status wanted, for at most timeout seconds; its last
    (status, detail)."""
    deadline = time.monotonic() + timeout
    while True:
        found = status_checks(address, cookie).get(check_id, ("missing", None))
        if found[0] == wanted or time.monotonic() >= deadline:
            return found
        time.sleep(STATUS_POLL_SECONDS)


def test_schema_behind_shows_an_error(host, address, expect, codedir, codeowner, tm_login):
    """While Node-RED runs on a database whose schema is behind this install's migrations, the status page's schema
    check is an error that points to the migration's journal lines. Sets tmdb.sqlite's user_version to 0 with Node-RED
    stopped, starts it once without the migration, and puts both back afterwards."""
    if not expect["pii_free"]:
        pytest.skip("writes the schema version of the Pi's tmdb.sqlite; set tm_expect.pii_free: true "
                    "(bench units only)")
    cookie = session(address, *tm_login)
    before = status_checks(address, cookie).get("apps.nodered.schema")
    assert before and before[0] == "ok", f"apps.nodered.schema before the test: {before}"
    pre = host.check_output("systemctl show -p ExecStartPre --value node-red-tm.service")
    only_migration = pre.count("path=") == 1 and "tmdb_migrate.py" in pre
    assert only_migration, "node-red-tm.service's ExecStartPre isn't only tmdb_migrate.py; the drop-in would skip more"
    original = None
    try:
        with host.sudo():
            host.check_output("systemctl stop node-red-tm.service")
        original = db_query(host, codedir, "PRAGMA user_version")[0][0]
        set_user_version(host, codeowner, codedir, 0)
        with host.sudo():
            host.check_output(f"mkdir -p {SKIP_MIGRATION.rsplit('/', 1)[0]} "
                              f"&& printf %s {shlex.quote(SKIP_MIGRATION_CONF)} > {SKIP_MIGRATION} "
                              "&& systemctl daemon-reload && systemctl start node-red-tm.service")
        behind = wait_for_check(address, cookie, "apps.nodered.schema", "error", SCHEMA_TIMEOUT_SECONDS)
    finally:
        # Each step runs even when the one before it fails, and each is safe to run twice, so a setup that failed
        # partway is still undone. The migration can't bring user_version back: from 0 it would fail on 0002.
        try:
            with host.sudo():
                host.check_output("systemctl stop node-red-tm.service")
            if original is not None:
                set_user_version(host, codeowner, codedir, original)
        finally:
            try:
                with host.sudo():
                    host.check_output(f"rm -f {SKIP_MIGRATION} && systemctl daemon-reload")
            finally:
                with host.sudo():
                    host.check_output("systemctl start node-red-tm.service")
                wait_until_ready(host, RESTART_TIMEOUT_SECONDS)
    assert behind[0] == "error" and "journalctl" in (behind[1] or ""), (
        f"apps.nodered.schema with user_version 0: {behind}")
    after = wait_for_check(address, cookie, "apps.nodered.schema", "ok", SCHEMA_TIMEOUT_SECONDS)
    assert after[0] == "ok", f"apps.nodered.schema after user_version was put back: {after}"


def boot_id(host):
    """This boot's id, or None while the Pi doesn't answer over SSH."""
    try:
        result = host.run("cat /proc/sys/kernel/random/boot_id")
    except RuntimeError:  # testinfra's SSH failure while the Pi reboots
        return None
    return result.stdout.strip() if result.rc == 0 else None


# Last in the module: it reboots the Pi.
def test_reboot_from_the_control_app(host, address, tm_login):
    """Reboots the Pi. An admin's reboot from the Device page goes through polkit, and the stack comes back without
    tm-control or nginx restarting after a failure."""
    cookie = session(address, *tm_login)
    before = boot_id(host)
    assert before, "couldn't read the Pi's boot id"
    answer = request_from_this_machine(address, f"{API}/system/reboot", "POST", cookie, {})
    if answer.status == 409:
        pytest.fail("tm-control answered 409: logind won't reboot now. Something may be holding it off, such as an "
                    "update (systemd-inhibit --list on the Pi), or polkit doesn't allow it "
                    "(test_polkit_allows_only_the_listed_actions)", pytrace=False)
    assert answer.status == 202, f"POST {API}/system/reboot answered {answer.status}"
    deadline = time.monotonic() + REBOOT_TIMEOUT_SECONDS
    while boot_id(host) in (before, None):
        assert time.monotonic() < deadline, (
            f"the Pi didn't reboot and come back within {REBOOT_TIMEOUT_SECONDS // 60} minutes")
        time.sleep(10)
    wait_until_ready(host, REBOOT_TIMEOUT_SECONDS)
    restarts = {unit: host.check_output(f"systemctl show -p NRestarts --value {unit}")
                for unit in ("tm-control.service", "revproxy.service")}
    assert restarts == dict.fromkeys(restarts, "0"), f"restarts after failures since the reboot: {restarts}"
