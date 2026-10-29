# tm-control M3 (Status and System) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show an operator, with no SSH, whether the device is healthy and why not; let an admin restart a service, set the date and time, and reboot; and give them a diagnostics text to paste into a support request.

**Architecture:**
- The status page is a list of **checks**, each `ok`, `warn`, `error`, or `unknown` with a one-line detail and, where one exists, a fix (a restart button, a re-scan, a link, or a hint). Each backend module declares its check groups; `core/checks.py` runs them with a per-check timeout, never raises, caches the report for a few seconds, and `GET /api/v1/status` returns it. The UI polls it every 10 seconds while the page is visible.
- New adapters read live state the way the device tests do: `lsusb`, `lspci -nn`, `/dev` and `/sys` paths, the rendered Quadlet units' `AddDevice=` lines, `systemctl show`, `timedatectl show`, Frigate's `/api/config` and `/api/stats` on `127.0.0.1:5000`, go2rtc's `/api/streams` on `127.0.0.1:1984`, and a new Node-RED endpoint `GET /tm-internal/status` on `127.0.0.1:1880`, which reports the config-load errors, the tmdb schema version, and the radars' state.
- Actions use polkit directly, as M2's unit restarts do: `systemctl restart` for the listed units, `timedatectl` for time, timezone, and NTP, and `systemctl reboot` / `systemctl poweroff` through logind. The polkit allowlist gains those action ids. No new root job: nothing in M3 needs root beyond what polkit grants, so the job runner and its polling UI stay as M2 left them.
- The UI gains three pages, Status, Device, and Date and time, a health line on the home page's device card, and one shared component, `CheckList`.

**Tech Stack:** As M2: Ansible (tmsetup role), Podman Quadlet, nginx 1.31.0, Frigate 0.18.1, Node-RED 5.0.8, Python 3.11+ (FastAPI 0.162.0, pydantic 2.14.1), pytest, Node 22 (Vue 3, Vuetify 3, Vite, TypeScript, Pinia, vue-router, openapi-typescript, Vitest). M3 adds no runtime dependency: HTTP reads use `urllib.request`, the MQTT probe is a hand-built CONNECT packet, and time parsing is `datetime`.

**Spec:** `design/specs/2026-10-02-tm-control-platform-design.md`, sections "Decisions → Privilege", "tm-control backend" (Modules, Privilege, API), "Integrations" (Node-RED state, Frigate, go2rtc, Hardware changes), "UI", "v1 scope" items 2 to 5, "Milestones → M3", and "Verification → M3". Read it with this plan. The M2 plan, `design/plans/2026-10-27-tm-control-m2-core-and-login.md`, shows the patterns this plan extends: its Tasks 2 (module and app factory), 5 (adapters and the command runner), 6 (install tasks and polkit), 7 (nginx), 9 (flows and env keys), 10 (UI modules), 11 (docs), and 12 (device tests and the Pi plan).

**Status:** written 2026-10-28 against `feature/tm-control-core-login/201` at `24000c5` (PR #261, M2, which already contains `dev` at `469b575`, the #260 merge). The maintainer approved all 19 decisions below on 2026-10-28. Implementation started the same day on `feature/tm-control-status-system/201`, branched from #261's head `24000c5` while #261 is open, which carries this file at `design/plans/2026-10-28-tm-control-m3-status-and-system.md`. Task 0 found #261 still open at `24000c5` and no other open PR, the off-device baseline at 742 passed and 1 skipped, and every pinned version current (checked 2026-10-28). Tasks 0–10 are implemented on this branch, and each task was reviewed. Task 11's device tests ran on a bench unit on 2026-10-28: an upgrade from M2 with a full `tmsetup.sh` run, single-tag runs of `node-red-tm` and `tm-control`, and the whole suite with `--disruptive` (155 passed, 4 skipped for live traffic and a missing environmental monitor). The fixes that run and the maintainer's checks on the unit needed are in the list below. Four Step 6 items that need a person remain (Set from this browser offline, the Dashboard's times after a time zone change, Diagnostics Copy on a phone, the Reboot and Shut down confirmation dialogs), then the PR.

**Changed during implementation** (where a task's text below differs, this list wins; each item is in the code and tested):
- The bench-Pi spike (Task 1) confirmed the seven polkit action ids. It also found that the media devices' model names are in `/sys/bus/media/devices/mediaN/model` (there's no `/sys/class/media`), that `timedatectl show` prints its times as local strings with no `--timestamp=` option, that `ss` falls back to `/proc/net` when the sandbox refuses netlink, and that `vcgencmd` without the `video` group fails with `Can't open device file: /dev/vcio_gencmd`.
- The status report runs all groups at the same time, and checks share reads through a per-report memo, `Context.probe(key, fn)`, so a hung app costs about one timeout and Frigate's config, Node-RED's status, `config.yml`, and the bus listings are read once per report. Groups appear in `MODULES` order: Services, Apps, Configuration, Hardware, Device, Date and time.
- Every backend task regenerates `openapi.json` and `schema.d.ts`, so each commit's test suite passes.
- The backend tests gain `device_client`, an app built as on a device (fake mode off) with synthetic secrets, so API tests run the real code paths with commands stubbed.
- Restart fixes carry their button text, "Restart <unit title>" (`restart_fix` in `modules/services/units.py`), and a unit that isn't installed reads as an error with a hint rather than "stopped". `GET /services` reads `ActiveEnterTimestamp` with `--timestamp=unix`; a unit's `NRestarts` warning says "restarted N times after failures" (systemd resets the count on a manual start, so not "since boot").
- Diagnostics redaction finds every span in the assembled text and then replaces them, so neither a value nor a `key=value` match can hide the other: each device secret's value (`DEVICE_SECRETS`, kept equal to `tmsetup_secret_names` by a test), the secret-looking values in `node-red-tm.env`, `frigate.env`, and `plate-recognizer.env` (the broker password lives there, and a journal line could print it inside a URL), and the value after `password`, `token`, `secret`, the setup code, and longer names ending in one of them. A journal tail cut by the output cap drops its partial last line.
- Reboot and power-off first ask logind (`CanReboot`, `CanPowerOff`) and answer 409 when it says no, for example while an update holds a shutdown inhibitor. No `-ignore-inhibit` action is granted.
- The disk check shows the code directory only when it's on a different filesystem from `/`.
- Node-RED's `init config defaults` passes `msg` with the ThingsBoard-host error, so it reaches the status page; the lat/lon/bearing errors stay log-only (they flag the shipped empty defaults, and tm-control's Location check validates those keys). nginx also denies `/nr/tm-internal/` in any letter case, because Node-RED matches paths case-insensitively.
- `lsusb` can't start inside the service's sandbox (libusb needs a netlink socket), so the Coral USB check reads the ids from `/sys/bus/usb/devices`. Radar names come from `node-red-tm.env`'s `TM_RADAR_SERIAL_PORT_0N` lines, with the template's index mapping as the fallback. The Hailo check is titled "Hailo accelerator" because the probe matches Hailo-8 and Hailo-8L.
- `POST /time` changes the time first, then NTP, then the time zone last, so nothing can fail after a zone change and its container restart is always queued. When NTP is on but has no time source, a time from the browser turns NTP off just long enough to set the clock and then back on, so the device resyncs once it's online. `{"ntp": false}` with a time turns NTP off and sets it.
- The command runner can pass environment variables (`TZ=UTC` for `timedatectl set-time`).
- The Status page's "Checked … ago" counts from when the page received the report, not from the report's own time, because the device's clock may be the thing that's wrong.
- On plain HTTP, when the browser refuses to copy the diagnostics (the click's permission can expire while the file downloads), the Device page shows the text in a read-only box, already selected, to copy by hand. After an accepted reboot the page says it will stop answering, and the app's "device didn't answer" screen appears on the next action.
- A restart from the Status page is queued after the 202 is sent, so restarting the web proxy can't cut off its own answer; a restart that then fails is logged, not a 500 (Task 3's `test_restart_failure_is_an_api_error` no longer applies). When the browser's time zone isn't on the device's list, "Set from this browser" still sets the time and reports the zone as unknown (`timezone_unknown`), with no container restart. The reboot and power-off 409 also covers the control app not being allowed and points to the diagnostics, and a failed logind question is logged with its exit status.
- The bench-Pi run found two things to fix. M2's `test_proxied_locations_respond` counted the new `/nr/tm-internal/` deny location as a broken app, so it joins `HIDDEN_LOCATIONS`, whose own test checks the 404. The radar-names check's ok detail now says the radars in `config.yml` are named as in `node-red-tm.env`. The run also showed that moving the clock ahead by more than Frigate's 20-second no-frames watchdog restarts Frigate's camera feed, so the Cameras check is an error for a minute or two; the Date and time docs say so.
- Saving Frigate's config restarts Frigate: its container exits with SIGTERM (status 143), and systemd restarts it as after a failure, so `NRestarts` counted it and the Services row warned until someone restarted Frigate by hand (found in the bench run's camera-rename check). Units now name the exit status they use to restart themselves (`restarts_itself_with`, Frigate only). When each of the unit's counted restarts this boot followed that status in PID 1's journal (`systemd.automatic_restart_exits`), the row is ok and says Frigate restarted itself. A crash, or a journal that can't be read, still warns. The device test `test_frigate_restarting_itself_stays_ok` restarts Frigate through its own API.
- The bench run's cable pull found a radar bug from before M3: a radar that loses power restarts its clock at zero, and every radar table stores the radar's clock, but Node-RED set that clock only at startup, on a `config.yml` change, and hourly. For up to an hour after a re-plug, radar rows had 1970 times, and events got no speed. The port-status node that M3 added now sends an enabled radar the time when its port opens, through a 5-second delay and a change node that reads the time after the delay. The delay is needed because, while the port opens, Linux echoes the start of the radar's greeting (`{"USB" : "USB In`) back to the radar, and the radar drops a `C=` command that follows within a moment; a USB capture on the bench unit showed both. A camera rename also needs Frigate's Save & Restart, which the config.yml docs now say.

