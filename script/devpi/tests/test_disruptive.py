"""Recovery: the stack comes back after a restart and after a reboot; the login fails closed and can be reset.

These stop services, reboot the Pi, or reset the unit's tm-control accounts, so they run only with
tmdev.py test --disruptive.
"""

import re
import shlex
import time

import pytest
from devpi_checks import (API, RESTARTING_UNITS, Redacted, find_hevc_decoder, frigate_host_devices,
                          request_from_this_machine, role_vars, session, tm_login_or_none)

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
