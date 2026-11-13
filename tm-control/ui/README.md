# tm-control UI

The control app's web pages: first-run setup, login, the home page with the device card and app tiles, the Status,
Device, Detection, and Date and time pages, the admin's Location page, the account page, and the admin's user list. It's a Vue 3 + Vuetify 3 + TypeScript
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

Regenerate `package-lock.json` with npm 11 (`npx -y npm@11 install --package-lock-only`), not with the npm in
the device's Node image. Its npm 10.9.9 crashes while resolving Vitest 4.1.x. `npm ci` with that npm 10 installs
from an existing lockfile without trouble, so the image still builds and tests the UI.

## How the code is laid out

- `src/main.ts` loads the device's setup status, builds the theme from its colors, and mounts the app.
- `src/router.ts` decides where each navigation goes: an unclaimed device to `/setup`, no session to `/login`, an
  outstanding license to `/welcome` (admins) or `/waiting` (viewers), and `/users`, `/location`, and `/cameras` to admins only.
- `src/stores/session.ts` is the only store: the setup status and the logged-in user.
- `src/api/client.ts` is the API client. `schema.d.ts` is generated from `openapi.json`; don't edit either by hand.
  The status, services, system info, and time endpoints declare their responses, so their types come from
  `schema.d.ts`. The older endpoints don't yet, and `types.ts` describes their bodies.
- `src/modules/<name>/` holds one feature's pages and an `index.ts` with its routes and menu entries. The `location`
  module is the Location page (`LocationPage.vue`), a place's panel (`PlaceDetails.vue`), and its dialogs: adding or
  editing a place (`PlaceForm.vue`), the deploy review (`DeployReview.vue`), corrections (`CorrectDialog.vue`), and
  importing (`ImportPlaces.vue`). Its `coordinates.ts` shows coordinates, names the bearing and precision choices,
  checks a pasted pair (`parsePair`) before the form sends it, and measures how far a correction moves a point
  (`distanceKm`). It never rounds: the API sends the stored coordinates already rounded, and its answer wins over the
  form's check.
- The `cameras` module is the Cameras page (`CamerasPage.vue`), a camera's settings form (`CameraEdit.vue`), and `rows.ts`,
  which holds the rules the page asks of a row (`rowState`, `zonesText`, `radarChoices`, `pointChoices`) so the page and
  its actions ask the same questions. Design notes: the page is a bordered `v-expansion-panels` accordion, one panel
  per camera and one open at a time, in the Location page's conventions (load, error, and 409-reload; no custom CSS),
  with the key in bold because it is the name saved with the data, and Frigate's name beside it in the secondary color
  because it stays on the device. A panel's header is the camera's summary, with what it opens in words beside the
  chevron (Settings, or Add as new for a Frigate camera no entry points at), so the boxes can say "in Settings"; the
  settings form opens right under it, inside the row, and the row's boxes and buttons sit below the form, outside the
  header, because a header is a button and can't hold links or buttons. A new Frigate camera's panel doesn't open while
  Frigate can't be compared.
  Each row's first words are its two switches, Frigate detection and Database capture, because an event is recorded
  only when both are on; `CameraEdit` sets Frigate's with its own request after the settings' `PUT`, and only when it
  changed. Only Off in Frigate is a chip. What the Status page's camera checks report about a row (the API's `issues`)
  is a compact tonal `v-alert` in the row, in the check's color, worded by `issueBoxes` with what to do on this page
  (a zones box links to Frigate's masks and zones settings at that camera), and one alert above the list counts the
  rows that need attention. An entry in step has no box, nor has a new Frigate camera whose detection is off (it drops
  nothing, so the API reports no issue for it; it keeps Point and Add as new), and while Frigate can't be compared a row
  shows its settings and nothing about Frigate. The actions that need the comparison (Point at this, Add as new, Use a
  neutral name, Remove) are offered only while Frigate answers and has cameras. Point, Use a neutral name, and Remove
  confirm first in a dialog (the error color only for Remove); Add as new opens `CameraEdit` with `adding`, which
  POSTs. A save that works closes the panel; one that fails keeps it open with the reason inside it. A refused
  action shows the API's message above the list, and a 409 or 404 (another admin got there first) loads it again.
  Every write answers with the whole new state, which replaces the page's, so there is no second request.
  The Radar field is a drop-down, because the radars are a short fixed list and a typed name could only be wrong:
  each shows its state under its name, a radar `config.yml` doesn't set up can't be chosen, and a radar the file
  names that the unit doesn't have is listed as missing so the field says what the file says. Vuetify's select shows
  nothing for a `null` value, so the form holds "No radar" as an empty string and turns it back into `null` on Save.
  The plates switch is there only when the add-on is installed; otherwise Save sends `null` and leaves the file's value
  alone. A 422 for the radar shows under the field, every other failure inside the form.
- `src/components/` holds what several pages share: the device card, the confirmation dialog, the list of checks and
  their status marks (`status.ts`), "20 seconds ago" in words (`relative-time.ts`), waiting for a root job
  (`jobs.ts`, used by setup's system password and the entered secrets), one entered secret's form
  (`EnteredSecret.vue`, the Device page's tokens and keys and the Detection page's Frigate+ key), copying text
  (`clipboard.ts`, the diagnostics and the label lists; `CopyButton.vue`, an icon button that copies one value), and
  saving a file (`download.ts`, the diagnostics and the model packages and files).
- The `network` module is the Network page (`NetworkPage.vue`), the hotspot's settings for admins
  (`HotspotSettings.vue`, its name-or-password dialog `HotspotField.vue`, and `rules.ts`, the name and password rules),
  `FactRow.vue` (a label above a value with its Copy button), and `summary.ts`, the words for the unit's links and
  internet that the Device page's card reuses.
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
- On the unit's own hotspot, the login and setup pages open with a tonal info note (`HotspotNote.vue`): no internet,
  and the `.local` address to open in a browser on an iPhone. The address is text, not a link, because a link would open
  inside the phone's sign-in window.

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
| +------------------------------+ |
| | Tokens and keys     (h6)  v  | |
| +------------------------------+ |
|   opened:                        |
|   Credentials this device ...    |
|   ThingsBoard access token       |
|   Set, ending in 0001.           |
|   [ ThingsBoard access token (o)]|
|   [Save] [Remove]                |
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
- Tokens and keys is for admins only, between Software and Diagnostics: one form per secret `GET /secrets` lists,
  but the Frigate+ API key, whose form is on the Detection page. The ThingsBoard access token appears on every
  device; the Plate Recognizer token and license key appear only on a device with the add-on. The section ends with
  "The Frigate+ API key is on the Detection page.", the last words a link to `/detection#frigate-plus`, so an admin
  who looks for the key here finds it. It's one expansion panel,
  closed when the page opens. The Status page's "Set the token" links to `/device#tokens-and-keys`, which opens it and scrolls to
  it. The page shows no problem there, so closing it hides nothing a person needs to see: the Status page warns
  about a missing token. The panel's title, a button, sits inside the `h2`, so the heading stays a heading for
  screen readers. Each form is a small heading
  with the secret's name, a line saying whether it's set ("Set, ending in 0001.", "Set." when the device shows no
  ending, "Not set."), a field that is always empty when the page loads, Save, and Remove when there's something to
  remove. The value is never shown back, so the field can't hold the current one; the ending is how an admin tells
  which token the device has. The field hides what's typed, with an eye button ("Show"/"Hide") to check a long
  token before saving it, and it's emptied once the device has the value.
- Saving or removing restarts the apps that read the value, so it takes as long as they do. While the job runs, an
  info line under the buttons says so ("Saving. Node-RED restarts, which takes about thirty seconds."), as setup's
  system-password step does, rather than leaving only a spinner for half a minute. The time is the sum of each app's
  (Node-RED and Plate Recognizer about thirty seconds, Frigate about a minute). Frigate's note adds "Traffic isn't
  counted while it does.", because the page says "Frigate restarted." when its container is up, before detection
  has started again. Remove asks first and names both
  the restart and what stops ("The upload to ThingsBoard stops until a token is set again."). Save doesn't ask:
  the section's paragraph already says it restarts the app, and a second tap for every token would be noise.
- The result stays under the form: "Saved. Node-RED restarted.", or "The value wasn't saved." with the job's log
  lines. When the log says the secret is written (an app failed to restart after the write), the headline says "The
  value was saved, but a restart failed." instead, so it doesn't contradict the log. Or, when the device never reports (the page waits five minutes, because the job can wait out two
  restarts), a warning to reload the page in a minute.
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
| This browser                     |
| 14:35:12                    (h4) |
| ...                              |
| The device is 3 minutes behind   |
| this browser.                    |
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
  seconds, so its clock can trail the browser's by a second; the sentence allows five.
- "Set from this browser" is the filled main button when the clocks differ, and outlined when they agree. It sends
  the browser's time and time zone, and the result says what the device did: "Time set from this browser.", or "The
  device already keeps time from the internet, so only the time zone changed.", followed by "Frigate and Node-RED are
  restarting." when the zone changed, or by "The clock moved ahead, so Frigate is restarting. The camera view is back
  in about a minute." when the time moved ahead by more than 20 seconds (`restarting` lists `frigate.service`; the
  device restarts Frigate because such a step stops its camera feed). When the device doesn't know the browser's zone
  (its tzdata can be older), the time still goes on and the result adds "The device doesn't know this browser's time
  zone (<zone>), so pick one below." When the device had to leave internet time off to keep the new time
  (`ntp_left_off`), the result says so and asks to turn on Keep time from the internet once the device is online.
  When internet time reached a time source while the time was being set (`ntp_took_over`), the result says the device
  got the time from the internet and keeps that, not the browser's. The Frigate sentence follows any of these.
