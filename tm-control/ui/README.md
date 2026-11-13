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
  rows that need attention. An entry in step has no box, and while Frigate can't be compared a row
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
  (`clipboard.ts`, the diagnostics and the label lists), and saving a file (`download.ts`, the diagnostics and the
  model packages and files).
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

The same people, the same rules. The page answers "what does this device look for, and with which model", and is
where the Frigate+ API key lives, because the key is how Frigate gets a Frigate+ model. Everyone who can log in sees
it all; admins also get the key's form and the actions that change the model (upload, use, download, delete), which
sit in this layout without moving anything.

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
| (Frigate reports a different list  |
|  than this model's .json.)         |
| Frigate tracks only the objects    |
| that are in both lists.            |
| > Objects the running model        |  <- h3 panel, closed
|   recognises (3)                   |
|     As Frigate reports them.       |
|     [Copy] [person] [bicycle] (car)|  <- [filled] = tracked
|     Filled: tracked on this device.|
| > Objects tracked on this device   |  <- h3 panel, closed
|   (6, 2 not recognised)            |
|     [Copy] (person) (car) !dog!    |  <- !amber! = not recognised
|     Amber: the running model       |
|     doesn't recognise it.          |
| Tracked but not recognised by the  |  <- visible while the panels are closed
| running model: !dog! !cat!         |
|                                    |
| Model in use                  (h2) |
| +--------------------------------+ |
| | My model  (In use)        (h3) | |  <- tinted
| | Local model, trained 2026-10.. | |
| | [Download]                     | |
| | (Frigate runs My model.)       | |
| | > Files and objects            | |  <- closed
| +--------------------------------+ |
|                                    |
| Other models on this device (2)(h2)|
| [Upload a model]                   |
| (Deleted ... result, if any)       |
| +--------------------------------+ |
| | The installer's model     (h3) | |
| | yolov9-s-...edgetpu.tflite     | |
| | [Use] [Download]               | |  <- filled, outlined
| | > Files and objects            | |
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
|                                    |
| > Frigate+      API key not set    |  <- h2 panel, closed
+------------------------------------+
```

A viewer sees the same page without Upload, the card buttons, the key's state, and the key's form, and keeps the Copy
buttons.

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
- A default with no file on the device (Frigate's built-in model on a device without a Coral, which the API can't
  list) still gets a card, made by the page, with "Built into Frigate." as its facts line and no fold. Without it, a CPU
  device's one choice would be a button with no card.
- One chip per model at most, in words: "In use" (in the heading blue), "can't run on this detector", or
  "incomplete" (a model file without its sidecar, or the other way round). The API's reason, when it has one, is a
  line under the facts.
- Three panels of the page's own: the two label lists and Frigate+, on the page's background rather than Vuetify's
  `surface`, so the card in use stays the only tinted thing. They're closed when the page opens. Each title says what's
  inside and counts it, or for Frigate+ says the key's state, so a closed row still says something. They open
  independently (both label lists can be open at once, to compare them), and their content is rendered while closed
  (`eager`), so the page's height is known when a link scrolls to the key. Each title, a button, sits inside its h3
  (the key's inside its h2), as the Device page's "Tokens and keys" does, so the outline stays the same for screen
  readers. The cards aren't in a panel: "Upload a model" and each model's buttons are one glance away, and a fold never
  sits inside a fold.
- The running model's list appears in two places on purpose. The list at the top is what Frigate reports, and it's the
  only list a model with no `.json` can have, such as Frigate's built-in model. The card's list is read from the
  model's `.json` or the installer's labels file, so the card in use looks like every other card. A caption in the top
  list says where it came from (`labels.source`). When it's Frigate's and the objects differ from the card's, as sets,
  one plain line under the facts says so. It has no alert color: it's rare, and
  usually a deliberate label-map edit.
- The label lists are chips because they are many short words that wrap well on a phone. A sentence above the two
  panels says how they relate: "Frigate tracks only the objects that are in both lists.", so "dog" in the second
  list and not the first is never tracked. The second is "Objects tracked on this device", not "by this model",
  because it's Frigate's `objects: track` config, not the model's; the wording sends someone to the right place to
  change it. Each list's Copy puts it on the clipboard comma-separated, ready to paste elsewhere, and says "Copied."
  beside the button for two seconds; a refused copy says so and stays.
- A chip can carry one of two marks, each with a legend in words that shows only when a chip has it, so color is never
  the only cue. Filled (`variant="tonal"`, the heading blue) is a recognised object the device tracks. Amber
  (`variant="outlined" color="warning"`) is a tracked object the running model doesn't recognise, and wins over filled.
  The amber objects also show under the closed panels, and the tracked list's title counts them ("(6, 2 not
  recognised)"), because they're the one thing here that means counts are missing. An other-model card's fold names
  what a switch would lose the same way. The card in use has no such line, since the top of the page says it already.
- The last panel is titled "Frigate+", because it covers getting a model as well as the key. Its state says "API key
  not set", "API key set", or "API key set, ending in ab12", with ", in use" while Frigate runs a Frigate+ model, and
  nothing for a viewer or until the secrets answer. The Status page's "Set the key" links to
  `/detection#frigate-plus`, which opens the panel and scrolls to it once the models have loaded. The key's form is
  the Device page's (`EnteredSecret.vue`) without its own heading and state line, which the title has.
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
