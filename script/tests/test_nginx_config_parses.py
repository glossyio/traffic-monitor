"""Render the reverse proxy's whole config with the role's variables and run nginx -t on it in the pinned image.

The same check tmsetup runs on the device before it deploys the config, so a named location in the wrong context or
a duplicate location fails here first. Skipped without Podman or the image (a failure in CI: required_tools.py).
"""

import re
import subprocess

from required_tools import missing_tool, needs
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
        path.write_text(render(f"container/revproxy/{name}.j2", ansible_facts={"hostname": "tm-ab12"}, **ROLE_VARS))


def have_image(image):
    """True if Podman has the image, or can pull it once."""
    if subprocess.run(["podman", "image", "exists", image], capture_output=True).returncode == 0:
        return True
    try:
        return subprocess.run(["podman", "pull", "--quiet", image], capture_output=True, timeout=300).returncode == 0
    except subprocess.TimeoutExpired:
        return False


@needs("podman", "needs Podman")
def test_rendered_config_passes_nginx_t(tmp_path):
    image = f"docker.io/library/nginx:{ROLE_VARS['tmsetup_nginx_version']}"
    if not have_image(image):
        missing_tool(f"{image} is neither cached nor pullable")
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


def mime_lines(tmp_path):
    """The rendered nginx.conf's lines from the mime.types include to its default_type."""
    render_config(tmp_path)
    text = (tmp_path / "nginx.conf").read_text()
    match = re.search(r"^ *include +/etc/nginx/mime\.types;.*?^ *default_type .*?;$", text, re.MULTILINE | re.DOTALL)
    assert match, "no mime.types include in nginx.conf"
    return match.group(0)


def test_mjs_is_added_after_the_included_mime_types(tmp_path):
    """nginx's mime.types has no .mjs, and the Location page's map runs its worker from one: a browser refuses a
    module script that isn't JavaScript. The types block comes after the include, so it adds to it."""
    lines = mime_lines(tmp_path)
    assert re.search(r"types\s*\{\s*text/javascript\s+mjs;\s*\}", lines)
    assert lines.index("mime.types") < lines.index("text/javascript mjs;")


@needs("podman", "needs Podman")
def test_mjs_and_js_are_both_served_as_javascript(tmp_path):
    """Run the pinned image on the rendered mime lines and ask for a .mjs, a .js, and a .css file."""
    image = f"docker.io/library/nginx:{ROLE_VARS['tmsetup_nginx_version']}"
    if not have_image(image):
        missing_tool(f"{image} is neither cached nor pullable")
    lines = mime_lines(tmp_path / "rendered")
    site = tmp_path / "site"
    site.mkdir()
    for name in ("a.mjs", "b.js", "c.css"):
        (site / name).write_text("x\n")
    (tmp_path / "n.conf").write_text(
        f"events {{}}\nhttp {{\n{lines}\naccess_log off;\nserver {{ listen 8089; root /srv; }}\n}}\n")
    (tmp_path / "probe.sh").write_text(
        "nginx -c /tmp/n.conf\nsleep 1\n"
        "for f in a.mjs b.js c.css; do echo \"$f $(curl -sI http://127.0.0.1:8089/$f | grep -i '^content-type')\"; done\n")
    result = subprocess.run(
        ["podman", "run", "--rm", "--entrypoint", "sh",
         "-v", f"{tmp_path / 'n.conf'}:/tmp/n.conf:ro,Z", "-v", f"{site}:/srv:ro,Z",
         "-v", f"{tmp_path / 'probe.sh'}:/tmp/probe.sh:ro,Z", image, "/tmp/probe.sh"],
        capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    types = {line.split()[0]: line.split(": ", 1)[1].strip() for line in result.stdout.splitlines()}
    assert types["a.mjs"] == "text/javascript"
    assert types["b.js"] in ("text/javascript", "application/javascript")  # js still maps, after the new block
    assert types["c.css"] == "text/css"
