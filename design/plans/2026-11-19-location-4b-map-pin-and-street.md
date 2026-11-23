# Location 4B: the map pin and the street, stored on the device

> **Note, 2026-11-23:** after the build, the street-data setting (`tmsetup_map_overpass_url`) was taken out of the map pin's pull request, because the second step (the street) is on hold. Its street data came from public Overpass servers, which are run by volunteers and at capacity, and the step waits for a source this project runs itself. The tasks below stay as the record of what was built, so they still name that setting.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An admin sets a place's exact spot on a map. Nothing is sent anywhere. The street step is Part B's.

**Architecture:**
- The phone's browser fetches the map and the street data from two outside hosts, both install settings. The device itself fetches nothing. With no internet (the device's own hotspot), the page falls back to today's form: typed or pasted coordinates, and no street step.
- The map library is loaded only when a map dialog opens (the UI's first lazy chunk). Every outside request goes out with no Referer and no credentials, and none is made before the admin presses a map button.
- Nothing here reads, writes, or shows a sensor's bearing, heading, or mounting. Those are planned as a form of their own, and this plan stays clear of it (Decision 9).

**Tech Stack:** Vue 3 + Vuetify 3 + TypeScript + Vite (Vitest, jsdom), MapLibre GL JS 6.x (one new runtime npm package, BSD-3-Clause, with its own types), Python 3.11 (FastAPI, pydantic 2; no new dependency), Ansible role `tmsetup` (two vars, one manifest section), Material for MkDocs, the dev-Pi tooling (`script/devpi/tmdev.py`).

**Spec:** the location and survey-id design (not yet published; the public record is the privacy design, `design/specs/2026-10-26-location-privacy-design.md`, from PR 260, and [issue 349](https://github.com/glossyio/traffic-monitor/issues/349)), section 7 (the map pin), as amended on 2026-11-19: the "Changed 2026-11-19" note in that section, open question 2, and the alternatives dated 2026-11-19. Section 9 (the block) is Part B's. The stub issue is [#349](https://github.com/glossyio/traffic-monitor/issues/349). "Decisions" below restates what the maintainer decided that day. Read the design with this plan. Where this plan goes beyond the design, say so in the PR rather than picking silently.

**Status:** written 2026-11-19 against `feature/exact-database-copy/325` at `1325f43`, the head of [PR 326](https://github.com/glossyio/traffic-monitor/pull/326), which merged into `dev` on 2026-11-20 as `575c5200`. Revised 2026-11-20: no bearing is read. Base: `dev`. Part A was built in this pull request with maplibre-gl 6.16.0 and nginx's `.mjs` type; Part B was revised and is not started. Two stacked PRs from this one plan: PR 1 is Tasks 1 to 3 (the map and the pin), branch `feature/location-map-pin/<issue>`; PR 2 is Tasks 4 to 8 (the street), branch `feature/location-street/<issue>`, off PR 1's branch. One public stub issue, [#349](https://github.com/glossyio/traffic-monitor/issues/349), covers both; PR 1 says "Part of", PR 2 closes it. Open PR [344](https://github.com/glossyio/traffic-monitor/pull/344) also edits `docs/use/location.md`; expect a small merge there.

**Size:** Part A only: the plan's estimate was about +1,000 lines, more than a third of it tests; it was built at 45 files, +2,262 and -38 lines (`git diff --shortstat 575c5200..HEAD` without this file), because the map's region and the review fixes came on top of the picker. To maintain afterwards: one runtime UI package that releases often (Dependabot groups its minor updates monthly), and two outside hosts that are install settings.

**Decisions** (the maintainer's are marked with the date; the rest are calls, open to change):
5. **OpenFreeMap with MapLibre GL (maintainer, 2026-11-19),** replacing the Leaflet choice of 2026-11-13. OpenStreetMap's own tile servers refuse requests that carry no Referer, so they would learn the device's local address; OpenFreeMap has no such rule.
6. **The two sources are install settings (maintainer, 2026-11-13):** role vars, the manifest, the API. Never an admin form. Empty turns that part off.
7. **No map without internet, and no pre-loaded tiles (maintainer, 2026-11-19).** On the hotspot the map buttons are replaced by a sentence. Typed coordinates with fewer than four decimal places get a warning, never a refusal: a location is optional, and a rough one is allowed.
9. **No bearing and no pose (maintainer, 2026-11-20).** How each sensor is mounted and where it points are planned as a form of their own, designed and not built, so nothing in this plan reads, writes, or shows a bearing.

The other decisions are about the street and come with Part B.

**Where the code stands that this plan touches** (read at `1325f43`, which is what `dev` got from PR 326):
- Role: `script/ansible/roles/tmsetup/vars/main.yml` has `tmsetup_sharing_maintainer_host` and `tmsetup_sharing_public_map_live`; `tasks/tm-control_service.yml` builds the manifest in a `set_fact` headed "Must match tm-control's Manifest model" (its `sharing:` part is the pattern), and `templates/tm-control/manifest.json.j2` is one line that dumps it.
- `tm-control/backend/tm_control/core/manifest.py`: `SharingInfo` and `NetworkInfo` are frozen dataclasses with defaults; `Manifest` gives each a default, so an older manifest loads. Unknown keys are ignored.
- `modules/location/router.py`: `PlacesState` (built by `_state()`, returned by `GET /surveys` and `PUT /surveys/precision`), `SurveyOut` (built by `_survey_out(survey, precision, usage)` and `_one(app_state, survey, ask_nodered)`), `_place`, `_pair`, `_invalid`, `ApiError`, `Audit(app_state.state).record(admin.id, "survey.<action>", place.id)`, `app_state.reconcile_lock`. Every route is `Depends(require_admin)`.
- `modules/location/places.py`: `Places` (the store), `Survey`, `Bearing`, `_surveys`, `_writing`, `rename_sensor`, `set_point`, `update_planned` (deletes and re-inserts the place's bearing rows). `modules/location/coordinates.py`: `exact()` (five places, `EXACT_PLACES`), `BEARINGS` (`n, s, e, w, ne, nw, se, sw`; blank means not set).
- `core/state.py`: `MIGRATIONS` has four entries; `tests/test_state.py` has one test per migration.
- Tests: `tests/fixtures/manifest.json` is also fake mode's manifest (`core/settings.py::FAKE_MANIFEST`). `script/tests/test_tm_control_install.py` has `collected_manifest()`, `rendered_manifest()`, `test_the_manifest_carries_the_sharing_values`, and `test_manifest_has_the_same_fields_as_tm_controls_fixture`, which needs the fixture's key paths to equal the rendered manifest's. `tests/test_settings_and_manifest.py` has the fixture and older-manifest tests. `tests/test_api_sharing.py::map_live` shows how a test swaps a manifest section (`dataclasses.replace`, `manifest.model_copy`). `tests/test_api_surveys.py` has the helpers `admin`, `places`, `survey`, `create`, `deploy`, `first_place`, `audit_rows`, `file_data`, `backups`.
- API files: `PYTHONPATH=tm-control/backend python -m tm_control dump-openapi > tm-control/ui/src/api/openapi.json`, then `(cd tm-control/ui && npm run api:generate)`. `tests/test_openapi_document.py` fails when the JSON drifts; nothing checks `schema.d.ts` but the build.
- UI, `tm-control/ui/src/modules/location/`: `LocationPage.vue` (loads `GET /api/v1/surveys`, hosts every dialog, the place panels with their button row), `PlaceForm.vue` (one "Coordinates" text field, `parsePair`, the geolocation button on a secure page, the line "A map pin is coming in a later update."), `CorrectDialog.vue` (its own copy of the field; `FAR_KM = 1`), `PlaceDetails.vue`, `DeployReview.vue`, `coordinates.ts` (`parsePair`, `formatExact`, `distanceKm`, `BEARINGS`, `bearingTitle`, `startingBearings`).
- UI elsewhere: `stores/session.ts` (`useSession()`; `session.status?.hotspot` is set when the page came over the hotspot), `components/HotspotNote.vue`, `api/client.ts` (`api`, `ApiError`, `messageOf`). No lazy loading exists yet: no `import()`, no `defineAsyncComponent`. `vite.config.ts` has no build options; Vitest runs in jsdom with `tests/setup.ts`.
- UI tests: `tests/mount.ts` (`mountAlone`, `mountApp`, `dialogText`, `dialogField`, `dialogButtons`, `clickInDialog`, `typeInto`), `tests/fake-api.ts` (`fakeApi`, `json`, `apiError`, `api.sent`), `tests/place-form.spec.ts` (line 138 asserts the placeholder), `tests/correct-dialog.spec.ts`, `tests/location-page.spec.ts` (`PLACES`, `IN_USE`, `PLANNED`, `USED`), `tests/coordinates.spec.ts`.
- nginx listens on port 80 only, and on the hotspot the device's DNS answers every name with the device, so an HTTPS request to an outside name from the hotspot is refused at once.
- Device tests: `script/devpi/tests/test_web.py` (`test_surveys_needs_an_admin`, the list of Location write paths a viewer is refused), `devpi_checks.py::places_state`.

## Global Constraints

- **Outside requests.** No request leaves the device's own origin until an admin presses a map button. After that, requests go only to the host of `map.style_url` (and the hosts its style names). Every one carries `referrerPolicy: 'no-referrer'` and no credentials. The control app's backend makes none.
- **No bearing, no pose.** No code in this plan takes a sensor's bearing as an input, and none changes `survey_bearings`, the place form's bearing fields, the deploy review, **Modify deployment**, or **Correct bearing**.
- **No location stays the default.** Nothing in this plan requires a place to have coordinates, and a typed coordinate is never refused for having few decimal places.
- No coordinate in any fixture, commit, PR text, or screenshot other than the docs' example `45.52252, -122.69120`, its neighbourhood, the fixtures' `45.0, -122.0`, and the time-zone cities tzdata lists. Survey ids in fixtures are the ones the existing tests use.
- The two sources are read from the API (`PlacesState.map`), never written into a component. A source that is not `https://` is off.
- `maplibre-gl` is imported by `PinMap.vue` and by nothing else, so it stays out of the entry chunk. Its version is pinned exactly; `package-lock.json` is regenerated with npm 11 (`npx -y npm@11 install --package-lock-only`).
- UI work follows `tm-control/ui/README.md`: conventional Vuetify, the one dark theme, system fonts, 44 px buttons, results beside the form, no toasts, sentence case, a dialog that starts over each time it opens and is named by its title. Each UI task's implementer loads the `frontend-design` skill and works test-first; the README's rules win over the skill's taste. New design notes go in the README.
- The API files are regenerated in the same commit as any model change.
- Every commit ends with the trailer block from the repo's `CLAUDE.md` (Assisted-by / AI-Model / AI-Effort / AI-Role); never `Co-Authored-By`. Docs follow "Writing docs" in `docs/development/contributing.md`; `mkdocs build --strict` passes. Nothing public names a device, a bench site, or where the block rules came from beyond "the public map's", and nothing public says more about the planned mounting form than this plan does.
- On a dev Pi: Frigate's detection, snapshots, and recording stay off; no item in this plan needs them.
- Off-device checks before each commit, from the repo root in the dev venv: `python -m pytest container/node-red-tm/schema/tests script/tests tm-control/backend/tests`; for UI tasks also the pinned Node image's `npm ci && npm run build && npm test`; for docs tasks `~/.venvs/tm-docs/bin/mkdocs build --strict`.

## Review Focus

1. **The map doesn't load:** the dialog says so and offers Try again; nothing is saved. Test in Task 3 (`a map that never loads says so`).

---

# Part A: the map and the pin (PR 1)

### Task 1: The map library, and proof that both hosts answer a browser

**Files:**
- Modify: `tm-control/ui/package.json`, `tm-control/ui/package-lock.json`
- Modify: `tm-control/ui/README.md` (the pinned-packages list)

**Interfaces:**
- Produces: `maplibre-gl` at an exact 6.x version in `dependencies`. Later tasks import it only from `PinMap.vue`.

- [ ] **Step 1: Pick the version.** `npm view maplibre-gl time --json`: the newest 6.x release at least 14 days old on the day of this task (6.17.0 qualifies from 2026-11-21). Read that version's docs and changelog for: the import form and the CSS path, `Map` options (`style`, `center`, `zoom`, `dragRotate`, `attributionControl`, `transformRequest`), `RequestParameters.referrerPolicy`, `Marker` (`draggable`, `color`, `setLngLat`, `dragend`), `NavigationControl`, `touchZoomRotate.disableRotation()`, the `load` and `error` events, and adding a GeoJSON source with a line layer. Note anything that differs from those names; Tasks 3 and 6 use them.
- [ ] **Step 2: Add it.** Pin the exact version; regenerate the lockfile with npm 11; `npm ci && npm run build && npm test` in the pinned Node image all pass.
- [ ] **Step 3: Prove the hosts, in a real browser engine** (the headless browser the screenshot reviews use), from a scratch page outside the repo that is served over plain `http://` from a non-localhost name or address, as the device's pages are:
  - a MapLibre map with `style: 'https://tiles.openfreemap.org/styles/liberty'` and `transformRequest: (url) => ({ url, referrerPolicy: 'no-referrer' })` renders, and the network log shows no `Referer` header on any request to that host;
  - `fetch('https://overpass-api.de/api/interpreter', { method: 'POST', body: new URLSearchParams({ data: '[out:json][timeout:25];way(45.51,-122.70,45.53,-122.68)["highway"];out geom;' }), referrerPolicy: 'no-referrer', credentials: 'omit' })` answers 200 with JSON that has `elements`, and its request has no `Referer`. Record the answer's size in bytes.
- [ ] **Step 4: Commit** ("Add MapLibre GL for the Location page's map").
- [ ] **Step 5: Stop and report to the maintainer:** the version, both results, the answer's size, and the API notes from Step 1. If either host refuses a request with no Referer, stop here: the choice between another host and sending the device's address is the maintainer's.

### Task 2: The map sources as install settings

**Files:**
- Modify: `script/ansible/roles/tmsetup/vars/main.yml`, `script/ansible/roles/tmsetup/tasks/tm-control_service.yml`
- Modify: `tm-control/backend/tm_control/core/manifest.py`, `tm-control/backend/tm_control/modules/location/router.py`
- Modify: `tm-control/backend/tests/fixtures/manifest.json`
- Modify: `tm-control/ui/src/api/openapi.json`, `tm-control/ui/src/api/schema.d.ts`, `tm-control/ui/tests/location-page.spec.ts` (the `PLACES` fixture), any other spec that builds a `PlacesState`
- Test: `script/tests/test_tm_control_install.py`, `tm-control/backend/tests/test_settings_and_manifest.py`, `tm-control/backend/tests/test_api_surveys.py`
- Test: `script/devpi/tests/test_web.py`

**Interfaces:**
- Produces, role: `tmsetup_map_style_url: 'https://tiles.openfreemap.org/styles/liberty'` and `tmsetup_map_overpass_url: 'https://overpass-api.de/api/interpreter'`, under a comment that says a browser fetches them, the device never does, and empty turns that part off. The manifest gains `map: {style_url, overpass_url}`.
- Produces, `core/manifest.py`:

  ```python
  @dataclass(frozen=True)
  class MapInfo:
      """Where a browser gets the Location page's map and street data (tmsetup_map_style_url,
      tmsetup_map_overpass_url). Empty means off; the device itself fetches neither."""

      style_url: str = ""
      overpass_url: str = ""
  ```

  and `Manifest.map: MapInfo = MapInfo()`.
- Produces, `router.py`: `class MapSources(BaseModel)` with `style_url: str | None` and `overpass_url: str | None`; `PlacesState.map: MapSources`; `_map_sources(info: MapInfo) -> MapSources`, where a value that doesn't start with `https://` is `None`, and `overpass_url` is `None` whenever `style_url` is.
- Produces, fixture: `"map": {"style_url": "https://tiles.openfreemap.org/styles/liberty", "overpass_url": "https://overpass-api.de/api/interpreter"}` (the real addresses: fake mode reads this file, and the maintainer reviews the UI there; no test fetches them).

- [ ] **Step 1: Write the failing tests**

```python
# script/tests/test_tm_control_install.py
def test_the_manifest_carries_the_map_values(): ...
    # vars == rendered manifest["map"] == Manifest.map, for both keys; both start with "https://"

# tm-control/backend/tests/test_settings_and_manifest.py
def test_the_fixture_manifest_names_the_map_sources(): ...
def test_an_older_manifest_without_map_loads_with_the_map_off(): ...   # MapInfo("", "")

# tm-control/backend/tests/test_api_surveys.py  (a helper map_sources(client, style, overpass) swaps the section)
def test_places_name_the_map_sources(admin): ...            # GET /surveys ["map"] == the fixture's two addresses
def test_precision_answers_with_the_map_sources(admin): ... # PUT /surveys/precision carries "map" too
@pytest.mark.parametrize("style", ["", "http://tiles.example.invalid/style", "ftp://x"])
def test_a_map_source_that_is_not_https_is_off(admin, style): ...   # both None
def test_no_street_data_leaves_the_map_on(admin): ...       # overpass "" → style_url set, overpass_url None

# script/devpi/tests/test_web.py
def test_surveys_name_the_roles_map_sources(address, admin_session): ...   # places_state()["map"] == role_vars()
```

- [ ] **Step 2: Run them to verify they fail.** `python -m pytest script/tests/test_tm_control_install.py tm-control/backend/tests -k "map" -v`: FAIL.
- [ ] **Step 3: Implement** the vars, the `set_fact` section, `MapInfo`, `MapSources`, `_map_sources`, and the field in `_state()`. Add `map` to every `PlacesState` the UI specs build, so the build passes.
- [ ] **Step 4: Regenerate the API files; run every off-device check.** PASS.
- [ ] **Step 5: Commit** ("Name the map and street data sources in the install's settings").

### Task 3: The pin

**Files:**
- Create: `tm-control/ui/src/modules/location/PinMap.vue`, `MapPicker.vue`, `MapPickButton.vue`
- Modify: `tm-control/ui/src/modules/location/coordinates.ts`, `PlaceForm.vue`, `CorrectDialog.vue`, `LocationPage.vue`
- Test: `tm-control/ui/tests/pin-map.spec.ts`, `map-picker.spec.ts`, `map-pick-button.spec.ts` (new); `coordinates.spec.ts`, `place-form.spec.ts`, `correct-dialog.spec.ts`, `location-page.spec.ts`
- Modify: `docs/use/location.md`, `docs/use/wifi-hotspot.md`, `docs/development/tm-control.md`, `tm-control/ui/README.md`, `CLAUDE.md`
- Create: `docs/assets/images/location-map-pin.png`, `design/plans/2026-11-19-location-4b-map-pin-and-street.md`

**Interfaces:**
- Consumes: `PlacesState.map` (Task 2), `maplibre-gl` (Task 1).
- Produces, `coordinates.ts`:
  - `type LatLon = { lat: number; lon: number }`
  - `decimalsTyped(text: string): number | null`: for text `parsePair` accepts, the smaller count of digits after the dot of its two numbers; `null` otherwise.
  - `roundedTo(decimals: number): string`: `'100 km'`, `'10 km'`, `'1 km'`, `'100 m'` for 0 to 3.
  - `FEW_DECIMALS = 4` and `fewDecimalsWarning(text: string): string`: `''`, or `` `For an exact location, use at least four decimal places (about 10 m). This is rounded to about ${roundedTo(n)}.` ``
- Produces, `PinMap.vue` (the only importer of `maplibre-gl` and `maplibre-gl/dist/maplibre-gl.css`):
  - props `styleUrl: string`, `centre: LatLon | null`, and `pin` (`defineModel<LatLon | null>`);
  - emits `ready` once the map's `load` fires, and `failed` once if an `error` fires before `load` or `load` hasn't fired within `LOAD_TIMEOUT_MS = 10000`;
  - opens at `pin` (zoom 17), else `centre` (zoom 14), else the whole world (zoom 1, centre `[0, 20]`);
  - a tap sets `pin`; the marker is draggable and a drag sets `pin`; longitudes are wrapped to -180..180; values are not rounded here;
  - rotation and pitch are off; zoom buttons are on, with no compass; the attribution control is the library's own;
  - `transformRequest` returns `{ url, referrerPolicy: 'no-referrer' }` for every request; the map is removed when the component unmounts.
- Produces, `MapPicker.vue`: props `styleUrl`, `start: LatLon | null`, `centre: LatLon | null`, `open` (model); emits `picked: [LatLon]`. It loads `PinMap.vue` with `defineAsyncComponent(() => import('./PinMap.vue'))`. Full-screen below Vuetify's `sm` breakpoint, `max-width="720"` above. Exact copy:
  - title: `Pick the place on a map`
  - `` `The map comes from ${host}. Your phone asks it for the area you look at; this device sends it nothing.` `` where `host` is `new URL(styleUrl).host`
  - before a pin: `Tap the map to place the pin, then drag it to the exact spot.` With a pin: its coordinates through `formatExact`
  - buttons: `Use this point` (disabled with no pin) and `Cancel`
  - on `failed`, in place of the map: `The map couldn't load. This phone may have no internet connection. Type or paste the coordinates instead.` with a `Try again` button that mounts the map afresh
- Produces, `MapPickButton.vue`: props `map: MapSources`, `centre: LatLon | null`, and `coordinates` (`defineModel<string>`); emits `picked`. It renders, in this order of precedence:
  - nothing, when `map.style_url` is `null`;
  - on the hotspot (`useSession().status?.hotspot`), the sentence `The map needs the internet, and this device's hotspot has none. Type or paste the coordinates, or come back to this page once the device is on your Wi-Fi.`
  - otherwise an outlined `Pick on a map` button (44 px) and the `MapPicker`, started at `parsePair(coordinates)`; on `picked` it sets `coordinates` to `` `${formatExact(lat)}, ${formatExact(lon)}` `` and emits `picked`.
- Produces, `PlaceForm.vue` and `CorrectDialog.vue`: new props `map: MapSources` and `centre: LatLon | null`; a `MapPickButton` under the coordinates field; `fewDecimalsWarning` shown as one `text-warning` line under the field (never an error; Save stays enabled). `PlaceForm` no longer has the "A map pin is coming" line. `PlaceForm`'s `saved` and `CorrectDialog`'s `corrected` emits gain a second value, `onMap: boolean`: whether the saved coordinates were last set by the map.
- Produces, `LocationPage.vue`: passes `:map="state.map"` and `:centre`, the place in use's point when it has one.
- Not changed: the bearing fields of `PlaceForm.vue`, and everything else about bearings.

- [ ] **Step 1: Write the failing tests**

```ts
// coordinates.spec.ts
// decimalsTyped: '45.52252, -122.69120' → 5; '45.5, -122.69120' → 1; '45, -122' → 0; 'abc' → null; '45,5 122' → null
// fewDecimalsWarning: '45.52, -122.69' → '…This is rounded to about 1 km.'; '45.5225, -122.6912' → ''; '' → ''

// pin-map.spec.ts   vi.mock('maplibre-gl') with fake Map, Marker, NavigationControl classes that record calls
test('opens at the pin at zoom 17, else the centre at 14, else the world')
test('every request is sent with no referrer')      // options.transformRequest('https://x/y') → { url, referrerPolicy: 'no-referrer' }
test('a tap sets the pin and a drag moves it')
test('a longitude past 180 is wrapped')
test('rotation is off and the map is removed on unmount')
test('a map that never loads says so')              // fake timers: no 'load' in 10 s → 'failed' once; an 'error' before 'load' → 'failed' once

// map-picker.spec.ts   vi.mock('../src/modules/location/PinMap.vue') with a stub that can emit ready, failed, update:pin
test('names the host of the map and says the device sends nothing')
test('Use this point is disabled until there is a pin, then answers with it')
test('a failure shows the message and Try again mounts the map again')
test('Cancel answers nothing')

// map-pick-button.spec.ts
test('no map source: nothing is shown')
test('on the hotspot: the sentence, and no button')
test('a picked point is written as "45.52252, -122.69120"')
test('the picker starts at the coordinates already in the field')

// place-form.spec.ts
test('the form no longer says a map pin is coming')
test('fewer than four decimal places warns and still saves')    // '45.52, -122.69' → warning text; Save enabled; POST body lat 45.52
test('four decimal places give no warning')
test('saved says whether the map set the coordinates')          // typed → false; picked → true; picked then retyped → false

// correct-dialog.spec.ts
test('a point picked more than 1 km away still asks the second question')   // FAR_TEXT

// location-page.spec.ts
test('the dialogs get the map sources and the place in use as the centre')
```

- [ ] **Step 2: Run them to verify they fail.** `npm test`: FAIL.
- [ ] **Step 3: Implement** the three components, the `coordinates.ts` helpers, and the changes to the two dialogs and the page. The marker takes the theme's `primary` colour.
- [ ] **Step 4: Run the tests and the build.** PASS. The build's output lists a chunk that holds the map library, and the entry chunk's size is within a few kilobytes of its size before Task 1. Record both sizes for the PR.
- [ ] **Step 5: Screenshot review** at 375 px and 1280 px in fake mode: the form with the button, the picker with and without a pin, the failure message, the hotspot sentence, the warning. Fix what the review finds and record it under a "What the screenshot review changed" heading in the README, with the design notes: the first requests outside the device and why they are allowed, the library's CSS as a new exception to the CSS list, and what was rejected (OpenStreetMap's own tiles, an address search, pre-loaded tiles, a map on the hotspot).
- [ ] **Step 6: Docs.** `docs/use/location.md`: picking on a map (what the phone asks the map's host for, that the device fetches nothing, that it isn't offered on the hotspot), the four-decimals advice, and that a maps app gives coordinates with no internet; the screenshot at the example point. `docs/use/wifi-hotspot.md`: one sentence in the Phones section. `docs/development/tm-control.md`: the manifest's `map` section, the `GET /surveys` row, the lazy chunk and how its specs fake the library. `CLAUDE.md`: the manifest line. `mkdocs build --strict` passes.
- [ ] **Step 7: Commit** the code, then the docs, then this plan's public copy (`design/plans/`, its Spec line pointing at PR 260's design and the stub issue).
- [ ] **Step 8: Pi plan for PR 1,** as a logged `tmdev check` on the bench unit after `tmdev deploy <host> -- -t revproxy -t tm-control`:
  1. The device suite passes; `GET /surveys` names the role's two sources.
  2. From a desktop browser on the LAN: add a place by pin at the example point; the saved point matches at five places.
  3. The network panel: nothing leaves the device's origin until **Pick on a map** is pressed; afterwards requests go only to the map's host, with no Referer.
  4. Correct that place's location by pin to a point more than 1 km away: the second question is asked.
  5. On the hotspot: the sentence, no button, no outside request; `45.52, -122.69` warns and saves. Note whether an iPhone on mobile data could have reached the map's host from there.
  6. Empty `tmsetup_map_style_url`, deploy `-t tm-control`: no button. Restore it and deploy again.
- [ ] **Step 9: Stop for the maintainer:** the UI review, the commits, and PR 1's text (the template filled in; the release note: "The Location page can set a place's coordinates from a map. The phone's browser fetches the map; the device fetches nothing, and the map isn't offered on the device's own hotspot. Typed coordinates with fewer than four decimal places now get a warning."). Nothing is pushed before the maintainer has read them.

### Task 3a: Where the map opens when there is no place to start from (added 2026-11-20)

Asked for by the maintainer on the bench, after Task 3: with no coordinates in the field and none on the place in use, the map opened on the whole world. It now opens over the device's region, worked out on the device with no outside request.

**Decisions (maintainer, 2026-11-20):** no outside call of any kind, so no IP lookup and no boundary data from elsewhere. The region is the principal city of the device's time zone, from the Pi's own time-zone data, and the map opens zoomed well out, so a whole time zone is about in view.

**The rule:**
- The map opens at the coordinates in the field (zoom 17), else at the place in use (zoom 14), else at the device's region (zoom 3), else on the whole world (zoom 1). Planned at zoom 5; the screenshot review showed that a zone's city often sits at the zone's edge (Los Angeles is at the south end of the Pacific zone), so zoom 5 and 4 showed only part of it, and zoom 3 gives a wide view around the city, about the size of a time zone.
- The region is the time zone's city from the Pi's own time-zone data (tzdata, on every Pi): the row whose third column is the device's time zone in `/usr/share/zoneinfo/zone1970.tab` or, for a zone that table has merged away (`Europe/Amsterdam`), in `zone.tab` beside it (same three columns, one country per row; `zone1970.tab` answers first, and legacy aliases such as `US/Pacific` give none), its second column (ISO 6709, `±DDMM±DDDMM` or `±DDMMSS±DDDMMSS`) as decimal degrees rounded to two places. Example: `America/Los_Angeles`, `+340308-1181434` → `34.05, -118.24`.
- It is used only when the Wi-Fi country is known and is one of the row's countries (its first column, comma-separated). The installer sets the zone (`-z`, default `America/Los_Angeles`) and the Wi-Fi country (`US` when the device has none), so a unit left on both defaults opens over Los Angeles until its zone is set on the Date and time page, and the check keeps a zone from sending the map to a country the Wi-Fi isn't set for. The zone (`timedate` adapter) and the country (`network.wifi_country()`) are what the Time page and the Network check already read.
- No region (`null`) when: there is no map (`style_url` null), the zone or the country can't be read, the country is unset, the zone isn't in either table (`Etc/UTC`), a table is missing or a row is malformed, or the country isn't the zone's.
- The region isn't private: it is a time zone's city, `GET /surveys` is admin-only, and at zoom 3 the map's host learns little more than the phone's internet address already tells it.

**Interfaces:** `MapSources` gains `region: LatLon | null` (`{lat, lon}`, default `null`), filled in `_state` only when `style_url` is set; `_map_sources` is unchanged. `GET /surveys` and `PUT /surveys/precision` carry it. The API files are regenerated. The UI passes `map.region` down to `PinMap.vue`, which uses it only when there's no pin and no centre.

**Files:** `tm-control/backend/tm_control/modules/location/` (a small module for the region, and the router), the fake mode's clock and Wi-Fi country if it needs a region to show, `tm-control/backend/tests/`, the API files, `tm-control/ui/src/modules/location/{MapPickButton,MapPicker,PinMap}.vue` and the two forms if they pass the map down, `tm-control/ui/tests/`, `docs/use/location.md`, `docs/development/tm-control.md`, `tm-control/ui/README.md`, `CLAUDE.md`.

- [ ] **Step 1: Tests first.** Backend: the ISO 6709 parse (both forms, both signs); `America/Los_Angeles` with country `US` gives `34.05, -118.24`; `Europe/London` with `US` gives none; country `""` or unreadable gives none; `Etc/UTC` gives none; a missing file and a malformed row give none and don't raise; `GET /surveys` carries `map.region`, and `null` when the style URL is empty. The file's path is a parameter, so the tests use a small hand-made file. UI: with no pin and no centre, the map opens at the region at zoom 3; a centre wins over the region (zoom 14); a pin wins over both (zoom 17); with no region, the whole world at zoom 1.
- [ ] **Step 2: Run them to verify they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests and the build.** Record the entry chunk's size.
- [ ] **Step 5: Screenshot review** in fake mode at 375 px and 1280 px: Add a place with no place in use, so the map opens at the region. Check that the zoom shows about a time zone, and say what was chosen and why in the README.
- [ ] **Step 6: Docs.** `docs/use/location.md`: where the map opens gains the region, and that the map's server then sees the tiles of that wider area. `docs/development/tm-control.md`: `map.region` in the `GET /surveys` row. The UI README: a design note (why the time zone, why the country check, what was rejected: an IP lookup and time-zone boundaries, both outside data). `CLAUDE.md`: the Location clause's `map` gains `region`.
- [ ] **Step 7: Commit** the code, then the docs.
- [ ] **Step 8: Bench:** deploy `-t tm-control` (and `-t revproxy` for the UI) to the bench unit, check that `GET /surveys` gives its region, and open the map from Add a place with no coordinates.

---

# Part B: the street (PR 2)

Part B was revised after Part A was built. Its tasks come to this file with the second pull request.