- Each change on the page clears the results of earlier ones, which it may have made untrue.
- A viewer sees the clocks, the sentence, the time zone, and whether the device keeps time from the internet, with
  no button, picker, or switch, and the page ends with "An administrator can set the time and time zone here."

#### Using a model by its ID, 2026-11-13

A Frigate+ model could only be used once it was on the device, which meant Frigate's own settings page or an upload,
and a person with a phone and the model's ID on the Frigate+ website had to leave the control app for the first.
The Frigate+ section now has a second panel, beside the key's: paste the ID, and Frigate downloads the model. It sits
with the key because the key is what it needs, and it is a panel because it's for the one time a model is chosen, so
it needn't take room on a page most people read. The download takes minutes, so the panel opens when one runs and the
page follows it instead of holding a request, and the Status page's Frigate+ warning (a key, no Frigate+ model) now
links to it.

#### What the screenshot review changed

The pages were checked in fake mode at 375 px and 1366 px wide, as an admin and as a viewer.

- Tapping the time zone picker put the caret where the finger landed, so typing "Berlin" made
  "America/Los_AngBerleles" and an empty list. The picker now selects its text when it gets focus, so typing replaces
  the zone.
- After a zone change and turning NTP off, the earlier "already keeps time from the internet" result still sat under
  "Set from this browser" and contradicted the switch below it. Each change now clears the earlier results.
- A "Time zone" heading sat right above a picker whose own label reads "Time zone". The heading is gone; a viewer
  sees "Time zone" as a label above the zone's name, like the card's facts.
- Tokens and keys (checked in fake mode at 375 px and 1366 px, with and without the Plate Recognizer add-on): the
  first build showed only a spinner on Save while the job ran, which on a device lasts half a minute or more. The
  info line under the buttons came from that.
- Looked at and kept: each token's name shows twice, as the form's heading and as the field's label. The heading
  carries the "Set, ending in 0001." line, and the label is what a screen reader announces in the field.
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

### Detection

The same people, the same rules. The page answers "what does this device look for, and with which model". It is also
where the Frigate+ API key lives, and where a Frigate+ model is used by its ID, since the key is how Frigate gets a
Frigate+ model. Everyone who can log in sees it all; admins also get the key's form, the ID form, and the actions that
change the model (upload, use, download, delete), which sit in this layout without moving anything.

The page keeps the running model in one place, its card under "Model in use", and has four sections in this order:
Object detection, Model in use, Frigate+, Other models on this device.

```text
+------------------------------------+
| Detection                     (h1) |
| See which model Frigate detects ...|
|                                    |
| Object detection              (h2) |
| [! Frigate isn't answering; ...]   |
| Detector        Running model      |
| edgetpu         My model, a local  |
|                 model              |
|                                    |
| Model in use                  (h2) |
| +--------------------------------+ |
| | My model  (In use)        (h3) | |  <- tinted
| | Local model, trained 2026-10.. | |
| | Tracked but not recognised by  | |  <- outside the fold: visible
| | the running model: !dog! !cat! | |     while it is closed
| | [Download]                     | |
| | (Frigate runs My model.)       | |
| | v Files and objects            | |  <- open here; "Objects" with no files
| |   Frigate tracks only the      | |
| |   objects in both lists.       | |
| |   (Frigate reports a different | |  <- only when the lists differ
| |    list than this model's      | |
| |    .json.)                     | |
| |   Objects the running model    | |
| |   recognises (3) (h4)  [Copy]  | |
| |   As Frigate reports them.     | |
| |   [person] [bicycle] (car)     | |  <- [filled] = tracked
| |   Filled: tracked on this      | |
| |   device.                      | |
| |   Objects tracked on this      | |
| |   device (6, 2 not recognised) | |
| |   (h4)                 [Copy]  | |
| |   (person) (car) !dog! !cat!   | |  <- !amber! = not recognised
| |   Amber: the running model     | |
| |   doesn't recognise it.        | |
| |   mine.tflite, 2.0 KB, SHA-256 | |
| |   mine.tflite.json, 433 bytes  | |
| +--------------------------------+ |
|                                    |
| Frigate+                      (h2) |  <- outside the panel
| When the device is online and has  |
| a Frigate+ API key, an             |
| administrator can use a model by   |
| its ID below, or ...               |  <- both paragraphs: everyone
| When it's offline, an              |
| administrator can upload ...       |
| > API key  set, ending in 0001     |  <- admins: two panels, closed (an
| > Use a model by its ID            |     h3 holds each title); a viewer
|                                    |     sees no panels
|                                    |
| Other models on this device (2)(h2)|
| [Upload a model]                   |
| (Deleted ... result, if any)       |
| +--------------------------------+ |
| | The installer's model     (h3) | |
| | yolov9-s-...edgetpu.tflite     | |
| | [Use] [Download]               | |  <- filled, outlined
| | > Files                        | |
| +--------------------------------+ |
| +--------------------------------+ |
| | Test site yolov9          (h3) | |
| | Frigate+ model, trained ...    | |
| | [Use] [Download] [Delete]      | |  <- filled, outlined, error outlined
| | v Files and objects            | |
| |   0123...cdef, 4.0 KB, SHA-256 | |
| |   0123...cdef.json, 433 bytes  | |
| |   Objects it recognises (3)(h4)| |
| |   [Copy] [person] [bicycle] .. | |
| |   Filled: tracked on this      | |
| |   device.                      | |
| |   Doesn't recognise 2 objects  | |
| |   tracked on this device:      | |
| |   !dog! !cat!                  | |
| +--------------------------------+ |
| (No other models on this device.)  |  <- when there are none
+------------------------------------+
```

A viewer sees the same page without Upload, the card buttons, and the two Frigate+ panels, and keeps the Copy buttons
and the Frigate+ text.

- A line under the title says what the page is for, in two sentences so a viewer isn't told the page lets them
  switch models.
- The detector and the running model are two facts, label above value, in the Device page's Software grid.
  "Detector", not "Hardware detector", because the value is `cpu` on a device without an accelerator; "Running
  model", because the page's verb for the state is "runs". The detector is named as Frigate and a model's sidecar
  name it, so it can be matched against the "for edgetpu" under each model. When Frigate doesn't answer, a warning
  above the facts says the page shows what Frigate's config file says.
