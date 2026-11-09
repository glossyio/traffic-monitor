---
description: How the control app (tm-control) is built: its backend modules, the login check nginx runs for every app, root jobs, fake mode, and how to add a module.
---

# tm-control

`tm-control` is the device's control app: the home page, setup, the login in front of every app, and the device's accounts. [Control app and login](../use/control-app.md) describes it from the operator's side. This page is for changing it.

It has three parts, all in the repository's [`tm-control/`](https://github.com/glossyio/traffic-monitor/tree/main/tm-control) folder:

| Folder | What it is | How it reaches the device |
|---|---|---|
| `backend/` | The Python app (FastAPI) and the `tm-control` command | Copied root-owned to `/usr/local/lib/traffic-monitor/tm-control`, with its own virtual environment, and run as `tm-control.service` |
| `ui/` | The web pages (Vue 3, Vuetify 3, TypeScript, Vite) | Built into the reverse proxy's image and served by nginx at `/` |
| `jobs/` | Scripts for the few things that need root | Copied root-owned to `/usr/local/libexec/traffic-monitor/` and run by fixed systemd units |

## How it runs

`tm-control.service` runs on the host, not in the pod, so the login keeps working when Podman doesn't. It runs as the code owner (default `tmadmin`), never as root, in a systemd sandbox, and listens on `127.0.0.1:8090` only. nginx is the only way in from the network.

It reads two things the installer writes, and keeps one database of its own:

* `/etc/traffic-monitor/secrets/`: the session key, Frigate's proxy secret, and the Node-RED editor's token key, each generated once on the device.
* `/etc/traffic-monitor/manifest.json`: what the installer installed and found, such as the version, the installing user, the proxied apps, and the home page's colors.
* `/var/lib/tm-control/state.sqlite`: users, the claim and the setup code's hash, license acceptances, job records, and an audit log. Numbered migrations in `core/state.py` create and update it, recorded in `PRAGMA user_version`. Never change a migration that has shipped; add the next one.

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
  adapters/      the outside world: command (runs an argv list with a timeout, never a shell), systemd, yamlfile
  modules/       one folder per feature, each with a router: auth, setup, account, system, jobs
```

Rules live in the backend; the UI shows what the API returns and posts what the operator types. `tm-control/ui/README.md` describes the UI's layout and design.

### Root jobs

tm-control never runs as root and never uses sudo. polkit lets its user start, stop, and restart a fixed list of units (`tmsetup_tm_control_polkit` in the role's `vars/main.yml`), and that's all. For work that needs root, tm-control writes a request to `/run/tm-control/jobs/<name>.json` and starts `tm-job-<name>.service`, a fixed root-owned oneshot unit. Its script in `tm-control/jobs/` checks the request strictly, does one thing, and deletes the request. tm-control follows the run through the unit and the journal, and `GET /api/v1/jobs/{id}` reports its status and log lines. The one job so far, `system-password`, sets the installing user's Linux password. It refuses an account that doesn't exist or has uid 0. `tmsetup.sh` also refuses to run as root, but a remote install with `-l root` still records root as the installing user, so the job's own check is the one that counts.

## Run it on a laptop

Fake mode runs the whole app without a Pi: it uses the test manifest, fixed secrets that aren't secret, and a job runner that pretends. Its state goes in `./.tm-control-fake/`. From the repository root, in the dev environment from [Contributing](contributing.md):

```bash
TM_CONTROL_FAKE=1 PYTHONPATH=tm-control/backend python -m tm_control fake-reset   # an unclaimed device; prints its setup code
TM_CONTROL_FAKE=1 PYTHONPATH=tm-control/backend python -m tm_control serve        # the backend on 127.0.0.1:8090
cd tm-control/ui && npm ci && npm run dev                                         # the UI on http://localhost:5173
```

In fake mode the API's interactive docs are at `/api/v1/docs`. `tm-control/ui/README.md` has the commands for regenerating the UI's typed client after an API change, and for building and testing the UI in the same Node image the device uses.

Run the backend's tests with the rest of the off-device tests:

```bash
.venv/bin/python -m pytest tm-control/backend/tests script/tests container/node-red-tm/schema/tests
```

## Add a module

A feature is one backend module and, if it has pages, one UI module.

1. **Backend:** add `backend/tm_control/modules/<name>/` with a `router.py` (an `APIRouter`) and an `__init__.py` that makes `module = Module("<name>", router)`. Add it to `MODULES` in `modules/__init__.py`. Endpoints take `current_user` or `require_admin` from `modules/auth/deps.py`, and raise `ApiError` for anything the operator should see.
2. **State:** if it needs tables, add the next migration in `core/state.py`.
3. **UI:** add `ui/src/modules/<name>/` with its pages and an `index.ts` that lists its routes and menu entries, and add it to `ui/src/modules/index.ts`. Regenerate the typed client as the UI's README describes.
4. **Root work:** add the job's name to `JOB_NAMES` in `core/jobs.py`, its script to `tm-control/jobs/`, its unit to the role's `templates/tm-control/`, and the unit to the polkit list.
5. **A new app behind the login:** add its location file with an auth snippet to `container/revproxy/tm/locations/` and to `tmsetup_revproxy_locations`, and its tile to `APPS` in `modules/system/router.py` and to `ui/src/modules/home/apps.ts`.
