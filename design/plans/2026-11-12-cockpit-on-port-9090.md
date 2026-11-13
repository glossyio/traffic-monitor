# Cockpit on port 9090 only, with its account named: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cockpit opens at `http://<device>:9090/` and nowhere else, every Cockpit page works, the docs say how to open it and when to use it, and administrators are told which account to log in to it with.

**Architecture:** Cockpit goes back to its default setup: no URL root, no nginx location. The home page keeps its Cockpit tile for administrators, but the tile links to port 9090 on the name the browser used instead of a path on port 80. Cockpit's own login (the Raspberry Pi user account) is the only gate, as it already is on `:9090`. The name of that account, which the manifest already holds as `installing_user`, goes to administrators only: the home page's tile and setup's system-password step show it, and viewers stop receiving it from `GET /system/info`.

**Tech Stack:** Ansible role files and Jinja templates (`script/ansible/roles/tmsetup`, `container/revproxy`), Python 3.11 + FastAPI (tm-control backend, pytest), Vue 3 + Vuetify 3 + Vitest (tm-control UI), Material for MkDocs, the dev-Pi tooling (`script/devpi/tmdev.py`).

**Spec:** this file. It amends the Cockpit rows of `design/specs/2026-10-02-tm-control-platform-design.md` ("Cockpit at `/system/` behind the proxy, and directly on `:9090`"). The maintainer chose this on 2026-11-12 over keeping the proxy under another name.

