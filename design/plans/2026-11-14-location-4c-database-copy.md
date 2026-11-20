# Location 4C: the database copy with exact locations

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An admin can download a copy of the database that includes the exact location of each place the device has been at, joined to the deployment records by a view, for analysis and mapping, while the database on the device keeps only rounded locations.

**Architecture:**
- The control app owns the exact locations and Node-RED owns the database, and neither opens the other's file. So the control app posts the list of places (id, exact latitude and longitude) to Node-RED over the loopback, under a random ticket, and answers the page with a `/storefiles` address that names the ticket.
- The download is the existing database download with one more step. Node-RED makes the `VACUUM INTO` copy it already makes for every database download, a new function node opens **that copy only** and adds a table of the places' exact locations and a view that joins it to `deployment`, and the existing `tar` step streams it. The copy's `deployment` table stays as the database has it, so `deployment.lat` and `lon` mean the rounded location everywhere: in the database, in what is uploaded, and in this copy. The copy is removed when the download ends, as today.
- The list lives in Node-RED's memory for ten minutes and is never written to disk, logged, or put on a message. The live `tmdb.sqlite` is never opened for this.
- The Location page gets a second button beside "Export exact locations", with a confirmation that says what the file reveals.

**Tech Stack:** Node-RED 5 flows (eight new nodes, four changed), Node's built-in `node:sqlite` in the Node-RED container (through `settings.js`; no new npm module, no image change), Python 3.11 (FastAPI, pydantic 2; no new dependency), Vue 3 + Vuetify 3 + TypeScript (Vitest; no new npm dependency), Material for MkDocs, the dev-Pi tooling (`script/devpi/tmdev.py`).

