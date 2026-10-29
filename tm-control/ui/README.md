# tm-control UI

The control app's web pages: first-run setup, login, the home page with the device card and app tiles, the Status,
Device, and Date and time pages, the account page, and the admin's user list. It's a Vue 3 + Vuetify 3 + TypeScript
app built with Vite. The UI only
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
  The status, services, system info, and time endpoints declare their responses, so their types come from
  `schema.d.ts`. The older endpoints don't yet, and `types.ts` describes their bodies.
- `src/modules/<name>/` holds one feature's pages and an `index.ts` with its routes and menu entries.
- `src/components/` holds what several pages share: the device card, the confirmation dialog, the list of checks and
  their status marks (`status.ts`), and "20 seconds ago" in words (`relative-time.ts`).
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
text and as the status marks on the Status page, which against the navy are 5.2:1 (error) to 7.9:1 (warning); the
alert's faint tint lowers that a little.

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
because Vuetify writes Roboto and capitals into its CSS. The only other CSS:

- `src/styles/focus.css`: a 2 px keyboard focus ring in the primary color. Vuetify's own focus cue is too faint to
  see on the filled buttons (about 1.2:1), and raising its opacity can't reach the 3:1 a focus indicator needs.
- Three small scoped style blocks: the setup code field; spacing for the license agreement's headings and
  paragraphs, which come from markdown and can't take Vuetify's classes; and tabular digits for the clocks on the
  Date and time page.

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
| Status    |  | tm-device                       (h4)     |  |
| Device    |  | Traffic Monitor 0.7.1                    |  |
| Date and  |  | Serial number   Device time              |  |
|   time    |  | 000000001234    2026-10-27 14:32 (UTC-4) |  |
| Account   |  | (x) 2 problems need attention   (link)   |  |
| Users     |  +------------------------------------------+  |
|           |  Apps                                          |
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
- Keyboard focus is always visible, and moving between setup steps puts the focus on the new step's heading.
- Nothing waits forever: the system-password step stops waiting for the device after two minutes and lets setup go
  on, and "Skip for now" works while it waits.

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

### Status, Device, and Date and time

The same people use these pages, often on a phone at the roadside, on the device's hotspot, with no internet and no
SSH. Their one job is to answer "is it working, and if not, what do I do" at a glance, in sunlight, and then to let
an admin do the few things that fix it. The notes above still hold: the device's colors, system fonts, cards only
for objects, no toasts, results where they happened, nothing that depends on hover.

#### Color and type

- No new colors. The four check statuses use Vuetify's dark-theme success (`#4CAF50`), warning (`#FB8C00`), and
  error (`#CF6679`), and the secondary text color for "unknown", only on each check's status mark and the verdict's
  icon. Titles and details stay in the text colors: a page of colored rows looks alarming and says nothing.
- Shape carries the status as well as color: a tick (`mdiCheckCircle`), a triangle (`mdiAlert`), a cross
  (`mdiCloseCircle`), and a question mark (`mdiHelpCircle`). Each row also names its status for screen readers
  ("Problem: Frigate"). Both live in `src/components/status.ts`.
- The verdict is `text-h5` in the body text color, not the heading blue, which would fight the status icon beside
  it. Group titles are `text-h6`, check titles `text-body-1`, details `text-body-2` in the secondary color.
- The two clocks are `text-h4` with tabular digits, so the time doesn't shift sideways as it ticks.

#### Layout

Each page has one bold thing: the verdict on Status, the card on Device, the two clocks on Date and time. Content is
left-aligned and at most 760 px wide, as on the other pages.

