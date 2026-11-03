# Location 1: tmdb survey migration and the Node-RED deployment engine

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every deployment row a survey id and a stored precision, round what tmdb holds to that precision, and make Node-RED start deployments on a survey or bearing change instead of a coordinate change, with the per-survey queries tm-control will read.

**Architecture:**
- A tmdb migration, `0002_deployment_survey.sql`, adds `survey_id` and `location_precision` to `deployment`, assigns one random survey id per distinct exact place in the existing rows, rounds every stored coordinate to one decimal place, and indexes `events(deployment_id)`. The runner backs the database up to `db/backup/tmdb-v1-*.sqlite` first; a later plan imports the exact places from that copy.
- On the `init-config` tab, `init config defaults` learns `deployment.survey_id` and `deployment.database_precision`, and the deployment engine is rewritten: one function node with four outputs (close, insert, rewrite, result) feeding three prepared sqlite nodes, deciding per enabled sensor from the open rows and the config, never from lat/lon. Rows are written rounded or null. The result payload keeps today's shape for the ThingsBoard tab.
- Four new `/tm-internal/` endpoints answer per-survey questions from `deployment` and `events` and rewrite stored coordinates to a coarser precision. `/tm-internal/status` reports the survey id and precision instead of coordinates, and the `deployments` client attribute stops carrying the exact top-level coordinates.
- No tm-control code changes. `config.yml` gets the two keys by hand or, from plan 3, from tm-control. Until then a missing `survey_id` keeps the open rows as they are.

**Tech Stack:** SQLite 3.40 SQL, Python 3.11 (the runner, pytest), Node-RED 5.0.8 flows (`node-red-node-sqlite` prepared statements, `http in`/`http response`), the Node.js function harness in `script/tests/test_node_red_flows.py`, Material for MkDocs.

**Spec:** the location and survey-id design (not yet published), sections 1, 3, 4, 6, 11 (the Node-RED half), 13, and "Open questions" 1. Read it with this plan. The entered-secrets design and the sharing sections are later plans. The deployment engine's behaviour table is section 6, step 2; where this plan and the design disagree, say so in the PR rather than picking one.

**Status:** written 2026-10-30 against `feature/tm-control-status-system/201` at `a87f946` (PR 269, M3, which contains PR 261 and `dev` at `469b575`). Branch: `feature/tmdb-survey-id/250`, stacked on M3; this file was added in the PR that implements it. Plans 2 (entered secrets), 3 (tm-control location state and screens), and 4 (upload gate and sharing) follow.

**Where M3 left things that this plan touches:**
- `init-config` tab: the config load chain is inject `ecc317fcd059b4c3` / watch `5ffb7c9c38b8c5b0` → "tm-internal: config load started" → file → YAML → `init config defaults` (`94136e5a6f092bb6`) → change `b0252bd49dc8e61d` (sets `global.config`) → change `ac8b2de05ec27001` (copies `payload.sensors` to `msg.sensors`) → template `696c3a7b0b83f7b5` (the open-rows SELECT) → sqlite `f6ecdd18d8e03f91` → change `6d2f607b324415b4` (`msg.sqlActiveDeployments`) → function `689b64c16a889e0a` (the engine) → switch `24efdc7f1231f7f0` → sqlite `bc398ad5de3bd112` (writes) or junction `05c37560dd57ea90` → link out `1ba33a74f2d3a680` to the ThingsBoard tab (`8768b75dbfee3973` → template `9b0f7197fe82bbfa`, `8a83d59ee0db1198` → function `c6ff73faf6fa9e98`) and a debug node. `b0252bd49dc8e61d` also feeds "tm-internal: config loaded" (`2b50b0bfb900ff09`), which writes `tm_status.deployment = {lat, lon, bearing}`.
- `GET /tm-internal/status` is http in `5cafb80984a9d01b` → "tm-internal: check token" (`cbc268130cc14c58`, two outputs) → "tm-internal: build status" (`a88895e60521585e`) → http response, or → 401 response. The token is `env.get("TM_INTERNAL_TOKEN")` against header `x-tm-internal-token`. nginx returns 404 for `/nr/tm-internal/`.
- `tm_status.schema_version` comes from a fixed sqlite node (`PRAGMA user_version`) → "tm-internal: record schema version" (`e813005490ef2e46`).
- The sqlite config node is `2f60c1ab30a6fc8f` (`TMDB` in the flows tests). The device serial is `env TM_RPI_SN`; the `system` tab copies it to `global.deviceAttributes.deviceName` after the engine first runs (issue 254).
- The function harness (`run_functions(steps, env, context)`) gives a function `msg`, `env.get`, `global.get/set` on one shared store, and `node.error/warn/log/status`. It has no `node.send` and no `node.done`: a function under test must return its outputs. A multi-output function returns an array with one entry per output; an entry may be an array of messages.
- Schema tests: `helpers.py` (`BASELINE_TABLES`, `migrate`, `create_db`, `query`, `columns`, `user_version`, `files_in`), `conftest.py` (`db_path`, `make_migrations`), `test_migrate.py` (asserts `user_version == 1` after a fresh migrate in five places and uses `with_a_second_migration` to get a non-baseline step), `test_flows_sql.py` (compiles every prepared/fixed sqlite node and every template feeding a sqlite node, with `$params` bound to NULL), `test_schema_snapshot.py` (`schema.sql` must equal `--dump-schema`).

