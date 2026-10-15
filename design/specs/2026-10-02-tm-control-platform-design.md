# tm-control: Traffic Monitor control app, platform design

- **Status:** approved 2026-10-02. Aligned with the open PRs on 2026-10-13. Re-checked on 2026-10-14 after #197, #218, #219, #220, and #222 merged into `dev` (see "Builds on open PRs").
- **Tracking:** #102 (wizard / configuration page), #201 and D#200 (central authentication), #169 (firewall), #185 (Cockpit), D#94 (FastAPI for host calls), D#199 (captive portal), #211 (data downloads 404 behind the proxy), #223 (data download errors return 200)
- **Scope:** this spec covers the **platform**. Features built on it, such as Wi-Fi/hotspot and camera rename, get their own specs.

## Builds on open PRs

Several PRs were open, most of them drafts, when this was written. The design builds on their approach. Their code may still change, so each milestone's plan re-checks what has merged before it starts.

```
dev (now includes #197, #218, #219, #220, #222)
└─ #202 feature/ai-use-policy (CLAUDE.md, AI-use policy)
   ├─ #205 bugfix/tmsetup-sudo-hint/mz
   ├─ #206 refactor/tmdb-schema-migrations/mz → #208 refactor/tmdb-schema-activate/mz
   │     → #214 feature/devpi-tooling/mz → #215 feature/devpi-tests/mz
   └─ #210 feature/switch_nginxconf_from_dict → #212 feature/185-cockpit
```

On 2026-10-14 every open branch above contained the latest `dev`, and all four stacks merged together without conflicts.

| PR | What this design takes from it |
|---|---|
| #202 | The AI-use policy, commit trailers, and CLAUDE.md conventions. |
| #205 | Raspberry Pi OS 6.2 and later asks for a sudo password. tm-control's runtime privilege never uses sudo (it uses polkit and root jobs), so this doesn't affect it. `sudo tm-control reset-admin` asks for the admin's password. |
| #206, #208 | The dev venv (`script/requirements-dev`) and pytest layout for off-device tests. The `runuser` pattern for commands that run as the code owner. Flows that no longer create tables. |
| #210 | **The nginx layout:** one `location` file per app in `container/revproxy/tm/locations/`, listed in `tmsetup_revproxy_locations`. Shared headers come from `tm/snippets/proxy-common.conf`. The config is bind-mounted, checked with `nginx -t` before restarting, and `/frigate` is hardcoded. tm-control's nginx changes are location files and snippets in this layout. |
| #212 | Cockpit at `/system/`, from backports, with `AllowUnencrypted` and `LoginTo = false`. It keeps its own login and listens on `:9090`, which is the rescue console. |
| #214, #215 | **Pi checks** run through `script/devpi/tmdev.py` (`deploy`, `check`, `test`). `--src` points a check or deploy at another checkout, such as a milestone's worktree. Device tests in `script/devpi/tests` compare a bench Pi against its expected hardware. Tests that stop services go in `test_disruptive.py` and run only with `test --disruptive`. Each milestone adds device tests there. |

**Merged into `dev` on 2026-10-14**

| PR | What changes for this design |
|---|---|
| #197 | Radar measurements in `flows.json`. #208 adds its radar time index to the schema baseline. tm-control's `/tm-internal/` endpoints go on top of the merged flows. |
| #218, #219 | Frigate gets the HEVC decoder that `utils/find_hevc_device.sh` finds (`tmsetup_hevc_device`, falling back to `/dev/media3`). M3's hardware checks add it as a probe. |
| #220 | Frigate 0.18.1, Node-RED 5.0.8, and go2rtc 1.9.14 with a checksummed download. go2rtc 1.9.12 and later refuses `exec:`, `echo:`, and `expr:` sources sent through its API, and can limit which modules load and which commands `exec` runs. M1 uses both limits. Frigate 0.18 rewrites an older `config.yml` to `version: 0.18-0` on its first start, keeping a `backup_config.yaml`. |
| #222 | When no accelerator is found, Frigate's `config.yml` gets a `cpu` detector. M3 reports that as a warning, not a failure. |

## Context

Today an operator configures a Traffic Monitor over SSH:
- Node-RED `config.yml` and Frigate `config.yml` are edited by hand.
- Wi-Fi is set up with `nmcli`.
- Services are restarted with `systemctl`.

The reverse proxy's home page (`container/revproxy/html/index.html.j2`) is a static list of links. Each app is also reachable on its own published port, each with its own login or none. That works for DIY builders but not for buyers of pre-built units, who shouldn't need SSH. It also doesn't suit temporary deployments that are reconfigured in the field, often offline on the device's hotspot.

**Outcome:** `tm-control`, a TM-specific control app at `/` behind the reverse proxy:
- A responsive UI for desktop and phone.
- An extensible, API-first backend that coordinates Frigate, Node-RED, go2rtc, and privileged OS services.
- One login in front of every app, with direct app ports closed.