Status (an admin's view; viewers see the same list with no buttons but Refresh):

```text
+----------------------------------+
| Status                      (h5) |
| (x) 2 problems need         (h5) |
|     attention                    |
| Checked just now        [Refresh]|
|                                  |
| Services                    (h6) |
| (v) Traffic Monitor pod          |
|     Running since 09:12.         |
| (x) Frigate                      |
|     Stopped after a failure.     |
|                 [Restart Frigate]|
|     Frigate is restarting. ...   |
|                                  |
| Hardware                    (h6) |
| (!) Radar on /dev/ttyACM1        |
|     A radar is plugged in, but   |
|     it isn't enabled. ...        |
| (v) HEVC decoder                 |
|     /dev/media1, reached ...     |
|                [Re-scan hardware]|
+----------------------------------+
```

- The verdict sums up the report: "Everything is working", "Working, with N things to look at" (warnings only),
  "N problems need attention" (any error), or "Some checks couldn't run" (unknowns and nothing worse). The home page's
  device card shows the same sentence as a link to `/status`.
- One plain list per group, with no tiles, counts, or collapsing: a problem is never hidden behind a tap.
- A check's fix shows as the API words it (`CheckList.vue`). A restart fix is a button named for the unit ("Restart
  Frigate"), right-aligned under the detail, for admins only. A group with any re-scan fix gets one "Re-scan
  hardware" button at its end. A link fix is a link at the end of the detail; a hint is a sentence after it.
- A restart asks first and says what the person will notice ("The camera view stops for about a minute while Frigate
  restarts."; `modules/status/restarts.ts`). Its result stays under the button until the check stops offering the
  restart.
- The list checks again every 10 seconds while the page is visible, and at once when it becomes visible again. A row
  that changes just changes, with no animation. When the device stops answering, the last list stays, with the error
  above it, and "Checked 2 minutes ago" keeps counting.
- "Checked ... ago" counts from when the page received the report, on the phone's clock, not from the report's own
  time: the device's clock may be wrong, which is one of the things the page reports.

Device:

```text
+----------------------------------+
| Device                      (h5) |
| +------------------------------+ |
| | tm-device              (h4)  | |
| | Raspberry Pi 5 Model B Rev   | |
| | 1.0, 8 GB memory             | |
| | Traffic Monitor 0.8.0        | |
| | Serial number                | |
| | Running for                  | |
| | Storage                      | |
| | 23 GB free of 58 GB          | |
| | [=======-------------------] | |
| | Temperature                  | |
| | Power                        | |
| +------------------------------+ |
| Software                    (h6) |
| Frigate 0.18.1    Node-RED 5.0.8 |
| go2rtc 1.9.14     nginx 1.31.0   |
| Commit 2da617a on dev   ...      |
| Diagnostics                 (h6) |
| [Download diagnostics] [Copy]    |
| Power                       (h6) |
| [Reboot the device]              |
| [Shut down the device]           |
+----------------------------------+
```

- The device card is the home page's card, extended: the one card, because the device is the one object. The storage
  line has the app's only bar, because it shows a proportion, which words do badly.
- Diagnostics and Power are for admins only. Copy uses the browser's clipboard on HTTPS and, on the plain HTTP a
  device is usually reached over, the older select-and-copy. That can be refused, because the tap that asked for it
  was a few seconds ago by the time the text arrives (iOS Safari is strict). Then the text appears in a read-only
  box, already selected, with "Copy the text from the box below." A later Copy or Download hides the box again.
  Selecting sets the range as well as calling `select()`, which iOS Safari ignores on a read-only textarea.
- Reboot and Shut down each ask first. After the device accepts, the page says "Rebooting. This page will stop
  answering for about two minutes." in place of the buttons. When something such as an update holds the shutdown off,
  the API's message shows there instead.

Date and time (below 600 px the clocks stack, the device's first):

```text
+----------------------------------+
| Date and time               (h5) |
| This device                      |
| 14:32:07                    (h4) |
| Oct 28, 2026                     |
| UTC-07:00                        |
| This phone                       |
| 14:35:12                    (h4) |
| ...                              |
| The device is 3 minutes behind   |
| this phone.                      |
| [Set from this browser]          |
|                                  |
| [Time zone: America/Los_A... v]  |
| [Save time zone]                 |
|                                  |
| (o) Keep time from the internet  |
|     The device has no time       |
|     source right now, so its     |
|     clock runs on its own.       |
+----------------------------------+
```

- Both clocks tick on from the last answer. The sentence under them compares the instants, and the offsets from UTC
  the clocks show, so two names for one zone (`Etc/UTC` and `UTC`) don't read as different. The device reports whole
  seconds, so its clock can trail the phone's by a second; the sentence allows five.
- "Set from this browser" is the filled main button when the clocks differ, and outlined when they agree. It sends
  the browser's time and time zone, and the result says what the device did: "Time set from this phone.", or "The
  device already keeps time from the internet, so only the time zone changed.", followed by "Frigate and Node-RED are
  restarting." when the zone changed. When the device doesn't know the phone's zone (its tzdata can be older), the
  time still goes on and the result adds "The device doesn't know this phone's time zone (<zone>), so pick one below."
- Each change on the page clears the results of earlier ones, which it may have made untrue.
- A viewer sees the clocks, the sentence, the time zone, and whether the device keeps time from the internet, with
  no button, picker, or switch, and the page ends with "An administrator can set the time and time zone here."

#### What the screenshot review changed

The pages were checked in fake mode at 375 px and 1366 px wide, as an admin and as a viewer.

- Tapping the time zone picker put the caret where the finger landed, so typing "Berlin" made
  "America/Los_AngBerleles" and an empty list. The picker now selects its text when it gets focus, so typing replaces
  the zone.
- After a zone change and turning NTP off, the earlier "already keeps time from the internet" result still sat under
  "Set from this browser" and contradicted the switch below it. Each change now clears the earlier results.
- A "Time zone" heading sat right above a picker whose own label reads "Time zone". The heading is gone; a viewer
  sees "Time zone" as a label above the zone's name, like the card's facts.
- Looked at and kept: when Frigate is down, three checks offer "Restart Frigate", and a restart's result shows under
  all three, because each button does the same thing and the result tells the person not to press the others. On a
  wide screen the right-aligned buttons sit far from their row's text, but they line up in one column with Refresh,
  and one layout for every width keeps the list simple.

#### Defaults rejected

- Dashboard tiles with counts per group, a donut, or badges per section: the verdict sentence says it in words.
- Colored row backgrounds: color only on the status marks.
- Collapsible groups: a problem must never be hidden behind a tap.
- A snackbar for "Restarting": results stay under the button that caused them.
- An icon-only or "Fix" button: each button names what it acts on.
- A `datetime-local` input for setting the time: the browser already knows the time, and typing it at the roadside
  is error-prone.
- Animating list changes when the checks refresh.
- A gauge for the temperature.
- "Checked ... ago" from the report's own time: wrong whenever the device's clock is.
