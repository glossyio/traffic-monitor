# tm-control M1 (Edge and Ports) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make nginx the only web service listening on the LAN. Every app port moves to loopback, go2rtc's API and stream editing are closed off, and the camera stream requires credentials. Logins don't change yet.

**Architecture:**
- The `revproxy` container leaves the pod and runs on the host network, still proxying to `127.0.0.1:<port>`.
- The pod publishes its ports on `127.0.0.1` only.
- go2rtc's API binds to loopback, its RTSP server requires a generated password, and nginx forwards only go2rtc's viewing paths.
- Existing devices are brought up to date by `tm-control migrate`, a small Python command (the first piece of the tm-control backend). It edits Frigate's `config.yml` round-trip, keeping comments.

**Tech Stack:** Ansible (tmsetup role), Podman Quadlet, nginx, go2rtc 1.8.5, Python 3.11+ with ruamel.yaml 0.19.1, pytest.

**Spec:** `design/specs/2026-10-02-tm-control-platform-design.md`, section "Milestones → M1". Read it with this plan.

## Global Constraints

**Logins stay as they are.** M1 changes no logins: `/frigate/` keeps proxying to `127.0.0.1:5000`, and the Node-RED editor keeps its own login. Both change in M2.

**Python**
- Runs on Python 3.11 and newer: the device runs 3.13 on Raspberry Pi OS Trixie, and the dev venv may be 3.11 or 3.12. Don't use syntax newer than 3.11.
- The only runtime dependency is `ruamel.yaml==0.19.1`. It's pure Python, so nothing compiles on the device.

**Who owns what on the device**
- Root may run tm-control code (M2 adds `sudo tm-control …`), so that code lives only under root-owned paths: `/usr/local/lib/traffic-monitor/tm-control` and `/usr/local/bin/tm-control`. It never goes under `{{ tmsetup_codedir }}`, because the code owner can write there.
- Secrets live in `/etc/traffic-monitor/secrets/`: the directory is `root:{{ tmsetup_codegroup }}` 0750 and files are 0640.
  - They're generated on the device, never committed, and never printed. Every Ansible task that handles a secret value sets `no_log: true`, or `diff: false` for templates.
  - `tmsetup.sh` copies all output into `~/tmsetup-*.log`.
- New Frigate variables are `FRIGATE_GO2RTC_RTSP_USER` and `FRIGATE_GO2RTC_RTSP_PASSWORD`. The spec was updated to these names. Don't reuse `FRIGATE_RTSP_PASSWORD`: Frigate's docs use it for people's own IP cameras.

**Conventions**
- **Ansible:**
  - task names `TMSetup - <Component> - <Action>`, with FQCN modules
  - `become: true` per task
  - registered results end in `_register`, and role variables start with `tmsetup_`
  - YAML indented with 2 spaces
- **Python:** indented with 4 spaces, with a docstring for each module. No AI-provenance comments.
- **Tests:**
  - Synthetic data only.
  - Test module basenames must be unique across the repo, because pytest's default import mode needs it.
  - Don't name new helper modules `helpers.py`, and don't `import conftest`.
- **Docs:** user docs under `docs/` use GitBook markdown. Design docs live under `design/`.
- **Commits:**
  - Commit one per task.
  - End each message with CLAUDE.md's trailer block, not `Co-Authored-By`:
    ```text
    Assisted-by: Claude Code <version from `claude --version`> (<interface: CLI, VS Code, JetBrains, desktop app, or web>)
    AI-Model: <model name> (<model id>)
    AI-Effort: <effort level>
    AI-Role: drafted
    ```
    If you don't know the interface or effort level, ask the person; don't guess.

**Running the checks**
- All checks run from the repo root in the dev venv (`.venv`, from `script/requirements-dev`).
- For Ansible, use `</dev/null` and send output to a file, as CLAUDE.md describes.

## Review Focus

These are the five likeliest failures for a person upgrading or using a device. Each one has a test in the task that owns it.

1. **Upgrading a device that already has `frigate.env` and Frigate's `config.yml`.** tmsetup doesn't overwrite these files without `-f`. After the upgrade, Frigate must still read the camera. Tests in Task 7: the migration produces exactly the URL that new installs get, and `frigate.env` gains both credential lines.
2. **Re-running `tmsetup.sh`.** The generated secrets must never be regenerated, because the go2rtc and Frigate sides would drift apart. They must never appear in the install log. Tests in Task 3.
3. **The reverse proxy restarting during the upgrade while the old pod still holds port 80.** nginx must come up once the pod releases the port. Tests in Task 2 check the handler order and that the unit keeps retrying.
4. **Crafted `/feeds/` requests.** These must get 403:
   - methods other than GET
   - `src=` values that are URLs or `exec:` sources, raw or percent-encoded
   - go2rtc API paths outside the viewing set (`config`, `log`, `exit`, `restart`, `webrtc`, bare `api`)

   Tests in Task 2.
5. **A hand-edited Frigate config that reads go2rtc by LAN IP instead of `host.containers.internal`.** The migration can't rewrite it, so it must warn loudly instead of silently leaving the camera dark. Test in Task 5.

---

### Task 0: Branch and design docs

**Files:**
- Add: `design/specs/2026-10-02-tm-control-platform-design.md` and this plan. They already exist, untracked.

- [ ] **Step 1: Pick the base branch**

M1 edits `CLAUDE.md` and `script/requirements-dev`, which so far exist only on `feature/ai-use-policy` and the tmdb schema branches (`refactor/tmdb-schema-migrations/mz`, `refactor/tmdb-schema-activate/mz`). Check whether they've been merged into `dev`:

```bash
git fetch origin
git ls-tree --name-only origin/dev | grep -E '^(CLAUDE.md|script)$'
git ls-tree --name-only origin/dev script/ | grep requirements-dev
```

- **Both are present:** base on `origin/dev`.
- **Otherwise:** base on `origin/refactor/tmdb-schema-activate/mz`, which contains both, and rebase onto `dev` after those branches merge. Tell the person which base you used.

- [ ] **Step 2: Create the branch and commit the design docs**

```bash
git switch -c feature/edge-ports/201 <base from step 1>
git add design/specs/2026-10-02-tm-control-platform-design.md design/plans/2026-10-02-tm-control-m1-edge-and-ports.md
git commit -m "Add tm-control platform spec and M1 plan" -m "<trailer block>"
```

If the untracked files don't come along when you switch branches, copy them from the original checkout first.

---

### Task 1: Template test harness, pod ports on loopback, opt-in LAN MQTT

**Files:**
- Create: `script/tests/tmsetup_render.py`
- Create: `script/tests/test_tmsetup_templates.py`
- Modify: `container/traffic-monitor.pod.j2`
- Modify: `script/ansible/roles/tmsetup/defaults/main.yml` (after `tmsetup_bool_plate_recognizer: false`)
- Modify: `script/tmsetup.sh` (`_VALID_CUSTOM_VARS` and the `-C` error message)

**Interfaces:**
- Produces, in `script/tests/tmsetup_render.py`:
  - `render(template: str, **variables) -> str`: renders a template given as a repo-relative path, like Ansible's template module.
  - `load_role_yaml(relative_path: str)`: loads a YAML file under `script/ansible/roles/tmsetup/`.
  - `resolve(value, variables)`: fills `{{ }}` expressions in loaded vars.
  - `proxies() -> list[dict]`: `tmsetup_proxies`, resolved.
- Produces the install variable `tmsetup_bool_mqtt_lan`, set with `tmsetup.sh -C mqtt_lan`.

- [ ] **Step 1: Write the render helper**

`script/tests/tmsetup_render.py`:

```python
"""Render tmsetup role templates the way Ansible's template module does, so tests can check them off-device.

Uses Jinja2 with Ansible's filters, Ansible's trim_blocks default, and StrictUndefined, so a template
that needs a variable the test didn't pass fails loudly. Jinja's own `default`/`d` are kept because
ansible-core 2.19+ replaces them with versions that don't recognize plain Jinja undefined values.
"""

from pathlib import Path

import jinja2
import yaml
from ansible.plugins.filter.core import FilterModule

REPO = Path(__file__).resolve().parents[2]
ROLE = REPO / "script" / "ansible" / "roles" / "tmsetup"


def _environment():
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(REPO)),
        undefined=jinja2.StrictUndefined,
        trim_blocks=True,
        keep_trailing_newline=True,
    )
    env.filters.update({name: f for name, f in FilterModule().filters().items() if name not in ("default", "d")})
    return env


def render(template, **variables):
    """Render a template given by its path relative to the repo root."""
    return _environment().get_template(template).render(**variables)


def load_role_yaml(relative_path):
    """Load a YAML file from the tmsetup role, e.g. 'vars/main.yml' or 'tasks/secrets.yml'."""
    return yaml.safe_load((ROLE / relative_path).read_text())


def resolve(value, variables):
    """Fill in the {{ }} expressions inside a loaded vars value, as Ansible does when the var is used."""
    if isinstance(value, str):
        return _environment().from_string(value).render(**variables)
    if isinstance(value, list):
        return [resolve(item, variables) for item in value]
    if isinstance(value, dict):
        return {key: resolve(item, variables) for key, item in value.items()}
    return value


def proxies():
    """tmsetup_proxies from vars/revproxy_vars.yml, with its variables filled in from vars/main.yml."""
    role_vars = load_role_yaml("vars/main.yml")
    return resolve(load_role_yaml("vars/revproxy_vars.yml")["tmsetup_proxies"], role_vars)
```

- [ ] **Step 2: Write the failing pod tests**

`script/tests/test_tmsetup_templates.py`:

```python
"""Render tmsetup templates and check what the device gets. Off-device; no Ansible run needed."""

from tmsetup_render import render


def published_ports(unit_text):
    return [line.split("=", 1)[1] for line in unit_text.splitlines() if line.startswith("PublishPort=")]


def test_pod_publishes_app_ports_on_loopback_only():
    pod = render("container/traffic-monitor.pod.j2", tmsetup_bool_mqtt_lan=False)
    assert published_ports(pod) == [
        "127.0.0.1:1880:1880",
        "127.0.0.1:1883:1883",
        "127.0.0.1:5000:5000",
        "127.0.0.1:8971:8971",
    ]


def test_pod_opens_mqtt_to_the_network_only_when_opted_in():
    # tmsetup.sh -C mqtt_lan passes the string "true"
    pod = render("container/traffic-monitor.pod.j2", tmsetup_bool_mqtt_lan="true")
    assert "1883:1883" in published_ports(pod)
    assert "127.0.0.1:1883:1883" not in published_ports(pod)
```

- [ ] **Step 3: Run the tests to check they fail**

Run: `.venv/bin/python -m pytest script/tests/test_tmsetup_templates.py -v`

Expected: both FAIL, because the current pod publishes `1880:1880`, `1964:1984`, `80:80`, and so on.

