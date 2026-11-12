---
description: How the control app (tm-control) is built: its backend modules, the login check nginx runs for every app, the status checks, root jobs and polkit, fake mode, and how to add a module or a check.
---

# tm-control

`tm-control` is the device's control app: the home page, setup, the login in front of every app, the device's accounts, and the Status, Device, Date and time, Detection, Cameras, and Location pages. [Control app and login](../use/control-app.md), [Check and fix the device](../use/device-health.md), [Choose the detection model](../use/detection.md), [Cameras](../use/cameras.md), and [Places and location](../use/location.md) describe it from the operator's side. This page is for changing it.

It has three parts, all in the repository's [`tm-control/`](https://github.com/glossyio/traffic-monitor/tree/main/tm-control) folder:

| Folder | What it is | How it reaches the device |
|---|---|---|
| `backend/` | The Python app (FastAPI) and the `tm-control` command | Copied root-owned to `/usr/local/lib/traffic-monitor/tm-control`, with its own virtual environment, and run as `tm-control.service` |
| `ui/` | The web pages (Vue 3, Vuetify 3, TypeScript, Vite) | Built into the reverse proxy's image and served by nginx at `/` |
| `jobs/` | Scripts for the few things that need root | Copied root-owned to `/usr/local/libexec/traffic-monitor/` and run by fixed systemd units |

## How it runs

`tm-control.service` runs on the host, not in the pod, so the login keeps working when Podman doesn't. It runs as the code owner (default `tmadmin`), never as root, in a systemd sandbox, and listens on `127.0.0.1:8090` only. nginx is the only way in from the network.

It reads two things the installer writes, and keeps one database of its own:

* `/etc/traffic-monitor/secrets/`: two kinds of secret. Five are generated once on the device: the session key, Frigate's proxy secret, the Node-RED editor's token key, the token for Node-RED's internal status, and go2rtc's RTSP password. Four are entered by an administrator: the ThingsBoard access token and the Plate Recognizer token and license key on the Device page, and the Frigate+ API key on the Detection page. The installer creates them empty, and only the `set-secret` job writes them. `GENERATED_SECRETS` and `ENTERED_SECRETS` in `core/secrets.py` match the role's `tmsetup_secret_names` and `tmsetup_entered_secret_names` (a test keeps each pair equal), `DEVICE_SECRETS` is the two together, and the diagnostics redact the value of each. An empty file means the secret isn't set. The `secrets` module (`GET /secrets`, and `POST` and `DELETE /secrets/{name}`) lists what is set, never a value, and starts the job.
* `/etc/traffic-monitor/manifest.json`: what the installer installed and found, such as the version, the installing user, the proxied apps, the home page's colors, and, on a device with a Coral, the model section the installer gives Frigate (`frigate.coral_model`, from the role's `tmsetup_frigate_coral_model`), which the Detection page puts back.
* `/var/lib/tm-control/state.sqlite`: users, the claim and the setup code's hash, license acceptances, job records, an audit log, and the Location page's places (`surveys`, `survey_bearings`, and `survey_corrections`). Numbered migrations in `core/state.py` create and update it, recorded in `PRAGMA user_version`. Never change a migration that has shipped; add the next one.

While the device is unclaimed, the installer keeps the setup code in a root-only file, `/etc/traffic-monitor/setup-code`, and hands it to `tm-control set-setup-code` on every run, which stores only its hash. The installer's command-line steps run as the code owner, and `sudo tm-control reset-admin` drops to that user after writing a new code file, so root never writes the database.

## The login check

nginx checks every app path with `auth_request` before it proxies the request. Each app's location file includes one of two snippets, `auth-viewer.conf` (any logged-in user) or `auth-admin.conf` (administrators), which send a subrequest to tm-control's `GET /api/v1/auth/verify`:

```text
browser ──GET /frigate/──▶ nginx (port 80)
                             │  auth_request /_auth  (internal location)
                             │    X-Original-URI: /frigate/
                             │    X-TM-Required-Role: viewer   (admin for /_auth_admin)
                             │    Cookie: tm_session=…
                             ▼
                           tm-control 127.0.0.1:8090  /api/v1/auth/verify
                             │
       ┌─────────────────────┼──────────────────────────┬──────────────────────────┐
       ▼                     ▼                          ▼                          ▼
  200 + identity       401 + X-TM-Redirect         403 forbidden        no answer (down, timeout)
  headers               (/setup, /login?next=…,     nginx returns 403    nginx returns 503 with
       │                 /welcome, or /waiting)                          the rescue page
       │                nginx answers 302
       ▼
  nginx proxies to the app, adding the headers that app needs
```

