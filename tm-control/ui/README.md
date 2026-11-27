# tm-control UI

The control app's web pages: first-run setup, login, the home page with the device card and app tiles, the Status,
Device, Detection, and Date and time pages, the admin's Location and Software update pages, the account page, the admin's user list, and the About page. It's a Vue 3 + Vuetify 3 + TypeScript
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

In fake mode the fake Frigate tracks a car, so a reference picture's people check says nobody was tracked; start the
backend with `TM_CONTROL_FAKE_PERSON=1` to have it track a person too, and turn a camera's detection off on the Cameras
page to reach the line that says the device couldn't check.

To try the home button that nginx adds to each app's page, open `http://localhost:5173/home-button-demo.html` while
`npm run dev` runs. It's a stand-in app page with the button on it; add `?app=nr` (or `dashboard`, `ui`, `feeds`) to
try another app's spot. Drag it to either side, drop it at an edge to tuck it, and reload to see that it stays where
you left it. Logged in on the same address, it shows the fake device's name and puts it in the tab's title; without
the backend or a login, it's the icon alone. The build leaves this page out.

`npm run build` writes the site to `dist/`, and the home button's script beside it as `dist/home-button.js` (the
build fails if that grows past 10 240 bytes), and `dist/third-party-licenses.txt`, the license texts of the libraries
bundled into the pages. The build tool writes that file (`build.license` in `vite.config.ts`); it is generated and never
edited, and the About page links to it. `npm test` runs the Vitest tests in `tests/`. To use the same Node
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
  outstanding license to `/welcome` (admins) or `/waiting` (viewers), and `/users`, `/location`, `/location/mounting`,
  `/cameras`, and `/update` to admins only.
- `public/favicon.svg` is the project's logo, from its website with the editor's leftovers removed. Vite copies it to
  `dist/` as it is, file mode included; the device's sources have no world read, so the revproxy image's build
  stage makes `dist/` readable for nginx (`chmod -R a+rX`).
- `src/stores/session.ts` is the only store: the setup status, the logged-in user, and the device's hostname, which
  comes with `GET /setup/status`, so the pages before login have it too, and stays when the session ends.
- `src/title.ts` builds the tab's title (`tm-01 · Status | Traffic Monitor` with a page name, `tm-01 | Traffic Monitor`
  on setup, login, and the license pages, and `Traffic Monitor` when the name is unknown, as on the error page). A page's name comes from its menu entry, or from `meta.title` in its route where it
  has none (the page for a viewer who opened an administrator's app, for one).
- `src/colors.ts` holds the default colors and the check for a device's own. It imports nothing, so the home button's
  script can use it without pulling in Vuetify; `src/theme.ts` re-exports `DEFAULT_COLORS`.
- `src/home-button/` is the home button nginx adds to each proxied app's page. `place.ts` is its logic as plain
  functions (which app a path belongs to, where a drop settles, what the browser remembers, the title's prefix),
  `main.ts` draws the button and handles the pointer and keyboard, and `entry.ts` starts it. It imports no Vue,
  Vuetify, or Pinia, and nothing that does, because it runs on other programs' pages and has to stay small.
  `vite.home-button.config.ts` is a second Vite build that turns `entry.ts` into one file, `dist/home-button.js`, after
  the main build, without emptying `dist/`. It fails the build when the file is over 10 240 bytes. The demo page
  `home-button-demo.html` is used by `npm run dev` only and isn't built.
- `src/api/client.ts` is the API client. `schema.d.ts` is generated from `openapi.json`; don't edit either by hand.
  The status, services, system info, and time endpoints declare their responses, so their types come from
  `schema.d.ts`. The older endpoints don't yet, and `types.ts` describes their bodies.
- `src/modules/<name>/` holds one feature's pages and an `index.ts` with its routes and menu entries. The `location`
  module is the Location page (`LocationPage.vue`), a place's panel (`PlaceDetails.vue`), and its dialogs: adding or
  editing a place (`PlaceForm.vue`), the deploy review (`DeployReview.vue`), corrections (`CorrectDialog.vue`), and
  importing (`ImportPlaces.vue`). The Mounting page (`MountingPage.vue`) is the place in use's mounting, with the
  heading dial (`HeadingDial.vue`), the side view (`MountSideView.vue`), and the lengths in feet or metres
  (`lengths.ts`). Its `coordinates.ts` shows coordinates, names the precision choices,
  checks a pasted pair (`parsePair`) before the form sends it, and measures how far a correction moves a point
  (`distanceKm`). It never rounds: the API sends the stored coordinates already rounded, and its answer wins over the
  form's check. `heading.ts` is the compass rule (`compassPoint`, `pointCentre`, `facing`, `headingChoices`) and
  `HeadingPick.vue` the one pick that uses it. `TimeZonePick.vue` is the one time zone control, and `timezones.ts`
  holds the list it offers and the time zone a place starts with.
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
  neutral camera name, Remove) are offered only while Frigate answers and has cameras. Point, Use a neutral camera
  name, and Remove confirm first in a dialog (the error color only for Remove); Add as new opens `CameraEdit` with
  `adding`, which POSTs. A save that works closes the panel; one that fails keeps it open with the reason inside it. A
  refused action shows the API's message above the list, and a 409 or 404 (another admin got there first) loads it
  again.
  Every write answers with the whole new state, which replaces the page's, so there is no second request.
  A camera's other zones (`otherZonesText`) are a secondary-color line under the zones line, because their names are
  saved with every event. Names with a word the backend's name check doesn't know get a note (`zoneNote`): a tonal
  `v-alert` with no `type`, so it takes the neutral color and no icon and reads quieter than an issue box, because it
  isn't a problem and doesn't count toward the alert above the list. A name that looks like an address is an issue box.
  A key Frigate made up (`zone_a9bacc03`) is what an event saves, so it leads; Frigate's name follows it in brackets
  only so the operator can find the zone in Frigate.
  The Radar field is a drop-down, because the radars are a short fixed list and a typed name could only be wrong:
  each shows its state under its name, a radar `config.yml` doesn't set up can't be chosen, and a radar the file
  names that the unit doesn't have is listed as missing so the field says what the file says. Vuetify's select shows
  nothing for a `null` value, so the form holds "No radar" as an empty string and turns it back into `null` on Save.
  The plates switch is there only when the add-on is installed; otherwise Save sends `null` and leaves the file's value
  alone. A 422 for the radar shows under the field, every other failure inside the form.
  Reference picture: an entry in step offers it, as a text button with the row's other actions while Frigate answers
  (`canTake` in `reference.ts`, which also holds the pictures' addresses and the legend's rows). It
  opens `ReferencePicture.vue`, one dialog the page keeps, in two steps. The first has the intro and the note on what
  the picture gives away, and only Take the pictures: the note comes before any picture, because what it asks (make
  sure nobody is in either picture, which the admin answers for; share them as you would the exact location) is
  decided before the take, not after, and it stays above the pictures on the second step. The device asks Frigate
  whether it is tracking a person on the camera when the pictures are taken, so the note says what that check can and
  can't promise. The second step opens with one line, between the note and the pictures, because it is about these
  pictures and is read before them (`peopleLine` in `reference.ts`, an alert marked `data-people`): a warning when
  Frigate was tracking a person, and plain information for the other two, "Frigate wasn't tracking a person" and "the
  device couldn't check", because neither of them is a finding. The `seen` warning is solid (`variant="flat"`), so it
  doesn't read as part of the note above it, which is a tonal warning. Its text is the navy, not white (`on-warning`
  in `theme.ts`; see Color below). The line never disables a button: Save the zip and
  Take again work the same for all three, because the admin answers for the pictures. It follows the newest take and
  goes with the pictures when they are dropped. Below it the second step shows the two pictures side by side on a
  desktop and stacked on a phone (`v-col cols="12" md="6"`), the
  zones' legend with a `v-sheet` swatch in each zone's colour, the location box, and Save the zip, Take again, and
  Close. The pictures are plain `<img>` elements pointing at the device: the session cookie authorizes them, and the
  page keeps no copy of them, so nothing is left once the dialog closes; closing it, or taking again, tells the device
  to drop them. A picture that fails to load, or a 404 from Save, means
  the device no longer holds them, so the dialog goes back to its first step and says so rather than showing a broken
  picture with a working Save button. In fake mode the three lines are reached without changing code: the line for
  "wasn't tracking" is the default, `TM_CONTROL_FAKE_PERSON=1` gives the warning, and a camera whose detection switch
  on the Cameras page is off gives the "couldn't check" line.
