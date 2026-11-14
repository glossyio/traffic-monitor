"""The home button's script line, checked through the rendered reverse proxy running in the pinned nginx image.

Two containers share one network namespace: a stub that plays tm-control's verify and every app (it compresses
whatever it is allowed to), and the real config in front of it. Skipped without Podman or the image (a failure in CI:
required_tools.py).
"""

import os
import shutil
import subprocess
from collections import namedtuple

import pytest

from required_tools import missing_tool
from test_nginx_config_parses import ROLE_VARS, have_image, render_config

LINE = '<script src="/home-button.js" defer></script></head>'
PAGE = {"Accept": "text/html,application/xhtml+xml", "Accept-Encoding": "gzip, deflate"}

STUB_CONF = """
events {}
http {
    include /etc/nginx/mime.types;
    server {  # tm-control's verify: always an administrator
        listen 127.0.0.1:%(control_port)s;
        location / { add_header X-TM-User tester always; add_header X-TM-Role admin always; return 200; }
    }
    server {  # every app: compresses whatever it is allowed to
        listen 127.0.0.1:1880; listen 127.0.0.1:8971; listen 127.0.0.1:1984;
        gzip on; gzip_min_length 1; gzip_proxied any; gzip_http_version 1.0;
        gzip_types application/javascript text/javascript;
        root /srv;
        add_header X-Saw-Accept-Encoding "[$http_accept_encoding]" always;
        location / { try_files $uri /index.html; }
    }
}
"""

Answer = namedtuple("Answer", "status headers body")


class Proxy:
    def __init__(self, stub):
        self.stub = stub

    def get(self, path, headers):
        """GET path on the proxy's port 80 with these request headers; the body is text unless it is compressed."""
        command = ["podman", "exec", self.stub, "curl", "-s", "-i", "http://127.0.0.1:80" + path]
        for name, value in headers.items():
            command += ["-H", f"{name}: {value}"]
        raw = subprocess.run(command, capture_output=True, timeout=60, check=True).stdout
        head, _, body = raw.partition(b"\r\n\r\n")
        lines = head.decode("latin-1").split("\r\n")
        answer_headers = {}
        for line in lines[1:]:
            name, _, value = line.partition(":")
            answer_headers[name.lower()] = value.strip()
        compressed = "content-encoding" in answer_headers
        return Answer(int(lines[0].split()[1]), answer_headers, "" if compressed else body.decode("utf-8", "replace"))


@pytest.fixture(scope="module")
def proxy(tmp_path_factory):
    if shutil.which("podman") is None:
        missing_tool("needs Podman")
    image = f"docker.io/library/nginx:{ROLE_VARS['tmsetup_nginx_version']}"
    if not have_image(image):
        missing_tool(f"{image} is neither cached nor pullable")
    root = tmp_path_factory.mktemp("home-button")
    root.chmod(0o755)  # the containers' nginx workers aren't the owner
    config = root / "config"
    config.mkdir(mode=0o755)
    render_config(config)
    for path in [config, *config.rglob("*")]:
        path.chmod(0o755 if path.is_dir() else 0o644)
    srv = root / "srv"
    srv.mkdir(mode=0o755)
    (srv / "index.html").write_text("<html><head><title>App</title></head><body>An app's page</body></html>")
    (srv / "app.js").write_text("console.log('an app script');" * 20)
    stub_conf = root / "stub.conf"
    stub_conf.write_text(STUB_CONF % {"control_port": ROLE_VARS["tmsetup_tm_control_port"]})
    for path in (srv / "index.html", srv / "app.js", stub_conf):
        path.chmod(0o644)

    stub, front = f"tm-home-button-stub-{os.getpid()}", f"tm-home-button-proxy-{os.getpid()}"
    nginx = ["--entrypoint", "nginx"]
    daemon_off = [image, "-g", "daemon off;"]
    try:
        subprocess.run(["podman", "run", "-d", "--name", stub, *nginx,
                        "-v", f"{stub_conf}:/etc/nginx/nginx.conf:ro,Z", "-v", f"{srv}:/srv:ro,Z", *daemon_off],
                       capture_output=True, text=True, timeout=120, check=True)
        mounts = [arg for mount in ROLE_VARS["tmsetup_revproxy_config_mounts"]
                  for arg in ("-v", f"{config / mount['path']}:{mount['target']}:ro,Z")]
        subprocess.run(["podman", "run", "-d", "--name", front, "--network", f"container:{stub}", *nginx,
                        *mounts, *daemon_off],
                       capture_output=True, text=True, timeout=120, check=True)
        yield Proxy(stub)
    finally:
        # The proxy first: it uses the stub's network namespace, so the stub can't go while it is there
        for name in (front, stub):
            subprocess.run(["podman", "rm", "-f", "-t", "0", name], capture_output=True, timeout=120)


@pytest.mark.parametrize("path", ["/dashboard/", "/frigate/", "/ui/", "/nr/", "/feeds/"])
def test_a_page_load_gets_the_script_line_once(proxy, path):
    answer = proxy.get(path, PAGE)
    assert answer.status == 200
    assert answer.headers.get("x-saw-accept-encoding") == "[]"  # the app was asked for plain text
    assert "content-encoding" not in answer.headers
    assert answer.body.count(LINE) == 1


def test_a_script_stays_compressed_and_untouched(proxy):
    answer = proxy.get("/frigate/app.js", {"Accept": "*/*", "Accept-Encoding": "gzip"})
    assert answer.headers.get("x-saw-accept-encoding") == "[gzip]"
    assert answer.headers.get("content-encoding") == "gzip"


def test_a_page_fetched_as_data_is_left_alone(proxy):
    answer = proxy.get("/frigate/", {"Accept": "*/*", "Accept-Encoding": "gzip"})
    assert answer.headers.get("content-encoding") == "gzip"


def test_downloads_never_get_the_script_line(proxy):
    assert LINE not in proxy.get("/storefiles?files=x", PAGE).body