## Global Constraints

- Migrations: SQLite 3.40 SQL only; no `BEGIN`, `COMMIT`, `END`, `VACUUM`, or `PRAGMA user_version` (the runner refuses the file); additive except the documented coordinate rewrite; never edit `0001_baseline.sql`.
- `flows.json` is edited programmatically and re-serialised with `json.dumps(flows, indent=4, ensure_ascii=False)` and no trailing newline; `python3 -m json.tool` must parse it; no `CREATE`/`ALTER`/`DROP` in any flow SQL. Node ids named in this plan keep their ids; new nodes get fresh 16-hex ids.
- Survey id: `^[0-9a-f]{8}-si$`. Precision: the strings `none`, `1`, `2`; the number stored in `location_precision` is `1`, `2`, or NULL. Coordinates in tmdb are never finer than two decimal places.
- Deployment id format stays `<ms>-<8 hex>-d`. Row shape the ThingsBoard tab reads stays `{updatedDeployment: [...], currentDeployment: [...]}`.
- No exact coordinate in any test fixture, commit, or PR text other than the Portland-scale example `45.52252, -122.69120` already in PR 260.
- Every commit ends with the trailer block from the repo's CLAUDE.md (Assisted-by / AI-Model / AI-Effort / AI-Role); never `Co-Authored-By`. Docs follow "Writing docs" in `docs/development/contributing.md`; `mkdocs build --strict` passes.
- Off-device checks before each commit: `python -m pytest container/node-red-tm/schema/tests script/tests` from the repo root in the dev venv.

## Review Focus