A 200 carries `X-TM-User`, `X-TM-Role`, `X-TM-Frigate-Secret`, and, for administrators, `X-TM-NR-Token`. The snippets copy them into nginx variables, and each app's location passes on what that app understands:

| App | What nginx sends it |
|---|---|
| Frigate (`127.0.0.1:8971`) | `X-Forwarded-User` and `X-Forwarded-Groups` (the role), and `X-Proxy-Secret`, which Frigate checks against `FRIGATE_PROXY_AUTH_SECRET` in `frigate.env`. nginx always sends both forwarded headers, because Frigate serves a request with only the secret as its default role, and it blanks `Remote-User`, `Remote-Groups`, and `Remote-Role`, which Frigate would also trust. Frigate's own login is off (`auth: enabled: false`). |
| Node-RED editor (`/nr/`) | `x-tm-nr-token`, a short-lived token that `settings.js` checks with `TM_NR_TOKEN_KEY` from `node-red-tm.env`. The editor has no users of its own. |
| Dashboards, camera feeds, Cockpit, data downloads | No identity: nginx's check is the whole gate. Cockpit then asks for its own Raspberry Pi login. |

A few rules keep the check sound:

* Only nginx's internal `/_auth` and `/_auth_admin` locations may call verify. A `location ^~ /api/v1/auth/verify` returns 404 to the network, the `/api/` location clears `X-TM-Required-Role`, and verify answers 404 without that header.
* The check is always a `GET` without a body, and without the `Authorization` header, so Cockpit's Basic login never reaches tm-control.
* Sessions last 7 days and roll: verify and the API re-issue a cookie that's more than a day old, and the snippets pass verify's `Set-Cookie` on to the browser. An app location must not set an `add_header` of its own, or it would drop that cookie.
* Only the check's own failure, which `auth_request` turns into a 500, becomes the rescue page (`error_page 500 =503 /unavailable.html`). An app's own 502 or 504 stays as it is.

The Node-RED token is `base64url(JSON {"u", "r", "exp"})`, a dot, and `base64url(HMAC-SHA256(key, first part))`, without padding, valid for 5 minutes. `NodeRedToken` in `backend/tm_control/core/auth.py` mints it, and `verifyProxyToken` in `container/node-red-tm/data/settings.js` checks it. Change both together; `script/tests/test_node_red_settings.py` runs tokens from one through the other.

The rest of the API, under `/api/v1/`, checks the session cookie itself. Every error has one shape, `{"error": {"code", "message", "detail"}}`. A request that changes something must send JSON from a page on the device (a matching `Origin` or `Referer`), or it gets 403.

## Backend layout

```text
tm-control/backend/tm_control/
  app.py         create_app(): loads the state, secrets, manifest, and license agreement, and mounts the modules
  cli.py         the tm-control command: serve, migrate, claim-status, set-setup-code, reset-admin,
                 and for development fake-reset and dump-openapi
  fake.py        fake mode's reset and the OpenAPI dump
  core/          shared rules: auth (passwords, sessions, backoff, setup code, users), csrf, errors, jobs,
                 manifest, migrate (config updates for older installs), secrets, settings, state
  adapters/      the outside world: command (runs an argv list with a timeout and an output cap, never a shell),
                 systemd, timedate, sysinfo, hardware, the apps' HTTP APIs (frigate, nodered, go2rtc), mqtt,
                 redact, yamlfile
  modules/       one folder per feature, each with a router: auth, setup, account, jobs, status, services, apps,
                 hardware, secrets, system, time, detection, cameras, location
```

Rules live in the backend; the UI shows what the API returns and posts what the operator types. `tm-control/ui/README.md` describes the UI's layout and design.

### Root jobs and polkit

tm-control never runs as root and never uses sudo. polkit lets its user do two things, both listed in `tmsetup_tm_control_polkit` in the role's `vars/main.yml`, and nothing else:

