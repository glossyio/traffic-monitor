# A place's time zone, recorded with its data

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Series:** `place-timezone`, two planned. PR 1 = the records, PR 2 = the pages.

**Goal:** An admin sets the time zone of each place the unit is used at, the device keeps it on that place's deployment rows and sends it with shared data, and a change corrects the rows in place. The installer stops setting the device's clock to `America/Los_Angeles` on every run.

**Architecture:**
- The zone lives in three places, as a place's point does: the control app's `state.sqlite` (`surveys.timezone`), Node-RED's `config.yml` (`deployment.timezone`, for the place in use), and tmdb's `deployment` rows (a `timezone` column). Node-RED never opens `state.sqlite`, and the control app never opens tmdb.
- The store is the source. `config.yml` mirrors it: every reconcile writes the place in use's zone into the file, so a hand edit or a reset file is put back. Nothing reads a place's zone from the file.
- Node-RED's deployment engine never compares the zone. It writes the file's zone on each row it starts, and rewrites an open row of the same place whose zone differs. The rows that have ended are rewritten by one internal endpoint, which the control app calls on every change, and when a reconcile has put a zone back into the file.
- The place's zone and the clock's zone are two facts. The Location page never sets the clock, and the installer's `-z` never sets a place.
- Two pull requests. PR 1 is everything but the pages: tmdb, the flows, the control app's store, file, and API, the upload, the installer, and their docs. PR 2 is the pages and nothing else, so its review is one of UI code only.

**Tech Stack:** Node-RED 5.0.10 function nodes (JavaScript in `flows.json`), a SQLite migration run by `tmdb_migrate.py`, Python 3.11 (FastAPI, pydantic 2, ruamel.yaml; no new dependency), Ansible and Bash for the installer, Vue 3 + Vuetify 3 + TypeScript (Vitest, jsdom; no new package), pytest with the function-node harness in `script/tests/test_node_red_flows.py`, the device tests in `script/devpi/tests`, Material for MkDocs.

**Spec:** "What it must do" below.

**Repo:** `glossyio/traffic-monitor`. PR 1 on `feature/place-timezone-records/370` off `dev`. PR 2 on `feature/place-timezone-pages/370` off `dev`, once PR 1 and mounting PR 3 are merged. One public issue covers both, https://github.com/glossyio/traffic-monitor/issues/370; PR 1 says "Part of", PR 2 closes it. All paths below are relative to the repo root.