- Each model is a bordered card (`border rounded-lg`): its title in an h3, so a screen reader can step between models,
  then its facts on one line, starting with its kind ("Frigate+ model" or "Local model"). The border says each card is
  one choice. Only the card Frigate runs is tinted, with the theme's `surface` (no elevation, no new color). A card
  shows what decides a switch, and its files and objects wait in its own closed fold, titled "Files and objects", or
  "Files" for a model with no labels. The fold's title is a plain button, not a heading, and the fold is transparent so
  the tint shows through. Each model looks the same wherever it's listed.
- The fold has one line per file with its size and the first 12 characters of its SHA-256. The full hash is the hash's
  tooltip, for comparing with a download's SHA256SUMS on a computer; on a phone the 12 characters are enough to tell
  two files apart. A file's name shows only when it isn't the title already. The installer's model has no sidecar, so
  it's titled "The installer's model", with its file name as its facts line. At 375 px each of those lines wraps to
  two, "SHA-256" and its hash staying together. A file name may break anywhere (`word-break: break-all`, scoped in
  `ModelBlock.vue`): the names that are long are IDs, and otherwise a 32-character Frigate+ name that fills a card's
  line leaves its comma to start the next one.
- The card in use is always there once the models have loaded, so the running model's lists have a home whether
  Frigate answers or not. The page makes the card when the list has none. A default with no file on the device
  (Frigate's built-in model on a device without a Coral, which the API can't list) gets one with "Built into
  Frigate." as its facts line ("Set up by the installer." for the installer's model) and no files; a running model
  with no entry in the list gets one titled with its name, or "Unknown model" when Frigate gave none, with no buttons
  and no file lines. Without the first, a CPU device's one choice would be a button with no
  card. The other cards are as the API lists them.
- One chip per model at most, in words: "In use" (in the heading blue), "can't run on this detector", or
  "incomplete" (a model file without its sidecar, or the other way round). The API's reason, when it has one, is a
  line under the facts.
- The card in use's fold holds the running model's lists, in this order: the sentence "Frigate tracks only the objects
  that are in both lists.", the "different list" line when it applies, "Objects the running model recognises" with its
  source line, "Objects tracked on this device", then the file lines. The sentence says how the two lists relate, so
  "dog" in the second list and not the first is never tracked. The second is "Objects tracked on this device", not "by
  this model", because it's Frigate's `objects: track` config, not the model's; the wording sends someone to the right
  place to change it. The fold is titled "Files and objects", or "Objects" on a card with no files. The lists
  (`RunningLists.vue`) are plain h4-headed lists, always shown inside the fold: the page's earlier two closed panels
  were rows to open inside a card that is itself a row to open, and a fold never sits inside a fold.
- The running model's list is Frigate's, as `labels.recognised` says, with `labels.source` naming where it came from
  in a caption; for a model with no `.json`, such as Frigate's built-in model, it's the only list there is. When it's
  Frigate's and the objects differ from the model's `.json`, as sets, one plain line says so. It has no alert color:
  it's rare, and usually a deliberate label-map edit. The `.json`'s own list isn't shown a second time on the card in
  use, so the card has one list of what the model recognises. The other models' cards keep theirs.
- The label lists are chips because they are many short words that wrap well on a phone. Each list's Copy puts it on
  the clipboard comma-separated, ready to paste elsewhere, and says "Copied." beside the button for two seconds; a
  refused copy says so and stays.
- A chip can carry one of two marks, each with a legend in words that shows only when a chip has it, so color is never
  the only cue. Filled (`variant="tonal"`, the heading blue) is a recognised object the device tracks. Amber
  (`variant="outlined" color="warning"`) is a tracked object the running model doesn't recognise, and wins over filled.
  The amber objects also sit on the card in use outside its fold, under its facts and above its buttons, because
  they're the one thing here that means counts are missing and it shouldn't take an open fold to see them. The tracked
  list's title counts them ("(6, 2 not recognised)"). An other-model card's fold names what a switch would lose the
  same way.
- Frigate+ is its own section, between the model in use and the other models, because the key and the ways to get a
  Frigate+ model come before a list of models already on the device. Its heading is an h2 outside any panel, and its
  two paragraphs show for everyone. An admin gets two panels under them, "API key" and "Use a model by its ID", both
  closed when the page opens, on the page's background rather than Vuetify's `surface`, so the card in use stays the
  only tinted thing. The key's state is grey text beside the first title: "not set", "set", or "set, ending in ab12",
  with ", in use" while Frigate runs a Frigate+ model, and nothing until the secrets answer. A viewer gets the text
  and no panels. The section does not wait for `GET /models`, so it shows, and the key's form works, when the models
  can't load. The Status page's "Set the key" links to `/detection#frigate-plus`, which opens the key's panel and
  scrolls to the section, and its "Choose a model" to `/detection#frigate-plus-model`, which opens the ID panel the
  same way. The panels' content is rendered while closed (`eager`), so the page's height is known when the link
  scrolls. Each panel's title, a button, sits inside an h3 (`text-body-1`, like the Location page's panels), with its
  words ("API key", "Use a model by its ID") in `text-subtitle-1 font-weight-medium`, the size of `EnteredSecret`'s
  own h3 on the Device page. At `text-h6` they read as large as the section's h2. The key's form is the Device page's
  (`EnteredSecret.vue`) without its own heading and state line.
