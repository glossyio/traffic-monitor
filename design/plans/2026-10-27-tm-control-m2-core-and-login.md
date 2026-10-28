# tm-control M2 (Core and Login) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put one login in front of every app. `tm-control` runs as a host service, issues the session cookie, and answers nginx's `auth_request`; a new device is claimed with a setup code and accepts the EULA before anything else loads.

**Architecture:**
- `tm-control.service` (FastAPI on `127.0.0.1:8090`, user `tmadmin`, systemd sandbox) owns users, sessions, claim state, the EULA record, and job records in `/var/lib/tm-control/state.sqlite`. It reads device secrets from `/etc/traffic-monitor/secrets/` and install facts from `/etc/traffic-monitor/manifest.json`, which tmsetup writes.
- nginx checks every app path with `auth_request`. The identity comes back as headers: Frigate gets `X-Forwarded-User`/`X-Forwarded-Groups` plus its proxy secret on port 8971, the Node-RED editor gets a short-lived HMAC token in `x-tm-nr-token`, and the dashboards are gated by nginx alone.
- The UI (Vue 3 + Vuetify 3) is built into the `revproxy` image by a multi-stage Containerfile and served by nginx at `/`. Its pages are setup, login, home, and account; everything else is API data.
- Privileged work goes through polkit (named units) and one root job, `tm-job-system-password.service`, which reads a request file tm-control writes.
- Existing devices are brought along by `tm-control migrate` (Frigate's `auth:`, `proxy:`, and `tls:` keys) and by `lineinfile` for the new `.env` keys, as M1 did.

**Tech Stack:** Ansible (tmsetup role), Podman Quadlet, nginx 1.31.0, Frigate 0.18.1, Node-RED 5.0.8, Python 3.11+ (FastAPI 0.162.0, uvicorn 0.54.0, pydantic 2.14.1, itsdangerous 2.2.0, argon2-cffi 25.1.0, ruamel.yaml 0.19.1), pytest + httpx 0.28.1, Node 22 LTS (Vue 3, Vuetify 3, Vite, TypeScript, Pinia, vue-router, openapi-typescript, Vitest).

**Spec:** `design/specs/2026-10-02-tm-control-platform-design.md` on `dev`, sections "Login and first run", "tm-control backend", "UI", "v1 scope" item 1, and "Milestones → M2". Read it with this plan. The M1 plan, `design/plans/2026-10-02-tm-control-m1-edge-and-ports.md`, shows the patterns this plan extends (Tasks 3, 4, 6, 10, 11, 12).

**Status:** written 2026-10-27 against `dev` at `127d242` (the #224 merge). The maintainer approved all 14 decisions below on 2026-10-27. Implementation started the same day on `feature/tm-control-core-login/201`, which carries this file at `design/plans/2026-10-27-tm-control-m2-core-and-login.md`. Task 0 found `dev` still at `127d242`, the off-device baseline at 257 passing tests, and every pinned version current.

**Where M1 left things (from the M1 plan's Status):**
- Everything M1 planned is on `dev`: loopback pod ports, revproxy on the host network, `/feeds/` view-only, `/storefiles`, go2rtc RTSP credentials, the broker login, #232's pod ordering, device secrets (`tasks/secrets.yml`, one secret so far), and the `tm-control` package with `migrate` installed root-owned under `/usr/local/lib/traffic-monitor/tm-control` with its venv. `files/tm-control` is already a symlink to the top-level `tm-control/`.
- Still open from M1's Pi plan: the person-only items (`/feeds/` on an iPhone, `/frigate/` live, `/dashboard/` live, the Node-RED watch test). Task 12 repeats the ones M2 changes.
- The edge tags render together: `mqtt_broker.yml`, `podman_setup.yml`, and `revproxy_setup.yml` run under `podman`, `frigate`, `node-red-tm`, `go2rtc`, and `revproxy`. M2 adds `tm-control` to that set and puts the tm-control service and Frigate's proxy settings under it too, because nginx can't answer without tm-control once `auth_request` is in.
- M1 left `/frigate/` on `127.0.0.1:5000`, the Node-RED editor on `admin`/`password`, and `index.html.j2` as the home page. M2 changes all three.

**Open PRs surveyed on 2026-10-27:** only #260 (location privacy spec, docs under `design/`). It touches nothing M2 edits, so M2 branches from `dev` and doesn't stack.

**Decisions made in this plan (2026-10-27).** These fill gaps in the spec or deviate from its text; the maintainer approved all 14 on 2026-10-27:

1. **Frigate's identity headers are `X-Forwarded-User` and `X-Forwarded-Groups`**, not `X-TM-User`/`X-TM-Role`. Frigate 0.18.1 accepts only a fixed list of trusted proxy headers (`Remote-User`, `Remote-Groups`, `X-Forwarded-User`, `X-Forwarded-Groups`, …) unless its nginx config is replaced. `X-TM-*` stay as the headers between nginx and tm-control. nginx also blanks `Remote-User`, `Remote-Groups`, and `Remote-Role` on the way to Frigate, so a client can't carry its own.
2. **Frigate's proxy secret reaches nginx through the verify response** (`X-TM-Frigate-Secret`), which nginx copies into `X-Proxy-Secret`. So no secret is written into an nginx file, and `revproxy_setup.yml` keeps showing its diffs.
3. **The UI is built inside the `revproxy` image** (multi-stage Containerfile: `node:22.23.4-alpine` builds, `nginx:1.31.0` serves) instead of a throwaway container writing `ui-dist` under `{{ tmsetup_codedir }}`. Same result, no new mechanism: the `.build` unit, Podman's layer cache ("only when sources change"), and `nginx -t` already exist. A failed UI build fails the build unit, and the running proxy keeps its old image. The UI sources reach the device with `ansible.posix.synchronize`, excluding `node_modules` and `dist`.
4. **`verify` stays at `/api/v1/auth/verify`** as the spec says, and the `/api/` location returns 404 for that exact path, so only nginx's internal `/_auth` locations reach it.
5. **The setup code follows the spec's two halves:** tmsetup writes the plain code to `/etc/traffic-monitor/setup-code` (root, 0600) and pushes its hash into tm-control's state through `tm-control set-setup-code`, run as `tmadmin` with `runuser`, on every run while the device is unclaimed. `sudo tm-control reset-admin` writes the root file first, then drops to `tmadmin` for the state change. tm-control stays the only writer of `state.sqlite`.
6. **Jobs are polled in M2.** `GET /api/v1/jobs/{id}` returns the status and the journal lines. The spec's SSE log stream comes with M3's longer jobs.
7. **One admin, any number of viewers.** Admins create, delete, and reset viewer accounts. A second admin isn't needed until someone asks.
8. **Only an admin accepts a new EULA version.** Until then viewers get 403 with a message that an administrator must accept the updated terms. The first acceptance is part of the claim request.
9. **`state.sqlite` is versioned** from day one (`PRAGMA user_version`, numbered in-process migrations applied at startup and by the CLI), because the location feature adds tables later.
10. **The Node-RED editor token** is `base64url(JSON claims) + "." + base64url(HMAC-SHA256)`, claims `{u, r, exp}`, 300-second life, minted per verify. `settings.js` verifies it with `TM_NR_TOKEN_KEY` from `node-red-tm.env`, sets `users: []`, and hides the editor's user menu (`editorTheme.userMenu: false`), because its Logout can't revoke a proxy token. Node-RED 5.0.8 reads a custom `tokenHeader` both on admin API requests (`strategies.js`, the `tokens` strategy) and on the `/comms` WebSocket upgrade (`comms.js`), so the editor opens without a login dialog. Task 1 proves it in a local container before anything depends on it.
11. **The polkit allowlist covers units only in M2:** the TM units and the job unit, verbs start/stop/restart. The time and reboot actions join when M3 ships the pages that use them, so no privilege is granted before code needs it.
12. **The manifest holds what M2 reads:** versions, git commit and branch, the installing user, paths, the probe definitions, the proxied locations, installed options, and the home page theme. Driver and firmware versions are added by M3 with the hardware checks.
13. **`/api/` is open to everyone; each endpoint checks the cookie itself.** The UI root is open (login and setup pages). Everything else includes an auth snippet. `storefiles.conf` uses `auth-admin`, as the spec says.
14. **Rate limiting is in memory,** per client IP and per username, with doubling delays. Restarting tm-control resets it. Failures are logged with the IP for the later fail2ban work.

## Global Constraints

**What M2 changes and what it leaves.** Logins change: after M2, every app path needs the tm-control session, Frigate is reached on 8971 with proxy auth, and the Node-RED editor has no built-in user. The pod's ports, go2rtc, MQTT, and data export stay as M1 left them.

**Python**
- Runs on Python 3.11 and newer, as in M1. No syntax newer than 3.11.
- Runtime dependencies, pinned in `tm-control/backend/requirements.txt`: `ruamel.yaml==0.19.1`, `fastapi==0.162.0`, `uvicorn==0.54.0`, `pydantic==2.14.1`, `itsdangerous==2.2.0`, `argon2-cffi==25.1.0`. `pydantic-core` and `argon2-cffi-bindings` ship aarch64 wheels, so nothing compiles on the device. Add `httpx==0.28.1` to `script/requirements-dev` for FastAPI's `TestClient`.
- Commands run through one runner with argv lists, a timeout, and an output cap. Never a shell.

**Who owns what on the device**
- tm-control code stays root-owned under `/usr/local/lib/traffic-monitor/tm-control` and `/usr/local/bin/tm-control` (M1). Job scripts go to `/usr/local/libexec/traffic-monitor/`, root-owned 0755. `tm-control.service` runs as `{{ tmsetup_codeowner }}` with `StateDirectory=tm-control` and `RuntimeDirectory=tm-control`, and never uses sudo.
- Secrets live in `/etc/traffic-monitor/secrets/` (`root:{{ tmsetup_codegroup }}` 0640), generated once by `tasks/secrets.yml`. M2 adds three names: `tm_control_session_key`, `frigate_proxy_secret`, `node_red_token_key`. Every Ansible task that handles a value sets `no_log: true` or `diff: false`.
- The setup code is the one secret the installer prints on purpose, and only while the device is unclaimed. It works once.
- `/etc/traffic-monitor/manifest.json` and `/etc/traffic-monitor/setup-code` are written by tmsetup only. tm-control reads the manifest; nothing but tmsetup and `reset-admin` touch the code file.

**HTTP and identity**
- Session cookie `tm_session`: `HttpOnly`, `SameSite=Lax`, `Path=/`, no `Secure` until HTTPS exists. Signed with itsdangerous (`URLSafeTimedSerializer`, salt `tm_session`), 7-day expiry, re-issued when more than a day old. It carries `uid`, `epoch`, and `iat`.
- Passwords: argon2id via `argon2.PasswordHasher()` defaults; 10 to 256 characters.
- Usernames: 3 to 32 characters of `[a-z0-9._-]`, compared case-insensitively.
- API errors are `{"error": {"code", "message", "detail"}}`. Codes used in M2: `unauthenticated`, `forbidden`, `not_claimed`, `already_claimed`, `eula_required`, `invalid_setup_code`, `rate_limited`, `validation`, `conflict`, `not_found`, `method_not_allowed`, `job_running`.
- CSRF: a non-GET request under `/api/` must have `Content-Type: application/json` and an `Origin` (or, failing that, `Referer`) whose host equals the request's `Host`. Otherwise 403 `forbidden`.
- The client IP is the `X-Forwarded-For` nginx sets; uvicorn runs with `--proxy-headers --forwarded-allow-ips 127.0.0.1`.

**Conventions** (as M1's Global Constraints, kept here in short):
- Ansible: `TMSetup - <Component> - <Action>` names, FQCNs, `become: true` per task, `_register` suffix, 2-space YAML, plain `loop:` templating.
- Variables: fixed shared values in `vars/main.yml` (`tmsetup_tm_control_port`, `tmsetup_tm_control_polkit`, `tmsetup_node_image`, `tmsetup_libexec_dir`), operator-tunable in `defaults/main.yml`, one-file literals hardcoded.
- Tests: synthetic data only; unique test module basenames across the repo; run each step's own test files.
- Docs follow "Writing docs → Style" in `docs/development/contributing.md`; new pages go in `mkdocs.yml`'s `nav:`; run `mkdocs build --strict`.
- Commits: one per task, ending with CLAUDE.md's trailer block (`Assisted-by`, `AI-Model`, `AI-Effort`, `AI-Role`). Ask for the interface and effort level if unknown.
- Pi checks run through `script/devpi/tmdev.py` before committing Task 12 and before opening the PR. Device names and addresses stay out of commits and PR text.

**Running the checks**
- From the repo root in the dev venv: `python -m pytest tm-control/backend/tests`, `python -m pytest script/tests`, `python -m pytest container/node-red-tm/schema/tests`.
- Ansible with `</dev/null`, output to a file.
- UI: `podman run --rm -v "$PWD/tm-control/ui:/ui:Z" -w /ui docker.io/library/node:22.23.4-alpine sh -c 'npm ci && npm run build && npm test'`.

## Review Focus

The failures most likely to bite a person using a device, each pinned by a test in the task that owns it:

1. **Upgrading a claimed-nothing device: the operator is locked out of their own device.** After the upgrade, every app path redirects to `/setup` until the device is claimed, and the code is in the installer's output and in `/etc/traffic-monitor/setup-code`. If tm-control doesn't start (bad venv, missing secret, unreadable manifest), every app path must fail with the rescue page that names Cockpit on `:9090`, and `/` must still load. Tests: Task 6 (the service starts with only the files tmsetup writes), Task 7 (the `error_page` chain renders), Task 12 (disruptive: stop tm-control, app paths answer 503 with the rescue text, `/` answers 200).
2. **A `-t revproxy` or `-t frigate` run on a device that is otherwise on M2.** nginx's auth snippets need tm-control running and Frigate on 8971 with proxy auth. Every tag that renders revproxy also installs and starts tm-control and gives Frigate its proxy settings. Test: Task 6's `main.yml` tag test; Task 8's task test.
3. **Frigate trusts a header the client sent.** A viewer who adds `X-Forwarded-Groups: admin` or `Remote-Role: admin` must stay a viewer. nginx sets both forwarded headers from `auth_request` variables and blanks the `Remote-*` ones. Tests: Task 7 renders `frigate.conf`; Task 12 sends the header from a viewer session and expects 403 on `/frigate/api/config/raw`.
4. **The Node-RED editor without the token key.** A device whose `node-red-tm.env` predates M2 has no `TM_NR_TOKEN_KEY`. `settings.js` must then refuse every token (fail closed), and the installer must add the key on every `node-red-tm` run, as it does for the broker keys. Tests: Task 9.
5. **A guessed setup code or password.** The claim endpoint and login back off per IP and per user, and the setup code works once. Tests: Task 3's backoff schedule, Task 4's claim tests (wrong code, repeated code, claimed device), Task 12's rate-limit check from this machine.
6. **A viewer reaching admin-only data.** `/nr/`, `/feeds/`, `/storefiles`, `/system/`, the user endpoints, and the system-password job are admin-only. Tests: Task 7 (every location names a snippet, and which), Task 4 (403s), Task 12 (viewer session gets 403 on each path).
7. **A password change that doesn't end other sessions.** Changing a password bumps the user's session epoch; the current browser gets a fresh cookie, every other one is logged out, and so is Frigate (its cookie is ours). Tests: Task 3 (epoch), Task 12 (`Logging out also ends Frigate access`).
8. **The system-password job with a crafted request.** The job must run only for the manifest's installing user, refuse any other key or username, never log the password, and delete the request. Tests: Task 5 (the script with a fake `chpasswd`), Task 6 (unit and polkit render), Task 12 (manual: a person sets it and logs in over SSH).

---

### Task 0: Base branch and a re-check against `dev`

**Files:**
- Create: branch `feature/tm-control-core-login/201` from `origin/dev`

- [ ] **Step 1: Branch and confirm the base**

```bash
git fetch origin && git switch -c feature/tm-control-core-login/201 origin/dev
git log --oneline -1    # expect 127d242 or a later dev merge
gh pr list --state open --json number,title,headRefName --jq '.[] | "\(.number) \(.headRefName) \(.title)"'
```

If `dev` moved past `127d242`, re-read the files this plan modifies (listed per task) and note anything that changed under a new "Status" paragraph at the top of this plan. If a new PR touches `container/revproxy/`, `container/frigate/`, `container/node-red-tm/data/settings.js`, `tasks/main.yml`, or `tm-control/`, stop and decide the base with the maintainer.

- [ ] **Step 2: Run the baseline checks**

```bash
python -m pytest tm-control/backend/tests script/tests container/node-red-tm/schema/tests -q
```
Expected: all pass (257 at `127d242`; two HEVC tests may skip without Podman or systemd 254).

- [ ] **Step 3: Pin the dependency versions**

Check PyPI for the current releases of the six runtime packages and `httpx`, and the Node 22 LTS release. If any differ from the Global Constraints, update the constraint text and the versions in Tasks 2 and 10 before starting. Record the check date here.

Checked 2026-10-27: the six runtime pins, `httpx==0.28.1`, and Node `22.23.4` (`docker.io/library/node:22.23.4-alpine`) are the current releases.

- [ ] **Step 4: Put the public copy of this plan on the branch**

Put this file at `design/plans/2026-10-27-tm-control-m2-core-and-login.md` with the Status line saying where it lives, and check that it names no devices, addresses, or example projects. Commit it as the branch's first commit:

```bash
git add design/plans/2026-10-27-tm-control-m2-core-and-login.md
git commit -m "Add the tm-control M2 (core and login) implementation plan" -m "<trailer block>"
```

---

### Task 1: Spikes in local containers (Node-RED token header, Frigate proxy auth)

Both spikes run on the dev machine with Podman, not on a Pi. Record each result (pass or fail, with the command output's relevant line) under this task's steps and in the PR's Testing section.

**Files:**
- Create: `tm-control/backend/tests/spikes/README.md` (what was tried and the result; no code)
- Scratch: `/tmp/claude-…/scratchpad/spike-nodered/`, `/tmp/claude-…/scratchpad/spike-frigate/`

- [ ] **Step 1: Node-RED 5.0.8 accepts a custom token header on the admin API and on `/comms`**

Write `settings.js` in the scratch dir with:

```js
const crypto = require("crypto");
module.exports = {
  flowFile: "flows.json",
  adminAuth: {
    type: "credentials",
    users: [],
    tokenHeader: "x-tm-nr-token",
    tokens: function (token) {
      return Promise.resolve(token === "spike-ok" ? { username: "spike", permissions: "*" } : null);
    },
  },
  editorTheme: { userMenu: false },
};
```

Run and probe:

```bash
podman run --rm -d --name nr-spike -p 127.0.0.1:1881:1880 -v "$PWD:/data:Z" docker.io/nodered/node-red:5.0.8
sleep 15
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:1881/settings                              # expect 401
curl -s -o /dev/null -w '%{http_code}\n' -H 'x-tm-nr-token: spike-ok' http://127.0.0.1:1881/settings  # expect 200
curl -s -o /dev/null -w '%{http_code}\n' -H 'x-tm-nr-token: nope' http://127.0.0.1:1881/settings      # expect 401
# WebSocket upgrade with the header: expect HTTP 101, and a {"topic":...} frame after sending a subscribe
python3 - <<'EOF'
import base64, json, os, socket
key = base64.b64encode(os.urandom(16)).decode()
s = socket.create_connection(("127.0.0.1", 1881))
s.sendall((f"GET /comms HTTP/1.1\r\nHost: 127.0.0.1:1881\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
           f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\nx-tm-nr-token: spike-ok\r\n\r\n").encode())
print(s.recv(1024).split(b"\r\n")[0])
payload = json.dumps({"subscribe": "notification/#"}).encode()
s.sendall(bytes([0x81, 0x80 | len(payload)]) + b"\0\0\0\0" + payload)  # masked text frame, zero mask
s.settimeout(5)
try:
    print(s.recv(1024)[:80])
except TimeoutError:
    print("no frame within 5 s (open connection, no auth failure)")
EOF
podman rm -f nr-spike
```

Expected: `401`, `200`, `401`, then `HTTP/1.1 101 Switching Protocols`, and either a frame or the 5-second line. A reply frame containing `"auth":"fail"` or a closed socket means the header isn't honored on the upgrade; then Decision 10 falls back to opening `/nr/?access_token=<token>` from the UI, and Task 9 changes accordingly.

- [ ] **Step 2: Frigate 0.18.1 honors `X-Forwarded-Groups` with `auth.enabled: false` and checks `X-Proxy-Secret`**

Write `config.yml` in the scratch dir:

```yaml
mqtt:
  enabled: false
auth:
  enabled: false
proxy:
  header_map:
    user: x-forwarded-user
    role: x-forwarded-groups
  auth_secret: spike-secret
  default_role: viewer
  logout_url: /logout
tls:
  enabled: false
cameras: {}
```

```bash
podman run --rm -d --name frigate-spike -p 127.0.0.1:8972:8971 -v "$PWD/config.yml:/config/config.yml:Z" --shm-size 128m ghcr.io/blakeblackshear/frigate:0.18.1
sleep 30
H='-H x-proxy-secret:spike-secret'
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8972/api/version                                            # no secret: expect 401
curl -s -o /dev/null -w '%{http_code}\n' $H -H 'x-forwarded-user: v' -H 'x-forwarded-groups: viewer' http://127.0.0.1:8972/api/config/raw   # expect 403
curl -s -o /dev/null -w '%{http_code}\n' $H -H 'x-forwarded-user: a' -H 'x-forwarded-groups: admin' http://127.0.0.1:8972/api/config/raw    # expect 200
curl -s -o /dev/null -w '%{http_code}\n' $H -H 'x-forwarded-user: v' -H 'x-forwarded-groups: viewer' -H 'remote-role: admin' http://127.0.0.1:8972/api/config/raw  # expect 403
curl -s $H -H 'x-forwarded-user: a' -H 'x-forwarded-groups: admin' http://127.0.0.1:8972/api/profile      # expect username a, role admin
podman rm -f frigate-spike
```

Expected as commented. If Frigate refuses an empty `cameras:` map, add one camera with `enabled: false` and the input `rtsp://127.0.0.1:1/none`. If the `remote-role` line returns 200, Task 7's `frigate.conf` must blank that header (it does; this confirms it matters). If the missing-secret line returns 200, note it: Frigate then only checks the secret when the header is present, and nginx must always send it (it does).

- [ ] **Step 3: Record and commit**

Write both results into `tm-control/backend/tests/spikes/README.md` (date, image tags, the expected and the observed codes).

```bash
git add tm-control/backend/tests/spikes/README.md
git commit -m "Record the Node-RED token header and Frigate proxy auth spikes for tm-control M2" -m "<trailer block>"
```

---

### Task 2: Backend core: settings, state DB with migrations, secrets, manifest, errors, app factory, `serve`

**Files:**
- Create: `tm-control/backend/tm_control/core/settings.py`
- Create: `tm-control/backend/tm_control/core/state.py`
- Create: `tm-control/backend/tm_control/core/secrets.py`
- Create: `tm-control/backend/tm_control/core/manifest.py`
- Create: `tm-control/backend/tm_control/core/errors.py`
- Create: `tm-control/backend/tm_control/adapters/command.py`
- Create: `tm-control/backend/tm_control/app.py`
- Create: `tm-control/backend/tm_control/modules/__init__.py`
- Create: `tm-control/backend/tests/fixtures/manifest.json`
- Create: `tm-control/backend/tests/test_state.py`, `test_settings_and_manifest.py`, `test_app_core.py`
- Modify: `tm-control/backend/tm_control/cli.py` (add `serve`)
- Modify: `tm-control/backend/requirements.txt`, `script/requirements-dev`
- Modify: `tm-control/backend/tests/conftest.py` (shared fixtures below)

**Interfaces:**
- Consumes: M1's `tm_control.cli.main`, `adapters/yamlfile.py`.
- Produces:
  - `Settings` (frozen dataclass) with `state_dir: Path`, `runtime_dir: Path`, `secrets_dir: Path`, `manifest_path: Path`, `host: str`, `port: int`, `fake: bool`, `eula_path: Path`; `Settings.from_env(environ) -> Settings`. Env names: `TM_CONTROL_STATE_DIR` (default `STATE_DIRECTORY` or `/var/lib/tm-control`), `TM_CONTROL_RUNTIME_DIR` (default `RUNTIME_DIRECTORY` or `/run/tm-control`), `TM_CONTROL_SECRETS_DIR` (`/etc/traffic-monitor/secrets`), `TM_CONTROL_MANIFEST` (`/etc/traffic-monitor/manifest.json`), `TM_CONTROL_BIND` (`127.0.0.1:8090`), `TM_CONTROL_FAKE` (`1` turns fake mode on).
  - `State(path: Path)`: `.connect() -> sqlite3.Connection` (WAL, `busy_timeout=5000`, `foreign_keys=ON`, row factory `sqlite3.Row`), `.migrate() -> int` (applies pending `MIGRATIONS`, returns the new `user_version`), `.version() -> int`. `MIGRATIONS: list[str]` indexed from 1. Migration 1 creates `users`, `device`, `eula_acceptances`, `jobs`, `audit` (columns below).
  - `Secrets(dir: Path)`: `.read(name: str) -> str` (strimmed file content; raises `MissingSecret(name)`), `.session_key`, `.frigate_proxy_secret`, `.node_red_token_key` (properties). `FakeSecrets()` returns fixed strings.
  - `Manifest` (pydantic model): `manifest_version: int`, `tm_version: str`, `git: GitInfo{commit, branch}`, `installing_user: str`, `codedir: str`, `codeowner: str`, `components: dict[str, str]`, `options: dict[str, bool]`, `revproxy_locations: list[str]`, `probes: Probes{detectors: dict, radar_paths: list[str], hevc_device: str}`, `homepage: Homepage{font: str, colors: dict[str, str]}`; `load_manifest(path) -> Manifest`; a missing or invalid file raises `ManifestError` with the path and the reason, never the content.
  - `ApiError(status: int, code: str, message: str, detail=None)` and `install_error_handlers(app)`, which renders `ApiError`, `RequestValidationError` (422 → `validation`), and `HTTPException` into the one error shape.
  - `run(argv: list[str], *, timeout: float = 30, max_output: int = 65536, input: bytes | None = None) -> CommandResult(returncode, stdout, stderr, timed_out)` in `adapters/command.py`; never a shell; output beyond the cap is truncated with a marker.
  - `create_app(settings: Settings | None = None) -> FastAPI` in `app.py`: builds `Settings.from_env` if none, opens `State`, runs `migrate()`, loads `Secrets`/`FakeSecrets` and the manifest (in fake mode from `tests/fixtures/manifest.json`), stores them on `app.state`, mounts every module router from `modules.MODULES` under `/api/v1`, and adds `GET /api/v1/health` → `{"status": "ok", "version": manifest.tm_version}`.
  - `Module(id: str, router: APIRouter, root_router: APIRouter | None = None)` dataclass in `modules/__init__.py`, with `MODULES: list[Module]` filled by later tasks. `router` mounts under `/api/v1`; `root_router` mounts at the app root, for the few non-API paths such as `GET /logout`.
  - `tm-control serve` runs `uvicorn.run(create_app(), host, port, proxy_headers=True, forwarded_allow_ips="127.0.0.1", log_config=None)`.

**State schema (migration 1):**
```sql
CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE COLLATE NOCASE,
  password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK (role IN ('admin','viewer')),
  session_epoch INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
CREATE TABLE device (key TEXT PRIMARY KEY, value TEXT NOT NULL);   -- setup_code_hash, claimed_at
CREATE TABLE eula_acceptances (id INTEGER PRIMARY KEY, version TEXT NOT NULL, accepted_at TEXT NOT NULL,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE SET NULL);
CREATE TABLE jobs (id TEXT PRIMARY KEY, name TEXT NOT NULL, requested_by INTEGER REFERENCES users(id),
  requested_at TEXT NOT NULL, finished_at TEXT, status TEXT NOT NULL);
CREATE TABLE audit (id INTEGER PRIMARY KEY, at TEXT NOT NULL, user_id INTEGER, action TEXT NOT NULL, detail TEXT);
```

- [ ] **Step 1: Write the failing tests**

`tests/conftest.py` gains:

```python
@pytest.fixture
def settings(tmp_path):
    """Settings for an isolated backend: temp state and runtime dirs, fake secrets, the fixture manifest."""
    return Settings(state_dir=tmp_path / "state", runtime_dir=tmp_path / "run", secrets_dir=tmp_path / "secrets",
                    manifest_path=FIXTURES / "manifest.json", host="127.0.0.1", port=0, fake=True,
                    eula_path=Path(tm_control.__file__).parent / "modules" / "setup" / "EULA.md")

@pytest.fixture
def client(settings):
    return TestClient(create_app(settings), base_url="http://tm-test.local")
```

`tests/test_state.py`:
```python
def test_fresh_database_gets_every_migration(tmp_path):
    state = State(tmp_path / "state.sqlite"); assert state.migrate() == len(MIGRATIONS) == state.version()
def test_migrate_twice_changes_nothing(tmp_path): ...  # second call returns the same version, no error
def test_connection_uses_wal_and_foreign_keys(tmp_path):
    con = State(...).connect(); assert con.execute("PRAGMA journal_mode").fetchone()[0] == "wal"; assert con.execute("PRAGMA foreign_keys").fetchone()[0] == 1
def test_users_role_is_constrained(tmp_path): ...  # inserting role 'root' raises sqlite3.IntegrityError
def test_usernames_are_unique_ignoring_case(tmp_path): ...  # 'Admin' after 'admin' raises IntegrityError
```

`tests/test_settings_and_manifest.py`:
```python
def test_settings_default_to_the_device_paths(): s = Settings.from_env({}); assert s.state_dir == Path("/var/lib/tm-control") and s.port == 8090 and not s.fake
def test_settings_follow_systemd_directories(): s = Settings.from_env({"STATE_DIRECTORY": "/x", "RUNTIME_DIRECTORY": "/y"}); ...
def test_fake_mode_flag(): assert Settings.from_env({"TM_CONTROL_FAKE": "1"}).fake
def test_manifest_fixture_loads(): m = load_manifest(FIXTURES / "manifest.json"); assert m.installing_user == "pi" and "frigate.conf" in m.revproxy_locations
def test_manifest_error_names_the_path_not_the_content(tmp_path): ...  # file with "password: x" → ManifestError message has the path, not "password"
def test_missing_secret_names_only_the_secret(tmp_path): ...  # MissingSecret('tm_control_session_key')
def test_command_runner_caps_output_and_times_out(): r = run(["sh", "-c", "yes | head -c 100000"], max_output=1000); assert len(r.stdout) <= 1000 + 40; r2 = run(["sleep", "5"], timeout=0.2); assert r2.timed_out
```
(The `sh -c` here is the test's subject, not the runner using a shell.)

`tests/test_app_core.py`:
```python
def test_health_reports_the_manifest_version(client): r = client.get("/api/v1/health"); assert r.status_code == 200 and r.json() == {"status": "ok", "version": "0.7.1-test"}
def test_errors_use_one_shape(client): r = client.get("/api/v1/nope"); assert r.status_code == 404 and set(r.json()["error"]) == {"code", "message", "detail"}
def test_method_not_allowed_uses_the_shape(client): r = client.post("/api/v1/health"); assert r.status_code == 405 and r.json()["error"]["code"] == "method_not_allowed"
def test_app_creates_and_migrates_the_state(settings): create_app(settings); assert State(settings.state_dir / "state.sqlite").version() == len(MIGRATIONS)
def test_serve_is_a_cli_command(): with pytest.raises(SystemExit) as e: main(["serve", "--help"]); assert e.value.code == 0
```

`tests/fixtures/manifest.json`: a complete manifest (version `0.7.1-test`, user `pi`, codedir `/opt/traffic-monitor`, codeowner `tmadmin`, all seven M1 locations, the three detectors' `dev_path`/`check_exists`/`frigate_type`/`frigate_device`, four radar paths, `/dev/rpi-hevc-dec`, the default homepage colors).

- [ ] **Step 2: Run the tests to see them fail**

Run: `python -m pytest tm-control/backend/tests/test_state.py tm-control/backend/tests/test_settings_and_manifest.py tm-control/backend/tests/test_app_core.py -q`
Expected: FAIL with import errors.

- [ ] **Step 3: Add the dependencies**

`tm-control/backend/requirements.txt` gains the five pins from Global Constraints. `script/requirements-dev` gains `httpx==0.28.1`. Reinstall the dev venv: `.venv/bin/pip install -r script/requirements-dev`.

- [ ] **Step 4: Implement the Interfaces**

Module docstrings as in M1. `State.migrate()` runs each pending migration in one transaction and sets `PRAGMA user_version` in the same transaction. `errors.py`'s handlers log the exception class and path, never request bodies. `create_app` registers routers from `MODULES` even when the list is empty.

- [ ] **Step 5: Run the tests to see them pass**

Run: the Step 2 command, plus `python -m pytest tm-control/backend/tests -q`.
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add tm-control/backend script/requirements-dev
git commit -m "Add tm-control's core: settings, versioned state database, secrets, manifest, errors, and serve" -m "<trailer block>"
```

---

### Task 3: Auth core and endpoints: passwords, sessions, backoff, CSRF, Node-RED token, verify, login, logout

**Files:**
- Create: `tm-control/backend/tm_control/core/auth.py`
- Create: `tm-control/backend/tm_control/core/csrf.py`
- Create: `tm-control/backend/tm_control/modules/auth/__init__.py`, `modules/auth/router.py`, `modules/auth/deps.py`
- Create: `tm-control/backend/tests/test_auth_core.py`, `test_api_auth.py`, `test_api_csrf.py`
- Modify: `tm-control/backend/tm_control/modules/__init__.py` (register `auth`)

**Interfaces:**
- Consumes: Task 2's `State`, `Secrets`, `ApiError`, `Settings`.
- Produces, in `core/auth.py`:
  - `hash_password(password: str) -> str`, `verify_password(hash: str, password: str) -> bool`, `check_password_rules(password: str) -> None` (raises `ApiError(422, "validation", …)` outside 10–256 chars), `check_username_rules(username: str) -> None`.
  - `Sessions(secret: str)`: `.issue(user_id: int, epoch: int, now: float | None = None) -> str`, `.load(cookie: str, now=None) -> SessionClaims(uid, epoch, iat) | None` (None on bad signature or age > 7 days), `.needs_refresh(claims, now) -> bool` (older than 1 day). `COOKIE_NAME = "tm_session"`, `MAX_AGE = 7 * 86400`.
  - `NodeRedToken(key: str)`: `.mint(username: str, role: str, now=None, ttl: int = 300) -> str`, `.verify(token: str, now=None) -> dict | None`. Format: `base64url(json.dumps({"u", "r", "exp"}, separators=(",", ":")))` + `.` + `base64url(hmac_sha256(key, body))`, both without `=` padding.
  - `Backoff(threshold: int = 5, base: float = 2.0, cap: float = 300.0)`: `.check(key: str, now) -> float` (seconds to wait, 0 when allowed), `.record_failure(key, now)`, `.reset(key)`. After `threshold` failures the wait is `base ** (failures - threshold + 1)` seconds, capped.
  - `SetupCode`: `generate() -> str` (8 characters from `ABCDEFGHJKLMNPQRSTUVWXYZ23456789`, formatted `XXXX-XXXX`), `normalize(text) -> str` (uppercase, hyphens and spaces removed), `hash_code(code) -> str` (argon2 of the normalized code), `verify_code(hash, code) -> bool`.
  - `Users(state: State)`: `.count_admins() -> int`, `.get(user_id) -> User | None`, `.by_username(username) -> User | None`, `.create(username, password, role) -> User`, `.delete(user_id)`, `.set_password(user_id, password)` (also bumps epoch), `.bump_epoch(user_id)`, `.list() -> list[User]`. `User` is a pydantic model `{id, username, role, session_epoch, created_at}`.
  - `Device(state: State)`: `.is_claimed() -> bool` (an admin exists), `.setup_code_hash() -> str | None`, `.set_setup_code_hash(hash)`, `.clear_setup_code()`, `.claim(username, password, eula_version, now) -> User` (one transaction: create the admin, record the acceptance, clear the hash, set `claimed_at`), `.unclaim(new_code_hash)` (delete every user, bump nothing else needed, set the new hash, clear `claimed_at`), `.eula_accepted(version) -> bool`, `.accept_eula(version, user_id, now)`.
  - `Audit(state)`: `.record(user_id: int | None, action: str, detail: str | None = None)`.
- Produces, in `modules/auth/deps.py`: FastAPI dependencies `current_user(request) -> User` (401 `unauthenticated` when missing or invalid), `require_admin(user) -> User` (403 `forbidden`), `client_ip(request) -> str`.
- Produces, in `modules/auth/router.py` (prefix `/auth`):
  - `GET /verify`: reads `X-Original-URI`, `X-TM-Required-Role` (`viewer` default), the cookie. Order: unclaimed → 401 with `X-TM-Redirect: /setup`; no valid session → 401 with `X-TM-Redirect: /login?next=<safe uri>`; EULA not accepted for the current version → admin 401 with `/welcome`, viewer 403; role below required → 403; else 200 with `X-TM-User`, `X-TM-Role`, `X-TM-Frigate-Secret`, and for admins `X-TM-NR-Token`. The safe uri keeps only a path that starts with one `/` (not `//`) and its query; anything else becomes `/`.
  - `POST /login {username, password}` → 200 `{user}` and the cookie; 401 `unauthenticated` on a wrong login (same message for unknown user and wrong password); 429 `rate_limited` with `Retry-After` when backoff applies (checked before the password); 409 `not_claimed` when no admin exists. Failures are logged at WARNING with the IP and the username, never the password.
  - `POST /logout` → 204 and clears the cookie. `GET /logout` (the module's `root_router`, so it's at the app root, not under `/api/v1`) → 302 to `/login` and clears the cookie; this is Frigate's `logout_url`.
  - `POST /logout-everywhere` → 204; bumps the user's epoch and clears the cookie.
  - `GET /session` → 200 `{claimed: bool, eula_accepted: bool, user: User | null}`; never 401, so the UI can route.
- Produces, in `core/csrf.py`: `CsrfMiddleware` applied to paths under `/api/`.

- [ ] **Step 1: Write the failing tests**

`tests/test_auth_core.py` (names tell the assertion):
```python
def test_password_hash_is_argon2id_and_verifies(): h = hash_password("correct horse 1"); assert h.startswith("$argon2id$") and verify_password(h, "correct horse 1") and not verify_password(h, "x")
@pytest.mark.parametrize("bad", ["short", "a" * 257]) def test_password_rules(bad): with pytest.raises(ApiError) as e: check_password_rules(bad); assert e.value.status == 422
@pytest.mark.parametrize("bad", ["ab", "Has Space", "x" * 33, "ädmin"]) def test_username_rules(bad): ...
def test_session_round_trip_and_epoch(): s = Sessions("k"); c = s.issue(7, 2, now=1000); assert s.load(c, now=1000) == SessionClaims(uid=7, epoch=2, iat=1000)
def test_session_expires_after_seven_days(): ... assert s.load(c, now=1000 + 7 * 86400 + 1) is None
def test_session_refresh_after_a_day(): ... assert not s.needs_refresh(claims, now=1000 + 3600) and s.needs_refresh(claims, now=1000 + 86401)
def test_tampered_or_foreign_session_is_rejected(): ... Sessions("other").load(c) is None; s.load(c[:-2] + "zz") is None
def test_node_red_token_matches_the_javascript_verifier():
    t = NodeRedToken("key").mint("admin", "admin", now=1_700_000_000)
    body, sig = t.split("."); assert json.loads(base64.urlsafe_b64decode(body + "==")) == {"u": "admin", "r": "admin", "exp": 1_700_000_300}
    assert sig == base64.urlsafe_b64encode(hmac.new(b"key", body.encode(), "sha256").digest()).rstrip(b"=").decode()
def test_node_red_token_rejects_expired_and_tampered(): ...
def test_backoff_schedule(): b = Backoff(); [b.record_failure("k", now=0) for _ in range(5)]; assert b.check("k", now=0) == 2.0; b.record_failure("k", now=0); assert b.check("k", now=0) == 4.0; assert b.check("k", now=1000) == 0
def test_backoff_caps_at_five_minutes(): ... 300.0
def test_setup_code_format_and_alphabet(): c = SetupCode.generate(); assert re.fullmatch(r"[ABCDEFGHJKLMNPQRSTUVWXYZ23456789]{4}-[ABCDEFGHJKLMNPQRSTUVWXYZ23456789]{4}", c)
def test_setup_code_normalizes_before_verifying(): h = SetupCode.hash_code("ABCD-EFGH"); assert SetupCode.verify_code(h, " abcd efgh ") and not SetupCode.verify_code(h, "ABCD-EFGJ")
def test_claim_creates_the_admin_and_records_the_eula_in_one_step(settings): ...  # Device.claim then is_claimed, eula_accepted("1"), setup_code_hash() is None
def test_unclaim_removes_every_user_and_sets_a_new_code(settings): ...
def test_set_password_bumps_the_epoch(settings): ...
```

Add to `tests/conftest.py`: a `claimed_client` fixture (claims through `Device.claim` with admin `admin`/`correct horse 1`, EULA version from the EULA file) and a `login(client, username, password)` helper returning the cookie, with `Origin: http://tm-test.local`. Later tasks use both.

`tests/test_api_auth.py`:
```python
def test_validation_errors_use_the_shape(claimed_client): r = claimed_client.post("/api/v1/auth/login", json={"username": 5}, headers=ORIGIN); assert r.status_code == 422 and r.json()["error"]["code"] == "validation"
def test_verify_sends_an_unclaimed_device_to_setup(client): r = client.get("/api/v1/auth/verify", headers={"X-Original-URI": "/frigate/"}); assert (r.status_code, r.headers["X-TM-Redirect"]) == (401, "/setup")
def test_verify_without_a_session_redirects_to_login_with_next(claimed_client): ... == (401, "/login?next=/dashboard/")
@pytest.mark.parametrize("uri, expected", [("//evil", "/"), ("http://evil/x", "/"), ("/ok?a=1", "/ok?a=1")]) def test_verify_sanitizes_next(claimed_client, uri, expected): ...
def test_verify_returns_identity_headers_for_a_logged_in_admin(claimed_client): ... 200; X-TM-User == "admin"; X-TM-Role == "admin"; X-TM-Frigate-Secret == FakeSecrets().frigate_proxy_secret; NodeRedToken(key).verify(r.headers["X-TM-NR-Token"])["u"] == "admin"
def test_verify_gives_viewers_no_node_red_token_and_403_on_admin_paths(claimed_client): ...
def test_verify_blocks_an_admin_until_the_current_eula_is_accepted(claimed_client, monkeypatch): ...  # bump the EULA version → 401 with /welcome; a viewer → 403 with code eula_required
def test_login_sets_a_cookie_and_session_shows_the_user(claimed_client): ...
def test_login_fails_the_same_way_for_a_wrong_password_and_an_unknown_user(claimed_client): ...  # both 401, identical body
def test_login_backs_off_after_five_failures(claimed_client): ... sixth → 429 with Retry-After
def test_login_on_an_unclaimed_device_is_409(client): ...
def test_logout_clears_the_cookie_and_get_logout_redirects(claimed_client): ...
def test_logout_everywhere_invalidates_the_other_session(claimed_client): ...  # two logins, logout-everywhere from one, verify with the other → 401
def test_session_is_never_401(client, claimed_client): ...
def test_old_cookie_is_refreshed(claimed_client, monkeypatch): ...  # issue with iat two days ago → verify answers 200 and a new Set-Cookie
```

`tests/test_api_csrf.py`:
```python
def test_post_without_origin_is_forbidden(claimed_client): r = claimed_client.post("/api/v1/auth/login", json={...}, headers={"Origin": None}); assert r.status_code == 403
def test_post_from_another_origin_is_forbidden(claimed_client): ... headers={"Origin": "http://evil.example"} → 403
def test_post_with_a_form_body_is_forbidden(claimed_client): ... data={"a": "b"} → 403
def test_matching_origin_and_json_pass(claimed_client): ... "Origin": "http://tm-test.local" → not 403
def test_referer_is_accepted_when_origin_is_missing(claimed_client): ...
def test_get_is_never_checked(claimed_client): ...
```
(`TestClient` sends no `Origin` by default, so the `login` helper passes `Origin: http://tm-test.local`.)

- [ ] **Step 2: Run the tests to see them fail**

Run: `python -m pytest tm-control/backend/tests/test_auth_core.py tm-control/backend/tests/test_api_auth.py tm-control/backend/tests/test_api_csrf.py -q`
Expected: FAIL with import errors.

- [ ] **Step 3: Implement the Interfaces**

Notes the signatures don't settle:
- `Sessions` uses `itsdangerous.URLSafeTimedSerializer(secret, salt="tm_session")` with `max_age=MAX_AGE`; the payload is `[uid, epoch, iat]`. The cookie is set with `httponly=True, samesite="lax", path="/", max_age=MAX_AGE`.
- `verify` looks the user up on every call (`Users.get`), compares `claims.epoch == user.session_epoch`, and refreshes the cookie when `needs_refresh`.
- `Backoff` keys: `f"ip:{ip}"` and `f"user:{username.lower()}"`; `login` checks both and records failures on both.
- Comparing hashes and codes uses the argon2 verifier (constant time); comparing nothing else needs it in this task.
- `CsrfMiddleware` is a pure-ASGI middleware (not `BaseHTTPMiddleware`), so bodies stream.

- [ ] **Step 4: Run the tests to see them pass**

Run: the Step 2 command, then `python -m pytest tm-control/backend/tests -q`.
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add tm-control/backend
git commit -m "Add tm-control's auth: argon2 passwords, signed sessions, login backoff, CSRF checks, and nginx's verify endpoint" -m "<trailer block>"
```

---

### Task 4: Setup and accounts: setup-code CLI, EULA, claim, account, users, audit

**Files:**
- Create: `tm-control/backend/tm_control/modules/setup/__init__.py`, `modules/setup/router.py`, `modules/setup/eula.py`, `modules/setup/EULA.md`
- Create: `tm-control/backend/tm_control/modules/account/__init__.py`, `modules/account/router.py`
- Create: `tm-control/backend/tm_control/core/claim_cli.py`
- Create: `tm-control/backend/tests/test_api_setup.py`, `test_api_account.py`, `test_claim_cli.py`
- Modify: `tm-control/backend/tm_control/cli.py` (`claim-status`, `set-setup-code`, `reset-admin`)
- Modify: `tm-control/backend/tm_control/modules/__init__.py`

**Interfaces:**
- Consumes: Task 3's `Device`, `Users`, `Audit`, `SetupCode`, `Sessions`, `Backoff`, `current_user`, `require_admin`.
- Produces:
  - `modules/setup/EULA.md`: the placeholder EULA. First line exactly `<!-- eula-version: 1 -->`, then a heading and placeholder paragraphs that say the project will supply the final wording. `eula.py`: `load_eula(path) -> Eula(version: str, markdown: str)`; a file without the version line raises `ValueError`.
  - Router `/setup`:
    - `GET /status` → `{claimed, eula: {version, accepted}}`, open.
    - `GET /eula` → `{version, markdown}`, open.
    - `POST /claim {setup_code, username, password, eula_version}` → 201 `{user}` + cookie. 409 `already_claimed`; 422 `validation` when `eula_version` isn't the current one, or the username/password break the rules; 403 `invalid_setup_code` (recorded as a failure for backoff on the IP, threshold 5, cap 300 s); 429 `rate_limited`. Audit `claim`.
    - `POST /eula/accept {version}` (admin) → 204; 422 when the version isn't current. Audit `eula.accept`.
  - Router `/account` and `/users`:
    - `GET /account` → `{user}`.
    - `POST /account/password {current_password, new_password}` → 204, bumps the epoch, and sets a fresh cookie for this browser. 401 on a wrong current password.
    - `GET /users` (admin) → `{users: [User]}`.
    - `POST /users {username, password}` (admin) → 201 `{user}` with role `viewer`. 409 `conflict` on a taken name.
    - `DELETE /users/{id}` (admin) → 204; 422 when the id is the caller or the last admin.
    - `POST /users/{id}/password {new_password}` (admin) → 204, bumps that user's epoch.
    - Every admin action writes an audit row.
  - CLI (in `core/claim_cli.py`, wired by `cli.py`), each reading `Settings.from_env` and running `State.migrate()` before anything else, so they work before the service has ever started:
    - `tm-control claim-status` → prints `claimed` or `unclaimed`, exit 0.
    - `tm-control set-setup-code` → reads one line from stdin, stores `SetupCode.hash_code(code)` when unclaimed and prints `stored`; prints `claimed` and exits 3 when claimed. Never prints the code.
    - `tm-control reset-admin` → must run as root (exit 2 otherwise, with a message). Generates a code, writes `/etc/traffic-monitor/setup-code` (0600 root, path from `--setup-code-file`, default that path), then drops privileges to the state directory's owner (`os.setgroups([])`, `os.setgid`, `os.setuid`) and calls `Device.unclaim(hash)`. Prints `Device unclaimed. Setup code: XXXX-XXXX` and the claim URL hint. Audit `reset-admin` with user_id NULL.
  - `Settings` gains `setup_code_file: Path` (default `/etc/traffic-monitor/setup-code`).

- [ ] **Step 1: Write the failing tests**

`tests/test_api_setup.py`:
```python
def test_status_and_eula_are_open(client): ...  # 200 without a cookie; eula version "1"; markdown contains "placeholder"
def test_claim_with_the_right_code_creates_the_admin_and_logs_in(client, setup_code): r = client.post("/api/v1/setup/claim", json={...}); assert r.status_code == 201 and r.json()["user"]["role"] == "admin" and "tm_session" in r.cookies; status → claimed and eula accepted
def test_claim_with_a_wrong_code_is_403_and_backs_off(client, setup_code): ... five 403s then 429
def test_claim_twice_is_409(client, setup_code): ...
def test_claim_requires_the_current_eula_version(client, setup_code): ... eula_version "0" → 422
def test_claim_enforces_username_and_password_rules(client, setup_code): ...
def test_claim_on_a_device_without_a_code_is_403(client): ...  # no hash stored → 403 invalid_setup_code
def test_eula_accept_is_admin_only_and_needs_the_current_version(claimed_client): ...
def test_audit_records_the_claim(client, setup_code, settings): ... one row with action "claim"
```
The `setup_code` fixture (in `conftest.py`) generates a code, stores its hash through `Device.set_setup_code_hash`, and returns the plain code.

`tests/test_api_account.py`:
```python
def test_account_shows_the_current_user(claimed_client): ...
def test_password_change_needs_the_current_password(claimed_client): ... wrong → 401
def test_password_change_keeps_this_browser_and_logs_out_the_others(claimed_client): ...  # second login's cookie → verify 401; first client's new cookie → 200
def test_admin_creates_lists_resets_and_deletes_viewers(claimed_client): ...  # 201 viewer; list has 2; reset password → the viewer's old cookie is 401; delete → 204; list has 1
def test_viewer_cannot_manage_users(claimed_client): ... 403 on GET /users, POST /users
def test_duplicate_username_is_409_ignoring_case(claimed_client): ...
def test_admin_cannot_delete_themselves(claimed_client): ... 422
def test_user_actions_are_audited(claimed_client, settings): ... actions {"user.create", "user.password", "user.delete"}
```

`tests/test_claim_cli.py` (env `TM_CONTROL_STATE_DIR` etc. from `settings`):
```python
def test_claim_status_reports_unclaimed_then_claimed(settings, capsys, monkeypatch): ...
def test_set_setup_code_stores_a_hash_and_never_prints_the_code(settings, capsys, monkeypatch): ...  # stdin "ABCD-EFGH\n" → "stored"; code not in stdout; Device.setup_code_hash() verifies
def test_set_setup_code_on_a_claimed_device_exits_3(settings, ...): ...
def test_reset_admin_refuses_without_root(settings, monkeypatch): monkeypatch.setattr(os, "geteuid", lambda: 1000); assert main(["reset-admin"]) == 2
def test_reset_admin_as_root_writes_the_file_then_unclaims(settings, tmp_path, monkeypatch, capsys):
    # geteuid → 0; patch os.setgroups/setgid/setuid to record calls; --setup-code-file tmp
    ... assert file mode == 0o600; "Setup code:" in out; not Device.is_claimed(); SetupCode.verify_code(hash, code printed)
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `python -m pytest tm-control/backend/tests/test_api_setup.py tm-control/backend/tests/test_api_account.py tm-control/backend/tests/test_claim_cli.py -q`
Expected: FAIL (routes 404, CLI commands unknown).

- [ ] **Step 3: Implement the Interfaces**

`reset-admin`'s privilege drop looks the owner up with `os.stat(settings.state_dir).st_uid` and `pwd.getpwuid`; it refuses (exit 1) when the state directory is root-owned, because then the service can't have created it.

- [ ] **Step 4: Run the tests to see them pass**

Run: the Step 2 command, then the whole backend suite.
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add tm-control/backend
git commit -m "Add tm-control's setup flow: setup code, EULA, claim, account, viewer accounts, and the reset-admin command" -m "<trailer block>"
```

---

### Task 5: Jobs: runner, the system-password root job, and its API

**Files:**
- Create: `tm-control/backend/tm_control/core/jobs.py`
- Create: `tm-control/backend/tm_control/adapters/systemd.py`
- Create: `tm-control/backend/tm_control/modules/jobs/__init__.py`, `modules/jobs/router.py`
- Create: `tm-control/backend/tm_control/modules/system/__init__.py`, `modules/system/router.py`
- Create: `tm-control/jobs/tm-job-system-password` (Python, stdlib only, executable bit set)
- Create: `tm-control/backend/tests/test_jobs.py`, `test_job_system_password.py`, `test_api_system.py`
- Modify: `tm-control/backend/tm_control/modules/__init__.py`

**Interfaces:**
- Consumes: Task 2's `run`, `Settings`, `Manifest`; Task 3's deps; Task 4's `Audit`.
- Produces:
  - `adapters/systemd.py`: `start_unit(name) -> CommandResult` (`systemctl start --no-block <name>`), `show_unit(name, properties: list[str]) -> dict[str, str]` (`systemctl show -p … --value` parsing), `journal_lines(unit: str, since: str, limit: int = 200) -> list[str]` (`journalctl -u <unit> --since <since> -o json`, `MESSAGE` fields).
  - `core/jobs.py`: `JobRunner(settings, state, systemd)` with `.start(name: str, request: dict, user_id: int) -> Job` and `.get(job_id: str) -> Job | None`. `Job` is `{id, name, status: "queued"|"running"|"succeeded"|"failed", requested_at, finished_at, log: list[str]}`. `start` writes `<runtime_dir>/jobs/<name>.json` (0600, created with `O_EXCL`), raises `ApiError(409, "job_running")` if the file exists or `ActiveState` is `activating`/`active`, then starts `tm-job-<name>.service` and inserts a `jobs` row. `get` derives the status from `ActiveState`/`Result` and the row, and the log from `journal_lines` since `requested_at`. `FakeJobRunner` (fake mode) writes the file, marks the job `succeeded` at once, and logs `fake: <name> done`.
  - `JOB_NAMES = {"system-password"}`; the unit name is `f"tm-job-{name}.service"`.
  - Router `/jobs`: `GET /jobs/{id}` (admin) → `Job`; 404 `not_found`.
  - Router `/system`: `POST /system/password {password}` (admin) → 202 `{id}`; writes `{"username": manifest.installing_user, "password": …}` as the request. Audit `system.password` with no detail. `GET /device` (any logged-in user) → `{hostname, serial, tm_version, time, apps: [{id, path, title, admin_only}], theme: {font, colors}}`. Hostname from `socket.gethostname()`, serial from `/sys/firmware/devicetree/base/serial-number` (or the fixture value in fake mode), time as ISO-8601 with offset. `apps` is the fixed list filtered by `manifest.revproxy_locations`: `dashboard.conf → ("dashboard", "/dashboard/", "Dashboard", False)`, `frigate.conf → ("frigate", "/frigate/", "Frigate", False)`, `legacy-ui.conf → ("legacy-ui", "/ui/", "Legacy Dashboard", False)`, `nodered.conf → ("nodered", "/nr/", "Node-RED editor", True)`, `go2rtc.conf → ("feeds", "/feeds/", "Camera feeds", True)`, `cockpit.conf → ("cockpit", "/system/", "Cockpit", True)`. Viewers get the list without `admin_only` entries.
  - `tm-control/jobs/tm-job-system-password`: reads `/run/tm-control/jobs/system-password.json` (path from argv[1] for tests), requires exactly the keys `username` and `password`, requires `username` to equal `installing_user` in the manifest (path from `TM_CONTROL_MANIFEST` or the default), requires 10–256 characters without newlines, runs `chpasswd` with `f"{username}:{password}\n"` on stdin (binary from `CHPASSWD` env var for tests, default `/usr/sbin/chpasswd`), deletes the request file in a `finally`, prints `password set for <username>` or the reason it refused (never the password), and exits 0/1.

- [ ] **Step 1: Write the failing tests**

`tests/test_jobs.py`:
```python
def test_start_writes_a_private_request_and_starts_the_unit(settings, fake_systemd): ...  # file mode 0o600; JSON equals request; start_unit called with "tm-job-system-password.service"
def test_second_start_while_the_request_exists_is_409(settings, fake_systemd): ...
def test_status_follows_the_unit(settings, fake_systemd): ...  # ActiveState activating → running; inactive+Result success → succeeded; failed → failed
def test_log_comes_from_the_journal_since_the_request(settings, fake_systemd): ...
def test_unknown_job_name_is_refused(settings): ... ValueError
```
`fake_systemd` is a stub with the three functions and recorded calls.

`tests/test_job_system_password.py` runs the script with `subprocess.run([sys.executable, "-I", JOB, request_path], env={"CHPASSWD": fake, "TM_CONTROL_MANIFEST": manifest})`, where `fake` is a tmp shell script that records its stdin to a file:
```python
def test_sets_the_password_for_the_installing_user(tmp_path): ... exit 0; recorded stdin == "pi:correct horse 1\n"; request file gone; stdout has "password set for pi" and not the password
@pytest.mark.parametrize("request_body", [{"username": "root", "password": "x" * 12}, {"username": "pi", "password": "short"}, {"username": "pi", "password": "x" * 12, "extra": 1}, {"username": "pi", "password": "a\nb" + "x" * 10}, "not json"])
def test_refuses_bad_requests_and_deletes_them(tmp_path, request_body): ... exit 1; chpasswd not called; file gone; stdout has no password text
def test_missing_request_is_an_error(tmp_path): ... exit 1
```

`tests/test_api_system.py`:
```python
def test_device_card_and_apps_for_an_admin(claimed_client): ... hostname set; serial "0000000012345678"; tm_version "0.7.1-test"; six apps
def test_viewers_see_no_admin_tiles(claimed_client): ... three apps, none admin_only
def test_apps_follow_the_manifest_locations(settings, ...): ...  # manifest without cockpit.conf → no cockpit tile
def test_system_password_job_is_admin_only_and_returns_202(claimed_client): ... viewer 403; admin 202 with id; GET /jobs/{id} → succeeded (fake runner); request JSON had the installing user
def test_system_password_enforces_the_rules(claimed_client): ... "short" → 422
def test_jobs_are_audited_without_the_password(claimed_client, settings): ...
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `python -m pytest tm-control/backend/tests/test_jobs.py tm-control/backend/tests/test_job_system_password.py tm-control/backend/tests/test_api_system.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement the Interfaces**

The job script has no dependency on `tm_control` (it runs as root from the venv's interpreter with `-EP`; keep it a single file with a docstring). `JobRunner.start` creates `<runtime_dir>/jobs` with mode 0700 if missing.

- [ ] **Step 4: Run the tests to see them pass**

Run: the Step 2 command, then the whole backend suite.
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add tm-control/backend tm-control/jobs
git commit -m "Add tm-control's job runner, the system-password root job, and the device card endpoint" -m "<trailer block>"
```

---
### Task 6: Install the tm-control service: unit, sandbox, polkit, job unit, manifest, secrets, setup code

**Files:**
- Create: `script/ansible/roles/tmsetup/tasks/tm-control_service.yml`
- Create: `script/ansible/roles/tmsetup/templates/tm-control/tm-control.service.j2`
- Create: `script/ansible/roles/tmsetup/templates/tm-control/tm-job-system-password.service.j2`
- Create: `script/ansible/roles/tmsetup/templates/tm-control/50-traffic-monitor.rules.j2`
- Create: `script/ansible/roles/tmsetup/templates/tm-control/manifest.json.j2`
- Modify: `script/ansible/roles/tmsetup/tasks/tm-control_setup.yml` (copy `tm-control/jobs/` to `{{ tmsetup_libexec_dir }}`)
- Modify: `script/ansible/roles/tmsetup/tasks/main.yml` (tags, the new import, the setup-code notice at the end)
- Modify: `script/ansible/roles/tmsetup/tasks/start_services.yml` (`tm-control.service` before `revproxy.service`)
- Modify: `script/ansible/roles/tmsetup/handlers/main.yml` (`Restart tm-control.service`)
- Modify: `script/ansible/roles/tmsetup/vars/main.yml` (`tmsetup_secret_names`, `tmsetup_tm_control_port: 8090`, `tmsetup_libexec_dir: /usr/local/libexec/traffic-monitor`, `tmsetup_tm_control_polkit`, `tmsetup_etc_dir: /etc/traffic-monitor`)
- Modify: `script/ansible/roles/tmsetup/vars/main.yml` (`rsync` in `tmsetup_packages`, for Task 10)
- Test: `script/tests/test_tmsetup_templates.py`, `script/tests/test_tmsetup_tasks.py`

**Interfaces:**
- Consumes: Tasks 2–5's CLI (`serve`, `claim-status`, `set-setup-code`), the job script, `tmsetup_secrets` (M1 Task 3), `tmsetup_tm_control_dir`.
- Produces on the device: `tm-control.service` (enabled, running on `127.0.0.1:8090`), `/etc/polkit-1/rules.d/50-traffic-monitor.rules`, `tm-job-system-password.service` (static, no `[Install]`), `/usr/local/libexec/traffic-monitor/tm-job-system-password`, `/etc/traffic-monitor/manifest.json` (`root:{{ tmsetup_codegroup }}` 0640), `/etc/traffic-monitor/setup-code` while unclaimed, `/var/lib/tm-control/` (`{{ tmsetup_codeowner }}` 0700), and the three new secrets.
- Produces for later tasks: `tmsetup_tm_control_port`, `tmsetup_etc_dir`, the edge tag set `[podman, frigate, node-red-tm, go2rtc, revproxy, tm-control]` on every import that renders the pod, revproxy, the broker login, tm-control, and Frigate's credentials.

**Templates (the values the tests pin):**

`tm-control.service.j2`:
```ini
[Unit]
Description=Traffic Monitor control app (tm-control)
After=network.target
[Service]
User={{ tmsetup_codeowner }}
Group={{ tmsetup_codegroup }}
SupplementaryGroups=systemd-journal
ExecStart=/usr/local/bin/tm-control serve
Environment=TM_CONTROL_SECRETS_DIR={{ tmsetup_secrets_dir }}
Environment=TM_CONTROL_MANIFEST={{ tmsetup_etc_dir }}/manifest.json
Environment=TM_CONTROL_BIND=127.0.0.1:{{ tmsetup_tm_control_port }}
StateDirectory=tm-control
StateDirectoryMode=0700
RuntimeDirectory=tm-control
RuntimeDirectoryMode=0700
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
Restart=on-failure
RestartSec=2
[Install]
WantedBy=multi-user.target
```
No `ReadWritePaths=` in M2: tm-control writes only its state and runtime directories.

`tm-job-system-password.service.j2`: `Type=oneshot`, `ExecStart={{ tmsetup_tm_control_dir }}/venv/bin/python -EP {{ tmsetup_libexec_dir }}/tm-job-system-password`, `Environment=TM_CONTROL_MANIFEST=…`, no `[Install]`, a comment that tm-control starts it through polkit and it reads `/run/tm-control/jobs/system-password.json`.

`50-traffic-monitor.rules.j2` (from `tmsetup_tm_control_polkit: {units: [traffic-monitor.service, frigate.service, node-red-tm.service, plate-recognizer.service, revproxy.service, go2rtc_server.service, tm-job-system-password.service], unit_verbs: [start, stop, restart]}`):
```js
polkit.addRule(function (action, subject) {
    if (subject.user !== "{{ tmsetup_codeowner }}") { return polkit.Result.NOT_HANDLED; }
    if (action.id === "org.freedesktop.systemd1.manage-units") {
        var units = [{% for u in tmsetup_tm_control_polkit.units %}"{{ u }}"{% if not loop.last %}, {% endif %}{% endfor %}];
        var verbs = [...same for unit_verbs...];
        if (units.indexOf(action.lookup("unit")) >= 0 && verbs.indexOf(action.lookup("verb")) >= 0) { return polkit.Result.YES; }
    }
    return polkit.Result.NOT_HANDLED;
});
```

`manifest.json.j2` renders `tmsetup_tm_control_manifest | to_nice_json`, a dict built in `tm-control_service.yml` with `set_fact`: `manifest_version: 1`, `tm_version`, `git: {commit, branch}` (from `git -C {{ playbook_dir }}/../.. rev-parse HEAD` and `--abbrev-ref HEAD` run with `delegate_to: localhost`, `become: false`, `failed_when: false`; `unknown` when git isn't there), `installing_user: "{{ ansible_user_id }}"`, `codedir`, `codeowner`, `components: {frigate, node_red, go2rtc, nginx, hailo}` from `vars/main.yml`, `options: {plate_recognizer: <stat of /etc/containers/systemd/plate-recognizer.container>}`, `revproxy_locations`, `probes: {detectors: <tmsetup_detectors with only dev_path, check_exists, frigate_type, frigate_device>, radar_paths, hevc_device}`, `homepage: {font, colors}`.

**Setup-code tasks** (in `tm-control_service.yml`, after the service is installed and `daemon_reload`ed, before `start_services`):
1. `Create the state directory` (`/var/lib/tm-control`, owner codeowner, 0700).
2. `Check whether the device is claimed`: `runuser -u {{ tmsetup_codeowner }} -- /usr/local/bin/tm-control claim-status`, `changed_when: false`, register `tmsetup_tm_control_claim_register`.
3. `Check for the setup code file`: stat `{{ tmsetup_etc_dir }}/setup-code`.
4. `Remove the setup code once the device is claimed`: `file: absent` when stdout is `claimed`.
5. `Generate a setup code` (`no_log`, when unclaimed and the file is missing): `set_fact` with `lookup('community.general.random_string', length=8, override_all='ABCDEFGHJKLMNPQRSTUVWXYZ23456789')` formatted `XXXX-XXXX`; `copy` it to the file, `owner: root`, `group: root`, `mode: '0600'`.
6. `Read the setup code` (`no_log`, when unclaimed): `slurp` the file.
7. `Give tm-control the setup code` (`no_log`, when unclaimed): `command` `runuser -u … -- /usr/local/bin/tm-control set-setup-code` with `stdin: "{{ code }}"`, `changed_when: false`. Runs on every unclaimed run, so a run that wrote the file but failed before this step is repaired by the next one.
8. At the end of `main.yml`, after `Start Services`, under the edge tags: `Show the setup code` (`debug`, when unclaimed): `This device isn't claimed yet. Open http://{{ ansible_facts['hostname'] }}.local/ (or its IP address) and enter the setup code {{ code }} to create the administrator account. The code works once.`

- [ ] **Step 1: Write the failing tests**

Append to `script/tests/test_tmsetup_templates.py`:
```python
def tm_control_unit(): return render("script/ansible/roles/tmsetup/templates/tm-control/tm-control.service.j2", tmsetup_codeowner="tmadmin", tmsetup_codegroup="tmadmin", tmsetup_secrets_dir="/etc/traffic-monitor/secrets", tmsetup_etc_dir="/etc/traffic-monitor", tmsetup_tm_control_port=8090).splitlines()
def test_tm_control_runs_as_the_code_owner_in_a_sandbox(): unit = tm_control_unit(); for line in ["User=tmadmin", "NoNewPrivileges=yes", "ProtectSystem=strict", "ProtectHome=yes", "PrivateTmp=yes", "StateDirectory=tm-control", "RuntimeDirectory=tm-control", "RuntimeDirectoryMode=0700", "RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6"]: assert line in unit
def test_tm_control_binds_to_loopback_only(): assert "Environment=TM_CONTROL_BIND=127.0.0.1:8090" in tm_control_unit()
def test_tm_control_has_no_write_paths_outside_its_state(): assert not any(l.startswith("ReadWritePaths=") for l in tm_control_unit())
def test_job_unit_is_a_root_oneshot_without_install(): unit = render(".../tm-job-system-password.service.j2", tmsetup_tm_control_dir=TM_CONTROL_DIR, tmsetup_libexec_dir="/usr/local/libexec/traffic-monitor", tmsetup_etc_dir="/etc/traffic-monitor"); assert "Type=oneshot" in unit and "[Install]" not in unit and "User=" not in unit and f"-EP /usr/local/libexec/traffic-monitor/tm-job-system-password" in unit
def test_polkit_rules_allow_only_named_units_for_the_code_owner(): rules = render(".../50-traffic-monitor.rules.j2", tmsetup_codeowner="tmadmin", tmsetup_tm_control_polkit=load_role_yaml("vars/main.yml")["tmsetup_tm_control_polkit"]); assert 'subject.user !== "tmadmin"' in rules and '"tm-job-system-password.service"' in rules and "timedate1" not in rules and "login1" not in rules
def test_polkit_rules_parse_as_javascript(): ...  # balanced braces and brackets; every `"..."` closed (a cheap syntax sanity check without node)
def test_manifest_renders_valid_json_with_the_fields_tm_control_reads(): doc = json.loads(render(".../manifest.json.j2", tmsetup_tm_control_manifest={...a dict shaped like the fixture...})); Manifest.model_validate(doc)  # import from tm_control with sys.path on tm-control/backend
```

Append to `script/tests/test_tmsetup_tasks.py`:
```python
EDGE_TAGS = {"podman", "frigate", "node-red-tm", "go2rtc", "revproxy", "tm-control"}
def test_everything_the_login_depends_on_renders_together():
    main = {t["name"]: t for t in load_role_yaml("tasks/main.yml")}
    for name in ["TMSetup - Main - Read the MQTT broker login", "TMSetup - Main - Setup Podman", "TMSetup - Main - Setup tm-control command line", "TMSetup - Main - Setup tm-control service", "TMSetup - Main - Give Frigate the go2rtc RTSP login", "TMSetup - Main - Setup NGinx Reverse Proxy", "TMSetup - Main - Start Services"]:
        assert EDGE_TAGS <= set(main[name]["tags"]), name
def test_tm_control_service_is_installed_before_frigate_and_after_the_package(): ...  # order in main.yml
def test_new_secrets_are_generated(): assert {"tm_control_session_key", "frigate_proxy_secret", "node_red_token_key"} <= set(load_role_yaml("vars/main.yml")["tmsetup_secret_names"])
def test_start_services_starts_tm_control_before_the_reverse_proxy(): ...
def test_tm_control_restart_handler_exists(): ...
def test_setup_code_tasks_hide_the_code_and_write_a_root_only_file():
    tasks = {t["name"]: t for t in load_role_yaml("tasks/tm-control_service.yml")}
    for name in [n for n in tasks if "setup code" in n.lower() and "Check" not in n and "Remove" not in n]: assert tasks[name].get("no_log") is True, name
    copy = tasks["TMSetup - tm-control Service - Generate a setup code"]["ansible.builtin.copy"]; assert (copy["owner"], copy["mode"]) == ("root", "0600")
def test_setup_code_is_pushed_to_tm_control_on_every_unclaimed_run(): ...  # the set-setup-code task has no `creates` and its when names the claim register
def test_state_commands_run_as_the_code_owner(): ...  # every tm-control command argv in tm-control_service.yml starts with /usr/sbin/runuser -u {{ tmsetup_codeowner }}
def test_manifest_is_root_owned_and_readable_by_the_code_owner(): ... ("root", "{{ tmsetup_codegroup }}", "0640")
def test_job_script_is_installed_root_owned_outside_codedir(): ...  # copy task dest startswith /usr/local/libexec, owner root, mode 0755
def test_setup_code_notice_is_the_last_task_and_runs_only_while_unclaimed(): ...
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `python -m pytest script/tests/test_tmsetup_templates.py script/tests/test_tmsetup_tasks.py -q`
Expected: the new tests FAIL (missing templates and tasks).

- [ ] **Step 3: Write the templates and tasks**

`tm-control_service.yml` order: polkit rules (`notify: Restart polkit.service`? No: polkitd reloads rules on its own; no handler) → libexec dir and job script copy → the two unit templates to `/etc/systemd/system/` (`notify: Restart tm-control.service`; `daemon_reload` in the start task) → manifest facts and template (`diff: false` isn't needed; it has no secrets) → state dir → setup-code tasks. `main.yml` gets `TMSetup - Main - Setup tm-control service` right after the package import, both with the edge tags; `Give Frigate the go2rtc RTSP login` and `Read the MQTT broker login` get the full edge tag set too. `start_services.yml`'s loop becomes `go2rtc_server.service, traffic-monitor.service, tm-control.service, revproxy.service`. `_VALID_TAGS` in `tmsetup.sh` already has `tm-control`.

- [ ] **Step 4: Run the tests and the Ansible checks**

```bash
python -m pytest script/tests -q
(cd script/ansible && ansible-playbook -i localhost setup.yml --syntax-check </dev/null > /tmp/syntax.txt 2>&1; tail -3 /tmp/syntax.txt)
python -c 'import sys,jinja2; e=jinja2.Environment(); [e.parse(open(f).read(), filename=f) for f in sys.argv[1:]]' $(git ls-files '*.j2')
```
Expected: tests pass; syntax check prints the playbook name with no error; the Jinja parse prints nothing.

- [ ] **Step 5: Commit**

```bash
git add script/ansible script/tests
git commit -m "Install tm-control as a sandboxed host service with polkit rules, a root job unit, the install manifest, and the setup code" -m "<trailer block>"
```

---

### Task 7: nginx: auth snippets, tm-control locations, the rescue page, and the login on every app

**Files:**
- Create: `container/revproxy/tm/snippets/auth-viewer.conf.j2`, `container/revproxy/tm/snippets/auth-admin.conf.j2`
- Create: `container/revproxy/tm/locations/tm-control-ui.conf.j2`, `tm-control-api.conf.j2`, `tm-control-auth.conf.j2`
- Create: `container/revproxy/html/unavailable.html.j2`
- Modify: `container/revproxy/nginx.conf.j2` (remove the `location /` block; keep the include)
- Modify: `container/revproxy/tm/locations/{cockpit,dashboard,frigate,go2rtc,legacy-ui,nodered,storefiles}.conf.j2` (each includes one snippet; `frigate.conf` also changes upstream and headers, see Task 8 for its Frigate side)
- Modify: `script/ansible/roles/tmsetup/vars/main.yml` (`tmsetup_revproxy_locations` gains the three files; `tmsetup_revproxy_snippets: [proxy-common.conf, auth-viewer.conf, auth-admin.conf]`)
- Modify: `script/ansible/roles/tmsetup/tasks/revproxy_setup.yml` (render every snippet from the list, in the check dir and the deployed dir; render `unavailable.html` instead of `index.html`; remove the deployed `index.html`)
- Delete: `container/revproxy/html/index.html.j2`
- Test: `script/tests/test_tmsetup_templates.py`, `script/tests/test_tmsetup_tasks.py`

**Interfaces:**
- Consumes: Task 3's verify contract (status codes and `X-TM-*` headers), Task 6's `tmsetup_tm_control_port`.
- Produces: the nginx variables `$tm_user`, `$tm_role`, `$tm_nr_token`, `$tm_frigate_secret`, `$tm_redirect`, set by either snippet and used by `frigate.conf` (Task 8) and `nodered.conf` (Task 9).

**Snippet `auth-viewer.conf.j2`** (`auth-admin.conf.j2` is identical except `auth_request /_auth_admin;`):
```nginx
# Login check for app paths. tm-control answers 200 with the identity headers, 401 (go log in, or
# set the device up), or 403. If tm-control is down, nginx's own 500 becomes the rescue page;
# an app's own error pages pass through unchanged (proxy_intercept_errors is off).
auth_request /_auth;
auth_request_set $tm_user $upstream_http_x_tm_user;
auth_request_set $tm_role $upstream_http_x_tm_role;
auth_request_set $tm_nr_token $upstream_http_x_tm_nr_token;
auth_request_set $tm_frigate_secret $upstream_http_x_tm_frigate_secret;
auth_request_set $tm_redirect $upstream_http_x_tm_redirect;
error_page 401 = @tm_login;
error_page 500 502 503 504 =503 /unavailable.html;
```

**`tm-control-auth.conf.j2`:**
```nginx
# tm-control's login check (auth_request) and where a request goes when it fails.
location = /_auth {
    internal;
    proxy_pass http://127.0.0.1:{{ tmsetup_tm_control_port }}/api/v1/auth/verify;
    proxy_pass_request_body off;
    proxy_set_header Content-Length "";
    proxy_set_header X-Original-URI $request_uri;
    proxy_set_header X-TM-Required-Role viewer;
}
location = /_auth_admin { ...same with X-TM-Required-Role admin; }
location @tm_login { return 302 $tm_redirect; }
location = /unavailable.html { internal; root /usr/share/nginx/html; }
```

**`tm-control-api.conf.j2`:**
```nginx
location /api/ {
    proxy_pass http://127.0.0.1:{{ tmsetup_tm_control_port }}/api/;
    include /etc/nginx/tm/snippets/proxy-common.conf;
    proxy_buffering off;
}
# Only nginx's internal /_auth locations may call verify
location = /api/v1/auth/verify { return 404; }
location = /logout { proxy_pass http://127.0.0.1:{{ tmsetup_tm_control_port }}/logout; include /etc/nginx/tm/snippets/proxy-common.conf; }
```

**`tm-control-ui.conf.j2`:** `location / { root /usr/share/nginx/html/ui; try_files $uri $uri/ /index.html; }` with a comment that the UI is built into the image (Task 10) and that login and setup pages must stay open.

**`unavailable.html.j2`:** a static page: "The Traffic Monitor's control app isn't answering, so the apps can't check your login. Open Cockpit at `http://<hostname>:9090/`, log in with your Raspberry Pi user account, and start `tm-control.service`, or over SSH run `sudo systemctl restart tm-control.service`." Uses the homepage colors; no JavaScript.

**Location changes:** `dashboard.conf`, `legacy-ui.conf` include `auth-viewer.conf`; `cockpit.conf`, `go2rtc.conf`, `nodered.conf`, `storefiles.conf` include `auth-admin.conf`. In `go2rtc.conf` the include goes inside `location /feeds/` before the `if`s; the regex 403 location stays as it is (it never proxies). `frigate.conf` includes `auth-viewer.conf` and gets Task 8's upstream and headers.

- [ ] **Step 1: Write the failing tests**

Append to `script/tests/test_tmsetup_templates.py`:
```python
SNIPPETS = load_role_yaml("vars/main.yml")["tmsetup_revproxy_snippets"]
APP_LOCATIONS = {"cockpit.conf": "auth-admin", "dashboard.conf": "auth-viewer", "frigate.conf": "auth-viewer", "go2rtc.conf": "auth-admin", "legacy-ui.conf": "auth-viewer", "nodered.conf": "auth-admin", "storefiles.conf": "auth-admin"}
def test_every_app_location_includes_exactly_one_auth_snippet(): for name, snippet in APP_LOCATIONS.items(): conf = location(name); assert conf.count("/etc/nginx/tm/snippets/auth-") == 1 and f"snippets/{snippet}.conf" in conf, name
def test_tm_control_locations_are_listed_and_the_home_page_is_gone(): assert {"tm-control-ui.conf", "tm-control-api.conf", "tm-control-auth.conf"} <= set(LOCATIONS); assert "location / " not in render("container/revproxy/nginx.conf.j2")
@pytest.mark.parametrize("name", ["auth-viewer.conf", "auth-admin.conf"]) def test_auth_snippets_set_every_identity_variable_and_the_error_pages(name): s = render(f"container/revproxy/tm/snippets/{name}.j2"); for v in ["tm_user", "tm_role", "tm_nr_token", "tm_frigate_secret", "tm_redirect"]: assert f"auth_request_set ${v} $upstream_http_x_{v};" in s; assert "error_page 401 = @tm_login;" in s and "error_page 500 502 503 504 =503 /unavailable.html;" in s
def test_viewer_and_admin_snippets_differ_only_in_the_auth_location(): ...  # diff of the two renders is the /_auth vs /_auth_admin line
def test_auth_locations_are_internal_and_name_the_role(): conf = location("tm-control-auth.conf"); assert "location = /_auth {" in conf and "internal;" in conf and "X-TM-Required-Role viewer" in conf and "X-TM-Required-Role admin" in conf and "proxy_pass_request_body off;" in conf
def test_verify_is_unreachable_from_the_network(): assert "location = /api/v1/auth/verify { return 404; }" in location("tm-control-api.conf")
def test_api_and_logout_are_proxied_to_tm_control_on_loopback(): ... "proxy_pass http://127.0.0.1:8090/api/;" and "location = /logout"
def test_ui_root_serves_the_built_app_with_history_fallback(): assert "try_files $uri $uri/ /index.html;" in location("tm-control-ui.conf") and "root /usr/share/nginx/html/ui;" in ...
def test_unavailable_page_names_cockpit_and_the_service(): page = render("container/revproxy/html/unavailable.html.j2", tmsetup_homepage_colors=..., tmsetup_homepage_font="Helvetica", ansible_facts={"hostname": "tm"}); assert ":9090" in page and "tm-control.service" in page and "<script" not in page
def test_no_location_carries_a_secret_value(): for name in LOCATIONS: assert "tmsetup_secrets" not in Path(f"container/revproxy/tm/locations/{name}.j2").read_text()
```
Update `test_feeds_*` if their rendered-text assertions moved because of the include line; the rules themselves don't change.

Append to `script/tests/test_tmsetup_tasks.py`:
```python
def test_revproxy_renders_every_snippet_in_the_check_and_the_deployment(): ...  # the "Render NGinx config for the check" loop and the "Create NGinx config file" loop both come from tmsetup_revproxy_snippets
def test_revproxy_no_longer_writes_the_hand_written_home_page(): names = [t["name"] for t in load_role_yaml("tasks/revproxy_setup.yml")]; assert "TMSetup - revproxy Setup - Create NGinx home page" not in names and "TMSetup - revproxy Setup - Remove the old home page" in names and "TMSetup - revproxy Setup - Create the rescue page" in names
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `python -m pytest script/tests/test_tmsetup_templates.py script/tests/test_tmsetup_tasks.py -q`
Expected: the new tests FAIL.

- [ ] **Step 3: Write the snippets, locations, page, and task changes**

In `revproxy_setup.yml`, the check-dir render loop becomes `['nginx.conf'] + snippets mapped to 'tm/snippets/' + locations mapped to 'tm/locations/'`; the deployed `Create NGinx config file` loop likewise. Add `Remove the old home page` (`file: absent` on `{{ tmsetup_codedir }}/revproxy/html/index.html`) and `Create the rescue page` (template to `html/unavailable.html`, 0644), both after the check passes, like the old home page task.

- [ ] **Step 4: Run the tests and check nginx parses the rendered config**

```bash
python -m pytest script/tests -q
python - <<'EOF'
# Render nginx.conf, every snippet, and every location with test values into a temp tree, then run nginx -t in the pinned image
...
EOF
```
Write that render-and-check as `script/tests/test_nginx_config_parses.py`: it skips without Podman, otherwise renders into `tmp_path` with `tmsetup_tm_control_port=8090`, `tmsetup_codedir=...`, and the Frigate/Node-RED variables, and runs `podman run --rm -v <tmp>:/etc/nginx/tm:ro,Z -v <tmp>/nginx.conf:/etc/nginx/nginx.conf:ro,Z docker.io/nginx:1.31.0 nginx -t`. Expected: `syntax is ok`. This catches a named location in the wrong context or a duplicate `location /` before a Pi does.

- [ ] **Step 5: Commit**

```bash
git add container/revproxy script/ansible script/tests
git commit -m "Put tm-control's login check in front of every app path and replace the home page with the control app" -m "<trailer block>"
```

---

### Task 8: Frigate on port 8971 with proxy authentication

**Files:**
- Modify: `container/frigate/config/config.yml.j2` (`auth:`, `proxy:`, `tls:` sections)
- Modify: `container/frigate/frigate.env.j2` (`FRIGATE_PROXY_AUTH_SECRET`)
- Modify: `container/revproxy/tm/locations/frigate.conf.j2` (upstream 8971, identity headers)
- Modify: `tm-control/backend/tm_control/core/migrate.py` (proxy step)
- Modify: `script/ansible/roles/tmsetup/tasks/frigate_credentials.yml` (the env line)
- Create: `tm-control/backend/tests/test_frigate_proxy_migration.py`
- Test: `tm-control/backend/tests/test_frigate_rtsp_migration.py` (counts in messages), `script/tests/test_tmsetup_templates.py`, `script/tests/test_tmsetup_tasks.py`

**Interfaces:**
- Consumes: Task 7's `$tm_user`, `$tm_role`, `$tm_frigate_secret`; `tmsetup_secrets['frigate_proxy_secret']`.
- Produces: `migrate.run(frigate_config, dry_run)` now applies two steps and reports each: `add_proxy_auth(config) -> bool` adds, when the top-level key is absent, `auth: {enabled: false}`, `proxy: {header_map: {user: x-forwarded-user, role: x-forwarded-groups}, auth_secret: "{FRIGATE_PROXY_AUTH_SECRET}", default_role: viewer, logout_url: /logout}`, and `tls: {enabled: false}`; keys that exist are left alone, and a warning names the key (`auth.enabled is true`, `proxy.auth_secret is missing`, `tls.enabled is true`) when the existing value would break the proxy login. Output lines: `updated: <n> camera input(s)`, `added proxy auth settings`, as a comma-joined list after `{PREFIX} {path}:`.

`config.yml.j2` gets, after `mqtt:`:
```yaml
# The reverse proxy logs users in and passes who they are; Frigate's own login is off (tm-control).
auth:
  enabled: false
proxy:
  header_map:
    user: x-forwarded-user
    role: x-forwarded-groups
{% raw %}
  auth_secret: "{FRIGATE_PROXY_AUTH_SECRET}"
{% endraw %}
  default_role: viewer
  logout_url: /logout
tls:
  enabled: false
```

`frigate.conf.j2`:
```nginx
# frigate - Frigate, on its authenticated port; the proxy passes who's logged in
location /frigate/ {
    include /etc/nginx/tm/snippets/auth-viewer.conf;
    proxy_pass http://127.0.0.1:8971/;
    include /etc/nginx/tm/snippets/proxy-common.conf;
    proxy_set_header X-Forwarded-Scheme $scheme;
    proxy_set_header X-Ingress-Path "/frigate";
    proxy_set_header X-Proxy-Secret $tm_frigate_secret;
    proxy_set_header X-Forwarded-User $tm_user;
    proxy_set_header X-Forwarded-Groups $tm_role;
    # Frigate trusts these too; never let a client supply them
    proxy_set_header Remote-User "";
    proxy_set_header Remote-Groups "";
    proxy_set_header Remote-Role "";
}
```

- [ ] **Step 1: Write the failing tests**

`tests/test_frigate_proxy_migration.py` (both fixture configs lack the keys):
```python
def test_adds_auth_proxy_and_tls_sections(frigate_config, capsys): assert run(frigate_config) == 0; doc = yaml.safe_load(frigate_config.read_text()); assert doc["auth"] == {"enabled": False} and doc["proxy"]["header_map"] == {"user": "x-forwarded-user", "role": "x-forwarded-groups"} and doc["proxy"]["auth_secret"] == "{FRIGATE_PROXY_AUTH_SECRET}" and doc["proxy"]["default_role"] == "viewer" and doc["proxy"]["logout_url"] == "/logout" and doc["tls"] == {"enabled": False}; assert "added proxy auth settings" in capsys.readouterr().out
def test_second_run_changes_nothing(frigate_config, capsys): ...
def test_existing_sections_are_left_alone_and_warned_about(frigate_config, capsys): ...  # prepend "auth:\n  enabled: true\n" → unchanged, stderr has "auth.enabled is true"
def test_proxy_section_without_a_secret_warns(frigate_config, capsys): ...
def test_migrated_sections_match_what_new_installs_get(): ...  # render config.yml.j2 with test vars; the three sections equal the migration's constants
def test_dry_run_lists_both_steps(frigate_config, capsys): ... "would update 1 camera input(s), add proxy auth settings"
```
Update `test_frigate_rtsp_migration.py` expectations where the summary line changed (`would update 1 camera input(s)` is still a substring).

Append to `script/tests/test_tmsetup_templates.py`:
```python
def test_new_frigate_configs_use_proxy_auth(): cfg = yaml.safe_load(<the file's existing Frigate config render, as test_new_frigate_configs_read_go2rtc_with_credentials uses>); assert cfg["auth"]["enabled"] is False and cfg["proxy"]["auth_secret"] == "{FRIGATE_PROXY_AUTH_SECRET}" and cfg["tls"]["enabled"] is False
def test_frigate_env_carries_the_proxy_secret(): env = render(...frigate.env.j2..., tmsetup_secrets={"go2rtc_rtsp_password": "p", "frigate_proxy_secret": "s"}, ...); assert "FRIGATE_PROXY_AUTH_SECRET=s" in env.splitlines()
def test_frigate_location_uses_the_authenticated_port_and_fixed_identity_headers(): conf = location("frigate.conf"); assert "proxy_pass http://127.0.0.1:8971/;" in conf; for h in ['X-Proxy-Secret $tm_frigate_secret', 'X-Forwarded-User $tm_user', 'X-Forwarded-Groups $tm_role', 'Remote-User ""', 'Remote-Groups ""', 'Remote-Role ""']: assert f"proxy_set_header {h};" in conf
```
Append to `script/tests/test_tmsetup_tasks.py`: `test_existing_frigate_env_gets_the_proxy_secret_without_printing_it` (the lineinfile loop in `frigate_credentials.yml` has a `FRIGATE_PROXY_AUTH_SECRET` item and `no_log`).

- [ ] **Step 2: Run the tests to see them fail**

Run: `python -m pytest tm-control/backend/tests/test_frigate_proxy_migration.py script/tests/test_tmsetup_templates.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

`add_proxy_auth` inserts the three sections right after `mqtt:` when it exists (ruamel `insert`), so the file reads like a new install; otherwise at the top. Keep M1's rule: warnings never print config text beyond key names.

- [ ] **Step 4: Run the tests to see them pass**

Run: `python -m pytest tm-control/backend/tests script/tests -q`. Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add container/frigate container/revproxy/tm/locations/frigate.conf.j2 tm-control/backend script/ansible script/tests
git commit -m "Serve Frigate on its authenticated port with the proxy's login, and add the proxy settings to existing configs" -m "<trailer block>"
```

---

### Task 9: Node-RED editor logs in with the proxy's token

**Files:**
- Modify: `container/node-red-tm/data/settings.js` (`adminAuth.users: []`, `tokens`, `tokenHeader`, `editorTheme.userMenu: false`)
- Modify: `container/node-red-tm/node-red-tm.env.j2` (`TM_NR_TOKEN_KEY`)
- Modify: `container/revproxy/tm/locations/nodered.conf.j2` (`proxy_set_header x-tm-nr-token $tm_nr_token;`)
- Modify: `script/ansible/roles/tmsetup/tasks/node-red-tm_setup.yml` (`lineinfile` for the key on every run, `no_log`, before the Quadlet render)
- Create: `script/tests/test_node_red_settings.py`
- Test: `script/tests/test_tmsetup_templates.py`, `script/tests/test_tmsetup_tasks.py`

**Interfaces:**
- Consumes: Task 3's token format; Task 7's `$tm_nr_token`; `tmsetup_secrets['node_red_token_key']`.
- Produces: `settings.js` exports `adminAuth.tokens(token)` → `Promise<{username, permissions: "*"} | null>` and `adminAuth.tokenHeader: "x-tm-nr-token"`. The verifier is a small function at the top of `settings.js`, `verifyProxyToken(token, key, nowSeconds)`, so a test can load it: it returns `null` when `key` is empty, the token isn't `body.sig`, the HMAC doesn't match (`crypto.timingSafeEqual` on equal-length buffers), `exp` has passed, or `r !== "admin"`.

- [ ] **Step 1: Write the failing tests**

`script/tests/test_node_red_settings.py` runs `node` when present (skip otherwise, like the HEVC tests skip without Podman):
```python
SETTINGS = REPO / "container/node-red-tm/data/settings.js"
def test_settings_have_no_built_in_user_and_read_the_proxy_header(): text = SETTINGS.read_text(); assert "users: []" in text and 'tokenHeader: "x-tm-nr-token"' in text and "$2a$08$" not in text and "userMenu: false" in text
@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
@pytest.mark.parametrize("key, token, expected", [("key", mint("admin", "admin", exp=future), "admin"), ("", mint(...), None), ("other", mint(...), None), ("key", mint("v", "viewer", exp=future), None), ("key", mint("admin", "admin", exp=past), None), ("key", "garbage", None)])
def test_javascript_verifier_agrees_with_the_python_minter(key, token, expected): out = subprocess.run(["node", "-e", f"const s=require({str(SETTINGS)!r}); const u=s.verifyProxyToken({token!r}, {key!r}, {now}); console.log(u ? u.username : 'null')"], ...); assert out == (expected or "null")
```
`mint` uses `NodeRedToken` from `tm_control` (add `tm-control/backend` to `sys.path` in this test module, the way `test_tmsetup_templates.py` will for the manifest test). `settings.js` must therefore also export `verifyProxyToken` (`module.exports.verifyProxyToken = verifyProxyToken;` after the settings object).

Append to `script/tests/test_tmsetup_templates.py`: `test_node_red_env_template_carries_the_token_key` (renders `TM_NR_TOKEN_KEY=<value>`), `test_nodered_location_passes_the_proxy_token` (`proxy_set_header x-tm-nr-token $tm_nr_token;` in `nodered.conf`).
Append to `script/tests/test_tmsetup_tasks.py`: `test_node_red_token_key_is_written_on_every_run_without_printing_it` (a `lineinfile` task in `node-red-tm_setup.yml` with `regexp: '^TM_NR_TOKEN_KEY='`, `no_log: true`, notifying `Restart node-red-tm.service`).

- [ ] **Step 2: Run the tests to see them fail**

Run: `python -m pytest script/tests/test_node_red_settings.py script/tests/test_tmsetup_templates.py script/tests/test_tmsetup_tasks.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

`settings.js`: `const crypto = require("crypto");` at the top; `verifyProxyToken` as specified; `adminAuth: { type: "credentials", users: [], tokenHeader: "x-tm-nr-token", tokens: (token) => Promise.resolve(verifyProxyToken(token, process.env.TM_NR_TOKEN_KEY || "", Date.now() / 1000)) }`; `editorTheme.userMenu: false`. Keep `credentialSecret` and everything else. `node-red-tm.env.j2` adds, after the credential secret: `# Verifies the login token the reverse proxy sends with each Node-RED editor request (set by tmsetup.sh)` and `TM_NR_TOKEN_KEY={{ tmsetup_secrets['node_red_token_key'] }}`. The `lineinfile` task runs only when the env file exists (`stat`, as `mqtt_broker.yml` does).

- [ ] **Step 4: Run the tests to see them pass**

Run: `python -m pytest script/tests -q` and `python3 -m json.tool container/node-red-tm/data/flows.json >/dev/null` (flows unchanged, this just keeps the habit). Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add container/node-red-tm container/revproxy/tm/locations/nodered.conf.j2 script/ansible script/tests
git commit -m "Open the Node-RED editor with the proxy's token instead of its own login" -m "<trailer block>"
```

---

### Task 10: The UI shell: setup, login, home, account; built into the revproxy image

**Files:**
- Create: `tm-control/ui/` — `package.json`, `package-lock.json`, `vite.config.ts`, `tsconfig.json`, `index.html`, `src/main.ts`, `src/App.vue`, `src/router.ts`, `src/stores/session.ts`, `src/api/client.ts`, `src/api/schema.d.ts` (generated), `src/api/openapi.json` (committed copy), `src/modules/index.ts`, `src/modules/{setup,auth,home,account}/index.ts` and pages, `src/components/{StatusCard,ConfirmDialog}.vue`, `src/theme.ts`, `tests/router.spec.ts`, `tests/setup-flow.spec.ts`, `README.md`
- Create: `tm-control/backend/tests/test_openapi_document.py`
- Create: `tm-control/backend/tm_control/fake.py` (fake-mode seeding) and the `tm-control fake-reset` CLI command
- Modify: `container/revproxy/Containerfile.j2` (multi-stage), `container/revproxy/.containerignore`
- Modify: `script/ansible/roles/tmsetup/tasks/revproxy_setup.yml` (sync `tm-control/ui/` to `{{ tmsetup_codedir }}/revproxy/ui/` before the build)
- Modify: `script/ansible/roles/tmsetup/vars/main.yml` (`tmsetup_node_image: docker.io/library/node:22.23.4-alpine`)
- Modify: `.gitignore` (`tm-control/ui/node_modules/`, `tm-control/ui/dist/`, `.tm-control-fake/`)
- Test: `script/tests/test_tmsetup_templates.py`, `script/tests/test_tmsetup_tasks.py`

**Interfaces:**
- Consumes: the API from Tasks 3–5 (`/api/v1/auth/session`, `/auth/login`, `/auth/logout`, `/auth/logout-everywhere`, `/setup/status`, `/setup/eula`, `/setup/claim`, `/setup/eula/accept`, `/account`, `/account/password`, `/users…`, `/system/device`, `/system/password`, `/jobs/{id}`); Task 7's root location.
- Produces:
  - Routes: `/` (home), `/login`, `/setup` (welcome → EULA → claim → optional system password → home), `/welcome` (EULA re-acceptance), `/account`, `/users` (admin). `router.ts` guards: before each navigation it loads `/setup/status` and `/auth/session` once (cached in the Pinia store): unclaimed → `/setup`; no user → `/login?next=…`; EULA not accepted → admin `/welcome`, viewer a "waiting for an administrator" page; `/users` → admin only.
  - `modules/<name>/index.ts` exports `{ id, routes, nav }`; `modules/index.ts` collects them.
  - `src/api/client.ts`: `openapi-fetch` client typed by `schema.d.ts`, with `credentials: "same-origin"`, `Content-Type: application/json`, and a response hook that turns the API's error shape into a thrown `ApiError`.
  - Theme: `theme.ts` builds the Vuetify theme from `/system/device`'s `theme.colors` with the M1 home page defaults as fallback; system fonts; `@mdi/js` icons only.
  - Pages are thin: forms post, show the API's `message`, and route on success. The claim page shows the setup code input as two groups of four, uppercases, and accepts the hyphen. The system-password step has the "same password as my account" checkbox (spec) and polls `/jobs/{id}` until it finishes.
  - Build: `npm run build` → `dist/`; `npm test` runs Vitest (router guards and the setup flow against a mocked client); `npm run api:generate` → `openapi-typescript src/api/openapi.json -o src/api/schema.d.ts`.
  - CLI: `tm-control dump-openapi` prints the app's OpenAPI document as JSON; `tm-control fake-reset` empties the fake state directory and prints a setup code.
  - Fake mode: `TM_CONTROL_FAKE=1 tm-control serve` (dev machine, `PYTHONPATH=tm-control/backend`) with state in `$TM_CONTROL_STATE_DIR` (default `./.tm-control-fake/`, in `.gitignore`). `npm run dev` proxies `/api` and `/logout` to `127.0.0.1:8090`. `tm-control/ui/README.md` has the four commands.
  - Image: `Containerfile.j2` becomes
    ```dockerfile
    FROM {{ tmsetup_node_image }} AS ui
    WORKDIR /ui
    COPY ui/package.json ui/package-lock.json ./
    RUN npm ci --no-audit --no-fund
    COPY ui/ ./
    RUN npm run build
    FROM docker.io/nginx:{{ tmsetup_nginx_version }}
    COPY --from=ui /ui/dist /usr/share/nginx/html/ui
    ```
    `.containerignore`: `html`, `tm`, `nginx.conf`, `ui/node_modules`, `ui/dist`.
  - Task: `TMSetup - revproxy Setup - Copy the control app's UI sources` with `ansible.posix.synchronize` (`src: tm-control/ui/`, `dest: {{ tmsetup_codedir }}/revproxy/ui/`, `delete: true`, `rsync_opts: ['--exclude=node_modules', '--exclude=dist', '--chmod=D750,F640']`, `become: true`), placed before `Create NGinx Containerfile`, notifying `Restart revproxy.service`. `rsync` joins `tmsetup_packages` (Task 6 added it). If `synchronize` misbehaves with `become` on a remote install (its known rough edge), the fallback is a tarball built on the controller from `git ls-files -co --exclude-standard tm-control/ui` and `ansible.builtin.unarchive` on the device; keep the same excludes either way.

- [ ] **Step 1: Write the failing tests**

`tm-control/backend/tests/test_openapi_document.py`:
```python
def test_committed_openapi_document_matches_the_app(settings): committed = json.loads((REPO / "tm-control/ui/src/api/openapi.json").read_text()); assert create_app(settings).openapi() == committed, "run: python -m tm_control dump-openapi > tm-control/ui/src/api/openapi.json && (cd tm-control/ui && npm run api:generate)"
```
(Add the `dump-openapi` CLI command in this task.)

`tm-control/ui/tests/router.spec.ts`: an unclaimed status routes `/` to `/setup`; no session routes `/account` to `/login?next=/account`; a viewer can't open `/users`; an admin with the EULA outstanding lands on `/welcome`.
`tm-control/ui/tests/setup-flow.spec.ts`: the claim form posts `{setup_code: "ABCD-EFGH", username, password, eula_version: "1"}` and moves to the system-password step; "same password" fills the field; skipping the step routes home.

Append to `script/tests/test_tmsetup_templates.py`: `test_revproxy_image_builds_the_ui_from_a_pinned_node_image` (the Containerfile has `FROM docker.io/library/node:22.23.4-alpine AS ui`, `npm ci`, `COPY --from=ui /ui/dist /usr/share/nginx/html/ui`, and the final `FROM docker.io/nginx:1.31.0`).
Append to `script/tests/test_tmsetup_tasks.py`: `test_ui_sources_are_synced_without_node_modules_before_the_image_build` (the synchronize task exists, excludes `node_modules` and `dist`, deletes extras, and comes before `Create NGinx Containerfile`).
`.containerignore` test: `test_revproxy_build_context_leaves_out_the_mounted_config_and_node_modules`.

- [ ] **Step 2: Run the tests to see them fail**

Run: `python -m pytest tm-control/backend/tests/test_openapi_document.py script/tests -q`. Expected: FAIL. The UI tests fail until Step 3 (`npm test` in the container).

- [ ] **Step 3: Scaffold and implement the UI**

`npm create vuetify@latest` or a hand-written `package.json` with: `vue@3`, `vuetify@3`, `vue-router@4`, `pinia@3`, `@mdi/js@7`, `openapi-fetch`; dev: `vite`, `@vitejs/plugin-vue`, `typescript`, `vue-tsc`, `vitest`, `@vue/test-utils`, `jsdom`, `openapi-typescript`. Pin exact versions in `package.json` (no `^`) and commit the lockfile. Keep components conventional (Vuetify `v-form`, `v-text-field`, `v-card`, `v-navigation-drawer`, `v-app-bar`), one page per file, no custom CSS beyond spacing. Phone and desktop: the drawer is temporary below `md`.

- [ ] **Step 4: Build and test in the pinned container, then the fake-mode click-through**

```bash
podman run --rm -v "$PWD/tm-control/ui:/ui:Z" -w /ui docker.io/library/node:22.23.4-alpine sh -c 'npm ci && npm run build && npm test'
TM_CONTROL_FAKE=1 PYTHONPATH=tm-control/backend python -m tm_control fake-reset   # prints a setup code
TM_CONTROL_FAKE=1 PYTHONPATH=tm-control/backend python -m tm_control serve &
(cd tm-control/ui && npm run dev)
```
Click through at phone width (375 px) and desktop: `/` → `/setup` → EULA → claim with the printed code → system-password step (fake job succeeds) → home shows the device card and tiles → account: change password → `/users`: add a viewer → log out → log in as the viewer → home shows no admin tiles, `/users` redirects. Record the result in the PR's Testing section. Expected: no console errors; every step as described.

Also render the image locally once: `podman build -f <(render Containerfile.j2) container/revproxy` is awkward because of the Jinja; instead run the Task 7 nginx-parse test and trust the Pi build in Task 12.

- [ ] **Step 5: Run the off-device suites**

Run: `python -m pytest tm-control/backend/tests script/tests -q`. Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add tm-control/ui tm-control/backend container/revproxy script/ansible script/tests .gitignore
git commit -m "Add the control app's UI (setup, login, home, account) and build it into the reverse proxy image" -m "<trailer block>"
```

---

### Task 11: Docs and CLAUDE.md

Follow "Writing docs → Style". Describe how things work, not how they changed; release notes carry the change. Run `~/.venvs/tm-docs/bin/mkdocs build --strict` at the end.

**Files:**
- Create: `docs/use/control-app.md` (Use the device → "Control app and login": claiming a device with the setup code, the EULA, logging in, admin and viewer roles, viewer accounts, changing passwords, the system password, log out everywhere, what to do if the control app is down, `sudo tm-control reset-admin`)
- Create: `docs/development/tm-control.md` (Development → "tm-control": the backend layout, modules, adapters, fake mode and `npm run dev`, how `auth_request` and the identity headers work, how to add a module; one diagram of the request flow)
- Modify: `docs/use/home-page.md` (the home page is the control app; the table loses its Login column and gains "Who can open it": any user / administrators; `/nr/` no longer says `admin`/`password`; the "If the home page doesn't load" note mentions the rescue page)
- Modify: `docs/setup-guide.md` (step 1 becomes "Claim the device": open the home page, enter the setup code from the installer's output, create the administrator account, accept the terms; later steps say "log in as an administrator" where they open Frigate or the editor)
- Modify: `docs/software-installation.md` (the installer prints the setup code at the end; keep it; "After it, open … and claim the device")
- Modify: `docs/build-your-own-device-diy/update.md` (after this update every app asks for the control app's login; a device that was never claimed shows the setup page, and the code is in the installer's output or in `/etc/traffic-monitor/setup-code`; the Node-RED editor's old login is gone)
- Modify: `docs/reference/network.md` (port 80 row: "the control app and every app behind its login"; a row for nothing new on the LAN; note that 8090 is loopback-only, like the apps)
- Modify: `docs/reference/tmsetup.md` (the `tm-control` tag row: the control app service, the manifest, the setup code; the edge tags update together, now including `tm-control`; `-f` keeps nothing new)
- Modify: `docs/configuration/environment.md` (`TM_NR_TOKEN_KEY` row: set by the installer, leave it; `NODE_RED_CREDENTIAL_SECRET` row unchanged)
- Modify: `docs/configuration/frigate-config.md` (Frigate's own login is off; the proxy passes the user and role; don't turn `auth.enabled` on; Frigate's Logout link logs out of the device)
- Modify: `docs/use/system-admin.md` (services table: `tm-control.service`; "When to restart what": the control app; "Where things are": `/var/lib/tm-control/state.sqlite`, `/etc/traffic-monitor/`)
- Modify: `docs/development/dev-environment.md` (step 1: log in to the device as an administrator, then open the editor; no `admin`/`password`)
- Modify: `docs/data-and-payloads/data-overview.md` and `docs/help-and-faq/frequently-asked-questions.md` (the sentences saying the live view and recordings have no login now say every app is behind the device's login, which is a login for the operator's network users, not an access control on the images themselves; link to the control app page)
- Modify: `README.md` (the UI list: every path needs the device login; the `/nr/` line loses the default login)
- Modify: `mkdocs.yml` (`nav:` entries for the two new pages; both folders are already globbed by `llmstxt`)
- Modify: `CLAUDE.md` ("What this repo is": `tm-control/` now has the backend, UI, and jobs; "Runtime topology": tm-control on `127.0.0.1:8090`, `auth_request`, the identity headers, Frigate on 8971, the Node-RED token, the UI built into the revproxy image, the rescue page; "Provisioning": the edge tag set includes `tm-control`, the manifest, the setup code, the three secrets; "Commands": `tm-control/backend/tests` and the UI container command; a rule that `settings.js`'s `verifyProxyToken` and `tm_control.core.auth.NodeRedToken` must agree, pinned by `test_node_red_settings.py`)
- Modify: `CONTRIBUTING.md` only if its test commands list changes (it points to CLAUDE.md's; check)
- Modify: `design/specs/2026-10-02-tm-control-platform-design.md`, factual corrections only, one line each, for the approved decisions that change its text: nginx calls verify with `X-Original-URI` and the required role, not a proxy secret (decisions 2 and 4); verify's 200 also carries `X-TM-Frigate-Secret`, and Frigate gets `X-Forwarded-User`/`X-Forwarded-Groups` (decisions 1 and 2); the UI "Build" paragraph describes the multi-stage revproxy image (decision 3); the polkit bullets say M2 ships the unit rules only and the time and reboot rules come with M3 (decision 11); job logs are polled in M2 and the SSE stream comes with M3 (decision 6)

- [ ] **Step 1: Write the pages and edits**

Keep each page to one reader and one job. The control app page is a how-to for operators; the tm-control development page is for contributors.

- [ ] **Step 2: Check the build and the links**

```bash
~/.venvs/tm-docs/bin/mkdocs build --strict 2>&1 | tail -5
grep -rn "admin.*password\|password.*admin" docs README.md | grep -v -i 'rtsp\|broker\|mqtt\|ThingsBoard\|Raspberry Pi user\|system password'
```
Expected: `Documentation built` with no warnings; the grep prints nothing.

- [ ] **Step 3: Commit**

```bash
git add docs mkdocs.yml README.md CLAUDE.md
git commit -m "Document the control app's login, setup code, and roles, and update the pages the login changes" -m "<trailer block>"
```

---

### Task 12: Device tests, the Pi test plan, and the PR

Same rules as M1's Task 12: a dev Pi from the inventory, never a field device; ask before anything disruptive; `T` is `.venv/bin/python script/devpi/tmdev.py` run from this branch's checkout. Device names, addresses, and the setup code stay out of commits and PR text.

**Files:**
- Modify: `script/devpi/tests/test_web.py`
- Modify: `script/devpi/tests/test_services.py` (`tm-control.service` in `CORE_UNITS`)
- Modify: `script/devpi/tests/devpi_checks.py` (`tm-control.service` in `RESTARTING_UNITS`; a `tm_control_login(hostvars)` helper returning `Redacted` username and password from the host's `tm_control_login` inventory variable, or skipping)
- Modify: `script/devpi/tests/test_disruptive.py` (tm-control stopped; reset-admin and claim)
- Modify: `script/devpi/dev-pis.example.yml` (`tm_control_login: {username, password}` with a comment: the dev Pi's admin login for the device tests; set it after claiming the unit; never commit the real file)
- Modify: `script/devpi/README.md` (the new inventory key and the module table rows)

**Interfaces:**
- Consumes: #215's fixtures (`host`, `address`, `expect`, `codedir`, `codeowner`, `hostvars`), `Redacted`, `status_from_this_machine`, `check_closed_to_this_machine`, `wait_until_ready`; the inventory's new `tm_control_login`.
- Produces: a `session(address, username, password)` helper in `test_web.py` that logs in over HTTP (`POST /api/v1/auth/login` with `Origin: http://<address>`) and returns the cookie header value, and `viewer_session` (creates a viewer named `tmdev-viewer-<random>` through the API, yields its cookie, deletes it after). Both raise `pytest.skip` when the inventory has no login.

- [ ] **Step 1: Write the device tests**

`test_web.py`:
- M1's tests that hit app paths from this machine now send the admin cookie: `test_feeds_is_view_only_from_this_machine` and `test_data_export_errors_from_this_machine` (without a session every path is 302). `test_frigate_api_hides_the_rtsp_password` reads Frigate on the Pi's `localhost:5000` instead of through the proxy. The expected statuses don't change.
- `DIRECT_PORTS` gains `(8090, "/api/v1/health")`; `CLOSED_TO_NETWORK` gains `8090`.
- `test_proxied_locations_respond` keeps passing: it treats 302 as answering. Map `/api/` to `/api/v1/health` and expect 200; `/` expects 200.
- `test_app_paths_redirect_to_login_without_a_session`: `/dashboard/`, `/frigate/`, `/ui/`, `/nr/`, `/feeds/`, `/storefiles`, `/system/` → 302 with `Location` starting `/login?next=` (or `/setup` if the unit isn't claimed; then skip the rest with a message).
- `test_verify_and_auth_locations_are_hidden`: `/api/v1/auth/verify` → 404, `/_auth` → 404.
- `test_admin_session_opens_every_app`: with the admin cookie each path above answers 200 (or Cockpit's 200/303).
- `test_viewer_gets_403_on_admin_paths`: `/nr/`, `/feeds/`, `/storefiles?files=x`, `/system/`, `/api/v1/users` → 403; `/dashboard/`, `/ui/`, `/frigate/` → 200.
- `test_frigate_ignores_client_supplied_roles`: viewer cookie plus `X-Forwarded-Groups: admin` and `Remote-Role: admin` on `/frigate/api/config/raw` → 403; the admin cookie → 200.
- `test_frigate_knows_the_user`: admin cookie on `/frigate/api/profile` → `username` equals the inventory username, role `admin` (compared on this machine; the username is `Redacted`).
- `test_node_red_editor_opens_with_the_proxy_token`: admin cookie on `/nr/settings` → 200 and JSON with `user.username`; no cookie → 302.
- `test_login_backs_off`: six wrong passwords for a made-up user → the sixth is 429 with `Retry-After`.
- `test_tm_control_listens_on_loopback_only`: on the Pi, `ss -tlnp` has `127.0.0.1:8090` and no `0.0.0.0:8090`/`[::]:8090`.
- `test_no_secret_in_the_install_log` (pii_free): the three secret files' values don't appear in `~/tmsetup-*.log` (the M1 Step 9 pattern with `grep -F -f`); the setup code may.
- `test_unavailable_page_is_served_for_errors`: `GET /unavailable.html` → 404 (internal only).

`test_disruptive.py`:
- `test_app_paths_fail_closed_when_tm_control_is_down`: stop `tm-control.service`; `/frigate/` → 503 with `9090` in the body; `/` → 200; start it; `wait_until_ready`.
- `test_reset_admin_then_claim` (pii_free only): `sudo tm-control reset-admin` → parse `Setup code: ([A-Z2-9]{4}-[A-Z2-9]{4})` from stdout (never log it); `/dashboard/` → 302 to `/setup`; `POST /api/v1/setup/claim` with the inventory login and the EULA version from `/api/v1/setup/eula` → 201; the admin session works again. This re-creates the inventory's admin, so the other tests keep passing.

- [ ] **Step 2: Open a check, deploy, and run the whole suite**

```bash
$T check start --host <host> --pr <n> --title "tm-control M2: core and login"
$T deploy <host> --on-pi
$T run <host> -- 'systemctl is-active tm-control.service revproxy.service frigate.service node-red-tm.service'
$T run <host> -- 'sudo journalctl -u tm-control.service -b --no-pager -o cat | tail -20'
$T test <host>
```
Expected: the deploy prints the setup code at the end (don't paste it anywhere); all four units active; tm-control's journal shows uvicorn listening on `127.0.0.1:8090`; the login-dependent tests skip until Step 3, everything else passes, including M1's tests. The first deploy builds the UI inside the revproxy image; note how long the build unit took (`systemctl show -p ExecMainStartTimestamp,ExecMainExitTimestamp revproxy-build.service`).

- [ ] **Step 3: Claim the unit and store the login**

A person opens `http://<host>.local/`, follows setup with the printed code, and creates the admin account. Put that login in the inventory as `tm_control_login`. Then `$T test <host>` again. Expected: the web tests pass, none skipped for a missing login. Record an item per Review Focus line that this covers (1, 3, 5, 6, 7).

- [ ] **Step 4: Upgrade path from M1**

If a bench unit is still on M1 (or re-deploy `dev` first): deploy M2 over it without `-f`. Expected: `frigate.env` gains `FRIGATE_PROXY_AUTH_SECRET`, `node-red-tm.env` gains `TM_NR_TOKEN_KEY` (check with `sudo grep -c` on the Pi, never printing values), `tm-control migrate` printed `added proxy auth settings`, Frigate's `config.yml` has the three sections, and `/frigate/` works after login. Record an item (Review Focus 1, 2, 4).

- [ ] **Step 5: Single-tag runs**

```bash
$T deploy <host> --on-pi -- -t revproxy
$T deploy <host> --on-pi -- -t frigate
$T test <host> -- -k "web or services"
```
Expected: both runs leave the login working (Review Focus 2). Record an item.

- [ ] **Step 6: Disruptive tests**

Ask first. `$T test <host> --disruptive -- -k "tm_control_is_down or reset_admin"`. Then, if the person agrees to the reboot, the full `--disruptive` set. Expected: pass; after the reboot, `test_no_crash_restarts[tm-control.service]` and `[revproxy.service]` are 0.

- [ ] **Step 7: Record what needs a person**

```bash
$T check item "Setup on a phone: /setup → EULA → code → admin account → system password → home, at phone width" manual
$T check item "iPhone Safari: after login, Frigate live view and Dashboard 2.0 live updates work through the cookie" manual
$T check item "Node-RED editor at /nr/ opens with no login dialog, deploys, and shows debug output (comms)" manual
$T check item "Frigate's Logout link logs out of the device; the next /frigate/ redirects to /login" manual
$T check item "System password set from the UI: SSH login with the new password works" manual --note "changes the dev Pi's user password; the person picks it"
$T check item "Change the admin password on one browser; a second browser is logged out of /frigate/ and /dashboard/" manual
```
When the person reports back, `$T check reopen <run dir>` and re-record each as `pass` or `fail`.

- [ ] **Step 8: Close the check and commit**

```bash
$T check status && $T check end
git add script/devpi
git commit -m "Add device tests for the control app's login: redirects, roles, Frigate's identity headers, the editor token, and failing closed" -m "<trailer block>"
```

- [ ] **Step 9: Open the PR**

Target `dev`; branch `feature/tm-control-core-login/201`. Body from the template:
- **Summary:** M2 of the tm-control platform spec: one login in front of every app. Link the spec, the plan (the public copy of this file, committed in this PR under `design/plans/`), and `#201`.
- **Docs:** the Task 11 pages.
- **Testing:** the check's checklist with placeholders for names and addresses; the off-device counts; the Task 1 spike results; the fake-mode click-through.
- **AI assistance:** filled in.
- **Release notes:**
  - Every app now needs the device's login. A new or upgraded device shows a setup page; the installer prints the setup code at the end of the run (also in `/etc/traffic-monitor/setup-code` until the device is claimed).
  - Frigate's own login is off; the proxy passes who is logged in. Frigate's Logout logs out of the device.
  - The Node-RED editor's `admin`/`password` login is gone; administrators open it from the home page.
  - `sudo tm-control reset-admin` recovers a device whose administrator password is lost.
  - Upgrade with a full `tmsetup.sh` run. Add the user's login to any script or bookmark that opened an app path directly.
