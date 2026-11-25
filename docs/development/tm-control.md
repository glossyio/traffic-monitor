---
description: How the control app (tm-control) is built: its backend modules, the login check nginx runs for every app, the status checks, root jobs and polkit, fake mode, and how to add a module or a check.
---

# tm-control

`tm-control` is the device's control app: the home page, setup, the login in front of every app, the device's accounts, and the Status, Device, Date and time, Network, Detection, Cameras, Location, and About pages. [Control app and login](../use/control-app.md), [Check and fix the device](../use/device-health.md), [Wi-Fi and the hotspot](../use/wifi-hotspot.md), [Choose the detection model](../use/detection.md), [Cameras](../use/cameras.md), and [Places and location](../use/location.md) describe it from the operator's side. This page is for changing it.

It has three parts, all in the repository's [`tm-control/`](https://github.com/glossyio/traffic-monitor/tree/main/tm-control) folder:

| Folder | What it is | How it reaches the device |
|---|---|---|
| `backend/` | The Python app (FastAPI) and the `tm-control` command | Copied root-owned to `/usr/local/lib/traffic-monitor/tm-control`, with its own virtual environment, and run as `tm-control.service` |
| `ui/` | The web pages (Vue 3, Vuetify 3, TypeScript, Vite) | Built into the reverse proxy's image and served by nginx at `/` |
| `jobs/` | Scripts for the few things that need root | Copied root-owned to `/usr/local/libexec/traffic-monitor/` and run by fixed systemd units |

## How it runs

`tm-control.service` runs on the host, not in the pod, so the login keeps working when Podman doesn't. It runs as the code owner (default `tmadmin`), never as root, in a systemd sandbox, and listens on `127.0.0.1:8090` only. nginx is the only way in from the network.

It reads two things the installer writes, and keeps one database of its own:

