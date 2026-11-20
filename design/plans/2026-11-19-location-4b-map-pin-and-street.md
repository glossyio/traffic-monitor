# Location 4B: the map pin and the street, stored on the device

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An admin sets a place's exact spot on a map, the page suggests the stretch of street nearest that spot, the admin confirms it or taps another, and the device stores that pick with the place. Nothing is sent anywhere.

**Architecture:**
- The phone's browser fetches the map and the street data from two outside hosts, both install settings. The device itself fetches nothing. With no internet (the device's own hotspot), the page falls back to today's form: typed or pasted coordinates, and no street step.
- The map library is loaded only when a map dialog opens (the UI's first lazy chunk). Every outside request goes out with no Referer and no credentials, and none is made before the admin presses a map button.
- The block is found in the browser from the streets in a grid-aligned box around the pin: the street nearest the pin, followed each way to its cross streets by the public map's own rules. The browser sends the whole block to the control app. The control app trims a long block to 300 m around the pin, off-centre by a private per-place offset, and stores the result in `state.sqlite`.
- A pick is per place: one street. It remembers the point it was made for, and reads as stale ("Check your street") when the place's location changes. It never touches `config.yml`, Node-RED, or the database.
- Nothing here reads, writes, or shows a sensor's bearing, heading, or mounting. Those are planned as a form of their own, and this plan stays clear of it (Decision 9).

**Tech Stack:** Vue 3 + Vuetify 3 + TypeScript + Vite (Vitest, jsdom), MapLibre GL JS 6.x (one new runtime npm package, BSD-3-Clause, with its own types), Python 3.11 (FastAPI, pydantic 2; no new dependency), Ansible role `tmsetup` (two vars, one manifest section), Material for MkDocs, the dev-Pi tooling (`script/devpi/tmdev.py`).

**Spec:** the location design in [PR 260](https://github.com/glossyio/traffic-monitor/pull/260), sections 7 (the map pin) and 9 (the block), as amended on 2026-11-19: the "Changed 2026-11-19" notes in both sections, open question 2, and the alternatives dated 2026-11-19. The stub issue is [#349](https://github.com/glossyio/traffic-monitor/issues/349). "Decisions" below restates what the maintainer decided that day. Read the design with this plan. Where this plan goes beyond the design, say so in the PR rather than picking silently.

**Status:** written 2026-11-19 against `feature/exact-database-copy/325` at `1325f43`, the head of [PR 326](https://github.com/glossyio/traffic-monitor/pull/326), which merged into `dev` on 2026-11-20 as `575c5200`. Revised 2026-11-20: no bearing is read, and a place has one street (Decision 9). Base: `dev`. Not started. Two stacked PRs from this one plan: PR 1 is Tasks 1 to 3 (the map and the pin), branch `feature/location-map-pin/<issue>`; PR 2 is Tasks 4 to 8 (the street), branch `feature/location-street/<issue>`, off PR 1's branch. One public stub issue, [#349](https://github.com/glossyio/traffic-monitor/issues/349), covers both; PR 1 says "Part of", PR 2 closes it. Open PR [344](https://github.com/glossyio/traffic-monitor/pull/344) also edits `docs/use/location.md`; expect a small merge there.

**Size:** about 40 files, +2,200 to 2,800 lines, more than a third of it tests: PR 1 about +1,000, PR 2 about +1,500. To maintain afterwards: one runtime UI package that releases often (Dependabot groups its minor updates monthly), two outside hosts that are install settings, and block rules that must stay in step with the public map's.

**Decisions** (the maintainer's are marked with the date; the rest are calls, open to change):
1. **The pin and the block pick, stored only (maintainer, 2026-11-19).** Sending the block, the Sharing page's block-or-point choice, and the notice text are the next plan.
2. **The flow starts from an exact pin (maintainer, 2026-11-19).** The block is suggested from the place's stored point. There is no way to pick a block for a place with no location.
3. **The block is picked with the place, on the Location page (maintainer, 2026-11-19),** not on the Sharing page as the design first had it.
4. **The block record (maintainer, 2026-11-19):** a GeoJSON-ordered line (`[lon, lat]` pairs, five decimal places), the street and cross-street names, the OpenStreetMap ids it came from, how each end finishes, and the street's tags. That is what an OpenLR encoder needs; no OpenLR reference is made on the device.
5. **OpenFreeMap with MapLibre GL (maintainer, 2026-11-19),** replacing the Leaflet choice of 2026-11-13. OpenStreetMap's own tile servers refuse requests that carry no Referer, so they would learn the device's local address; OpenFreeMap has no such rule.
6. **The two sources are install settings (maintainer, 2026-11-13):** role vars, the manifest, the API. Never an admin form. Empty turns that part off.
7. **No map without internet, and no pre-loaded tiles (maintainer, 2026-11-19).** On the hotspot the map buttons are replaced by a sentence. Typed coordinates with fewer than four decimal places get a warning, never a refusal: a location is optional, and a rough one is allowed.
8. **Adjusting means tapping another street.** A pick is always one block. No dragging of ends, no pick longer than a block.
9. **No bearing and no pose (maintainer, 2026-11-20).** How each sensor is mounted and where it points are planned as a form of their own, designed and not built, so nothing in this plan reads, writes, or shows a bearing. Two things follow, and both are calls: the suggestion is the street nearest the place's point, where the public map looks along the camera's bearing; and a place has one street, where the design of 2026-10-31 gave each sensor its own. A corner unit that counts two streets gets the second one later, as a per-sensor choice on top of the place's street, the way a sensor's bearing overrides the place's.
10. **The 300 m trim is the control app's job,** not the browser's. The offset that places the pin in the window is random, made once per place, kept in `state.sqlite`, and never returned by the API. So a second pick can't shift the window, and nobody who sees the line can work the pin out from it.
11. **Street names are stored as OpenStreetMap writes them** ("Southeast Washington Street"). Shortening is the public map's job.
12. **The street lookup asks for a box, not the spot:** the pin plus 400 m each way, each edge moved outward to a multiple of 0.01°.
13. **The street step needs an exact point.** It is refused when the place's latitude and longitude both have three decimal places or fewer, because a suggestion from a rounded point would be wrong.
14. **The pick is a column on the place, `surveys.map_block`,** beside the private `surveys.map_window`. `survey_bearings` is left alone, and its `map_block_ref` and `map_side` stay unused.
15. **`stale` is worked out when the place is read,** from the point the pick remembers. No other route writes a flag. Turning the device to count another street raises no flag: the operator chooses the street again.

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

- **Outside requests.** No request leaves the device's own origin until an admin presses a map button. After that, requests go only to the host of `map.style_url` (and the hosts its style names) and, for the street step, the host of `map.overpass_url`. Every one carries `referrerPolicy: 'no-referrer'` and no credentials. The control app's backend makes none.
- **The exact point never goes to the street-data host.** The query holds a box whose edges are multiples of 0.01°. The pin's coordinates appear in no query, URL, or header.
- **Stored only.** A pick is written to `state.sqlite` and nowhere else: not `config.yml`, not Node-RED, not `tmdb.sqlite`, not any export, download, or upload. It starts no deployment.
- **Private values.** `surveys.map_window` and a pick's `made_for` are never in an API answer, a log line, an audit row, or an error message. Audit rows for this feature carry the place id only: no coordinate, no street name.
- **No bearing, no pose.** No code in this plan takes a sensor's bearing as an input, and none changes `survey_bearings`, the place form's bearing fields, the deploy review, **Modify deployment**, or **Correct bearing**. A change of bearing neither moves a pick nor marks it stale.
- **No location stays the default.** Nothing in this plan requires a place to have coordinates, and a typed coordinate is never refused for having few decimal places.
- No coordinate in any fixture, commit, PR text, or screenshot other than the docs' example `45.52252, -122.69120`, its neighbourhood, and the fixtures' `45.0, -122.0`. Survey ids in fixtures are the ones the existing tests use. Street data in a fixture is hand-built, or recorded at the example point with OpenStreetMap's attribution beside it.
- The two sources are read from the API (`PlacesState.map`), never written into a component. A source that is not `https://` is off.
- `maplibre-gl` is imported by `PinMap.vue` and by nothing else, so it stays out of the entry chunk. Its version is pinned exactly; `package-lock.json` is regenerated with npm 11 (`npx -y npm@11 install --package-lock-only`).
- UI work follows `tm-control/ui/README.md`: conventional Vuetify, the one dark theme, system fonts, 44 px buttons, results beside the form, no toasts, sentence case, a dialog that starts over each time it opens and is named by its title. Each UI task's implementer loads the `frontend-design` skill and works test-first; the README's rules win over the skill's taste. New design notes go in the README.
- The API files are regenerated in the same commit as any model change.
- Every commit ends with the trailer block from the repo's `CLAUDE.md` (Assisted-by / AI-Model / AI-Effort / AI-Role); never `Co-Authored-By`. Docs follow "Writing docs" in `docs/development/contributing.md`; `mkdocs build --strict` passes. Nothing public names a device, a bench site, or where the block rules came from beyond "the public map's", and nothing public says more about the planned mounting form than this plan does.
- On a dev Pi: Frigate's detection, snapshots, and recording stay off; no item in this plan needs them.
- Off-device checks before each commit, from the repo root in the dev venv: `python -m pytest container/node-red-tm/schema/tests script/tests tm-control/backend/tests`; for UI tasks also the pinned Node image's `npm ci && npm run build && npm test`; for docs tasks `~/.venvs/tm-docs/bin/mkdocs build --strict`.

## Review Focus

1. **The phone loses its connection part-way:** the map loaded but the street data doesn't, or the reverse. The dialog says which one failed and offers Try again; nothing is saved. Tests in Task 3 (`a map that never loads says so`) and Task 6 (`street data that fails can be tried again`).
2. **The nearest street is the wrong one:** a place at a corner, or set back from the street it counts. The dialog says the suggestion is the nearest street and how to change it, a tap picks another, and nothing is stored until **Use this street**. Tests in Task 4 (`at a corner the nearer street wins, and a tap picks the other`) and Task 6 (`Pick a different street then a tap changes the block`, `Cancel stores nothing`).
3. **A long road:** a block over 300 m, or one that runs past the edge of the street data. The stored line is 300 m, holds the pin's nearest point, and never has it at the middle; an end past the data is "unknown", not a dead end. Tests in Task 4 (`an end near the box's edge is unknown`) and Task 5 (`test_a_long_line_is_cut_to_the_window`, `test_new_window_is_never_near_the_middle`).
4. **The place changes after the pick:** the location is corrected, a planned place loses its location, a planned place is edited, a bearing changes, a camera is renamed on the Cameras page. The pick reads stale, isn't listed, is kept, and for the last two is left exactly as it was. Tests in Task 5 (`test_a_corrected_location_makes_the_pick_stale`, `test_a_place_that_lost_its_location_lists_no_street`, `test_editing_a_planned_place_keeps_its_pick`, `test_a_changed_bearing_leaves_the_pick_alone`, `test_renaming_a_sensor_leaves_the_pick_alone`).
5. **Street data that isn't what was asked for:** an HTML error page with status 200, a way with missing geometry, a way with one node, an answer cut off by the server's own timeout. No crash; the bad parts are skipped or the whole answer is a failure. Tests in Task 4 (`parse skips ways it cannot use`, `an answer that is not json is a failure`, `a cut off answer is a failure`).

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

---

# Part B: the street (PR 2)

Part B is being revised before it is built (paths and trails, and the street-data query); this copy is updated with PR 2.

### Task 4: Finding the block, in the browser *(tricky)*

**Files:**
- Create: `tm-control/ui/src/modules/location/geo.ts`, `blocks.ts`, `overpass.ts`
- Create: `tm-control/ui/tests/geo.spec.ts`, `blocks.spec.ts`, `overpass.spec.ts`, `tm-control/ui/tests/streets.ts` (hand-built networks), `tm-control/ui/tests/fixtures/streets-example.json` and `streets-example.md` (its source, date, and OpenStreetMap's attribution and licence)

**Interfaces:**
- Produces, `geo.ts` (planar maths in metres on a local projection; points are `[lon, lat]`, as GeoJSON):

  ```ts
  export type Point = [number, number]
  export function project(ref: Point, p: Point): [number, number]           // metres east and north of ref
  export function nearestOn(line: Point[], p: Point): { distance: number; along: number; segment: number }
  export function lineLength(line: Point[]): number
  ```
- Produces, `overpass.ts`:

  ```ts
  export interface Box { south: number; west: number; north: number; east: number }
  export const GRID = 0.01
  export const SEARCH_M = 400
  export function boxAround(p: Point, metres = SEARCH_M): Box    // p ± metres, each edge moved outward to a multiple of GRID
  export function inside(box: Box, p: Point, marginM: number): boolean      // at least marginM from every edge
  export function query(box: Box): string
  //   '[out:json][timeout:25];way(<south>,<west>,<north>,<east>)["highway"];out geom;'   edges printed with two decimals
  export class StreetDataError extends Error { reason: 'refused' | 'timeout' | 'incomplete' | 'network' }
  export async function fetchWays(url: string, box: Box): Promise<unknown>
  ```

  `fetchWays` POSTs `new URLSearchParams({ data: query(box) })` with `referrerPolicy: 'no-referrer'` and `credentials: 'omit'`, gives up after 30 s (`timeout`), and throws `refused` for a status that isn't 200, `incomplete` for a body that isn't JSON with an `elements` array or whose `remark` holds `runtime error`, and `network` for a failed fetch.
- Produces, `blocks.ts`:

  ```ts
  export const NEAR_M = 80, REACH_MARGIN_M = 50, TAP_M = 30
  export type End = 'cross' | 'dead_end' | 'unknown'
  export interface FoundBlock {
    street: string                 // the street's name as OpenStreetMap has it; '' when unnamed
    cross: string[]                // the cross streets' names at the two ends, in the line's order, no repeats; 0 to 2
    line: Point[]                  // the street's own nodes from one end to the other, not rounded
    osm: { way: number; ways: number[]; nodes: [number, number]; ends: [End, End]; base: string }
    tags: Record<string, string>   // the street's tags, kept keys only
  }
  export interface Network { /* the parsed ways and each node's point */ }
  export function parseWays(answer: unknown): Network
  export function blockAt(network: Network, point: Point, withinM: number, box: Box): FoundBlock | null
  export function blockName(block: { street: string; cross: string[] }): string
  ```

  `osm.way` is the way nearest the point; `osm.ways` the sorted ids of the street's ways the line runs along; `osm.nodes` the node ids at the line's first and last points; `osm.ends` how each of those ends finishes; `osm.base` the answer's `osm3s.timestamp_osm_base`, or `''`.
- The rules. Rules 1, 2, and 4 to 7 are the public map's. Rule 3 is this plan's own: the public map starts from the street a camera faces, and this plan reads no bearing (Decision 9).
  1. **What is read.** An element is used when its `type` is `way` and it has a `nodes` list and a `geometry` list of the same length with no missing point. Anything else is skipped.
  2. **A street** has `highway` in: `motorway`, `trunk`, `primary`, `secondary`, `tertiary`, each of those with `_link`, `unclassified`, `residential`, `living_street`. **A cross street** is a street, or a `highway=service` way whose `service` is not `driveway`, `parking_aisle`, `alley`, `emergency_access`, or `drive-through`. A service way is never the place's own street.
  3. **The street at a point.** Over every segment of every street, the distance from the point to the segment. The smallest wins; ties go to the lower way id, then the earlier segment. Farther than `withinM`: `null`. The suggestion asks with the place's point and `NEAR_M`; a tap asks with the tapped point and `TAP_M`. A bearing is never an input.
  4. **The street's ways** are every street way with that way's `name`; for an unnamed way, that way alone.
  5. **Walking.** From each end of the nearest segment, away from the other: at a node that a cross street of another name shares (any other cross street, when the street is unnamed), the block ends as `cross`, and its cross-street name is the alphabetically first name among those ways, if any has one. Otherwise, at a node that is not `inside(box, node, REACH_MARGIN_M)`, it ends as `unknown`. Otherwise go on to a neighbouring node of the street's ways not yet visited, the straightest when there are several; with none, it ends as `dead_end`.
  6. **`blockName`:** `` `${street} between ${a} and ${b}` ``, `` `${street} near ${a}` ``, or `street`; an unnamed street reads `an unnamed street`.
  7. **Kept tag keys:** `highway`, `name`, `ref`, `oneway`, `junction`, `maxspeed`, `surface`, `lanes`, `bridge`, `tunnel`, `embedded_rails`, and any key that starts with `sidewalk`, `cycleway`, or `parking`; at most 40, values cut to 255 characters.
- `tests/streets.ts` builds Overpass-shaped answers in code: `grid()` (three named east-west streets crossing three named north-south avenues, 100 m apart, around `[-122.6912, 45.52252]`), with options for a driveway off a block, a dead end, an unnamed street, a street split into two ways mid-block, and a 900 m road with no cross street.
- `streets-example.json` is recorded once at the docs' example point with `curl` and a User-Agent that names this project and its repository URL, for `way(around:200,45.52252,-122.69120)["highway"];out geom;`, and trimmed to the keys the parser reads.

- [ ] **Step 1: Write the failing tests**

```ts
// geo.spec.ts
test('project gives metres east and north of the reference')
test('nearestOn gives the distance, the position along the line, and the segment')
test('lineLength of a 100 m by 100 m L is 200 m, to the centimetre')

// overpass.spec.ts
test('boxAround moves every edge outward to the grid')      // [-122.6912, 45.52252] → south 45.51, north 45.53, west -122.70, east -122.68
test('the query holds the box and never the point')         // no '45.52252', no '122.6912'
test('fetchWays posts with no referrer and no credentials') // the init passed to a stubbed fetch
test('an answer that is not json is a failure')             // 200 with '<html>' → reason 'incomplete'
test('a cut off answer is a failure')                       // remark 'runtime error: Query timed out' → 'incomplete'
test('a refusal, a timeout, and a dropped connection each say which')   // 429 → 'refused'; fake timers 30 s → 'timeout'; reject → 'network'

// blocks.spec.ts
test('parse skips ways it cannot use')                      // no nodes, geometry of another length, a null point, a node, a relation
test('the street nearest the point is the block\'s street') // a point 12 m south of the middle street, mid-block
test('at a corner the nearer street wins, and a tap picks the other')   // 8 m from the avenue, 15 m from the street
test('a block runs between the nearest cross streets, with both names')
test('the line is the street\'s own nodes, never the point')
test('a driveway does not cut the block')
test('a service road is never the street but can be a cross street')    // a point 3 m from an alley still gets the street
test('a dead end is near its one cross street')             // ends ['cross', 'dead_end'], blockName '… near …'
test('an end near the box\'s edge is unknown')              // the 900 m road in a box that ends 30 m past its last node
test('a street split into two ways is one block')           // osm.ways has both ids; osm.way is the nearest one
test('no street within the distance asked is no block')     // 80 m for a place, 30 m for a tap
test('an unnamed street reads as one')
test('only the kept tags are kept')
test('the recorded answer at the example point gives a named block within 80 m of it')
```

- [ ] **Step 2: Run them to verify they fail.** `npm test -- geo blocks overpass`: FAIL.
- [ ] **Step 3: Implement** `geo.ts`, `overpass.ts`, `blocks.ts`. Nothing here imports Vue, the API client, or the map library, and nothing takes a bearing.
- [ ] **Step 4: Run the tests and the build.** PASS.
- [ ] **Step 5: Commit** ("Find the block of street nearest a place").

### Task 5: Storing the pick

**Files:**
- Modify: `tm-control/backend/tm_control/core/state.py`, `modules/location/places.py`, `modules/location/coordinates.py`, `modules/location/router.py`
- Create: `tm-control/backend/tm_control/modules/location/blockline.py`
- Modify: `tm-control/ui/src/api/openapi.json`, `tm-control/ui/src/api/schema.d.ts`, and the UI specs that build a `SurveyOut` (`block: null`)
- Test: `tm-control/backend/tests/test_state.py`, `test_places.py`, `test_api_surveys.py`, `test_openapi_document.py`; create `tests/test_blockline.py`

**Interfaces:**
- Produces, `core/state.py`, migration 5 (the next number, if another PR has taken 5 by then):

  ```sql
  ALTER TABLE surveys ADD COLUMN map_window REAL;  -- where the place's point sits in a trimmed block; private, never leaves the device
  ALTER TABLE surveys ADD COLUMN map_block TEXT;   -- JSON: the place's street and the point it was picked for
  ```

  `survey_bearings` is not touched.
- Produces, `blockline.py`:

  ```python
  CAP_M = 300
  MAX_AWAY_M = 500
  MAX_POINTS = 500
  BANDS = ((0.15, 0.40), (0.60, 0.85))  # where the point may sit in a window, as a part of its length: never the middle

  def new_window() -> float: ...
      # a fraction drawn evenly from the two bands, with the secrets module
  def stored_line(line: list[tuple[float, float]], point: tuple[float, float], window: float) -> list[tuple[float, float]]: ...
      # line and point are (lon, lat). Raises BlockLineError("too_far") when the point is more than MAX_AWAY_M from the
      # line. A line of CAP_M or less is kept whole. A longer one is cut to CAP_M, starting at
      # min(max(along - CAP_M * window, 0), length - CAP_M), where `along` is the point's nearest position on the line.
      # The result is quantised to five places with repeats dropped; fewer than two points left raises
      # BlockLineError("too_short").
  ```
- Produces, `coordinates.py`: `is_rounded(lat: float, lon: float) -> bool`, true when both equal themselves rounded to three places.
- Produces, `places.py`:

  ```python
  class MadeFor(BaseModel):      # private: the point the pick was made for
      lat: float
      lon: float
  class BlockOsm(BaseModel):
      way: int
      ways: list[int]
      nodes: tuple[int, int]
      ends: tuple[Literal["cross", "dead_end", "unknown"], Literal["cross", "dead_end", "unknown"]]
      base: str
  class Block(BaseModel):
      street: str
      cross: list[str]
      line: list[tuple[float, float]]
      osm: BlockOsm
      tags: dict[str, str]
      made_for: MadeFor
      picked_at: str
  # Survey gains: block: Block | None
  Places.window(survey_id: str) -> float                      # the place's map_window, drawn with new_window() on first use
  Places.set_block(survey_id: str, block: Block | None) -> None   # None clears the column
  ```

  `update_planned`, `set_point`, `set_in_use`, `set_bearing`, and `rename_sensor` leave both new columns alone.
- Produces, `router.py`:

  ```python
  class BlockIn(BaseModel):
      street: str = Field(max_length=TEXT_MAX)
      cross: list[Annotated[str, Field(max_length=TEXT_MAX)]] = Field(max_length=2)
      line: list[tuple[float, float]] = Field(min_length=2, max_length=MAX_POINTS)
      osm: BlockOsm              # ways: 1 to 50 ids; base: at most 40 characters
      tags: dict[str, str] = Field(max_length=40)     # keys at most 64 characters, values at most 255
  class BlockPick(BaseModel):
      block: BlockIn | None      # None clears the place's street
  class BlockOut(BaseModel):
      street: str
      cross: list[str]
      line: list[tuple[float, float]]
      stale: bool
  # SurveyOut gains: block: BlockOut | None

  @router.put("/{survey_id}/block", response_model=SurveyOut)
  def set_block(survey_id: str, body: BlockPick, request: Request, admin: User = Depends(require_admin)): ...
  ```

  `set_block`, under `reconcile_lock`: 404 for an unknown place. A `null` block clears the pick for any place. Otherwise 409 `no_location` ("Give this place a location first.") for a place with no point; 409 `rounded_location` ("This place's location is rounded. Set the exact spot first, to at least four decimal places.") when `is_rounded`; 422 naming `line` for a point out of range, and for `BlockLineError` ("That street is more than 500 m from this place." or "That street is too short to store."). The pick is stored with `line = stored_line(...)` under `Places.window(place.id)`, `made_for` set to the place's point now, and `picked_at` now. One audit row, `survey.block`, with the place id. It answers the place through `_one(app_state, survey, ask_nodered=False)`.
- `SurveyOut.block` is `null` for a place with no pick, and for a place with no point (the stored pick is kept, and reads stale if a location comes back). `stale` is true when the place's point differs from `made_for`. No bearing is read to store, list, or judge a pick.

- [ ] **Step 1: Write the failing tests**

```python
# test_state.py
def test_migration_five_adds_the_street_and_the_window(tmp_path): ...   # both columns on surveys; survey_bearings unchanged

# test_blockline.py   (lines built along a parallel near 45.0, -122.0)
def test_a_short_line_is_kept_whole_at_five_places(): ...          # repeats dropped
def test_a_long_line_is_cut_to_the_window(): ...
    # 1,000 m line, point beside its 500 m mark, window 0.25 → 300 m ± 1 m long, running from 425 m to 725 m
def test_the_window_stops_at_the_lines_ends(): ...                 # point at 20 m, window 0.6 → starts at 0
def test_the_point_is_never_on_the_stored_line(): ...              # a point 15 m off the line is no vertex of it
def test_a_line_too_far_away_is_refused(): ...                     # 600 m → BlockLineError("too_far")
def test_new_window_is_never_near_the_middle(): ...                # 2,000 draws: all in BANDS, none in (0.40, 0.60)

# test_places.py
def test_a_places_window_is_made_once(): ...
def test_set_block_stores_replaces_and_clears(): ...
def test_editing_a_planned_place_keeps_its_pick(): ...             # update_planned leaves map_block and map_window alone
def test_renaming_a_sensor_leaves_the_pick_alone(): ...

# test_api_surveys.py   (BLOCK: a 180 m line 20 m north of the place, Main Street between 1st and 2nd Avenue)
def test_the_street_needs_an_admin(claimed_client, login): ...     # viewer 403
def test_a_pick_is_stored_and_listed(admin): ...                   # PUT answers block with street, cross, line, stale False; GET /surveys too
def test_a_long_block_is_stored_as_300_m(admin): ...
def test_a_pick_answers_without_its_private_parts(admin): ...      # no "made_for", "map_window", "osm", "tags", "picked_at" in the body
def test_a_place_with_no_location_takes_no_pick(admin): ...        # 409 no_location
def test_a_rounded_location_takes_no_pick(admin): ...              # lat 45.523, lon -122.691 → 409 rounded_location
def test_a_street_far_from_the_place_is_refused(admin): ...        # 422, field "line"
def test_a_null_block_clears_the_pick(admin): ...
def test_a_corrected_location_makes_the_pick_stale(admin): ...     # POST /{id}/location, then stale True
def test_a_place_that_lost_its_location_lists_no_street(admin): ...   # a planned place edited to blank coordinates → block None
def test_a_changed_bearing_leaves_the_pick_alone(admin): ...       # deploy with another bearing: the same block, stale False
def test_a_pick_changes_no_file_and_asks_nodered_nothing(admin, monkeypatch): ...
    # config.yml's bytes and backups() are the same before and after; every NodeRed method raises if called
def test_the_audit_row_names_the_place_only(admin): ...            # "survey.block", the id; no "Main Street", no coordinate
def test_surveys_paths_are_declared_with_their_answers(): ...      # the existing test, with the new path added
```

- [ ] **Step 2: Run them to verify they fail.** `python -m pytest tm-control/backend/tests -k "block or pick or street or window or migration_five" -v`: FAIL.
- [ ] **Step 3: Implement** the migration, `blockline.py` (with its own small projection, nearest-point, length, and cut-by-metres helpers), the store, `is_rounded`, the models, and the route.
- [ ] **Step 4: Regenerate the API files; run every off-device check.** PASS.
- [ ] **Step 5: Commit** ("Store a place's street, trimmed around the place").

### Task 6: The street dialog and the place's panel *(tricky)*

**Files:**
- Create: `tm-control/ui/src/modules/location/StreetDialog.vue`, `PlaceStreet.vue`
- Modify: `tm-control/ui/src/modules/location/PinMap.vue`, `LocationPage.vue`, `coordinates.ts`
- Test: `tm-control/ui/tests/street-dialog.spec.ts`, `place-street.spec.ts` (new); `pin-map.spec.ts`, `location-page.spec.ts`

**Interfaces:**
- Consumes: `blockAt`, `blockName`, `parseWays`, `NEAR_M`, `TAP_M` (Task 4); `boxAround`, `fetchWays`, `StreetDataError` (Task 4); `PUT /api/v1/surveys/{survey_id}/block` and `SurveyOut.block` (Task 5).
- Produces, `coordinates.ts`: `isRounded(lat: number, lon: number): boolean`, the same rule as the backend's.
- Produces, `PinMap.vue`, new optional props and one emit: `movable: boolean` (default `true`; `false` fixes the pin and stops taps from moving it), `lines: Point[][]` (drawn as one GeoJSON source with a line layer in the theme's `primary` colour, 6 px wide, redrawn when the prop changes), and `tap: [LatLon]`, emitted for a tap when `movable` is `false`.
- Produces, `StreetDialog.vue`: props `place: SurveyOut`, `map: MapSources`, `open` (model); emits `saved: [SurveyOut]` and `stale` (on 409). It takes no sensor and no bearing. When it opens it fetches the streets for `boxAround([place.lon, place.lat])` once, then finds `blockAt` for the place's point within `NEAR_M`. Exact copy:
  - title: `Choose the street`
  - `This is the stretch of street the public map would show for this device, in place of its exact spot. Choosing it sends nothing.`
  - `` `The map comes from ${mapHost} and the street data from ${streetHost}. Your phone asks them for the area around this place; this device sends them nothing.` ``
  - while fetching: `Looking up the streets around this place…`
  - with a block: `` `${blockName(block)}` `` and, under it, `This is the street nearest this place. If the device counts another street, pick that one.`
  - a block over 300 m adds: `The public map would show about 300 m of it.`
  - no block within `NEAR_M`: `No street found within 80 m of this place. Tap the street the device counts.`, with the map already waiting for a tap
  - street data failure: `` `The street data couldn't be loaded from ${streetHost}.` `` with `Try again`
  - buttons: `Use this street` (disabled until there is a block), `Pick a different street`, `Cancel`
  - after `Pick a different street`: `Tap the street on the map.`; the next `tap` runs `blockAt` for the tapped point within `TAP_M`, and a tap that finds nothing says `No street there. Tap closer to the street.` and keeps the block shown
  - `Use this street` PUTs `{ block }`, emits `saved` with the answer, and closes; an API error is shown beside the buttons. `Cancel` sends nothing.
- Produces, `PlaceStreet.vue`: props `place: SurveyOut`, `map: MapSources`; emits `choose`. It shows nothing for a place with no location. Otherwise:
  - with a pick: `` `Street: ${blockName(place.block)}` ``;
  - a stale pick adds a warning: `Check your street: this place's location changed since the street was chosen.`
  - the button `Choose the street`, or `Change the street` with a pick; in its place on the hotspot: `Choosing the street needs the internet, and this device's hotspot has none. Come back to this page once the device is on your Wi-Fi.`; for a rounded location: `Set the exact spot, to at least four decimal places, to choose a street.`; with `map.overpass_url` null, no button and no sentence.
- Produces, `LocationPage.vue`: a `PlaceStreet` in each place's panel, above the button row; one `StreetDialog` for the place being chosen for. After `PlaceForm`'s `saved` or `CorrectDialog`'s `corrected` with `onMap` true, for a place with a location that isn't rounded and no pick, and with `map.overpass_url` set, the street dialog opens for that place.
- Not changed by this task: the place form's bearing fields, the deploy review, **Modify deployment**, and **Correct bearing**.

- [ ] **Step 1: Write the failing tests**

```ts
// pin-map.spec.ts
test('a fixed pin does not move, and a tap is reported')
test('lines are drawn, and redrawn when they change')

// street-dialog.spec.ts   PinMap stubbed; vi.mock('../src/modules/location/overpass') so fetchWays answers tests/streets.ts
test('asks for a grid-aligned box around the place, once')
test('shows the nearest street by name and says it can be changed')   // 'Main Street between 1st Avenue and 2nd Avenue'
test('no street within 80 m asks for a tap')                        // Use this street stays disabled until the tap
test('Pick a different street then a tap changes the block')
test('a tap away from any street says so and keeps the block')
test('a block over 300 m says how much the public map would show')
test('Use this street sends the pick and answers saved')            // api.sent: PUT …/block with the body
test('Cancel stores nothing')                                       // no PUT in api.sent
test('street data that fails can be tried again')                   // StreetDataError → the message; Try again → a second fetch
test('an API refusal is shown and the dialog stays open')

// place-street.spec.ts
test('a place with no location shows nothing')
test('a pick shows the street')
test('a stale pick warns')
test('on the hotspot the sentence replaces the button')
test('a rounded location says to set the exact spot')
test('no street data source: no button')

// location-page.spec.ts
test('saving a place whose pin came from the map opens the street dialog')
test('saving typed coordinates does not')
test('a saved street shows in the place\'s panel')
```

- [ ] **Step 2: Run them to verify they fail.** `npm test`: FAIL.
- [ ] **Step 3: Implement** the two components, the `PinMap.vue` additions, and the page's changes.
- [ ] **Step 4: Run the tests and the build.** PASS.
- [ ] **Step 5: Screenshot review** at 375 px and 1280 px in fake mode: the dialog with a street, with none found, in tap mode, with the failure; the panel with a street, stale, on the hotspot, rounded. Fix what the review finds; record it and the design notes in the README (one street per place, no bearing read and why, a tap in place of dragging, where the trim happens and why).
- [ ] **Step 6: Commit** ("Choose the street a place counts, from a map").
- [ ] **Step 7: Stop for the maintainer's UI review.**

### Task 7: Docs and device tests

**Files:**
- Modify: `docs/use/location.md`, `docs/use/wifi-hotspot.md`, `docs/development/tm-control.md`, `tm-control/ui/README.md`, `CLAUDE.md`
- Create: `docs/assets/images/location-street.png`
- Modify: `script/devpi/tests/test_web.py`

- [ ] **Step 1: The device test.** Add `PUT /surveys/{id}/block` to the Location write paths a viewer is refused, and `test_a_place_lists_its_street`: every place in `places_state()` has a `block` key, `null` or an object with `street`, `cross`, `line`, and `stale`.
- [ ] **Step 2: `docs/use/location.md`,** a "Choose the street" section: what the block is (the stretch of street between cross streets that the device counts), what it is for (the public map would show it in place of your exact spot; choosing it sends nothing, and turning the map on is a separate choice that a later update adds to the Sharing page), that the page suggests the street nearest the place's spot and you tap another when the device counts a different one, the 300 m rule in one sentence, "Check your street" after a location is corrected, that turning the device to count another street means choosing the street again, what the phone asks the two hosts for (the map for the area viewed; the street data for a box a kilometre or two across, never the exact spot), and that it needs a phone or computer with internet on the device's network. The screenshot at the example point.
- [ ] **Step 3: The other pages.** `wifi-hotspot.md`: the street can't be chosen on the hotspot. `docs/development/tm-control.md`: the route, `surveys.map_block` and `map_window`, the lookup modules and their rules' source ("the public map's rules", and the one that differs), how the specs fake the street data. `CLAUDE.md`: the Location page's routes and the state columns.
- [ ] **Step 4: `mkdocs build --strict` and every off-device check.** PASS.
- [ ] **Step 5: Commit** ("Document choosing a place's street").

### Task 8: Pi plan and PR 2

- [ ] **Step 1: Pi plan,** as a logged `tmdev check` on the bench unit after `tmdev deploy <host> -- -t revproxy -t tm-control`, with a place at the docs' example point:
  1. The device suite passes.
  2. From a desktop browser on the LAN: **Choose the street** on that place; the suggestion is the street nearest the place; **Use this street** saves; the panel shows the name after a reload.
  3. The network panel: the street query holds a box with two-decimal edges and no pin; no request carries a Referer; requests go only to the two hosts.
  4. **Pick a different street,** tap, save: the name changes.
  5. A place on a road with no cross street for more than 300 m: `GET /surveys` shows a line of about 300 m, and the place's nearest point on it is not at its middle.
  6. Correct the place's location: "Check your street". Choose again: gone. Deploy with another bearing: no warning, and the street is unchanged.
  7. `config.yml`'s modification time and the deployment rows are the same before and after a pick.
  8. Add a place by pin: the street dialog opens by itself after Save.
  9. On the hotspot: the street name still shows; the sentence replaces the button; no outside request.
  10. Empty `tmsetup_map_overpass_url`, deploy `-t tm-control`: the pin still works and no street button shows. Restore it and deploy again.
  Items 2 to 8 need a desktop browser or an iPhone on the LAN. Record each with `tmdev.py check item`; end with `tmdev.py check end`.
- [ ] **Step 2: Every off-device check once more** on the final branch; `git grep` the branch for the names of private repositories, servers, and issues, for device names, and for any coordinate that isn't allowed.
- [ ] **Step 3: PR 2's text,** the template filled in. The release note: "A place on the Location page can now have a street: the stretch between cross streets that the device counts. The page suggests the street nearest the place's exact spot, and you confirm it or tap another. It is stored on the device and sent nowhere; a later update lets the public map show it in place of the exact spot." Also: the Docs list, the Pi plan's results, the chunk sizes, the limits (no map without internet; one street per place; the suggestion doesn't know which way a sensor faces; a pick isn't refreshed when OpenStreetMap changes; nothing uses the pick yet), and the AI-assistance section. The maintainer reads the commit messages and the PR text before any push.

## Later

- **Sending the block** (the next plan): the pick mirrored to `config.yml`, the upload gate's block form of the map attribute, the Sharing page's choice between the block and a rounded point, the notice text, and the street's name in the deploy review.
- **A "try anyway" link on the hotspot,** if the bench shows an iPhone on mobile data can load the map there.
- **Refreshing a pick** when OpenStreetMap's streets change under it.
- **The block in the exact database copy** and the exact-locations export.
- **A second street for a corner unit:** a per-sensor choice on top of the place's street. It needs to know which sensor counts which street, so it comes with or after the form for how each sensor is mounted and aimed.
- **A suggestion that follows the way a sensor faces,** and **aiming a sensor on the map:** that form's, once it records a heading. `PinMap.vue` is the piece it would build on.
- **An address search,** and **dragging a block's ends**: both left out on purpose; see the README's design notes.
- **OpenLR and Overture references:** the public map can derive them from the stored line; nothing on the device changes.
