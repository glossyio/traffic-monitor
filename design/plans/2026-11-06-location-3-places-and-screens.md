# Location 3: places in tm-control and the Location page

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give tm-control the list of places a unit has been, is, or will be, and a Location page where an admin adds a place, deploys the unit to it, corrects a wrong entry, lowers the stored precision, and imports places from a file, so that moving the unit is a few taps on a phone and `config.yml` is never edited by hand for it.

**Architecture:**
- `state.sqlite` gains migration 3: `surveys`, `survey_bearings`, and `survey_corrections`, as the design's section 5 has them (the `sharing_consents` table waits for plan 4). A `location` backend module owns them: `places.py` (the store), `coordinates.py` (ids, rounding, parsing), `config.py` (the edits to Node-RED's `config.yml`, through the existing round-trip writer), `reconcile.py` (first run, the upgrade import from the pre-migration backup, and following a hand edit of the file), and `router.py` (`/api/v1/surveys`).
- tm-control writes `config.yml` from the running service for the first time: the unit gets `ReadWritePaths=` for Node-RED's config directory, and every write is a round-trip edit with a backup and an atomic replace. Node-RED's watch node (node-watch, which watches the directory by name) re-reads the file, and its deployment engine from plan 1 does the rest. tm-control never opens `tmdb.sqlite`; it asks Node-RED's `/tm-internal/` endpoints, two of which are new here: the location and bearing corrections.
- The UI gets a `location` module: the page, a place form, the deploy review step, the correction dialog, and the CSV import, in the conventions of the Device and Detection pages. Coordinates are typed or pasted, or taken from the phone on HTTPS; the map pin and the public-map block picker come with plan 4, which needs the map anyway.
- Fake mode gets a fake Node-RED that runs the engine's rules in memory and a seeded `config.yml`, so the page works on a laptop.

**Tech Stack:** Python 3.11 (FastAPI 0.162, pydantic 2, ruamel.yaml 0.19, sqlite3 and `decimal` from the standard library; no new dependency), Node-RED 5.0.8 flows (function, switch, and `node-red-node-sqlite` prepared statements), Ansible (the tmsetup role), Jinja2, Vue 3 + Vuetify 3 + TypeScript (Vitest, `openapi-fetch`; no new npm dependency), Material for MkDocs, the dev-Pi tooling (`script/devpi/tmdev.py`).