**Status:** written 2026-11-25 against `dev` at `f0c360a4` (#369 merged). No public PR is open. Three pieces of work are near this one:
- **mounting PR 3, the form** (planned, not started): it works in `tm-control/ui/src/modules/location/` and `docs/use/location.md`, and it holds back while an open PR touches either. PR 1 here touches neither. PR 2 here starts after it merges.
- **setup-history PR 2, the upload:** it edits the upload gate and `upload-lists.json`. This plan adds one name to that file's `deployment` list and doesn't edit the gate.
- **tmupdate PR 2** (in progress): it edits `script/tmsetup.sh`. Task 7 changes one usage line there.
- Whichever merges second renumbers: this plan claims tmdb migration `0012` and the control app's state migration 8.

**Size** (estimates):
- PR 1 about 34 files, +1,000 to 1,300 lines, about half of it tests.
- PR 2 about 14 files, +500 to 700 lines, about 40% tests.
- To maintain afterwards: one more column in tmdb and one in `state.sqlite`; one more internal endpoint; one more API route; the zone's shape rule written twice (the flows and `zones.py`, with a test that compares them); one small pick component and one small dialog.

**Decisions.** The maintainer's are marked with a date. The rest are calls made while writing this, open to change.

1. **The zone belongs to the place. It is recorded at every precision, also at "No location stored" (maintainer, the design). The API can clear it, but the pages never do (Part B, 2026-11-26).** The operator confirms it.
2. **The place's zone and the clock's zone stay independent (maintainer, 2026-11-25).** The Location page shows one line when they differ and never changes the clock, because a clock zone change restarts the pod and nginx.
3. **Two pull requests, the records and then the pages (maintainer, 2026-11-25).** He first approved one PR. Mounting PR 3 was then given the Location page's folder, and the pages here would collide with it, so the plan split them and he approved the split the same day. The records can go now.
4. **One name, `timezone`:** the tmdb column, the `config.yml` key, the API field, the CSV column, and the store's column.
5. **`config.yml` mirrors the store.** A hand edit of `deployment.timezone` is put back at the next reconcile, as the `sharing:` block is. A point typed into the file is followed as a correction; the zone isn't, because a zone has to be one the device knows and following it would need that check in a third place.
6. **A zone is valid when the device lists it** (`timedatectl list-timezones`, the Date and time page's list). It is stored as picked, with no canonical form: `Asia/Calcutta` stays `Asia/Calcutta`.
7. **A change is an audit row with the old and new zone, not a correction row.** `survey_corrections.field` is a `CHECK`, and a third value would mean rebuilding the table again. Nothing uploads or exports the audit table.
8. **A change rewrites every row of the place, the ended ones too.** The server hears of the open rows at the next config load, as with a corrected location; nothing re-sends an ended row.
9. **`PUT /surveys/{id}/timezone` takes a place of any status.** A planned place changes in the store only.
10. **The deploy review saves a changed zone with its own request before the deploy.** The deploy route then writes the place's zone into the file with the id, in one save.
11. **The installer sets the clock's zone only with `-z`, and asks nothing.** A unit always has a zone (the imager's or the image's), and the Date and time page changes it.
12. **The upload:** `timezone` joins the `deployment` list, so telemetry rows carry it. The `deployments` attribute's per-sensor entries don't.
13. **The notice's sentence is the maintainer's** (Task 8).

## What it must do

1. **A place has one time zone or none.** A zone is an IANA name the device lists, such as `America/New_York`. Its shape, checked wherever a value is read from a file or a request to Node-RED: trimmed text of 1 to 64 characters matching `^[A-Za-z0-9_+-]+(/[A-Za-z0-9_+-]+){0,2}$`.
2. **Where it is kept.** `surveys.timezone` (TEXT, NULL for none); `deployment.timezone` in `config.yml` for the place in use (blank for none); `deployment.timezone` in tmdb (TEXT, NULL for none) on every row of the place.
3. **Setting it.** `POST /surveys` and `PATCH /surveys/{id}` take it for a planned place. `PUT /surveys/{id}/timezone` sets or clears it for any place. The places CSV import takes a `timezone` column, and the export writes one.
4. **A change never starts a deployment.** Open rows of the place in use are rewritten by the engine or the endpoint, ended rows by the endpoint. A place that isn't in use changes in the store and, when it was used, in its rows.
5. **The file follows the store.** After any reconcile the file's `deployment.timezone` equals the place in use's zone. A file with no such key and a place with no zone is left as it is.
6. **Deploying** writes the place's zone into the file with its id. The new rows carry it from their start.
7. **The upload** sends `timezone` on deployment rows, at every precision.
8. **`GET /surveys`** answers each place's `timezone` and the device clock's zone as `clock_timezone`.
9. **The pages (PR 2).** The maintainer changed the default on 2026-11-26, before any page code: a place starts with the unit's clock's time zone, not the browser's, and nothing on the page clears a time zone.
   - One **Time zone** control in Add a place, Edit, the deploy review, and the dialog below. It shows a "Time zone" label, the line "`<time zone>`, the same as the unit's clock", and one box, "This place is in a different time zone". Ticking the box opens the list, the Date and time page's picker over `GET /api/v1/time/timezones`; unticking it puts the clock's time zone back. The name is saved with the place, never a marker that follows the clock. The box starts ticked when the starting value differs from the clock's. When the clock's time zone is unknown, there is no line and no box, and the list shows at once.
   - Its hint, "Recorded with this place's data, also when no location is stored.", always shows. When the list can't be loaded, the box still works; ticked, the list is disabled and shows the error in place of the hint.
   - The browser's time zone is never used, and no field on the page clears a time zone: no clear button and no "None" choice. The API still takes null, and the page never sends it.
   - Each used or in-use place's panel shows **Time zone** ("Not set" for none) and has a **Time zone** button that opens a dialog with the same control. The dialog says: "Changing it corrects this place's stored deployments. It starts no new deployment." Its Save is off only when there is no time zone to send.
   - On the place in use, with no time zone: "This place has no time zone. Set one so its data can be read in local time."
   - On the place in use, when its time zone and the clock's differ: "The unit's clock is set to `<time zone>`. Change it on Date and time.", with a link to `/time`.
   - The import's preview shows each line's time zone as "Time zone: `<time zone>`".
10. **The installer** changes the clock's zone only when `-z` is given.

## Where the code stands that this plan touches

Read at `dev` `f0c360a4`.

- **tmdb.** `container/node-red-tm/schema/migrations/` ends at `0011_deployment_mounting.sql`. `deployment` has `id, entryStartDateTime, entryEndDateTime, lat, lon, sensorType, sensorName, deviceName, survey_id, location_precision, heading_deg, pitch_deg, height_m, view_distance_m, mount`. `tests/helpers.py` holds `LATEST_VERSION = 11`. `tests/test_0011_deployment_mounting.py` finds its columns by counting from the end (`names[-5:]`), which a later column breaks. `test_flows_sql.py` compiles every static SQL statement in `flows.json` against the migrated schema. `schema.sql` is regenerated as the schema README says.
- **Flows, `init-config` tab.**
  - "init config defaults" (`94136e5a6f092bb6`) settles `msg.payload.deployment`: `lat`, `lon`, `survey_id` (lower-cased, or `null` with a `node.error` that names the key), `database_precision`.
  - "deployment engine" (`689b64c16a889e0a`): `decide()` with rules 1 to 6, `insertRow`, `rewriteRow`, `keepRow`; four outputs (close, insert, rewrite, the rows for ThingsBoard). Its statements are the sqlite nodes "insert deployment" (`f5e4484aeb11facf`) and "rewrite deployment" (`94dad283c8f696f4`); the open rows come from the template `696c3a7b0b83f7b5`.
  - The internal endpoints sit in the group `3da2c0e89c06736d`. The location correction is the model: `http in` (`787e6f820c6aa230`) → "tm-internal: check token" → "tm-internal: validate location correction" (two outputs) → the prepared sqlite node "re-round survey coordinates" → "tm-internal: answer location correction" → `http response`.
- **The upload.** `container/node-red-tm/data/upload-lists.json` has a `deployment` list, and the gate cuts each deployment row to it.
- **Flows tests** (`script/tests/test_node_red_flows.py`): `ENGINE_SQL`, `OPEN_ROWS_SQL`, `ROW_KEYS`, `open_row()`, `engine()`, `TM_INTERNAL_PATHS`, `TM_INTERNAL_METHODS`, `VALIDATORS`, `DEPLOYMENT_COLUMNS`, `test_upload_lists_file`, `test_every_deployment_row_key_is_on_the_upload_list`, and `test_the_flows_read_a_heading_as_the_control_app_does` (the model for a rule kept in two languages).
- **The control app** (`tm-control/backend/tm_control/`).
  - `core/state.py`: seven migrations; `surveys` has no zone.
  - `modules/location/places.py`: `Survey`, `Places.create`, `update_planned`, `set_point`, `_SURVEY_COLUMNS`.
  - `modules/location/config.py`: `Deployment`, `_parse_deployment`, `NodeRedConfig.set_place`, `set_survey_id`, `set_precision`; `save()` writes only when the text changed.
  - `modules/location/reconcile.py`: `_follow` puts a reset file's id, precision, headings, and mounting back, and its `_saved(config, restoring)` saves only when restoring.
  - `modules/location/router.py`: `SurveyIn`, `SurveyOut`, `PlacesState`, `ImportRow`, `create_place`, `edit_place`, `deploy_place`, `correct_location` (the model for the new route's order: the file, the store, the audit row, Node-RED, and a 502 that says to do it again), `export_places`, `_parse_csv`, `_import_row`, `_region` (how the device's zone is read in fake mode and on a device).
  - `adapters/nodered.py`: `NodeRed.correct_location`. `fake.py`: `FakeNodeRed._engine` repeats the engine's rules, and `FakeClock.list_timezones`.
  - `modules/time/router.py`: `GET /time/timezones` answers `timedatectl list-timezones` to any signed-in user.
- **The installer.** `defaults/main.yml` has `tmsetup_timezone: 'America/Los_Angeles'`. `tasks/base_setup.yml`'s "TMSetup - Base Setup - Set timezone" runs on every run, under `always`. `tmsetup.sh -z` passes `tmsetup_timezone`.
- **The UI** (`tm-control/ui/src/modules/location/`): `PlaceForm.vue`, `DeployReview.vue`, `PlaceDetails.vue`, `ImportPlaces.vue`, `LocationPage.vue`. `modules/time/TimePage.vue` has the zone picker this plan's is modelled on (a `v-autocomplete` over `GET /time/timezones`).

## Global Constraints

- **The name, the shape, and the page's words are those in "What it must do".** No task picks another.
- **A zone never starts or ends a deployment,** in the flows or in fake mode.
- **The control app never opens tmdb, and Node-RED never opens `state.sqlite`.**
- **Not private, but not noisy.** A zone may appear in an audit row. It appears in no log line, no error message, and no config error: those name the key or the column. No coordinate, description, or reason is logged, audited, or put in an error message, as before.
- **Flows:** edit `flows.json` programmatically and write it back with `json.dumps(flows, indent=4, ensure_ascii=False)` and no trailing newline. New nodes go on the tab and in the group of the nodes they sit beside. No `CREATE` or `ALTER TABLE` in the flows.
- **UI work follows `tm-control/ui/README.md`:** conventional Vuetify, the one dark theme, system fonts, 44 px buttons, results beside the form, no toasts, sentence case. Each UI task's implementer loads the `frontend-design` skill and works test-first; the README's rules win over the skill's taste. New design notes go in the README.
- The API files (`tm-control/ui/src/api/openapi.json`, `schema.d.ts`) are regenerated in the same commit as any model change.
- No coordinate in any fixture, commit, PR text, or screenshot other than the docs' example `45.52252, -122.69120` and the fixtures' `45.0, -122.0`. Test zones are `America/New_York`, `Asia/Tokyo`, and `Europe/Berlin`, which fake mode's clock lists; `Mars/Olympus` is the name no device lists.
- Every commit ends with the trailer block from the repo's `CLAUDE.md` (Assisted-by / AI-Model / AI-Effort / AI-Role); never `Co-Authored-By`. Docs follow "Writing docs" in `docs/development/contributing.md`; `mkdocs build --strict` passes. Nothing public names a device, a bench site, a partner, or a tool.
- PR titles start `place-timezone PR <n>: `, and each PR's first body line is the `Series:` line.
- On a dev Pi: Frigate's detection, snapshots, and recording stay off. No item in this plan needs them.
- Off-device checks before each commit, from the repo root in the dev venv: `python -m pytest container/node-red-tm/schema/tests script/tests tm-control/backend/tests`; for UI tasks also the pinned Node image's `npm ci && npm run build && npm test`; for docs tasks `~/.venvs/tm-docs/bin/mkdocs build --strict`.

## Review Focus

1. **A zone the device doesn't list.** A name can be missing from the device's tzdata (`Asia/Calcutta` on a unit without the legacy names, or a zone newer than the unit's data). The pages never take a name from the browser, so only a typed CSV line or a direct request can bring one; the API refuses the name with a 422 that names the field; a CSV line is refused, and the preview names the line. Tests in Task 6 (`test_an_unknown_zone_is_refused_and_changes_nothing`, `test_the_import_refuses_an_unknown_zone_by_column`).
2. **Node-RED is down while a zone changes.** The store and the file change, the route answers 502 and says to save again, and saving the same zone again rewrites the rows. A planned place needs no Node-RED. Tests in Task 6 (`test_a_change_without_nodered_answers_502_and_keeps_the_change`, `test_saving_the_same_zone_again_rewrites_the_rows`, `test_a_planned_place_needs_no_nodered`).
3. **Nothing starts a deployment:** a zone set, changed, or cleared; a file put back after a hand edit; a reset file; the upgrade, where the file has no key and every row is NULL. Tests in Task 2 (`test_engine_never_starts_a_deployment_for_a_zone`, `test_engine_keeps_rows_from_before_the_columns`), Task 5 (`test_a_reset_file_gets_the_zone_back_in_the_same_save`, `test_a_file_without_the_key_is_left_alone_when_the_place_has_no_zone`, `test_fake_engine_heals_the_zone_and_starts_nothing`), and Task 6 (`test_a_change_keeps_every_deployment_id`).
4. **A wrong value in the file:** a number, `not a zone!`, `../../etc/passwd`, four parts, 65 characters. Node-RED reads none and reports the key without the value, no row takes it, and the next reconcile writes the place's own zone back. Tests in Task 2 (`test_init_config_defaults_timezone`), Task 4 (`test_read_zone`, `test_the_flows_read_a_zone_as_the_control_app_does`), and Task 5 (`test_a_hand_edited_zone_is_put_back`).
5. **"No location stored" still records the zone,** and a run of the installer leaves both zones alone. Tests in Task 2 (`test_engine_records_the_zone_with_no_location`) and Task 7 (`test_the_installer_sets_no_time_zone_unless_asked`).

---

# Part A: the records (place-timezone PR 1)

PR 1 changes no page. After it, a zone is set through the API or the places CSV, and the Location page neither shows nor loses it.

### Task 1: tmdb: `timezone` on `deployment`

**Files:**
- Create: `container/node-red-tm/schema/migrations/0012_deployment_timezone.sql`, `container/node-red-tm/schema/tests/test_0012_deployment_timezone.py`
- Modify: `container/node-red-tm/schema/schema.sql` (regenerated), `container/node-red-tm/schema/tests/helpers.py`, `container/node-red-tm/schema/tests/test_0011_deployment_mounting.py`

**Interfaces:**
- Produces: `deployment.timezone TEXT`, the table's last column, NULL on every row that exists. `LATEST_VERSION = 12`.

- [ ] **Step 1: Write the failing tests** in `test_0012_deployment_timezone.py`, on the shape of `test_0011_deployment_mounting.py` (a database migrated through `0011` with one open and one closed row).
  - `test_0012_adds_the_column_and_rewrites_no_row`: `user_version` goes from 11 to `LATEST_VERSION`; `columns(db_path, "deployment")[-1] == "timezone"`; its declared type is `TEXT`; every row is as before with `None` added.
  - `test_0012_applies_to_a_legacy_shaped_deployment_table`: `LEGACY_SCHEMA` migrates to `LATEST_VERSION` and `"timezone" in columns(db_path, "deployment")`.
- [ ] **Step 2: Run** `python -m pytest container/node-red-tm/schema/tests`. The two fail.
- [ ] **Step 3: Write the migration.** A header comment in the style of `0011` (what the column holds, that it is optional, that no row is rewritten, that the name is checked where it is read), then `ALTER TABLE deployment ADD COLUMN timezone TEXT;`.
- [ ] **Step 4: Regenerate `schema.sql`** with the README's command, set `LATEST_VERSION = 12`, and change `test_0011`'s position check to find its four columns right after `heading_deg` (`names[i:i + 5]` from `names.index("heading_deg")`), so it no longer counts from the end.
- [ ] **Step 5: Run** the schema tests. PASS.
- [ ] **Step 6: Commit** ("Add the time zone column to the deployment table").

### Task 2: Node-RED reads the zone, records it, and uploads it *(tricky)*

**Files:**
- Modify: `container/node-red-tm/data/flows.json` (nodes `94136e5a6f092bb6`, `689b64c16a889e0a`, `f5e4484aeb11facf`, `94dad283c8f696f4`, `696c3a7b0b83f7b5`), `container/node-red-tm/data/upload-lists.json`, `container/node-red-tm/data/README.md` if it lists the fields
- Test: `script/tests/test_node_red_flows.py`

**Interfaces:**
- Produces: `global.config.deployment.timezone`, a zone by item 1's shape, or `null`. A missing, `null`, or `''` value is `null` with no error. Any other value that isn't a zone is `null` with `node.error("Node-RED config.yml key deployment.timezone is not a time zone name; ignoring it")`: the key, never the value.
- Produces, the statements:
  - "insert deployment": the column list and the values each gain `timezone` / `$timezone` as their last entry.
  - "rewrite deployment": `UPDATE deployment SET survey_id = $survey_id, lat = $lat, lon = $lon, location_precision = $location_precision, heading_deg = $heading_deg, timezone = $timezone WHERE id = $id;`
  - The open rows' SELECT gains `timezone` after `mount`.
- Produces, the engine's rules. `zone` is `global.config.deployment.timezone` or `null`; a row with no `timezone` key reads as `null`.
  - Rule 2 and rule 5 (a row starts): the new row's `timezone` is `zone`.
  - Rule 4 (a row from before any survey is adopted): the rewrite sets `zone`.
  - Rule 6 (the same deployment): when the row's zone isn't `zone`, the row is rewritten with `zone`. A precision that also re-rounds the row makes one rewrite, not two.
  - Rule 3 (no survey in the file): the row's zone stays as it is, also when its precision is re-rounded.
  - Rule 5 never looks at the zone.
  - The rows for ThingsBoard carry `timezone`.
- Produces: `upload-lists.json`'s `deployment` list ends with `"timezone"`.

- [ ] **Step 1: Write the failing tests.** `ENGINE_SQL`, `OPEN_ROWS_SQL`, `ROW_KEYS`, and `DEPLOYMENT_COLUMNS` gain the column; `open_row()` gains `timezone=None`.
  - `test_init_config_defaults_timezone(given, expected, errors)`: `"America/New_York"` and `" Europe/Berlin "` give the name, trimmed, and no error; a missing key, `None`, and `''` give `None` and no error; `5`, `"not a zone!"`, `"../../etc/passwd"`, `"a/b/c/d"`, and a 65-character name each give `None` and one error whose text has `deployment.timezone` and not the value.
  - `test_engine_inserts_rows_with_the_places_zone`: a fresh database and `{**ENGINE_PLACE, "timezone": "America/New_York"}`: every insert has `$timezone` `"America/New_York"`, and the rows for ThingsBoard carry it.
  - `test_engine_never_starts_a_deployment_for_a_zone(row_zone, file_zone)`, for `(None, "America/New_York")`, `("America/New_York", None)`, and `("America/New_York", "Asia/Tokyo")`: no close, no insert, one rewrite per open row whose parameters are the row's own values with `$timezone` the file's, and the same deployment ids in the global context.
  - `test_engine_leaves_matching_open_rows_alone` also holds with the same zone on both sides.
  - `test_engine_keeps_rows_from_before_the_columns`: rows with no `timezone` key and a file with none write nothing.
  - `test_engine_without_a_survey_id_leaves_the_zone`: a file with no survey and no zone, and rows with `"America/New_York"`: nothing is written.
  - `test_engine_adopts_a_row_with_the_zone`: rule 4's rewrite has `$timezone` the file's.
  - `test_engine_lowers_precision_and_sets_the_zone_in_one_rewrite`: a coarser precision and a new zone give one rewrite per row with both.
  - `test_engine_records_the_zone_with_no_location`: `database_precision: "none"` and a zone: the inserts have NULL coordinates and the zone.
  - `test_upload_lists_file` expects the longer list; `test_every_deployment_row_key_is_on_the_upload_list` passes through `ROW_KEYS`.
- [ ] **Step 2: Run** `python -m pytest script/tests/test_node_red_flows.py -k "timezone or engine or upload_lists or deployment_row"`. The new ones fail.
- [ ] **Step 3: Edit the five nodes and the list file.** In "init config defaults" the zone is settled after `database_precision`, in that block's style. In the engine, `rewriteRow` takes the zone to write, and `keepRow` decides rule 3 and rule 6 apart. The engine's opening comment says the zone is never compared.
- [ ] **Step 4: Run** `python -m pytest script/tests container/node-red-tm/schema/tests`. PASS.
- [ ] **Step 5: Commit** ("Record a place's time zone on its deployment rows and send it with them").

### Task 3: The internal endpoint

**Files:**
- Modify: `container/node-red-tm/data/flows.json` (new nodes in the group `3da2c0e89c06736d`; the scope of the catch that covers that group's sqlite nodes)
- Test: `script/tests/test_node_red_flows.py`

**Interfaces:**
- Produces: `POST /tm-internal/surveys/:id/timezone`. Body `{"timezone": <a zone by item 1's shape> | null}`; the key is required. Answers 204 with no body; 400 `{"error": "bad_request", "detail": "survey_id" | "timezone"}`. Nothing is logged or echoed. Validator: "tm-internal: validate timezone correction". Statement, named "rewrite survey timezone": `UPDATE deployment SET timezone = $timezone WHERE survey_id = $survey_id;`

- [ ] **Step 1: Write the failing tests.**
  - `TM_INTERNAL_PATHS`, `TM_INTERNAL_METHODS`, and `VALIDATORS` gain the endpoint, so the token and refusal tests cover it.
  - `test_timezone_correction_is_validated(survey_id, body, detail)`: `{"timezone": "America/New_York"}` and `{"timezone": null}` give the two parameters; `{}`, `{"timezone": 5}`, `{"timezone": ""}`, `{"timezone": "not a zone!"}`, a 65-character name, and a malformed id each give 400 with that `detail` and reach no SQL.
  - `test_timezone_correction_runs_one_prepared_statement_and_answers_204`: through `correction_chain`, the statement's name and text, and 204 with an empty body.
  - `test_timezone_correction_rewrites_every_row_of_the_place`: on a migrated database with an open and a closed row of one survey and a row of another, the statement changes the first two and leaves the third.
- [ ] **Step 2: Run them.** They fail.
- [ ] **Step 3: Add the nodes,** a copy of the location correction's chain with new ids, placed below the group's last row. Add the sqlite node to the catch's scope and the new nodes to the group's `nodes`.
- [ ] **Step 4: Run** `python -m pytest script/tests container/node-red-tm/schema/tests`. PASS.
- [ ] **Step 5: Commit** ("Add the internal endpoint that corrects a place's time zone").

### Task 4: The control app's rule, store, and file

**Files:**
- Create: `tm-control/backend/tm_control/modules/location/zones.py`, `tm-control/backend/tests/test_zones.py`
- Modify: `tm-control/backend/tm_control/core/state.py`, `tm-control/backend/tm_control/modules/location/places.py`, `tm-control/backend/tm_control/modules/location/config.py`
- Test: `tm-control/backend/tests/test_state.py`, `test_places.py`, `test_location_config.py`, `script/tests/test_node_red_flows.py`

**Interfaces:**
- Produces, `zones.py` (standard library only, no I/O):
  - `ZONE_MAX = 64`
  - `read_zone(value) -> str | None`: the trimmed text when `value` is text of item 1's shape, else `None`. This is how a file's value is read, and what Node-RED's defaults do.
- Produces, `core/state.py`, migration 8: `ALTER TABLE surveys ADD COLUMN timezone TEXT;` with a comment on the lines of migration 6's.
- Produces, `places.py`:
  - `Survey.timezone: str | None`
  - `Places.create(..., timezone: str | None = None)`, a keyword after the existing ones
  - `Places.update_planned(survey_id, description, lat, lon, headings, timezone: str | None)`
  - `Places.set_timezone(survey_id: str, timezone: str | None, now: float | None = None) -> None`, which also sets `updated_at`
- Produces, `config.py`:
  - `Deployment.timezone: str | None`, `read_zone` of the file's value
  - `NodeRedConfig.set_timezone(timezone: str | None) -> bool`: writes `deployment.timezone` as plain text, added after `database_precision` when the block has no such key. `None` blanks a key that is there and adds none. It answers whether it changed the block's value (the raw value, not `read_zone` of it), which is what the reconcile saves on.

- [ ] **Step 1: Write the failing tests.**
  - `test_zones.py::test_read_zone(given, expected)`: the cases of Task 2's `test_init_config_defaults_timezone`, with the same answers.
  - `test_node_red_flows.py::test_the_flows_read_a_zone_as_the_control_app_does`: one table of values run through "init config defaults" and through `zones.read_zone`, on the shape of `test_the_flows_read_a_heading_as_the_control_app_does`.
  - `test_state.py`: the version checks expect 8; `test_migration_8_adds_the_zone_and_keeps_every_place`: a store at version 7 with a place keeps it, with `timezone` NULL.
  - `test_places.py`: `test_a_place_is_created_with_its_zone`, `test_update_planned_replaces_the_zone` (to a name and to `None`), `test_set_timezone_changes_the_zone_and_the_updated_time`, `test_a_place_from_before_has_no_zone`.
  - `test_location_config.py`: `test_deployment_reads_the_zone` (a name, a blank, a missing key, junk as `None`); `test_set_timezone_writes_plain_text_after_the_precision`; `test_set_timezone_none_blanks_the_key`; `test_set_timezone_none_adds_no_key` (the saved text is the loaded text); `test_set_timezone_keeps_the_files_comments`.
- [ ] **Step 2: Run them.** They fail.
- [ ] **Step 3: Write `zones.py`, migration 8, and the store's and the file's parts.**
- [ ] **Step 4: Run** `python -m pytest tm-control/backend/tests script/tests`. PASS.
- [ ] **Step 5: Commit** ("Keep each place's time zone in the control app's store and config.yml").

### Task 5: The reconcile, the Node-RED client, and fake mode

**Files:**
- Modify: `tm-control/backend/tm_control/modules/location/reconcile.py`, `tm-control/backend/tm_control/adapters/nodered.py`, `tm-control/backend/tm_control/fake.py`
- Test: `tm-control/backend/tests/test_reconcile.py`, `test_nodered_adapter.py`, `test_fake_nodered.py`

**Interfaces:**
- Consumes: Task 4's `Survey.timezone`, `Deployment.timezone`, `NodeRedConfig.set_timezone`; Task 3's endpoint.
- Produces: `NodeRed.set_timezone(survey_id: str, timezone: str | None) -> None`, a POST to `/surveys/<id>/timezone` with `{"timezone": timezone}`.
- Produces, `FakeNodeRed`: every row has `timezone`; its engine follows Task 2's rules; `set_timezone` rewrites every row of the survey and raises `NodeRedError("bad_request", 400)` for what the endpoint refuses.
- Changes, `_follow`: once the place in use is known, `config.set_timezone(current.timezone)` is part of whatever that run saves, and a run that would have saved nothing saves when that changed the file. Such a run answers `followed="restored"`. The hand-deploy branch writes the named place's zone with its point. A place created from the file (`_create_from_file`, `_first_run`) has no zone, whatever the file holds. A run that put the zone back then calls `nodered.set_timezone` for the place, best effort as `_re_round` is, so a row that ended while the file held the wrong zone is corrected too.

- [ ] **Step 1: Write the failing tests.**
  - `test_reconcile.py`:
    - `test_a_reset_file_gets_the_zone_back_in_the_same_save`: a file without id and zone, a place in use with `America/New_York`: one save puts both back (one backup file), and the fake's deployment ids are the same.
    - `test_a_hand_edited_zone_is_put_back`: the file says `Europe/Berlin`, the place `America/New_York`: after `ensure` the file says `America/New_York`, the place is unchanged, and no correction row is written.
    - `test_a_file_without_the_key_is_left_alone_when_the_place_has_no_zone`: the file's text is byte for byte as before.
    - `test_a_zone_in_the_file_of_a_place_with_none_is_blanked`.
    - `test_a_hand_deploy_writes_the_places_zone`: the file names a planned place by hand; after `ensure` the file holds that place's zone.
    - `test_the_file_never_gives_a_place_its_zone`: a file with an unknown id and a zone creates a place with `timezone` `None`.
  - `test_nodered_adapter.py::test_set_timezone_posts_the_body`: the path, the method, and both bodies (a name, `null`).
  - `test_fake_nodered.py`: `test_rows_carry_the_zone`; `test_fake_engine_heals_the_zone_and_starts_nothing` (ids unchanged after the file's zone changes and after it is cleared); `test_fake_engine_without_a_survey_leaves_the_zone`; `test_fake_set_timezone_rewrites_every_row_of_the_place` (open, closed, and not another survey's); `test_fake_set_timezone_refuses_what_the_flows_refuse` (a bad id, `5`, `""`, `"not a zone!"`).
- [ ] **Step 2: Run them.** They fail.
- [ ] **Step 3: Write the three parts.** `_saved` saves when the run restores a reset file or the place's zone changed the file, and says `restored` then, unless an unknown id was followed in the same run (`unknown_id`); otherwise it writes nothing, so a hand edit that is only formatting stays as typed.
- [ ] **Step 4: Run** `python -m pytest tm-control/backend/tests`. PASS.
- [ ] **Step 5: Commit** ("Put a place's time zone back into config.yml on every reconcile").

### Task 6: The API *(tricky)*

**Files:**
- Modify: `tm-control/backend/tm_control/modules/location/router.py`, `tm-control/ui/src/api/openapi.json`, `tm-control/ui/src/api/schema.d.ts`, and the UI test fixtures that build a `SurveyOut`, a `PlacesState`, or an `ImportRow` (`tm-control/ui/tests/fake-api.ts` and the Location specs), which gain the new fields and change nothing else
- Test: `tm-control/backend/tests/test_api_surveys.py`, `test_openapi_document.py`

**Interfaces:**
- Consumes: Tasks 4 and 5.
- Produces, the models: `SurveyIn.timezone: str | None = Field(default=None, max_length=64)`; `SurveyOut.timezone` (from `Survey`); `PlacesState.clock_timezone: str | None` (the device clock's zone, `None` when it can't be read); `ImportRow.timezone: str | None`; `TimezoneIn {timezone: str | None = Field(max_length=64)}`, the key required.
- Produces: a zone in a request is trimmed, a blank one is none, and a name that isn't in the device's list (`list_timezones()` of the fake clock in fake mode, of `timedate` otherwise) is refused: 422 `validation`, field `timezone`, "The device doesn't know that time zone." A list that can't be read is the Date and time page's 500.
- Produces: `PUT /surveys/{survey_id}/timezone` → `SurveyOut`. Admins only. Under the reconcile lock, after `_reconciled`:
  1. 404 for no such place; the zone is checked.
  2. The place in use: the file must name it (else `_not_the_place`, 409); `config.set_timezone`, then `save_config`.
  3. The store, when the zone differs from the stored one, and then an audit row `survey.timezone` with the detail `<survey id> <old>><new>`, where a missing zone is written `none`.
  4. A place that isn't planned: `nodered.set_timezone`, also when the zone was already the stored one. A `NodeRedError` is a 502 with "The place's time zone changed, but its stored rows weren't updated. Save it again."
- Changes: `create_place` and `edit_place` pass the checked zone on. `deploy_place` calls `config.set_timezone(place.timezone)` beside `set_place`, in the same save.
- Changes, the CSV:
  - The export's header is `survey_id, lat, lon, timezone, status, created_at, updated_at`; a place with no zone has an empty cell.
  - The import takes a column whose header is exactly `timezone`, anywhere after `lon`. It is the zone and never a sensor's column. An empty cell is none. A name the device doesn't list refuses the line with "The time zone isn't one the device knows." The dry run answers each row's `timezone`.

- [ ] **Step 1: Write the failing tests** in `test_api_surveys.py`.
  - `test_a_place_is_planned_and_edited_with_a_zone`: POST and PATCH with a zone, with a blank, and without the key.
  - `test_an_unknown_zone_is_refused_and_changes_nothing`: POST, PATCH, and PUT with `Mars/Olympus` each answer 422 with field `timezone`; the store, the file, and the fake's rows are as before.
  - `test_put_sets_the_zone_of_the_place_in_use`: the answer, the store, the file, and every row of the place hold it; one audit row with `none>America/New_York`.
  - `test_a_change_keeps_every_deployment_id`: set, change, and clear, with the ids compared after each.
  - `test_put_clears_the_zone`: `null` gives a blank key, NULL rows, and an audit row ending `>none`.
  - `test_put_on_a_used_place_rewrites_its_rows_and_not_the_file`.
  - `test_a_planned_place_needs_no_nodered`: with the fake down, a PUT on a planned place answers 200.
  - `test_a_change_without_nodered_answers_502_and_keeps_the_change`: the store and the file changed, the message is the one above.
  - `test_saving_the_same_zone_again_rewrites_the_rows`: after that 502, the same PUT with the fake up answers 200, the rows hold the zone, and no second audit row is written.
  - `test_put_refuses_a_file_that_names_another_place`: 409 `config_changed`, nothing written.
  - `test_put_needs_an_admin_and_a_known_place`: 403 for a viewer, 404 for an unknown id.
  - `test_deploying_writes_the_places_zone`: the file and the new rows hold it from their start; deploying a place with no zone blanks the key.
  - `test_get_surveys_answers_the_clocks_zone`: `clock_timezone` is the fake clock's.
  - `test_the_export_has_a_zone_column`: the header and one row with a zone, one without.
  - `test_the_import_takes_a_zone_column`: `description,lat,lon,timezone` and `description,lat,lon,<sensor>,timezone`, a dry run and a real one.
  - `test_the_import_refuses_an_unknown_zone_by_column`: the problem's message has no part of the value.
  - `test_a_zone_never_reaches_a_log_line`: with `caplog`, a set, a refusal, and a 502 log nothing that holds the zone.
  - `test_openapi_document.py` gains the route.
- [ ] **Step 2: Run them.** They fail.
- [ ] **Step 3: Write the route, the model fields, and the CSV's column.**
- [ ] **Step 4: Regenerate the API files** (the UI README's two commands), add the new fields to the UI's fixtures, and run the UI's build and tests in the pinned Node image. PASS, with no component changed.
- [ ] **Step 5: Run** `python -m pytest tm-control/backend/tests script/tests`. PASS.
- [ ] **Step 6: Commit** ("Add a place's time zone to the Location API and the places CSV").

### Task 7: The installer leaves the clock's zone alone

**Files:**
- Modify: `script/ansible/roles/tmsetup/defaults/main.yml`, `script/ansible/roles/tmsetup/tasks/base_setup.yml`, `script/tmsetup.sh` (the usage line for `-z`), `script/ansible/roles/tmsetup/README.md` (its `tmsetup_timezone` line)
- Modify: `tm-control/backend/tm_control/modules/location/region.py` and `fake.py` (comments that say the installer sets `America/Los_Angeles`), `docs/reference/tmsetup.md`, `docs/use/device-health.md`, `docs/configuration/node-red-config.md`
- Test: `script/tests/test_tmsetup_templates.py`, or the module beside it that reads the role's task files

**Interfaces:**
- Produces: `tmsetup_timezone: ''`. "TMSetup - Base Setup - Set timezone" has `when: tmsetup_timezone | length > 0`. The usage line reads `"-z TIMEZONE" "Set the device's time zone (left as it is unless given)"`.

- [ ] **Step 1: Write the failing test** `test_the_installer_sets_no_time_zone_unless_asked`: the default is `''`; the task that calls `community.general.timezone` has that `when`; `tmsetup.sh`'s usage text has no `America/Los_Angeles`.
- [ ] **Step 2: Run it.** It fails.
- [ ] **Step 3: Make the three changes,** and correct the comments.
- [ ] **Step 4: The docs.**
  - `reference/tmsetup.md`: `-z` sets the device's time zone; without it the installer leaves the zone as it is.
  - `device-health.md`: the Date and time page sets the zone; `-z` is another way.
  - `node-red-config.md`: the sentence on time settings says the same.
- [ ] **Step 5: Run** `python -m pytest script/tests`, the two `ansible-playbook` checks and `bash -n script/tmsetup.sh` from the repo's `CLAUDE.md`, and `mkdocs build --strict`. PASS.
- [ ] **Step 6: Commit** ("Leave the device's time zone alone unless the installer is given -z").

### Task 8: The notice, the docs, the device tests, and the plan's public copy

**Files:**
- Modify: `tm-control/backend/tm_control/modules/sharing/NOTICE.md` (Step 1), `container/node-red-tm/config/config.yml.j2`
- Modify: `docs/data-and-payloads/data-overview.md`, `docs/data-and-payloads/integrations.md`, `docs/configuration/node-red-config.md`, `docs/use/sharing.md`, `docs/development/tm-control.md`, `CLAUDE.md`
- Modify: `script/devpi/tests/test_web.py`
- Create: `design/plans/2026-11-25-place-time-zone.md`

- [ ] **Step 1: Draft the notice's sentence, and stop.** The notice is the maintainer's text. Propose, under "Share data", after the sentence on how each sensor is mounted: "It also sends the time zone you set for the place, also when no location is stored." Show him the paragraph before and after, and take his wording and his decision on the notice's version.
- [ ] **Step 2: The template.** `config.yml.j2`'s `deployment:` block gains, after `database_precision`, `timezone:  # the place's time zone, set on the control app's Location page; an edit here is put back`. `test_node_red_config_template_has_no_time_section` still passes, and its docstring drops the installer.
- [ ] **Step 3: The device tests.**
  - `test_a_places_time_zone_needs_an_admin`: a viewer's PUT is refused with 403.
  - `test_surveys_answer_each_places_zone_and_the_clocks`: every survey in `places_state` has a `timezone` key, and `clock_timezone` equals `timedatectl show -p Timezone --value` on the host.
- [ ] **Step 4: The docs.**
  - `data-overview.md`, the `deployment` table: `timezone`, "the place's time zone as a tz database name, empty when none was set"; a line that a change corrects the place's rows and starts no deployment.
  - `node-red-config.md`, "deployment": the key, that the control app writes it, and that a hand edit is put back.
  - `integrations.md` and `sharing.md`: deployment rows carry `timezone`.
  - `tm-control.md`: the route; `surveys.timezone`; the internal endpoint in the Node-RED table; that the file mirrors the store; the order of a change and what a 502 means; the CSV's column.
  - `CLAUDE.md`: the Location clause (the route, and `deployment.timezone` among what the page writes and puts back); the internal endpoints' count and the new one; that the installer sets the clock's zone only with `-z`.
- [ ] **Step 5: The plan's public copy:** this file, as `design/plans/2026-11-25-place-time-zone.md`.
- [ ] **Step 6: Run** every off-device check and `mkdocs build --strict`. PASS.
- [ ] **Step 7: Commit** the template and device tests, then the docs, then the plan's copy, then the notice with the maintainer's wording.

### Task 9: Pi plan and PR 1

- [ ] **Step 1: Pi plan,** as a logged `tmdev check` on a bench unit marked `pii_free`. Frigate's detection stays off throughout; say so in the check. Note the unit's clock zone at the start and put it back at the end.
  1. Set the clock's zone to `America/New_York` on the Date and time page's API, and note the open deployment ids. Then `tmdev deploy <host> -- -t node-red-tm -t tm-control`. After it: the clock's zone is still `America/New_York`; the device suite passes; `tmdb_migrate.py --check` says up to date at version 12; the journal has `applied 0012_deployment_timezone.sql`; the open ids are the same; `config.yml` has no new key.
  2. `PUT /surveys/<the place in use>/timezone` with `Asia/Tokyo`: 200; the same deployment ids; every row of the place in tmdb, the file, and `GET /surveys` hold it; one audit row.
  3. By hand in `config.yml`: `timezone: Europe/Berlin`. Load `GET /surveys`: the file says `Asia/Tokyo` again, the rows too, and the ids are the same.
  4. By hand: `timezone: 5`. Node-RED's log names the key and no value. After `GET /surveys` the file is right again.
  5. `PUT` with `Mars/Olympus`: 422, and nothing changed.
  6. `tmdev deploy <host> -- -f -t node-red-tm` (ask the maintainer before any `-f`), then load the home page: the file has the place's id and zone again, and no new deployment id.
  7. Plan a second place with `America/New_York` and deploy it: its new rows hold `America/New_York`, and the first place's ended rows still hold `Asia/Tokyo`. `PUT` the first place to `Europe/Berlin`: its ended rows change, and the second place's rows and the file don't.
  8. `PUT` the place in use to `null`: its rows are NULL and the file's key is blank.
  9. `tmdev deploy <host> -- -z America/Los_Angeles -t tm-control`: the clock's zone is `America/Los_Angeles`, and the place's zone is as item 8 left it. Put the clock's zone back.
  10. **Manual, the maintainer's:** with sharing on to his test server, the deployment telemetry with `timezone` is accepted.
- [ ] **Step 2: Every off-device check once more** on the final branch; `git grep` the branch for issue numbers that aren't public, device names, and any coordinate that isn't allowed.
- [ ] **Step 3: PR 1's text,** the template filled in, "Part of" the issue.
  - Title: `place-timezone PR 1: Record each place's time zone with its data`.
  - First body line: `Series: place-timezone PR 1 of 2 · stacked on dev · next: PR 2, the Location page's time zone field · map: #370`.
  - The release note: "The device can now record the time zone of each place it is used at. The zone is kept with the place's deployments in the database and sent with shared data, also when no location is stored. It is set through the control app's API or the places CSV for now; the Location page's field comes next. The installer no longer sets the device's clock to `America/Los_Angeles` on every run: it changes the time zone only when given `-z`."
  - Also: the Docs list; the Pi plan's results; that the migration adds one column and rewrites no row; the limits (no page yet; a hand edit of the key is put back; an ended row's change isn't sent again; the gate doesn't yet hold a new field back until the notice is read again); and the AI-assistance section.
  - The maintainer reads the commit messages and the PR text before any push.

---

# Part B: the pages (place-timezone PR 2)

PR 2 changes no route, no file format, and no stored value. It starts after PR 1 and mounting PR 3 are in `dev`, and its first step re-reads `LocationPage.vue`, `DeployReview.vue`, and `PlaceDetails.vue` as mounting PR 3 left them.

**The maintainer changed the default on 2026-11-26,** after the plan was written and before any page code. The plan started a new place from the browser's time zone, with a "Filled in from this browser" line, and let a field clear it. The pages started instead from the unit's clock's time zone, with a box to choose another, and never clear one. The reasons are in the UI README's part "A place's time zone": the unit's clock is set for where the unit is, while a place planned from a desk in another time zone would get the desk's; and a time zone is recorded with the place's data, so the page offers no way to drop it. Words say "time zone" in full in every new name, since Frigate's zones are a different thing on the Cameras page: `TimeZonePick.vue`, `TimeZoneDialog.vue`, `timezones.ts`, and their specs `time-zone-pick.spec.ts`, `time-zone-dialog.spec.ts`, and `timezones.spec.ts`. The API's field stays `timezone`.

Five rulings made while building, each cheap to undo:

- **R1.** `PlaceDetails.vue` reads `place.status === 'in_use'` for the place in use's two lines, so it gets no new `inUse` prop (mounting PR 3's code already does the same).
- **R2.** The panel's **Time zone** fact shows on every used or in-use place, also when Node-RED didn't answer, because the time zone comes from the control app's store.
- **R3.** The import's "This unit's header" and its paragraph name the `timezone` column after `lon`, so the column isn't hidden from someone who copies the header.
- **R4.** Placement: the control sits after the map pick and the phone's location in the place form, after the sensors in the deploy review (before "Stored in the database"), and the **Time zone** button after **Correct location** and before **Delete**.
- **R5.** The deploy review remembers a time zone its `PUT` saved, so a deploy retried after a failed deploy doesn't send the `PUT` again.

### Task 10: The time zone pick

**Files:**
- Create: `tm-control/ui/src/modules/location/TimeZonePick.vue`, `tm-control/ui/src/modules/location/timezones.ts`
- Test: `tm-control/ui/tests/time-zone-pick.spec.ts`, `tm-control/ui/tests/timezones.spec.ts`
- Modify: `tm-control/ui/README.md` (the design note)

**Interfaces:**
- Produces, `timezones.ts`:
  - `startingTimeZone(place, clock): string | null`: the place's time zone, else the clock's, else null.
  - `loadTimeZones(): Promise<string[]>`: `GET /api/v1/time/timezones`.
- Produces, `TimeZonePick.vue`: `v-model: string | null`; props `timeZones: string[]`, `clockTimeZone: string | null`, `error?: string`, `disabled?: boolean`. The label, the line, the box, the list, and the hint of item 9, with no clear button.

- [ ] **Step 1: Write the design note** in the UI README, and show it to the maintainer before the code.
- [ ] **Step 2: Write the failing tests.**
  - `timezones.spec.ts`: the place's time zone wins; the clock's when the place has none; null when neither is known; the list is asked for from the device; a failed request is thrown as the client throws it.
  - `time-zone-pick.spec.ts`: the clock's time zone shows with the box unticked and the list hidden; ticking shows the list at the same time zone; the picked time zone is emitted; unticking emits the clock's; the box starts ticked when the value differs from the clock's; with no clock time zone the list shows and there is no box; the hint shows; there is no clear button; an error disables the list and replaces the hint, and the box still works; everything is disabled while `disabled`.
- [ ] **Step 3: Run them.** They fail.
- [ ] **Step 4: Write the two files.**
- [ ] **Step 5: Run** the UI's build and tests in the pinned Node image. PASS.
- [ ] **Step 6: Commit** ("Add the time zone control to the Location page's parts").

### Task 11: The time zone in Add a place, Edit, the deploy review, and the import's preview

**Files:**
- Modify: `tm-control/ui/src/modules/location/PlaceForm.vue`, `DeployReview.vue`, `ImportPlaces.vue`, `LocationPage.vue` (it loads the list once and passes it down)
- Test: `tm-control/ui/tests/place-form.spec.ts`, `deploy-review.spec.ts`, `import-places.spec.ts`, `location-page.spec.ts`

**Interfaces:**
- Consumes: Task 10; PR 1's `SurveyIn.timezone`, `PUT /surveys/{id}/timezone`, `ImportRow.timezone`, and `clock_timezone`.
- Produces: `PlaceForm` and `DeployReview` take `timeZones` and `timeZonesError` and read the clock's time zone from the page's state.
  - `PlaceForm`: a new place starts with the clock's time zone, an edited one with its own. The body it sends has `timezone`.
  - `DeployReview`: starts with the place's time zone, else the clock's. On Deploy, when the value differs from the place's as last saved, it sends the `PUT` first and deploys only after a 200 (and not again on a retry: R5). A failed `PUT` shows its message beside the buttons and deploys nothing.
  - `ImportPlaces`: each previewed line with a time zone shows "Time zone: `<time zone>`".
- Produces: when the list didn't load, both forms still save everything else, and the box still gives the clock's time zone.

- [ ] **Step 1: Write the failing tests** for each of those: a new place starts with the clock's; an edited one with its own; the time zone is sent with the place; the form saves without the list; the review's unchanged time zone sends no `PUT`, a changed one is saved before the deploy, and a refused one deploys nothing; the preview shows a line's time zone; the list is asked for once.
- [ ] **Step 2: Run them.** They fail.
- [ ] **Step 3: Write the four changes.**
- [ ] **Step 4: Run** the UI's build and tests. PASS.
- [ ] **Step 5: Commit** ("Set a place's time zone when it is planned and when it is deployed").

### Task 12: The time zone on a place's panel

**Files:**
- Create: `tm-control/ui/src/modules/location/TimeZoneDialog.vue`
- Modify: `tm-control/ui/src/modules/location/PlaceDetails.vue`, `LocationPage.vue`
- Test: `tm-control/ui/tests/time-zone-dialog.spec.ts`, `place-details.spec.ts`, `location-page.spec.ts`

**Interfaces:**
- Consumes: Task 10; PR 1's `PUT`, `SurveyOut.timezone`, `PlacesState.clock_timezone`.
- Produces, `TimeZoneDialog.vue`: `v-model:open`; props `place`, `timeZones`, `timeZonesError`, `clockTimeZone`; a `TimeZonePick` starting from the place's time zone, else the clock's, the sentence of item 9, Cancel and Save. Save sends the `PUT` (saving the same time zone again is allowed, so a save that failed halfway can be finished), emits `saved` with the answered place, and closes. An error stays beside the buttons; a 409 also emits `stale`. It starts over each time it opens.
- Produces, `PlaceDetails.vue`: a **Time zone** fact beside First used and Last used, "Not set" for none; the two lines of item 9, each only on the place in use, and neither when it would be wrong (no line about the clock when its time zone is unknown or the place has none).
- Produces, `LocationPage.vue`: a **Time zone** button on each used or in-use place's panel, after **Correct location**, that opens the dialog; `saved` loads the places again.

- [ ] **Step 1: Write the failing tests:** the dialog starts from the place's time zone, else the clock's; it saves and closes, also for a place with none and for the same time zone again; it shows the API's message and stays open; a 409 asks the page to load again; it starts over each time. The panel shows the time zone and "Not set", asks the place in use with none for one, says when the clock's differs with a link to Date and time, and says nothing when they match or the clock's is unknown. A used place has the button and a planned place has none.
- [ ] **Step 2: Run them.** They fail.
- [ ] **Step 3: Write the dialog and the two changes.**
- [ ] **Step 4: Run** the UI's build and tests. PASS.
- [ ] **Step 5: Screenshots in fake mode** at 375 px and 1280 px, of Add a place, the deploy review, the dialog, and a panel with each of the two lines. The docs' example place only.
- [ ] **Step 6: Commit** ("Show and change a place's time zone on the Location page").

### Task 13: Docs for the pages

**Files:**
- Modify: `docs/use/location.md`, `docs/development/tm-control.md` (the UI's parts), `tm-control/ui/README.md`, `design/plans/2026-11-25-place-time-zone.md`

- [ ] **Step 1: `docs/use/location.md`.**
  - A part "Set the place's time zone": what it is for, where the control is, that a place gets the unit's clock's time zone unless the box is ticked, that it is recorded even when no location is stored, and that the page can't clear it.
  - That it is not the device's clock: the Date and time page sets that, and the page says when the two differ.
  - In the import's part: the `timezone` column; in the export's: its `timezone` column.
- [ ] **Step 2: The public copy** gains anything Part B changed.
- [ ] **Step 3: Run** `mkdocs build --strict`. PASS.
- [ ] **Step 4: Commit** ("Document the Location page's time zone field").

### Task 14: Pi plan and PR 2

- [ ] **Step 1: Pi plan,** as a logged `tmdev check` on a bench unit marked `pii_free`, after `tmdev deploy <host> -- -t tm-control -t revproxy` (the UI ships in the revproxy image).
  1. The device suite passes.
  2. On a phone, **Add a place**: the line names the unit's clock's time zone, the box is unticked, and the browser's time zone appears nowhere. Repeat in one desktop browser.
  3. Save the place and deploy it from the review with the box ticked and another time zone chosen: the new rows hold the chosen time zone.
  4. On the place in use, **Time zone**: change it. The panel shows the new time zone, the deployment ids are the same, and the line about the unit's clock appears or goes as the two differ or match.
  5. Look for a way to clear it: there is none on the page. A place with no time zone says "Not set" and, in use, asks for one.
  6. A viewer doesn't see the Location page (unchanged).
- [ ] **Step 2: Every off-device check once more;** the grep of Task 9's Step 2.
- [ ] **Step 3: PR 2's text,** the template filled in, "Closes" the issue.
  - Title: `place-timezone PR 2: Set a place's time zone on the Location page`.
  - First body line: `Series: place-timezone PR 2 of 2 · stacked on #<PR 1> (merged) · next: none planned · map: #370`.
  - The release note: "The Location page has a Time zone setting for each place, which starts as the unit's clock's time zone when you add a place or deploy it. The page says when the place's time zone and the device's clock differ."
  - Also: the Docs list, the screenshots, the Pi plan's results, the limits, and the AI-assistance section.
  - The maintainer reads the commit messages and the PR text before any push.

## Later

- **A zone worked out from the coordinates.** It needs a boundary file on the device, and the operator's check makes it unnecessary.
- **Treating two names of one zone as the same** (`Asia/Calcutta` and `Asia/Kolkata`), for the line about the clock.
- **Setting the clock's zone from the Location page,** or the place's from the Date and time page.
- **The zone in a correction's history,** if someone needs more than the audit row.
- **Sending an ended row again** after its place's zone or location is corrected.
- **Opening the map over the place's zone** when the place has no point.
- **Holding a new upload field back until the notice is read again.** The gate still sends a listed field at once.
