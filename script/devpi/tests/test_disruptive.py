"""Recovery: the stack comes back after a restart and after a reboot.

These stop the pod or the whole Pi, so they run only with tmdev.py test --disruptive.
"""

import time

import pytest

pytestmark = pytest.mark.disruptive

UNITS = ["go2rtc_server.service", "traffic-monitor.service", "frigate.service", "node-red-tm.service",
         "revproxy.service"]
# Answers with plain text (the version), so only the HTTP status is checked.
FRIGATE_UP = "curl -fsS -o /dev/null --max-time 10 http://localhost:5000/api/version"
RESTART_TIMEOUT_SECONDS = 5 * 60
REBOOT_TIMEOUT_SECONDS = 10 * 60


def not_ready(host):
    """What isn't back yet, or an empty list once every unit is active and Frigate's API answers."""
    try:
        waiting = [unit for unit in UNITS if host.run(f"systemctl is-active {unit}").stdout.strip() != "active"]
        if not waiting and host.run(FRIGATE_UP).rc != 0:
            waiting = ["Frigate API on port 5000"]
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
