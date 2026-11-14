# Home button on every app, and the unit's name in every tab: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** From every app nginx proxies, one press on a small, movable home button returns to the control app; every tab names the unit; a viewer who opens an admin app gets a page instead of a bare 403; and the two install-time hostname copies the button replaces are gone.

**Architecture:**
- nginx adds one `<script src="/home-button.js" defer></script>` line to each proxied app's HTML with `sub_filter`, from a new snippet the five app locations include. A `map` asks the app for an uncompressed answer only on a page load, so everything else stays compressed.
- The script is TypeScript in `tm-control/ui/src/home-button/`, built by a second, tiny Vite build to `dist/home-button.js` (one self-contained file, no Vue, no Vuetify). It draws the button in a shadow root, reads the live hostname and colors from `GET /api/v1/system/device`, and prefixes the tab's title.
- The control app's own tab and bar get the name from the same API call, held in the session store.
- `GET /auth/verify` sends a viewer's page load on an admin path to a new `/admin-only` page; anything else keeps its 403.
- The rescue page's Cockpit link is written by nginx from `$host` (a server-side include), and the Node-RED editor's hostname title is removed.

**Tech Stack:** nginx 1.31.0 (`sub_filter`, `map`, `ssi`; all in the pinned image), Jinja templates in the Ansible role, Python 3.11 + FastAPI (pytest), Vue 3 + Vuetify 3 + TypeScript + Vite 7 (Vitest, jsdom), Material for MkDocs, the dev-Pi tooling (`script/devpi/tmdev.py`). No new dependency in any of them.

**Issue:** #TBD (a way back to the control app from every app, and the device's name in every tab). Also closes #263.

