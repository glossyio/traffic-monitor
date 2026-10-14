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