- The ID panel (`PlusModelById.vue`) is a short paragraph on where the ID is, one field, "Model ID", and one 44 px
  button, "Download and use". The field takes a pasted `plus://` address and surrounding spaces, and says "A model ID
  is 32 characters, each 0-9 or a-f." under itself for anything else, with the button off, so nothing wrong is sent.
  The confirmation says the download can take a few minutes and the restart about one. An ID of a model the device
  already has, with both its files, is confirmed as a Use ("Use <title>?", Use's own text and button), since the
  server takes the short path; the request is the same. The page's `working` flag also covers a running download, so
  Use, Upload a model, Download, and Delete are off meanwhile (the key's panel stays open to Save and Remove), and the
  panel shows an info alert, "Frigate is downloading the model. This can take a few minutes. You can leave this
  page.", under the button. The page asks `GET /models` every 3 seconds while the record says `downloading`, with no
  limit of its own, because the server ends the record; a download begun elsewhere opens the panel and is followed the
  same way. A `saved` record is a Use's restart: the page waits for Frigate as after a Use. A `refused` or `failed`
  one shows its message under the button, Frigate's own words included, also when it's found on opening the page.
- The admin's actions are buttons on each card, 44 px tall, in order of weight: Use (filled, not on the model in use),
  Download (outlined, any model whose model file is on the device), and Delete (red outline, when the API says it can
  be). "Upload a model" sits under the "Other models" heading, above the cards it adds to, visible with nothing to
  open. The device's default (the installer's model, or Frigate's built-in model on a device without a Coral) has its
  own Use when Frigate runs something else, which puts it back through `POST /models/default/use`; the defaults have
  no Delete. A Use that can't work is disabled, with the reason under it ("It's built for hailo8l, and this device
  detects with edgetpu.").
- "Upload a model" opens a dialog: one package, or a model file with or without its .json, sent the .json first. A
  model file sent alone opens a form for what Frigate needs to know about it, filled in with Frigate's documented
  example for a Coral or a Hailo-8L; only the labels are always the person's to type. A .json sent alone finishes a
  model file already on the device. The picker shows every file, because a Frigate+ model file has no extension and
  a phone's picker would hide it behind a filter; the device tells the kinds apart by name.
- Download saves a model with both its files as a package (`<name>.zip`), without asking. A model without a .json
  the device can read, and a default, downloads as its model file alone, under its own name, after a dialog that says
  so and that whoever uploads the file fills in what Frigate needs to know about it; for a default it also says to
  rename the file first, because a device keeps that name for its own copy. That dialog's button is primary, not the
  error colour, since a download changes nothing.
- Use and Delete ask first. Use says Frigate restarts and that traffic isn't counted meanwhile; after the device
  accepts, "Frigate is restarting." shows under the model, and the page asks again every 3 seconds until Frigate
  answers with the model ("Frigate runs My model."), or, after 90 seconds, points to the Status page. Each result
  shows where its action was: on the model's card (it moves to "Model in use" with the card when Frigate runs it),
  or, for a deleted model, above the other models' cards. An API refusal shows its message there, Frigate's
  own words included.

#### What changed on 2026-11-13

The running model's lists lived in a section of their own at the top, apart from the card for the same model, so
"what is this device running" was answered in two places, and the Frigate+ key sat after the long list of other
models. The page now keeps the running model in one place:

- The two label lists, the sentence about them, and the "different list" line moved from the top section into the card
  in use's fold. The amber "not recognised" chips moved onto the card, outside the fold. The top section is now the
  detector, the running model, and Frigate's alerts.
- The card in use is always there, so the lists show when the running model has no entry or can't be read.
- Frigate+ moved above the other models and lost its panel around the text. Its heading and two paragraphs are
  plain, and the key is the one panel, "API key".

The two closed label panels, the three-panel layout, and the placement of Frigate+ last, described in the notes below,
are the layout before this change.

#### What the screenshot review changed

The page was checked in fake mode at 375 px and 1366 px wide, as an admin and as a viewer, and through the
`#frigate-plus` link.

- At 375 px a file line broke between "SHA-256" and its hash. The two now stay together.

After the page was reshaped into blocks and panels, it was checked again the same way, and at 360 px for the
narrowest phones:

- Vuetify gives panels the `surface` color, so the closed panels were as tinted as the block in use, which then
  didn't stand out. The panels take the page's background now.
- The key's state sat against its name ("Frigate+ API keyNot set"). Vuetify 3.13 has no column-gap class, so a
  scoped rule sets the gap.
- Inside the panel, a Frigate+ model's 32-character file name filled a block's line at 360 and 375 px, and its comma
  started the next line. Narrower panel padding only moved the break, so the file name may now break anywhere.

After the page was reshaped into four sections, it was checked again at 375 px and 1366 px, as an admin and as a viewer,
through the `#frigate-plus` link, and through a Use and a Delete:

- The fold's title text touched the edge of its hover and focus band, because the title had no side padding to keep it
  aligned with the card's text. The fold now reaches 8 px past that text on each side, and the title and content pad
  it back.
- A closed card looked bottom-heavy, with the card's padding under the title's own. The fold takes back 8 px of it.
- On a Coral unit running the installer's model, Frigate's list had 91 entries, 74 of them `unknown`, so the top list
  read "(91)" over rows of `unknown` chips while the card said 17. The API now leaves `unknown` out of every list.
- Looked at and kept: at 375 px each list title in the fold wraps and its Copy sits on its own row. Nothing overlaps,
  and Copy sat on its own row inside the old panels too.
- The panel titles ("API key", and "Use a model by its ID" after it) were at `text-h6`, as large as the "Frigate+" h2
  above them, and had no heading around them. Each now sits in an h3 at the size of the Device page's key titles.

#### Defaults rejected

- A data table of the models: its columns don't fit 375 px, and most cells are empty for the installer's model.
- `v-card` per model: a Vuetify card reads as something to open. The cards here are a border and, for the one in use,
  the surface tint; the maintainer asked for the border after the first build, so that each model reads as one choice.
- A strict accordion (one panel open at a time): comparing the two label lists needs both open.
- "Expand for …" as a panel title: the chevron says that; the title names and counts what's inside.
- The full hash on the page: 64 characters wrap into a block that hides the rest of the line.
- A color or icon per object: the labels are Frigate's words, and copying them is the job. Color on a chip says only
  whether it's tracked or missing.
- One accordion for all the other models: it hid Upload and put a fold inside a fold.

### Location

For admins only, because the places hold exact coordinates. The page answers "where does the database think this
unit is, and how precisely", and lists the places the unit has been or will go. Adding, deploying, correcting, and
importing places open dialogs from this page, so they move nothing on it.

```text
+----------------------------------+
| Location                    (h5) |
| (!) Node-RED hasn't answered yet |  only then
| +------------------------------+ |
| | Front of the school    (h4)  | |
| | In use                       | |
| | 34b17422-si                  | |
| | Stored in the database       | |
| | 45.52, -122.69               | |
| | Exact location               | |
| | 45.52252, -122.69120         | |
| | Sharing      Bearing, picam  | |
| +------------------------------+ |
| Places                      (h6) |
| [Add a place] [Import places]    |
| +------------------------------+ |
| | Front of the school (In use) | |
| | 34b17422-si                  | |
| | 45.52, -122.69             v | |
| +------------------------------+ |
| | No description (Used)        | |  opened
| | First used    Last used      | |
| | No events recorded at this   | |
| | place.                       | |
| | Deployments (4)              | |
| | | Deployed Nov 7, 10:15 PM,  | |  newest first; the running one
| | | running now                | |  has a blue left border
| | | picam_h265                 | |
| | | Facing N  Correct bearing  | |
| | |   TM_RADAR_SERIAL_PORT_00  | |  indented under its camera
| | |   Facing N  Correct bearing| |
| | | Deployed Nov 2, ... to ... | |  grey left border
| | | picam_h265 ...             | |
| | [Re-deploy here]             | |  by status, see below
| | [Correct location] [Delete]  | |
| +------------------------------+ |
| Precision                   (h6) |
| To better protect your privacy,  |  always in view
| by default the database ...      |
| +------------------------------+ |
| | Change the precision       v | |  closed; opened below
| | Now: About 1 km ...          | |
| | This setting is for the whole| |
| | device: ...                  | |
| | ( ) No location stored       | |
| | ( ) About 10 km (example)    | |
| | (o) About 1 km (example),    | |
| |     the default              | |
| | [ ] Also round the rows      | |  coarser choice only
| |     already stored           | |
| | [Save]                       | |
| +------------------------------+ |
+----------------------------------+
```

- The place in use is the page's one card, the device card's `StatusCard`, because it's the one object the page is
  about. It shows both the coordinates the database stores and the exact ones, labelled "Stored in the database" and
  "Exact location", so an admin sees what the precision does to their point before changing it.
- The precision comes last, because most devices never change it and the places are what the page is used for. Its
  header is at the same level as Places, and the paragraph under it, always in view, says why the location is rounded
  and what a shared copy holds. The choices are one closed panel, whose title names the device's choice, so the value
  shows without a tap. The panel stays open after Save, so the result line can be read.
- Inside, the precision is three radio buttons, coarsest first, with the area in words and, in parentheses, one example
  point stored at that precision, so "about 1 km" also reads as coordinates; "the default" follows about 1 km. "Also
  round the rows already stored" shows only for a coarser choice, because a finer one can't bring back what was rounded
  away; a line says it applies from the next deployment instead. Ticking it asks first ("This can't be undone."). For
  No location stored, the box, its line, and the confirmation say "remove" rather than "round", because that's what
  happens.
- When saving the precision is refused because `config.yml` changed (409), the page loads the places again, as every
  other write does. A 502 doesn't reload: the file has the choice and the rows don't, and pressing Save again finishes
  it.
- Each place is a bordered panel, as on the Detection page: its title says the description, the status chip, the id
  in the secondary color, and the stored coordinates, so a closed list still says what each place is. The chip is in
  the heading blue only for the place in use. The panels open independently, and opening one asks for its events
  and deployments once.
- The deployments are a list, not a table: a sensor name such as `TM_RADAR_SERIAL_PORT_00` and two dates don't fit
  four columns at 375 px, and each deployment has a "Correct bearing" button.
- The list is grouped by the deploy each row came from, newest first, so a place with four deployments reads as two
  deploys of a camera and its radar, and the current one is on top on a phone. Rows that start within a second of a
  group's first row are one deploy: this version's engine starts every row of a config load at the same instant, and
  released versions' rows, which imported places hold, can be a millisecond or so apart. The group's heading holds the
  start, the latest end, or "running now" (so the border's color isn't the only signal), and names a day once when it
  started and ended on the same one. A row shows its own end only when the heading doesn't say it. Cameras come first, and a
  radar deployed with a camera is indented under it. That's order, not pairing: on a device with two cameras the
  radars sit under the last one, since the API doesn't send `camera_radar`.
- The main button is named by the place's status (`deployWords`): "Deploy here" for a planned place, "Re-deploy here"
  for a used one, and "Modify deployment" for the place in use, where only bearings can change. The review's title and
  its dialog's name use the same words, and its button reads "Deploy", "Re-deploy", or "Modify".
- Delete asks first and says what goes. For a used place: its exact location is deleted, and the database keeps the
  rounded one stored with each record. The place in use has no Delete.
- When Node-RED hasn't answered the first reconcile, or `config.yml` can't be read, a warning at the top says so, and
  for a bad file points to the Location check on the Status page. When Node-RED doesn't answer the usage counts, the
  panels leave out "First used" and "Last used" rather than saying a used place was never used.
- `formatStored` pads the API's stored values to the precision's places ("45.0", not "45"); the values are already
  rounded, so padding changes no digit. Nothing on the page rounds a coordinate.
- A panel's facts, events, and deployments are `PlaceDetails.vue`; the page keeps the buttons, because they open the
  page's dialogs.

#### Adding a place, and the deploy review

```text
+----------------------------------+   +----------------------------------+
| Add a place                      |   | Deploy here                      |
| [Description                   ] |   | Corner by the park               |
|  Private: it never leaves the    |   | 0f0e0d0c-si                      |
|  device                          |   |                                  |
| [Coordinates                   ] |   | picam_h265                       |
|  Paste latitude, longitude ...   |   | New deployment starts      (blue)|
| [Use this phone's location]      |   | Was N, now [NE  v]               |
|  (HTTPS only; else one sentence) |   | TM_RADAR_SERIAL_PORT_00          |
| A map pin is coming in a later   |   | New deployment starts            |
| update.                          |   | Was not set, now [Not set v]     |
| Which way each sensor faces here |   |                                  |
| [Bearing, picam_h265         v]  |   | Stored in the database:          |
| [Bearing, TM_RADAR_SERIAL_... v] |   | 45.0, -122.0                     |
|                  [Cancel] [Save] |   | Not sharing                      |
+----------------------------------+   | Counts from now on attach to the |
                                       | new deployment.                  |
                                       |               [Cancel] [Deploy]  |
                                       +----------------------------------+
```

- The form (`PlaceForm.vue`) is a dialog with a `v-model` for whether it's open, as `ConfirmDialog` is, and starts
  over each time it opens. "Edit" on a planned place opens it with the place's values; a used place has "Correct
  location" instead.
- The coordinates are one field, because a maps app copies "latitude, longitude" as one string. `parsePair` checks
  it as it's typed: a decimal comma, the wrong order (which puts the longitude out of the latitude's range), or
  anything else that isn't a pair shows "Enter latitude, longitude with a dot as the decimal mark" and disables Save.
  A blank field saves a place with no location. The backend still quantises what's sent to five places.
- "Use this phone's location" shows only on a secure page, because browsers refuse the location to any other; on
  plain HTTP one sentence says so instead. It asks for the precise reading and writes it into the field at five
  decimal places, where the admin can still see and change it before saving. A refusal shows the browser's own
  reason.
- Each sensor's bearing starts at the place's own, else at the sensor's bearing in `config.yml` now, in the form and
  the review alike (`startingBearings`). A new place starting at "Not set" would have saved a blank bearing that the
  review then offered as the place's choice.
- The review (`DeployReview.vue`) is the one step on the page that changes what's recorded, so it says the
  consequences in words, one sensor at a time: "New deployment starts" (in the heading blue) or "Unchanged", the
  bearing it had, and a select for the one to deploy with. Moving to another place starts a new deployment for every
  sensor, as the deployment engine does. Then what the database will store for the place, rounded by the API, what's
  shared, and that counts from now on attach to the new deployment (only when one starts).
- The place in use has "Modify deployment", to record a turn of the unit. There the review starts from the bearings
  `config.yml` has now, each sensor reads "Unchanged" until its bearing changes, and Modify stays disabled until one
  does, with a line that says so.
- Deploy sends every enabled sensor's bearing, so what's recorded is what the review showed. While the API waits for
  Node-RED, the dialog says "Waiting for Node-RED to reload the settings", Cancel is disabled, and a click beside the
  dialog doesn't close it (`persistent`), so the answer isn't lost. The review then gives way to the result: the new
  deployment ids, each with Copy, or, when Node-RED hasn't reloaded the settings, a warning that the settings are
  saved and not to deploy again; Deploy is gone by then, so it can't be pressed twice. The list and any open panels
  load again behind the dialog.
- A connection that drops while the API waits doesn't get the app's usual "try again": `config.yml` may be written
  by then. The review says the settings may already be saved and to check the place before deploying again, Deploy
  is gone, and the page loads the places, which show whether the deploy happened.
- When the API refuses a save or a deploy because something changed since the page loaded (409), the dialog shows
  its message and the page loads the places again behind it.
- The deploy dialog keeps showing its review while it fades out, rather than emptying first, and each opening starts
  a fresh review. Both dialogs are named by their title for screen readers.

#### Corrections, and importing places

- A correction is for a value entered wrong, never for a move, and both dialogs (`CorrectDialog.vue`) open by saying
  so: "Use this only if the location was entered wrong. Every record from this place will say it was at the new
  point. If the unit moved, deploy it to the place it moved to instead." The bearing's says the same of its deployment
  and points to Modify deployment, and both end with
  "Copies and uploads that already left the device keep the old values." The button reads "Correct", not "Save".
- "Correct location" shows only for a used place or the place in use that has a point: a correction needs one, and
  a place with none is planned anew. The field starts at the exact point and can't be left blank. A new point more
  than about 1 km from the old one (`distanceKm`) gets a second confirmation, with a red button, that gives the
  distance and says to deploy instead. The same point again is allowed, because correcting again is how a correction
  whose stored rows weren't re-rounded (502) is finished; the same bearing isn't, because there's nothing to finish.
- "Correct bearing" is a text button on each deployment's "Facing" line, so a long list stays compact on a phone.
- The import is preview, then import. Preview sends the text as a dry run and lists the places the API read, by
  line, with the lines it couldn't read in an error above them. Import sends the same text again and is enabled only
  when the preview found places and no errors; any change to the text forgets the preview. The API creates every
  place or none. A file is read into the same box as pasted text, so what's previewed is always on screen, and
  64 KiB, the API's limit, is checked before anything is sent. The dialog is `scrollable`, so a long preview scrolls
  under the title and the buttons stay in view, and `persistent`, so a click beside it can't hide the result.

#### What the screenshot review changed

The page was checked in fake mode at 375 px and 1280 px wide, with a used place opened, the coarser precision
chosen, and the delete confirmation open. The corrections, the far-move confirmation, and the import's preview and
result were checked at the same widths. The place form, the review, and the result were checked at the same widths.

- "Deployments" was both a fact (the count) and the list's heading. The heading now carries the count,
  "Deployments (2)".
- A deployment that started and ended on the same day repeated the date. The end now shows the time only.
- The deployments ran together; they're further apart now.
- The precision's paragraph said the exact location "stays on this page", which isn't where it's kept. It now says
  "kept only on this device, outside the database", and a line under the checkbox says what happens without it.
- At 375 px the review's "Stored in the database: 45.0, -122.0" broke between the two numbers, which read as two
  values. The pair now stays on one line.
- "Correct bearing" was a small button, in smaller type than the "Facing N" beside it. It's the normal size now.
- At 375 px the import's example header broke inside a sensor's name; it now breaks only after a comma. The preview
  appeared below the fold, with Preview and Import scrolled away; the dialog now scrolls its content instead.

After the first bench runs, the page was checked again in fake mode at 375 px and 1280 px wide, with a deploy history
on one place, the precision panel open, and No location stored chosen:

- The precision sat between the card and the places, pushing the places off the first screen for a setting most devices
  never change. It moved to the end, with its choices closed and the current one in the panel's title. A first version
  put the whole section in the panel and a note under the card; the header and the reason read better together, in view.
- A flat list of four deployments with four dates read as four events. They're grouped by deploy now.
- "Deploy here" on a place the unit had already used, or on the one it's at, said the wrong thing. The button now
  follows the status.
- "Also round the rows" read wrong for No location stored, which removes the location. It has its own words now.
- `column-gap-2` isn't a Vuetify class, so the deployment line's gap came only from its button's padding. It's `gc-2`
  now.

#### Defaults rejected

- A data table of the deployments: see above.
- A select for the precision: three choices read better side by side, and the current one shows without a tap.
- A strict accordion: comparing two places needs both open.
- Icon-only actions in each panel: each button names what it does.
- Separate latitude and longitude fields: a pasted pair would have to be split by hand, and two fields are where the
  wrong order goes unnoticed.
- A table for the review (sensor, before, after): its columns don't fit 375 px, and "New deployment starts" is a
  sentence, not a cell.
- Showing the deployment ids before Deploy: they don't exist until Node-RED starts the deployments, and the review is
  about consequences, not ids.
- Closing the review on its own after a deploy: the ids are what an admin may need to copy, and the warning that
  Node-RED hasn't reloaded must stay until it's read.
- A table for the import's preview: a sensor column per sensor doesn't fit 375 px. Each place is a short list item,
  as the deployments are.
- One Import button that previews and imports in one go: the preview is what lets an admin catch a wrong column
  before anything is created.

### Network

For everyone who is signed in. The page answers "how do I reach this unit, and what is it connected to", which a
person at the roadside needs when the phone has to join the unit's hotspot or someone has to find it on a router's
client list. It shows names, hardware (MAC) addresses, and IP addresses, which are exactly the things typed into
another device, so every one has a Copy button. The Device page carries a short summary of the same facts.

```text
+----------------------------------+
| Network                     (h5) |
| (!) The network state couldn't   |  only when NetworkManager did
|     be read ...      [Try again] |  not answer; then only the names
| This device                 (h6) |
| Name                             |
| tm-ab12                   [copy] |
| Local name                       |
| tm-ab12.local             [copy] |
| Ethernet                         |
| Connected                        |
| MAC address                      |
| 2C:CF:67:00:AB:11         [copy] |
| IP address                       |
| 192.168.1.57              [copy] |
| Gateway                          |
| 192.168.1.1               [copy] |
| DNS server                       |
| 192.168.1.1               [copy] |
| Wi-Fi                            |
| On its hotspot (TM-AB12)         |
| MAC address ...                  |
| Internet                         |
| Not reachable                    |
| Hotspot                     (h6) |
| State                            |
| On                               |
| Name                             |
| TM-AB12                   [copy] |
| Name hidden                      |
| No                               |
| Address                          |
| http://10.42.0.1/                |
| http://tm-ab12.local/            |
+----------------------------------+
```

- Label above value, as on the other pages. A link's details (MAC, IP, gateway, DNS) sit under the link's own line
  as the same label-above-value pairs, indented by a left border so they read as belonging to it. One column at every
  width: a MAC address and an IPv6 address are too long for two columns at 375 px, and the value wraps (`text-break`)
  rather than push the Copy button off the screen.
- Copy sits right after the value, on the same line, so the tap target is next to what it copies. Its label says what it
  copies and where it belongs ("Copy Ethernet MAC address", "Copy hotspot name"), because a screen reader hears the
  button without the text beside it. A check replaces the icon for two seconds. When the browser refuses, "Select the text to copy
  it." appears beside the button, as the Device page's diagnostics do when they show the text in a box.
- The lines are plain words from `summary.ts`: "HomeNet, signal 72%", "On its hotspot (TM-AB12)", "Joining a
  network", "Not connected", "Switched off". The internet line is "Reachable", "Not reachable", "Needs a sign-in
  page", or "Not checked yet". The words live in one place, so the Device page's summary and this page can't differ.
- A unit without Ethernet shows no Ethernet row. A unit without a built-in radio says "No built-in Wi-Fi radio".
  When NetworkManager didn't answer, both would be wrong (they only mean "none found"), so the page shows the names
  and the warning, and nothing else.
- A viewer sees the hotspot read-only (state, name, whether the name is hidden, the addresses) with "An administrator
  can change the hotspot here.", and never a password or a control. An admin sees the settings below instead.
- The Device page appends one line per connected link ("Ethernet", "Wi-Fi") to its card and a "Network details" link
  to this page. If the network state can't be read, the card is the same as before: the summary is an addition, never
  something the page waits for or fails on.

#### The page's layout: one screen

On a laptop the page has to fit one screen, and the part people come for is the Wi-Fi networks and a join, not the
unit's addresses or the hotspot's settings. So This device and Hotspot are folded panels (`CollapsePanel.vue`) side by
side in one `v-row`, each in a `md="6"` column (one column below `md`), and Wi-Fi networks is full width below them and
never folds. The join card stays above all of them, also never folded: it carries the countdown and its buttons.

```text
| Network                     (h5) |
| [join card, when there is a join]|
| +-----------------+ +----------+ |  md and up: two columns
| | This device   v | | Hotspot v| |  folded: a summary under the title
| | tm-ab12.local   | | TM-AB12  | |  This device: the .local name and the addresses in use
| | 192.168.1.57, ..| |          | |  Hotspot: its name, or "Hotspot off"
| +-----------------+ +----------+ |
| Wi-Fi networks              (h6) |
```

- Both panels start folded on every visit and nothing is remembered between visits: a remembered "open" would hide the
  summary the next person expects, and a stale choice is worse than one more tap.
- The panel's heading is the page's `h2`, and the button that folds it is inside the heading, as in the accordion
  pattern. `v-expansion-panel`'s title is a button with no heading around it, which would take "This device" and
  "Hotspot" out of a screen reader's list of headings, so the panel is a small component of its own made of `v-card`,
  `v-btn`, and `v-expand-transition`. Its content stays mounted while folded: a job started in the panel and its notice
  go on, and the page can open the panel when they have news.
- A folded panel never hides something that needs attention. The Hotspot panel opens itself when a change it made starts,
  and again when that change ends with a failure, an unreported result, or a refusal, so the device's words are on screen;
  a folded panel that holds such words shows a warning mark ("Needs attention") beside its title. The person can fold it
  again. This device has nothing of that kind, so it opens only when asked. A join's lock message is not news: the card
  above it says what is happening, so the panels stay folded under a join.
- An anchor in the address opens its panel and scrolls to it: `#this-device`, `#hotspot` (and `#wifi-networks`, which
  only scrolls), below the app bar (`scroll-margin-top`, as on the Device and Detection pages). The Status page's "Set a
  password" fix for a hotspot with no password links to `/network#hotspot` (`SET_A_PASSWORD` in
  `modules/network/checks.py`), so an admin lands on the open panel with the password row. The Device page and the join
  banner link to plain `/network`.