**Status:** written 2026-11-13 against `dev` at `b4a26f1`. Not started. Branch: `feature/home-button/<id>`, off `dev`, in its own worktree. The PR also closes [issue 263](https://github.com/glossyio/traffic-monitor/issues/263). The open Detection PRs (315, 318) don't touch these files apart from the regenerated `openapi.json` and `schema.d.ts`; whichever merges second regenerates them.

**Models:** implementers on Sonnet 5.5, except Task 4 (the button's behavior), which is marked tricky (Opus 5.5). Per-task reviews on Sonnet 5.5; the final whole-branch review on Fable 5.2. Tasks 3, 4, 5, and 6 touch the UI: their implementers load `frontend-design` and the superpowers TDD and verification skills, and the constraint (conventional Vuetify for the pages, the control app's colors for the button) wins over any flourish. Stop for the maintainer after Task 4 (the button can be tried on a laptop) and before Task 9 (the bench).

**Decisions made while writing this plan** (calls, open to change):
1. **The rescue page uses a server-side include, not a script.** `<!--# echo var="host" -->` with `ssi on` in its location. The page's test has refused `<script` since it was written, and this keeps that. Checked in the pinned image: `tm-01.local` and `[fd00::1]` come out right, and nginx answers a malformed `Host` with 400 before the page.
2. **A second Vite build, not a second entry.** `vite.home-button.config.ts` builds `src/home-button/entry.ts` in library mode as an IIFE named `home-button.js` into `dist/` without emptying it. The main build stays as it is.
3. **The size limit is in that build.** A small plugin in the config fails the build when `home-button.js` is over 10 240 bytes.
4. **The colors' defaults move** from `src/theme.ts` to a new `src/colors.ts` with no Vuetify import, so the script can use them. `theme.ts` re-exports `DEFAULT_COLORS`, so nothing else changes.
5. **The page's name in the tab comes from the menu entry** whose `to` is the route's path, or from the route's `meta.title` where a page has no menu entry.
6. **An off-device test runs the real config** in the pinned nginx image with a stub app behind it (Task 1). It is the only proof short of a Pi that the script line arrives.
7. **While the app's own title is empty** (the old dashboard, for a moment), the tab's title is the hostname alone.
8. **The viewer page's code is `admin_only`**, and its route is `/admin-only`.
9. **Added after the maintainer tried the demo page:** the Traffic Monitor logo (the project website's favicon, cleaned up) is the control app's favicon, served as /favicon.svg; the home button keeps the house icon, which reads as "home" at 20 px where the logo doesn't. Four small hardening fixes from review went in at the same time (Escape stays inside the button, no drag from a hover, the click swallow can't eat a later press, the size limit counts bytes).

## Where `dev` left things that this plan touches

- nginx (`container/revproxy/`): `nginx.conf.j2` (one `http` block; maps `$connection_upgrade`, `$tm_sign_in`, `$tm_on_hotspot`); `tm/snippets/` (`proxy-common`, `auth-viewer`, `auth-admin`), listed in `tmsetup_revproxy_snippets` (`vars/main.yml`); `tm/locations/` (`dashboard`, `frigate`, `go2rtc`, `legacy-ui`, `nodered` are the apps with pages; `storefiles` is downloads); `tm-control-auth.conf.j2` holds `location = /unavailable.html { internal; root /usr/share/nginx/html; }`; `html/unavailable.html.j2` uses `ansible_facts['hostname']` twice. `tm-control-ui.conf.j2` serves `/usr/share/nginx/ui` at `/` with `Cache-Control: no-cache`, which is where `home-button.js` will be.
- Role tests (`script/tests`): `test_tmsetup_templates.py` (`location(name)`, `snippet(name)`, `nginx_main_conf()`, `location_block`, `APP_LOCATIONS`, `test_snippets_are_listed`, `test_no_app_location_adds_its_own_headers`, `test_unavailable_page_names_cockpit_and_the_service`, `test_failed_logins_redirect_and_the_rescue_page_is_internal`); `test_nginx_config_parses.py` (`ROLE_VARS`, `render_config(root)`, `have_image(image)`, the Podman pattern); `required_tools.py` (`needs`, `missing_tool`); `test_node_red_settings.py` (`SETTINGS`).
- Backend: `modules/auth/router.py::verify` (the 403 is its role check, just before the 200's headers); `tests/test_api_auth.py` (`verify(client, uri, role)`, `add_viewer`, `VIEWER`, `login`, `test_verify_gives_viewers_no_node_red_token_and_403_on_admin_paths`); `tests/test_openapi_document.py` fails when `ui/src/api/openapi.json` doesn't match `python -m tm_control dump-openapi` (verify's docstring is in it).
- UI (`tm-control/ui`): `src/App.vue` (the frame; `<v-app-bar-title>` reads "Traffic Monitor"); `src/router.ts` (`RouteMeta`, `redirectFor`); `src/stores/session.ts`; `src/modules/index.ts` (`MODULES`, `NavItem`); `src/modules/auth/index.ts`; `src/theme.ts` (`DEFAULT_COLORS`, `HEX_COLOR`, `buildTheme`); `src/next.ts` (`APP_PATHS` still lists `/system`); `src/api/types.ts` (`Device`, which lacks the `theme` the API returns). Tests: `tests/mount.ts` (`mountApp(path)`), `tests/fake-api.ts` (`fakeApi`, `status`, `ADMIN`, `VIEWER`, `THEME`), `tests/router.spec.ts` (its last test pins the exact requests a navigation makes), `tests/theme.spec.ts`, `tests/next.spec.ts`. Build: `npm run build` is `vue-tsc --noEmit && vite build`; `tsconfig.json` includes `src`, `tests`, and `vite.config.ts`.
- Device tests (`script/devpi/tests`): `test_web.py` (`request_from_this_machine(address, path, method, cookie, body, headers)` returns an `Answer` with `.status`, `.headers`, `.body`; `admin_session`, `viewer_session`; `VIEWER_STATUSES`); `test_disruptive.py` (the rescue-page test counts the lines naming 9090).

## Global Constraints

- The script line is exactly `<script src="/home-button.js" defer></script>`, added before `</head>`, once per page.
- The five app locations that get it: `dashboard.conf`, `frigate.conf`, `go2rtc.conf`, `legacy-ui.conf`, `nodered.conf`. Never `storefiles.conf` or a `tm-control-*` location.
- No app location gains an `add_header`. `test_no_app_location_adds_its_own_headers` stays as it is and passes.
- Nothing about the hotspot's sign-in rule (`$tm_sign_in`) changes.
- No hostname is written into a page or config file by the installer in anything this plan adds. `ansible_facts['hostname']` stays only in `nginx.conf.j2`'s sign-in map and `main.yml`'s closing notice.
- The script: no dependency beyond one icon path from `@mdi/js`; no import of `vue`, `vuetify`, `pinia`, or any file that imports them; at most 10 240 bytes built.
- The button: narrow means the window is under 600 px wide; 40 px round button with a touch target of at least 44 px; a drag is a movement of more than 8 px; it settles on the left or right edge; it tucks when dropped within 12 px of an edge; storage key `tm-home-button`; apps `dashboard`, `frigate`, `ui`, `nr`, `feeds`.
- Titles: the control app after login `<hostname> · <Page> | Traffic Monitor`; before login, on setup, and on the license pages `Traffic Monitor`; on an app `<hostname> · <the app's title>`.
- `flows.json` is not touched.
- Copy uses the UI's words: "Log out", "administrator", "viewer". Docs follow "Writing docs" and its "Style" rules in `docs/development/contributing.md`.
- Commit trailers and the PR's "AI assistance" section follow `CLAUDE.md` ("AI use in this repository"). Ask the maintainer for the interface and effort level; never guess.
- Keep device names and addresses out of commits, the PR, the docs, and the public copy of this plan. Examples use `tm-01`.
- Nothing is pushed until the maintainer has read the commit messages and the PR text.
- No Frigate detection, snapshots, or recording is turned on for any step. Device tests read HTML and headers only, never an image.

## Review Focus

1. **A page embedded in another page** (a stream inside a dashboard): no button inside the frame. Pinned in Task 4 (`start` does nothing when `win.top !== win.self`).
2. **Browser storage that throws or holds junk** (private mode, an old or hand-edited entry): the button appears at its default spot. Pinned in Task 3 (`readPlaces`).
3. **The device call fails** (control app restarting, session just ended): the icon alone, the title untouched, the link still `/`. Pinned in Task 4.
4. **An app that rewrites its title** on every view (Frigate): the prefix stays, once, without a loop. Pinned in Tasks 3 (`titled`) and 4 (the observer).
5. **A viewer's download** from the Data export page, which falls back to a plain `/storefiles` link: the browser lands on `/admin-only`, and a script or `curl` still gets 403. Pinned in Task 6 (backend) and Task 7 (the device test, run in Task 9).

---

### Task 1: nginx adds the script line to the five apps' pages

**Files:**
- Create: `container/revproxy/tm/snippets/home-button.conf.j2`
- Create: `script/tests/test_nginx_home_button.py`
- Modify: `container/revproxy/nginx.conf.j2` (a `map` after `$connection_upgrade`'s)
- Modify: `container/revproxy/tm/locations/{dashboard,frigate,go2rtc,legacy-ui,nodered}.conf.j2` (one `include` each)
- Modify: `script/ansible/roles/tmsetup/vars/main.yml` (`tmsetup_revproxy_snippets`)
- Test: `script/tests/test_tmsetup_templates.py`, `script/tests/test_nginx_home_button.py`

**Interfaces:**
- Produces: every page under `/dashboard/`, `/frigate/`, `/ui/`, `/nr/`, `/feeds/` carries the script line; `/home-button.js` is whatever the UI build puts in `dist/` (Task 4).

- [ ] **Step 1: Write the failing template tests** in `test_tmsetup_templates.py`

```python
HOME_BUTTON = "include /etc/nginx/tm/snippets/home-button.conf;"
PAGE_LOCATIONS = ["dashboard.conf", "frigate.conf", "go2rtc.conf", "legacy-ui.conf", "nodered.conf"]


@pytest.mark.parametrize("name", LOCATIONS)
def test_only_the_apps_with_pages_get_the_home_button(name):
    assert location(name).count(HOME_BUTTON) == (1 if name in PAGE_LOCATIONS else 0)


def test_home_button_snippet_adds_one_script_line_and_no_header():
    lines = [line.strip() for line in snippet("home-button.conf").splitlines()]
    assert "sub_filter '</head>' '<script src=\"/home-button.js\" defer></script></head>';" in lines
    assert "sub_filter_once on;" in lines
    assert "proxy_set_header Accept-Encoding $tm_page_encoding;" in lines
    assert not [line for line in lines if line.startswith("add_header")]


def test_only_a_page_load_asks_the_app_for_an_uncompressed_answer():
    lines = [line.strip() for line in nginx_main_conf().splitlines()]
    start = lines.index("map $http_accept $tm_page_encoding {")
    assert lines[start + 1:start + 4] == ["default $http_accept_encoding;", '"~*text/html" "";', "}"]
```

Change `test_snippets_are_listed` to expect `home-button.conf` as the fourth name.

- [ ] **Step 2: Write the failing functional test** `script/tests/test_nginx_home_button.py`

It runs two containers of the pinned nginx image that share one network namespace (`podman run -d --name <stub> …`, then `podman run -d --network container:<stub> …`), and asks with `podman exec <stub> curl`. Reuse `ROLE_VARS`, `render_config`, and `have_image` from `test_nginx_config_parses`; decorate with `@needs("podman", "needs Podman")`; remove both containers in a `finally`; give the containers names that hold `os.getpid()`.

The stub's config (a string in the test), mounted as its `nginx.conf`, with a directory holding `index.html` (`<html><head><title>App</title></head><body>…</body></html>`) and `app.js`:

```nginx
events {}
http {
    include /etc/nginx/mime.types;
    server {  # tm-control's verify: always an administrator
        listen 127.0.0.1:{{ tmsetup_tm_control_port }};
        location / { add_header X-TM-User tester always; add_header X-TM-Role admin always; return 200; }
    }
    server {  # every app: compresses whatever it is allowed to
        listen 127.0.0.1:1880; listen 127.0.0.1:8971; listen 127.0.0.1:1984;
        gzip on; gzip_min_length 1; gzip_proxied any; gzip_http_version 1.0; gzip_types application/javascript;
        root /srv;
        add_header X-Saw-Accept-Encoding "[$http_accept_encoding]" always;
        location / { try_files $uri /index.html; }
    }
}
```

The tests (one container pair per module, as a module-scoped fixture):

```python
LINE = '<script src="/home-button.js" defer></script></head>'
PAGE = {"Accept": "text/html,application/xhtml+xml", "Accept-Encoding": "gzip, deflate"}


@pytest.mark.parametrize("path", ["/dashboard/", "/frigate/", "/ui/", "/nr/", "/feeds/"])
def test_a_page_load_gets_the_script_line_once(proxy, path):
    answer = proxy.get(path, PAGE)
    assert answer.status == 200
    assert answer.headers.get("x-saw-accept-encoding") == "[]"      # the app was asked for plain text
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
```

`proxy.get(path, headers)` runs `curl -s -i` with those headers against `http://127.0.0.1:80` inside the container and returns status, lower-cased headers, and the body as text (for a compressed answer, the body isn't read).

- [ ] **Step 3: Run both test files and see them fail**

Run: `python -m pytest script/tests/test_tmsetup_templates.py script/tests/test_nginx_home_button.py -q`
Expected: the new template tests fail (no snippet, no map), and the functional tests fail on the missing script line.

- [ ] **Step 4: Add the map, the snippet, the five includes, and the list entry**

`nginx.conf.j2`, after the `$connection_upgrade` map:

```nginx
    # A page load asks the app for an uncompressed answer, so home-button.conf can add its script line to the HTML.
    # Every other request keeps the browser's own Accept-Encoding. (An empty value sends no header.) A browser on
    # plain HTTP sends no Sec-Fetch-* headers, so Accept is what tells a page load from the rest.
    map $http_accept $tm_page_encoding {
        default $http_accept_encoding;
        "~*text/html" "";
    }
```

`tm/snippets/home-button.conf.j2`:

```nginx
# The home button: one script line added to an app's HTML page, which draws a link back to the control app
# (tm-control/ui/src/home-button). Include this in an app location that serves pages, beside its proxy-common.conf
# and auth snippet. No add_header here: the auth snippets' Set-Cookie must stay the location's only one.
proxy_set_header Accept-Encoding $tm_page_encoding;
sub_filter '</head>' '<script src="/home-button.js" defer></script></head>';
sub_filter_once on;
```

In each of the five location files, add `include /etc/nginx/tm/snippets/home-button.conf;` on the line after the location's `proxy-common.conf` include (in `nodered.conf.j2` and `go2rtc.conf.j2`, in the main location only, never in the deny blocks). Add `- home-button.conf` to `tmsetup_revproxy_snippets`.

- [ ] **Step 5: Run the role's tests**

Run: `python -m pytest script/tests -q`
Expected: all pass, including `test_rendered_config_passes_nginx_t` and `test_revproxy_renders_every_snippet_in_the_check_and_the_deployment`.

- [ ] **Step 6: Commit** (`Add the home button's script line to the proxied apps' pages`)

---

### Task 2: The rescue page and the Node-RED editor stop using the install-time hostname

**Files:**
- Modify: `container/revproxy/html/unavailable.html.j2`
- Modify: `container/revproxy/tm/locations/tm-control-auth.conf.j2` (the `/unavailable.html` location)
- Modify: `container/node-red-tm/data/settings.js` (`editorTheme.header`, `editorTheme.page`)
- Test: `script/tests/test_tmsetup_templates.py`, `script/tests/test_nginx_home_button.py`, `script/tests/test_node_red_settings.py`

**Interfaces:**
- Consumes: Task 1's `proxy` fixture.
- Produces: the Node-RED editor's own title is "Node-RED" (its default), which Task 4's prefix turns into `tm-01 · Node-RED`.

- [ ] **Step 1: Change and add the tests**

`test_unavailable_page_names_cockpit_and_the_service` renders without `ansible_facts` and asserts:

```python
    assert '<a href="http://<!--# echo var="host" -->:9090/">http://<!--# echo var="host" -->:9090/</a>' in page
    assert "<title>Traffic Monitor unavailable</title>" in page
    assert "tm-control.service" in page and "sudo systemctl restart tm-control.service" in page
    assert "<script" not in page and ".local" not in page
```

`test_failed_logins_redirect_and_the_rescue_page_is_internal` expects `location = /unavailable.html { internal; root /usr/share/nginx/html; ssi on; }`.

In `test_nginx_home_button.py`, mount a rendered `unavailable.html` at `/usr/share/nginx/html/unavailable.html` and add a second stub (or a second fixture) whose verify port isn't listening, so the login check fails:

```python
@pytest.mark.parametrize("host, shown", [("tm-01.local", "tm-01.local"), ("192.0.2.7", "192.0.2.7"),
                                         ("[2001:db8::7]", "[2001:db8::7]")])
def test_the_rescue_page_links_to_cockpit_on_the_name_the_browser_used(proxy_without_tm_control, host, shown):
    answer = proxy_without_tm_control.get("/dashboard/", {"Accept": "text/html", "Host": host})
    assert answer.status == 503
    assert f'<a href="http://{shown}:9090/">http://{shown}:9090/</a>' in answer.body
    assert "<!--#" not in answer.body
```

In `test_node_red_settings.py`:

```python
def test_the_editor_takes_no_name_from_the_installer():
    assert "TM_HOSTNAME" not in SETTINGS.read_text()
```

- [ ] **Step 2: Run them and see them fail**

Run: `python -m pytest script/tests/test_tmsetup_templates.py script/tests/test_nginx_home_button.py script/tests/test_node_red_settings.py -q`

- [ ] **Step 3: Make the changes**

- `unavailable.html.j2`: the title becomes `Traffic Monitor unavailable`; both uses of `http://{{ ansible_facts['hostname'] }}.local:9090/` become `http://<!--# echo var="host" -->:9090/`; the words "(or the device's IP address with port 9090)" go, since the link is now right for either.
- `tm-control-auth.conf.j2`: add `ssi on;` to the `/unavailable.html` location, and say why in its comment (the Cockpit link names the address the browser used).
- `settings.js`: remove the `header` and `page` entries of `editorTheme` with their comments.

- [ ] **Step 4: Run the role's tests** (`python -m pytest script/tests -q`), all pass

- [ ] **Step 5: Commit** (`Rescue page and Node-RED editor: no hostname copied at install`)

---

### Task 3: The button's logic, as plain functions

**Files:**
- Create: `tm-control/ui/src/colors.ts`
- Create: `tm-control/ui/src/home-button/place.ts`
- Modify: `tm-control/ui/src/theme.ts` (imports from `colors.ts`, re-exports `DEFAULT_COLORS`)
- Test: `tm-control/ui/tests/home-button-place.spec.ts`

**Interfaces:**
- Produces, from `src/colors.ts`:
  - `DEFAULT_COLORS` and `type ColorName` (moved as they are)
  - `colorOf(colors: Partial<Record<string, string>> | undefined, name: ColorName): string`, the device's color when it is a `#rrggbb` value, else the default (the body of `buildTheme`'s inner `color`)
- Produces, from `src/home-button/place.ts`:
  - `type Side = 'left' | 'right'`
  - `interface Place { side: Side; y: number; tucked: boolean }`, where `y` is the button's center as a fraction of the window's height, 0 to 1
  - `APPS = ['dashboard', 'frigate', 'ui', 'nr', 'feeds'] as const`
  - `appOf(pathname: string): string | null`
  - `defaultPlace(app: string, narrow: boolean): Place`
  - `dropped(x: number, y: number, width: number, height: number): Place`
  - `isDrag(dx: number, dy: number): boolean`
  - `topOf(place: Place, height: number, size: number): number`, the button's top in pixels, kept at least 8 px inside the window
  - `titled(hostname: string, title: string): string`
  - `readPlaces(storage: Pick<Storage, 'getItem'> | null): Record<string, Place>`
  - `savePlace(storage: Pick<Storage, 'getItem' | 'setItem'> | null, app: string, place: Place): void`
  - `STORAGE_KEY = 'tm-home-button'`, `NARROW = 600`, `DRAG_PX = 8`, `TUCK_PX = 12`

- [ ] **Step 1: Write the failing tests** `tests/home-button-place.spec.ts`

```ts
describe('appOf', () => {
  it.each([['/frigate/', 'frigate'], ['/frigate/review?x=1', 'frigate'], ['/nr/', 'nr'], ['/ui/', 'ui'],
           ['/dashboard/monitoring', 'dashboard'], ['/feeds/stream.html', 'feeds']])('%s is %s', (path, app) => {
    expect(appOf(path)).toBe(app)
  })
  it.each(['/', '/status', '/frigatex/', '/storefiles', '/api/v1/system/device'])('%s is no app', (path) => {
    expect(appOf(path)).toBeNull()
  })
})

describe('defaultPlace', () => {
  it('is bottom right', () => {
    expect(defaultPlace('dashboard', false)).toEqual({ side: 'right', y: 0.9, tucked: false })
    expect(defaultPlace('frigate', false)).toEqual({ side: 'right', y: 0.9, tucked: false })
  })
  it("is above Frigate's bottom bar on a narrow screen", () => {
    expect(defaultPlace('frigate', true)).toEqual({ side: 'right', y: 0.72, tucked: false })
    expect(defaultPlace('nr', true)).toEqual({ side: 'right', y: 0.9, tucked: false })
  })
})

describe('dropped', () => {
  it('settles on the nearer side at the height it was dropped', () => {
    expect(dropped(300, 400, 1000, 800)).toEqual({ side: 'left', y: 0.5, tucked: false })
    expect(dropped(700, 200, 1000, 800)).toEqual({ side: 'right', y: 0.25, tucked: false })
  })
  it('tucks when dropped within 12 px of an edge', () => {
    expect(dropped(12, 400, 1000, 800)).toEqual({ side: 'left', y: 0.5, tucked: true })
    expect(dropped(988, 400, 1000, 800)).toEqual({ side: 'right', y: 0.5, tucked: true })
    expect(dropped(13, 400, 1000, 800).tucked).toBe(false)
  })
  it('keeps the height between 0 and 1 when dropped outside the window', () => {
    expect(dropped(500, -50, 1000, 800).y).toBe(0)
    expect(dropped(500, 900, 1000, 800).y).toBe(1)
  })
})

it('calls a movement of more than 8 px a drag', () => {
  expect(isDrag(8, 0)).toBe(false)
  expect(isDrag(6, 6)).toBe(true)
})

it('keeps the button at least 8 px inside the window', () => {
  expect(topOf({ side: 'right', y: 0.5, tucked: false }, 800, 40)).toBe(380)
  expect(topOf({ side: 'right', y: 0, tucked: false }, 800, 40)).toBe(8)
  expect(topOf({ side: 'right', y: 1, tucked: false }, 800, 40)).toBe(752)
  expect(topOf({ side: 'right', y: 0.5, tucked: false }, 30, 40)).toBe(8)   // a window shorter than the button
})

describe('titled', () => {
  it.each([
    ['Live - Frigate', 'tm-01 · Live - Frigate'],
    ['', 'tm-01'],
    ['   ', 'tm-01'],
    ['tm-01', 'tm-01'],
    ['tm-01 · Live - Frigate', 'tm-01 · Live - Frigate'],
    ['tm-010 status', 'tm-01 · tm-010 status'],
  ])('%j becomes %j', (title, expected) => {
    expect(titled('tm-01', title)).toBe(expected)
  })
  it('leaves the title alone without a hostname', () => {
    expect(titled('', 'Frigate')).toBe('Frigate')
  })
})

describe('readPlaces and savePlace', () => {
  const stored = (text: string | null) => ({ getItem: () => text })
  it('reads what savePlace wrote, per app', () => {
    const data = new Map<string, string>()
    const storage = { getItem: (k: string) => data.get(k) ?? null, setItem: (k: string, v: string) => void data.set(k, v) }
    savePlace(storage, 'frigate', { side: 'left', y: 0.3, tucked: true })
    savePlace(storage, 'nr', { side: 'right', y: 0.6, tucked: false })
    expect([...data.keys()]).toEqual(['tm-home-button'])
    expect(readPlaces(storage)).toEqual({ frigate: { side: 'left', y: 0.3, tucked: true }, nr: { side: 'right', y: 0.6, tucked: false } })
  })
  it.each([null, '', 'not json', '[]', '"x"', '{"frigate": 5}', '{"frigate": {"side": "top", "y": 0.5, "tucked": false}}',
           '{"frigate": {"side": "left", "y": 7, "tucked": false}}', '{"frigate": {"side": "left", "y": 0.5}}'])(
    'drops an entry it cannot use: %j', (text) => {
      expect(readPlaces(stored(text))).toEqual({})
    })
  it('keeps the good entries beside a bad one', () => {
    const text = '{"frigate": {"side": "left", "y": 0.5, "tucked": false}, "nr": "junk", "other": {"side": "left", "y": 0.5, "tucked": false}}'
    expect(readPlaces(stored(text))).toEqual({ frigate: { side: 'left', y: 0.5, tucked: false } })   // "other" is no app
  })
  it('returns nothing, and does not throw, when storage throws or is missing', () => {
    const broken = { getItem: () => { throw new Error('denied') }, setItem: () => { throw new Error('denied') } }
    expect(readPlaces(broken)).toEqual({})
    expect(readPlaces(null)).toEqual({})
    expect(() => savePlace(broken, 'frigate', { side: 'left', y: 0.5, tucked: false })).not.toThrow()
    expect(() => savePlace(null, 'frigate', { side: 'left', y: 0.5, tucked: false })).not.toThrow()
  })
})
```

Add to `tests/theme.spec.ts`: `colorOf({ background: '#112233' }, 'background')` is `'#112233'`; `colorOf({ background: 'red' }, 'background')` and `colorOf(undefined, 'background')` are `DEFAULT_COLORS.background`.

- [ ] **Step 2: Run them and see them fail** (`npm test -- home-button-place theme`, in `tm-control/ui`)

- [ ] **Step 3: Write `src/colors.ts`** (move `DEFAULT_COLORS`, `ColorName`, and `HEX_COLOR` out of `theme.ts`; `theme.ts` imports them, uses `colorOf` in `buildTheme`, and keeps `export { DEFAULT_COLORS }`) **and `src/home-button/place.ts`** with the signatures above. `place.ts` imports nothing.

- [ ] **Step 4: Run the UI's tests and type check** (`npm test && npx vue-tsc --noEmit`), all pass

- [ ] **Step 5: Commit** (`Home button: where it sits, what it remembers, and the tab's title`)

---

### Task 4: The button itself, its build, and a page to try it on (tricky: Opus 5.5)

**Files:**
- Create: `tm-control/ui/src/home-button/main.ts`, `tm-control/ui/src/home-button/entry.ts`
- Create: `tm-control/ui/vite.home-button.config.ts`
- Create: `tm-control/ui/home-button-demo.html`
- Modify: `tm-control/ui/package.json` (`build`), `tm-control/ui/tsconfig.json` (`include`)
- Test: `tm-control/ui/tests/home-button.spec.ts`

**Interfaces:**
- Consumes: everything Task 3 produces.
- Produces:
  - `start(win: Window = window, app: string | null = appOf(win.location.pathname)): void` in `main.ts`
  - `entry.ts`, whose whole body is `import { start } from './main'` and `start()`
  - `dist/home-button.js` from `npm run build`

**What `start` does:**
1. Returns at once when `app` is null, when `win.top !== win.self`, or when the document already holds an element with the id `tm-home-button`.
2. Appends `<div id="tm-home-button">` to `document.documentElement` with an open shadow root holding its own `<style>`, a link, and a handle:
   - the link: `<a href="/" aria-label="Traffic Monitor home">` with the `mdiHome` icon as inline SVG and a `<span>` for the hostname, empty and hidden until it is known;
   - the handle: `<button type="button" aria-label="Show the home button">`, shown only while tucked, when the link is hidden.
3. Places it from `readPlaces(storage)[app] ?? defaultPlace(app, narrow)`, where `narrow` is `win.innerWidth < NARROW` and `storage` is `win.localStorage` read inside a `try` (null if that throws). Position is `fixed`, on `place.side`, at `topOf(place, win.innerHeight, size)`, above the page (`z-index: 2147483647`). It places itself again on `resize`.
4. Pointer events on the link: `pointerdown` records the start; `pointermove` beyond `isDrag` starts a drag and moves the button with the pointer; `pointerup` after a drag sets the place to `dropped(x, y, win.innerWidth, win.innerHeight)`, saves it, and swallows the click that follows. A press that never became a drag is an ordinary click on the link.
5. A click on the handle untucks and saves. Escape on the focused link tucks and saves, and focus moves to the handle.
6. Asks `fetch('/api/v1/system/device', { credentials: 'same-origin', headers: { Accept: 'application/json' } })`. On a 200 with a non-empty string `hostname`: the span shows it (on a narrow window the span stays hidden), the link's label becomes `Traffic Monitor home, <hostname>`, the colors come from `colorOf(theme.colors, …)`, and the title is set to `titled(hostname, document.title)` now and again whenever the app changes it (a `MutationObserver` on `<head>`; setting the same title again changes nothing, which is what stops a loop). On anything else: nothing changes and nothing is logged.

**Looks** (the rest is the implementer's, within these): 40 px round on a narrow window, a pill of the same height with the hostname on a wider one, a touch target of at least 44 px; fill `background`, a 1 px border and the icon in `header_text`, the name in `body_text`; opacity about 0.6 at rest and 1 on hover, focus, and while pressed or dragged; a visible focus ring; the handle a 6 px by 44 px bar on the edge with a touch target 24 px wide; `env(safe-area-inset-*)` respected; `@media print { display: none }`; `touch-action: none` on the link so a drag doesn't scroll the page; no animation longer than 150 ms, and none under `prefers-reduced-motion`.

- [ ] **Step 1: Write the failing tests** `tests/home-button.spec.ts`

Each test starts from an empty document (remove `#tm-home-button`, clear `localStorage`, reset `document.title`), uses `fakeApi` for the device call, and reads the shadow root through `document.getElementById('tm-home-button')!.shadowRoot!`. A helper `drag(from, to)` dispatches `pointerdown`, `pointermove`, and `pointerup` on the link as `MouseEvent`s of those types with `clientX`/`clientY` (jsdom may lack `PointerEvent`; the code must not need `setPointerCapture` to exist). A `beforeEach` sets the window to 1000 by 800 (`vi.stubGlobal('innerWidth', 1000)`, `vi.stubGlobal('innerHeight', 800)`); a test that needs another size sets its own.

```ts
const DEVICE = { hostname: 'tm-01', theme: THEME }

it('draws a link home on an app page, and nothing on any other page', async () => {
  start(window, null)
  expect(document.getElementById('tm-home-button')).toBeNull()
  start(window, 'frigate')
  expect(link().getAttribute('href')).toBe('/')
})

it('draws once, however often it is loaded', () => {
  start(window, 'frigate'); start(window, 'frigate')
  expect(document.querySelectorAll('#tm-home-button').length).toBe(1)
})

it('draws nothing inside an embedded page', () => {
  const framed = Object.create(window, { top: { value: {} }, self: { value: window } })
  start(framed, 'frigate')
  expect(document.getElementById('tm-home-button')).toBeNull()
})

it('shows the hostname and names the tab once the device answers', async () => {
  fakeApi({ 'GET /api/v1/system/device': DEVICE })
  document.title = 'Frigate'
  start(window, 'frigate'); await flushPromises()
  expect(link().textContent).toContain('tm-01')
  expect(link().getAttribute('aria-label')).toBe('Traffic Monitor home, tm-01')
  expect(document.title).toBe('tm-01 · Frigate')
})

it('keeps the name on the tab when the app changes its title', async () => {
  fakeApi({ 'GET /api/v1/system/device': DEVICE })
  start(window, 'frigate'); await flushPromises()
  document.title = 'Review - Frigate'; await flushPromises()
  expect(document.title).toBe('tm-01 · Review - Frigate')
})

it.each([['a 401', apiError(401, 'unauthenticated', 'Log in to continue.')], ['no hostname', { theme: THEME }],
         ['a hostname that is not text', { hostname: 5 }]])('is the icon alone after %s', async (_, answer) => {
  fakeApi({ 'GET /api/v1/system/device': answer })
  document.title = 'Frigate'
  start(window, 'frigate'); await flushPromises()
  expect(link().getAttribute('href')).toBe('/')
  expect(link().getAttribute('aria-label')).toBe('Traffic Monitor home')
  expect(document.title).toBe('Frigate')
})

it('is the icon alone when the device cannot be reached at all', async () => {
  vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('network')))
  start(window, 'frigate'); await flushPromises()
  expect(link().getAttribute('href')).toBe('/')
})

it('goes home on a press, and not after a drag', () => {
  start(window, 'dashboard')
  expect(clickIsLetThrough(() => drag([900, 700], [904, 702]))).toBe(true)     // 4.5 px: a press
  expect(clickIsLetThrough(() => drag([900, 700], [300, 400]))).toBe(false)    // a drag
})

it('remembers where it was dropped, for this app only', () => {
  start(window, 'dashboard')
  drag([900, 700], [300, 400])
  expect(JSON.parse(localStorage.getItem('tm-home-button')!)).toEqual({ dashboard: { side: 'left', y: 0.5, tucked: false } })
})

it('starts where it was left', () => {
  localStorage.setItem('tm-home-button', JSON.stringify({ nr: { side: 'left', y: 0.25, tucked: false } }))
  start(window, 'nr')
  expect(host().style.left).not.toBe('')
  expect(host().style.top).toBe('180px')                                        // 0.25 of 800, less half of 40
})

it('tucks when dropped at the edge, and comes back from its handle', () => {
  start(window, 'dashboard')
  drag([900, 700], [995, 400])
  expect(isHidden(link())).toBe(true)
  expect(isHidden(handle())).toBe(false)
  handle().click()
  expect(isHidden(link())).toBe(false)
  expect(JSON.parse(localStorage.getItem('tm-home-button')!).dashboard.tucked).toBe(false)
})

it('tucks on Escape and moves focus to the handle', () => {
  start(window, 'dashboard')
  link().focus()
  link().dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
  expect(isHidden(link())).toBe(true)
  expect(host().shadowRoot!.activeElement).toBe(handle())
})

it('still works when storage is refused', () => {
  vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('denied') })
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('denied') })
  start(window, 'dashboard')
  expect(() => drag([900, 700], [300, 400])).not.toThrow()
  expect(link().getAttribute('href')).toBe('/')
})

it('hides the hostname on a narrow window', async () => {
  vi.stubGlobal('innerWidth', 390)
  fakeApi({ 'GET /api/v1/system/device': DEVICE })
  start(window, 'frigate'); await flushPromises()
  expect(isHidden(link().querySelector('span')!)).toBe(true)
  expect(link().getAttribute('aria-label')).toBe('Traffic Monitor home, tm-01')
})

it("imports nothing of the control app's", () => {
  for (const file of ['main.ts', 'entry.ts', 'place.ts']) {
    const source = readFileSync(new URL(`../src/home-button/${file}`, import.meta.url), 'utf8')
    const imports = [...source.matchAll(/from '([^']+)'/g)].map((m) => m[1])
    expect(imports.filter((name) => !['./main', './place', '../colors', '@mdi/js'].includes(name))).toEqual([])
  }
  expect(readFileSync(new URL('../src/colors.ts', import.meta.url), 'utf8')).not.toMatch(/^import /m)
})
```

`link()`, `handle()`, `host()`, `isHidden(el)` (the `hidden` attribute), and `clickIsLetThrough(fn)` (runs `fn`, then dispatches a cancelable `click` on the link and returns whether it was left uncancelled) are helpers in the spec.

- [ ] **Step 2: Run it and see it fail** (`npm test -- home-button.spec`)

- [ ] **Step 3: Write `main.ts` and `entry.ts`** to the description above.

- [ ] **Step 4: Run the UI's tests and type check**, all pass

- [ ] **Step 5: Add the build**

`vite.home-button.config.ts`: library mode, `entry: 'src/home-button/entry.ts'`, `formats: ['iife']`, `name: 'tmHomeButton'`, `fileName: () => 'home-button.js'`, `outDir: 'dist'`, `emptyOutDir: false`, no Vue plugins, and a plugin whose `generateBundle` throws `home-button.js is <n> bytes; the limit is 10240` when the chunk's code is longer than 10 240 bytes.

`package.json`: `"build": "vue-tsc --noEmit && vite build && vite build --config vite.home-button.config.ts"`. `tsconfig.json`: add `vite.home-button.config.ts` to `include`.

- [ ] **Step 6: Build in the device's Node image and check the output**

Run (from the repo root): `podman run --rm -v "$PWD/tm-control/ui:/ui:Z" -w /ui docker.io/library/node:22.23.4-alpine sh -c 'npm ci && npm run build && npm test && ls -l dist/home-button.js dist/index.html && head -c 200 dist/home-button.js'`
Expected: the build and tests pass; `dist/index.html` still exists; `home-button.js` is under 10 240 bytes and holds no `import` statement.

- [ ] **Step 7: Add the demo page** `home-button-demo.html` at the UI's root: a stand-in app (a top bar, a list long enough to scroll, a bar fixed to the bottom like Frigate's on a phone) and

```html
<script type="module">
  import { start } from '/src/home-button/main.ts'
  start(window, new URLSearchParams(location.search).get('app') ?? 'frigate')
</script>
```

Vite's dev server serves it at `http://localhost:5173/home-button-demo.html`; the production build doesn't include it (only `index.html` is an input). Say so, and how to try the button, in `tm-control/ui/README.md` under "Run it on a laptop (fake mode)".

- [ ] **Step 8: Try it** in fake mode at laptop width and at 390 px wide: press, drag to each side, tuck, untuck, Escape, reload (the spot is kept), `?app=nr` (its own spot). Take a screenshot of each width for the maintainer.

- [ ] **Step 9: Commit** (`Home button: the script, its build, and a demo page`)

**Stop here for the maintainer** to try the demo page before the remaining tasks.

---

### Task 5: The unit's name in the control app's tab and bar

**Files:**
- Create: `tm-control/ui/src/title.ts`
- Modify: `tm-control/ui/src/stores/session.ts`, `tm-control/ui/src/App.vue`, `tm-control/ui/src/router.ts` (`RouteMeta.title`), `tm-control/ui/src/api/types.ts` (`Device.theme`)
- Test: `tm-control/ui/tests/title.spec.ts`, `tm-control/ui/tests/router.spec.ts`

**Interfaces:**
- Produces:
  - `pageTitle(hostname: string, page: string | undefined): string` in `src/title.ts`
  - `session.hostname: string` ('' until known), set by a new action `loadName(): Promise<void>` that `refresh()` starts, without waiting for it, when it finds a user
  - `RouteMeta.title?: string`, a page's name where it has no menu entry
  - `Device.theme: { font: string; colors: Record<string, string> }`

- [ ] **Step 1: Write the failing tests**

`tests/title.spec.ts`:

```ts
it.each([
  ['tm-01', 'Status', 'tm-01 · Status | Traffic Monitor'],
  ['tm-01', undefined, 'tm-01 | Traffic Monitor'],
  ['', 'Status', 'Traffic Monitor'],
  ['', undefined, 'Traffic Monitor'],
])('%j on %j is %j', (hostname, page, expected) => {
  expect(pageTitle(hostname, page)).toBe(expected)
})

describe('the tab and the bar', () => {
  const answers = (user: typeof ADMIN | null, device: Response | object = { hostname: 'tm-01', apps: [], theme: THEME }) =>
    fakeApi({ 'GET /api/v1/setup/status': status(true), 'GET /api/v1/auth/session': { user },
              'GET /api/v1/system/device': device, 'GET /api/v1/status': apiError(500, 'x', 'x') })

  it('name the unit and the page after login', async () => {
    answers(ADMIN)
    const { wrapper } = await mountApp('/account')
    expect(document.title).toBe('tm-01 · Account | Traffic Monitor')
    expect(wrapper.find('.v-app-bar').text().replace(/\s+/g, ' ')).toBe('tm-01 | Traffic Monitor')
  })

  it('follow the page', async () => {
    answers(ADMIN)
    const { router } = await mountApp('/')
    expect(document.title).toBe('tm-01 · Home | Traffic Monitor')
    await router.push('/time'); await flushPromises()
    expect(document.title).toBe('tm-01 · Date and time | Traffic Monitor')
  })

  it('say only "Traffic Monitor" before login', async () => {
    const api = answers(null)
    await mountApp('/login')
    expect(document.title).toBe('Traffic Monitor')
    expect(api.sent.map((r) => r.path)).not.toContain('/api/v1/system/device')
  })

  it('say only "Traffic Monitor" when the name cannot be read', async () => {
    answers(ADMIN, apiError(500, 'x', 'x'))
    const { wrapper } = await mountApp('/account')
    expect(document.title).toBe('Traffic Monitor')
    expect(wrapper.find('.v-app-bar').text()).toBe('Traffic Monitor')
  })
})
```

In `router.spec.ts`, the last test's expected requests become `['/api/v1/auth/session', '/api/v1/setup/status', '/api/v1/system/device']` (the name is read once, not on every navigation).

- [ ] **Step 2: Run them and see them fail**

- [ ] **Step 3: Implement**

- `title.ts`: `pageTitle` as the table says.
- `session.ts`: state `hostname: ''`; `loadName()` reads `GET /api/v1/system/device` and keeps a non-empty string `hostname`, and on any failure leaves `''` and raises nothing; `refresh()` calls `void this.loadName()` after it has a user; `sessionEnded()` clears `hostname`.
- `App.vue`: the page's name is `route.meta.title`, or else the title of the `MODULES` menu entry whose `to` equals `route.path`. A `watchEffect` sets `document.title = pageTitle(route.meta.bare || unreachable ? '' : session.hostname, name)`. In the bar, with a hostname: the name in the title's present style (`text-primary font-weight-bold`) followed by ` | Traffic Monitor` in `text-secondary`, in one `v-app-bar-title` so that a long name is cut with an ellipsis; without one, "Traffic Monitor" as now.
- `router.ts`: `title?: string` in `RouteMeta`, with a comment.
- `types.ts`: `theme` on `Device`.

- [ ] **Step 4: Run the UI's tests and type check**, all pass (other specs that mount the app may need a `GET /api/v1/system/device` answer added where they compare the exact requests)

- [ ] **Step 5: Commit** (`Control app: the unit's name in the tab and the bar`)

---

### Task 6: A viewer who opens an admin app gets a page (issue 263)

**Files:**
- Create: `tm-control/ui/src/modules/auth/AdminOnlyPage.vue`
- Modify: `tm-control/backend/tm_control/modules/auth/router.py` (`verify`)
- Modify: `tm-control/ui/src/modules/auth/index.ts`, `tm-control/ui/src/router.ts` (`redirectFor`), `tm-control/ui/src/next.ts` (`APP_PATHS`)
- Modify: `tm-control/ui/src/api/openapi.json`, `tm-control/ui/src/api/schema.d.ts` (regenerated)
- Test: `tm-control/backend/tests/test_api_auth.py`, `tm-control/ui/tests/router.spec.ts`, `tm-control/ui/tests/admin-only-page.spec.ts`, `tm-control/ui/tests/next.spec.ts`

**Interfaces:**
- Produces: verify answers a viewer on an admin path with 401, code `admin_only`, and `X-TM-Redirect: /admin-only` when the request's `Accept` header contains `text/html` (in any letter case); 403 `forbidden` otherwise, as before. The UI route `/admin-only`, with `meta.title` "Administrators only".

- [ ] **Step 1: Write the failing backend tests** in `test_api_auth.py`

```python
def verify_page(client, uri, role, accept="text/html,application/xhtml+xml,*/*;q=0.8"):
    headers = {"X-Original-URI": uri, "X-TM-Required-Role": role, "Accept": accept}
    return client.get("/api/v1/auth/verify", headers=headers)


@pytest.mark.parametrize("uri", ["/nr/", "/feeds/", "/storefiles?files=x"])
def test_verify_sends_a_viewers_page_load_on_an_admin_path_to_the_admin_only_page(claimed_client, login, uri):
    add_viewer(claimed_client)
    login(claimed_client, *VIEWER)
    r = verify_page(claimed_client, uri, "admin")
    assert r.status_code == 401 and r.json()["error"]["code"] == "admin_only"
    assert r.headers["X-TM-Redirect"] == "/admin-only"
    assert not [name for name in r.headers if name.lower().startswith("x-tm-") and name.lower() != "x-tm-redirect"]


@pytest.mark.parametrize("accept", ["*/*", "application/json", "", "text/plain, image/*"])
def test_verify_still_refuses_a_viewers_other_requests_on_an_admin_path(claimed_client, login, accept):
    add_viewer(claimed_client)
    login(claimed_client, *VIEWER)
    r = verify_page(claimed_client, "/nr/", "admin", accept=accept)
    assert r.status_code == 403 and r.json()["error"]["code"] == "forbidden"
    assert "X-TM-User" not in r.headers and "X-TM-Redirect" not in r.headers


def test_verify_reads_accept_in_any_case(claimed_client, login):
    add_viewer(claimed_client)
    login(claimed_client, *VIEWER)
    assert verify_page(claimed_client, "/nr/", "admin", accept="TEXT/HTML").status_code == 401


def test_accept_changes_nothing_for_anyone_else(claimed_client, login):
    assert verify_page(claimed_client, "/nr/", "admin").headers["X-TM-Redirect"].startswith("/login?next=")
    login(claimed_client, *ADMIN)
    assert verify_page(claimed_client, "/nr/", "admin").status_code == 200
    add_viewer(claimed_client)
    viewer = other_client(claimed_client)
    login(viewer, *VIEWER)
    assert verify_page(viewer, "/dashboard/", "viewer").status_code == 200
```

`ADMIN`, `VIEWER`, `add_viewer`, and `other_client` are the file's own. The existing `test_verify_gives_viewers_no_node_red_token_and_403_on_admin_paths` stays as it is: it sends no `Accept` and still gets 403.

- [ ] **Step 2: Run them and see them fail** (`python -m pytest tm-control/backend/tests/test_api_auth.py -q`)

- [ ] **Step 3: Change `verify`**

Add `ADMIN_ONLY_PAGE = "/admin-only"` beside the module's other constants. In the role check, before the 403: when `"text/html" in request.headers.get("accept", "").lower()`, raise `ApiError(401, "admin_only", "This app is for administrators.", headers={"X-TM-Redirect": ADMIN_ONLY_PAGE})`. Update the docstring's list of redirects and say that anything that isn't a page load keeps its 403.

- [ ] **Step 4: Regenerate the API document** (verify's docstring is in it)

Run: `PYTHONPATH=tm-control/backend python -m tm_control dump-openapi > tm-control/ui/src/api/openapi.json && (cd tm-control/ui && npm run api:generate)`
Then: `python -m pytest tm-control/backend/tests -q`, all pass.

- [ ] **Step 5: Write the failing UI tests**

`tests/router.spec.ts`:

```ts
it('shows a viewer the administrators-only page, and sends an admin home from it', async () => {
  device(true, VIEWER)
  const router = createAppRouter(createMemoryHistory())
  await router.push('/admin-only')
  expect(router.currentRoute.value.fullPath).toBe('/admin-only')
})

it('sends an admin home from the administrators-only page', async () => {
  device(true, ADMIN)
  const router = createAppRouter(createMemoryHistory())
  await router.push('/admin-only')
  expect(router.currentRoute.value.fullPath).toBe('/')
})
```

`tests/admin-only-page.spec.ts` mounts the app at `/admin-only` as `VIEWER` (`alice`) and expects: an `h1` reading "This app is for administrators"; the text "You're logged in as alice, a viewer. The app you opened needs this device's administrator."; one link reading "Home" whose `href` is `/`; one link reading "Log out" whose `href` is `/logout`; the menu present (the page is not `bare`); and `document.title` "tm-01 · Administrators only | Traffic Monitor" with a device answer.

`tests/next.spec.ts`: `/system/` now goes home like any unknown path (`nextStep('/system/', origin, [])` is `{ route: '/' }`), and `/admin-only` is one of the app's own pages when it is in `spaPaths`.

- [ ] **Step 6: Run them and see them fail**, then implement

- `AdminOnlyPage.vue`: the copy above, the Home button `color="primary" size="large" to="/"`, Log out `variant="text" size="large" href="/logout"`, laid out as `WaitingPage.vue` lays its two buttons out.
- `modules/auth/index.ts`: `{ path: '/admin-only', component: AdminOnlyPage, meta: { title: 'Administrators only' } }`.
- `router.ts`, in `redirectFor` after the license checks: `if (to.path === '/admin-only' && access.user.role === 'admin') return '/'`.
- `next.ts`: remove `'/system'` from `APP_PATHS`.

- [ ] **Step 7: Run the UI's tests and type check**, all pass

- [ ] **Step 8: Commit** (`A viewer who opens an admin app gets a page, not a bare 403`)

---

### Task 7: Device tests

**Files:**
- Modify: `script/devpi/tests/test_web.py`, `script/devpi/tests/test_disruptive.py`

**Interfaces:**
- Consumes: `request_from_this_machine(address, path, cookie=…, headers=…)`, `admin_session`, `viewer_session`.

- [ ] **Step 1: Add the tests** (they can only run on a Pi; Task 9 runs them)

```python
SCRIPT_LINE = b'<script src="/home-button.js" defer></script></head>'
PAGE = {"Accept": "text/html,application/xhtml+xml", "Accept-Encoding": "gzip"}
APP_PAGES = ["/dashboard/", "/frigate/", "/ui/", "/nr/", "/feeds/", "/feeds/stream.html"]


@pytest.mark.parametrize("path", APP_PAGES)
def test_app_pages_carry_the_home_button(address, admin_session, path):
    """nginx adds the script line to each app's page, once, and serves the page uncompressed to do it."""
    answer = request_from_this_machine(address, path, cookie=admin_session, headers=PAGE)
    found = (answer.status, answer.headers.get("Content-Encoding"), answer.body.count(SCRIPT_LINE))
    assert found == (200, None, 1), f"{path}: (status, Content-Encoding, script lines)"


def test_what_isnt_a_page_load_stays_compressed(address, admin_session):
    """The Dashboard compresses its page when asked; a request that isn't a page load must still get that."""
    answer = request_from_this_machine(address, "/dashboard/", cookie=admin_session,
                                       headers={"Accept": "*/*", "Accept-Encoding": "gzip"})
    assert (answer.status, answer.headers.get("Content-Encoding")) == (200, "gzip")


def test_home_button_script_is_served_without_a_login(address):
    answer = request_from_this_machine(address, "/home-button.js")
    kind = (answer.headers.get("Content-Type") or "").split(";")[0]
    found = (answer.status, kind, answer.headers.get("Cache-Control"), len(answer.body) <= 10240)
    assert found == (200, "application/javascript", "no-cache", True), "(status, type, Cache-Control, within the limit)"


@pytest.mark.parametrize("path", ["/nr/", "/feeds/", "/storefiles?files=x"])
def test_a_viewers_page_load_on_an_admin_app_goes_to_the_admin_only_page(address, viewer_session, path):
    answer = request_from_this_machine(address, path, cookie=viewer_session, headers={"Accept": "text/html"})
    assert (answer.status, answer.headers.get("Location")) == (302, "/admin-only"), f"{path}: (status, Location)"
```

`test_viewer_gets_403_on_admin_paths` stays as it is; give its docstring one more sentence (it sends no `Accept`, as a script would).

In `test_disruptive.py`, the rescue-page test also checks that the page's Cockpit link names the address the request was sent to: with tm-control stopped, a request for `/dashboard/` made on the Pi to `http://localhost/` has `http://localhost:9090/` in its body, and no `<!--#`. Keep the address out of every assertion message.

- [ ] **Step 2: Check they collect and are skipped off-device** (`python -m pytest script/devpi/tests -q` without `TM_DEV_HOSTS`: no errors)

- [ ] **Step 3: Commit** (`Device tests for the home button, the viewer page, and the rescue page's link`)

---

### Task 8: Docs

**Files:**
- Modify: `docs/use/home-page.md`, `docs/use/control-app.md`, `docs/use/system-admin.md` (only if it describes the rescue page's link), `docs/development/tm-control.md`, `tm-control/ui/README.md`, `CLAUDE.md`
- Create: `design/plans/2026-11-13-home-button.md` (this plan)

- [ ] **Step 1: Read "Writing docs" and "Style"** in `docs/development/contributing.md`

- [ ] **Step 2: Write**

- `docs/use/home-page.md`: a section "Getting back to the home page" after the apps table. What to say: every app except Cockpit shows a small home button; press it to come back; drag it to either side if it covers something; drag it into the edge to tuck it away, and press the thin handle to bring it back; each app remembers its own spot in that browser; on a computer it shows the device's name, so tuck it before taking a screenshot you'll share if you'd rather the name weren't in it; each tab's title starts with the device's name. Fix the page's sentence that ends "Its menu has **Status**, **Device**, and **Date and time**" only if this plan's text touches it.
- `docs/use/control-app.md`: in "Administrators and viewers", after the table, one sentence: a viewer who opens an administrator's app from a link sees a page that says so, with a way back to the home page.
- `docs/development/tm-control.md`: verify's diagram and list (the `/admin-only` redirect, and that only a page load gets it); a short section on the home button (the snippet, the map and why `Accept`, the script's home in `ui/src/home-button`, the second build and its size limit, the device call, what to check after an app upgrade).
- `tm-control/ui/README.md`: "How the code is laid out" (`src/home-button/`, `colors.ts`, `title.ts`, the second Vite config) and a design note for the button (sizes, the two edges, tuck instead of remove and why, the shadow root, what was tried and rejected).
- `CLAUDE.md`: the snippets (`home-button.conf`) and the `$tm_page_encoding` map in the revproxy paragraph; verify's redirect list (`/admin-only`, page loads only); the rescue page's `ssi`; that `TM_HOSTNAME` now feeds only the Node-RED flows (`flows.json`); the UI build's second output.

- [ ] **Step 3: Build the docs** (`~/.venvs/tm-docs/bin/mkdocs build --strict`), no warnings

- [ ] **Step 4: Commit** (`Docs: the home button, the viewer page, and where the hostname comes from`)

---

### Task 9: The bench, then the PR

**Stop for the maintainer before this task.** It deploys to a bench Pi and needs the maintainer's phones.

- [ ] **Step 1: Run every off-device check** from the worktree: the three pytest suites, the Ansible syntax check, the Jinja parse, `bash -n script/tmsetup.sh`, the UI build and Vitest in the Node image, `mkdocs build --strict` (commands in `CLAUDE.md`). All pass.

- [ ] **Step 2: Record the Pi plan with `tmdev check`** (run from the branch's worktree with the dev-Pi tooling's venv, see `script/devpi/README.md`; one host at a time):
  1. `tmdev deploy <host> -- -t revproxy -t node-red-tm`, then the device tests (`tmdev test <host>`, and `--disruptive -- -k rescue` for the rescue page).
  2. Each of the five apps opens for the admin, and its own work still works: the editor deploys a flow, a dashboard draws its charts, the feeds play, a Data export download starts. In Frigate, open the pages only; turn nothing on.
  3. The viewer account: the button shows on the dashboards and Frigate; `/nr/` in the address bar lands on the administrators-only page; its Home and Log out work.
  4. With tm-control stopped, the rescue page's Cockpit link opens Cockpit, by name and by IP address.
  5. Whether nginx's own 502 page for a stopped app carries the button (record the answer; either is fine).

- [ ] **Step 3: The maintainer's checks, by eye** (the AI reads no screenshot that shows a camera view):
  - On a laptop: the button's starting spot in each app; move it, tuck it, reload.
  - On the Android phone and the iPhone, on the LAN and in the hotspot's sign-in window: the icon-only button, a drag, a tuck, and that a tap on the handle works where the back swipe starts.
  - Frigate's live view full screen: the button is gone, and back afterwards.
  - Tab titles in each app.
  Record what moved in the starting spots; change `defaultPlace` and its tests if any did, and commit that.

- [ ] **Step 4: Write the PR text** from the template: closes the new issue and issue 263; the "Docs" section lists Task 8's pages; "AI assistance" filled in; the Pi checks by item, with no device name or address. Show the maintainer the commits and the PR text. Push and open the PR only after they approve.