**Spec:** the location and survey-id design (not yet published; the public record is the privacy design, `design/specs/2026-10-26-location-privacy-design.md`, from PR 260, and [issue 325](https://github.com/glossyio/traffic-monitor/issues/325)), section 10, the last bullet of section 12, and open question 3. The maintainer's decisions of 2026-11-13 replace parts of section 10; they are listed in "Decisions" below. Read the design with this plan. Where this plan goes beyond the design, say so in the PR rather than picking silently.

**Status:** written 2026-11-14 against `feature/sharing-page/314` at `4eb6ed6`, the branch of [PR 321](https://github.com/glossyio/traffic-monitor/pull/321) (plan 4A, open, not merged), because the button sits in the "Exact locations" section that PR adds. Branch: `feature/exact-database-copy/325`, off that branch; this file was added in the PR that implements it. [Issue 325](https://github.com/glossyio/traffic-monitor/issues/325) tracks this work. The PR is opened against that branch and retargeted to `dev` when PR 321 merges. If PR 321 has merged when the build starts, branch off `dev` instead. Other open PRs ([320](https://github.com/glossyio/traffic-monitor/pull/320), [315](https://github.com/glossyio/traffic-monitor/pull/315), [318](https://github.com/glossyio/traffic-monitor/pull/318)) touch none of this plan's code; expect only `CLAUDE.md` and docs merge conflicts.

**Size:** about 150 lines of flow JavaScript in four new function nodes and two changed ones, 60 lines of Python, 60 lines of Vue, and roughly 500 lines of tests. To maintain afterwards: one more `/tm-internal/` endpoint in the contract list, and one function node that depends on `node:sqlite` (checked by a device test, so a Node-RED image update that breaks it is caught on the bench).

**Decisions** (the maintainer's of 2026-11-13 and 2026-11-14 are marked; the rest are calls, open to change):
1. **Node-RED rewrites the copy (maintainer).** The control app posts the list; Node-RED applies it to the throwaway copy. The control app never opens a database file of Node-RED's, and its service gets no new writable path. This answers the design's open question 3.
2. **The live database never gets exact coordinates (maintainer).** The function that writes the copy opens one file, the copy in its own snapshot folder, on a connection of its own. It refuses the file `TM_DATABASE_PATH_TMDB` names. No statement that carries the list runs on the flows' shared database connection.
3. **The download uses `/storefiles` (maintainer),** not a stream from the control app's API as the design had it. It keeps the admin-only check, the 30-minute read timeout, the free-space check, the Cancel button, and the one-time links for Android's sign-in window.
4. **The button goes beside "Export exact locations" (maintainer),** on the Location page.
5. **A ticket, good for ten minutes, not single-use.** The control app makes a random ticket (32 hex characters) for each request. Node-RED keeps the list under it for 600 seconds, the life of a download link, and any request for that ticket in that time gets the copy. It can't be single-use: Android's sign-in window fetches a download twice (once itself, once through the phone's downloader), and the second fetch is the one that saves. Every request still passes nginx's admin check.
6. **The list is claimed when the request arrives.** A large database takes minutes to copy, so the request takes its list at the start and the function that writes it reads that copy of the list, not the ticket. A ticket that runs out during the copy doesn't spoil a download that already started.
7. **A lookup table and a view; `deployment` is not changed (maintainer, 2026-11-14).** The copy gains a table `survey_exact_location (survey_id, lat, lon)`, one row per place, and a view `deployment_exact` that is `deployment` with `exact_lat` and `exact_lon` beside it. This replaces the design's rewrite of `deployment.lat` and `lon` in place. It is the shape the upload already has, where the exact point is the separate `exact_location` attribute `{survey_id, lat, lon}`, and it is the "Export exact locations" list inside the file. A reader or a pipeline that uses `deployment.lat` and `lon` gets the rounded location from every file, so an exact point can't be picked up by mistake.
   - The copy holds the device's whole exact history, which the maintainer asked for on 2026-11-14: every place it has been at, past ones included, and through the view each deployment's sensor, start, and end beside its place's exact point. A place has one point, so a corrected place appears with its corrected point.
   - Only places the device has been at: the control app sends the places marked in use or used that have coordinates, and Node-RED inserts a place only if the copy's `deployment` table names it. A planned place is never in the copy.
   - A place the control app no longer knows (deleted, or never imported), a place with no coordinates, and rows from before any place was recorded have no row in the table, so the view gives them empty `exact_lat` and `exact_lon`.
   - **The record of corrections stays on the device (maintainer, 2026-11-14).** Putting it in the copy was considered and left out. A correction rewrites the record and keeps its ids, so the latest values for a place id and a deployment id are the truth, and a map or an analysis needs nothing more. The old value of a location correction is an exact coordinate of somewhere the device never was, which a correction exists to remove, and someone who holds an earlier copy already has the old value and can compare by id. If the time of a correction is ever wanted in the copy, it can be added without the values.
   - The two `CREATE` statements run only on the throwaway copy. They are the one exception to "the flows define no schema", which is about `tmdb.sqlite`.
8. **The file names say what it is.** The archive is `<hostname>_<time>_tmdb-exact-locations.tar.gz` and holds `tmdb-exact-locations.sqlite`, so nobody mistakes it for the shareable database.
9. **`node:sqlite`, through `settings.js`.** The function node needs a database connection of its own. The Node-RED image runs Node 24, which has SQLite built in, so `settings.js` puts `require('node:sqlite')` in `functionGlobalContext` beside `fs` and `path`. See "Checked while planning" for why not the function node's own module list, and for the fallback.
10. **Nothing to add means no copy.** When no place the device has been at (in use or used) has coordinates, the control app answers 409 and the button is disabled with the reason. The Dashboard's own database download is the same file.
11. **No new consent record.** This is a local download by an admin, like "Export exact locations": a confirmation that says what the file reveals, and an audit row with the number of places. Nothing is sent anywhere.
12. **What stays on the card, and for how long.** The copy with exact locations exists under `db/snapshot/` from the end of the copy step until the download ends. If power is lost meanwhile, it stays there until Node-RED next starts, which removes everything under `db/snapshot/` before any download can begin (existing behaviour). The docs' developer page says so.

**Checked while planning** (2026-11-14, in a throwaway `nodered/node-red:5.0.8` container; nothing here needs repeating):
- The image runs Node 24.21. `require('node:sqlite')` works there and prints no warning. CI's Node (22.23.4, from `tmsetup_node_image`) has it too and prints an `ExperimentalWarning` on stderr.
- A function node can't load it through its own module list: `libs: [{var: 'sqlite', module: 'node:sqlite'}]` is refused at start with `node:sqlite [install_not_allowed]`, because Node-RED strips `node:` and looks for a built-in named `sqlite`. `functionGlobalContext` is the way in.
- A `VACUUM INTO` copy of a WAL database is in `delete` journal mode. Opening it with `new DatabaseSync(file)`, running `BEGIN IMMEDIATE`, one prepared statement per place with `$lat`, `$lon`, `$survey_id`, `COMMIT`, and `close()` leaves one file, passes `PRAGMA integrity_check`, and leaves the source untouched. `DatabaseSync` creates a missing file, so the function checks the file exists first.
- The table, the guarded `INSERT`, and the view of Task 2 were run with Python's `sqlite3` against `schema.sql`: a listed place the `deployment` table doesn't name gets no row, and the view returns `deployment`'s columns followed by `exact_lat` and `exact_lon`, empty where there is no row.
- Fallback, if the bench shows a problem with `node:sqlite`: the `sqlite3` npm module the sqlite nodes already use. A file in `/data` can `require('sqlite3')` (the image sets `NODE_PATH=/usr/src/node-red/node_modules:/data/node_modules`), and the same rewrite works with it; it is asynchronous and can't be run in the off-device tests.

**Where the code stands that this plan touches:**
- `flows.json`, `ui-database` tab, group "Dashboard 2 - Compress & Download 1 or More Files" (`c3e71a6b79637b6f`): `GET /storefiles` (`d6503c258431b152`) → "Validate filenames, setup tar" (`2398aa8b9ca25816`) → "Test for error" (`04630be97890045c`) → "copy database first?" (`a7ea83d9c70f2981`, sets `msg.topic = "VACUUM INTO '<msg.snapshot>/tmdb.sqlite'"`) → sqlite node "copy database for download" (`6b71ab080a582bd2`) → "stop if cancelled" (`5ce2b1e89783a67e`) → exec "zip files" (`30d1dd9d6d580fa4`, `tar czvf - --checkpoint=1000` + `msg.tarArgs`) → "download chunks" / "handle end of file or error" (`41deab2c99a209b8`, removes `msg.snapshot`). "catch database copy" (`d4485dfc776d50fc`, scope: the two copy nodes) → "database copy failed" (`3a226e9922929100`). For `files=/db/tmdb.sqlite`, validate sets `msg.snapshot = '/db/snapshot/<time>-<random>'`, `msg.tarArgs = ' -C ' + msg.snapshot + ' -- tmdb.sqlite'`, and `msg.downloadName`. Error answers go to the `http response` `8a12d83e700bcaa6` **and** to the Dashboard notification `9297900926075b54` and the link out `8f8958d08aa3a85d`; Dashboard nodes send what they get to every open Dashboard, viewers' included.
- `flows.json`, `init-config` tab, group "tm-control surveys" (`3da2c0e89c06736d`): six `/tm-internal/` endpoints, each `http in` → its own "tm-internal: check token" function (same code, two outputs, 401) → a validator (two outputs, 400) → the work → `http response`. `script/tests/test_node_red_flows.py` pins the list (`TM_INTERNAL_PATHS`, `TM_INTERNAL_METHODS`, `VALIDATORS`), the tab, the group, and that a refused request reaches nothing but an `http response`.
- `container/node-red-tm/data/settings.js`: `functionGlobalContext: { fs, path }`, `contextStorage` memory only. `script/tests/test_node_red_settings.py` loads the file under `node` (`run_node`).
- `script/tests/test_node_red_flows.py`: `run_functions(steps, env, context, flow)` runs function bodies in a `vm` sandbox whose `global.get` reads a JSON object, so `global.get("fs")` is undefined there; the existing download tests only check text. `named`, `_download_nodes`, `reachable`, `needs_node`. Tests that pin nodes this plan changes: `test_database_download_tars_a_copy` (the catch scope), `test_cancel_stops_a_database_download_during_the_copy` (`stop["wires"][0]`), `test_download_names_cannot_become_tar_options`, `test_every_tm_internal_endpoint_checks_the_token_first`, `test_refused_requests_reach_no_sql`, `test_survey_endpoints_sit_with_the_status_endpoint`.
- `tm-control/backend/tm_control/adapters/nodered.py`: `NodeRed._call(method, path, query, body)`, `NodeRedError(code, status)` (never carries a body). `fake.py`: `FakeNodeRed(NodeRed)`. `modules/location/router.py`: `export_places` (`GET /surveys/export`, the pattern to follow: `reconcile.ensure`, `Places(...).list()`, `Audit.record`), `_nodered_error`. `core/auth.py`: `DownloadGrants.issue(user, address, files, now) -> token`, `TTL = 600.0`, `DOWNLOAD_PATH`, `DOWNLOAD_TOKEN`. `modules/auth/router.py`: `download_link` builds `f"{DOWNLOAD_PATH}?files={quote(files, safe='/,')}&{DOWNLOAD_TOKEN}={token}"`; verify passes that address once without a session, and with a session it ignores the token. `modules/auth/deps.py`: `client_ip`, `require_admin`.
- UI: `src/modules/location/LocationPage.vue` (the "Exact locations" section with `confirmExport`, `exporting`, `exportError`, `exportExact`; the Precision paragraph that ends "A later update will let you export a copy of the database with each place's exact location, for analysis and mapping."), `src/components/download.ts` (`saveBlob`), `src/components/ConfirmDialog.vue`. Tests: `tests/location-page.spec.ts` (the `describe` around `EXPORT`, and the Precision text near line 319).
- Device tests: `script/devpi/tests/test_web.py` (`TM_INTERNAL_WRITES`, `test_tm_internal_writes_need_the_token_on_the_pi`, `test_data_export_errors_from_this_machine`, `test_data_export_tars_a_database_copy`, `test_surveys_needs_an_admin`, `test_in_use_place_matches_config_yml` for the `pii_free`-only pattern).

## Global Constraints

- An exact coordinate reaches Node-RED only in the body of `POST /tm-internal/database/exact-copy`, and from there only the table `survey_exact_location` of a copy under `db/snapshot/`. The copy's `deployment` table is never changed. An exact coordinate is never written to `tmdb.sqlite`, never put on a `msg` (not as a property, not in `msg.payload`, not in an error), never passed to `node.warn`, `node.error`, `node.log`, or a status, and never kept past its ticket's ten minutes or its own download.
- The function that writes the copy is the only node that uses `global.get("sqlite")`, and the only one in the flows with a `CREATE` statement. No sqlite node on the flows' database connection (`2f60c1ab30a6fc8f`) gets a statement that carries the list, and `tmdb.sqlite` never has the table or the view.
- The control app's log lines, audit rows, and error messages for this feature hold counts and names only: no coordinate, no ticket, no link.
- No exact coordinate in any fixture, commit, PR text, or screenshot other than the example `45.52252, -122.69120` and the fixtures' `45.0, -122.0`. Survey ids in fixtures are `3f9a1c2e-si`, `aaaaaaaa-si`, and `bbbbbbbb-si`.
- The control app never opens `tmdb.sqlite` or a copy of it; Node-RED never opens `state.sqlite`.
- `flows.json` is edited programmatically and re-serialised with `json.dumps(flows, indent=4, ensure_ascii=False)` and no trailing newline; existing nodes keep their ids; new nodes get fresh 16-hex ids and sit in their group's `nodes` list; the MQTT nodes' ids stay.
- The Dashboard's own "Download Database" and the JSON exports behave exactly as before.
- Every commit ends with the trailer block from the repo's `CLAUDE.md` (Assisted-by / AI-Model / AI-Effort / AI-Role); never `Co-Authored-By`. Docs follow "Writing docs" in `docs/development/contributing.md`; `mkdocs build --strict` passes. Nothing public names a device or a bench site.
- On a dev Pi: Frigate's detection, snapshots, and recording stay off; no item in this plan needs them. The database and its copies are read only on a `pii_free` unit, and only as counts.
- Off-device checks before each commit, from the repo root in the dev venv: `python -m pytest container/node-red-tm/schema/tests script/tests tm-control/backend/tests`; for UI tasks also `cd tm-control/ui && npm test && npm run build`; for docs tasks `~/.venvs/tm-docs/bin/mkdocs build --strict`.

## Review Focus

1. Android's sign-in window fetches the address twice, and the second fetch saves the file: the same ticket must serve both, each with its own copy. Test in Task 2 (`test_a_ticket_serves_a_second_request_in_its_time`); bench item 8.
2. The list on a message would reach the Dashboard's notification and every open Dashboard, viewers' included: no message in the download flow carries a coordinate, on the success path or any error path. Tests in Task 2 (`test_no_download_message_carries_a_coordinate`, parametrised over the claim, the refusal, and the writer's output).
3. A database large enough that the copy outlasts the ticket: the download that already started still gets its exact locations. Test in Task 2 (`test_a_claimed_list_outlives_its_ticket`).
4. The rewrite fails (no `sqlite` in the settings, a copy without a `deployment` table, a full disk): nothing is served, the copy is removed, and no rounded file goes out under the exact name. Tests in Task 2 (`test_a_failed_rewrite_is_caught_and_removes_the_copy`, `test_exact_writer_fails_closed_without_sqlite`).
5. Places at the edges of the list: a place deleted from the Location page, rows from before any place was recorded, and a place with no coordinates have no row in the table and an empty pair in the view; a planned place the device was never at is not in the copy at all; and a device with no located place it has been at gets a 409 and a disabled button, not an archive that only looks exact. Tests in Task 2 (`test_exact_writer_adds_the_lookup_table_and_leaves_deployment_alone`, `test_exact_writer_leaves_out_a_place_the_database_never_names`), Task 3 (`test_database_copy_leaves_out_planned_places`, `test_database_copy_needs_a_located_place`), and Task 4.

---

### Task 1: Flows: the list endpoint

**Files:**
- Modify: `container/node-red-tm/data/flows.json` (seven nodes in the group `3da2c0e89c06736d` on `init-config`)
- Modify: `script/tests/test_node_red_flows.py` (`HARNESS`, `TM_INTERNAL_PATHS`, `TM_INTERNAL_METHODS`, `VALIDATORS`, new tests)

**Interfaces:**
- Produces, `POST /tm-internal/database/exact-copy`, token-checked like the other six. Body `{"ticket": "<32 lowercase hex>", "places": [{"survey_id": "<8 hex>-si", "lat": <number>, "lon": <number>}, ...]}`. Answers 204 with no body; 401 `{"error": "unauthorized"}`; 400 `{"error": "bad_request", "detail": "ticket" | "places"}`.
- Produces, nodes: `http in` → function "tm-internal: check token" (the same `func` as the other six, two outputs, an `http response` 401 on the second) → function "tm-internal: validate exact copy" (two outputs, an `http response` 400 on the second) → function "tm-internal: keep exact copy list" → `http response` (status from `msg.statusCode`).
- Produces, the validator's rules: `ticket` is a string matching `^[0-9a-f]{32}$`; `places` is an array of 1 to 10000 objects; in each, `survey_id` is a string matching `^[0-9a-f]{8}-si$`, `lat` a finite number from -90 to 90, `lon` a finite number from -180 to 180 (numbers, not strings, as "tm-internal: validate location correction" checks them); no `survey_id` twice. It passes on `msg.exactCopy = {ticket, places}` holding only those three keys per place, and removes `msg.payload`.
- Produces, global context `exact_copies`: `{ "<ticket>": { "places": [...], "expires": <ms since the epoch> } }`. "keep exact copy list" first drops every entry whose `expires` has passed, then, while four or more remain, drops the one that expires soonest, then stores the new entry with `expires = Date.now() + 600000`, sets a `setTimeout` for 600000 ms that deletes that ticket if its `expires` is unchanged, deletes `msg.exactCopy`, and answers 204 with an empty payload. A comment names `DownloadGrants.TTL` as the number the 600 seconds match.
- Produces, harness: after writing its JSON, `HARNESS` ends the process itself (`process.stdout.write(output, () => process.exit(0))`), so a function's pending timer can't hold a test for ten minutes.

- [ ] **Step 1: Write the failing tests**

In `script/tests/test_node_red_flows.py`: add the path to `TM_INTERNAL_PATHS`, `"post"` to `TM_INTERNAL_METHODS`, and `"tm-internal: validate exact copy"` to `VALIDATORS` (the three convention tests then cover the token check, the tab, the group, and the 400 path). New tests, with `TICKET = "0123456789abcdef0123456789abcdef"` and `PLACE = {"survey_id": "3f9a1c2e-si", "lat": 45.52252, "lon": -122.6912}`:

```python
@needs_node
@pytest.mark.parametrize("body, detail", [
    ({"ticket": TICKET, "places": [PLACE]}, None),
    ({"ticket": TICKET.upper(), "places": [PLACE]}, "ticket"),
    ({"ticket": TICKET[:-1], "places": [PLACE]}, "ticket"),
    ({"places": [PLACE]}, "ticket"),
    ({"ticket": TICKET, "places": []}, "places"),
    ({"ticket": TICKET, "places": "3f9a1c2e-si"}, "places"),
    ({"ticket": TICKET, "places": [PLACE, PLACE]}, "places"),
    ({"ticket": TICKET, "places": [{**PLACE, "lat": "45.52252"}]}, "places"),
    ({"ticket": TICKET, "places": [{**PLACE, "lon": None}]}, "places"),
    ({"ticket": TICKET, "places": [{**PLACE, "lat": 90.5}]}, "places"),
    ({"ticket": TICKET, "places": [{**PLACE, "survey_id": "x' OR 1=1"}]}, "places"),
    ("ticket=x", "ticket"),
])
def test_exact_copy_list_is_validated(body, detail): ...
    # ok: output 1 has msg.exactCopy == {"ticket": TICKET, "places": [PLACE]} and no payload
    # refused: output 2 has statusCode 400 and payload {"error": "bad_request", "detail": detail}; no coordinate in it

@needs_node
def test_exact_copy_list_keeps_only_three_keys_per_place(): ...   # {**PLACE, "description": "x"} → the kept place == PLACE

@needs_node
def test_keep_stores_the_list_for_ten_minutes_and_answers_204(): ...
    # global exact_copies[TICKET]["places"] == [PLACE]; expires within 600000 ± 5000 ms of now;
    # the returned msg has statusCode 204, payload "", no exactCopy, and "45.52252" not in json.dumps(msg)

@needs_node
def test_keep_drops_expired_lists_and_keeps_at_most_four(): ...
    # context: one expired entry and four current ones → afterwards the expired one and the soonest-expiring
    # current one are gone, and four entries remain, the new one among them

def test_keep_sets_a_timer_that_matches_the_download_links_life(): ...
    # "setTimeout(" in func and "600000" in func and "DownloadGrants.TTL" in func
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest script/tests/test_node_red_flows.py -k "exact_copy or keep_ or tm_internal or refused or survey_endpoints" -v`
Expected: FAIL (the endpoint isn't in the flows).

- [ ] **Step 3: Add the seven nodes and the harness line**

With a short script, as the constraint says. The token check's `func` is copied from an existing check node, not retyped. Each function starts with a comment that says what it does and that nothing is logged or echoed, like "tm-internal: validate location correction".

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest script/tests container/node-red-tm/schema/tests -v` and `python3 -m json.tool container/node-red-tm/data/flows.json >/dev/null`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add container/node-red-tm/data/flows.json script/tests/test_node_red_flows.py
git commit -m "Let the control app hand Node-RED the exact locations for one database copy"
```

### Task 2: Flows: add the exact locations to the download's copy

**Files:**
- Modify: `container/node-red-tm/data/settings.js` (`functionGlobalContext`)
- Modify: `container/node-red-tm/data/flows.json` ("Validate filenames, setup tar", "stop if cancelled", "database copy failed", "catch database copy"; one new function node in the group `c3e71a6b79637b6f`)
- Modify: `script/tests/test_node_red_flows.py`, `script/tests/test_node_red_settings.py`, `script/tests/required_tools.py`

**Interfaces:**
- Consumes: global `exact_copies` (Task 1).
- Produces, `settings.js`: `functionGlobalContext.sqlite` is `require('node:sqlite')`, or `null` when this Node has none (a `try`/`catch`, so Node-RED still starts), with a comment: for the one function that writes a database copy, never `tmdb.sqlite`.
- Produces, "Validate filenames, setup tar": a request whose `files` is exactly one name matching `^tmdb-exact-[0-9a-f]{32}$` is an exact copy; it never reaches the file checks. The function drops expired entries from `exact_copies`, then:
  - no entry for the ticket → `msg.statusCode = 404`, `msg.payload = "This download link has expired. Start the download again from the Location page."`, and a `node.error` without the ticket;
  - else `msg.snapshot` as for the database, `msg.exactCopy = true`, `msg.tarArgs = ' -C ' + msg.snapshot + ' -- tmdb-exact-locations.sqlite'`, `msg.downloadName = prefix + 'tmdb-exact-locations.tar.gz'`, and the entry's `places` stored in flow context `exactCopyPlaces[msg.snapshot]`. The entry stays in `exact_copies` until it expires (decision 5).
- Produces, function "write exact locations into the copy" (one output), wired between "stop if cancelled" output 1 and "zip files". Without `msg.exactCopy` it returns `msg` untouched. Otherwise it takes and deletes `exactCopyPlaces[msg.snapshot]`, and throws an `Error` with a fixed text (`"exact copy: ..."`) when: `global.get("sqlite")` is missing; there is no list; the folder that holds `msg.snapshot` isn't named `snapshot`; `<msg.snapshot>/tmdb.sqlite` doesn't exist; or its real path is the real path of `env.get("TM_DATABASE_PATH_TMDB")`. Then:

  ```js
  const db = new sqlite.DatabaseSync(file);
  try {
      db.exec("BEGIN IMMEDIATE");
      db.exec("CREATE TABLE survey_exact_location (survey_id TEXT PRIMARY KEY, lat REAL NOT NULL, lon REAL NOT NULL)");
      // Only a place the copy's deployment table names: a place the device was never at stays out of the file
      const insert = db.prepare(
          "INSERT INTO survey_exact_location (survey_id, lat, lon) SELECT $survey_id, $lat, $lon " +
          "WHERE EXISTS (SELECT 1 FROM deployment WHERE survey_id = $survey_id)");
      for (const place of places) {
          insert.run({ $survey_id: place.survey_id, $lat: place.lat, $lon: place.lon });
      }
      db.exec("CREATE VIEW deployment_exact AS SELECT d.*, s.lat AS exact_lat, s.lon AS exact_lon " +
          "FROM deployment d LEFT JOIN survey_exact_location s USING (survey_id)");
      db.exec("COMMIT");
  } finally {
      db.close();
  }
  fs.renameSync(file, path.join(msg.snapshot, "tmdb-exact-locations.sqlite"));
  return msg;
  ```

  The `deployment` table is read, never written. A thrown error reaches "catch database copy", whose scope gains this node, so "database copy failed" removes the folder and answers 500.
- Produces, "stop if cancelled" and "database copy failed": each also deletes `exactCopyPlaces[msg.snapshot]` when it removes the copy.
- Produces, harness: `run_functions(..., modules=())`. For each name in `modules` (`"fs"`, `"path"`, `"sqlite"`), the harness's `global.get(name)` answers Node's module (`node:sqlite` for `"sqlite"`), as `functionGlobalContext` does on the device, and the name is left out of the global context it prints. A step whose function throws is recorded the way Node-RED treats it, instead of ending the run: its result is `null` and its log gains `["error", <the error's message>, true]`. `required_tools.py` gains a probe for a `node` that has `node:sqlite` (22.13 or later), and a marker `needs_node_sqlite` built on it.

- [ ] **Step 1: Write the failing tests**

`test_node_red_settings.py`: `test_function_nodes_get_sqlite_for_the_database_copy` (`Object.keys(s.functionGlobalContext).sort()` is `["fs", "path", "sqlite"]`, and `typeof s.functionGlobalContext.sqlite.DatabaseSync === "function"`).

`test_node_red_flows.py`. A fixture `exact_copy_files(tmp_path)` builds, with Python's `sqlite3` and `container/node-red-tm/schema/schema.sql`, a live database `tmp/tmdb.sqlite` and its copy `tmp/snapshot/x1/tmdb.sqlite` with these `deployment` rows:

| id | survey_id | lat | lon | location_precision |
|---|---|---|---|---|
| `1-00000001-d` | `3f9a1c2e-si` | 45.5 | -122.7 | 1 |
| `1-00000002-d` | `3f9a1c2e-si` | NULL | NULL | NULL |
| `1-00000003-d` | `aaaaaaaa-si` | 45.0 | -122.0 | 1 |
| `1-00000004-d` | NULL | 45.0 | -122.0 | 2 |

The writer runs with `modules=("fs", "path", "sqlite")`, `env={"TM_DATABASE_PATH_TMDB": <live>}`, `flow={"exactCopyPlaces": {<snapshot>: [PLACE]}}`, and `msg = {"snapshot": <snapshot>, "exactCopy": True}`.

```python
@needs_node_sqlite
def test_exact_writer_adds_the_lookup_table_and_leaves_deployment_alone(exact_copy_files): ...
    # the copy is now tmp/snapshot/x1/tmdb-exact-locations.sqlite and tmdb.sqlite is gone from that folder;
    # SELECT * FROM deployment ORDER BY id is the same four rows as before the step, precision included;
    # SELECT * FROM survey_exact_location == [("3f9a1c2e-si", 45.52252, -122.6912)];
    # SELECT id, exact_lat, exact_lon FROM deployment_exact ORDER BY id gives the pair for rows 1 and 2 and
    # (None, None) for rows 3 and 4; the view's columns are deployment's, then exact_lat, exact_lon;
    # PRAGMA integrity_check is "ok"; the folder holds exactly one file

@needs_node_sqlite
def test_exact_writer_leaves_out_a_place_the_database_never_names(exact_copy_files): ...
    # the list also holds {"survey_id": "bbbbbbbb-si", "lat": 45.0, "lon": -122.0} → survey_exact_location has one row

@needs_node_sqlite
def test_exact_writer_never_touches_the_live_database(exact_copy_files): ...
    # sha256 of tmp/tmdb.sqlite is the same before and after

@needs_node_sqlite
def test_exact_writer_refuses_the_live_database_and_a_folder_outside_snapshot(tmp_path): ...
    # (a) TM_DATABASE_PATH_TMDB names the very file under snapshot/x1 → the step logs an error, returns nothing,
    #     and the file has no survey_exact_location table; (b) msg.snapshot = tmp/elsewhere/x1 → the same

@needs_node_sqlite
def test_a_failed_rewrite_is_caught_and_removes_the_copy(tmp_path): ...
    # a copy with no deployment table → the writer throws, the file is not renamed, and it has no
    # survey_exact_location table (the transaction never committed); then, statically:
    # "catch database copy"'s scope == {copy first, copy, writer}, and "database copy failed" removes msg.snapshot

@needs_node
def test_exact_writer_fails_closed_without_sqlite(): ...      # modules=("fs", "path") → throws; no file is created
@needs_node
def test_exact_writer_passes_other_downloads_through(): ...   # no msg.exactCopy → the same msg, flow context untouched

@needs_node
def test_validate_claims_the_list_for_an_exact_copy(): ...
    # context exact_copies {TICKET: {places: [PLACE], expires: now + 60000}}, msg.payload.files "tmdb-exact-" + TICKET →
    # msg.snapshot starts "/db/snapshot/", msg.exactCopy is True, msg.tarArgs ends " -- tmdb-exact-locations.sqlite",
    # msg.downloadName ends "_tmdb-exact-locations.tar.gz", no statusCode;
    # flow exactCopyPlaces == {msg.snapshot: [PLACE]}

@needs_node
def test_a_ticket_serves_a_second_request_in_its_time(): ...
    # two validate steps with the same ticket → two different msg.snapshot values, each with its list in flow context

@needs_node
def test_a_claimed_list_outlives_its_ticket(exact_copy_files): ...
    # claim, then empty exact_copies in the context, then run the writer with the claimed flow context →
    # survey_exact_location has its row

@needs_node
@pytest.mark.parametrize("files, entry", [
    ("tmdb-exact-" + TICKET, None),                                   # never kept
    ("tmdb-exact-" + TICKET, {"places": [PLACE], "expires": 1}),     # expired
])
def test_validate_refuses_an_unknown_or_expired_ticket(files, entry): ...
    # statusCode 404, the expiry text, no msg.snapshot, no flow entry; an expired entry is gone from exact_copies;
    # the ticket isn't in any logged text

@needs_node
@pytest.mark.parametrize("step", ["claim", "refusal", "writer"])
def test_no_download_message_carries_a_coordinate(step, ...): ...
    # "45.52252" and "122.6912" are not in json.dumps(of every msg the step returns)

def test_exact_copy_is_wired_between_the_copy_and_tar(): ...
    # "stop if cancelled" output 1 → the writer only; the writer → "zip files" only; the writer is in the download group;
    # "stop if cancelled" and "database copy failed" each contain 'exactCopyPlaces' once

def test_only_the_copy_writer_opens_a_database_itself(): ...
    # exactly one node in flows.json mentions global.get("sqlite"), and it is the writer;
    # it is also the only function whose code holds "CREATE TABLE" or "CREATE VIEW", and its code has no UPDATE,
    # DELETE, DROP, or ALTER; no sqlite node's sql mentions survey_exact_location or deployment_exact
```

Update `test_database_download_tars_a_copy` (the scope has three ids) and `test_cancel_stops_a_database_download_during_the_copy` (`stop["wires"][0]` is the writer).

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest script/tests/test_node_red_flows.py script/tests/test_node_red_settings.py -k "exact or sqlite or database_download or cancel_stops" -v`
Expected: FAIL.

- [ ] **Step 3: Implement**

`settings.js` first, then the flows edits with a script. Keep "copy database first?" as it is: it copies to `tmdb.sqlite` for both kinds of download, and its free-space sum reads that name.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest script/tests container/node-red-tm/schema/tests -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add container/node-red-tm/data script/tests
git commit -m "Add exact locations to a database download's copy, never the database"
```

**Stop for review** after this task: the flows are complete.

### Task 3: The control app: `POST /api/v1/surveys/database-copy`

**Files:**
- Modify: `tm-control/backend/tm_control/adapters/nodered.py`, `fake.py`, `modules/location/router.py`
- Modify: `tm-control/backend/tests/test_nodered_adapter.py`, `tests/test_api_surveys.py`, `tests/test_api_auth.py`, `tests/test_openapi_document.py`
- Regenerate: `tm-control/ui/src/api/openapi.json`, `src/api/schema.d.ts`

**Interfaces:**
- Consumes: `POST /tm-internal/database/exact-copy` (Task 1); `DownloadGrants.issue`, `DOWNLOAD_PATH`, `DOWNLOAD_TOKEN`, `client_ip`.
- Produces, `NodeRed.keep_exact_copy(self, ticket: str, places: list[dict]) -> None`: `POST /database/exact-copy` with `{"ticket": ticket, "places": places}`; raises `NodeRedError` as the other calls do.
- Produces, `FakeNodeRed.keep_exact_copy`: keeps the call in `self.exact_copies: dict[str, list[dict]]`.
- Produces, `POST /surveys/database-copy` (admin; declared before the `{survey_id}` routes), response model `DatabaseCopyOut(url: str, places: int)`:
  1. `reconcile.ensure(app_state, admin.id)`, a `ConfigError` answered as `export_places` does.
  2. The places whose status is `in_use` or `used` and that have both coordinates, as `{"survey_id": place.id, "lat": place.lat, "lon": place.lon}`. A planned place is never sent. None → `ApiError(409, "no_exact_locations", "No place this device has been at has an exact location, so a copy would hold nothing more than the database download on the Data export page.")`.
  3. `ticket = secrets.token_hex(16)`; `app_state.nodered.keep_exact_copy(ticket, places)`; a `NodeRedError` → `_nodered_error(error, "The copy wasn't started.")`.
  4. `files = f"tmdb-exact-{ticket}"`; `token = app_state.download_grants.issue(admin, client_ip(request), files, time.monotonic())`.
  5. `Audit(...).record(admin.id, "survey.database_copy", str(len(places)))`.
  6. `{"url": f"{DOWNLOAD_PATH}?files={files}&{DOWNLOAD_TOKEN}={token}", "places": len(places)}`, with `Cache-Control: no-store`.
- The link always carries a one-time token: a browser with a session never spends it, and Android's downloader, which has none, needs it.

- [ ] **Step 1: Write the failing tests**

- `test_nodered_adapter.py`: `test_keep_exact_copy_posts_the_ticket_and_the_places` (the path, the method, the body); `test_a_refused_exact_copy_raises_without_the_body` (a 400 → `NodeRedError("bad_request")`, and `"45.52252"` not in `repr(error)` or `str(error)`).
- `test_api_surveys.py`:
  - `test_database_copy_is_admin_only` (no session 401, a viewer 403, nothing posted to Node-RED).
  - `test_database_copy_sends_the_located_places_and_answers_a_link` (the place in use at `45.52252, -122.69120`, a used one with no location → the fake holds one ticket whose list is `[{"survey_id": <id>, "lat": 45.52252, "lon": -122.6912}]`; `places == 1`; `url` matches `^/storefiles\?files=tmdb-exact-[0-9a-f]{32}&tm_token=[A-Za-z0-9_-]+$`, and its ticket is the fake's).
  - `test_database_copy_leaves_out_planned_places` (a planned place with coordinates beside the located place in use → the list holds the place in use only).
  - `test_database_copy_needs_a_located_place` (the place in use has no location and the only located place is planned → 409 `no_exact_locations`; nothing posted; `len(app.state.download_grants)` unchanged).
  - `test_database_copy_makes_no_link_when_node_red_fails` (`keep_exact_copy` raising `NodeRedError("unreachable")` → 502 `nodered_error`; no grant; no audit row).
  - `test_database_copy_audits_the_count_only` (`("survey.database_copy", "1")` in the audit rows; no coordinate, ticket, or token in any audit row or captured log line: use `caplog`).
  - `test_two_database_copies_get_different_tickets`.
- `test_api_auth.py`: `test_verify_passes_a_database_copy_link_once_without_a_session` (the `url` from the endpoint as `X-Original-URI` with `X-TM-Required-Role: admin` and no cookie → 200; again → 401).
- `test_openapi_document.py`: the path is declared with its response model.

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tm-control/backend/tests -k "database_copy or exact_copy or openapi" -v`
Expected: FAIL.

- [ ] **Step 3: Implement**

- [ ] **Step 4: Run the tests to verify they pass, regenerate the API description**

Run: `python -m pytest tm-control/backend/tests -v`, then `PYTHONPATH=tm-control/backend python -m tm_control dump-openapi > tm-control/ui/src/api/openapi.json && (cd tm-control/ui && npm run api:generate)`
Expected: PASS; the two generated files change.

- [ ] **Step 5: Commit**

```bash
git add tm-control/backend tm-control/ui/src/api
git commit -m "Start a database copy with exact locations from the control app"
```

### Task 4: The Location page: the button

**Files:**
- Modify: `tm-control/ui/src/components/download.ts`, `src/modules/location/LocationPage.vue`, `tm-control/ui/README.md`
- Test: `tm-control/ui/tests/location-page.spec.ts`

The implementer loads `frontend-design:frontend-design`, `superpowers:test-driven-development`, and `superpowers:verification-before-completion`, adds short design notes to `tm-control/ui/README.md`, and screenshots the section at phone and desktop width in fake mode. Conventional Vuetify components; no custom CSS beyond spacing. In fake mode the link leads nowhere (there is no Node-RED); the README says so.

**Interfaces:**
- Consumes: `POST /api/v1/surveys/database-copy` → `{url, places}` (Task 3).
- Produces, `download.ts`: `export function openDownload(url: string): void`, which is `window.location.assign(url)`, the way the Dashboard's download starts (and the way that works in Android's sign-in window). Tests spy on it.
- Produces, the "Exact locations" section:
  - The paragraph becomes: "The database keeps a rounded location. You can save each place's exact one as a list, or download a copy of the database that has the exact locations in it."
  - Two buttons in a row that wraps (`d-flex flex-wrap ga-3`): "Export exact locations" (as it is) and "Download the database with exact locations" (outlined, primary, large, with its own `loading`). The second is disabled while no place in `state.surveys` with the status `in_use` or `used` has both `lat` and `lon`, with the line "No place this device has been at has an exact location yet." under the buttons.
  - A `ConfirmDialog` before the request, title "Download the database with exact locations?", text "This copy of the database includes the exact location of each place the device has been at. The database on this device keeps its rounded locations. Give the copy only to someone who should know where the device was.", confirm "Download".
  - On confirm: `POST`, then `openDownload(url)`, then an info alert: "The device is making the copy. The download starts by itself when the copy is ready, which can take a few minutes for a large database. The file's name ends in tmdb-exact-locations.tar.gz." A failure shows the API's message in the section's error alert and opens nothing.
- Produces, the Precision paragraph: its last sentence becomes "To give someone a copy of the database with each place's exact location, for analysis and mapping, use Download the database with exact locations, above."

- [ ] **Step 1: Write the failing tests**

In `tests/location-page.spec.ts`, beside the export's tests (`vi.spyOn(download, 'openDownload').mockImplementation(() => {})`):
- `it('asks before starting a database copy, then opens the link the API gives')` (no `POST` before the confirm; after it, one `POST /api/v1/surveys/database-copy` and `openDownload` called with the answer's `url`; the "making the copy" text shows).
- `it('opens nothing when the dialog is cancelled')`.
- `it("shows the API's message and opens nothing when the copy can't start")` (a 502).
- `it('disables the database copy when no place the device has been at has an exact location, and says why')` (a located planned place alone doesn't enable it).
- `it('keeps Export exact locations as it was')` (the CSV test still passes beside the new button).
- The Precision text test near line 319 expects the new sentence.

- [ ] **Step 2: Run them to verify they fail**

Run: `cd tm-control/ui && npx vitest run tests/location-page.spec.ts`
Expected: FAIL.

- [ ] **Step 3: Implement**

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd tm-control/ui && npm test && npm run build`
Expected: PASS, build clean.

- [ ] **Step 5: Commit**

```bash
git add tm-control/ui
git commit -m "Offer a database copy with exact locations on the Location page"
```

### Task 5: Docs, CLAUDE.md, and the READMEs

**Files:**
- Modify: `docs/use/location.md`, `docs/use/sharing.md`, `docs/ui/database.md`, `docs/data-and-payloads/data-overview.md`, `docs/development/tm-control.md`, `docs/assets/images/location-page.png` (retaken from fake mode if the section is in the picture), `CLAUDE.md`
- Test: `~/.venvs/tm-docs/bin/mkdocs build --strict`

- [ ] **Step 1: Write the edits**

- `docs/use/location.md`: a section "Download the database with exact locations" after "Export the exact locations", in operator words: what the copy is for; where the button is and what the confirmation asks; that the device makes the copy first, so the download starts after a wait; the file's name; what it adds to the database (decision 7): the table `survey_exact_location`, the view `deployment_exact` with one example query that lists where the device was and when (each deployment's sensor, start, end, and exact point), that this covers every place the device has been at and not only the one in use, that the `deployment` table still holds the rounded location, which places are in the table (those the device has been at), the three cases where the view's exact pair is empty, and that a corrected place or bearing appears as corrected, so an earlier copy can differ and the newer one is right; that the database on the device is unchanged and the Data export page's download still holds rounded locations; that the copy identifies where the device was, so it is for people who should know. Then the sentences elsewhere on the page that say the exact location leaves the device only by sharing or by the export gain this third way, each with a link to the new section.
- `docs/use/sharing.md`: the "The exact location is for you to give or keep" box names the copy beside the file from **Export exact locations**.
- `docs/ui/database.md`: under "Download the database", one sentence that this download holds the rounded location, with a link to the new section for the copy with exact ones.
- `docs/data-and-payloads/data-overview.md`: a short section for `survey_exact_location` and `deployment_exact`, with their columns, that says they exist only in a copy made with **Download the database with exact locations**, never in the database on the device, and that they hold what the `exact_location` attribute holds when the exact location is shared; the sentence "the exact location is never written to it" stays true for the database.
- `docs/development/tm-control.md`: in the Location module's part, the flow of a copy (the route, the ticket and its ten minutes, why it isn't single-use, the list in memory only, the claim at request start, the function that opens only the copy, `node:sqlite` through `functionGlobalContext` and why not the function node's module list, what happens when the rewrite fails, and what a power cut leaves on the card until Node-RED starts); the internal endpoint in the list of those the Location module calls; in "Download links", that the Location page's link is made by the route itself.
- `CLAUDE.md`: the internal-endpoint contract ("calls six more" becomes seven, with the new one and its body); the download group's new step and the rule that only "write exact locations into the copy" uses `global.get("sqlite")`, never on `tmdb.sqlite`, and that its `CREATE TABLE` and `CREATE VIEW` on the throwaway copy are the one exception to "never add `CREATE`/`ALTER TABLE` to the flows"; `settings.js`'s `functionGlobalContext`; the Location page's line in "What this repo is".
- `tm-control/ui/README.md`: Task 4 wrote its notes; check they match the built page.

- [ ] **Step 2: Build strictly**

Run: `~/.venvs/tm-docs/bin/mkdocs build --strict`
Expected: no warnings.

- [ ] **Step 3: Commit**

```bash
git add docs CLAUDE.md tm-control/ui/README.md
git commit -m "Document the database copy with exact locations"
```

### Task 6: Device tests

**Files:**
- Modify: `script/devpi/tests/test_web.py`

**Interfaces:**
- Consumes: `admin_session`, `viewer_session`, `expect`, `host`, `address`, `codedir`, `codeowner`, `request_from_this_machine`, `status_from_this_machine`, `Redacted`, and the fixture that limits a test to `pii_free` hosts (as `test_in_use_place_matches_config_yml` uses).

- [ ] **Step 1: Write the tests**

- `TM_INTERNAL_WRITES` gains `http://127.0.0.1:1880/tm-internal/database/exact-copy` (so `test_tm_internal_writes_need_the_token_on_the_pi` covers it).
- `test_node_red_has_sqlite_for_the_database_copy(host)`: `sudo podman exec node-red-tm node -e "require('node:sqlite')"` exits 0.
- `test_database_copy_needs_an_admin(address, admin_session, viewer_session)`: a viewer's `POST /api/v1/surveys/database-copy` is 403; the admin's is 200 with a `url` that starts `/storefiles?files=tmdb-exact-`, or 409 `no_exact_locations`. The link is wrapped in `Redacted`.
- `test_an_unknown_database_copy_link_is_404(address, admin_session)`: `/storefiles?files=tmdb-exact-` + 32 zeros with the admin session → 404 (added to `test_data_export_errors_from_this_machine`'s cases if that fits better).
- `test_a_database_copy_holds_exact_locations_and_the_database_does_not` (`pii_free` hosts only; skipped when the admin's `POST` answers 409): fetch the link from this machine into a temporary folder, untar it, and with Python's `sqlite3` on the dev machine assert `tmdb-exact-locations.sqlite` is the only member, `PRAGMA integrity_check` is `ok`, `SELECT count(*) FROM survey_exact_location` is at least 1, `SELECT count(*) FROM deployment_exact WHERE exact_lat IS NOT NULL` is at least 1, and `SELECT count(*) FROM deployment WHERE lat IS NOT NULL AND location_precision IS NULL` is 0. Then on the Pi, as the code owner, `SELECT count(*) FROM sqlite_master WHERE name IN ('survey_exact_location', 'deployment_exact')` on `tmdb.sqlite` is 0, and `db/snapshot` holds no entry. The temporary folder is removed in a `finally`. Failure messages print counts, never a row.

- [ ] **Step 2: Check them off-device**

Run: `python -m pytest script/devpi/tests --collect-only -q 2>&1 | tail -3`
Expected: collected, no errors.

- [ ] **Step 3: Commit**

```bash
git add script/devpi/tests
git commit -m "Check the database copy with exact locations on a device"
```

**Stop for review** before the Pi plan.

### Task 7: The Pi plan

Through `tmdev.py check start|item|status|end`, one host, from a worktree (`script/devpi/README.md`), on the `pii_free` unit with a camera and radar. Deploy with `tmdev.py deploy <host> -- -t node-red-tm -t tm-control`. Frigate's detection, snapshots, and recording stay off throughout; no item needs them. Nothing printed may hold a coordinate's digits, a link, or a token: record counts, file names, and status codes.

- [ ] 1. **Setup.** The place in use has the example coordinates (Correct location on the page if it has none). `GET /api/v1/surveys` shows it; `journalctl -u node-red-tm` since the deploy has no line naming `sqlite` or `install_not_allowed`.
- [ ] 2. **Device tests.** `tmdev.py test <host> -- -k "database_copy or exact or tm_internal or data_export or sqlite"`, then the full non-disruptive suite. This covers the copy's contents, the live database, and the empty `db/snapshot`.
- [ ] 3. **From a desktop browser** (maintainer-observed, or the assistant with a browser on the dev machine): press the button, confirm; the file saves as `<hostname>_<time>_tmdb-exact-locations.tar.gz`; the page shows the "making the copy" text; the Dashboard's Data export page shows and then hides its "Processing File(s)" window.
- [ ] 4. **The Dashboard's download is unchanged.** "Download Database" saves `…_tmdb.tar.gz`; the database in it has neither `survey_exact_location` nor `deployment_exact`.
- [ ] 5. **The ticket's life.** Request a link through the API with the admin session and fetch it twice with `curl -o /dev/null -w '%{http_code}'`: 200 both times. Request another, wait 11 minutes, fetch: 404.
- [ ] 6. **A restart mid-download.** Fetch a link with `curl --limit-rate 20k`, and while it runs, `sudo systemctl restart node-red-tm.service`: curl ends with an error, and once Node-RED is up `db/snapshot` is gone or empty.
- [ ] 7. **A viewer.** A viewer's session gets 403 from the route and from `/storefiles`; the Location page isn't in a viewer's menu (as before).
- [ ] 8. **Android's sign-in window** (maintainer, with a phone on the unit's hotspot): the download saves from the window, and the saved file is the exact copy. If it doesn't save, stop and record what the phone showed; decision 5 depends on this.
- [ ] 9. **Leave the unit as it was:** no downloaded file left on the Pi or the dev machine, `db/snapshot` empty, the place's coordinates as the bench keeps them.
- [ ] Record each item with `tmdev.py check item`, and end with `tmdev.py check end`.

### Task 8: Pull request

- [ ] Run every off-device check in Global Constraints once more on the final branch; `npm run build`; `git grep` the branch for device names and any coordinate other than the two allowed.
- [ ] Copy this plan to `design/plans/2026-11-14-location-4c-database-copy.md` and commit it ("Add the plan for the database copy with exact locations").
- [ ] Open the PR as a draft, against `feature/sharing-page/314` while PR 321 is open and against `dev` once it has merged, with the template filled in: the release-note paragraph ("The Location page can download a copy of the database with each place's exact location, for analysis and mapping. The copy adds a table of exact locations by place id and a view that joins it to the deployments; the deployment records themselves keep the rounded location. The database on the device still holds only rounded locations, and so does the download on the Data export page. The copy is for admins, asks first, and is named tmdb-exact-locations so it isn't mistaken for the shareable database."), what is new in `settings.js`, the Docs list from Task 5, the Pi plan's results, the limits (decision 12; a list waits in Node-RED's memory for up to ten minutes; on Android the copy is made twice), and the AI-assistance section. The maintainer reads the commit messages and the PR text before any push.

## Later

- **The map pin and the block picker** (design section 9), the next plan: a map library loaded only when an admin opens the map, the pin on the place form, the per-sensor block picker on the Sharing page, the block form of `public_map`, and the "Check your street" flag.
- **Moving the downloads' page into the control app.** Not needed for this plan: Node-RED must make the file, because it owns the database and its copy waits for the flows' writes. What could move later is the page: the buttons for both downloads in the control app, with progress and Cancel, while Node-RED still makes the file. Reasons to do it then: progress on the Location page (below), one place for downloads instead of two, a job that makes the copy once for Android's double fetch (which would keep a copy with exact locations on the card longer, so not for this file), and a later store for identifying data with its own download rules. Backup and restore is not a reason; it leaves the database out.
- **A JSON or CSV export with exact locations.** The Data export page's JSON files carry `deployment_id` only, so a reader joins them to the copy's `deployment_exact` view, or to the "Export exact locations" list by `survey_id`. Nothing more is planned.
- **Progress on the Location page.** The page can't see the copy's progress; the Dashboard's window can. If the wait confuses people, the control app could read a progress figure from Node-RED's status.