- `src/components/` holds what several pages share: the device card, the confirmation dialog, the list of checks and
  their status marks (`status.ts`), "20 seconds ago" in words (`relative-time.ts`), waiting for a root job
  (`jobs.ts`, used by setup's system password and the entered secrets), one entered secret's form
  (`EnteredSecret.vue`, the Device page's tokens and keys, the Detection page's Frigate+ key, and the Sharing page's token), copying text
  (`clipboard.ts`, the diagnostics and the label lists; `CopyButton.vue`, an icon button that copies one value), and
  saving a file (`download.ts`, the diagnostics and the model packages and files).
- The `network` module is the Network page (`NetworkPage.vue`), the hotspot's settings for admins
  (`HotspotSettings.vue`, its name-or-password dialog `HotspotField.vue`, and `rules.ts`, the name and password rules),
  `FactRow.vue` (a label above a value with its Copy button), and `summary.ts`, the words for the unit's links and
  internet that the Device page's card reuses.
- The `sharing` module is the Sharing page (`SharingPage.vue`: the summary card, the review alert, and the polling after
  a save), its Download your data card for admins (`DownloadCard.vue`, with `size.ts` for the database's size in words),
  its form for admins (`SharingForm.vue`), one choice's box (`ConsentBox.vue`), and `examples.ts`, the three sample
  payloads the "See an example" buttons show.
- The `update` module is the Software update page (`UpdatePage.vue`), for admins only, after Date and time in the menu:
  what is installed, the check, the offer, the start, and the log. `RunProgress.vue` draws a run's stages. `update.ts`
  holds `useUpdate()`, which reads `GET /update` and asks again every 3 seconds while a run goes on, as `useJoin()`
  does for a Wi-Fi join, and `words.ts` the words for the stage ids and reason codes the device sends.
- The `about` module is the About page (`AboutPage.vue`), open to every signed-in user and last in the menu. It makes no
  request of its own. `credits.json` is its list of credits, one row per project; `script/tests/test_about_credits.py`
  checks it against the dependencies. `RoadParade.vue` and `parade.ts` are the parade, described in "The About page" below.
- `src/next.ts` decides where to go after login, and refuses to send anyone off the device.

## The About page

The page asks the device for nothing and fetches nothing, so it reads the same on the hotspot with no internet. Its
sentences and the order of its groups are in `AboutPage.vue`; the credits are the rows of `credits.json`, kept current
as `docs/development/tm-control.md` describes.

The parade is deliberate. After the page's last line sits a traffic cone with no visible label (a button whose
`aria-label` is "Count some traffic"). A click opens a strip of road, one traveler crosses it every 2 seconds, and a
tally counts them; a second click closes it. It stores and sends nothing, it stops when the page is left, and with
reduced motion nothing moves but the tally still counts. It is an Easter egg, so it is not in the user docs.

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
alert's faint tint lowers that a little. The one solid warning, the reference picture's "tracking a person" line,
turns that around: its text is the navy on the orange (7.9:1), chosen by `theme.ts` the same way as a button's,
because white on the orange would be about 2.4:1.

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
- `maplibre-gl/dist/maplibre-gl.css`, the map library's own stylesheet, for the Location page's map, its zoom buttons,
  its attribution, and its marker. Only `PinMap.vue` imports it, so it loads with the map and not with the page. The
  library draws all of that itself, so there is nothing in Vuetify to use instead; the marker takes the theme's
  `primary`.
- Three small scoped style blocks: the setup code field; spacing for the license agreement's headings and
  paragraphs, which come from markdown and can't take Vuetify's classes; and tabular digits for the clocks on the
  Date and time page.
- `touch-action: none`, as a style attribute on the heading dial's ring only (`HeadingDial.vue`), so a finger dragged
  on the ring turns the needle instead of scrolling the page. It is behaviour, not look; Vuetify has no class for it.

### Layout

Pages before login (setup, login, the license pages) have no menu: one column, at most 480 px wide, centered, with
a small `tm-01 | Traffic Monitor` line, as in the app bar, above the page title. Pages after login have the app bar and a menu drawer that stays
open from the `md` breakpoint (960 px) up and slides in below it. Content is left-aligned and at most 760 px wide.

Setup (one page, five steps):

```text
+--------------------------------+
| Traffic Monitor                |
| Step 3 of 5                    |
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

The fifth step is Sharing. The paragraph (nothing is shared unless the admin turns it on) is always there. When the
ThingsBoard token is already set (an upgraded device that had one), the Sharing page's own form (`SharingForm` with
`firstRun`, whose button reads "Save and finish") sits under it; without a token there is no form, since the token
is entered on the Sharing page later. "Not now" ends setup either way. If the state can't be read, the step is the
paragraph and "Not now".

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
  then three numbered steps from the phone's sign-in window to a browser, which saves the downloads the window can't.
  Copy the `.local` address comes first, because the second step (Use this network as is on Android, Use Without
  Internet on an iPhone) closes the window and the note with it; the third names the Nearby devices permission an
  Android 17 browser needs. The address has a Copy button and is text, not a link, because a link would open inside
  the phone's sign-in window.

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
|   Plate Recognizer API token     |
|   Set, ending in 0001.           |
|   [ Plate Recognizer token   (o)]|
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
  but the Frigate+ API key, whose form is on the Detection page, and the ThingsBoard access token, whose form is on
  the Sharing page. The Plate Recognizer token and license key appear only on a device with the add-on. The section
  ends with "The Frigate+ API key is on the Detection page. The ThingsBoard token is on the Sharing page.", each
  last phrase a link (`/detection#frigate-plus`, `/sharing`), so an admin who looks for either here finds it. It's
  one expansion panel, closed when the page opens; a link to `/device#tokens-and-keys` opens it and scrolls to it. The
  page shows no problem there, so closing it hides nothing a person needs to see: the Status page warns about a
  missing token. The panel's title, a button, sits inside the `h2`, so the heading stays a heading for
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
| | Sharing      Not sharing     | |
| | Facing, picam_h265           | |
| | NE (40°)                     | |
| | (!) This place has mounting  | |  only while values from last
| |     values from the last ... | |  time wait to be confirmed
| |     [Mounting]               | |
| +------------------------------+ |
| Places                      (h6) |
| [Add a place] [Import places]    |
| +------------------------------+ |
| | Front of the school (In use) | |  opened
| | 34b17422-si                  | |
| | 45.52, -122.69               | |
| | First used    Last used      | |
| | No events recorded at this   | |
| | place.                       | |
| | Deployments (4)              | |
| | | Deployed Nov 7, 10:15 PM,  | |  newest first; the running one
| | | running now                | |  has a blue left border
| | | picam_h265                 | |
| | | Facing NE (40°) · 7.0 ft up| |  what is recorded, in the
| | | · tilted 15°  Mounting     | |  Mounting page's unit
| | |   TM_RADAR_SERIAL_PORT_00  | |  indented under its camera
| | |   No heading set  Mounting | |
| | | Deployed Nov 2, ... to ... | |  grey left border
| | | picam_h265                 | |
| | | Facing N (0°)              | |
| | |   Correct heading          | |  an ended one
| | [Mounting] [Correct location]| |  by status, see below
| +------------------------------+ |
| | No description (Used)      v | |
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
- "Exact locations" sits between the places and the precision: one paragraph and one button, "Export exact locations",
  outlined, primary, and large. It asks first, in a `ConfirmDialog` whose confirm button is the primary colour, not the
  error colour, because nothing is destroyed, only handed out. The export comes from `GET /surveys/export` and is saved
  with `saveBlob`, as the Detection page's downloads are. The place in use's "Sharing" line and the deploy review's
  line say "Sharing: data and the exact location" when the exact location is on.
- The download of the database with each place's exact location used to be a second button here. It moved to the
  Sharing page's Download your data card, with the same request (`POST /surveys/database-copy`), and the Location page
  no longer starts a database download. The card's design notes, in the Sharing section below, now describe the
  question, the tick, and why the button stays off after a start. This page's "Exact locations" and
  Precision paragraphs each end in a `router-link` to `/sharing` (text-primary, as the Device page links to Sharing).
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
  four columns at 375 px, and each deployment has a button. Its line says what is recorded: "Facing NE (40°) · 7.0 ft
  up · tilted 15°", in the unit the Mounting page last used (`savedUnit`), and only the parts that are set.
- The list is grouped by the deploy each row came from, newest first, so a place with four deployments reads as two
  deploys of a camera and its radar, and the current one is on top on a phone. Rows that start within a second of a
  group's first row are one deploy: this version's engine starts every row of a config load at the same instant, and
  released versions' rows, which imported places hold, can be a millisecond or so apart. The group's heading holds the
  start, the latest end, or "running now" (so the border's color isn't the only signal), and names a day once when it
  started and ended on the same one. A row shows its own end only when the heading doesn't say it. Cameras come first, and a
  radar deployed with a camera is indented under it. That's order, not pairing: on a device with two cameras the
  radars sit under the last one, since the API doesn't send `camera_radar`.
- The main button is named by the place's status (`deployWords`): "Deploy here" for a planned place and "Re-deploy
  here" for a used one. The review's title and its dialog's name use the same words, and its button reads "Deploy" or
  "Re-deploy". The place in use isn't deployed to: its main button is "Mounting", a link to the Mounting page, where
  its headings and mounting change.
- While any sensor of the place in use has values from last time (`previous` in `GET /surveys/{id}/mounting`), the
  card ends with a tonal warning, "This place has mounting values from the last time the unit was here. They aren't
  recorded until you confirm them.", and a Mounting button. It goes once each such sensor is saved there. It sits in
  the card, because it is about the place in use. A mounting the page can't read shows nothing here; the Mounting page
  says why. Each load of the page asks again, keeps the last answer until the new one arrives (so the warning and the
  running rows' buttons don't flicker), and drops an answer that isn't the newest request's (after a deploy, the old
  place's refusal can arrive last).
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
|  (under 4 decimals: a warning)   |   | Was N (0°), now [NE  v]          |
| [Pick on a map]                  |   | TM_RADAR_SERIAL_PORT_00          |
| [Use this phone's location]      |   | New deployment starts            |
|  (HTTPS only; else one sentence) |   | Was not set, now [Not set v]     |
| Which way each sensor faces here |   |                                  |
| [Facing, picam_h265          v]  |   | Stored in the database:          |
| [Facing, TM_RADAR_SERIAL_...  v] |   | 45.0, -122.0                     |
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
- Each sensor's heading starts at the place's own, else at the sensor's heading in `config.yml` now, in the form and
  the review alike (`startingHeadings`). A new place starting at "Not set" would have saved a blank heading that the
  review then offered as the place's choice.
- A sensor's heading is whole degrees, 0 to 359, clockwise from north; a compass point is only a way to pick one and
  to read one, and nothing stores a point. `HeadingPick.vue` is the one eight-point pick, used by the place form, the
  review, and the correction, so the three can't drift apart. Choosing a point gives its centre (N is 0, NE 45, and
  so on). It lists a heading that isn't a centre first, titled by `facing` ("NE (40°)"), so a heading set elsewhere
  (the CSV, a later page, a file someone edited) is shown as it is, and opening the pick and leaving it never rounds
  it to a point; the Correct button stays off until the heading differs from the deployment's. The pick remembers
  the last such heading it was given while it is mounted, so after a tap on a point the measured one is still listed
  and can be chosen again (in the review, the row goes back to "Unchanged"). Because of that memory, the place form
  keys each pick by the place and the correction keys its pick by the deployment: both dialogs stay mounted and are
  reused, and an unkeyed pick would offer one place's heading for another. The review needs no key, since the page
  mounts a new one each time it opens. The card, the
  deployment lines, the review's "Was ...", and the import's preview all read a heading with `facing`: "NE (40°)",
  or "Not set" (the deployment line says "No heading set"). `heading.ts` repeats the backend's compass rule
  (`coordinates.py`), because the UI needs it to title a pick; a test holds it to the same table.
- The review (`DeployReview.vue`) is the one step on the page that changes what's recorded, so it says the
  consequences in words, one sensor at a time: "New deployment starts" (in the heading blue), the
  heading it had (in words, "Was NE (40°)"), and a pick for the one to deploy with. Moving to another place starts a new deployment for every
  sensor, as the deployment engine does. Then what the database will store for the place, rounded by the API, what's
  shared, and that counts from now on attach to the new deployment (only when one starts).
- The place in use has no review: a turn, like any other change of how the unit is mounted, is recorded on the
  Mounting page, which asks the API whether it was a move.
- Deploy sends every enabled sensor's heading, so what's recorded is what the review showed. While the API waits for
  Node-RED, the dialog says "Waiting for Node-RED to reload the settings", Cancel is disabled, and a click beside the
  dialog doesn't close it (`persistent`), so the answer isn't lost. The review then gives way to the result: the new
  deployment ids, each with Copy, or, when Node-RED hasn't reloaded the settings, a warning that the settings are
  saved and not to deploy again; Deploy is gone by then, so it can't be pressed twice. The list and any open panels
  load again behind the dialog. Under the result is the next step, with a Mounting button: "Next, record how the unit
  is mounted.", or, when the deploy's answer lists `previous` sensors, "This place has mounting values from the last
  time the unit was here. They aren't recorded until you confirm them." (the words await the maintainer's read). A
  move records none of the four mounting values, so the Mounting page is what comes after every deploy.
- A connection that drops while the API waits doesn't get the app's usual "try again": `config.yml` may be written
  by then. The review says the settings may already be saved and to check the place before deploying again, Deploy
  is gone, and the page loads the places, which show whether the deploy happened.
- When the API refuses a save or a deploy because something changed since the page loaded (409), the dialog shows
  its message and the page loads the places again behind it.
- The deploy dialog keeps showing its review while it fades out, rather than emptying first, and each opening starts
  a fresh review. Both dialogs are named by their title for screen readers.

#### Picking the point on a map

`MapPickButton.vue` sits under the coordinates field of the place form and of "Correct location". It opens
`MapPicker.vue`, a dialog around `PinMap.vue`, which is the only file that imports the map library (MapLibre GL).

- The first requests outside the device. Until an admin presses "Pick on a map" the page asks nothing of any other
  host. After that the phone's browser, not the device, asks the host of `map.style_url` for the style, tiles, fonts,
  and sprites of the area on screen. That is allowed because an admin asked for it with a button that says what it
  is, and the exact point is never sent: a tap only reads the map and then fills a field. What the host learns is the
  area on screen, never the point: the tiles that cover the view. Its vector tiles stop at zoom 14, so even the
  closest view asks for squares about 1.7 km on a side (at 45.5° N). The picker names the host and says the device
  sends it nothing; it doesn't state the tile size. Every request is made with no referrer (`transformRequest`), and
  the page's referrer policy (`index.html`, `same-origin`) does the same for the links in the map's corner, the
  attribution, which open their sites with no Referer; the device's own requests keep theirs, which the CSRF check
  falls back on. The control app's backend makes no request. The map's address comes from the API
  (`PlacesState.map`), never from the UI's code; an address that isn't `https://` is off, and with none there is no
  button.
- The hotspot has no internet, so on it the button gives way to one sentence that says so and says to type or paste
  the coordinates, or to come back once the device is on Wi-Fi. The page knows it is on the hotspot from
  `GET /setup/status`.
- The picker opens at the point already in the field (zoom 17), else at the place in use (zoom 14), else over the
  device's region (zoom 3), else on the whole world. A tap places the pin and the marker, which takes the theme's
  `primary`, can be dragged to the exact spot. A tap on the marker itself isn't a tap on the map: MapLibre would
  deliver it to the map's click as well and move the pin a little. North stays up and the map stays flat, for the
  mouse, a touch, and the keyboard alike; nothing here uses a bearing or a tilt. A double click or double tap doesn't
  zoom (`doubleClickZoom: false`), because each tap of it would place the pin too; pinch, the wheel, and the buttons
  zoom.
- The region is for a place with nothing to start from, so the map doesn't open on the whole world. The backend works
  it out from the device's own files (`modules/location/region.py`, `MapSources.region`): the city of the time zone,
  from the Pi's own time-zone data, rounded to two places, and null with no map. The data is two tzdata tables:
  `zone1970.tab` answers first, and a zone it doesn't list (it merged many names away, such as `Europe/Amsterdam`) is
  looked up in `zone.tab` beside it. Legacy aliases such as `US/Pacific` give none. The region is used only when the
  Wi-Fi country is set and is one of the countries the zone's row lists. The installer sets the zone only with `-z`, and
  a unit's zone is the imager's or the image's unless changed. It sets the Wi-Fi country (`US` when the device has
  none), so a unit whose zone is a US one passes the check and opens over that zone's city until the zone is set on the
  Date and time page; the check keeps a zone from sending the map to a country the Wi-Fi isn't set for. Rejected:
  looking up the device's internet address, and time-zone boundary data. Both come from outside the device, and the
  maintainer ruled out any outside request for this. The region isn't private: it is a time zone's city, `GET /surveys`
  is admin-only, and the map's host learns little more at this zoom than the phone's internet address tells it. The zoom
  is 3, a wide view around the city, about the size of a time zone. A time zone's city often sits at the zone's edge
  (Los Angeles at the south end of the Pacific zone), so the view has to be wide to show much of the zone around the
  city. Zoom 5 showed only the south of California and zoom 4 only California and part of its neighbours; a fake-mode
  review at 375 and 1280 px found zoom 3 holds the whole Pacific zone on a phone and, on a wide screen, runs from
  Portland to Mexico. Going further out or in is one constant (`REGION_ZOOM` in `PinMap.vue`) and its test. Fake mode is
  in the Pacific zone with Wi-Fi country US, so it shows this.
- "Use this point" writes the field at five decimal places, as the device keeps an exact location, and the admin can
  still change it before saving. It waits for the map itself to set the pin (a tap or a drag) and is off while the
  map has failed, so the field's own point is never written back as a pick. Typed coordinates with fewer than four
  decimal places get one warning line in the warning color under the field, with the size they will be rounded to; it
  never blocks Save, because a rough location is a choice, not a mistake. `saved` and `corrected` say whether the map
  set the coordinates last.
- The picker is full-screen on a phone (below `sm`) and 720 px wide above. Like the other Location dialogs it is
  `persistent`, so a drag that ends outside the map can't close it; Cancel is the way out.
- A map that can't load says so, in place of the map, with "Try again", which starts the map afresh. Any `error`
  before the map's `load`, or no `load` in 10 seconds, counts as a failure, by design (a map that half-loads is of no
  use for placing a pin), so one missing tile on a flaky connection can show the failure message. The map stays
  mounted while the dialog fades out and goes at after-leave, so the dialog's body doesn't collapse. A browser that
  can't make the map at all (no WebGL2) and a map file that can't be fetched get the same message. A page loaded
  before an upgrade needs a reload: its map file is gone, so the picker says the map failed, and Try again asks for
  the file again (`MapPicker.vue` imports it by hand, since `defineAsyncComponent` keeps a failed load).