- The summary is two short lines at most: the unit's `.local` name, then the addresses in use (the cable's when it is
  connected, the Wi-Fi's when it has one), then for Hotspot its name or "Hotspot off". A unit without a hotspot has no
  panel, only the sentence that says so.
- Viewers get the same panels, with the read-only facts inside and no control but the heading's own button.

#### The hotspot's settings (admins)

```text
| Hotspot                     (h6) |
| (o-) Hotspot on                  |  switch; off asks first
| Name                             |
| TM-AB12 [copy]          [Change] |
| Password                         |
| ••••••••          [Show] [Change]|  Show asks the device, Hide forgets
| (-o) Hide the name               |  switch; asks first
| Address                          |
| http://10.42.0.1/                |
| http://tm-ab12.local/            |
| (i) Saved. The hotspot restarted.|  the job's result, kept after it
| A hotspot on a pole is visible ...|
+----------------------------------+
```

- Every change is `POST /network/hotspot`, which starts a root job that restarts the hotspot, and the page follows
  the job. One change at a time: every control is disabled while a job runs, and an alert says what is happening.
- The password is fetched from the device (`GET /network/hotspot/password`) each time Show is tapped, and dropped on
  Hide or when anything changes. The row shows dots otherwise. A hotspot without a password says "None. Anyone nearby
  can join." and offers "Set a password" in place of Show and Change.
