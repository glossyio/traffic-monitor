# tm-control UI

The control app's web pages: first-run setup, login, the home page with the device card and app tiles, the
account page, and the admin's user list. It's a Vue 3 + Vuetify 3 + TypeScript app built with Vite. The UI only
shows what the API returns and posts what the operator types; the rules live in the Python backend
(`tm-control/backend`).

On a device, tmsetup copies these sources into the reverse proxy's build directory, and the revproxy image builds
them with `npm ci && npm run build` in a pinned Node container (`container/revproxy/Containerfile.j2`). nginx
serves the result at `/` (`container/revproxy/tm/locations/tm-control-ui.conf.j2`).

## Run it on a laptop (fake mode)

Fake mode runs the backend with the test manifest, fixed secrets, and a fake job runner, so the whole app works
without a Pi. Its state goes in `./.tm-control-fake/`, which git ignores. Run these from the repo root, in the dev
venv (see the repo's `CLAUDE.md`):

```bash
# 1. Start over as an unclaimed device. Prints the setup code to type on the setup page.
TM_CONTROL_FAKE=1 PYTHONPATH=tm-control/backend python -m tm_control fake-reset

# 2. Run the backend on 127.0.0.1:8090. Restart it after each fake-reset.
TM_CONTROL_FAKE=1 PYTHONPATH=tm-control/backend python -m tm_control serve

# 3. In another terminal, run the UI at http://localhost:5173. It sends /api and /logout to the backend.
cd tm-control/ui && npm ci && npm run dev

# 4. After an API change, update the API description the client is typed from.
PYTHONPATH=tm-control/backend python -m tm_control dump-openapi > tm-control/ui/src/api/openapi.json
cd tm-control/ui && npm run api:generate
```

`npm run build` writes the site to `dist/`, and `npm test` runs the Vitest tests in `tests/`. To use the same Node
as the device's build, run them in the pinned image:

```bash
podman run --rm -v "$PWD/tm-control/ui:/ui:Z" -w /ui docker.io/library/node:22.23.4-alpine \
    sh -c 'npm ci && npm run build && npm test'
```

## How the code is laid out

- `src/main.ts` loads the device's setup status, builds the theme from its colors, and mounts the app.
- `src/router.ts` decides where each navigation goes: an unclaimed device to `/setup`, no session to `/login`, an
  outstanding license to `/welcome` (admins) or `/waiting` (viewers), and `/users` to admins only.
- `src/stores/session.ts` is the only store: the setup status and the logged-in user.
- `src/api/client.ts` is the API client. `schema.d.ts` is generated from `openapi.json`; don't edit either by hand.
  `types.ts` describes the response bodies, which the API doesn't declare yet.
- `src/modules/<name>/` holds one feature's pages and an `index.ts` with its routes and menu entries.
- `src/next.ts` decides where to go after login, and refuses to send anyone off the device.

## Design notes

Who uses it: people who claim and run a pre-built Traffic Monitor. Many aren't technical, many are on a phone at the
roadside, joined to the device's own hotspot, with no internet. So the pages have to read clearly on a 375 px
screen, load with nothing from the internet, and say plainly what to do next.

### Color

The colors come from the device's home-page theme (`tmsetup_homepage_colors`), which `GET /api/v1/setup/status`
returns, so the setup and login pages already use them. `src/theme.ts` maps them onto one dark Vuetify theme:

| Theme color       | Default   | Used for                                                                 |
|-------------------|-----------|--------------------------------------------------------------------------|
| `background`      | `#0C1120` | The page background                                                      |
| `header_text`     | `#3a82ff` | Page headings (as on the old home page), primary buttons, links, focus   |
| `body_text`       | `#f8fafc` | Body text and text on cards                                              |
| `link_hover_text` | `#8895a7` | Secondary text: hints, labels, the "Step 2 of 4" line                    |
| (derived) surface | `#181d2b` | Cards and dialogs: the background mixed with 5% of the body text color   |
| (Vuetify) error   | `#CF6679` | Error messages and the red confirm buttons ("Remove viewer")             |

Contrast, for the defaults: body text on the background is about 18:1 and secondary text about 6:1. The blue is
5.2:1 against the navy, so headings and links pass WCAG AA. White text on the blue would be only 3.6:1, and white on
the red about 3.5:1, so filled buttons use the navy as their text color (5.2:1 on both). `theme.ts` picks whichever
of the background and body text colors reads better on each button color, so a device with other colors keeps
readable buttons. Warning, info, and success colors stay Vuetify's dark-theme defaults. They appear only as alert
text, which against the navy is 5.2:1 (error) to 7.9:1 (warning); the alert's faint tint lowers that a little.

### Type

System fonts only, so nothing is downloaded: `system-ui, -apple-system, "Segoe UI", Roboto, "Noto Sans",
"Helvetica Neue", Arial, sans-serif`. The manifest's font name (`Helvetica`) is ignored, because a font name alone
falls back unpredictably on Android and Windows. The scale uses Vuetify's typography classes:

- Device name on the home page: `text-h4` (34 px).
- Page titles: `text-h5` (24 px), in the heading color.
- Section titles: `text-h6` (20 px).
- Body and form text: `text-body-1` (16 px). Hints and labels: `text-body-2` (14 px) in the secondary color.
- The setup code field: monospace, larger, with wider letter spacing, so it reads like the code printed on the card.

The font stack and sentence-case buttons are set in `src/styles/settings.scss`, Vuetify's documented SASS settings,
because Vuetify writes Roboto and capitals into its CSS. Two small scoped style blocks are the only other CSS: the
setup code field, and spacing for the license agreement's headings and paragraphs, which come from markdown and
can't take Vuetify's classes.

### Layout

Pages before login (setup, login, the license pages) have no menu: one column, at most 480 px wide, centered, with
a small "Traffic Monitor" name above the page title. Pages after login have the app bar and a menu drawer that stays
open from the `md` breakpoint (960 px) up and slides in below it. Content is left-aligned and at most 760 px wide.

Setup (one page, four steps):

```text
+--------------------------------+
| Traffic Monitor                |
| Step 3 of 4                    |
| [=========-----]               |
|                                |
| Create the administrator       |
| account                        |
|                                |
| Setup code                     |
| [ ABCD-EFGH        ]  (mono)   |
| Username  [            ]       |
| Password  [            ]       |
| Confirm   [            ]       |
|                                |
| [Back]      [Claim this device]|
+--------------------------------+
```

Home (desktop; on a phone the drawer hides behind the menu button and the tiles stack):

```text
+-----------+------------------------------------------------+
| Traffic Monitor                                     (bar)  |
+-----------+------------------------------------------------+
| Home      |  +------------------------------------------+  |
| Account   |  | tm-device                       (h4)     |  |
| Users     |  | Traffic Monitor 0.7.1                    |  |
|           |  | Serial number   Device time              |  |
|           |  | 000000001234    2026-10-27 14:32 (UTC-4) |  |
|           |  +------------------------------------------+  |
|           |  Traffic data                                  |
|           |  [Dashboard] [Frigate] [Legacy dashboard]      |
|           |  Device administration         (admins only)   |
|           |  [Node-RED] [Camera feeds] [Cockpit]           |
| admin     |                                                |
| Log out   |                                                |
+-----------+------------------------------------------------+
```

Account: the username and role, then "Change your password", then "Log out everywhere". Users: who can view the
data, an "Add a viewer" form, and the list of accounts, each viewer with a menu to set a new password or remove them.

### Copy

- Name things as the operator knows them: the device, the setup code on the card, the system password (the Linux
  password for Cockpit and SSH), administrator and viewer.
- Buttons say what happens: "Start setup", "Claim this device", "Set system password", "Skip for now", "Log in",
  "Change password", "Add viewer", "Remove viewer", "Log out everywhere". A result uses the same verb ("Password
  changed").
- Errors show the API's own message, which says what went wrong, and add the next step where the API can't know it,
  such as "Check that this phone is still on the device's network" when the device doesn't answer.
- Results appear next to the form that caused them and stay there, rather than in a toast that disappears.
- Sentence case, no exclamation marks, no apologies.

### Principles

- One memorable element: the device card, which reads like the label on the box, with the device's name as the
  largest text in the app. Everything else is quiet.
- Cards only for things that are objects (the device, an app to open); forms sit directly on the page.
- Nothing depends on hover. The main action on each page is a large button (44 px tall), and menu rows are 48 px.

### What the screenshot review changed

The first build was checked in fake mode at 375 px and 1366 px wide. These changed after that review:

- The red confirm buttons had white text at 3.5:1. They now get the navy, like the blue buttons.
- The menu used Vuetify's compact "nav" list, whose 13 px text is small on a phone. It's a plain list now (16 px).
- Checkboxes sat 8 px inside the text column; they now line up with it.
- Fake mode showed the laptop's own hostname on the device card, which would end up in shared screenshots. Fake
  mode now reports `tm-fake`, as it already reported a fake serial number.

### Defaults rejected

- Vuetify's capitalized buttons: harder to read, and capitals read as shouting.
- Vuetify's stepper header for setup: its four labelled steps wrap or truncate at 375 px. "Step 3 of 4" with a
  progress bar says the same in one line.
- Toasts (snackbars) for results: they vanish before someone glancing at a phone reads them.
- Icon-only row actions on the users page: a menu with words is clearer, and fits a phone.
- Stat tiles with big numbers on the home page: the device has no live numbers to show yet, and the next milestone's
  status checks get their own page.
- A web font, or Roboto from Google: the device is often offline.