- The map library, its stylesheet, and its worker are a chunk of their own, loaded the first time the picker opens
  (a dynamic `import()` in `MapPicker.vue`), so the page's first download doesn't grow by them. The worker is a
  separate `.mjs` file, which nginx serves as JavaScript (`mime.types` has no `mjs`). The entry chunk grew by about
  6.6 kB (2 kB gzipped), from `MapPickButton.vue`, `MapPicker.vue`, the coordinate helpers, and the two forms'
  changes, because `LocationPage` imports them directly; `PinMap.vue` is in the lazy chunk, and none of the entry's
  growth is library code.

#### Corrections, and importing places

- A correction is for a value entered wrong, never for a move, and both dialogs (`CorrectDialog.vue`) open by saying
  so: "Use this only if the location was entered wrong. Every record from this place will say it was at the new
  point. If the unit moved, deploy it to the place it moved to instead." The heading's says the same of its deployment
  and points to the Mounting page of the place in use for a turn, and both end with
  "Copies and uploads that already left the device keep the old values." The button reads "Correct", not "Save".
- "Correct location" shows only for a used place or the place in use that has a point: a correction needs one, and
  a place with none is planned anew. The field starts at the exact point and can't be left blank. A new point more
  than about 1 km from the old one (`distanceKm`) gets a second confirmation, with a red button, that gives the
  distance and says to deploy instead. The same point again is allowed, because correcting again is how a correction
  whose stored rows weren't re-rounded (502) is finished; the same heading isn't, because there's nothing to finish.
- "Correct heading" is a text button on the "Facing" line of a deployment that has ended, so a long list stays compact
  on a phone. A running deployment at the place in use has "Mounting" there instead, a link to the Mounting page: what
  runs is changed there, where the API decides whether it is a correction or a move. A running deployment whose sensor
  has no section on that page (a sensor disabled in `config.yml` since its deployment started keeps its open row, and
  the page lists enabled sensors only) keeps "Correct heading", so its heading can still be fixed; the Location page
  passes `PlaceDetails` the sensors it read from `GET /surveys/{id}/mounting`, and while that is unknown it offers
  Mounting.
- The import is preview, then import. Preview sends the text as a dry run and lists the places the API read, by
  line, with the lines it couldn't read in an error above them. Import sends the same text again and is enabled only
  when the preview found places and no errors; any change to the text forgets the preview. The API creates every
  place or none. A file is read into the same box as pasted text, so what's previewed is always on screen, and
  64 KiB, the API's limit, is checked before anything is sent. The dialog is `scrollable`, so a long preview scrolls
  under the title and the buttons stay in view, and `persistent`, so a click beside it can't hide the result.

#### A place's time zone

