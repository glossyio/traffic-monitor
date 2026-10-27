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

**Status:** written 2026-10-02, aligned with the open PRs on 2026-10-13, and re-checked on 2026-10-14. Every PR it builds on merged into `dev` on 2026-10-25 (#202, #205, #206, #208, #210, #212, #214, #215), and Task 0 ran the same day:
- It rebased this branch onto `dev` (`e076db0`) and re-checked the plan against the merged files. Step 2 lists what had changed.
- Tasks 1, 2, 3, 8, and 9, and Task 12's collection step, were run on the rebased branch in a scratch worktree. Their expected counts below come from that run.
- Tasks 4 and 5 depend on `dev` only through the Frigate template, unchanged since the 2026-10-14 run, and the render helper. Task 4's fixtures still generate as expected with today's helper.

On 2026-10-26, after #240, #241, #242, and #257 merged, the branch was rebased onto `dev` again (`7c85c70`; Task 0 Step 4) and the plan re-checked:
- #242 put `script/tests/tmsetup_render.py` on `dev` and added 8 HEVC tests to `script/tests`. Two of them skip on machines without Podman or systemd 254, so each step now runs its own test files instead of counting the whole folder.
- #257 reorganized the docs by the reader's task, and #241 added the docs style rules and the PR template's Docs section. Task 11 (docs) is rewritten for both.
- MQTT on the network now needs a login the broker enforces: new Task 10. Docs moved to Task 11, and device tests to Task 12.
- #256 is folded into Task 7.

Tasks 1–3 ran later on 2026-10-26. Task 2's `/feeds/` rules came out stricter than first written. The `src` check could be bypassed, because nginx matches `$arg_src` ignoring case and without decoding the parameter name, while go2rtc decodes names and is case-sensitive. A `dst` parameter also let a WebSocket publish into a stream. Parameter names must now be lowercase and unencoded, and `dst` is refused. Task 2's steps and the counts in Tasks 2 and 3 show the result.

Tasks 4–11 ran the same day. Two changes came out of their reviews, and the steps below include both:
- Task 7 shows `tm-control migrate`'s warnings, which went to stderr and stayed hidden on a normal run.
- Task 8 accepts only plain file names in a download request, and puts `--` before them in tar's arguments. Before, a name with spaces passed the folder check and gave tar extra options, including one that runs a command. Traversal names now get 400 instead of 403, and Task 12's device tests expect that.

The spec's "Builds on merged PRs" section describes the PRs. This plan uses their files:
- #210's nginx location files
- #212's Cockpit
- #206's dev venv and pytest layout
- #214's `tmdev.py`, and #215's device tests

**Decisions, 2026-10-25:**
- **Cockpit's `:9090` stays open** as the rescue console. It's a plain-HTTP login outside the proxy, so M2's login at the proxy won't cover it. But binding it to `127.0.0.1` would leave SSH as the only rescue when Podman or nginx is broken. #212's review raised the question on 2026-10-23.
- **#232 is folded in as Task 9**, because Task 1 edits the same pod unit. Docs became Task 10, and device tests Task 11. Since 2026-10-26 they're Tasks 11 and 12.

**Decisions, 2026-10-26:**
- **MQTT on the network needs a login the broker enforces.** The Aedes broker checked no login, so the spec's "requires broker credentials" wasn't true. `-C mqtt_lan` also lasted only one installer run, because the pod unit is rewritten on every run. Now port 1883 opens to the network exactly when `node-red-tm.env` sets `TM_MQTT_BROKER_USERNAME` and `TM_MQTT_BROKER_PASSWORD`, and the broker enforces them (Task 10).
- **#256 is folded into Task 7**, for new installs and `-f` runs.
- **The ports table gets its own Reference page**, `docs/reference/network.md` (Task 11).

**Already done:** the `/storefiles` fix for #211 was made early on `feature/edge-ports/201`, and was checked on a dev Pi on 2026-10-14. Task 0 rebased it onto `dev`, so that check covered an older tree; Task 12 checks `/storefiles` again. That commit added:
- `container/revproxy/tm/locations/storefiles.conf.j2` and its `tmsetup_revproxy_locations` entry
- `script/tests/tmsetup_render.py` (Task 1 Step 1). Since the 2026-10-26 rebase it comes from `dev`, where #242 added an identical copy.
- `script/tests/test_tmsetup_templates.py`, with `LOCATIONS`, `location()`, and the storefiles test
- the CLAUDE.md mention

Tasks 1, 2, 11, and 12 below build on those files instead of creating them.

**Folded in:** #223 is Task 8. Download errors came back as 200, and a failed `tar` left the download open. #208 also edited `flows.json`, though not these nodes. On 2026-10-25, Task 8's script ran cleanly on the merged `dev`'s `flows.json`, and the schema tests still passed. #232 is Task 9: the pod stayed down after `tmnet-network.service` failed once at boot. #256 is in Task 7: new installs no longer publish Frigate's object snapshots on MQTT.

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
  - The MQTT broker login is an operator setting in `node-red-tm.env`, not a device secret (Task 10).
- **Pi checks:** run them with `script/devpi/tmdev.py` (`deploy`, `check`, `test`) before committing or opening the PR (Task 12). Keep device names and addresses out of commits and PR text.
- **Python:** indented with 4 spaces, with a docstring for each module. No AI-provenance comments.
- **Tests:**
  - Synthetic data only.
  - Test module basenames must be unique across the repo, because pytest's default import mode needs it.
  - Don't name new helper modules `helpers.py`, and don't `import conftest`.
  - Run each step's own test files. `script/tests` also holds #242's HEVC tests, two of which skip on machines without Podman or systemd 254, so a count of the whole folder depends on the machine.
- **Docs:** user docs under `docs/` are built with Material for MkDocs (see "Writing docs" in `docs/development/contributing.md`). Use admonitions (`!!! warning`), relative `.md` links, and Markdown images in `docs/assets/images/`. A new page must be added to `nav:` in `mkdocs.yml`. Check with `mkdocs build --strict`. Design docs live under `design/` and aren't published. Follow the style rules under "Writing docs", and list the changed pages in the PR's Docs section.
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

These are the likeliest failures for a person upgrading or using a device. Each one has a test in the task that owns it.

1. **Upgrading a device that already has `frigate.env` and Frigate's `config.yml`.** tmsetup doesn't overwrite these files without `-f`. After the upgrade, Frigate must still read the camera. The device's config may still be Frigate 0.17's: Frigate 0.18 rewrites it on its first start, after `tm-control migrate` has run. Tests in Tasks 4 and 5 run on both a 0.17 and a 0.18 config. Tests in Task 7 check that the migration produces exactly the URL that new installs get, and that `frigate.env` gains both credential lines.
2. **Re-running `tmsetup.sh`.** The generated secrets must never be regenerated, because the go2rtc and Frigate sides would drift apart. They must never appear in the install log. Tests in Task 3.
3. **The reverse proxy restarting during the upgrade while the old pod still holds port 80.** nginx must come up once the pod releases the port. Tests in Task 2 check the handler order and that the unit keeps retrying. On a Pi, #215's `test_no_crash_restarts[revproxy.service]` fails if revproxy still had to retry after the handler restarted it (Task 12 Step 5).
4. **Crafted `/feeds/` requests.** These must get 403:
   - methods other than GET
   - `src=` values that are URLs or `exec:` sources, raw or percent-encoded
   - parameter names that are upper-case or percent-encoded (`SRC=`, `%73rc=`), which nginx and go2rtc read differently
   - `dst=`, which makes a WebSocket publish into a stream instead of viewing it
   - go2rtc API paths outside the viewing set (`config`, `log`, `exit`, `restart`, `webrtc`, bare `api`). The viewing set includes HLS's `hls/` paths, which iPhones older than iOS 17 use.

   Tests in Task 2 check the rendered `go2rtc.conf`. Device tests in Task 12 send the same requests to a Pi.
5. **A hand-edited Frigate config that reads go2rtc by LAN IP instead of `host.containers.internal`.** The migration can't rewrite it, so it must warn loudly instead of silently leaving the camera dark. Test in Task 5.
6. **Data export after port 1880 closes (#211).** Both downloads on the Dashboard's database page, the JSON export and the database download, go to `/storefiles?files=…` at the site root. Through the proxy that path returned 404. It worked only on port 1880, so without its own location M1 would leave no way to download data. That's fixed already (see "Already done"), with an off-device test in `test_tmsetup_templates.py`. On a Pi, #215's `test_proxied_locations_respond` and a Task 12 test cover it. The endpoint's errors also came back as 200, and a `tar` failure left the download open (#223). Task 8 fixes both, and Task 12 tests them on a Pi.
7. **A failed start of `tmnet-network.service` at boot (#232).** The pod must still start, because the network it uses persists on disk. Test in Task 9 for the rendered unit; Task 12's disruptive device test makes the network unit fail once on a Pi.
8. **MQTT on the network.** Port 1883 must open only with a login the broker enforces, and stay that way through `-t` runs, `-f`, and updates. A device that already had `TM_MQTT_BROKER_USERNAME` and `TM_MQTT_BROKER_PASSWORD` set must keep Frigate connected, so the installer copies the login into `frigate.env`. A missing key must never reach Node-RED: it would keep the literal `${…}` text, and the broker would require it as the login. Tests in Task 10; device tests in Task 12.

---

### Task 0: Base branch and a re-check against what merged

Done on 2026-10-25, after the stacks merged, and run again on 2026-10-26 (Step 4). The steps stay as a record, and to re-run if `dev` moves before M1 starts.

- [x] **Step 1: Check that the stacks this plan builds on have merged**

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

On 2026-10-25 all six files were on `origin/dev` (`e076db0`).

- [x] **Step 2: Re-check this plan against the merged files**

Merged code may differ from the drafts this plan was written against. Diff the files the tasks below edit against what this plan quotes, and update the plan before starting:

```bash
git show $B:container/revproxy/revproxy.container.j2
git show $B:container/revproxy/tm/locations/go2rtc.conf.j2
git show $B:container/revproxy/tm/locations/cockpit.conf.j2
git show $B:script/ansible/roles/tmsetup/tasks/revproxy_setup.yml | grep -n -B2 -A8 'Check NGinx config$'
git show $B:script/tmsetup.sh | grep -n -E '_VALID_TAGS=|_VALID_CUSTOM_VARS=|Valid values'
git show $B:script/devpi/tests/test_web.py | head -20
git show $B:script/devpi/tests/test_disruptive.py | head -40
git show $B:script/ansible/roles/tmsetup/files/go2rtc.yaml | grep -o 'exec:[A-Za-z0-9_-]*' | sort -u   # Task 7's exec.allow_paths
git show $B:script/ansible/roles/tmsetup/vars/main.yml | grep -E 'go2rtc_version|frigate_version|node_red_tm_version'
```

On 2026-10-14 all of this matched. On 2026-10-25 these had changed in the final merges, and the tasks below now follow `dev`:
- **`revproxy.container.j2`** takes its config mounts from `tmsetup_revproxy_config_mounts` in `vars/main.yml`, a list the `nginx -t` check uses too (#210). Task 2 keeps that loop, and its unit test passes the list.
- **The "Check NGinx config" task** runs `nginx -t` with the `containers.podman.podman_container` module. It resolves `host.containers.internal` through `etc_hosts`, not `--add-host` (#210). Task 2 Step 4 removes the `etc_hosts` entry.
- **`cockpit.conf.j2`** has a comment between `location` and `proxy_pass` (#212). Task 2 Step 4 now shows the whole file.
- **`README.md`** lists Cockpit as a fifth app (#212), so the list moved down a line. `docs/setup-guide.md`'s Frigate address is now on line 70. Task 11 follows both.
- **`test_web.py`** already imports `urllib.error` (Task 12 Step 1).
- **`tmdev.py run`** joins the words after `--` and runs them in the Pi's login shell. Task 12 now passes compound commands as one quoted word instead of `sh -c`.

Everything else still matched:
- the `tmsetup.sh` lines;
- `rpicam-vid` as the only `exec` command;
- go2rtc v1.9.14, Frigate 0.18.1, and Node-RED 5.0.8;
- the handler, start-services, and main task names;
- Frigate's camera input path;
- every node id and quoted function text in Task 8.

- [x] **Step 3: Move the branch onto the base**

`feature/edge-ports/201` sat on #210's final review-fix head, `a473ec1`, which is also its merge base with `dev`. So a plain rebase replays only this branch's commits:

```bash
git switch feature/edge-ports/201
git rebase origin/dev
git log --oneline origin/dev..HEAD   # the design-doc commits and the storefiles commit, nothing from #210
```

On 2026-10-25 this replayed 11 commits, with two conflicts:
- `CLAUDE.md`, in the list of proxied paths: keep `dev`'s `/system` and this branch's `/storefiles`.
- `.gitignore`: take `dev`'s, which already ignores `__pycache__/` and `.pytest_cache/`. The commit that added those lines now changes only `tmsetup_render.py`, and its message no longer mentions them.

`git range-diff a473ec1..origin/feature/edge-ports/201 origin/dev..HEAD` showed the other nine commits unchanged. `git diff --stat origin/dev` listed only the design docs, `storefiles.conf.j2` and its `vars/main.yml` line, `script/tests/`, and the CLAUDE.md line. The off-device checks passed: 70 tests (`script/tests` and the schema tests), the Ansible syntax check, the template parse, `flows.json`, and `bash -n`. Every patch from `feature/tm-control-design/102` was already on this branch.

The push followed the same day. Draft PR #224 targets `dev`: GitHub moved it there when #210's branch was deleted. To push a rebase, ask the person first, then:

```bash
git push --force-with-lease origin feature/edge-ports/201
gh pr view 224 --json baseRefName,mergeable,commits --jq '.baseRefName, .mergeable, (.commits | length)'   # dev, MERGEABLE, 11
```

`gh pr edit` fails on this repo with a Projects (classic) error. To change the PR's base or description, use `gh api -X PATCH repos/glossyio/traffic-monitor/pulls/224 -f base=dev` (or `-F body=@<file>`).

- [x] **Step 4: Rebase again after the 2026-10-26 merges**

#240, #241, #242, and #257 merged after Step 3. On 2026-10-26 the branch was rebased onto `dev` (`7c85c70`) in a worktree:

```bash
git rebase origin/dev
# CONFLICT (add/add) in script/tests/tmsetup_render.py: #242 added the same file to dev
git checkout --ours script/tests/tmsetup_render.py && git add script/tests/tmsetup_render.py
git rebase --continue   # drops "Give the template test helper all of Ansible's filters": already upstream
```

`dev`'s copy of the helper is identical to this branch's final one, so keeping it changes nothing. 13 commits became 12, and the storefiles commit's message now says the helper comes from #242. The 78 off-device tests passed (69 schema, 8 HEVC, 1 storefiles). The plan was then re-checked against the merged files; Status lists what changed.

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
- Produces the install variable `tmsetup_bool_mqtt_lan`, set with `tmsetup.sh -C mqtt_lan`. Task 10 makes it create a broker login.
- Consumes the fact `tmsetup_mqtt_lan_open`, which Task 10 sets. Until then it's undefined, and the pod keeps 1883 on loopback.

- [x] **Step 1: The render helper (already on the branch)**

The storefiles commit added `script/tests/tmsetup_render.py` with this content. Check it still matches, and don't rewrite it:

```python
"""Render tmsetup role templates the way Ansible's template module does, so tests can check them off-device.

Uses Jinja2 with Ansible's filters, Ansible's trim_blocks default, and StrictUndefined, so a template
that needs a variable the test didn't pass fails loudly. Jinja's own `default`/`d` are kept because
ansible-core 2.19+ replaces them with versions that don't recognize plain Jinja undefined values.
"""

import functools
from pathlib import Path

import jinja2
import yaml
from ansible.plugins.filter import core, encryption, mathstuff, urls, urlsplit

REPO = Path(__file__).resolve().parents[2]
ROLE = REPO / "script" / "ansible" / "roles" / "tmsetup"


@functools.cache
def _environment():
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(REPO)),
        undefined=jinja2.StrictUndefined,
        trim_blocks=True,
        keep_trailing_newline=True,
    )
    for module in (core, encryption, mathstuff, urls, urlsplit):
        env.filters.update({name: f for name, f in module.FilterModule().filters().items() if name not in ("default", "d")})
    return env


def render(template, **variables):
    """Render a template given by its path relative to the repo root."""
    return _environment().get_template(template).render(**variables)


def load_role_yaml(relative_path):
    """Load a YAML file from the tmsetup role, e.g. 'vars/main.yml' or 'tasks/secrets.yml'."""
    return yaml.safe_load((ROLE / relative_path).read_text())
```

- [x] **Step 2: Write the failing pod tests**

Append to `script/tests/test_tmsetup_templates.py`, which already has the module docstring, `from tmsetup_render import load_role_yaml, render`, `LOCATIONS`, `location()`, and the storefiles test:

```python


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
```

- [x] **Step 3: Run the tests to check they fail**

Run: `.venv/bin/python -m pytest script/tests/test_tmsetup_templates.py -v`

Expected: `test_pod_publishes_app_ports_on_loopback_only` FAILS, because the current pod publishes `1880:1880`, `1964:1984`, `80:80`, and so on. The MQTT test and the storefiles test already pass, since today's pod publishes 1883 on all interfaces. The MQTT test guards the `{% if %}` branch once Step 4 adds it.

- [x] **Step 4: Bind the pod's ports to loopback**

In `container/traffic-monitor.pod.j2`, replace the ten `PublishPort=` lines (from `PublishPort=1880:1880` through `PublishPort=80:80`) with:

```
# Published on 127.0.0.1 only: the reverse proxy (host network) and host services reach these,
# the LAN doesn't. Every app is served to the network by the reverse proxy on port 80.
PublishPort=127.0.0.1:1880:1880
{% if tmsetup_mqtt_lan_open | default(false) | bool %}
# MQTT on all interfaces, because node-red-tm.env sets a broker login the broker enforces (tasks/mqtt_broker.yml).
PublishPort=1883:1883
{% else %}
PublishPort=127.0.0.1:1883:1883
{% endif %}
PublishPort=127.0.0.1:5000:5000
PublishPort=127.0.0.1:8971:8971
```

This drops 1964 (Frigate's go2rtc), 8080 (plate-recognizer), 8564–8566 (Frigate restream and WebRTC), and 80, which moves to the host-network nginx in Task 2. Until Task 10 sets `tmsetup_mqtt_lan_open`, 1883 stays on loopback.

In `script/ansible/roles/tmsetup/defaults/main.yml`, after `tmsetup_bool_plate_recognizer: false`, add:

```yaml
# Creates an MQTT broker login in node-red-tm.env if it has none (tmsetup.sh -C mqtt_lan).
# The login is what opens port 1883 to the network; see tasks/mqtt_broker.yml.
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

#229, which builds the `ansible-playbook` command as a bash array, changes other lines of `tmsetup.sh`. If it merges first, these two edits still apply as written.

- [x] **Step 5: Run the tests and syntax checks**

Run: `.venv/bin/python -m pytest script/tests/test_tmsetup_templates.py -v && bash -n script/tmsetup.sh && echo OK`

Expected: 3 passed, then `OK`.

- [x] **Step 6: Commit**

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
- Produces: `/feeds/` accepts only GET, lowercase unencoded parameter names, no `dst`, and plain stream names in `src`, and denies go2rtc API paths beyond viewing. Task 12's device tests check this on a Pi.

- [x] **Step 1: Write the failing tests**

At the top of `script/tests/test_tmsetup_templates.py`, add `import re` and `import pytest`. The `tmsetup_render` import already includes `load_role_yaml`. Then append:

```python
def revproxy_unit():
    return render(
        "container/revproxy/revproxy.container.j2",
        tmsetup_codedir="/opt/traffic-monitor",
        tmsetup_revproxy_config_mounts=load_role_yaml("vars/main.yml")["tmsetup_revproxy_config_mounts"],
    ).splitlines()


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
    assert "proxy_pass http://127.0.0.1:9090;" in location("cockpit.conf")


def test_feeds_accepts_only_get_and_plain_stream_names():
    conf = location("go2rtc.conf")
    assert "limit_except GET { deny all; }" in conf
    assert 'if ($arg_src !~ "^[A-Za-z0-9_-]*$") { return 403; }' in conf
    assert 'if ($args !~ "^([a-z0-9_]+(=[^&]*)?(&|$))*$") { return 403; }' in conf
    assert "if ($arg_dst) { return 403; }" in conf


def denied_api_pattern():
    return re.search(r'location ~ "([^"]+)" \{\s*return 403;', location("go2rtc.conf")).group(1)


def src_pattern():
    return re.search(r'\$arg_src !~ "([^"]+)"', location("go2rtc.conf")).group(1)


def args_pattern():
    return re.search(r'\$args !~ "([^"]+)"', location("go2rtc.conf")).group(1)


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
        ("/feeds/api/stream.mjpeg", False),
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


@pytest.mark.parametrize(
    "args, allowed",
    [
        ("", True),
        ("src=picam_h265_detect", True),
        ("src=a&src=b&mode=webrtc%2Cmse&width=50%25&background=false", True),
        ("id=Ab12cd", True),
        ("%73rc=rtsp://192.0.2.1/x", False),
        ("SRC=picam_h265_detect&src=rtsp://192.0.2.1/x", False),
        ("Src=rtsp://192.0.2.1/x", False),
        ("s+rc=rtsp://192.0.2.1/x", False),
    ],
)
def test_feeds_accepts_only_plain_parameter_names(args, allowed):
    """nginx matches $arg_src ignoring case and undecoded; go2rtc decodes names and is case-sensitive."""
    assert bool(re.search(args_pattern(), args)) is allowed
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

- [x] **Step 2: Run the tests to check they fail**

Run: `.venv/bin/python -m pytest script/tests/test_tmsetup_templates.py script/tests/test_tmsetup_tasks.py -v`

Expected: most new tests FAIL:
- `go2rtc.conf` and `cockpit.conf` still use `host.containers.internal`.
- `Network=host` is missing.
- There's no deny location.
- `revproxy.service` isn't in the start loop.

On 2026-10-25, with Task 1 done, those two files gave 37 failed, 9 passed. With the parameter-name, `dst`, and `stream.mjpeg` tests added on 2026-10-26, the count is 46 failed, 9 passed.

- [x] **Step 3: Move revproxy to the host network**

Replace `container/revproxy/revproxy.container.j2` with the version below. It keeps #210's bind mounts, including the `tmsetup_revproxy_config_mounts` loop that the `nginx -t` check shares. It drops `Pod=` and adds the restart settings.

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
{% for mount in tmsetup_revproxy_config_mounts %}
Volume={{ tmsetup_codedir }}/revproxy/{{ mount['path'] }}:{{ mount['target'] }}:ro
{% endfor %}

[Service]
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
```

The pod-app location files (`dashboard.conf`, `frigate.conf`, `legacy-ui.conf`, `nodered.conf`) already proxy to `127.0.0.1:<port>`. With Task 1's loopback publishing they keep working unchanged.

- [x] **Step 4: Point the host apps at loopback and restrict `/feeds/`**

Replace `container/revproxy/tm/locations/go2rtc.conf.j2` with:

```
# go2rtc - Go2RTC Feeds (runs on the host; nginx shares the host network)
# View streams only. go2rtc's API can add stream sources and change its config, so refuse every
# method but GET, any src that isn't a plain stream name, and API paths the players don't use.
location /feeds/ {
    limit_except GET { deny all; }
    # Parameter names must be lowercase and unencoded. nginx finds $arg_src ignoring case and
    # without decoding it, but go2rtc decodes names and tells SRC from src, so ?%73rc= or
    # ?SRC=x&src= would pass a URL source to go2rtc unchecked.
    if ($args !~ "^([a-z0-9_]+(=[^&]*)?(&|$))*$") { return 403; }
    # dst publishes into a stream instead of viewing it, e.g. go2rtc's WebRTC page over the WebSocket
    if ($arg_dst) { return 403; }
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

Why the parameter-name rule: without it, `?%73rc=rtsp://…` gives nginx an empty `$arg_src`, and `?SRC=x&src=rtsp://…` gives it `x`, while go2rtc (Go's `net/url`) reads the URL in both cases. With names limited to lowercase and unencoded, nginx and go2rtc read the same `src`. go2rtc's own players send only such names (`src`, `mode`, `width`, `background`, and `id` on HLS paths).

Why `dst` is refused: in go2rtc 1.9.14, `GET /api/ws?dst=<stream>` followed by a `webrtc/offer` message adds a producer to that stream (`internal/webrtc/webrtc.go`). Task 7 leaves the `webrtc` module out, but `/feeds/` should be view-only on its own. Its other `dst` handlers need POST, or sit on paths the regex location denies. No viewing request uses `dst`.

In `container/revproxy/tm/locations/cockpit.conf.j2`, change the first comment and the upstream. The whole file becomes:

```
# cockpit - Cockpit system administration (runs on the host; nginx shares the host network)
location /system/ {
    # No URI after the port, so nginx passes Cockpit's request URI through unchanged
    proxy_pass http://127.0.0.1:9090;
    include /etc/nginx/tm/snippets/proxy-common.conf;
    # Per Cockpit's nginx guidance: stream responses, and keep ETags (gzip drops them)
    proxy_buffering off;
    gzip off;
}
```

In `script/ansible/roles/tmsetup/tasks/revproxy_setup.yml`, find the "Check NGinx config" task inside the "Check NGinx config before deploying it" block. Delete its `etc_hosts:` key and the `host.containers.internal: 127.0.0.1` line under it. In the comment above the task, delete the line `# etc_hosts lets nginx resolve the go2rtc upstream inside the container.` No location uses that name anymore, and `nginx -t` needs no name lookups for IP upstreams.

- [x] **Step 5: Restart and start revproxy after the pod**

In `script/ansible/roles/tmsetup/handlers/main.yml`, move the whole `Restart revproxy.service` handler (its 6 lines) to directly after the `Restart traffic-monitor.service` handler. Handlers run in file order, and the pod must release port 80 first.

In `script/ansible/roles/tmsetup/tasks/start_services.yml`, add `revproxy.service` as the last item of the loop:

```yaml
  loop:
    - go2rtc_server.service
    - traffic-monitor.service
    - revproxy.service
```

- [x] **Step 6: Run the tests and the Ansible syntax check**

Run:

```bash
.venv/bin/python -m pytest script/tests/test_tmsetup_templates.py script/tests/test_tmsetup_tasks.py -v
(cd script/ansible && ../../.venv/bin/ansible-playbook -i localhost setup.yml --syntax-check </dev/null > /tmp/tm-syntax.log 2>&1); echo "exit $?"; tail -3 /tmp/tm-syntax.log
```

Expected: all tests pass (55 in those two files), then `exit 0`.

The real `nginx -t` runs on the Pi during deploy, in #210's check task, and again in Task 12. For an earlier check, render `nginx.conf`, `tm/snippets/proxy-common.conf`, and the listed location files into a scratch directory with `tmsetup_render.render`; they need no variables. Then run `nginx -t` on them in `docker.io/library/nginx:1.31.0` with no host alias. On 2026-10-25 that passed for this task's files. A running copy then returned 403 for every denied `/feeds/` request above. It proxied every allowed path, `/storefiles`, `/system/`, and `/frigate/`, which answered 502 because no apps were running. Send a `Host:` header other than `localhost`, or the image's stock `default.conf` answers.

- [x] **Step 7: Commit**

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

- [x] **Step 1: Write the failing tests**

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

- [x] **Step 2: Run the tests to check they fail**

Run: `.venv/bin/python -m pytest script/tests/test_tmsetup_tasks.py -v`

Expected: the four new tests FAIL with `FileNotFoundError` (no `tasks/secrets.yml` yet) or `ValueError` (task not in `main.yml`).

- [x] **Step 3: Write the secrets task file**

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

The MQTT broker login isn't one of these secrets. It's an operator setting in `node-red-tm.env` that the operator also gives to their own MQTT clients, so a second copy here would go stale (Task 10).

- [x] **Step 4: Register the variables and the import**

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

- [x] **Step 5: Run the tests and the Ansible checks**

Run:

```bash
.venv/bin/python -m pytest script/tests/test_tmsetup_templates.py script/tests/test_tmsetup_tasks.py -v
(cd script/ansible && ../../.venv/bin/ansible-playbook -i localhost setup.yml --syntax-check </dev/null > /tmp/tm-syntax.log 2>&1); echo "exit $?"; tail -3 /tmp/tm-syntax.log
```

Expected: all tests pass (59 in those two files), then `exit 0`.

- [x] **Step 6: Commit**

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

- [x] **Step 1: Add the dependency and the test fixture**

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

- [x] **Step 2: Write the failing tests**

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

- [x] **Step 3: Run the tests to check they fail**

Run: `.venv/bin/python -m pytest tm-control/backend/tests -v`

Expected: collection ERROR, `ModuleNotFoundError: No module named 'tm_control'`.

- [x] **Step 4: Write the package**

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

- [x] **Step 5: Run the tests to check they pass**

Run: `.venv/bin/python -m pytest tm-control/backend/tests -v`

Expected: 16 passed (8 tests, each on both fixtures).

- [x] **Step 6: Commit**

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

- [x] **Step 1: Write the failing tests**

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

- [x] **Step 2: Run the tests to check they fail**

Run: `.venv/bin/python -m pytest tm-control/backend/tests -v`

Expected: collection ERROR, `ImportError: cannot import name 'migrate' from 'tm_control.core'` (or no module `tm_control.cli`).

- [x] **Step 3: Write the migration and the command line**

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

- [x] **Step 4: Run the tests to check they pass**

Run: `.venv/bin/python -m pytest tm-control/backend/tests -v`

Expected: 36 passed. The tests that use `frigate_config` run on both fixtures.

- [x] **Step 5: Commit**

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

- [x] **Step 1: Write the failing tests**

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

- [x] **Step 2: Run the tests to check they fail**

Run: `.venv/bin/python -m pytest script/tests -v`

Expected: the new tests FAIL with `TemplateNotFound`, `KeyError: 'tmsetup_tm_control_dir'`, and `FileNotFoundError`.

- [x] **Step 3: Write the wrapper template, the task file, and the symlink**

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

- [x] **Step 4: Register the variables, package, import, and tag**

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

- [x] **Step 5: Run the tests and Ansible checks**

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

- [x] **Step 6: Commit**

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
- Modify: `container/frigate/config/config.yml.j2` (camera input path, and `mqtt: enabled: false` for #256)
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

- [x] **Step 1: Write the failing tests**

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


def test_new_frigate_configs_keep_object_snapshots_off_mqtt():
    """Frigate publishes a cropped snapshot of each object on MQTT unless the camera turns it off (#256)."""
    config = yaml.safe_load(render("container/frigate/config/config.yml.j2", tmsetup_detectors={}))
    assert config["cameras"]["picam_h265"]["mqtt"] == {"enabled": False}

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


def test_frigate_env_template_hides_its_diff():
    """frigate.env.j2 renders the go2rtc RTSP password, and a -f run with -a diff would print it into ~/tmsetup-*.log."""
    task = frigate_tasks()["TMSetup - Frigate Setup - Create Frigate container configuration files"]
    assert task["diff"] is False


def test_existing_frigate_config_is_migrated_as_the_code_owner():
    task = frigate_tasks()["TMSetup - Frigate Setup - Update Frigate config from older installs"]
    argv = task["ansible.builtin.command"]["argv"]
    assert argv[:4] == ["/usr/sbin/runuser", "-u", "{{ tmsetup_codeowner }}", "--"]
    assert argv[4:6] == ["/usr/local/bin/tm-control", "migrate"]
    assert task["notify"] == "Restart frigate.service"


def test_frigate_config_update_warnings_are_shown():
    """migrate warns on stderr and exits 0; Ansible hides a successful command's stderr without -v."""
    names = list(frigate_tasks())
    show = frigate_tasks()["TMSetup - Frigate Setup - Show warnings from the Frigate config update"]
    assert names.index("TMSetup - Frigate Setup - Show warnings from the Frigate config update") == (
        names.index("TMSetup - Frigate Setup - Update Frigate config from older installs") + 1
    )
    assert show["ansible.builtin.debug"]["msg"] == "{{ tmsetup_frigate_migrate_register.stderr_lines }}"
    assert "WARNING" in show["when"]


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

- [x] **Step 2: Run the tests to check they fail**

Run: `.venv/bin/python -m pytest script/tests tm-control/backend/tests -v`

Expected: the new tests FAIL with `TemplateNotFound: .../go2rtc.yaml.j2`, the old input path, the missing `mqtt` key, `KeyError` for the new task names, and the drift test failing.

- [x] **Step 3: Write the go2rtc template**

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

`app.modules` and `exec.allow_paths` need go2rtc 1.9.12 or later; #220 pinned 1.9.14. In go2rtc's source, `webrtc.listen: ""` only skips the fixed :8555 listener, and WebRTC still negotiates on random UDP ports. Leaving the module out is what turns WebRTC off. Task 12 Step 6 checks that no go2rtc UDP socket is open. If a stream later needs another command, add it to `allow_paths`; the drift test above fails until you do.

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

- [x] **Step 4: Point Frigate at the credentialed stream**

In `container/frigate/config/config.yml.j2`, change:

```yaml
        - path: rtsp://host.containers.internal:8554/picam_h265_detect
```

to:

```yaml
        - path: rtsp://{FRIGATE_GO2RTC_RTSP_USER}:{FRIGATE_GO2RTC_RTSP_PASSWORD}@host.containers.internal:8554/picam_h265_detect
```

Under `cameras: picam_h265:`, after `type: generic`, add (#256):

```yaml
    mqtt:
      enabled: false
```

Frigate then stops publishing each object's snapshot on MQTT. `frigate/events`, which Node-RED counts, is unaffected. This reaches new installs and `-f` runs; existing devices keep their setting, and the docs say how to turn the snapshots off.

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

In `script/ansible/roles/tmsetup/tasks/frigate_setup.yml`, add `diff: false` to `TMSetup - Frigate Setup - Create Frigate container configuration files`, after `become: true`. That task renders `frigate.env.j2`, which now holds the password (Global Constraints). Then, directly after that task, add:

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

- name: TMSetup - Frigate Setup - Show warnings from the Frigate config update
  ansible.builtin.debug:
    msg: '{{ tmsetup_frigate_migrate_register.stderr_lines }}'
  when: "'WARNING' in tmsetup_frigate_migrate_register.stderr"
```

`frigate.env` and `config.yml` aren't overwritten without `-f`. The first task gives existing devices the credentials. The second rewrites their camera input, keeping comments and writing a backup, and does nothing on new installs. It runs as the code owner through `runuser`, like the tmdb migration in `node-red-tm.container.j2`. The third shows `migrate`'s warnings: it prints them on stderr and exits 0, and Ansible hides a successful command's stderr without `-v`, so a camera read by LAN IP would otherwise go dark unnoticed (Review Focus 5). The warnings never hold a password: `migrate` skips URLs that carry credentials.

- [x] **Step 5: Run every check**

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

- [x] **Step 6: Commit**

```bash
git add -A script/ansible/roles/tmsetup/templates/go2rtc.yaml.j2 script/ansible/roles/tmsetup/files/go2rtc.yaml \
    script/ansible/roles/tmsetup/tasks/go2rtc_setup.yml script/ansible/roles/tmsetup/tasks/frigate_setup.yml \
    script/ansible/roles/tmsetup/vars/main.yml container/frigate/config/config.yml.j2 container/frigate/frigate.env.j2 \
    script/tests/ tm-control/backend/tests/
git commit -m "Bind go2rtc's API to loopback, require RTSP credentials, and load only the modules TM uses" -m "<trailer block>"
```

---

### Task 8: Data download errors (#223)

The Dashboard database page's downloads are served by `GET /storefiles` in the `ui-database` flow, in the group "Dashboard 2 - Compress & Download 1 or More Files". #223 has two bugs there:
- **Validation errors come back as 200.** "Validate filenames, setup tar" sets `msg.res.statusCode`. The `http response` node only reads its own setting, then `msg.statusCode`, then falls back to 200.
- **A `tar` failure never ends the download.**
  - "handle end of file or error" turns `msg.payload` into a string.
  - The "check result" switch then tests `msg.payload.code`, which is always undefined by that point. So the error branch can't be reached, and nothing ends the response.
  - On 2026-10-14, a bench Pi asked for a file Node-RED couldn't read. `tar` exited 2, and the Pi sent the 200 headers, then held the download open until curl gave up.
  - The Cancel button sets `msg.kill = "SIGKILL"`, and that lands on the same path.
- **A failed download still saves a file.** "Validate filenames, setup tar" sets `Content-Type` and `Content-Disposition: attachment` before `tar` runs. When `tar` fails before its first byte, the 500 goes out with those headers, and the browser saves the error text as a small `…_tmdb.tar.gz` (found in review on 2026-10-23).
- **The database download reads a file that's still being written.** Node-RED writes `tmdb.sqlite` all the time, so on a busy device GNU `tar` can exit 1 ("file changed as we read it") at the end of a multi-GB download. On 2026-10-25 the user chose to tar a consistent copy instead, and to tell people on the database page that it can take a minute or two to start.

The task also tightens the folder check. `filePath.startsWith(baseDir)` accepted `/db/temp-other/…`, and also `.`, which is the whole temp folder. The Dashboard only sends file names in `/db/temp` and `/db/tmdb.sqlite`, so requiring a path separator after the folder breaks no download.

**Files:**
- Modify: `container/node-red-tm/data/flows.json`. The download group's nodes change, along with "setup test", which belongs to the `/test` endpoint.
- Create: `script/tests/test_node_red_flows.py`

**Interfaces:**
- Produces: `GET /storefiles` answers 400, 403, or 404, with the message as the body. When `tar` fails, it answers 500 if nothing has been sent yet; otherwise it closes the connection. Either way the message shows up as the Dashboard notification. The download headers go out with the first chunk, so a failure before that is a plain HTTP error with no file to save.
- Produces: a database download first copies `tmdb.sqlite` with `VACUUM INTO` into its own folder under `/db/snapshot/`, through the sqlitedb config node every flow uses. It tars that copy and deletes it when `tar` ends (success, failure, or Cancel). If the copy fails, for example because the disk is full, it answers 500. Task 12's device tests check all of this on a Pi.

- [x] **Step 1: Write the failing test**

`script/tests/test_node_red_flows.py`:

```python
"""Check Node-RED's flows.json off-device."""

import json
from pathlib import Path

FLOWS = Path(__file__).resolve().parents[2] / "container" / "node-red-tm" / "data" / "flows.json"


def test_http_errors_set_msg_status_code():
    """The http response node takes its status from msg.statusCode. A status put on msg.res is ignored, so the reply is a 200 (#223)."""
    flows = json.loads(FLOWS.read_text())
    offenders = [node["name"] for node in flows if node["type"] == "function" and "msg.res.statusCode" in node["func"]]
    assert offenders == []


def test_download_headers_wait_for_the_first_chunk():
    """Headers set before tar runs make the browser save an early error as a small ".tar.gz" holding the message."""
    flows = json.loads(FLOWS.read_text())
    setters = sorted(node["name"] for node in flows if node["type"] == "function" and "Content-Disposition" in node["func"])
    assert setters == ["download chunks"]


def test_database_download_tars_a_copy():
    """Node-RED keeps writing tmdb.sqlite, so tar reads a VACUUM INTO copy instead of the live file."""
    flows = json.loads(FLOWS.read_text())

    def one(name):
        [node] = [node for node in flows if node.get("name") == name]
        return node

    assert one("zip files")["addpay"] == "tarArgs"
    copy = one("copy database for download")
    assert (copy["type"], copy["sqlquery"], copy["mydb"]) == ("sqlite", "msg.topic", "2f60c1ab30a6fc8f")
    assert "VACUUM INTO" in one("copy database first?")["func"]
    assert set(one("catch database copy")["scope"]) == {copy["id"], one("copy database first?")["id"]}


def test_download_names_cannot_become_tar_options():
    """tar gets each requested name as an argument, so a name with spaces or a leading "-" could add tar options."""
    flows = json.loads(FLOWS.read_text())
    [validate] = [node for node in flows if node.get("name") == "Validate filenames, setup tar"]
    assert '!/^[A-Za-z0-9][A-Za-z0-9._-]*$/.test(fileName)' in validate["func"]
    assert "msg.tarArgs = ' -C ' + baseDir + ' --' + filepath;" in validate["func"]
    assert "msg.tarArgs = ' -C ' + msg.snapshot + ' -- tmdb.sqlite';" in validate["func"]
```

- [x] **Step 2: Run it to check it fails**

Run: `.venv/bin/python -m pytest script/tests/test_node_red_flows.py -v`

Expected: 4 FAIL.
- The status test names "setup test" and "Validate filenames, setup tar".
- The header test lists the same two nodes instead of "download chunks".
- The copy test fails on its first assert, because "zip files" still reads `payload.filepath`.
- The tar-options test fails, because there's no file-name check yet.

- [x] **Step 3: Edit the flows**

Make the edit with a script and write the file back the way Node-RED does (see CLAUDE.md). Run this once from the repo root; don't commit the script. Each `swap` asserts that its text appears exactly once, so the script stops if the merged nodes differ from what's quoted here.

```bash
python3 - <<'EOF'
import json
from pathlib import Path

FLOWS = Path("container/node-red-tm/data/flows.json")
flows = json.loads(FLOWS.read_text())
by_id = {node["id"]: node for node in flows}


def swap(node, old, new):
    assert node["func"].count(old) == 1, (node["name"], old)
    node["func"] = node["func"].replace(old, new)


validate = by_id["2398aa8b9ca25816"]  # "Validate filenames, setup tar"
for code in (400, 403, 404):
    swap(validate, f"msg.res.statusCode = {code};", f"msg.statusCode = {code};")
swap(validate, "if (!filePath.startsWith(baseDir)) {", "if (!filePath.startsWith(baseDir + path.sep)) {")
swap(validate, "msg.res.statusCode = 0;\n", "")
# tar's arguments move to msg.tarArgs, because the sqlite node that copies the database replaces msg.payload
swap(validate, "msg.payload.filepath = ' -C ' + baseDir + ' ' + (files == '/db/tmdb.sqlite' ? 'tmdb.sqlite' : filepath);", """\
if (files == '/db/tmdb.sqlite') {
  // Node-RED keeps writing tmdb.sqlite, so tar a copy made by "copy database for download"
  msg.snapshot = '/db/snapshot/' + ISONow.replace(/:/g, '') + '-' + Math.random().toString(36).slice(2, 8);
  msg.tarArgs = ' -C ' + msg.snapshot + ' -- tmdb.sqlite';
} else {
  msg.tarArgs = ' -C ' + baseDir + ' --' + filepath;
}""")
# tar gets each name as an argument (spawn mode splits on spaces), so allow only plain file names
swap(validate, """\
 // Resolve the full path to prevent path traversal attacks
  const filePath = path.resolve(baseDir, fileName);""", """\
  // Only plain file names: tar gets each name as an argument, so spaces or a leading "-" would become tar options
  if (baseDir != "/db" && !/^[A-Za-z0-9][A-Za-z0-9._-]*$/.test(fileName)) {
    node.error("Invalid file name: " + fileName);
    msg.statusCode = 400;
    msg.payload = "Invalid file name.";
    return msg;
  }

 // Resolve the full path to prevent path traversal attacks
  const filePath = path.resolve(baseDir, fileName);""")
swap(validate, """\
// set browser download headers
msg.res._res.append('Content-Type', 'application/octet-stream');
const filename = prefix + name + ".tar.gz";
msg.res._res.append('Content-Disposition', 'attachment; filename="' + filename + '"');
""", """\
// "download chunks" sets the download headers with the first chunk, so an error before then is a plain HTTP error
msg.downloadName = prefix + name + ".tar.gz";
""")

setup_test = by_id["3141bbce81b4c183"]  # "setup test", the /test endpoint
swap(setup_test, "msg.res.statusCode = 0;\n", "")
swap(setup_test, "msg.res._res.append('Content-Type', 'application/octet-stream');\n", "")
swap(setup_test, "msg.payload.filepath = ", "msg.tarArgs = ")
swap(setup_test, """\
const filename = "test.tar.gz";
msg.res._res.append('Content-Disposition', 'attachment; filename="' + filename + '"');
""", 'msg.downloadName = "test.tar.gz";\n')

zip_files = by_id["30d1dd9d6d580fa4"]  # exec: tar czvf - ...
zip_files["addpay"] = "tarArgs"

by_id["857384c653c6a46c"]["func"] = """\
// Set the download headers with the first chunk, so a failure before any data is a plain HTTP error.
const res = msg.res._res;
if (!res.headersSent) {
    res.setHeader('Content-Type', 'application/octet-stream');
    res.setHeader('Content-Disposition', 'attachment; filename="' + msg.downloadName + '"');
}
res.write(msg.payload);
return null;"""

instructions = by_id["138179c5e9949f4f"]  # ui-template "download instructions"
old = "while the Traffic Monitor was deployed and capturing, only from this device.</p>"
assert instructions["format"].count(old) == 1
instructions["format"] = instructions["format"].replace(old, old + """
        <p>The device first makes a consistent copy of the database, so a large database can take
            a minute or two before the download starts.</p>""")

test_for_error = by_id["04630be97890045c"]  # switch: tar on success, error response otherwise
test_for_error["property"] = "statusCode"
test_for_error["rules"] = [{"t": "null"}, {"t": "else"}]

handle_end = by_id["41deab2c99a209b8"]  # "handle end of file or error"
handle_end["func"] = """\
// Remove the database copy, if this download made one
if (msg.snapshot) {
    global.get("fs").rmSync(msg.snapshot, { recursive: true, force: true });
}

// tar has finished. The exec node gives its exit code as msg.payload.code (0 means the archive
// is complete), and msg.payload.signal when it was stopped, as the Cancel button does.
if (msg.payload.code === 0) {
    msg.res._res.end(); // send end-of-file
    return null;
}

if (msg.payload.signal) {
    msg.payload = "Download stopped";
} else {
    msg.payload = "Download failed: tar exited with code " + msg.payload.code;
    node.error(msg.payload);
}

// Output 1 sends an HTTP error, output 2 shows the message on the Dashboard.
if (msg.res._res.headersSent) {
    // Part of the archive already went out with status 200. Closing the connection makes
    // the browser mark the download as failed instead of saving a cut-off file.
    msg.res._res.destroy();
    return [null, msg];
}
msg.statusCode = 500;
return [msg, msg];"""
handle_end["outputs"] = 2
handle_end["wires"] = [["8a12d83e700bcaa6"], ["9297900926075b54"]]  # http response; ui-notification

check_result = "513356e9f9a779df"  # switch on msg.payload.code, which is never set by then
flows.remove(by_id[check_result])
by_id[handle_end["g"]]["nodes"].remove(check_result)

# A database download copies tmdb.sqlite first: "Test for error" -> "copy database first?" -> sqlite -> tar
group = by_id[validate["g"]]
FUNCTION = {"type": "function", "outputs": 1, "timeout": 0, "noerr": 0, "initialize": "", "finalize": "", "libs": []}


def add(node):
    node.update(z=validate["z"], g=group["id"])
    flows.append(node)
    group["nodes"].append(node["id"])
    return node["id"]


copy_failed = add({**FUNCTION, "id": "3a226e9922929100", "name": "database copy failed", "x": 1090, "y": 2060,
                   # http response, ui-notification, link out "hide compressing file(s)"
                   "wires": [["8a12d83e700bcaa6", "9297900926075b54", "8f8958d08aa3a85d"]], "func": """\
// The database copy for a download failed: remove what was copied and answer with an error.
global.get("fs").rmSync(msg.snapshot, { recursive: true, force: true });
const reason = String((msg.error && msg.error.message) || "unknown error");
msg.payload = /SQLITE_FULL|disk is full/.test(reason)
    ? "Download failed: not enough free space to copy the database"
    : "Download failed: couldn't copy the database: " + reason;
node.error(msg.payload);
msg.statusCode = 500;
return msg;"""})
copy_db = add({"id": "6b71ab080a582bd2", "type": "sqlite", "name": "copy database for download",
               "mydb": "2f60c1ab30a6fc8f", "sqlquery": "msg.topic", "sql": "", "x": 860, "y": 2060,
               "wires": [[zip_files["id"]]]})
prepare = add({**FUNCTION, "id": "a7ea83d9c70f2981", "name": "copy database first?", "outputs": 2, "x": 860, "y": 1920,
               "wires": [[zip_files["id"]], [copy_db]], "func": """\
// A database download tars a copy (msg.snapshot, set by "Validate filenames, setup tar"),
// because Node-RED keeps writing tmdb.sqlite. Other downloads go straight to tar.
if (!msg.snapshot) {
    return [msg, null];
}
const fs = global.get("fs");
const path = global.get("path");
const root = path.dirname(msg.snapshot);
// Remove copies left by a download that never finished, e.g. when Node-RED restarted mid-download
const stale = Date.now() - 60 * 60 * 1000;
for (const entry of fs.existsSync(root) ? fs.readdirSync(root) : []) {
    const dir = path.join(root, entry);
    if (fs.statSync(dir).mtimeMs < stale) {
        fs.rmSync(dir, { recursive: true, force: true });
    }
}
fs.mkdirSync(msg.snapshot, { recursive: true });
// The same sqlitedb config as every other flow, so their writes wait for the copy instead of failing
msg.topic = "VACUUM INTO '" + msg.snapshot + "/tmdb.sqlite'";
return [null, msg];"""})
add({"id": "d4485dfc776d50fc", "type": "catch", "name": "catch database copy", "scope": [prepare, copy_db],
     "uncaught": False, "x": 870, "y": 2100, "wires": [[copy_failed]]})
test_for_error["wires"][0] = [prepare]

FLOWS.write_text(json.dumps(flows, indent=4, ensure_ascii=False))
EOF
```

What it changes:
- **"Validate filenames, setup tar"** sets `msg.statusCode` for 400, 403, and 404. Its folder check requires `baseDir + path.sep`, and it drops the `msg.res.statusCode = 0` success flag. Names in `/db/temp` must be plain file names (`^[A-Za-z0-9][A-Za-z0-9._-]*$`, else 400), and tar's arguments put `--` before them. The exec node runs in spawn mode, which splits the command line on spaces, so a name such as `events.json --checkpoint-action=exec=<cmd> /../events.json` passed the folder check (it resolves to `/db/temp/events.json`) and gave tar an option that runs a command. The Dashboard only sends plain names. Traversal names such as `../tmdb.sqlite` now get this 400 before the folder check.
- **"setup test"** drops the same flag. It goes straight to `tar` and never used the flag.
- **"Test for error"** routes on `msg.statusCode`: unset goes to `tar`, set goes to the error response.
- **"handle end of file or error"** is rewritten with two outputs:
  - On success, it ends the response.
  - On a failure where part of the archive has already gone out, it closes the connection, so the browser marks the download failed.
  - On a failure before anything was sent, it answers 500.
  - Either way, the message goes to the Dashboard notification. Cancel gives "Download stopped", without a Node-RED error.
- **"check result"** is removed.
- **Download headers** move from "Validate filenames, setup tar" and "setup test" into **"download chunks"**, which sets them before the first write. tar's arguments move from `msg.payload.filepath` to `msg.tarArgs`, and **"zip files"** reads them from there.
- **A database download** goes through three new nodes before `tar`:
  - **"copy database first?"** makes a folder for this download under `/db/snapshot/`, removes folders more than an hour old, and sets `msg.topic` to `VACUUM INTO '<folder>/tmdb.sqlite'`. Other downloads go straight to `tar`.
  - **"copy database for download"** is a sqlite node on the shared sqlitedb config (`2f60c1ab30a6fc8f`).
  - **"catch database copy"** sends a failure in either node to **"database copy failed"**. That node removes the folder and answers 500, saying so when the disk is full. It also shows the notification and hides the processing window.
  - "handle end of file or error" removes the folder when `tar` ends, Cancel included.
- **"download instructions"** says a large database can take a minute or two before the download starts.

GNU `tar` exits 1 when a file changes while it's being read. That still counts as a failed download (decided 2026-10-14), so don't treat exit 1 as success. A database download now tars its own copy, which nothing writes to, so it shouldn't happen there (decided 2026-10-25). The cost:
- The copy needs about 1x the database in free space.
- On a 2-3 GB database it takes 1-2 minutes before the first byte, and the database page says so.
- While it runs, every other flow's SQL waits behind it on the shared sqlitedb connection. A second connection would avoid the wait, but in the default rollback-journal mode its read lock would make those writes fail with `SQLITE_BUSY`. Queued writes should be delayed, not lost, but this hasn't been measured. Task 12 Step 5 checks it on a Pi.

- [x] **Step 4: Run the checks**

Run:

```bash
.venv/bin/python -m pytest script/tests container/node-red-tm/schema/tests -v
python3 -m json.tool container/node-red-tm/data/flows.json >/dev/null && echo "flows ok"
git diff --stat container/node-red-tm/data/flows.json
```

Expected:
- all pass. The schema tests include #208's `test_flows_sql.py`, which checks the SQL in `flows.json` against the schema.
- `flows ok`
- only `flows.json` changed: `1 file changed, 102 insertions(+), 44 deletions(-)` on 2026-10-25's `dev`.

There's no Node.js in the dev tools, so Task 12 runs the function code itself on a Pi. On 2026-10-14 the edited nodes were also run under Node 22 with stub `msg` and `node` objects, and they checked out:
- 400, 403, or 404 for no files, a missing file, `../tmdb.sqlite`, `../temp-other.json`, and `.`;
- no status for the Dashboard's own requests;
- end on exit 0;
- 500 when nothing had been sent;
- the connection closed when data had gone out;
- "Download stopped" for Cancel.

The header move, the database copy, and the page text were added on 2026-10-25. The script above was then run on a copy of that day's `flows.json`: the three tests went from failing to passing. Later that day it ran again on the merged `dev` (`e076db0`, after #208's flow changes), in the scratch worktree that already had Tasks 1 to 3. Every `swap` matched once, the three tests again went from failing to passing, and all 122 off-device tests passed. The changed and new function code was run under Node 22 with stub `msg`, `node`, and `fs` objects, and it checked out:
- a database request gets its own `/db/snapshot/<stamp>-<random>` folder and `tarArgs`, with no headers set yet;
- JSON requests and traversal checks behave as before;
- headers are set once, with the first chunk;
- "copy database first?" prunes only folders more than an hour old, and throws (for the catch node) when it can't make the folder;
- "database copy failed" answers 500 with the disk-full message and removes the folder;
- "handle end of file or error" removes the folder on success and on failure.

The sqlite node, the catch node, and the shared connection weren't exercised. Task 12 runs them on a Pi.

- [x] **Step 5: Commit**

```bash
git add container/node-red-tm/data/flows.json script/tests/test_node_red_flows.py
git commit -m "Return real HTTP errors from data downloads, and end a download when tar fails (#223)" -m "<trailer block>"
```

---

### Task 9: Keep the pod starting when its network unit fails once (#232)

`traffic-monitor.pod.j2` uses `Network=tmnet.network`. For a `.network` reference, Quadlet adds `Requires=tmnet-network.service` and `After=tmnet-network.service` to the pod's unit. On a bench Pi, `tmnet-network.service` crashed once during boot with a Podman panic. Its `Restart=on-failure` brought it back a moment later. By then the pod's start job had already failed with result `dependency`, and systemd doesn't retry those, so the pod stayed down until the next deploy.

The network itself was never missing. Podman keeps it in `/etc/containers/networks/` across reboots, and the unit only runs `podman network create --ignore`. So the pod needs to start after the unit, not to require it:
- Naming the network (`Network=tmnet`, the `NetworkName=` in `tmnet.network.j2`) stops Quadlet from adding `Requires=`.
- The pod's own `[Unit]` keeps the order with `Wants=` and `After=`.

On a fresh install the network unit still runs first, and tmsetup's run creates the network.

**Files:**
- Modify: `container/traffic-monitor.pod.j2`
- Test: `script/tests/test_tmsetup_templates.py`

**Interfaces:**
- Produces: a pod unit with no `Requires=` on `tmnet-network.service`. Task 12's disruptive device test checks on a Pi that the pod starts after one failed start of that unit.

- [x] **Step 1: Write the failing test**

Append to `script/tests/test_tmsetup_templates.py`:

```python


def test_pod_starts_even_if_its_network_unit_fails_once():
    """A .network reference makes Quadlet add Requires=tmnet-network.service, so one failed start of that unit
    at boot kept the pod down (#232). The pod names the network instead, and orders itself after the unit."""
    network = render("container/tmnet.network.j2").splitlines()
    name = next(line.split("=", 1)[1] for line in network if line.startswith("NetworkName="))
    pod = render("container/traffic-monitor.pod.j2", tmsetup_mqtt_lan_open=False).splitlines()
    assert f"Network={name}" in pod
    assert "Network=tmnet.network" not in pod
    assert "Wants=tmnet-network.service" in pod
    assert "After=tmnet-network.service" in pod
```

- [x] **Step 2: Run it to check it fails**

Run: `.venv/bin/python -m pytest script/tests/test_tmsetup_templates.py -v -k network_unit`

Expected: FAIL, because the pod still has `Network=tmnet.network`.

- [x] **Step 3: Name the network in the pod**

In `container/traffic-monitor.pod.j2`, change:

```
[Unit]
Description=Traffic Monitor pod
```

to:

```
[Unit]
Description=Traffic Monitor pod
# Start after the network unit without requiring it. With Network=tmnet.network, Quadlet adds Requires=,
# and one failed start of tmnet-network.service at boot kept the pod down (#232). The network persists
# in /etc/containers/networks/, so the pod can start even when the unit fails.
Wants=tmnet-network.service
After=tmnet-network.service
```

Then change `Network=tmnet.network` to `Network=tmnet`. `tmnet` is the `NetworkName=` in `container/tmnet.network.j2`, and the test fails if the two drift apart.

If Podman is installed on the dev machine, check what Quadlet generates from the rendered files:

```bash
d=$(mktemp -d)
.venv/bin/python -c "import sys; sys.path.insert(0, 'script/tests'); from tmsetup_render import render
open('$d/traffic-monitor.pod', 'w').write(render('container/traffic-monitor.pod.j2', tmsetup_mqtt_lan_open=False))
open('$d/tmnet.network', 'w').write(render('container/tmnet.network.j2'))"
QUADLET_UNIT_DIRS=$d /usr/libexec/podman/quadlet -dryrun | sed -n '/^---traffic-monitor.service---/,$p' \
    | grep -o -E '^Requires=.*|^(Wants|After)=tmnet.*|network tmnet'
```

Expected: `Wants=tmnet-network.service`, `After=tmnet-network.service`, and `network tmnet`, with no `Requires=` line. The pattern matches only at the start of a line, because Quadlet copies the unit's comments, and one of them mentions `Requires=`. On 2026-10-25, Podman 5.7.0's Quadlet gave exactly that. Before the change it printed `Requires=tmnet-network.service` in place of the `Wants=` line. Task 12 checks the behavior on the Pi's Podman 5.4.

- [x] **Step 4: Run the tests**

Run: `.venv/bin/python -m pytest script/tests -v`

Expected: all pass.

- [x] **Step 5: Commit**

```bash
git add container/traffic-monitor.pod.j2 script/tests/test_tmsetup_templates.py
git commit -m "Start the pod even if its network unit fails once at boot (#232)" -m "<trailer block>"
```

---

### Task 10: MQTT on the network only with a broker login

The MQTT broker is the Aedes node in Node-RED. It had no credentials, so `TM_MQTT_BROKER_USERNAME` and `TM_MQTT_BROKER_PASSWORD` in `node-red-tm.env` only made Node-RED's own client send a login, and nothing checked it. Task 1's `-C mqtt_lan` also lasted only one run: `podman_setup.yml` rewrites the pod unit on every run tagged `podman`, `frigate`, or `node-red-tm`.

This task makes the rule hold on every installer run. Port 1883 is open to the network exactly when `node-red-tm.env` sets both values, and the broker enforces them:
- The Aedes node takes its credentials from `${TM_MQTT_BROKER_USERNAME}` and `${TM_MQTT_BROKER_PASSWORD}`, like the client node `a5d65dd0e3566daa`. Node-RED 5.0.8 substitutes `${…}` in any node's credentials (`@node-red/runtime/lib/nodes/index.js`). node-red-contrib-aedes 0.15 checks logins only when both values are non-empty, so a device without a login behaves as before.
- A missing key is different from a blank one. Node-RED substitutes a variable only when it exists (`if (r !== undefined)` in `flows/util.js`), so a missing key leaves the literal `${…}` text, and the broker would require it as the login. The installer writes both keys on every run, blank or not.
- Frigate logs in with `FRIGATE_MQTT_USER` and `FRIGATE_MQTT_PASSWORD` from `frigate.env`. They default to `mqtt_user` and `mqtt_pass`, which nothing checked. The installer copies the login there.
- `-C mqtt_lan` creates a login (username `tm`, 32 random characters) when `node-red-tm.env` has none. The login lives in the operator's settings file, so later runs keep it. To close the port, blank both values and run `tmsetup.sh -t node-red-tm`.

**Files:**
- Create: `script/ansible/roles/tmsetup/tasks/mqtt_broker.yml`
- Modify: `script/ansible/roles/tmsetup/tasks/main.yml` (import right after the secrets import)
- Modify: `container/node-red-tm/node-red-tm.env.j2` and `container/frigate/frigate.env.j2`
- Modify: `script/ansible/roles/tmsetup/tasks/node-red-tm_setup.yml` (`diff: false` on "Create Node-RED-TM Configs")
- Modify: `container/node-red-tm/data/flows_cred.json`, only through Step 4's procedure
- Test: `script/tests/test_tmsetup_tasks.py`, `script/tests/test_tmsetup_templates.py`, `script/tests/test_node_red_flows.py`

**Interfaces:**
- Consumes: `tmsetup_bool_mqtt_lan` from Task 1.
- Produces:
  - the fact `tmsetup_mqtt_broker_login`, a dict with `username` and `password`, empty strings when there's no login
  - the fact `tmsetup_mqtt_lan_open`, which Task 1's pod template reads
  - the broker's credentials, which Task 12's device tests check

- [x] **Step 1: Write the failing tests**

Append to `script/tests/test_tmsetup_tasks.py`:

```python
def mqtt_broker_tasks():
    return {task["name"]: task for task in load_role_yaml("tasks/mqtt_broker.yml")}


def test_broker_login_is_read_on_every_run_that_renders_the_pod():
    main = load_role_yaml("tasks/main.yml")
    names = [task["name"] for task in main]
    login = main[names.index("TMSetup - Main - Read the MQTT broker login")]
    assert set(login["tags"]) == {"podman", "frigate", "node-red-tm"}
    secrets = names.index("TMSetup - Main - Generate and read device secrets")
    assert names.index("TMSetup - Main - Read the MQTT broker login") == secrets + 1


def test_broker_login_tasks_hide_the_values():
    for name, task in mqtt_broker_tasks().items():
        if any(module in task for module in ("ansible.builtin.slurp", "ansible.builtin.set_fact", "ansible.builtin.lineinfile")):
            assert task.get("no_log") is True, name


def test_both_broker_keys_are_written_even_when_blank():
    """Node-RED keeps a missing variable's ${...} text, and the broker would then require it as the login."""
    task = mqtt_broker_tasks()["TMSetup - MQTT Broker - Write the broker login to node-red-tm.env"]
    assert [item["key"] for item in task["loop"]] == ["TM_MQTT_BROKER_USERNAME", "TM_MQTT_BROKER_PASSWORD"]
    assert "tmsetup_mqtt_lan_open" not in str(task.get("when", ""))


def test_a_login_change_restarts_both_ends():
    tasks = mqtt_broker_tasks()
    for name in ("TMSetup - MQTT Broker - Write the broker login to node-red-tm.env",
                 "TMSetup - MQTT Broker - Give Frigate the broker login"):
        assert set(tasks[name]["notify"]) == {"Restart frigate.service", "Restart node-red-tm.service"}, name


def test_node_red_env_template_hides_its_diff():
    """node-red-tm.env.j2 renders the broker login, and a -f run with -a diff would print it into ~/tmsetup-*.log."""
    task = next(t for t in load_role_yaml("tasks/node-red-tm_setup.yml")
                if t["name"] == "TMSetup - Node-RED-TM Setup - Create Node-RED-TM Configs")
    assert task["diff"] is False
```

Append to `script/tests/test_tmsetup_templates.py`:

```python
LOGIN = {"username": "tm", "password": "s3cret"}
NO_LOGIN = {"username": "", "password": ""}


def mqtt_lines(text):
    # Only the MQTT settings, so a failing assert can't print other values, such as the credential secret
    return [line for line in text.splitlines() if "MQTT_" in line and not line.startswith("#")]


def node_red_env(login):
    return mqtt_lines(render(
        "container/node-red-tm/node-red-tm.env.j2",
        ansible_facts={"hostname": "tm-test"}, tmsetup_raspberry_pi_serial="0000", tmsetup_tm_version="0.0.0",
        tmsetup_mqtt_broker_login=login,
    ))


def frigate_env(login):
    return mqtt_lines(render(
        "container/frigate/frigate.env.j2",
        tmsetup_frigate_rtsp_password="password", tmsetup_frigate_mqtt_user="mqtt_user",
        tmsetup_frigate_mqtt_password="mqtt_pass", tmsetup_codedir="/opt/traffic-monitor",
        tmsetup_frigate_version="0.18.1", tmsetup_go2rtc_rtsp_user="frigate", tmsetup_secrets=SECRETS,
        tmsetup_mqtt_broker_login=login,
    ))


def test_env_templates_render_the_broker_login():
    assert "TM_MQTT_BROKER_USERNAME=tm" in node_red_env(LOGIN)
    assert "TM_MQTT_BROKER_PASSWORD=s3cret" in node_red_env(LOGIN)
    assert "FRIGATE_MQTT_USER=tm" in frigate_env(LOGIN)
    assert "FRIGATE_MQTT_PASSWORD=s3cret" in frigate_env(LOGIN)


def test_env_templates_without_a_login():
    assert "TM_MQTT_BROKER_USERNAME=" in node_red_env(NO_LOGIN)
    assert "TM_MQTT_BROKER_PASSWORD=" in node_red_env(NO_LOGIN)
    assert "FRIGATE_MQTT_USER=mqtt_user" in frigate_env(NO_LOGIN)
```

In Task 7's `test_frigate_env_carries_the_go2rtc_credentials`, add `tmsetup_mqtt_broker_login=NO_LOGIN` to the `render` call, because `frigate.env.j2` now needs it.

Append to `script/tests/test_node_red_flows.py`:

```python
def test_mqtt_nodes_keep_their_ids():
    """flows_cred.json stores the broker login by node id, so these nodes must keep their ids (Task 10)."""
    types = {node["id"]: node["type"] for node in json.loads(FLOWS.read_text())}
    assert types.get("9ca3b6ed1a6334c0") == "aedes broker"
    assert types.get("a5d65dd0e3566daa") == "mqtt-broker"


def test_flows_cred_is_still_encrypted():
    assert list(json.loads((FLOWS.parent / "flows_cred.json").read_text())) == ["$"]
```

No test decrypts `flows_cred.json`. Step 4's procedure checks what the broker does with it, and Task 12's device tests check it on a Pi.

- [x] **Step 2: Run the tests to check they fail**

Run: `.venv/bin/python -m pytest script/tests/test_tmsetup_templates.py script/tests/test_tmsetup_tasks.py script/tests/test_node_red_flows.py -v`

Expected: the new task tests FAIL with `FileNotFoundError` (no `tasks/mqtt_broker.yml`) or `ValueError` (no import), the diff test with `KeyError`, and the template tests on the old lines. The node-id and encryption tests already pass and guard Step 4.

- [x] **Step 3: Write the task file, the import, and the templates**

`script/ansible/roles/tmsetup/tasks/mqtt_broker.yml`:

```yaml
---
# TMSetup - MQTT Broker: port 1883 is open to the network exactly when node-red-tm.env sets a broker
# login, and the broker enforces it. main.yml imports this with every tag that renders the pod.
# Tasks that handle the login set no_log, because tmsetup.sh copies all output into ~/tmsetup-*.log.
- name: TMSetup - MQTT Broker - Check for the env files
  become: true
  loop:
    - '{{ tmsetup_codedir }}/node-red-tm/node-red-tm.env'
    - '{{ tmsetup_codedir }}/frigate/frigate.env'
  ansible.builtin.stat:
    path: '{{ item }}'
  register: tmsetup_mqtt_env_stat_register

- name: TMSetup - MQTT Broker - Read node-red-tm.env
  become: true
  no_log: true
  ansible.builtin.slurp:
    src: '{{ tmsetup_codedir }}/node-red-tm/node-red-tm.env'
  register: tmsetup_mqtt_env_register
  when: tmsetup_mqtt_env_stat_register.results[0].stat.exists

- name: TMSetup - MQTT Broker - Set the broker login
  no_log: true
  vars:
    env_text: "{{ tmsetup_mqtt_env_register.content | b64decode if tmsetup_mqtt_env_stat_register.results[0].stat.exists else '' }}"
    found_username: "{{ (env_text | regex_search('(?m)^TM_MQTT_BROKER_USERNAME=.*$') or '') | regex_replace('^TM_MQTT_BROKER_USERNAME=', '') | trim }}"
    found_password: "{{ (env_text | regex_search('(?m)^TM_MQTT_BROKER_PASSWORD=.*$') or '') | regex_replace('^TM_MQTT_BROKER_PASSWORD=', '') | trim }}"
    create: "{{ (tmsetup_bool_mqtt_lan | default(false) | bool) and not found_username and not found_password }}"
  ansible.builtin.set_fact:
    tmsetup_mqtt_broker_login_created: '{{ create }}'
    tmsetup_mqtt_broker_login:
      username: "{{ 'tm' if create else found_username }}"
      password: "{{ lookup('community.general.random_string', length=32, special=false) if create else found_password }}"

- name: TMSetup - MQTT Broker - Open port 1883 only with a login
  no_log: true
  ansible.builtin.set_fact:
    tmsetup_mqtt_lan_open: "{{ tmsetup_mqtt_broker_login.username != '' and tmsetup_mqtt_broker_login.password != '' }}"

# The failed expression names variables, never values, so this task can show its message.
- name: TMSetup - MQTT Broker - Check the broker login
  ansible.builtin.assert:
    that:
      - (tmsetup_mqtt_broker_login.username == '') == (tmsetup_mqtt_broker_login.password == '')
      - tmsetup_mqtt_broker_login.username is regex('^[A-Za-z0-9._-]*$')
      - tmsetup_mqtt_broker_login.password is regex('^[A-Za-z0-9._-]*$')
    fail_msg: >-
      TM_MQTT_BROKER_USERNAME and TM_MQTT_BROKER_PASSWORD in node-red-tm.env must both be set or both be blank,
      using only letters, digits, '.', '_', and '-', with no quotes. Fix the file, then run tmsetup.sh again.
    quiet: true

- name: TMSetup - MQTT Broker - Write the broker login to node-red-tm.env
  become: true
  no_log: true
  loop:
    - { key: TM_MQTT_BROKER_USERNAME, value: '{{ tmsetup_mqtt_broker_login.username }}' }
    - { key: TM_MQTT_BROKER_PASSWORD, value: '{{ tmsetup_mqtt_broker_login.password }}' }
  ansible.builtin.lineinfile:
    path: '{{ tmsetup_codedir }}/node-red-tm/node-red-tm.env'
    regexp: '^{{ item.key }}='
    line: '{{ item.key }}={{ item.value }}'
  when: tmsetup_mqtt_env_stat_register.results[0].stat.exists
  notify:
    - Restart frigate.service
    - Restart node-red-tm.service

- name: TMSetup - MQTT Broker - Give Frigate the broker login
  become: true
  no_log: true
  loop:
    - { key: FRIGATE_MQTT_USER, value: '{{ tmsetup_mqtt_broker_login.username }}' }
    - { key: FRIGATE_MQTT_PASSWORD, value: '{{ tmsetup_mqtt_broker_login.password }}' }
  ansible.builtin.lineinfile:
    path: '{{ tmsetup_codedir }}/frigate/frigate.env'
    regexp: '^{{ item.key }}='
    line: '{{ item.key }}={{ item.value }}'
  register: tmsetup_mqtt_frigate_lines_register
  when:
    - tmsetup_mqtt_lan_open
    - tmsetup_mqtt_env_stat_register.results[1].stat.exists
  notify:
    - Restart frigate.service
    - Restart node-red-tm.service

- name: TMSetup - MQTT Broker - Remind about the other MQTT clients
  ansible.builtin.debug:
    msg: >-
      The MQTT broker now requires the login in {{ tmsetup_codedir }}/node-red-tm/node-red-tm.env, and port 1883 is
      open to the network. Give that login to the air quality sensor (mqtt_username and mqtt_password in its
      config.json) and to every other MQTT client, such as Home Assistant or a display board.
  when: tmsetup_mqtt_lan_open and (tmsetup_mqtt_broker_login_created or tmsetup_mqtt_frigate_lines_register is changed)
...
```

On a fresh install the two env files don't exist yet. The facts still carry the login, and the templates render it when Node-RED's and Frigate's setup create the files later in the run. `-f` keeps the login the same way, because this file reads it before the templates replace `node-red-tm.env`.

In `script/ansible/roles/tmsetup/tasks/main.yml`, directly after `TMSetup - Main - Generate and read device secrets` (Task 3), add:

```yaml
- name: TMSetup - Main - Read the MQTT broker login
  tags:
    - podman
    - frigate
    - node-red-tm
  ansible.builtin.import_tasks:
    file: mqtt_broker.yml
```

In `container/node-red-tm/node-red-tm.env.j2`, replace the four lines from `# mqtt user, leave blank for no authentication` through `TM_MQTT_BROKER_PASSWORD=` with:

```
# MQTT broker login. The broker enforces it, and port 1883 opens to the network only when both are set.
# Change it by running tmsetup.sh (-t node-red-tm), which also gives it to Frigate. Leave both blank for no login.
TM_MQTT_BROKER_USERNAME={{ tmsetup_mqtt_broker_login.username }}
TM_MQTT_BROKER_PASSWORD={{ tmsetup_mqtt_broker_login.password }}
```

In `container/frigate/frigate.env.j2`, change the two MQTT lines to:

```
FRIGATE_MQTT_USER={{ tmsetup_mqtt_broker_login.username or tmsetup_frigate_mqtt_user }}
FRIGATE_MQTT_PASSWORD={{ tmsetup_mqtt_broker_login.password or tmsetup_frigate_mqtt_password }}
```

In `script/ansible/roles/tmsetup/tasks/node-red-tm_setup.yml`, add `diff: false` to `TMSetup - Node-RED-TM Setup - Create Node-RED-TM Configs`, after `become: true`.

- [x] **Step 4: Give the broker node its credentials**

`flows_cred.json` is encrypted, so don't edit it by hand. Set the credentials through Node-RED's admin API in a throwaway container built from this repo, then copy back only `flows_cred.json`. Run this once from the repo root, with Podman, and don't commit the scripts. Nothing prints the credential secret. If any step behaves differently from what's described here, stop and tell the person.

```bash
d=$(mktemp -d)
cp container/node-red-tm/data/{flows.json,flows_cred.json,settings.js,package.json} "$d"/
chmod -R a+rwX "$d"   # the image runs Node-RED as uid 1000
.venv/bin/python -c "import sys; sys.path.insert(0, 'script/tests'); from tmsetup_render import load_role_yaml, render
open('$d/Containerfile', 'w').write(render('container/node-red-tm/Containerfile.j2',
    tmsetup_node_red_tm_version=load_role_yaml('vars/main.yml')['tmsetup_node_red_tm_version']))"
podman build -q -t tm-cred-edit -f "$d/Containerfile" container/node-red-tm
# The credential secret and a made-up login go in a file, never on a command line
grep '^NODE_RED_CREDENTIAL_SECRET=' container/node-red-tm/node-red-tm.env.j2 > "$d/env"
printf 'TM_MQTT_BROKER_HOST=localhost\nTM_MQTT_BROKER_PORT=1883\nTM_MQTT_BROKER_USERNAME=check\nTM_MQTT_BROKER_PASSWORD=check-pass\n' >> "$d/env"
podman run -d --rm --name tm-cred-edit --env-file "$d/env" -v "$d":/data -p 127.0.0.1:18800:1880 -p 127.0.0.1:18830:1883 tm-cred-edit
```

The flows log errors about the missing `/config` and `/db` folders; that's expected. Then set the credentials:

```bash
.venv/bin/python - <<'EOF'
import json, time, urllib.request
BASE = "http://127.0.0.1:18800"


def call(method, path, body=None, token=None, headers=None):
    request = urllib.request.Request(BASE + path, method=method, data=None if body is None else json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json", **(headers or {}),
                                              **({"Authorization": "Bearer " + token} if token else {})})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read() or b"null")


for _ in range(90):
    try:
        urllib.request.urlopen(BASE + "/auth/login", timeout=5)
        break
    except OSError:
        time.sleep(2)
token = call("POST", "/auth/token", {"client_id": "node-red-admin", "grant_type": "password", "scope": "*",
                                     "username": "admin", "password": "password"})["access_token"]
v2 = {"Node-RED-API-Version": "v2"}
current = call("GET", "/flows", token=token, headers=v2)
[broker] = [node for node in current["flows"] if node["id"] == "9ca3b6ed1a6334c0"]
broker["credentials"] = {"username": "${TM_MQTT_BROKER_USERNAME}", "password": "${TM_MQTT_BROKER_PASSWORD}"}
call("POST", "/flows", {"rev": current["rev"], "flows": current["flows"]}, token=token,
     headers={**v2, "Node-RED-Deployment-Type": "full"})
print("credentials set")
EOF
```

Check what the broker now does, with a raw MQTT 3.1.1 CONNECT (return code 0 accepted, 5 not authorized):

```bash
cat > "$d/connack.py" <<'EOF'
import socket
import sys


def field(text):
    data = text.encode()
    return len(data).to_bytes(2, "big") + data


def connack(username=None, password=None, port=18830):
    flags = 0x02 | (0x80 if username is not None else 0) | (0x40 if password is not None else 0)
    body = field("MQTT") + bytes([4, flags]) + (30).to_bytes(2, "big") + field("tm-cred-check")
    body += (field(username) if username is not None else b"") + (field(password) if password is not None else b"")
    with socket.create_connection(("127.0.0.1", port), timeout=5) as connection:
        connection.sendall(bytes([0x10, len(body)]) + body)
        return connection.recv(4)[3]


print("no login", connack(), "wrong", connack("check", "wrong"), "right", connack("check", "check-pass"))
EOF
.venv/bin/python "$d/connack.py"
```

Expected: `no login 5 wrong 5 right 0`. Then check a device without a login:

```bash
podman stop tm-cred-edit
sed -i 's/^\(TM_MQTT_BROKER_\(USERNAME\|PASSWORD\)\)=.*/\1=/' "$d/env"
podman run -d --rm --name tm-cred-edit --env-file "$d/env" -v "$d":/data -p 127.0.0.1:18800:1880 -p 127.0.0.1:18830:1883 tm-cred-edit
sleep 20 && .venv/bin/python "$d/connack.py"
podman stop tm-cred-edit
```

Expected: `no login 0`, and the two connects that send a login also print 0, because a broker without credentials accepts anyone. Then copy the result back:

```bash
.venv/bin/python -c "import json, sys; assert json.load(open(sys.argv[1])) == json.load(open(sys.argv[2])), 'flows changed'" \
    "$d/flows.json" container/node-red-tm/data/flows.json && echo "flows unchanged"
cp "$d/flows_cred.json" container/node-red-tm/data/flows_cred.json
podman rmi tm-cred-edit && rm -rf "$d"
```

Expected: `flows unchanged`. Only `flows_cred.json` changes in the repo.

- [x] **Step 5: Run the checks**

Run:

```bash
.venv/bin/python -m pytest script/tests container/node-red-tm/schema/tests -v
(cd script/ansible && ../../.venv/bin/ansible-playbook -i localhost setup.yml --syntax-check </dev/null > /tmp/tm-syntax.log 2>&1); echo "exit $?"
.venv/bin/python -c 'import sys,jinja2; e=jinja2.Environment(); [e.parse(open(f).read(), filename=f) for f in sys.argv[1:]]' $(git ls-files --cached --others --exclude-standard '*.j2') && echo "templates parse"
git diff --stat
```

Expected:
- all tests pass
- `exit 0`
- `templates parse`
- `git diff --stat` lists the task file, `main.yml`, `node-red-tm_setup.yml`, both env templates, `flows_cred.json`, and the three test files.

- [x] **Step 6: Commit**

```bash
git add script/ansible/roles/tmsetup/tasks/mqtt_broker.yml script/ansible/roles/tmsetup/tasks/main.yml \
    script/ansible/roles/tmsetup/tasks/node-red-tm_setup.yml container/node-red-tm/node-red-tm.env.j2 \
    container/frigate/frigate.env.j2 container/node-red-tm/data/flows_cred.json script/tests/
git commit -m "Open MQTT to the network only with a broker login the broker enforces" -m "<trailer block>"
```

---

### Task 11: Docs and CLAUDE.md

The docs follow "Writing docs" in `docs/development/contributing.md` (#241): describe how things work, not how they changed; say each fact once and link to it; and give real values, such as `/opt/traffic-monitor`, rather than variables. What changed goes in the release notes (Task 12 Step 12). Check every value against the code.

**Files:**
- Create: `docs/reference/network.md`
- Modify: `mkdocs.yml` (nav)
- Modify: `docs/use/home-page.md`, `docs/ui/database.md`, `docs/build-your-own-device-diy/update.md`, `docs/use/system-admin.md`
- Modify: `docs/data-and-payloads/integrations.md`, `docs/data-and-payloads/data-overview.md`
- Modify: `docs/configuration/frigate-config.md`, `docs/configuration/environment.md`, `docs/reference/tmsetup.md`
- Modify: `docs/add-ons/air-quality.md`, `docs/development/dev-environment.md`
- Modify: `README.md` (lines 45–49 and 63)
- Modify: `CLAUDE.md`

- [x] **Step 1: Write the ports page**

`docs/reference/network.md`:

````markdown
---
description: The network ports a Traffic Monitor opens, and the login the camera stream needs.
---

# Network ports

Other computers reach the Traffic Monitor's apps through the [home page](../use/home-page.md) on port 80. The apps themselves accept connections only from the device.

| Port | Used for |
|---|---|
| 22 | SSH |
| 80 | The home page and every app it links to |
| 1883 | MQTT, only when the broker has a login. See [MQTT and ThingsBoard](../data-and-payloads/integrations.md#mqtt). |
| 5353 (UDP) | `<hostname>.local` names (mDNS) |
| 8554 | The camera stream (RTSP), with a username and password |
| 9090 | Cockpit, with your Raspberry Pi login. Use it if the home page doesn't load. |

When the device hosts its own Wi-Fi network, it also answers DHCP and DNS on it.

## Camera stream login

The camera stream on port 8554 needs the username `frigate` and a password generated on the device at install. To play the stream in another program, such as VLC, read the password on the device:

```bash
sudo cat /etc/traffic-monitor/secrets/go2rtc_rtsp_password
```

Then open `rtsp://frigate:<password>@<device>:8554/picam_h265_detect`.
````

In `mkdocs.yml`, under `nav:` → `- Reference:`, after `- Installer options: reference/tmsetup.md`, add:

```yaml
      - Network ports: reference/network.md
```

The `llmstxt` plugin's `reference/*.md` already picks the page up.

- [x] **Step 2: Update the pages that describe what M1 changes**

Revise each in place; delete what M1 makes untrue rather than adding a note about it.

- **`docs/use/home-page.md`:** replace the "Direct ports" note with one titled "If the home page doesn't load": the apps accept connections only from the device, so open Cockpit at `http://<device>:9090`, log in with the Raspberry Pi account, and check the services in [System administration](system-admin.md). Link [Network ports](../reference/network.md).
- **`docs/ui/database.md`:** delete the "Download from Node-RED's port" warning (#211 is fixed). Under "Download the database", say that the device first makes a consistent copy of the database, so a large one can take a minute or two before the download starts, and that a failed download shows its reason on the page (#223).
- **`docs/build-your-own-device-diy/update.md`:** in "Before you update", keep the database download, and drop "Open that page on Node-RED's port…".
- **`docs/use/system-admin.md`:**
  - The app containers run in one pod. `revproxy.service` runs on the host network, outside the pod, so the home page stays up when the pod is down.
  - Add a row to "When to restart what": after changing the MQTT broker login in `node-red-tm.env`, run `bash traffic-monitor/script/tmsetup.sh -t node-red-tm`, which gives the login to Frigate and opens or closes port 1883 to match. A plain restart leaves Frigate on the old login.
- **`docs/data-and-payloads/integrations.md`:**
  - The opening and the MQTT section: the broker is on by default and accepts connections only from the device. Frigate, the air quality sensor, and Node-RED connect locally.
  - A new subsection, "Connect from other devices":
    1. Give the broker a login: `bash traffic-monitor/script/tmsetup.sh -t node-red-tm -C mqtt_lan`. Or set your own `TM_MQTT_BROKER_USERNAME` and `TM_MQTT_BROKER_PASSWORD` (letters, digits, `.`, `_`, and `-`) in `/opt/traffic-monitor/node-red-tm/node-red-tm.env` and run the command without `-C mqtt_lan`. The broker then requires the login from every client, the installer gives it to Frigate, and port 1883 opens to your network.
    2. Read it: `sudo grep ^TM_MQTT_BROKER_ /opt/traffic-monitor/node-red-tm/node-red-tm.env`.
    3. Give it to the [air quality sensor](../add-ons/air-quality.md) and to each MQTT client.
    4. Check from another computer: `mosquitto_sub -h <device> -u <username> -P <password> -t tm/events`.
    5. To change or remove it, edit the two values and run `bash traffic-monitor/script/tmsetup.sh -t node-red-tm` again.
  - A `!!! warning`: the login crosses the network unencrypted, and anyone who has it can read every topic and publish false data. Open MQTT only on a network you trust.
  - The topic table's snapshot row: Frigate publishes it only when the camera's `mqtt` setting is on, which new installs turn off (#256). Link Tune object detection.
  - The `tm/events` example gets `-u <username> -P <password>`.
- **`docs/data-and-payloads/data-overview.md`:** in "By default, the device sends no images…", say Frigate's snapshots on the MQTT broker stay on the device unless you give the broker a login, and that new installs turn them off.
- **`docs/configuration/frigate-config.md`:**
  - The `_hr` input path keeps the login: `rtsp://{FRIGATE_GO2RTC_RTSP_USER}:{FRIGATE_GO2RTC_RTSP_PASSWORD}@host.containers.internal:8554/picam_h265_detect_hr`. Frigate fills in the `{…}` values from `frigate.env`.
  - "Recordings and snapshots": new installs turn the MQTT snapshots off with `mqtt: enabled: false` under `cameras: picam_h265:`. On an older install, add those lines in the configuration editor.
- **`docs/configuration/environment.md`:**
  - The `TM_MQTT_BROKER_USERNAME` and `TM_MQTT_BROKER_PASSWORD` rows: the broker's login, required from every client when both are set, which also opens port 1883 to the network. Letters, digits, `.`, `_`, and `-` only. Link "Connect from other devices".
  - The "restart the service" step: for the broker login, run the installer instead.
- **`docs/reference/tmsetup.md`:**
  - The `-C` row: `plate_recognizer`, or `mqtt_lan`, which creates an MQTT broker login when there isn't one.
  - A `tm-control` row in the tags table: the `tm-control` command, which updates settings files from earlier versions. The `frigate` tag runs it too.
  - "What `-f` replaces": the MQTT broker login carries into the fresh `node-red-tm.env` and `frigate.env`.
- **`docs/add-ons/air-quality.md`:** add `mqtt_username` and `mqtt_password` to the settings table, needed once the broker has a login.
- **`docs/development/dev-environment.md`:** the editor is at `http://<device>/nr/`.

In `README.md`, replace the bullets under "User Interfaces (UI) / port numbers references" with:

```markdown
- `http://<device_ip_address>/` is the home page, with links to every app below.
- `http://<device_ip_address>/ui/` is the [Node-RED](https://nodered.org/) dashboard and your primary device dashboard, use it to ensure it is capturing events, see the latest events, and see summarized stats.
- `http://<device_ip_address>/frigate/` to view the [Frigate](https://github.com/blakeblackshear/frigate) interface and make any configuration changes specific to your deployment
- `http://<device_ip_address>/feeds/` shows the [go2rtc](https://github.com/AlexxIT/go2rtc) camera streams on the Raspberry Pi. Use this if your cameras are giving errors in Frigate.
- `http://<device_ip_address>/system/` opens [Cockpit](https://cockpit-project.org/) for system administration: services, logs, updates, containers, and a terminal. Log in with your Raspberry Pi user account. Cockpit also answers directly on port `9090`.
- `http://<device_ip_address>/nr/` is the Node-RED flow editor used to develop the logic to connect events to speeds, create event records, capture radar readings, and more. This is primarily used by developers. The default admin login is admin/password.

See [Network ports](https://docs.trafficmonitor.ai/latest/reference/network/) for the ports the device opens.
```

Also replace `Device dashboard available at \`http://<device_ip_address>:1880/ui\`.` with `Device dashboard available at \`http://<device_ip_address>/ui/\`.`.

- [x] **Step 3: Update CLAUDE.md**

Make these edits to the matching text. If a sentence was reworded on your base branch, apply the same meaning.

1. **"What this repo is"**: after the `utils/` bullet, add:

   ```markdown
   - `tm-control/`: the Traffic Monitor control app (spec in `design/specs/`). So far only `tm-control migrate`, which tmsetup runs to update config files from older installs. It's installed root-owned to `/usr/local/lib/traffic-monitor/tm-control` and `/usr/local/bin/tm-control`.
   - `design/`: specs and implementation plans. Not published to the docs site.
   ```

2. **"Commands"**:
   - Change `The off-device tests cover the tmdb schema (\`container/node-red-tm/schema/tests\`).` to `The off-device tests cover the tmdb schema (\`container/node-red-tm/schema/tests\`), the role's templates and tasks and \`flows.json\` (\`script/tests\`), and tm-control (\`tm-control/backend/tests\`).`
   - Change the pytest line to:

     ```bash
     python -m pytest container/node-red-tm/schema/tests script/tests tm-control/backend/tests  # schema, role templates and tasks, tm-control
     ```

   - Add `tm-control` to the end of the tag list in the `tmsetup.sh -T` line's comment (Task 6's tag).

3. **"Runtime topology"**, first bullet:
   - Change `All containers (frigate, node-red-tm, revproxy, optional plate-recognizer) run in one pod` to `The app containers (frigate, node-red-tm, optional plate-recognizer) run in one pod`.
   - After `nginx proxies to \`127.0.0.1:<port>\`.`, add a sub-bullet: `The pod publishes its ports on 127.0.0.1 only (1880, 1883, 5000, 8971). 1883 also opens to the LAN when \`node-red-tm.env\` sets a broker login, which the Aedes broker enforces (\`tasks/mqtt_broker.yml\`); \`-C mqtt_lan\` creates one.`

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
     - `go2rtc.conf` and `cockpit.conf` proxy to `127.0.0.1`. `go2rtc.conf` also limits `/feeds` to viewing: GET only, lowercase unencoded parameter names (nginx and go2rtc must read the same `src`), no `dst`, plain stream names as `src`, and a sibling regex location that returns 403 for go2rtc API paths the players don't use.
     ```

     The storefiles commit already added `/storefiles` to this bullet's list of proxied paths.

7. **"Overwrite semantics"**: add at the end:

   ```
   To change an existing device's `config.yml` without `-f`, add a step to `tm-control migrate` (round-trip edit with a backup), as tmsetup does for the go2rtc RTSP credentials. Add new `*.env` keys with `lineinfile`.
   ```

8. **"Editing `flows.json`"**, the `flows_cred.json` bullet: after `don't hand-edit it.`, add `It holds the MQTT nodes' \`${TM_MQTT_BROKER_*}\` credential references, stored by node id. Change it only with the container procedure in the M1 plan's Task 10, and keep the MQTT nodes' ids.`

- [x] **Step 4: Check the docs build inputs**

Run:

```bash
grep -rn -E ':1880|:5000|:1984' README.md docs CLAUDE.md
grep -n 'reference/network' mkdocs.yml
~/.venvs/tm-docs/bin/mkdocs build --strict
```

Expected:
- The first command prints nothing except lines that describe internal addresses, such as `127.0.0.1:1984` and `http://frigate:5000/api/...` in CLAUDE.md.
- The second prints the new nav line.
- The build passes. With `--strict` it fails on broken links or anchors, and on a page missing from the nav. Set up `~/.venvs/tm-docs` as described in CLAUDE.md's docs check.

- [x] **Step 5: Commit**

```bash
git add docs/ mkdocs.yml README.md CLAUDE.md
git commit -m "Document network access through the reverse proxy and the MQTT broker login" -m "<trailer block>"
```

---

### Task 12: Device tests and the Pi test plan, through tmdev

This uses #214's `script/devpi/tmdev.py` and #215's device tests, which compare a bench Pi with its expected hardware. Run the Pi test plan before committing this task and before opening the PR:
- Use a dev Pi from the local inventory, never a field device.
- Keep device names and addresses out of commits and PR text.
- Ask the person before any step that reboots the Pi or stops services.

`T` below stands for `.venv/bin/python script/devpi/tmdev.py`. Run it from this branch's checkout, so `test` runs this branch's device tests; the `.venv` needs `ansible-inventory`, which CLAUDE.md's dev venv has. `run` joins the words after `--` with spaces and runs them in the Pi's login shell. So pass a pipe or a compound command as one quoted word (`-- 'cmd1 | cmd2'`), not as `sh -c …`. An unquoted `|` runs the rest on this machine.

**Files:**
- Modify: `script/devpi/tests/test_web.py`
- Modify: `script/devpi/tests/test_disruptive.py`

**Interfaces:**
- Consumes:
  - #215's `host`, `hostvars`, `expect`, `codedir`, and `codeowner` fixtures, and `wait_until_ready` in `test_disruptive.py`
  - #214's `tmdev.py` commands: `check start|item|status|end`, `deploy`, `run`, and `test`
  - Task 2's `/feeds/` rules
  - Task 7's RTSP credentials
  - Task 8's download errors
  - Task 9's pod unit, which no longer requires `tmnet-network.service`
  - Task 10's broker login

- [ ] **Step 1: Write the device tests**

At the top of `script/devpi/tests/test_web.py`, add `import socket` to the imports; it already imports `urllib.error` and `urllib.request`. Then append:

```python
# Edge and ports (tm-control M1): from this machine, only nginx answers, and /feeds is view-only.
CLOSED_TO_NETWORK = [1880, 1984, 5000, 8971]  # 1883: see the MQTT tests below


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
        ("/feeds/api/stream.mp4?%73rc=rtsp://192.0.2.1/x", "GET", 403),
        ("/feeds/api/stream.mp4?SRC=picam_h265_detect&src=rtsp://192.0.2.1/x", "GET", 403),
        ("/feeds/api/ws?dst=picam_h265_detect", "GET", 403),
        ("/feeds/api/streams?src=x", "POST", 403),
    ],
)
def test_feeds_is_view_only_from_this_machine(host, hostvars, path, method, expected):
    assert status_from_this_machine(host, hostvars, path, method) == expected


@pytest.mark.parametrize(
    "query, expected",
    [
        ("", 400),
        ("?files=tmdev-missing.json", 404),
        ("?files=../tmdb.sqlite", 400),
        ("?files=../temp-other.json", 400),
        ("?files=-v", 400),
        ("?files=a%20b.json", 400),
    ],
)
def test_data_export_errors_from_this_machine(host, hostvars, query, expected):
    """Node-RED's download endpoint answers through the proxy with real error statuses (#211, #223)."""
    assert status_from_this_machine(host, hostvars, f"/storefiles{query}") == expected


def test_failed_data_export_ends_the_download(host, expect, codedir, codeowner):
    """When tar fails, Node-RED ends the download instead of leaving it open (#223)."""
    if not expect["pii_free"]:
        pytest.skip("writes a file into the Pi's data folder; set tm_expect.pii_free: true (bench units only)")
    if codeowner == "root":
        pytest.skip("Node-RED runs as root, so it can read the planted file")
    temp = f"{codedir}/node-red-tm/db/temp"
    with host.sudo():
        if host.run(f"test -d {temp}").rc != 0:
            pytest.skip("Node-RED hasn't created db/temp yet")
        # An empty file only root can read: it exists, so validation passes, and tar fails on it.
        host.check_output(f"install -m 000 /dev/null {temp}/tmdev-unreadable.json")
    try:
        # Straight to Node-RED on the Pi, so nginx's read timeout can't end a download that Node-RED left open.
        result = host.run("curl -s -o /dev/null -D - -w '%{http_code}' --max-time 20 "
                          "'http://localhost:1880/storefiles?files=tmdev-unreadable.json'")
    finally:
        with host.sudo():
            host.check_output(f"rm -f {temp}/tmdev-unreadable.json")
    status = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else ""
    # 500 if tar failed before sending anything; otherwise the connection is cut mid-download (curl exit 18).
    # Before #223's fix the download stayed open until curl gave up (exit 28).
    assert (result.rc, status) in {(0, "500"), (18, "200")}, (result.rc, result.stdout)
    if status == "500":
        assert "content-disposition" not in result.stdout.lower(), "the browser would save the error as a file"


def test_data_export_tars_a_database_copy(host, expect, codedir):
    """The database download tars a VACUUM INTO copy, then removes it (2026-10-25)."""
    if not expect["pii_free"]:
        pytest.skip("downloads the whole database; set tm_expect.pii_free: true (bench units only)")
    # The archive stays on the Pi: only its file list comes back.
    listing = host.run("curl -sf --max-time 900 'http://localhost:1880/storefiles?files=/db/tmdb.sqlite' | tar tzf -")
    assert (listing.rc, listing.stdout.split()) == (0, ["tmdb.sqlite"]), listing.stderr
    with host.sudo():
        leftovers = host.run(f"find {codedir}/node-red-tm/db/snapshot -mindepth 1").stdout.split()
    assert leftovers == []


def test_data_export_copy_failure_is_an_http_error(host, expect, codedir):
    """If the database copy fails, the download is a 500 with no file to save."""
    if not expect["pii_free"]:
        pytest.skip("writes into the Pi's data folder; set tm_expect.pii_free: true (bench units only)")
    snapshot = f"{codedir}/node-red-tm/db/snapshot"
    with host.sudo():
        # A file where the copies' folder belongs, so the copy can't start
        host.check_output(f"rm -rf {snapshot} && install -m 000 /dev/null {snapshot}")
    try:
        result = host.run("curl -s -o /dev/null -D - -w '%{http_code}' --max-time 60 "
                          "'http://localhost:1880/storefiles?files=/db/tmdb.sqlite'")
    finally:
        with host.sudo():
            host.check_output(f"rm -f {snapshot}")
    assert result.stdout.strip().splitlines()[-1] == "500", result.stdout
    assert "content-disposition" not in result.stdout.lower()


def test_camera_stream_needs_credentials(host, hostvars):
    """go2rtc's RTSP server answers a DESCRIBE without credentials with 401."""
    address = pi_address(host, hostvars)
    request = f"DESCRIBE rtsp://{address}:8554/picam_h265_detect RTSP/1.0\r\nCSeq: 1\r\n\r\n"
    with socket.create_connection((address, 8554), timeout=5) as connection:
        connection.sendall(request.encode())
        status_line = connection.recv(1024).decode(errors="replace").splitlines()[0]
    assert status_line.startswith("RTSP/1.0 401"), status_line


def mqtt_connack(address, username=None, password=None, port=1883):
    """Send an MQTT 3.1.1 CONNECT and return the CONNACK return code: 0 accepted, 5 not authorized."""
    def field(text):
        data = text.encode()
        return len(data).to_bytes(2, "big") + data

    flags = 0x02 | (0x80 if username is not None else 0) | (0x40 if password is not None else 0)
    body = field("MQTT") + bytes([4, flags]) + (30).to_bytes(2, "big") + field("tmdev-check")
    body += (field(username) if username is not None else b"") + (field(password) if password is not None else b"")
    length, encoded = len(body), b""
    while True:
        length, digit = divmod(length, 128)
        encoded += bytes([digit | (0x80 if length else 0)])
        if not length:
            break
    with socket.create_connection((address, port), timeout=5) as connection:
        connection.sendall(b"\x10" + encoded + body)
        return connection.recv(4)[3]


def broker_login(host, expect, codedir):
    if not expect["pii_free"]:
        pytest.skip("reads node-red-tm.env; set tm_expect.pii_free: true (bench units only)")
    with host.sudo():
        text = host.run(f"grep '^TM_MQTT_BROKER_' {codedir}/node-red-tm/node-red-tm.env").stdout
    values = dict(line.split("=", 1) for line in text.splitlines() if "=" in line)
    return values.get("TM_MQTT_BROKER_USERNAME", ""), values.get("TM_MQTT_BROKER_PASSWORD", "")


def test_mqtt_port_follows_the_broker_login(host, hostvars, expect, codedir):
    """MQTT is open to the network only with a broker login, and the broker enforces it (Task 10)."""
    username, password = broker_login(host, expect, codedir)
    address = pi_address(host, hostvars)
    if not (username and password):
        with pytest.raises(OSError):
            socket.create_connection((address, 1883), timeout=5).close()
        return
    # Compare return codes only, so the login never appears in an assertion message
    assert mqtt_connack(address) == 5
    assert mqtt_connack(address, username, password + "x") == 5
    assert mqtt_connack(address, username, password) == 0


PI_MQTT_CONNACK = (
    "import socket; s = socket.create_connection(('127.0.0.1', 1883), timeout=5); "
    "s.sendall(bytes([0x10, 23]) + b'\\x00\\x04MQTT\\x04\\x02\\x00\\x1e\\x00\\x0btmdev-check'); "
    "print(s.recv(4)[3])"
)


def test_mqtt_broker_enforces_its_login_on_the_pi(host, expect, codedir):
    """On the Pi, a client without a login is refused exactly when a broker login is set."""
    username, password = broker_login(host, expect, codedir)
    expected = "5" if username and password else "0"
    assert host.check_output("python3 -c " + shlex.quote(PI_MQTT_CONNACK)) == expected


def test_frigate_logs_in_to_the_mqtt_broker(host):
    """Frigate has reached the broker with its login since it last started (Task 10)."""
    with host.sudo():
        since = host.check_output("systemctl show -p ActiveEnterTimestamp --value frigate.service")
        errors = host.run(f"journalctl -u frigate.service --since {shlex.quote(since)} --no-pager "
                          "| grep -c -i 'unable to connect to mqtt'").stdout.strip()
    assert errors == "0"
```

Check the exact wording of Frigate 0.18.1's MQTT connection error before relying on the `grep`, and adjust the pattern if it differs.

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


# Makes the network unit's next start fail once, like the Podman panic in #232; its Restart=on-failure then brings it up.
NETWORK_DROPIN = "/run/systemd/system/tmnet-network.service.d/tmdev-fail-once.conf"
NETWORK_FAILED_ONCE = "/run/tmdev-tmnet-failed-once"
FAIL_ONCE = f'[Service]\nExecStartPre=/bin/sh -c "test -e {NETWORK_FAILED_ONCE} || {{ touch {NETWORK_FAILED_ONCE}; exit 1; }}"\n'


def test_pod_starts_after_its_network_unit_fails_once(host):
    """One failed start of tmnet-network.service, as at boot in #232, doesn't keep the pod down."""
    with host.sudo():
        host.check_output("systemctl stop traffic-monitor.service tmnet-network.service")
        host.check_output(f"mkdir -p {NETWORK_DROPIN.rsplit('/', 1)[0]} && rm -f {NETWORK_FAILED_ONCE} "
                          f"&& printf %s {shlex.quote(FAIL_ONCE)} > {NETWORK_DROPIN} && systemctl daemon-reload")
    try:
        with host.sudo():
            host.run("systemctl start traffic-monitor.service")  # before #232's fix, a dependency job fails here
        deadline = time.monotonic() + 120
        while host.run("systemctl is-active traffic-monitor.service").stdout.strip() != "active":
            assert time.monotonic() < deadline, "the pod didn't start after tmnet-network.service failed once (#232)"
            time.sleep(5)
        assert host.file(NETWORK_FAILED_ONCE).exists, "the drop-in didn't make tmnet-network.service fail"
    finally:
        with host.sudo():
            host.check_output(f"rm -f {NETWORK_DROPIN} {NETWORK_FAILED_ONCE} && systemctl daemon-reload")
            host.check_output("systemctl start tmnet-network.service traffic-monitor.service")
        wait_until_ready(host, RESTART_TIMEOUT_SECONDS)
```

Add `import shlex` to the imports at the top of `test_disruptive.py`.

- [ ] **Step 2: Check the tests are collected and skip without a dev Pi**

Run:

```bash
.venv/bin/python -m pytest -q -p no:cacheprovider script/devpi/tests
.venv/bin/python -m pytest -q -p no:cacheprovider --collect-only script/devpi/tests/test_web.py script/devpi/tests/test_disruptive.py \
    | grep -c -E 'closed_to_the_network|view_only|needs_credentials|data_export|mqtt|survives_a_stopped_pod|network_unit_fails_once'
```

Expected: everything skipped, because no `TM_DEV_HOSTS` is set, and then `25`.

- [ ] **Step 3: Open the check and record the baseline**

Run these while the Pi still runs the code from before M1:

```bash
$T check start --host <host> --pr 224 --title "M1: edge and ports"
$T test <host> -- -k "closed_to_the_network or view_only or needs_credentials or data_export or mqtt"
```

Expected: the new tests fail, which shows they catch the problem:
- the ports are open;
- `/feeds/api/config` answers;
- RTSP needs no login;
- `/storefiles` errors come back as 200. A Pi without the storefiles commit gives nginx's 404 instead, so there the 404 case passes.
- On a `pii_free` unit, `test_mqtt_port_follows_the_broker_login` fails, because port 1883 is open without a login. The two other MQTT tests pass.
- On a `pii_free` unit, the failed-download test fails with curl's exit 28, because the download stays open, and the copy-failure test fails because the download succeeds. The database-copy test passes before M1 too: the archive still holds `tmdb.sqlite`, and there's no snapshot folder. Elsewhere all three are skipped.

With the person's OK, because it stops the pod for a few minutes, also run `$T test <host> --disruptive -- -k network_unit_fails_once`. It fails, which reproduces #232, and its cleanup starts the pod again.

Record it:

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
- All pass, including #215's existing ones: `nginx -t`, every proxied location answers (now including `/storefiles`), the direct ports answer on the Pi's `localhost`, and the home page loads from this machine. `test_cameras.py` reads the camera name from Frigate's input path with `:8554/<name>`, which still matches the credentialed URL. `test_no_crash_restarts[revproxy.service]` should pass too. It counts restarts since the handler last restarted revproxy, so a failure means the pod still held port 80 at that point (Review Focus 3). Bring that to the person.
- The 23 new non-disruptive tests pass. On a unit without `pii_free`, 18 pass, and five are skipped: the three data-export tests that write to the Pi or download the database, and the two MQTT tests that read `node-red-tm.env`.
- On a `pii_free` unit, while `test_data_export_tars_a_database_copy` runs: the Dashboard's Monitoring page keeps updating, and afterwards `$T run <host> -- 'sudo journalctl -u node-red-tm --since -15min | grep -c -E "SQLITE_BUSY|database is locked"'` prints `0`. Record it as an item. If writes failed or Node-RED stalled during the copy, stop and bring it to the person; don't work around it.

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
- `:9090` (Cockpit, the rescue console)
- `:1883`, only on a unit with a broker login (Step 9)
- DHCP/DNS, only in hotspot mode

Nothing listens on 1880, 1984, 5000, 8555, or 8971, and go2rtc has no UDP sockets. Repeat the `ss -ulnp` part while a browser plays `/feeds/stream.html?src=picam_h265_detect` (Step 10). go2rtc should still have no UDP socket, which shows WebRTC isn't loaded. Record an item.

- [ ] **Step 7: Check that re-runs keep the secrets and keep them out of the log**

Re-run on the Pi itself, so its install log lands on the Pi where the check can read it:

```bash
$T run <host> -- sudo sha256sum /etc/traffic-monitor/secrets/go2rtc_rtsp_password
$T deploy <host> --on-pi -- -t frigate -t go2rtc
$T run <host> -- sudo sha256sum /etc/traffic-monitor/secrets/go2rtc_rtsp_password
$T run <host> -- 'ls ~/tmsetup-*.log && { sudo grep -l -F -f /etc/traffic-monitor/secrets/go2rtc_rtsp_password ~/tmsetup-*.log || echo "no secrets in logs"; }'
```

Expected:
- The two hashes match. A hash isn't the secret.
- "Update Frigate config from older installs" reports *ok*, not changed.
- The last command lists the install logs, then prints `no secrets in logs`. The `ls` keeps a missing log from passing the check.

Record an item.

- [ ] **Step 8: Check the home page survives the pod**

Ask the person first: this stops data capture for a few minutes.

```bash
$T test <host> --disruptive -- -k "survives_a_stopped_pod or network_unit_fails_once"
$T run <host> -- "sudo journalctl -u frigate.service -b | grep -i -E '401|unauthorized' || echo none"
```

Expected: both tests pass, and the journal check prints `none`, meaning Frigate reads the camera with the credentials. Record an item. #215's `test_restart_recovers` and `test_reboot_recovers` also cover M1's restart order. Run the full `--disruptive` set only if the person agrees to a reboot.

- [ ] **Step 9: Open MQTT to the network with a broker login**

Ask the person first: this restarts Node-RED and Frigate. On a `pii_free` unit only, because it reads `node-red-tm.env`:

```bash
$T deploy <host> --on-pi -- -t node-red-tm -C mqtt_lan
$T test <host> -- -k mqtt
$T run <host> -- 'sudo grep "^TM_MQTT_BROKER_" /opt/traffic-monitor/node-red-tm/node-red-tm.env | sha256sum'
$T deploy <host> --on-pi -- -t node-red-tm
$T run <host> -- 'sudo grep "^TM_MQTT_BROKER_" /opt/traffic-monitor/node-red-tm/node-red-tm.env | sha256sum'
$T run <host> -- 'sudo sh -c "grep ^TM_MQTT_BROKER_PASSWORD= /opt/traffic-monitor/node-red-tm/node-red-tm.env | cut -d= -f2- > /run/tmdev-mqtt-pw" && { sudo grep -l -F -f /run/tmdev-mqtt-pw ~/tmsetup-*.log || echo "no broker password in logs"; }; sudo rm -f /run/tmdev-mqtt-pw'
```

Expected:
- The MQTT device tests pass with the login set. From this machine, a client without it and a wrong password get code 5, and the right login gets 0. Frigate's journal has no MQTT connection errors.
- The two hashes match: a later plain `-t node-red-tm` run keeps the login. A hash isn't the secret.
- `no broker password in logs`.

Then blank both values with `$T run <host> -- 'sudo sed -i "s/^\(TM_MQTT_BROKER_\(USERNAME\|PASSWORD\)\)=.*/\1=/" /opt/traffic-monitor/node-red-tm/node-red-tm.env'`, run `$T deploy <host> --on-pi -- -t node-red-tm`, and run `$T test <host> -- -k mqtt` again: port 1883 is closed to this machine, and a client without a login on the Pi gets 0. Leave the unit that way, or run `-C mqtt_lan` again. Record an item for each part.

A unit that had a login set by hand before M1 should keep Frigate connected after the upgrade (`test_frigate_logs_in_to_the_mqtt_broker`). If no bench unit has one, record that case as not tested.

- [ ] **Step 10: Record what needs a person**

These need eyes or the Node-RED editor, so record them as `manual`:

```bash
$T check item "/feeds/stream.html?src=picam_h265_detect plays in a desktop browser and on an iPhone (MSE)" manual
$T check item "/frigate/ shows the camera live, not offline" manual
$T check item "/dashboard/ updates live, /ui/ loads, /nr/ asks for the editor login" manual
$T check item "A data export from the /dashboard/ database page downloads through the proxy" manual
$T check item "Node-RED watch test: in-place, then two atomic edits of config.yml each log event 'update'" manual \
    --note "Spec, Risks to verify early"
```

When the person reports back, reopen the check with `$T check reopen <run_dir>` and re-record those items as `pass` or `fail`.

- [ ] **Step 11: Close the check and commit**

```bash
$T check status
$T check end
git add script/devpi/tests/test_web.py script/devpi/tests/test_disruptive.py
git commit -m "Add device tests for closed app ports, the view-only /feeds, download errors, the proxy outliving the pod, and the pod outliving a network failure" -m "<trailer block>"
```

- [ ] **Step 12: Update PR #224 and mark it ready**

Draft PR #224 has been open since 2026-10-14. Ask the person first. Then check that it targets `dev` (Task 0 Step 3), and rewrite its description for the finished M1 with `gh api -X PATCH repos/glossyio/traffic-monitor/pulls/224 -F body=@<file>`; `gh pr edit` fails on this repo. Read the current description first, so the person's own edits aren't lost. The person marks it ready and merges it, with a merge commit like the stacks before it. Closing keywords only fire on merges into `main`, so close #211, #223, #232, and #256 by hand once it's in `dev`. Fill in:
- **Docs:** the pages Task 11 changed, in the PR template's Docs section.
- **Testing:** the check's checklist, with device names and addresses replaced by placeholders, plus the off-device results. Never include secret values.
- **Release notes:**
  - Direct app ports are closed; use the `/…` paths.
  - Frigate's restream ports and port 8080 aren't published.
  - The camera stream needs credentials.
  - Data export downloads now work through the proxy (#211).
  - Download errors return their HTTP status, and a download that fails partway ends instead of hanging (#223).
  - The pod starts even if its network unit fails once at boot (#232).
  - MQTT port 1883 is reachable only from the device unless `node-red-tm.env` sets a broker login, which the broker now enforces. `-C mqtt_lan` creates one. Home Assistant and display boards need it.
  - A broker login set earlier is now enforced and copied to Frigate. Add it to the air quality sensor before upgrading, or blank it.
  - New installs don't publish Frigate's object snapshots on MQTT (#256).
  - Upgrade with a full `tmsetup.sh` run.
- **AI assistance:** fill in the template's section.