* Start, stop, and restart a fixed list of units. tm-control itself isn't on it; restart it with Cockpit or SSH.
* Seven actions: `org.freedesktop.timedate1.set-time`, `set-timezone`, and `set-ntp` for the Date and time page, and `org.freedesktop.login1.reboot`, `reboot-multiple-sessions`, `power-off`, and `power-off-multiple-sessions` for the Device page. The `-ignore-inhibit` variants aren't granted, so tm-control asks logind (`CanReboot`, `CanPowerOff`) first and answers 409 while an inhibitor, such as an update, holds the device up.

A time zone change restarts `traffic-monitor.service` and `revproxy.service` after the response, because the containers bind-mount `/etc/localtime` and keep the old zone until they restart. A time change that moved the clock ahead by more than 20 seconds (`FRIGATE_JUMP_SECONDS` in `modules/time/router.py`), by `set-time` or by NTP while the request watched, restarts `frigate.service` the same way, or at once when a later step of the request fails. Frigate's capture stops on such a step and, from a few minutes, may not recover by itself. A time zone change in the same request restarts the pod instead, which covers Frigate. Each admin action records an audit row. For work that needs root, tm-control writes a request to `/run/tm-control/jobs/<name>.json` and starts `tm-job-<name>.service`, a fixed root-owned oneshot unit. Its script in `tm-control/jobs/` checks the request strictly, does one thing, and deletes the request. tm-control follows the run through the unit and the journal, and `GET /api/v1/jobs/{id}` reports its status and log lines. There are two jobs:

| Job | What it does |
|---|---|
| `system-password` | Sets the installing user's Linux password. It refuses an account that doesn't exist or has uid 0. `tmsetup.sh` also refuses to run as root, but a remote install with `-l root` still records root as the installing user, so the job's own check is the one that counts. |
| `set-secret` | Writes or empties one entered secret. The request holds the secret's name and value. The script accepts only the four names in its own table (`thingsboard_access_token`, `frigate_plus_api_key`, `plate_recognizer_token`, and `plate_recognizer_license_key`), and only an empty value or one that matches that secret's pattern, and it refuses anything else without printing the value. It writes the secret's file, rewrites the secret's `KEY=` lines in `node-red-tm.env`, `frigate.env`, or `plate-recognizer.env`, then restarts the units that read them, in that order. A step that fails leaves the device no worse than before, and the log says which step it was. If a restart fails, the secret is already written, and the next Save runs again. |

`SECRETS` in `tm-control/jobs/tm-job-set-secret` repeats the secrets' patterns (`VALUE_PATTERNS` in `core/secrets.py`) and restart units (`ENTERED` in `modules/secrets/router.py`), because the script imports nothing from tm-control; tests keep them the same.

## Status checks