The device stores times in UTC, so anyone who counts a place's data by local hour needs the place's time zone. Almost
every place is in the same time zone as the unit's clock, so that is what a place gets unless someone says otherwise,
and choosing another takes a tick first, so it isn't changed by accident. The time zone belongs to the place, not to
the unit: the Location page never sets the device's clock, and the Date and time page never sets a place's time zone.
The page only says when the two differ. (Not to be confused with Frigate's zones, the areas drawn on a camera's
picture, which this page doesn't touch.)

```text
+----------------------------------+   +----------------------------------+
| Add a place                      |   | Add a place                      |
| ...                              |   | ...                              |
| [Pick on a map]                  |   | [Pick on a map]                  |
| Time zone                        |   | Time zone                        |
| America/Los_Angeles, the same as |   | [x] This place is in a different |
| the unit's clock                 |   |     time zone                    |
| [ ] This place is in a different |   | [Time zone  America/New_York  v] |
|     time zone                    |   |  Recorded with this place's data,|
|  Recorded with this place's data,|   |  also when no location is stored.|
|  also when no location is stored.|   | Which way each sensor faces here |
| Which way each sensor faces here |   | ...                              |
| ...                              |   +----------------------------------+
+----------------------------------+     ticked: the list opens
  also Edit, the deploy review (after
  the sensors, before "Stored in the
  database"), and the Time zone dialog

  A panel, the place in use:
| First used    Last used   Time zone        |
| 3 days ago    In use now  America/New_York |
| The unit's clock is set to                 |  only when the two differ
| America/Los_Angeles. Change it on Date and |  "Date and time" links to /time
| time.                                      |
| ...                                        |
| [Mounting] [Correct location] [Time zone]  |
```

- One control, `TimeZonePick.vue`, wherever a place's time zone is set: Add a place, Edit, the deploy review, and
  the Time zone dialog, so the four can't drift apart. It says the time zone in words and has one box, "This place is
  in a different time zone".
  - Unticked, the place gets the clock's time zone (`clock_timezone` in `GET /surveys`), and the line names it: "the
    same as the unit's clock". The name is saved with the place, not a "follow the clock" marker, because the clock
    can be changed later and the place's records must keep the time zone they were made in.
  - Ticked, the list opens under the box, starting at the same time zone. Unticking puts the clock's back.
  - The box starts ticked when the place already has a time zone other than the clock's, so Edit shows it as it is.
  - When the clock's time zone is unknown (null, or an empty name, which the page reads as unknown), there is no line
    and no box: the list shows at once, empty unless the place has a time zone.
  - The hint, "Recorded with this place's data, also when no location is stored.", always shows, because an admin who
    chose No location stored wouldn't expect anything about the place to be kept.
- The list is the Date and time page's picker: a `v-autocomplete` over `GET /time/timezones`, outlined, labelled
  "Time zone", with its text selected on focus, so typing "Berlin" replaces the time zone (that page's screenshot
  review found the caret landing mid-name). The page asks for the list once, when it opens, and passes it to every
  control. When it can't be loaded, the box still works, since the clock's time zone needs no list; ticked, the field
  shows the error in place of the hint and is disabled, and the form still saves everything else. Emptying its text
  changes nothing: Vuetify clears a single list's model when its text is emptied, so the control ignores the empty
  value, keeps the last name, and shows it again when the list loses focus. That is what keeps the page from clearing a
  time zone. The place form also leaves `timezone` out of its body when there is none (the clock's is unknown and none
  was picked), so an edit keeps the stored one and a new place has none, and the review sends no time zone it doesn't
  have.
- The browser's time zone isn't used. The unit's clock is set for where the unit is, and a place planned from a desk
  in another time zone would get the desk's.
- The review saves a changed time zone with its own request (`PUT /surveys/{id}/timezone`) before it deploys, and
  deploys only once that is answered. A refusal shows beside the buttons and deploys nothing. The deploy then writes
  the place's time zone into the settings with its id, so the new deployments carry it from their start. An unchanged
  time zone sends no request. A planned place with none (from an import with the column blank, or from before this
  version) gets the clock's at its review. For a used place, a line under the control says "Changing it corrects this
  place's stored deployments." while the choice differs from the saved one (a place with none counts as differing),
  because the same save rewrites that place's stored rows, which the planned place's doesn't; it is gone once the review
  has saved the choice. It doesn't say "It starts no new deployment", which would be untrue in a review that starts
  them. The review asks the page to load the places again (`stale`) when the request failed in any way, and when the
  deploy then failed after a request this review sent, so the page doesn't keep showing the old time zone beside a
  store that has the new one; a 409 asks once.
- Each used place and the place in use show "Time zone" on their panel, with "Not set" for none, beside First used
  and Last used. It shows also when Node-RED didn't answer, because the time zone comes from the control app. Their
  "Time zone" button, after Correct location, opens the dialog, which has the same control: for a place with none,
  Save sets the clock's. A planned place has neither, because Edit shows its time zone. The dialog's sentence says what
  a change does to the records, as the corrections' do, but its button reads Save, not Correct: setting a time zone for
  the first time isn't correcting a mistake. A 409 or a 5xx makes the page load the places again, because after a 502
  the time zone is saved though its rows weren't updated.
  Save is never disabled for an unchanged time zone, so a save that failed halfway can be finished, as Correct location
  allows the same point again; it waits only when there is no time zone to send (no clock time zone, none chosen),
  because the page never sends null.
- Two lines, in normal text and only on the place in use, because neither is an error:
  - With no time zone (a place from before this version): "This place has no time zone. Set one so its data can be
    read in local time."
  - When its time zone and the clock's differ: "The unit's clock is set to `<time zone>`. Change it on Date and
    time.", with "Date and time" a link to `/time`. The line points to that page instead of offering to set the clock
    here, because changing the clock's time zone restarts Frigate, Node-RED, and nginx. It shows nothing when the
    clock's time zone is unknown, or when the place has none (the first line says that). Two names for one time zone
    (such as `Asia/Calcutta` and `Asia/Kolkata`) read as different; that is rare, and the line only informs.
- Rejected: the list always open (most places never need it, and an open list invites a stray tap); starting from the
  browser's time zone (above); a list grouped by region or by UTC offset (the Date and time page's flat list is the one
  admins know, and typing a city finds it).

#### The heading dial

`HeadingDial.vue` is how the Mounting page sets which way a sensor faces: a ring to tap or drag, the eight compass
points as buttons around it, and a number field for an exact heading. It is a plain input (`heading`, `label`,
`disabled`; it emits `update:heading`) and sends nothing to the API. `HeadingPick` stays the pick for the place form,
the review, and the correction.

```text
+----------------------------------+
| Heading                          |  the label
|(NW)          (N)          (NE)   |  44 px round buttons
|       .-------+-------.          |
|      /            /    \         |  needle in the primary color
|(W)  +         o         +  (E)   |  ring 200 px, a tick at each point
|      \                 /         |
|       '-------+-------'          |
|(SW)          (S)          (SE)   |
| 52°, north-east.                 |  facingWords
| [Degrees from north 52] [Not set]|
|  Enter a whole number from 0 to  |  only for a number outside 0 to 359
|  359.                            |
| North is up on a map. A phone's  |  secondary text
| compass shows magnetic north ... |
+----------------------------------+
```

At 1280 px the dial stays on the left at the same size, and the words, the field, Not set, and the help line sit in a
column beside it (`v-row` with `v-col cols="12" sm="auto"` and `v-col cols="12" sm`); below 600 px they stack under it.

- The dial is 288 px square at every width, which leaves room for a card's padding inside a phone's 343 px: three
  rows of Vuetify utilities (`d-inline-flex flex-column`, each row `d-flex justify-space-between align-center`). The
  middle row is W, a 200 px SVG, E; the top and bottom rows stretch to the same width, so N and S sit over the
  centre and each corner point sits exactly on its 45° line. No CSS positions anything. Drawing the points inside the
  SVG was rejected: SVG has no buttons, and a `<g role="button">` would have to rebuild focus, Enter, and Space by hand.
- The points are real `v-btn`s, round and 44 px (`icon :size="44"`, the text "NE" as their content), outlined in the
  body text color. The one whose centre is the heading is filled `primary` with `aria-pressed="true"`; at 52° none
  is filled, because pressing NE would change 52 to 45. Each is named "NE, north-east, 45°", which keeps the visible
  letters in the name for voice control. Tab goes through them in reading order (NW, N, NE, W, E, SW, S, SE), then the
  field, then Not set.
- The SVG (`width`, `height`, and `viewBox` attributes) holds the ring (`secondary`, on a `surface` face), a tick at
  each of the eight points, the hub, and the needle in `primary`. Its colors come from Vuetify's `text-*` classes and
  `currentColor`, so a device's own colors follow. It is `aria-hidden`, since the words and the buttons say all of it.
- A press on the ring sets the heading there, and a drag follows the finger: `pointerdown` takes pointer capture, so
  the drag keeps going when it leaves the ring, and `pointermove` sets it until `pointerup`, `pointercancel`, or
  `lostpointercapture` (a hidden tab, say), so a drag that lost its pointer never follows a later hover.
  `angleAt` turns the point into whole degrees clockwise with up as 0 (right 90, down 180, left 270), and 359.5
  rounds to 0, so a drag across the top goes 358, 359, 0, 1 without a jump. A press on the hub (within 12 px of the
  centre) changes nothing, because the angle there is noise. `touch-action: none` on the SVG only, so a drag on
  the ring turns the needle instead of scrolling the page; a swipe anywhere else still scrolls.
- The words under the dial are `facingWords`: "52°, north-east.", or "Not set." A `d-sr-only` live region says the
  same after a point, Not set, a tap, or the end of a drag, never at each step of a drag, and not while typing,
  because the field reads out its own value; leaving the field says the heading it set, so the region never holds an
  older one.
- The field is a `v-text-field` with `inputmode="numeric"`, the label "Degrees from north", and at most 12 rem wide
  (its `max-width` prop). The text is sent whenever it is a whole number from 0 to 359, key by key, so the needle
  follows the typing. Anything else ("52.5", "-1") is not sent and the field says "Enter a whole number from 0 to
  359." Typing "400" sends 4, then 40, and refuses the third key: the heading is 40 while the field shows "400" and
  the message. An empty field changes nothing and says nothing: it is the moment between deleting a number and typing
  the next, and only Not set clears the heading (the maintainer chose this on review). Leaving the field puts it back
  in step with the heading ("400" becomes 40, "05" becomes 5, an empty box shows the heading again) and clears the
  message. When the heading changes by a point, a tap, or Not set, the field shows it (empty for Not set) and any
  message goes.
- Not set is an outlined button beside the field, 56 px tall to line up with it, filled `primary` with
  `aria-pressed="true"` while there is no heading. The needle is then gone, the hub stays, and the field is empty.
- The help line, under the field in the secondary color and tied to it with `aria-describedby`: "North is up on a
  map. A phone's compass shows magnetic north unless it is set to true north. If you only know the compass point, tap
  it."
- The label is a `text-body-1` line above the dial, and the whole dial is a `role="group"` named by it, so a screen
  reader says which sensor's heading a button belongs to.
