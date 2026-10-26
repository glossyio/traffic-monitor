"""Recovery: the stack comes back after a restart and after a reboot.

These stop the pod or the whole Pi, so they run only with tmdev.py test --disruptive.
"""

import time

import pytest
from devpi_checks import RESTARTING_UNITS

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