- The new name and password are typed into a dialog (`HotspotField.vue`). The field shows what is typed, and there is
  no second field to type it again: a hidden field typed twice protects against a typo the person can't see, but on
  a phone at the roadside the person is about to write the password down and give it to every phone, so seeing it
  once is the better check. The dialog itself is the confirmation: it says to write the password down and that every
  phone must rejoin, and its button names the action ("Change name", "Change password", "Set password"). The button
  stays disabled until the rules pass, and the rule's message appears under the field.
- The rules are the API's, repeated in `rules.ts` so a bad value is refused before the device is asked, with the
  API's words: a name is 1 to 32 bytes of UTF-8 (counted with `TextEncoder`, so accents and emoji count more than
  one) with no control character and no space at either end, and a password is 8 to 63 printable ASCII characters
  with no space at either end. The API checks again and its 422 message would show in the page's alert.
- The warnings come before the change, in the dialog the change goes through. A name or password change warns only
  while the hotspot is up ("The hotspot restarts, and phones on it are disconnected. Each phone must rejoin by
  hand."). Turning off, hiding, and showing the name again ask in a confirm dialog; turning on does not ask. Turning
  off says the unit has no wireless way in without its Wi-Fi network and needs an Ethernet cable. Hiding says the
  hotspot can still be found by scanning and that Android needs the network added by hand with Hidden network ticked.
  When the page was opened over the hotspot (`session.status.hotspot`), every warning that applies ends "You're on
  the hotspot now, so this page stops answering when you save." A long warning is split into paragraphs
  (`ConfirmDialog` and `HotspotField` start a paragraph at each line break).
- Losing the unit is expected. The restart often disconnects the phone the admin is using, so once the device has
  accepted the change, a request that fails to reach it while the job runs is not an error: the page says "This page
  lost the unit, which is expected when your phone is on the hotspot. Join <name> again, then reload this page." (with
  the new name), or after turning off, "The hotspot is off. Reach the unit on its Wi-Fi network or by Ethernet." Any
  other failure (the device refusing the change, a failed job) is an error with the device's words.
