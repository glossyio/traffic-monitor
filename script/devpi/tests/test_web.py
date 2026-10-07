"""The reverse proxy and the apps behind it answer, on the Pi and from this machine."""

import re
import shlex
import urllib.request

import pytest

# Prefix locations from `nginx -T`; exact (=), regex (~), and named (@) locations are skipped,
# since those are error pages and internal routes rather than apps.
LOCATION = re.compile(r"^\s*location\s+(?:\^~\s*)?(/\S*)\s*\{", re.MULTILINE)
DIRECT_PORTS = [(1880, "/"), (5000, "/api/version"), (1984, "/api/streams")]


def http_status(host, url, host_header=None):
    header = f"-H {shlex.quote('Host: ' + host_header)} " if host_header else ""
    return host.check_output(f"curl -s -o /dev/null -w '%{{http_code}}' --max-time 10 {header}{url}")


def test_nginx_config_valid(host):
    with host.sudo():
        result = host.run("podman exec revproxy nginx -t")
    assert result.rc == 0, result.stderr.strip()


def test_proxied_locations_respond(host, hostvars):
    """Every location the running proxy serves answers without a 404, a 5xx, or a timeout.

    Requests carry the Pi's address as Host, as a browser's would. With Host: localhost, the
    nginx image's stock default.conf (server_name localhost) would answer instead.
    """
    with host.sudo():
        config = host.check_output("podman exec revproxy nginx -T 2>/dev/null")
    locations = sorted(set(LOCATION.findall(config)))
    assert "/" in locations, f"no 'location /' in the running config; found {locations}"
    address = hostvars.get("ansible_host", host.backend.hostname)
    statuses = {path: http_status(host, f"http://localhost{path}", address) for path in locations}
    failing = {path: code for path, code in statuses.items() if code in ("000", "404") or code.startswith("5")}
    assert not failing, f"proxied paths failing: {failing} (all: {statuses})"


@pytest.mark.parametrize("port, path", DIRECT_PORTS)
def test_direct_port_responds(host, port, path):
    code = http_status(host, f"http://localhost:{port}{path}")
    assert code == "200", f"http://localhost:{port}{path} returned {code}"


def test_home_page_reachable_from_this_machine(host, hostvars):
    address = hostvars.get("ansible_host", host.backend.hostname)
    with urllib.request.urlopen(f"http://{address}/", timeout=10) as response:
        assert response.status == 200
