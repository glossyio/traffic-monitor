# tm-control M1 (Edge and Ports) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make nginx the only web service listening on the LAN. Every app port moves to loopback, go2rtc's API and stream editing are closed off, and the camera stream requires credentials. Logins don't change yet.

**Architecture:**
- The `revproxy` container leaves the pod and runs on the host network, still proxying to `127.0.0.1:<port>`.
- The pod publishes its ports on `127.0.0.1` only.
- go2rtc's API binds to loopback, its RTSP server requires a generated password, and nginx forwards only go2rtc's viewing paths.
- Existing devices are brought up to date by `tm-control migrate`, a small Python command (the first piece of the tm-control backend). It edits Frigate's `config.yml` round-trip, keeping comments.

**Tech Stack:** Ansible (tmsetup role), Podman Quadlet, nginx 1.31.0, go2rtc 1.9.14, Frigate 0.18.1, Node-RED 5.0.8, Python 3.11+ with ruamel.yaml 0.19.1, pytest.

**Spec:** `design/specs/2026-10-02-tm-control-platform-design.md`, section "Milestones → M1". Read it with this plan.

**Status:** written 2026-10-02 and aligned with the open PRs on 2026-10-13. Re-checked on 2026-10-14 against `dev` after #197, #218, #219, #220, and #222 merged, and against the open stacks' latest pushes. That pass ran Tasks 1, 2, 4, and 5 against a merge of all the stacks, and their expected counts below come from that run. The spec's "Builds on open PRs" section describes the PRs. This plan assumes their files:
- #210's nginx location files
- #212's Cockpit
- #206's dev venv and pytest layout
- #214's `tmdev.py`, and #215's device tests

Don't start until those have merged. Task 0 checks.

**Already done:** the `/storefiles` fix for #211 was made early, on `feature/edge-ports/201` based on #210's head (`579084a`), and was checked on a dev Pi on 2026-10-14. That commit added:
- `container/revproxy/tm/locations/storefiles.conf.j2` and its `tmsetup_revproxy_locations` entry
- `script/tests/tmsetup_render.py` (Task 1 Step 1)
- `script/tests/test_tmsetup_templates.py`, with `LOCATIONS`, `location()`, and the storefiles test
- the CLAUDE.md mention

Tasks 1, 2, 8, and 9 below build on those files instead of creating them.

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
  - Copy the shape of what's there: plain `loop:` templating, one location file per app (#210), and the container trio for container services.
- **Variables:**
  - A fixed value shared by several tasks or templates goes in `vars/main.yml`, like `tmsetup_hailo_driver_dir`. That covers `tmsetup_secrets_dir`, `tmsetup_secret_names`, `tmsetup_tm_control_dir`, and `tmsetup_go2rtc_rtsp_user`.
  - A value an operator may change goes in `defaults/main.yml`, with `-C` for booleans, like `tmsetup_bool_mqtt_lan`.
  - A literal used once, in one file, is hardcoded, like `/frigate`.
- **Pi checks:** run them with `script/devpi/tmdev.py` (`deploy`, `check`, `test`) before committing or opening the PR (Task 9). Keep device names and addresses out of commits and PR text.
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

1. **Upgrading a device that already has `frigate.env` and Frigate's `config.yml`.** tmsetup doesn't overwrite these files without `-f`. After the upgrade, Frigate must still read the camera. The device's config may still be Frigate 0.17's: Frigate 0.18 rewrites it on its first start, after `tm-control migrate` has run. Tests in Tasks 4 and 5 run on both a 0.17 and a 0.18 config. Tests in Task 7 check that the migration produces exactly the URL that new installs get, and that `frigate.env` gains both credential lines.
2. **Re-running `tmsetup.sh`.** The generated secrets must never be regenerated, because the go2rtc and Frigate sides would drift apart. They must never appear in the install log. Tests in Task 3.
3. **The reverse proxy restarting during the upgrade while the old pod still holds port 80.** nginx must come up once the pod releases the port. Tests in Task 2 check the handler order and that the unit keeps retrying.
4. **Crafted `/feeds/` requests.** These must get 403:
   - methods other than GET
   - `src=` values that are URLs or `exec:` sources, raw or percent-encoded
   - go2rtc API paths outside the viewing set (`config`, `log`, `exit`, `restart`, `webrtc`, bare `api`). The viewing set includes HLS's `hls/` paths, which iPhones older than iOS 17 use.

   Tests in Task 2 check the rendered `go2rtc.conf`. Device tests in Task 9 send the same requests to a Pi.