**Spec:** the location and survey-id design (not yet published; the public record is the privacy design, `design/specs/2026-10-26-location-privacy-design.md`, from PR 260, and [issue 285](https://github.com/glossyio/traffic-monitor/issues/285)), sections 1, 2, 3, 5, 6 (the two correction endpoints and the usage change), 7, 11, 12, 13, and "Open questions" 3. Its "(maintainer)" items stand; the "(call)" items are kept or changed in the "Decisions" list below, which says why. Sections 8, 9, 10, and the rest of 6 (the upload gate, the `sharing:` block, the map, the exact-location export) are plan 4. Read the design with this plan. Where this plan goes beyond the design, say so in the PR rather than picking silently.

**Status:** written 2026-11-06 against `feature/detection-page/283` at `0529e11` (PR 284, which contains PR 280, PR 278 (plan 2), PR 277 (plan 1), PR 269, PR 261, and `dev`). Branch: `feature/location-page/285`, stacked on PR 284's branch; this file was added in the PR that implements it. [Issue 285](https://github.com/glossyio/traffic-monitor/issues/285) tracks this work.

**Decisions made while writing this plan** (calls, open to change):
1. **Base branch is PR 284's, the top of the stack.** This plan edits the unit template's `ReadWritePaths=` (PR 284 added the first), `modules/__init__.py`, the UI's module list, `contracts.py` (PR 280 and 284 added checks), `CLAUDE.md`, and the control-app docs. Any lower base would conflict with the PRs above it at merge. The stacked-PR routine applies: retarget as each one merges.
2. **The map pin and the Overpass picker wait for plan 4.** Both need a map library and an online phone; plan 4's block picker needs the same map. This plan takes coordinates by typing or pasting and, on HTTPS, from the phone. The page says a map pin is coming.
3. **The exact-location copy of the database (design section 10) moves to plan 4** with the exact-location CSV of section 8: both hand exact data to a recipient, and the copy needs the `VACUUM INTO` snapshot and a 2 to 3 GB stream through tm-control, which is work of its own. So `POST /tm-internal/database/snapshot` isn't built here, and "Open questions" 3 stays open.
4. **`tm-control migrate` never touches `state.sqlite`.** The design's section 11 step 1 has migrate create the default survey; migrate runs as root, and a root-created row or journal file in the 0700 state directory would break the service. Migrate adds `database_precision: '1'` and removes per-sensor coordinates; the service's reconcile step creates the default survey on its first run and writes `survey_id`. Node-RED meanwhile runs with no survey id and keeps its open rows, which the engine adopts once the id arrives (plan 1, rule 4).
5. **Reconcile runs on every `GET /surveys` and on every status report**, not only at startup: the one-time import is flagged in the `device` table, and the cheap part (follow a hand edit of `config.yml`: an unknown `survey_id` becomes a place, changed coordinates become a `config`-sourced correction) runs each time, so the store follows the file as section 5 wants.
6. **Deploy waits for Node-RED inside the request** (up to 20 s, polling the deployments endpoint each second) and answers with the new rows and whether it saw them, instead of the page polling. The page shows one result either way; nginx's proxy read timeout is 60 s.
7. **The 409 on a changed file is server-side only.** `RoundTripFile.save` already refuses when the file changed after it was loaded; the page sends no hash. A hand edit between the page's load and its save is caught by that, and the page reloads.
8. **Deploy writes the bearing under each enabled sensor's `deployment:` block** and leaves the top-level `bearing` as it is. The engine reads only the per-sensor bearing (after copy-down), so this is the one place a bearing has to be right; the top-level value stays a default for sensors added later.
9. **Correct location requires coordinates.** A place with no location can't be "corrected" to one through that dialog (it's an edit of a planned place, or a new place); a place with coordinates can't be corrected to none. Keeps `POST /tm-internal/surveys/<id>/location` to one shape.
10. **The usage endpoint also answers the rows with no survey id** (one group with `survey_id: null`), so the page can show "Before any place was recorded" with counts; those rows aren't listed one by one.
11. **A survey's `map_mode`, `map_block_ref`, and `map_side` columns are created here but not written**; plan 4 fills them. Creating the tables once keeps migration 3 the design's shape.
12. **Correct bearing on an open row is refused while Node-RED doesn't answer**, since the row, `survey_bearings`, and `config.yml` have to change in that order; a closed row's correction needs only Node-RED, and is refused the same way.
13. **The Status page's Location check gains the places' state**: an import that hasn't run, or a `survey_id` in the file that no place has, is a warning with a link to the Location page. `Context` gets the state database for it.
14. **The "Review sharing" Status item of section 12 waits for plan 4**, which owns the consents it points at.

**Where the stack left things that this plan touches:**
- `core/state.py`: `MIGRATIONS` has two entries; `State.connect()` (WAL, foreign keys on, `sqlite3.Row`), `State.migrate()`. `core/auth.py`: `Device` (`claim`, `is_claimed`, the `device` key-value table), `Audit.record(user_id, action, detail)`, `_reading`/`_writing` context managers. `tests/test_state.py` asserts the version after a fresh migrate.
- `adapters/yamlfile.py`: `RoundTripFile(path, mapping_indent)` with `.data`, `.loaded_text`, `.save(now)` (backup `config.yml.<stamp>.bak`, `write_atomic`, keeps mode and, as root, owner; `ConcurrentEditError` when the file changed since load), `read_config(path) -> ConfigRead(data, problem, line, column)`. `core/migrate.py::_run_node_red` loads Node-RED's file with `mapping_indent=4` ("as config.yml.j2 indents"); the template's `deployment:` block is `lat`, `lon`, `bearing: 'n'`, `survey_id:` (empty, with a comment), `database_precision: '1'`.
- `adapters/nodered.py`: `STATUS_URL`, `TOKEN_HEADER = "X-TM-Internal-Token"`, `status(token) -> (code, body)`, `config_path(codedir)`, `config(codedir) -> ConfigRead`. `adapters/httpjson.py`: `get(url, headers, timeout) -> (status, bytes)`, `post(url, body, content_type, headers, timeout)`, `get_json`, loopback-only, `TIMEOUT = 3`. `core/secrets.py`: `Secrets.node_red_internal_token` (a property), `FakeSecrets`.
- Node-RED's `/tm-internal/` endpoints (`init-config` tab, plan 1): `GET /status` (`deployment: {survey_id, database_precision}`, `config.loaded_at`, `schema_version`), `GET /deployments?survey_id=` (rows: `id, entryStartDateTime, entryEndDateTime, lat, lon, bearing, sensorType, sensorName, survey_id, location_precision`, oldest first, as `{deployments: [...]}`), `GET /surveys/usage` (`{surveys: [{survey_id, first_start, last_end, open_count, deployment_count}]}`, node `dce8e3e7d11d02ac` with `WHERE survey_id IS NOT NULL`), `GET /surveys/:id/events` (`{survey_id, event_count, first_event, last_event}`), `POST /deployments/precision` (`{precision}` → 204; `rewrite precision` `db7c70a85f045770` and `rewrite precision to none` `e1ed1757d394e260`). Each chain is http in → "tm-internal: check token" → "tm-internal: validate …" (two outputs: ok, 400) → sqlite (prepared, `msg.params` with `$names`) → "tm-internal: answer …" → http response; the shared "tm-internal: database error" function answers 500. Ids are validated with `/^[0-9a-f]{8}-si$/` (lower case only; `init config defaults` folds case and accepts an unquoted precision number, so tm-control normalises before calling).
- The deployment engine (`689b64c16a889e0a`): per enabled sensor, adopt an open row with no survey id and the same bearing; a new survey id or bearing closes the row and inserts one (`<ms>-<8 hex>-d`); a blank survey id keeps the rows; precision alone never starts a deployment, a coarser one re-rounds the open rows; coordinates are never compared. The watch node re-reads `config.yml` on any change (node-watch watches the file's directory and matches by name, so an atomic replace is an `update`; the plan's bench item 1 proves it).
- `modules/apps/contracts.py`: `GROUP = CheckGroup("config", "Configuration", [cameras_in_config, zones, radar_names, location, thingsboard, frigate_plus])`; `location()` answers `config.deployment` "Location" and today accepts only unquoted numbers and doesn't look at `survey_id` or `database_precision` (PR 277's follow-ups). `tests/test_contract_checks.py::test_cameras_match` asserts the id and title lists; `tests/fixtures/status_fake.json` lists the group's checks; `script/devpi/tests/test_web.py::CONFIG_CHECKS` names them. `core/checks.py`: `Check(id, title, status, detail, fix)`, `Fix(kind="link", href, text)`, `Context(settings, manifest, secrets)` with `probe(key, fn)`; `app.py` builds it as `lambda: Context(app.state.settings, app.state.manifest, app.state.secrets)`.
- Backend layout: `modules/__init__.py` has `Module(id, router, root_router, check_groups)` and `MODULES`; `app.py` mounts each router under `/api/v1` and sets `app.state.{settings, state, secrets, manifest, jobs, status, fake_clock}`. `modules/secrets/router.py` is the pattern for pydantic models, `require_admin`, `ApiError(status, code, message)`, and an audit row per write; `modules/detection/router.py` for a 409 while something is in progress and for `BackgroundTasks`. `modules/setup/router.py::claim` creates the first admin. `core/settings.py`: `Settings(state_dir, runtime_dir, secrets_dir, manifest_path, fake, …)`; fake mode's files live beside `state_dir` (`fake.model_cache` is `settings.state_dir.parent / "model_cache"`). `fake.py`: `reset()` recreates the state and seeds the model cache; `status_groups()` reads fixed checks from `status_fake.json`.
- Tests: `tests/conftest.py` gives `settings` (temp dirs, fake secrets, the fixture manifest), `client`, `claimed_client`, `login`, and `device_client` + `apps` (a fake of the apps' HTTP answers with `edit_config_yml`). `tests/fixtures/node_red_config_ok.yml` is the template's shape with `lat: 45.0`, `lon: -122.0`, `bearing: 'n'`, one camera and one radar enabled, no `survey_id` or `database_precision`. `script/tests/test_node_red_flows.py`: `run_functions(steps, env, context)`, `named(flows, name)`, `endpoint_nodes()`, and `test_tm_internal_status_endpoint_exists` as the pattern for asserting a chain; `script/tests/test_tmsetup_templates.py::test_tm_control_writes_only_its_state_and_frigates_config` asserts the unit's one `ReadWritePaths=` line.
- UI: `src/modules/index.ts` (`MODULES` in menu order, `NavItem.adminOnly`), `src/modules/device/DevicePage.vue` (load/error/progress pattern, `StatusCard`, `ConfirmDialog`, sections with `h2`), `src/components/{StatusCard,ConfirmDialog,EnteredSecret}.vue`, `clipboard.ts` (`copyText`), `relative-time.ts`, `api/client.ts` (`api`, `messageOf`), `tests/mount.ts` (`mountApp`, `field`, `button`, `click`, `clickInDialog`, `dialogText`), `tests/fake-api.ts` (`signedIn(user, answers)`, `ADMIN`, `VIEWER`, `apiError`). The README's fake-mode steps regenerate `openapi.json` and `schema.d.ts` after an API change.
- Role: `templates/tm-control/tm-control.service.j2` (`ProtectSystem=strict`, one `ReadWritePaths=` for Frigate's config directory); `tasks/entered_secrets.yml` runs `tm-control migrate --secrets-dir … --node-red-config <config.yml>` as root before any config template, with `changed_when` on lines not ending `: up to date`. `config.yml` is `0640 codeowner:codegroup`; the Node-RED container runs as the code owner's uid with the config directory mounted at `/config`. The tmdb runner (`container/node-red-tm/schema/tmdb_migrate.py`) writes `db/backup/tmdb-v<version>-<stamp>.sqlite` before migrating, so a unit upgraded from a release has `tmdb-v0-*` (released units are at schema version 0) or `tmdb-v1-*`.
- Docs: `docs/use/control-app.md`, `docs/use/detection.md` (a page's structure: description front matter, what the page is for, a phone screenshot, sections per action), `docs/use/device-health.md` (the checks), `docs/configuration/node-red-config.md` (`## deployment`, which says moving and correcting are done on the Location page "once it ships"), `docs/setup-guide.md` (step 4 still edits the file over SSH), `docs/development/tm-control.md`, `tm-control/ui/README.md`, `CLAUDE.md` ("tm-control install" bullets).

## Global Constraints

- Survey id: `^[0-9a-f]{8}-si$`, eight random hex characters from `secrets.token_hex(4)`; compared and stored in lower case. Deployment id: `^\d+-[0-9a-f]{8}-d$`. Bearings: `n s e w ne nw se sw` or empty. Precision: the strings `none`, `1`, `2` in `config.yml` and the API; the number `1`, `2`, or NULL in tmdb.
- Exact coordinates are kept to at most five decimal places (quantised half away from zero on input), `lat` in [-90, 90], `lon` in [-180, 180], both set or neither. They live in `state.sqlite` and `config.yml` only. Rounding to the stored precision is half away from zero, as SQLite's `ROUND` and the engine's `toFixed`.
- No coordinate, description, or reason is ever logged, audited, put in an error message, or returned by any endpoint a viewer can call. Audit rows carry the survey id (and a deployment id) only. `GET /surveys` and everything under it is admin-only.
- No exact coordinate in any test fixture, commit, PR text, or screenshot other than the Portland-scale example `45.52252, -122.69120` already in PR 260, and `45.0, -122.0` from the fixture.
- tm-control never opens `tmdb.sqlite`; the pre-migration backup is opened read-only (`?mode=ro&immutable=1`) and is the one tmdb file it reads. Node-RED never opens `state.sqlite`.
- `config.yml` is written only through `RoundTripFile` with `mapping_indent=4`: comments, key order, and quoting kept; a backup beside the file; atomic replace; `ConcurrentEditError` → 409.
- `flows.json` is edited programmatically and re-serialised with `json.dumps(flows, indent=4, ensure_ascii=False)` and no trailing newline; `python3 -m json.tool` must parse it; no `CREATE`/`ALTER`/`DROP` in any flow SQL; existing node ids keep their ids; new nodes get fresh 16-hex ids; the MQTT nodes' ids stay.
- Every commit ends with the trailer block from the repo's `CLAUDE.md` (Assisted-by / AI-Model / AI-Effort / AI-Role); never `Co-Authored-By`. Docs follow "Writing docs" in `docs/development/contributing.md`; `mkdocs build --strict` passes. Nothing public names a device.
- Off-device checks before each commit, from the repo root in the dev venv: `python -m pytest container/node-red-tm/schema/tests script/tests tm-control/backend/tests`; for UI tasks also `cd tm-control/ui && npm test && npm run build`; for docs tasks `~/.venvs/tm-docs/bin/mkdocs build --strict`.

## Review Focus

1. A `config.yml` with no `deployment:` block, or a sensor with no `deployment:` block: the writer creates the blocks in place rather than failing, and the result still loads. Test in Task 4 (`test_deploy_creates_missing_deployment_blocks`).
2. Node-RED down or restarting during Deploy here: the file is written, no rows appear, and the API answers 200 with `reloaded: false` and the page says Node-RED hasn't reloaded yet, rather than an error that invites a second deploy (which would write the same file again). Tests in Task 7 (`test_deploy_without_nodered_says_not_reloaded`) and Task 10 (the `reloaded: false` case in `deploy-review.spec.ts`).
3. The file changed between the page's load and its save (another admin, a hand edit): 409 `config_changed`, nothing written, no backup made. Test in Task 4 (`test_concurrent_edit_is_refused`).
4. A backup in the oldest deployment shape (no `lat`/`lon` columns), or one that isn't a database: the import skips it with one log line (no path contents), creates the in-use place from `config.yml`, and still marks the device reconciled. Test in Task 5 (`test_unreadable_backup_is_skipped`).
5. Coordinates typed with a decimal comma (`45,52252`), in the wrong order (`-122.69120, 45.52252` fails the latitude range), or with more than five decimals: refused or quantised as the rules say, never stored as something else. Tests in Task 3 (`test_parse_pair_refuses_a_decimal_comma`, `test_exact_quantises_to_five_places`) and Task 10 (the form's own check).

---

### Task 1: The unit may write Node-RED's config directory; the adapter reaches every `/tm-internal/` endpoint

**Files:**
- Modify: `script/ansible/roles/tmsetup/templates/tm-control/tm-control.service.j2` (the `ReadWritePaths=` lines and the comment above them)
- Modify: `script/tests/test_tmsetup_templates.py` (`test_tm_control_writes_only_its_state_and_frigates_config`)
- Modify: `tm-control/backend/tm_control/adapters/nodered.py`
- Test: `tm-control/backend/tests/test_nodered_adapter.py` (create)

**Interfaces:**
- Consumes: `httpjson.get`, `httpjson.post`, `yamlfile.RoundTripFile`.
- Produces, in `adapters/nodered.py`:
  - `BASE = "http://127.0.0.1:1880/tm-internal"`; `STATUS_URL` stays.
  - `class NodeRedError(RuntimeError)` with `.code` in `"unreachable" | "refused" | "bad_request" | "database_error" | "unexpected"` (unreachable: no answer; refused: 401; bad_request: 400; database_error: 500; unexpected: any other status or a body that isn't JSON) and `.status: int | None`.
  - `class NodeRed:` built with `token: str`. Methods, each raising `NodeRedError`: `report() -> dict` (the status body), `deployments(survey_id: str) -> list[dict]`, `usage() -> list[dict]`, `events(survey_id: str) -> dict`, `set_precision(precision: str) -> None`, `correct_location(survey_id: str, lat: float, lon: float) -> None`, `correct_bearing(deployment_id: str, bearing: str) -> None`, and `after_config_write() -> None` (does nothing; the fake overrides it).
  - `config_file_path(settings, manifest) -> Path`: `settings.state_dir.parent / "node-red-tm" / "config" / "config.yml"` in fake mode, else `config_path(manifest.codedir)`.
  - `open_config(path) -> RoundTripFile` with `mapping_indent=4`.

- [ ] **Step 1: Write the failing tests**

`script/tests/test_tmsetup_templates.py`: change the assertion to the two lines, in this order: `ReadWritePaths=/opt/traffic-monitor/frigate/config`, `ReadWritePaths=/opt/traffic-monitor/node-red-tm/config`; rename the test `test_tm_control_writes_only_its_state_and_the_two_config_directories` and its docstring (the Location page writes Node-RED's `config.yml`).

`tests/test_nodered_adapter.py` (monkeypatch `httpjson.get` and `httpjson.post` to record the URL and headers and answer a canned `(status, bytes)`):
- `test_deployments_sends_the_token_and_parses_the_rows`: `GET …/deployments?survey_id=3f9a1c2e-si` with the `X-TM-Internal-Token` header; `{"deployments": [...]}` → the list.
- `test_each_status_maps_to_an_error_code`: parametrised over `(None, "unreachable")`, `(401, "refused")`, `(400, "bad_request")`, `(500, "database_error")`, `(418, "unexpected")`.
- `test_correct_location_posts_json`: `POST …/surveys/3f9a1c2e-si/location` with body `{"lat": 45.52252, "lon": -122.6912}` as `application/json`; 204 → returns None.
- `test_correct_bearing_posts_json`: `POST …/deployments/1700000000000-0badf00d-d/bearing` body `{"bearing": "ne"}`.
- `test_config_file_path_in_fake_mode_is_beside_the_state_dir` and `test_config_file_path_on_a_device_is_under_codedir`.

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest script/tests/test_tmsetup_templates.py -k tm_control_writes tm-control/backend/tests/test_nodered_adapter.py -v`
Expected: FAIL (one `ReadWritePaths=` line; `NodeRed` not defined).

- [ ] **Step 3: Implement**

The unit: a second `ReadWritePaths={{ tmsetup_codedir }}/node-red-tm/config` line after the first, and the comment says Node-RED's `config.yml` is written by the Location page. `adapters/nodered.py`: the class and helpers above; `_call(method, path, query, body)` builds the URL with `urllib.parse.urlencode` for the query, sends the header, raises by status, and `json.loads` the body only when it's non-empty (204 has none).

- [ ] **Step 4: Run the tests to verify they pass**

Run: the Step 2 command.
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add script/ansible/roles/tmsetup/templates/tm-control/tm-control.service.j2 script/tests/test_tmsetup_templates.py tm-control/backend/tm_control/adapters/nodered.py tm-control/backend/tests/test_nodered_adapter.py
git commit -m "Let tm-control write Node-RED's config directory and call every internal endpoint"
```

### Task 2: Migration 3 and the places store

**Files:**
- Modify: `tm-control/backend/tm_control/core/state.py` (append `MIGRATIONS[2]`)
- Create: `tm-control/backend/tm_control/modules/location/__init__.py`, `places.py`
- Modify: `tm-control/backend/tests/test_state.py` (the version is 3 after a fresh migrate)
- Test: `tm-control/backend/tests/test_places.py` (create)

**Interfaces:**
- Consumes: `State`, and the `_reading`/`_writing` context managers imported from `core/auth.py` (one import line; moving them is a refactor for another PR).
- Produces, in `modules/location/places.py`:
  - `STATUSES = ("planned", "in_use", "used")`; `SOURCES = ("ui", "csv", "default", "imported_config", "imported_backup")`.
  - `class Bearing(BaseModel)`: `sensor_type: str`, `sensor_name: str`, `bearing: str`.
  - `class Survey(BaseModel)`: `id`, `description: str | None`, `lat: float | None`, `lon: float | None`, `status`, `source`, `created_at: str`, `updated_at: str`, `bearings: list[Bearing]`.
  - `class Places:` built with `state: State`. `list() -> list[Survey]` (in use first, then planned by `created_at` descending, then used by `updated_at` descending); `get(survey_id) -> Survey | None`; `in_use() -> Survey | None`; `create(survey_id, description, lat, lon, bearings, source, status, user_id, now=None) -> Survey` (lat and lon floats at five places or None; raises `ValueError` for a second `in_use`); `update_planned(survey_id, description, lat, lon, bearings) -> Survey` (raises `ValueError` unless the status is `planned`); `set_in_use(survey_id, now=None) -> None` (the previous in-use row becomes `used`); `set_point(survey_id, lat, lon, now=None)`; `set_bearing(survey_id, sensor_type, sensor_name, bearing)`; `record_correction(survey_id, deployment_id, field, old_value, new_value, reason, source, user_id, now=None)`; `delete(survey_id)` (raises `ValueError` for the in-use row); `reconciled_at() -> str | None` and `mark_reconciled(now=None)` (the `device` key `surveys_reconciled_at`).
  - Module docstring: the store is the exact history (design section 5); nothing here is logged.

- [ ] **Step 1: Write the failing tests**

`tests/test_state.py`: the fresh-migrate assertions become `3`; add `test_migration_3_creates_the_survey_tables` (`surveys`, `survey_bearings`, `survey_corrections` in `sqlite_master`, with `surveys.status` refusing `'elsewhere'` through its CHECK).

`tests/test_places.py` (a `State` on `tmp_path`, migrated):
- `test_create_and_list_order`: a used, a planned, and an in-use place; `list()` puts the in-use first.
- `test_only_one_place_is_in_use`: `set_in_use` on a planned place marks the previous one `used`; `create(..., status="in_use")` while one exists raises `ValueError`.
- `test_bearings_round_trip`: created with `[Bearing("cameras", "picam_h265", "n"), Bearing("radars", "TM_RADAR_SERIAL_PORT_00", "")]`, read back in that order; `set_bearing` replaces one.
- `test_update_planned_refuses_a_used_place`.
- `test_delete_refuses_the_place_in_use` and `test_delete_removes_its_bearings_and_corrections` (cascade).
- `test_correction_rows_keep_old_and_new_values`: `record_correction(..., "location", "45.0,-122.0", "45.00001,-122.0", None, "ui", 1)` reads back.
- `test_reconciled_flag_starts_unset`.

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tm-control/backend/tests/test_state.py tm-control/backend/tests/test_places.py -v`
Expected: FAIL (version 2; no `places` module).

- [ ] **Step 3: Implement**

Migration 3 is the design's section 5 SQL for the three tables, with `map_mode` on `surveys` and `map_block_ref`/`map_side` on `survey_bearings` kept (decision 11) and `sharing_consents` left out, plus `CREATE INDEX survey_corrections_survey ON survey_corrections (survey_id)`. `Places` is plain sqlite3 in one transaction per method; `list()` reads bearings in one query and groups them.

- [ ] **Step 4: Run the tests to verify they pass**

Run: the Step 2 command.
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tm-control/backend/tm_control/core/state.py tm-control/backend/tm_control/modules/location tm-control/backend/tests/test_state.py tm-control/backend/tests/test_places.py
git commit -m "Keep the unit's places in state.sqlite"
```

### Task 3: Ids, rounding, and parsing

**Files:**
- Create: `tm-control/backend/tm_control/modules/location/coordinates.py`
- Test: `tm-control/backend/tests/test_coordinates.py` (create)

**Interfaces:**
- Produces, in `coordinates.py`:
  - `SURVEY_ID = re.compile(r"^[0-9a-f]{8}-si$")`, `DEPLOYMENT_ID = re.compile(r"^\d+-[0-9a-f]{8}-d$")`, `BEARINGS = ("n", "s", "e", "w", "ne", "nw", "se", "sw")`, `PRECISIONS = ("none", "1", "2")`, `EXACT_PLACES = 5`.
  - `new_survey_id() -> str`.
  - `normalize_survey_id(value) -> str | None`: the lower-cased id when it matches, else None (as `init config defaults` does).
  - `normalize_precision(value) -> str | None`: `1`, `"1"`, `"NONE"`, `2.0` → `"1"`, `"1"`, `"none"`, `"2"`; anything else None.
  - `normalize_bearing(value) -> str | None`: trimmed, lower-cased, `""` for empty or None; None when it isn't one of `BEARINGS`.
  - `exact(value) -> float | None`: a number or numeric string quantised to five places half away from zero (`Decimal(str(value)).quantize(Decimal("0.00001"), ROUND_HALF_UP)`), as a float; `""`/None → None; raises `ValueError` for anything else, and for a latitude or longitude outside its range when called as `exact(value, "lat")` / `exact(value, "lon")`.
  - `stored(lat, lon, precision: str) -> tuple[float | None, float | None]`: what tmdb would hold: both None for `none` or when either is None; else each rounded half away from zero to 1 or 2 places.
  - `parse_pair(text) -> tuple[float, float]`: `"45.52252, -122.69120"`, `"45.52252 -122.69120"`, or `"45.52252,-122.69120"` → `(45.52252, -122.6912)`; raises `ValueError` for anything else (a decimal comma, a single number, a third number, text).

- [ ] **Step 1: Write the failing tests**

`tests/test_coordinates.py`:
- `test_new_survey_id_matches_the_pattern` (two ids differ).
- `test_normalize_survey_id_folds_case` (`"3F9A1C2E-SI"` → `"3f9a1c2e-si"`; `"3f9a1c2e-d"` → None).
- `test_normalize_precision` parametrised over the five cases above.
- `test_exact_quantises_to_five_places`: `exact("45.522525")` → `45.52253` (half away from zero), `exact(-122.691204)` → `-122.6912`, `exact("")` → None.
- `test_exact_range_checks`: `exact(91, "lat")`, `exact(-181, "lon")`, `exact("north", "lat")` raise `ValueError`.
- `test_stored_rounds_half_away_from_zero`: `stored(45.55, -122.65, "1")` → `(45.6, -122.7)`; `stored(45.52252, -122.6912, "2")` → `(45.52, -122.69)`; `stored(45.0, None, "2")` → `(None, None)`; `stored(45.0, -122.0, "none")` → `(None, None)`.
- `test_parse_pair_accepts_comma_or_space` and `test_parse_pair_refuses_a_decimal_comma` (`"45,52252 -122,69120"` raises).

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tm-control/backend/tests/test_coordinates.py -v`
Expected: FAIL (module missing).

- [ ] **Step 3: Implement `coordinates.py`**

`decimal` only; `parse_pair` splits on a comma or whitespace and requires exactly two tokens that each parse as a `Decimal` with a dot or no fraction.

- [ ] **Step 4: Run the tests to verify they pass**

Run: the Step 2 command.
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tm-control/backend/tm_control/modules/location/coordinates.py tm-control/backend/tests/test_coordinates.py
git commit -m "Survey ids, coordinate rounding, and pasted coordinates"
```

### Task 4: The edits to Node-RED's `config.yml`

**Files:**
- Create: `tm-control/backend/tm_control/modules/location/config.py`
- Test: `tm-control/backend/tests/test_location_config.py` (create)

**Interfaces:**
- Consumes: `nodered.open_config(path)`, `coordinates.normalize_*`, `coordinates.exact`.
- Produces, in `config.py`:
  - `SENSOR_TYPES = ("cameras", "radars", "airquality_monitors")`.
  - `class ConfigError(Exception)` with `.code` in `"missing" | "unreadable" | "invalid" | "changed" | "write_failed"` (from `FileNotFoundError`/`OSError`/`YAMLError` or a non-mapping/`ConcurrentEditError`/write errors).
  - `class Deployment(BaseModel)`: `survey_id: str | None`, `lat: float | None`, `lon: float | None`, `precision: str` (`"1"` when missing or invalid, as the engine defaults), `survey_id_invalid: bool`, `precision_invalid: bool`.
  - `class NodeRedConfig:` built with `path: Path`; loads at construction (raises `ConfigError`). `deployment() -> Deployment`; `sensors() -> list[Bearing]` (every enabled sensor under `sensors.<type>.<name>` for the three types, with its bearing: the sensor's `deployment.bearing`, else the top-level `bearing`, normalised, `""` when invalid); `sharing() -> Literal["data", "none"]` (`thingsboard.enabled is True`); `set_place(survey_id, lat, lon)` (top-level `survey_id` lower-cased, `lat`/`lon` as floats or `None`; creates `deployment:` when missing); `set_precision(precision: str)`; `set_sensor_bearing(sensor_type, sensor_name, bearing)` (creates the sensor's `deployment:` block when missing; refuses a sensor that isn't in the file with `KeyError`); `save() -> bool` (True when the file changed; raises `ConfigError("changed")` on `ConcurrentEditError`).
  - `read_deployment(read: ConfigRead) -> Deployment | None`: the same parse from an already-read `ConfigRead` (for the contract check, Task 8), None when `read.data` is None.

- [ ] **Step 1: Write the failing tests**

`tests/test_location_config.py` (copy `fixtures/node_red_config_ok.yml` to `tmp_path`):
- `test_deployment_reads_the_fixture`: `survey_id None`, `lat 45.0`, `precision "1"`, nothing invalid.
- `test_deployment_normalises_quoted_and_upper_case_values`: a file with `lat: '45.52252'`, `survey_id: 3F9A1C2E-SI`, `database_precision: 2` → `45.52252`, `"3f9a1c2e-si"`, `"2"`.
- `test_deployment_flags_invalid_values`: `survey_id: nope`, `database_precision: '3'` → both `_invalid` True, `precision "1"`.
- `test_sensors_lists_enabled_ones_with_the_copied_down_bearing`: the fixture → `[Bearing("cameras", "picam_h265", "n"), Bearing("radars", "TM_RADAR_SERIAL_PORT_00", "n")]`; the disabled air-quality sensor isn't listed; a camera with `deployment: {bearing: 'e'}` reports `e`.
- `test_set_place_writes_the_id_and_coordinates_and_keeps_comments`: after `set_place("3f9a1c2e-si", 45.52252, -122.6912)` and `save()`, the text still has the template's comments and `    survey_id: 3f9a1c2e-si`; `read_config` gives the values back; a `.bak` exists.
- `test_set_place_with_no_location_writes_empty_coordinates`: `set_place(id, None, None)` → `lat:` and `lon:` empty, which `read_config` reads as None.
- `test_deploy_creates_missing_deployment_blocks`: a file without a top-level `deployment:` and a camera without one: `set_place` and `set_sensor_bearing("cameras", "picam_h265", "sw")` both succeed and the result parses with the bearing under the camera.
- `test_set_sensor_bearing_refuses_an_unknown_sensor` (`KeyError`).
- `test_concurrent_edit_is_refused`: load, append a line to the file by hand, `set_place`, `save()` → `ConfigError` with code `changed`; the file still has the hand edit and no `.bak`.
- `test_unchanged_edits_write_nothing`: `set_precision("1")` on the fixture (missing → written) changes the file, but a second `save()` returns False.
- `test_sharing_reads_thingsboard_enabled`.

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tm-control/backend/tests/test_location_config.py -v`
Expected: FAIL (module missing).

- [ ] **Step 3: Implement `config.py`**

Round-trip edits on `self._file.data` (a `CommentedMap`); a new `deployment:` block is inserted after `thingsboard` when that exists, else at the end; `survey_id` and `database_precision` are added after `bearing` when absent. Values: floats as floats, strings as strings; ruamel quotes `"1"` itself.

- [ ] **Step 4: Run the tests to verify they pass**

Run: the Step 2 command.
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tm-control/backend/tm_control/modules/location/config.py tm-control/backend/tests/test_location_config.py
git commit -m "Edit the place, precision, and bearings in Node-RED's config.yml in place"
```

### Task 5: Reconcile: first run, the upgrade import, and following the file

**Files:**
- Create: `tm-control/backend/tm_control/modules/location/reconcile.py`
- Modify: `tm-control/backend/tm_control/modules/setup/router.py` (`claim` calls `reconcile.ensure` after the audit row, inside a `try` that logs the exception class and nothing else)
- Test: `tm-control/backend/tests/test_reconcile.py` (create). The claim's effect is tested through the API in Task 7.

**Interfaces:**
- Consumes: `Places`, `NodeRedConfig`, `NodeRed` (or the fake), `coordinates`.
- Produces, in `reconcile.py`:
  - `BACKUP_GLOB = "tmdb-v[01]-*.sqlite"`; `backup_dir(manifest) -> Path` (`<codedir>/node-red-tm/db/backup`).
  - `class Outcome(BaseModel)`: `state: Literal["done", "waiting_nodered", "config_unreadable"]`, `imported: int` (places created from the backup on this run), `created_default: bool`, `followed: Literal["none", "unknown_id", "coordinates"]`.
  - `ensure(app_state, user_id: int | None = None) -> Outcome`: under `app_state.reconcile_lock` (a `threading.Lock` set in `create_app`):
    1. `NodeRedConfig(path)`; on `ConfigError` → `config_unreadable` (nothing else runs).
    2. If `places.reconciled_at()` is None: the one-time part.
       - No place in the store, and the file has no `survey_id` and no coordinates → create the default survey (`new_survey_id()`, description `"First location"`, no coordinates, `in_use`, source `default`, bearings from `sensors()`), write its id (`set_place`) and, when missing, `database_precision` `"1"`; `save()`; mark reconciled; `created_default=True`.
       - Otherwise Node-RED is needed: `report()`; a `NodeRedError`, or `schema_version` under 2, → `waiting_nodered`.
       - Import: the newest file matching `BACKUP_GLOB`, when there is one and no place has source `imported_backup`: open with `sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True)`; `SELECT id, lat, lon FROM deployment WHERE lat IS NOT NULL AND lon IS NOT NULL`; any `sqlite3.Error` (a legacy shape without those columns, not a database) → one `log.warning("skipping the tmdb backup: %s", type(error).__name__)` and no import. Then `usage()` for the survey ids with rows, `deployments(id)` for each, and a map from deployment id to survey id; group the backup rows by survey id; each group's exact point is the most common `(lat, lon)` pair in it (they're equal by construction; a tie keeps the first). Create a `used` place per group with source `imported_backup`, description None, `created_at`/`updated_at` from that survey's `first_start`/`last_end` (ms → ISO 8601 UTC), bearings none.
       - The in-use place: if the file names a `survey_id` that exists → `set_in_use`; if it names one that doesn't → create it from the file (source `imported_config`, the file's coordinates, bearings from `sensors()`) as `in_use`. If the file names none: the place whose point equals the file's `(lat, lon)` at five places (an imported one, or any) → `set_in_use` and write its id; none, or the file has no coordinates → create from the file (source `imported_config`, `in_use`) and write its id. Writes go through `set_place` (keeping the file's coordinates) and `save()`; mark reconciled.
    3. Every run, after step 2 or when already reconciled: follow the file.
       - The file's `survey_id` names a place that isn't in use → `set_in_use` (`followed="unknown_id"` when it had to be created, as in step 2's unknown case, source `imported_config`).
       - The file's coordinates differ from the in-use place's (both at five places; None counts as a value) → `set_point`, `record_correction(..., "location", old, new, None, "config", None)`, and when both new values are numbers, `correct_location` on Node-RED (a `NodeRedError` is logged by class and ignored; the rows stay as they were). `followed="coordinates"`.
    4. `done`.
  - Nothing logs a coordinate, an id's description, or a path's contents.

- [ ] **Step 1: Write the failing tests**

`tests/test_reconcile.py` (an app state built by hand: `settings` fixture, `State` migrated, a `NodeRedConfig` path in `tmp_path`, and a `FakeNodeRed` from Task 7; where the fake is needed before Task 7 exists, a minimal stub class in the test with `report`, `usage`, `deployments`, `correct_location`):
- `test_first_run_creates_the_default_place_and_writes_its_id`: the fixture file with `lat`/`lon` emptied and no `survey_id`; after `ensure`: one `in_use` place "First location", source `default`, the file's `survey_id` equals it, `database_precision: '1'` added, `reconciled_at` set, no Node-RED call made.
- `test_waits_for_nodered_when_the_file_has_coordinates`: the fixture as is; the stub's `report` raises `NodeRedError("unreachable")` → `waiting_nodered`, no place created, not reconciled; a second call with Node-RED answering `schema_version: 2` proceeds.
- `test_import_from_the_backup_groups_places_by_survey_id`: a backup `tmdb-v0-20261101T000000Z.sqlite` in `<tmp>/node-red-tm/db/backup` with a `deployment` table of four rows (ids `A`..`D`; A and B at `45.52252, -122.6912`, C and D at `45.53, -122.7`); the stub's `usage()` answers two survey ids with `deployments(id)` listing `[A, B]` and `[C, D]`; the file has `lat: 45.52252`, `lon: -122.6912` and no `survey_id` → two places, both with source `imported_backup`: the first, found by its point, is `in_use`, the second `used`; the file now names the first; `imported == 2`.
- `test_no_matching_point_creates_the_place_from_the_file`: same backup, the file at `45.6, -122.8` → three places, the new one `in_use` with source `imported_config`.
- `test_unreadable_backup_is_skipped`: the backup file is `b"not a database"` → `imported == 0`, one warning naming only the exception class, the in-use place created from the file, reconciled.
- `test_import_runs_once`: a second `ensure` with the backup still there creates nothing.
- `test_following_an_unknown_survey_id_in_the_file`: reconciled device; the file's `survey_id` changed by hand to a fresh id → a new `in_use` place with that id, source `imported_config`, the previous one `used`.
- `test_following_changed_coordinates_records_a_config_correction`: the file's `lat` changed by hand → the in-use point updated, one correction row with source `config`, the stub's `correct_location` called once with the new pair.
- `test_claim_calls_ensure_and_survives_its_failure`: `claim` with `reconcile.ensure` monkeypatched to raise → 201 all the same, one log line naming the exception class.

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tm-control/backend/tests/test_reconcile.py -v`
Expected: FAIL (module missing).

- [ ] **Step 3: Implement `reconcile.py` and the claim hook**

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tm-control/backend/tests/test_reconcile.py tm-control/backend/tests/test_api_setup.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tm-control/backend/tm_control/modules/location/reconcile.py tm-control/backend/tm_control/modules/setup/router.py tm-control/backend/tests/test_reconcile.py
git commit -m "Create the first place at claim, import past places at upgrade, and follow config.yml"
```

### Task 6: Node-RED: the two correction endpoints, and usage counts the rows with no survey

**Files:**
- Modify: `container/node-red-tm/data/flows.json` (`init-config` tab). The endpoints are documented in `docs/development/tm-control.md`, which Task 12 updates.
- Test: `script/tests/test_node_red_flows.py`

**Interfaces:**
- Produces, in the flows:
  - `POST /tm-internal/surveys/:id/location`, body `{lat, lon}` (both finite numbers in range), validated by "tm-internal: validate location correction" (`msg.params = {$survey_id, $lat, $lon}`; 400 `{error: "bad_request", detail: "survey_id" | "lat" | "lon"}`), run by a prepared sqlite node "re-round survey coordinates": `UPDATE deployment SET lat = ROUND($lat, location_precision), lon = ROUND($lon, location_precision) WHERE survey_id = $survey_id AND location_precision IS NOT NULL;`, answered 204 by "tm-internal: answer location correction".
  - `POST /tm-internal/deployments/:id/bearing`, body `{bearing}` (one of the eight or `""`), validated by "tm-internal: validate bearing correction" (id `/^\d+-[0-9a-f]{8}-d$/`; `msg.params = {$id, $bearing}`; 400 with `detail` `"deployment_id"` or `"bearing"`), sqlite "rewrite deployment bearing": `UPDATE deployment SET bearing = $bearing WHERE id = $id;`, 204.
  - "read survey usage" (`dce8e3e7d11d02ac`) loses its `WHERE` clause, so the rows with no survey id come back as one group with `survey_id: null`; "tm-internal: answer survey usage"'s comment says so.
  - Both chains wire their sqlite node's error path to the existing "tm-internal: database error" as the precision chain does (copy that chain's wiring; new ids for every new node).

- [ ] **Step 1: Write the failing tests**

`script/tests/test_node_red_flows.py`:
- `test_tm_internal_correction_endpoints_exist`: `endpoint_nodes()` has `post /tm-internal/surveys/:id/location` and `post /tm-internal/deployments/:id/bearing`, each chained through a "tm-internal: check token" node.
- `test_location_correction_validates_the_id_and_the_pair`: `run_functions` on "tm-internal: validate location correction": `({id: "3f9a1c2e-si"}, {lat: 45.52252, lon: -122.6912})` → first output with `$lat`/`$lon`; `{lat: "45", lon: -122}`, `{lat: 91, lon: 0}`, and an upper-case id → second output, 400 with the right `detail`.
- `test_bearing_correction_validates_the_id_and_the_bearing`: `""` and `"NE"` → ok (`$bearing` lower-cased); `"north"` → 400.
- `test_survey_usage_counts_rows_without_a_survey`: the sqlite node's `sql` has no `WHERE survey_id IS NOT NULL` and still groups by `survey_id`.
- `test_flows_json_round_trips_through_json_dumps`: the file's text equals `json.dumps(json.loads(text), indent=4, ensure_ascii=False)` (no such test exists yet; it pins the serialisation every later edit relies on).

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest script/tests/test_node_red_flows.py -k "correction or usage" -v`
Expected: FAIL.

- [ ] **Step 3: Implement with a one-off script**

A script in the scratchpad loads `flows.json`, copies the precision chain's nodes (http in, check token, validate, sqlite, answer, two http responses) twice with fresh ids, sets names, urls, `func`, and `sql` as above, places them under the precision chain on the `init-config` tab, edits `dce8e3e7d11d02ac`'s `sql`, and writes the file back with `json.dumps(flows, indent=4, ensure_ascii=False)` and no trailing newline. `python3 -m json.tool` parses the result; `git diff --stat` shows only `flows.json`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest script/tests -v`
Expected: PASS, the MQTT ids and credentials tests included.

- [ ] **Step 5: Commit**

```bash
git add container/node-red-tm/data/flows.json script/tests/test_node_red_flows.py
git commit -m "Let tm-control correct a place's rows and a deployment's bearing, and count rows with no survey"
```

### Task 7: The API: `/api/v1/surveys`, and the fake Node-RED

**Files:**
- Create: `tm-control/backend/tm_control/modules/location/router.py`
- Modify: `tm-control/backend/tm_control/modules/location/__init__.py` (`module = Module("location", router)`), `modules/__init__.py` (`location.module` after `detection.module`), `app.py` (`app.state.nodered`, `app.state.config_path`, `app.state.reconcile_lock`), `fake.py` (`FakeNodeRed`, `seed_config`, `reset` calls it), `core/settings.py` only if a fake path helper is cleaner there
- Test: `tm-control/backend/tests/test_api_surveys.py` (create), `tests/test_api_setup.py` (the claim test from Task 5), `tests/test_openapi_document.py` (the new paths are declared with response models)

**Interfaces:**
- Consumes: Tasks 1 to 5.
- Produces, in `router.py` (`APIRouter(prefix="/surveys", tags=["location"])`, every route `Depends(require_admin)`; a survey id in a path that doesn't match `SURVEY_ID` is 404 `not_found`; a `NodeRedError` is 502 `nodered_error` ("Node-RED didn't answer" for `unreachable`, "the internal token doesn't match; re-run tmsetup.sh -t node-red-tm" for `refused`, else "Node-RED answered an error") except where a route says otherwise; a `ConfigError` is 409 `config_changed` for `changed`, else 500 `config_error` with the code in the message and nothing from the file):
  - Models: `Bearing` (from `places`), `SurveyOut` (`Survey`'s fields plus `stored_lat`, `stored_lon` (at the device's precision), `first_used: int | None`, `last_used: int | None` (ms, from usage), `open_count: int`, `deployment_count: int`, `imported: bool` (source `imported_backup`)), `Unassigned(deployment_count, first_start, last_end)`, `PlacesState(precision, in_use: str | None, sensors: list[Bearing], sharing, surveys: list[SurveyOut], unassigned: Unassigned | None, reconcile: Literal["done", "waiting_nodered", "config_unreadable"], nodered: bool)`, `SurveyIn(description: str | None = Field(max_length=200), lat: float | None, lon: float | None, bearings: list[Bearing])`, `DeployIn(bearings: list[Bearing])`, `DeployOut(deployed_at: int, reloaded: bool, deployments: list[DeploymentOut])`, `DeploymentOut(id, started, ended, lat, lon, bearing, sensor_type, sensor_name, location_precision)`, `EventsOut(event_count, first_event, last_event)`, `PrecisionIn(precision: Literal["none", "1", "2"], round_stored: bool = False)`, `LocationCorrection(lat: float, lon: float, reason: str | None = Field(max_length=200))`, `BearingCorrection(bearing: str, reason: str | None = Field(max_length=200))`, `ImportIn(csv: str = Field(max_length=65536), dry_run: bool = True)`, `ImportRow(line: int, description, lat, lon, bearings)`, `ImportProblem(line: int, message: str)`, `ImportOut(rows: list[ImportRow], errors: list[ImportProblem], created: list[str])`.
  - `GET /surveys` → `PlacesState`: `reconcile.ensure` first; `nodered` False and usage counts zero when Node-RED doesn't answer (the page still lists the places).
  - `POST /surveys` (201 `SurveyOut`): a planned place; `exact` on the pair (422 `validation` with the field name), bearings normalised; audit `survey.create` with the id.
  - `PATCH /surveys/{id}` (`SurveyOut`): planned only; 409 `not_planned` otherwise.
  - `DELETE /surveys/{id}` (204): 409 `in_use` for the place in use.
  - `POST /surveys/{id}/deploy` (`DeployOut`): the bearings from the body (every enabled sensor must be named; a missing one takes the place's stored bearing, else the file's current one); `set_in_use`; `set_bearing` for each; `set_place` + `set_sensor_bearing` + `save()`; `nodered.after_config_write()`; audit `survey.deploy`; then poll `deployments(id)` every 1 s for up to 20 s until every sensor whose survey or bearing changed has a row with `entryStartDateTime >= deployed_at` (ms before the write), or stop at once when Node-RED raises `unreachable`; `reloaded` says whether they all appeared. The same place deployed again with the same bearings writes nothing and answers `reloaded: true` with the current rows.
  - `GET /surveys/{id}/deployments` → `{deployments: [DeploymentOut]}`; `GET /surveys/{id}/events` → `EventsOut`.
  - `PUT /surveys/precision` (declared before the `{id}` routes; 200 `PlacesState`): `set_precision`, `save()`, `after_config_write()`; with `round_stored`, `set_precision` on Node-RED after the write (a `NodeRedError` here is 502 after the file was written; the message says the file changed and the rows didn't); audit `survey.precision` with the value.
  - `POST /surveys/{id}/location` (`SurveyOut`): a used or in-use place (409 `not_used` for a planned one; edit it instead); `set_point`, `record_correction` (source `ui`, the admin's id), `correct_location` on Node-RED (502 leaves the store changed and says the rows weren't re-rounded; the next `GET` doesn't retry: the admin can correct again), and for the in-use place `set_place` with the new pair and `save()` (which the follow step then sees as equal); audit `survey.correct_location`.
  - `POST /surveys/{id}/deployments/{deployment_id}/bearing` (`DeploymentOut`): `DEPLOYMENT_ID` else 404; the row must be in `deployments(id)` (404); `correct_bearing` on Node-RED first; when the row is open, then `set_bearing` and `set_sensor_bearing` + `save()`; `record_correction(..., "bearing", old, new, reason, "ui", admin.id)`; audit `survey.correct_bearing` with both ids.
  - `POST /surveys/import` (`ImportOut`): `csv.DictReader` on the text; header `description,lat,lon` required (the rest `<sensor_type>.<sensor_name>` or `<sensor_name>` columns, matched against `sensors()`, each a bearing); a row is refused by line number for a bad pair, a half-blank pair, an unknown bearing, or an unknown sensor; `dry_run` answers rows and errors and creates nothing; otherwise, with no errors, creates planned places with source `csv` and answers their ids; with errors, creates nothing (422 `validation` with the errors in `detail`).
- Produces, in `fake.py`: `class FakeNodeRed(NodeRed)`: in-memory `deployment` rows and a `config_path`; `report()` answers `schema_version: 2`, the file's survey id and precision; `after_config_write()` re-reads the file and runs the engine's rules (adopt, unchanged, new on survey or bearing change, re-round open rows on a coarser precision) on its rows for every enabled sensor; `usage`, `deployments`, `events` (events: `event_count` 0), `set_precision`, `correct_location`, `correct_bearing` as the real one; `seed_config(settings)` copies `tests/fixtures/node_red_config_ok.yml` to `config_file_path(settings, …)` when it's missing; `reset()` deletes it and seeds it again. `create_app`: `app.state.nodered = fake.FakeNodeRed(path) if settings.fake else NodeRed(secrets.node_red_internal_token)`.

- [ ] **Step 1: Write the failing tests**

`tests/test_api_surveys.py` (the `claimed_client` fixture, whose app is in fake mode, so the fake Node-RED and the seeded file are there; a `places` helper that returns `GET /surveys`'s JSON):
- `test_surveys_needs_an_admin`: a viewer gets 403; unauthenticated 401.
- `test_claim_created_the_first_place_from_the_fixture`: the fixture has coordinates, so the first `GET` creates the in-use place with source `imported_config` at `45.0, -122.0` (fake mode: no backup, Node-RED answers), `precision "1"`, `sensors` lists the camera and the radar with `n`, `reconcile "done"`.
- `test_create_a_planned_place_and_list_order`.
- `test_create_refuses_a_bad_pair`: `lat: 91` → 422 naming `lat`; `lat` without `lon` → 422.
- `test_deploy_writes_the_file_and_starts_deployments`: create a place at `45.52252, -122.6912` with the camera bearing `e`; deploy → `reloaded True`, two rows started at or after `deployed_at` with `survey_id` the new id and `bearing` `e`/`n`, `lat 45.5`, the file's `deployment.survey_id` is the new id and the camera's `deployment.bearing` is `e`; the old place is `used`.
- `test_deploy_the_same_place_again_changes_nothing`: a second deploy → the same deployment ids, `reloaded True`, no new `.bak`.
- `test_deploy_without_nodered_says_not_reloaded`: monkeypatch the fake's `deployments` to raise `NodeRedError("unreachable")` → 200, `reloaded False`, the file written.
- `test_precision_rewrite_rounds_the_open_rows_and_optionally_all`: lower to `none` with `round_stored` → every row's `lat` null; the file says `'none'`.
- `test_correct_location_rounds_the_rows_and_records_it`: on the in-use place, `45.52252, -122.6912` → the rows at `45.5, -122.7`, the file's `lat` updated, one correction (checked through `Places`), 409 `not_used` on a planned place.
- `test_correct_bearing_on_an_open_row_updates_the_file`: `sw` → the row, the place's bearing, and the file's camera bearing all `sw`; a closed row's correction leaves the file alone.
- `test_delete_refuses_the_place_in_use_and_removes_a_used_one`.
- `test_import_previews_then_creates`: `description,lat,lon,picam_h265\nMain St,45.52252,-122.69120,n\nNo location,,,\n` → two rows, no errors; `dry_run False` → two planned places with sources `csv`; a line with `45,52252` or `bearing north` → that line's error, nothing created.
- `test_no_coordinate_in_any_log_line` (a `caplog` sweep over the whole module's tests: no line contains `45.5`).
- `tests/test_openapi_document.py`: the new paths are in the document with `200`/`201`/`204` responses declared.

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tm-control/backend/tests/test_api_surveys.py -v`
Expected: FAIL (404s: no router).

- [ ] **Step 3: Implement the router, the fake, and the wiring**

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tm-control/backend/tests -v`
Expected: PASS.

- [ ] **Step 5: Regenerate the API description and commit**

Run: `PYTHONPATH=tm-control/backend python -m tm_control dump-openapi > tm-control/ui/src/api/openapi.json && (cd tm-control/ui && npm run api:generate)`

```bash
git add tm-control/backend tm-control/ui/src/api
git commit -m "Add the surveys API: places, deploy, corrections, precision, and import"
```

### Task 8: Migrate, the Location check, and the status link

**Files:**
- Modify: `tm-control/backend/tm_control/core/migrate.py` (`_run_node_red`: two more steps; the `--node-red-config` flag's help in `cli.py` now says "move secrets out and update the deployment keys")
- Modify: `tm-control/backend/tm_control/modules/apps/contracts.py` (`location`, which reads `Places(context.state)` directly), `core/checks.py` (`Context(settings, manifest, secrets, state=None)`), `app.py` (passes `app.state.state`)
- Test: `tm-control/backend/tests/test_entered_secrets_migration.py` (or a new `test_location_migration.py`), `tests/test_contract_checks.py`, `script/tests/test_tmsetup_tasks.py` only if `entered_secrets.yml`'s `changed_when` lines need a new "up to date" phrase

**Interfaces:**
- Produces, in `migrate.py`: within the existing `--node-red-config` run, after the secret moves: (a) `deployment.database_precision` added as `'1'` after `bearing` when the key is missing (step text "add deployment.database_precision"); (b) each `sensors.<type>.<name>.deployment.lat`/`.lon` deleted (step text "remove lat/lon under sensors.<type>.<name>.deployment; the location is per unit"), pruning an emptied `deployment:` block. Both print through the existing steps list, so a file needing nothing still ends `: up to date`.
- Produces, in `contracts.py::location`: reads `read_deployment` (Task 4) and the per-sensor keys: errors for `survey_id_invalid` ("deployment.survey_id isn't a survey id (8 hex characters and -si)"), `precision_invalid` ("deployment.database_precision isn't none, 1, or 2"), a coordinate that isn't numeric or in range (numeric strings accepted now), or a bearing that isn't one of the eight; warnings for a `lat`/`lon` under a sensor's `deployment:` ("ignored; the location is per unit; tmsetup removes it") and, when `context.state` is given, for a file `survey_id` that no place has or an import not yet run (`Places(state).reconciled_at() is None`), each with `Fix(kind="link", href="/location", text="Open the Location page")`; ok says "Place <id> is in use at precision <p>." or "No location is set." The id and title stay `config.deployment` / "Location".

- [ ] **Step 1: Write the failing tests**

Migration: `test_migrate_adds_database_precision_once` (the fixture → `'1'` quoted, placed after `bearing`, second run "up to date"), `test_migrate_removes_per_sensor_coordinates_and_names_the_sensor` (a camera with `deployment: {lat: 45.0, lon: -122.0, bearing: 'e'}` → bearing kept, the two keys gone, stdout names `sensors.cameras.picam_h265`, no value printed).

Contract checks (the `apps` fixture's `edit_config_yml`): `test_location_accepts_quoted_coordinates`, `test_location_rejects_a_bad_survey_id_and_precision`, `test_location_warns_about_per_sensor_coordinates`, `test_location_links_to_the_page_when_the_file_names_an_unknown_place` (with a `State` passed in `Context`), `test_location_without_a_state_skips_the_places_check`.

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tm-control/backend/tests -k "migrat or location" -v`
Expected: FAIL.

- [ ] **Step 3: Implement**

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tm-control/backend/tests script/tests -v`
Expected: PASS (`status_fake.json` needs no change: the check id is unchanged).

- [ ] **Step 5: Commit**

```bash
git add tm-control/backend
git commit -m "Migrate the precision key, drop per-sensor coordinates, and check the survey keys on the Status page"
```

### Task 9: The Location page: the list, the precision, and deleting

**Files:**
- Create: `tm-control/ui/src/modules/location/index.ts`, `LocationPage.vue`, `coordinates.ts`
- Modify: `tm-control/ui/src/modules/index.ts` (`location` after `detection`)
- Test: `tm-control/ui/tests/location-page.spec.ts`, `tests/coordinates.spec.ts` (create)

**Interfaces:**
- Produces: route `/location` (`meta: { adminOnly: true }`), nav `{ title: 'Location', to: '/location', icon: mdiMapMarkerOutline, adminOnly: true }`.
- Produces, in `coordinates.ts`: `parsePair(text: string): { lat: number; lon: number } | null` (the backend's rules, for the form's immediate check; the API's answer wins), `formatStored(lat: number | null, lon: number | null): string` ("45.5, -122.7" or "No location stored"), `formatExact(lat, lon)` ("45.52252, -122.69120", five places, or "No location"), `BEARINGS` with labels ("N", "NE", …, and "Not set"), `PRECISIONS` with the labels "No location stored", "About 10 km (default)", "About 1 km".
- Produces, in `LocationPage.vue`: `GET /api/v1/surveys` on mount (load/error/progress as the Device page); `h1` "Location"; a `StatusCard` for the place in use (title: description or "No description"; subtitle: the id and "In use"; items: "Stored in the database" (`formatStored`), "Exact location" (`formatExact`), "Sharing" ("Sharing: data" / "Not sharing"), one row per sensor "Bearing, <sensor name>"); a notice when `reconcile !== 'done'` ("Node-RED hasn't answered yet, so past places may be missing. The page checks again when you reload it."); a section "Precision" with a radio group and a "Also round the rows already stored" checkbox that only shows when the new value is coarser, Save, and a `ConfirmDialog` when the checkbox is on ("This can't be undone."); a section "Places" with "Add a place" and "Import places" buttons (rendered here; Tasks 10 and 11 wire them to their dialogs) and a `v-expansion-panels` list, one panel per survey: title line (description or "No description", the id in `text-body-2 text-secondary`, status chip "In use"/"Planned"/"Used", `formatStored`), expanded text: first and last used (`relative-time`), deployment count, "Imported from your previous settings" for `imported`, on expand a `GET /surveys/{id}/events` ("N events from … to …"), the deployments table (sensor, bearing, started, ended), and the action buttons: "Deploy here" (planned and used), "Edit" (planned), "Correct location" (used, in use), "Delete" (planned, used) with a `ConfirmDialog` whose text for a used place says the exact coordinates go with it while the database keeps the rounded ones; the "Before any place was recorded" panel when `unassigned` is set; the empty-state line from the design when there's only the default place with no coordinates.

- [ ] **Step 1: Write the failing tests**

`tests/coordinates.spec.ts`: `parsePair` accepts the three forms and refuses a decimal comma; `formatStored(null, null)` is "No location stored"; `formatExact(45.52252, -122.6912)` is "45.52252, -122.69120".

`tests/location-page.spec.ts` (`signedIn(ADMIN, { 'GET /api/v1/surveys': PLACES })` with a `PLACES` fixture of an in-use place at `45.5, -122.7` stored, one planned, one used and imported):
- `it('is in the menu for admins only and sends a viewer home')` (the router's `adminOnly`).
- `it('shows the place in use with its stored and exact coordinates and the bearings')`.
- `it('lists the places in use, planned, then used, and marks the imported one')`.
- `it('loads the events when a place is expanded')` (the `GET …/events` answer appears).
- `it('asks before deleting and sends DELETE')` (`clickInDialog('Delete')`, the request in `sent`).
- `it('offers to round the stored rows only when the precision goes down and confirms it')` (`PUT /api/v1/surveys/precision` body `{precision: 'none', round_stored: true}`).
- `it('says when Node-RED has not answered')` (`reconcile: 'waiting_nodered'`).

- [ ] **Step 2: Run them to verify they fail**

Run: `cd tm-control/ui && npx vitest run tests/location-page.spec.ts tests/coordinates.spec.ts`
Expected: FAIL (no module).

- [ ] **Step 3: Implement**

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd tm-control/ui && npm test && npm run build`
Expected: PASS, build clean (`vue-tsc` included).

- [ ] **Step 5: Commit**

```bash
git add tm-control/ui/src/modules tm-control/ui/tests
git commit -m "Add the Location page: the places, the precision, and deleting a place"
```

### Task 10: Adding and editing a place, and Deploy here

**Files:**
- Create: `tm-control/ui/src/modules/location/PlaceForm.vue`, `DeployReview.vue`
- Modify: `LocationPage.vue` (wires the dialogs)
- Test: `tm-control/ui/tests/place-form.spec.ts`, `tests/deploy-review.spec.ts` (create), `tests/location-page.spec.ts`

**Interfaces:**
- Produces, `PlaceForm.vue`: props `sensors: Bearing[]`, `survey?: SurveyOut` (edit), `open` (v-model); fields: Description ("Private: it never leaves the device"), Coordinates (one text field; `parsePair` on input; the hint "Paste latitude, longitude from a maps app, such as 45.52252, -122.69120"; an error line "Enter latitude, longitude with a dot as the decimal mark" when text is there and doesn't parse), a "Use this phone's location" button shown only when `window.isSecureContext` (`navigator.geolocation.getCurrentPosition`, `enableHighAccuracy`, the reading to five places into the field; a refusal shows the browser's message), and on plain HTTP the sentence "Browsers only share your location with secure pages. Paste coordinates instead."; one bearing select per sensor; the line "A map pin is coming in a later update."; Save → `POST /surveys` or `PATCH /surveys/{id}`; emits `saved`.
- Produces, `DeployReview.vue`: props `place: SurveyOut`, `state: PlacesState`; the review list from the design's section 7: the description and id; per sensor "New deployment starts" or "Unchanged" (new when `state.in_use !== place.id` or the chosen bearing differs from the sensor's current one) with "was <old>, now <select>" (the select edits the bearing to deploy with; it starts at the place's stored bearing for that sensor, else the current one); "Stored in the database: <formatStored at state.precision>" or "Nothing stored"; the sharing line; "Counts from now on attach to the new deployment."; Deploy → `POST /surveys/{id}/deploy` with every sensor's bearing; while waiting, "Waiting for Node-RED to reload the settings"; the result: the new deployment ids with a Copy button each (`copyText`), or when `reloaded` is false "The settings are saved. Node-RED hasn't reloaded them yet; the deployments appear once it does. Don't deploy again." Emits `deployed`, and the page reloads `GET /surveys`.

- [ ] **Step 1: Write the failing tests**

`tests/place-form.spec.ts` (`mountAlone`): a pasted pair fills in; a decimal comma shows the error and disables Save; the phone button is absent when `window.isSecureContext` is false and present when true (stub `navigator.geolocation`); Save posts `{description, lat, lon, bearings}`.

`tests/deploy-review.spec.ts`: a used place with a different bearing lists "New deployment starts" for that sensor and "Unchanged" for the other; Deploy posts the bearings; a `reloaded: false` answer shows the "Don't deploy again" text; a `reloaded: true` answer lists two ids with Copy.

`tests/location-page.spec.ts`: "Add a place" opens the form and the list reloads after `saved`; "Deploy here" on a used place opens the review.

- [ ] **Step 2: Run them to verify they fail**

Run: `cd tm-control/ui && npx vitest run tests/place-form.spec.ts tests/deploy-review.spec.ts tests/location-page.spec.ts`
Expected: FAIL.

- [ ] **Step 3: Implement**

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd tm-control/ui && npm test && npm run build`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tm-control/ui/src/modules/location tm-control/ui/tests
git commit -m "Add and edit places, and deploy the unit to one after a review step"
```

### Task 11: Corrections and the CSV import

**Files:**
- Create: `tm-control/ui/src/modules/location/CorrectDialog.vue`, `ImportPlaces.vue`
- Modify: `LocationPage.vue`
- Test: `tm-control/ui/tests/correct-dialog.spec.ts`, `tests/import-places.spec.ts` (create), `tests/location-page.spec.ts`

**Interfaces:**
- Produces, `CorrectDialog.vue`: props `kind: 'location' | 'bearing'`, `place: SurveyOut`, `deployment?: DeploymentOut`, `open` (v-model). Location: the design's wording ("Use this only if the location was entered wrong. Every record from this place will say it was at the new point. To move the unit, use Deploy here instead."), a Coordinates field as in the form, a Reason field (optional, 200), Correct; when the new point is more than about 1 km from the old (a haversine in `coordinates.ts`, `distanceKm`), a second confirmation ("That's far enough to look like a move. Correct it anyway?"); the line "Copies and uploads that already left the device keep the old values."; posts `POST /surveys/{id}/location`. Bearing: a select, a Reason, posts `POST /surveys/{id}/deployments/{deployment_id}/bearing`. Emits `corrected`.
- Produces, `ImportPlaces.vue`: a file input (`.csv`, read with `FileReader` as text, 64 KiB cap with a message) or a textarea; the format line (`description,lat,lon` and one column per sensor named as in the settings, bearings as `n`, `ne`, …; blank `lat,lon` for a place with no location); Preview → `POST /surveys/import` with `dry_run: true`; a table of the rows, and the errors by line; Import (enabled when there are rows and no errors) → `dry_run: false`; the result "Added N places"; emits `imported`.

- [ ] **Step 1: Write the failing tests**

`tests/correct-dialog.spec.ts`: a location correction within 1 km posts without a second dialog; one 2 km away asks again and posts after "Correct it anyway"; a bearing correction posts `{bearing, reason}`.

`tests/import-places.spec.ts`: pasted CSV previews rows and errors from the fake answer; Import is disabled with an error present; with none it posts `dry_run: false` and shows "Added 2 places".

`tests/location-page.spec.ts`: "Correct location" and "Correct bearing" open the dialog with the right kind; "Import places" opens the import and the list reloads after `imported`.

- [ ] **Step 2: Run them to verify they fail**

Run: `cd tm-control/ui && npx vitest run tests/correct-dialog.spec.ts tests/import-places.spec.ts tests/location-page.spec.ts`
Expected: FAIL.

- [ ] **Step 3: Implement**

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd tm-control/ui && npm test && npm run build`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tm-control/ui/src/modules/location tm-control/ui/tests
git commit -m "Correct a place's location or a deployment's bearing, and import places from a file"
```

### Task 12: Docs, CLAUDE.md, and the READMEs

**Files:**
- Create: `docs/use/location.md` ("Places and location"), `docs/assets/images/location-page.png` and `location-deploy-review.png` (phone screenshots from fake mode, synthetic descriptions and the Portland-scale example only)
- Modify: `mkdocs.yml` (nav: after "Choose the detection model" in the same section; the `llmstxt` section if `docs/use` isn't already listed whole), `docs/use/control-app.md` (the pages list), `docs/use/device-health.md` (the Location check's new messages and link), `docs/configuration/node-red-config.md` (`## deployment`: the page does moving and correcting; a hand edit of `survey_id` starts a deployment, of `lat`/`lon` is recorded as a correction; per-sensor `lat`/`lon` removed by the installer), `docs/setup-guide.md` (step 4 → the Location page; SSH no longer needed for it; the `openssl rand` paragraph goes), `docs/use/system-admin.md` (the "Edit Node-RED's config.yml" row mentions the page), `docs/build-your-own-device-diy/update.md` (what the upgrade does to places, from the design's section 11, in operator words), `docs/development/tm-control.md` (the `location` module, the fake Node-RED, the seeded `config.yml`, the migration), `tm-control/ui/README.md` (the module and `coordinates.ts`), `CLAUDE.md` (the unit's two `ReadWritePaths=`; `state.sqlite` holds the places; tm-control writes `config.yml` for the Location page; the two new internal endpoints; the "tm-control migrate" note)
- Test: `~/.venvs/tm-docs/bin/mkdocs build --strict`

- [ ] **Step 1: Write the page and the edits**

`docs/use/location.md`: what a place is (the design's section 1 in operator words: a place can have no coordinates; the database keeps a rounded point, the exact point stays on the device), the page's sections (the place in use, precision with the three choices and what each stores, the places list and what the marks mean, adding a place by pasting coordinates or from the phone on HTTPS, Deploy here and the review step, correcting a wrong location or bearing and why it isn't a move, importing from a CSV with the format, deleting), what happens at upgrade ("Imported from your previous settings"), and the privacy lines (description never leaves the device; what the stored precision reveals; copies already shared keep old values). No exact coordinates but the example.

- [ ] **Step 2: Build strictly**

Run: `~/.venvs/tm-docs/bin/mkdocs build --strict`
Expected: no warnings.

- [ ] **Step 3: Commit**

```bash
git add docs mkdocs.yml CLAUDE.md tm-control/ui/README.md
git commit -m "Document the Location page and the places behind it"
```

### Task 13: Device tests

**Files:**
- Modify: `script/devpi/tests/test_web.py`, `test_dataflow.py`, `test_services.py`

**Interfaces:**
- Consumes: `admin_session`, `viewer_session`, `expect`, `codedir`, `node_red_config` (pii_free hosts), `db_query`, `host`.

- [ ] **Step 1: Write the tests**

`test_web.py`: `test_surveys_needs_an_admin` (viewer 403, admin 200 with `reconcile == "done"` and one `in_use`); the `/tm-internal` token test's path list gains `POST /tm-internal/surveys/3f9a1c2e-si/location` and `POST /tm-internal/deployments/1-00000000-d/bearing` (401 without the token, through the loopback port on the Pi); `test_in_use_place_matches_config_yml` (pii_free: `GET /surveys`'s `in_use` equals `config.yml`'s `survey_id`, and `precision` its `database_precision`). `test_dataflow.py`: `test_every_survey_in_tmdb_is_a_known_place` (pii_free: each distinct `survey_id` in `deployment` is in `GET /surveys`). `test_services.py`: `systemctl show -p ReadWritePaths tm-control.service` names both config directories.

- [ ] **Step 2: Check them off-device**

Run: `python -m pytest script/devpi/tests --collect-only -q 2>&1 | tail -3`
Expected: collected, no errors.

- [ ] **Step 3: Commit**

```bash
git add script/devpi/tests
git commit -m "Check the Location page's API and the places on a device"
```

### Task 14: The Pi plan

Through `tmdev.py check start|item|status|end`, one host at a time, from a worktree (`script/devpi/README.md`). Deploy with `tmdev.py deploy <host> -- -t tm-control -t node-red-tm` (the unit, migrate, the flows). Every description a placeholder; no file contents printed; coordinates in the log only as the Portland-scale example or `45.0, -122.0`.

- [ ] **Bench A** (the pii_free unit with a camera and radar, upgraded from PR 284; it has coordinates in `config.yml` and a `tmdb-v0-*` or `tmdb-v1-*` backup from plan 1's bench):
  1. **The watch fires on tm-control's write.** After the deploy: `GET /surveys` imports the past places (`imported` marked), the in-use place matches the file; then "Deploy here" on a planned place: within 30 s `journalctl -u node-red-tm` shows the config load and `GET /surveys/{id}/deployments` has new rows started after the request (`reloaded: true`). If it doesn't fire, stop the bench and record it: the fallback is a `POST /tm-internal/config/reload` endpoint, which this plan doesn't build.
  2. First run: `sudo tm-control reset-admin`, claim again → `config.yml` names a survey, "First location" in use (the file had coordinates, so source `imported_config`; blank the coordinates by hand first for the `default` path and check both).
  3. A bearing change on Deploy here starts a new deployment for that sensor only ("Unchanged" for the other).
  4. Correct bearing on the open row: the row, `config.yml`, and the page agree; no new deployment (the ids are unchanged); a closed row's correction changes only tmdb.
  5. Correct location by 2 km: the second confirmation; tmdb rows re-rounded; `config.yml`'s `lat`/`lon` updated; a correction row (through a `sqlite3` read of `state.sqlite` as the code owner, counts only).
  6. Precision: lower to `none` with "Also round the rows already stored" → every row null; raise to `2` → open rows unchanged, the next deploy stores two places.
  7. Hand edits: change `lat` in `config.yml` over SSH → the next `GET /surveys` records a `config` correction; change `survey_id` to a fresh id → a new in-use place "imported" from the file; the Status page's Location check links to the page while the id is unknown (check it before the `GET`).
  8. Import: a two-line CSV, one bad line refused by number; delete a used place and a planned one; the in-use one is refused.
  9. Viewer session: `/location` isn't in the menu, `GET /surveys` is 403.
  10. `tm-control migrate --dry-run` on a copy of the file with a per-sensor `lat`: names the sensor, prints no value.
  11. Device tests: `tmdev.py test <host> -- -k "survey or place or location or tm_internal"`, then the full non-disruptive suite.
  12. Leave the unit on a placeholder place with its original precision; delete the test places; remove the `.bak` files.
- [ ] **Bench B** (the second unit): a fresh install path (`tmsetup.sh` full run on the branch, blank coordinates): claim → the default place; deploy to a typed place; the suite with its skips.
- [ ] Record each item with `tmdev.py check item`, and end with `tmdev.py check end`.

### Task 15: Pull request

- [ ] Run every off-device check in Global Constraints once more on the final branch; `npm run build`; `git grep` the branch for device names and any coordinate other than the two allowed.
- [ ] Copy this plan to `design/plans/2026-11-06-location-3-places-and-screens.md` and commit it ("Add the Location page plan").
- [ ] Open the PR against `feature/detection-page/283` with the template filled in: the release-note paragraph ("The control app gains a Location page: add the places the unit is used at, deploy it to one from a phone, correct a wrong entry, choose how much of the location the database keeps, and import places from a file. `config.yml` is written by the page; editing it by hand still works. At upgrade, the places a unit recorded before are imported with their exact coordinates kept on the device only."), the two internal endpoints, the unit's new write path, the migration, the Docs list from Task 12, the Pi plan's results, the follow-ups (the map pin and the block picker, the exact-location copy, the `sharing:` block: plan 4), and the AI-assistance section. Retarget when PR 284 merges.