`GET /api/v1/status` returns a report of check groups, which the Status page shows and the home page sums up in one line. Each module lists its groups in `Module.check_groups`, and the report shows them in `MODULES` order: Services, Apps, Configuration (the apps module's second group), Hardware, Device (from the system module), and Date and time.

A check function takes a `Context` and returns a list of `Check`s, each with an `id`, a `title`, a `status` (`ok`, `warn`, `error`, or `unknown`), a one- or two-sentence `detail` that says what to do, and an optional `fix`:

| Fix kind | The UI shows |
|---|---|
| `restart` | A button, for admins, that restarts `unit` after a confirmation. Make it with `restart_fix()` in `modules/services/units.py`, so every such button reads `Restart <unit title>`. |
| `rescan` | One "Re-scan hardware" button at the end of the group, for admins, which calls `POST /status/rescan`. |
| `link` | A link to `href`, a page in the UI such as `/time` or `/device`. |
| `hint` | `text`, after the detail. |

The runner in `core/checks.py` keeps the page up whatever a probe does:

* Checks never raise. A function that raises, or doesn't finish within the group's 5-second timeout, becomes one `unknown` check that names the exception class or the timeout, never its message, which could hold a command's output or a secret.
* All groups run at the same time, so a hung app costs about one timeout, not one per check.
* `Context.probe(key, fn)` runs `fn` once per report for every check that asks for the same key. Frigate's config and stats, Node-RED's status, `config.yml`, the unit states, and the bus listings are each read once.
* The report is cached for 5 seconds; `POST /status/rescan` (admins) runs it again at once.

Details name cameras, zones, radars, units, and config keys, never a URL, a password, or a command's output. The one exception is Frigate's log, which two checks quote:

* The Apps group's Frigate check is an error when `/api/config` says `safe_mode: true` (`probes.frigate_safe_mode`), which is how Frigate answers a config that doesn't validate: it starts with no cameras, so `config.cameras`, `config.zones`, `apps.frigate.cameras`, and `apps.go2rtc.streams` have nothing to compare, report `unknown`, and point at this check. The detail quotes Frigate's validation messages.
* The Configuration group's Frigate+ check (`config.frigate_plus`) reads `model.path` from Frigate's `config.yml` on disk, whether the `frigate_plus_api_key` secret is set, and whether a `plus://` model's two files are in `model_cache`. It warns about a key without a `plus://` model, and is an error for a `plus://` model Frigate can't get or can't use, quoting the log line that says why. Whenever Frigate doesn't answer, whatever systemd says of the unit (in a crash loop it's `active` between crashes), it quotes the traceback's last line without claiming the download caused it, because the journal's tail shows how Frigate stopped, not why; with no such line it's `unknown`. When that line holds Frigate's `Unable to refresh API token` (`REFUSED_KEY`), which Frigate raises for any answer but a token, the detail says Frigate+ gave no token for the key, as with a wrong key or an unreachable Frigate+, and links to the key form; both errors end with the ways out in `WAYS_OUT`. When the model's two files are on the device, Frigate loads it without asking Frigate+, so the detail quotes the line without the fetch advice and points at the Apps group's Frigate check. That check quotes the same line, with a link to the diagnostics and a pointer to the Services row's restart, since a crash loop without a `plus://` model has no other check to name its cause. `probes.frigate_journal` reads the current run's messages while the unit is active and either Frigate answers or systemd hasn't restarted it after a failure, and the journal's tail otherwise, where the run that failed left its traceback. A failure restart is `NRestarts` above 0 whose last automatic restart didn't follow Frigate's own exit 143 (`units.last_restart_cause`, from PID 1's journal, as the Services group reads it): after a Save & Restart the counter is 1 while Frigate starts, and the run before the save mustn't be quoted. One of Frigate's own restarts within `RESTART_LOOP_SPACING` (120 s) of the counted automatic restart before it is a loop, not a save (`units.restart_causes`, from PID 1's restart times alone; a hand restart resets the count, so a single restart is never a loop): the Services row warns with the counts, the Apps group's Frigate check says Frigate keeps stopping itself while it isn't answering, and the probe reads the tail. The restart Frigate's watchdog makes when a detector process dies is the known case; tm-control reads no log line for it.

Both quote only the `Message :` lines of Frigate's validation block and the last line of a traceback, through `redact()` in `modules/apps/checks.py`, which replaces anything shaped like a Frigate+ key with `<key>` and cuts each line to `MESSAGE_MAX` characters. `traceback_last_line` strips journalctl's prefix and the timestamp Frigate's s6 supervisor puts on each line (`S6_TIMESTAMP`) before it matches an exception line. It quotes nothing when s6's `[INFO] Service Frigate exited with code 0` line (`ORDERLY_EXIT`; a kill by SIGTERM counts too) comes after the last exception line. Frigate logs two tracebacks of its own while it stops for a Save & Restart, and the unit stays active until its container has halted, so the probe reads the run that is stopping; a crash of Frigate's own process has a nonzero exit line, so that crash loop still quotes; Frigate's watchdog restarts it the same way as a save when a detector process dies, so that loop quotes nothing, and is caught by its cadence instead.

The Hardware group's accelerator check claims only the host side ("Ready on the host and passed to Frigate"). Frigate's stats keep a dead detector process's pid and its starting 10.0 ms, so whether detection works is Frigate's to report, through the restarts above.

### Add a check

1. Write the function in the module's `checks.py`. Read through `context.probe` anything another check also reads, and run commands through `adapters/command.run` with an argv list, a timeout of at most 4 seconds, and an output cap. HTTP reads go to `127.0.0.1` only, with a 3-second timeout.
2. Add it to the module's `CheckGroup`, or make a new group and list it in the module's `check_groups`.
3. Test each status it can return, with synthetic data. The backend tests' `device_client` fixture builds the app as on a device (fake mode off, synthetic secrets, the test manifest), with the apps not answering and the hardware absent, so an API test runs the real code with only the outside world stubbed.
4. Add the check to `tests/fixtures/status_fake.json` if fake mode should show a new status or kind of fix.

### Node-RED's internal status

Node-RED answers `GET /tm-internal/status` on `127.0.0.1:1880` with its uptime, the errors from its last `config.yml` load, the database's schema version, and each radar's port and last reading. A flow on the `init-config` tab serves it. It checks the `X-TM-Internal-Token` header against `TM_INTERNAL_TOKEN` in `node-red-tm.env`, which the installer fills from the `node_red_internal_token` secret on every run, and refuses every request when that variable is unset or empty. `adapters/nodered.py` reads it, and calls the Location module's endpoints on the same port with the same token (see [The Location module](#the-location-module)). nginx answers 404 for `/nr/tm-internal/` in any letter case, because Node-RED matches paths whatever their case. The JSON fields are a contract between the flow and the checks: `script/tests/test_node_red_flows.py` and `tests/fixtures/nodered_status.json` pin them.

### The Detection module

The `detection` module serves the [Detection page](../use/detection.md). It reads Frigate's running config and `config.yml`, and the files in Frigate's `model_cache`. Its routes, under `/api/v1/models`:

| Route | Who | What it does |
|---|---|---|
| `GET /models` | Any logged-in user | The detector, the running model, the models in `model_cache` with their files, hashes, and each one's labels, and the two label lists for the running model |
| `PUT /models/upload/{filename}` | Admin | Streams a model file, a sidecar, or a zip or tar.gz of both into `model_cache` |
| `POST /models/{name}/sidecar` | Admin | Writes the sidecar for a model file that has none, from the form's values |
| `POST /models/{name}/use` | Admin | Sets Frigate's `model:` section to the model, then restarts Frigate |
| `POST /models/default/use` | Admin | Puts back the installer's model, or removes the section on a device without a Coral |
| `GET /models/{name}/package` | Admin | A zip of the model's two files and `SHA256SUMS` |
| `GET /models/{name}/file` | Admin | The model file alone, for a model with no sidecar to package, such as the installer's |
| `DELETE /models/{name}` | Admin | Removes the model's files, unless it runs or is the installer's or Frigate's own default |

The module writes only inside `model_cache` and Frigate's `config.yml`, plus its own state directory. Every `model_cache` write goes through a descriptor of the directory opened with `O_NOFOLLOW`, after `valid_name` has checked the name; `config.yml` is edited by its path through `RoundTripFile`, as `tm-control migrate` edits config files (a backup, an atomic replace, the owner kept). When Frigate answers in safe mode, which it enters when its config fails to validate, it runs a stand-in config, so `GET /models` reads the detector and the running model from `config.yml` and says `frigate_safe_mode`; a Use still goes through Frigate's API, which validates the whole config. The caps are 100 MB for a request and a model file, 2 MB for a sidecar, 3 archive members, and 512 MB of free storage left afterwards. Use goes through Frigate's config API, which checks the whole config, and edits `config.yml` itself, with a backup, only when Frigate doesn't answer. Both end in a restart of `frigate.service`.

Uploads need two things from the edge. nginx has its own location, `^~ /api/v1/models/upload/` in `tm-control-api.conf.j2`, with `client_max_body_size 100m` and `proxy_request_buffering off`, so the body streams to tm-control instead of being buffered. Because of that, tm-control reads the rest of a refused upload before it answers, so nginx can pass the answer on rather than a 502. The upload body is `application/octet-stream`, which the cross-site check in `core/csrf.py` admits along with `application/json`, because the check still requires a same-origin request. Every other `/api/` path keeps nginx's default body limit.

The sidecars are a Frigate+ model record's JSON. The module reads only the fields the page shows and keeps the whole file as it was uploaded, so a download returns it unchanged. It never puts a record's other fields in an answer, a log line, or an audit row.

### The Location module

The `location` module serves the [Location page](../use/location.md). It's for admins only, because the places hold exact coordinates: every route under `/api/v1/surveys` takes `require_admin`. The places are in `state.sqlite`; the place in use is also in Node-RED's `config.yml`, under `deployment:`, which is what Node-RED reads. tm-control never opens `tmdb.sqlite`, and Node-RED never opens `state.sqlite`.

| Route | What it does |
|---|---|
| `GET /surveys` | The place in use, the precision, the enabled sensors and their bearings, the places with Node-RED's usage counts, and the deployments recorded before any place. Runs the reconcile first. |
| `POST /surveys`, `PATCH` and `DELETE /surveys/{id}` | Plan a place, edit a planned one, delete one that isn't in use |
| `POST /surveys/{id}/deploy` | Writes the place and every enabled sensor's bearing into `config.yml`, then asks Node-RED every second, for up to 20 seconds, for the new deployments. `reloaded: false` when they didn't appear, which isn't an error: the file is written. |
| `PUT /surveys/precision` | Writes `database_precision`; with `round_stored`, also has Node-RED round the rows already stored |
| `POST /surveys/{id}/location`, `POST /surveys/{id}/deployments/{deployment_id}/bearing` | Corrections: the place's point, re-rounded in Node-RED's rows, or one deployment's bearing; each records a row in `survey_corrections` |
| `GET /surveys/{id}/deployments`, `GET /surveys/{id}/events` | A place's deployments, and its event count and span, from Node-RED |
| `POST /surveys/import` | Planned places from a CSV: a dry run lists what it read, and the import creates all or none |

The rules:

* `coordinates.py` holds them: survey ids (`<8 hex>-si`, from `secrets.token_hex(4)`), typed coordinates quantised to five decimal places half away from zero on their decimal text, and the stored ones rounded half away from zero, as SQLite's `ROUND` and the flows' `toFixed` do. The UI's `coordinates.ts` only checks a pasted pair before it sends; the API's answer wins.
* `config.py` edits `config.yml` through `RoundTripFile`, with `mapping_indent=4`, so comments, key order, and quoting stay. Each save keeps a backup beside the file, of which the newest 10 stay, and replaces it atomically. The backups of Frigate's `config.yml` from the Detection page's file fallback follow the same limit. Pruning touches only these `config.yml.<UTC stamp>.bak` names. It leaves the Ansible backups from `tmsetup.sh`, a copy made by hand, and every `<file>.<UTC stamp>.migrate.bak` from `tm-control migrate`, which can hold the only copy of what the migration removed. A file changed since it was read is a `ConcurrentEditError`, which the API answers with 409 `config_changed`.
* `reconcile.py` keeps the store and the file in step. It runs at claim, on every `GET /surveys`, and before the checks of every status report that isn't the cached one (`StatusCache`'s `prepare`), under `app.state.reconcile_lock`, which every write also holds. The status report waits at most two seconds for that lock, skips the run when a write holds it longer, and logs any error by its class name. Once per device it makes the first place: on a fresh device (no coordinates, no `survey_id`, and no backup), **First location** with no coordinates; on an upgraded one, a used place for each survey in the newest `tmdb-v0-*` or `tmdb-v1-*` backup in `node-red-tm/db/backup/`, opened read-only and immutable, then the place in use from the file. It waits until Node-RED reports schema version 2. An unreadable backup is skipped with one log line. Every run after that follows hand edits of the file, as [Edit the location by hand](../configuration/node-red-config.md#edit-the-location-by-hand) describes.
* No coordinate, description, or reason is logged, audited, or put in an error message. Audit rows carry the survey id, and a deployment id or the precision.

The module calls six Node-RED endpoints, besides `/tm-internal/status`, on `127.0.0.1:1880` with `X-TM-Internal-Token`. Flows on the `init-config` tab serve them, and `script/tests/test_node_red_flows.py` pins them:

| Endpoint | What it does |
|---|---|
| `GET /tm-internal/deployments?survey_id=<id>` | A survey's deployment rows |
| `GET /tm-internal/surveys/usage` | First start, last end, and open and total deployment counts for each survey, and for the rows with no survey |
| `GET /tm-internal/surveys/<id>/events` | A survey's event count, and its first and last event |
| `POST /tm-internal/deployments/precision` | Rounds every stored row to a coarser precision, or clears the coordinates for `none` |
| `POST /tm-internal/surveys/<id>/location` | Rewrites a survey's stored coordinates from a new point, each row at its own precision |
| `POST /tm-internal/deployments/<id>/bearing` | Rewrites one deployment's bearing |

`tm-control migrate --node-red-config`, run by the installer, also brings `deployment:` up to date: it adds `database_precision: '2'` where it's missing, and removes `lat` and `lon` from a sensor's own `deployment:` block. The Location check (`location` in `modules/apps/contracts.py`) checks the same keys at run time.

### The Cameras module

The `cameras` module serves the [Cameras page](../use/cameras.md). It's for admins only, like the Location page, because it's a settings page: every route under `/api/v1/cameras` takes `require_admin`. It owns the `sensors.cameras` entries in Node-RED's `config.yml` and writes no other config file, so never Frigate's. The one other thing it writes is the places' bearings (`survey_bearings` in `state.sqlite`) when an entry is re-keyed. It never opens `tmdb.sqlite`.

An entry's key is the camera's neutral name, the one the flows record and share. Its optional `frigate_camera` is Frigate's name for it, and without one the key is Frigate's name too, so installs that never used the page need no migration. `names.py` makes the keys, `camera_<N>_<6 hex>`, from `secrets.token_hex(3)` and redraws a token a neutral name in the file already ends with. The module never logs, audits, or puts in an error message Frigate's name: audit rows carry the neutral name.

| Route | What it does |
|---|---|
| `GET /cameras` | Whether Frigate answers or is in safe mode, the rows, the unit's radars with their state, and whether the Plate Recognizer add-on is installed |
| `POST /cameras` | Adds an entry under a new neutral name for a Frigate camera that no entry points at |
| `PUT /cameras/{name}` | Sets `enabled`, `camera_radar` (a radar of the unit that has an entry under `sensors.radars`, or null), and `plate_recognizer` |
| `POST /cameras/{name}/frigate-camera` | Points the entry at another Frigate camera: the rename |
| `POST /cameras/{name}/neutral-name` | Re-keys an entry to a new neutral name, keeping its position, comments, and sub-keys, and renames its `survey_bearings` rows in every place, the file first |
| `DELETE /cameras/{name}` | Removes an entry whose Frigate camera is gone, or that repeats another entry's |

The rules:

* `state.py::compare` is the one comparison of Frigate's cameras, read unfiltered from its running config (`enabled: false` is Off), with the file's entries. It gives a row for each entry in file order, then one for each Frigate camera that no entry points at, and it's what the page and the `config.cameras` and `config.zones` checks use, so they can't disagree. When Frigate doesn't answer or is in safe mode, every entry is `unknown`, never `absent`. The page, the checks, and the diagnostics all read the entries through `camera_entries()` in `modules/location/config.py`.
* Every write holds `app.state.reconcile_lock`, loads `config.yml` through `NodeRedConfig`, compares against Frigate again, and refuses with 409 `cameras_changed` when the rows no longer match what the admin confirmed, or `config_changed` when the file changed. Except `PUT`, they need Frigate to answer, and refuse with 409 `frigate_unavailable` otherwise.
* `NodeRedConfig`'s camera methods (`add_camera`, `set_camera`, `point_camera`, `rename_camera`, `remove_camera`) edit through `RoundTripFile`, as the deployment edits do, so comments, order, and quoting stay.
* Copy diagnostics replaces every Frigate camera name that differs from its entry's key, and every Frigate camera no entry points at, with `redact_words` (whole words, longest first), the way it replaces a secret. It reads the names from the file, Frigate's running config, Frigate's config file (`adapters.frigate.config_file`, which still names a camera while Frigate is down or in safe mode; a file that can't be read is skipped), and the `config.yml` backups beside the file. `check_groups` text may name Frigate's cameras, because the Status page is behind the login.

Node-RED gets the mapping from "init config defaults" (the `init-config` tab), which sets three globals after everything that can throw, so a rejected load leaves the old ones: `frigate_cameras`, a map from Frigate's name to the key; `camera_labels`, each key's label for the dashboard pickers, `<key> (<Frigate's name>)` when the two differ; and `tm_warned`, which is reset on every load so a warning is logged once per config load: one for events from cameras no entry points at, which names none of them, and one for each radar name a camera is paired with that `config.yml` lacks. They're their own globals, not part of `global.config`, because `config_tm` uploads the config. "append config" looks each event's camera up in `frigate_cameras` and sets it to the key before anything reads it, so the `events` row, `tm/event` and `tm/events`, ThingsBoard, and Plate Recognizer carry only the key. An event from a camera the map lacks is dropped with one warning, and a `camera_radar` that names no radar records the event without one.

### What the sandbox allows

`tm-control.service` runs with `ProtectSystem=strict`, `RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6`, and `SupplementaryGroups=systemd-journal video`. It writes its state and runtime directories and two config directories under the code directory (`ReadWritePaths`): Frigate's, `frigate/config`, for the models the Detection page manages, and Node-RED's, `node-red-tm/config`, for the `config.yml` the Location page writes. The rest of the system is read-only to it. The sandbox also shaped the probes:

* No netlink socket, so `lsusb` can't start. The Coral USB check reads the vendor and product ids from `/sys/bus/usb/devices` instead, and `ss` falls back to reading `/proc/net` for the MQTT broker's port.
* `vcgencmd get_throttled` needs the `video` group to open `/dev/vcio_gencmd`. Without it, the power check says to rerun the installer.
* The HEVC decoder check compares `/dev/rpi-hevc-dec` with the media device whose `/sys/bus/media/devices/mediaN/model` names the decoder.
* `timedatectl show` prints its times as local strings; tm-control reads the clock itself.
* tm-control never writes the secrets directory; the `set-secret` job does.

## Run it on a laptop

Fake mode runs the whole app without a Pi: it uses the test manifest, fixed secrets that aren't secret, a job runner that pretends, a clock in memory for the Date and time page, a status report from `tests/fixtures/status_fake.json`, whose groups show every status and kind of fix, a fake Node-RED for the Location page, and a fake Frigate with a second camera, `oak_ave_tele`, that no entry in the seeded `config.yml` points at, so the Cameras page's actions work. Its state goes in `./.tm-control-fake/`. From the repository root, in the dev environment from [Contributing](contributing.md):

```bash
TM_CONTROL_FAKE=1 PYTHONPATH=tm-control/backend python -m tm_control fake-reset   # an unclaimed device; prints its setup code
TM_CONTROL_FAKE=1 PYTHONPATH=tm-control/backend python -m tm_control serve        # the backend on 127.0.0.1:8090
cd tm-control/ui && npm ci && npm run dev                                         # the UI on http://localhost:5173
```

Fake mode seeds `.tm-control-fake/node-red-tm/config/config.yml` from `tests/fixtures/node_red_config_ok.yml` (a camera and a radar, and a `deployment` block at 45.0, -122.0 with no survey id), and keeps it, with whatever the app wrote to it, until the next `fake-reset`. Its Node-RED (`FakeNodeRed` in `fake.py`) keeps deployment rows in memory and runs the deployment engine's rules on them whenever that file changes, so deploys, corrections, and hand edits of the file behave as on a device; after a restart of `serve`, only the place in use has deployments. Its backup directory is empty, so there's nothing to import. Fake mode also seeds `.tm-control-fake/model_cache` with two synthetic model pairs and the installer's model file, and keeps the model its fake Frigate runs in `.tm-control-fake/running-model`; Use there changes that file and restarts nothing. In fake mode the API's interactive docs are at `/api/v1/docs`. `tm-control/ui/README.md` has the commands for building and testing the UI in the same Node image the device uses.

Every change to the API regenerates the UI's typed client in the same commit, so each commit's tests pass:

```bash
PYTHONPATH=tm-control/backend python -m tm_control dump-openapi > tm-control/ui/src/api/openapi.json
(cd tm-control/ui && npm run api:generate)   # writes src/api/schema.d.ts
```

Run the backend's tests with the rest of the off-device tests:

```bash
.venv/bin/python -m pytest tm-control/backend/tests script/tests container/node-red-tm/schema/tests
```

## Add a module

A feature is one backend module and, if it has pages, one UI module.

1. **Backend:** add `backend/tm_control/modules/<name>/` with a `router.py` (an `APIRouter`) and an `__init__.py` that makes `module = Module("<name>", router)`, with `check_groups=` if it has status checks. Add it to `MODULES` in `modules/__init__.py`. Endpoints take `current_user` or `require_admin` from `modules/auth/deps.py`, and raise `ApiError` for anything the operator should see.
2. **State:** if it needs tables, add the next migration in `core/state.py`.
3. **UI:** add `ui/src/modules/<name>/` with its pages and an `index.ts` that lists its routes and menu entries, and add it to `ui/src/modules/index.ts`. Regenerate the typed client as the UI's README describes.
4. **Root work:** prefer a polkit action or unit verb on the list. Otherwise add the job's name to `JOB_NAMES` in `core/jobs.py`, its script to `tm-control/jobs/`, its unit to the role's `templates/tm-control/`, and the unit to the polkit list.
5. **A new app behind the login:** add its location file with an auth snippet to `container/revproxy/tm/locations/` and to `tmsetup_revproxy_locations`, and its tile to `APPS` in `modules/system/router.py` and to `ui/src/modules/home/apps.ts`.