- A failed job shows its log lines, as the Device page's secrets do. A line ending "the settings are saved" adds "The
  settings were saved, but the hotspot didn't restart." above it, because the change is then in place and only the
  restart failed; the page loads the state again either way.
- Under the settings, one paragraph says why: a hotspot on a pole is visible to anyone passing and public Wi-Fi maps
  record where names are seen; hiding the name reduces that and only turning the hotspot off prevents it.

#### The Wi-Fi networks section

Below "This device" and "Hotspot" (`WifiNetworks.vue`, from `GET /network/wifi`), shown when the network state could
be read. Everyone sees the two lists; only an admin gets Refresh, Forget, and Move up / Move down.

```text
| Wi-Fi networks              (h6) |
| Saved networks                   |
| The unit joins the first of      |
| these it finds.                  |
| HomeNet                          |
| [Joined] [Hidden]                |
| Forget  [down]                   |
| ---------------------------------|
| Depot                            |
| [Not in range] [Couldn't join]   |
| The unit couldn't join this ...  |
| Forget  [up]                     |
| Nearby networks       [Refresh]  |
| Looked 1 minute ago              |
| (wifi4) HomeNet (lock) [Saved]   |
| (wifi3) CafeGuest                |
| Open networks can't be joined.   |
+----------------------------------+
```

- A saved row is a list item with the name on the first line, its marks (chips) under it, and its buttons under
  those, on one line: Forget first, then the Move buttons. The buttons sit on their own line at every width, as the
  hotspot's Change and Show do, so a long name wraps (`text-break`) instead of pushing them off a phone's screen, and
  the row has the same shape at 375 px and 1366 px. Forget comes first so it stays where the eye lands after the
  name, in the same place on every row, whichever Move buttons the row has. The marks are "Joined" (in use), "In range" or
  "Not in range" (nothing when the unit can't tell), "Couldn't join", "Hidden", and "Not joined by itself". The
  "Couldn't join" tip is a line of text under the chips, not a tooltip: a tooltip needs a hover, and the phone at
  the roadside has none.
- Move up and Move down exist only for networks the unit joins by itself, because only those have a place in the
  order: none above the first, none below the last. A tap sends every such network's uuid in the new order (`moved()`
  in `networks.ts`), so the unit never has to guess which ones the page meant; a list that changed meanwhile comes back
  as 409 `stale_order` and its message is shown. Networks that aren't automatic come last and have only Forget.
- A nearby row is the signal (an icon by quarter, with the percentage as its label), the name with a lock after it for
  networks that need a password, and the marks "Joined" and "Saved". A network the unit can't join, by kind, has the reason under
  its name (`whyNot()`). The list is the strongest first, as the API sends it.