- [ ] **Step 4: Bind the pod's ports to loopback**

In `container/traffic-monitor.pod.j2`, replace the ten `PublishPort=` lines (from `PublishPort=1880:1880` through `PublishPort=80:80`) with:

```
# Published on 127.0.0.1 only: the reverse proxy (host network) and host services reach these,
# the LAN doesn't. Every app is served to the network by the reverse proxy on port 80.
PublishPort=127.0.0.1:1880:1880
{% if tmsetup_bool_mqtt_lan | default(false) | bool %}
# MQTT on all interfaces for sensors on other devices (tmsetup.sh -C mqtt_lan).
PublishPort=1883:1883
{% else %}
PublishPort=127.0.0.1:1883:1883
{% endif %}
PublishPort=127.0.0.1:5000:5000
PublishPort=127.0.0.1:8971:8971
```

This drops 1964 (Frigate's go2rtc), 8080 (plate-recognizer), 8564–8566 (Frigate restream and WebRTC), and 80, which moves to the host-network nginx in Task 2.

In `script/ansible/roles/tmsetup/defaults/main.yml`, after `tmsetup_bool_plate_recognizer: false`, add:

```yaml
# Opens MQTT port 1883 to the network for sensors on other devices (tmsetup.sh -C mqtt_lan).
# Set broker credentials first; see docs/configuration/network-access.md.
tmsetup_bool_mqtt_lan: false
```

In `script/tmsetup.sh`, change:

```bash
declare -a _VALID_CUSTOM_VARS=("plate_recognizer")
```

to:

```bash
declare -a _VALID_CUSTOM_VARS=("plate_recognizer" "mqtt_lan")
```

Also fix the error message, which only prints the first valid value. Change:

```bash
          printf "Valid values are:\n  %s\n" "${_VALID_CUSTOM_VARS}"
```

to:

```bash
          printf "Valid values are:\n"
          printf "  %s\n" "${_VALID_CUSTOM_VARS[@]}"
```

- [ ] **Step 5: Run the tests and syntax checks**

Run: `.venv/bin/python -m pytest script/tests -v && bash -n script/tmsetup.sh && echo OK`

Expected: 2 passed, then `OK`.

- [ ] **Step 6: Commit**

```bash
git add script/tests/tmsetup_render.py script/tests/test_tmsetup_templates.py container/traffic-monitor.pod.j2 \
    script/ansible/roles/tmsetup/defaults/main.yml script/tmsetup.sh
git commit -m "Publish pod ports on loopback only; add opt-in LAN MQTT" -m "<trailer block>"
```

---

### Task 2: Reverse proxy on the host network; `/feeds/` limited to viewing

**Files:**
- Modify: `container/revproxy/revproxy.container.j2`
- Modify: `container/revproxy/nginx.conf.j2`
- Modify: `script/ansible/roles/tmsetup/vars/revproxy_vars.yml` (the `go2rtc` entry)
- Modify: `script/ansible/roles/tmsetup/handlers/main.yml` (move `Restart revproxy.service` after `Restart traffic-monitor.service`)
- Modify: `script/ansible/roles/tmsetup/tasks/start_services.yml` (start `revproxy.service`)
- Test: `script/tests/test_tmsetup_templates.py`
- Test: create `script/tests/test_tmsetup_tasks.py`

**Interfaces:**
- Consumes: `render`, `proxies`, and `load_role_yaml` from Task 1.
- Produces three optional per-proxy keys in `tmsetup_proxies`. The nginx template renders them for any proxy, and M2 reuses them.
  - `methods`: a list of HTTP methods. Other methods get 403.
  - `arg_patterns`: a dict mapping each query argument to a regex. A non-matching argument gets 403.
  - `allow_paths`: a regex matched against `$uri`. A non-matching path gets 403.

- [ ] **Step 1: Write the failing tests**

At the top of `script/tests/test_tmsetup_templates.py`:
- Add `import re` and `import pytest`.
- Change `from tmsetup_render import render` to `from tmsetup_render import proxies, render`.

Then append:

```python
def nginx_conf():
    return render("container/revproxy/nginx.conf.j2", tmsetup_proxies=proxies())


def location_block(conf, path):
    start = conf.index(f"location {path} {{")
    return conf[start:conf.index("\n        }", start)]


def go2rtc_proxy():
    return next(proxy for proxy in proxies() if proxy["name"] == "go2rtc")


def test_revproxy_runs_on_the_host_network_outside_the_pod():
    unit = render("container/revproxy/revproxy.container.j2", tmsetup_codedir="/opt/traffic-monitor").splitlines()
    assert "Network=host" in unit
    assert not any(line.startswith("Pod=") for line in unit)


def test_revproxy_keeps_retrying_while_port_80_is_still_taken():
    unit = render("container/revproxy/revproxy.container.j2", tmsetup_codedir="/opt/traffic-monitor").splitlines()
    assert "StartLimitIntervalSec=0" in unit
    assert "RestartSec=5" in unit


def test_no_upstream_goes_through_host_containers_internal():
    assert "host.containers.internal" not in nginx_conf()


def test_feeds_proxies_go2rtc_on_loopback_with_restrictions():
    block = location_block(nginx_conf(), "/feeds/")
    assert "proxy_pass http://127.0.0.1:1984/;" in block
    assert "limit_except GET { deny all; }" in block
    assert 'if ($arg_src !~ "^[A-Za-z0-9_-]*$") { return 403; }' in block
    assert "if ($tm_allow_go2rtc = 0) { return 403; }" in block
    assert "map $uri $tm_allow_go2rtc {" in nginx_conf()


@pytest.mark.parametrize(
    "path, allowed",
    [
        ("/feeds/", True),
        ("/feeds/stream.html", True),
        ("/feeds/video-rtc.js", True),
        ("/feeds/api/ws", True),
        ("/feeds/api/streams", True),
        ("/feeds/api/frame.jpeg", True),
        ("/feeds/api/stream.mp4", True),
        ("/feeds/api/stream.m3u8", True),
        ("/feeds/api", False),
        ("/feeds/api/config", False),
        ("/feeds/api/log", False),
        ("/feeds/api/exit", False),
        ("/feeds/api/restart", False),
        ("/feeds/api/webrtc", False),
        ("/feeds/api/streams/extra", False),
        ("/feeds/api/streamsX", False),
    ],
)
def test_feeds_allows_only_go2rtc_viewing_paths(path, allowed):
    assert bool(re.search(go2rtc_proxy()["allow_paths"], path)) is allowed


@pytest.mark.parametrize(
    "src, allowed",
    [
        ("picam_h265_detect", True),
        ("", True),
        ("exec:id", False),
        ("exec%3Aid", False),
        ("rtsp://192.168.1.20/live", False),
        ("ffmpeg:picam_h265_detect#video=h264", False),
        ("a b", False),
    ],
)
def test_feeds_accepts_only_stream_names_as_src(src, allowed):
    assert bool(re.search(go2rtc_proxy()["arg_patterns"]["src"], src)) is allowed
```

Create `script/tests/test_tmsetup_tasks.py`:

```python
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
```

- [ ] **Step 2: Run the tests to check they fail**

Run: `.venv/bin/python -m pytest script/tests -v`

Expected: the new tests FAIL. For example, `KeyError: 'allow_paths'`, `Network=host` missing, and `ValueError: 'revproxy.service' is not in list`.

- [ ] **Step 3: Move revproxy to the host network**

Replace `container/revproxy/revproxy.container.j2` with:

```
[Unit]
Description=Traffic Monitor NGinx Reverse Proxy container
# Keep retrying: during an upgrade the old pod can hold port 80 for a few seconds.
StartLimitIntervalSec=0

[Container]
ContainerName=revproxy
Image=revproxy.build
# Host network, outside the pod: nginx is the only service listening on the LAN, reaches the apps
# on 127.0.0.1, and keeps serving the home page when the pod is down.
Network=host
Volume=/etc/localtime:/etc/localtime:ro
Volume={{ tmsetup_codedir }}/revproxy/html:/usr/share/nginx/html:ro

[Service]
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
```

- [ ] **Step 4: Add the per-proxy restrictions to the nginx template**

In `container/revproxy/nginx.conf.j2`, replace the line `    #gzip  on;` with:

```
    #gzip  on;
{% for proxy in tmsetup_proxies if proxy['allow_paths'] is defined %}

    # {{ proxy['name'] }}: 1 when the request path is one the proxy may forward
    map $uri $tm_allow_{{ proxy['name'] }} {
        "~{{ proxy['allow_paths'] }}" 1;
        default 0;
    }
{% endfor %}
```

In the same file, replace these two lines:

```
        location {{ proxy['base_path'] }}/ {{ '{' }}
            proxy_pass {{ proxy['pass'] }};
```

with:

```
        location {{ proxy['base_path'] }}/ {{ '{' }}
{% if proxy['methods'] is defined %}
            limit_except {{ proxy['methods'] | join(' ') }} {{ '{' }} deny all; {{ '}' }}
{% endif %}
{% for arg, pattern in (proxy['arg_patterns'] | default({})).items() %}
            if ($arg_{{ arg }} !~ "{{ pattern }}") {{ '{' }} return 403; {{ '}' }}
{% endfor %}
{% if proxy['allow_paths'] is defined %}
            if ($tm_allow_{{ proxy['name'] }} = 0) {{ '{' }} return 403; {{ '}' }}
{% endif %}
            proxy_pass {{ proxy['pass'] }};
```

- [ ] **Step 5: Restrict the go2rtc proxy entry**

In `script/ansible/roles/tmsetup/vars/revproxy_vars.yml`, replace the whole `go2rtc` entry with:

```yaml
  - name: go2rtc
    base_path: /feeds
    label: Go2RTC Feeds
    pass: http://127.0.0.1:1984/
    # View streams only. go2rtc's API can add stream sources that run commands, so refuse
    # everything but GET, stream names other than plain names, and API paths beyond viewing.
    methods:
      - GET
    arg_patterns:
      src: '^[A-Za-z0-9_-]*$'
    allow_paths: '^/feeds/(?!api(/|$))|^/feeds/api/(streams|ws|frame\.jpeg|stream\.(mp4|m3u8|mjpeg))$'
    set_headers:
      - Host $host
      - X-Real-IP $remote_addr
      - Upgrade $http_upgrade
      - Connection "upgrade"
```

- [ ] **Step 6: Restart and start revproxy after the pod**

In `script/ansible/roles/tmsetup/handlers/main.yml`, move the whole `Restart revproxy.service` handler (its 6 lines) to directly after the `Restart traffic-monitor.service` handler. Handlers run in file order, and the pod must release port 80 first.

In `script/ansible/roles/tmsetup/tasks/start_services.yml`, add `revproxy.service` as the last item of the loop:

```yaml
  loop:
    - go2rtc_server.service
    - traffic-monitor.service
    - revproxy.service
```

- [ ] **Step 7: Run the tests and the Ansible syntax check**

Run:

```bash
.venv/bin/python -m pytest script/tests -v
(cd script/ansible && ../../.venv/bin/ansible-playbook -i localhost setup.yml --syntax-check </dev/null > /tmp/tm-syntax.log 2>&1); echo "exit $?"; tail -3 /tmp/tm-syntax.log
```

Expected: all tests pass, then `exit 0`.

- [ ] **Step 8: Commit**

```bash
git add container/revproxy/revproxy.container.j2 container/revproxy/nginx.conf.j2 \
    script/ansible/roles/tmsetup/vars/revproxy_vars.yml script/ansible/roles/tmsetup/handlers/main.yml \
    script/ansible/roles/tmsetup/tasks/start_services.yml script/tests/
git commit -m "Run the reverse proxy on the host network; limit /feeds to viewing" -m "<trailer block>"
```

---

### Task 3: Device secrets

**Files:**
- Create: `script/ansible/roles/tmsetup/tasks/secrets.yml`
- Modify: `script/ansible/roles/tmsetup/tasks/main.yml` (import right after "Setup base")
- Modify: `script/ansible/roles/tmsetup/vars/main.yml`
- Test: `script/tests/test_tmsetup_tasks.py`

**Interfaces:**
- Produces:
  - the fact `tmsetup_secrets`, a dict mapping each secret name to its value
  - `tmsetup_secrets_dir`
  - `tmsetup_secret_names`, which for M1 is `[go2rtc_rtsp_password]`
- Task 7 uses `tmsetup_secrets['go2rtc_rtsp_password']`. M2 adds names to the list.

- [ ] **Step 1: Write the failing tests**

Append to `script/tests/test_tmsetup_tasks.py`:

```python
def secrets_tasks():
    return {task["name"]: task for task in load_role_yaml("tasks/secrets.yml")}


def test_every_task_that_touches_secret_values_hides_its_output():
    for name, task in secrets_tasks().items():
        if name != "TMSetup - Secrets - Create secrets directory":
            assert task.get("no_log") is True, name


def test_existing_secrets_are_never_regenerated():
    generate = secrets_tasks()["TMSetup - Secrets - Generate missing secrets"]["ansible.builtin.copy"]
    assert generate["force"] is False


def test_secrets_are_readable_only_by_root_and_the_code_owner():
    tasks = secrets_tasks()
    directory = tasks["TMSetup - Secrets - Create secrets directory"]["ansible.builtin.file"]
    generate = tasks["TMSetup - Secrets - Generate missing secrets"]["ansible.builtin.copy"]
    assert (directory["owner"], directory["group"], directory["mode"]) == ("root", "{{ tmsetup_codegroup }}", "0750")
    assert (generate["owner"], generate["group"], generate["mode"]) == ("root", "{{ tmsetup_codegroup }}", "0640")


def test_secrets_are_read_on_every_run():
    main = load_role_yaml("tasks/main.yml")
    names = [task["name"] for task in main]
    secrets = main[names.index("TMSetup - Main - Generate and read device secrets")]
    assert secrets["tags"] == ["always"]
    assert names.index("TMSetup - Main - Generate and read device secrets") == names.index("TMSetup - Main - Setup base") + 1
```

- [ ] **Step 2: Run the tests to check they fail**

Run: `.venv/bin/python -m pytest script/tests/test_tmsetup_tasks.py -v`

Expected: the four new tests FAIL with `FileNotFoundError` (no `tasks/secrets.yml` yet) or `ValueError` (task not in `main.yml`).

- [ ] **Step 3: Write the secrets task file**

`script/ansible/roles/tmsetup/tasks/secrets.yml`:

```yaml
---
# TMSetup - Secrets: generated once on the device, readable by root and the code owner, never in the repo.
# Every task that handles a value sets no_log, because tmsetup.sh copies all output into ~/tmsetup-*.log.
- name: TMSetup - Secrets - Create secrets directory
  become: true
  ansible.builtin.file:
    path: '{{ tmsetup_secrets_dir }}'
    state: directory
    owner: root
    group: '{{ tmsetup_codegroup }}'
    mode: '0750'

- name: TMSetup - Secrets - Generate missing secrets
  become: true
  no_log: true
  loop: '{{ tmsetup_secret_names }}'
  ansible.builtin.copy:
    dest: '{{ tmsetup_secrets_dir }}/{{ item }}'
    content: "{{ lookup('community.general.random_string', length=32, special=false) }}"
    force: false
    owner: root
    group: '{{ tmsetup_codegroup }}'
    mode: '0640'

- name: TMSetup - Secrets - Read secrets
  become: true
  no_log: true
  loop: '{{ tmsetup_secret_names }}'
  ansible.builtin.slurp:
    src: '{{ tmsetup_secrets_dir }}/{{ item }}'
  register: tmsetup_secrets_slurp_register

- name: TMSetup - Secrets - Set secrets fact
  no_log: true
  ansible.builtin.set_fact:
    tmsetup_secrets: >-
      {{ dict(tmsetup_secret_names | zip(tmsetup_secrets_slurp_register.results
         | map(attribute='content') | map('b64decode') | map('trim'))) }}
...
```

`force: false` writes a secret only when its file doesn't exist yet, so re-runs keep the existing values. Values are alphanumeric, so they're safe inside URLs.

- [ ] **Step 4: Register the variables and the import**

In `script/ansible/roles/tmsetup/vars/main.yml`, before the closing `...`, add:

```yaml
# Secrets generated once on the device by tasks/secrets.yml. Only names here; values never in the repo.
tmsetup_secrets_dir: /etc/traffic-monitor/secrets
tmsetup_secret_names:
  - go2rtc_rtsp_password
```

In `script/ansible/roles/tmsetup/tasks/main.yml`, directly after the `TMSetup - Main - Setup base` import, add:

```yaml
- name: TMSetup - Main - Generate and read device secrets
  tags:
    - always
  ansible.builtin.import_tasks:
    file: secrets.yml
```

- [ ] **Step 5: Run the tests and the Ansible checks**

Run:

```bash
.venv/bin/python -m pytest script/tests -v
(cd script/ansible && ../../.venv/bin/ansible-playbook -i localhost setup.yml --syntax-check </dev/null > /tmp/tm-syntax.log 2>&1); echo "exit $?"; tail -3 /tmp/tm-syntax.log
```

Expected: all tests pass, then `exit 0`.

- [ ] **Step 6: Commit**

```bash
git add script/ansible/roles/tmsetup/tasks/secrets.yml script/ansible/roles/tmsetup/tasks/main.yml \
    script/ansible/roles/tmsetup/vars/main.yml script/tests/test_tmsetup_tasks.py
git commit -m "Generate device secrets once and keep them out of the install log" -m "<trailer block>"
```

---

### Task 4: tm-control package with round-trip YAML editing

**Files:**
- Create: `tm-control/backend/requirements.txt`
- Create: `tm-control/backend/tm_control/__init__.py`
- Create: `tm-control/backend/tm_control/__main__.py`
- Create: `tm-control/backend/tm_control/adapters/__init__.py` (empty)
- Create: `tm-control/backend/tm_control/adapters/yamlfile.py`
- Create: `tm-control/backend/tm_control/core/__init__.py` (empty)
- Create: `tm-control/backend/tests/conftest.py`
- Create: `tm-control/backend/tests/fixtures/frigate_config_v0.17.yml` (generated in step 1)
- Create: `tm-control/backend/tests/test_yamlfile.py`
- Modify: `script/requirements-dev`

**Interfaces:**
- Produces, in `tm_control.adapters.yamlfile`:
  - `class RoundTripFile(path, mapping_indent=2)`:
    - `.data`: the loaded document, which you edit in place.
    - `.render() -> str`
    - `.save(now: datetime | None = None) -> Path | None`: writes atomically if the content changed. Returns the backup's path, or `None` if nothing changed.
  - `class ConcurrentEditError(RuntimeError)`
  - `write_atomic(path: Path, text: str) -> None`
  - `backup_path(path: Path, now: datetime | None = None) -> Path`: returns `<name>.<YYYYMMDDTHHMMSSZ>.bak`.
- Produces the pytest fixture `frigate_config`: a `Path` to a 0640 copy of the fixture in `tmp_path/config/config.yml`.

- [ ] **Step 1: Add the dependency and the test fixture**

`tm-control/backend/requirements.txt`:

```
# tm-control runtime dependencies, pinned. Installed on the device into a venv by tmsetup.sh (tm-control tag).
ruamel.yaml==0.19.1
```

In `script/requirements-dev`, add this line after `-r requirements`:

```
-r ../tm-control/backend/requirements.txt
```

Install it: `.venv/bin/pip install -r script/requirements-dev`

Generate the fixture from the Frigate template as it is now, before Task 7 changes it. It represents an existing device's config:

```bash
mkdir -p tm-control/backend/tests/fixtures
.venv/bin/python - <<'EOF'
import sys
sys.path.insert(0, "script/tests")
from tmsetup_render import render

detectors = {
    "edgetpu_usb": {"dev_path": "/dev/bus/usb", "frigate_type": "edgetpu", "frigate_device": "usb",
                    "exists": True, "dev_path_available": True, "fresh_install": False},
    "edgetpu_pci": {"dev_path": "/dev/apex_0", "frigate_type": "edgetpu", "frigate_device": "pci",
                    "exists": False, "dev_path_available": False, "fresh_install": False},
    "hailo8l": {"dev_path": "/dev/hailo0", "frigate_type": "hailo8l", "frigate_device": "PCIe",
                "exists": False, "dev_path_available": False, "fresh_install": False},
}
text = render("container/frigate/config/config.yml.j2", tmsetup_detectors=detectors)
open("tm-control/backend/tests/fixtures/frigate_config_v0.17.yml", "w").write(text)
EOF
grep -n 'path: rtsp://host.containers.internal:8554/picam_h265_detect' tm-control/backend/tests/fixtures/frigate_config_v0.17.yml
```

Expected: one matching line, with no credentials in it. Don't regenerate this fixture after Task 7.

- [ ] **Step 2: Write the failing tests**

`tm-control/backend/tests/conftest.py`:

```python
import shutil
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def frigate_config(tmp_path):
    """A copy of Frigate's config.yml as tmsetup rendered it before go2rtc RTSP credentials (synthetic)."""
    (tmp_path / "config").mkdir()
    path = tmp_path / "config" / "config.yml"
    shutil.copy(FIXTURES / "frigate_config_v0.17.yml", path)
    path.chmod(0o640)
    return path
```

`tm-control/backend/tests/test_yamlfile.py`:

```python
import stat
from datetime import datetime, timezone

import pytest

from tm_control.adapters import yamlfile
from tm_control.adapters.yamlfile import ConcurrentEditError, RoundTripFile

NOW = datetime(2026, 10, 2, 15, 30, 0, tzinfo=timezone.utc)


def test_round_trip_without_edits_is_byte_identical(frigate_config):
    document = RoundTripFile(frigate_config)
    assert document.render() == frigate_config.read_text()


def test_round_trip_keeps_a_final_newline(frigate_config):
    frigate_config.write_text(frigate_config.read_text() + "\n")
    assert RoundTripFile(frigate_config).render() == frigate_config.read_text()


def test_save_without_edits_writes_nothing(frigate_config):
    before = frigate_config.stat().st_mtime_ns
    assert RoundTripFile(frigate_config).save(now=NOW) is None
    assert frigate_config.stat().st_mtime_ns == before
    assert sorted(p.name for p in frigate_config.parent.iterdir()) == ["config.yml"]


def test_save_changes_only_the_edited_line_and_keeps_comments_and_quotes(frigate_config):
    original = frigate_config.read_text()
    document = RoundTripFile(frigate_config)
    document.data["cameras"]["picam_h265"]["detect"]["fps"] = 5
    document.save(now=NOW)

    old_lines, new_lines = original.splitlines(), frigate_config.read_text().splitlines()
    changed = [(a, b) for a, b in zip(old_lines, new_lines) if a != b]
    assert len(old_lines) == len(new_lines)
    assert changed == [("      fps: 10", "      fps: 5")]
    assert '  password: "{FRIGATE_MQTT_PASSWORD}"' in new_lines
    assert "#  mycpu:" in new_lines


def test_save_backs_up_the_previous_file(frigate_config):
    original = frigate_config.read_text()
    document = RoundTripFile(frigate_config)
    document.data["mqtt"]["port"] = 1884
    backup = document.save(now=NOW)

    assert backup == frigate_config.with_name("config.yml.20261002T153000Z.bak")
    assert backup.read_text() == original


def test_save_keeps_the_file_mode(frigate_config):
    document = RoundTripFile(frigate_config)
    document.data["mqtt"]["port"] = 1884
    document.save(now=NOW)
    assert stat.S_IMODE(frigate_config.stat().st_mode) == 0o640


def test_save_refuses_when_the_file_changed_after_loading(frigate_config):
    document = RoundTripFile(frigate_config)
    frigate_config.write_text(frigate_config.read_text() + "# edited by hand\n")
    document.data["mqtt"]["port"] = 1884
    with pytest.raises(ConcurrentEditError):
        document.save(now=NOW)
    assert frigate_config.read_text().endswith("# edited by hand\n")


def test_failed_write_leaves_the_file_and_no_temp_files(frigate_config, monkeypatch):
    original = frigate_config.read_text()

    def fail(*args):
        raise OSError("disk full")

    monkeypatch.setattr(yamlfile.os, "replace", fail)
    with pytest.raises(OSError):
        yamlfile.write_atomic(frigate_config, "new: content\n")
    assert frigate_config.read_text() == original
    assert sorted(p.name for p in frigate_config.parent.iterdir()) == ["config.yml"]
```

- [ ] **Step 3: Run the tests to check they fail**

Run: `.venv/bin/python -m pytest tm-control/backend/tests -v`

Expected: collection ERROR, `ModuleNotFoundError: No module named 'tm_control'`.

- [ ] **Step 4: Write the package**

`tm-control/backend/tm_control/__init__.py`:

```python
"""Traffic Monitor control app (tm-control)."""
```

`tm-control/backend/tm_control/__main__.py`:

```python
import sys

from tm_control.cli import main

sys.exit(main())
```

`tm_control.cli` arrives in Task 5. Nothing imports `__main__` before then.

`tm-control/backend/tm_control/adapters/__init__.py` and `tm-control/backend/tm_control/core/__init__.py` are empty files.

`tm-control/backend/tm_control/adapters/yamlfile.py`:

```python
"""Edit YAML config files in place: keep comments, key order, and quoting, and write atomically with a backup."""

import contextlib
import io
import os
import shutil
import stat
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from ruamel.yaml import YAML


class ConcurrentEditError(RuntimeError):
    """The file changed on disk after it was loaded, so saving would overwrite someone else's edit."""


def _round_trip_yaml(mapping_indent):
    yaml = YAML()  # round-trip mode keeps comments, key order, and (with preserve_quotes) quoting
    yaml.preserve_quotes = True
    yaml.indent(mapping=mapping_indent, sequence=mapping_indent + 2, offset=mapping_indent)
    yaml.width = 4096  # never re-wrap long lines such as ffmpeg arguments
    return yaml


def backup_path(path, now=None):
    """Where save() copies the current file before replacing it, e.g. config.yml.20261002T153000Z.bak."""
    now = now or datetime.now(timezone.utc)
    return path.with_name(f"{path.name}.{now:%Y%m%dT%H%M%SZ}.bak")


def write_atomic(path, text):
    """Replace path with text so readers see the old file or the new one, never a partial write.

    Keeps the file's permission bits, and its owner when running as root.
    """
    original = path.stat()
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, stat.S_IMODE(original.st_mode))
        if os.geteuid() == 0:
            os.chown(tmp, original.st_uid, original.st_gid)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        raise


class RoundTripFile:
    """A YAML file loaded for editing. Change .data, then call save()."""

    def __init__(self, path, mapping_indent=2):
        self.path = Path(path)
        self._yaml = _round_trip_yaml(mapping_indent)
        self._loaded_text = self.path.read_text()
        self.data = self._yaml.load(self._loaded_text)

    def render(self):
        out = io.StringIO()
        self._yaml.dump(self.data, out)
        text = out.getvalue()
        if not self._loaded_text.endswith("\n"):
            text = text.removesuffix("\n")  # keep a missing final newline, so an unedited file renders identically
        return text

    def save(self, now=None):
        """Write the edited data if it differs from the file. Return the backup's path, or None if nothing changed."""
        text = self.render()
        if text == self._loaded_text:
            return None
        if self.path.read_text() != self._loaded_text:
            raise ConcurrentEditError(f"{self.path} changed after it was loaded; not saving")
        backup = backup_path(self.path, now)
        shutil.copy2(self.path, backup)
        write_atomic(self.path, text)
        self._loaded_text = text
        return backup
```

`mapping_indent=2` with `sequence=4, offset=2` reproduces tmsetup's Frigate config byte for byte. Node-RED's `config.yml` uses 4-space mappings, and M2 passes `mapping_indent=4` for it.

- [ ] **Step 5: Run the tests to check they pass**

Run: `.venv/bin/python -m pytest tm-control/backend/tests -v`

Expected: 8 passed.

- [ ] **Step 6: Commit**

```bash
git add tm-control/ script/requirements-dev
git commit -m "Add tm-control package with round-trip YAML editing" -m "<trailer block>"
```

---

### Task 5: `tm-control migrate` command

**Files:**
- Create: `tm-control/backend/tm_control/core/migrate.py`
- Create: `tm-control/backend/tm_control/cli.py`
- Test: create `tm-control/backend/tests/test_frigate_rtsp_migration.py`
- Test: create `tm-control/backend/tests/test_tm_control_cli.py`

**Interfaces:**
- Consumes: `RoundTripFile` and `ConcurrentEditError` from Task 4.
- Produces, in `tm_control.core.migrate`:
  - `HOST_GO2RTC_RTSP` = `"rtsp://host.containers.internal:8554/"`
  - `HOST_GO2RTC_RTSP_WITH_CREDENTIALS` = `"rtsp://{FRIGATE_GO2RTC_RTSP_USER}:{FRIGATE_GO2RTC_RTSP_PASSWORD}@host.containers.internal:8554/"`
  - `add_go2rtc_rtsp_credentials(config) -> int`
  - `uncredentialed_rtsp_8554_inputs(config) -> list[tuple[str, str]]`
  - `run(frigate_config: Path, dry_run: bool = False) -> int` (an exit code)
- Produces `tm_control.cli.main(argv: list[str] | None = None) -> int`.
- Output contract that Ansible relies on (Task 7):
  - stdout contains `updated` only when the file changed.
  - Errors go to stderr, starting with `tm-control migrate: ERROR`, with exit code 1.

- [ ] **Step 1: Write the failing tests**

`tm-control/backend/tests/test_frigate_rtsp_migration.py`:

```python
from tm_control.core import migrate

DEFAULT_INPUT = "        - path: rtsp://host.containers.internal:8554/picam_h265_detect"
MIGRATED_INPUT = (
    "        - path: rtsp://{FRIGATE_GO2RTC_RTSP_USER}:{FRIGATE_GO2RTC_RTSP_PASSWORD}"
    "@host.containers.internal:8554/picam_h265_detect"
)


def output(capsys):
    captured = capsys.readouterr()
    return captured.out + captured.err


def add_camera(path, name, input_path):
    """Add a camera with one ffmpeg input to a Frigate config, at the top of the cameras: key."""
    text = path.read_text().replace(
        "cameras:\n",
        f"cameras:\n  {name}:\n    ffmpeg:\n      inputs:\n        - path: {input_path}\n          roles:\n            - detect\n",
        1,
    )
    path.write_text(text)


def test_rewrites_the_default_camera_input_and_nothing_else(frigate_config, capsys):
    original = frigate_config.read_text()
    assert migrate.run(frigate_config) == 0

    old_lines, new_lines = original.splitlines(), frigate_config.read_text().splitlines()
    assert [(a, b) for a, b in zip(old_lines, new_lines) if a != b] == [(DEFAULT_INPUT, MIGRATED_INPUT)]
    assert "updated 1 camera input(s)" in output(capsys)
    assert len(list(frigate_config.parent.glob("config.yml.*.bak"))) == 1


def test_running_twice_changes_nothing_the_second_time(frigate_config, capsys):
    migrate.run(frigate_config)
    after_first = frigate_config.read_text()
    capsys.readouterr()

    assert migrate.run(frigate_config) == 0
    assert frigate_config.read_text() == after_first
    assert "up to date" in output(capsys)
    assert len(list(frigate_config.parent.glob("config.yml.*.bak"))) == 1


def test_leaves_other_cameras_alone(frigate_config, capsys):
    add_camera(frigate_config, "street_ipcam", "rtsp://{FRIGATE_RTSP_USER}:{FRIGATE_RTSP_PASSWORD}@192.168.1.20:554/live")
    add_camera(frigate_config, "restream", "rtsp://127.0.0.1:8554/picam_h265_detect")

    assert migrate.run(frigate_config) == 0
    text = frigate_config.read_text()
    assert "rtsp://{FRIGATE_RTSP_USER}:{FRIGATE_RTSP_PASSWORD}@192.168.1.20:554/live" in text
    assert "rtsp://127.0.0.1:8554/picam_h265_detect" in text
    assert "WARNING" not in output(capsys)


def test_warns_about_port_8554_inputs_it_cannot_rewrite(frigate_config, capsys):
    add_camera(frigate_config, "by_ip", "rtsp://192.168.1.50:8554/picam_h265_detect")

    assert migrate.run(frigate_config) == 0
    assert "rtsp://192.168.1.50:8554/picam_h265_detect" in frigate_config.read_text()
    assert "WARNING camera 'by_ip'" in output(capsys)


def test_keeps_quotes_on_a_quoted_input(frigate_config):
    frigate_config.write_text(frigate_config.read_text().replace(
        "path: rtsp://host.containers.internal:8554/picam_h265_detect",
        "path: 'rtsp://host.containers.internal:8554/picam_h265_detect'",
    ))
    migrate.run(frigate_config)
    assert (
        "path: 'rtsp://{FRIGATE_GO2RTC_RTSP_USER}:{FRIGATE_GO2RTC_RTSP_PASSWORD}"
        "@host.containers.internal:8554/picam_h265_detect'"
    ) in frigate_config.read_text()


def test_dry_run_reports_without_writing(frigate_config, capsys):
    original = frigate_config.read_text()
    assert migrate.run(frigate_config, dry_run=True) == 0
    assert frigate_config.read_text() == original
    assert "would update 1 camera input(s)" in output(capsys)
    assert list(frigate_config.parent.glob("config.yml.*.bak")) == []


def test_config_without_cameras_is_up_to_date(tmp_path, capsys):
    path = tmp_path / "config.yml"
    path.write_text("mqtt:\n  enabled: false\n")
    assert migrate.run(path) == 0
    assert "up to date" in output(capsys)


def test_missing_file_is_an_error(tmp_path, capsys):
    assert migrate.run(tmp_path / "missing.yml") == 1
    assert "ERROR reading" in output(capsys)


def test_invalid_yaml_is_an_error_and_is_left_alone(tmp_path, capsys):
    path = tmp_path / "config.yml"
    path.write_text("cameras: [unclosed\n")
    assert migrate.run(path) == 1
    assert "ERROR reading" in output(capsys)
    assert path.read_text() == "cameras: [unclosed\n"
```

`tm-control/backend/tests/test_tm_control_cli.py`:

```python
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tm_control.cli import main

BACKEND_DIR = Path(__file__).resolve().parents[1]


def test_migrate_command_updates_the_file(frigate_config):
    assert main(["migrate", "--frigate-config", str(frigate_config)]) == 0
    assert "{FRIGATE_GO2RTC_RTSP_USER}" in frigate_config.read_text()


def test_migrate_requires_the_frigate_config_option():
    with pytest.raises(SystemExit) as exit_info:
        main(["migrate"])
    assert exit_info.value.code == 2


def test_runs_as_a_module(frigate_config):
    result = subprocess.run(
        [sys.executable, "-m", "tm_control", "migrate", "--dry-run", "--frigate-config", str(frigate_config)],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(BACKEND_DIR)},
    )
    assert result.returncode == 0, result.stderr
    assert "would update 1 camera input(s)" in result.stdout
```

- [ ] **Step 2: Run the tests to check they fail**

Run: `.venv/bin/python -m pytest tm-control/backend/tests -v`

Expected: collection ERROR, `ImportError: cannot import name 'migrate' from 'tm_control.core'` (or no module `tm_control.cli`).

- [ ] **Step 3: Write the migration and the command line**

`tm-control/backend/tm_control/core/migrate.py`:

```python
"""Bring config files from older installs up to date. Each step is idempotent: running it again changes nothing."""

import sys
from urllib.parse import urlsplit

from ruamel.yaml import YAMLError

from tm_control.adapters.yamlfile import ConcurrentEditError, RoundTripFile

PREFIX = "tm-control migrate:"

# Frigate reads the Pi camera from go2rtc on the host. Since go2rtc's RTSP server requires credentials,
# camera inputs must carry them; Frigate fills in {FRIGATE_*} from frigate.env.
HOST_GO2RTC_RTSP = "rtsp://host.containers.internal:8554/"
HOST_GO2RTC_RTSP_WITH_CREDENTIALS = (
    "rtsp://{FRIGATE_GO2RTC_RTSP_USER}:{FRIGATE_GO2RTC_RTSP_PASSWORD}@host.containers.internal:8554/"
)
# Hosts that are Frigate's own container (its bundled go2rtc), not the host's go2rtc.
FRIGATE_LOCAL_HOSTS = {"127.0.0.1", "localhost"}


def _camera_inputs(config):
    """Yield (camera name, input mapping) for every ffmpeg input in a Frigate config."""
    cameras = config.get("cameras") if isinstance(config, dict) else None
    for name, camera in (cameras or {}).items():
        ffmpeg = camera.get("ffmpeg") if isinstance(camera, dict) else None
        inputs = ffmpeg.get("inputs") if isinstance(ffmpeg, dict) else None
        for item in inputs or []:
            if isinstance(item, dict) and isinstance(item.get("path"), str):
                yield name, item


def add_go2rtc_rtsp_credentials(config):
    """Point inputs that read the host's go2rtc at its credentialed URL. Return how many changed."""
    changed = 0
    for _, item in _camera_inputs(config):
        path = item["path"]
        if path.startswith(HOST_GO2RTC_RTSP):
            new_path = HOST_GO2RTC_RTSP_WITH_CREDENTIALS + path[len(HOST_GO2RTC_RTSP):]
            item["path"] = type(path)(new_path)  # same str subclass, so quoting style is kept
            changed += 1
    return changed


def uncredentialed_rtsp_8554_inputs(config):
    """Inputs on port 8554 without credentials that this migration can't safely rewrite (e.g. a LAN IP)."""
    found = []
    for name, item in _camera_inputs(config):
        url = urlsplit(item["path"])
        if url.scheme != "rtsp" or url.username:
            continue
        try:
            port = url.port
        except ValueError:
            continue
        if port == 8554 and url.hostname not in FRIGATE_LOCAL_HOSTS:
            found.append((name, item["path"]))
    return found


def run(frigate_config, dry_run=False):
    """Apply every migration step to Frigate's config.yml. Return a process exit code."""
    try:
        document = RoundTripFile(frigate_config)
    except (OSError, YAMLError) as error:
        print(f"{PREFIX} ERROR reading {frigate_config}: {error}", file=sys.stderr)
        return 1

    changed = add_go2rtc_rtsp_credentials(document.data)
    for camera, path in uncredentialed_rtsp_8554_inputs(document.data):
        print(
            f"{PREFIX} WARNING camera '{camera}' reads {path} without credentials. If that is this "
            "device's go2rtc, add {FRIGATE_GO2RTC_RTSP_USER}:{FRIGATE_GO2RTC_RTSP_PASSWORD}@ before the host.",
            file=sys.stderr,
        )
    if not changed:
        print(f"{PREFIX} {frigate_config}: up to date")
        return 0
    if dry_run:
        print(f"{PREFIX} {frigate_config}: would update {changed} camera input(s) to use go2rtc RTSP credentials")
        return 0
    try:
        backup = document.save()
    except (OSError, ConcurrentEditError) as error:
        print(f"{PREFIX} ERROR writing {frigate_config}: {error}", file=sys.stderr)
        return 1
    print(f"{PREFIX} {frigate_config}: updated {changed} camera input(s) to use go2rtc RTSP credentials (backup: {backup})")
    return 0
```

`tm-control/backend/tm_control/cli.py`:

```python
"""Command line for tm-control. On a device, run it as `tm-control <command>`."""

import argparse
from pathlib import Path

from tm_control.core import migrate


def main(argv=None):
    parser = argparse.ArgumentParser(prog="tm-control", description="Traffic Monitor control app")
    commands = parser.add_subparsers(dest="command", required=True)

    migrate_parser = commands.add_parser("migrate", help="update config files from older installs")
    migrate_parser.add_argument("--frigate-config", type=Path, required=True, help="path to Frigate's config.yml")
    migrate_parser.add_argument("--dry-run", action="store_true", help="report what would change without writing")

    args = parser.parse_args(argv)
    if args.command == "migrate":
        return migrate.run(args.frigate_config, dry_run=args.dry_run)
    return 2
```

- [ ] **Step 4: Run the tests to check they pass**

Run: `.venv/bin/python -m pytest tm-control/backend/tests -v`

Expected: 20 passed.

- [ ] **Step 5: Commit**

```bash
git add tm-control/backend/tm_control/core/migrate.py tm-control/backend/tm_control/cli.py tm-control/backend/tests/
git commit -m "Add tm-control migrate to add go2rtc RTSP credentials to existing Frigate configs" -m "<trailer block>"
```

---

### Task 6: Install the tm-control command on the device

**Files:**
- Create: `script/ansible/roles/tmsetup/tasks/tm-control_setup.yml`
- Create: `script/ansible/roles/tmsetup/templates/tm-control/tm-control.j2`
- Create: symlink `script/ansible/roles/tmsetup/files/tm-control` → `../../../../../tm-control/`
- Modify: `script/ansible/roles/tmsetup/tasks/main.yml` (import before "Setup Frigate")
- Modify: `script/ansible/roles/tmsetup/vars/main.yml` (`tmsetup_tm_control_dir`, and `python3-venv` in `tmsetup_packages`)
- Modify: `script/tmsetup.sh` (`_VALID_TAGS`)
- Test: `script/tests/test_tmsetup_templates.py`
- Test: `script/tests/test_tmsetup_tasks.py`

**Interfaces:**
- Consumes: the `tm_control` package from Tasks 4 and 5.
- Produces:
  - On the device, `/usr/local/bin/tm-control`, which runs the root-owned copy in `/usr/local/lib/traffic-monitor/tm-control`.
  - `tmsetup_tm_control_dir`.
  - The `tm-control` tag. Tags `frigate` and `tm-control` both run this task file.

- [ ] **Step 1: Write the failing tests**

Add `import ast` to the imports at the top of `script/tests/test_tmsetup_templates.py`, then append:

```python
TM_CONTROL_DIR = "/usr/local/lib/traffic-monitor/tm-control"


def test_tm_control_wrapper_runs_only_the_root_owned_copy():
    script = render("script/ansible/roles/tmsetup/templates/tm-control/tm-control.j2", tmsetup_tm_control_dir=TM_CONTROL_DIR)
    assert script.splitlines()[0] == f"#!{TM_CONTROL_DIR}/venv/bin/python -EP"
    assert f'sys.path.insert(0, "{TM_CONTROL_DIR}/backend")' in script
    ast.parse(script)
```

Append to `script/tests/test_tmsetup_tasks.py`:

```python
def test_tm_control_code_lives_outside_the_code_owners_directory():
    tm_control_dir = load_role_yaml("vars/main.yml")["tmsetup_tm_control_dir"]
    assert tm_control_dir.startswith("/usr/local/")
    assert not tm_control_dir.startswith(load_role_yaml("defaults/main.yml")["tmsetup_codedir"])


def test_tm_control_files_are_root_owned():
    for task in load_role_yaml("tasks/tm-control_setup.yml"):
        for module in ("ansible.builtin.file", "ansible.builtin.copy", "ansible.builtin.template"):
            if module in task:
                assert task[module]["owner"] == "root", task["name"]


def test_frigate_and_tm_control_tags_install_tm_control_before_frigate():
    main = load_role_yaml("tasks/main.yml")
    names = [task["name"] for task in main]
    tm_control = main[names.index("TMSetup - Main - Setup tm-control command line")]
    assert set(tm_control["tags"]) == {"tm-control", "frigate"}
    assert names.index("TMSetup - Main - Setup tm-control command line") < names.index("TMSetup - Main - Setup Frigate")
```

- [ ] **Step 2: Run the tests to check they fail**

Run: `.venv/bin/python -m pytest script/tests -v`

Expected: the new tests FAIL with `TemplateNotFound`, `KeyError: 'tmsetup_tm_control_dir'`, and `FileNotFoundError`.

- [ ] **Step 3: Write the wrapper template, the task file, and the symlink**

`script/ansible/roles/tmsetup/templates/tm-control/tm-control.j2`:

```python
#!{{ tmsetup_tm_control_dir }}/venv/bin/python -EP
"""tm-control command line, installed by tmsetup.sh (tm-control tag).

-E ignores PYTHON* environment variables and -P keeps the current directory off sys.path,
so the code that runs is always the root-owned copy below, even under sudo.
"""
import sys

sys.path.insert(0, "{{ tmsetup_tm_control_dir }}/backend")

from tm_control.cli import main  # noqa: E402

sys.exit(main())
```

`script/ansible/roles/tmsetup/tasks/tm-control_setup.yml`:

```yaml
---
# TMSetup - tm-control Setup tasks
# Root may run this code, so it lives under /usr/local and stays root-owned, outside
# {{ tmsetup_codedir }}, which the code owner can write.
- name: TMSetup - tm-control Setup - Create install directories
  become: true
  loop:
    - /usr/local/lib/traffic-monitor
    - '{{ tmsetup_tm_control_dir }}'
    - '{{ tmsetup_tm_control_dir }}/backend'
  ansible.builtin.file:
    path: '{{ item }}'
    state: directory
    owner: root
    group: root
    mode: '0755'

- name: TMSetup - tm-control Setup - Copy the tm_control package
  become: true
  ansible.builtin.copy:
    src: tm-control/backend/tm_control
    dest: '{{ tmsetup_tm_control_dir }}/backend/'
    owner: root
    group: root
    mode: u=rwX,go=rX

- name: TMSetup - tm-control Setup - Copy pinned requirements
  become: true
  ansible.builtin.copy:
    src: tm-control/backend/requirements.txt
    dest: '{{ tmsetup_tm_control_dir }}/requirements.txt'
    owner: root
    group: root
    mode: '0644'

- name: TMSetup - tm-control Setup - Create virtual environment
  become: true
  ansible.builtin.command:
    cmd: python3 -m venv {{ tmsetup_tm_control_dir }}/venv
    creates: '{{ tmsetup_tm_control_dir }}/venv/bin/python'

- name: TMSetup - tm-control Setup - Install pinned requirements
  become: true
  ansible.builtin.command:
    argv:
      - '{{ tmsetup_tm_control_dir }}/venv/bin/pip'
      - install
      - --no-input
      - --disable-pip-version-check
      - --requirement
      - '{{ tmsetup_tm_control_dir }}/requirements.txt'
  register: tmsetup_tm_control_pip_register
  changed_when: "'Successfully installed' in tmsetup_tm_control_pip_register.stdout"

- name: TMSetup - tm-control Setup - Install the tm-control command
  become: true
  ansible.builtin.template:
    src: tm-control/tm-control.j2
    dest: /usr/local/bin/tm-control
    owner: root
    group: root
    mode: '0755'

- name: TMSetup - tm-control Setup - Check the tm-control command runs
  become: true
  ansible.builtin.command:
    argv:
      - /usr/local/bin/tm-control
      - --help
  changed_when: false
...
```

Create the symlink the same way as `files/container`:

```bash
ln -s ../../../../../tm-control/ script/ansible/roles/tmsetup/files/tm-control
ls script/ansible/roles/tmsetup/files/tm-control/backend/requirements.txt
```

- [ ] **Step 4: Register the variables, package, import, and tag**

In `script/ansible/roles/tmsetup/vars/main.yml`:
- Add `- python3-venv` as the last item of `tmsetup_packages`.
- Before the closing `...`, add:

  ```yaml
  # tm-control code and venv: root-owned, outside tmsetup_codedir (which the code owner can write)
  tmsetup_tm_control_dir: /usr/local/lib/traffic-monitor/tm-control
  ```

In `script/ansible/roles/tmsetup/tasks/main.yml`, directly before `TMSetup - Main - Setup Frigate`, add:

```yaml
- name: TMSetup - Main - Setup tm-control command line
  tags:
    - tm-control
    - frigate
  ansible.builtin.import_tasks:
    file: tm-control_setup.yml
```

In `script/tmsetup.sh`, add `"tm-control"` to the end of `_VALID_TAGS`:

```bash
declare _VALID_TAGS=("base" "full_upgrade" "wifi" "go2rtc" "detectors" "podman" "frigate" "node-red-tm" "plate-recognizer" "revproxy" "tm-control")
```

- [ ] **Step 5: Run the tests and Ansible checks**

Run:

```bash
.venv/bin/python -m pytest script/tests tm-control/backend/tests -v
(cd script/ansible && ../../.venv/bin/ansible-playbook -i localhost setup.yml --syntax-check </dev/null > /tmp/tm-syntax.log 2>&1); echo "exit $?"
(cd script/ansible && ../../.venv/bin/ansible-playbook -i localhost setup.yml --list-tags </dev/null > /tmp/tm-tags.log 2>&1); grep -o 'tm-control' /tmp/tm-tags.log | head -1
bash -n script/tmsetup.sh && echo OK
```

Expected:
- all tests pass
- `exit 0`
- `tm-control`
- `OK`

- [ ] **Step 6: Commit**

```bash
git add script/ansible/roles/tmsetup/tasks/tm-control_setup.yml script/ansible/roles/tmsetup/templates/tm-control/ \
    script/ansible/roles/tmsetup/files/tm-control script/ansible/roles/tmsetup/tasks/main.yml \
    script/ansible/roles/tmsetup/vars/main.yml script/tmsetup.sh script/tests/
git commit -m "Install the tm-control command root-owned under /usr/local" -m "<trailer block>"
```

---

### Task 7: go2rtc API on loopback with RTSP credentials; Frigate uses them

**Files:**
- Create: `script/ansible/roles/tmsetup/templates/go2rtc.yaml.j2`
- Delete: `script/ansible/roles/tmsetup/files/go2rtc.yaml`
- Modify: `script/ansible/roles/tmsetup/tasks/go2rtc_setup.yml` (the "Setup go2rtc rpicam settings" task)
- Modify: `container/frigate/config/config.yml.j2` (camera input path)
- Modify: `container/frigate/frigate.env.j2`
- Modify: `script/ansible/roles/tmsetup/tasks/frigate_setup.yml` (two tasks after "Create Frigate container configuration files")
- Modify: `script/ansible/roles/tmsetup/vars/main.yml` (`tmsetup_go2rtc_rtsp_user`)
- Test: `script/tests/test_tmsetup_templates.py`
- Test: `script/tests/test_tmsetup_tasks.py`
- Test: `tm-control/backend/tests/test_frigate_rtsp_migration.py`

**Interfaces:**
- Consumes:
  - `tmsetup_secrets['go2rtc_rtsp_password']` from Task 3
  - `/usr/local/bin/tm-control` from Task 6
  - `migrate.HOST_GO2RTC_RTSP_WITH_CREDENTIALS` and the `updated` output contract from Task 5
- Produces:
  - `frigate.env` keys `FRIGATE_GO2RTC_RTSP_USER` and `FRIGATE_GO2RTC_RTSP_PASSWORD`
  - `tmsetup_go2rtc_rtsp_user: frigate`

- [ ] **Step 1: Write the failing tests**

Add `import yaml` to the imports at the top of `script/tests/test_tmsetup_templates.py`, then append:

```python
SECRETS = {"go2rtc_rtsp_password": "s3cret"}
CREDENTIALED_INPUT = "rtsp://{FRIGATE_GO2RTC_RTSP_USER}:{FRIGATE_GO2RTC_RTSP_PASSWORD}@host.containers.internal:8554/picam_h265_detect"


def test_go2rtc_api_is_loopback_only_and_rtsp_needs_credentials():
    config = yaml.safe_load(render(
        "script/ansible/roles/tmsetup/templates/go2rtc.yaml.j2",
        tmsetup_go2rtc_rtsp_user="frigate", tmsetup_secrets=SECRETS,
    ))
    assert config["api"] == {"listen": "127.0.0.1:1984"}
    assert config["rtsp"] == {"listen": ":8554", "username": "frigate", "password": "s3cret"}
    assert config["webrtc"] == {"listen": ""}
    assert set(config["streams"]) == {"picam_h265_detect", "picam_h265_detect_hr"}


def test_new_frigate_configs_read_go2rtc_with_credentials():
    config = yaml.safe_load(render("container/frigate/config/config.yml.j2", tmsetup_detectors={}))
    assert config["cameras"]["picam_h265"]["ffmpeg"]["inputs"][0]["path"] == CREDENTIALED_INPUT


def test_frigate_env_carries_the_go2rtc_credentials():
    lines = render(
        "container/frigate/frigate.env.j2",
        tmsetup_frigate_rtsp_password="password", tmsetup_frigate_mqtt_user="mqtt_user",
        tmsetup_frigate_mqtt_password="mqtt_pass", tmsetup_codedir="/opt/traffic-monitor",
        tmsetup_frigate_version="0.17.2", tmsetup_base_path_frigate="/frigate",
        tmsetup_go2rtc_rtsp_user="frigate", tmsetup_secrets=SECRETS,
    ).splitlines()
    assert "FRIGATE_GO2RTC_RTSP_USER=frigate" in lines
    assert "FRIGATE_GO2RTC_RTSP_PASSWORD=s3cret" in lines
    assert "FRIGATE_RTSP_PASSWORD=password" in lines  # operators' own variable is untouched
```

Append to `script/tests/test_tmsetup_tasks.py`:

```python
def frigate_tasks():
    return {task["name"]: task for task in load_role_yaml("tasks/frigate_setup.yml")}


def test_existing_frigate_env_gets_both_credentials_without_printing_them():
    task = frigate_tasks()["TMSetup - Frigate Setup - Add go2rtc RTSP credentials to frigate.env"]
    assert task["no_log"] is True
    assert [item["key"] for item in task["loop"]] == ["FRIGATE_GO2RTC_RTSP_USER", "FRIGATE_GO2RTC_RTSP_PASSWORD"]


def test_existing_frigate_config_is_migrated_as_the_code_owner():
    task = frigate_tasks()["TMSetup - Frigate Setup - Update Frigate config from older installs"]
    argv = task["ansible.builtin.command"]["argv"]
    assert argv[:4] == ["/usr/sbin/runuser", "-u", "{{ tmsetup_codeowner }}", "--"]
    assert argv[4:6] == ["/usr/local/bin/tm-control", "migrate"]
    assert task["notify"] == "Restart frigate.service"


def test_go2rtc_config_with_the_password_is_root_only_and_never_diffed():
    task = next(t for t in load_role_yaml("tasks/go2rtc_setup.yml") if t["name"] == "TMSetup - Go2rtc Setup - Setup go2rtc rpicam settings")
    template = task["ansible.builtin.template"]
    assert (template["src"], template["owner"], template["mode"]) == ("go2rtc.yaml.j2", "root", "0600")
    assert task["diff"] is False
```

At the top of `tm-control/backend/tests/test_frigate_rtsp_migration.py`, add `from pathlib import Path` above `from tm_control.core import migrate`, and add `REPO = Path(__file__).resolve().parents[3]` below the imports. Then append:

```python

def test_migrated_inputs_match_what_new_installs_get():
    template = (REPO / "container" / "frigate" / "config" / "config.yml.j2").read_text()
    assert migrate.HOST_GO2RTC_RTSP_WITH_CREDENTIALS + "picam_h265_detect" in template
```

- [ ] **Step 2: Run the tests to check they fail**

Run: `.venv/bin/python -m pytest script/tests tm-control/backend/tests -v`

Expected: the new tests FAIL with `TemplateNotFound: .../go2rtc.yaml.j2`, the old input path, `KeyError` for the new task names, and the drift test failing.

- [ ] **Step 3: Write the go2rtc template**

Create `script/ansible/roles/tmsetup/templates/go2rtc.yaml.j2` with this header, followed by the `streams:` block copied unchanged from `script/ansible/roles/tmsetup/files/go2rtc.yaml`. That's everything after its first comment line.

```yaml
# /var/lib/go2rtc/go2rtc.yaml - written by tmsetup.sh (go2rtc tag); edits here are overwritten
api:
  # Only this device can reach the API and web UI; the reverse proxy serves the viewing pages at /feeds/.
  listen: "127.0.0.1:1984"
rtsp:
  # Frigate reads the camera here from the pod, so RTSP stays on all interfaces but needs credentials.
  listen: ":8554"
  username: "{{ tmsetup_go2rtc_rtsp_user }}"
  password: "{{ tmsetup_secrets['go2rtc_rtsp_password'] }}"
webrtc:
  # No fixed WebRTC port; players use MSE through the proxy.
  listen: ""
streams:
```

Then remove the old file: `git rm script/ansible/roles/tmsetup/files/go2rtc.yaml`

In `script/ansible/roles/tmsetup/tasks/go2rtc_setup.yml`, replace the "Setup go2rtc rpicam settings" task with:

```yaml
- name: TMSetup - Go2rtc Setup - Setup go2rtc rpicam settings
  become: true
  diff: false
  ansible.builtin.template:
    dest: /var/lib/go2rtc/go2rtc.yaml
    group: root
    mode: '0600'
    owner: root
    src: go2rtc.yaml.j2
  notify: Restart go2rtc_server service
```

go2rtc runs as root, so 0600 keeps the RTSP password from other local users.

- [ ] **Step 4: Point Frigate at the credentialed stream**

In `container/frigate/config/config.yml.j2`, change:

```yaml
        - path: rtsp://host.containers.internal:8554/picam_h265_detect
```

to:

```yaml
        - path: rtsp://{FRIGATE_GO2RTC_RTSP_USER}:{FRIGATE_GO2RTC_RTSP_PASSWORD}@host.containers.internal:8554/picam_h265_detect
```

In `container/frigate/frigate.env.j2`, after the `FRIGATE_RTSP_PASSWORD=` line, add:

```
# Credentials Frigate uses to read the camera from go2rtc on the host (set by tmsetup.sh)
FRIGATE_GO2RTC_RTSP_USER={{ tmsetup_go2rtc_rtsp_user }}
FRIGATE_GO2RTC_RTSP_PASSWORD={{ tmsetup_secrets['go2rtc_rtsp_password'] }}
```

In `script/ansible/roles/tmsetup/vars/main.yml`, before the closing `...`, add:

```yaml
# go2rtc RTSP user that Frigate logs in as; the password is tmsetup_secrets['go2rtc_rtsp_password']
tmsetup_go2rtc_rtsp_user: frigate
```

In `script/ansible/roles/tmsetup/tasks/frigate_setup.yml`, directly after `TMSetup - Frigate Setup - Create Frigate container configuration files`, add:

```yaml
- name: TMSetup - Frigate Setup - Add go2rtc RTSP credentials to frigate.env
  become: true
  no_log: true
  loop:
    - { key: FRIGATE_GO2RTC_RTSP_USER, value: '{{ tmsetup_go2rtc_rtsp_user }}' }
    - { key: FRIGATE_GO2RTC_RTSP_PASSWORD, value: "{{ tmsetup_secrets['go2rtc_rtsp_password'] }}" }
  ansible.builtin.lineinfile:
    path: '{{ tmsetup_codedir }}/frigate/frigate.env'
    regexp: '^{{ item.key }}='
    line: '{{ item.key }}={{ item.value }}'
  notify: Restart frigate.service

- name: TMSetup - Frigate Setup - Update Frigate config from older installs
  become: true
  ansible.builtin.command:
    argv:
      - /usr/sbin/runuser
      - -u
      - '{{ tmsetup_codeowner }}'
      - --
      - /usr/local/bin/tm-control
      - migrate
      - --frigate-config
      - '{{ tmsetup_codedir }}/frigate/config/config.yml'
  register: tmsetup_frigate_migrate_register
  changed_when: "'updated' in tmsetup_frigate_migrate_register.stdout"
  notify: Restart frigate.service
```

`frigate.env` and `config.yml` aren't overwritten without `-f`. The first task gives existing devices the credentials. The second rewrites their camera input, keeping comments and writing a backup, and does nothing on new installs. It runs as the code owner through `runuser`, like the tmdb migration in `node-red-tm.container.j2`.

- [ ] **Step 5: Run every check**

Run:

```bash
.venv/bin/python -m pytest script/tests tm-control/backend/tests container/node-red-tm/schema/tests -v
(cd script/ansible && ../../.venv/bin/ansible-playbook -i localhost setup.yml --syntax-check </dev/null > /tmp/tm-syntax.log 2>&1); echo "exit $?"
.venv/bin/python -c 'import sys,jinja2; e=jinja2.Environment(); [e.parse(open(f).read(), filename=f) for f in sys.argv[1:]]' $(git ls-files --cached --others --exclude-standard '*.j2') && echo "templates parse"
python3 -m json.tool container/node-red-tm/data/flows.json >/dev/null && echo "flows ok"
```

Expected:
- all tests pass
- `exit 0`
- `templates parse`
- `flows ok`

- [ ] **Step 6: Commit**

```bash
git add -A script/ansible/roles/tmsetup/templates/go2rtc.yaml.j2 script/ansible/roles/tmsetup/files/go2rtc.yaml \
    script/ansible/roles/tmsetup/tasks/go2rtc_setup.yml script/ansible/roles/tmsetup/tasks/frigate_setup.yml \
    script/ansible/roles/tmsetup/vars/main.yml container/frigate/config/config.yml.j2 container/frigate/frigate.env.j2 \
    script/tests/ tm-control/backend/tests/
git commit -m "Bind go2rtc's API to loopback and require RTSP credentials for the camera stream" -m "<trailer block>"
```

---

### Task 8: Docs and CLAUDE.md

**Files:**
- Create: `docs/configuration/network-access.md`
- Modify: `docs/SUMMARY.md`
- Modify: `README.md` (lines 44–48 and 62)
- Modify: `docs/setup-guide.md` (line 67)
- Modify: `docs/development/dev-environment.md` (line 22)
- Modify: `CLAUDE.md`

- [ ] **Step 1: Write the network access page**

`docs/configuration/network-access.md`:

````markdown
---
description: Which network ports the Traffic Monitor opens, and how to reach each app.
---

# Network Access

Every app on the Traffic Monitor is reached through the home page on port 80. The apps themselves only accept connections from the device, so other computers reach them through these paths:

| App | Address |
|---|---|
| Home page | `http://<device>/` |
| Dashboard | `http://<device>/dashboard/` |
| Frigate | `http://<device>/frigate/` |
| Legacy dashboard | `http://<device>/ui/` |
| Node-RED editor | `http://<device>/nr/` |
| Camera feeds (go2rtc) | `http://<device>/feeds/` |

`<device>` is the device's IP address or `<hostname>.local`.

## Open ports

| Port | Used for |
|---|---|
| 22 | SSH |
| 80 | Home page and every app above |
| 8554 | Camera stream (RTSP), with a username and password |
| 5353 (UDP) | `<hostname>.local` names (mDNS) |
| 9090 | Cockpit, when installed |

The camera feeds page shows the camera streams. It doesn't offer go2rtc's config editor or stream management.

### Camera stream credentials

The camera stream on port 8554 needs the username `frigate` and a password generated on the device at install. To play the stream in another program, such as VLC, read the password on the device:

```bash
sudo cat /etc/traffic-monitor/secrets/go2rtc_rtsp_password
```

Then open `rtsp://frigate:<password>@<device>:8554/picam_h265_detect`.

## MQTT for sensors on other devices

The MQTT broker only accepts connections from the device itself, which is all the air quality sensor needs. If a sensor on another device publishes to it, open MQTT to the network:

1. Set a broker username and password: `TM_MQTT_BROKER_USERNAME` and `TM_MQTT_BROKER_PASSWORD` in `/opt/traffic-monitor/node-red-tm/node-red-tm.env`.
2. Set the same values as `FRIGATE_MQTT_USER` and `FRIGATE_MQTT_PASSWORD` in `/opt/traffic-monitor/frigate/frigate.env`.
3. Run `bash script/tmsetup.sh -C mqtt_lan`.
4. From another computer, check that the broker refuses a connection without the username and password.

{% hint style="warning" %}
Without step 1, anyone on the network can publish to the broker and add false data to your Traffic Monitor.
{% endhint %}

## Changes from earlier versions

* Ports 1880, 1883, 1984, 5000, and 8971 aren't reachable from other computers anymore. Use the paths above.
* Frigate's restream ports (8564–8566) and the Plate Recognizer port (8080) aren't published anymore.
* The camera stream on port 8554 needs the username and password above.
````

In `docs/SUMMARY.md`, under `## Configuration`, after `* [Node-RED Config](configuration/node-red-config.md)`, add:

```markdown
* [Network Access](configuration/network-access.md)
```

- [ ] **Step 2: Update the port references in the README and docs**

In `README.md`, replace the four bullets under "User Interfaces (UI) / port numbers references" with:

```markdown
- `http://<device_ip_address>/` is the home page, with links to every app below.
- `http://<device_ip_address>/ui/` is the [Node-RED](https://nodered.org/) dashboard and your primary device dashboard, use it to ensure it is capturing events, see the latest events, and see summarized stats.
- `http://<device_ip_address>/frigate/` to view the [Frigate](https://github.com/blakeblackshear/frigate) interface and make any configuration changes specific to your deployment
- `http://<device_ip_address>/feeds/` shows the [go2rtc](https://github.com/AlexxIT/go2rtc) camera streams on the Raspberry Pi. Use this if your cameras are giving errors in Frigate.
- `http://<device_ip_address>/nr/` is the Node-RED flow editor used to develop the logic to connect events to speeds, create event records, capture radar readings, and more. This is primarily used by developers. The default admin login is admin/password.

See [Network Access](https://docs.trafficmonitor.ai/configuration/network-access) for the ports the device opens.
```

Also replace `Device dashboard available at \`http://<device_ip_address>:1880/ui\`.` with `Device dashboard available at \`http://<device_ip_address>/ui/\`.`.

In `docs/setup-guide.md`, replace `` `http://<TM_IP_ADDRESS>:5000` `` with `` `http://<TM_IP_ADDRESS>/frigate/` ``.

In `docs/development/dev-environment.md`, replace `` `http://<you_ip>:1880` `` with `` `http://<your_ip>/nr/` ``.

- [ ] **Step 3: Update CLAUDE.md**

Make these edits to the matching text. If a sentence was reworded on your base branch, apply the same meaning.

1. **"What this repo is"**: after the `utils/` bullet, add:

   ```markdown
   - `tm-control/`: the Traffic Monitor control app (spec in `design/specs/`). So far only `tm-control migrate`, which tmsetup runs to update config files from older installs. It's installed root-owned to `/usr/local/lib/traffic-monitor/tm-control` and `/usr/local/bin/tm-control`.
   - `design/`: specs and implementation plans. Not published to GitBook.
   ```

2. **"Commands"**: change the pytest line to:

   ```bash
   python -m pytest container/node-red-tm/schema/tests script/tests tm-control/backend/tests  # schema, role templates and tasks, tm-control
   ```

3. **"Runtime topology"**, first bullet:
   - Change `All containers (frigate, node-red-tm, revproxy, optional plate-recognizer) run in one pod` to `The app containers (frigate, node-red-tm, optional plate-recognizer) run in one pod`.
   - After `nginx proxies to \`127.0.0.1:<port>\`.`, add a sub-bullet: `The pod publishes its ports on 127.0.0.1 only (1880, 1883, 5000, 8971). Set \`tmsetup_bool_mqtt_lan\` (\`-C mqtt_lan\`) to open 1883 to the LAN.`

4. **"Runtime topology"**, go2rtc bullet:
   - Change `config from \`roles/tmsetup/files/go2rtc.yaml\`` to `config from \`roles/tmsetup/templates/go2rtc.yaml.j2\``.
   - Replace the sentence about Frigate reading the stream and port 1964 with:

     ```
     Its API listens on 127.0.0.1:1984. Its RTSP server needs credentials. Frigate reads `rtsp://{FRIGATE_GO2RTC_RTSP_USER}:{FRIGATE_GO2RTC_RTSP_PASSWORD}@host.containers.internal:8554/picam_h265_detect`; the values are in `frigate.env`, and the password comes from `/etc/traffic-monitor/secrets/` (generated by `tasks/secrets.yml`).
     ```

5. **"Runtime topology"**: replace the UIs bullet with:

   ```markdown
   - UIs: the home page on `:80` links to each app. Node-RED editor `/nr/` (admin/password), legacy dashboard `/ui/`, Dashboard 2.0 `/dashboard/`, Frigate `/frigate/`, and go2rtc streams `/feeds/` (viewing only). nginx is the only web server the LAN can reach.
   ```

6. **"Runtime topology"**, nginx bullet: at the start, add:

   ```
   nginx (`revproxy`) runs on the host network, outside the pod, so the home page stays up when the pod is down.
   ```

   Then add at the end:

   ```
   Per-proxy `methods`, `arg_patterns`, and `allow_paths` restrict what a path may forward; `/feeds` uses them.
   ```

7. **Node-RED flows, `init-config` bullet**: replace `The config is read only when the flows start.` with:

   ```
   A `watch` node reloads it when the file changes, which re-records deployments and re-initializes the radars.
   ```

8. **"Overwrite semantics"**: add at the end:

   ```
   To change an existing device's `config.yml` without `-f`, add a step to `tm-control migrate` (round-trip edit with a backup), as tmsetup does for the go2rtc RTSP credentials. Add new `*.env` keys with `lineinfile`.
   ```

- [ ] **Step 4: Check the docs build inputs**

Run:

```bash
grep -rn -E ':1880|:5000|:1984' README.md docs CLAUDE.md | grep -v 'network-access.md'
grep -n 'network-access' docs/SUMMARY.md
```

Expected:
- The first command prints nothing except lines that describe internal addresses (`127.0.0.1:…`).
- The second prints the new SUMMARY line.

- [ ] **Step 5: Commit**

```bash
git add docs/configuration/network-access.md docs/SUMMARY.md README.md docs/setup-guide.md docs/development/dev-environment.md CLAUDE.md
git commit -m "Document network access through the reverse proxy" -m "<trailer block>"
```

---

### Task 9: Verify on a test Pi (a person runs this)

The implementer can't reach a Pi. Hand this checklist to the person and record their results in the PR's Testing section. Use a test Pi running current `dev` with a camera and a working Frigate, not a field device. Don't paste secret values anywhere; only report pass or fail.

- [ ] **Step 1: Upgrade the test Pi with a full run**

```bash
cd ~/traffic-monitor && git fetch && git switch feature/edge-ports/201
bash script/tmsetup.sh            # full run: this is the upgrade path; reboot if asked
```

Expected:
- The run succeeds.
- "Update Frigate config from older installs" reports *changed* the first time.

- [ ] **Step 2: Only nginx is listening on the network**

On the Pi:

```bash
sudo ss -tlnup | grep -v -E '127\.0\.0\.1|\[::1\]'
```

Expected: listeners on `:22`, `:80`, `:8554` (go2rtc), `:5353` (avahi), `:9090` only if Cockpit is installed, and DHCP/DNS only in hotspot mode. Nothing on 1880, 1883, 1984, 5000, 8555, or 8971.

From another computer:

```bash
for port in 1880 1883 1984 5000 8971; do nc -zv -w 3 <pi> $port; done
```

Expected: every port refused or timed out.

- [ ] **Step 3: The camera stream needs credentials**

From another computer, run `ffprobe -v error rtsp://<pi>:8554/picam_h265_detect`. Expected: `401 Unauthorized`.

On the Pi:

```bash
ffprobe -v error -show_entries stream=codec_name "rtsp://frigate:$(sudo cat /etc/traffic-monitor/secrets/go2rtc_rtsp_password)@127.0.0.1:8554/picam_h265_detect"
```

Expected: `codec_name=hevc`.

- [ ] **Step 4: `/feeds/` is view-only and nginx's config is valid**

```bash
sudo podman exec revproxy nginx -t
for u in 'feeds/' 'feeds/api/streams' 'feeds/api/config' 'feeds/api/log' 'feeds/api' 'feeds/api/stream.mp4?src=exec:id' 'feeds/api/stream.mp4?src=exec%3Aid'; do
  printf '%-40s ' "$u"; curl -s -o /dev/null -m 5 -w '%{http_code}\n' "http://<pi>/$u"
done
curl -s -o /dev/null -w '%{http_code}\n' -X POST 'http://<pi>/feeds/api/streams?src=x'
```

Expected:
- `nginx -t` reports `syntax is ok`.
- `feeds/` and `feeds/api/streams` return 200.
- Every other URL, and the POST, returns 403.

In a browser, `http://<pi>/feeds/stream.html?src=picam_h265_detect` plays.

- [ ] **Step 5: The apps still work through the proxy**

- `http://<pi>/frigate/` shows the camera live and not offline.
- `sudo journalctl -u frigate.service -b | grep -i -E '401|unauthorized'` prints nothing.
- `/dashboard/` updates live, `/ui/` loads, and `/nr/` asks for the editor login.

- [ ] **Step 6: The home page survives the pod**

```bash
sudo systemctl stop traffic-monitor.service
curl -s -o /dev/null -w '%{http_code}\n' http://<pi>/            # expect 200
curl -s -o /dev/null -w '%{http_code}\n' http://<pi>/frigate/    # expect 502
sudo systemctl start traffic-monitor.service
```

- [ ] **Step 7: Re-runs are idempotent, and secrets stay stable and out of the log**

```bash
sudo sha256sum /etc/traffic-monitor/secrets/* > /tmp/secrets-before
bash script/tmsetup.sh -t frigate -t go2rtc -y
sudo sha256sum /etc/traffic-monitor/secrets/* | diff /tmp/secrets-before - && echo "secrets unchanged"
sudo grep -l -F -f /etc/traffic-monitor/secrets/go2rtc_rtsp_password ~/tmsetup-*.log || echo "no secrets in logs"
rm /tmp/secrets-before
```

Expected:
- "Update Frigate config from older installs" reports *ok*, not changed.
- `secrets unchanged`
- `no secrets in logs`

- [ ] **Step 8: The Node-RED `watch` test (spike for M2)**

Follow "Risks to verify early" in the spec:
1. Add a debug node set to "system console" on the `init-config` watch node.
2. Make three comment-only edits of `config.yml`: an in-place append, then two atomic `cp` + `mv` replacements.
3. Expect one `event: 'update'` line in `sudo journalctl -u node-red-tm.service -f` per edit.
4. Clean up with `sed -i '/# watch-test/d'` and `bash script/tmsetup.sh -t node-red-tm`.

Report which of the three edits fired.

- [ ] **Step 9 (only if you need LAN MQTT): Credentials are enforced**

1. Set the broker credentials as `docs/configuration/network-access.md` describes.
2. Run `bash script/tmsetup.sh -C mqtt_lan`.
3. From another computer, run `mosquitto_sub -h <pi> -t '#' -C 1 -W 5` without credentials.

It must be refused. If it isn't, report it: the docs then need to say LAN MQTT isn't supported yet, and the PR must say so.

- [ ] **Step 10: Open the PR to `dev`**

- **Testing section:** steps 1–9 with pass or fail. Never include secret values.
- **Release notes:**
  - Direct ports are closed. Use the `/…` paths.
  - Frigate's restream ports and port 8080 aren't published.
  - RTSP needs credentials.
  - Upgrade with a full `tmsetup.sh` run.
- **AI assistance section:** fill in the template's section.
