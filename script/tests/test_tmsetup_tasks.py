"""Checks on the tmsetup role's task and handler files that guard against upgrade mistakes."""

from tmsetup_render import load_role_yaml


def test_revproxy_restarts_after_the_pod_so_port_80_is_free():
    names = [handler["name"] for handler in load_role_yaml("handlers/main.yml")]
    assert names.index("Restart revproxy.service") > names.index("Restart traffic-monitor.service")


def test_start_services_starts_the_reverse_proxy_after_the_pod():
    start = next(
        task for task in load_role_yaml("tasks/start_services.yml")
        if task["name"] == "TMSetup - Start Services - Start and enable traffic-monitor services"
    )
    assert start["loop"].index("revproxy.service") > start["loop"].index("traffic-monitor.service")