1. A coordinate quoted in YAML (`lat: '45.52252'`) arrives as a string; the engine must store the rounded number, not NULL or `NaN`. Test in Task 3 (`test_engine_rounds_string_coordinates`).
2. One sensor with two open rows (left by issue 254's `undefined` device names): the engine must keep the newest and close the rest, not leave rows open forever. Test in Task 3 (`test_engine_closes_duplicate_open_rows`).
3. A `deployment` table in the legacy shape (`entryDateTime`, `orientation`, `address`, no `bearing`): the migration must still apply and leave the device at version 2 with drift reported, not fail. Test in Task 1 (`test_0002_applies_to_the_legacy_deployment_shape`).
4. Half-blank coordinates (`lat` set, `lon` empty): tmdb stores NULL for both and `location_precision` NULL. Tests in Task 1 (migration) and Task 3 (engine).
5. A `/tm-internal/surveys/<id>/events` call with an id that isn't a survey id must answer 400 and run no SQL, so a malformed id can't become a table scan. Test in Task 5.

---

### Task 1: Migration 0002 and the schema tests

**Files:**
- Create: `container/node-red-tm/schema/migrations/0002_deployment_survey.sql`
- Modify: `container/node-red-tm/schema/schema.sql` (regenerated), `container/node-red-tm/schema/tests/helpers.py`, `container/node-red-tm/schema/tests/test_migrate.py`
- Create: `container/node-red-tm/schema/tests/test_0002_deployment_survey.py`

**Interfaces:**
- Produces: `deployment` columns `survey_id TEXT` and `location_precision INTEGER`; index `index_events_deployment_id ON events(deployment_id)`; `user_version` 2; the runner's backup `db/backup/tmdb-v1-<stamp>.sqlite` holding the exact rows.

- [ ] **Step 1: Write the failing migration tests**

```python
# test_0002_deployment_survey.py
"""0002 on synthetic rows: ids per place before rounding, rounding to one decimal, NULL pairs, and the legacy shape."""
import sqlite3
from helpers import SCHEMA_DIR, LEGACY_SCHEMA, create_db, migrate, query, user_version, columns

BASELINE = (SCHEMA_DIR / "migrations" / "0001_baseline.sql").read_text()
ROWS = [  # id, start, end, lat, lon, bearing, sensorType, sensorName
    ("1-a-d", 1, 2, 45.52252, -122.69120, "n", "cameras", "picam_h265"),      # place A, closed
    ("2-b-d", 3, None, 45.52252, -122.69120, "s", "radars", "TM_RADAR_SERIAL_PORT_00"),  # place A, open
    ("3-c-d", 4, None, 45.5300, -122.7000, "e", "cameras", "picam_h265"),     # place B
    ("4-d-d", 5, None, None, None, "", "cameras", "picam_h265"),             # no location
    ("5-e-d", 6, None, 45.52252, None, "w", "radars", "TM_RADAR_SERIAL_PORT_01"),  # half blank
]

def v1_db(path):
    create_db(path, BASELINE, user_version=1)
    con = sqlite3.connect(path)
    con.executemany("INSERT INTO deployment (id, entryStartDateTime, entryEndDateTime, lat, lon, bearing, sensorType, sensorName)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?)", ROWS)
    con.commit(); con.close()

def test_0002_adds_columns_index_and_version(db_path):
    v1_db(db_path)
    assert migrate("--db", db_path) == 0
    assert user_version(db_path) == 2
    assert columns(db_path, "deployment")[-2:] == ["survey_id", "location_precision"]
    assert query(db_path, "SELECT name FROM sqlite_master WHERE type = 'index' AND name = 'index_events_deployment_id'")

def test_0002_assigns_one_survey_id_per_exact_place_before_rounding(db_path):
    v1_db(db_path)
    migrate("--db", db_path)
    ids = dict(query(db_path, "SELECT id, survey_id FROM deployment"))
    assert ids["1-a-d"] == ids["2-b-d"]                      # same exact place, open or closed
    assert ids["1-a-d"] != ids["3-c-d"]                      # 45.53 rounds to the same 1 dp cell, still a different place
    assert all(len(i) == 11 and i.endswith("-si") for i in (ids["1-a-d"], ids["3-c-d"]))
    assert ids["4-d-d"] is None and ids["5-e-d"] is None      # no location, no survey

def test_0002_rounds_to_one_decimal_and_nulls_half_blank_pairs(db_path):
    v1_db(db_path)
    migrate("--db", db_path)
    rows = {r[0]: r[1:] for r in query(db_path, "SELECT id, lat, lon, location_precision FROM deployment")}
    assert rows["1-a-d"] == (45.5, -122.7, 1)
    assert rows["3-c-d"] == (45.5, -122.7, 1)
    assert rows["4-d-d"] == (None, None, None)
    assert rows["5-e-d"] == (None, None, None)

def test_0002_keeps_the_exact_rows_in_the_backup(db_path):
    v1_db(db_path)
    migrate("--db", db_path)
    [backup] = (db_path.parent / "backup").glob("tmdb-v1-*.sqlite")
    assert query(backup, "SELECT lat, lon FROM deployment WHERE id = '1-a-d'") == [(45.52252, -122.69120)]

OLDEST_DEPLOYMENT = ("CREATE TABLE deployment (id TEXT PRIMARY KEY, entryDateTime REAL, lat REAL, lon REAL,"
                     " orientation TEXT, address TEXT, description TEXT);")  # the shape on the oldest devices

def test_0002_applies_to_the_legacy_deployment_shape(db_path, capsys):
    create_db(db_path, OLDEST_DEPLOYMENT)  # version 0, no other tables: baseline adds them and keeps this one
    con = sqlite3.connect(db_path)
    con.execute("INSERT INTO deployment (id, lat, lon) VALUES ('old-d', 45.52252, -122.69120)")
    con.commit(); con.close()
    assert migrate("--db", db_path) == 0
    assert user_version(db_path) == 2
    assert query(db_path, "SELECT lat, lon, survey_id IS NOT NULL FROM deployment") == [(45.5, -122.7, 1)]
    out = capsys.readouterr()
    assert "DRIFT" in out.out + out.err  # the missing baseline columns are reported, as today
```

`fixtures/legacy_v0_schema.sql` holds the *current* deployment shape (the pre-#208 flows' `CREATE TABLE`), so the oldest shape is written inline above; don't change the fixture.

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest container/node-red-tm/schema/tests/test_0002_deployment_survey.py -v`
Expected: FAIL (`user_version` 1, no `survey_id` column).

- [ ] **Step 3: Write `0002_deployment_survey.sql`**

The design's SQL (section 4), in this order: the two `ALTER TABLE ... ADD COLUMN`; a temporary table of distinct exact `(lat, lon)` pairs where both are not NULL, given `lower(hex(randomblob(4))) || '-si'` each; `UPDATE deployment SET survey_id` by exact match on both columns; drop the temporary table; `UPDATE ... SET lat = ROUND(lat, 1), lon = ROUND(lon, 1), location_precision = 1 WHERE lat IS NOT NULL AND lon IS NOT NULL`; `UPDATE ... SET lat = NULL, lon = NULL WHERE lat IS NULL OR lon IS NULL`; `CREATE INDEX IF NOT EXISTS index_events_deployment_id ON events(deployment_id)`. A header comment says what the file does to existing data and where the exact rows went. No transaction statements.

- [ ] **Step 4: Regenerate `schema.sql` and update the shared test expectations**

Run: `python3 container/node-red-tm/schema/tmdb_migrate.py --dump-schema > container/node-red-tm/schema/schema.sql`

In `helpers.py` add `LATEST_VERSION = 2` and in `test_migrate.py` replace the literal `1` in the fresh-migrate assertions with it. `test_fresh_database_gets_baseline_tables_and_version` keeps "no backup" only for an empty database: a fresh file has no tables, so the runner still skips the backup. `with_a_second_migration` now needs a third file name (`0003_create_extra.sql`) or a bespoke pair; keep its intent. `BASELINE_TABLES` is unchanged (0002 adds no table).

- [ ] **Step 5: Run the whole schema suite**

Run: `python -m pytest container/node-red-tm/schema/tests -v`
Expected: PASS, including `test_schema_sql_matches_the_migrations` and every `test_flow_sql_compiles_against_schema` (the old flows still compile against v2).

- [ ] **Step 6: Time the migration on a large synthetic database**

Write a throwaway script in the scratch directory (not committed) that creates a v1 database with 5,000,000 `events` rows (random `deployment_id` from 20 ids) and 200 `deployment` rows, then runs `migrate("--db", ...)` and prints the elapsed time, with and without the `CREATE INDEX` line. Record both numbers in the PR body. Decision rule: if the index adds more than 5 minutes on this machine, remove the `CREATE INDEX` line from 0002 and note in the PR that the per-survey event count becomes a scan; the Pi number in Task 7 is the final word.

- [ ] **Step 7: Commit**

`git add container/node-red-tm/schema` then commit: "Add tmdb migration 0002: survey ids, one-decimal coordinates, events index".

---

### Task 2: `init config defaults` learns the two keys

**Files:**
- Modify: `container/node-red-tm/data/flows.json` (node `94136e5a6f092bb6`, `func`)
- Modify: `container/node-red-tm/config/config.yml.j2` (`deployment:` block)
- Test: `script/tests/test_node_red_flows.py`

**Interfaces:**
- Produces: after this node, `msg.payload.deployment.survey_id` is a valid id or `null`, `msg.payload.deployment.database_precision` is one of `'none'`, `'1'`, `'2'` (default `'1'`), and `lat`/`lon` are numbers or `''`.

- [ ] **Step 1: Write the failing tests**

In `test_node_red_flows.py`, next to `test_thingsboard_without_a_host_is_a_config_error`, using its `render`/`load_role_yaml` pattern for the template and `run_functions` for the node:

```python
@needs_node
@pytest.mark.parametrize("given, expected, errors", [
    ({}, {"survey_id": None, "database_precision": "1"}, set()),
    ({"survey_id": "3f9a1c2e-si", "database_precision": "2"}, {"survey_id": "3f9a1c2e-si", "database_precision": "2"}, set()),
    ({"survey_id": "3F9A1C2E-si"}, {"survey_id": "3f9a1c2e-si", "database_precision": "1"}, set()),      # case folded
    ({"survey_id": "home"}, {"survey_id": None, "database_precision": "1"}, {"deployment.survey_id"}),
    ({"database_precision": "3"}, {"survey_id": None, "database_precision": "1"}, {"deployment.database_precision"}),
    ({"database_precision": 1}, {"survey_id": None, "database_precision": "1"}, set()),                  # YAML number
])
def test_init_config_defaults_survey_keys(given, expected, errors): ...
    # config = rendered template with lat/lon 0.0; config["deployment"].update(given)
    # assert {k: step["result"]["payload"]["deployment"][k] for k in expected} == expected
    # assert {text.split()[3] for level, text, _ in step["logged"] if level == "error"} == errors

@needs_node
def test_init_config_defaults_allows_blank_coordinates(): ...
    # config["deployment"] = {"lat": "", "lon": "", "bearing": ""} → no error logged, lat and lon stay ""

def test_config_template_has_the_survey_keys(): ...
    # rendered template's deployment block has database_precision "1" and a survey_id key that renders empty
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest script/tests/test_node_red_flows.py -k "survey_keys or blank_coordinates or template_has_the_survey" -v`
Expected: FAIL.

- [ ] **Step 3: Change the function and the template**

In the `deployment` section of the function: accept `''`/`null`/missing `lat`/`lon` without an error (the type error stays for non-empty non-numbers; the message text keeps the key as its fourth word). Add `survey_id`: missing or empty → `null`; otherwise lower-case it and require `/^[0-9a-f]{8}-si$/`, else `node.error("Node-RED config.yml key deployment.survey_id is not a survey id (8 hex characters and -si); ignoring it")` and `null`. Add `database_precision`: `String(value)` of a missing value is `'1'`; allowed `'none'`, `'1'`, `'2'`, else an error naming `deployment.database_precision` and `'1'`. Leave the copy-down loop alone: the engine reads both keys from the top level only.

In `config.yml.j2`, under `deployment:` add `survey_id:` (empty; comment: "set by the Location page; a change here starts a new deployment") and `database_precision: '1'` (comment: "none, 1, or 2 decimal places stored in the database"). The template is written only on first install, so existing files get defaults from the function.

- [ ] **Step 4: Run the tests**

Run: `python -m pytest script/tests -v`
Expected: PASS, including the existing `test_thingsboard_without_a_host_is_a_config_error` (its `"north"`/`"west"` still error) and `test_init_config_defaults_loads_the_new_config_template`.

- [ ] **Step 5: Commit**

"Read deployment.survey_id and database_precision in init config defaults".

---

### Task 3: The deployment engine

**Files:**
- Modify: `container/node-red-tm/data/flows.json` on the `init-config` tab: template `696c3a7b0b83f7b5`, function `689b64c16a889e0a`; remove switch `24efdc7f1231f7f0` and sqlite `bc398ad5de3bd112`; add three sqlite nodes.
- Test: `script/tests/test_node_red_flows.py`; `container/node-red-tm/schema/tests/test_flows_sql.py` picks the new SQL up by itself.

**Interfaces:**
- Consumes: `msg.sensors` (from `ac8b2de05ec27001`), `msg.sqlActiveDeployments` (rows of the SELECT below), `global.config.deployment.{survey_id, database_precision, lat, lon}`, `env TM_RPI_SN`.
- Produces: output 1 → sqlite "close deployment", prepared `UPDATE deployment SET entryEndDateTime = $ended WHERE id = $id`; output 2 → sqlite "insert deployment", prepared `INSERT INTO deployment (id, entryStartDateTime, lat, lon, bearing, sensorType, sensorName, deviceName, survey_id, location_precision) VALUES ($id, $started, $lat, $lon, $bearing, $sensorType, $sensorName, $deviceName, $survey_id, $location_precision)`; output 3 → sqlite "rewrite deployment", prepared `UPDATE deployment SET survey_id = $survey_id, lat = $lat, lon = $lon, location_precision = $location_precision WHERE id = $id`; output 4 → junction `05c37560dd57ea90` with `msg.payload = {updatedDeployment, currentDeployment}` where each row has `id, entryStartDateTime, entryEndDateTime, lat, lon, bearing, sensorType, sensorName, deviceName, survey_id, location_precision`. Each SQL message carries its values in `msg.params` with `$`-prefixed keys. `global.config.sensors.<type>.<name>.deployment.id` and `global.tm_status.deployments` (the `currentDeployment` list) are set.
- The SELECT (template `696c3a7b0b83f7b5`): `SELECT id, entryStartDateTime, lat, lon, bearing, sensorType, sensorName, deviceName, survey_id, location_precision FROM deployment WHERE entryEndDateTime IS NULL ORDER BY sensorType, sensorName, entryStartDateTime DESC;` (all open rows; the engine groups them).

- [ ] **Step 1: Write the failing engine tests**

A helper in the test module builds the inputs and runs the node: `engine(sensors, open_rows, deployment, env=None)` returns `(close, insert, rewrite, result)` from `run_functions([(named(flows, "deployment engine"), {"sensors": sensors, "sqlActiveDeployments": open_rows})], env={"TM_RPI_SN": "serial-1", **(env or {})}, context={"config": {"deployment": deployment, "sensors": sensors}})` by unpacking `step["result"]`, with each output normalised to a list of messages. Sensors fixture: `{"cameras": {"picam_h265": {"enabled": True, "deployment": {"bearing": "n"}}}, "radars": {"TM_RADAR_SERIAL_PORT_00": {"enabled": True, "deployment": {"bearing": "s"}}, "TM_RADAR_SERIAL_PORT_01": {"enabled": False}}}`. Place: `{"survey_id": "3f9a1c2e-si", "database_precision": "1", "lat": 45.52252, "lon": -122.69120}`.

```python
def test_engine_inserts_a_row_per_enabled_sensor_on_a_fresh_database(): ...
    # no open rows → insert has 2 messages; params: $survey_id "3f9a1c2e-si", $lat 45.5, $lon -122.7,
    # $location_precision 1, $deviceName "serial-1", $bearing per sensor, $id matches r"^\d{13}-[0-9a-f]{8}-d$";
    # close and rewrite empty; result.payload.currentDeployment has 2 rows; global config.sensors...deployment.id set

def test_engine_leaves_matching_open_rows_alone(): ...
    # open rows with the same survey_id and bearing → all four outputs empty except result; ids reused in global

def test_engine_adopts_an_open_row_without_a_survey(): ...
    # open camera row with survey_id None, same bearing → rewrite has 1 message with $id of that row,
    # $survey_id, $lat 45.5, $lon -122.7, $location_precision 1; no close, no insert for that sensor

def test_engine_starts_a_deployment_on_a_new_survey_or_bearing(): ...
    # camera open row survey "aaaaaaaa-si" (different), radar open row same survey but bearing "e" →
    # close has 2 (both ids, $ended an integer ms), insert has 2; updatedDeployment lists the 2 closed rows

def test_engine_never_compares_coordinates(): ...
    # open rows at 45.5/-122.7 with the same survey and bearing, config lat moved to 45.6 → nothing written

def test_engine_ignores_coordinates_under_a_sensor(): ...
    # camera deployment {"bearing": "n", "lat": 40.0, "lon": -100.0}, no open rows →
    # insert $lat 45.5, $lon -122.7 (the top level's, rounded); the location is per unit (design section 3)

def test_engine_lowers_precision_in_place_and_ignores_a_raise(): ...
    # open rows location_precision 2 (45.52/-122.69), config precision "1" → rewrite with 45.5/-122.7/1, no close
    # open rows location_precision 1, config precision "2" → nothing written

def test_engine_stores_null_for_none_or_missing_coordinates(): ...
    # precision "none" with coordinates → insert $lat None, $lon None, $location_precision None
    # precision "1" with lat "" → the same three None

def test_engine_without_a_survey_id_creates_missing_rows_and_closes_nothing(): ...
    # survey_id None: camera has an open row with survey "aaaaaaaa-si" (unchanged, not closed), radar has none
    # → insert 1 with $survey_id None; close empty

def test_engine_rounds_string_coordinates(): ...
    # lat "45.52252" (quoted YAML) → $lat 45.5; lat "north" → $lat None and one node.error naming deployment.lat

def test_engine_closes_duplicate_open_rows(): ...
    # two open camera rows, same survey and bearing, starts 10 and 20 → close has 1 message for the start-10 row;
    # currentDeployment keeps the start-20 row

def test_engine_skips_disabled_sensors(): ...
    # TM_RADAR_SERIAL_PORT_01 (disabled) with an open row → nothing written for it, and its row is not closed

def test_engine_wiring(): ...
    # function has outputs 4; wires[0..2] each reach one sqlite node with sqlquery "prepared", mydb TMDB, and the
    # SQL above (compare after whitespace normalisation); wires[3] == [["05c37560dd57ea90"]];
    # nodes 24efdc7f1231f7f0 and bc398ad5de3bd112 no longer exist; the template's SQL is the SELECT above
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest script/tests/test_node_red_flows.py -k engine -v`
Expected: FAIL (`named(flows, "deployment engine")` finds nothing).

- [ ] **Step 3: Rewrite the engine**

Rename `689b64c16a889e0a` to "deployment engine", set `outputs` 4, and replace `func`. Decision per enabled sensor (type, name), with `open` = that sensor's open rows newest first, `want` = `{survey_id, bearing}` from config (bearing per sensor, lower-cased, `''` for empty), `stored` = `round(lat, lon)` per `database_precision` (numbers or numeric strings via `Number()`; anything else or `'none'` → all three NULL and, for a non-numeric non-empty value, one `node.error` naming `deployment.lat` or `deployment.lon`):

1. Close every open row after the first (output 1).
2. No open row → insert (output 2) with `want` and `stored`.
3. `want.survey_id` is null → keep the row (no close, no rewrite), unless there's none.
4. Row `survey_id` is null and bearing equal → rewrite (output 3) with `want.survey_id` and `stored`.
5. Row `survey_id` or bearing differs → close (output 1) and insert (output 2).
6. Otherwise, if the row's `location_precision` is finer than the config's (2 vs 1, or any vs `none`) → rewrite with `stored` and the same survey id; else nothing.

`deviceName` is `env.get("TM_RPI_SN") || null`. `$ended` and `entryStartDateTime` are `Date.now()`. `currentDeployment` lists, per sensor, the row as it is after this run (inserted, rewritten, or unchanged); `updatedDeployment` lists closed rows with `entryEndDateTime`. Set `global.config.sensors.<type>.<name>.deployment.id` and `global.tm_status.deployments`. Return `[close, insert, rewrite, [{payload}]]`; no `node.send`, no `node.done`.

Add the three sqlite nodes (`sqlquery: "prepared"`, `mydb: "2f60c1ab30a6fc8f"`, `z` the init-config tab, names as in Interfaces) and the template's SELECT; delete the switch and the old sqlite node. Keep the debug node and the link out as they are.

- [ ] **Step 4: Run every off-device check**

Run: `python -m pytest container/node-red-tm/schema/tests script/tests -v && python3 -m json.tool container/node-red-tm/data/flows.json >/dev/null`
Expected: PASS; `test_flow_sql_compiles_against_schema` lists the three new prepared statements by name and the SELECT.

- [ ] **Step 5: Commit**

"Rewrite the deployment engine around survey ids and bearings; store rounded coordinates".

---

### Task 4: Status and the ThingsBoard deployment payloads stop carrying exact coordinates

**Files:**
- Modify: `container/node-red-tm/data/flows.json`: function `2b50b0bfb900ff09` ("tm-internal: config loaded"), template `9b0f7197fe82bbfa` ("set deployment client side attribute payload").
- Test: `script/tests/test_node_red_flows.py`

**Interfaces:**
- Produces: `/tm-internal/status` body `deployment: {survey_id: <id or null>, database_precision: "none"|"1"|"2"}`. The `deployments` client attribute's `deploymentTopLevel` becomes `{"survey_id": ..., "database_precision": ...}`; the per-sensor entries come from `currentDeployment` and are rounded already.

- [ ] **Step 1: Write the failing tests**

```python
@needs_node
def test_config_loaded_records_the_survey_not_the_coordinates(): ...
    # run 2b50b0bfb900ff09 with context config.deployment = {survey_id, database_precision, lat, lon, bearing}
    # → global tm_status.deployment == {"survey_id": "3f9a1c2e-si", "database_precision": "1"}

def test_no_init_config_node_puts_coordinates_in_tm_status(): ...
    # no function on the init-config tab contains 'tm_status.deployment' together with 'lat'

def test_deployment_attribute_has_no_top_level_coordinates(): ...
    # template 9b0f7197fe82bbfa: "global.config.deployment.lat" not in template; "survey_id" in template
```

- [ ] **Step 2: Run to verify they fail**, then **Step 3:** make the two changes (the template's `deploymentTopLevel` keys: `survey_id`, `database_precision`), then **Step 4:** run `python -m pytest script/tests -v` (PASS; M3's `test_tm_internal_status_endpoint_exists` still passes).

- [ ] **Step 5: Commit**

"Report the survey instead of coordinates in /tm-internal/status and the deployments attribute".

---

### Task 5: Per-survey endpoints under `/tm-internal/`

**Files:**
- Modify: `container/node-red-tm/data/flows.json` (init-config tab, new nodes)
- Test: `script/tests/test_node_red_flows.py`; SQL compiled by `test_flows_sql.py`.

**Interfaces (all token-checked like `/tm-internal/status`; 401 without the token):**

| Node chain | Request | SQL (prepared) | Response |
|---|---|---|---|
| `GET /tm-internal/deployments` | query `survey_id` (validated) | `SELECT id, entryStartDateTime, entryEndDateTime, lat, lon, bearing, sensorType, sensorName, survey_id, location_precision FROM deployment WHERE survey_id = $survey_id ORDER BY entryStartDateTime` | 200 `{"deployments": [rows]}` |
| `GET /tm-internal/surveys/usage` | none | `SELECT survey_id, MIN(entryStartDateTime) AS first_start, MAX(entryEndDateTime) AS last_end, SUM(entryEndDateTime IS NULL) AS open_count, COUNT(*) AS deployment_count FROM deployment WHERE survey_id IS NOT NULL GROUP BY survey_id` | 200 `{"surveys": [rows]}` |
| `GET /tm-internal/surveys/:id/events` | path `id` (validated) | `SELECT COUNT(*) AS event_count, MIN(start_time) AS first_event, MAX(start_time) AS last_event FROM events WHERE deployment_id IN (SELECT id FROM deployment WHERE survey_id = $survey_id)` | 200 `{"survey_id", "event_count", "first_event", "last_event"}` |
| `POST /tm-internal/deployments/precision` | JSON body `{"precision": "none"|"1"|"2"}` (validated) | for `1`/`2`: `UPDATE deployment SET lat = ROUND(lat, $p), lon = ROUND(lon, $p), location_precision = $p WHERE location_precision > $p`; for `none`: `UPDATE deployment SET lat = NULL, lon = NULL, location_precision = NULL WHERE lat IS NOT NULL OR lon IS NOT NULL` | 204 |

`events.start_time` is the event's start in Unix seconds (the events INSERT's `$start_time`). Invalid input → 400 `{"error": "bad_request", "detail": "<which value>"}` with no sqlite node reached. The snapshot endpoint from design section 6 is not in this plan; it ships with the exact-location export in plan 3.

- [ ] **Step 1: Write the failing tests**

```python
TM_INTERNAL_PATHS = {"/tm-internal/status", "/tm-internal/deployments", "/tm-internal/surveys/usage",
                     "/tm-internal/surveys/:id/events", "/tm-internal/deployments/precision"}

def test_every_tm_internal_endpoint_checks_the_token_first(): ...
    # the http in nodes' urls == TM_INTERNAL_PATHS; each one's first wire target is a function whose func equals
    # cbc268130cc14c58's func, with outputs 2, and whose second output reaches an http response with statusCode "401"

@needs_node
@pytest.mark.parametrize("name, msg, ok", [
    ("tm-internal: validate survey query", {"req": {"query": {"survey_id": "3f9a1c2e-si"}}}, True),
    ("tm-internal: validate survey query", {"req": {"query": {"survey_id": "x' OR 1=1"}}}, False),
    ("tm-internal: validate survey path", {"req": {"params": {"id": "3f9a1c2e-si"}}}, True),
    ("tm-internal: validate survey path", {"req": {"params": {"id": "3f9a1c2e"}}}, False),
    ("tm-internal: validate precision", {"req": {}, "payload": {"precision": "2"}}, True),
    ("tm-internal: validate precision", {"req": {}, "payload": {"precision": "3"}}, False),
])
def test_tm_internal_validators(name, msg, ok): ...
    # two outputs: ok → output 1 with msg.params == {"$survey_id": "3f9a1c2e-si"} for the survey validators, and for
    # precision msg.params == {"$p": 2} and msg.precision_none False ("none" → params {} and precision_none True);
    # not ok → output 2 with msg.statusCode 400 and payload == {"error": "bad_request", "detail": <value name>}

def test_precision_rewrite_uses_two_statements(): ...
    # two prepared sqlite nodes named "rewrite precision" and "rewrite precision to none", each reached from the
    # validator through a switch on msg.precision_none; both have mydb TMDB
```

- [ ] **Step 2: Run to verify they fail.** Expected: FAIL (no such http in nodes).

- [ ] **Step 3: Build the four chains**

Each: `http in` → token check (a copy of `cbc268130cc14c58`'s `func`, named "tm-internal: check token") → validator function (two outputs) → prepared sqlite (`mydb` TMDB) → a shaping function (`msg.payload` into the response object; `msg.statusCode` 204 and empty payload for the POST) → `http response`; validator output 2 → `http response` 400; token output 2 → `http response` 401. The precision chain has a `switch` on `msg.precision_none` between the validator and its two sqlite nodes. Set `msg.params` in the validator. Node names as the tests say.

- [ ] **Step 4: Run every off-device check** (as Task 3 Step 4). Expected: PASS; the new prepared statements appear in `test_flow_sql_compiles_against_schema`.

- [ ] **Step 5: Commit**

"Add per-survey /tm-internal endpoints: deployments, usage, events, precision rewrite".

---

### Task 6: Docs

**Files:**
- Modify: `docs/data-and-payloads/data-overview.md` (Privacy paragraph, the table row for `deployment`, the `deployment` section), `docs/configuration/node-red-config.md` (the `deployment` section), `docs/setup-guide.md` (step 4), `container/node-red-tm/schema/README.md`, `CLAUDE.md` (the `init-config` sentence), `.github/PULL_REQUEST_TEMPLATE.md` is not changed; the PR body carries the release note.

- [ ] **Step 1: Write the pages**

- `data-overview.md`: the `deployment` row says "No: the location is rounded to about 10 km (one decimal place) by default, and never finer than about 1 km"; the `deployment` section documents `survey_id` ("the place; one id per place the device has been used at, with no coordinates in it") and `location_precision`, says `lat`/`lon` are rounded to `database_precision` or empty, and adds the principle from design section 15 in one sentence: the database holds shareable data only.
- `node-red-config.md`: `survey_id` and `database_precision` rows in the `deployment` table (values, defaults, "a change of `survey_id` or a sensor's `bearing` starts a new deployment; a change of `lat`/`lon` does not"); `lat`/`lon` "optional; five decimal places at most; stored rounded"; a sensor's `deployment:` block takes `bearing` only (a `lat`/`lon` there is no longer read; the location is per unit); drop "Four decimal places give address-level accuracy"; remove the sentence "A `deployment` without `lat` or `lon` isn't recorded".
- `setup-guide.md` step 4: the location is optional; what to set when the device is used in one place and never shared; describe the two new keys in one sentence each; the SSH instructions stay until plan 3 moves them to the Location page.
- schema README: a sentence under "Check drift reports" naming the legacy `deployment` shape and that 0002 applies to it; the Testing-on-a-Pi expectations mention `tmdb-v1-*.sqlite` as where the exact rows are kept and that it is the operator's to delete.
- `CLAUDE.md`: "It also records deployments (lat/lon/bearing)" → "It also records deployments (survey id, bearing, rounded coordinates)".

- [ ] **Step 2: Build the docs**

Run: `~/.venvs/tm-docs/bin/mkdocs build --strict`
Expected: no warnings.

- [ ] **Step 3: Commit**

"Document survey ids, stored precision, and the rounding at upgrade".

---

### Task 7: Device tests and the Pi plan

**Files:**
- Modify: `script/devpi/tests/test_dataflow.py`
- The Pi plan is recorded with `tmdev.py check`, not committed.

- [ ] **Step 1: Add device tests (pii_free units only, via `node_red_config` / `require_pii_free`)**

```python
def test_deployment_rows_are_never_finer_than_two_decimals(host, codedir, codeowner, expect): ...
    # runuser sqlite3 query: SELECT count(*) FROM deployment WHERE lat IS NOT NULL AND (ROUND(lat, 2) != lat OR ROUND(lon, 2) != lon) → 0
    # and SELECT count(*) FROM deployment WHERE (lat IS NULL) != (lon IS NULL) → 0

def test_open_deployments_carry_the_configured_survey(host, codedir, codeowner, node_red_config): ...
    # skip when config deployment.survey_id is empty; else every row with entryEndDateTime IS NULL has that survey_id

def test_schema_current  # unchanged: --check exits 0 at version 2
```

- [ ] **Step 2: The Pi plan (`tmdev.py check start` with these items, run before the PR opens)**

1. Upgrade a pii_free bench unit that holds rows at five decimal places, from current `dev`: journal shows `backed up … tmdb-v1-…`, `applied 0002_deployment_survey.sql`, `migrated … from version 1 to 2`, no new `DRIFT`; record the migration time and the database size; `--check` exits 0.
2. After the upgrade, with no `survey_id` in `config.yml`: the open rows are unchanged (same ids), rounded to one decimal; events keep arriving with those ids.
3. Set `survey_id` in `config.yml` to a fresh id: open rows without a survey are adopted (same ids, new survey id), the status endpoint reports it; set a different id: new rows, old ones closed; edit `lat` only: nothing changes.
4. Set `database_precision: '2'` then `'none'`: no new rows; `POST /tm-internal/deployments/precision` with `none` nulls every coordinate; `GET .../surveys/usage` and `.../surveys/<id>/events` answer; a malformed id answers 400; no token answers 401.
5. Fresh install on a second card: version 2 straight away, no backup directory, rows with NULL coordinates and NULL survey id until a survey is set.
6. `tmdev.py test <host>`: the data-flow tests pass.

- [ ] **Step 3: Commit**

"Add device tests for rounded deployment rows and the configured survey".

---

### Task 8: Pull request

- Target `feature/tm-control-status-system/201` (retarget to `dev` when PR 269 merges, per the stacked-PR routine).
- Body: what changes in tmdb at upgrade and where the exact rows went (the release note paragraph, to be copied into the release), the migration timings from Task 1 Step 6 and the Pi, the index decision, the Pi plan's results, closes issues 250 and 254, the "Docs" list from Task 6, and the "AI assistance" section. Say that `config.yml` grows two keys, that the Location page and sharing follow in later PRs, and that until then the survey id is set by hand.
- No coordinates beyond the Portland example.
