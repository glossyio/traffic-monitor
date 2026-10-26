"""Recovery: the stack comes back after a restart and after a reboot.

These stop the pod or the whole Pi, so they run only with tmdev.py test --disruptive.
"""

import time

import pytest
from devpi_checks import RESTARTING_UNITS, find_hevc_decoder, frigate_host_devices, role_vars

pytestmark = pytest.mark.disruptive

# A unit is active before its app answers; node-red-tm runs tmdb_migrate.py and then boots Node-RED.
# Only the HTTP status is checked.
APPS_UP = [
    ("Frigate API on port 5000", "curl -fsS -o /dev/null --max-time 10 http://localhost:5000/api/version"),
    ("Node-RED on port 1880", "curl -fsS -o /dev/null --max-time 10 http://localhost:1880/"),
    ("nginx on port 80", "curl -fsS -o /dev/null --max-time 10 http://localhost/"),
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
        # go2rtc's rpicam-vid holds the ISP; Frigate holds the decoder.
        host.check_output("systemctl stop frigate.service go2rtc_server.service")
        # The minors these two drivers hold; the camera front end keeps its own and isn't touched.
        # testinfra runs sudo commands with /bin/sh, which has no brace expansion, so both paths are spelled out.
        freed = sorted(int(line.split(":")[1]) for line in host.check_output(
            "cat /sys/bus/platform/devices/1000800000.codec/media*/dev"
            " /sys/bus/platform/devices/1000880000.pisp_be/media*/dev").splitlines())
        decoder_minor = int(host.check_output("cat /sys/bus/platform/devices/1000800000.codec/media*/dev").split(":")[1])
        try:
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