- Refresh starts a scan (a root job; the unit's hotspot pauses for a few seconds) and the page follows it. The line
  above the list says when the unit last looked ("Looked 3 minutes ago"), and the unit looks only when asked, so the
  page never shows a list as newer than it is.
- One job runs at a time. While a scan, a forget, or a reorder runs, every control in the section is disabled, and so
  is every control when the parent says a join is pending (`locked`). A failed job shows its log lines, as the
  hotspot's does, and the page loads both answers again whatever the outcome.
- Forgetting asks first. For the network in use the question says where the unit goes: onto its hotspot when that is
  on (with the hotspot's name), or nowhere when it is off, which is the warning about the Ethernet cable. After
  forgetting the network in use, a page that loses the unit says the unit left the network and how to reach it on the
  hotspot; for any other network, a lost request is an ordinary error.
- With the radio switched off, the section says so and shows nothing else (the lists would be stale). Without a radio,
  it says only that. When the unit couldn't read the networks, it says that.

#### Joining a network (admins)

An admin taps **Join** on a nearby network that needs a password and isn't in use (never on an open, enterprise, or
WPA3-only one, which the unit can't join, and never for a viewer). The unit tests the network, and if the test passes
it counts down 5 minutes and then switches to it. The page is usually open on a phone in Android's sign-in window while
the unit's hotspot goes away for the test, so the words matter more than the layout.

```text
| Join HomeNet                     |   dialog
| The unit tests HomeNet first.    |
| Its hotspot is away for up to a  |
| minute, then comes back with the |
| result. A phone on the hotspot   |
| must rejoin TM-AB12 by hand ...  |
| You're on the hotspot now, so    |   only over the hotspot
| this page stops answering ...    |
| The unit's Wi-Fi MAC address     |
| 2C:CF:67:00:AB:12         [copy] |
| A network that only admits ...   |
| Password for HomeNet             |   or "Uses the saved password."
| [____________________]           |   shows what is typed
|        [Cancel] [Test and join]  |

| Network                     (h5) |
| +------------------------------+ |   the result card, above This device
| | HomeNet works                | |
| | The unit's address there: .. | |
| | Wi-Fi MAC address: ..        | |
| | Or open: http://tm-ab12.local/ |
| | Internet: reachable          | |
| | Joining HomeNet in 4:58      | |
| | [Cancel]       [Switch now]  | |
| | When the unit joins HomeNet, | |
| | its hotspot stops. Join ...  | |
| +------------------------------+ |
| This device                 (h6) |
```

- The card (`JoinCard.vue`) sits above "This device" whenever the unit has a join to show, in every stage from the
  test to a result nobody has dismissed. It is the page's one place for the join, so the sections below say only that
  they are locked. A viewer sees the same card with no buttons; an admin gets Switch now and Cancel during the
  countdown, and Dismiss on a result.
- The phone's view changes while the join runs, so the card says what to do next at each stage, not only what
  happened. While the unit tests, the card says so; if the page can't reach the unit (the usual case over the
  hotspot) it says that is expected and names the hotspot to rejoin. If the unit was on a Wi-Fi network instead
  (`join.before` is that network's profile), the hotspot never appears, so the card says the unit goes back to where it
  was by itself. The page keeps asking (`useJoin()` in `join.ts`) every 2 seconds for as long as a join is pending, whether or not the last request worked, and the first answer
  that does arrive shows the result. A request that fails is not an error here, so the card never shows one for it.
- The countdown is the device's number, counted down by the page between answers so the clock moves every second
  though the page asks every 2. At 390 px it reads as one column: the address and the MAC address each on a line,
  then the clock, then Cancel and Switch now side by side, then the sentence about the hotspot. The times are
  `m:ss`, never seconds.
- The address, the MAC address, and the `.local` name are plain text; Copy is beside the address, and beside the MAC
  address in the "couldn't join" sentence, where the person has to type it into a router's list (a viewer gets Copy too: it
  changes nothing). The `.local` name is
  not a link: inside a phone's sign-in window a link opens in that window, as `HotspotNote` explains.
- After Join is sent and before the unit reports a join, the card says it is testing. If the unit reports none within
  15 seconds while the page can still reach it, the page says "The test didn't start. Try again." and drops the card.
- One thing happens at a time across the whole page. While the join is pending, and while a scan, forget, reorder, or
  hotspot change runs, every control in the Wi-Fi networks and Hotspot sections is disabled. The section that started a
  job keeps its own "working" line; the other is disabled and says why ("Finish or cancel the Wi-Fi join first." for
  a join, "Wait for the Wi-Fi change to finish." for the other section's job). `NetworkPage` ORs the sections' reports
  (`busy`) with the pending join.
- The home page shows one line (`JoinBanner.vue`) to an admin while a join exists, with a "See it" link: the admin may
  not have the Network page open when the countdown ends. It asks when the home page loads and keeps asking while a join is
  pending (the same `useJoin` as the Network page, so the time moves and the line changes when the join ends). It
  shows nothing when it can't read the first answer.

#### What the screenshot review changed

The page was checked in fake mode at 375 px and 1366 px wide, as an admin and as a viewer, and at 375 px with a joined
network (a long name, an IPv6 address, two DNS servers, "Needs a sign-in page"), with the network unreadable, and
after a tap on Copy that worked and one the browser refused.

- On the Device card the "Network details" link was in the small default type, a hard target on a phone. It is
  body-sized now.
- Looked at and kept: the page is the same for admins and viewers, so the two sets of screenshots match.
- Looked at and kept: when the browser refuses a copy, the line "Select the text to copy it." wraps under the value at
  375 px and the button drops to its own line beside it. It is short-lived and says what to do, and a wider layout for
  one rare state would cost every other row.
- Looked at and kept: an IPv6 address and a long network name fit at 375 px without pushing Copy off the screen.
- Looked at and kept: the Wi-Fi value on the Device card breaks after a "·" at 375 px, so the MAC address sits on its
  own line. It is one address per line, not a cut in the middle of one.

The Wi-Fi networks section was checked in fake mode at 390 px and 1280 px wide, as an admin and as a viewer, and at 390
px with the page's answer replaced by a busy one (a joined network with a very long name, one that couldn't be joined,
a hidden one, one that isn't automatic, a long enterprise network), with the radio off, and with the Forget question
open for a network not in use and for the one in use.

- Forget and Refresh were the default text buttons, which pad their label, so "Forget" started 20 px right of the
  network's name and "Refresh" ended 20 px short of the column's edge. They are pulled back by their padding (`ms-n4`
  and `me-n4`) so the label lines up with the text above it.
- Forget was on the right edge, with the Move buttons on the left. At 1280 px that put it the whole width of the
  column from the name it belongs to, and its place moved with the row. It is now first in the row, next to the Move buttons.
- The lock sat at the right end of the row when a name wrapped, away from the name it belongs to. It is part of the
  name's line now and follows its last word.
- Looked at and kept: the viewer's rows have no buttons and no empty line where they would be, so its list is shorter
  than the admin's.
- Looked at and kept: a very long network name wraps at 390 px in the saved row, the nearby row, and the Forget
  question's title, without pushing a button off the screen.

The hotspot's settings were checked at 375 px: the page, Show, each dialog (name, a name over 32 bytes, password,
hide, turn off), the same dialogs with the page opened over the hotspot, the lost-unit message, and after turning off.

- The hide dialog was one block of six lines. `ConfirmDialog` now starts a paragraph at each line break, so the
  restart warning, the hiding sentences, and the "you're on the hotspot" sentence read apart.
- Change, Show, and Hide were the small default text buttons, a hard target on a phone; they are large (44 px) now.
- Looked at and kept: the lost-unit message is an info alert, not an error, and the name above it is still the old one
  because the page can't ask the device any more.
- Looked at and kept: a rule's message wraps and hyphenates under the field at 375 px; it stays readable.

The join was checked in fake mode at 390 px (and the countdown at 1280 px), as an admin and as a viewer: the Wi-Fi
section with Join, the dialog for a network not saved, a saved one, one with a too-short password, one opened over the
hotspot, and one while the unit is on a network; the testing card, the countdown, switching, joined, cancelled, and the
failures the fake can reach (a wrong password, a network that gave no address); the sections locked by a join; and the
home page's banner. Cards the fake can't reach (not in range, busy, could not run, switch failed, interrupted, the sign-in
page network, the page that lost the unit, a very long name) were checked with the page's answer replaced.

- The dialog's three or four sentences about what happens were one block of text. They are paragraphs now (the test, what
  a phone must do, the switch), so a person can find the part about their phone.
- The countdown card had the icon in a left column, which left the MAC address line too narrow at 390 px: it broke after
  "Wi-Fi MAC address:". The icon sits beside the title now and the lines under it use the card's whole width.
- Copy dropped under the unit's address on its own line. The address and its Copy button stay together now
  (`text-no-wrap`), so the pair moves to the next line as one.
- The sentence that says the hotspot stops and to join the network too was small and grey, as a footnote. It is the
  instruction a phone on the hotspot needs, so it is in the card's normal text.
- The lines of the countdown touched each other, in particular the sign-in page sentence under "Or open". They have a line
  of space between them.
- The Wi-Fi section's controls were greyed out with no reason beside them, and the join card is a screen above them.
  The section says why, in the same words as the hotspot's.
- "See it" on the home page was a small text button next to the line it belongs to, a hard target on a phone. It is
  large (44 px).
- Looked at and kept: with the fake, a join reaches `joined` within the 2-second poll, so "The unit is joining ... now" is
  seen only with a stubbed answer, and the card then shows both addresses where the fake has them.
- Looked at and kept: a very long network name wraps in the title, the clock line, and both sentences about the hotspot
  without pushing a button off the screen.
- Looked at and kept: the same card, with no buttons, for a viewer; the viewer's countdown still moves every second.

#### Defaults rejected

- A progress bar for the countdown: the clock is the information, and a bar needs the start time, which the page doesn't
  have after a reload.
- A link on the `.local` name or the unit's address in the card: inside a phone's sign-in window it would open in that
  window, which can't reach the new network.
- A Cancel button while the unit tests: the test runs for a minute at most, with the radio away from the page that
  would press it.
- A table of links and addresses: its columns don't fit 375 px, and there are at most two links.
- A chip or colored dot for connected or not: the words say it, and "Not connected" isn't an error on a unit that has
  a cable or a hotspot but not both.
- Showing the hotspot's address as links: inside a phone's sign-in window a link opens in that window, so the address
  is plain text (as `HotspotNote` does).
- A second "type it again" field for the password: see above; the dialog shows the value and asks the person to write
  it down instead.
- Dots with a reveal toggle inside the dialog's field, as the entered secrets use: those are values the device keeps and
  never shows back, but this password is one the person must read and hand to every phone.
- A refresh timer: an address changes when the unit changes network, and the person has just done that; the page loads
  when opened, and "Try again" reloads it.
