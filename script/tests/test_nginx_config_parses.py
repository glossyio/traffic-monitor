"""Render the reverse proxy's whole config with the role's variables and run nginx -t on it in the pinned image.

The same check tmsetup runs on the device before it deploys the config, so a named location in the wrong context or
a duplicate location fails here first. Skipped without Podman.
"""

import re
import shutil
import subprocess

import pytest
from tmsetup_render import load_role_yaml, render

ROLE_VARS = {**load_role_yaml("defaults/main.yml"), **load_role_yaml("vars/main.yml")}


def render_config(root):
    """Lay the rendered files out like {{ tmsetup_codedir }}/revproxy on the device."""
    files = (["nginx.conf"]
             + [f"tm/snippets/{name}" for name in ROLE_VARS["tmsetup_revproxy_snippets"]]
             + [f"tm/locations/{name}" for name in ROLE_VARS["tmsetup_revproxy_locations"]])
    for name in files:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render(f"container/revproxy/{name}.j2", **ROLE_VARS))


def have_image(image):
    """True if Podman has the image, or can pull it once."""
    if subprocess.run(["podman", "image", "exists", image], capture_output=True).returncode == 0:
        return True
    try:
        return subprocess.run(["podman", "pull", "--quiet", image], capture_output=True, timeout=300).returncode == 0
    except subprocess.TimeoutExpired:
        return False


@pytest.mark.skipif(shutil.which("podman") is None, reason="needs Podman")
def test_rendered_config_passes_nginx_t(tmp_path):
    image = f"docker.io/library/nginx:{ROLE_VARS['tmsetup_nginx_version']}"
    if not have_image(image):
        pytest.skip(f"{image} is neither cached nor pullable")
    render_config(tmp_path)
    volumes = [arg for mount in ROLE_VARS["tmsetup_revproxy_config_mounts"]
               for arg in ("-v", f"{tmp_path / mount['path']}:{mount['target']}:ro,Z")]
    # Like tmsetup's check: nginx as the entrypoint, so the image's startup scripts don't run
    result = subprocess.run(["podman", "run", "--rm", "--entrypoint", "nginx", *volumes, image, "-t"],
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    assert "syntax is ok" in result.stderr


def test_nr_tm_internal_is_denied(tmp_path):
    """Review Focus 5: Node-RED's internal endpoints are for tm-control on loopback, so /nr/ never proxies them, even
    for an admin. The whole config, this block included, passes nginx -t in test_rendered_config_passes_nginx_t."""
    render_config(tmp_path)
    conf = (tmp_path / "tm/locations/nodered.conf").read_text().splitlines()
    assert "location ^~ /nr/tm-internal/ { return 404; }" in conf
    # Node-RED's routes ignore case, so a case variant would otherwise reach it through location /nr/
    assert 'location ~* "^/nr/tm-internal(/|$)" { return 404; }' in conf
    pattern = re.compile(r"^/nr/tm-internal(/|$)", re.IGNORECASE)
    for path in ("/nr/TM-Internal/status", "/nr/tm-INTERNAL/", "/nr/Tm-Internal"):
        assert pattern.search(path), path
    for path in ("/nr/", "/nr/flows", "/nr/tm-internals", "/tm-internal/status"):
        assert not pattern.search(path), path