- Disabled: the buttons and the field are Vuetify's disabled ones, the SVG is drawn at Vuetify's disabled opacity
  (its `opacity` attribute, 0.38) and ignores the pointer, and `touch-action` is left off, so the page scrolls over
  it. The words stay at full strength, since the heading is still a fact.

The dial was checked in a scratch mount at 375 px and 1280 px wide: a measured heading (52), a point's centre (45),
Not set, disabled, a number outside 0 to 359, a drag that went off the ring, and a point pressed from the keyboard.

- The field had a "°" suffix, which Vuetify puts at the far end of the box, so it read as a stray mark, away from the
  number. It's gone: the label says degrees, and the words above say "52°".
- Not set (44 px) sat higher than the field (56 px) beside it. It's 56 px tall now, so the two line up.
- Looked at and kept: at 375 px the dial leaves about 55 px free on its right, and the field's message wraps onto two
  lines under the 12 rem field.
- Looked at and kept: a pressed point that also has keyboard focus is a shade darker, from Vuetify's focus overlay, as
  every filled button is; the focus ring around it is what shows the focus.

Defaults rejected for the dial:

- A slider (`v-slider`) from 0 to 359: it puts north at both ends, so a turn from 350 to 10 crosses the whole bar.
- The eight-point `v-select` alone, as `HeadingPick`: a heading measured with a phone (52) can't be entered.
- `v-number-input`: it quietly clamps 400 to 359 when the field loses focus, and its plus and minus buttons repeat
  what the points and the ring do.
- Dragging the needle's tip only: a small target on a phone. Any press on the ring moves the needle there.
- The ring as a keyboard slider (`role="slider"`, arrow keys): a ninth stop that repeats the field. Keyboard users
  type the number or press a point.
- Points in compass order for Tab (N, NE, E, ...): it needs `tabindex` juggling, and reading order matches what's seen.
- A larger dial on a wide screen: one size is one set of numbers to test, and a mouse doesn't need more room.

#### Lengths and the side view

The control app stores metres. Feet exist only on the page, in `lengths.ts`: `shown` (the text of a field: one decimal
in feet, two in metres, empty for no length), `decimal` (a plain number as typed, with one comma and no dot read as
the decimal mark, since many phones' keypads have no dot, but not a comma before exactly three digits, "1,000", which
may be a thousands separator), `typed` (what was typed, as metres to two decimals, null for nothing or for text that
isn't a number), `both` ("7.0 ft (2.13 m)", the chosen unit first), and `savedUnit` and `saveUnit`. A foot
is 0.3048 m, and rounding is half away from zero, as the backend rounds (`toFixed` works on the number's exact value, as
the backend does). The unit is feet until someone chooses metres, because the usual mounts are whole feet (7, 12, and
16), so feet are the unit they are round in; each length is shown in both, so metres are always there. The browser
remembers the choice in `localStorage` under `tm.mounting.unit`. A browser may refuse its storage, so every read and
write is inside `try`, and a refusal means feet and a choice that lasts until the page is closed.

`MountSideView.vue` is the page's drawing of one sensor: `heightM`, `pitchDeg`, `distanceM`, and `unit` in, nothing out.
It is a picture, not a calculator. The page passes the API's dry-run values, where the API has already worked out
whichever of tilt and distance isn't measured, and the drawing lays out the three it is given.

```text
+------------------------------------+
|              15°                   |  the tilt, above the unit
|        7.0 ft [#]__                |  the height beside the support, the unit on it
|               |    ----____        |  the line of sight, in the primary color
|               |            ----o   |  o: the centre of the view, on the road
|  -------------+-----------------   |  the road
|               |<--- 26.1 ft --->|  |  the distance along the ground
+------------------------------------+
```

- One scale for both directions, so the support and the ground point both fit in the 300 by 180 drawing: the smaller
  of what the height and what the distance allow. A distance that is missing asks for no room. The unit keeps its size
  when the support is short (0.5 m at 286 m is a unit sitting on the road), and the height's label moves up to stay
  clear of the road.
- Colors are Vuetify's, as in the dial: the road, the support, and the distance's ruler are `text-secondary`; the unit,
  the line of sight, and the ground point are `text-primary`; labels are the text color. All of it is `currentColor`,
  with `width`, `height`, and `viewBox` attributes and no CSS. The drawing is a fixed 300 px wide, like the dial's 200,
  which leaves room inside a card's padding on a phone's 343 px.
- A missing value leaves its part dashed and unlabelled. With no tilt, the line of sight is dashed (it still runs to the
  ground point, if the distance is there); with no distance, the ruler under the road is dashed and has no label,
  which is also what a tilt of 0 looks like, since the centre of the view is then at the horizon and the line runs level
  to the edge. With a tilt above 0 and no distance (the API gives none when it would be over 1,000 m), the line of
  sight is solid and runs at that tilt to the right edge or the road, whichever it meets first, and a tilt of 90
  draws it straight down. With neither value, the line of sight is a dashed stand-in. A tilt of 90 with a distance of
  0 also draws the line straight down over the support. With no height there is nothing to draw: one line, "Enter the
  height to see the side view."
- The text alternative says what the labels say: "Side view. The unit is 7.0 ft above the road. Its tilt is 15° below
  level. The centre of its view is 26.1 ft along the ground.", and "not set" for a missing tilt or distance. The SVG is
  `role="img"` with that as its `aria-label`; the text inside it is for people who can see it.

The side view was checked in a scratch mount at 375 px and 1280 px wide: a full set of values in feet and in metres, a
tilt of 0, a tilt of 90, no height, a height of 100 m and one of 0.5 m, 0.5 m with a 286 m distance, a missing tilt, a
missing distance, and only a height.

- At 0.5 m and 286 m the height's label sat on the road line, over a support too short to hold it. It now stays above
  the road.
- Looked at and kept: at a tilt of 90 the line of sight lies over the support, so the support shows a blue stripe; and
  at 1280 px the drawing stays at 300 px on the left, like the dial.

Defaults rejected for the side view:

- A drawing that stretches to the card's width: its text would scale with it, and a label that is 12 px on a phone is
  17 px on a desktop.
- A separate scale for height and distance, so a tall support and a far ground point both look large: it draws the wrong
  tilt, and the tilt is what the drawing is for.
- Working the missing value out in the drawing: the API already does, and a second copy would drift from it.

#### The Mounting page

`MountingPage.vue`, at `/location/mounting`, is where an admin records how the unit is mounted at the place in use. It
is admin-only, like the Location page, and has no menu entry of its own: the Location page leads to it. It reads
`GET /surveys` for the place in use, then `GET /surveys/{id}/mounting`, and writes with `PUT` on the same path.

```text
+----------------------------------+
| < Location                       |  a text link back
| Mounting                    (h5) |
| Front of the school              |
| a1b2c3d4-si                      |
| How the unit is mounted at this  |
| place. The numbers are stored... |
| (!) Node-RED didn't answer, ...  |  only then
| Units  (o) Feet  ( ) Metres      |
| Start from a usual mount         |
| ( ) Tripod beside the road       |
| ( ) Pole or sign post            |
| ( ) Upstairs window over an ...  |
| ( ) My own measurements          |
| -------------------------------- |
| picam_h265                  (h6) |
| Camera                           |
| (i) From last time: 12.0 ft up,  |  only with `previous`
|     tilted 15°, pole or sign post|
|     [Use these values]           |
| Which way it faces               |
|   (the heading dial)             |
| [Height above the road  12.0 ft] |
|  12.0 ft (3.66 m)                |
|  From the road surface ...       |
| (o) I measured the tilt          |
| ( ) I measured the distance      |
| [Tilt below level          15 °] |
|  How far the camera points ...   |
| [Distance to the centre  44.8 ft]|  greyed: the dry run's value
|  44.8 ft (13.66 m)               |
|  Along the ground, from ...      |
|   (the side view)                |
| -------------------------------- |
| TM_RADAR_SERIAL_PORT_00     (h6) |
| Radar                            |
| [x] Same as picam_h265           |
| Takes picam_h265's heading,      |
| height, and tilt.                |
| -------------------------------- |
| Did the unit move or turn?       |  only when the dry run asks
| picam_h265: heading 40° to 62°   |
| (o) No, it is where it was. I    |
|     measured it better.          |
| ( ) Yes, it was moved or turned. |
| The record of the running        |
| deployment is corrected.         |
| [Save] [Cancel]  Saved.          |  the result beside the buttons
+----------------------------------+
```

- The order is the order of the work at the roadside. Where it is and what it is for come first, so a person who
  followed a link knows what the numbers will do. The units come before any number, because every length on the page
  is shown in them. The usual mounts come before the sections, because picking one fills every section at once, and a
  person who starts from one only adjusts after. Then one section per sensor, in the API's order (each camera, its
  radar under it, the other radars, the rest), titled with the sensor's name, since that is what the deployments list
  shows. Last the question, then Save: the question is about the save, so it sits where the save is.
- Inside a section, what the person does in order: which way it faces, then how high, then the tilt or the distance,
  then the picture that checks it. The notice of last time's values goes at the top of its section, not after the
  drawing: it offers to fill the fields below it, and on a phone an offer under the drawing would be found only after
  the fields were typed in.
- At 375 px a section is one column: the dial (288 px), then each field at 20 rem with its lines under it, then the
  side view (300 px), all left-aligned. Each field shows its value in the other unit under it ("12.0 ft (3.66 m)",
  `both`) and its help in the secondary color under that. A section has no card around it: the page is one form, and
  a top border with the sensor's name as an `h2` separates the sections, as the Location page's sections are separated.
- The usual mounts are a radio group, not a select, so the three and "My own measurements" are read without a tap.
  Picking a mount sets, in every camera's and radar's section that isn't following a camera, the height, the tilt, "I
  measured the tilt", and the mount's key; nothing is saved until Save. "My own measurements" clears the key in those
  sections and leaves the numbers. The group starts at the key every such section shares, at "My own measurements"
  when none has a key and one has a number, and at nothing otherwise, and is chosen the same way again after **Use
  these values** and after "Same as" is ticked or unticked, so it never shows a mount the form won't save.