It doesn't replace Frigate, the Node-RED dashboards, or Cockpit.

### Success criteria

1. **New unit:** an operator goes from hotspot to EULA, claim, time, and all-green checks with no SSH. Wi-Fi setup follows in its own feature spec.
2. **Re-deployment:** a temporary re-deployment takes minutes from a phone, once the location and camera-rename features land.
3. **Extensibility:** a new sensor or service is one backend module plus one UI module, with no core changes.
4. **Resilience:** when Frigate, Node-RED, or the pod is broken, the home and status pages still work and can restart them.
5. **Offline:** everything works offline over plain HTTP, on an IP address or a `<hostname>.local` name.

## Decisions

| Topic | Decision |
|---|---|
| Backend placement | Host systemd service `tm-control` (Python 3.11+, FastAPI). Runs as the code owner (`tmadmin`) in a systemd sandbox. Doesn't depend on Podman, so it keeps working when containers don't. |
| Privilege | polkit rules from one Ansible allowlist cover TM units, time, and reboot. NetworkManager comes later. Fixed, root-owned `tm-job-<name>.service` units handle everything else. tm-control never runs as root. |
| Edge | `revproxy` (nginx) leaves the pod and runs with `Network=host`. It's the only LAN web listener. Everything else binds to `127.0.0.1`. nginx keeps #210's layout: one location file per app, bind-mounted, and checked with `nginx -t` before each restart. |
| Auth | tm-control serves the login and issues session cookies. nginx `auth_request` checks every app path. Identity is passed on to Frigate (port 8971 proxy headers plus `X-Proxy-Secret`) and to the Node-RED editor (signed token in `tokenHeader`). Roles: admin and viewer. |
| Why not off-the-shelf SSO | Authelia and tinyauth need HTTPS and real domains or subdomains, which rules out IPs and `.local`. Basic Auth isn't sent on WebSocket upgrades by Safari, which breaks Frigate live view and Dashboard 2.0 on iPhones. Using Frigate's login for everything would lock everyone out whenever Frigate breaks. |
| First run | Welcome → EULA → **setup code** + admin account → optional system (Linux) password with a "same password" checkbox → home. |
| Linux accounts | The OS admin account created in Raspberry Pi Imager stays: it's for Cockpit, SSH, updates, and recovery. Web users live in tm-control, not Linux. `tmadmin` stays a no-login service account. Dev Pis also have #214's key-only `tmdev` account, which field devices never get. |
| Cockpit | As #212 sets it up: its own PAM login, at `/system/` behind the proxy, and directly on `:9090` as the rescue console. |
| Install variables | A fixed value shared by several tasks or templates becomes a non-configurable variable in `vars/main.yml`, like `tmsetup_hailo_driver_dir` and `tmsetup_revproxy_locations`. A value an operator may change goes in `defaults/main.yml`, with `-C` for booleans. A literal used once, in one file, is hardcoded, like `/frigate` in `frigate.conf.j2`. |
| Host service | tm-control follows the host-service pattern of `go2rtc_server.service`, not the container trio (Containerfile, `.build`, `.container`). That's deliberate: it needs host privileges and has to keep working when Podman doesn't. |
| Front end | Vue 3 + Vuetify 3 + TypeScript + Vite, the same stack as Node-RED Dashboard 2.0. Kept thin: logic in Python, the UI renders API data. Conventional, documented patterns so non-front-end maintainers can review it. |
| Config ownership | Existing config files stay the source of truth. tm-control edits them in place and never keeps a shadow copy. Node-RED stays the only writer of `tmdb.sqlite`. |
| Install facts vs live state | The install manifest holds install facts and hardware probe definitions only. tm-control probes live hardware itself. |

## Architecture

### Edge and ports

This is the end state after M2. M1 keeps `/frigate/` on :5000 and the current Node-RED editor login.

```
Phone / laptop ──HTTP :80──▶ nginx (revproxy, host network)
  /                 UI static files ({{codedir}}/tm-control/ui-dist)   open: login, setup, assets
  /api/             tm-control   127.0.0.1:8090                         tm-control checks its own cookie
  /frigate/         Frigate      127.0.0.1:8971 (TLS off)               auth_request, any role
  /dashboard/ /ui/  Node-RED     127.0.0.1:1880                         auth_request, any role
  /storefiles       Node-RED     127.0.0.1:1880 (data export download)  auth_request, admin
  /nr/              Node-RED editor                                     auth_request, admin
  /feeds/           go2rtc       127.0.0.1:1984 (viewing paths only)    auth_request, admin; config API/editor denied
  /system/          Cockpit      127.0.0.1:9090                         auth_request, admin + Cockpit login
Outside nginx: SSH :22, Cockpit :9090 (rescue, once #185 lands), mDNS, hotspot DHCP/DNS,
               go2rtc RTSP :8554 (credentials; Frigate reads the camera through it)
```

