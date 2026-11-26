# Setup History Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The database records which model, which software versions, and which camera settings were in force over time, so every event can be tied to them with one view, `events_with_setup`; a second PR sends the rows with shared data, without the three names a person typed.

**Architecture:** The control app gathers a snapshot of the setup (the running model from the Detection module's code, each camera's settings from Frigate's `/api/config`) on a background thread and posts it to a new Node-RED endpoint, `POST /tm-internal/setup`, at start, after its own changes, and every five minutes. Node-RED keeps two history tables, `setup_device` and `setup_camera`: an engine like the deployment engine reads the open rows, compares, and closes and inserts only when something differs. A view joins each event to the rows in force at its start. PR 2 sends each opened or closed row to the upload as a new kind of telemetry, `setup`, behind field lists, and sends the open rows again after a start, after the upload is turned on, and once a day.

**Tech Stack:** Python 3.13 (FastAPI control app, `threading`), Node-RED 5.0.10 function nodes (JavaScript in `flows.json`), SQLite migrations run by `tmdb_migrate.py`, pytest with the function-node harness in `script/tests/test_node_red_flows.py`, Ansible (one task), MkDocs.

**Spec:** "What it must do" below.

**Repo:** `glossyio/traffic-monitor`, two stacked PRs, each in its own worktree:

- **PR 1, the record** (Tasks 1 to 11): branch `feature/setup-history/358` off `dev`.
- **PR 2, the upload** (Tasks 12 to 15): branch `feature/setup-history-upload/358` off `dev`, once PR 1 and one other PR have merged (see "PR 2: the upload").

The public issue for this work is 358. All paths below are relative to the repo root.

## What it must do

1. **Two tables.** `setup_device` holds what is true of the whole unit; `setup_camera` holds what is true of one camera. Each row has a text `id`, `started` and `ended` in Unix milliseconds (as `deployment` rows), and the facts. `ended` is empty while the row is in force.
2. **`setup_device` facts:** `tm_version`, `tm_commit`, `schema_version`, `frigate_version`, `unit_system` (Frigate's `metric` or `imperial`, which names the unit of zone side lengths), `detector`, `model_id`, `model_file`, `model_sha256`, `model_kind` (`frigate_plus`, `local`, `installer_default`, `frigate_default`), `model_title`, `model_trained_at`, `model_base`, `model_type`, `model_width`, `model_height`, `labels_available` (JSON list).
3. **`setup_camera` facts:** `camera` (the `sensors.cameras` key in `config.yml`), `detect_width`, `detect_height`, `detect_fps`, `stationary_threshold`, `stationary_interval` (Frigate's `detect.stationary` values, in frames), `lens_hfov` (the detect stream's horizontal field of view in degrees; always empty in this change, filled by a later one), `labels_tracked` (JSON list), `thresholds` (JSON: each tracked label's filter numbers), `zones` (JSON list), `masks` (JSON), `profile` (the active Frigate profile's key when this camera defines that profile, else empty).
4. **Zones.** For each zone: `key`, `enabled`, `corners` (a list of `[x, y]` fractions of the frame in the order Frigate stores them), `distances` (as entered), `inertia`, `loitering_time`, `speed_threshold`, `objects`, `filters`. Never its `friendly_name` and never its colour.
5. **Masks.** `{"motion": [...], "objects": [...], "object_filters": {<label>: [...]}}`, each mask as `{"enabled": <bool>, "corners": [[x, y], ...]}`. Never a mask's id or `friendly_name`.
6. **The view.** `events_with_setup` is every column of `events`, then `setup_device_id` and the device facts under a `setup_` prefix, then `setup_camera_id` and the camera facts under a `camera_` prefix, from the row in force at the event's `start_time`. An event appears exactly once whatever the tables hold; an event with no row in force has those columns empty.
7. **Who gathers.** The control app. It posts a snapshot when it starts, after a model is used or a camera entry is saved through it, and every five minutes; after a snapshot that couldn't be completed or posted it tries again in 30 seconds.
8. **A new row only when something differs.** Rows are compared in a canonical form: lists whose order means nothing are sorted (labels, a zone's objects, the zones by key, the masks), JSON is written with sorted keys. A reordered list starts no row.
9. **An incomplete snapshot changes nothing.** When Frigate doesn't answer, runs in safe mode, or doesn't say which profile is active, or `config.yml` can't be read, the snapshot says `complete: false` and every row stays as it is. A camera whose Frigate camera is missing keeps its row.
10. **Whitelist.** Only the facts listed above leave the control app, keyed by `config.yml` camera keys. No Frigate camera name, no input path, no `friendly_name`. Node-RED accepts only the listed fields and only camera keys its own config has.
11. **A camera's row ends** when its key leaves `config.yml`.
12. **Status.** `GET /tm-internal/status` gains `setup`: when the last snapshot arrived and whether it was complete. A Status check, **Setup history**, warns when none has arrived for 15 minutes.
13. **Names.** A running model's title, and an active profile's key, that look like an address or a person's name draw a warning on the Status page, which never quotes them. Model titles get their own rule: numbers don't count (`512` in a title is a size).
14. **Model facts that were missing.** The control app keeps a Frigate+ record's `baseModel`. A default model's type and size come from Frigate's own answer, so they are no longer empty.
15. **Installer.** `TM_VERSION` in `node-red-tm.env` is refreshed on every run, so an upgraded unit reports its new version.
16. **Upload (PR 2).** Setup rows go out with **Share data**, as `values.setup = {device: [...], cameras: [...]}`; no new choice on the Sharing page.
    - **When.** Each row that opens or closes is sent. Every open row is sent again on the first complete snapshot after Node-RED starts, after the upload is turned on or its server changes, after the cameras that are captured change, and once a day. An upload that fails is never repeated, and a unit may start sharing long after its rows opened, so without this a server could hold events and never learn the setup they were counted under. A row goes out more than once; a server keys rows on `id`.
    - **What.** `setup` joins the gate's list of telemetry, and two new lists, `setup_device` and `setup_camera`, name the row fields that are sent: every column but `model_title`, `model_file`, and `profile`. Those three are names a person typed, and they stay on the unit; a server tells models apart by `model_sha256` and `model_id`. Zone keys are sent, inside `zones`, only for zones that are on, on a camera `config.yml` captures: those are the zones whose keys go out with events, and the ones the Zone names check reads. A zone that is off, and every zone of a camera that isn't captured, stays on the unit; a zone that is turned on starts a new row, which is sent with it.
    - **The notice** says so, under the version it has (`2026-11`, which no release has carried).
17. **The field rule has a test.** For each table: the snapshot the control app builds, the fields Node-RED accepts, the INSERT's columns and parameters, the table, the view's columns, and (PR 2) the upload list can't drift apart without a test failing.
18. **Docs and the sharing notice** say what is recorded (PR 1) and what is sent (PR 2).

Not in this change: filling `lens_hfov`; a radar's setup rows; any page or form in the control app's UI; anything on the deployment rows, a sensor's bearing or heading, or how it is mounted; the JSON export on the Data export page (the tables reach a reader through the database download); accuracy figures for a model.

## Global Constraints

- `flows.json` is edited by a script and written back with `json.dumps(flows, indent=4, ensure_ascii=False)` and no trailing newline. `test_flows_json_round_trips_through_json_dumps` must keep passing.
- Existing nodes keep their ids. A new node gets a new 16-hex id, sits in a group on its tab (in the group's `nodes` list, with `x`/`y` inside the group's box, the parent group's box grown if needed), and is found by name in tests.
- Function nodes run in Node-RED's sandbox: no `structuredClone`, no `fetch`. The test harness enforces this.
- No log line, warning, status text, or check detail names a camera (in Frigate's spelling or the key's), a zone, a model's title, or a profile, or quotes a value. Errors are named by class or by field name.
- Frigate's name for a camera is in no snapshot, no row, no context, and no upload.
- The control app reads Frigate only through `adapters/frigate.py`, and judges it by its API's answers, never by log text.
- The control app never opens `tmdb.sqlite`; Node-RED never opens `state.sqlite`.
- The migration only creates two tables, two indexes, and one view. It is written here as `0007`, and another stack of branches claims `0007` to `0009`. Never edit a migration that is already on `dev`. Before Task 1, look at `dev`'s newest migration and take the next number; if another migration merges while this branch is open, renumber this one. A renumbering changes the file's name, its test file's name, the versions in its tests, `LATEST_VERSION`, `schema.sql`, the pinned version in `test_migrate.py`, and the version the bench expects in the journal.
- A text fact longer than 128 characters is recorded as empty, never cut.
- The upload gate fails closed: when its lists can't be read, the two new ones included, it sends nothing (PR 2).
- No setup row leaves the unit with `model_title`, `model_file`, or `profile` (PR 2): the engine leaves them out, the lists don't name them, and the gate cuts what isn't listed.
- No setup row leaves the unit with a zone that is off, or with any zone of a camera that isn't captured (PR 2): the engine leaves them out, and the gate cuts them again.
- No UI source file changes in PR 1. PR 2 changes only the Sharing page's example.
- Docs ride with the code and follow "Writing docs" in `docs/development/contributing.md`. `mkdocs build --strict` must pass.
- On a bench unit nothing here turns on Frigate's detection, snapshots, or recording. The snapshot only reads Frigate's `/api/config`, `/api/version`, and `/api/profile/active`.
- Commit messages end with the trailer block in the repo's `CLAUDE.md`. No device names or addresses in commits or PR text.
- Nothing is pushed. The maintainer reads the commits and the PR text first.
- Other work in progress shares files with this one, and nothing else. Another stack of branches:
    - claims tmdb migrations `0007` to `0009` and adds a feature to `tmdb_migrate.py` (this plan doesn't touch the runner);
    - adds entries to `TM_INTERNAL_PATHS`, `TM_INTERNAL_METHODS`, and `VALIDATORS` in `script/tests/test_node_red_flows.py`, and renames one endpoint in them;
    - changes the upload gate node `ae3349867027d005` and adds a list to `upload-lists.json` (PR 2 here does both too);
    - changes text in the sharing notice, the sharing and data docs pages, and `CLAUDE.md`.

  Whichever merges second merges `dev` in, keeps both sides, and renumbers its migration. For PR 2 the order is settled: it is built after that stack's change to the gate and the list file is on `dev`. A conflict inside a node's `func` in `flows.json` is settled by taking `dev`'s node and making this plan's change to it again, never by editing the conflicted string by hand. This plan changes no node of the deployment engine, reads and names no deployment column (the view included), and adds no migration to the control app's store.

## Review Focus

Inputs the requirements imply and a person will meet; each has a test in the task named.

1. Frigate stopped, restarting after a model change, or in safe mode when a snapshot is due: no row closes and none opens; the row for the new model starts only once Frigate answers again. Tasks 3 and 7.
2. Frigate lists the same zones, labels, or masks in another order, or `/api/config` gives a number as `3` once and `3.0` later: no new row. Tasks 3 and 6.
3. A close that failed and left two open rows for one key, or Node-RED restarted with nothing in memory: the engine closes the older row, the view still lists each event once, and a snapshot that arrives before the schema version is known is refused and tried again. Tasks 1 and 3.
4. Events from before the first setup row, and events of a camera that has no row: listed once by the view with the setup columns empty. Task 1.
5. A zone or mask with a `friendly_name` that is an address, a Frigate camera named for a street, and an input path with a login in `/api/config`: none of them is in the snapshot, a row, a log line, or a check's detail. Tasks 6 and 9.
6. A unit that turns sharing on months after its rows opened, a server that couldn't be reached when the model changed, Node-RED restarted: the server still gets every open row, within a day at most, and no row twice in one message. Task 12.
7. A model titled for a street, a model file named for one, a profile keyed with an address: none of the three is in what leaves the unit, whether the engine left it out or only the gate was asked. Tasks 12 and 13.

## Files

| File | Change |
|---|---|
| `container/node-red-tm/schema/migrations/0007_setup_history.sql` | New: two tables, two indexes, the view |
| `container/node-red-tm/schema/schema.sql` | Regenerated |
| `container/node-red-tm/data/flows.json` | PR 1: a new group "tm-control setup history: POST /tm-internal/setup" on `init-config`, inside the status group `d9d94c0d493873b9`; changed node `a88895e60521585e` ("tm-internal: build status"). PR 2: the engine gains an output and a `link out`; a new group "setup" inside "thingsboard telemetry" on `thingsboard`; changed node `ae3349867027d005` (upload gate) |
| `container/node-red-tm/data/upload-lists.json`, `container/node-red-tm/data/README.md` | PR 2: `setup` in `telemetry`; new lists `setup_device` and `setup_camera`, each its table's columns but the three kept on the unit |
| `tm-control/backend/tm_control/modules/setup_history/` | New package: `__init__.py`, `snapshot.py` (what is gathered), `poster.py` (the thread) |
| `tm-control/backend/tm_control/adapters/frigate.py` | `active_profile()` |
| `tm-control/backend/tm_control/adapters/nodered.py` | `NodeRed.post_setup()` |
| `tm-control/backend/tm_control/modules/detection/inventory.py` | `Sidecar.base_model` |
| `tm-control/backend/tm_control/modules/cameras/zones.py` | `corners()` and `object_filters()` become public names |
| `tm-control/backend/tm_control/modules/apps/name_check.py` | `check_title()` |
| `tm-control/backend/tm_control/modules/apps/checks.py`, `contracts.py`, `core/checks.py` | Two checks; `Context.setup` |
| `tm-control/backend/tm_control/app.py`, `cli.py`, `fake.py` | The poster is built in `create_app` and started by `serve`; the fake Node-RED takes a snapshot |
| `tm-control/backend/tm_control/modules/detection/router.py`, `modules/cameras/router.py` | A wake after each change |
| `script/ansible/roles/tmsetup/tasks/node-red-tm_setup.yml` | `TM_VERSION` refreshed |
| `tm-control/backend/tm_control/modules/sharing/NOTICE.md`, `tm-control/ui/src/modules/sharing/examples.ts` | PR 2 |
| `script/devpi/tests/test_dataflow.py`, `script/devpi/README.md` | One device test |
| Tests | `container/node-red-tm/schema/tests/helpers.py`, `test_migrate.py`, `test_0007_setup_history.py` (new); `script/tests/test_node_red_flows.py`, `script/tests/test_tmsetup_tasks.py`; `tm-control/backend/tests/test_setup_snapshot.py`, `test_setup_poster.py` (new), `test_detection_inventory.py`, `test_name_check.py`, `test_app_checks.py`, `test_contract_checks.py`, `test_nodered_adapter.py`, `test_api_models.py`, `test_api_cameras.py`, `fixtures/nodered_status.json`, `fixtures/frigate_api_config.json` |
| Docs | `docs/data-and-payloads/setup-history.md` (new), `data-overview.md`, `docs/use/device-health.md`, `docs/ui/database.md`, `mkdocs.yml`, `container/node-red-tm/schema/README.md`, `CLAUDE.md`; PR 2: `docs/data-and-payloads/integrations.md`, `docs/use/sharing.md`, `docs/data-and-payloads/setup-history.md`, `data-overview.md`, `CLAUDE.md`, `design/plans/2026-11-23-setup-history.md` |

## Commands

```bash
. .venv/bin/activate                                   # the dev venv from CLAUDE.md, in the same shell call
python -m pytest container/node-red-tm/schema/tests -q
python -m pytest script/tests/test_node_red_flows.py -q
python -m pytest tm-control/backend/tests -q
python -m pytest container/node-red-tm/schema/tests script/tests tm-control/backend/tests -q   # everything off-device
python3 container/node-red-tm/schema/tmdb_migrate.py --dump-schema > container/node-red-tm/schema/schema.sql
(cd script/ansible && ansible-playbook -i localhost setup.yml --syntax-check </dev/null)
podman run --rm -v "$PWD/tm-control/ui:/ui:Z" -w /ui docker.io/library/node:22.23.4-alpine sh -c 'npm ci && npm run build && npm test'   # PR 2 only
~/.venvs/tm-docs/bin/mkdocs build --strict
```

The flows tests need `node` on the path; without it they skip, and CI fails a skip.

## Names used across tasks

| Name | What it is |
|---|---|
| `DEVICE_FACTS` | `tm_version`, `tm_commit`, `frigate_version`, `unit_system`, `detector`, `model_id`, `model_file`, `model_sha256`, `model_kind`, `model_title`, `model_trained_at`, `model_base`, `model_type`, `model_width`, `model_height`, `labels_available`, in that order: the keys of a snapshot's `device`. A constant in `snapshot.py` and in the tests |
| `CAMERA_FACTS` | `detect_width`, `detect_height`, `detect_fps`, `stationary_threshold`, `stationary_interval`, `lens_hfov`, `labels_tracked`, `thresholds`, `zones`, `masks`, `profile`, in that order: the keys of each camera in a snapshot |
| `SETUP_DEVICE_COLUMNS` (tests) | `id`, `started`, `ended`, then `DEVICE_FACTS` with `schema_version` inserted after `tm_commit` |
| `SETUP_CAMERA_COLUMNS` (tests) | `id`, `started`, `ended`, `camera`, then `CAMERA_FACTS` |
| JSON columns | `labels_available`, `labels_tracked`, `thresholds`, `zones`, `masks`: TEXT holding JSON written with sorted keys and no spaces |
| Snapshot body | `{"complete": false}`, or `{"complete": true, "device": {<DEVICE_FACTS>}, "cameras": {<key>: {<CAMERA_FACTS>}}}`. Every fact key is present; an unknown value is `null` |
| Row ids | `<started ms>-<8 hex>-sd` for a device row, `-sc` for a camera row, made as the deployment engine makes its `-d` ids |
| `global.tm_status.setup` | `{received_at: <ISO text>, complete: <bool>, changed_at: <ISO text or null>}`: the last snapshot Node-RED accepted, and when a row last changed |
| "setup engine" outputs | 1: close device, `{params: {$ended, $id}}`. 2: insert device, `{params: {$<column>: <value>}}`. 3: close camera. 4: insert camera. 5: the request's message with the answer. PR 2 adds 6: `{payload: {ts, device: [<row>...], cameras: [<row>...]}}`, when a row opened or closed or the open rows are due |
| `SETUP_KEPT_ON_THE_UNIT` (tests, PR 2) | `{"model_title", "model_file", "profile"}`: setup facts that are saved and never uploaded; changing it is a decision. The engine holds the same three as `KEPT_ON_THE_UNIT` |
| A sent row (PR 2) | The table's columns but `SETUP_KEPT_ON_THE_UNIT`, in column order; the JSON columns parsed back into lists and mappings; `ended` null while the row is open; `zones` holds only the zones that are on, and is null for a camera that isn't captured |
| `flow.setup_sent` (PR 2) | `{to: <the upload's URL>, at: <ms>, captured: <sorted keys of the captured cameras>}` on `init-config`, in memory: where and when the engine last handed every open row to the upload, and which cameras were captured then |
| `Snapshot` (`snapshot.py`) | `@dataclass(frozen=True)`: `body: dict`, `flagged: tuple[str, ...]` (of `"model_title"`, `"profile"`) |
| `app.state.setup_poster` | The `Poster`. `wake()`, `start()`, `stop()`, `run_once() -> bool`, `summary() -> dict` |
| `Context.setup` | `Poster.summary()`: `{"gathered": <bool>, "flagged": [<str>...]}` |

In tests, `NOW = 1795000000000` (milliseconds) and `T = 1795000000` (seconds).

---

## PR 1: the record

### Task 1: The migration and the view

**Files:**
- Create: `container/node-red-tm/schema/migrations/0007_setup_history.sql`, `container/node-red-tm/schema/tests/test_0007_setup_history.py`
- Modify: `container/node-red-tm/schema/schema.sql`, `container/node-red-tm/schema/tests/helpers.py`, `container/node-red-tm/schema/tests/test_migrate.py`, `container/node-red-tm/schema/README.md`

**Interfaces:**
- Produces: the two tables with the columns of `SETUP_DEVICE_COLUMNS` and `SETUP_CAMERA_COLUMNS` in order; the view `events_with_setup`; `LATEST_VERSION = 7`; `ALL_TABLES` gains `setup_device` and `setup_camera`.

- [ ] **Step 1: Write the failing tests** in `test_0007_setup_history.py`, in the style of `test_0004_watch_log.py` (a database at version 6 built by `migrate`, then 0007 applied):

```python
SETUP_DEVICE = {
    "id": "TEXT", "started": "INTEGER", "ended": "INTEGER", "tm_version": "TEXT", "tm_commit": "TEXT",
    "schema_version": "INTEGER", "frigate_version": "TEXT", "unit_system": "TEXT", "detector": "TEXT",
    "model_id": "TEXT", "model_file": "TEXT", "model_sha256": "TEXT", "model_kind": "TEXT", "model_title": "TEXT",
    "model_trained_at": "TEXT", "model_base": "TEXT", "model_type": "TEXT", "model_width": "INTEGER",
    "model_height": "INTEGER", "labels_available": "TEXT",
}
SETUP_CAMERA = {
    "id": "TEXT", "started": "INTEGER", "ended": "INTEGER", "camera": "TEXT", "detect_width": "INTEGER",
    "detect_height": "INTEGER", "detect_fps": "INTEGER", "stationary_threshold": "INTEGER",
    "stationary_interval": "INTEGER", "lens_hfov": "REAL", "labels_tracked": "TEXT", "thresholds": "TEXT",
    "zones": "TEXT", "masks": "TEXT", "profile": "TEXT",
}
```

  - `test_0007_adds_the_two_tables_and_nothing_else`: each table's `PRAGMA table_info` names and declared types equal the mapping above, in order; `id` is the primary key; `started` and (for cameras) `camera` are `NOT NULL`; every other table's columns are as at version 6; `user_version` is 7.
  - `test_view_columns`: the view's columns are `events`' columns in order, then `setup_device_id`, then `setup_<fact>` for each device column after `ended`, then `setup_camera_id`, then `camera_<fact>` for each camera column after `camera`. Build the expected list from `columns(path, "events")` and the two mappings, so a column added to a table without the view fails here.
  - `test_view_joins_the_rows_in_force`: one device row `[1000 s, 2000 s)` and an open one from 2000 s (times in ms), two camera rows for `cam_a` likewise, one open row for `cam_b`. Events of `cam_a` at 1500 s and 2500 s get the first and the second ids; an event at exactly 2000 s gets the second; an event of `cam_b` gets its row and the device row.
  - `test_view_lists_an_event_once_whatever_the_tables_hold`: two open device rows and two open `cam_a` rows that overlap; `SELECT count(*) FROM events_with_setup` equals `SELECT count(*) FROM events`, and each event takes the row with the later `started`.
  - `test_view_leaves_the_setup_empty_when_no_row_is_in_force`: an event before the first row, an event of a camera with no row, and an event with an empty `camera` are each listed once with `setup_device_id` or `setup_camera_id` NULL.
  - `test_view_shows_a_column_added_to_events_later`: after `ALTER TABLE events ADD COLUMN later TEXT`, a new connection's `SELECT later FROM events_with_setup` works.

- [ ] **Step 2: Run them to see them fail**

Run: `python -m pytest container/node-red-tm/schema/tests/test_0007_setup_history.py -q`
Expected: FAIL, no such table `setup_device`.

- [ ] **Step 3: Write `0007_setup_history.sql`.** A header comment in the style of `0004`'s (what the tables hold, that times are Unix milliseconds, that the view stores nothing). The two `CREATE TABLE` statements with the columns above, `id TEXT PRIMARY KEY`. Two indexes: `index_setup_device_started ON setup_device(started)` and `index_setup_camera_camera_started ON setup_camera(camera, started)`. The view, in this shape, with every fact column named:

```sql
CREATE VIEW events_with_setup AS
SELECT e.*,
    d.id AS setup_device_id, d.tm_version AS setup_tm_version, /* ... each device fact ... */
    c.id AS setup_camera_id, c.detect_width AS camera_detect_width /* ... each camera fact ... */
FROM events e
LEFT JOIN setup_device d ON d.id = (
    SELECT s.id FROM setup_device s
    WHERE s.started <= e.start_time * 1000 AND (s.ended IS NULL OR s.ended > e.start_time * 1000)
    ORDER BY s.started DESC, s.id DESC LIMIT 1)
LEFT JOIN setup_camera c ON c.id = (
    SELECT s.id FROM setup_camera s
    WHERE s.camera = e.camera AND s.started <= e.start_time * 1000
        AND (s.ended IS NULL OR s.ended > e.start_time * 1000)
    ORDER BY s.started DESC, s.id DESC LIMIT 1);
```

  The subquery with `LIMIT 1` is what keeps an event to one row when two rows overlap.

- [ ] **Step 4: Regenerate `schema.sql`, set `LATEST_VERSION = 7`, add the two tables to `ALL_TABLES`**, and bring `test_migrate.py`'s pinned version in line. `test_schema_snapshot.py` and `test_flows_sql.py` must pass unchanged.

- [ ] **Step 5: `container/node-red-tm/schema/README.md`:** the first view in tmdb. Say that a later migration that adds a column to either table drops and recreates the view to show it, and that SQLite refuses to drop or rename an `events` column while the view names it.

- [ ] **Step 6: Run the schema tests**

Run: `python -m pytest container/node-red-tm/schema/tests -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add container/node-red-tm/schema
git commit   # subject: Add the setup history tables and the events_with_setup view
```

---

### Task 2: Node-RED accepts a snapshot

**Files:**
- Modify: `container/node-red-tm/data/flows.json`, `script/tests/test_node_red_flows.py`

**Interfaces:**
- Produces: `POST /tm-internal/setup` on `init-config`: `http in` → "tm-internal: check token" (a copy of the other endpoints' node, same name, same code) → "tm-internal: validate setup" (outputs: 1 accepted, 2 refused) → Task 3's nodes. On output 1 the message carries `msg.setup = {complete, device, cameras}` with only listed fields. Refusals answer through `http response` nodes with 401, 400, and 503 as the other endpoints do.

- [ ] **Step 1: Write the failing tests.** Add `/tm-internal/setup` to `TM_INTERNAL_PATHS`, `TM_INTERNAL_METHODS` (`"post"`), and `VALIDATORS` (`"tm-internal: validate setup"`); the existing wiring and group tests then cover the endpoint. Then, with `run_functions` on the validator and a `context` whose `config.sensors.cameras` has `cam_a` and `cam_b` and whose `tm_status.schema_version` is 7:

```python
GOOD = {"complete": True, "device": {**dict.fromkeys(DEVICE_FACTS), "tm_version": "0.8.0", "model_width": 320,
                                     "labels_available": ["car", "person"]},
        "cameras": {"cam_a": {**dict.fromkeys(CAMERA_FACTS), "detect_width": 1536, "zones": [], "masks": {}}}}

@pytest.mark.parametrize("body, status, detail", [
    ("text", 400, "body"), ({}, 400, "complete"), ({"complete": "yes"}, 400, "complete"),
    ({**GOOD, "device": None}, 400, "device"),
    ({**GOOD, "device": {**GOOD["device"], "frigate_camera": "x"}}, 400, "device.frigate_camera"),
    ({**GOOD, "device": {**GOOD["device"], "model_width": "320"}}, 400, "device.model_width"),
    ({**GOOD, "device": {**GOOD["device"], "labels_available": "car"}}, 400, "device.labels_available"),
    ({**GOOD, "device": {**GOOD["device"], "tm_version": "x" * 129}}, 400, "device.tm_version"),
    ({**GOOD, "cameras": {"cam_a": {**GOOD["cameras"]["cam_a"], "friendly_name": "x"}}}, 400, "cameras.friendly_name"),
    ({**GOOD, "cameras": {"cam_a": {**GOOD["cameras"]["cam_a"], "zones": "z"}}}, 400, "cameras.zones"),
])
def test_validate_setup_refuses(body, status, detail): ...   # output 2, msg.statusCode, payload {"error": "bad_request", "detail": detail}
```

  - `test_validate_setup_accepts_an_incomplete_snapshot`: `{"complete": False}` leaves on output 1 with `msg.setup == {"complete": False}`; anything beside `complete` in such a body is dropped.
  - `test_validate_setup_keeps_only_config_cameras`: a body with `cam_a` and `street_cam` passes with `msg.setup.cameras` holding `cam_a` only, and the log is empty.
  - `test_validate_setup_waits_for_the_config_and_the_schema_version`: with no `config` in context, or `tm_status.schema_version` missing, a complete body leaves on output 2 with 503 and `{"error": "not_ready"}`; an incomplete body is still accepted.
  - `test_validate_setup_caps_a_json_fact`: `zones` whose JSON text is over 16384 characters is refused with `cameras.zones`.
  - A fact key that is missing from `device` or from a camera is refused with its name (every key is present in a snapshot).

- [ ] **Step 2: Run to see them fail**

Run: `python -m pytest script/tests/test_node_red_flows.py -q -k "setup or tm_internal"`
Expected: FAIL, no node named "tm-internal: validate setup".

- [ ] **Step 3: Add the nodes** with the edit script. The validator's rules, which the tests above pin:
  - The body is a mapping with a boolean `complete`.
  - Text facts (`tm_version`, `tm_commit`, `frigate_version`, `unit_system`, `detector`, `model_id`, `model_file`, `model_sha256`, `model_kind`, `model_title`, `model_trained_at`, `model_base`, `model_type`, `profile`): a string of 1 to 128 characters, or null.
  - Whole-number facts (`model_width`, `model_height`, `detect_width`, `detect_height`, `detect_fps`, `stationary_threshold`, `stationary_interval`): an integer, or null. `lens_hfov`: a finite number, or null.
  - `labels_available`, `labels_tracked`: a list of strings. `zones`: a list. `thresholds`, `masks`: a mapping. Each at most 16384 characters as JSON.
  - `cameras` is a mapping of at most 32 entries; a key that `global.get("config").sensors.cameras` doesn't have is left out without a word.
  - `detail` names a field only, as `device.<field>` or `cameras.<field>`, never a camera's key or a value.

- [ ] **Step 4: Run the flows tests**

Run: `python -m pytest script/tests/test_node_red_flows.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add container/node-red-tm/data/flows.json script/tests/test_node_red_flows.py
git commit   # subject: Add the endpoint that takes a setup snapshot from the control app
```

---

### Task 3: The setup engine

**Files:**
- Modify: `container/node-red-tm/data/flows.json`, `script/tests/test_node_red_flows.py`, `tm-control/backend/tests/fixtures/nodered_status.json`

**Interfaces:**
- Consumes: `msg.setup` from Task 2.
- Produces: after the validator, two `sqlite` reads (the tmdb config node `2f60c1ab30a6fc8f`, prepared statements), each followed by a `change` node as the deployment engine's read is: "read open setup_device" (`SELECT * FROM setup_device WHERE ended IS NULL ORDER BY started DESC, id DESC`) into `msg.openDevice`, "read open setup_camera" (the same on `setup_camera`) into `msg.openCameras`; then the function "setup engine" with the five outputs under "Names used across tasks", wired to four `sqlite` nodes ("close setup_device", "insert setup_device", "close setup_camera", "insert setup_camera") and an `http response`. `global.tm_status.setup`. The status body's `setup` key.

- [ ] **Step 1: Write the failing tests** for "setup engine" with `run_functions`, `tm_status.schema_version` 7, and `config.sensors.cameras` holding `cam_a` and `cam_b`. The engine takes the time from `Date.now()` once per message; where a test below says "now", it asserts a whole number of milliseconds between the times the test took before and after the run, and that a closed row's `$ended` equals the `$started` of the row that replaces it:
  - `test_setup_engine_starts_rows_on_an_empty_database`: a complete snapshot with `cam_a` gives one device insert and one camera insert, `$started` now, `$ended` absent, ids ending `-sd` and `-sc`, `$schema_version` 7, each JSON column a string; the answer is 200 `{"changed": 2}`.
  - `test_setup_engine_changes_nothing_when_nothing_differs`: open rows that hold exactly what the snapshot says give no close, no insert, `{"changed": 0}`.
  - `test_setup_engine_ignores_order_and_number_form`: the open row's `zones` text has its keys in another order than the snapshot's, and the snapshot gives `speed_threshold` as `3.0` where the row's text has `3`: nothing changes.
  - `test_setup_engine_closes_and_opens_when_a_fact_differs`, parametrized over one device fact (`model_sha256`), `schema_version` (the global is 8 now), and one camera fact (`zones`): the open row closes with `$ended` now and a new row opens with `$started` now; the other table is untouched.
  - `test_setup_engine_leaves_everything_alone_for_an_incomplete_snapshot`: `{"complete": False}` with open rows: no close, no insert, `{"changed": 0}`.
  - `test_setup_engine_keeps_the_row_of_a_camera_the_snapshot_leaves_out`: `cam_b` has an open row and isn't in `msg.setup.cameras`, but is in the config: its row stays.
  - `test_setup_engine_ends_the_row_of_a_camera_that_left_the_config`: an open row for `cam_gone`, which the config doesn't have: closed. With an incomplete snapshot it is closed all the same (the config is Node-RED's own).
  - `test_setup_engine_ends_no_row_without_a_cameras_mapping`: with no `config` in context, or a config whose `sensors.cameras` isn't a mapping, an incomplete snapshot closes nothing, as the deployment engine closes nothing without a sensors object.
  - `test_setup_engine_closes_the_older_of_two_open_rows`: two open device rows and two open `cam_a` rows: the older of each closes, and the newer is the one compared.
  - `test_setup_engine_records_what_arrived`: after a complete snapshot `tm_status.setup` is `{received_at: <now, ISO>, complete: true, changed_at: <now or what it was>}`; after an incomplete one `complete` is false and `changed_at` keeps its value.
  - `test_setup_engine_logs_nothing`: every case above leaves the step's log empty.
  - `test_setup_inserts_name_every_column`: each insert node's SQL names exactly the table's columns but `ended`, and the engine's insert parameters are exactly those names with `$` (the field rule's Node-RED half).
- [ ] **Step 2:** In the status tests, `test_status_reports_the_setup_history`: "tm-internal: build status" answers `setup: null` when `tm_status.setup` isn't set, and the three fields when it is. Add `"setup": {"received_at": "2026-10-28T22:54:55.000Z", "complete": true, "changed_at": null}` to `fixtures/nodered_status.json`.

- [ ] **Step 3: Run to see them fail**

Run: `python -m pytest script/tests/test_node_red_flows.py -q -k setup`
Expected: FAIL, no node named "setup engine".

- [ ] **Step 4: Add the nodes.** The engine's rules, in order:
  1. One open row per key: every open row after the newest is closed.
  2. A camera's open rows are closed when `config.sensors.cameras` is a mapping and doesn't have its key. When it isn't a mapping, no row is closed for that reason.
  3. With `complete` false, nothing more happens.
  4. Device: the candidate is the snapshot's `device` plus `schema_version` from `tm_status`. Each JSON column is written by one function, `canonical(value)`: `JSON.stringify` with every mapping's keys sorted, at any depth. With no open row, insert. With one, compare the candidate with it column by column (`null` and a missing value are equal; a JSON column compares the row's text, parsed and written again by `canonical`, with the candidate's); insert and close only when one differs.
  5. Cameras: the same for each key in `msg.setup.cameras`.
  6. The answer: `msg.statusCode = 200`, `msg.payload = {changed: <rows inserted>}`.

  The inserts and closes leave as new messages that carry only `params`, never `msg.req` or `msg.res`. "tm-internal: build status" gains `setup: status.setup || null`.

- [ ] **Step 5: Run the flows tests and the schema tests** (`test_flows_sql.py` prepares the new statements against the schema)

Run: `python -m pytest script/tests/test_node_red_flows.py container/node-red-tm/schema/tests -q`
Expected: PASS.

- [ ] **Step 6: Stop for the maintainer's look at the flows.** Run `~/.claude/tools/tm-flows-review/tm-flows-review.sh` and hand him what it prints, with the list of new nodes and the one changed node.

- [ ] **Step 7: Commit**

```bash
git add container/node-red-tm/data/flows.json script/tests/test_node_red_flows.py tm-control/backend/tests/fixtures/nodered_status.json
git commit   # subject: Keep the setup history: a new row only when the snapshot differs
```

---

### Task 4: The Frigate facts the snapshot lacks

**Files:**
- Modify: `tm-control/backend/tm_control/adapters/frigate.py`, `tm-control/backend/tm_control/modules/detection/inventory.py`, `tm-control/backend/tm_control/modules/cameras/zones.py`, `tm-control/backend/tm_control/modules/cameras/reference.py` (only if it imports a renamed name)
- Test: `tm-control/backend/tests/test_frigate_frames.py` (it holds the Frigate adapter's HTTP tests, with a local `http_app`), `test_detection_inventory.py`, `test_cameras_zones.py`, `tm-control/backend/tests/fixtures/model_sidecar.json`

**Interfaces:**
- Produces:
  - `frigate.active_profile() -> tuple[bool, str | None]`: `GET {BASE}/profile/active` with `FRESH`. `(True, <key>)` for a 200 whose JSON is a mapping with `active_profile` a non-empty string; `(True, None)` for a 200 with `active_profile` null, and for a 404 (a Frigate without profiles); `(False, None)` for anything else.
  - `Sidecar.base_model: str | None`, from the record's `baseModel` when it is a string, else `None`. The module docstring's sentence about what a sidecar is read for names it.
  - `zones.corners(value) -> list[Corner]` and `zones.object_filters(value) -> dict[str, dict[str, int | float]]`: today's `_corners` and `_filters` under public names, with the same behaviour; callers inside the module follow.

- [ ] **Step 1: Confirm the route.** In Frigate 0.18.2's source, `frigate/api/app.py` defines `GET /profile/active`, answering `{"active_profile": <name or null>}`. Confirm it is mounted under `/api` as `/config` is (the same router), and write the file and line in the function's docstring. If it isn't under `/api`, stop and tell the maintainer.
- [ ] **Step 2: Write the failing tests:** the five answers of `active_profile` (a key, null, 404, a 500, no answer), with the HTTP helper patched as the adapter's other tests patch it; `parse_sidecar` keeps `baseModel` and reads a number there as `None`; `corners` and `object_filters` under their new names give what the old tests expect.
- [ ] **Step 3: Run to see them fail**

Run: `python -m pytest tm-control/backend/tests -q -k "active_profile or base_model or corners or object_filters"`
Expected: FAIL (no such attribute).

- [ ] **Step 4: Implement the three.**
- [ ] **Step 5: Run the control app's tests**

Run: `python -m pytest tm-control/backend/tests -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add tm-control/backend
git commit   # subject: Read Frigate's active profile and a model record's base model
```

---

### Task 5: A title's name check

**Files:**
- Modify: `tm-control/backend/tm_control/modules/apps/name_check.py`
- Test: `tm-control/backend/tests/test_name_check.py`

**Interfaces:**
- Produces: `check_title(title: str) -> Literal["pattern"] | None`. `check_name` is unchanged.

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.parametrize("title, expected", [
    ("yolov9s-512", None), ("mobiledet 320x320", None), ("Fall 2026 retrain", None), ("model 1420", None),
    ("O'Brien bikes", "pattern"), ("Oak St bikes", "pattern"), ("1420 Oak Street", "pattern"),
    ("Maple Avenue v2", "pattern"), ("street model", None), ("", None),
])
def test_check_title(title, expected):
    assert check_title(title) == expected
```

- [ ] **Step 2: Run to see it fail**

Run: `python -m pytest tm-control/backend/tests/test_name_check.py -q`
Expected: FAIL, `check_title` isn't defined.

- [ ] **Step 3: Implement `check_title`.** A title is a made-up name, so an unknown word alone is nothing, and a number of any length is a size or a date: "pattern" only for an apostrophe, a shortened street kind (`STREET_ABBREVIATIONS`), or an address word (`ADDRESS_WORDS`) together with a word that is neither a number nor known. Share the word splitting with `check_name`; don't copy the lists.
- [ ] **Step 4: Run** the same command. Expected: PASS.
- [ ] **Step 5: Commit**

```bash
git add tm-control/backend
git commit   # subject: Add a name check for a model's title
```

---

### Task 6: What a snapshot holds

**Files:**
- Create: `tm-control/backend/tm_control/modules/setup_history/__init__.py` (a docstring only), `tm-control/backend/tm_control/modules/setup_history/snapshot.py`, `tm-control/backend/tests/test_setup_snapshot.py`
- Modify: `tm-control/backend/tests/fixtures/frigate_api_config.json` only if a test needs a key it lacks; prefer building the camera in the test

**Interfaces:**
- Consumes: `zones.zone_facts`, `zones.detect_size`, `zones.corners`, `zones.object_filters` (Task 4); `Sidecar.base_model`; `detection.picker.detector_type`, `running_model`, `first_detector`; `detection.inventory.inventory`, `installer_default`, `model_cache_dir`; `detection.labels.recognised`; `apps.contracts.MODEL_ID`; `name_check.check_name`, `check_title`.
- Produces, in `snapshot.py`:
  - `DEVICE_FACTS`, `CAMERA_FACTS`: tuples, as under "Names used across tasks". `TEXT_MAX = 128`.
  - `device_facts(manifest, frigate_version: str, frigate_config: Mapping, config_file: ConfigRead, models: list[Model], installer: InstallerDefault | None) -> dict`
  - `camera_facts(camera: Mapping, active_profile: str | None) -> dict`
  - `flagged(device: dict, profiles: Iterable[str]) -> tuple[str, ...]`
  - `Snapshot` and `INCOMPLETE = Snapshot({"complete": False}, ())`
  - `gather(app_state) -> Snapshot` (Task 7 calls it; it never raises for an app that doesn't answer)

- [ ] **Step 1: Write the failing tests.** Pure functions first, each on a camera or config written out in the test:
  - `test_camera_facts_has_exactly_the_listed_keys`: `tuple(camera_facts({}, None)) == CAMERA_FACTS`, every value `None`, `[]`, or `{}`; and the same for `device_facts` with `DEVICE_FACTS`.
  - `test_camera_facts_reads_detect_and_stationary`: `detect` `{width: 1536, height: 864, fps: 10, stationary: {interval: 50, threshold: 50}}` gives those five numbers; `lens_hfov` is `None`.
  - `test_camera_facts_sorts_what_has_no_order`: `objects.track` `["person", "car"]` gives `["car", "person"]`; zones given as `zone_b` then `zone_a` come out by key; a zone's `objects` are sorted; its `corners` and `distances` keep their order.
  - `test_camera_facts_zone_shape`: a zone gives exactly the keys `key`, `enabled`, `corners`, `distances`, `inertia`, `loitering_time`, `speed_threshold`, `objects`, `filters`, with `corners` as `[[0.542, 0.429], ...]`.
  - `test_camera_facts_thresholds_are_the_tracked_labels_filters`: `objects.filters` for `car` (tracked) and `dog` (not tracked) gives `car`'s numbers only, and only `zones.FILTER_KEYS`; a filter's `mask` is not in `thresholds`.
  - `test_camera_facts_masks`: `motion.mask` `{"m1": {"friendly_name": "12 Oak St drive", "enabled": True, "coordinates": "0,0,1,0,1,1"}, "m2": None}`, an `objects.mask`, and an `objects.filters.car.mask` give `{"motion": [{"enabled": True, "corners": [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0]]}], "objects": [...], "object_filters": {"car": [...]}}`; masks are sorted by their corners; an entry that is null or has fewer than three corners is left out; a label with no mask left has no entry.
  - `test_camera_facts_profile`: with `active_profile="night"`, a camera whose `profiles` has `night` gives `"night"`; one without gives `None`.
  - `test_nothing_typed_as_a_display_name_is_kept`: a camera with `name` and `friendly_name` `"Oak Ave by the school"`, zones and masks with `friendly_name`, `ffmpeg.inputs[0].path` `"rtsp://user:pw@10.0.0.9/stream"`: `json.dumps(camera_facts(...))` has none of `Oak`, `rtsp`, `10.0.0.9`, `friendly_name`, `color`.
  - `test_device_facts_for_each_kind_of_model`, parametrized over a Frigate+ pair, a local pair, the installer's default, and Frigate's own default with no file: `model_kind`, `model_file`, `model_sha256` (the model file's, not the sidecar's), `model_id` (the sidecar's id only when it matches `MODEL_ID`), `model_title` (the sidecar's name), `model_trained_at`, `model_base`. For Frigate's own default on a CPU detector, the file, hash, id, and title are `None`.
  - `test_device_facts_type_and_size_come_from_frigate`: `model_type`, `model_width`, `model_height` are the first detector's `model` section's `model_type`, `width`, `height`, else the top-level `model` section's; a width that is `True` or text is `None`.
  - `test_device_facts_versions_and_unit`: `tm_version` and `tm_commit` from the manifest; `unit_system` is `ui.unit_system` when it is `metric` or `imperial`, else `None`; `labels_available` is sorted.
  - `test_a_long_text_is_left_out`: a sidecar name of 129 characters gives `model_title` `None`.
  - `test_flagged`: a title `"Oak St bikes"` gives `("model_title",)`; a profile `"1420_oak_st"` gives `("profile",)`; both give both, in that order; neither gives `()`.

  Then `gather`, with the adapters patched (`frigate.version`, `frigate.config`, `frigate.active_profile`, the config read) and a `tmp_path` model cache:
  - `test_gather_is_incomplete_when_frigate_or_the_config_cant_be_read`, parametrized: no version, no config, safe mode, `active_profile` `(False, None)`, `config.yml` unreadable. Each gives `INCOMPLETE`.
  - `test_gather_keys_cameras_by_config_key`: an entry `cam_a` with `frigate_camera: oak_ave`, an entry `cam_dup` pointing at the same camera, an entry `cam_gone` whose camera Frigate lacks, and a Frigate camera no entry points at: `body["cameras"]` has `cam_a` only, and `"oak_ave"` is nowhere in `json.dumps(body)`.
  - `test_gather_includes_an_entry_that_is_off`: an entry with `enabled: false` whose Frigate camera exists has its facts.
  - `test_gather_flags_only_profiles_in_use`: the active profile is checked; a profile no camera defines isn't in any row and isn't flagged.
  - `test_gather_in_fake_mode_reads_the_fake_frigate`: with fake settings it builds a complete snapshot from `fake.frigate_answer`, a fake version text, and no active profile, and touches no adapter.

- [ ] **Step 2: Run to see them fail**

Run: `python -m pytest tm-control/backend/tests/test_setup_snapshot.py -q`
Expected: FAIL, no module `tm_control.modules.setup_history`.

- [ ] **Step 3: Implement `snapshot.py`.** Decisions the tests leave open:
  - `gather` reads in this order and stops at the first that fails: `frigate.version()`, `frigate.config()` (safe mode counts as failing), `frigate.active_profile()`, then `config.yml` through the same reader the Cameras routes use (`app_state.config_path`). It pairs entries with Frigate's cameras with `cameras.state.compare`, and takes each row that has a name, no `duplicate_of`, and `in_frigate` of `on` or `off`.
  - The model facts come from the same calls `get_models` in `detection/router.py` makes (`installer_default`, `detector_type`, `inventory`, `running_model`, `recognised`), in the same order. For Frigate's own default, the model's entry is the inventory's `frigate_default` one when it has one.
  - The first gather after a start hashes the running model's file (up to 100 MB); `inventory` caches the hash, so later ones don't.
  - A text fact that isn't a string, is empty, or is longer than `TEXT_MAX` is `None`.

- [ ] **Step 4: Run the control app's tests**

Run: `python -m pytest tm-control/backend/tests -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tm-control/backend
git commit   # subject: Gather the setup snapshot: the model, the versions, and each camera's settings
```

---

### Task 7: The poster

**Files:**
- Create: `tm-control/backend/tm_control/modules/setup_history/poster.py`, `tm-control/backend/tests/test_setup_poster.py`
- Modify: `tm-control/backend/tm_control/adapters/nodered.py`, `tm-control/backend/tm_control/app.py`, `tm-control/backend/tm_control/cli.py`, `tm-control/backend/tm_control/fake.py`
- Test: `tm-control/backend/tests/test_nodered_adapter.py`, `test_app_core.py`, `test_tm_control_cli.py`

**Interfaces:**
- Consumes: `snapshot.gather`, `Snapshot`.
- Produces:
  - `NodeRed.post_setup(self, body: dict) -> None`: `POST /setup`; raises `NodeRedError` as the other calls do (a 503 is `unexpected`).
  - `FakeNodeRed.post_setup(self, body: dict) -> None`: keeps the body as `self.setup`; its `report()` gains `"setup": {"received_at": <ISO now>, "complete": <bool>, "changed_at": None}` once one arrived, else `"setup": None`.
  - In `poster.py`: `INTERVAL = 300.0`, `RETRY = 30.0`, and

    ```python
    class Poster:
        def __init__(self, gather: Callable[[], Snapshot], post: Callable[[dict], None],
                     interval: float = INTERVAL, retry: float = RETRY): ...
        def run_once(self) -> bool: ...   # gather and post; True only when a complete snapshot was accepted
        def start(self) -> None: ...      # one daemon thread; a second call does nothing
        def stop(self) -> None: ...
        def wake(self) -> None: ...       # ends the current wait, so the next snapshot is made now
        def summary(self) -> dict: ...    # {"gathered": bool, "flagged": list[str]}
    ```

  - `app.state.setup_poster`, built in `create_app` in both modes and never started there; `serve()` starts it when `settings.fake` is false.
  - The status report's `Context` is built with `setup=app.state.setup_poster.summary()` (Task 9 adds the parameter; until then this line waits).

- [ ] **Step 1: Write the failing tests** in `test_setup_poster.py`, with `gather` and `post` as plain functions that record their calls:
  - `test_run_once_posts_the_body_and_reports_complete`: a complete snapshot is posted as its `body`, and `run_once()` is `True`; `summary()` is `{"gathered": True, "flagged": [...]}` with the snapshot's flags.
  - `test_run_once_posts_an_incomplete_snapshot_too`: `INCOMPLETE` is posted, `run_once()` is `False`, and `summary()["gathered"]` is `False`.
  - `test_run_once_never_raises`, parametrized: `gather` raises `RuntimeError("secret text")`; `post` raises `NodeRedError("unreachable")`. `run_once()` is `False`, and the one log record (`caplog`) names the exception's class and not its text.
  - `test_the_loop_waits_the_interval_after_a_complete_post_and_the_retry_otherwise`: drive the loop with a fake wait function (inject it, as `fetch.wait` takes `sleep`) and assert the waits asked for: `300.0` after `True`, `30.0` after `False`.
  - `test_wake_ends_the_wait`: with a real thread, an interval of 60, and a `gather` that sets an event each call: after `start()` the first call arrives; `wake()` brings a second within a second; `stop()` ends the thread (`join(2)` returns with it dead).
  - `test_start_twice_runs_one_thread`.
- [ ] **Step 2:** `test_nodered_adapter.py`: `post_setup` sends the body as JSON to `/tm-internal/setup` with the token header, and a 503 raises `NodeRedError` with code `unexpected`. `test_app_core.py`: `create_app` gives `app.state.setup_poster` and starts no thread (`threading.enumerate()` before and after). `test_tm_control_cli.py`: `serve` starts the poster for a device's settings and not for fake settings (patch `uvicorn.run` and `Poster.start`).

- [ ] **Step 3: Run to see them fail**

Run: `python -m pytest tm-control/backend/tests -q -k "poster or post_setup or serve"`
Expected: FAIL.

- [ ] **Step 4: Implement.** The thread's loop is `while not stopped: ok = run_once(); wait(interval if ok else retry)`, where the wait ends early on `wake()` or `stop()`. `serve()` keeps the app in a variable so it can start the poster before `uvicorn.run`; the thread is a daemon, so it ends with the process.

- [ ] **Step 5: Run the control app's tests**

Run: `python -m pytest tm-control/backend/tests -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add tm-control/backend
git commit   # subject: Post the setup snapshot at start and every five minutes
```

---

### Task 8: A snapshot right after a change

**Files:**
- Modify: `tm-control/backend/tm_control/modules/detection/router.py`, `tm-control/backend/tm_control/modules/cameras/router.py`
- Test: `tm-control/backend/tests/test_api_models.py`, `test_api_cameras.py`

**Interfaces:**
- Consumes: `request.app.state.setup_poster.wake()`.

- [ ] **Step 1: Write the failing tests.** Replace `app.state.setup_poster` with an object that counts `wake()` calls. One test per route:
  - Detection: each route that makes Frigate run another model (a model's use, the default's use, and a Frigate+ model used by its ID, where the wake is in the callback that runs once Frigate has saved) wakes once after it succeeded, and not when it was refused.
  - Cameras: each route that saves `config.yml` (add, edit, re-key, remove) wakes once after the file was written, and not on a 409 or a 422. The route that switches Frigate's detection doesn't wake: no fact in the snapshot changes.
- [ ] **Step 2: Run to see them fail**

Run: `python -m pytest tm-control/backend/tests/test_api_models.py tm-control/backend/tests/test_api_cameras.py -q -k wake`
Expected: FAIL (0 calls).

- [ ] **Step 3: Add the calls.** A model change restarts Frigate, so the snapshot right after the wake is incomplete, and the 30-second retry is what records the new model once Frigate answers.
- [ ] **Step 4: Run** the two files whole. Expected: PASS.
- [ ] **Step 5: Commit**

```bash
git add tm-control/backend
git commit   # subject: Take a setup snapshot right after a model or camera change
```

---

### Task 9: The two Status checks

**Files:**
- Modify: `tm-control/backend/tm_control/core/checks.py`, `tm-control/backend/tm_control/modules/apps/checks.py`, `tm-control/backend/tm_control/modules/apps/contracts.py`, `tm-control/backend/tm_control/app.py`, `tm-control/backend/tests/fixtures/status_fake.json` (so fake mode's Status page shows both)
- Test: `tm-control/backend/tests/test_checks_core.py`, `test_app_checks.py`, `test_contract_checks.py`

**Interfaces:**
- Consumes: `Poster.summary()`; the status body's `setup` and `uptime_seconds`.
- Produces: `Context(..., setup: dict | None = None)` with `context.setup`; `apps.checks.setup_history(context)`, id `apps.setup_history`, title "Setup history", last in the Apps group; `contracts.setup_names(context)`, id `config.setup_names`, title "Model and profile names", right after `zone_names` in its group.

- [ ] **Step 1: Write the failing tests.** `setup_history`, with Node-RED's report patched and the clock fixed:

| Node-RED's report | Status | Detail |
|---|---|---|
| none (it didn't answer) | unknown | "Node-RED didn't answer, so the setup history's state isn't known." |
| no `setup` key | warn | "Node-RED's flows don't keep the setup history. Re-run the installer with tmsetup.sh -t node-red-tm." |
| `setup` null, `uptime_seconds` under 600 | ok | "Waiting for the first snapshot since Node-RED started." |
| `setup` null, `uptime_seconds` 600 or more | warn | "No snapshot of the setup has arrived since Node-RED started; if it stays this way, download the diagnostics on the Device page." |
| `received_at` over 900 seconds old | warn | "The last snapshot of the setup arrived 20 minutes ago." (through `duration`) |
| `complete` false, recent | ok | "Frigate isn't answering, so the recorded setup stays as it is." |
| `complete` true, recent | ok | "The model, the versions, and each camera's settings are recorded." |

  `setup_names`, with `context.setup` set:

| `context.setup` | Status | Detail |
|---|---|---|
| `None`, or `gathered` false | unknown | "The setup hasn't been read yet." |
| `flagged` empty | ok | "The running model's title and the active profile's name don't look like an address or a person's name." |
| `["model_title"]` | warn | "The running model's title looks like an address or a person's name. It is saved in the database." with a link fix "Open the Detection page" to `/detection` |
| `["profile"]` | warn | "Frigate's active profile has a name that looks like an address or a person's name. It is saved in the database." |
| both | warn | the two sentences, the model's first, with the Detection link |

  And `test_no_check_quotes_a_name`: with a flagged title in the poster's last snapshot, neither check's detail holds a word of it.

- [ ] **Step 2: Run to see them fail**

Run: `python -m pytest tm-control/backend/tests -q -k "setup_history or setup_names"`
Expected: FAIL.

- [ ] **Step 3: Implement** the parameter, the two functions, and the `Context` line in `app.py`. Neither check imports from `modules/setup_history` (that package imports the Detection module, which imports `apps.checks`).
- [ ] **Step 4: Run the control app's tests.** Expected: PASS.
- [ ] **Step 5: Commit**

```bash
git add tm-control/backend
git commit   # subject: Add Status checks for the setup history and for a model's or a profile's name
```

---

### Task 10: The installer refreshes TM_VERSION, and the field rule's test

**Files:**
- Modify: `script/ansible/roles/tmsetup/tasks/node-red-tm_setup.yml`, `script/tests/test_tmsetup_tasks.py` (it covers the two token lines), `script/tests/test_node_red_flows.py`

- [ ] **Step 1: Write the failing tests.**
  - Beside the test for the two token lines: a `lineinfile` task named `TMSetup - Node-RED-TM Setup - Refresh TM_VERSION in node-red-tm.env`, with `regexp: '^TM_VERSION='`, `line: 'TM_VERSION={{ tmsetup_tm_version }}'`, `become: true`, `when: tmsetup_node_red_env_stat_register.stat.exists`, and `notify: Restart node-red-tm.service`. It has no `no_log`: the version isn't a secret.
  - `test_setup_fields_agree` in `test_node_red_flows.py`, the field rule across the three layers. Import the control app's constants (add `tm-control/backend` to `sys.path` as the file does for other imports from there, or read the two tuples from `snapshot.py` with `ast` if it doesn't): the validator accepts a body with exactly `DEVICE_FACTS` and `CAMERA_FACTS` and refuses one more key; the engine's insert parameters for it are `SETUP_DEVICE_COLUMNS` and `SETUP_CAMERA_COLUMNS` without `ended`; and those equal the tables' columns in `schema.sql`.
- [ ] **Step 2: Run to see them fail.** Expected: the task test fails (no such task); `test_setup_fields_agree` may already pass, which is fine: it guards later changes.
- [ ] **Step 3: Add the task** after the internal-token task.
- [ ] **Step 4: Run**

Run: `python -m pytest script/tests -q` and the Ansible syntax check under "Commands"
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add script
git commit   # subject: Refresh TM_VERSION in node-red-tm.env on every installer run
```

---

### Task 11: Docs, a device test, the bench, and the text for review (PR 1)

**Files:** the docs in the table under "Files" (PR 1's), `script/devpi/tests/test_dataflow.py`, `script/devpi/README.md`

- [ ] **Step 1: `docs/data-and-payloads/setup-history.md`** (new; in `mkdocs.yml`'s nav after "Watch log"). For a person who has the database and wants to compare counts across models or settings:
  - What it is for: the detection model decides what is counted, so a count means little without knowing which model, which versions, and which zones were in force.
  - How rows work: a row holds what was true from `started` until `ended`; the row in force has no `ended`; a new row starts only when something changed. Times are Unix milliseconds, where an event's times are seconds.
  - A table of each table's columns with type and meaning, in the page style of `watch-log.md`. For `model_kind`, the four values. For `model_sha256`: it identifies the model file whatever its name. For `model_id`: Frigate+'s id, empty for other models. For `lens_hfov`: not filled yet. For `zones`, `masks`, and `thresholds`: the JSON's shape, with one short example each, and that corners are fractions of the frame in the order Frigate stores them. For `profile`: Frigate's active profile when the camera defines it.
  - The view, with two examples that run as written: counts by label for each model (`GROUP BY setup_model_file, label`), and the events recorded while a camera's zones were as they are now.
  - What to know: a change made in Frigate's own screens is recorded within five minutes, so events in between are tied to the earlier row; a change made on the Detection or Cameras page is recorded at once, or when Frigate is back; events from before this was installed have no row; while Frigate is down nothing is recorded as changed.
  - What an operator typed and is kept: zone keys, a model's title and file name, a profile's key. The names Frigate shows for zones, masks, and cameras are not kept.
  - That the tables are in the database download and not in the JSON export.
- [ ] **Step 2: `docs/data-and-payloads/data-overview.md`**: the database's row names the setup history; "Tables" gains the two rows and the view, with the personal-data column saying what typed text they hold, and a link.
- [ ] **Step 3: `docs/use/device-health.md`**: the two new checks, what each state means, and what to do.
- [ ] **Step 4: `docs/ui/database.md`**: under "Download JSON", one sentence, as the watch log has.
- [ ] **Step 5: `CLAUDE.md`**: the tm-internal list gains `POST /tm-internal/setup` and the status body's `setup`; the control app's paragraph gains the snapshot thread (what it reads, when it posts, that `serve` starts it); "Overwrite semantics" gains `TM_VERSION`; the tmdb paragraph names the view and the README's note.
- [ ] **Step 6: Build the docs**

Run: `~/.venvs/tm-docs/bin/mkdocs build --strict`
Expected: it builds with no warning.

- [ ] **Step 7: The device test.** `test_the_setup_history_has_a_row_in_force(host, codedir, node_red_config)` in `test_dataflow.py` (every test there runs only on a unit marked `pii_free`). It reads only.
  - Skip, saying why, when `tm-control.service` or `node-red-tm.service` has been active for less than 2 minutes.
  - Exactly one `setup_device` row has no `ended`. Its `tm_version` equals the manifest's, its `schema_version` equals `PRAGMA user_version`, and its `frigate_version` equals what Frigate's `/api/version` answers.
  - For each `sensors.cameras` key whose Frigate camera is in Frigate's `/api/config`: exactly one open `setup_camera` row, with `detect_width` and `detect_height` equal to Frigate's, and `zones` a JSON list whose keys are that camera's zone keys.
  - `SELECT count(*) FROM events_with_setup` equals `SELECT count(*) FROM events`.
  - `GET /tm-internal/status` (the helper the status tests use) has `setup.complete` true and `received_at` within 400 seconds of the Pi's clock.
  - Assertion messages name columns and keys, never Frigate's name for a camera.

  `script/devpi/README.md`: the test joins the table of what the device tests check.

- [ ] **Step 8: Commit**

```bash
git add docs mkdocs.yml CLAUDE.md container/node-red-tm/schema/README.md script/devpi
git commit   # subject: Document the setup history and add its device test
```

- [ ] **Step 9: Run everything off-device once more** (pytest, the docs, `python3 -m json.tool container/node-red-tm/data/flows.json >/dev/null`, the Ansible syntax check). All pass.

- [ ] **Step 10: Bench run, logged with `tmdev check`**, on a bench unit marked `pii_free`, at the branch head, from a worktree. Nothing here turns on Frigate's detection, snapshots, or recording; say so in the check. Use the whole installer. Deploy to one unit at a time. Items:
  1. Before the deploy: record the schema version and the database's size, and the `TM_VERSION` line in `node-red-tm.env`.
  2. Deploy. The journal shows `applied 0007_setup_history.sql` and the version going to 7 with no new `DRIFT` line. `TM_VERSION` in `node-red-tm.env` is the branch's. Record how long the migration took.
  3. The first rows: within two minutes of both services being up there is one open device row and one open row per camera. Compare the device row with the Detection page (model, kind, SHA-256, labels) and the camera row with Frigate's `/api/config` (detect size, zones). Record how long the first snapshot took, which includes hashing the model file.
  4. Nothing changes, nothing is written: after 15 minutes there are still the same rows, and the Status page's **Setup history** is ok.
  5. A model change from the Detection page (Use on another model the unit has, then back): each change closes the device row and opens one, the camera rows stay, and the new row's `started` is after Frigate came back. Record the seconds between the click and `started`.
  6. A zone edited in Frigate's own editor (move one corner, save): within five minutes the camera's row closes and a new one opens whose `zones` differ only in that corner. Record the delay. Put the corner back.
  7. A mask and a profile, added in Frigate's config editor with a `friendly_name` that looks like an address, the profile then switched on: the row's `masks` has the shape and no name, `profile` has the key, the Status page's **Model and profile names** warns when the key looks like an address, and no journal line of `tm-control` or `node-red-tm` has the name. Then remove both. This is also the check that `/api/config` shows the settings in force while a profile is active: with a profile that changes `detect.fps` or a zone, the row shows the profile's value.
  8. Frigate stopped for 15 minutes: no row closes or opens, **Setup history** stays ok with the "isn't answering" line, and the same rows are in force after it is started again.
  9. `node-red-tm.service` restarted: no new row afterwards. `tm-control.service` restarted: no new row afterwards.
  10. The view: `SELECT count(*)` equals the events table's; if the unit has events, pick one from before the deploy (setup columns empty) and, with a synthetic `frigate/events` message on the device's broker, one after (the open rows' ids).
  11. `tmdev.py test <host>` passes, the new test included.
  12. The database download from the Data export page holds both tables and the view; the JSON export is as before.
  13. Cleanup, recorded in the check: the model, the zone, the masks, and the profiles are as before the run, Frigate is running, and its `/api/config` (sent with `X-Cache-Bypass: 1`) still shows detection off for the bench camera.

- [ ] **Step 11: The public plan copy.** Copy this plan to `design/plans/2026-11-23-setup-history.md`, and commit it last.

- [ ] **Step 12: Write the text, and stop.** For the maintainer to read before anything is pushed: the PR title and body from `.github/PULL_REQUEST_TEMPLATE.md`, against `dev`, with the bench check's id, that the migration only creates two tables, two indexes, and a view, the three delays recorded on the bench, and the template's "Docs" and "AI assistance" sections filled in. Under limits, say: a change made in Frigate's own screens is recorded up to five minutes late; `lens_hfov` is empty until a later change; a radar's setup isn't recorded; the rows aren't uploaded until the next PR; the Status warning for a title or a profile is the only place the name check shows.

---

## PR 2: the upload

Branch `feature/setup-history-upload/358` off `dev`, once two PRs are in it: PR 1 here, and the other stack's PR that gives deployment rows a field list in the upload gate (it adds the list `deployment` to `upload-lists.json`). Don't start before both have merged. Every step below that touches the gate, the list file, their tests, or the notice starts from what `dev` holds then and keeps all of it.

### Task 12: The engine hands rows to the upload

**Files:**
- Modify: `container/node-red-tm/data/flows.json`, `script/tests/test_node_red_flows.py`

**Interfaces:**
- Produces: "setup engine" output 6, wired to a `link out` "setup rows" in its group; on `thingsboard`, in a new group "setup" inside "thingsboard telemetry", a `link in` and the function "format setup telemetry", wired where "format watch telemetry" is wired (`8c521232f464d27a`). Output 6's message is `{payload: {ts: <ms>, device: [<row>...], cameras: [<row>...]}}`; the format node makes it `{payload: {ts, values: {setup: {device, cameras}}}}`.
- Produces: `SETUP_KEPT_ON_THE_UNIT`, a sent row, and `flow.setup_sent`, as under "Names used across tasks".

- [ ] **Step 1: Write the failing tests.** Each runs the engine with `config.thingsboard = {"enabled": True, "url": "https://tb.example.org"}` unless it says otherwise, and "current" means `flow.setup_sent = {"to": "https://tb.example.org", "at": <one second before the run>, "captured": <the sorted keys of the captured cameras>}`:
  - `test_setup_engine_sends_each_opened_and_closed_row`: current, and a device fact differs. Output 6 carries `ts` now, `device` with two rows (the closed one with `ended` now, the new one with `ended` null), and `cameras` empty. Each row's keys are `SETUP_DEVICE_COLUMNS` without `SETUP_KEPT_ON_THE_UNIT`, in order, with `labels_available` a list.
  - `test_setup_engine_sends_nothing_when_nothing_changed_and_nothing_is_due`: current, with an unchanged snapshot and with an incomplete one: no message on output 6, and `flow.setup_sent` as it was.
  - `test_setup_engine_sends_the_open_rows_when_they_are_due`, parametrized over `flow.setup_sent`: absent (Node-RED just started), `to` another URL, `at` 86 400 000 ms before now, `at` after now. An unchanged complete snapshot, with one open device row and open rows for `cam_a` and `cam_b`: output 6 carries those three rows with `ended` null, and `flow.setup_sent` is `{to: <the URL>, at: <now>}`.
  - `test_setup_engine_sends_each_row_once_when_due_and_changed`: `flow.setup_sent` absent and `cam_a`'s zones differ: `cameras` holds `cam_a`'s closed row, its new row, and `cam_b`'s open row; `device` holds the open row; no `id` appears twice.
  - `test_setup_engine_waits_for_a_complete_snapshot_to_send_the_open_rows`: `flow.setup_sent` absent and an incomplete snapshot, with an open row for `cam_gone`, which the config doesn't have: output 6 carries that one closed row and nothing else, and `flow.setup_sent` stays absent.
  - `test_setup_engine_sends_nothing_while_the_upload_is_off`, parametrized over `thingsboard`: `enabled` false, no block, `enabled` true with no `url`. A snapshot that changes a row gives no message on output 6 and leaves no `flow.setup_sent`, whatever it held. Then, with the upload on, the next unchanged complete snapshot sends every open row: turning sharing on is what sends them.
  - `test_setup_engine_never_sends_a_kept_name`: open and new rows with `model_title` `"12 Oak St bikes"`, `model_file` `"oak_st.tflite"`, and `profile` `"1420_oak_st"`: the JSON text of output 6's message has none of the three values and none of the three keys.
  - `test_format_setup_telemetry`: output 6's message becomes `{ts, values: {setup: {device, cameras}}}`.
  - The five outputs of PR 1's tests are unchanged.
- [ ] **Step 2: Run to see them fail.** Expected: FAIL (the engine has five outputs).
- [ ] **Step 3: Change the engine and add the nodes.** The engine's seventh rule, after the status record:
  1. `to` is `config.thingsboard.url` when `config.thingsboard.enabled === true` and the URL is text that isn't empty; otherwise there is none.
  2. With no `to`, `flow.setup_sent` is removed and output 6 carries nothing.
  3. The open rows are due when rule 3 let the snapshot through (complete, schema version known) and `flow.setup_sent` isn't a mapping with this `to`, or its `at` isn't a number, is 86 400 000 ms or more before now, or is after now (the clock stepped back), or its `captured` isn't the list of captured cameras now.
  4. When they are due, output 6 carries the rows closed in this run and every row open after it, kept or new, and `flow.setup_sent` becomes `{to, at: now, captured}`.
  5. Otherwise it carries the rows closed and opened in this run, and nothing when there are none.

  A list with no row is an empty list. A kept or closed row is sent from what the read gave, a new one from its insert's parameters; either way a JSON column's text is parsed, and text that can't be parsed is sent as null. The engine's opening comment names the sixth output and says the three names never leave on it. Nothing is logged.
- [ ] **Step 4: Run the flows tests.** Expected: PASS.
- [ ] **Step 5: Commit**

```bash
git add container/node-red-tm/data/flows.json script/tests/test_node_red_flows.py
git commit   # subject: Hand setup rows to the upload: each change, and the open rows after a start and daily
```

---

### Task 13: The gate and its lists

**Files:**
- Modify: `container/node-red-tm/data/flows.json` (node `ae3349867027d005`), `container/node-red-tm/data/upload-lists.json`, `container/node-red-tm/data/README.md`, `script/tests/test_node_red_flows.py`

**Interfaces:**
- Produces: `upload_lists.telemetry` gains `"setup"`; new lists, after the ones `dev` has, `setup_device` (`SETUP_DEVICE_COLUMNS` without `SETUP_KEPT_ON_THE_UNIT`) and `setup_camera` (`SETUP_CAMERA_COLUMNS` without it); the gate's `telemetrySetup(value)`.

- [ ] **Step 1: Write the failing tests,** beside the watch log's gate tests and in their shape:
  - A `setup` value passes with both lists of rows, each row cut to its list's fields; a field that isn't listed is left out and named once as `setup_device.<field>` or `setup_camera.<field>`, never with its value.
  - `test_gate_applies_the_zone_rule`: a camera row's `zones` keeps only the zones that are on; it is removed for a camera that isn't captured (no `enabled: true` under `sensors.cameras`) and when it isn't a list; each case is warned once as `upload:setup_zones`, never with a camera, a zone, or a value.
  - `test_gate_cuts_a_kept_name_that_reaches_it`: a device row that carries `model_title` and `model_file`, and a camera row that carries `profile`, leave without them, each named once and never quoted. The engine leaves them out already; the gate is the second check.
  - A key of `setup` other than `device` and `cameras` is left out and named once; a list with no row left is left out; a `setup` with nothing left is left out, and the item with it when it was the only value.
  - `test_gate_sends_nothing_without_readable_lists` gains two cases, lists with no `setup_device` and lists whose `setup_camera` holds a name that isn't text: the gate sends nothing at all, for any kind of message.
  - With the upload off, nothing passes.
  - `test_upload_lists_file`: the keys are `dev`'s, then `setup_device` and `setup_camera`; `telemetry` ends with `"setup"`; each new list equals its table's columns without `SETUP_KEPT_ON_THE_UNIT`.
  - `test_setup_fields_agree` (Task 10) gains the upload: each list equals its table's columns without `SETUP_KEPT_ON_THE_UNIT`, and the keys of a row on the engine's output 6 equal its list, so a column added later fails here until it is listed or kept.
  - `test_everything_uploaded_passes_the_gate` passes with the new format node.
- [ ] **Step 2: Run to see them fail.** Expected: FAIL (`setup` is left out as unlisted).
- [ ] **Step 3: Change the gate and the lists.** `telemetrySetup` follows `telemetryWatch`: the two keys are `device` and `cameras`, with the lists `setup_device` and `setup_camera`. The gate's list of required list names gains the two, and its opening comment names the setup rows. It also checks `zones` a second time, as it checks the three names: in a camera row it keeps only the zones whose `enabled` is `true`, and it removes `zones` when the row's camera isn't `enabled: true` under `sensors.cameras` in the config; either is warned once, never with a camera, a zone, or a value. Start from `dev`'s node, which by now also cuts deployment rows to a list, and keep it all.
- [ ] **Step 4: `container/node-red-tm/data/README.md`:** the count of lists the gate needs, the two new lists, and one sentence in the style of the event one: a new setup column goes on its list, or in `SETUP_KEPT_ON_THE_UNIT` in `script/tests/test_node_red_flows.py` when it stays on the device, and `test_setup_fields_agree` checks it.
- [ ] **Step 5: Run the flows tests.** Expected: PASS.
- [ ] **Step 6: Stop for the maintainer's look at the flows** (the review tool, as in Task 3), for Tasks 12 and 13 together.
- [ ] **Step 7: Commit**

```bash
git add container/node-red-tm/data script/tests/test_node_red_flows.py
git commit   # subject: Let the setup history through the upload gate, field by field
```

---

### Task 14: The notice and the example

**Files:**
- Modify: `tm-control/backend/tm_control/modules/sharing/NOTICE.md`, `tm-control/ui/src/modules/sharing/examples.ts` and any UI test that pins the example

The **Model and profile names** check keeps its words, "It is saved in the database.": a title, a file name, and a profile's key aren't sent.

- [ ] **Step 1: The example.** `SHARE_DATA_EXAMPLE` gains, after `watch`, a `setup` value with one device row and one camera row: made-up but plausible values, the fields of the two lists only (no `model_title`, `model_file`, or `profile`), one zone with four corners. The comment above it names the setup. Run the UI build and tests.
- [ ] **Step 2: The notice.** The maintainer agreed this wording on 2026-11-25. The first line stays `<!-- notice-version: 2026-11 -->`. Under "Share data", after the sentence that ends "from a sensor that was off.", add:

  > It also sends the device's setup whenever it changes: which detection model is running (its fingerprint, type, and size, never its name), the software versions, and each camera's detection settings, including the shape of every mask and of every zone that is on, and the names you typed for those zones.

  And the paragraph that begins "It doesn't send" becomes:

  > It doesn't send images, video, plate reads, the rest of your device's settings, your Wi-Fi details, or the descriptions you give places.

  If the "Share data" section on `dev` holds anything but the text PR 1 was built on plus one sentence about how each sensor is mounted, stop and show the maintainer the paragraph before and after.
- [ ] **Step 3: Run** the control app's tests and the UI build and tests. Expected: PASS.
- [ ] **Step 4: Commit**

```bash
git add tm-control
git commit   # subject: Say in the sharing notice and its example that the setup history is sent
```

---

### Task 15: Docs, the bench, and the text for review (PR 2)

- [ ] **Step 1: Docs.**
  - `docs/data-and-payloads/integrations.md`: the ThingsBoard list gains the setup history: one `setup` value when a row opens or closes, and the open rows again after Node-RED starts, after the upload is turned on or its server changes, and once a day, so a server keys rows on `id`; the row fields are on the same list file; a model's title and file name and a profile's key are never sent.
  - `docs/use/sharing.md`: the **Share data** row's "What it sends" names the setup history, with a link; its "What it doesn't send" says "the rest of the device's settings" and names a model's title and file name and a profile's name.
  - `docs/data-and-payloads/setup-history.md`: what is sent and when, in place of whatever says the rows stay on the device. "What an operator typed" says which names leave: the key of a zone that is on, on a camera that is captured, is sent inside `zones`; a zone that is off, every zone of a camera that isn't captured, a model's title, its file name, and a profile's key stay on the device, in the database and its download.
  - `docs/data-and-payloads/data-overview.md`: the two tables' rows, if they say anything about sharing.
  - `CLAUDE.md`: the `thingsboard` paragraph (the `setup` telemetry, the two lists, `SETUP_KEPT_ON_THE_UNIT`, `test_setup_fields_agree`) and the engine's sixth output with `flow.setup_sent`.
  - Build with `mkdocs build --strict`.
- [ ] **Step 2: Commit**

```bash
git add docs CLAUDE.md
git commit   # subject: Document the setup history's upload
```

- [ ] **Step 3: Run everything off-device once more,** the UI included.
- [ ] **Step 4: Bench run, logged with `tmdev check`,** on a bench unit marked `pii_free`, whole installer, one unit at a time. Nothing here turns on Frigate's detection, snapshots, or recording. Items 4 to 7 are the maintainer's, with his token and a ThingsBoard server:
  1. Deploy onto a unit that runs PR 1: no migration runs, and no setup row changes because of the deploy except the device row when `tm_commit` changed.
  2. The Sharing page's **See an example** shows the `setup` value, with no title, file name, or profile, and the notice reads as agreed.
  3. With sharing off, a model change writes rows and Node-RED's log shows no upload try.
  4. Sharing turned on: within six minutes one `setup` telemetry message arrives that holds every open row, the device's and each camera's. No row on the server has `model_title`, `model_file`, or `profile`.
  5. A model change sends one `setup` message whose `device` list has the closed and the new row, and no camera row unless the model also changes the camera's tracked labels.
  6. `node-red-tm.service` restarted: after the next complete snapshot the open rows arrive again, with the ids the server already has.
  7. Node-RED's log has no "left out" or "didn't load" warning. Afterwards the unit is left not sharing.
  8. `tmdev.py test <host>` passes.
  9. Cleanup, recorded in the check: the model is as before, and Frigate's `/api/config` (sent with `X-Cache-Bypass: 1`) still shows detection off for the bench camera.

  The daily send isn't benched; Task 12's tests cover it.
- [ ] **Step 5: The public plan copy.** Bring `design/plans/2026-11-23-setup-history.md` in line with this plan, and commit it last.
- [ ] **Step 6: Write the text, and stop.** The PR title and body against `dev`, with the bench check's id and the template's sections filled in. Under limits, say:
  - A row that closed while sharing was off, or while the server couldn't be reached, never reaches the server; it learns the setup from the open rows, and a close it missed shows as the next row's start.
  - The server receives a row more than once and has to key on `id`.
  - A model's title, its file name, and a profile's key aren't sent, so a server tells models apart by fingerprint and id, and sees a profile only as settings that changed.
  - The gate doesn't yet hold a new kind of data back until the notice is read again.