- Lengths: each length field keeps the metres it was loaded with until someone types in it, so switching between feet
  and metres, or leaving a field untouched, never sends a value that went through feet and back. Text typed back to
  what the page last put in the field gives that value back too: a height saved as 3.00 m reads "9.8" in feet, which
  typed would be 2.99 m, so a digit typed and deleted changes nothing. A field emptied clears that value. A comma
  is the decimal mark when there is one and no dot ("7,5"). A field with text `typed` can't read ("1,000", "abc")
  says "Enter a number, such as 12 or 12.5." under it, isn't sent, and keeps Save off; the page sends no dry run
  while one does, since the API couldn't check what the person meant. A negative or a number past a limit is sent,
  and the API's sentence shows under the field. The tilt is read the same way, in degrees.
- One of tilt and distance is measured and the other worked out. The person picks which with two radio buttons; the
  other field is disabled and shows the value the last dry run worked out. Choosing the other as measured starts it
  from that shown value, so switching alone changes no number. A switch made while a dry run is waiting or on its way,
  or while **Try again** is offered, sends that dry run first and starts from its answer, so a height typed just before
  the switch is the one the value is worked out for. When the API works none out (no height), the field starts from what
  was last typed in it, so a tilt typed before the height survives a switch to the distance and back; a field that was
  never measured holds nothing, so a tilt of 0 switched to the distance starts empty and not at a distance from before.
  The one that stops being measured forgets any text it couldn't read, since it is no longer sent: only the height and
  the measured one can hold the form back. The page does no trigonometry: a tilt of 0 shows an empty distance because
  the API gives none.
- After each change the page waits 400 ms and sends the whole form as a dry run; a counter drops any answer that
  isn't the newest request's. Every section is sent every time, a following radar as `same_as_camera: true`, because
  a save writes only the sensors it names. Save is off until the form differs from what was loaded, while a dry run is
  waiting or was refused, while a field can't be read, and while Node-RED doesn't answer.
- "Same as <camera>" is never ticked for the person. It starts ticked only when the API says `same_as_camera`, which
  it does only while the radar's five values equal its camera's; ticking it is always the person's act. Ticked, the
  section hides the dial, the fields, and the side view, and says "Takes <camera>'s heading, height, and tilt."
  Unticking shows them again, filled with the camera's values as the form has them, so the radar starts where it was.
  A ticked radar shows its own values from last time only when they differ from its camera's, or the camera has none:
  otherwise the camera's notice offers them and one save confirms both. Its **Use these values** unticks it, with the
  camera's heading, and fills the rest from last time, so its own values are never overwritten unseen.
- The question sits in the page above Save, shown when the newest dry run says `ask`, with the dry run's `suggested`
  answer already chosen and the changes that count listed ("picam_h265: heading 40° to 62°", and a length in both
  units, "height 12.0 ft (3.66 m) to 13.0 ft (3.96 m)", so a change smaller than a tenth of a foot still reads as
  one), old value from the page's load and new from the dry run. A filled-in value or a new mount key doesn't count,
  so it isn't part of what is asked and isn't listed. The person's answer holds while the changes that count stay as
  they were; once they differ (another turn, say), the dry run's new `suggested` is chosen again. Under the choice,
  what it does: the running record is corrected, or "A new deployment starts now for" the sensors with a change that
  counts (`changes` with `counts`). It isn't a dialog: the answer is part of the form and belongs beside what changed,
  a dialog would hide the numbers it asks about, and a change to a field while the question shows asks the API again.
  A 409 `answer_needed` from a save sends a dry run at once, so the question appears.
- The result stays beside Save until the form changes again: "Saved.", "Saved. A new deployment started for ...",
  "Saved. Node-RED hasn't loaded the settings yet; the new deployment appears once it does. Don't save again.", or the
  API's sentence. After a save the page loads the mounting again, so a sensor whose last values were confirmed loses its
  notice and Save is off until the next change. While a save is on its way every control that changes the form is off
  (the units, the usual mounts, "Same as", Use these values, the dial, and the fields), because the reload after it
  would replace an edit made meanwhile.