**Where M2 left things (from the M2 plan's Status and PR #261):**
- `tm-control.service` runs as the code owner with `SupplementaryGroups=systemd-journal`, no `ReadWritePaths=`, state in `/var/lib/tm-control`, and requests in `/run/tm-control`. polkit allows start, stop, and restart of the seven listed units and nothing else (`tmsetup_tm_control_polkit` in `vars/main.yml`).
- Modules are `Module(id, router, root_router)` in `modules/__init__.py`; `create_app` mounts them. Endpoints take `current_user` or `require_admin`. Errors are `ApiError(status, code, message)`. Commands go through `adapters/command.run(argv, timeout, max_output)`. `adapters/systemd.py` has `start_unit`, `show_unit`, `journal_entries`, and `journal_lines`.
- The manifest (`core/manifest.py`, `manifest_version: 1`) holds `probes.detectors` (each detector's `dev_path`, `check_exists`, `frigate_type`, `frigate_device`), `probes.radar_paths`, `probes.hevc_device`, `components`, `options`, `revproxy_locations`, and `homepage`.
- The home page's `GET /system/device` returns hostname, serial, version, time, apps, and theme. The UI has `StatusCard`, `ConfirmDialog`, and `EulaText`; `router.ts` guards by claim, session, EULA, and `adminOnly`; `stores/session.ts` is the only store.
- Jobs are polled (`GET /jobs/{id}`), one job (`system-password`). The UI's response types are hand-written (#262).
- Device tests log in with the inventory's `tm_control_login` and have `admin_session`, `viewer_session`, `tm_login`, `pi_json`, `read_root_file`, `find_hevc_decoder`, `frigate_host_devices`, and `request_from_this_machine`.
- `tmsetup_secret_names` has four secrets. New `.env` keys reach existing devices with `lineinfile` (`TM_NR_TOKEN_KEY` in `node-red-tm_setup.yml`).
- Node-RED's `init config defaults` function reports config problems with `node.error`, which only the editor's debug panel and the journal show. The `system` tab collects OS release, Frigate version, the time zone, and metrics for ThingsBoard. `config.yml.j2` still has `time.timezone` and `time.npt_set`; the flows read `npt_set` once (normalizing it) and `timezone` never (#251, closed).

**Open PRs surveyed on 2026-10-28:** only #261 (M2, `dev ← feature/tm-control-core-login/201`, 30 commits, not a draft, unmerged). M3 touches the same backend, UI, role, nginx, and flows files, so it branches from #261's branch and its PR targets that branch. When #261 merges with a merge commit, the M3 PR is retargeted to `dev` (GitHub rebases the stack; re-check the device evidence at the merged SHA). Open issues M3 touches: #217 (Coral USB's second id; fixed here), #255 (`camera_radar` names a missing radar; M3 adds the contract check, the flows fix stays open), #243 (camera-only devices store no direction; the zone check names it). #246 and #248 (time zone and day boundary in the dashboards) stay open and are not M3; the time page's "correct times" check in the Pi plan reads the Frigate and Node-RED logs, not the dashboards.

**Decisions made in this plan (2026-10-28).** These fill gaps in the spec or deviate from its text. Each gives the options with their size (S/M/L) and what the maintainer would own afterwards. The maintainer approved all 19 as recommended on 2026-10-28, with decision 11 amended first (viewers see the Date and time page read-only):

1. **Node-RED state comes from `http in` endpoints under `/tm-internal/`, as the spec says, with one new device secret.** Options:
   - *(a) The spec's endpoints (chosen).* `GET /tm-internal/status` in `flows.json`, checked against `X-TM-Internal-Token`; the token is a fifth device secret, `node_red_internal_token`, written to `node-red-tm.env` as `TM_INTERNAL_TOKEN` (template plus `lineinfile`, like `TM_NR_TOKEN_KEY`) and read by tm-control from the secrets directory; nginx answers 404 for `/nr/tm-internal/`. **M.** Owns: about a dozen flow nodes, one secret, one env key, one nginx line, one adapter. Later features (config edits, the explicit reload) add endpoints the same way.
   - *(b) Node-RED writes a status file* every 10 seconds under `/data`, and tm-control reads it by mtime. **S.** Owns: a timer and a file node, staleness logic in tm-control, and a write to the microSD card every 10 seconds. No endpoint for later reloads.
   - *(c) No Node-RED change:* tm-control reads `config.yml` and the database header itself. **S.** Misses the config-load errors and the radars' live state, which are the point of the check.
2. **The tmdb schema check compares Node-RED's `PRAGMA user_version` with the newest migration file.** Options:
   - *(a) Node-RED reports `user_version` (chosen)* through `/tm-internal/status`, read on its own connection, so no second connection ever takes a read lock. tm-control compares it with the highest `NNNN_*.sql` in `{{ tmsetup_codedir }}/node-red-tm/schema/migrations/`, which it can read. When the schema is behind, the check is an **error** with the hint `sudo journalctl -u node-red-tm | grep tmdb-migrate`. When Node-RED doesn't answer, it's `unknown` (and the Node-RED check is already an error). **S.** Owns: one sqlite node in the flows and ten lines of Python. Drift (`tmdb_migrate.py --check`'s `DRIFT`) isn't checked; the spec asks for "behind" only.
   - *(b) tm-control runs `tmdb_migrate.py --check`.* **S**, but it opens a second connection whose read lock can fail a Node-RED write (no busy timeout), and it reports drift text meant for developers.
   - *(c) tm-control reads bytes 60 to 63 of `tmdb.sqlite`* (the header's `user_version`) with no SQLite connection. **S**, works with Node-RED down, but reads a stale header while a WAL holds the newest change, and it's a trick a maintainer has to remember.
3. **Optional detectors and radars keep reaching the containers through install-time `AddDevice=` lines; M3 reports, the detector feature fixes.** The spec's open M3 question. Options:
   - *(a) Keep install-time detection (chosen).* The hardware checks compare what's on the host with what the rendered `.container` units pass, and a mismatch reads "present on the host but not passed to Frigate; re-run `tmsetup.sh -t detectors -t frigate`" (or `-t node-red-tm` for a radar). The spec's "Install support" job ships with the detector feature spec. **S.** Owns nothing new. Known limit, unchanged from today: a radar unplugged at boot keeps `node-red-tm.service` from starting until it's plugged in and restarted, which the status page now shows with a restart button.
   - *(b) A udev rule per device kind* with a stable symlink and a device unit the container waits for, as #242 did for the HEVC decoder. **L.** Owns: a rule per kind (USB serial by port path, Coral USB by vendor id, PCIe by driver), new device names that the radar env names must keep mapping to, boot ordering, and a migration for existing devices.
   - *(c) A udev-triggered root job* that re-renders and restarts the container when a device appears. **M.** Owns: a job that restarts Node-RED whenever a radar is re-plugged, losing the events in that window, and surprising behavior to document.
4. **"Passed to the container" reads the rendered Quadlet unit, not `podman inspect`.** The spec compares with `podman inspect`, which needs root for rootful containers. tm-control instead reads `/etc/containers/systemd/frigate.container` and `node-red-tm.container` (root-owned, world-readable) for `AddDevice=` lines, and checks that the unit is active. That's the install's contract, and it's what the device tests `test_frigate_gets_the_device` and `test_node_red_gets_the_radars` already read. The HEVC decoder's "present" layer keeps the spec's `readlink -f` versus a `/sys/class/media` scan. **S.**
5. **tm-control never runs the manifest's `check_exists` shell strings.** They're the installer's. tm-control has its own probe table keyed by detector kind: `edgetpu_usb` → `lsusb` and `1a6e:089a|18d1:9302` (#217), `edgetpu_pci` → `lspci -nn` and `coral|1ac1:089a`, `hailo8l` → `lspci -nn` and `hailo`, with the kernel modules `apex` and `hailo_pci` for the driver layer. A kind the table doesn't know gets an `unknown` check. The manifest's `dev_path`, `frigate_type`, and `frigate_device` are used as they are, and `manifest_version` stays 1. The role's `edgetpu_usb.check_exists` in `defaults/main.yml` gets the second id too, which closes #217. **S.**
6. **No SSE job log in M3.** The spec says the SSE stream comes with M3's longer jobs, but M3 has no root job: restarts, time, and reboot go through polkit, and diagnostics is a synchronous download. Options:
   - *(a) Defer SSE (chosen)* to the first feature with a job that runs longer than a few seconds (TM update, "Install support"). The job endpoint and the UI's 2-second polling stay. **0.** The spec's API paragraph gets a one-line correction.
   - *(b) Ship `GET /jobs/{id}/events` now* (a `StreamingResponse` of `text/event-stream` with 15-second keepalives; `/api/` already has `proxy_buffering off`; `EventSource` in the UI with a polling fallback). **M.** Owns: a streaming code path and its tests, exercised by nothing until a later feature.
7. **Date and time writes go through polkit, not a root job.** `timedatectl set-time`, `set-timezone`, and `set-ntp` run as the code owner with the three `org.freedesktop.timedate1.*` action ids added to `tmsetup_tm_control_polkit`. A timezone change restarts `traffic-monitor.service` (the pod: Frigate, Node-RED, and Plate Recognizer bind-mount `/etc/localtime`, which `set-timezone` replaces, so the running containers keep the old zone file) and `revproxy.service`, after the response is sent (FastAPI `BackgroundTasks`), and calls `time.tzset()` so tm-control's own clock display follows. Node-RED re-sends the radar time on its restart, as the spec expects. **S.**
8. **"Set from this browser" keeps NTP when NTP already has the time.** The spec says it turns NTP off first if needed. Rule: the UI sends the browser's time and IANA time zone; if `NTPSynchronized=yes`, the backend sets only the time zone and reports that the time came from NTP; otherwise it turns NTP off, sets the time, then the time zone. The time zone must be one of `timedatectl list-timezones`; the time must be within 20 years of 2026-01-01 (a floor the release updates). **S.**
9. **Reboot and shut down are both offered, with a confirmation each.** polkit gets `org.freedesktop.login1.reboot`, `reboot-multiple-sessions`, `power-off`, and `power-off-multiple-sessions` (logind asks for the `-multiple-sessions` id when someone is logged in over SSH or Cockpit). Shut down's confirmation says the device must then be unplugged and plugged back in. Options were reboot only (**S**) or both (**S**); both, because the spec grants power-off and an operator packing up a temporary deployment should shut down before pulling power. **S.**
10. **Restart covers the TM units in the polkit list, not tm-control itself.** `POST /services/{unit}/restart` accepts `traffic-monitor.service` (the pod), `frigate.service`, `node-red-tm.service`, `plate-recognizer.service` (only when the manifest says it's installed), `go2rtc_server.service`, and `revproxy.service`. tm-control restarting itself is Cockpit's job (`/system/`) or the rescue console's, and it isn't in the polkit list. Restarting revproxy drops the browser's connection for a second; the UI's existing "device didn't answer" handling covers it. **S.**
11. **Viewers see Status, Device, and Date and time read-only; diagnostics is admin-only.** The spec doesn't say who sees status. A viewer is often the person standing at the device, so they see every check and its hint, and the two clocks with their difference, the time zone, and whether the device keeps time from the internet, but no buttons, no time zone picker, and no NTP switch. `GET /status`, `GET /services`, `GET /system/info`, and `GET /time` take `current_user`; every POST and `GET /system/diagnostics` (it holds journal lines) take `require_admin`. (Amended 2026-10-28 at the maintainer's request: the Date and time page was admin-only.) **S.**
12. **The UI's routes are `/status`, `/device`, and `/time`.** Not `/system`: nginx proxies `/system/` to Cockpit, so a reload at `/system/` would open Cockpit. **S.**
13. **Diagnostics is a text download, with secrets stripped by value.** `GET /system/diagnostics` returns `text/plain` as an attachment: the device info, the status report, the services, the time state, the manifest, and the last 50 journal lines of each TM unit and tm-control. Before sending, every device secret's value (the five secrets, read from the secrets directory) is replaced with `<redacted>`, and so is anything matching `(password|passwd|token|secret|access_token)\s*[=:]\s*\S+`. The UI offers "Download" and "Copy"; on plain HTTP `navigator.clipboard` is unavailable, so Copy selects a textarea and uses `document.execCommand("copy")`. **S.**
14. **The `time:` section leaves `config.yml.j2`, and the flow tolerates its absence.** #251's time half (the 2026-10-26 refresh design assigned it to M3): `tmsetup_timezone` still sets the OS time zone at install, the Date and time page changes it afterwards, and a second time zone in `config.yml` would only confuse. New installs and `-f` runs get a template without `time:`; existing devices keep the keys, which nothing reads. `init config defaults` stops touching `msg.payload.time` (today it would throw on a missing key). The configuration docs drop the keys. **S.**
15. **The manifest gains no driver versions.** The spec's M2 decision 12 left "driver and firmware versions" for M3's hardware checks. The driver layer needs only the device path and the kernel module (`/proc/modules`), and the Device page shows the component versions the manifest already has, so nothing is added. **0.**
16. **The MQTT broker-login check is part of the apps group.** From the 2026-10-26 refresh (accepted risk 1): when `ss -ltn` shows 1883 bound to `0.0.0.0` or `[::]`, tm-control sends one MQTT CONNECT without credentials to `127.0.0.1:1883` and expects a CONNACK that refuses it (return code 4 or 5); an accepted connection is an **error** ("the broker accepts clients without a login while port 1883 is open to the network"). When 1883 is on loopback only, the check is `ok` with "broker on this device only". **S**, about 30 lines, no MQTT library.
17. **Device tests keep their own probes and add one test that `/api/v1/status` agrees with them.** The spec's open question: asserting only against tm-control would make the tests depend on it. The new test logs in, reads the report, and expects the inventory's detector, radars, services, and schema checks to be `ok` (or the CPU-detector `warn` on a unit with no accelerator). The existing probe tests stay as the independent view. **S.**
18. **`tm-control.service` gains `SupplementaryGroups=video`** for `vcgencmd get_throttled` (`/dev/vcio`), as the spec's Privilege section foresaw. `ReadWritePaths=` stays empty: M3 reads `config.yml` and never writes it. **S.**
19. **The new routers declare response models.** #262 asks for this on the M2 routers; M3's new endpoints start that way, so the UI's types for them come from `openapi.json`. #262 stays open for the M2 endpoints. **S.**

## Global Constraints

**What M3 changes and what it leaves.** M3 adds reads and three kinds of action (restart, time, reboot). Login, claim, sessions, nginx's auth snippets, Frigate's proxy auth, the Node-RED editor token, the pod's ports, and the job runner stay as M2 left them. No config file is written by tm-control in M3.

**Python**
- Python 3.11 and newer; no new runtime dependency (`requirements.txt` unchanged). Pins as M2: fastapi 0.162.0, uvicorn 0.54.0, pydantic 2.14.1, itsdangerous 2.2.0, argon2-cffi 25.1.0, ruamel.yaml 0.19.1.
- Every command runs through `adapters/command.run` with an argv list, a timeout of at most 4 seconds for a probe, and an output cap. HTTP reads use `urllib.request.urlopen` with a 3-second timeout on `127.0.0.1` only.
- **Checks never raise.** A check function that raises or exceeds its timeout becomes an `unknown` check whose detail names the exception class or the timeout, never a traceback or a command's output.
- Nothing M3 logs or returns holds a secret: the diagnostics text is redacted by value, and journal lines are only ever returned after redaction.

**Who may do what**
- Every GET in M3 takes `current_user`. Every POST, and `GET /system/diagnostics`, takes `require_admin`. Each admin action records an `Audit` row (`services.restart`, `time.set`, `system.reboot`, `system.power_off`, `status.rescan`).
- Privilege comes only from the polkit list in `vars/main.yml`: the units for restart, the `timedate1` actions for time, the `login1` actions for reboot and power-off. tm-control still never uses sudo and has no root job in M3.
- `tm-control.service` runs with `SupplementaryGroups=systemd-journal video` and no `ReadWritePaths=`.

**API**
- JSON under `/api/v1/`; errors are `{"error": {"code", "message", "detail"}}`. New codes: none; M3 uses `validation`, `forbidden`, `not_found`, `conflict`, and `internal`.
- Check statuses are exactly `ok`, `warn`, `error`, `unknown`. Fix kinds are exactly `restart`, `rescan`, `link`, `hint`.
- The status report is cached for 5 seconds; `POST /status/rescan` bypasses the cache.

**Conventions** (as M2's Global Constraints): Ansible task names `TMSetup - <Component> - <Action>`, FQCNs, `become: true` per task, `_register` suffix, 2-space YAML; fixed shared values in `vars/main.yml`, operator-tunable in `defaults/main.yml`; tests use synthetic data only, with unique test module basenames; docs follow `docs/development/contributing.md` and pass `mkdocs build --strict`; `flows.json` is re-serialized with `json.dumps(flows, indent=4, ensure_ascii=False)`; one commit per task ending with CLAUDE.md's trailer block (ask for the interface and effort if unknown); Pi checks run through `script/devpi/tmdev.py`, and device names, addresses, and secrets stay out of commits and PR text.

**Running the checks**
- Repo root, dev venv: `python -m pytest tm-control/backend/tests`, `python -m pytest script/tests`, `python -m pytest container/node-red-tm/schema/tests`; `python3 -m json.tool container/node-red-tm/data/flows.json >/dev/null`.
- Ansible with `</dev/null`, output to a file.
- UI: `podman run --rm -v "$PWD/tm-control/ui:/ui:Z" -w /ui docker.io/library/node:22.23.4-alpine sh -c 'npm ci && npm run build && npm test'`.
- After an API change: `PYTHONPATH=tm-control/backend python -m tm_control dump-openapi > tm-control/ui/src/api/openapi.json && (cd tm-control/ui && npm run api:generate)`.

## Review Focus

The failures most likely to bite a person using a device, each pinned by a test in the task that owns it:

1. **A probe that hangs takes the status page with it.** A wedged USB bus, a Frigate that accepts the connection and never answers, or a slow `lspci` must leave the page rendering with that one check `unknown` within 5 seconds. Tests: Task 2 (`test_a_check_that_hangs_becomes_unknown_within_the_timeout`, `test_a_check_that_raises_becomes_unknown_without_a_traceback`); Task 6 (Frigate adapter timeout).
2. **A restart, time, or reboot request from a viewer, or for a unit not on the list.** Every action must answer 403 for a viewer and 404 for an unknown unit, and polkit must refuse anything the API gets wrong. Tests: Task 3 (`test_restart_refuses_a_unit_off_the_list`, `test_viewer_cannot_restart`), Task 8, Task 4, Task 11's device test `test_polkit_allows_only_the_listed_actions`.
3. **"Set from this browser" with a bad time zone or a wrong clock.** A time zone must come from `timedatectl list-timezones`; a time before 2026-01-01 or more than 20 years after it is refused; when NTP has the time, the device's clock isn't overwritten with the phone's. Tests: Task 8.
4. **A secret in the diagnostics text.** The journal of `node-red-tm` can print the broker password on a connection error, and the installer's log prints the setup code. Every secret value and every `password=` style line must be redacted before the text leaves the device. Tests: Task 4 (`test_diagnostics_never_contains_a_secret_value`, one case per secret and per pattern).
5. **Node-RED's internal endpoint reached through nginx or without the token.** `/nr/tm-internal/status` must be 404 even for an admin, and `127.0.0.1:1880/tm-internal/status` must be 401 without the right header and refuse everything when `TM_INTERNAL_TOKEN` is unset. Tests: Task 5 (flows and nginx render tests), Task 11 (device tests from this machine and on the Pi).
6. **A device whose migration failed.** The schema check must show an error with the journal hint while Node-RED runs on an empty database. Tests: Task 6 (recorded Node-RED status with `schema_version: 0`), Task 11 (disruptive, `pii_free` only: `test_schema_behind_shows_an_error`).
7. **A time zone change that the containers don't see.** After `set-timezone`, Frigate's and Node-RED's logs must show the new zone, which means the pod restarted. Tests: Task 8 (the restart is queued after a zone change and not after an NTP toggle), Task 11 (disruptive `test_timezone_change_restarts_the_containers`).

---

### Task 0: Base branch and a re-check against #261

**Files:**
- Create: branch `feature/tm-control-status-system/201` from `origin/feature/tm-control-core-login/201`

- [ ] **Step 1: Branch and confirm the base**

```bash
git fetch origin && git switch -c feature/tm-control-status-system/201 origin/feature/tm-control-core-login/201
git log --oneline -1    # expect 24000c5 or a later commit of #261
gh pr list -R glossyio/traffic-monitor --state open --json number,title,headRefName,baseRefName --jq '.[] | "\(.number) [\(.baseRefName) <- \(.headRefName)] \(.title)"'
```

If #261 has merged, branch from `origin/dev` at its merge commit instead and target `dev`. If #261 gained commits after `24000c5`, re-read the files this plan modifies (listed per task) and note the changes under a new "Status" paragraph. If a new PR touches `tm-control/`, `container/node-red-tm/data/flows.json`, `container/revproxy/`, or the role's `tasks/tm-control_service.yml` or `vars/main.yml`, stop and decide the base with the maintainer.

- [ ] **Step 2: Run the baseline checks**

```bash
python -m pytest tm-control/backend/tests script/tests container/node-red-tm/schema/tests -q
python3 -m json.tool container/node-red-tm/data/flows.json >/dev/null && bash -n script/tmsetup.sh
```
Expected: all pass (742 passed, 1 skipped at `2da617a`).

- [ ] **Step 3: Confirm the pins**

Check PyPI for the six runtime pins and `httpx==0.28.1`, and Docker Hub for `node:22.23.4-alpine`. M3 adds no dependency; if a pin moved, update M2's constraint text and the Containerfile, and record the check date here.

- [ ] **Step 4: Put the public copy of this plan on the branch**

Put this file at `design/plans/2026-10-28-tm-control-m3-status-and-system.md`, with the Status line saying the decisions were approved and where the plan lives, and check that it names no devices, addresses, or example projects. Commit it as the branch's first commit:

```bash
git add design/plans/2026-10-28-tm-control-m3-status-and-system.md
git commit -m "Add the tm-control M3 (status and system) implementation plan" -m "<trailer block>"
```

---

### Task 1: Spike on the bench Pi: polkit for timedate1 and login1 from the sandboxed service

Non-disruptive. It proves, before any code depends on it, that the code owner can set time properties and is allowed to reboot through logind, with the rules M3 will install. `T` is `.venv/bin/python script/devpi/tmdev.py`.

**Files:**
- Create: `tm-control/backend/tests/spikes/README.md` (append an "M3" section: what was tried and the result; no code)
- Scratch: `$CLAUDE_JOB_DIR/tmp/spike-polkit/50-traffic-monitor-m3.rules`

- [ ] **Step 1: Install a temporary rule with the M3 action ids and probe from the code owner**

Write the scratch rule, which allows the code owner (`tmadmin` unless the inventory says otherwise) the seven action ids from decisions 7 and 9, and copy it to the Pi as `/etc/polkit-1/rules.d/49-tm-m3-spike.rules` (a lower number than 50, so it's read first; polkitd reloads on its own). Then:

```bash
$T run <host> -- "sudo runuser -u tmadmin -- timedatectl show"
$T run <host> -- "sudo runuser -u tmadmin -- timedatectl set-ntp \$(timedatectl show -p NTP --value | tr A-Z a-z); echo rc=\$?"
$T run <host> -- "sudo runuser -u tmadmin -- busctl call org.freedesktop.login1 /org/freedesktop/login1 org.freedesktop.login1.Manager CanReboot"
$T run <host> -- "sudo runuser -u tmadmin -- busctl call org.freedesktop.login1 /org/freedesktop/login1 org.freedesktop.login1.Manager CanPowerOff"
$T run <host> -- "sudo systemd-run --uid=tmadmin -p NoNewPrivileges=yes -p ProtectSystem=strict -p PrivateTmp=yes --wait --pipe timedatectl set-ntp \$(timedatectl show -p NTP --value | tr A-Z a-z); echo rc=\$?"
$T run <host> -- "sudo rm /etc/polkit-1/rules.d/49-tm-m3-spike.rules"
```

Expected: `set-ntp` with the current value exits 0 both as a plain process and under the sandbox options; `CanReboot` and `CanPowerOff` print `s "yes"` (with an SSH session open, logind evaluates the `-multiple-sessions` id, so `yes` here proves both ids are allowed). If either prints `s "challenge"` or `s "no"`, the rule's action list is incomplete; fix the list in Task 4 before relying on it. Nothing is rebooted.

- [ ] **Step 2: Check that `vcgencmd` works for the code owner with the video group**

```bash
$T run <host> -- "sudo runuser -u tmadmin -- vcgencmd get_throttled; echo rc=\$?"
$T run <host> -- "sudo systemd-run --uid=tmadmin -p SupplementaryGroups=video -p NoNewPrivileges=yes --wait --pipe vcgencmd get_throttled; echo rc=\$?"
```
Expected: the first fails (no `/dev/vcio` access), the second prints `throttled=0x...` with rc 0. If the second fails too, Task 4's throttling check falls back to `/sys/devices/platform/soc/*firmware*/get_throttled` when it exists, and `unknown` otherwise.

- [ ] **Step 3: Record and commit**

Append the results (date, OS version from `/etc/os-release`, the commands' relevant output lines) to the spikes README.

```bash
git add tm-control/backend/tests/spikes/README.md
git commit -m "Record the polkit spike for tm-control's time and reboot actions" -m "<trailer block>"
```

---

### Task 2: Check core: the check model, groups per module, the runner with timeouts, the cache, and `GET /status`

**Files:**
- Create: `tm-control/backend/tm_control/core/checks.py`
- Create: `tm-control/backend/tm_control/modules/status/__init__.py`, `modules/status/router.py`
- Modify: `tm-control/backend/tm_control/modules/__init__.py` (`Module` gains `check_groups`; register `status`)
- Modify: `tm-control/backend/tm_control/app.py` (`app.state.status = StatusCache(...)`)
- Modify: `tm-control/backend/tm_control/fake.py` (fake check groups from a fixture)
- Create: `tm-control/backend/tests/fixtures/status_fake.json` (one group per later task with every status represented)
- Test: `tm-control/backend/tests/test_checks_core.py`, `tm-control/backend/tests/test_api_status.py`

**Interfaces:**
- Produces, in `core/checks.py`:
  - `Status = Literal["ok", "warn", "error", "unknown"]`
  - `class Fix(BaseModel)`: `kind: Literal["restart", "rescan", "link", "hint"]`, `text: str`, `unit: str | None = None`, `href: str | None = None`
  - `class Check(BaseModel)`: `id: str`, `title: str`, `status: Status`, `detail: str`, `fix: Fix | None = None`
  - `class Group(BaseModel)`: `id: str`, `title: str`, `checks: list[Check]`
  - `class Report(BaseModel)`: `generated_at: str`, `summary: dict[Status, int]`, `groups: list[Group]`
  - `class Context`: `settings`, `manifest`, `secrets`, `probes` (a per-report dict for memoized command output, so `lsusb` runs once per report)
  - `CheckFn = Callable[[Context], list[Check]]`; `class CheckGroup(NamedTuple)`: `id`, `title`, `fns: list[CheckFn]`
  - `run_group(group: CheckGroup, context: Context, timeout: float = 5.0) -> Group`: each fn in a worker thread; a fn that raises or times out yields one `Check(id=f"{group.id}.{fn.__name__}", status="unknown", detail=...)`.
  - `class StatusCache`: `__init__(self, groups: list[CheckGroup], context_factory, ttl: float = 5.0)`; `report(force: bool = False) -> Report`, under a lock, reusing a report younger than `ttl` unless `force`.
- Produces, in `modules/__init__.py`: `Module(id, router, root_router=None, check_groups: tuple[CheckGroup, ...] = ())`.
- Produces: `GET /api/v1/status` → `Report` (any user); `POST /api/v1/status/rescan` → `Report` (admin, audited `status.rescan`).
- Later tasks add their `CheckGroup`s to their modules; the status module collects `[g for m in MODULES for g in m.check_groups]`.

- [ ] **Step 1: Write the failing core tests**

`test_checks_core.py`:
- `test_run_group_collects_each_functions_checks`: two fns returning one check each → a `Group` with both, in order.
- `test_a_check_that_raises_becomes_unknown_without_a_traceback`: a fn raising `RuntimeError("secret-value")` → one check, `status == "unknown"`, `detail == "The check failed (RuntimeError)."`, and `"secret-value" not in detail`.
- `test_a_check_that_hangs_becomes_unknown_within_the_timeout`: a fn sleeping 3 s with `timeout=0.2` → `unknown`, `detail == "The check didn't finish within 0.2 seconds."`, and `run_group` returns in under 1 s.
- `test_summary_counts_every_status`: a report from groups with 2 ok, 1 warn, 1 error, 1 unknown → `summary == {"ok": 2, "warn": 1, "error": 1, "unknown": 1}`.
- `test_cache_reuses_a_fresh_report_and_force_bypasses_it`: a counting fn; two `report()` calls within the ttl run it once; `report(force=True)` runs it again.
- `test_probes_memo_is_per_report`: two fns reading `context.probes.setdefault("lsusb", counter())` share one call per report.

`test_api_status.py`:
- `test_status_needs_a_session`: `GET /api/v1/status` → 401.
- `test_status_report_for_a_viewer_and_an_admin`: both get 200 with `groups`, `summary`, `generated_at`; the fake fixture's groups come back as is.
- `test_rescan_is_admin_only_and_audited`: viewer → 403; admin → 200 and an `audit` row with action `status.rescan`.
- `test_openapi_declares_the_report_model`: `openapi.json` has the `Report` schema under the status path's 200 response.

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tm-control/backend/tests/test_checks_core.py tm-control/backend/tests/test_api_status.py -q`
Expected: FAIL with `ModuleNotFoundError: tm_control.core.checks`.

- [ ] **Step 3: Implement `core/checks.py`, the `Module` field, the status module, the fake groups, and the app wiring**

`run_group` uses one `ThreadPoolExecutor` per call and `future.result(timeout=...)`; a timed-out worker is left to finish on its own (the command runner's own timeout bounds it). Fake mode's `check_groups` come from `fixtures/status_fake.json` loaded into `Group` objects, so the UI click-through shows every status and fix kind. The context factory reads `app.state.settings`, `manifest`, and `secrets`.

- [ ] **Step 4: Run the tests**

Run: `python -m pytest tm-control/backend/tests -q`
Expected: PASS, including the existing suites.

- [ ] **Step 5: Commit**

```bash
git add tm-control/backend
git commit -m "Add the status check core: checks, groups per module, a runner with timeouts, and GET /status" -m "<trailer block>"
```

---

### Task 3: Services: unit state, restart through polkit, and the services check group

**Files:**
- Modify: `tm-control/backend/tm_control/adapters/systemd.py` (`restart_unit`, `show_units`)
- Create: `tm-control/backend/tm_control/modules/services/__init__.py`, `modules/services/router.py`, `modules/services/units.py`, `modules/services/checks.py`
- Modify: `tm-control/backend/tm_control/modules/__init__.py` (register)
- Modify: `tm-control/backend/tm_control/fake.py` (fake unit states)
- Test: `tm-control/backend/tests/test_api_services.py`

**Interfaces:**
- Consumes: Task 2's `CheckGroup`, `Check`, `Fix`; `adapters/command.run`; `require_admin`; `Audit`.
- Produces, in `units.py`: `UNITS: list[Unit]` with `Unit(unit, title, option=None, restartable=True)`: `traffic-monitor.service` "Traffic Monitor pod", `frigate.service` "Frigate", `node-red-tm.service` "Node-RED", `plate-recognizer.service` "Plate Recognizer" (`option="plate_recognizer"`), `go2rtc_server.service` "Camera streams (go2rtc)", `revproxy.service` "Web proxy (nginx)", `tm-control.service` "Control app" (`restartable=False`). `units_for(manifest) -> list[Unit]` drops units whose option the manifest says is off.
- Produces, in `adapters/systemd.py`: `restart_unit(name) -> CommandResult` (`systemctl restart --no-block`), `show_units(names, properties) -> dict[str, dict[str, str]]` (one `systemctl show` per unit; properties `ActiveState`, `SubState`, `NRestarts`, `ActiveEnterTimestamp`, `InvocationID`).
- Produces: `GET /api/v1/services` → `list[Service]` with `unit`, `title`, `active_state`, `sub_state`, `since: str | None`, `restarts: int`, `restartable: bool`; `POST /api/v1/services/{unit}/restart` → 202 `{"unit": ...}` (admin; 404 `not_found` for a unit not in `units_for(manifest)` or with `restartable=False`; audited `services.restart` with the unit as detail).
- Produces: `CheckGroup("services", "Services", [service_checks])`: one `Check` per unit, id `services.<unit>`, `ok` when `active`; `warn` "starting" when `activating`/`reloading`; `error` "stopped" when `inactive` and `error` "failed" when `failed`, each with `Fix(kind="restart", unit=..., text="Restart")` for restartable units; `NRestarts > 0` on an otherwise `active` unit → `warn` with "restarted N times since boot".

- [ ] **Step 1: Write the failing tests**

`test_api_services.py` (patch `tm_control.adapters.systemd.run` with a fake that records argv and answers from a dict of unit properties):
- `test_services_list_for_a_viewer`: 200, seven units minus `plate-recognizer.service` with the fixture manifest, `tm-control.service` has `restartable: false`.
- `test_restart_queues_a_no_block_restart`: admin POST `/api/v1/services/frigate.service/restart` → 202, the fake saw `["systemctl", "restart", "--no-block", "frigate.service"]`, and an audit row `services.restart` / `frigate.service`.
- `test_restart_refuses_a_unit_off_the_list`: `sshd.service`, `tm-control.service`, `../frigate.service`, and `plate-recognizer.service` (option off) → 404.
- `test_viewer_cannot_restart`: 403, and the fake saw no `systemctl restart`.
- `test_service_checks_name_the_fix`: with `frigate.service` `failed` and `node-red-tm.service` `active` with `NRestarts=3`: `services.frigate.service` is `error` with `fix.kind == "restart"`, `services.node-red-tm.service` is `warn` with "3 times" in the detail; `tm-control.service` active → `ok` with `fix is None`.
- `test_restart_failure_is_an_api_error`: the fake returns rc 1 → 500 `internal` with a message that names the unit and no stderr content.

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tm-control/backend/tests/test_api_services.py -q`
Expected: FAIL (`modules.services` missing).

- [ ] **Step 3: Implement the adapter functions, `units.py`, the router, the checks, and the fake states**

- [ ] **Step 4: Run the tests**

Run: `python -m pytest tm-control/backend/tests -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tm-control/backend
git commit -m "Add the services module: unit state, restart through polkit, and the services checks" -m "<trailer block>"
```

---

### Task 4: Device info, host checks, diagnostics, reboot and power-off, and their install changes

**Files:**
- Create: `tm-control/backend/tm_control/adapters/sysinfo.py`, `adapters/redact.py`
- Modify: `tm-control/backend/tm_control/adapters/systemd.py` (`journal_tail(unit, lines)`, `reboot()`, `power_off()`)
- Modify: `tm-control/backend/tm_control/modules/system/router.py` (`GET /system/info`, `GET /system/diagnostics`, `POST /system/reboot`, `POST /system/power-off`), `modules/system/__init__.py` (check group), create `modules/system/checks.py`
- Modify: `tm-control/backend/tm_control/fake.py`
- Modify: `script/ansible/roles/tmsetup/vars/main.yml` (`tmsetup_tm_control_polkit.actions`), `templates/tm-control/50-traffic-monitor.rules.j2`, `templates/tm-control/tm-control.service.j2` (`SupplementaryGroups=systemd-journal video`)
- Test: `tm-control/backend/tests/test_api_system_info.py`, `tm-control/backend/tests/test_redact.py`; `script/tests/test_tm_control_install.py` (render tests)

**Interfaces:**
- Consumes: Task 2's check types; the secrets (`Secrets.read(name)` for each of `NAMES`); `journal_lines`.
- Produces, in `adapters/sysinfo.py` (each returns `None` on any failure): `model()` (`/proc/device-tree/model`), `os_release()` (`/etc/os-release` `PRETTY_NAME`), `kernel()` (`platform.release()`), `uptime_seconds()` (`/proc/uptime`), `memory()` (`/proc/meminfo` `MemTotal`, `MemAvailable`, in bytes), `disk(path)` (`shutil.disk_usage`), `soc_temperature_c()` (`/sys/class/thermal/thermal_zone0/temp` / 1000), `throttled()` (`vcgencmd get_throttled` → `{"raw": "0x50000", "now": [...], "since_boot": [...]}` with the names `under-voltage`, `frequency-capped`, `throttled`, `soft-temperature-limit` for bits 0–3 and 16–19).
- Produces, in `adapters/redact.py`: `redact(text: str, values: list[str]) -> str`: replaces each value (longest first) with `<redacted>`, then `(?i)\b(password|passwd|token|secret|access_token)\b(\s*[=:]\s*)\S+` with `\1\2<redacted>`.
- Produces: `GET /api/v1/system/info` → `SystemInfo` (hostname, serial, model, os, kernel, uptime_seconds, memory, disks (`/` and the manifest's `codedir`), tm (version, commit, branch, installing_user), components, soc_temperature_c, throttled); `GET /api/v1/system/diagnostics` → `text/plain; charset=utf-8` with `Content-Disposition: attachment; filename="tm-diagnostics-<hostname>-<YYYYMMDD-HHMMSS>.txt"` (admin); `POST /api/v1/system/reboot` and `POST /api/v1/system/power-off` → 202 (admin, audited, `systemctl reboot` / `systemctl poweroff` queued as a background task after the response).
- Produces: `CheckGroup("device", "Device", [disk_checks, memory_check, temperature_check, throttling_check])`: disk free on `/` and `codedir`: `warn` under 2 GiB, `error` under 512 MiB; memory `warn` under 200 MiB available; temperature `warn` at 80 °C, `error` at 85 °C; throttling: any bit set now → `error` naming it ("under-voltage now; check the power supply"), only since-boot bits → `warn`; unreadable → `unknown` with "needs the video group" when `vcgencmd` fails with a permission error.
- Produces, in the role: `tmsetup_tm_control_polkit.actions` = the seven ids from decisions 7 and 9; the rules file allows `action.id` in that list for the code owner.

- [ ] **Step 1: Write the failing tests**

`test_redact.py`:
- `test_redact_replaces_each_value_and_prefers_the_longest`: values `["abc", "abcdef"]`, text `x=abcdef y=abc` → `x=<redacted> y=<redacted>`.
- `test_redact_masks_password_and_token_lines`: `password=hunter2`, `Password: hunter2`, `TM_MQTT_BROKER_PASSWORD=hunter2`, `access_token: tb-token-1` → each value becomes `<redacted>`, keys kept.
- `test_redact_leaves_ordinary_text`: a journal line with no secret is unchanged.

`test_api_system_info.py` (patch the sysinfo functions and `journal_tail`):
- `test_system_info_for_a_viewer`: 200 with every field; fake mode reports `tm-fake` and the fake serial.
- `test_system_info_tolerates_missing_sources`: every sysinfo function returning `None` → 200 with nulls, no 500.
- `test_diagnostics_is_admin_only_and_an_attachment`: viewer 403; admin 200, content type `text/plain`, a `Content-Disposition` attachment with `tm-diagnostics-`.
- `test_diagnostics_never_contains_a_secret_value`: the fake secrets' five values are planted in a patched journal line each, plus `TM_MQTT_BROKER_PASSWORD=hunter2` and `Setup code: ABCD-EFGH` → none of the values appear in the body, `<redacted>` does.
- `test_device_checks_thresholds`: free 1 GiB → `warn`; 100 MiB → `error`; 84 °C → `warn`; throttled `0x50005` → `error` naming `under-voltage` and `throttled`; `0x50000` → `warn`; `vcgencmd` permission error → `unknown` mentioning the video group.
- `test_reboot_and_power_off_are_admin_only_audited_and_queued`: viewer 403; admin 202; the fake saw `["systemctl", "reboot"]` (and `poweroff`) only after the response; audit rows `system.reboot`, `system.power_off`.

`script/tests/test_tm_control_install.py`:
- `test_polkit_rules_allow_the_time_and_power_actions`: the rendered rules contain each of the seven action ids and still the unit list and verbs.
- `test_tm_control_service_has_the_video_group`: `SupplementaryGroups=systemd-journal video` and no `ReadWritePaths=`.

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tm-control/backend/tests/test_api_system_info.py tm-control/backend/tests/test_redact.py script/tests/test_tm_control_install.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement the adapters, the endpoints, the checks, the fake values, and the role changes**

The diagnostics text, in this order, each under a `== Title ==` line: device info (as JSON), the time state (`timedatectl show`'s lines; Task 8 doesn't change this), the status report, the services, the manifest, then for each unit in `UNITS` plus `tm-control.service` the last 50 journal lines (`journalctl -u <unit> -n 50 --no-pager -o short-iso`). Build the whole text, then `redact(text, [every secret value])`, then send. The rules template keeps the unit rule and adds, before `return polkit.Result.NOT_HANDLED`, a second `if` over the `actions` list.

- [ ] **Step 4: Run the tests**

Run: `python -m pytest tm-control/backend/tests script/tests -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tm-control/backend script/ansible/roles/tmsetup script/tests
git commit -m "Add device info, host checks, redacted diagnostics, and reboot and power-off through polkit" -m "<trailer block>"
```

---

### Task 5: Node-RED's `/tm-internal/status` endpoint, its token, and the `time:` cleanup

**Files:**
- Modify: `container/node-red-tm/data/flows.json` (new nodes on the `init-config` tab, a status node on `capture-radar`; edit `init config defaults`)
- Modify: `container/node-red-tm/node-red-tm.env.j2` (`TM_INTERNAL_TOKEN`), `container/node-red-tm/config/config.yml.j2` (drop `time:`)
- Modify: `script/ansible/roles/tmsetup/vars/main.yml` (`node_red_internal_token` in `tmsetup_secret_names`), `tasks/node-red-tm_setup.yml` (`lineinfile` for `TM_INTERNAL_TOKEN`)
- Modify: `tm-control/backend/tm_control/core/secrets.py` (`NODE_RED_INTERNAL_TOKEN` in `NAMES`), `tests/fixtures` (the fake secrets)
- Modify: `container/revproxy/tm/locations/nodered.conf.j2` (`location ^~ /nr/tm-internal/ { return 404; }`)
- Modify: `container/node-red-tm/schema/README.md`, `docs/data-and-payloads/data-overview.md` (the schema check; docs text, finished in Task 10)
- Test: `script/tests/test_node_red_flows.py`, `script/tests/test_nginx_config_parses.py`, `script/tests/test_tmsetup_tasks.py`, `script/tests/test_tmsetup_templates.py`

**Interfaces:**
- Produces: `GET http://127.0.0.1:1880/tm-internal/status` with header `X-TM-Internal-Token: <token>` → 200 JSON:
  ```json
  {"status": "ok", "tm_version": "…", "uptime_seconds": 123,
   "config": {"loaded_at": "<ISO>", "errors": ["<message>", "…"]},
   "schema_version": 1,
   "radars": {"TM_RADAR_SERIAL_PORT_00": {"enabled": true, "port_open": true, "last_reading_at": "<ISO or null>"}},
   "deployment": {"lat": 0.0, "lon": 0.0, "bearing": "n"}}
  ```
  401 `{"error": "unauthorized"}` without the header or with a wrong one, and always 401 when `TM_INTERNAL_TOKEN` is empty or unset (fail closed).
- Flow design (the script that edits `flows.json` follows CLAUDE.md's re-serialization rule):
  - `init-config` tab: an `http in` node (GET `/tm-internal/status`) → function `tm-internal: check token` (compares `msg.req.headers["x-tm-internal-token"]` with `env.get("TM_INTERNAL_TOKEN")`; a plain compare, since the endpoint is on loopback and the token is 32 random characters; an empty token refuses everything; on mismatch sends 401 through the second output) → function `tm-internal: build status` (reads `global.tm_status`) → `http response`. A second output of the token function → `http response` (401).
  - `global.tm_status` is kept by: a `catch` node scoped to `init config defaults` and the YAML node, appending `msg.error.message` to `tm_status.config.errors`; the `watch`/startup path clearing `errors` and setting `loaded_at` before the YAML parse; a `sqlite` node running `PRAGMA user_version` after each config load, storing `tm_status.schema_version`; on the `capture-radar` tab, a `status` node scoped to the four `receive RADAR_0N` serial nodes, setting `tm_status.radars[name].port_open` from the status text (connected or not), and a small function after each `receive RADAR_0N` setting `last_reading_at`; `enabled` and `deployment` copied from `global.config` after each load.
  - `init config defaults`: remove the `msg.payload.time.npt_set` line; nothing else reads `time`.
- Produces, in the role: the fifth secret and the env key on every `node-red-tm` run, as `TM_NR_TOKEN_KEY` is added.

- [ ] **Step 1: Write the failing tests**

`script/tests/test_node_red_flows.py`:
- `test_tm_internal_status_endpoint_exists`: one `http in` node with `url == "/tm-internal/status"` and `method == "get"`, wired to a function whose `func` reads `x-tm-internal-token` and `TM_INTERNAL_TOKEN`, and that function's second output reaches an `http response` with `statusCode` 401.
- `test_tm_internal_token_check_fails_closed` (runs the function body under `node` like `test_node_red_settings.py` does): with `TM_INTERNAL_TOKEN` unset, a request with any header value goes to the 401 output; with the token set, a wrong value goes to 401 and the right one passes.
- `test_init_config_no_longer_reads_time`: `init config defaults`'s `func` doesn't contain `payload.time`.
- `test_schema_version_is_recorded`: a `sqlite` node with `sql` containing `PRAGMA user_version` on the `init-config` tab.

`script/tests/test_nginx_config_parses.py`: `test_nr_tm_internal_is_denied`: the rendered `nodered.conf` contains `location ^~ /nr/tm-internal/ { return 404; }` and the full config still passes the existing parse check.

`script/tests/test_tmsetup_tasks.py`: `test_node_red_env_gains_the_internal_token_on_every_run`: the `lineinfile` task for `TM_INTERNAL_TOKEN` exists with `regexp: '^TM_INTERNAL_TOKEN='` and notifies `Restart node-red-tm.service`; `tmsetup_secret_names` lists `node_red_internal_token`.

`script/tests/test_tmsetup_templates.py`: `test_node_red_config_template_has_no_time_section`; `test_node_red_env_template_has_the_internal_token`.

`tm-control/backend/tests/test_settings_and_manifest.py` (or the secrets test): `test_secrets_require_the_internal_token`.

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest script/tests tm-control/backend/tests -q`
Expected: the new tests FAIL.

- [ ] **Step 3: Edit the flows by script, the templates, the role, the secrets module, and nginx**

Write the editing script under `$CLAUDE_JOB_DIR/tmp/`, run it once, and check `python3 -m json.tool` plus a `git diff --stat` that touches only the new and edited nodes. Give each new node a fresh 16-hex id and keep the MQTT nodes' ids.

- [ ] **Step 4: Run the tests and a local Node-RED smoke test**

Run: `python -m pytest script/tests tm-control/backend/tests -q && python3 -m json.tool container/node-red-tm/data/flows.json >/dev/null`
Then, as M2's Task 1 did, start `docker.io/nodered/node-red:5.0.8` with the repo's `flows.json`, `settings.js`, and an env of `TM_INTERNAL_TOKEN=spike`, and:
```bash
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:1881/tm-internal/status                              # 401
curl -s -H 'X-TM-Internal-Token: spike' http://127.0.0.1:1881/tm-internal/status                               # 200 JSON with schema_version
```
Expected: 401, then JSON. Missing node modules in the stock image (sqlite, serial) make those nodes report errors in the log; the status endpoint still answers, with `schema_version: null`.

- [ ] **Step 5: Commit**

```bash
git add container script/ansible/roles/tmsetup script/tests tm-control/backend
git commit -m "Add Node-RED's internal status endpoint with its token, and drop the unused time settings" -m "<trailer block>"
```

---

### Task 6: App checks and contract checks: Frigate, Node-RED, go2rtc, the broker login, and the configuration contracts

**Files:**
- Create: `tm-control/backend/tm_control/adapters/frigate.py`, `adapters/nodered.py`, `adapters/go2rtc.py`, `adapters/mqtt.py`, `adapters/httpjson.py` (one `get_json(url, headers, timeout)` for the three)
- Create: `tm-control/backend/tm_control/modules/apps/__init__.py`, `modules/apps/checks.py`, `modules/apps/contracts.py`
- Modify: `tm-control/backend/tm_control/modules/__init__.py` (register)
- Create: `tm-control/backend/tests/fixtures/frigate_api_config.json`, `frigate_api_stats.json`, `go2rtc_streams.json`, `nodered_status.json`, `node_red_config_ok.yml` (synthetic)
- Test: `tm-control/backend/tests/test_app_checks.py`, `tm-control/backend/tests/test_contract_checks.py`

**Interfaces:**
- Consumes: Task 5's endpoint and the `node_red_internal_token` secret; the manifest's `codedir` and `components`; Task 2's types.
- Produces, in the adapters (each returns `None` when the app doesn't answer, times out, or returns non-JSON; never raises): `frigate.version()`, `frigate.config()`, `frigate.stats()` (`http://127.0.0.1:5000/api/...`, 3 s); `nodered.status(token) -> tuple[int | None, dict | None]` (the HTTP status and the JSON body from `http://127.0.0.1:1880/tm-internal/status`, 3 s; `(None, None)` when it doesn't answer, so a 401 can be told from a dead Node-RED); `nodered.config(codedir)` → the parsed `config.yml` (`ruamel.yaml` safe load; `None` on a YAML error, with the error kept for the check); `go2rtc.streams()` (`http://127.0.0.1:1984/api/streams`); `mqtt.anonymous_connect_refused(host="127.0.0.1", port=1883, timeout=3) -> bool | None` (sends a minimal MQTT 3.1.1 CONNECT with client id `tm-control-check` and no credentials, reads the CONNACK; `True` when the return code is 4 or 5, `False` when 0, `None` when no answer); `mqtt.port_1883_open_to_network() -> bool | None` (`ss -ltnH` lines with `:1883` whose local address isn't `127.0.0.1` or `[::1]`).
- Produces: `newest_migration(codedir) -> int | None` in `modules/apps/checks.py` (the highest `NNNN` among `<codedir>/node-red-tm/schema/migrations/NNNN_*.sql`).
- Produces: `CheckGroup("apps", "Apps", [frigate_checks, nodered_checks, go2rtc_checks, broker_check])`:
  - `apps.frigate.reachable`: version answered → `ok` "Frigate <version>", `warn` when it differs from `components.frigate`; no answer → `error` with a restart fix for `frigate.service`.
  - `apps.frigate.cameras`: each camera enabled in Frigate's config has `camera_fps > 0` in stats → `ok`; a camera at 0 → `error` naming it, restart fix.
  - `apps.nodered.reachable`: status answered → `ok` "Node-RED up <relative uptime>"; 401 → `error` "the internal token doesn't match; re-run `tmsetup.sh -t node-red-tm`"; no answer → `error` with a restart fix for `node-red-tm.service`.
  - `apps.nodered.config`: `config.errors` empty → `ok`; else `warn` with the messages joined (first three, then "and N more"); `config.yml` unparsable on the host → `error` "config.yml has a YAML error: <line/column only>".
  - `apps.nodered.schema`: `schema_version == newest_migration` → `ok` "schema version N"; lower → `error` "the database schema is behind (N of M); Node-RED can't write new data. See `sudo journalctl -u node-red-tm | grep tmdb-migrate`" with `Fix(kind="link", href="/device", text="Diagnostics")`; higher → `warn` "newer than this install"; Node-RED down or `schema_version` null → `unknown`.
  - `apps.go2rtc.streams`: for each Frigate camera input whose path names a stream on `:8554`, that stream has producers → `ok`; none → `error` with a restart fix for `go2rtc_server.service`; go2rtc not answering → `error`.
  - `apps.broker.login`: 1883 on loopback only → `ok` "broker on this device only"; open and refuses → `ok` "login enforced on the network port"; open and accepts → `error` (decision 16); open and no answer → `unknown`.
- Produces: `CheckGroup("config", "Configuration", [camera_contract, zone_contract, radar_contract, deployment_contract])`, from `config.yml` and Frigate's config:
  - `config.cameras`: every Frigate camera is in `sensors.cameras` and enabled → `ok`; a Frigate camera missing or disabled there → `error` "events from <name> are not recorded" (the #249/camera-rename case); a config camera Frigate doesn't have → `warn`.
  - `config.zones`: each enabled camera has `zone_capture`, `zone_near`, `zone_far`, and `zone_radar` in Frigate → `ok`; missing ones → `warn` listing them, with "without zone_near and zone_far, events get a direction only from the radar (#243)" when those are the missing ones.
  - `config.radars`: each `sensors.radars.<name>` is a `TM_RADAR_SERIAL_PORT_0N` name → else `error`; each enabled camera's `camera_radar` names an enabled radar → else `error` "camera <name> is paired with radar <r>, which isn't enabled; its events are dropped (#255)".
  - `config.deployment`: `lat` in [-90, 90], `lon` in [-180, 180], `bearing` in `n s e w ne nw se sw` or empty → `ok`; else `error` naming the key.

- [ ] **Step 1: Write the failing tests**

`test_app_checks.py` (patch the adapters' `get_json` and `run`, use the fixtures):
- `test_frigate_reachable_and_version_mismatch`, `test_frigate_down_has_a_restart_fix`, `test_camera_without_frames_is_an_error`.
- `test_nodered_status_token_mismatch_names_the_fix` (401 → the `-t node-red-tm` hint), `test_nodered_config_errors_are_a_warning`, `test_yaml_error_is_reported_without_the_file_content`.
- `test_schema_behind_is_an_error_with_the_journal_hint` (`schema_version: 0`, two migration files → "0 of 2"), `test_schema_current_is_ok`, `test_schema_unknown_when_nodered_is_down`.
- `test_go2rtc_stream_without_producer_is_an_error`.
- `test_broker_check_only_connects_when_1883_is_open` (loopback only → `ok`, no socket opened), `test_broker_accepting_anonymous_clients_is_an_error`, `test_mqtt_connect_packet_is_well_formed` (the bytes of the CONNECT: fixed header `0x10`, protocol name `MQTT`, level 4, flags `0x02`, keepalive, client id).
- `test_newest_migration_reads_the_highest_number` (`0001_baseline.sql`, `0003_x.sql` → 3; empty dir → None).
- `test_adapters_never_raise_on_timeout_or_bad_json`.

`test_contract_checks.py`:
- `test_cameras_match`, `test_disabled_camera_is_an_error`, `test_missing_zones_name_the_direction_problem`, `test_radar_name_must_be_an_env_name`, `test_camera_radar_must_name_an_enabled_radar` (#255), `test_deployment_values` (lat 91 → error; bearing `north` → error; empty bearing → ok).

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tm-control/backend/tests/test_app_checks.py tm-control/backend/tests/test_contract_checks.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement the adapters, the checks, and the contracts**

- [ ] **Step 4: Run the tests**

Run: `python -m pytest tm-control/backend/tests -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tm-control/backend
git commit -m "Add the app and configuration checks: Frigate, Node-RED and its schema, go2rtc, the broker login, and the name contracts" -m "<trailer block>"
```

---

### Task 7: Hardware checks: detectors in layers, the HEVC decoder, and radars

**Files:**
- Create: `tm-control/backend/tm_control/adapters/hardware.py`
- Create: `tm-control/backend/tm_control/modules/hardware/__init__.py`, `modules/hardware/checks.py`, `modules/hardware/probes.py`
- Modify: `tm-control/backend/tm_control/modules/__init__.py` (register; no router)
- Modify: `script/ansible/roles/tmsetup/defaults/main.yml` (`edgetpu_usb.check_exists: lsusb | grep -iE '1a6e:089a|18d1:9302'`, #217)
- Test: `tm-control/backend/tests/test_hardware_checks.py`; `script/tests/test_tmsetup_templates.py` (or the file that already tests `defaults/main.yml`: the USB probe matches both ids)

**Interfaces:**
- Consumes: the manifest's `probes` (decision 5), Task 2's `Context.probes` memo, Task 6's adapters: `frigate.config()`, `frigate.stats()`, `nodered.status()` (its `radars`), and `nodered.config()`.
- Produces, in `adapters/hardware.py`: `lsusb()`, `lspci()` (memoized through `context.probes`), `module_loaded(name)` (`/proc/modules`), `path_exists(path)`, `unit_adds_device(unit_file, dev_path) -> bool | None` (reads `/etc/containers/systemd/<unit_file>`; `None` if unreadable), `hevc_decoder()` → `{"symlink": readlink -f of the manifest's `hevc_device` or None, "scanned": the /dev/mediaN whose `/sys/class/media/mediaN/model` is `rpi-hevc-dec`, or None}`.
- Produces, in `probes.py`: `DETECTOR_PROBES = {"edgetpu_usb": Probe(bus="usb", pattern=r"1a6e:089a|18d1:9302", module=None), "edgetpu_pci": Probe(bus="pci", pattern=r"(?i)coral|1ac1:089a", module="apex"), "hailo8l": Probe(bus="pci", pattern=r"(?i)hailo", module="hailo_pci")}`.
- Produces: `CheckGroup("hardware", "Hardware", [detector_checks, hevc_checks, radar_checks])`:
  - **Detectors.** For each kind in the manifest's `probes.detectors` that the table knows and that is present on its bus, one check `hardware.detector.<kind>` whose status is the first failing layer: (2) driver: `dev_path` exists and, when the probe names a module, it's loaded, else `error` "driver not ready; re-run `tmsetup.sh -t detectors`"; (3) passed: `frigate.container` has `AddDevice=<dev_path>:<dev_path>`, else `error` "present on the host but not passed to Frigate; re-run `tmsetup.sh -t detectors -t frigate`"; (4) configured: Frigate's `/api/config` has a detector with that `type` (and `device` for edgetpu), else `error` "not in Frigate's config"; (5) working: `/api/stats` names that detector with a `pid`, else `error` with `Fix(kind="restart", unit="frigate.service")`. All layers pass → `ok` with the inference speed. A present kind the table doesn't know → `unknown`. No kind present → one check `hardware.detector.none`: `warn` "no AI accelerator found; Frigate detects on the CPU (slow)" when Frigate's config has a `cpu` detector, `error` when it has none.
  - **HEVC decoder.** `hardware.hevc.present`: `symlink == scanned` → `ok`; no scanned device → `error` "the kernel shows no HEVC decoder"; symlink missing or different → `error` "the decoder's symlink is stale; reboot or re-run `tmsetup.sh -t frigate`" with a `link` fix to `/device`. `hardware.hevc.passed`: `frigate.container` has `AddDevice=<hevc_device>` and `frigate.service` is active → `ok`, else `error`.
  - **Radars.** For each path in `probes.radar_paths`, with env name `TM_RADAR_SERIAL_PORT_0N` from its index: present on the host? passed (`node-red-tm.container` `AddDevice=<path>`)? configured (`sensors.radars.<name>.enabled` in `config.yml`, read through Task 6's `nodered.config()`)? open (Node-RED status `radars[name].port_open`)? A path neither present nor configured yields no check. Present but not passed → `error` "re-run `tmsetup.sh -t node-red-tm`"; present and passed but not configured → `warn` "enable `sensors.radars.<name>` in config.yml"; configured but not present → `error` "not plugged in"; configured and present but not open → `error` with `Fix(kind="restart", unit="node-red-tm.service")`; all good → `ok` with "last reading <relative time>" when Node-RED reports one.
  - Every check carries `Fix(kind="rescan", text="Re-scan hardware")` when its status isn't `ok`, in addition to any hint, so the UI shows the re-scan button on the group.

- [ ] **Step 1: Write the failing tests**

`test_hardware_checks.py` (fake `lsusb`/`lspci` text, a `tmp_path` with fake unit files, `/proc/modules` text, recorded Frigate config and stats dicts, a recorded Node-RED status dict, and a `config.yml` text):
- `test_coral_usb_is_present_under_both_ids` (#217): `1a6e:089a` and `18d1:9302` each count as present.
- `test_detector_layers_name_the_first_failure`: six cases (driver missing, not passed, not configured, no pid, all good, unknown kind) with the expected status, detail fragment, and fix.
- `test_no_accelerator_is_a_warning_with_the_cpu_detector`: no match on either bus, Frigate config `detectors.cpu` → `warn`; no `cpu` → `error`.
- `test_hevc_present_compares_symlink_and_scan`: equal → `ok`; symlink to another media node → `error` "stale"; none scanned → `error`.
- `test_radar_layers`: present and passed and configured and open → `ok`; present not passed → `error` naming `-t node-red-tm`; configured not present → `error` "not plugged in"; present not configured → `warn`; configured, present, not open → `error` with a restart fix; an unused path → no check.
- `test_unreadable_unit_file_is_unknown`: `unit_adds_device` returning `None` → the passed layer is `unknown`, not `error`.
- `test_hardware_checks_memoize_the_bus_listings`: two detector kinds, `lsusb` and `lspci` each run once per report.

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tm-control/backend/tests/test_hardware_checks.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement the adapter, the probe table, the checks, and the `defaults/main.yml` fix**

- [ ] **Step 4: Run the tests**

Run: `python -m pytest tm-control/backend/tests script/tests -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tm-control/backend script/ansible/roles/tmsetup script/tests
git commit -m "Add the hardware checks: detectors in layers, the HEVC decoder, and radars; match both Coral USB ids" -m "<trailer block>"
```

---

### Task 8: Date and time: read, set from the browser, time zone, NTP, and the container restart

**Files:**
- Create: `tm-control/backend/tm_control/adapters/timedate.py`
- Create: `tm-control/backend/tm_control/modules/time/__init__.py`, `modules/time/router.py`, `modules/time/checks.py`
- Modify: `tm-control/backend/tm_control/modules/__init__.py` (register), `fake.py`, `modules/system/router.py` (the device card's `time` after `tzset`)
- Test: `tm-control/backend/tests/test_api_time.py`

**Interfaces:**
- Consumes: Task 3's `restart_unit`; Task 4's polkit actions; `Audit`.
- Produces, in `adapters/timedate.py`: `show() -> TimeState | None` (`timedatectl show` → `Timezone`, `NTP`, `NTPSynchronized`, `TimeUSec`, `RTCTimeUSec`, `CanNTP`); `list_timezones() -> list[str]` (cached for the process); `set_timezone(name)`, `set_ntp(enabled: bool)`, `set_time(when: datetime)` (as `timedatectl set-time "YYYY-MM-DD HH:MM:SS"` in UTC with `TZ=UTC` in the environment), each returning `CommandResult`.
- Produces: `GET /api/v1/time` → `TimeState`: `device_time` (ISO 8601 with offset), `timezone`, `ntp: {enabled, synchronized, available}`, `rtc_time: str | None`; `GET /api/v1/time/timezones` → `list[str]`; `POST /api/v1/time` (admin) body `TimeChange`: `timezone: str | None`, `ntp: bool | None`, `time: str | None` (ISO 8601 with offset, as the browser sends `new Date().toISOString()`) → 200 `TimeResult`: the new `TimeState` plus `time_kept_from_ntp: bool` and `restarting: list[str]`.
  - Order: if `time` is given and NTP is enabled and synchronized → don't set the time, `time_kept_from_ntp = True`; else if `time` is given → `set_ntp(False)` when enabled, then `set_time`. Then `set_timezone` if given and different. Then `set_ntp` if `ntp` is given. If the time zone changed: `time.tzset()`, queue `restart_unit` for `traffic-monitor.service` and `revproxy.service` as a background task, and list them in `restarting`. Audit `time.set` with which fields changed (no values).
  - Validation (422 `validation`): `timezone` not in `list_timezones()`; `time` unparsable, before `2026-01-01T00:00:00Z`, or after `2046-01-01T00:00:00Z`; an empty body.
- Produces: `CheckGroup("time", "Date and time", [time_checks])`: `time.plausible`: device time before the floor → `error` "the clock is wrong; set it on the Date and time page" with `Fix(kind="link", href="/time")`; NTP enabled and not synchronized → `warn` "no time source reachable (offline?); the clock runs on its own" with the link; NTP disabled → `ok` "set by hand" ; else `ok` "synchronized".

- [ ] **Step 1: Write the failing tests**

`test_api_time.py` (patch `run` with a fake that answers `timedatectl show` and `list-timezones` and records the rest):
- `test_time_state_for_a_viewer`: 200 with the fields; `ntp.available` from `CanNTP`.
- `test_timezones_list_is_cached`: two calls, one `list-timezones` run.
- `test_set_from_browser_with_ntp_synchronized_keeps_the_time`: body with `time` and `timezone` → `set-time` never ran, `set-timezone` ran, `time_kept_from_ntp` is true, `restarting == ["traffic-monitor.service", "revproxy.service"]`.
- `test_set_from_browser_without_ntp_sets_ntp_off_then_time_then_zone`: order of recorded argv is `set-ntp false`, `set-time …`, `set-timezone …`; the `set-time` argument equals the body's instant in UTC.
- `test_timezone_unchanged_restarts_nothing`: same zone → `restarting == []`, no `systemctl restart`.
- `test_ntp_toggle_alone_restarts_nothing`.
- `test_refuses_an_unknown_timezone_and_an_implausible_time`: `Mars/Olympus` → 422; `1999-12-31T00:00:00Z` → 422; `2050-01-01T00:00:00Z` → 422; `{}` → 422.
- `test_time_change_is_admin_only_and_audited`: viewer 403; admin's audit row `time.set` has no time value in its detail.
- `test_time_checks`: device time 2020 → `error` with the link; NTP on and unsynchronized → `warn`; NTP off → `ok`.
- `test_timedatectl_failure_is_an_api_error_without_stderr`: rc 1 → 500 `internal`.

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tm-control/backend/tests/test_api_time.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement the adapter, the module, the checks, and the fake state**

- [ ] **Step 4: Run the tests**

Run: `python -m pytest tm-control/backend/tests -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tm-control/backend
git commit -m "Add the date and time module: set from the browser, time zone, NTP, and the container restart" -m "<trailer block>"
```

---

### Task 9: The UI: Status, Device, and Date and time pages, the home page's health line, and the typed client

Build from the design plan below, which was written with the `frontend-design` skill against the UI README's design notes; the spec's constraints (conventional Vuetify, thin UI, 375 px first, system fonts, `@mdi/js`) win over any flourish. Take screenshots in fake mode at 375 px and 1366 px and record what the review changed in the README.

**Files:**
- Modify: `tm-control/ui/src/api/openapi.json`, `schema.d.ts` (regenerated), `types.ts` (only for M2 endpoints; M3's come from the schema)
- Create: `tm-control/ui/src/components/CheckList.vue`, `RelativeTime.ts` (a small formatter)
- Create: `tm-control/ui/src/modules/status/index.ts`, `StatusPage.vue`; `modules/device/index.ts`, `DevicePage.vue`; `modules/time/index.ts`, `TimePage.vue`
- Modify: `tm-control/ui/src/modules/index.ts` (menu order: Home, Status, Device, Date and time, then account), `modules/home/HomePage.vue` (health line), `tm-control/ui/README.md` (design notes), `App.vue` only if the nav needs it
- Test: `tm-control/ui/tests/check-list.spec.ts`, `status-page.spec.ts`, `time-page.spec.ts`, `device-page.spec.ts`, `router.spec.ts` (new routes), `tests/fake-api.ts` (the M3 endpoints)

**Interfaces:**
- Consumes: `GET /status`, `POST /status/rescan`, `GET /services`, `POST /services/{unit}/restart`, `GET /system/info`, `GET /system/diagnostics`, `POST /system/reboot`, `POST /system/power-off`, `GET /time`, `GET /time/timezones`, `POST /time`; `useSession().isAdmin`; `ConfirmDialog`, `StatusCard`.
- Produces: `CheckList` (props `{ group: Group, admin: boolean, busy: string | null }`, emits `restart(unit)`, `rescan()`), `StatusPage` (`/status`), `DevicePage` (`/device`), `TimePage` (`/time`; any user, controls for admins), the home page's health line, and a "Status, Device, and Date and time" section in `tm-control/ui/README.md`'s design notes (the plan below, plus what the screenshot review changed).

**Design plan (2026-10-28).** The brief: the same people as M2, often on a phone at the roadside, on the device's hotspot, with no internet, and no SSH. The pages' one job is to answer "is it working, and if not, what do I do" in sunlight, at a glance, and then to let an admin do the few things that fix it. The M2 design notes still rule: the device's theme colors, system fonts, cards only for objects, no toasts, results stay where they happened, nothing depends on hover.

- *Color.* No new palette: the device theme's `background` (`#0C1120`), `primary` (`#3a82ff`), `on-background` (`#f8fafc`), `secondary` (`#8895a7`), `surface` (`#181d2b`). The four statuses use Vuetify's dark-theme `success` (`#4CAF50`), `warning` (`#FB8C00`), `error` (`#CF6679`), and `secondary` for `unknown`, and only on the status mark (an icon, which needs 3:1 and has it) and the verdict's icon. Titles, details, and rows stay in the text colors: a page of colored rows looks alarming at a glance and says nothing. Shape carries the status alongside color: `mdiCheckCircle`, `mdiAlert` (a triangle), `mdiCloseCircle`, `mdiHelpCircle`.
- *Type.* The existing scale. The one addition: the two clocks on the Date and time page in `text-h4` with `font-variant-numeric: tabular-nums`, so the digits don't jitter as they tick. Group titles `text-h6`; check titles `text-body-1`; details `text-body-2` in `secondary`; the verdict `text-h5` in the text color, not the heading blue, because its color would fight the status icon beside it.
- *Layout.* Left-aligned, at most 760 px, as the other pages. The memorable element of M3 is the **verdict**: one sentence at the top of the Status page, with one large status icon (32 px) before it, that says the whole page in words. Under it, one plain list per group. No tiles, no counts per group, no charts, no collapsing: a problem must never be hidden behind a tap.

Status, at 375 px (the admin's view; viewers see the same list with no buttons):

```text
+----------------------------------+
| Status                      (h5) |
|                                  |
| (!) 2 things need attention (h5) |
| Checked just now        [Refresh]|
|                                  |
| Services                    (h6) |
| (v) Traffic Monitor pod          |
|     running since 09:12          |
| (x) Frigate                      |
|     stopped after a failure      |
|                  [Restart Frigate]|
| (v) Node-RED                     |
|     running since 09:12          |
|                                  |
| Hardware                    (h6) |
| (!) Radar on /dev/ttyACM0        |
|     Plugged in, but not enabled  |
|     in config.yml (sensors.      |
|     radars.TM_RADAR_SERIAL_      |
|     PORT_00).                    |
|              [Re-scan hardware]  |
| (v) HEVC decoder                 |
|     passed to Frigate            |
| ...                              |
+----------------------------------+
```

Each row: the status mark in the left gutter, the title, the detail under it, and at most one button on the row, right-aligned, 44 px tall, named for what it does ("Restart Frigate", not "Fix"). "Re-scan hardware" appears once, at the end of the Hardware group, only when something in it isn't ok. A `link` fix is a text link inside the detail ("Set it on the Date and time page"). A `hint` is just the detail. The verdict sentences, from the summary: "Everything is working"; "Working, with N things to look at" (warnings only); "N problems need attention" (any error); "Some checks couldn't run" (unknowns and nothing worse). "Checked just now" counts up ("Checked 20 seconds ago") and the list refreshes in place every 10 seconds while the page is visible, with no animation; a row that changes just changes. The home page's health line is the same sentence, as a link to `/status`.

Device, at 375 px:

```text
+----------------------------------+
| Device                      (h5) |
|                                  |
| +------------------------------+ |
| | tm-device              (h4)  | |
| | Raspberry Pi 5, 8 GB         | |
| | Traffic Monitor 0.8.0        | |
| | Serial number  Up since      | |
| | 00000000123    Oct 27, 09:12 | |
| | Storage                      | |
| | 23 GB free of 58 GB          | |
| | [=======-------------------] | |
| | Temperature   Power          | |
| | 54 °C         ok             | |
| +------------------------------+ |
|                                  |
| Software                    (h6) |
| Frigate 0.18.1 · Node-RED 5.0.8  |
| go2rtc 1.9.14 · nginx 1.31.0     |
| Commit 2da617a on dev            |
|                                  |
| Diagnostics                 (h6) |
| A text file with the device's    |
| state and recent logs, for a     |
| support request. Passwords and   |
| keys are removed.                |
| [Download diagnostics] [Copy]    |
|                                  |
| Power                       (h6) |
| [Reboot the device]              |
| [Shut down the device]           |
+----------------------------------+
```

The device card is the home page's card, extended: it's the one card on the page, because the device is the one object. The storage line is text with a thin bar under it, which is the only bar in the app; it shows a proportion, which words do badly. Software, Diagnostics, and Power sit directly on the page. Reboot and Shut down are outlined buttons, each behind `ConfirmDialog` ("Reboot the device?" / "The device will be unreachable for about two minutes." / "Reboot"; "Shut down the device?" / "The device will turn off. To start it again, unplug it and plug it back in." / "Shut down"); after confirming, the page shows "Rebooting. This page will stop answering for about two minutes." in place, and the app's existing "device didn't answer" screen takes over.

Date and time, at 375 px:

```text
+----------------------------------+
| Date and time               (h5) |
|                                  |
| This device        This phone    |
| 14:32:07  (h4)     14:35:12 (h4) |
| Oct 28, 2026       Oct 28, 2026  |
| UTC-07:00          UTC-07:00     |
|                                  |
| The device is 3 minutes behind   |
| this phone.                      |
| [Set from this browser]          |
|                                  |
| Time zone                        |
| [America/Los_Angeles        v]   |
| [Save time zone]                 |
|                                  |
| [x] Keep time from the internet  |
|     The device has no time       |
|     source right now, so its     |
|     clock runs on its own.       |
+----------------------------------+
```

The two clocks are the page's instrument: the same instant from two sources, side by side, both ticking from the last fetch plus elapsed time, with the difference stated in words under them ("The device and this phone agree"; "The device is 3 minutes behind this phone"; "The device's time zone differs from this phone's"). "Set from this browser" is the filled primary button when they differ by more than 5 seconds or by zone, outlined when they agree. After it, the result stays in place: "Time set from this phone. Frigate and Node-RED are restarting." or "The device already keeps time from the internet, so only the time zone changed." The NTP switch's helper line reads from `ntp.synchronized`: "The device keeps time from the internet." or the offline sentence above. Below 600 px the two clocks stack, device first. A viewer sees the clocks, the difference sentence, the time zone as text, and the NTP sentence, with no button, picker, or switch; the page then ends with "An administrator can set the time and time zone here."

- *Copy.* Check titles name the thing ("Frigate", "Radar on /dev/ttyACM0", "Database schema", "Clock"); details say the state in one sentence and the next step in another, in the API's words. Buttons name the unit they act on. Confirmations say what the person will notice ("The camera view stops for about a minute while Frigate restarts."). Errors from the API show as they are, next to the row or form.
- *Principles.* One bold thing per page: the verdict on Status, the card on Device, the clocks on Date and time. Color only on status marks. Every action's result is written where the action was. Nothing collapses, scrolls sideways, or depends on hover. Keyboard focus visible on every row button.

**Review against the generic default.** A status page done without thought is a grid of colored tiles with big counts, a donut, badges per section, and collapsible accordions; a device page is stat cards; a time page is a form. The plan above replaced all of those on purpose: the verdict sentence instead of counts, lists instead of tiles, the single card for the single object, and two live clocks instead of a datetime field. Two choices that are conventional are conventional by the spec's rule (plain Vuetify, non-front-end maintainers review it): the status-mark-plus-title-plus-detail row, and the autocomplete for the time zone. The dark navy and blue are the device's own theme, not a choice made here.

**Defaults rejected:** dashboard tiles and counts per group; colored row backgrounds; collapsible groups; a snackbar for "Restarting"; an icon-only fix button; a `datetime-local` input for setting the time (the browser already knows the time; typing it is error-prone at the roadside); animating list changes; a gauge for temperature.

- [ ] **Step 1: Regenerate the client and write the failing UI tests**

```bash
PYTHONPATH=tm-control/backend python -m tm_control dump-openapi > tm-control/ui/src/api/openapi.json
(cd tm-control/ui && npm run api:generate)
```

Tests (Vitest with the mount helper and `fake-api.ts`):
- `check-list.spec.ts`: renders four statuses with their icons; a `restart` fix shows the button only for admins and emits the unit; a group with any non-ok hardware check shows one `Re-scan hardware` button; a `hint` fix renders as text; a `link` fix renders a `router-link`.
- `status-page.spec.ts`: the verdict for `{ok: 5, warn: 1, error: 0, unknown: 0}` reads "Working, with 1 thing to look at", for one error "1 problem needs attention", for all ok "Everything is working"; polling calls `GET /status` again after 10 s (fake timers) and not while hidden; a restart posts to `/services/frigate.service/restart` after confirmation and the row's button reads "Restart Frigate".
- `device-page.spec.ts`: the card renders with the storage line and bar; `Reboot the device` posts only after confirmation and the page then shows the "Rebooting" text in place; viewers see no Diagnostics or Power section.
- `time-page.spec.ts`: both clocks render and tick with fake timers; a viewer sees them and the zone as text, no button, picker, or switch, and the administrator sentence; a 180 s difference reads "The device is 3 minutes behind this phone"; `Set from this browser` posts the browser's instant and zone; the result's `time_kept_from_ntp` shows the "only the time zone changed" text; choosing a zone and saving posts `{timezone}` only.
- `router.spec.ts`: `/status`, `/device`, and `/time` open for a viewer; `/system` stays off the router's routes (it would be Cockpit).

- [ ] **Step 2: Run them to verify they fail**

Run: `cd tm-control/ui && npm test`
Expected: the new specs FAIL.

- [ ] **Step 3: Write the components and pages, register the modules, and add the health line**

- [ ] **Step 4: Build, test, and click through fake mode**

Run: `podman run --rm -v "$PWD/tm-control/ui:/ui:Z" -w /ui docker.io/library/node:22.23.4-alpine sh -c 'npm ci && npm run build && npm test'`
Expected: build ok, all specs pass.

Fake mode click-through (backend `TM_CONTROL_FAKE=1`, UI `npm run dev`) at 375 px and 1366 px: home with the health line; Status with every status and fix kind from the fixture, a restart confirm, a re-scan; Device with diagnostics Download and Copy and the two confirmations; Date and time with Set from this browser, a zone change, and the NTP switch; the same pages as a viewer (no buttons, pickers, or switches). No console errors.

- [ ] **Step 5: Commit**

```bash
git add tm-control/ui
git commit -m "Add the Status, Device, and Date and time pages and the home page's health line" -m "<trailer block>"
```

---

### Task 10: Docs, CLAUDE.md, and the spec corrections

**Files:**
- Create: `docs/use/device-health.md` ("Check and fix the device": the Status page and what each group means, restart, re-scan, the Device page and diagnostics, reboot and shut down, the Date and time page and "Set from this browser", what to do when the clock is wrong offline, and what viewers see on each page)
- Modify: `mkdocs.yml` (the new page under Use the device, after Control app), `docs/use/control-app.md` (a short pointer), `docs/use/system-admin.md` ("Services": restart from the control app first, Cockpit second), `docs/data-and-payloads/data-overview.md` and `container/node-red-tm/schema/README.md` (the schema-behind warning and the journal hint), the configuration page that documents `config.yml`'s `time:` keys (remove them; say the time zone is set at install by `tmsetup_timezone` and later on the Date and time page), `docs/reference/tmsetup.md` if it lists the secrets or `.env` keys (`TM_INTERNAL_TOKEN`), `docs/development/tm-control.md` (check groups, the module's `check_groups`, the Node-RED internal endpoint and its token, the polkit actions, fake mode's status fixture), `docs/help-and-faq/frequently-asked-questions.md` (an entry for "The status page says the database schema is behind")
- Modify: `CLAUDE.md` (tm-control's bullet list: the checks, the actions, the fifth secret, the polkit actions, the `/tm-internal/` contract, the `time:` removal), `script/devpi/README.md` (the module table rows for the new device tests, written in Task 11)
- Modify: `design/specs/2026-10-02-tm-control-platform-design.md` (factual corrections only: "podman inspect" → the rendered unit; SSE deferred to the first long job; the polkit actions list; the M3 device-handling question answered; the `time:` keys; "M3 planning picks one" for the schema check → Node-RED's status)

- [ ] **Step 1: Write the pages following "Writing docs → Style" in `docs/development/contributing.md`**

Plain language for operators; no file paths on the operator pages except the one journal command the schema warning shows; relative `.md` links; admonitions for the offline-clock note and the shut-down warning.

- [ ] **Step 2: Build the docs**

Run: `~/.venvs/tm-docs/bin/mkdocs build --strict`
Expected: no warnings; the new page is in the nav.

- [ ] **Step 3: Commit**

```bash
git add docs mkdocs.yml CLAUDE.md container/node-red-tm/schema/README.md design/specs script/devpi/README.md
git commit -m "Document the status, device, and date and time pages, and correct the spec for M3" -m "<trailer block>"
```

---

### Task 11: Device tests, the Pi test plan, and the PR

Same rules as M2's Task 12: a dev Pi from the inventory, never a field device; ask before anything disruptive; `T` is `.venv/bin/python script/devpi/tmdev.py` run from this branch's checkout. Device names, addresses, and secrets stay out of commits and PR text. Tests that read `config.yml` or the token run only on `pii_free` units.

**Files:**
- Modify: `script/devpi/tests/test_web.py`, `test_services.py`, `test_disruptive.py`, `devpi_checks.py` (a `tm_internal_token(host)` helper returning the secret as `Redacted`, read as root)
- Modify: `script/devpi/README.md` (module table rows)

**Interfaces:**
- Consumes: `admin_session`, `viewer_session`, `tm_login`, `expect` (`ai_coprocessor`, `radars`, `pii_free`), `request_from_this_machine`, `pi_json`, `read_root_file`, `wait_until_ready`.

- [ ] **Step 1: Write the device tests**

`test_web.py`:
- `test_status_report_agrees_with_the_inventory` (decision 17): admin `GET /api/v1/status` → 200; the expected detector's check is `ok` (or `hardware.detector.none` is `warn` when the inventory says `none`); each inventory radar's check is `ok`; every `services.*` check is `ok`; `apps.nodered.schema` is `ok`; the `config.*` checks are `ok` or `warn`, never `error`. On failure print the check ids and details only.
- `test_viewer_gets_403_on_every_action`: `POST /services/frigate.service/restart`, `/status/rescan`, `/system/reboot`, `/system/power-off`, `/time` → 403; `GET /system/diagnostics` → 403; `GET /status`, `/services`, `/system/info`, `/time` → 200.
- `test_tm_internal_is_hidden_behind_the_proxy`: admin cookie on `/nr/tm-internal/status` → 404.
- `test_tm_internal_needs_the_token_on_the_pi` (`pii_free`): on the Pi, `curl` to `127.0.0.1:1880/tm-internal/status` → 401; with the token header → 200 and JSON with `schema_version` an integer (the token never printed).
- `test_diagnostics_has_no_secret_value` (`pii_free`): admin downloads diagnostics; none of the five secrets' values, nor the broker password from `node-red-tm.env`, appear in the text; the text contains `== Status ==`.
- `test_time_state_matches_timedatectl`: `GET /time`'s `timezone` equals `timedatectl show -p Timezone --value` on the Pi, and `ntp.enabled` matches `NTP`.

`test_services.py`:
- `test_polkit_allows_only_the_listed_actions`: as the code owner (`runuser`), `busctl … CanReboot` → `yes`, `timedatectl set-ntp <current>` → rc 0; `systemctl start sshd.service` still refused (existing test covers units); `loginctl terminate-user root` refused.
- `test_tm_control_has_the_video_group`: `systemctl show -p SupplementaryGroups tm-control.service` contains `video`; `GET /system/info`'s `throttled` isn't null.

`test_disruptive.py`:
- `test_restart_from_the_control_app`: read `frigate.service`'s `InvocationID`; admin `POST /services/frigate.service/restart` → 202; within 60 s the unit is `active` with a new `InvocationID`; `wait_until_ready`.
- `test_timezone_change_restarts_the_containers`: read the current zone; `POST /time {"timezone": "Pacific/Auckland"}` (or `UTC` if that's current) → `restarting` lists the pod and revproxy; within 60 s `timedatectl show -p Timezone` is the new zone, `traffic-monitor.service` and `revproxy.service` have new `InvocationID`s, and `sudo journalctl -u node-red-tm -n 5 -o short` shows timestamps in the new zone; then restore the zone the same way.
- `test_set_time_from_the_api` (`pii_free`): `POST /time {"ntp": false}`; `POST /time {"time": <now + 120 s>}`; `date +%s` on the Pi is within 5 s of that; `POST /time {"ntp": true}` restores (the unit re-syncs when it has a time source; assert only that `ntp.enabled` is true).
- `test_schema_behind_shows_an_error` (`pii_free`, ask first): stop `node-red-tm.service`; as the code owner run `python3 -c` to set `PRAGMA user_version = 0` on `tmdb.sqlite`; start the unit (`ExecStartPre` re-applies `0001_baseline.sql`, which fails on the existing tables and rolls back; Node-RED starts anyway); `apps.nodered.schema` becomes `error` with `journalctl` in its detail within 30 s; restore `user_version` to the newest migration's number with the unit stopped, start it, and check the check is `ok` again.
- `test_reboot_from_the_control_app` (ask first): admin `POST /system/reboot` → 202; the host goes away and comes back; `wait_until_ready`; `test_no_crash_restarts` stays 0 for tm-control and revproxy.

- [ ] **Step 2: Open a check, deploy, and run the whole suite**

```bash
$T check start --host <host> --pr <n> --title "tm-control M3: status and system"
$T deploy <host> --on-pi
$T run <host> -- 'systemctl is-active tm-control.service revproxy.service frigate.service node-red-tm.service go2rtc_server.service'
$T run <host> -- 'sudo journalctl -u tm-control.service -b --no-pager -o cat | tail -20'
$T test <host>
```
Expected: the deploy adds `TM_INTERNAL_TOKEN` to `node-red-tm.env` (check with `sudo grep -c '^TM_INTERNAL_TOKEN=' …`, never printing the value), restarts Node-RED and tm-control, rebuilds the revproxy image with the new UI; all units active; every non-disruptive test passes, including M1's and M2's.

- [ ] **Step 3: Pull a cable and watch the layers**

With the maintainer: unplug the radar (and, if the unit has one, the Coral USB), `POST /status/rescan` or press Re-scan, and record which check went `error` and what it said; plug it back in, re-scan, restart the named unit from the Status page, and record that the check is `ok` again. Then `$T test <host> -- -k status` to confirm. Record an item per Review Focus line this covers (1, 2, 5, 6).

- [ ] **Step 4: Single-tag runs**

```bash
$T deploy <host> --on-pi -- -t node-red-tm
$T deploy <host> --on-pi -- -t tm-control
$T test <host> -- -k "web or services"
```
Expected: the token survives both runs and the status page keeps working. Record an item.

- [ ] **Step 5: Disruptive tests**

Ask first. `$T test <host> --disruptive -- -k "restart_from or timezone or set_time"`, then `-k schema_behind`, then, if the person agrees, `-k reboot_from` and the full `--disruptive` set. Expected: pass; after the reboot `test_no_crash_restarts` is 0 for tm-control and revproxy.

- [ ] **Step 6: Record what needs a person**

```bash
$T check item "Status page at phone width: every group renders, a restart from the page works, the health line on the home page matches" manual
$T check item "Unplug the radar: the radar check fails with the right layer; re-plug, re-scan, restart Node-RED: ok again" manual
$T check item "Unit with a Coral USB in use shows as present (18d1:9302)" manual --note "skip on a unit without one"
$T check item "Set from this browser, with the unit offline (Wi-Fi off): the device time matches the phone within a few seconds" manual
$T check item "Time zone change: Frigate's and Node-RED's log timestamps and the Dashboard's times follow the new zone" manual
$T check item "Diagnostics: Download and Copy work on a phone over plain HTTP; the text holds no secret" manual
$T check item "Reboot and Shut down ask for confirmation; Reboot comes back; Shut down turns the unit off (power-cycle it)" manual --note "ask before shut down"
$T check item "Renamed Frigate camera trips the cameras contract check; renamed back, it's ok" manual
```
When the person reports back, `$T check reopen <run dir>` and re-record each as `pass` or `fail`.

- [ ] **Step 7: Close the check and commit**

```bash
$T check status && $T check end
git add script/devpi
git commit -m "Add device tests for the status report, the control app's actions, the internal endpoint, and the time and schema checks" -m "<trailer block>"
```

- [ ] **Step 8: Open the PR**

Target `feature/tm-control-core-login/201` while #261 is open (retarget to `dev` after it merges); branch `feature/tm-control-status-system/201`. Body from the template:
- **Summary:** M3 of the tm-control platform spec: the status and configuration checks, restart from the page, the Device page with diagnostics, reboot and shut down, and the Date and time page. Link the spec, the plan (the public copy of this file under `design/plans/`), and `#201`. `Closes #217`.
- **Docs:** the Task 10 pages.
- **Testing:** the check's checklist with placeholders for names and addresses; the off-device counts; the Task 1 spike; the fake-mode click-through.
- **AI assistance:** filled in.
- **Release notes:**
  - The home page shows the device's health, and a Status page lists what's wrong and how to fix it. Administrators can restart Frigate, Node-RED, the camera streams, and the web proxy from there.
  - A Device page shows versions, storage, temperature, and power state, with a diagnostics text to send when asking for help. Secrets are stripped from it.
  - Administrators set the date, time, and time zone from the Date and time page, including from a phone with no internet.
  - Administrators can reboot or shut down the device from the Device page.
  - The status page warns when the database schema is behind after a failed migration.
  - A Coral USB Accelerator is now detected on installer re-runs after its firmware has loaded (#217).
  - `config.yml`'s unused `time:` settings are gone from new installs; the time zone is set at install and on the Date and time page.
  - Upgrade with a full `tmsetup.sh` run, which adds the internal token Node-RED and the control app share.

---

## Self-review notes (2026-10-28)

- **Spec coverage.** v1 scope 2 (health summary): Task 9. Scope 3 (services, apps, hardware, contracts): Tasks 3, 6, 7. Scope 4 (system info, diagnostics): Task 4. Scope 5 (date and time, set from browser, zone, NTP, restart): Task 8. "Node-RED state" and the schema check: Tasks 5 and 6. "Hardware changes" layers and re-scan: Tasks 2 and 7. Polkit time and reboot: Tasks 4 and 8. Verification → M3 items: Task 11. Not covered on purpose: SSE (decision 6), fix actions beyond restart and re-scan (the detector feature spec), `ReadWritePaths` (nothing writes).
- **Type consistency.** `CheckGroup`, `Check`, `Fix`, `Report` from Task 2 are used by name in Tasks 3 to 9; `restart_unit` (Task 3) is used by Task 8; `nodered.status`/`nodered.config` and the Frigate adapter (Task 6) are consumed by Task 7, which tests its checks with recorded dicts.
- **Proportion.** The plan is about as long as the M2 plan and shorter than the code it describes; the check tables are the decisions an implementer can't make alone.