**Status:** written 2026-11-12 against `origin/dev` at `e1b353f`, in the worktree `~/code/tm-cockpit-9090`, branch `bugfix/cockpit-port-9090/307`, for [issue 307](https://github.com/glossyio/traffic-monitor/issues/307). Task 3 folds in [issue 265](https://github.com/glossyio/traffic-monitor/issues/265) (name the account on the tile and the setup step), added on 2026-11-12 because Task 2 already rewrites the tile; the PR closes both issues.

## What was found

Checked on a bench Pi with Cockpit 371 (`371-1~bpo13+1`), 2026-11-12:

1. **Services, Logs, and Terminal say "Not found".** `cockpit.conf` sets `UrlRoot = /system/`, and Cockpit's own package for those pages is also named `system` (pages `system`, `system/services`, `system/logs`, `system/terminal`). Cockpit's link builder (`encode` in `base1/cockpit.js`) adds the root only when the link doesn't already start with `/<root>/`, so Services gets `/system/services`. Its reader (`decode`) then strips the root and looks for a page named `services`. Overview (`system`) is the one page of that package that gets the root, which is why it works and why its address reads `/system/system`. Any root that isn't a Cockpit package name avoids the "Not found", but not item 2.
2. **`http://<device>:9090/` answers 404.** With any `UrlRoot`, Cockpit serves only paths under it: `:9090/system/` loads, `:9090/` doesn't. The rescue page (`container/revproxy/html/unavailable.html.j2`) and four docs pages send people to the bare `:9090`.
3. **The login in front of `/system/` protects nothing.** Port 9090 stays open to the network on purpose (decided 2026-10-25: it's the rescue console), so the control app's check only adds a second login.

`/system/` was never in a release (it's on `dev` only), so no redirect from the old address is needed.

For issue 265, checked in the code at `e1b353f`:

4. **Nothing shows the account name.** Setup's system-password step says "a system account", and the Cockpit tile says "Log in with the system password".
5. **Viewers already receive it.** `GET /system/info` returns `tm.installing_user` to every logged-in user (`test_system_info_for_a_viewer` expects it), which issue 265 rules out. No page reads the field.

## Global Constraints

- Cockpit's port is `9090`, plain HTTP. `cockpit.conf` keeps exactly `AllowUnencrypted = true` and `LoginTo = false` under `[WebService]`.
- The tile's link is `http://<the hostname the browser used>:9090/`. No new manifest key and no new role variable: `9090` is a literal in `APPS`, as it is in the rescue page.
- The tile stays admin-only on the home page. That hides a link; it isn't access control, and no text may say it is.
- No page, comment, or test may describe Cockpit as "behind the login" or "through the proxy" afterwards.
- The account name reaches administrators only. A viewer gets `null` in both places that carry it, and a request without a session gets 401. The diagnostics download (administrators only) keeps it.
- Where the name isn't known (the request failed, or an older answer), every text falls back to its wording without a name. No text may show "null", "undefined", or an empty pair of commas.
- Docs follow "Writing docs" and its "Style" rules in `docs/development/contributing.md`. Read them before Task 5.
- Commit trailers and the PR's "AI assistance" section follow `CLAUDE.md` ("AI use in this repository"). Ask the maintainer for the interface and effort level; never guess.
- Keep device names and addresses out of commits, the PR, and this file.
- Nothing is pushed until the maintainer has read the commit messages and the PR text.

## Review Focus

1. **Home page opened by IP, by `<name>.local`, or by an IPv6 literal:** the tile uses the same name with `:9090`. Pinned by the `appHref` tests in Task 2 (`window.location.hostname` keeps an IPv6 literal's brackets).
2. **The control app or nginx is down:** `:9090/` still loads. tm-control stopped is pinned by Task 4's disruptive test; nginx stopped is bench item B5.
3. **A device upgraded from today's `dev`:** the location file is deleted from the device, `/etc/cockpit/cockpit.conf` is rewritten, and Cockpit restarts. Bench items B1 to B4 run on a unit that had the old setup.
4. **A viewer:** sees no Cockpit tile, and can reach Cockpit's login page by typing the address, as before. The docs say so (Task 5); the backend test for viewers' tiles stays. A viewer also gets no account name: pinned by Task 3's backend tests and Task 4's device test.
5. **A single `-t` run on an old device:** `base` runs with every tag and rewrites `cockpit.conf`, while the location file and the tile change only with the edge tags. A device left like that has a `/system/` tile that opens a broken page until the whole installer runs. That's the documented rule ("a single `-t` assumes the rest of the device already runs the same version"); say it in the PR's upgrade note, and don't add code for it.
6. **The setup step can't read the name** (the request fails, or the claim just happened and the answer is slow): the step shows its text without a name and still works. Pinned by Task 3's setup test.
7. **Fake mode on a laptop:** the tile links to `localhost:9090`, where nothing listens. Accepted.

---

### Task 1: The installer stops proxying Cockpit

**Files:**
- Modify: `script/ansible/roles/tmsetup/files/cockpit.conf`
- Delete: `container/revproxy/tm/locations/cockpit.conf.j2`
- Modify: `script/ansible/roles/tmsetup/vars/main.yml` (`tmsetup_revproxy_locations`)
- Modify: `script/ansible/roles/tmsetup/tasks/start_services.yml` (one comment)
- Modify: `container/revproxy/tm/locations/tm-control-auth.conf.j2`, `container/revproxy/tm/snippets/proxy-common.conf.j2` (comments only)
- Test: `script/tests/test_tmsetup_templates.py`

**Interfaces:**
- Produces: `tmsetup_revproxy_locations` without `cockpit.conf`, which is what the manifest's `revproxy_locations` carries to tm-control (Task 2 must not depend on it for Cockpit).

- [ ] **Step 1: Write the failing tests** in `script/tests/test_tmsetup_templates.py`, using the file's `REPO`, `LOCATIONS`, and `location()` helpers (add `import configparser`):

```python
def test_cockpit_serves_its_own_port_at_the_root():
    """A UrlRoot makes Cockpit answer 404 at :9090/, and a root named for one of Cockpit's own packages (as /system
    was) breaks that package's links."""
    conf = configparser.ConfigParser()
    conf.read(REPO / "script/ansible/roles/tmsetup/files/cockpit.conf")
    assert dict(conf["WebService"]) == {"allowunencrypted": "true", "loginto": "false"}


def test_nginx_does_not_proxy_cockpit():
    assert "cockpit.conf" not in LOCATIONS
    assert not (REPO / "container/revproxy/tm/locations/cockpit.conf.j2").exists()
    assert all("9090" not in location(name) for name in LOCATIONS)
```

- [ ] **Step 2: Run them and see both fail**

Run: `python -m pytest script/tests/test_tmsetup_templates.py -k cockpit -v`
Expected: both new tests FAIL (`urlroot` and `protocolheader` present; `cockpit.conf` listed).

- [ ] **Step 3: Make the change**
  - `files/cockpit.conf`: delete the `ProtocolHeader` and `UrlRoot` lines.
  - Delete `container/revproxy/tm/locations/cockpit.conf.j2` and its line in `tmsetup_revproxy_locations`. The role already removes location files on the device that aren't in the list.
  - In the same test file: drop `"cockpit.conf"` from `APP_LOCATIONS`, and drop the Cockpit line from `test_host_apps_are_proxied_on_loopback` (rename the test if it then covers one app). `test_unavailable_page_names_cockpit_and_the_service` stays as it is: its `:9090/` link is now correct.
  - Comments: `start_services.yml` ("starts Cockpit on demand for /system/" becomes "on port 9090"); both `Authorization ""` comments in `tm-control-auth.conf.j2` and the matching comment in the test (the header is still blanked, so no credential a client sends reaches tm-control; Cockpit is no longer the reason); `proxy-common.conf.j2` (drop "such as Cockpit").

- [ ] **Step 4: Run the off-device checks**

Run: `python -m pytest script/tests -q` and `(cd script/ansible && ansible-playbook -i localhost setup.yml --syntax-check </dev/null)`
Expected: all pass.

- [ ] **Step 5: Commit** — `Serve Cockpit on port 9090 only, at its root`

### Task 2: The home page's Cockpit tile links to port 9090

**Files:**
- Modify: `tm-control/backend/tm_control/modules/system/router.py` (`APPS`, `device()`)
- Modify: `tm-control/backend/tests/test_api_system.py`, `tm-control/backend/tests/fixtures/manifest.json`
- Modify: `tm-control/ui/src/api/types.ts` (`DeviceApp`), `tm-control/ui/src/modules/home/apps.ts`, `tm-control/ui/src/modules/home/HomePage.vue`
- Modify: `tm-control/ui/src/modules/device/index.ts` (comment), `tm-control/ui/src/modules/account/UsersPage.vue` (one sentence)
- Test: `tm-control/ui/tests/home-page.spec.ts`, `tm-control/ui/tests/router.spec.ts`

**Interfaces:**
- Produces (API): each item of `GET /api/v1/system/device`'s `apps` gains `"port": int | null`. Cockpit is `{"id": "cockpit", "path": "/", "title": "Cockpit", "admin_only": true, "port": 9090}`; every other app has `"port": null`.
- Produces (UI): `appHref(app: Pick<DeviceApp, 'path' | 'port'>, hostname: string = window.location.hostname): string` in `apps.ts`.

- [ ] **Step 1: Backend tests first.** In `test_api_system.py`:
  - `test_device_card_and_apps_for_an_admin`: every expected app gets `"port": None`, and the last is the Cockpit item above.
  - `test_apps_follow_the_manifest_locations`: remove `"go2rtc.conf"` instead of `"cockpit.conf"` and expect `["dashboard", "frigate", "legacy-ui", "nodered", "cockpit"]`. This pins that Cockpit's tile no longer depends on a location file.
  - `fixtures/manifest.json`: remove `"cockpit.conf"` from `revproxy_locations`.

Run: `python -m pytest tm-control/backend/tests/test_api_system.py -q` — Expected: the two tests FAIL.

- [ ] **Step 2: Backend.** `APPS` rows become `(location file or None, id, path, title, admin_only, port or None)`; Cockpit's row is `(None, "cockpit", "/", "Cockpit", True, 9090)`. A row with no location file is always installed. Update the comment above `APPS` to say so. Run the backend suite: `python -m pytest tm-control/backend/tests -q` — Expected: PASS.

- [ ] **Step 3: UI tests first.** In `home-page.spec.ts` (import `ADMIN` from `./fake-api` and `appHref` from the module):

```ts
it('links an app on its own port to that port, on the name the browser used', async () => {
  const apps = [
    { id: 'frigate', path: '/frigate/', title: 'Frigate', admin_only: false, port: null },
    { id: 'cockpit', path: '/', title: 'Cockpit', admin_only: true, port: 9090 },
  ]
  signedIn(ADMIN, { 'GET /api/v1/system/device': { ...DEVICE, apps } })
  const { wrapper } = await mountApp('/')
  expect(wrapper.find('main a[href="/frigate/"]').exists()).toBe(true)
  expect(wrapper.find(`main a[href="http://${window.location.hostname}:9090/"]`).exists()).toBe(true)
})

it('builds a port link from any kind of hostname', () => {
  expect(appHref({ path: '/frigate/', port: null }, 'tm.local')).toBe('/frigate/')
  expect(appHref({ path: '/', port: 9090 }, 'tm.local')).toBe('http://tm.local:9090/')
  expect(appHref({ path: '/', port: 9090 }, '192.0.2.10')).toBe('http://192.0.2.10:9090/')
  expect(appHref({ path: '/', port: 9090 }, '[2001:db8::1]')).toBe('http://[2001:db8::1]:9090/')
})
```

  In `router.spec.ts`, delete `has no page under /system, which nginx sends to Cockpit`: the reason is gone.

- [ ] **Step 4: UI.** Add `port: number | null` to `DeviceApp`; add `appHref` to `apps.ts` (scheme is always `http:`, since Cockpit is set up for plain HTTP); the tile's `:href` in `HomePage.vue` uses it. Cockpit's description in `apps.ts` becomes `'Services, logs, updates, and a terminal, on port 9090. Log in with the system password.'` (Task 3 adds the account's name to it). In `device/index.ts`, drop "Not /system: nginx sends that to Cockpit." In `UsersPage.vue`, the sentence becomes "Viewers can open the dashboards and Frigate. They can't open the Node-RED editor or the camera feeds, and can't change settings."

- [ ] **Step 5: Build and test the UI in the pinned Node image**

Run: `podman run --rm -v "$PWD/tm-control/ui:/ui:Z" -w /ui docker.io/library/node:22.23.4-alpine sh -c 'npm ci && npm run build && npm test'`
Expected: build succeeds, all tests pass.

- [ ] **Step 6: Commit** — `Link the home page's Cockpit tile to port 9090`

### Task 3: Name the system account for administrators (issue 265)

**Files:**
- Modify: `tm-control/backend/tm_control/modules/system/router.py` (`device()`, `info()`), `tm-control/backend/tm_control/modules/system/info.py` (`TmInstall`)
- Modify: `tm-control/backend/tests/test_api_system.py`, `tm-control/backend/tests/test_api_system_info.py`
- Regenerate: `tm-control/ui/src/api/openapi.json`, `tm-control/ui/src/api/schema.d.ts` (never by hand; the commands are in `tm-control/ui/README.md`)
- Modify: `tm-control/ui/src/api/types.ts` (`Device`), `tm-control/ui/src/modules/home/apps.ts`, `tm-control/ui/src/modules/home/HomePage.vue`, `tm-control/ui/src/modules/setup/SetupPage.vue`
- Test: `tm-control/ui/tests/home-page.spec.ts`, `tm-control/ui/tests/setup-flow.spec.ts`

**Interfaces:**
- Consumes: Task 2's `DeviceApp` and the Cockpit description in `apps.ts`.
- Produces (API): `GET /api/v1/system/device` gains a top-level `"system_user": str | null`: the manifest's `installing_user` for an administrator, `null` for a viewer. `GET /api/v1/system/info`'s `tm.installing_user` becomes `str | null`, `null` for a viewer.
- Produces (UI): `Device.system_user: string | null`; `appDetails(id: string, systemUser: string | null = null): AppDetails`.

- [ ] **Step 1: Backend tests first.**
  - `test_api_system.py`: in `test_device_card_and_apps_for_an_admin`, `body["system_user"] == "pi"`; in `test_viewers_see_no_admin_tiles`, `r.json()["system_user"] is None`. `test_the_device_card_needs_a_login` already pins the 401.
  - `test_api_system_info.py`: `test_system_info_for_a_viewer` expects `"installing_user": None`. Add `test_system_info_names_the_installing_user_for_an_admin`: logged in as the administrator, `r.json()["tm"]["installing_user"] == "pi"`. The diagnostics test that looks for `"installing_user": "pi"` stays unchanged.

Run: `python -m pytest tm-control/backend/tests/test_api_system.py tm-control/backend/tests/test_api_system_info.py -q` — Expected: the changed and new tests FAIL, except the administrator's, which passes already.

- [ ] **Step 2: Backend.** `device()` adds `system_user`. `TmInstall.installing_user` becomes `str | None`, and the `info` route sets it to `None` unless the user is an administrator; `system_info()` itself is unchanged, so diagnostics still gets the name. Run the backend suite — Expected: PASS. Then regenerate `openapi.json` and `schema.d.ts`.

- [ ] **Step 3: UI tests first.**
  - `home-page.spec.ts`: with `ADMIN` and a device whose `system_user` is `'pi'` and whose apps include Task 2's Cockpit item, the Cockpit tile's text contains `Log in as pi with the system password.`; with `system_user: null`, it contains `Log in with the system password.` and not `Log in as`.
  - `setup-flow.spec.ts`, using that file's own way of reaching the system-password step: when `GET /api/v1/system/device` answers with `system_user: 'pi'`, the step's text contains `a system account, pi, for Cockpit`; when that request has no answer (the fake API's 404), the step's text contains `a system account, for Cockpit`, and the password form still submits. After the job succeeds with the name known, the success alert contains `as pi`.

- [ ] **Step 4: UI.**
  - `apps.ts`: `appDetails` takes the name. With one, Cockpit's description is `` `Services, logs, updates, and a terminal, on port 9090. Log in as ${systemUser} with the system password.` ``; without, Task 2's text. `HomePage.vue` passes `device.value?.system_user`.
  - `SetupPage.vue`: when the page switches to the system-password section, read `system_user` from `GET /api/v1/system/device` once; a failure is silent and leaves the name unknown. With a name, the three texts read as below, the name in `<strong>`; without one, they stay as they are today.
    - Intro: "The device also has a system account, **pi**, for Cockpit (the device's system tools) and SSH. Give it a new password now, or skip this and keep the password it has."
    - Success: "System password set. From now on, log in to Cockpit (the device's system tools) and over SSH as **pi** with this password."
    - Timed out: today's text, with "log in to Cockpit as **pi** with the new password".

- [ ] **Step 5: Build and test the UI** with Task 2's `podman run` command — Expected: build succeeds, all tests pass.

- [ ] **Step 6: Commit** — `Name the system account on the Cockpit tile and the setup step`

### Task 4: Device tests

**Files:**
- Modify: `script/devpi/tests/test_web.py`, `script/devpi/tests/test_disruptive.py`

- [ ] **Step 1: `test_web.py`.** Remove `"/system/"` from `APP_PATHS`, `ADMIN_OPENS`, and `VIEWER_STATUSES`, and Cockpit from the comment above `ADMIN_OPENS`. Add:

```python
COCKPIT_PORT = 9090


def test_cockpit_answers_at_the_root_of_its_own_port(address):
    """Cockpit is the rescue console: its login page loads at http://<device>:9090/, with no path, and without
    nginx or the control app's login."""
    answer = request_from_this_machine(f"{address}:{COCKPIT_PORT}", "/")
    html = answer.headers.get("Content-Type", "").startswith("text/html")
    assert (answer.status, html) == (200, True), "Cockpit on port 9090: (status, an HTML page)"


def test_nginx_does_not_proxy_cockpit(address):
    """/system/ is no app's path any more: nginx serves the control app's page for it and asks for no login."""
    answer = request_from_this_machine(address, "/system/")
    assert (answer.status, answer.headers.get("Location")) == (200, None), "/system/ without a session"
```

- [ ] **Step 2: `test_disruptive.py`.** In `test_app_paths_fail_closed_when_tm_control_is_down`, while tm-control is stopped (inside the `try`), also read Cockpit's status on the Pi (`curl -s -o /dev/null -w '%{http_code}' --max-time 10 http://localhost:9090/` through `host.run`), and after the existing assertions assert it is `"200"`: the rescue page's link must load while the control app is down. Extend the docstring by one clause.

- [ ] **Step 3: The account name, in `test_web.py`.** With the fixtures `admin_session` and `viewer_session`, read `GET {API}/system/device` and `GET {API}/system/info` as each. The administrator's `system_user` and `tm.installing_user` are non-empty strings; the viewer's are both `None`. Put no value in an assertion message: say only which field of which answer was wrong.

- [ ] **Step 4: Check they collect.** Run: `python -m pytest script/devpi/tests --collect-only -q` — Expected: no errors (they run for real in Task 6).

- [ ] **Step 5: Commit** — `Test Cockpit on its own port and the account name on a device`

### Task 5: Docs

**Files (each checked against the change; the list is what `grep -rn -i "cockpit\|/system/\|9090"` finds today):**
- `docs/use/system-admin.md`, `docs/use/home-page.md`, `docs/use/control-app.md`, `docs/reference/network.md`, `docs/development/tm-control.md`, `README.md`
- `CLAUDE.md`, `script/devpi/README.md`, `tm-control/ui/README.md` (only if a line there is now wrong)
- `design/specs/2026-10-02-tm-control-platform-design.md` (one sentence)

- [ ] **Step 1: `docs/use/system-admin.md`, the Cockpit section.** Replace its one paragraph with this (adjust wording to the style rules, keep the facts):

```markdown
## Cockpit

[Cockpit](https://cockpit-project.org/) is the device's system console in the browser. It shows the services and their logs, the Podman containers, system updates, and the user accounts, and it has a terminal, so most administration needs no SSH client.

Open `http://<device>:9090/`, with the same name or address you use for the home page, and log in with your Raspberry Pi user account. Administrators also have a **Cockpit** tile on the home page, which opens the same address and names the account to log in with.

Cockpit has its own port and its own login. It doesn't need the home page, the [control app](control-app.md), or the apps, so it still opens when they don't. Use it when:

* the home page doesn't load, or a page says the control app isn't answering
* you want to restart a service, or read its log
* you need a terminal and have no SSH client
* you want to install system updates or change the system password

For everyday checks, start with the control app's [Status page](device-health.md#the-status-page).

!!! info "Who can open Cockpit"

    Anyone on your network can reach Cockpit's login page. Only the Raspberry Pi user account gets past it. The control app's accounts don't work there.
```

- [ ] **Step 2: The other user pages.**
  - `home-page.md`: Cockpit's row gets the address `http://<device>:9090/`, and "Who" becomes administrators see the tile, and anyone with the Raspberry Pi user account can log in. Say above or below the table that Cockpit is the one app with its own port.
  - `control-app.md`: the opening paragraph's list of apps the login opens ends at the camera feeds, followed by one sentence that Cockpit has its own address and login, linking to `system-admin.md#cockpit`. In the roles table, the row becomes "Node-RED editor and Camera feeds", with one sentence under the table that Cockpit uses the Raspberry Pi user account, not these accounts. In "The system password", add that setup's system-password step and the home page's Cockpit tile show administrators the account's name, for whoever didn't install the device.
  - `network.md`: the 9090 row says Cockpit, with your Raspberry Pi login; the home page's Cockpit tile opens it; it works when the home page doesn't.
  - `README.md`: the `/system/` bullet becomes `http://<device_ip_address>:9090/`, with the Raspberry Pi login only.

- [ ] **Step 3: Developer and repo docs.**
  - `docs/development/tm-control.md`: take Cockpit out of the "No identity" row and out of the `Authorization` rule; in "A new app behind the login", add that an app on its own port is an `APPS` row with no location file and a port. Wherever the page lists what `GET /system/device` or `GET /system/info` returns, add `system_user` and the viewers' `null`.
  - `CLAUDE.md`: Cockpit leaves the list of UIs behind the login, the list of paths nginx proxies, the list of apps nginx reaches, and the `Authorization` parenthesis. Add one sentence where the UIs are listed: Cockpit is only on `:9090`, with no `UrlRoot`, because a root makes `:9090/` a 404 and a root named for a Cockpit package breaks that package's links. Mention the `APPS` port column where the new-app steps are.
  - `script/devpi/README.md`: the PR-check example uses `/system/`; change it to this change's check (title "Cockpit on port 9090", `curl ... http://localhost:9090/`).
  - The spec: at the end of the Cockpit row of its decisions table, add "Changed 2026-11-12: Cockpit is on `:9090` only; see `design/plans/2026-11-12-cockpit-on-port-9090.md`." Leave the rest of the spec and the older plans as the record.

- [ ] **Step 4: Check nothing still points at the old address.**

Run: `git grep -n -i "/system/" -- docs README.md CLAUDE.md script/devpi/README.md tm-control/ui/README.md | grep -v "api/v1/system\|systemd"`
Expected: no line about Cockpit.

Run: `~/.venvs/tm-docs/bin/mkdocs build --strict`
Expected: builds with no warnings.

- [ ] **Step 5: Commit** — `Document Cockpit's address and when to use it`

### Task 6: Bench run, then hand over for review

Run on the bench Pi the maintainer names (it must still have today's `dev` setup, so the upgrade path is what's tested). Read `script/devpi/README.md` first. Run `tmdev.py` from this worktree with the tools checkout's Python (`~/code/tm-devpi/.venv/bin/python`), so the device tests are this branch's.

- [ ] **Step 1: Make sure no other check is open.** `tmdev.py check status`. Only one check can be open, and `tmdev.py run` logs into whichever is open, even one for another host. If another session's check is open, ask the maintainer; the usual answer is a separate run log for this work, by setting `TM_DEV_LOG_DIR` on every `tmdev.py` command (`script/devpi/README.md`).

- [ ] **Step 2: Open the check and run the whole installer** (`check start` with `--src` set to this worktree, then `deploy <host>`). Ask the maintainer before anything that reboots.

- [ ] **Step 3: Record each item with `check item`:**

| # | Item | How |
|---|---|---|
| B1 | `:9090/` answers 200 (it was 404) | `curl -s -o /dev/null -w '%{http_code}' http://localhost:9090/` on the Pi |
| B2 | `/etc/cockpit/cockpit.conf` has only `AllowUnencrypted` and `LoginTo` | `cat` it |
| B3 | The device's nginx locations no longer include `cockpit.conf` | list the rendered locations directory |
| B4 | The device tests pass | `tmdev.py test <host>`, then `tmdev.py test <host> --disruptive -- -k fail_closed`; name any failure the inventory already expects for that unit |
| B5 | Cockpit answers with nginx stopped | stop `revproxy.service`, repeat B1's `curl`, start it again |
| B6 | Manual, by the maintainer (it needs the Raspberry Pi password): as an administrator, the home page's Cockpit tile opens `:9090`; the tile names the Raspberry Pi account; after logging in, Overview, Services, Logs, and Terminal each load, and the address bar reads `/system`, `/system/services`, `/system/logs`, `/system/terminal` | browser |
| B7 | Manual: a viewer's home page has no Cockpit tile | browser |
| B8 | Manual, only if the maintainer agrees to unclaim the bench unit (`sudo tm-control reset-admin`): setup's system-password step names the account | browser |

- [ ] **Step 4: Close the check** (`check end`).

- [ ] **Step 5: Stop for review.** Give the maintainer the commit messages and a PR draft that fills in the template, including: the findings above in a few sentences, that it closes issues 307 and 265, the upgrade note from Review Focus 5, the docs pages changed, and the bench results without device names. Push nothing until they say so.