- The notice of last time's values is a tonal info alert in its section: "From last time: 12.0 ft up, tilted 15°, pole
  or sign post" (a distance, "44.8 ft to the centre of the view", where there is no tilt, so a distance measured
  without a height still has something to offer) and **Use these values**, which fills the section's fields, the
  measured choice, and the mount. Nothing is recorded until Save, and the dry run then lists them as filled-in values,
  which don't count, so nothing is asked.
  The Location page's card and the deploy review's result say the same in one sentence with a **Mounting** button
  (the words await the maintainer's read).
- A refused value (422 with `detail.index` and `detail.field`) shows the API's sentence under that section's field; a
  refusal of anything without a field of its own shows in its section, and one with no index under Save. A save's
  refusal shows its sentence once: under its field when the page shows that field, else beside Save. A 409 other
  than `answer_needed` loads the page again. A dry run that fails any other way (no answer from the device, a 500)
  shows its sentence under Save with **Try again**, which sends the same dry run, since nothing else would send one
  until the form changed; Save stays off until one is answered. No place in use, or a mounting the API refuses to
  read, shows a warning in place of the form.
- Cancel goes back to the Location page and sends nothing.
- The page, the dial, the side view, and the lengths are in the entry chunk, because the routes import their pages
  directly, as every other page's do. The entry chunk is 723.74 kB (237.74 kB gzipped), up from 696.74 kB (229.36 kB)
  before the dial, the lengths, the side view, and the page, and the Location page's changes for it.

The page was checked in fake mode at 375 px and 1280 px wide: the form as a fresh device has it, a usual mount picked,
a heading set on the dial by a press and a drag, the result after a save, a radar following its camera and unticked,
the question after a turn, the result that names the new deployments, and the notice of last time's values after a
deploy away and back.

- "Distance to the centre of the view" was cut off as the field's floated label at 14 rem. The three fields are 20 rem
  now, which holds it and still fits a phone's column.
- The height and distance fields kept an empty row for their message while they had no value, so their help sat
  further below them than the tilt's. All three leave out the row when there is nothing in it.
- Looked at and kept: at 1280 px the dial's words, field, and help sit beside it, because the side-by-side layout
  switches at 600 px of window width (Vuetify's `sm`), and in the page's 760 px column there is room for both. At
  375 px they stack under it.
- Looked at and kept: a mouse drag that starts on the dial's ring and runs over the page's text selects nothing in
  Chromium (the ring's pointer capture keeps the events), so the dial needs no `preventDefault`.
- Looked at and kept: a long result ("Saved. A new deployment started for picam_h265 and TM_RADAR_SERIAL_PORT_00.")
  wraps under Save and Cancel instead of beside them, on a phone and on a wide screen.
- Looked at and kept, in a second check: **Try again** sits at the top right of its alert, as on the page's load
  error, and on a phone the sentence wraps beside it; a following radar's own notice sits between "Same as" and
  "Takes …", so it is seen before the line it replaces; and on a phone a question line in both units can wrap
  inside a length ("13.0" at the end of one line, "ft (3.96 m)" on the next), which still reads.

Defaults rejected for the page:

- A dialog for the whole form on the Location page: a dial, three fields, and a drawing per sensor don't fit a phone's
  dialog, and the Location page behind it would show none of it.
- A question for each field, or for each sensor: the API asks once for a save, and one answer covers it.
- Working the numbers out in the browser (the distance from the tilt, whether to ask, the suggested answer): the API
  does, and two copies of the rules would drift. The page compares the form with what it loaded only to turn Save on.
- A select for the usual mounts: the titles are long and a person would have to open it to see the choices.
- A tick that sets itself when the numbers happen to match: following the camera would then be the page's choice, and
  later changes to the camera would move the radar without the person deciding it.

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
- "Correct heading" (it was "Correct bearing") was a small button, in smaller type than the "Facing N" beside it.
  It's the normal size now.
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

Headings in degrees (checked in fake mode at 375 px and 1280 px wide: the card for the place in use, a deployment's
line with Correct heading and its dialog, the deploy review, the place form, and a pick opened on a measured heading):

- At 375 px the review's row, "Was NE (40°), now" and its pick, squeezed the pick to "NE (4..." because the words
  don't wrap. The row wraps now, so the pick drops under the words on a phone and stays beside them on a wide screen,
  and the pick is wide enough for "NE (40°)" (11 rem, not 9).
- Looked at and kept: a pick on a measured heading lists it first and again by its point below ("NE (40°)", then
  "NE"), so a person can see that choosing NE changes the heading to 45. It stays listed after a point is chosen,
  so a tap on the wrong point can be undone without Cancel.

The map pin (checked in fake mode at 375 and 1280 px wide, with the real map: the form with its button, the picker
with and without a pin, the failure message, the hotspot sentence, and the warning; the marker was tapped and dragged
and the picker closed mid-fade, in a real browser):

- Tapping the marker moved the pin a little, because the tap also reached the map's own click. A tap on the marker is
  ignored now. Dragging it, and tapping the map beside it, still move the pin.
- The map was removed the moment the dialog began to close, so the dialog's body collapsed while it faded. The map
  now stays until the dialog has left.
- On a phone the failure's alert grew to fill the dialog, and with a first fix squashed to a sliver, because a
  Vuetify alert sets its own flex size and the dialog's body is a column. The alert sits in a block of its own now.
- The failure still said "Tap the map to place the pin" under the message. With no map, that line is gone.
- The sentence on the hotspot and the warning about decimals sat tight under the field's hint and read as more of
  the hint. They have more room above.
- The keyboard could still rotate the map (shift with the arrow keys); that is off now too.
- Looked at and kept: "Use this point" with no pin is dim, as every disabled button is; the line under the map says
  what to do.
- Looked at and kept: the map is light on the dark theme. It is the map's own style, and the library's attribution
  stays as it draws it.

The Mounting page's way in (checked in fake mode at 375 and 1280 px wide: the place in use's card with the notice of
last time's values, its panel with a running and two ended deploys, and the deploy review's result after a deploy back
to a place used before):

- Looked at and kept: at 375 px "Correct heading" on an ended deployment drops under its line, which now carries the
  height and the tilt too; on a running one, "Mounting" still fits beside "Facing SE (120°)", since a move records none
  of the four.
- Looked at and kept: the card's notice is a tonal warning inside the card, so it reads as part of the place in use,
  and its Mounting button is outlined, as the deploy result's is; the place's own panel has the filled one.

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
- OpenStreetMap's own tiles: its usage policy is for light use, not for an app that every install's phones would
  ask. The install names a source in the manifest, which a site can change.
- An address search on the map: it would send an address, which is exactly what a private place is, to a search
  service. A pin picked on the map needs nothing typed.
- Tiles kept on the device for offline use: the unit would store and update a map, on a card that is for its data,
  to serve a page used a few times; and a phone with no internet can type or paste a point.
- A map on the hotspot: the phone has no internet there, so the map could only fail. One sentence says so instead.

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
| | 192.168.1.57, ..| | Fallback | |  Hotspot: its name, or "Hotspot off"; under the name, the
| |                 | | only. ...| |  fallback line while the unit is on a Wi-Fi network
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
- The summary is two lines at most (the fallback line may wrap in a narrow column): the unit's `.local` name, then the addresses in use (the cable's when it is
  connected, the Wi-Fi's when it has one), then for Hotspot its name or "Hotspot off". Hotspot's second line is the
  fallback line ("Fallback only. This unit is on HomeNet.", grey like This device's addresses), shown only while the
  unit is on a Wi-Fi network and the hotspot is on, because then the hotspot isn't on air and the name alone reads as if
  it were. A unit without a hotspot has no panel, only the sentence that says so.
- Open, the Hotspot panel then starts with one grey sentence on when the hotspot would start and how the unit gets
  back to a network (`fallbackNote` in `summary.ts`; the 5 minutes is `tm-network-retry`'s timer, and the minute is
  NetworkManager's, measured at about 75 seconds). It is grey text, not a `v-alert`, and it neither opens the panel nor
  sets its warning mark: it describes how the unit normally works, and an alert on this page means something needs
  doing.
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

### Sharing

The page says what the device uploads and to which server, for everyone signed in, and lets an admin change it. It is
built from conventional Vuetify parts and no CSS beyond spacing (and one `scroll-margin-top`, as the Device page has,
so the Status page's "Check the token" link doesn't land under the app bar).

- **Where the state lives.** `SharingPage` reads `GET /sharing` and holds the answer. It passes it to `SharingForm`
  as a prop. The form copies it into its own fields (server, host, protocol, port, three boxes, "I've read the
  notice") and sends them with `PUT /sharing`; the API's answer goes back up as `saved` and replaces the page's copy.
  The form starts its fields again from the state only when the saved choices change, not when the token's state or
  the server's answer does, so a host typed before the token job finishes isn't lost.
- **The rules for the boxes are in one place, `SharingForm`.** Each box is its own `ConsentBox`, never ticked unless
  the saved state says so, never bundled. A box that can't be ticked says why in a line under it ("Set the access
  token first.", "Turn on Share data first.", "The exact location is only sent over https.", "Not live yet."). A box
  that is already ticked is never disabled, so a choice can always be withdrawn where it was given: untick it and save.
  Unticking Share data unticks the other two. Changing the server unticks the exact location and the map (the choices
  were made for the old server) and asks first, in a dialog, when either was on.
- **The notice** ("I've read the notice") is for the maintainer's server only. It is needed when the save adds
  something to what is shared: Share data turned on, the server just changed to the maintainer's, or a choice newly
  ticked while the notice has changed since it was read; Save stays disabled until it is ticked. A save that only keeps
  or withdraws choices never needs it, so an admin can withdraw under a changed notice without reading it. While the
  notice has changed and Share data is on, the box is offered anyway (never pre-ticked), because ticking it is how
  the grants are recorded under the new version and the Status warning clears. The page sends a notice version only
  with the box shown and ticked.
- **The summary card** is the saved state, not the form: it says what is shared, with which server, how the server
  last answered (in the Status check's words, shorter), and, while sharing is on, which location is sent. Viewers see
  the card and one sentence. After a save that leaves the upload on, the page reads the state again every 5 seconds
  for up to a minute while the server's answer is `waiting` or `unknown`.
- **Two Save buttons.** The token has its own (`EnteredSecret`'s `saveText`, "Save token"; it saves the token through
  the secrets API and restarts Node-RED), and the form has "Save" for the server and the choices. The token's form
  also sits in a bordered sheet so the two read as separate.
- **Polling is quiet.** A failed check while the page waits for the first upload stops the checking and shows nothing,
  because the form above still works; only the page's first read shows an error.
- **Download your data.** The card is the first on the page and only admins see it. It's a `StatusCard` so it looks
  like Saved settings below it: the size is the card's one item (none when the device can't say), and the box, button,
  message, and note sit in its slot. The question is a `ConfirmDialog` with a primary button rather than a warning
  one, because a download changes nothing on the device. Unticked, Download asks `POST /sharing/download`; ticked, it
  asks `POST /surveys/database-copy`. The tick, the message, and "started" are the card's own state, so the page reading
  its state again (after a save, after "I've reviewed this") changes none of them. Once a download has started,
  Download and the box stay off until the page is reloaded, because each download makes a full copy of the database on
  the device. In fake mode the answered link points at `/storefiles`, which the dev server doesn't serve, so nothing
  downloads.

#### What the screenshot review changed

The page was checked in fake mode at 375 px and 1366 px wide, as an admin (a new device, the token set, Share data and
the exact location ticked with their examples open, the saved state, the own-server fields, and the question about
changing the server) and as a viewer.

- The card was titled "What this device shares", the same as the section of boxes below it. It is "Saved settings"
  now, which also says that it shows what is saved, not what is ticked.
- The token's field and its Save sat in the page's flow, so the token's Save and the form's Save read as one pair. The
  token is in a bordered sheet, and its button reads "Save token".
- The Protocol drop-down had Vuetify's underlined style next to the outlined text fields. It is outlined.
- "I've read the notice" was 8 px left of the other checkboxes (a negative margin copied from the license page). It
  lines up with them now.
- The "Saved." line disappeared at once when the saved state came back with a normalised value (the form started again
  from it and counted that as an edit). It waits for the form to settle.
- Looked at and kept: the reason line under a disabled box is in normal text, not the secondary color, because it is
  the instruction a person needs; the boxes' text wraps to five lines at 375 px, which keeps the words the plan asks for.
- Looked at and kept: a viewer sees the card and one sentence, with no empty space where the form would be.

The first-run step and the Location page's "Exact locations" were checked the same way, in fake mode at 375 px and
1366 px wide (setup with and without a token; the section and its confirmation on the Location page). What changed:

- With no token, "Not now" was a text button with the text button's inner padding, so it sat 20 px right of the
  paragraph above it, as the only thing on the step. It is a filled button then, and an outlined one under the form's
  "Save and finish", so the two never look alike.
- Looked at and kept: the Location page's Precision paragraph still says a later update will export the database with
  each place's exact location. The new file lists the places, not the database, so the sentence is still true.
  (Since changed: the database copy now exists, and the paragraph points at Download your data on the Sharing page.)
- Looked at and kept: the export confirmation uses the primary colour, not the error colour used for deletes.

#### Defaults rejected

- Switches instead of checkboxes: a switch reads as taking effect at once, and nothing here does until Save.
- One "I agree" box for all three choices: each choice has its own box, with its own example and its own withdrawal.
- A tooltip for each example: a phone has no hover. The example opens under the box, in the page's flow.
- The notice in a dialog: a long text in a dialog scrolls twice on a phone. It opens in place, in the license page's
  box.
- Polling for as long as the page is open: the first upload takes a minute at most, and a page left open on a unit
  with the server down would ask every 5 seconds for ever.
- A progress bar or polling for the download: the device doesn't report progress, and the browser's own download list
  shows the transfer once it starts. The note says what to expect instead.
- A link in the note for the download: the address is good for ten minutes, and a link left on the page would let a
  later click start another copy. The page opens it once and keeps no link.

### Software update

For admins only. The page answers "is there a newer version, and can this unit take it from here", starts the update,
and then follows it while the unit builds, switches, and perhaps restarts. The person may be on the unit's hotspot,
where the page loses the unit for minutes during the switch, so the page has to stay calm about that and keep the
last thing it knew on screen. It is built from conventional Vuetify parts and no CSS beyond spacing. The page decides
nothing: the device answers with codes (`relation`, `status`, `reason`, stage ids), and `words.ts` and the page put them
into words.

```text
+----------------------------------+
| Software update             (h5) |
| Traffic Monitor 0.8.0 · Stable · |  ", modified" after the commit
| commit 2da617a                   |  for a changed copy
|                                  |
| Updating to 0.8.1           (h6) |  while a run goes on (or a start
| (i) The device isn't answering...|  is pending): only when lost
| (v) Download                     |
| (v) Check                        |
| (o) Prepare           (spinner)  |
| ( ) Build                        |  the known stages still to come,
| ( ) Restore point                |  in the secondary color
| ...                              |
| You can close this page. The     |
| update carries on.               |
|                                  |
|   or, after a run:               |
| The update didn't start     (h6) |  only after a start the device
| (x) Another install or update... |  refused; the run's ending stays
| Last update                 (h6) |
| (x) The new version's images     |
|     didn't build, so nothing ... |
|     Detail: ...                  |
| (v) Download ... (x) Build       |  the stages as they ended
| [Try again]                      |  or Finish the update, or Reload
|                                  |
|   when no run goes on:           |
| Channel                     (h6) |
| (o) Stable releases              |
| ( ) Development (newest, can     |
|     break)                       |
|     A device on Development goes |
|     back to Stable only when ... |
| [Check for updates]  Last checked|  filled until another button is
| Checking asks GitHub. Nothing is |  the main one
| sent until you press it.         |
| (x) GitHub could not be reached..|  a failed check, beside it
| Version 0.8.1 is available.      |  or up to date, newer, or "update
| Released Nov 20, 2026            |  it with the installer" + docs link
| Before you start            (h6) |  only for an offer that is ahead
| (x) Plate Recognizer add-on      |  the checks, with the Status
|     ... Run the full installer...|  page's marks (CheckList)
| The update saves the settings as |
| a restore point. It doesn't save |
| the counted data: download the   |
| database first.                  |
| [Update to 0.8.1]                |  disabled while a check fails
| +------------------------------+ |
| | Log                       v  | |  folded; loaded when opened
| +------------------------------+ |
+----------------------------------+
```

- **Nothing goes online by itself.** Opening the page reads `GET /update`, which never asks GitHub. Only Check for
  updates does (`POST /update/check`), and the hint under the button says so. The device allows one check a minute; a
  second one inside the minute is a 429, and its message (with the wait) shows in an error alert under the button, as
  does any other failed check.
- **The channel** is two radio choices, preselected from the installed channel each time the device names one. The
  sentence about going back to Stable sits under the Development choice, lined up with its label, as plain secondary
  text (not inside the radio's label, where the radio button sat centred on four lines at 375 px). A check asks about
  the chosen channel, and an offer shows only while its channel is the one chosen, so "Update to 0.8.1" never sits under
  Development.
- **The offer** is worded by its relation: "Version 0.8.1 is available." with the release date in the secondary color
  (Stable), "12 changes since this version are available (commit 6666666)." (Development; "1 change ... is"), "This
  device is up to date.", "This device is newer than the latest release.", or, for histories that split and a commit
  GitHub doesn't know, "This device can't be updated from here. Update it with the installer." with a link to the
  docs' update page. The update button names the target: "Update to 0.8.1", or "Update to commit 6666666".
- **Before you start** shows only for an offer that is ahead: the API's `checks` drawn by the Status page's
  `CheckList` (its marks, title, detail, and hint), then the sentence about the restore point with a link to the
  Sharing page (`/sharing`), whose Download your data card gives the database. With no checks the heading stands alone above that sentence. The
  update button is disabled while `can_start` is false (any check is an error); a warning doesn't block it.
- **One main button.** Check for updates is filled until another button is the one to press: Update to ..., the last
  run's Try again or Finish the update, or Reload. Then it is outlined.
- **The start asks first** (`ConfirmDialog`, in the primary colour: it isn't a delete), with the time it takes and that
  the unit stops for a few minutes and may restart. It posts the offer's channel and commit and nothing else. A refusal
  (an old check, another update) shows the API's message under the button.
- **While it runs** the controls for a new check and start are hidden, because the device would refuse a start anyway,
  and the run takes their place right under the installed line. `RunProgress` lists `run.stages` in the file's order:
  done (the Status page's tick), running (a small spinner), and, after the current stage, the stages a run still goes
  through as not started, in the secondary color. `reboot` isn't among those: the unit restarts only when the installer
  asks, so listing it would say it will. A stage this version doesn't know shows by its id, and then nothing is listed
  as to come. A run the device reads over an older run's final file has no stages; it shows "An update is running."
  with no list, and an unreadable one says the page can't read its stages and points at the log.
- **Losing the unit is expected.** `useUpdate()` asks every 3 seconds while `run.status` is `running` or a start is
  `starting` (fake mode answers a start with the run itself), and gives up on one ask after 8 seconds. An ask that
  fails, times out, or gets an error answer while it follows a run is not an error: the last stages stay, an info
  alert says the unit isn't answering and that this is expected, and the page keeps asking. The first answer that
  arrives clears it. Only a failed first load is an error (with Try again).
- **The end replaces the progress in the same place,** under "Last update": a success alert "Updated to 0.8.1.", an
  error alert with the reason's words, the `detail` as "Detail: ...", and the docs or Status page link where the words
  call for one, or a warning for a run that a restart or power cut stopped ("Nothing was changed." when it stopped
  before the switch) or cut off in the switch. The stages show as they ended, with the unfinished one marked failed
  (a cross) or stopped (a triangle); after an update that ended ok they would only be a column of ticks, so they don't.
  Try again (asks first, like the start) and Finish the update (doesn't ask: it carries on a switch that was already
  confirmed) post the run's own target, `retry`, and show only when the device gives one. After an update that ended
  ok while the page was open (the page saw it running), "This page is from the version before." and Reload. A start
  the device refused (`started.status` `failed`) is newer than any run, so it comes first, under "The update didn't
  start", and stays until the next start or a restart of the control app; the page has no Dismiss for it. It shows above
  the last run's ending, never in its place: a refused Finish the update or Try again must leave that button (and the
  run's stages) where they were, or the switch could no longer be finished from the page. With no run, it stands alone.
- **The log** is one expansion panel at the end, its title inside the `h2` as on the Device page, folded on every visit
  and loaded each time it is opened (`GET /update/log`), with Refresh and a Copy button. The run's own log comes first,
  then the two units' journal lines after a blank line, in one bordered box in Vuetify's monospace class that scrolls
  past 360 px and wraps long lines, so nothing scrolls sideways at 375 px.
- **Reason words** (`words.ts`) are one sentence and the next step where there is one, and never the code. The four
  that need the installer end "Update it with the installer." and link the docs' update page; `switch_failed` and
  `health_failed` say the unit may be on the new version and link the Status page. A code this version doesn't know
  reads "The update failed. The log below has the details."

#### What the screenshot review changed

The page was checked in fake mode at 375 px and 1366 px wide: before a check, the Development offer, the Stable offer
(checked in the page), the start's question, a Stable run to its end with the page open and the page opened after it, a
Development run to `build_failed` with the log open, and a second check inside the minute. With the page's answer
replaced: up to date, newer, histories that split, a blocking check and a warning, the unit not answering in the
switch, a run cut off in the switch, one stopped in Build, `health_failed`, a start refused as busy, a run read over an
older run's final file, and one the page can't read.

- "Channel" was the radio group's own small grey label, indented 16 px from the text above it. It is a section heading
  (`h2`) now, as on the Sharing page, and the group takes it as its accessible name.
- The sentence about going back to Stable was part of the Development radio's label, so at 375 px the radio button sat
  in the middle of four lines. It is a line of its own under the choice, lined up with the label.
- A Development offer one commit ahead read "1 changes ... are available". It reads "1 change ... is available".
- The result of a run had no heading, so a page opened days later showed an alert with nothing to say it was about the
  last update. It is under "Last update" now, and a refused start under "The update didn't start", above it.
- With a run cut off or failed, Check for updates and Finish the update (or Try again) were both filled. Check is
  outlined whenever another button is the one to press.
- Looked at and kept: in fake mode, after a Stable run ends ok, the page still offers 0.8.1, because the fake unit's
  version doesn't change and the control app doesn't restart. On a unit the control app restarts in the switch and
  forgets the check, so the offer is gone.
- Looked at and kept: fake mode writes every stage of a failed run as finished, so its list is all ticks above the
  error. A real run's failing stage has no finish time and shows the cross (checked with a stubbed answer).
- Looked at and kept: the wait after a second check inside the minute reads "Wait a little before checking again. Wait
  19 seconds before the next try." The first sentence is the API's, the second the client's (`messageOf`), which every
  page shares.

#### Defaults rejected

- A progress bar or percentage for the run: the stages take very different times (Build can take half an hour), so a
  bar would stall and jump. The list of stages says where it is.
- A stepper (`v-stepper`) for the stages: its header doesn't fit 375 px, and a run's stages are a list that a later
  version can add to.
- A red error while the unit is away: that is the switch working as it should.
- A toast for "Update started" or the end: the run's own section says it, where the button was.
- Checking for updates when the page opens: the person decides when the unit talks to GitHub.
- A Dismiss for a refused start: the device keeps it until the next start, and a page that hid it would show it again on
  the next visit.
- A switch for the channel: a switch reads as taking effect at once, and the channel only says what the next check asks
  about.

### The home button

The apps nginx proxies (Dashboard 2.0, the legacy dashboard, Frigate, the Node-RED editor, and the camera feeds) have
no way back to the control app, and in a phone's sign-in window there's no address bar to retype it in. So nginx adds
one script line to each app's page, and the script draws a button that links to `/`. The nginx side is described in
[tm-control](../../docs/development/tm-control.md#the-home-button).

- **Size.** A round button 40 px across, with a touch target of 46 px (the link's own box plus 3 px on each side that
  take the press). A window under 600 px wide is narrow, and there the button is the icon alone; wider, it's a pill
  with the icon and the device's name, cut with an ellipsis when the name is long. Resting at 60% opacity, it goes solid
  on hover, focus, or touch. It stays 8 px inside the window and clear of a phone's notch and home bar.
- **Two edges.** A drag (a movement of more than 8 px; less is a press, which goes home) ends with the button on the
  left or right edge, whichever is nearer, at the height it was dropped. A button that can rest anywhere
  tends to end up over the middle of a page, and the tuck needs an edge to go to anyway. Its starting spot is the
  bottom right in every app, except Frigate on a narrow screen, where it starts higher on the right edge so it clears
  Frigate's bottom bar.
- **Tuck instead of remove.** Dropping the button within 12 px of an edge, or pressing Escape while it has focus,
  shrinks it to a thin handle that stays on the edge. Pressing the handle brings the button back. There's no setting that
  removes it for good, because once it's gone there is nowhere inside another program's page to offer "show it again".
  Each app's side, height, and tucked state are kept in one `localStorage` entry, `tm-home-button`, keyed by the
  app's path (`dashboard`, `frigate`, `ui`, `nr`, `feeds`). Storage that is missing, refuses writes, or holds something
  unusable means the defaults, quietly.
- **Shadow root.** The button lives in a shadow root, so an app's styles can't change it and its styles can't leak
  into the app. A page that is embedded in another page (a stream inside a dashboard) gets no button, and nothing is
  drawn when printing. The icon is the house from `@mdi/js`; the project's logo, which is the control app's favicon,
  doesn't read as "home" at 20 px.
- **Colors.** The device's `background`, `header_text`, and `body_text` colors (the last for the name), with the control
  app's defaults until the device answers (or if it doesn't).
- **The name.** The script asks `GET /api/v1/system/device` after it draws the button. With an answer, the button shows
  the name and the tab's title becomes `tm-01 · <the app's own title>`, kept in place when the app changes its title
  (Frigate does on every view). Without one, the button is the icon alone and the title is untouched.
- **After a drag.** The click that ends a drag is swallowed once, and only if it comes straight away (Enter on the
  focused link makes a click of its own, later). A hover with no button down cancels a drag whose release was missed.

What was considered and rejected:

- A full-width bar on top of every app. Frigate and the Node-RED editor size themselves to the full window, so a bar
  pushes their bottom edge off the screen. Avoiding that means wrapping each app in a frame, which hides the app's real
  address; bookmarks, the return-after-login link, and the sign-in window's downloads all depend on it.
- Each app's own hooks. The Node-RED editor can load an extra script and the dashboards can carry a link, but Frigate
  and go2rtc offer nothing: three mechanisms, a change to the flows, and two apps still without a way home.
- A service worker that adds the button in the browser. Service workers need HTTPS, and the device serves plain HTTP.
- The device's name written into the page by nginx, which is one more copy made at install and stale after a rename.
- A hand-written script beside nginx's static files: no type check, and its tests would need a setup of their own.