- **nginx config** (#210's layout):
  - Each app's `location` is its own file in `container/revproxy/tm/locations/`, listed in `tmsetup_revproxy_locations`.
  - Moving to the host network keeps #210's bind mounts and its pre-restart `nginx -t`.
  - `go2rtc.conf` and `cockpit.conf` change from `host.containers.internal` to `127.0.0.1`. The pod-app locations already use `127.0.0.1`.
  - A new `storefiles.conf` proxies `/storefiles` to Node-RED. The Dashboard's database page links both its downloads, the JSON export and the database, to `/storefiles?files=…` from the site root, so through the proxy they return 404 (#211). Today they work only on port 1880, which M1 closes. A whole `tmdb.sqlite` can be several GB, so the location turns off proxy buffering. M1 also fixes the Node-RED side (#223). Its download errors come back as 200, and a `tar` failure leaves the download open.
- **Pod** (`container/traffic-monitor.pod.j2`):
  - Publish 5000, 8971, 1880, and 1883 as `127.0.0.1:<port>:<port>`.
  - Drop 80, which moves to the host-network nginx.
  - Drop 1964, 8080, and 8564–8566.
- **go2rtc** (`files/go2rtc.yaml` becomes a template):
  - `api.listen: 127.0.0.1:1984`.
  - RTSP username and password come from a generated secret. Frigate inputs use `{FRIGATE_GO2RTC_RTSP_USER}:{FRIGATE_GO2RTC_RTSP_PASSWORD}@`. These are new variables, so a `FRIGATE_RTSP_PASSWORD` that operators already use for their own cameras is left alone.
  - `app.modules` loads only the modules TM uses: `api`, `ws`, `rtsp`, `exec`, `ffmpeg`, `mp4`, `hls`, and `mjpeg`. Leaving out `webrtc` turns WebRTC off. `webrtc.listen: ""` alone would only drop the fixed :8555 port, and WebRTC could still negotiate on random UDP ports. Players fall back to MSE (Safari 17 and later through ManagedMediaSource), or to HLS on older iPhones.
  - `exec.allow_paths: [rpicam-vid]`: stream sources can run only the camera command.
  - `go2rtc.conf` exposes only go2rtc's viewing paths:
    - It accepts only GET.
    - `src` must be a plain stream name. go2rtc itself already refuses `exec:` sources from its API. This rule also blocks URL sources, which would make the device connect to other hosts, and `ffmpeg:` sources.
    - A sibling location denies API paths other than the ones the players use: `location ~ "^/feeds/api(?!/(streams|ws|frame\.jpeg|stream\.(mp4|m3u8|mjpeg)|hls/(playlist\.m3u8|segment\.(ts|m4s)|init\.mp4))$)" { return 403; }`.
  - go2rtc doesn't ask for its API or RTSP credentials from localhost. nginx connects from localhost, so nginx's rules are the API's real limit.
- **Cockpit** (#212): `cockpit.conf` sets `AllowUnencrypted`, so the `:9090` rescue console also answers over plain HTTP. Like SSH, it's protected only by the OS login.
- **MQTT 1883:**
  - Loopback by default.
  - LAN access is an opt-in install variable for off-device sensors and requires broker credentials (`TM_MQTT_BROKER_USERNAME/PASSWORD`).
  - Outbound connections, such as a future ThingsBoard MQTT link, are unaffected.
- **Secrets:**
  - Generated once on the device under `/etc/traffic-monitor/` (root:tmadmin 0640). Never in the repo.
  - They cover the session key, the Frigate proxy secret, the Node-RED token key, the internal token, and the RTSP password.

### Login and first run

**Request flow**
1. nginx runs `auth_request /_auth`, which calls `GET 127.0.0.1:8090/api/v1/auth/verify` with `X-Original-URI` and the proxy secret.
2. The response is one of:
   - **200** with `X-TM-User`, `X-TM-Role`, and `X-TM-NR-Token`.
   - **401** → redirect to `/login?next=…`.
   - **403** → forbidden.
3. verify also sends the user to `/setup` while the device is unclaimed and to `/welcome` until the EULA is accepted.

**In the location files** (#210's layout)
- Two snippets carry the login check: `tm/snippets/auth-viewer.conf` and `tm/snippets/auth-admin.conf`. Each holds `auth_request` plus the identity headers.
- Every location file includes one of them. That replaces a per-proxy `auth:` field.
- tm-control's own paths get their own location files, listed in `tmsetup_revproxy_locations`:
  - `/api/`
  - the internal `/_auth`
  - the UI root

**Session cookie**
- Named `tm_session`, signed with itsdangerous.
- Flags: HttpOnly, SameSite=Lax, and Secure once HTTPS exists.
- Carries the user id, a per-user session epoch, and the issue time.
- 7-day rolling expiry.
- Bumping the epoch on a password change, or with "log out everywhere", invalidates every session.

**Passwords**
- argon2id (argon2-cffi), with a 10-character minimum.
- Login attempts back off per IP and per user. Failures are logged with the IP for a future fail2ban (D#198).
- CSRF protection: non-GET requests need a matching Origin or Referer, and bodies must be JSON.

**Claiming**
- tmsetup generates a setup code when no admin exists and prints it at the end of the install, per host for remote installs. The code is 8 characters from an unambiguous alphabet, formatted `XXXX-XXXX`.
- tm-control's state stores only a hash. The code works once, and attempts are rate-limited.
- A root-only copy at `/etc/traffic-monitor/setup-code` (0600) lets tmsetup re-runs print the same code until the device is claimed. The first tmsetup run after claiming deletes it.
- `sudo tm-control reset-admin` unclaims the device and prints a new code. On Raspberry Pi OS 6.2 and later, sudo asks for the admin's password (#205).
- Sellers of pre-built units print the code on the card, next to the hotspot password.

**EULA**
- A versioned markdown file in the repo, with placeholder text until the project supplies the final wording.
- Acceptance is per device and records the version, time, and user.
- A new version prompts again.

**Frigate**
Frigate is on 0.18.1 (#220). Its config schema has every key below, and `proxy.auth_secret` is an `EnvString`, so `{FRIGATE_…}` substitution works there. How they behave at runtime still needs a Pi (see Risks).
- `auth.enabled: false`.
- `proxy.header_map.user/role` and `proxy.auth_secret`.
- `proxy.default_role: viewer`, so a missing header means least privilege.
- `proxy.logout_url: /logout`.
- `tls.enabled: false`.
- `frigate.conf` keeps #210's hardcoded `/frigate` base path and `X-Ingress-Path`. Its upstream moves to `127.0.0.1:8971`.
- Node-RED (`frigate:5000`) and tm-control (`127.0.0.1:5000`) keep using the internal port.

**Node-RED editor**
- `adminAuth` gets `tokens()` and `tokenHeader`. Node-RED 5.0.8 (#220) still supports both.
- The token is short-lived, HMAC-signed by tm-control, and carries the user and role. `settings.js` verifies it.
- The built-in editor user is removed.
- Dashboards and http-in routes are gated by nginx only.

### tm-control backend

```
tm-control/
  backend/tm_control/
    core/       settings + manifest, auth/sessions, state DB, job runner, command runner, errors, migrate CLI
    adapters/   systemd, journal, timedate, frigate, nodered, go2rtc, hardware, yamlfile (+ later nmcli, github)
    modules/    setup (claim/EULA), auth, system, services, status, time … (one folder per feature)
  backend/tests/   pytest, off-device, recorded fixtures
  ui/              Vue app
  jobs/            root job scripts, installed root-owned to /usr/local/libexec/traffic-monitor/
```

**Adapters**
- The only code that touches the OS or other apps. They return Pydantic models.
- Commands go through one runner: argv lists (never a shell), timeouts, and output caps.
- Commands use machine-readable output: `systemctl show`, `journalctl -o json`, `timedatectl show`, `lspci -nn`, `lsusb`, and `/sys`.

**Modules**
- Each module declares an `id`, a router, status checks, and wizard steps. A check returns an id, title, status (ok/warn/error/unknown), detail, and a fix action or link.
- The core loads modules from the manifest's enabled list, so plate-recognizer appears only when it's installed.
- Checks never raise. They report `unknown` or `error` with a reason, so the status page always renders.

**Privilege**
- `tm-control.service` runs as `User=tmadmin` with `SupplementaryGroups=systemd-journal video`.
- Sandbox: `NoNewPrivileges`, `ProtectSystem=strict`, `StateDirectory=tm-control`, `RuntimeDirectory=tm-control` (for job requests), `PrivateTmp`, and `RestrictAddressFamilies`.
- `ReadWritePaths=` is limited to `{{codedir}}/node-red-tm/config`. Feature specs add paths only when they need them, for example Frigate's `model_cache` for model upload.
- polkit rules (`/etc/polkit-1/rules.d/50-traffic-monitor.rules`, rendered from the `tmsetup_tm_control_polkit` list in `vars/main.yml`) allow:
  - `systemd1.manage-units` for named TM units, with the verbs start, stop, and restart.
  - `timedate1.set-time`, `set-timezone`, and `set-ntp`.
  - `login1.reboot` and `power-off`.
- Root jobs:
  1. The API writes a request to `/run/tm-control/jobs/<name>.json`.
  2. It starts `tm-job-<name>.service`.
  3. The root-owned script validates the request strictly, does one thing, and deletes the request.

  Status comes from `systemctl show` and logs from the journal. Jobs survive API restarts.
- None of this uses sudo, so Raspberry Pi OS 6.2's sudo password (#205) doesn't get in the way.

**State**
- `/var/lib/tm-control/state.sqlite`, with tm-control as the only writer.
- Holds users and roles, session epochs, claim state and the setup-code hash, EULA acceptances, job records, and an audit log of admin actions.

**Manifest**
- Written by every tmsetup run to `/etc/traffic-monitor/manifest.json`. tm-control only reads it.
- Contents:
  - TM version, and git commit and branch.
  - Component versions from `vars/main.yml`.
  - The installing user (`ansible_user_id`, or `-l` for remote installs).
  - Enabled options.
  - Probe definitions from `tmsetup_detectors` and `tmsetup_radar_paths`, and the HEVC decoder in `tmsetup_hevc_device`.
  - The drivers and firmware tmsetup installed, with versions.
  - `tmsetup_revproxy_locations`, which tells tm-control which apps are proxied. For example, Cockpit's tile appears only when `cockpit.conf` is listed.

**API**
- JSON under `/api/v1/`, with one error shape: `{error: {code, message, detail}}`.
- Long-running actions return 202 and a job id. `GET /jobs/{id}` reports status, and an SSE stream carries the log.
- The status page polls about every 10 seconds.
- The OpenAPI document generates the UI's typed client.

### Integrations

**Node-RED `config.yml`**
- Edited with a ruamel.yaml round trip, which keeps comments and quoting.
- Written atomically (temp file, then rename), with a timestamped backup first.
- Returns 409 if the file's hash changed since it was read.
- Node-RED reloads the file through the `init-config` `watch` node. That node uses `node-watch`, which watches the parent directory, so renames count. The fallback is an explicit reload endpoint.

**Node-RED state**
- New `http in` endpoints under `/tm-internal/` cover status, the last config errors from `init config defaults`, and deployment and radar state.
- Each endpoint checks `X-TM-Internal-Token`, and nginx denies `/nr/tm-internal/`.
- Add them by script, as CLAUDE.md describes, on top of whatever flows have merged. #197 and #208 both change `flows.json`.

**Frigate**
- Reads: `/api/config`, `/api/stats`, and `/api/version`.
- Writes:
  1. `GET /api/config/raw`.
  2. Round-trip edit.
  3. `POST /api/config/save?save_option=saveonly|restart`.

  Frigate validates the result, and a rejected change leaves nothing applied. This is the same approach as the existing ThingsBoard restore flow.

**go2rtc**
- Read-only `/api/streams`.

**Hardware changes**
- tm-control probes live hardware on each status refresh, and when the user presses **Re-scan hardware**, using the manifest's probe definitions.
- Each detector goes through layered checks:
  1. present
  2. driver and firmware ready
  3. visible to its container
  4. configured in Frigate
  5. working, according to `/api/stats`

  The first failing layer names the fix.
- With no accelerator, Frigate runs its `cpu` detector (#222). The detector check reports that as a warning ("detecting on the CPU, slow"), not an error.
- The HEVC decoder (#218) gets two layers: present, and passed to Frigate.
- The fix actions ship in the detector feature spec: "Use in Frigate", an "Install support" job running `tmsetup.sh -t detectors -t frigate`, and "Switch detector". The platform ships the checks and a restart button.
- #215's device tests check the same layers from the dev machine: expected, present, configured, and working. M3 uses the same layer names and the same probe commands, so a failure reads the same in both.
- **Open question for M3 planning:** should #215's device tests assert against tm-control's `/api/v1/status` instead of keeping their own probes? That would remove duplication, but the tests would then depend on tm-control working.

### UI (`tm-control/ui/`)

**Structure**
- `App.vue`: the app bar and a responsive nav drawer.
- `router.ts`: sends unclaimed devices to `/setup`, unaccepted EULAs to `/welcome`, and missing sessions to `/login`.
- `api/`: the generated client.
- `stores/session.ts`: the only Pinia store.
- `modules/<name>/`: pages plus an `index.ts` that exports `{id, routes, nav, wizardSteps}`. `modules/index.ts` collects them.
- Shared components: StatusCard, CheckList, JobLog, and ConfirmDialog.

**Offline-ready**
- All assets are bundled. The UI uses system fonts and `@mdi/js` icons.
- Theme colors come from `tmsetup_homepage_colors`.

**Build**
- tmsetup runs `npm ci && npm run build` in a throwaway, pinned `docker.io/node:22-alpine` container, only when the UI sources change (tracked by a hash stamp).
- The output goes to `{{codedir}}/tm-control/ui-dist`, which is mounted read-only into nginx.

**Fake mode**
- `TM_CONTROL_FAKE=1` runs the backend on recorded fixtures, and `npm run dev` proxies `/api` to it.
- This lets anyone run and review the whole app on a laptop, without a Pi.

## v1 scope

1. **First run and auth:** claim, EULA, login and logout, an account page, admin-managed viewer accounts, and the system-password root job.
2. **Home:**
   - A device card with hostname, serial, TM version, time, and a health summary.
   - App tiles from a fixed list in the UI's home module that matches the location files. A tile shows only when its location is listed in the manifest. Viewers don't see admin-only tiles.
   - This replaces #210's hand-written `index.html.j2`.
3. **Status and config check:**
   - **Services:** TM units, with restart.
   - **Apps:**
     - Frigate: reachable, version, and detector stats.
     - Node-RED: reachable, and its config-load errors (D#151).
     - go2rtc: streams producing.
   - **Hardware:** layered detector checks, the HEVC decoder, radars present and visible, disk, and temperature and throttling.
   - **Contracts:**
     - Frigate cameras match `sensors.cameras`.
     - Each enabled camera has `zone_capture`, `zone_near`, `zone_far`, and `zone_radar`.
     - Radar names match `TM_RADAR_SERIAL_PORT_*` and the devices present.
     - lat, lon, and bearing are valid.
     - The time is plausible.
4. **System info:**
   - Versions with commit, OS and kernel, uptime, and memory and disk.
   - **Copy diagnostics**, with secrets stripped.
5. **Date and time:**
   - Device time shown next to browser time.
   - **Set from this browser** sets time and timezone, turning NTP off first if needed.
   - A timezone picker and an NTP toggle.
   - A timezone change restarts the containers, which read `/etc/localtime` at start, and Node-RED re-sends the radar time.

**Later, each with its own spec:**
- Wi-Fi/hotspot and a captive portal. These use NetworkManager checkpoint rollback, plus a host-level auto-hotspot watchdog that evolves `utils/wlan_check.sh`.
- Camera rename.
- location/survey_id: a tmdb migration plus Node-RED changes. Browser geolocation needs HTTPS.
- Detector actions and model upload.
- ThingsBoard settings, including outbound MQTT.
- Radar settings.
- TM update, as a root job around `tmsetup.sh`.
- Container logs and storage.
- Firewall (#169), HTTPS, fail2ban (D#198), and backup/restore (#173).

## Milestones

Each milestone gets its own implementation plan in `design/plans/` and can ship on its own. Each one needs the nginx stack (#210, #212) and the test and tooling stack (#206 to #215), so it starts once those have merged. Its first task re-checks the plan against what merged.

**M1: edge and ports.** Auth stays as it is today.
- revproxy moves to `Network=host` and out of the pod. The `go2rtc.conf` and `cockpit.conf` upstreams move to `127.0.0.1`.
- Pod ports move to loopback, and the unused ones are dropped.
- go2rtc: API on loopback, RTSP credentials, only the modules TM uses (so no WebRTC), and `exec` limited to `rpicam-vid`. `go2rtc.conf` limits `/feeds/` to viewing paths.
- A `storefiles.conf` location, so the Dashboard's data export downloads through the proxy.
- Device tests in `script/devpi/tests` check that the direct ports are closed to the network, that `/feeds/` is restricted, and (disruptive) that the home page survives a stopped pod.
- Secrets are generated on the device.
- A tm-control package skeleton, with its venv and the `tm-control migrate` CLI. The CLI adds RTSP credentials to existing Frigate camera inputs; it edits round trip, makes a backup, and is idempotent.
- `/frigate/` stays on 127.0.0.1:5000, and the Node-RED editor keeps its current login until M2.

**M2: core and login.**
- `tm-control.service`, with its sandbox, polkit rules, job runner, state, and manifest.
- Auth (claim, login, users, verify) and the EULA.
- nginx `auth_request`, through the `auth-viewer` and `auth-admin` snippets that each location file includes. `storefiles.conf` uses `auth-admin` for now, because it can download the whole `tmdb.sqlite`. Revisit if viewers need data export. tm-control's `/api/`, `/_auth`, and UI-root location files are added to `tmsetup_revproxy_locations`.
- Frigate switches to port 8971 with proxy auth, and `migrate` adds the `proxy:`, `tls:`, and `auth:` keys.
- The Node-RED editor switches to proxy tokens, and its built-in user is removed.
- The system-password job.
- The UI shell: setup, login, home, and account.

**M3: status and system.**
- Status and config checks, the Node-RED `/tm-internal/` endpoints, and restart actions.
- Hardware handling:
  - An optional `AddDevice=-<path>` for every known detector and radar path. Quadlet adds the device only if it exists. #215's `AddDevice` assertions in `test_ai_coprocessor` and `test_radars` change with it.
  - The Coral USB probe matches both `1a6e:089a` and `18d1:9302`. The ID changes after Frigate initializes the device.
- The system info and date/time pages.

## Critical files

**New**
- `tm-control/`: backend, ui, and jobs.
- `script/ansible/roles/tmsetup/tasks/tm-control_setup.yml`.
- `script/ansible/roles/tmsetup/templates/tm-control/`: the unit, job units, and polkit rules.
- `container/revproxy/tm/snippets/auth-viewer.conf.j2` and `auth-admin.conf.j2` (M2).
- `container/revproxy/tm/locations/storefiles.conf.j2` (M1).
- `container/revproxy/tm/locations/` files for tm-control's `/api/`, `/_auth`, and UI root (M2).
- Device tests in `script/devpi/tests` for each milestone.
- `script/ansible/roles/tmsetup/templates/go2rtc.yaml.j2`, which replaces `files/go2rtc.yaml`.
- `script/ansible/roles/tmsetup/files/tm-control`: a symlink to the top-level `tm-control/`, like `files/container`.

**Modified**
- `container/traffic-monitor.pod.j2`: loopback ports and removals.
- `container/revproxy/revproxy.container.j2`: `Network=host` and no `Pod=`. #210's bind mounts stay, and M2 adds the `ui-dist` mount.
- `container/revproxy/tm/locations/*.conf.j2`:
  - `go2rtc.conf` gets the `/feeds/` restrictions and `127.0.0.1:1984`.
  - `cockpit.conf` changes to `127.0.0.1:9090`.
  - `frigate.conf` changes to `127.0.0.1:8971` in M2.
  - Every file includes an auth snippet in M2.
- `container/revproxy/html/index.html.j2`, #210's hand-written page: retired in M2 and replaced by the UI home.
- `script/ansible/roles/tmsetup/vars/main.yml`: tm-control's variables, and new entries in `tmsetup_revproxy_locations`.
- `container/frigate/config/config.yml.j2` and `frigate.env.j2`:
  - The `proxy:`, `tls:`, and `auth:` keys.
  - RTSP credentials in the input path.
  - `FRIGATE_GO2RTC_RTSP_USER`/`FRIGATE_GO2RTC_RTSP_PASSWORD` and the proxy secret.
- `container/frigate/frigate.container.j2` and `container/node-red-tm/node-red-tm.container.j2`: optional `AddDevice=-` lines (M3).
- `container/node-red-tm/data/settings.js`: `adminAuth.tokens`/`tokenHeader`, with no built-in user.
- `container/node-red-tm/node-red-tm.env.j2`: the token and internal secrets. Existing devices get them through `lineinfile`.
- `container/node-red-tm/data/flows.json`: the `/tm-internal/` endpoints and config-error capture.
- `script/ansible/roles/tmsetup/defaults/main.yml`: the Coral USB probe.
- Role tasks and handlers:
  - `script/ansible/roles/tmsetup/tasks/main.yml`
  - `script/ansible/roles/tmsetup/handlers/main.yml`
  - `script/ansible/roles/tmsetup/tasks/start_services.yml`
  - `script/ansible/roles/tmsetup/tasks/revproxy_setup.yml`
  - `script/ansible/roles/tmsetup/tasks/go2rtc_setup.yml`
- `script/tmsetup.sh`: `tm-control` in `_VALID_TAGS`, and printing the setup code.
- `script/requirements-dev`: backend test dependencies.
- Docs:
  - `docs/setup-guide.md`: the no-SSH flow.
  - `docs/configuration/*`.
  - A new user page for the portal.
  - `docs/development/`: tm-control architecture, the module guide, fake mode, and how the UI works.
- `CLAUDE.md`: the architecture update. The `config.yml` watch reload also corrects "read only when the flows start".

## Reuse

- #210's nginx layout:
  - the location files and `tmsetup_revproxy_locations`
  - `tm/snippets/proxy-common.conf` for forwarding and WebSocket headers
  - the pre-restart `nginx -t` check in `revproxy_setup.yml`, which also removes location files that aren't listed
- #214/#215's `tmdev.py` and device-test layers, for every Pi check.
- `tmsetup_detectors` and `tmsetup_radar_paths` (`script/ansible/roles/tmsetup/defaults/main.yml`), plus the probe logic in `tasks/detectors_check.yml`. They're copied into the manifest, and tm-control reuses the same probe commands and paths.
- The Frigate config read-and-save pattern from the `thingsboard` tab (`fetch frigate /api/config/raw`, `validate Frigate config, save and restart`).
- The `init-config` `watch` reload chain for `config.yml`.
- Install patterns:
  - Quadlet and `.build` units.
  - The `templates/container` and `files/container` symlinks.
  - The force-and-backup handling of the `config.yml` and `*.env` templates.
  - The `go2rtc_server.service` host-service pattern.
- The dev venv and pytest layout from `container/node-red-tm/schema/tests`. The same rule applies: synthetic or recorded data only, never device data.

## Risks to verify early

These are spikes in the M1 and M2 plans.

**Node-RED `watch` through the bind mount on atomic rename.** Test on a test Pi:
1. Add a debug node set to "system console" on the `init-config` watch node.
2. Follow the log with `sudo journalctl -u node-red-tm.service -f`.
3. As `tmadmin`, make three comment-only edits of `config.yml`:
   1. an in-place append
   2. an atomic `cp` + `mv`
   3. a second atomic `cp` + `mv`
4. Expect one `event: 'update'` line per edit.
5. Clean up with `sed -i '/# watch-test/d'` and re-run `tmsetup.sh -t node-red-tm`.

**Other risks**
- The Node-RED 5.0.8 editor loads with no login dialog when nginx injects the `tokenHeader`.
- Frigate 0.18.1. 0.18.1's source already confirms the keys and the `auth_secret` env substitution. Still to check on a Pi:
  - the role header is honored with `auth.enabled: false`
  - `logout_url` behaves as expected
- On a device still on Frigate 0.17, `tm-control migrate` edits `config.yml` before Frigate 0.18's own migration rewrites it. The credentialed input must survive that rewrite.
- With `app.modules` trimmed, go2rtc still serves the camera to Frigate and `/feeds/` still plays, and no go2rtc UDP socket opens during playback.
- Safari on iOS and macOS: Frigate live view and Dashboard 2.0 WebSockets work through `auth_request` with the cookie.
- Frigate reads go2rtc RTSP via `host.containers.internal` with credentials. With WebRTC off, MSE fallback works in Frigate and in `/feeds`.
- The OS baseline is Raspberry Pi OS Trixie (Podman 5.4), which `.build` Quadlets and `AddDevice=-` need.
- `rpicam-vid --list-cameras` works while go2rtc holds the camera.
- The PRs this design builds on are still open, and some are drafts. Their code can change before it merges, so each milestone plan starts by re-checking against what merged.

## Verification

**Off-device, in the dev venv (#206; see CLAUDE.md)**
- `python -m pytest tm-control/backend/tests script/tests container/node-red-tm/schema/tests`. `script/tests` is the role-template and task tests M1 adds.
- Ansible `--syntax-check` and `--list-tags`, expecting the `tm-control` tag.
- A Jinja parse of every `*.j2`, including the new ones.
- `python3 -m json.tool` on `flows.json`.
- `bash -n script/tmsetup.sh`.
- UI: `npm ci && npm run build && npm test` in `node:22-alpine`.
- A fake-mode click-through of setup → login → home → status → time, at phone width and at desktop width.

**On a test Pi, never a field device**

Run these through `tmdev.py`:
1. `deploy` the branch.
2. Open a `check` for the PR's test plan.
3. Run `test <host>` for the device tests, which include the new ones each milestone adds.
4. Record the steps a person must do, such as browser and iPhone checks, as `manual` items.

Keep device names and addresses out of the PR.

*M1*
- From another machine, `nmap -p- <pi>` shows only TCP 22, 80, 9090 (if Cockpit is present), and 8554. On the Pi, `ss -ulnp` shows no go2rtc UDP sockets, even while `/feeds/` plays.
- Direct connections to 5000, 1880, and 1984 are refused.
- RTSP without credentials gets 401.
- `/feeds/api/config` returns 403.
- Frigate live view and Dashboard 2.0 work through the proxy.
- A data export from the Dashboard's database page downloads through the proxy.
- Stopping `traffic-monitor.service` leaves the home page up (a disruptive device test).
- The watch-node test passes.

*M2*
- Claiming works with the setup code, and a wrong code is rate-limited.
- `/frigate/` redirects to `/welcome` before the EULA is accepted.
- After logging in on iPhone Safari, Frigate live view and Dashboard 2.0 live updates work.
- The Node-RED editor opens without a second login.
- A viewer gets 403 on `/nr/`, `/feeds/`, and `/storefiles`.
- Logging out also ends Frigate access.
- With tm-control stopped, app paths fail closed with a rescue message, and Cockpit on `:9090` still works.
- The system-password job changes the Linux password. Check by logging in over SSH.
- `reset-admin` works.
- `ss -tlnp` shows tm-control on 127.0.0.1 only.

*M3*
- A healthy unit is all green.
- Unplugging a radar or detector fails the right layer, with the right explanation.
- Re-plugging it, re-scanning, and restarting brings it back.
- An in-use Coral USB (`18d1:9302`) shows as present.
- A unit with no accelerator shows a warning for the CPU detector, not an error.
- **Set from this browser**, while offline, matches the device time to the browser.
- A timezone change restarts the containers, and the times shown are correct.
- A renamed Frigate camera trips the contract check.
