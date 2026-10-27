"""Render tmsetup templates and check what the device gets. Off-device; no Ansible run needed."""

from tmsetup_render import load_role_yaml, render

LOCATIONS = load_role_yaml("vars/main.yml")["tmsetup_revproxy_locations"]


def location(name):
    return render(f"container/revproxy/tm/locations/{name}.j2")


def test_data_export_downloads_are_proxied_to_node_red():
    """ui-database's download links are root-relative (/storefiles?files=...), so they need their own location (#211)."""
    assert "storefiles.conf" in LOCATIONS
    conf = location("storefiles.conf")
    assert "location /storefiles {" in conf
    assert "proxy_pass http://127.0.0.1:1880;" in conf
    assert "proxy_buffering off;" in conf


def published_ports(unit_text):
    return [line.split("=", 1)[1] for line in unit_text.splitlines() if line.startswith("PublishPort=")]


def test_pod_publishes_app_ports_on_loopback_only():
    pod = render("container/traffic-monitor.pod.j2", tmsetup_mqtt_lan_open=False)
    assert published_ports(pod) == [
        "127.0.0.1:1880:1880",
        "127.0.0.1:1883:1883",
        "127.0.0.1:5000:5000",
        "127.0.0.1:8971:8971",
    ]


def test_pod_opens_mqtt_to_the_network_only_with_a_broker_login():
    # Task 10 sets tmsetup_mqtt_lan_open when node-red-tm.env has a broker login
    pod = render("container/traffic-monitor.pod.j2", tmsetup_mqtt_lan_open=True)
    assert "1883:1883" in published_ports(pod)
    assert "127.0.0.1:1883:1883" not in published_ports(pod)
