# The Mounting form: how each sensor is mounted, recorded with its deployment

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An admin records how the unit is mounted at the place in use (each sensor's heading in degrees, its height above the road, and its tilt or the distance to the centre of its view), the device keeps those facts on the sensor's deployment row, and a change is either a correction of the running deployment or the start of a new one, as the admin answers "Did the unit move or turn?". The heading takes the place of the eight-point `bearing` everywhere it is kept.

**Architecture:**
- The facts live in three places, as a sensor's bearing did: the control app's `state.sqlite` (per place and sensor), Node-RED's `config.yml` (the sensor's `deployment:` block, for the place in use), and tmdb's `deployment` rows (five columns, of which `heading_deg` takes the place of `bearing`). Node-RED never opens `state.sqlite`, and the control app never opens tmdb.
- One fact says which way a sensor faces: `heading_deg`, a whole number of degrees. A compass point is a way to pick a heading (its centre) and to read one ("NE (40°)"), and nothing stores a point. So no rule has to keep two values in agreement.
- Node-RED's deployment engine starts a new deployment when any of the five differs between a sensor's open row and `config.yml`, as it did for the bearing. To correct in place, the control app rewrites the open row first, through an internal endpoint, and writes the file second, so the engine finds nothing to change. That is the order **Correct bearing** already uses.
- Every rule is in Python, in one module with no I/O: the limits, tilt from distance and distance from tilt, which compass point a heading belongs to, which changes count, and the answer chosen in advance. The form asks the API for a dry run as the admin types and shows what it answers. The UI holds only what a drawing needs: the dial's geometry and feet to metres.
- Three pull requests from this plan, each stacked on the one before.
  - PR 1 replaces `bearing` with `heading_deg` everywhere it lives (tmdb, the flows, `config.yml`, the installer, the control app's store, API, and pages, the upload, the docs) and adds nothing else. Old rows and files are converted to their point's centre.
  - PR 2 records the other four facts: the columns, the engine, the endpoints, the API, the upload's field list, and the reference picture's `pose`.
  - PR 3 is the form and nothing else, so its review is one of UI code only.

**Tech Stack:** Node-RED 5.0.10 function nodes (JavaScript in `flows.json`), a SQLite migration run by `tmdb_migrate.py`, Python 3.11 (FastAPI, pydantic 2, ruamel.yaml; no new dependency), Vue 3 + Vuetify 3 + TypeScript (Vitest, jsdom; no new package), pytest with the function-node harness in `script/tests/test_node_red_flows.py`, the device tests in `script/devpi/tests`, Material for MkDocs.

**Spec:** "What it must do" below.

**Repo:** `glossyio/traffic-monitor`. PR 1 on `feature/heading-replaces-bearing/357` off `dev`; PR 2 on `feature/mounting-records/357` off PR 1's branch; PR 3 on `feature/mounting-form/357` off PR 2's. Each is a stacked PR in its own worktree. One public issue, #357, covers the three; PRs 1 and 2 say "Part of", PR 3 closes it. All paths below are relative to the repo root.

**Status:** written 2026-11-23 against `dev` at `8c0f0544`. Revised 2026-11-24, after the other change's first pull request merged with `0007`. Another change in progress touches the same places, and whichever merges second does the chore:
- **tmdb migrations `0008` to `0011`.** This plan claims `0008` to `0010` (PR 1) and `0011` (PR 2); the other change merged first with `0007`. Its view, `events_with_setup`, names no `deployment` column, so PR 1's `0010` drops `bearing` with the view in place, and a test reads the view after a full migrate.
- **`script/tests/test_node_red_flows.py`:** `TM_INTERNAL_PATHS`, `TM_INTERNAL_METHODS`, and `VALIDATORS` gain entries from both.
- **The "upload gate" node** (`ae3349867027d005`) is one JSON line. This plan edits it in Task 12; the other change edits it in its second PR. The second to merge reapplies its edit by hand.
- **The sharing notice**, the sharing and data docs pages, and `CLAUDE.md`.

This plan claims the control app's state migrations 5 (PR 1) and 6 (PR 2).

Whatever reads `bearing` from shared data has to read `heading_deg` once PR 1 is on a unit.

**Size** (estimates):
- PR 1 about 75 files and 1,400 to 1,900 changed lines (about +1,100 to +1,400 and -700 to -900). Most of it is renames and their tests. The new code is the runner's line, the three migrations, the store's conversion, the `migrate` step, and one small pick component.
- PR 2 about 32 files, +1,700 to 2,100 lines, about half of it tests.
- PR 3 about 22 files, +1,500 to 1,900 lines, about 40% tests.
- To maintain afterwards: one heading where there was a bearing; four more tmdb columns and five more `state.sqlite` columns; two more internal endpoints; a `needs-column` line in the migration runner; a reader of the old `bearing` key in two languages; one page with two drawn components (SVG written by hand, no package); the limits written twice (the flows and `mounting.py`, with a test that compares them) and the compass table three times (the flows, Python, TypeScript, each pinned to the same table).

**Decisions.** The maintainer's are marked with a date. The rest are calls made while writing this, open to change. Decisions 5 to 8 are the four that are cheap to change now and expensive after a release; they were put to the maintainer on 2026-11-23, and his answers are in them.

1. **Three pull requests: the heading in place of the bearing, the records, then the form (maintainer, 2026-11-23).** He first chose two, the records and the form. Replacing `bearing` (Decision 10) put a PR of its own in front, so that the rename is reviewed apart from anything new.
2. **The dial only. No aiming on a map (maintainer, 2026-11-23).**
3. **The reference picture's `pose` has no field of view yet (maintainer, 2026-11-23).** The field of view belongs to a planned record of each camera's settings, which will hold it per camera. `pose.hfov_deg` is written as `null` until that exists.
4. **What the form holds (maintainer, 2026-11-17):** height; tilt or distance, either one measured and the other worked out; a heading dial in place of the bearing drop-down, for radars too; three usual mounts with the numbers below; a side view that follows the numbers; "Did the unit move or turn?" with an answer already chosen; lengths typed in feet by default and stored in metres; the mount's key recorded; roll not recorded.
5. **Names (maintainer, 2026-11-23: the technically correct word).** `heading_deg`, `pitch_deg`, `height_m`, `view_distance_m`, `mount`: the same five names for the tmdb columns, the `config.yml` keys, the API fields, and the reference picture's `pose`. He asked whether `bearing_deg` would sit better beside the `bearing` column, and chose whichever word is correct. A heading is the way a thing itself points; a bearing is the direction from one point to another. A mounted sensor has a heading, and heading and pitch are the usual pair for a camera's aim. Decision 10 then took `bearing` away altogether. The unit is in the name because the form takes feet and a person editing `config.yml` must not have to guess. `view_distance_m`, not `distance_m`, because a later change adds a distance to the nearest lane.
6. **A new place starts with no mounting facts, and so does a place the unit returns to (maintainer, 2026-11-23; the return changed by the maintainer, 2026-11-25).**
   - **Deploy here** at a place that was never measured leaves the four empty for every sensor, and the new deployments say "not measured" until the form is saved. Empty, not a default number: an empty value says nobody measured, which a default can't. The usual mounts are the form's starting numbers, one tap away, and nothing is recorded until Save.
   - **Re-deploy here** at a place used before does the same: the unit was taken down and put up again in between, so none of the four is recorded. What the form last saved there is offered as `previous` and recorded only by a save that writes that sensor; the heading is the one chosen in the deploy review. Saving the offered values fills empty ones, so nothing is asked, and the open row is corrected in place. The Location page and the Mounting page say the values wait to be confirmed (PR 3).
   - 2026-11-25: the call within his first answer had been to record the values at once, as a place's stored bearing was. He chose the other way that answer named: fill the form only and record nothing until someone saves. There is no way to dismiss the offered values; they are offered until a save writes that sensor.
7. **The form is a page of its own, `/location/mounting`, and the button on the place in use reads Mounting (maintainer agreed, 2026-11-23; PR 3).** It takes the place of **Modify deployment**, whose review step goes. The form is long on a phone (a dial and a drawing for each sensor), which a dialog carries badly.
8. **The upload gate gets a field list for deployment rows (call; the maintainer confirmed on 2026-11-23 that the five are shared, since none is personal data).** Today it passes deployment rows whole, so a new column would upload without anyone listing it. With the list, the five are sent because they are listed, like every event field.
9. **Any difference in the five starts a new deployment in Node-RED; the control app corrects in place by changing the row first.** So a hand edit of a mounting key in `config.yml` is a move, as a hand edit of the bearing is today.
10. **`heading_deg` replaces `bearing` everywhere, and old values become their point's centre (maintainer, 2026-11-23).** He asked whether the eight compass points were still needed once a sensor has a heading, and chose to drop them rather than keep a column for old times' sake. Nothing on the device computed with the bearing: only the deployment record and the upload read it. What follows, as calls:
    - **tmdb and the control app's store:** each stored bearing is converted and its column dropped. `n` is 0, `ne` 45, and so on round to `nw` 315; anything else becomes empty. tmdb's own backup from before the migration keeps the old text.
    - **`config.yml`:** Node-RED's start rewrites each `bearing` key as `heading_deg` (`tm-control migrate --node-red-headings`, an `ExecStartPre` beside the tmdb migration), so the file and the database change while no flow runs. The installer's pass never touches it: it runs while the old Node-RED and its config watch are still up, and that engine would start a deployment on the change. The rule: the installer pass may not change a key that a running engine compares. A `bearing` still found in a file (an old backup put back, a hand edit from old notes) is read as its point's centre where its block has no `heading_deg`, by Node-RED and the control app alike, and the Status page says to convert it. So neither the order of an upgrade nor an old file starts a deployment. The other way would be to stop reading it at once.
    - **The upload** sends `heading_deg` where it sent `bearing`. That breaks whatever reads `bearing` from shared data, and the release note says so.
    - **Compass points stay on the pages** as an eight-point pick, which stores the point's centre, and in what is shown: "NE (40°)". The places CSV takes a point or whole degrees.
    - **A point picked and later measured is a change like any other.** 45 to 40 asks "Did the unit move or turn?" when traffic was recorded, with "measured it better" chosen. Nothing records that a heading was only a compass point.
11. **"Recorded traffic"** means an event for a camera's deployment and a radar reading for a radar's. When Node-RED can't say (an air-quality monitor, a slow query, no answer), the form asks.
12. **One answer for a save.** Under "moved or turned", a sensor starts a new deployment only when its own change counts (rule 7 below); the others in the same save are corrected in place.
13. **Saving needs Node-RED.** Without it the row can't be corrected first, so nothing is saved and the form says why. A dry run works without it.
14. **Planned places, the deploy review, and the correction of one deployment keep an eight-point pick,** which stores the point's centre. The dial and the other four values are for the place in use.
15. **An air-quality monitor gets the dial and nothing else.**
16. **A radar that a camera names as its own takes that camera's values** until the admin unticks "Same as the camera". The tick isn't stored: it reads as ticked while the two sets of values are equal. `config.yml` has no such fallback: a radar with no value of its own reads the top-level block, as every sensor does.
17. **A correction made on the form carries no reason.** A corrected heading is still written to `survey_corrections`; the other four are written to the audit log with the old and new values.
18. **Limits:** height above 0 and at most 100 m; distance 0 to 1,000 m.
19. **The usual mounts go into the existing "Choose a site and mount" page,** not a new page, so no path changes. The photographs are the maintainer's to take.
20. **In fake mode a deployment counts as having recorded traffic once it is 30 seconds old,** so the question can be seen on a laptop.

## What it must do

1. **Five facts for each sensor at the place in use.**

   | Fact | Name | Values | Stored as |
   |---|---|---|---|
   | Heading, clockwise from true north | `heading_deg` | a whole number, 0 to 359 | INTEGER |
   | Tilt below level | `pitch_deg` | 0 to 90 | REAL, one decimal |
   | Height above the road | `height_m` | above 0, at most 100 | REAL, two decimals |
   | Distance along the ground to the centre of the view | `view_distance_m` | 0 to 1,000 | REAL, two decimals |
   | The usual mount started from | `mount` | `tripod`, `pole`, `window`; in the file and the database any `^[a-z0-9_]{1,32}$` | TEXT |

   Each is optional and empty by default. Rounding is half away from zero, as coordinates are rounded. `heading_deg` is the only record of which way a sensor faces: `bearing` is gone from the database, the store, the API, and the upload (PR 1).
2. **A compass point is a way to pick a heading and to read one, and nothing stores a point.** With `POINTS = n, ne, e, se, s, sw, w, nw`, a point's centre is its index times 45, and the point of heading `h` is `POINTS[floor(((h + 22.5) mod 360) / 45)]`: 0 and 22 are `n`, 23 and 67 are `ne`, 68 is `e`, 337 is `nw`, 338 and 359 are `n`. Picking a point sets the heading to its centre. A heading is shown with its point: "NE (40°)". An old `bearing` is converted the same way: one of the eight, after trimming and lower-casing, becomes its centre, and anything else becomes empty.
3. **Tilt and distance: one is measured, the other worked out.** The control app remembers which (`measured`: `pitch` or `distance`).
   - Distance from tilt: `height_m / tan(pitch_deg)`. None when there is no height, when the tilt is 0 (the centre of the view is at the horizon), or when the result is over 1,000.
   - Tilt from distance: `atan2(height_m, view_distance_m)` in degrees; 90 when the distance is 0. None when there is no height.
   - Worked cases: 2.13 m and 15° give 7.95 m; 3.66 m and 15° give 13.66 m; 4.88 m and 15° give 18.21 m; 3.66 m and 13.72 m give 14.9°.
4. **Three usual mounts,** shipped with the control app. Picking one fills in the height and the tilt and nothing else, and nothing is saved until Save.

   | Key | Title | Height | Tilt |
   |---|---|---|---|
   | `tripod` | Tripod beside the road | 2.13 m (7 ft) | 15° |
   | `pole` | Pole or sign post | 3.66 m (12 ft) | 15° |
   | `window` | Upstairs window over an intersection | 4.88 m (16 ft) | 15° |

5. **On the deployment row.** tmdb's `deployment` table gets the five columns and loses `bearing`. PR 1 adds `heading_deg`, fills it from each row's bearing (item 2), and drops `bearing`. PR 2 adds the other four, empty on every existing row. A new row is written with the sensor's values from `config.yml`. The upgrade starts no deployment, whether `config.yml` was converted before Node-RED read it or after.
6. **A deployment starts when the place or any of the five changes** in `config.yml`. While the file names no place, a change waits, as a bearing change did.
7. **"Did the unit move or turn?"** is asked once for a save, and only when it matters.
   - A change *counts* when a value that was set is changed or cleared: the heading, the height, or the measured one of tilt and distance. The one worked out follows it and is never a change of its own, so choosing the other of the two as "measured" without changing its number changes nothing, even when the worked-out value moves by a rounding step. Filling in an empty value doesn't count. The mount's key never counts.
   - The question is asked when a sensor has a change that counts and its open deployment has recorded traffic, or Node-RED couldn't say.
   - The answer chosen in advance is "moved or turned" when a counting change is 20° or more of heading, 0.3 m or more of height, or 5° or more of tilt (measured, or worked out from a measured distance), and "measured it better" below that. The size of a turn is the smaller angle between the two headings: 350° to 10° is 20°.
   - "Moved or turned": each sensor with a counting change gets a new deployment from now. "Measured it better", and every change that doesn't count: the open deployment's row is corrected in place.
   - A save that needs the answer and has none is refused, and nothing is written.
8. **Nothing is half saved.** A corrected row whose file write then fails is put back. A save while Node-RED doesn't answer is refused.
9. **The file's values survive a reset.** After `tmsetup.sh -f` renders `config.yml` from the template, the control app writes the place in use's mounting back, as saved for this use (item 10), for each sensor whose heading in the file is blank or the one it has stored, and no deployment starts. A heading someone put in the reset file is theirs, and that sensor gets nothing back.
10. **A move records none of the four (the maintainer's change, 2026-11-25).** Deploying to another place removes each enabled sensor's tilt, height, distance, and mount from the file, at a place used before as at a new one, so the new deployments record none of them. The heading is the one chosen at the deploy, which starts from the place's stored one. The store keeps what the form last saved for each sensor at the place, marked unconfirmed, and offers it as `previous` until a save that writes that sensor confirms it; a reset gives back only a confirmed mounting. What is offered is the form's last save, not a hand edit of the file, which the store never saw.
11. **Correct heading takes the place of Correct bearing (PR 1).** It rewrites one deployment's heading, with a reason, row first and file second for a running one, and writes a `survey_corrections` row. From PR 3 a running deployment at the place in use is corrected on the Mounting page, and **Correct heading** is for one that has ended.
12. **Upload.** The five are sent on deployment rows with **Share data**, because a new `deployment` list in `upload-lists.json` names them; a row's key that isn't listed is left out. The notice says so.
13. **The reference picture's data file gains `pose`:** the camera's five, with `hfov_deg: null`, or `null` when nothing is recorded. The drawing's caption says which way the camera faces. `format_version` stays 1.
14. **The form (PR 3):** a page for the place in use with a section for each sensor, one unit selector (feet by default, remembered in the browser, each length shown in both units), "Start from a usual mount", a compass dial with a number field, the tilt-or-distance choice with the other value greyed, a side view that follows the numbers, the question above Save, and the result beside the form. It works on the hotspot, since it needs no internet.
15. **Nothing here identifies a place.** The five hold no coordinate, name, or description, so they may be logged in an audit row and uploaded.
16. **Docs** say what is recorded, how to measure it, and what a change does, in the same PR as the code they describe.

## Where the code stands that this plan touches

Read at `dev` `8c0f0544`; the tmdb bullet as of `bc72d593`.

- **tmdb.** `container/node-red-tm/schema/migrations/` ends at `0007` (the setup history, whose view `events_with_setup` reads `events` and the two setup tables). `deployment` has `id, entryStartDateTime, entryEndDateTime, lat, lon, bearing, sensorType, sensorName, deviceName, survey_id, location_precision`. `tests/helpers.py` holds `LATEST_VERSION`, `LEGACY_SCHEMA`, `migrate`, `columns`, `query`, `user_version`. `test_flows_sql.py` compiles every static SQL statement in `flows.json` against the migrated schema. The exact-location copy's view is `SELECT d.*`, so new columns show through it unchanged.
  - `tmdb_migrate.py` runs SQL files only, each in one transaction, and copies the database once per run before the pending files. A file that fails is rolled back, and Node-RED starts on the old version. No index, view, or trigger names `deployment.bearing`. The README says SQLite 3.40 is the oldest a device may have, asks for a table rebuild to drop a column, and describes a legacy-shaped `deployment` table (`entryDateTime`, `orientation`, `address`, no `bearing`) that `0002` still applies to.
- **Flows, `init-config` tab.**
  - "init config defaults" (`94136e5a6f092bb6`) normalises each enabled sensor's `deployment` block: top-level keys are copied down where the sensor has none. An invalid top-level bearing is reported and kept; an invalid one of a sensor becomes `''` with `node.error(text, msg)`, in a text that holds the value. The catch node `99132403b74d7a50` has this node in its scope, so an error given with `msg` becomes a config error on the Status page. The engine is not in that scope.
  - "deployment engine" (`689b64c16a889e0a`): `decide()` with rules 1 to 6, `bearingOf`, `legacyBearing` (a stored `'null'` or `'undefined'`), `insertRow`, `rewriteRow`, `keepRow`; four outputs (close, insert, rewrite, the rows for ThingsBoard). Its SQL nodes: "insert deployment" (`f5e4484aeb11facf`), "rewrite deployment" (`94dad283c8f696f4`), "close deployment" (`3c63afe206e5d65e`), and the template "query open deployments" (`696c3a7b0b83f7b5`).
  - The internal endpoints sit in the group `3da2c0e89c06736d`: each is `http in` → "tm-internal: check token" (a copy per endpoint) → a validator with two outputs → a prepared sqlite node → an answer function → `http response`. "read survey deployments" is `5d5d7f4aabe982c2`; the bearing correction's statement is "rewrite deployment bearing" (`ac9c1f431f070f3a`); "tm-internal: validate survey path" is `eee4243f7e032aa3`. The catch `e27f61c06fec6515` lists every sqlite node of the group.
- **Flows, `thingsboard` tab.** "upload gate" (`ae3349867027d005`): `listedFields(value, list, label, notMapping)` cuts a mapping to a list; `rowsOf` and `reRound` handle deployment rows, which pass whole today; the lists come from `container/node-red-tm/data/upload-lists.json` (keys `telemetry`, `attributes`, `event`, `watch_camera`, `watch_radar`). The `deployments` attribute is built by the template `9b0f7197fe82bbfa` with `sensorType, lat, lon, bearing, id` for each sensor, all as text. "format deployment telemetry" (`c6ff73faf6fa9e98`) sends the engine's rows as they are. Nothing else in the flows reads a bearing: no dashboard, direction, or speed logic.
- **Flow tests, `script/tests/test_node_red_flows.py`:** `run_functions`, `named`, `engine(sensors, open_rows, deployment)`, `EngineRun`, `open_row`, `camera_row`, `radar_row`, `ENGINE_SQL`, `OPEN_ROWS_SQL`, `ROW_KEYS`, `SURVEY_SQL`, `TM_INTERNAL_PATHS`, `TM_INTERNAL_METHODS`, `VALIDATORS`, `correction_chain(url)`, `gate(msg, ...)`, `upload_lists()`, `GATE_ROW`, `test_upload_lists_file`, `test_gate_sends_nothing_without_readable_lists`. `script/tests` already imports `tm_control` (see `test_node_red_settings.py`).
- **Control app, `tm-control/backend/tm_control/`.**
  - `core/state.py`: `MIGRATIONS` has four entries, each run statement by statement in one transaction with foreign keys on. `survey_bearings` is `(survey_id, sensor_type, sensor_name, bearing TEXT NOT NULL, map_block_ref, map_side)`, keyed by its first three. `survey_corrections.field` has `CHECK (field IN ('location', 'bearing'))`.
  - `modules/apps/contracts.py`: the Status page's Location check (`config.deployment`), with a copy of `BEARINGS` and a `_bearing_ok` of its own. A check's status is `error` or `warn`.
  - `core/migrate.py`: `_run_node_red` edits `config.yml` through `RoundTripFile`, collects `(would, done)` pairs, saves once with a backup, and places `database_precision` after `survey_id` or `bearing`. Its tests are in `tests/test_location_migration.py`.
  - `modules/location/places.py`: `Places` with `set_bearing`, `rename_sensor`, `update_planned` (deletes and re-inserts a planned place's bearing rows), `record_correction`; the models `Bearing` and `Survey`.
  - `modules/location/config.py`: `NodeRedConfig` with `sensors()` (each enabled sensor's bearing as the engine copies it down), `cameras()` (`CameraEntry.camera_radar`), `blank_bearings()`, `set_sensor_bearing()` (creates the sensor's `deployment:` block), and the helpers `_set`, `_remove`, `put_after`. `set_place` and `set_survey_id` put `survey_id` after `bearing`. `SENSOR_TYPES = ("cameras", "radars", "airquality_monitors")`.
  - `modules/location/coordinates.py`: `BEARINGS`, `normalize_bearing`, `round_half_away`, `DEPLOYMENT_ID`.
  - `modules/location/router.py`: `deploy_place` (`switching` is true when the place changes), `correct_bearing` with `_write_bearing` and `_put_row_back`, `_wait_for_rows`, `_deployment(row)`, `DeploymentOut`, `PlacesState.sensors: list[Bearing]`, `_place`, `_invalid`, `_nodered_error`, `Audit(...).record(user_id, action, detail)`, `app_state.reconcile_lock`.
  - `modules/location/reconcile.py`: `_follow` puts the place in use and its bearings back into a reset file (`restoring`).
  - `adapters/nodered.py`: the `NodeRed` client (`deployments`, `correct_bearing`, ...), `NodeRedError`.
  - `fake.py`: `FakeNodeRed` runs the engine's rules in Python over rows in memory; fake mode and the backend tests both use it.
  - `modules/cameras/reference.py`: `Reference`, `data_file`, `caption`; `modules/cameras/router.py::take_reference` builds the `Reference`.
- **Backend tests:** `tests/test_api_surveys.py` (`admin`, `places`, `survey`, `create`, `deploy`, `rows`, `first_place`, `file_data`, `backups`, `CAMERA`, `RADAR`, the `no_waiting` fixture), `tests/test_places.py`, `tests/test_location_config.py`, `tests/test_state.py` (one test per migration), `tests/test_cameras_reference.py`.
- **API files:** `PYTHONPATH=tm-control/backend python -m tm_control dump-openapi > tm-control/ui/src/api/openapi.json`, then `(cd tm-control/ui && npm run api:generate)`.
- **UI, `tm-control/ui/src/modules/location/`:** `index.ts` (the module's routes and nav), `LocationPage.vue` (the card for the place in use, the panels, `openReview`), `DeployReview.vue` (also serves **Modify deployment**), `PlaceDetails.vue` (each deployment with **Correct bearing**), `CorrectDialog.vue`, `PlaceForm.vue` (a planned place), `ImportPlaces.vue` (the CSV), `coordinates.ts` (`BEARINGS`, `bearingTitle`, `startingBearings`, `deployWords`). The same `v-select` over `BEARINGS` is written out three times, in the dialog, the review, and the place form. Tests: `tests/mount.ts` (`mountAlone`, `mountApp`, `typeInto`, and the dialog helpers), `tests/fake-api.ts` (`fakeApi`, `json`, `apiError`, `api.sent`), `tests/location-page.spec.ts`, `tests/deploy-review.spec.ts`, `tests/place-details.spec.ts`.
- **Docs:** `docs/use/location.md` ("Move or turn the device", "Correct a wrong location or bearing"), `docs/configuration/node-red-config.md` ("deployment"), `docs/data-and-payloads/data-overview.md` ("deployment"), `docs/use/cameras.md` ("The data file"), `docs/deployment-and-mounting-guide.md`, `docs/development/tm-control.md`.
- **The installer:** `tmsetup_bearing: ''` in the role's `defaults/main.yml`, written by `container/node-red-tm/config/config.yml.j2` as `bearing: '{{ tmsetup_bearing }}'`. `tmsetup.sh -C` doesn't offer it.
- **Where `bearing` is written today,** by lines that mention it: the backend 176 and its tests 268, the UI 145 and its tests 89, the flow tests 102, the docs 26, and 13 nodes of `flows.json`.

## Global Constraints

- **The names and limits are those in "What it must do", items 1 to 4.** No task picks another name, unit, or number.
- **One place for the rules.** `coordinates.py` holds item 2 (PR 1), and `tm-control/backend/tm_control/modules/location/mounting.py` holds every rule of items 3, 4, and 7 (PR 2). `mounting.py` imports the standard library, pydantic, and `coordinates.py`, and does no I/O. Two repeats are allowed, each pinned by a test against the same table: the flows check the same limits on what they read from `config.yml` and read an old `bearing` the same way, and the UI needs the compass points to title a pick and to draw the dial.
- **No arithmetic on mounting values in the UI** beyond feet to metres and the dial's geometry. Tilt from distance, what changed, whether to ask, and the answer chosen in advance all come from the API's dry run.
- **Stored in metres and degrees.** Feet exist only on the page.
- **The control app never opens tmdb, and Node-RED never opens `state.sqlite`.**
- **Not private, but not noisy.** The five may appear in an audit row. No coordinate, description, or reason is logged, audited, or put in an error message, as before. A config error names the key's path, never the value.
- **After PR 1 nothing writes a bearing.** The word stays only where something from before is read: the old key in `config.yml` (the flows' defaults node, `coordinates.read_heading`, `migrate`, the Status check), the two conversions (tmdb's migration and the store's), and the docs' note for people with older files and exports. PR 1's last task greps for the rest.
- **PR 1 changes no behaviour a person sees** beyond the words "Facing" and "heading" and a heading shown in degrees. Anything new belongs to PR 2 or PR 3.
- **Flows:** edit `flows.json` programmatically and write it back with `json.dumps(flows, indent=4, ensure_ascii=False)` and no trailing newline. New nodes go on the tab and in the group of the nodes they sit beside. No `CREATE` or `ALTER TABLE` in the flows.
- **UI work follows `tm-control/ui/README.md`:** conventional Vuetify, the one dark theme, system fonts, 44 px buttons, results beside the form, no toasts, sentence case. Each UI task's implementer loads the `frontend-design` skill and works test-first; the README's rules win over the skill's taste. New design notes go in the README.
- The API files are regenerated in the same commit as any model change.
- No coordinate in any fixture, commit, PR text, or screenshot other than the docs' example `45.52252, -122.69120` and the fixtures' `45.0, -122.0`.
- Every commit ends with the trailer block from the repo's `CLAUDE.md` (Assisted-by / AI-Model / AI-Effort / AI-Role); never `Co-Authored-By`. Docs follow "Writing docs" in `docs/development/contributing.md`; `mkdocs build --strict` passes. Public text describes the pose's use as "placing the recorded paths on a street plan", and names no device or bench site.
- On a dev Pi: Frigate's detection, snapshots, and recording stay off. No item in this plan needs them; an event for the bench is a synthetic `frigate/events` message on the device's broker.
- Off-device checks before each commit, from the repo root in the dev venv: `python -m pytest container/node-red-tm/schema/tests script/tests tm-control/backend/tests`; for UI tasks also the pinned Node image's `npm ci && npm run build && npm test`; for docs tasks `~/.venvs/tm-docs/bin/mkdocs build --strict`.

## Review Focus

1. **A half-filled form:** a height with no tilt or distance, a tilt of 0 or 90, a distance of 0, a tilt with no height. The values given are saved, the one that can't be worked out is empty, and nothing divides by zero. Tests in Task 13 (`test_distance_from_tilt`, `test_tilt_from_distance`, `test_without_a_height_only_the_measured_one_is_kept`) and Task 21 (`a tilt of zero shows no distance`).
2. **A file from before, or a hand edit that is wrong:** `bearing: 'ne'` with no `heading_deg` (read as 45, and the Status page says to convert it), both keys (the heading wins), `heading_deg: 400`, a number in quotes, a negative height, a mount with a space in it. A wrong value is ignored by key with a config error that holds no value, the row stores nothing for it, and the form shows it empty. Tests in Task 2 (`test_init_config_defaults_heading`, `test_init_config_defaults_reads_an_old_bearing_as_its_centre`), Task 4 (`test_the_flows_read_a_heading_as_the_control_app_does`, `test_location_warns_about_an_old_bearing_key`), Task 10 (`test_init_config_defaults_mounting_keys`), and Task 14 (`test_mountings_reads_the_file_as_the_engine_does`).
3. **Node-RED is down, slow, or answers part-way through a save.** Nothing is half saved: the save is refused and the file and the store are as they were; a row corrected before the file refused is put back; a slow "recorded" answer means the form asks. Tests in Task 15 (`test_a_save_without_nodered_changes_nothing`, `test_a_refused_file_puts_the_rows_back`, `test_an_unknown_recorded_asks`).
4. **North:** 350° to 10° is a turn of 20°, 359 and 0 are both `n`, and a drag across the top of the dial doesn't jump. Tests in Task 4 (`test_compass_point`), Task 13 (`test_a_turn_is_the_smaller_angle`), and Task 19 (`angleAt wraps at north`).
5. **Nothing starts a deployment by accident:** the upgrade (rows converted, and a file converted before Node-RED reads it or after), a database whose `deployment` table is in the legacy shape, a reset of `config.yml`, a save that changes nothing, a dry run, renaming a camera on the Cameras page. Tests in Task 1 (`test_a_needs_column_migration_is_skipped_when_it_does_not`, the drift test), Task 2 (`test_engine_keeps_a_converted_row_with_an_unconverted_file`), Task 10 (`test_engine_keeps_rows_from_before_the_columns`), Task 14 (`test_a_reset_file_gets_the_mounting_back`, `test_renaming_a_sensor_keeps_its_mounting`), and Task 15 (`test_a_dry_run_writes_nothing`, `test_saving_the_same_values_writes_nothing`).

---

# Part A: the heading in place of the bearing (PR 1)

PR 1 changes a name and a stored form, and nothing a person does: the pages keep their eight-point picks, **Modify deployment** stays, and no new fact is recorded. Tasks 5 and 6 are reviewed as a pair, because the API's renamed fields leave the UI's build failing between them.

### Task 1: tmdb: `heading_deg` in place of `bearing`

**Files:**
- Create: `container/node-red-tm/schema/migrations/0008_deployment_heading.sql`, `migrations/0009_deployment_heading_from_bearing.sql`, `migrations/0010_deployment_drop_bearing.sql`, `container/node-red-tm/schema/tests/test_0009_deployment_heading.py`
- Modify: `container/node-red-tm/schema/tmdb_migrate.py`, `README.md`, `schema.sql` (regenerated), `tests/helpers.py` (`LATEST_VERSION`), `tests/test_migrate.py`

**Interfaces:**
- Produces, the runner: a migration file whose first line is exactly `-- tmdb-migrate: needs-column <table>.<column>` is applied only to a database whose table has that column. Otherwise the runner logs `tmdb-migrate: <file>: skipped, <table> has no column <column>`, sets the version, and goes on. A first line that starts `-- tmdb-migrate:` and isn't that form is refused, as a file with `BEGIN` is.
- Produces: `deployment.heading_deg INTEGER`, the table's last column, and no `deployment.bearing`. tmdb is at version 10.
- `0008`: `ALTER TABLE deployment ADD COLUMN heading_deg INTEGER;`
- `0009` and `0010`, each with the first line `-- tmdb-migrate: needs-column deployment.bearing`:

  ```sql
  -- 0009
  UPDATE deployment SET heading_deg = CASE lower(trim(bearing, ' ' || char(9, 10, 11, 12, 13)))
      WHEN 'n' THEN 0 WHEN 'ne' THEN 45 WHEN 'e' THEN 90 WHEN 'se' THEN 135
      WHEN 's' THEN 180 WHEN 'sw' THEN 225 WHEN 'w' THEN 270 WHEN 'nw' THEN 315 END
  WHERE heading_deg IS NULL;
  -- 0010
  ALTER TABLE deployment DROP COLUMN bearing;
  ```

- Why three files and the runner's line: SQLite has no "if the column exists", and the README's legacy-shaped `deployment` table has no `bearing`. Without the line, `0009` would fail there and that unit would stay at version 8 for good. The drop is a file of its own so that a drop that fails (a view, an index, or a trigger on the device names `bearing`) leaves the rows converted at version 9, where the flows compare real headings; the runner's unit starts Node-RED even when a migration fails. `WHERE heading_deg IS NULL` keeps a heading the flows wrote at version 8. The trim takes the same characters as the other converters (a space, tab, line feed, vertical tab, form feed, and carriage return); SQLite's one-argument `trim()` takes spaces only. `DROP COLUMN`, not a table rebuild, because a rebuild from a fixed column list would also drop whatever else a drifted table holds.

- [ ] **Step 1: Check the numbers.** If `migrations/` on the branch's base already has a `0008`, these are the next three free numbers, and every number below moves with them. Say so in the commit.
- [ ] **Step 2: Write the failing tests.**
  - `test_migrate.py`: `test_a_needs_column_migration_is_applied_when_the_column_exists`; `test_a_needs_column_migration_is_skipped_when_it_does_not` (the version is set, the log has the line, the table is as it was); `test_an_unknown_runner_line_is_refused`; `test_a_skip_that_hits_a_sqlite_error_is_rolled_back` (a `sqlite3.Error` in the column lookup or the version write of a skipped file rolls back, raises `MigrationError` with the applied file's wording, and leaves `user_version` as it was). Update `test_drift_is_reported_for_an_old_deployment_table_and_left_alone`: `bearing` is no longer reported missing, `0009` and `0010` are logged as skipped, the run still exits 0 at `LATEST_VERSION`, and the table's columns end with `survey_id, location_precision, heading_deg` with its own old columns kept.
  - `test_0009_deployment_heading.py`, from a database migrated to 7:
    - `test_bearings_become_headings(bearing, heading)`: `'n'` 0, `'NE'` 45, `' e '` 90, `'se'` 135, `'s'` 180, `'sw'` 225, `'w'` 270, `'nw'` 315; a point with tabs, line feeds, vertical tabs, form feeds, or carriage returns around it gives its centre; `''`, NULL, `'null'`, `'undefined'`, `'north'`, and the number 45 all give NULL.
    - `test_the_bearing_column_is_gone_and_nothing_else_changed`: an open and a closed row keep every other value, and `columns(db, "deployment")` is the old list without `bearing`, then `heading_deg`.
    - `test_the_backup_from_before_still_holds_the_bearing`: the runner's `tmdb-v7-*` copy has the column and its text.
    - `test_a_fresh_database_has_no_bearing`.
    - `test_the_setup_view_still_reads_after_the_drop`: from an empty database and from `LEGACY_SCHEMA`, a full migrate drops `bearing` and `SELECT * FROM events_with_setup LIMIT 0` runs.
    - `test_a_row_that_already_has_a_heading_keeps_it`: from version 8, a row with a heading and a bearing keeps its heading.
    - `test_a_drop_that_fails_leaves_the_rows_converted`: a view that names `bearing` makes `0010` fail; the run exits 1 at version 9 with the heading filled.
    - `test_rows_written_before_a_failed_drop_is_retried_keep_their_heading`: a row written at version 9 keeps its heading when `0010` applies once the view is gone.
- [ ] **Step 3: Run them.** They fail.
- [ ] **Step 4: The runner, the three files, `schema.sql`, `LATEST_VERSION = 10`.** Each file's header comment says what it does, that `0009` rewrites data and `0010` drops a column, and where the old text is kept (the runner's backup).
- [ ] **Step 5: The README.** The rule on dropping a column allows `ALTER TABLE ... DROP COLUMN` for a plain column (not a key, not indexed, not named by a view, a trigger, or a constraint) and keeps the table rebuild for the rest. A rule for the `needs-column` line, with `0009` and `0010` as its example, and for putting a drop in a file of its own after the conversion. The legacy-shape example says `0002` and `0008` apply to it and `0009` and `0010` are skipped.
- [ ] **Step 6: Run** `python -m pytest container/node-red-tm/schema/tests`. The SQL compile test fails until Task 2 changes the flows; every other test passes.
- [ ] **Step 7: Commit** together with Task 2, so no commit has flows that name a column the schema lacks.

### Task 2: Node-RED reads and records the heading *(tricky)*

**Files:**
- Modify: `container/node-red-tm/data/flows.json` (nodes `94136e5a6f092bb6`, `689b64c16a889e0a`, `f5e4484aeb11facf`, `94dad283c8f696f4`, `696c3a7b0b83f7b5`, `c25adb99d55eb890`, `5d5d7f4aabe982c2`)
- Test: `script/tests/test_node_red_flows.py`

**Interfaces:**
- Produces, "init config defaults": after it runs, the top-level `deployment` and every enabled sensor's `deployment` have `heading_deg`, a whole number from 0 to 359 or `null`, and no `bearing` key. The rule for one block:
  - a `heading_deg` that is a whole number from 0 to 359 is kept;
  - a missing, `null`, or `''` one takes the centre of the block's `bearing` when that is one of the eight after trimming and lower-casing (item 2), else `null`;
  - anything else (360, -1, 40.5, `'40'`, `true`) is `null`, with `node.error(text, msg)` and the text `` `${path}.heading_deg isn't a whole number from 0 to 359` ``, where `path` is `deployment` or `sensors.<type>.<name>.deployment`. No value is in the text.
  - A sensor's block that has either key settles its own heading, so a blank one still overrides the top level's, as a blank bearing did. A block with neither takes the top level's.
  - An old `bearing` gives no error here. The Status page's Location check reports it (Task 4).
- Produces, the engine: `headingOf(value)` is the value when it is a whole number from 0 to 359, else `null` (the engine's tests call it without the defaults node). `want.heading_deg`. `sameHeading` is `headingOf(row.heading_deg) === want.heading_deg`, used where `sameBearing` was. `legacyBearing` and its branches in `rewriteRow` and `keepRow` go: the migration turned those rows' `'null'` and `'undefined'` into NULL. The parameters are `$heading_deg` where `$bearing` was.
- Produces, SQL: the five statements name `heading_deg` where they named `bearing`, in the same position.

- [ ] **Step 1: Write the failing tests.**
  - Update the pinned texts and helpers: `ENGINE_SQL`, `OPEN_ROWS_SQL`, `ROW_KEYS`, `SURVEY_SQL`, `DEPLOYMENT_ROW`; `engine_sensors` (camera 0, radar 180), `open_row`, `camera_row`, `radar_row` take a heading; `new_device_config` passes `tmsetup_heading_deg`.
  - `test_init_config_defaults_heading(top, sensor, expected, errors)`, parametrized: no key anywhere is `null`; a top-level 90 reaches a sensor with no block and one whose block has neither key; a sensor's own 40 wins; a sensor's blank `heading_deg` under a top-level 90 is `null`; each bad value is `null` with exactly one error that names the path, holds no value, and was given with `msg`; 0 and 359 pass.
  - `test_init_config_defaults_reads_an_old_bearing_as_its_centre`: `bearing: 'NE'` with no `heading_deg` is 45 at the top level and in a sensor's block, with no error; `bearing: 'ne'` beside `heading_deg: 100` is 100; `bearing: 'up'` is `null`; no block keeps a `bearing` key afterwards.
  - `test_engine_keeps_a_converted_row_with_an_unconverted_file`: through the defaults node and the engine, an open row with heading 45 and a file that still says `bearing: 'ne'` write nothing.
  - Rename and retarget: `test_init_config_defaults_allows_a_blank_heading`, `test_engine_starts_a_deployment_on_a_new_survey_or_heading` (also from `null` to a value and back), `test_engine_adopts_only_when_the_heading_matches`, `test_engine_without_a_survey_id_holds_a_heading_change`.
  - Remove `test_engine_treats_blank_and_upper_case_bearings_as_equal`, `test_engine_stores_a_legacy_blank_bearing_as_blank`, and `test_engine_adopts_a_row_with_a_legacy_blank_bearing`, and say in the commit that the migration's tests now cover those rows.
- [ ] **Step 2: Run them.** They fail.
- [ ] **Step 3: "init config defaults",** then the engine, then the five SQL texts.
- [ ] **Step 4: Run** `python -m pytest script/tests container/node-red-tm/schema/tests`. PASS, including the SQL compile test.
- [ ] **Step 5: Commit** Tasks 1 and 2 ("Record a sensor's heading in degrees in place of its bearing").

### Task 3: The heading correction's endpoint, and the upload's key

**Files:**
- Modify: `container/node-red-tm/data/flows.json` (nodes `869932985ebcad5c`, `0f1b996794be419a`, `ac9c1f431f070f3a`, `0aae1d3d3e4c7d3e`, `c6ff73faf6fa9e98`, `9b0f7197fe82bbfa`)
- Modify: `script/devpi/tests/test_web.py` (`TM_INTERNAL_WRITES`), `script/devpi/README.md`
- Test: `script/tests/test_node_red_flows.py`

**Interfaces:**
- Produces: `POST /tm-internal/deployments/:id/heading`, body `{"heading_deg": <a whole number from 0 to 359> | null}`. Answers 204; 400 `{"error": "bad_request", "detail": "deployment_id" | "heading_deg"}` for a malformed id, a missing key, text, a fraction, a boolean, 360, or -1. The nodes are renamed "tm-internal: validate heading correction", "rewrite deployment heading" (`UPDATE deployment SET heading_deg = $heading_deg WHERE id = $id;`), and "tm-internal: answer heading correction". The old path is gone.
- Produces, the upload: telemetry rows carry `heading_deg`, since they are the engine's rows (the sample in the node's comment is updated). The `deployments` attribute's template writes `"heading_deg": "{{heading_deg}}"`, text like its neighbours, `""` when unset.

- [ ] **Step 1: Write the failing tests.** `TM_INTERNAL_PATHS`, `TM_INTERNAL_METHODS`, and `VALIDATORS` name the new path and validator. `test_heading_correction_validates_the_id_and_the_heading` takes the cases above. `GATE_ROW` and `GATE_ATTRIBUTES` hold `heading_deg`. New: `test_the_deployments_attribute_carries_the_heading` (the template rendered for a sensor at 45 and for one with none: `"45"` and `""`), and `test_only_the_config_reader_still_says_bearing` (of every node in `flows.json`, only `94136e5a6f092bb6` holds the word).
- [ ] **Step 2: Run them.** They fail.
- [ ] **Step 3: Edit the six nodes,** keeping their ids, wiring, and the catch's scope.
- [ ] **Step 4: The device tests' list and the README's row** name the new path.
- [ ] **Step 5: Run** `python -m pytest script/tests`. PASS.
- [ ] **Step 6: Commit** ("Correct a deployment's heading, and upload it, in degrees").

### Task 4: The control app's compass helpers, the Status check, `migrate`, and the installer's value

**Files:**
- Modify: `tm-control/backend/tm_control/modules/location/coordinates.py`, `modules/apps/contracts.py`, `core/migrate.py`, `cli.py`
- Modify: `script/ansible/roles/tmsetup/defaults/main.yml`, `container/node-red-tm/config/config.yml.j2`, `container/node-red-tm/node-red-tm.container.j2`
- Test: `tm-control/backend/tests/test_coordinates.py`, `test_contract_checks.py`, `test_location_migration.py`, `test_tm_control_cli.py`, the fixtures `node_red_config_ok.yml`, `node_red_config_old_template.yml`, `node_red_config_v071_bearing.yml`, and `node_red_config_dev_bearing.yml`; `script/tests/test_tmsetup_templates.py`, `script/tests/test_tmsetup_tasks.py`, `script/tests/test_node_red_flows.py`

**Interfaces:**
- Produces, `coordinates.py` (added; `BEARINGS` and `normalize_bearing` stay until Task 5 removes their last users):

  ```python
  POINTS = ("n", "ne", "e", "se", "s", "sw", "w", "nw")
  HEADING_MAX = 359

  def valid_heading(value) -> bool             # an int that isn't a bool, from 0 to HEADING_MAX
  def point_centre(point) -> int | None        # trimmed and lower-cased; None for anything that isn't one of POINTS
  def compass_point(heading_deg: int) -> str   # item 2
  def facing(heading_deg: int | None) -> str   # "NE (40°)"; "" for None
  def read_heading(block) -> int | None        # one deployment block, by Task 2's rule; never raises; None for a block that isn't a mapping
  ```

- Changes, `contracts.py`: its own `BEARINGS` and `_bearing_ok` go. The Location check (`config.deployment`) reports, for the top level and each enabled sensor's own block: an error `"<path>.heading_deg isn't a whole number from 0 to 359, or empty"` for a value `valid_heading` refuses; and a warning for a `bearing` key that holds a value: `"<path>.bearing is the old name for which way a sensor faces. Node-RED converts it to heading_deg when it next starts: restart Node-RED, or write heading_deg (whole degrees from north) in its place."`
- Produces, `core/migrate.py`: `run_node_red_headings(config_path, dry_run=False)`, behind a new option `tm-control migrate --node-red-headings <config.yml>` that needs no secrets directory. It does only the bearing changes; `run_node_red` (the installer's `--node-red-config`) never touches a `bearing` and places `database_precision` after `survey_id`, else `heading_deg`, else `bearing`. For the top-level `deployment` block and every sensor's, enabled or not:
  - a `bearing` key becomes `heading_deg` in the same position, with its comment kept: the centre for one of the eight, blank for a blank one;
  - a `bearing` that is neither is left as it is, with a warning that names the key's path and no value;
  - a blank `heading_deg` beside one of the eight takes its centre, as Node-RED reads such a block, and the `bearing` goes;
  - a `bearing` beside a `heading_deg` that holds a value, or a blank `bearing` beside a blank one, is removed.
  - It reports `(would, done)` like the other steps, says `up to date` when there is nothing to do, and saves the file once, with its backup, as today.
- Changes, `node-red-tm.container.j2`: a second `ExecStartPre=-`, after the tmdb one, runs `runuser -u <code owner> -- timeout 60 /usr/local/bin/tm-control migrate --node-red-headings <codedir>/node-red-tm/config/config.yml`. The installer never passes `--node-red-headings`.
- Changes, the installer: `tmsetup_heading_deg: ''` takes the place of `tmsetup_bearing`, and the template writes `heading_deg: {{ tmsetup_heading_deg }}` where it wrote `bearing`. `-C` never offered the old one.

- [ ] **Step 1: Write the failing tests.**
  - `test_coordinates.py`: `test_compass_point` (item 2's table, plus 112 and 113, 157 and 158, 202 and 203, 247 and 248, 292 and 293); `test_point_centre` (`ne` 45, `' N '` 0, `''` and `'north'` None); `test_valid_heading` (0 and 359 yes; 360, -1, 40.5, `'40'`, `True`, None no); `test_facing`; `test_read_heading` (Task 2's cases).
  - `script/tests/test_node_red_flows.py`: `test_the_flows_read_a_heading_as_the_control_app_does`: one table of blocks through "init config defaults" and through `read_heading`, with the same answers.
  - `test_contract_checks.py`: retarget the three bearing tests to headings (`test_location_checks_each_enabled_sensors_own_heading`, `test_location_ignores_a_disabled_sensors_heading`); `test_location_warns_about_an_old_bearing_key` (the path, no value, status `warn`); `test_location_says_nothing_about_a_blank_bearing_key`. `test_app_checks.py`'s sample of Node-RED's old "Invalid bearing value" line becomes the new text.
  - `test_location_migration.py`, through `run_node_red_headings`: `test_migrate_writes_heading_deg_in_place_of_bearing` (the top level and a sensor; the key's position and comment kept; a backup made); `test_migrate_converts_a_blank_bearing_to_a_blank_heading`; `test_migrate_leaves_a_bearing_it_cannot_read_and_warns_by_key`; `test_migrate_removes_a_bearing_beside_a_heading`; `test_migrate_twice_changes_nothing`; `test_migrate_dry_run_says_what_it_would_do`; `test_the_start_converts_every_kind_of_bearing`; `test_the_start_does_none_of_the_installers_steps`; `test_the_start_has_nothing_to_do_on_a_file_with_no_bearing`; `test_the_start_reads_no_secrets`. `test_migrate_ignores_a_sensor_deployment_with_only_a_bearing` becomes `test_migrate_converts_a_sensor_deployment_with_only_a_bearing`. Through `run_node_red`: `test_the_installer_pass_leaves_every_kind_of_bearing_alone` (byte-identical, `up to date`); `test_the_installer_pass_does_its_other_steps_and_keeps_every_bearing_line`; `test_the_installer_pass_places_database_precision_after_a_bearing_it_leaves`; and the guard, `test_the_installer_pass_changes_no_key_a_running_engine_compares`, over a v0.7.1-shaped and a dev-shaped file (`bearing` and `survey_id` unchanged in every block).
  - `test_tm_control_cli.py`: `--node-red-headings` alone is accepted and reads no secrets directory; its dry run; the "give at least one of" text names it.
  - `script/tests`: the rendered Node-RED unit has exactly two `ExecStartPre=` lines, both starting `-`, the second running `migrate --node-red-headings` on the config path as the code owner; `entered_secrets.yml`'s argv never holds `--node-red-headings`.
  - `test_tmsetup_templates.py`: the template renders `heading_deg: 90` for 90 and a blank value for `''`, and no `bearing`.
- [ ] **Step 2: Run them.** They fail.
- [ ] **Step 3: Implement,** in the order of Interfaces.
- [ ] **Step 4: Run** the backend tests and `script/tests`. PASS.
- [ ] **Step 5: Commit** ("Convert config.yml's bearing to a heading, and check it").

### Task 5: The control app's store, file, and API *(tricky)*

**Files:**
- Modify: `tm-control/backend/tm_control/core/state.py`, `modules/location/places.py`, `config.py`, `router.py`, `reconcile.py`, `coordinates.py`, `adapters/nodered.py`, `fake.py`, `modules/cameras/router.py` (a docstring)
- Modify: `tm-control/ui/src/api/openapi.json`, `tm-control/ui/src/api/schema.d.ts` (regenerated)
- Test: `tm-control/backend/tests/test_state.py`, `test_places.py`, `test_location_config.py`, `test_reconcile.py`, `test_api_surveys.py`, `test_api_cameras.py`, `test_api_cameras_reference.py`, `test_nodered_adapter.py`, `test_openapi_document.py`, `test_coordinates.py`

**Interfaces:**
- Produces, `core/state.py`, migration 5. Both tables are rebuilt, because `survey_corrections.field` has a `CHECK` that names `'bearing'`:
  - `survey_sensors (survey_id, sensor_type, sensor_name, heading_deg INTEGER CHECK (heading_deg BETWEEN 0 AND 359), map_block_ref, map_side)`, with the key, the reference, and the `map_side` check that `survey_bearings` had. Its rows are copied `ORDER BY rowid`, so each place keeps its order, with the bearing converted by item 2. `survey_bearings` is dropped.
  - `survey_corrections` with `CHECK (field IN ('location', 'heading_deg'))`. Its rows keep their ids; a row whose field was `'bearing'` has the new field, and its old and new values become the centre as text, or NULL.
- Produces, `places.py`: `class SensorHeading(BaseModel)` with `sensor_type: str`, `sensor_name: str`, `heading_deg: int | None`, in place of `Bearing`; `Survey.headings: list[SensorHeading]`; `Places.set_heading(survey_id, sensor_type, sensor_name, heading_deg: int | None)`; `create` and `update_planned` take `headings`; `record_correction` is called with `field="heading_deg"`.
- Produces, `config.py`: `sensors() -> list[SensorHeading]`, read with `read_heading` and the copy-down of Task 2; `blank_headings()` (the enabled sensors that read as `None` and hold no value the reader refused); `set_sensor_heading(sensor_type, sensor_name, heading_deg: int | None)`, which writes a plain number or a blank, removes the block's `bearing` key, and otherwise keeps `set_sensor_bearing`'s behaviour (no block is added for a blank under a blank top level; `ValueError` for a value `valid_heading` refuses; `KeyError`; `ConfigError("invalid")`). `set_place` and `set_survey_id` place `survey_id` after `heading_deg`, or after `bearing` in a file not yet converted.
- Produces, `router.py`:

  | Was | Is |
  |---|---|
  | `SurveyIn.bearings`, `DeployIn.bearings`, `ImportRow.bearings`, `SurveyOut.bearings` | `.headings: list[SensorHeading]` |
  | `PlacesState.sensors: list[Bearing]` | `list[SensorHeading]` |
  | `DeploymentOut.bearing: str` | `heading_deg: int \| None` |
  | `BearingCorrection {bearing, reason}` | `HeadingCorrection {heading_deg: int \| None, reason: str \| None}` |
  | `POST /{survey_id}/deployments/{deployment_id}/bearing`, `correct_bearing`, audit `survey.correct_bearing` | `.../heading`, `correct_heading`, audit `survey.correct_heading` |

  - The API takes whole numbers only: 422 `validation` with field `headings` and "A heading is a whole number from 0 to 359, or blank." The other three messages say "heading" where they said "bearing".
  - The CSV import alone also takes a compass point in a sensor's column and stores its centre. Its refusal: "The heading for <column> must be a whole number from 0 to 359, a compass point (n, ne, e, se, s, sw, w, nw), or blank."
  - `_wait_for_rows` matches a row by its `heading_deg`. `_write_heading` and `_put_row_back` keep the order: the row first, then the file.
- Produces, `adapters/nodered.py`: `NodeRed.correct_heading(deployment_id: str, heading_deg: int | None)`, `POST /deployments/<id>/heading`.
- Produces, `fake.py`: `FakeNodeRed`'s rows hold `heading_deg`, its engine compares it, and `correct_heading` refuses what Task 3's validator refuses.
- Changes, `reconcile.py`: the restore uses `blank_headings` and `set_sensor_heading`; nothing else changes. `coordinates.py` loses `BEARINGS` and `normalize_bearing`.

- [ ] **Step 1: Write the failing tests.**
  - `test_state.py`: `test_migration_five_turns_bearings_into_headings` (a version 4 store with a place whose sensors have `'ne'`, `''`, and `'NW'`, in that order, a `map_side`, and one correction of each field: the rows come back as 45, NULL, 315 in the same order with the map columns kept; the bearing correction reads `heading_deg`, with `'n'` and `'e'` now `'0'` and `'90'`; the location correction is as it was; `survey_bearings` is gone; a heading of 360 is refused by the table).
  - Rename and retarget every test the old names appear in, keeping what each proves: in `test_api_surveys.py` (`test_deploy_body_headings_win_and_are_checked`, `test_deploy_with_blank_headings_adds_no_block_to_the_sensors`, `test_correct_heading_on_an_open_row_updates_the_file`, `test_correct_heading_on_a_closed_row_leaves_the_file`, `test_a_file_changed_while_saving_a_heading_puts_the_row_back`, `test_correct_heading_refusals`), `test_location_config.py` (its seven), `test_places.py` (its three), `test_reconcile.py`, `test_api_cameras.py`, `test_nodered_adapter.py`, `test_openapi_document.py` (the path).
  - New: `test_the_api_refuses_a_compass_point` (a deploy with `"heading_deg": "ne"` is 422); `test_the_csv_takes_a_compass_point_or_degrees` (`ne` and `45` both store 45; `400` and `north` are refused by column name); `test_sensors_reads_an_old_bearing_key` and `test_setting_a_heading_removes_the_old_key` in `test_location_config.py`; `test_places_state_lists_each_sensors_heading`; `test_no_bearing_in_the_api` (the OpenAPI document has no name or path with the word).
- [ ] **Step 2: Run them.** They fail.
- [ ] **Step 3: Implement,** then regenerate the API files.
- [ ] **Step 4: Run** `python -m pytest tm-control/backend/tests script/tests`. PASS. The UI's build fails from this commit until Task 6's; that is expected, and nothing is pushed between them.
- [ ] **Step 5: Commit** ("Keep each sensor's heading in the control app's store and API").

### Task 6: The pages

**Files:**
- Create: `tm-control/ui/src/modules/location/heading.ts`, `HeadingPick.vue`, `tm-control/ui/tests/heading.spec.ts`, `heading-pick.spec.ts`
- Modify: `tm-control/ui/src/modules/location/coordinates.ts`, `LocationPage.vue`, `PlaceDetails.vue`, `CorrectDialog.vue`, `DeployReview.vue`, `PlaceForm.vue`, `ImportPlaces.vue`
- Modify: `tm-control/ui/tests/coordinates.spec.ts`, `correct-dialog.spec.ts`, `deploy-review.spec.ts`, `import-places.spec.ts`, `location-page.spec.ts`, `place-details.spec.ts`, `place-form.spec.ts`, `tm-control/ui/README.md`

**Interfaces:**
- Produces, `heading.ts`:

  ```ts
  export const POINTS = ['n', 'ne', 'e', 'se', 's', 'sw', 'w', 'nw'] as const
  export function compassPoint(heading: number): string           // item 2
  export function pointCentre(point: string): number | null
  export function facing(heading: number | null): string          // "NE (40°)"; "Not set" for null
  export function headingChoices(current: number | null): { value: number | null; title: string }[]
  ```

  `headingChoices` is the eight centres titled N to NW, then `{ value: null, title: 'Not set' }`. When `current` is a heading that isn't a centre, it comes first, titled by `facing`, so opening a pick never changes a measured heading.
- Produces, `HeadingPick.vue`: one `v-select` over `headingChoices`, with `v-model` a `number | null` and the props `label?: string`, `ariaLabel?: string`, `density?`. It takes the place of the three selects written out in `CorrectDialog`, `DeployReview`, and `PlaceForm`.
- Changes, `coordinates.ts`: `BEARINGS` and `bearingTitle` go; `startingBearings` becomes `startingHeadings`, with the same rule.
- Changes, the words: "Bearing, <sensor>" becomes "Facing, <sensor>" on the card and in the place form; a deployment's line reads "Facing NE (45°)" or "No heading set"; **Correct bearing** becomes **Correct heading**, and its dialog's text says "heading" where it said "bearing"; the deploy review says "Change a heading to start a new one."; the import's help reads "with the way it faces: a compass point (n, ne, e, se, s, sw, w, nw), whole degrees from north (0 to 359), or blank."

- [ ] **Step 1: Write the failing tests.**
  - `heading.spec.ts`: `compassPoint` and `pointCentre` over the table of `test_compass_point`; `facing` for 40, 0, and null; `headingChoices` has nine items for a centre or null, and ten, the measured one first, for 40.
  - `heading-pick.spec.ts`: `choosing a point gives its centre`; `Not set gives null`; `a measured heading is shown and kept until another is chosen`.
  - Retarget each spec's cases to headings, keeping what each proves: the card's lines, the correction's body (`{ heading_deg: 90, reason }`, and `null` for Not set), the review's body (`{ headings }`) and its "New deployment starts" and "Unchanged" lines, the place form's body, the import's refusal text.
- [ ] **Step 2: Run them.** They fail.
- [ ] **Step 3: Build it.** No new package, and no change to what any page lets a person do.
- [ ] **Step 4: The README:** the wireframes and the prose say "Facing" and "heading"; a note that `HeadingPick` is the one eight-point pick and why it shows a measured heading.
- [ ] **Step 5: Run** the pinned Node image's `npm ci && npm run build && npm test`. PASS.
- [ ] **Step 6: Screenshot review** in fake mode at 375 px and 1280 px: the Location card, the deploy review, the place form, a deployment's line with **Correct heading**, and its dialog.
- [ ] **Step 7: Commit** ("Show and pick headings on the Location page").

### Task 7: Docs, and the plan's public copy

**Files:**
- Modify: `docs/configuration/node-red-config.md`, `docs/data-and-payloads/data-overview.md`, `docs/data-and-payloads/integrations.md`, `docs/use/location.md`, `docs/use/device-health.md`, `docs/setup-guide.md`, `docs/build-your-own-device-diy/update.md`, `docs/development/tm-control.md`, `CONTRIBUTING.md`, `CLAUDE.md`
- Modify: the screenshots under `docs/assets/images/` that show "Bearing"
- Create: `design/plans/2026-11-23-mounting-form.md`

- [ ] **Step 1: `node-red-config.md`.** `heading_deg` in place of `bearing` in the `deployment` table and in the cameras' and radars' rows: whole degrees clockwise from true north, 0 to 359, empty by default. A short "If your file still says `bearing`" part: Node-RED converts it when it starts; until then a compass point is read as its centre (the table of eight), and the Status page says to restart Node-RED.
- [ ] **Step 2: `data-overview.md`.** The `deployment` table's row is `heading_deg`. A note for anyone with older exports: before this release the column was `bearing`, a compass point, and the upgrade wrote each as its centre. The sentence on when a new row starts says "heading".
- [ ] **Step 3: `integrations.md`.** The deployment telemetry and the `deployments` attribute carry `heading_deg` where they carried `bearing`. Say plainly that a dashboard or a script that read `bearing` must change.
- [ ] **Step 4: `location.md`.** **Correct heading**; the section "Correct a wrong location or heading", with every link to its old anchor updated; the review's words; the import's column help. Retake the screenshots whose words changed, at the docs' example place.
- [ ] **Step 5: The other pages.** `device-health.md`, `setup-guide.md`, and `update.md` say "heading". `CONTRIBUTING.md`'s advice on sharing a `config.yml` names the heading. `docs/development/tm-control.md`: the routes, `survey_sensors`, the internal endpoint. `CLAUDE.md`: `survey_sensors`, `POST /tm-internal/deployments/:id/heading`, "sensor headings", and that `config.yml`'s `bearing` is read only as an old key.
- [ ] **Step 6: This plan's copy** is committed under `design/plans/`, after the docs, as its own commit.
- [ ] **Step 7: Run** every off-device check, `mkdocs build --strict`, and `git grep -i bearing`. What is left is the old-key reader in the flows and in `coordinates.py`, `migrate`, the migrations and their tests, the docs' "still says `bearing`" part, older plans under `design/`, and a comment about the map's rotation. PASS.
- [ ] **Step 8: Commit** the docs, then the plan's copy.

### Task 8: Pi plan and PR 1

- [ ] **Step 1: Pi plan,** as a logged `tmdev check` on a bench unit marked `pii_free`, after a whole `tmdev deploy <host>` (the installer's `migrate` step and the pod both matter). Frigate's detection stays off throughout; say so in the check.
  1. Before the deploy: note the open deployment ids, each sensor's `bearing` in `config.yml`, and `python3 -c 'import sqlite3; print(sqlite3.sqlite_version)'` (3.40 or later).
  2. After it: the device suite passes; `tmdb_migrate.py --check` says up to date at version 10; the journal has the three files applied and names the backup; `config.yml` has `heading_deg` with each point's centre and no `bearing`, with a backup beside it.
  3. The open deployment ids are the same as before, and each row's `heading_deg` is its old point's centre: the upgrade started no deployment. `config.yml` holds `bearing` until node-red-tm restarts and `heading_deg` after; node-red-tm's journal shows the `--node-red-headings` pre-start line's status and how long it took.
  4. The Location page shows "Facing NE (45°)" (or the unit's own), and **Correct heading** on an ended deployment changes that row and nothing else.
  5. By hand in `config.yml`, put `bearing: 'e'` in place of a sensor's `heading_deg`: after Node-RED reloads, a new deployment has 90, and the Status page's Location check warns about the old key by its path and says to restart Node-RED. Restart it: the file has `heading_deg: 90`, and the deployment id stays. Put it right.
  6. By hand, `heading_deg: 400`: the config check names the key and no value, and the new row has no heading. Put it right.
  7. **Manual, the maintainer's:** with sharing on to a test server, the deployment telemetry and the attribute arrive with `heading_deg`.
- [ ] **Step 2: Every off-device check once more** on the final branch; `git grep` the branch for device names and any coordinate that isn't allowed.
- [ ] **Step 3: PR 1's text,** the template filled in, "Part of" the issue. The release note: "Which way a sensor faces is now a heading in whole degrees (`heading_deg`, 0 to 359, clockwise from north) in place of one of eight compass points (`bearing`). The upgrade converts the database and `config.yml`: north-east becomes 45, and so on. **Breaking:** shared data and the `deployment` table carry `heading_deg`, not `bearing`, so a dashboard, export, or script that read `bearing` must change." Also: the Docs list; the Pi plan's results; that the migration is destructive (it rewrites `deployment` rows and drops a column, with the old text in the runner's backup) and how long it took; the runner's new line; and the AI-assistance section. The maintainer reads the commit messages and the PR text before any push.

---

# Part B: the records (PR 2)

### As built

Where the build of this part differs from what the tasks below say, or settles what they leave open. A later reader should take these in place of the task text.

- **The sharing notice isn't changed here.** Item 12 and Task 12's last steps speak of the notice. Its wording is the maintainer's, so this PR leaves `NOTICE.md` as it is. The docs describe the gate and what is sent, and quote no notice sentence that isn't there.
- **The four keys belong under each sensor's `deployment:` block.** "Init config defaults" copies the top-level `deployment:` keys down to a sensor key by key, as it always did, and the control app reads the file the same way. A sensor that sets only its tilt takes the height from the top level, if there is one there. The installer writes none of the five.
- **A limit is checked on the value after rounding.** Tilt is rounded to one decimal and lengths to two, half away from zero, and then the limit applies: 90.04 degrees is 90 and passes, 0.004 m is 0 and fails. `mount` is case-sensitive: `Pole` is refused.
- **A mount the file holds passes as it is.** The API takes one of the three usual mounts, or the key `config.yml` already holds for that sensor, which may be any key the file allows. So a key typed by hand can be sent back unchanged or cleared, and any other key is refused.
- **The worked-out one of tilt and distance is the API's.** Whatever a request sends for the one that isn't `measured` is ignored, and the answer holds the worked-out value.
- **A small change of height can suggest "moved".** When the distance is the measured one, the tilt worked out from it is compared old against new, so a height change that moves that tilt by 5 degrees or more makes "moved or turned" the answer chosen in advance, as a measured tilt that changes by that much does.
- **Editing a planned place keeps each sensor's stored mounting.** Changing a planned place's description, location, or headings doesn't clear what a sensor has stored there.
- **`DeploymentOut` always carries the four.** The fields are present and null when nothing was recorded, so a client never has to tell a missing key from an empty one.
- **Both mounting routes run the reconcile first.** `GET` and `PUT /surveys/{id}/mounting` run it as `GET /surveys` does, before taking the lock, so a file that `tmsetup.sh -f` reset gets the place's id, headings, and the mounting saved for this use back before it is read. A save whose file no longer names the place once it holds the lock is refused with 409 `config_changed`. Without this, a save into a reset file would take its empty values for the place's and write them to the open rows and the store.
- **Deploy here and Correct location run the reconcile first too.** In a reset file, Correct location for the place in use wrote the id beside blank headings and no mounting, so Node-RED started deployments with none of the place's values, and Deploy here left the template's precision to be kept as the operator's choice. Both routes now run it before taking the lock, and Correct location refuses with 409 `config_changed` when the file no longer names the place in use once it holds the lock. A deploy is meant to change the id, so it has no such check.
- **A save writes each sensor the request names whose values differ from the file or from the store.** Values that came from a hand edit of the file become the place's stored mounting once a save writes them. A sensor the request leaves out isn't written: not its row, its block in `config.yml`, or its stored mounting.
- **A move records none of the four (the maintainer's change, 2026-11-25; item 10 and Decision 6).** Putting a place in use marks each of its store rows that holds any of the four unconfirmed (state migration 7; every row from before stays confirmed). Deploy here removes the four from every enabled sensor's own block, and a reset gets back only a confirmed row's four. `GET` and `PUT .../mounting` give each sensor `previous`: null, or the four and `measured` as stored. The deploy's answer lists in `previous` the sensors whose values wait, and is empty when none wait and when the place didn't change. A save that writes a sensor confirms its row; Correct heading changes the heading and leaves the mark. There is no way to dismiss the values.
- **A place the upgrade puts in use gets its sensors' headings.** When the reconcile puts in use a place that already exists (one the upgrade imported, or one a hand edit of `survey_id` names), each enabled sensor the place has no row for gets one with the file's heading. A row it has is never changed, and only the store is written, so no deployment starts. Without it, a `tmsetup.sh -f` on an upgraded unit before any Deploy here or save gave no heading back. The gap is on `dev` too; it was found in the code, not on a device.
- **A refusal about one sensor says which.** A 422 for a value carries `detail.field` and `detail.index`, the position of the sensor in the request.
- **A failed correction call puts that row back too.** The call may have changed the row before it timed out, so the rows already corrected and the one whose call failed all get their old values.

### Task 9: The other four columns on `deployment`

**Files:**
- Create: `container/node-red-tm/schema/migrations/0011_deployment_mounting.sql`, `container/node-red-tm/schema/tests/test_0011_deployment_mounting.py`
- Modify: `container/node-red-tm/schema/schema.sql` (regenerated), `container/node-red-tm/schema/tests/helpers.py` (`LATEST_VERSION`)

**Interfaces:**
- Produces: `deployment.pitch_deg REAL`, `height_m REAL`, `view_distance_m REAL`, `mount TEXT`, in that order after `heading_deg`. tmdb is at version 11.

- [ ] **Step 1: Check the number.** If `migrations/` on the branch's base already has a `0011`, this file takes the next free number, and every "11" below moves with it. Say so in the commit.
- [ ] **Step 2: Write the failing tests** in `test_0011_deployment_mounting.py`, after the pattern of `test_0005_time_stopped.py`:
  - `test_0011_adds_the_four_columns_and_rewrites_no_row`: a database migrated to 10 with two deployment rows (one open, one closed) is migrated; `columns(db, "deployment")` ends with `heading_deg` and the four, with those declared types; both rows have NULL in all four and every other value as it was; `user_version` is `LATEST_VERSION`.
  - `test_0011_applies_to_a_legacy_shaped_deployment_table`: from `LEGACY_SCHEMA`, a full migrate ends at `LATEST_VERSION` with the four columns present.
- [ ] **Step 3: Run them.** `python -m pytest container/node-red-tm/schema/tests -k 0011` fails: no such migration.
- [ ] **Step 4: Write the migration:** four `ALTER TABLE deployment ADD COLUMN` statements and a header comment that says what each column holds, its unit, that every existing row keeps NULL, and that no row is rewritten. Regenerate `schema.sql` with `python3 container/node-red-tm/schema/tmdb_migrate.py --dump-schema`. Set `LATEST_VERSION = 11`.
- [ ] **Step 5: Run** `python -m pytest container/node-red-tm/schema/tests`. PASS.
- [ ] **Step 6: Commit** ("Add the mounting columns to the deployment table").

### Task 10: Node-RED reads the other four from `config.yml` and records them *(tricky)*

**Files:**
- Modify: `container/node-red-tm/data/flows.json` (nodes `94136e5a6f092bb6`, `689b64c16a889e0a`, `f5e4484aeb11facf`, `696c3a7b0b83f7b5`, `5d5d7f4aabe982c2`)
- Test: `script/tests/test_node_red_flows.py`

**Interfaces:**
- Consumes: Task 2's heading, already read, compared, and recorded.
- Produces, "init config defaults": after it runs, every enabled sensor's `deployment` object also has the keys `pitch_deg`, `height_m`, `view_distance_m`, `mount`, each a valid value or `null`. Numbers are rounded as in item 1.
- Produces, the engine: each row object it builds or passes on (`currentDeployment`, `updatedDeployment`) has the five; "insert deployment" takes `$pitch_deg, $height_m, $view_distance_m, $mount` after `$location_precision`.
- Produces, SQL: "query open deployments" and "read survey deployments" select the four after `location_precision`. "rewrite deployment" and "close deployment" are unchanged.

- [ ] **Step 1: Write the failing tests.**
  - Update the pinned texts: `ENGINE_SQL["insert deployment"]`, `OPEN_ROWS_SQL`, `ROW_KEYS`, `SURVEY_SQL["/tm-internal/deployments"]`. Give `open_row` four more optional arguments, default `None`.
  - `test_init_config_defaults_mounting_keys(given, expected, errors)`, parametrized over a camera's `deployment` block with `heading_deg: 40`:
    - no other key: the four `None`, no error;
    - `pitch_deg: 14.94, height_m: 2.134, view_distance_m: 7.951, mount: 'tripod'`: `14.9, 2.13, 7.95, 'tripod'`, no error, and the heading still 40;
    - each of `pitch_deg` 91, -1, `'15'`, `true`; `height_m` 0, 101, `'2'`; `view_distance_m` -1, 1001; `mount` `'Tripod!'`, a 33-character key, 5: that key `None`, the others kept, and exactly one error;
    - Every error names the key's path (`sensors.cameras.picam_h265.deployment.height_m`), holds no value, and was given with a `msg` (the harness reports that as the third item of the log entry).
  - `test_init_config_defaults_limits_are_inclusive`: 0 and 90, 0.01 and 100, 0 and 1000 all pass.
  - `test_engine_keeps_rows_from_before_the_columns`: open rows with no mounting keys at all, and sensors with none, write nothing.
  - `test_engine_keeps_a_row_whose_mounting_matches`: row and file both `40, 15, 2.13, 7.95, 'tripod'` (the file's tilt as `15.0`): nothing written.
  - `test_engine_starts_a_deployment_when_a_mounting_value_changes(key, row_value, file_value)`, over each of the five, including a value set to `None` and a `None` set to a value: one close, one insert, and the insert's parameters hold the file's five.
  - `test_engine_adopts_only_when_the_mounting_matches_too`: a row with no survey, the same heading, and another height is closed and a new one inserted, not rewritten.
  - `test_engine_without_a_survey_id_holds_a_mounting_change`: with no `survey_id` in the file, a changed height writes nothing.
  - `test_engine_rows_for_thingsboard_carry_the_mounting`: every row in output 4 has the five keys.
- [ ] **Step 2: Run them** (`python -m pytest script/tests/test_node_red_flows.py -k "mounting or engine"`). They fail.
- [ ] **Step 3: "init config defaults".** In the loop over enabled sensors, after the heading is settled in both branches (the sensor has a `deployment` block, or gets a copy of the top-level one), normalise the four on the sensor's `deployment` object: a missing, `null`, or `''` value is `null` with no error; a value outside item 1 is `null` with `node.error(text, msg)`. The rounding is `Number(value.toFixed(places))`, as the engine rounds coordinates.
- [ ] **Step 4: The engine.** A `mountingOf(deployment)` that returns the four as they are (anything that isn't a finite number, or text for `mount`, is `null`: the engine tests call it without the defaults node). `want` carries them beside the heading. `sameMounting(row, want)` compares the four, `null` equal to missing. In `decide`, rules 4 and 5 use `sameHeading && sameMounting(row, want)` where they use `sameHeading` after Task 2. `insertRow` puts the four in the row and the parameters. The comment at the top says a deployment starts when the survey or how the sensor is mounted changes.
- [ ] **Step 5: The three SQL texts,** as in Interfaces.
- [ ] **Step 6: Run** `python -m pytest script/tests container/node-red-tm/schema/tests`. PASS, including the SQL compile test.
- [ ] **Step 7: Commit** ("Record how each sensor is mounted on its deployment row").

### Task 11: Two internal endpoints

**Files:**
- Modify: `container/node-red-tm/data/flows.json` (new nodes in the group `3da2c0e89c06736d`; the scope of the catch `e27f61c06fec6515`)
- Test: `script/tests/test_node_red_flows.py`

**Interfaces:**
- Produces: `POST /tm-internal/deployments/:id/mounting`. Body: `{"heading_deg", "pitch_deg", "height_m", "view_distance_m", "mount"}`, all five keys required, each `null` or valid by item 1. Answers 204; 400 `{"error": "bad_request", "detail": "<the first key refused, or deployment_id>"}`. Statement, named "rewrite deployment mounting": `UPDATE deployment SET heading_deg = $heading_deg, pitch_deg = $pitch_deg, height_m = $height_m, view_distance_m = $view_distance_m, mount = $mount WHERE id = $id;` Task 3's `.../heading` stays beside it, for the correction of one deployment's heading with a reason.
- Produces: `GET /tm-internal/surveys/:id/recorded`. Answers `{"deployments": {"<deployment id>": true | false | null}}` for the survey's open rows: `true` when the row has recorded traffic, `null` when the row's sensor type has no rule. Statement, named "read survey recorded":

  ```sql
  SELECT d.id AS id,
      CASE d.sensorType
          WHEN 'cameras' THEN EXISTS (SELECT 1 FROM events WHERE deployment_id = d.id)
          WHEN 'radars' THEN EXISTS (SELECT 1 FROM radar_dov
              WHERE time >= d.entryStartDateTime / 1000.0 - 86400 AND deployment_id = d.id)
      END AS recorded
  FROM deployment d
  WHERE d.survey_id = $survey_id AND d.entryEndDateTime IS NULL;
  ```

  The time bound lets the radar part use the index on `radar_dov(time)`; the day's margin covers a clock that was set back after the deployment began.

- [ ] **Step 1: Write the failing tests.**
  - `TM_INTERNAL_PATHS`, `TM_INTERNAL_METHODS`, and `VALIDATORS` gain the two (`"tm-internal: validate mounting correction"`, and for the read `"tm-internal: validate recorded path"`, a copy of "tm-internal: validate survey path" under a name of its own, because the tests find a validator by its name), so the existing token and refusal tests cover them.
  - `test_mounting_correction_is_validated(deployment_id, body, detail)`: a full valid body gives the six parameters, rounded; a missing key, each limit one step past, a `'40'`, and a malformed id each give 400 with that `detail` and reach no SQL.
  - `test_mounting_correction_runs_one_prepared_statement_and_answers_204`: through `correction_chain`, the statement's name and text, and 204 with an empty body.
  - `test_survey_recorded_statement`: the pinned text, and on such a database: a camera's open row with one event is 1; a radar's open row with a reading after its start is 1; a radar's with none is 0; an air-quality monitor's is NULL; a closed row and another survey's row aren't listed.
  - `test_survey_recorded_answer(rows, expected)`: 1, 0, and NULL become `true`, `false`, and `null`, keyed by id; no rows give `{"deployments": {}}`.
- [ ] **Step 2: Run them.** They fail.
- [ ] **Step 3: Add the nodes,** each chain a copy of its neighbour's shape (the heading correction's for the POST, the survey events' for the GET), with new ids, placed below the group's last row. Add the two new sqlite nodes to the catch's scope and the new nodes to the group's `nodes`.
- [ ] **Step 4: Run** `python -m pytest script/tests container/node-red-tm/schema/tests`. PASS.
- [ ] **Step 5: Commit** ("Add the internal endpoints the Mounting form needs").

### Task 12: The upload: a field list for deployment rows

**Files:**
- Modify: `container/node-red-tm/data/upload-lists.json`, `container/node-red-tm/data/flows.json` (`ae3349867027d005`), `container/node-red-tm/data/README.md`, `container/node-red-tm/data/settings.js` only if it names the lists' keys
- Modify: `tm-control/backend/tm_control/modules/sharing/NOTICE.md` (Step 5)
- Test: `script/tests/test_node_red_flows.py`, `script/tests/test_node_red_settings.py` if it pins the keys

**Interfaces:**
- Produces: `upload-lists.json` gains `"deployment": ["id", "entryStartDateTime", "entryEndDateTime", "lat", "lon", "sensorType", "sensorName", "deviceName", "survey_id", "location_precision", "heading_deg", "pitch_deg", "height_m", "view_distance_m", "mount"]`.
- Changes, the gate: the lists are readable only when `deployment` is a list of text too. Each deployment row, in the telemetry's two lists and in the `deployments` attribute (every entry but `deploymentTopLevel`), is cut to the list with `listedFields(row, lists.deployment, "deployment", "")` before it is re-rounded; a row with no field left is dropped.

- [ ] **Step 1: Write the failing tests.**
  - `test_upload_lists_file` expects the new list.
  - `test_gate_keeps_only_the_listed_deployment_fields`: a telemetry row with the five and a key `note` goes out with the five and without `note`, and the log has one warning that names `deployment.note` and no value.
  - `test_gate_cuts_the_deployments_attribute_rows_too`: the same for a sensor's entry; `deploymentTopLevel` is as it was.
  - `test_gate_still_re_rounds_a_cut_row`: the existing re-round cases pass through the list (it holds `location_precision`).
  - `test_gate_sends_nothing_without_readable_lists` gains lists with no `deployment`.
  - `test_every_deployment_row_key_is_on_the_upload_list`: `ROW_KEYS` and the keys the attribute's template writes are all in the list.
- [ ] **Step 2: Run them.** They fail.
- [ ] **Step 3: Edit the list file and the gate.** The gate's opening comment says deployment rows are cut to their list.
- [ ] **Step 4: Run** `python -m pytest script/tests`. PASS.
- [ ] **Step 5: Draft the notice's sentence, and stop.** The notice is the maintainer's text. Propose, under "Share data", after the sentence about the location: "It also sends how each sensor is mounted, when you have recorded it: its height above the road, how far it tilts down, and which way it faces in degrees." Show the maintainer the paragraph before and after, and take his wording and his decision on the notice's version (`2026-11` today; no release has carried it yet).
- [ ] **Step 6: Commit** the gate ("Send deployment rows by a field list, with how each sensor is mounted"), then the notice with the maintainer's wording.

### Task 13: The rules, in one module

**Files:**
- Create: `tm-control/backend/tm_control/modules/location/mounting.py`, `tm-control/backend/tests/test_mounting.py`
- Modify: `script/tests/test_node_red_flows.py` (one test that compares the flows' limits with the module's)

**Interfaces:**
- Produces:

  ```python
  FIELDS = ("heading_deg", "pitch_deg", "height_m", "view_distance_m", "mount")
  PITCH_MAX = 90.0                     # POINTS, HEADING_MAX, and the compass functions are Task 4's, in coordinates.py
  HEIGHT_MAX_M = 100.0
  VIEW_DISTANCE_MAX_M = 1000.0
  MOUNT_KEY = re.compile(r"^[a-z0-9_]{1,32}$")
  MOVED_HEADING_DEG = 20
  MOVED_HEIGHT_M = 0.3
  MOVED_PITCH_DEG = 5.0

  class Mount(BaseModel):
      key: str
      title: str
      height_m: float
      pitch_deg: float

  MOUNTS: tuple[Mount, ...]            # item 4's three, in that order

  class Mounting(BaseModel):
      sensor_type: str
      sensor_name: str
      heading_deg: int | None = None
      pitch_deg: float | None = None
      height_m: float | None = None
      view_distance_m: float | None = None
      measured: Literal["pitch", "distance"] | None = None
      mount: str | None = None

  class MountingError(ValueError):     # .field names the value refused; str() is a sentence with no value in it
      field: str

  class Change(BaseModel):
      sensor_type: str
      sensor_name: str
      field: str                       # one of FIELDS
      counts: bool

  class SensorKey(BaseModel):
      sensor_type: str
      sensor_name: str

  class Review(BaseModel):
      changes: list[Change]
      ask: bool
      suggested: Literal["moved", "measured"] | None
      new_deployments: list[SensorKey]

  def read(sensor_type: str, sensor_name: str, raw: Mapping) -> Mounting
  def checked(given: Mounting, mounts: tuple[Mount, ...] = MOUNTS) -> Mounting
  def turn(old: Mounting, new: Mounting) -> int | None
  def review(old: list[Mounting], new: list[Mounting], recorded: Mapping[tuple[str, str], bool | None],
             moved: bool | None) -> Review
  ```

- `read` is the lenient reader of a sensor's `deployment` mapping from `config.yml`: it reads the heading with `coordinates.read_heading`, applies the same limits to the other four as Task 10's defaults node, never raises, and leaves `measured` as `None`.
- `checked` is the strict one, for the API. It raises `MountingError` for a value outside item 1, a `mount` that isn't in `mounts`, a tilt or distance given with no `measured`, and, for an `airquality_monitors` sensor, anything but a heading. It returns the values rounded, with the unmeasured one of tilt and distance worked out (item 3), whatever was sent for it. A `measured` whose own value is empty becomes `None`, with both empty.
- `turn` is item 7's size of a turn, `None` when either side has no heading.
- `review` applies item 7. `old` and `new` are matched by sensor; a sensor in only one of them is skipped. Of the tilt and the distance, `changes` can list only the one `new.measured` names (the one `old.measured` names when the new one is empty, and the tilt when neither names one); the other is never listed. `recorded[key]` of `False` means nothing recorded; `True`, `None`, or a missing key all count as recorded. `new_deployments` is empty unless `moved is True`.

- [ ] **Step 1: Write the failing tests** in `test_mounting.py`:
  - `test_distance_from_tilt`, `test_tilt_from_distance`: item 3's four worked cases; a tilt of 90 gives 0.0; a tilt of 0 gives no distance; a distance of 0 gives 90.0; a result over 1,000 gives none.
  - `test_without_a_height_only_the_measured_one_is_kept`.
  - `test_checked_refuses(field, value)`: every limit one step past, a `bool` for a number, an unknown mount, a tilt with no `measured`, a height on an air-quality monitor; `error.field` is that field and `str(error)` holds no value.
  - `test_checked_rounds`: 2.134 is 2.13, 14.96 is 15.0.
  - `test_read_drops_what_the_flows_drop`: the same cases as Task 10's parametrized test, with the same results.
  - `test_a_turn_is_the_smaller_angle`: 350 to 10 is 20; 45 to 90 is 45; 45 to 40 is 5; a side with no heading gives `None`.
  - `test_filling_an_empty_value_does_not_count`, `test_the_mount_never_counts`, `test_clearing_a_value_counts`.
  - `test_nothing_recorded_does_not_ask`, `test_an_unknown_recorded_asks`.
  - `test_the_answer_chosen(change, suggested)`: heading 40 to 59 is `measured`, 40 to 60 is `moved`; height 2.13 to 2.42 `measured`, to 2.43 `moved`; tilt 15.0 to 19.9 `measured`, to 20.0 `moved`; a distance-only change with no tilt on either side is `measured`.
  - `test_moved_starts_deployments_only_where_a_change_counts`: one save with a camera turned 40° and a radar's height filled in for the first time, `moved=True`: `new_deployments` holds the camera only.
  - `test_measured_starts_none`, `test_no_change_is_an_empty_review`.
  - `test_tilt_and_distance_are_listed_once`; `test_choosing_the_other_as_measured_is_not_a_change` (2.13 m, a measured tilt of 62.0° with its distance of 1.13 m, then the distance 1.13 m sent as the measured one: the tilt comes back 62.1°, and `changes` is empty).
- [ ] **Step 2: Run them.** `python -m pytest tm-control/backend/tests/test_mounting.py` fails: no module.
- [ ] **Step 3: Write the module.**
- [ ] **Step 4: The comparison,** in `script/tests/test_node_red_flows.py`: `test_mounting_limits_match_the_control_apps` runs "init config defaults" on each limit of the four and one step past it, and asserts the flows keep exactly what `mounting.read` keeps. Task 4's test already ties the heading.
- [ ] **Step 5: Run** `python -m pytest script/tests tm-control/backend/tests`. PASS.
- [ ] **Step 6: Commit** ("Add the mounting rules to the control app").

### Task 14: The store, the file, the Node-RED client, and fake mode

**Files:**
- Modify: `tm-control/backend/tm_control/core/state.py`, `modules/location/places.py`, `modules/location/config.py`, `modules/location/reconcile.py`, `adapters/nodered.py`, `fake.py`
- Test: `tm-control/backend/tests/test_state.py`, `test_places.py`, `test_location_config.py`, the reconcile tests, the tests of `FakeNodeRed`

**Interfaces:**
- Produces, `core/state.py`: migration 6 adds to `survey_sensors`: `pitch_deg REAL`, `height_m REAL`, `view_distance_m REAL`, `measured TEXT CHECK (measured IN ('pitch', 'distance'))`, `mount TEXT`.
- Produces, `Places`:
  - `mountings(survey_id: str) -> list[Mounting]`: the place's rows, in insertion order.
  - `set_mounting(survey_id: str, mounting: Mounting) -> None`: the row's heading and five columns, inserted when the sensor has no row.
- Produces, `NodeRedConfig`:
  - `mountings() -> list[Mounting]`: every enabled sensor, in `sensors()`'s order, read with `mounting.read`.
  - `set_sensor_mounting(sensor_type: str, sensor_name: str, mounting: Mounting | None) -> None`: writes the heading as `set_sensor_heading` does, then the other four keys after `heading_deg` in `FIELDS`'s order; a `None` value removes its key, and a `None` mounting removes the four and leaves the heading alone. Raises `KeyError` for a sensor that isn't in the file.
- Produces, `NodeRed`:
  - `correct_mounting(deployment_id: str, values: Mapping) -> None`: `POST /deployments/<id>/mounting` with the five keys.
  - `recorded(survey_id: str) -> dict[str, bool | None]`: `GET /surveys/<id>/recorded`; `NodeRedError("unexpected")` when `deployments` isn't a mapping of ids to `true`, `false`, or `null`.
- Produces, `FakeNodeRed`: rows carry the five; the engine reads `config.mountings()` and compares the five in rules 4 and 5, as Task 10's does; `correct_mounting` and `recorded` answer as the real endpoints do (400 for the same inputs); `RECORDS_AFTER = 30.0`, the seconds after which a camera's or a radar's open row counts as having recorded traffic (an air-quality monitor's is always `None`).
- Changes, `reconcile._follow`: in the `restoring` branch, after the headings go back, each enabled sensor that has none of the other four in the file, has any of them stored for the place in use, and whose heading in the file now equals its stored heading, gets its stored mounting written back.

- [ ] **Step 1: Write the failing tests.**
  - `test_state.py`: `test_migration_six_adds_the_mounting_columns` (the five columns; a row written before keeps NULLs and its heading; `measured` refuses `'both'`).
  - `test_places.py`: `test_set_mounting_inserts_and_updates`, `test_mountings_lists_a_places_rows`, `test_renaming_a_sensor_keeps_its_mounting`, `test_editing_a_planned_place_still_replaces_its_headings`.
  - `test_location_config.py`: `test_mountings_reads_the_file_as_the_engine_does` (the valid case, an invalid value, an old `bearing` key, a disabled sensor left out); `test_set_sensor_mounting_writes_the_keys_in_order_after_the_heading`; `test_set_sensor_mounting_keeps_comments_and_other_keys` (round trip: the bytes differ only in the sensor's block); `test_a_none_value_removes_its_key`; `test_none_removes_the_four_and_keeps_the_heading`; `test_set_sensor_mounting_creates_the_deployment_block`; `test_set_sensor_mounting_for_a_sensor_not_in_the_file_is_a_key_error`.
  - Reconcile: `test_a_reset_file_gets_the_mounting_back` (after the place's id and headings are blanked, as `-f` leaves them, one `ensure` writes the id and the five, and `FakeNodeRed` starts no deployment); `test_a_reset_file_with_another_heading_gets_no_mounting`; `test_a_file_that_has_mounting_keys_keeps_them`.
  - `FakeNodeRed`: `test_fake_engine_starts_a_deployment_on_a_mounting_change`, `test_fake_correct_mounting_then_the_file_starts_none`, `test_fake_recorded_follows_the_rows_age`, `test_fake_correct_mounting_refuses_what_the_flows_refuse`.
- [ ] **Step 2: Run them.** They fail.
- [ ] **Step 3: Implement,** in the order of Interfaces.
- [ ] **Step 4: Run** `python -m pytest tm-control/backend/tests script/tests`. PASS.
- [ ] **Step 5: Commit** ("Keep each sensor's mounting in the places store and config.yml").

### Task 15: The API *(tricky)*

**Files:**
- Modify: `tm-control/backend/tm_control/modules/location/router.py`
- Modify: `tm-control/ui/src/api/openapi.json`, `tm-control/ui/src/api/schema.d.ts` (regenerated)
- Create: `tm-control/backend/tests/test_api_mounting.py`
- Test: `tm-control/backend/tests/test_api_surveys.py`

**Interfaces:**
- Consumes: Task 13's `checked`, `review`, `Mounting`, `Mount`, `MOUNTS`, `Change`, `SensorKey`; Task 14's store, file, and client methods.
- Produces, models:

  ```python
  class SensorMounting(Mounting):
      camera: str | None                        # for a radar: the first enabled camera whose camera_radar names it
      same_as_camera: bool                      # camera is set and the radar's five equal that camera's
      deployment_id: str | None                 # its open deployment row; None when Node-RED has none or didn't answer
      recorded: bool | None

  class MountingState(BaseModel):
      sensors: list[SensorMounting]             # cameras, each followed by its radar; then other radars; then the rest
      mounts: list[Mount]
      nodered: bool                             # whether Node-RED answered

  class SensorMountingIn(Mounting):
      same_as_camera: bool = False

  class MountingIn(BaseModel):
      sensors: list[SensorMountingIn] = Field(max_length=32)
      moved: bool | None = None
      dry_run: bool = True

  class MountingOut(BaseModel):
      saved: bool
      sensors: list[SensorMounting]             # as stored after a save, or as they would be
      changes: list[Change]
      ask: bool
      suggested: Literal["moved", "measured"] | None
      new_deployments: list[SensorKey]
      reloaded: bool | None                     # after a save that starts deployments: whether Node-RED was seen to
  ```

  `DeploymentOut` gains the other four beside Task 5's `heading_deg`, each `None` when the row has none.
- Produces, routes, both `Depends(require_admin)`:
  - `GET /surveys/{survey_id}/mounting -> MountingState`. 404 for no such place; 409 `not_in_use` for a place that isn't in use. The values come from `config.yml`; `measured` from the store's row, else `pitch` when the file has a tilt, else `distance` when it has a distance. Node-RED not answering isn't an error: `nodered` is false and every `deployment_id` and `recorded` is `None`.
  - `PUT /surveys/{survey_id}/mounting`, body `MountingIn`, `-> MountingOut`.
    - 404 and 409 `not_in_use` as above. 422 `validation` with `detail.field` for a `MountingError`, for a sensor that isn't enabled in `config.yml` or is named twice, and for `same_as_camera` on a sensor with no `camera`. A sensor the body leaves out keeps its values, and nothing is written for it.
    - `same_as_camera` replaces the item's five and `measured` with that camera's: the camera's item in the same body when there is one, else the camera's values now.
    - The review is `review(old, new, recorded, body.moved)`, with `old` the file's values and `recorded` from `nodered.recorded` (any `NodeRedError` there means every sensor is unknown).
    - `dry_run`: answers the review, `saved: false`, and writes nothing.
    - A sensor is *written* when any of the five or `measured` differs from what is stored, whether or not `changes` lists it (a worked-out value that moved by a rounding step is written, in place).
    - A save with `ask` and `moved is None`: 409 `answer_needed`. A save with no sensor to write: `saved: true` and nothing written.
    - A save, under `app_state.reconcile_lock`, in this order: read the place's open rows (`nodered.deployments`; a `NodeRedError` is 502 and nothing is written); for each sensor to write that isn't in `new_deployments` and has an open row, `nodered.correct_mounting`; write every such sensor to `config.yml` with `set_sensor_mounting` and save; write each to the store with `set_mounting`. If a correction or the file's save fails, the rows already corrected are put back with their old values (best effort, logged by class name) and the error is answered.
    - Records: `Audit.record(admin.id, "survey.mounting", place.id)` for every save that wrote something; for each sensor corrected in place, a `survey_corrections` row when its heading changed (`field` `heading_deg`, no reason) and an audit row `survey.correct_mounting` whose detail is the place id, the deployment id, and each other changed field as `name old>new`.
    - After the lock, when `new_deployments` isn't empty: ask Node-RED every `POLL_INTERVAL` for up to `DEPLOY_TIMEOUT` until each of those sensors has an open row that started at or after the save; `reloaded` says whether they all did.
- Changes:
  - `deploy_place`, when `switching`: after each enabled sensor's heading is written (the one chosen at this deploy, as after Task 5), `set_sensor_mounting` writes the place's stored row for it (from `places.mountings(place.id)`) with that heading. A sensor the place has no row for, or a row with none of the other four, gets `None`, which removes the four from the file. The store keeps its rows.

- [ ] **Step 1: Write the failing tests** in `test_api_mounting.py`, with `FakeNodeRed.RECORDS_AFTER` set by a fixture (`0` for "has recorded", `float("inf")` for "has not"):
  - Reading: `test_mounting_needs_an_admin` (GET and PUT, a viewer gets 403), `test_mounting_of_a_place_not_in_use_is_refused`, `test_a_new_units_mounting_is_empty` (every enabled sensor listed, the radar after its camera with `camera` set and `same_as_camera` true, the three mounts), `test_mounting_reads_a_hand_edit`, `test_mounting_without_nodered_still_lists`.
  - Dry run: `test_a_dry_run_writes_nothing` (the file's bytes, the store, the rows, and the audit log are as before), `test_a_dry_run_works_out_the_distance`, `test_a_dry_run_names_the_field_it_refuses`.
  - First fill: `test_a_first_fill_corrects_the_open_row` (the deployment ids are the same before and after; the row, the file, and the store hold the values; no question was needed although traffic was recorded).
  - The question: `test_a_change_with_traffic_needs_the_answer` (409 `answer_needed`, nothing written), `test_an_unknown_recorded_asks`, `test_a_change_without_traffic_is_corrected_in_place`, `test_moved_starts_a_new_deployment` (the old row is closed with its old values, the new one holds the new, `reloaded` is true), `test_measured_corrects_in_place_and_records_it` (same id; the audit row's detail holds the field with its old and new value; a changed heading has a `survey_corrections` row), `test_moved_corrects_the_sensors_whose_change_does_not_count`.
  - `test_same_as_camera_copies_the_cameras_values`, `test_same_as_camera_needs_a_camera`, `test_a_sensor_left_out_keeps_its_values`, `test_a_sensor_that_is_not_enabled_is_refused`.
  - Failure: `test_a_save_without_nodered_changes_nothing` (502), `test_a_refused_file_puts_the_rows_back` (the file is edited between the load and the save, so the save answers 409; the row holds its old values again), `test_saving_the_same_values_writes_nothing`.
  - `test_no_coordinate_in_any_log_line` still passes with these routes called.
- [ ] **Step 2: Add to `test_api_surveys.py`:** `test_a_new_place_starts_with_no_mounting` (after a save at the first place, a deploy to a place never used: the file and the new rows have none of the four, and the first place's stored rows still hold theirs), `test_a_return_offers_the_places_mounting_and_records_none` (then a deploy back to the first: on new deployment ids, the file and the new rows hold none of the four, and `GET .../mounting` and the deploy's answer offer what was saved there as `previous`, `measured` included), `test_a_return_takes_the_heading_chosen_at_the_deploy_and_offers_the_rest`, `test_a_return_gives_a_sensor_the_place_never_had_no_mounting`, `test_correct_heading_leaves_the_other_four_alone`, `test_deployments_list_their_mounting`.
- [ ] **Step 3: Run them.** They fail.
- [ ] **Step 4: Implement,** then regenerate the API files.
- [ ] **Step 5: Run** `python -m pytest tm-control/backend/tests script/tests`, and the UI's build and tests in the pinned Node image (the generated types changed). PASS.
- [ ] **Step 6: Commit** ("Add the mounting routes to the Location API").

### Task 16: The reference picture's `pose`

**Files:**
- Modify: `tm-control/backend/tm_control/modules/cameras/reference.py`, `modules/cameras/router.py`, `fake.py` if fake mode builds a `Reference` of its own
- Modify: `docs/use/cameras.md`
- Test: `tm-control/backend/tests/test_cameras_reference.py`

**Interfaces:**
- Produces: `Reference.pose: dict | None`. `take_reference` fills it from `config.mountings()` for `("cameras", name)`: `{"heading_deg", "pitch_deg", "height_m", "view_distance_m", "mount", "hfov_deg": None}`; the whole of it `None` when all five are empty.
- Produces: `data_file` writes `"pose"` after `"location"`. `caption` ends with `  ·  facing NE (40°)` for a heading (Task 4's `facing`), and has no such part without one. `FORMAT_VERSION` stays 1.

- [ ] **Step 1: Write the failing tests:** `test_the_data_file_holds_the_pose`, `test_the_pose_is_null_when_nothing_is_recorded`, `test_the_pose_has_no_field_of_view_yet`, `test_the_caption_says_which_way_the_camera_faces` (with a heading and without), `test_the_drawing_still_fits_its_caption` (the SVG holds the whole caption, escaped), and, through the API, `test_a_reference_takes_the_pose_from_the_file`.
- [ ] **Step 2: Run them.** They fail.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: `docs/use/cameras.md`,** in "The data file": a row for `pose` and one for each key in it, with units, that `hfov_deg` is empty for now, and that the pose is what the Location page's record holds for the camera when the picture is taken.
- [ ] **Step 5: Run** the backend tests and `mkdocs build --strict`. PASS.
- [ ] **Step 6: Commit** ("Add the camera's pose to the reference picture's data file").

### Task 17: Docs, device tests, and the plan's public copy

**Files:**
- Modify: `docs/data-and-payloads/data-overview.md`, `docs/configuration/node-red-config.md`, `docs/data-and-payloads/integrations.md`, `docs/use/sharing.md`, `docs/use/location.md`, `docs/development/tm-control.md`, `CLAUDE.md`
- Modify: `script/devpi/tests/test_web.py`, `script/devpi/tests/devpi_checks.py`, `design/plans/2026-11-23-mounting-form.md`

- [ ] **Step 1: The device tests.**
  - `devpi_checks.mounting_state(address, cookie)`: the place in use's `GET .../mounting`.
  - `test_mounting_needs_an_admin`: a viewer's GET and PUT are refused; add the PUT to the list of Location writes a viewer is refused.
  - `test_mounting_lists_every_enabled_sensor`: each entry has the keys of `SensorMounting`; `mounts` has the three keys.
  - `test_a_mounting_dry_run_changes_nothing`: sending the values back with `dry_run` answers `saved: false`, no change, no question; the place's deployment ids are the same before and after.
- [ ] **Step 2: `data-overview.md`,** the `deployment` table: the four new columns with units and "empty when not recorded", beside `heading_deg`; the sentence on when a new row starts says "or how the sensor is mounted"; a line that a correction changes the row in place.
- [ ] **Step 3: `node-red-config.md`,** "deployment":
  - a table of the five keys under a sensor's `deployment:` block, with units and limits;
  - that the Location page's Mounting form writes them (the form comes with PR 3; until then the API or a hand edit);
  - that a hand edit of any of them starts a new deployment, like the heading;
  - in "Edit the location by hand", that a reset file gets the mounting saved for this use back with the heading;
  - the `deployment` rows of the two sensor tables.
- [ ] **Step 4: The other pages.**
  - `integrations.md` and `sharing.md`: deployment rows carry the five, and only listed fields are sent.
  - `docs/use/location.md`, in "Move or turn the device": a deploy records none of the four, at a place the unit was at before as at a new one, and the values last saved at a place used before are offered until a save records them.
  - `docs/development/tm-control.md`: the two routes and their answers; `survey_sensors`' columns; the two internal endpoints in the Node-RED table; `mounting.py` and the rule that nothing else restates it; the order of a save and why; fake mode's 30 seconds.
  - `CLAUDE.md`: the Location clause (the `/surveys/{id}/mounting` routes; `config.yml`'s sensor mounting keys among what the page writes); the count of internal endpoints, with the two named; the upload lists' `deployment`; the test that ties the limits.
- [ ] **Step 5: The plan's public copy** gains anything Part B changed.
- [ ] **Step 6: Run** every off-device check and `mkdocs build --strict`. PASS.
- [ ] **Step 7: Commit** the device tests, then the docs, then the plan's copy.

### Task 18: Pi plan and PR 2

- [ ] **Step 1: Pi plan,** as a logged `tmdev check` on a bench unit marked `pii_free`, after `tmdev deploy <host> -- -t node-red-tm -t tm-control`. Frigate's detection stays off throughout; say so in the check.
  1. Before the deploy, note the open deployment ids. After it: the device suite passes; `tmdb_migrate.py --check` says up to date at version 11; the journal has `applied 0011_deployment_mounting.sql`; the open deployment ids are the same.
  2. `PUT .../mounting` with a height, a tilt, and a heading for the camera, as an admin, `dry_run` false: the deployment id is the same, and the row, `config.yml`, and `GET .../mounting` hold the values. No question was needed.
  3. Publish one synthetic `frigate/events` `end` message for the camera on the device's broker, so its deployment has an event. A dry run that turns the heading by 30°: `ask` is true and `suggested` is `moved`. Save with `moved: true`: a new deployment id; the old row is closed with the old heading.
  4. A dry run that raises the height by 0.1 m: `suggested` is `measured`. Save with `moved: false`: the same deployment id, the row corrected, and an audit row with the old and new height.
  5. By hand in `config.yml`: `height_m: -1`. The Status page's config check names the key and no value; the new row has no height. Put it right.
  6. `tmdev deploy <host> -- -f -t node-red-tm`, then load the home page: `config.yml` has the place's id and the five again; no new deployment id.
  7. **Deploy here** to a second place through the API: its rows have none of the four, and `GET .../mounting` is empty. Deploy back to the first place (the maintainer's change, 2026-11-25): its new rows and `config.yml` hold the heading chosen and none of the four, and the deploy's answer and `GET .../mounting` offer what item 4 saved as `previous`.
  8. A reference picture's zip, taken with the location box cleared: the data file has `pose` with the camera's values and `hfov_deg: null`. Read the data file's keys only; never open a picture.
  9. **Manual, the maintainer's:** with sharing on to a test server, the server accepts the five new keys on deployment rows.
- [ ] **Step 2: Every off-device check once more** on the final branch; `git grep` the branch for device names and any coordinate that isn't allowed.
- [ ] **Step 3: PR 2's text,** the template filled in, "Part of" the issue. The release note: "The device can now record how each sensor is mounted: its height above the road and its tilt, beside its heading. The values are kept with each deployment in the database and sent with shared data. They are set through the control app's API or `config.yml` for now; the form comes next." Also: the Docs list; the Pi plan's results; that the migration adds four columns and rewrites no row; the limits (no form yet; a hand edit of a mounting key starts a new deployment; a new place starts unmeasured, and so does a place used before, which offers its last values until a save records them; the gate doesn't yet hold a new field back until the notice is read again); and the AI-assistance section. The maintainer reads the commit messages and the PR text before any push.

---

# Part C: the form (PR 3)

### Task 19: The heading dial *(tricky)*

**Files:**
- Create: `tm-control/ui/src/modules/location/HeadingDial.vue`, `tm-control/ui/tests/heading-dial.spec.ts`
- Modify: `tm-control/ui/src/modules/location/heading.ts`, `tm-control/ui/tests/heading.spec.ts`, `tm-control/ui/README.md` (design notes)

**Interfaces:**
- Produces, `heading.ts`:

  ```ts
  // added to Task 6's POINTS, compassPoint, pointCentre, facing, and headingChoices
  export function angleAt(x: number, y: number, cx: number, cy: number): number   // 0 to 359; up is 0, right is 90
  export function facingWords(heading: number | null): string
  ```

  `facingWords`: `"52°, north-east."` for a heading; `"Not set."` for none.
- Produces, `HeadingDial.vue`: props `heading: number | null`, `label: string`, `disabled?: boolean`; emits `update:heading`. Choosing a point emits its centre. A click or drag on the dial, or a number typed, emits that heading. **Not set** emits `null`.

- [ ] **Step 1: Write the failing tests.**
  - `heading.spec.ts`: `angleAt wraps at north` (a point just left of straight up is 359, just right is 0 or 1; straight right is 90, down 180, left 270; the centre itself is 0); `facingWords` in its two forms.
  - `heading-dial.spec.ts`: `choosing a compass point sets its centre`; `typing a number sets the heading`; `a number outside 0 to 359 is not sent, and the field says why`; `a click on the dial sets the heading there`; `the eight points and the number field can be reached and used from the keyboard`; `the needle and the words follow the heading`; `Not set clears it`; `disabled, nothing can be changed`.
- [ ] **Step 2: Run them.** They fail.
- [ ] **Step 3: Design notes first,** in the README's Location section: the dial's size at 375 px, where the number field sits, and the help line ("North is up on a map. A phone's compass shows magnetic north unless it is set to true north. If you only know the compass point, tap it.").
- [ ] **Step 4: Build it:** one SVG with a ring, the eight points as real buttons around it, and a needle; pointer events with capture for the drag, and `touch-action: none` on the ring so a drag doesn't scroll the page; a Vuetify number field beside it. No new package.
- [ ] **Step 5: Run** the build and the tests. PASS.
- [ ] **Step 6: Screenshot review** at 375 px and 1280 px, in a scratch mount of the component: a heading, a compass point's centre, not set, disabled. Note in the README what the review changed.
- [ ] **Step 7: Commit** ("Add the heading dial").

### Task 20: Lengths in two units, and the side view

**Files:**
- Create: `tm-control/ui/src/modules/location/lengths.ts`, `tm-control/ui/src/modules/location/MountSideView.vue`
- Test: `tm-control/ui/tests/lengths.spec.ts`, `tm-control/ui/tests/mount-side-view.spec.ts`

**Interfaces:**
- Produces, `lengths.ts`:

  ```ts
  export type Unit = 'ft' | 'm'
  export function shown(metres: number | null, unit: Unit): string      // the field's text: one decimal in feet, two in metres; '' for null
  export function typed(text: string, unit: Unit): number | null        // metres, two decimals; null for '' or text that isn't a number
  export function both(metres: number | null, unit: Unit): string       // "7.0 ft (2.13 m)" or "2.13 m (7.0 ft)"; '' for null
  export function savedUnit(): Unit                                     // 'ft' unless the browser remembers 'm'
  export function saveUnit(unit: Unit): void
  ```

  One foot is 0.3048 m. The browser's memory is `localStorage` under `tm.mounting.unit`, read and written inside `try`, because a browser may refuse it.
- Produces, `MountSideView.vue`: props `heightM: number | null`, `pitchDeg: number | null`, `distanceM: number | null`, `unit: Unit`. An SVG side view: the road, the support with the unit on it at the height, the line of sight down to the centre of the view, and the three values written beside their parts in the chosen unit. With a value missing, that part is dashed and unlabelled. With no height it shows one line: "Enter the height to see the side view." It has a text alternative that says the same as the labels.

- [ ] **Step 1: Write the failing tests.**
  - `lengths.spec.ts`: 2.13 m shows as `7.0` in feet and `2.13` in metres; `7` typed in feet is 2.13; `12` is 3.66; `16` is 4.88; `''` and `'abc'` are null; `both` in each order; `savedUnit` is `ft` with nothing remembered, `m` after `saveUnit('m')`, and `ft` when `localStorage` throws.
  - `mount-side-view.spec.ts`: `the labels follow the values and the unit`; `a tilt of zero draws a level line and labels no distance`; `a tilt of 90 draws straight down`; `no height shows the one line`; `a height of 100 m and one of 0.5 m both stay inside the drawing`; `the text alternative names the three values`.
- [ ] **Step 2: Run them.** They fail.
- [ ] **Step 3: Build both.** The drawing scales so the support and the ground point both fit; it never works a value out, it draws the three it is given.
- [ ] **Step 4: Run** the build and the tests. PASS.
- [ ] **Step 5: Commit** ("Add the side view and the length units").

### Task 21: The Mounting page *(tricky)*

**Files:**
- Create: `tm-control/ui/src/modules/location/MountingPage.vue`, `tm-control/ui/tests/mounting-page.spec.ts`
- Modify: `tm-control/ui/src/modules/location/index.ts`, `LocationPage.vue`, `DeployReview.vue`, `PlaceDetails.vue`, `coordinates.ts`
- Modify: `tm-control/ui/tests/location-page.spec.ts`, `deploy-review.spec.ts`, `place-details.spec.ts`, `router.spec.ts` or `admin-only-page.spec.ts`, `tm-control/ui/README.md`

**Interfaces:**
- Consumes: Task 15's routes and types from `api/schema`; `HeadingDial`, `MountSideView`, `lengths.ts`.
- Produces: the route `/location/mounting`, `meta: { adminOnly: true }`, not in the nav.

**The page, top to bottom:**
1. A link back to Location. The title "Mounting". The place in use's description and id. One line: "How the unit is mounted at this place. The numbers are stored with each deployment and help place the recorded paths on a street plan."
2. A warning in place of the form when no place is in use or the API refused. A warning above it when `nodered` is false: "Node-RED didn't answer, so changes can't be saved now."
3. **Units:** Feet or Metres, from `savedUnit()`, saved on change.
4. **Start from a usual mount:** the mounts and "My own measurements". Picking a mount sets, in every camera's and radar's section that isn't following a camera, the height, the tilt, "I measured the tilt", and the mount's key. "My own measurements" clears the key and leaves the numbers.
5. **A section for each sensor,** in the API's order, titled with the sensor's name:
   - a radar with a `camera`: the checkbox "Same as <camera>". Ticked, the section shows the one line "Takes <camera>'s heading, height, and tilt." and sends `same_as_camera`;
   - the dial, labelled "Which way it faces";
   - for a camera or a radar: "Height above the road", with the help "From the road surface straight below the camera up to the lens. Use a tape measure."; then the choice "I measured the tilt" or "I measured the distance"; then "Tilt below level" ("How far the camera points down. 0 is level, 90 is straight down. Hold a phone's level app against the camera.") and "Distance to the centre of the view" ("Along the ground, from the spot right below the camera to the spot on the road at the very centre of the picture."). The one not measured is greyed and shows the dry run's value. Each length shows the other unit under it, from `both`;
   - the side view, drawn from the dry run's values;
   - when the sensor has `previous`, the values ("From last time: 12.0 ft up, tilted 15°, pole or sign post") and **Use these values**, which fills the fields and the measured choice. Nothing is recorded until Save. The dry run lists them as filled-in values, so nothing is asked;
   - a field the API refused shows the API's sentence under it.
6. **The question,** shown when the last dry run says `ask`: "Did the unit move or turn?", with what changed listed under it ("picam_h265: heading 40° to 62°"), and two choices, the dry run's `suggested` already chosen: "No, it is where it was. I measured it better." and "Yes, it was moved or turned." Under the choice, what it does: "The record of the running deployment is corrected." or "A new deployment starts now for <sensors>. Traffic already recorded keeps the old values."
7. **Save** and **Cancel**. Save is off until something differs from what was loaded and the last dry run has come back with no refusal. The result sits beside the buttons: "Saved."; "Saved. A new deployment started for <sensors>."; "Saved. Node-RED hasn't loaded the settings yet; the new deployment appears once it does. Don't save again."; or the API's sentence. After a save the page loads the mounting again.

**How it talks to the API:** it loads `GET /api/v1/surveys` for the place in use, then its mounting. After each change it waits 400 ms, sends the whole form as a dry run, and uses the newest answer only (a counter drops an older one that arrives late). Every section is sent on every dry run and save, a ticked radar as `same_as_camera: true`, because a save writes only the sensors it names. It sends lengths in metres from `typed`. Save sends the same body with `dry_run: false` and `moved` from the question when it is shown. A 409 `answer_needed` shows the question; another 409 loads the page again.

**The Location page:**
- The place in use's button reads **Mounting** and goes to the page. `deployWords` loses its in-use case, and `DeployReview` loses the mode that changed headings at the place in use.
- After a deploy, the result gains a line with a **Mounting** button: "Next, record how the unit is mounted.", or, when the deploy's answer lists `previous`, "This place has mounting values from the last time the unit was here. They aren't recorded until you confirm them." (2026-11-25, with Decision 6's change: this replaces "This place's mounting from last time is in use again." The words are proposals for the maintainer's read.)
- While any sensor of the place in use has `previous` (from `GET .../mounting`), the Location page shows a warning with the same sentence and the **Mounting** button. It stays until each such sensor is saved.
- In `PlaceDetails`, each deployment's line gains what is recorded, in feet or metres by `savedUnit()`: "Facing NE (40°) · 7.0 ft up · tilted 15°". **Correct heading** shows on a deployment that has ended; a running one at the place in use shows **Mounting**.

- [ ] **Step 1: Design notes first,** in the README: the order above and why; that the tick is never ticked for the person (it reads ticked only while the radar's values equal the camera's, so ticking it is always the person's act); how a section reads at 375 px; where the question sits and why it isn't a dialog; what "Same as" hides; what was rejected (a dialog for the whole form; a question for each field; working the numbers out in the browser).
- [ ] **Step 2: Write the failing tests** in `mounting-page.spec.ts`, with `fakeApi`:
  - `it lists a section for each sensor, the radar after its camera`;
  - `a place that is not in use shows the reason and no form`;
  - `feet are shown by default, and metres after the switch, which is remembered`;
  - `picking a usual mount fills the height and the tilt and sends its key`; `my own measurements clears the key and keeps the numbers`;
  - `a change sends one dry run after the pause, in metres`; `an older answer that arrives late is ignored`;
  - `the value not measured is greyed and shows the dry run's`; `a tilt of zero shows no distance`;
  - `a refused field shows the API's sentence under it, and Save is off`;
  - `the question shows when the dry run asks, with its answer already chosen`; `it lists what changed`; `the other answer can be chosen, and Save sends it`;
  - `no question is shown when the dry run does not ask`;
  - `Save sends the form with dry_run false`; `the result says which sensors started a new deployment`; `a slow Node-RED says not to save again`;
  - `answer_needed from a save shows the question`;
  - `a radar that follows its camera sends same_as_camera and hides its fields`; `unticking shows them with the camera's values`;
  - `the tick starts as the API reports same_as_camera`; `a radar whose values differ from its camera's starts unticked and is sent as loaded`;
  - `the deploy result says the last values wait to be confirmed`; `the Location page warns while values wait`; `Use these values fills the section and Save sends them`; `the notice goes once the sensor is saved`;
  - `an air-quality monitor has the dial only`;
  - `without Node-RED the page warns and Save is off`;
  - `Cancel goes back to Location without saving`.
- [ ] **Step 3: Update the other specs:** the Location page's button and card; the deploy review without its in-use mode and with the next-step line in both wordings (`a return to a place says its last values wait to be confirmed`); the place details' line and buttons; the route is admin-only.
- [ ] **Step 4: Run them.** They fail.
- [ ] **Step 5: Build it.**
- [ ] **Step 6: Run** the build and the tests. PASS. Record the entry chunk's size before and after.
- [ ] **Step 7: Screenshot review** in fake mode at 375 px and 1280 px: an empty form; a usual mount picked; a heading set on the dial; the question after a turn (fake mode's deployments count as having recorded traffic after 30 seconds); the result after a save; a radar following its camera; the Location page's card and panel. Note in the README what the review changed.
- [ ] **Step 8: Commit** the page, then the Location page's changes.

### Task 22: Docs for the form

**Files:**
- Modify: `docs/use/location.md`, `docs/deployment-and-mounting-guide.md`, `docs/setup-guide.md`, `docs/configuration/node-red-config.md`, `docs/development/tm-control.md`, `tm-control/ui/README.md`, `CLAUDE.md`, `design/plans/2026-11-23-mounting-form.md`
- Create: `docs/assets/images/location-mounting.png`; replace `docs/assets/images/location-page.png` if the card changed in it

- [ ] **Step 1: `docs/use/location.md`.**
  - A section "Record how the unit is mounted": what each value is and how to measure it, with the form's own help text; the dial, and that tapping a compass point is fine when that is all you know; tilt or distance, and that the page works out the other; the usual mounts; feet and metres; "Same as the camera" for a radar.
  - "Did the unit move or turn?": when it is asked, what each answer does, and that the page chooses one from the size of the change.
  - "Move or turn the device" loses **Modify deployment**: a turn is recorded on the Mounting page. After **Deploy here**, the next step is Mounting. A deploy records none of the four, at a place the unit was at before as at a new one. At a place used before, the values from last time are offered: where the notice shows (the deploy's result and the Location page), and that **Use these values** and then Save confirm them. A new place starts with nothing recorded.
  - "Correct a wrong location or heading": **Correct heading** is for a deployment that has ended; a running one is corrected on the Mounting page.
  - The page's description and the list of buttons. The screenshot, at the docs' example place.
- [ ] **Step 2: `docs/deployment-and-mounting-guide.md`:** a "Usual mounts" part with the table of item 4 in feet and metres and a sentence on each. A photograph of each is the maintainer's to take and approve; until he supplies them the part has no picture, and the PR text says so.
- [ ] **Step 3: The other pages.** The setup guide says to level the camera from side to side, because roll isn't recorded (add it if it isn't there). `node-red-config.md` names the Mounting page where Task 17 said "the form comes with PR 3". `docs/development/tm-control.md`: the page, its dry runs, and what the UI computes and what it doesn't. `CLAUDE.md`: the page's route in the Location clause. The plan's public copy gains anything Part C changed.
- [ ] **Step 4: `mkdocs build --strict` and every off-device check.** PASS.
- [ ] **Step 5: Commit** ("Document the Mounting page").

### As built

Where the build of this part differs from what the tasks above say, or settles what they leave open. A later reader should take these in place of the task text.

- **The dial's notes.** The dial is a ring to tap or drag, the eight points as buttons around it in three rows, a number field labelled "Degrees from north", and **Not set**. The field's message is "Enter a whole number from 0 to 359." The help line is the one the task names. A press within 12 pixels of the centre changes nothing, because the angle there is noise (the hub's dead zone). A drag keeps going when the pointer leaves the ring, and a drag across north doesn't jump.
- **An empty heading field changes nothing.** Only **Not set** clears the heading. The task text said an empty field was **Not set**; a blank field next to a heading that is still set would have been a lie.
- **The notice of last time's values sits at the top of its section,** above the dial, not after the side view, because it offers to fill the fields below it. Its words are "From last time:" and the values (the distance where there is no tilt), with **Use these values**. A radar ticked **Same as** its camera shows its own notice only when its last values differ from the camera's, or the camera has none; its **Use these values** unticks it and fills the section, so its own values can't be overwritten unseen by confirming the camera's. The usual mounts' choice is set again after **Use these values** and after the tick changes. The Location page's card and the deploy's result say "This place has mounting values from the last time the unit was here. They aren't recorded until you confirm them.", or "Next, record how the unit is mounted." when none wait. These sentences await the maintainer's read.
- **Correct heading stays for a running deployment whose sensor has no section on the Mounting page.** A sensor that is listed but turned off in `config.yml` keeps its open row, and the page lists enabled sensors only, so that row would have offered neither button. Every other running deployment at the place in use shows **Mounting**.
- **The question lists only the changes that count.** A value filled in for the first time, or a new mount key, is not listed and not asked about.
- **The person's answer is kept only while the counting changes are the same.** When another change makes them differ, as a second turn does, the dry run's `suggested` is chosen again, because the person answered a different question.
- **Unreadable text is held back.** Text the page can't read as a number in the height or in the measured one of tilt and distance isn't sent: the field says "Enter a number, such as 12 or 12.5.", no dry run is sent, and Save stays off. The one that stops being measured forgets such text. One comma and no dot is read as the decimal mark ("7,5"), since many phones' keypads have no dot; a comma before exactly three digits ("1,000") is still refused.
- **A field nobody touched is sent as it was loaded.** A length is converted from feet only when someone types in it, so switching units or leaving a field alone never sends a value that went through feet and back. Text typed back to what the page last put in the field gives that value back too, so a height saved as 3.00 m, shown as 9.8 ft, isn't changed to 2.99 m by a digit typed and deleted. The question lists a length in both units.
- **Switching which one is measured changes no number.** A switch made while a dry run is waiting or on its way, or while **Try again** is offered, sends that dry run first and starts from its answer. When the API works none out (no height), the field starts from what was last typed in it; a field that was never measured holds nothing of its own.
- **A dry run that gets no answer offers Try again.** Any failure but a 422 or a 409 shows its sentence under Save with **Try again**, which sends the same dry run; Save stays off until one is answered.
- **Controls are off while a save is on its way,** because the reload after it would replace an edit made meanwhile. A "Saved." result stays until the form changes again.
- **The usual mounts have no picture yet.** The photographs are the maintainer's to take; the docs' "Usual mounts" part has a table and a sentence for each.
- **The units** are kept in the browser under `tm.mounting.unit` and never reach the API.
- **The side view and the dial are drawn in SVG, with `touch-action: none` on the dial's ring** (one style attribute, listed in the README's "The only other CSS", so a drag doesn't scroll the page). No package was added.
- **The page is in the entry chunk** (723.74 kB, 237.74 kB gzipped, up from 696.74 kB and 229.36 kB), like every other page.

### Task 23: Pi plan and PR 3

- [ ] **Step 1: Pi plan,** as a logged `tmdev check` on the bench unit after `tmdev deploy <host> -- -t revproxy -t tm-control`. Frigate's detection stays off. Items 2 to 8 need a person at a phone or a desktop browser: record each as `manual` for the maintainer.
  1. The device suite passes.
  2. On a phone on the LAN: the place in use's **Mounting** opens the page; a usual mount fills the height and the tilt; the distance follows; the side view follows.
  3. The dial by touch: a tap on a point, a drag across north, a typed number. The page doesn't scroll while dragging.
  4. Save a first fill: "Saved.", and the place's panel shows the same deployment with the values.
  5. With an event recorded (a synthetic message, as in Task 18), turn the heading by 30°: the question shows with "moved or turned" chosen; Save starts a new deployment, and the panel shows both.
  6. Change the height by a few centimetres: the question shows with "measured it better" chosen; Save keeps the deployment.
  7. Feet and metres: switch, reload, and the choice is kept; a saved 7.0 ft reads 7.0 ft again.
  8. On the hotspot: the page works, since it needs no internet. As a viewer: the page isn't offered, and its address goes home.
  9. `config.yml` holds the five under each sensor, and the control app's journal for the test holds no coordinate.
- [ ] **Step 2: Every off-device check once more** on the final branch; the same `git grep` as Task 18.
- [ ] **Step 3: PR 3's text,** the template filled in, closing the issue. The release note: "The Location page has a Mounting page for the place in use. It records which way each sensor faces, on a compass dial that takes degrees or a compass point, with its height above the road and its tilt or the distance to the centre of its view. Usual mounts fill in starting numbers, and a side view follows what you type. When a value changes after traffic was recorded, the page asks whether the unit moved or was only measured better. It takes the place of Modify deployment." Also: the Docs list, the Pi plan's results, the chunk sizes, the limits (the place in use only; no aiming on a map; the photographs of the usual mounts still to come; the radar's own angle to the road is a later change), and the AI-assistance section. The maintainer reads the commit messages and the PR text before any push.

## Later

- **The field of view in `pose`,** once a planned record of each camera's settings holds it.
- **The radar's part of the form:** its angle to the road and a speed correction from it. It builds on this form.
- **A radar that turns apart from its camera:** "turned so many degrees to the left or right of the camera", in place of a second heading.
- **Aiming on the map,** with the Location page's map component.
- **Correcting the mounting of a deployment that has ended.** Only its heading can be corrected.
- **A mark for a heading that was only a compass point,** if anyone using the data needs to tell a picked 45° from a measured one (Decision 10).
- **Taking the old `bearing` key's reader out,** once no file from before this change is likely to come back.
- **Dismissing the values offered from an earlier visit** without saving them: a field on the save and a button (Decision 6).
- **The mounting in the places CSV,** for import and export.
- **The phone's own compass** as a way to set the heading. A browser gives a page the compass only over HTTPS, and the unit serves plain HTTP.
- **The site's time zone** with the place, which shares this page's neighbourhood and nothing else.
- **Holding a new upload field back until the notice is read again.** The gate still sends a listed field at once.