5. **A hand-edited Frigate config that reads go2rtc by LAN IP instead of `host.containers.internal`.** The migration can't rewrite it, so it must warn loudly instead of silently leaving the camera dark. Test in Task 5.
6. **Data export after port 1880 closes (#211).** Both downloads on the Dashboard's database page, the JSON export and the database download, go to `/storefiles?files=…` at the site root. Through the proxy that path returned 404. It worked only on port 1880, so without its own location M1 would leave no way to download data. That's fixed already (see "Already done"), with an off-device test in `test_tmsetup_templates.py`. On a Pi, #215's `test_proxied_locations_respond` and a Task 9 test cover it.

---

### Task 0: Base branch and a re-check against what merged

The design docs are on `feature/tm-control-design/102`, based on `feature/ai-use-policy` (#202). M1's code needs files from both open stacks.

- [ ] **Step 1: Check that the stacks this plan builds on have merged**

Each of these must exist on the base you pick. `origin/dev` is preferred.

```bash
git fetch origin
B=origin/dev
for f in CLAUDE.md script/requirements-dev container/revproxy/tm/locations/go2rtc.conf.j2 \
         container/revproxy/tm/locations/cockpit.conf.j2 script/devpi/tmdev.py script/devpi/tests/test_web.py; do
  git cat-file -e "$B:$f" 2>/dev/null && echo "ok      $f" || echo "MISSING $f"
done
```

If anything is missing, stop and tell the person which PRs haven't merged:
- `tm/locations/*` comes from #210 and #212.
- `requirements-dev` comes from #206.
- `script/devpi/*` comes from #214 and #215.

Don't build M1 on a stack of drafts without asking.

- [ ] **Step 2: Re-check this plan against the merged files**

Merged code may differ from the drafts this plan was written against. Diff the files the tasks below edit against what this plan quotes, and update the plan before starting:

```bash
git show $B:container/revproxy/revproxy.container.j2
git show $B:container/revproxy/tm/locations/go2rtc.conf.j2
git show $B:container/revproxy/tm/locations/cockpit.conf.j2
git show $B:script/ansible/roles/tmsetup/tasks/revproxy_setup.yml | grep -n -A8 'Check NGinx config'
git show $B:script/tmsetup.sh | grep -n -E '_VALID_TAGS=|_VALID_CUSTOM_VARS=|Valid values'
git show $B:script/devpi/tests/test_web.py | head -20
git show $B:script/devpi/tests/test_disruptive.py | head -40
git show $B:script/ansible/roles/tmsetup/files/go2rtc.yaml | grep -o 'exec:[A-Za-z0-9_-]*' | sort -u   # Task 7's exec.allow_paths
git show $B:script/ansible/roles/tmsetup/vars/main.yml | grep -E 'go2rtc_version|frigate_version|node_red_tm_version'
```

On 2026-10-14 all of this matched. The only `exec` command was `rpicam-vid`, and the versions were go2rtc v1.9.14, Frigate 0.18.1, and Node-RED 5.0.8.

- [ ] **Step 3: Move the branch onto the base**

`feature/edge-ports/201` already exists. It's #210's head (`579084a`), plus the design docs merged in, plus the storefiles commit. Replay everything after `579084a` onto the base. That works whether #210 merged as-is or squashed:

```bash
git switch feature/edge-ports/201
git rebase --onto $B 579084a
git log --oneline $B..HEAD   # the design-doc commits and the storefiles commit, nothing from #210
```

If the design docs changed on `origin/feature/tm-control-design/102` after the branch was made, bring those commits too.

---

### Task 1: Template test harness, pod ports on loopback, opt-in LAN MQTT

**Files:**
- Exists: `script/tests/tmsetup_render.py` (from the storefiles commit)
- Modify: `script/tests/test_tmsetup_templates.py` (from the storefiles commit)
- Modify: `container/traffic-monitor.pod.j2`
- Modify: `script/ansible/roles/tmsetup/defaults/main.yml` (after `tmsetup_bool_plate_recognizer: false`)
- Modify: `script/tmsetup.sh` (`_VALID_CUSTOM_VARS` and the `-C` error message)

**Interfaces:**
- Produces, in `script/tests/tmsetup_render.py`:
  - `render(template: str, **variables) -> str`: renders a template given as a repo-relative path, like Ansible's template module.
  - `load_role_yaml(relative_path: str)`: loads a YAML file under `script/ansible/roles/tmsetup/`.
- Produces the install variable `tmsetup_bool_mqtt_lan`, set with `tmsetup.sh -C mqtt_lan`.

- [ ] **Step 1: The render helper (already on the branch)**

The storefiles commit added `script/tests/tmsetup_render.py` with this content. Check it still matches, and don't rewrite it:

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
```

- [ ] **Step 2: Write the failing pod tests**

Append to `script/tests/test_tmsetup_templates.py`, which already has the module docstring, `from tmsetup_render import load_role_yaml, render`, `LOCATIONS`, `location()`, and the storefiles test:

```python


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

Expected: `test_pod_publishes_app_ports_on_loopback_only` FAILS, because the current pod publishes `1880:1880`, `1964:1984`, `80:80`, and so on. The MQTT opt-in test and the storefiles test already pass, since today's pod publishes 1883 on all interfaces. The opt-in test guards the `{% if %}` branch once Step 4 adds it.

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

Expected: 3 passed, then `OK`.

- [ ] **Step 6: Commit**

```bash
git add script/tests/test_tmsetup_templates.py container/traffic-monitor.pod.j2 \
    script/ansible/roles/tmsetup/defaults/main.yml script/tmsetup.sh
git commit -m "Publish pod ports on loopback only; add opt-in LAN MQTT" -m "<trailer block>"
```

---

### Task 2: Reverse proxy on the host network; `/feeds/` limited to viewing

This builds on #210's layout: one location file per app in `container/revproxy/tm/locations/`, listed in `tmsetup_revproxy_locations` (`vars/main.yml`). It also builds on #212's `cockpit.conf`.

**Files:**
- Modify: `container/revproxy/revproxy.container.j2`
- Modify: `container/revproxy/tm/locations/go2rtc.conf.j2`
- Modify: `container/revproxy/tm/locations/cockpit.conf.j2`
- Modify: `script/ansible/roles/tmsetup/tasks/revproxy_setup.yml` (the "Check NGinx config" task)
- Modify: `script/ansible/roles/tmsetup/handlers/main.yml` (move `Restart revproxy.service` after `Restart traffic-monitor.service`)
- Modify: `script/ansible/roles/tmsetup/tasks/start_services.yml` (start `revproxy.service`)
- Test: `script/tests/test_tmsetup_templates.py`
- Test: create `script/tests/test_tmsetup_tasks.py`

**Interfaces:**
- Consumes:
  - `render` and `load_role_yaml` from `tmsetup_render.py`
  - `LOCATIONS` and `location()` from `test_tmsetup_templates.py`
  - `storefiles.conf` from the storefiles commit. It proxies to `127.0.0.1:1880`, so the host network needs no change to it.
- Produces: `/feeds/` accepts only GET and plain stream names, and denies go2rtc API paths beyond viewing. Task 9's device tests check this on a Pi.

- [ ] **Step 1: Write the failing tests**

At the top of `script/tests/test_tmsetup_templates.py`, add `import re` and `import pytest`. The `tmsetup_render` import already includes `load_role_yaml`. Then append:

```python
def revproxy_unit():
    return render("container/revproxy/revproxy.container.j2", tmsetup_codedir="/opt/traffic-monitor").splitlines()


def test_revproxy_runs_on_the_host_network_outside_the_pod():
    unit = revproxy_unit()
    assert "Network=host" in unit
    assert not any(line.startswith("Pod=") for line in unit)


def test_revproxy_keeps_its_bind_mounted_config():
    unit = revproxy_unit()
    assert "Volume=/opt/traffic-monitor/revproxy/nginx.conf:/etc/nginx/nginx.conf:ro" in unit
    assert "Volume=/opt/traffic-monitor/revproxy/tm:/etc/nginx/tm:ro" in unit


def test_revproxy_keeps_retrying_while_port_80_is_still_taken():
    unit = revproxy_unit()
    assert "StartLimitIntervalSec=0" in unit
    assert "RestartSec=5" in unit


@pytest.mark.parametrize("name", LOCATIONS)
def test_no_location_goes_through_host_containers_internal(name):
    assert "host.containers.internal" not in location(name)


def test_host_apps_are_proxied_on_loopback():
    assert "proxy_pass http://127.0.0.1:1984/;" in location("go2rtc.conf")
    assert "proxy_pass http://127.0.0.1:9090/system/;" in location("cockpit.conf")


def test_feeds_accepts_only_get_and_plain_stream_names():
    conf = location("go2rtc.conf")
    assert "limit_except GET { deny all; }" in conf
    assert 'if ($arg_src !~ "^[A-Za-z0-9_-]*$") { return 403; }' in conf


def denied_api_pattern():
    return re.search(r'location ~ "([^"]+)" \{\s*return 403;', location("go2rtc.conf")).group(1)


def src_pattern():
    return re.search(r'\$arg_src !~ "([^"]+)"', location("go2rtc.conf")).group(1)


@pytest.mark.parametrize(
    "path, denied",
    [
        ("/feeds/", False),
        ("/feeds/stream.html", False),
        ("/feeds/video-rtc.js", False),
        ("/feeds/api/ws", False),
        ("/feeds/api/streams", False),
        ("/feeds/api/frame.jpeg", False),
        ("/feeds/api/stream.mp4", False),
        ("/feeds/api/stream.m3u8", False),
        ("/feeds/api/hls/playlist.m3u8", False),
        ("/feeds/api/hls/segment.ts", False),
        ("/feeds/api/hls/segment.m4s", False),
        ("/feeds/api/hls/init.mp4", False),
        ("/feeds/api", True),
        ("/feeds/api/", True),
        ("/feeds/api/config", True),
        ("/feeds/api/log", True),
        ("/feeds/api/exit", True),
        ("/feeds/api/restart", True),
        ("/feeds/api/webrtc", True),
        ("/feeds/api/streams/extra", True),
        ("/feeds/api/streamsX", True),
        ("/feeds/api/hls/", True),
    ],
)
def test_feeds_denies_go2rtc_api_paths_beyond_viewing(path, denied):
    assert bool(re.search(denied_api_pattern(), path)) is denied


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
    assert bool(re.search(src_pattern(), src)) is allowed
```

The regex tests read their patterns from the rendered `go2rtc.conf`, so they test what nginx gets.

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

Expected: most new tests FAIL:
- `go2rtc.conf` and `cockpit.conf` still use `host.containers.internal`.
- `Network=host` is missing.
- There's no deny location.
- `revproxy.service` isn't in the start loop.

On the 2026-10-14 merge of the stacks, with Task 1 and the storefiles commit done, it was 37 failed, 9 passed.

- [ ] **Step 3: Move revproxy to the host network**

Replace `container/revproxy/revproxy.container.j2` with the version below. It keeps #210's bind mounts, drops `Pod=`, and adds the restart settings.

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
Volume={{ tmsetup_codedir }}/revproxy/nginx.conf:/etc/nginx/nginx.conf:ro
Volume={{ tmsetup_codedir }}/revproxy/tm:/etc/nginx/tm:ro

[Service]
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
```

The pod-app location files (`dashboard.conf`, `frigate.conf`, `legacy-ui.conf`, `nodered.conf`) already proxy to `127.0.0.1:<port>`. With Task 1's loopback publishing they keep working unchanged.

- [ ] **Step 4: Point the host apps at loopback and restrict `/feeds/`**

Replace `container/revproxy/tm/locations/go2rtc.conf.j2` with:

```
# go2rtc - Go2RTC Feeds (runs on the host; nginx shares the host network)
# View streams only. go2rtc's API can add stream sources and change its config, so refuse every
# method but GET, any src that isn't a plain stream name, and API paths the players don't use.
location /feeds/ {
    limit_except GET { deny all; }
    if ($arg_src !~ "^[A-Za-z0-9_-]*$") { return 403; }
    proxy_pass http://127.0.0.1:1984/;
    include /etc/nginx/tm/snippets/proxy-common.conf;
}
location ~ "^/feeds/api(?!/(streams|ws|frame\.jpeg|stream\.(mp4|m3u8|mjpeg)|hls/(playlist\.m3u8|segment\.(ts|m4s)|init\.mp4))$)" {
    return 403;
}
```

The regex location is a sibling, not nested. nginx checks regex locations after picking the longest prefix, so for `/feeds/api/config` it wins over `/feeds/` and returns 403. #215's `test_web.py` collects only prefix locations, so it skips this one.

Why the `src` rule is still needed: go2rtc 1.9.12 and later refuses `exec:`, `echo:`, and `expr:` sources sent through its API. A `src` can still be a URL, which makes the device connect to another host, or an `ffmpeg:` source. The `hls/` paths are HLS segments for iPhones older than iOS 17, which can't use MSE.

In `container/revproxy/tm/locations/cockpit.conf.j2`, change the comment and upstream to:

```
# cockpit - Cockpit system administration (runs on the host; nginx shares the host network)
location /system/ {
    proxy_pass http://127.0.0.1:9090/system/;
```

Leave the rest of the file as #212 wrote it.

In `script/ansible/roles/tmsetup/tasks/revproxy_setup.yml`, in the "Check NGinx config" task, delete the line `--add-host host.containers.internal:127.0.0.1`. In the comment above the task, delete the sentence starting `--add-host lets nginx resolve`. No location uses that name anymore, and `nginx -t` needs no name lookups for IP upstreams.

- [ ] **Step 5: Restart and start revproxy after the pod**

In `script/ansible/roles/tmsetup/handlers/main.yml`, move the whole `Restart revproxy.service` handler (its 6 lines) to directly after the `Restart traffic-monitor.service` handler. Handlers run in file order, and the pod must release port 80 first.

In `script/ansible/roles/tmsetup/tasks/start_services.yml`, add `revproxy.service` as the last item of the loop:

```yaml
  loop:
    - go2rtc_server.service
    - traffic-monitor.service
    - revproxy.service
```

- [ ] **Step 6: Run the tests and the Ansible syntax check**

Run:

```bash
.venv/bin/python -m pytest script/tests -v
(cd script/ansible && ../../.venv/bin/ansible-playbook -i localhost setup.yml --syntax-check </dev/null > /tmp/tm-syntax.log 2>&1); echo "exit $?"; tail -3 /tmp/tm-syntax.log
```

Expected: all tests pass (46 so far), then `exit 0`.

The real `nginx -t` runs on the Pi during deploy, in #210's check task, and again in Task 9. For an earlier check, render the config into a scratch directory and run `nginx -t` in `docker.io/library/nginx:1.31.0` with no `--add-host`. On 2026-10-14 that passed for this task's files. A running copy then returned 403 for every denied `/feeds/` request above and proxied every allowed path and `/storefiles`.

- [ ] **Step 7: Commit**

```bash
git add container/revproxy/revproxy.container.j2 container/revproxy/tm/locations/go2rtc.conf.j2 \
    container/revproxy/tm/locations/cockpit.conf.j2 script/ansible/roles/tmsetup/tasks/revproxy_setup.yml \
    script/ansible/roles/tmsetup/handlers/main.yml script/ansible/roles/tmsetup/tasks/start_services.yml script/tests/
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
- Create: `tm-control/backend/tests/fixtures/frigate_config_v0.17.yml` and `frigate_config_v0.18.yml` (generated in step 1)
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
- Produces the pytest fixture `frigate_config`: a `Path` to a 0640 copy of a fixture in `tmp_path/config/config.yml`. It's parametrized, so every test that uses it runs once on the Frigate 0.17 config and once on the 0.18 config.

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

Generate two fixtures before Task 7 changes the template. They stand for the two kinds of existing device:
- `frigate_config_v0.17.yml`: the template from just before #220's Frigate 0.18 bump (`8f3ed72^`), with a Coral USB. Most devices in the field have this config.
- `frigate_config_v0.18.yml`: today's template with no accelerator, which gives #222's `cpu` detector.

```bash
mkdir -p tm-control/backend/tests/fixtures
.venv/bin/python - <<'EOF'
import subprocess
import sys
sys.path.insert(0, "script/tests")
from tmsetup_render import _environment, render


def detectors(accelerator):
    return {
        "edgetpu_usb": {"dev_path": "/dev/bus/usb", "frigate_type": "edgetpu", "frigate_device": "usb",
                        "exists": accelerator, "dev_path_available": accelerator, "fresh_install": False},
        "edgetpu_pci": {"dev_path": "/dev/apex_0", "frigate_type": "edgetpu", "frigate_device": "pci",
                        "exists": False, "dev_path_available": False, "fresh_install": False},
        "hailo8l": {"dev_path": "/dev/hailo0", "frigate_type": "hailo8l", "frigate_device": "PCIe",
                    "exists": False, "dev_path_available": False, "fresh_install": False},
    }


fixtures = "tm-control/backend/tests/fixtures"
v017 = subprocess.check_output(["git", "show", "8f3ed72^:container/frigate/config/config.yml.j2"], text=True)
open(f"{fixtures}/frigate_config_v0.17.yml", "w").write(
    _environment().from_string(v017).render(tmsetup_detectors=detectors(True)))
open(f"{fixtures}/frigate_config_v0.18.yml", "w").write(
    render("container/frigate/config/config.yml.j2", tmsetup_detectors=detectors(False)))
EOF
grep -c 'path: rtsp://host.containers.internal:8554/picam_h265_detect$' tm-control/backend/tests/fixtures/*.yml
grep -h '^version:' tm-control/backend/tests/fixtures/*.yml
```

Expected: a count of 1 for each file, with no credentials in the path. Then `version: 0.17-0` and `version: 0.18-0`. Don't regenerate these fixtures after Task 7.

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


@pytest.fixture(params=["frigate_config_v0.17.yml", "frigate_config_v0.18.yml"])
def frigate_config(request, tmp_path):
    """A copy of Frigate's config.yml as tmsetup rendered it before go2rtc RTSP credentials (synthetic).

    v0.17 is from before Frigate 0.18 (#220), with a Coral USB; v0.18 is from after, with the CPU detector (#222).
    """
    (tmp_path / "config").mkdir()
    path = tmp_path / "config" / "config.yml"
    shutil.copy(FIXTURES / request.param, path)
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
    comments = [line for line in old_lines if line.lstrip().startswith("#")]
    assert len(comments) >= 2
    assert comments == [line for line in new_lines if line.lstrip().startswith("#")]


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

`mapping_indent=2` with `sequence=4, offset=2` reproduces tmsetup's Frigate config byte for byte, for both the 0.17 and the 0.18 template. These are also the settings Frigate 0.18's own config migration uses. Node-RED's `config.yml` uses 4-space mappings, and M2 passes `mapping_indent=4` for it.

- [ ] **Step 5: Run the tests to check they pass**

Run: `.venv/bin/python -m pytest tm-control/backend/tests -v`

Expected: 16 passed (8 tests, each on both fixtures).

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

Expected: 36 passed. The tests that use `frigate_config` run on both fixtures.

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


def go2rtc_config():
    return yaml.safe_load(render(
        "script/ansible/roles/tmsetup/templates/go2rtc.yaml.j2",
        tmsetup_go2rtc_rtsp_user="frigate", tmsetup_secrets=SECRETS,
    ))


def test_go2rtc_api_is_loopback_only_and_rtsp_needs_credentials():
    config = go2rtc_config()
    assert config["api"] == {"listen": "127.0.0.1:1984"}
    assert config["rtsp"] == {"listen": ":8554", "username": "frigate", "password": "s3cret"}
    assert set(config["streams"]) == {"picam_h265_detect", "picam_h265_detect_hr"}


def test_go2rtc_loads_no_webrtc_and_runs_only_allowed_commands():
    config = go2rtc_config()
    assert "webrtc" not in config["app"]["modules"]
    assert "webrtc" not in config
    for name, source in config["streams"].items():
        if source.startswith("exec:"):
            assert source[len("exec:"):].split()[0] in config["exec"]["allow_paths"], name


def test_new_frigate_configs_read_go2rtc_with_credentials():
    config = yaml.safe_load(render("container/frigate/config/config.yml.j2", tmsetup_detectors={}))
    assert config["cameras"]["picam_h265"]["ffmpeg"]["inputs"][0]["path"] == CREDENTIALED_INPUT


def test_frigate_env_carries_the_go2rtc_credentials():
    lines = render(
        "container/frigate/frigate.env.j2",
        tmsetup_frigate_rtsp_password="password", tmsetup_frigate_mqtt_user="mqtt_user",
        tmsetup_frigate_mqtt_password="mqtt_pass", tmsetup_codedir="/opt/traffic-monitor",
        tmsetup_frigate_version="0.18.1",
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

Create `script/ansible/roles/tmsetup/templates/go2rtc.yaml.j2` with this header. After it, copy the stream entries from `script/ansible/roles/tmsetup/files/go2rtc.yaml` unchanged: everything after that file's own `streams:` line, which the header already ends with.

```yaml
# /var/lib/go2rtc/go2rtc.yaml - written by tmsetup.sh (go2rtc tag); edits here are overwritten
app:
  # Load only what the camera, Frigate, and /feeds use. Without the webrtc module, WebRTC is off
  # (webrtc.listen: "" would only drop the fixed port), and players use MSE through the proxy.
  modules: [api, ws, rtsp, exec, ffmpeg, mp4, hls, mjpeg]
api:
  # Only this device can reach the API and web UI; the reverse proxy serves the viewing pages at /feeds/.
  listen: "127.0.0.1:1984"
rtsp:
  # Frigate reads the camera here from the pod, so RTSP stays on all interfaces but needs credentials.
  listen: ":8554"
  username: "{{ tmsetup_go2rtc_rtsp_user }}"
  password: "{{ tmsetup_secrets['go2rtc_rtsp_password'] }}"
exec:
  # Streams may only run rpicam-vid. go2rtc already refuses exec sources sent through its API.
  allow_paths: [rpicam-vid]
streams:
```

`app.modules` and `exec.allow_paths` need go2rtc 1.9.12 or later; #220 pinned 1.9.14. In go2rtc's source, `webrtc.listen: ""` only skips the fixed :8555 listener, and WebRTC still negotiates on random UDP ports. Leaving the module out is what turns WebRTC off. Task 9 Step 6 checks that no go2rtc UDP socket is open. If a stream later needs another command, add it to `allow_paths`; the drift test above fails until you do.

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
git commit -m "Bind go2rtc's API to loopback, require RTSP credentials, and load only the modules TM uses" -m "<trailer block>"
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

The camera feeds page shows the camera streams. It doesn't offer go2rtc's config editor, stream management, or WebRTC. Players use MSE, or HLS on older iPhones.

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
* Data export downloads from the dashboard's database page now work through the home page address.
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
     Its API listens on 127.0.0.1:1984. Its RTSP server needs credentials. Frigate reads `rtsp://{FRIGATE_GO2RTC_RTSP_USER}:{FRIGATE_GO2RTC_RTSP_PASSWORD}@host.containers.internal:8554/picam_h265_detect`; the values are in `frigate.env`, and the password comes from `/etc/traffic-monitor/secrets/` (generated by `tasks/secrets.yml`). `app.modules` leaves out `webrtc`, and `exec.allow_paths` allows only `rpicam-vid`; a new stream command must be added there.
     ```

5. **"Runtime topology"**: replace the UIs bullet (#212's version ends with `host Cockpit \`:9090\``) with:

   ```markdown
   - UIs: the home page on `:80` links to each app. Node-RED editor `/nr/` (admin/password), legacy dashboard `/ui/`, Dashboard 2.0 `/dashboard/`, Frigate `/frigate/`, go2rtc streams `/feeds/` (viewing only), and Cockpit `/system/`. Apart from Cockpit's own `:9090`, its rescue console, nginx is the only web server the LAN can reach.
   ```

6. **"Runtime topology"**, nginx bullet (#210's version, with its location-file sub-bullets):
   - At the start, add:

     ```
     nginx (`revproxy`) runs on the host network, outside the pod, so the home page stays up when the pod is down.
     ```

   - Add a sub-bullet:

     ```markdown
     - `go2rtc.conf` and `cockpit.conf` proxy to `127.0.0.1`. `go2rtc.conf` also limits `/feeds` to viewing: GET only, plain stream names as `src`, and a sibling regex location that returns 403 for go2rtc API paths the players don't use.
     ```

     The storefiles commit already added `/storefiles` to this bullet's list of proxied paths.

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

### Task 9: Device tests and the Pi test plan, through tmdev

This uses #214's `script/devpi/tmdev.py` and #215's device tests, which compare a bench Pi with its expected hardware. Run the Pi test plan before committing this task and before opening the PR:
- Use a dev Pi from the local inventory, never a field device.
- Keep device names and addresses out of commits and PR text.
- Ask the person before any step that reboots the Pi or stops services.

`T` below stands for `.venv/bin/python script/devpi/tmdev.py`.

**Files:**
- Modify: `script/devpi/tests/test_web.py`
- Modify: `script/devpi/tests/test_disruptive.py`

**Interfaces:**
- Consumes:
  - #215's `host` and `hostvars` fixtures, and `wait_until_ready` in `test_disruptive.py`
  - #214's `tmdev.py` commands: `check start|item|status|end`, `deploy`, `run`, and `test`
  - Task 2's `/feeds/` rules
  - Task 7's RTSP credentials

- [ ] **Step 1: Write the device tests**

At the top of `script/devpi/tests/test_web.py`, add `import socket` and `import urllib.error` to the imports. Then append:

```python
# Edge and ports (tm-control M1): from this machine, only nginx answers, and /feeds is view-only.
CLOSED_TO_NETWORK = [1880, 1883, 1984, 5000, 8971]


def pi_address(host, hostvars):
    return hostvars.get("ansible_host", host.backend.hostname)


@pytest.mark.parametrize("port", CLOSED_TO_NETWORK)
def test_app_port_closed_to_the_network(host, hostvars, port):
    """The apps listen on 127.0.0.1 only, so from this machine their ports refuse or time out."""
    with pytest.raises(OSError):
        socket.create_connection((pi_address(host, hostvars), port), timeout=5).close()


def status_from_this_machine(host, hostvars, path, method="GET"):
    request = urllib.request.Request(f"http://{pi_address(host, hostvars)}{path}", method=method)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code


@pytest.mark.parametrize(
    "path, method, expected",
    [
        ("/feeds/", "GET", 200),
        ("/feeds/api/streams", "GET", 200),
        ("/feeds/api", "GET", 403),
        ("/feeds/api/config", "GET", 403),
        ("/feeds/api/log", "GET", 403),
        ("/feeds/api/stream.mp4?src=exec:id", "GET", 403),
        ("/feeds/api/stream.mp4?src=exec%3Aid", "GET", 403),
        ("/feeds/api/streams?src=x", "POST", 403),
    ],
)
def test_feeds_is_view_only_from_this_machine(host, hostvars, path, method, expected):
    assert status_from_this_machine(host, hostvars, path, method) == expected


def test_data_export_reaches_node_red_from_this_machine(host, hostvars):
    """Node-RED answers a download with no files with a message; without the storefiles location nginx answers 404 (#211)."""
    with urllib.request.urlopen(f"http://{pi_address(host, hostvars)}/storefiles", timeout=10) as response:
        assert response.read().decode(errors="replace").strip() == "No files specified"


def test_camera_stream_needs_credentials(host, hostvars):
    """go2rtc's RTSP server answers a DESCRIBE without credentials with 401."""
    address = pi_address(host, hostvars)
    request = f"DESCRIBE rtsp://{address}:8554/picam_h265_detect RTSP/1.0\r\nCSeq: 1\r\n\r\n"
    with socket.create_connection((address, 8554), timeout=5) as connection:
        connection.sendall(request.encode())
        status_line = connection.recv(1024).decode(errors="replace").splitlines()[0]
    assert status_line.startswith("RTSP/1.0 401"), status_line
```

#215's `test_direct_port_responds` stays as it is. It checks the same ports on the Pi's `localhost`, where the apps still answer.

Append to `script/devpi/tests/test_disruptive.py`, which is already marked `disruptive`:

```python
def proxy_status(host, address, path):
    # Host header as a browser's would be, so the nginx image's stock default.conf (server_name localhost) doesn't answer
    return host.check_output(f"curl -s -o /dev/null -w '%{{http_code}}' --max-time 10 -H 'Host: {address}' http://localhost{path}")


def test_home_page_survives_a_stopped_pod(host, hostvars):
    """nginx runs outside the pod, so with the pod stopped the home page loads and the apps answer 502."""
    address = hostvars.get("ansible_host", host.backend.hostname)
    with host.sudo():
        host.check_output("systemctl stop traffic-monitor.service")
    try:
        assert proxy_status(host, address, "/") == "200"
        assert proxy_status(host, address, "/frigate/") == "502"
    finally:
        with host.sudo():
            host.check_output("systemctl start traffic-monitor.service")
        wait_until_ready(host, RESTART_TIMEOUT_SECONDS)
```

- [ ] **Step 2: Check the tests are collected and skip without a dev Pi**

Run:

```bash
.venv/bin/python -m pytest -q -p no:cacheprovider script/devpi/tests
.venv/bin/python -m pytest -q -p no:cacheprovider --collect-only script/devpi/tests/test_web.py script/devpi/tests/test_disruptive.py \
    | grep -c -E 'closed_to_the_network|view_only|needs_credentials|data_export|survives_a_stopped_pod'
```

Expected: everything skipped, because no `TM_DEV_HOSTS` is set, and then `16`.

- [ ] **Step 3: Open the check and record the baseline**

Run these while the Pi still runs the code from before M1:

```bash
$T check start --host <host> --title "M1: edge and ports"        # add --pr <n> once the PR exists
$T test <host> -- -k "closed_to_the_network or view_only or needs_credentials or data_export"
```

Expected: the new tests fail, because ports are open, `/feeds/api/config` answers, RTSP needs no login, and `/storefiles` gets nginx's 404. That shows they catch the problem. The data-export test passes instead if the Pi already runs the storefiles commit (tm-dev units got it on 2026-10-14). Record it:

```bash
$T check item "New device tests fail before M1 is deployed" pass --evidence cmd-NNN
```

- [ ] **Step 4: Deploy the upgrade path**

Ask the person first: a full run can reboot the Pi.

```bash
$T deploy <host>
```

Expected: the run succeeds. In the deploy's `tmsetup.log`, "Update Frigate config from older installs" reports *changed*, and "Check NGinx config" passes. Record an item with the deploy as evidence.

- [ ] **Step 5: Run every device test**

```bash
$T test <host>
```

Expected:
- All pass, including #215's existing ones: `nginx -t`, every proxied location answers (now including `/storefiles`), the direct ports answer on the Pi's `localhost`, and the home page loads from this machine. `test_cameras.py` reads the camera name from Frigate's input path with `:8554/<name>`, which still matches the credentialed URL.
- The 15 new non-disruptive tests pass.

Record an item.

- [ ] **Step 6: Check what listens on the network**

```bash
$T run <host> -- sudo ss -tlnup
```

Expected: apart from `127.0.0.1` and `[::1]`, the only listeners are:
- `:22`
- `:80`
- `:8554` (go2rtc)
- `:5353` (avahi)
- `:9090`, if Cockpit is installed
- DHCP/DNS, only in hotspot mode

Nothing listens on 1880, 1883, 1984, 5000, 8555, or 8971, and go2rtc has no UDP sockets. Repeat the `ss -ulnp` part while a browser plays `/feeds/stream.html?src=picam_h265_detect` (Step 9). go2rtc should still have no UDP socket, which shows WebRTC isn't loaded. Record an item.

- [ ] **Step 7: Check that re-runs keep the secrets and keep them out of the log**

Re-run on the Pi itself, so its install log lands on the Pi where the check can read it:

```bash
$T run <host> -- sudo sha256sum /etc/traffic-monitor/secrets/go2rtc_rtsp_password
$T deploy <host> --on-pi -- -t frigate -t go2rtc
$T run <host> -- sudo sha256sum /etc/traffic-monitor/secrets/go2rtc_rtsp_password
$T run <host> -- sh -c 'sudo grep -l -F -f /etc/traffic-monitor/secrets/go2rtc_rtsp_password ~/tmsetup-*.log || echo "no secrets in logs"'
```

Expected:
- The two hashes match. A hash isn't the secret.
- "Update Frigate config from older installs" reports *ok*, not changed.
- The last command prints `no secrets in logs`.

Record an item.

- [ ] **Step 8: Check the home page survives the pod**

Ask the person first: this stops data capture for a few minutes.

```bash
$T test <host> --disruptive -- -k survives_a_stopped_pod
$T run <host> -- sh -c "sudo journalctl -u frigate.service -b | grep -i -E '401|unauthorized' || echo none"
```

Expected: the test passes, and the journal check prints `none`, meaning Frigate reads the camera with the credentials. Record an item. #215's `test_restart_recovers` and `test_reboot_recovers` also cover M1's restart order. Run the full `--disruptive` set only if the person agrees to a reboot.

- [ ] **Step 9: Record what needs a person**

These need eyes or the Node-RED editor, so record them as `manual`:

```bash
$T check item "/feeds/stream.html?src=picam_h265_detect plays in a desktop browser and on an iPhone (MSE)" manual
$T check item "/frigate/ shows the camera live, not offline" manual
$T check item "/dashboard/ updates live, /ui/ loads, /nr/ asks for the editor login" manual
$T check item "A data export from the /dashboard/ database page downloads through the proxy" manual
$T check item "Node-RED watch test: in-place, then two atomic edits of config.yml each log event 'update'" manual \
    --note "Spec, Risks to verify early"
```

Only if LAN MQTT is needed: after `-C mqtt_lan` and broker credentials, a client without credentials must be refused. If it isn't, the docs must say LAN MQTT isn't supported yet.

When the person reports back, reopen the check with `$T check reopen <run_dir>` and re-record those items as `pass` or `fail`.

- [ ] **Step 10: Close the check and commit**

```bash
$T check status
$T check end
git add script/devpi/tests/test_web.py script/devpi/tests/test_disruptive.py
git commit -m "Add device tests for closed app ports, the view-only /feeds, and the proxy outliving the pod" -m "<trailer block>"
```

- [ ] **Step 11: Open the PR to `dev`**

Ask the person first. Fill in:
- **Testing:** the check's checklist, with device names and addresses replaced by placeholders, plus the off-device results. Never include secret values.
- **Release notes:**
  - Direct app ports are closed; use the `/…` paths.
  - Frigate's restream ports and port 8080 aren't published.
  - The camera stream needs credentials.
  - Data export downloads now work through the proxy.
  - Upgrade with a full `tmsetup.sh` run.
- **AI assistance:** fill in the template's section.