* `/etc/traffic-monitor/secrets/`: two kinds of secret, and the hotspot's password. Five are generated once on the device: the session key, Frigate's proxy secret, the Node-RED editor's token key, the token for Node-RED's internal status, and go2rtc's RTSP password. Four are entered by an administrator: the ThingsBoard access token on the Sharing page, the Plate Recognizer token and license key on the Device page, and the Frigate+ API key on the Detection page. The installer creates them empty, and only the `set-secret` job writes them. `GENERATED_SECRETS` and `ENTERED_SECRETS` in `core/secrets.py` match the role's `tmsetup_secret_names` and `tmsetup_entered_secret_names` (a test keeps each pair equal), `DEVICE_SECRETS` is the two together, and the diagnostics redact the value of each. An empty file means the secret isn't set. The `secrets` module (`GET /secrets`, and `POST` and `DELETE /secrets/{name}`) lists what is set, never a value, and starts the job. The hotspot's password, `hotspot_password`, is in neither list: `tm-hotspot-setup` creates it, and writes it again when it adopts a hand-made profile; otherwise only the `network` job changes it. tm-control reads it (`read_hotspot_password` in `core/secrets.py`) for one route, `GET /network/hotspot/password`, which answers admins only.
* `/etc/traffic-monitor/manifest.json`: what the installer installed and found, such as the version, the installing user, the proxied apps, the home page's colors, and, on a device with a Coral, the model section the installer gives Frigate (`frigate.coral_model`, from the role's `tmsetup_frigate_coral_model`), which the Detection page puts back, and `network`, the hotspot's Wi-Fi device, profile name, and address (`wlan0`, `tm-hotspot`, `10.42.0.1`, from the role's `tmsetup_wifi_device`, `tmsetup_hotspot_profile`, and `tmsetup_hotspot_address`), which the Network checks and `tm-control card` read, and `sharing`, the maintainer's upload server and whether the public map choice is live (`maintainer_host` and `public_map_live`, from the role's `tmsetup_sharing_maintainer_host` and `tmsetup_sharing_public_map_live`), which the Sharing page and its checks read, and `map`, where a browser gets the Location page's map from (`style_url`, from the role's `tmsetup_map_style_url`; empty turns the map off), and `update`, the GitHub repository the install came from (`repo`, from the role's `tmsetup_update_repo`) and its channel (`channel`: `stable` for a release, `development` for a version ending in `-dev`, which follows the version). tm-control only passes the map's address on, and fetches nothing.
* `/var/lib/tm-control/state.sqlite`: users, the claim and the setup code's hash, license acceptances, job records, an audit log, the Location page's places (`surveys`, `survey_sensors` with each sensor's `heading_deg`, `pitch_deg`, `height_m`, `view_distance_m`, `measured`, `mount`, and `unconfirmed`, which a move sets on each row that holds any of the four and a save that writes the sensor clears, and `survey_corrections`), and the Sharing page's consents (`sharing_consents`, migration 4). Numbered migrations in `core/state.py` create and update it, recorded in `PRAGMA user_version`. Never change a migration that has shipped; add the next one.

While the device is unclaimed, the installer keeps the setup code in a root-only file, `/etc/traffic-monitor/setup-code`, and hands it to `tm-control set-setup-code` on every run, which stores only its hash. The installer's command-line steps run as the code owner, and `sudo tm-control reset-admin` drops to that user after writing a new code file, so root never writes the database.

## The login check

nginx checks every app path with `auth_request` before it proxies the request. Each app's location file includes one of two snippets, `auth-viewer.conf` (any logged-in user) or `auth-admin.conf` (administrators), which send a subrequest to tm-control's `GET /api/v1/auth/verify`:

```text
browser ──GET /frigate/──▶ nginx (port 80)
                             │  auth_request /_auth  (internal location)
                             │    X-Original-URI: /frigate/
                             │    X-TM-Required-Role: viewer   (admin for /_auth_admin)
                             │    X-Forwarded-For: the browser's address
                             │    Cookie: tm_session=…
                             ▼
                           tm-control 127.0.0.1:8090  /api/v1/auth/verify
                             │
       ┌─────────────────────┼──────────────────────────┬──────────────────────────┐
       ▼                     ▼                          ▼                          ▼
  200 + identity       401 + X-TM-Redirect         403 forbidden        no answer (down, timeout)
  headers               (/setup, /login?next=…,     nginx returns 403    nginx returns 503 with
       │                 /welcome, /waiting, or                          the rescue page
       │                 /admin-only)
       │                nginx answers 302
       ▼
  nginx proxies to the app, adding the headers that app needs
```

A 200 carries `X-TM-User`, `X-TM-Role`, `X-TM-Frigate-Secret`, and, for administrators, `X-TM-NR-Token`. The snippets copy them into nginx variables, and each app's location passes on what that app understands:

| App | What nginx sends it |
|---|---|
| Frigate (`127.0.0.1:8971`) | `X-Forwarded-User` and `X-Forwarded-Groups` (the role), and `X-Proxy-Secret`, which Frigate checks against `FRIGATE_PROXY_AUTH_SECRET` in `frigate.env`. nginx always sends both forwarded headers, because Frigate serves a request with only the secret as its default role, and it blanks `Remote-User`, `Remote-Groups`, and `Remote-Role`, which Frigate would also trust. Frigate's own login is off (`auth: enabled: false`). |
| Node-RED editor (`/nr/`) | `x-tm-nr-token`, a short-lived token that `settings.js` checks with `TM_NR_TOKEN_KEY` from `node-red-tm.env`. The editor has no users of its own. |
| Dashboards, camera feeds, data downloads | No identity: nginx's check is the whole gate. |

A few rules keep the check sound:

* Only nginx's internal `/_auth` and `/_auth_admin` locations may call verify. A `location ^~ /api/v1/auth/verify` returns 404 to the network, the `/api/` location clears `X-TM-Required-Role`, and verify answers 404 without that header.
* The check is always a `GET` without a body, and without the `Authorization` header, so no credential a client sends there reaches tm-control.
* Sessions last 7 days and roll: verify and the API re-issue a cookie that's more than a day old, and the snippets pass verify's `Set-Cookie` on to the browser. An app location must not set an `add_header` of its own, or it would drop that cookie.
* A viewer on an admin path gets a 403, except for a page load: when the request's `Accept` header names `text/html`, verify answers 401 with `X-TM-Redirect: /admin-only`, and nginx turns that into a 302 to a page of the control app that says the app is for administrators and offers **Home** and **Log out**. Scripts, downloads, and anything else that doesn't ask for HTML keep the 403. A client can send any `Accept` it likes; the only difference is a redirect to a page that holds nothing instead of a 403.
* Only the check's own failure, which `auth_request` turns into a 500, becomes the rescue page (`error_page 500 =503 /unavailable.html`). An app's own 502 or 504 stays as it is.

The Node-RED token is `base64url(JSON {"u", "r", "exp"})`, a dot, and `base64url(HMAC-SHA256(key, first part))`, without padding, valid for 5 minutes. `NodeRedToken` in `backend/tm_control/core/auth.py` mints it, and `verifyProxyToken` in `container/node-red-tm/data/settings.js` checks it. Change both together; `script/tests/test_node_red_settings.py` runs tokens from one through the other.

The rest of the API, under `/api/v1/`, checks the session cookie itself. Every error has one shape, `{"error": {"code", "message", "detail"}}`. A request that changes something must send JSON from a page on the device (a matching `Origin` or `Referer`), or it gets 403.

### Download links

Android's sign-in window fetches a download twice: its own request carries the session cookie, then it hands the address to a download helper that sends no cookie. On Android 17 the window is also the only browser that reaches a unit with nothing to set up: any other needs its user to allow the Nearby devices permission first (Android's [local network protection](https://developer.android.com/privacy-and-security/local-network-permission)). So the Data export page asks for a link that passes the check once without the cookie:

1. Just before it starts a download, the page sends `POST /api/v1/auth/download-link` with `{"files": …}`. tm-control answers an administrator with `/storefiles?files=…&tm_token=…`, a random one-time token kept in memory. Anyone else gets an error, and the page falls back to the plain `/storefiles?files=…` address, which still works wherever the browser downloads the file itself.
2. The browser's own request has a session, so verify checks it as usual and leaves the link unused.
3. The helper's request has no session. verify lets it through as the administrator only when the address is exactly `/storefiles` with `files` and `tm_token` and nothing else, on an admin location, within 600 seconds, from the address the link was made for (`X-Forwarded-For`, which the `/_auth` locations set to nginx's own `$remote_addr`), and for the same `files`. The user must still be an administrator with the same sessions, and the current license agreement must be accepted. The answer carries `X-TM-User` and `X-TM-Role` only: no Frigate secret, no Node-RED token, no cookie.

The first request without a session that presents a token spends it, whether or not the rest matched. A login redirect leaves the token out of its `next=`. nginx's access log records the token; the parameter is named `tm_token` so that the diagnostics download hides its value with every other key ending in `token`. Two routes make a link themselves, with the same `DownloadGrants.issue`, and the Sharing page's **Download your data** card uses both: `POST /api/v1/sharing/download` for the whole database (`files=/db/tmdb.sqlite`, the name the Dashboard's download sends), and `POST /api/v1/surveys/database-copy` for the `files` name it also sends Node-RED the list for. Three routes make a download link, and only the Dashboard's asks `download-link`. The two download templates live in `flows.json` (the ui-templates "Button to trigger download request" and "redirect to storefiles URL"), and `script/tests/test_node_red_flows.py` checks that they ask for the same link.

## The home button

Each app is a separate program, so none of them links back to the control app. nginx adds one line to the HTML of the five apps that serve pages (Dashboard 2.0, the legacy dashboard, Frigate, the Node-RED editor, and the camera feeds): `<script src="/home-button.js" defer></script>`, placed before `</head>`. The script draws a home button over the page and puts the device's name in the tab's title. The user-facing description is in [Home page and apps](../use/home-page.md#getting-back-to-the-home-page).

* **The snippet** is `container/revproxy/tm/snippets/home-button.conf.j2`, which sets `sub_filter` and the upstream `Accept-Encoding`, `If-None-Match`, and `If-Modified-Since`. The five app locations include it beside `proxy-common.conf` and their auth snippet. `storefiles` and the control app's own locations don't. The snippet adds no response header, so the rule that an app location sets no `add_header` still holds.
* **The `$tm_page_encoding` map** in `nginx.conf.j2` is why the apps' scripts and data stay compressed. `sub_filter` works only on uncompressed text, so nginx asks the app for an uncompressed answer when the request's `Accept` header contains `text/html`, and passes the browser's own `Accept-Encoding` otherwise. Two maps beside it do the same for `If-None-Match` and `If-Modified-Since`, so an app never answers a page load with a 304 for a copy the browser cached before the button existed. `Accept` is the signal because a browser on plain HTTP sends no `Sec-Fetch-*` headers. An app's own background request for an HTML fragment is treated as a page load; a fragment has no `</head>`, so nothing is added, and the script does nothing the second time it loads on a page.
* **The script** is `tm-control/ui/src/home-button/` (`place.ts` holds the logic as plain functions, `main.ts` the button, `entry.ts` the start). A second Vite build, `vite.home-button.config.ts`, turns it into one file, `dist/home-button.js`, with no Vue or Vuetify in it. The build fails when the file is over 10 240 bytes. nginx serves it from the control app's UI directory with the rest of the site (`no-cache`), and it needs no login to fetch.
* **The device call:** the script asks `GET /api/v1/system/device`, which any logged-in user may read, for `hostname` and the theme's colors. (The control app's own pages take the name from `GET /api/v1/setup/status`, which needs no login.) Without an answer (the control app is restarting, or the session ended), the button is the icon alone, the title stays as the app set it, and the button still goes home. The script, and the pages it adds to, carry no copy of the name made at install.
* **After an app upgrade,** open each app once and look at where the button sits, and run the device tests, which check that each app's page still carries the script line. An app that compresses a page when asked not to would stop the script line from being added. A `Content-Security-Policy` that doesn't allow the control app's own script, or its `/api` fetch, would stop the script or its device call; a same-origin script passes `script-src 'self'`.

## Backend layout

```text
tm-control/backend/tm_control/
  app.py         create_app(): loads the state, secrets, manifest, and license agreement, and mounts the modules
  cli.py         the tm-control command: serve, migrate, claim-status, set-setup-code, reset-admin, card,
                 and for development fake-reset and dump-openapi
  fake.py        fake mode's reset and the OpenAPI dump
  core/          shared rules: auth (passwords, sessions, backoff, setup code, users), csrf, errors, jobs,
                 card (the device's card), manifest, migrate (config updates for older installs), secrets, settings, state
  adapters/      the outside world: command (runs an argv list with a timeout and an output cap, never a shell),
                 systemd, timedate, sysinfo, hardware, network (nmcli and iw, read-only), the apps' HTTP APIs (frigate,
                 nodered, go2rtc), mqtt,
                 redact, yamlfile
  modules/       one folder per feature, each with a router: auth, setup, account, jobs, status, services, apps,
                 hardware, network, secrets, system, time, detection, cameras, location, sharing
```

Rules live in the backend; the UI shows what the API returns and posts what the operator types. `tm-control/ui/README.md` describes the UI's layout and design.

### Root jobs and polkit

tm-control never runs as root and never uses sudo. polkit lets its user do two things, both listed in `tmsetup_tm_control_polkit` in the role's `vars/main.yml`, and nothing else:

* Start, stop, and restart a fixed list of units. tm-control itself isn't on it; restart it with Cockpit or SSH. `tm-job-network.service` is on it for the Network page's changes, `tm-job-network-join.service` for a Wi-Fi join, `tm-network-retry.service` is on it for the Hotspot check's fix, and `FIX_UNITS` in `modules/services/units.py` lists the units like it, which a check's fix may start but the Services list doesn't show; `POST /services/{unit}/restart` accepts them.
* Seven actions: `org.freedesktop.timedate1.set-time`, `set-timezone`, and `set-ntp` for the Date and time page, and `org.freedesktop.login1.reboot`, `reboot-multiple-sessions`, `power-off`, and `power-off-multiple-sessions` for the Device page. The `-ignore-inhibit` variants aren't granted, so tm-control asks logind (`CanReboot`, `CanPowerOff`) first and answers 409 while an inhibitor, such as an update, holds the device up.

A time zone change restarts `traffic-monitor.service` and `revproxy.service` after the response, because the containers bind-mount `/etc/localtime` and keep the old zone until they restart. A time change that moved the clock ahead by more than 20 seconds (`FRIGATE_JUMP_SECONDS` in `modules/time/router.py`), by `set-time` or by NTP while the request watched, restarts `frigate.service` the same way, or at once when a later step of the request fails. Frigate's capture stops on such a step and, from a few minutes, may not recover by itself. A time zone change in the same request restarts the pod instead, which covers Frigate. Each admin action records an audit row. For work that needs root, tm-control writes a request to `/run/tm-control/jobs/<name>.json` and starts `tm-job-<name>.service`, a fixed root-owned oneshot unit. Its script in `tm-control/jobs/` checks the request strictly, does one thing, and deletes the request. tm-control follows the run through the unit and the journal, and `GET /api/v1/jobs/{id}` reports its status and log lines. There are four jobs:

| Job | What it does |
|---|---|
| `system-password` | Sets the installing user's Linux password. It refuses an account that doesn't exist or has uid 0. `tmsetup.sh` also refuses to run as root, but a remote install with `-l root` still records root as the installing user, so the job's own check is the one that counts. |
| `set-secret` | Writes or empties one entered secret. The request holds the secret's name and value. The script accepts only the four names in its own table (`thingsboard_access_token`, `frigate_plus_api_key`, `plate_recognizer_token`, and `plate_recognizer_license_key`), and only an empty value or one that matches that secret's pattern, and it refuses anything else without printing the value. It writes the secret's file, rewrites the secret's `KEY=` lines in `node-red-tm.env`, `frigate.env`, or `plate-recognizer.env`, then restarts the units that read them, in that order. A step that fails leaves the device no worse than before, and the log says which step it was. If a restart fails, the secret is already written, and the next Save runs again. |
| `network` | Changes the Wi-Fi hotspot: on or off, its name, its password, and whether its name is hidden. It also scans for networks, forgets a saved one, sets the order of the saved ones, and passes Switch now and Cancel to the join. See [The Network module and the hotspot](#the-network-module-and-the-hotspot). |
| `network-join` | Tests a Wi-Fi network under a NetworkManager checkpoint, comes back, counts down, and switches to it. See [The Wi-Fi join](#the-wi-fi-join). |

`SECRETS` in `tm-control/jobs/tm-job-set-secret` repeats the secrets' patterns (`VALUE_PATTERNS` in `core/secrets.py`) and restart units (`ENTERED` in `modules/secrets/router.py`), because the script imports nothing from tm-control; tests keep them the same.

## Status checks

`GET /api/v1/status` returns a report of check groups, which the Status page shows and the home page sums up in one line. Each module lists its groups in `Module.check_groups`, and the report shows them in `MODULES` order: Services, Apps, Configuration (the apps module's second group), Hardware, Network, Device (from the system module), and Date and time.

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

Node-RED answers `GET /tm-internal/status` on `127.0.0.1:1880` with its uptime, the errors from its last `config.yml` load, the database's schema version, the size of `tmdb.sqlite` in bytes (`database_bytes`: a whole number from 0 up, or `null` when the file can't be read), each radar's port and last reading, and an `upload` section (see [The Sharing module](#the-sharing-module)). A flow on the `init-config` tab serves it. It checks the `X-TM-Internal-Token` header against `TM_INTERNAL_TOKEN` in `node-red-tm.env`, which the installer fills from the `node_red_internal_token` secret on every run, and refuses every request when that variable is unset or empty. `adapters/nodered.py` reads it, and calls the Location module's endpoints on the same port with the same token (see [The Location module](#the-location-module)). nginx answers 404 for `/nr/tm-internal/` in any letter case, because Node-RED matches paths whatever their case. The JSON fields are a contract between the flow and the checks: `script/tests/test_node_red_flows.py` and `tests/fixtures/nodered_status.json` pin them.

### The Detection module

The `detection` module serves the [Detection page](../use/detection.md). It reads Frigate's running config and `config.yml`, and the files in Frigate's `model_cache`. Its routes, under `/api/v1/models`:

| Route | Who | What it does |
|---|---|---|
| `GET /models` | Any logged-in user | The detector, the running model, the models in `model_cache` with their files, hashes, and each one's labels, and the two label lists for the running model |
| `PUT /models/upload/{filename}` | Admin | Streams a model file, a sidecar, or a zip or tar.gz of both into `model_cache` |
| `POST /models/{name}/sidecar` | Admin | Writes the sidecar for a model file that has none, from the form's values |
| `POST /models/{name}/use` | Admin | Sets Frigate's `model:` section to the model, then restarts Frigate |
| `POST /models/default/use` | Admin | Puts back the installer's model, or removes the section on a device without a Coral |
| `POST /models/plus/{id}/use` | Admin | Uses a Frigate+ model by its ID: a Use when the device has the model's two files, otherwise a download that Frigate makes (see [Using a Frigate+ model by its ID](#using-a-frigate-model-by-its-id)). Answers 202, with `started` as `restart` or `download` |
| `GET /models/{name}/package` | Admin | A zip of the model's two files and `SHA256SUMS` |
| `GET /models/{name}/file` | Admin | The model file alone, for a model with no sidecar to package, such as the installer's |
| `DELETE /models/{name}` | Admin | Removes the model's files, unless it runs or is the installer's or Frigate's own default |

The module writes only inside `model_cache` and Frigate's `config.yml`, plus its own state directory. Every `model_cache` write goes through a descriptor of the directory opened with `O_NOFOLLOW`, after `valid_name` has checked the name; `config.yml` is edited by its path through `RoundTripFile`, as `tm-control migrate` edits config files (a backup, an atomic replace, the owner kept). When Frigate answers in safe mode, which it enters when its config fails to validate, it runs a stand-in config, so `GET /models` reads the detector and the running model from `config.yml` and says `frigate_safe_mode`; a Use still goes through Frigate's API, which validates the whole config. The caps are 100 MB for a request and a model file, 2 MB for a sidecar, 3 archive members, and 512 MB of free storage left afterwards. Use goes through Frigate's config API, which checks the whole config, and edits `config.yml` itself, with a backup, only when Frigate doesn't answer. Both end in a restart of `frigate.service`.

Uploads need two things from the edge. nginx has its own location, `^~ /api/v1/models/upload/` in `tm-control-api.conf.j2`, with `client_max_body_size 100m` and `proxy_request_buffering off`, so the body streams to tm-control instead of being buffered. Because of that, tm-control reads the rest of a refused upload before it answers, so nginx can pass the answer on rather than a 502. The upload body is `application/octet-stream`, which the cross-site check in `core/csrf.py` admits along with `application/json`, because the check still requires a same-origin request. Every other `/api/` path keeps nginx's default body limit.

The sidecars are a Frigate+ model record's JSON. The module reads only the fields the page shows and keeps the whole file as it was uploaded, so a download returns it unchanged. It never puts a record's other fields in an answer, a log line, or an audit row.

### Using a Frigate+ model by its ID

`POST /models/plus/{id}/use` takes an ID of 32 lowercase hexadecimal characters (`PLUS_ID` in `inventory.py`), and answers 422 `bad_id` for anything else. `contracts.MODEL_ID` is looser on purpose: it is the rule for a path someone typed into a config. When `model_cache` already holds the model's file and sidecar under that ID, the route is `POST /models/{id}/use`. Otherwise it needs the Frigate+ API key (409 `no_key`) and a Frigate that answers (409 `frigate_down`), and it never writes `config.yml` itself: a model that isn't on the device can't be validated without Frigate, which is also what downloads it.

Frigate downloads the model while it validates a config whose `model:` has `path: plus://<id>`, so its `POST /api/config/save` holds its answer for minutes. The route sends that config from a thread (`fetch.py`) and answers 202 at once. The thread keeps one record, which `GET /models` returns to admins as `fetch` (`downloading`, then `saved`, `refused`, or `failed`, with a message for the last two). The record stays until the next download starts or a Use succeeds. A viewer's `fetch` is null. The record lives in memory, in `app.state.fetches`.

How the thread follows the save:

* A 200 is `saved`: it audits `models.use` with the ID and restarts `frigate.service`. A 400 is `refused`, with Frigate's own lines, redacted by `picker.refusal_lines`.
* Frigate's port 5000 is its own nginx, which gives up on a request after 6 minutes (`proxy_read_timeout 360`) while Frigate goes on downloading. So after no answer, a 502, or a 504, the thread reads Frigate's config every 5 seconds. The config holding exactly the text it sent means Frigate saved: `saved`, then the restart. Frigate not answering is `failed` at once, "Frigate stopped before the download finished." The old config after 10 minutes (`WAIT`) is `failed` with "Frigate didn't finish downloading the model in 10 minutes." A refusal Frigate makes after its proxy gave up is never seen, so it ends as that same message.
* Whatever the thread calls, it ends the record: an unexpected error is `failed`, named by its class only, because an exception's text could hold the key.

One model change reaches Frigate at a time. `Fetches` has a gate that a Use, the default's Use, and a use by ID each take, without waiting, before they send Frigate a config, and a download's start takes it before it lets go. A second change meanwhile is 409 `changing`, and any change while a download runs is 409 `downloading`. Upload, download, and delete stay open. Any new caller of `frigate.save_config` has to take the gate first; today's callers are the picker's Use save and the download's wait. Fake mode follows a fake download on a thread of its own (`FAKE_FETCH_SECONDS`), through the same record and gate.

The design leaves three gaps, which are accepted:

* The record is in memory. If tm-control restarts during a download, the record is lost, and a save Frigate makes afterwards gets no restart from tm-control. Frigate has the new config on disk but runs the old model until it restarts for another reason.
* Frigate writes the config text it was sent. An edit saved in Frigate's configuration editor during the download is overwritten.
* If Frigate's download outlasts the 10-minute wait, Frigate may still write the config later, with no restart from tm-control, after the gate is free again.

### The Location module

The `location` module serves the [Location page](../use/location.md). It's for admins only, because the places hold exact coordinates: every route under `/api/v1/surveys` takes `require_admin`. The places are in `state.sqlite`; the place in use is also in Node-RED's `config.yml`, under `deployment:`, which is what Node-RED reads. tm-control never opens `tmdb.sqlite`, and Node-RED never opens `state.sqlite`.

| Route | What it does |
|---|---|
| `GET /surveys` | The place in use, the precision, the enabled sensors and their headings, the places with Node-RED's usage counts, the deployments recorded before any place, and `map`, the map's address from the manifest (`style_url`), null unless it is `https://`, with `region`, where the map opens when there is no place to start from: the city of the device's time zone (from the Pi's own time-zone data, `zone1970.tab` and then `zone.tab`, two decimal places), only when the Wi-Fi country is one of the zone's countries, and null otherwise or with no map. Runs the reconcile first. |
| `POST /surveys`, `PATCH` and `DELETE /surveys/{id}` | Plan a place, edit a planned one, delete one that isn't in use |
| `POST /surveys/{id}/deploy` | Writes the place and every enabled sensor's `heading_deg` into `config.yml`, then asks Node-RED every second, for up to 20 seconds, for the new deployments. `reloaded: false` when they didn't appear, which isn't an error: the file is written. A move to another place removes each sensor's `pitch_deg`, `height_m`, `view_distance_m`, and `mount` from the file, at a place used before as at a new one, and `previous` lists the sensors (`sensor_type`, `sensor_name`) whose values from the place's last use wait to be confirmed. It is empty when none wait, and when the place didn't change. |
| `PUT /surveys/precision` | Writes `database_precision`; with `round_stored`, also has Node-RED round the rows already stored |
| `POST /surveys/{id}/location`, `POST /surveys/{id}/deployments/{deployment_id}/heading` | Corrections: the place's point, re-rounded in Node-RED's rows, or one deployment's heading (`heading_deg`, a whole number from 0 to 359 or null); each records a row in `survey_corrections` |
| `GET /surveys/{id}/deployments`, `GET /surveys/{id}/events` | A place's deployments, and its event count and span, from Node-RED. Each deployment carries the four mounting values beside `heading_deg`, always present and null when none was recorded. |
| `GET /surveys/{id}/mounting` | How each enabled sensor is mounted at the place in use, as `config.yml` has it: `sensors`, `mounts` (the three usual mounts), and `nodered`, whether Node-RED answered. Each sensor has its `sensor_type`, `sensor_name`, the five values (`heading_deg`, `pitch_deg`, `height_m`, `view_distance_m`, `mount`), `measured` (`pitch`, `distance`, or null), `camera` (for a radar, the first enabled camera that names it), `same_as_camera`, `deployment_id` (its open row), `recorded` (whether that row has recorded traffic; null when Node-RED can't say), and `previous`. `previous` is null, or the `pitch_deg`, `height_m`, `view_distance_m`, `measured`, and `mount` last saved for the sensor at this place, which are offered after a move here and not recorded. They are offered until a save writes that sensor; there is no way to dismiss them. Cameras come first, each followed by its radar, then the other radars, then the rest. Another place than the one in use is 409 `not_in_use`. When Node-RED doesn't answer, `nodered` is false and no sensor has a `deployment_id` or `recorded`. |
| `PUT /surveys/{id}/mounting` | Checks or saves how the sensors are mounted. The body is `sensors` (each with `sensor_type`, `sensor_name`, the five values, `measured`, and `same_as_camera` to take a radar's values from its camera; the answer's other keys, `camera`, `deployment_id`, `recorded`, and `previous`, are ignored if sent; a sensor left out keeps its values and the save writes nothing for it), `moved` (the answer to "Did the unit move or turn?"), and `dry_run`, which is true unless the body says otherwise. The answer is `saved`, the `sensors` as they are or would be, `changes`, `ask`, `suggested` (`moved`, `measured`, or null), `new_deployments`, and `reloaded`. A sensor the save writes has its values confirmed, so its `previous` is null from then on; saving the `previous` values fills empty ones, so nothing is asked. A save that needs the answer and has none is 409 `answer_needed`, and a save while Node-RED doesn't answer is 502; a dry run answers either way. A value the rules refuse is 422 `validation` with `detail.field` and, for a sensor of the body, `detail.index`; the message never holds the value. |
| `POST /surveys/import` | Planned places from a CSV: a dry run lists what it read, and the import creates all or none |
| `POST /surveys/database-copy` | Starts a [database copy with the exact locations](#a-database-copy-with-the-exact-locations): answers `{url, places}`, a one-time `/storefiles` link and how many places the copy will hold, or 409 `no_exact_locations` |

The rules:

* `coordinates.py` holds them: survey ids (`<8 hex>-si`, from `secrets.token_hex(4)`), typed coordinates quantised to five decimal places half away from zero on their decimal text, and the stored ones rounded half away from zero, as SQLite's `ROUND` and the flows' `toFixed` do. The UI's `coordinates.ts` only checks a pasted pair before it sends; the API's answer wins.
* `config.py` edits `config.yml` through `RoundTripFile`, with `mapping_indent=4`, so comments, key order, and quoting stay. Each save keeps a backup beside the file, of which the newest 10 stay, and replaces it atomically. The backups of Frigate's `config.yml` from the Detection page's file fallback follow the same limit. Pruning touches only these `config.yml.<UTC stamp>.bak` names. It leaves the Ansible backups from `tmsetup.sh`, a copy made by hand, and every `<file>.<UTC stamp>.migrate.bak` from `tm-control migrate`, which can hold the only copy of what the migration removed. A file changed since it was read is a `ConcurrentEditError`, which the API answers with 409 `config_changed`.
* `reconcile.py` keeps the store and the file in step. It runs at claim, on every `GET /surveys`, deploy, location correction, and request to a place's mounting, and before the checks of every status report that isn't the cached one (`StatusCache`'s `prepare`), under `app.state.reconcile_lock`, which every write also holds. The status report waits at most two seconds for that lock, skips the run when a write holds it longer, and logs any error by its class name. Once per device it makes the first place: on a fresh device (no coordinates, no `survey_id`, and no backup), **First location** with no coordinates; on an upgraded one, a used place for each survey in the newest `tmdb-v0-*` or `tmdb-v1-*` backup in `node-red-tm/db/backup/`, opened read-only and immutable, then the place in use from the file. It waits until Node-RED reports schema version 2. An unreadable backup is skipped with one log line. Every run after that follows hand edits of the file, as [Edit the location by hand](../configuration/node-red-config.md#edit-the-location-by-hand) describes. Putting a place in use (a deploy, or a hand edit of `survey_id`) marks each of its `survey_sensors` rows that holds any of the four `unconfirmed`, and a reset file gets back only a confirmed row's four. Putting in use a place that already exists, at the upgrade or by a hand edit, also stores the file's heading for each enabled sensor the place has no row for, and changes no row it has.
* `mounting.py` holds every rule of how a sensor is mounted and does no I/O: the five values and their limits, tilt and distance worked out from each other, the three usual mounts, which changes count, whether to ask "Did the unit move or turn?", and the answer chosen in advance. Nothing else restates them. The routes, `config.py`, and `places.py` call it, and the flows repeat only the limits and the old compass points, which `test_mounting_limits_match_the_control_apps` in `script/tests/test_node_red_flows.py` pins against the same table. A limit is checked on the value after rounding (tilt to one decimal, lengths to two, half away from zero), and a value that is sent for the worked-out one of tilt and distance is ignored.
* A save of the mounting (`PUT /surveys/{id}/mounting`) runs in this order. `GET` runs step 1 too.
    1. The reconcile runs first, as on `GET /surveys`, so a file that `tmsetup.sh -f` reset gets the place's id, headings, and the mounting saved for this use back before it is read. The rest runs under the reconcile lock, and a save whose file no longer names the place by then is refused with 409 `config_changed`.
    2. It checks the body. A mount must be one of the three usual mounts, or the key the file already holds for that sensor.
    3. It asks Node-RED for the place's deployments and for which have recorded traffic. A save is refused with 502 while Node-RED doesn't answer.
    4. It corrects the open row of each sensor that changed and wasn't answered "moved or turned". The rows go first, so a refused correction leaves the file alone.
    5. It writes `config.yml` for every sensor the body names whose values differ from the file or the store. A sensor the body leaves out isn't written. Node-RED starts a new deployment itself when it sees the file change, so only a sensor that moved gets one. Values someone typed into the file by hand become the place's stored mounting the next time a save writes them.
    6. Last, it writes the store, so that a refused file save leaves the store as it was. A sensor written here has its values confirmed.

    If a correction or the file write fails, the rows already corrected are put back, including the one whose call failed, because it may have changed before the timeout. A row a save started answers `recorded: false`.
* No coordinate, description, or reason is logged, audited, or put in an error message. Audit rows carry the survey id, and a deployment id or the precision. The five mounting values identify no place, so a correction's audit row may list the ones it changed.

The module calls nine Node-RED endpoints, besides `/tm-internal/status`, on `127.0.0.1:1880` with `X-TM-Internal-Token`. Flows on the `init-config` tab serve them, and `script/tests/test_node_red_flows.py` pins them:

| Endpoint | What it does |
|---|---|
| `GET /tm-internal/deployments?survey_id=<id>` | A survey's deployment rows |
| `GET /tm-internal/surveys/usage` | First start, last end, and open and total deployment counts for each survey, and for the rows with no survey |
| `GET /tm-internal/surveys/<id>/events` | A survey's event count, and its first and last event |
| `POST /tm-internal/deployments/precision` | Rounds every stored row to a coarser precision, or clears the coordinates for `none` |
| `POST /tm-internal/surveys/<id>/location` | Rewrites a survey's stored coordinates from a new point, each row at its own precision |
| `POST /tm-internal/deployments/<id>/heading` | Rewrites one deployment's `heading_deg` |
| `POST /tm-internal/deployments/<id>/mounting` | Rewrites one deployment's heading, tilt, height, view distance, and mount in place; all five are required, and null clears one |
| `GET /tm-internal/surveys/<id>/recorded` | For each of a survey's open deployments, whether it has recorded traffic: an event for a camera, a radar reading dated no earlier than a day before the deployment began for a radar, and null for any other sensor |
| `POST /tm-internal/database/exact-copy` | Keeps a list of places' exact locations in memory under a ticket, for one database copy; 204 with no body |

#### The map on the Location page

The place form and **Correct location** can pick the point on a map. The map is the browser's business: tm-control only reports where to get it (`map` in `GET /surveys`, from the manifest) and makes no request to it. The UI (`ui/src/modules/location/`) draws it with MapLibre GL, which only `PinMap.vue` imports. `MapPicker.vue` loads `PinMap.vue` with a dynamic `import()`, so the library, its stylesheet, and its worker are separate files that the browser fetches the first time the picker opens, and the page's first download doesn't grow by them. The worker is a `.mjs` file, which the revproxy's nginx serves as JavaScript (`types { text/javascript mjs; }` in `nginx.conf.j2`, because its `mime.types` has none).

The specs don't run the library, which needs WebGL: `pin-map.spec.ts` replaces `maplibre-gl` with small classes that record what `PinMap.vue` asks of them (the options, the marker, the events), and `map-picker.spec.ts` replaces `PinMap.vue` with a stub that can drop a pin or fail. To see the real map, run [fake mode](#run-it-on-a-laptop), whose manifest names a map source, in a browser with internet access.

#### A database copy with the exact locations

`POST /surveys/database-copy`, which the Sharing page's card calls when its box is ticked, is the one place the exact locations leave tm-control for a database file, and neither side opens the other's database to do it.

1. The route sends only the places marked in use or used that have both coordinates, so a planned place is never sent. With none, it answers 409 `no_exact_locations` and sends nothing.
2. It makes a ticket, 32 random hex characters, and posts it with the places (`survey_id`, `lat`, `lon`) to `POST /tm-internal/database/exact-copy`. Node-RED checks the body (1 to 10,000 places, each id and finite coordinate valid, no id twice) and keeps the list in memory under the ticket for 600 seconds, the life of a download link. It never writes the list to disk or logs it. The list is on a message for one hop only: the validator hands it to "keep exact copy list" as `msg.exactCopy`, which removes it before answering, and no message that reaches a response, a Dashboard node, or a debug node carries it. Node-RED holds at most four lists, dropping expired ones first and then the one that expires soonest. Starting the flows drops every list, including one claimed for a copy that was in flight.
3. The route asks `DownloadGrants` for a link for `files=tmdb-exact-<ticket>` and answers with it. The audit row `survey.database_copy` holds the number of places, and neither it, the log, nor an error holds a coordinate, a ticket, or a link.
4. The Sharing page's card navigates to the link, so the download goes through nginx's admin check like any `/storefiles` download and works in Android's sign-in window. The ticket isn't single-use, because that window fetches the address twice and the second fetch is the one that saves, so a ticket serves every request in its ten minutes, each with a copy of its own. nginx's access log records the link, so it holds the ticket as well as the token; the diagnostics download replaces both.
5. In the `ui-database` download group, "Validate filenames, setup tar" recognizes the single name `tmdb-exact-<ticket>` and takes the list at the start of the request. A large database takes minutes to copy, so a ticket that runs out meanwhile doesn't spoil a download that began. An unknown or expired ticket is a 404. The existing steps then make the `VACUUM INTO` copy, and "write exact locations into the copy" opens only that copy and writes a table `survey_exact_location` and a view `deployment_exact`, as [the data page](../data-and-payloads/data-overview.md#the-exact-location-in-a-database-copy) describes. It adds a place only if the copy's `deployment` table names it, refuses the file `TM_DATABASE_PATH_TMDB` names, and renames the file to `tmdb-exact-locations.sqlite` for the `tar` step. The archive is named `<hostname>_<time>_tmdb-exact-locations.tar.gz`.
6. The function opens the copy with Node's built-in `node:sqlite`, which `settings.js` puts in `functionGlobalContext` as `sqlite` (`null` when the Node has none, so Node-RED still starts and the step refuses). A function node can't load it through its own module list: Node-RED strips the `node:` prefix and looks for a built-in named `sqlite`, and refuses the install. No statement that carries the list runs on the flows' shared database connection, and no other node uses `global.get("sqlite")`.
7. When the rewrite fails, for example because the copy is missing, the Node has no `node:sqlite`, or the disk is full, the step throws an error whose text names the step, or is SQLite's or Node's own message (which can name the copy's path), never a coordinate. The existing "catch database copy" removes the copy and its claimed list, and answers 500, so nothing is served, and a copy without the exact locations never goes out under the exact name.
8. The copy exists under `db/snapshot/` from the end of the copy step until the download ends. If the power fails meanwhile, it stays on the card until Node-RED next starts, when "remove database copies left by a restart" removes everything under `db/snapshot/`, before any download can begin.

`tm-control migrate --node-red-config`, run by the installer, also brings `deployment:` up to date: it adds `database_precision: '2'` where it's missing, and removes `lat` and `lon` from a sensor's own `deployment:` block. It never changes a key that a running Node-RED compares, such as a `bearing`: the installer runs it while the old Node-RED is still up, and that Node-RED's config watch would close the open deployments and start new ones. `tm-control migrate --node-red-headings` converts each old `bearing` to `heading_deg` instead. `node-red-tm.service` runs it as the code owner before Node-RED starts, next to the tmdb migration, so the file and the database change while no flow runs; a failure doesn't stop Node-RED, whose flows read a `bearing` as its point's centre, and the next start tries again. Its warnings are in the `node-red-tm.service` log. The Location check (`location` in `modules/apps/contracts.py`) checks the same keys at run time.

### The Sharing module

The `sharing` module serves the [Sharing page](../use/sharing.md). Its routes sit under `/api/v1/sharing`; any signed-in user can read, and only an admin can write. A viewer's answer has no host for an operator's own server, no token state, and no `download`.

| Route | What it does |
|---|---|
| `GET /sharing` | Where the upload goes, what is recorded as chosen for that server, whether the notice in force is the one the choice was made under, whether the public map is live, whether the place in use has a location, how the server last answered, and, for an admin, `download` (`null` for a viewer): the database's size from Node-RED's status (`database_bytes`, `null` without a whole number) and `exact_places`, the places in use or used with both coordinates. Runs the follow step first. |
| `PUT /sharing` | Admins. Saves the server and the three choices: `config.yml` first (the `thingsboard:` and `sharing:` blocks), the consent rows second. A refused save records nothing. |
| `POST /sharing/download` | Admins. Answers `{url}`, a one-time `/storefiles?files=/db/tmdb.sqlite&tm_token=…` link, after Node-RED's status answers (otherwise 502 `nodered_error`, "The download wasn't started.", and no link). Writes the audit row `sharing.download`, with no detail. |
| `GET /sharing/notice` | The sharing notice and its version. |
| `POST /sharing/reviewed` | Admins. Clears the review that an upload found on asks for. |

The rules:

* `consents.py` keeps one row per change in `sharing_consents` (`state.sqlite`, migration 4). A *target* is `maintainer` or `own:<host>`; the latest row for a target and a choice is the answer. A grant records the notice version it was given under (`own-server` for an operator's own server, `pre-consent` for an upload found on). Rows are never deleted, and the order is the row id, because a unit's clock can step back. The host is part of a target key and stays in the database.
* `follow.py` keeps `config.yml`'s `sharing:` block equal to the rows. Node-RED reads the block and never `state.sqlite`, so a hand edit of it grants nothing: with the upload off, every choice for the target is withdrawn and the review flag is cleared; with it on and no Share data recorded (a unit upgraded with the upload on), it is recorded as granted before consent existed and the review flag is set; every choice for any other server is withdrawn. A file with no block means the rounded location only: a save writes the block before its rows, so a granted exact location or public map next to no block is withdrawn (the file was replaced or the block deleted), never restored. Then the block is rewritten to what the rows say when it says something else, or written when it is missing and the upload is on, and Node-RED is told. It runs inside `reconcile.ensure` and `reconcile.for_status_report`, and at the start of `GET` and `PUT /sharing`, under `app.state.reconcile_lock`.
* A save is judged against the store after the follow step, so a hand edit since the page was read counts. The notice's version is needed only for the maintainer's server, with the upload on, when the save turns Share data on or grants a choice that isn't granted yet; while Share data is already granted under the current notice, a save can add a choice without it. Withdrawing never needs it, and the exact location needs `https`. The public map is refused for an own server and until the manifest says it is live.
* `download.py` holds the Download your data card's facts and its link. The size comes from Node-RED's status and nowhere else, because the control app never opens `tmdb.sqlite`; an older Node-RED that leaves `database_bytes` out, or a value that isn't a whole number from 0 up, reads as no size, not an error. The count reads the places store as it is, without the reconcile `GET /surveys` runs. The card starts the database copy in the UI: unticked, it posts `POST /sharing/download`; ticked, `POST /surveys/database-copy` (see [A database copy with the exact locations](#a-database-copy-with-the-exact-locations)); and the page opens the answered link with `openDownload`. Neither route's link, token, or ticket goes to a log, an audit row, or an error message.
* `server.py` turns the `upload` section of Node-RED's `/tm-internal/status` (`enabled`, `last_ok_at`, `last_failure_at`, `last_failure`) into the page's state: off, waiting, ok, stale (no accepted upload for 900 seconds), or the last failure's kind (`unreachable`, `refused`, `rejected`, `server_error`) while it is newer than the last accepted upload; unknown without the section. tm-control never contacts the server: Node-RED's "record upload result" node on the `thingsboard` tab keeps the last answer from the status code, and never the URL, which holds the token.
* The Status page's `config.sharing` check (Configuration group) and `apps.sharing_server` check (Apps group) read the same things. The first warns for a review that is needed, for a notice nobody has read or that has changed, and for a `sharing:` value the device ignores; the second words the server's state. Neither shows the host, a notice version, or a note.
* The host, the token, coordinates, and notes are never logged, audited, or put in an error message. A `sharing.update` audit row lists the names of the fields that changed, such as `enabled,exact_location`. `tm-control migrate --node-red-config` changes the old placeholder host `tb.server.com` to the maintainer's while the upload is off.

The upload gate is a function node on the `thingsboard` tab, after the rate limit and just before the request is built, so each message is judged under the config it is sent with. Only these leave the unit:

* Telemetry keys `event`, `radar`, `airquality`, `system_metrics`, and `deployments`. Deployment rows are re-rounded to the coarser of their own `location_precision` and the unit's `database_precision`.
* Attribute keys `deployments`, `radarinfo`, and six `sysinfo_*` keys (`sysinfo_tmVersion`, `sysinfo_osHostname`, `sysinfo_osRelease`, `sysinfo_osTimeZone`, `sysinfo_deviceName`, `sysinfo_frigateVersion`).
* Three attributes added to the `deployments` one: `consents` (what the page chose, and the target and notice version, which it reports only to the server they were chosen for and as `null` to any other), `exact_location` (the place's id and its coordinates to five places, only with the consent, a `sharing.host` that matches `thingsboard.host`, an `https` URL, and a place with a location, else empty), and `public_map` (the id and a point to three places, for the maintainer's server only).

The gate sends nothing while the upload is off, so a message that waited in the rate limit while Share data was turned off is dropped rather than sent. It also fails closed on shapes it can't read: a `deployments` value that isn't a mapping is left out, telemetry `deployments` keeps only its `updatedDeployment` and `currentDeployment` lists and only when each is an array, and a row that isn't a mapping is dropped. A key or shape that isn't listed is left out and named once per config load, never with its value. Nothing uploads `config.yml` or Frigate's configuration. `script/tests/test_node_red_flows.py` pins the gate, the lists, and the `upload` section.

### The Cameras module

The `cameras` module serves the [Cameras page](../use/cameras.md). It's for admins only, like the Location page, because it's a settings page: every route under `/api/v1/cameras` takes `require_admin`. It owns the `sensors.cameras` entries in Node-RED's `config.yml` and writes no other config file, so never Frigate's. The other things it changes are the places' sensor headings (`survey_sensors` in `state.sqlite`) when an entry is re-keyed, and Frigate's detection switch for a camera, through Frigate's API, which changes no file of Frigate's that tm-control writes. It never opens `tmdb.sqlite`.

An entry's key is the camera's neutral name, the one the flows record and share. Its optional `frigate_camera` is Frigate's name for it, and without one the key is Frigate's name too, so installs that never used the page need no migration. `names.py` makes the keys, `camera_<N>_<6 hex>`, from `secrets.token_hex(3)` and redraws a token a neutral name in the file already ends with. The module never logs, audits, or puts in an error message Frigate's name: audit rows carry the neutral name.

| Route | What it does |
|---|---|
| `GET /cameras` | Whether Frigate answers or is in safe mode, the rows, the unit's radars with their state, and whether the Plate Recognizer add-on is installed |
| `POST /cameras` | Adds an entry under a new neutral name for a Frigate camera that no entry points at |
| `PUT /cameras/{name}` | Sets `enabled`, `camera_radar` (a radar of the unit that has an entry under `sensors.radars`, or null), and `plate_recognizer` |
| `POST /cameras/{name}/frigate-camera` | Points the entry at another Frigate camera: the rename |
| `POST /cameras/{name}/neutral-name` | Re-keys an entry to a new neutral name, keeping its position, comments, and sub-keys, and renames its `survey_sensors` rows in every place, the file first |
| `PUT /cameras/{name}/frigate-detection` | Turns Frigate's object detection on or off for the entry's camera with Frigate's `PUT /api/camera/<name>/set/detect`, the live view's switch: no restart, and Frigate keeps it in `.runtime_state.json` beside its config. 409 `camera_off` when the camera is off in Frigate, 502 `frigate_error` when Frigate doesn't take it. `config.yml` isn't changed |
| `DELETE /cameras/{name}` | Removes an entry whose Frigate camera is gone, or that repeats another entry's |
| `POST /cameras/{name}/reference` | Takes the [reference picture](../use/cameras.md#take-a-reference-picture): Frigate's `latest.jpg` for the entry's camera, plain and with `zones=1`, at quality 95, held in memory under a ticket. Answers `ReferenceOut` (the ticket, the files' stem, the detect size, the distance unit, each zone's `ZoneFacts`, and `has_location`) and records `camera.reference`. 409 `camera_off` when the camera is off in Frigate, 409 `no_picture` when Frigate has no live frame |
| `GET /cameras/{name}/reference/{ticket}/{picture}` | `clean.jpg` or `zones.jpg`, as held, with `Cache-Control: no-store` |
| `GET /cameras/{name}/reference/{ticket}/package?location=` | The zip of the two pictures, the data file (with the place's exact point only when `location` is true), and the SVG, built in memory, `no-store`. Records `camera.reference_saved` or `camera.reference_saved_with_location` |
| `DELETE /cameras/{name}/reference/{ticket}` | Drops the ticket; 204 whether or not it was held |

The rules:

* `state.py::compare` is the one comparison of Frigate's cameras, read from its running config (`enabled: false` is Off; the running config carries the live view's switches as they are now, and `adapters.frigate.config` reads it with `X-Cache-Bypass`, past the 5 seconds Frigate's nginx keeps an `/api/` answer), with the file's entries. It gives a row for each entry in file order, then one for each Frigate camera that is on and that no entry points at, and it's what the page and the `config.cameras`, `config.zones`, and `config.zone_names` checks use, so they can't disagree. When Frigate doesn't answer or is in safe mode, every entry is `unknown`, never `absent`. A row's `detect` is whether Frigate detects objects on the camera now: false for a camera that is Off, and null when it can't be read. `zones_missing` lists the four zones the flows read that Frigate lacks for the camera, and `zones_off` those it has with `enabled: false` (Frigate 0.18's zone switch). `zone_names` lists the camera's other zones that are on, in Frigate's order, each with what `check_name` in `modules/apps/name_check.py` found: `pattern` (it looks like an address or a person's name), `unknown_word` (a word its two hand-written lists don't know), or null. A key Frigate's zone editor made up from a name it couldn't use as a key (`zone_` and 8 hex characters, the first a letter, with a `friendly_name` other than the key; the rule is `_MADE_UP` in `state.py`, not in the leaf module) isn't checked: its `check` is null and `ZoneName.friendly_name` carries Frigate's name, which only the Cameras page shows; every other zone's `friendly_name` is null. The check imports nothing from `tm_control`, needs no network, and never blocks or renames. A row's `issues` (`level` and `code`) are the per-camera judgements of the `config.cameras`, `config.zones`, `config.zone_names`, and `config.radars` checks, made once in `state.py::_issues` (`compare` takes `sensors.radars` for the radar one); a Frigate camera no entry points at is `not_paired` only while its `detect` isn't false, because with Frigate's detection off nothing is dropped; the checks word them, and the page marks each row with them. The zones check's fix opens Frigate's masks and zones settings for a single camera (`/frigate/settings?page=masksAndZones&camera=<name>`, a `Fix` with `external: true`, which the Status page renders as a plain link instead of a route), and the Cameras page for several. The `zone_names` issue (a warning, under the zones issue's rule: enabled, on in Frigate, not a duplicate) is raised for a `pattern` name only; an `unknown_word` name is a note on the page and nothing on the Status page. The `config.zone_names` check counts the `pattern` names and names the cameras, and never quotes a zone name, because check details go into Copy diagnostics. The page, the checks, and the diagnostics all read the entries through `camera_entries()` in `modules/location/config.py`.
* Every write holds `app.state.reconcile_lock`, loads `config.yml` through `NodeRedConfig`, compares against Frigate again, and refuses with 409 `cameras_changed` when the rows no longer match what the admin confirmed, or `config_changed` when the file changed. Except `PUT /cameras/{name}`, they need Frigate to answer, and refuse with 409 `frigate_unavailable` otherwise.
* `NodeRedConfig`'s camera methods (`add_camera`, `set_camera`, `point_camera`, `rename_camera`, `remove_camera`) edit through `RoundTripFile`, as the deployment edits do, so comments, order, and quoting stay. `set_camera`, `point_camera`, and `rename_camera` refuse an entry that carries a YAML anchor or is shared with another entry through an alias (`main_st: &cam`, then `oak_ave_wide: *cam`), because the edit would change both; the API answers 500 `config_error`, as for any file it can't edit.
* The reference picture's pictures live only in `app.state.references` (`References` in `modules/cameras/reference.py`): a ticket from `secrets.token_urlsafe(16)` answers only the admin who took it, for 600 seconds on the monotonic clock. A new take drops that admin's earlier one, and the store holds two at most, so at most four frames are in memory. A ticket that isn't held, or is held for another camera, is 404 `reference_expired`. Frigate answers a camera that isn't sending with its own error picture, HTTP 200 and no header, so the take refuses a frame two ways: Frigate's stats must give the camera a `camera_fps` above 0, and the JPEG's size, read from its SOF marker, must be the camera's detect size; a frame marked `X-Frigate-Offline` is refused too. `zones.py` reads each zone from Frigate's `/api/config` (`ZoneFacts`: corners as fractions in stored order, lettered A, B, C, kept as they are below 0 or above 1, since `/api/config` gives fractions even for a zone whose `config.yml` holds pixels, and a pixel point past the frame becomes a fraction above 1; side lengths by side; of a zone's `filters`, only each object's `FILTER_KEYS` that hold a number; Frigate's colours, which `/api/config` gives as blue, green, red), `reference.py` holds the tickets and writes the data file and the zip, and `svg.py` draws the SVG as text, escaping every key. The take doesn't check for people, and the dialog's note makes that the admin's job: Frigate 0.18 saves an event only once the object has moved and has a clip or a snapshot, so `/api/events` never shows a person standing still, and the live list that does (the WebSocket's `camera_activity`) would need a WebSocket client. No picture, ticket, or point goes to a log line, an audit row, or an error message: the audit detail is the entry's key, `HideTickets` replaces the ticket in uvicorn's access log with `-`, the error handlers in `core/errors.py` log the route's path template, and the cross-site check's 403 line names the method and no path. The entry's key is the only camera name in any of them, so they hold Frigate's name only for an entry that uses it as its key, as the installer's `picam_h265` does. nginx's access log still holds the ticket, as it holds a download link's token; it answers only the admin who took it, for 10 minutes.
* Copy diagnostics replaces every Frigate camera name that differs from its entry's key, and every Frigate camera no entry points at, Off ones included (it doesn't use `compare`'s rows, which leave those out), with `redact_words` (whole words, longest first; a percent escape before a name, or one that was encoded once more (`%252C`), counts as an edge, so every name in a login redirect's `next=` is replaced too), the way it replaces a secret. It reads the names from the file, Frigate's running config, Frigate's config file (`adapters.frigate.config_file`, which still names a camera while Frigate is down or in safe mode; a file that can't be read is skipped), and the `config.yml` backups beside the file. It also replaces the query string after every `config/set?` and after its percent-encoded form, which a login redirect's `next=` carries (`_CONFIG_SET` in `diagnostics.py`), because nginx's access log and Frigate's journal keep the request line, and the zone editor's holds a zone's key and the name typed for it. `check_groups` text may name Frigate's cameras, because the Status page is behind the login.

Node-RED gets the mapping from "init config defaults" (the `init-config` tab), which sets three globals after everything that can throw, so a rejected load leaves the old ones: `frigate_cameras`, a map from Frigate's name to the key; `camera_labels`, each key's label for the dashboard pickers, `<key> (<Frigate's name>)` when the two differ; and `tm_warned`, which is reset on every load so a warning is logged once per config load: one for events from cameras no entry points at, which names none of them, and one for each radar name a camera is paired with that `config.yml` lacks. They're their own globals, not part of `global.config`, because "init config defaults" takes `frigate_camera` out of each entry before the config is stored: in Node-RED, Frigate's name lives only in `frigate_cameras`, `camera_labels`, and the `frigate_facts` flow context on `capture-events`, where "keep frigate facts" keeps each camera's detect size from Frigate's `/api/config` under Frigate's name. Only two nodes read an event before its camera gets the key: "vet sub_label" and "frigate fields", which looks the detect size up by Frigate's name and puts no name in what it adds. "append config" then looks each event's camera up in `frigate_cameras` and sets it to the key, so the `events` row, `tm/event` and `tm/events`, ThingsBoard, and Plate Recognizer carry only the key. An event from a camera the map lacks is dropped with one warning, and a `camera_radar` that names no radar records the event without one.

### The Network module and the hotspot

The `network` module adds the Network check group (`hotspot`, `wifi`, `internet`, and `wifi_country`, in `modules/network/checks.py`) and the Network page's routes. Both read the unit's network through `adapters/network.py`, which runs `nmcli` and `iw` and never asks for a secret. An offline unit is normal, so the Internet check is never a warning or an error, and a read that fails is `unknown`. The hotspot's values come from the manifest's `network` section. The checks' words are the contract with [the operator page](../use/wifi-hotspot.md).

The routes are in `modules/network/router.py`:

| Route | Who | What it does |
|---|---|---|
| `GET /network` | Any signed-in user | The unit's names, its Ethernet and Wi-Fi links (MAC and IP addresses, gateway, DNS servers), the internet, and the hotspot's state, as `NetworkState` from `state.py`. A value NetworkManager doesn't give is missing, not an error, and `readable: false` says it didn't answer at all. It never holds a password. |
| `GET /network/hotspot/password` | Admins | The password file's text, `""` for a hotspot with no password, and `null` when the file can't be read. The answer carries `Cache-Control: no-store`, and each call records a `network.hotspot_password_shown` audit row. It is the only place a password leaves the device. |
| `POST /network/hotspot` | Admins | Takes any of `enabled`, `name`, `password`, and `hidden`, checks them, and answers 202 with the job's id. A name takes 1 to 32 bytes of UTF-8 and a password 8 to 63 printable ASCII characters, each with no space at either end; a value that breaks its rule, or a request with nothing to change, is a 422 with a sentence and no job. A unit with no hotspot profile is a 409 (`no_hotspot`). The audit row `network.hotspot` lists the fields sent, never their values. |

The Wi-Fi routes come from `modules/network/wifi.py` and the same router. `wifi.py` reads three files that root's scripts write in `/run/traffic-monitor/` (`network-scan.json`, `network-retry.json`, and `network-join.json`) and the saved networks from `adapters/network.py`. It is read only and never reads a password. A file that is missing, unreadable, or not in its form reads as nothing, not as an error. NetworkManager's sentences are never read: a saved network is what `saved_wifi` returns, and the network in use is its profile's UUID. The profile a join is testing is left out of the saved networks until the join saves it, because NetworkManager lists it while the test runs.

| Route | Who | What it does |
|---|---|---|
| `GET /network/wifi` | Any signed-in user | `WifiNetworks`: the saved networks in the order the unit tries them (with `in_use`, `automatic`, `hidden`, `in_range`, and `could_not_join`), the nearby networks from the last scan (with `signal`, `security`, `saved`, `in_use`), how long ago the scan was, and the join. |
| `GET /network/join` | Any signed-in user | The `JoinState` the Network page's card and the home page's banner show, or `null`. It reads one file, and the join unit's state while a stage is still going: a pending stage while the unit isn't running reads as `interrupted`. |
| `POST /network/wifi/scan` | Admin | Starts the `network` job's `scan`. A radio that is missing (`no_radio`) or off (`radio_off`) is a 409 before any job. |
| `POST /network/wifi/forget` | Admin | Starts `forget` for a saved network's UUID, or 404 for one that isn't saved. The audit row names the network. |
| `POST /network/wifi/order` | Admin | Starts `order` with the UUIDs of exactly the networks that join by themselves, or 409 `stale_order`. |
| `POST /network/wifi/join` | Admin | Checks the name and password, the radio, that no join is pending, that the network isn't in use, and that the last scan heard it with a password; then starts the `network-join` job with a name and password, or a saved network's UUID when no password is sent. The audit row names the network and holds no password. |
| `POST /network/wifi/join/switch` | Admin | Starts the `network` job's `switch-now`, or 409 `no_countdown`. |
| `POST /network/wifi/join/cancel` | Admin | Starts `cancel`, which also dismisses a result. 409 while the join is switching. |

Every route that starts a change refuses it with 409 `join_pending` while a join is testing, counting down, or switching (`refuse_while_joining`), and the Network page disables its controls the same way. The routes answer 202 with the job's id and the page follows the job with `GET /jobs/{id}`. In fake mode, `fake_network` stands in for NetworkManager, the password file, and the join job's state.

`jobs/tm-job-network` is the root script behind `POST /network/hotspot`, run by `tm-job-network.service`. Its docstring lists every check and the order of its steps. The request is `{"action": "hotspot"}` plus the fields that were sent. The script repeats the name and password rules from `router.py`, because it imports nothing from tm-control, and a test keeps the two the same. In short, it:

1. Checks the request, then takes the lock, `/run/traffic-monitor/network.lock`. `tm-network-retry` takes the same lock, so the timer never moves the radio in the middle of a change. The job waits for it up to 10 seconds, and the retry run, which never waits, prints `locked` and stops.
2. Writes a new password to the password file first, and then changes the profile with one `nmcli connection modify`. The file is the source of truth, so a failed change puts the old file back.
3. Restarts the hotspot only when it is up and its name, password, or hidden setting changed (`connection up` applies them). Turning the hotspot off takes it down. Turning it on, on the built-in radio only, switches the radio on if it is off and starts the hotspot if the radio is idle. Nothing here restarts NetworkManager.

It prints one line per step, never a password, and exits 1 with `refused: <sentence>` or `failed: <step>`; a line ending `the settings are saved` means the profile changed and only the restart failed.

`tm-job-network` has five more actions, `{"action": "scan"}`, `forget`, `order`, `switch-now`, and `cancel`, and the same checks, hostile request, and lock. Its docstring has the full list:

* `scan` runs `iw dev <device> scan flush` and writes `network-scan.json`: the time, and each network heard with its signal (0 to 100) and its security (`open`, `password`, `wpa3`, `enterprise`, or `other`). What `iw` prints is the names and settings of other people's networks, so the script parses it as text, never prints it, and sends a name to `nmcli` only when tm-control sends it back in a later request. `flush` empties the kernel's cache first, because a plain scan keeps listing a network for about 30 seconds after it left the air. While `iw` is busy (exit status 240, which it is while NetworkManager scans and for 10 to 14 seconds after the hotspot restarts) the action tries again every 5 seconds for as long as its 60 seconds last.
* `forget` deletes a saved Wi-Fi client profile by UUID. When the unit was on it, it waits for the radio and starts the hotspot if nothing took over.
* `order` gives the networks that join by themselves a priority, the first the highest, changing only the ones that differ.
* `switch-now` and `cancel` never wait for the lock, because the join job holds it for its whole run. They write one word to `network-join.control`, which the join job reads every second. `cancel` on a finished result removes the state file, and on a join that died it rolls back the checkpoint, deletes the profile under test unless it is saved, and then removes the state file.

### The Wi-Fi join

`jobs/tm-job-network-join` is the root script behind `POST /network/wifi/join`, run by `tm-job-network-join.service`. Its request is `{"ssid": ..., "password": ...}` or `{"uuid": ...}`, and it deletes the request as soon as it reads it, so the password is on `/run` for a moment. Its docstring lists every step. In short, it:

1. Takes the lock and holds it to the end. Held by someone else: the state becomes `failed` with reason `busy`. When the state file shows that an earlier run died mid-test, the job rolls back that run's checkpoint and deletes its profile under test unless it is saved. A checkpoint that no such run left belongs to another program, such as Cockpit's networking page around each change, so the job leaves it alone; step 3 then fails, and nothing is changed.
2. Checks the radio and the profile in use, and scans with `flush`, once; a scan that fails doesn't stop the test. A network the scan doesn't hear is `failed` with reason `not_in_range`, and the radio is never touched. The flush is what keeps the hotspot from being taken away for a network that has just left.
3. Makes the checkpoint: a NetworkManager checkpoint with a 90-second rollback timeout, over D-Bus with `busctl`. If it can't, the job stops before it touches the radio. After this point every path, including an error and SIGTERM, rolls back to the checkpoint. If the script itself dies, NetworkManager rolls back by itself 90 seconds later.
4. Adds the profile under test in memory (`save no`), so a password that fails never reaches the microSD card, and runs `nmcli --wait 45 connection up` on it. The in-memory profile is the only place the new password lives, and the job never prints it.
5. On success reads the address and DNS servers and probes the internet: up to three DNS questions, a second apart, to the network's first two DNS servers in turn (the first question right after a join can fail at once), then one HTTP request to `connectivity-check.ubuntu.com`, over sockets bound to the Wi-Fi, in 10 seconds in all. Only the answer's status code is read: 204 is `reachable`, and any other answer is `sign_in_page`. No address, no answer, or an error is `not_reachable`.
6. Rolls back the checkpoint and waits for the radio to be where it was. A failure is `not_joined`, or `no_address` when the join waited out its 45 seconds with the device connected but without an address (exit status 3 with the device at state 70).
7. Counts down 300 seconds, reading the control file every second. `cancel` ends it and deletes the profile unless it is saved. `switch` starts the switch.
8. Switches: sets the profile to autoconnect with a priority above every other saved network, deletes the saved profiles of the same name when the password is new, and runs `connection up`. The radio is read until it is up on any profile. If it isn't, `connection up` on the profile it was on, or on the hotspot, and the state is `switch_failed`; the network stays saved and its failure goes on record in `network-retry.json`.

The reasons the page gives come from the scan and from exit statuses and device states, never from a sentence of `nmcli`, `iw`, or `busctl`, which can carry a command line. The job prints fixed sentences, exit statuses, and error type names.

The files, all in `/run/traffic-monitor/`, 0644 and root's, each written under a temporary name and renamed:

| File | Written by | Holds |
|---|---|---|
| `network-scan.json` | `tm-job-network` (`scan`) | The networks heard, strongest first, with the time. |
| `network-join.json` | `tm-job-network-join` | The state: `stage` (`testing`, `countdown`, `switching`, `joined`, `failed`, `cancelled`, `switch_failed`), `ssid`, `uuid`, `saved`, `before`, `joined`, `reason` (`not_in_range`, `not_joined`, `no_address`, `busy`, `error`), `address`, `internet`, `switch_monotonic`, `finished_at`. Never the password. tm-control adds `interrupted` when a pending stage's unit isn't running. |
| `network-join.control` | `tm-job-network` (`switch-now`, `cancel`) | One word, `switch` or `cancel`. The join job reads it every second and removes it once read, and whenever a run ends. |
| `network-retry.json` | `tm-network-retry`, and the join job for a failure | The failures on record per saved network, which set its wait of 5, 15, then 60 minutes. |

The lock, `/run/traffic-monitor/network.lock`, is held by `tm-job-network` for its run, by `tm-job-network-join` for all of its run (the test, the countdown, and the switch), and by each `tm-network-retry` run. The retry never waits for it, so the timer never moves the radio mid-change. `tm-job-network` waits up to 10 seconds, except for `switch-now` and `cancel`, which must reach a join that holds it. A join that finds the lock held ends as `busy`.

The unit allows 900 seconds (`TimeoutStartSec`), the longest a run can take: 10 + 60 + 90 + 45 + 300 + 75 + 45. `TimeoutStopSec=120` gives a stop time to roll back.

Two scripts in `jobs/` run as root, and neither is a `tm-job` unit. Both are standard-library Python with no `tm_control` imports, run as `/usr/bin/python3 -EP` from the root-owned `/usr/local/libexec/traffic-monitor/`, and read no password into their output:

| Script | Run by | What it does |
|---|---|---|
| `tm-hotspot-setup` | The installer's `wifi` tasks | Creates the `tm-hotspot` profile, or adopts an access-point profile made by hand, and ensures its device, priority, mode, address, and IPv6 setting. The password file is the source of truth for the password. It never activates or deactivates a profile, so a joined phone stays joined. Its docstring lists the order of its steps and its exit statuses. |
| `tm-network-retry` | `tm-network-retry.timer`, 90 seconds after boot and 5 minutes after each run ends, and the Hotspot check's **Restart the hotspot** | Keeps the radio on a known network or on the hotspot. It starts the hotspot when no network holds the radio, leaves it alone while a phone is joined, and scans for the saved networks otherwise, one network per run, with a 5, 15, then 60 minute wait after each failure. Its docstring lists its steps and outcomes. It keeps its memory in `/run/traffic-monitor/network-retry.json`. |

`tm-hotspot-firewall.service` loads the `inet tm_hotspot` nftables table before NetworkManager can start the hotspot. The table drops forwarded traffic into and out of the hotspot's subnet, so phones on it reach the unit and nothing behind it.

nginx's sign-in rule is in `container/revproxy/nginx.conf.j2`. On the hotspot dnsmasq answers every name with the unit's address, so a phone's connection test arrives with a foreign `Host`. A request that arrived on the hotspot's address with any name but that address or the unit's own is redirected to `http://10.42.0.1/`, which makes the phone open its sign-in window. The rule must never answer such a test with success: on Android 17 no browser reaches the unit until its user allows the Nearby devices permission for it, so the sign-in window is the only way in that needs no setup. nginx also sets `X-TM-Hotspot: 1` from the address a request arrived on, replacing any value the client sent, and `GET /api/v1/setup/status` then returns `hotspot.local_name`, which the login and setup pages show in a note: the address to copy, and the steps from a phone's sign-in window to a browser. The same answer carries `hostname` for everyone, with no login, and the control app's tab and bar take the unit's name from it, so the pages before login name the unit too. The name is no secret: mDNS announces it on the network.

`sudo tm-control card` (`core/card.py`) prints the device's addresses, the hotspot's name and password, and the setup code. It refuses to run without root, reads the password and setup-code files and nmcli's answer first, and only then opens the state database. `--json` prints the same values, and `--unclaimed-only`, which the installer passes, prints nothing and exits 3 once the device is claimed.

### What the sandbox allows

`tm-control.service` runs with `ProtectSystem=strict`, `RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6 AF_NETLINK`, and `SupplementaryGroups=systemd-journal video`. It writes its state and runtime directories and two config directories under the code directory (`ReadWritePaths`): Frigate's, `frigate/config`, for the models the Detection page manages, and Node-RED's, `node-red-tm/config`, for the `config.yml` the Location page writes. The rest of the system is read-only to it. The sandbox also shaped the probes:

* The Coral USB check reads the vendor and product ids from `/sys/bus/usb/devices` rather than running `lsusb`, which needed a netlink socket the service first lacked, and `ss` falls back to reading `/proc/net` for the MQTT broker's port.
* `AF_NETLINK` is there for `iw`, which reads the Wi-Fi country for the Network checks. The Network checks otherwise use `nmcli`, which needs nothing more, and never ask it for a password.
* `vcgencmd get_throttled` needs the `video` group to open `/dev/vcio_gencmd`. Without it, the power check says to rerun the installer.
* The HEVC decoder check compares `/dev/rpi-hevc-dec` with the media device whose `/sys/bus/media/devices/mediaN/model` names the decoder.
* `timedatectl show` prints its times as local strings; tm-control reads the clock itself.
* tm-control never writes the secrets directory; the `set-secret` and `network` jobs do. It reads the hotspot's password file (mode 0640, the secrets directory's group) for the one admin-only route.

## Keeping the credits current

The About page lists the open source projects the device is built on. Its list is one file, `tm-control/ui/src/modules/about/credits.json`, with a row for each project: its name, license type, address, the group it is shown in, and sometimes a short note. The two rows in the group `built-on` (Frigate NVR and Node-RED) also have a sentence in `does`, which the page shows under "Built on".

The list credits only what Traffic Monitor names itself, not what those projects bring with them:

* the direct dependencies of the control app's pages (`tm-control/ui/package.json`), of its backend (`tm-control/backend/requirements.txt`), and of Node-RED (`container/node-red-tm/data/package.json`);
* the components the installer records in the manifest (`components` in the role's `tm-control_service.yml`), such as Frigate, go2rtc, and nginx;
* a few things the installer puts on the unit by name, such as FFmpeg, Podman, and Cockpit.

Each row's `covers` list says which dependencies and components the row answers for, as `ui:<npm name>`, `node-red:<npm name>`, `python:<pip name>`, or `component:<manifest key>`. A row with no `covers` is one the test can't check.

`script/tests/test_about_credits.py` fails when a dependency or a component has no row, and when a row answers for something that is gone. Its message names each one, so it tells you what to add or remove. To add a row, copy the license type from the project's own license file, not from a package listing, and use the project's own page as the address. If the project states no license, ask the maintainer rather than guessing. Open the address to check that it works.

The test can't see these, so look them over before a release:

* the apt packages in the role's `vars/main.yml`, and whether a package is worth a row (a new service or a new tool the installer relies on);
* the Containerfiles, for the video tools they build, FFmpeg and its encoders (x264 and x265) among them, and the license each is built under;
* the Coral model and where it comes from. Its row gives YOLOv9's license, GPL-3.0, and not the MIT license of the repository that publishes the model: a unit holds only the model file and its labels, the model is built from YOLOv9, and its release states no license of its own. If a later release states one, use that;
* the map source (`tmsetup_map_style_url`), and the credit the page gives for it;
* the sentence about trademarks, which names each trademark's owner. Add a name when a new project's name appears on the page, and keep to naming projects, never showing their logos.

The same page links to `third-party-licenses.txt`, the license texts of the libraries bundled into the control app's pages. The UI build makes it (`build.license` in `tm-control/ui/vite.config.ts`) and writes it to `dist/`. It is generated, so never edit it or add it to git.

## Run it on a laptop

Fake mode runs the whole app without a Pi: it uses the test manifest, fixed secrets that aren't secret, a job runner that pretends, a clock in memory for the Date and time page, a status report from `tests/fixtures/status_fake.json`, whose groups show every status and kind of fix, a fake Node-RED for the Location page, and a fake Frigate with a second camera, `oak_ave_tele`, that no entry in the seeded `config.yml` points at, so the Cameras page's actions work. Its state goes in `./.tm-control-fake/`. From the repository root, in the dev environment from [Contributing](contributing.md):

```bash
TM_CONTROL_FAKE=1 PYTHONPATH=tm-control/backend python -m tm_control fake-reset   # an unclaimed device; prints its setup code
TM_CONTROL_FAKE=1 PYTHONPATH=tm-control/backend python -m tm_control serve        # the backend on 127.0.0.1:8090
cd tm-control/ui && npm ci && npm run dev                                         # the UI on http://localhost:5173
```

Fake mode seeds `.tm-control-fake/node-red-tm/config/config.yml` from `tests/fixtures/node_red_config_ok.yml` (a camera and a radar, and a `deployment` block at 45.0, -122.0 with no survey id), and keeps it, with whatever the app wrote to it, until the next `fake-reset`. Its Node-RED (`FakeNodeRed` in `fake.py`) keeps deployment rows in memory and runs the deployment engine's rules on them whenever that file changes, so deploys, corrections, and hand edits of the file behave as on a device; after a restart of `serve`, only the place in use has deployments. It has no traffic to count, so an open camera or radar row counts as having recorded traffic 30 seconds after it starts (`RECORDS_AFTER`), which is what lets the Mounting save's question come up on a laptop. Its backup directory is empty, so there's nothing to import. Fake mode also seeds `.tm-control-fake/model_cache` with two synthetic model pairs and the installer's model file, and keeps the model its fake Frigate runs in `.tm-control-fake/running-model`; Use there changes that file and restarts nothing. The fake Frigate can download one Frigate+ model ID, `fedcba9876543210fedcba9876543210` (`fake.FAKE_FETCHABLE_ID`); any other ID is refused after 5 seconds (`FAKE_FETCH_SECONDS`), as a device would show a refusal. The Frigate+ key has to be set first, or the route answers 409 `no_key`. In fake mode the API's interactive docs are at `/api/v1/docs`. `tm-control/ui/README.md` has the commands for building and testing the UI in the same Node image the device uses.

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
5. **A new app behind the login:** add its location file with an auth snippet to `container/revproxy/tm/locations/` and to `tmsetup_revproxy_locations`, and its tile to `APPS` in `modules/system/router.py` and to `ui/src/modules/home/apps.ts`. An app on its own port, as Cockpit is on 9090, has no location file: its `APPS` row has `None` for the file and its port, and the tile links to that port on the name the browser used.
