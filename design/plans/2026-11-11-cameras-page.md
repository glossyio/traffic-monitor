# Cameras page: neutral camera names, and `sensors.cameras` kept in step with Frigate

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give admins a Cameras page that keeps `sensors.cameras` in `config.yml` in step with Frigate's cameras and sets each camera's record, radar, and plates settings, and make the `sensors.cameras` key a neutral name so that Frigate's hand-written camera name never enters `tmdb.sqlite` or anything shared.

**Architecture:**
- Node-RED maps Frigate's camera name to the `sensors.cameras` key at one node, capture-events' "append config". "init config defaults" builds the map (and the pickers' labels) as globals of their own, outside `global.config`, because `config` is uploaded. Everything downstream of "append config" carries the key. The same tasks fix issues 54, 255, and 249, make the deployment engine close the row of a sensor that left the file, and refill the dashboard pickers on every config load.
- tm-control gets a `cameras` backend module: `names.py` (the neutral name), `state.py` (the one comparison of Frigate's cameras with the file's entries, which the Status checks also use), and `router.py` (`/api/v1/cameras`). The edits to `config.yml` are new methods on the existing `NodeRedConfig`, saved through the existing round-trip writer.
- The Status checks compare by `frigate_camera`, link to the page with the existing `link` fix, and Copy diagnostics replaces Frigate's camera names.
- The UI gets a `cameras` module: the page and one edit dialog, in the conventions of the Location page.

**Tech Stack:** Python 3.11 (FastAPI, pydantic 2, ruamel.yaml; no new dependency), Node-RED 5.0.8 flows (function and change nodes, JSONata), Vue 3 + Vuetify 3 + TypeScript (Vitest, `openapi-fetch`; no new npm dependency), Material for MkDocs, the dev-Pi tooling (`script/devpi/tmdev.py`).

**Spec:** the Cameras page design (not yet published; the public record is [issue 295](https://github.com/glossyio/traffic-monitor/issues/295) and this plan). Its "(maintainer)" items stand; where this plan goes beyond the design, the "Decisions" list says so, and the PR says so too rather than picking silently.

**Status:** written 2026-11-11 against `dev` at `e1b353f`, and implemented on its branch; this file was added in the PR that implements it. Two changes made during implementation are written into the tasks below: the API's schemas are `CameraRow` and `CameraRadar` (first written as `Row` and `RadarOut`, names a later module's schema could take), and the docs' nav lists Cameras before "Places and location", as the app's menu does. After the bench run, the maintainer's review changed the page beyond this plan, and the tasks below don't say so: each row shows **Frigate detection** and **Database capture** (the switch first called "Record events"), the settings dialog sets Frigate's detection through Frigate's own API (`PUT /cameras/{name}/frigate-detection`), a Frigate camera that is off and that no entry points at isn't listed, the Frigate link reads "to add a camera or change a camera's name, streams, or zones", a zone turned off in Frigate warns like a missing one, each row carries a box for each problem the Status checks report about it (with a count above the list, and a zones box linking to Frigate's masks and zones settings at that camera), and each row is an expansion panel that opens to its settings form in place of the Edit button and the dialog. A second review of the whole branch then changed three more things the tasks below don't say: the detection switch is audited as `camera.detection_on` or `camera.detection_off`; `set_camera`, `point_camera`, and `rename_camera` refuse an entry that carries a YAML anchor or is shared with another entry through an alias (500 `config_error`); and a Frigate camera that no entry points at is `not_paired` only while Frigate's detection is on for it. Branch: `feature/cameras-page/295`, off `dev`; [issue 295](https://github.com/glossyio/traffic-monitor/issues/295) is the public stub issue for this work (opened 2026-11-11), and this plan points at it. The open Wi-Fi PRs (290, 293) don't touch these files apart from the regenerated `openapi.json` and `schema.d.ts`; whichever merges second regenerates them.

**Models:** implementers on Sonnet 5.5, except Tasks 1, 3, and 4, which are marked tricky (Opus 5.5). Per-task reviews on Sonnet 5.5. UI tasks (8, 9) load `frontend-design` and the superpowers TDD and verification skills; the spec's constraint (conventional Vuetify, the Location page's look) wins over any design flourish. Stop for the maintainer after Task 3 (the flows are reviewable alone) and before Task 11.

**Decisions made while writing this plan** (calls, open to change):
1. **Three globals, all set by "init config defaults" as its last statements** (after everything that can throw, so a rejected load leaves the old ones): `frigate_cameras` (`{<Frigate's name>: <key>}`), `camera_labels` (`{<key>: <label>}`), and `tm_warned` (`{}`, the once-per-load warning memory). Nothing is added to `msg.payload`, which becomes `global.config` and `config_tm`.
2. **The regions default lives in Plate Recognizer's "format http request" node**, not in "init config defaults": a file with no `addons` block needs no change there.
3. **One comparison.** `modules/cameras/state.py::compare` is used by the page and by `config.cameras` and `config.zones`, so the two can't disagree.
4. **A write answers with the page's whole new state** (`CamerasState`), so the page needs no second request.
5. **The three config helpers move** from `modules/location/router.py` (`_load_config`, `_save`, `_config_error`) to `modules/location/access.py` as `load_config`, `save_config`, `config_error`, and both routers import them.
6. **A duplicate entry** (a second entry naming a Frigate camera an earlier entry names) can be removed on the page, like an entry whose Frigate camera is gone.
7. **The fake status fixture's `config.cameras` becomes the error with the link**, so the link shows in fake mode.
8. **`FakeNodeRed` mirrors the engine's new rule**, as it mirrors the others.

**Where `dev` left things that this plan touches:**
- Flows (`container/node-red-tm/data/flows.json`), by node id:
  - init-config: `94136e5a6f092bb6` "init config defaults" (ends `return msg;`, feeds `b0252bd49dc8e61d`, which sets `global.config`, and link out `2fa46892748adc43`, which carries the same object to ThingsBoard and capture-radar); `689b64c16a889e0a` "deployment engine" (reads `msg.sensors` and `msg.sqlActiveDeployments`; helpers `closeRow`, `insertRow`, `decide`; `openRows` keyed `<type>.<name>`); catch `99132403b74d7a50` records an error passed with `msg` into `tm_status.config.errors`.
  - capture-events: `8eaa1d06a29a5d2b` "append config, deployment properties" (input `msg.frigate_event` = Frigate's `after`; sets `msg.enabled`, `msg.radarEnabled`, `msg.frigate_event.radarName` and `.deployment_id`; feeds switch `627ba0f672680054` "camera enabled?"); `a8aeffd2e5bc17f2` "event finalize output" (`camera: msg.frigate_event.camera`). The tab's catch `056bd6503d1c42c6` sends errors to a debug node only.
  - plate-recognizer: `ce5360091646c733` "format http request" (constant `camera_id` and regions), `f76c2b5b2b99096a` "write params for plate_recognizer insert" (`camera_id` from the API's answer), switch `b8705f8be97656d3` (reads `payload.camera`).
  - thingsboard: `9941048ea93dc79c` "format init-config client-side attributes" (`config_tm: msg.payload`, the live config object).
  - ui-monitoring: inject `e3b795e05d7650b2` → change `f50a7968e032532a` "set cameras, default to index 0" → `ui_dropdown` `bb08a223f0aaef0f`; function `eb140f61419c6a08` "structure frigate api/summary" compares Frigate's `myItem.camera` with `flow.camera_selection`. Dashboard 2 - Monitoring: inject `22bc03eebc06aa57` → change `2e49ae46131b1b63` → `ui-dropdown` `3132d36d148e80d2`.
- Flow tests (`script/tests/test_node_red_flows.py`): `run_functions(steps, env=None, context=None)` runs `(node, msg)` steps under node with one shared dotted-key `global`, records `node.error/warn/log` as `[level, text, msg_given]`, and returns `{"results": [{"result", "logged"}], "global": {...}}`; there is no `flow` object. `named(flows, name)`, `INIT_DEFAULTS`, `SET_CONFIG`, `new_device_config()`, `engine(sensors, open_rows, deployment)` with `.close/.insert/.rewrite/.written()/.payload`, `engine_sensors()`, `open_row(...)`, `camera_row()`, `radar_row()`, `ENGINE_PLACE`, `needs_node`.
- tm-control backend: `modules/location/config.py::NodeRedConfig` (`_file.data` is a ruamel `CommentedMap`; `set_sensor_bearing`; `save() -> bool`, `ConfigError` codes); `adapters/yamlfile.py` (`RoundTripFile`, `put_after`, `blank_line_after`, backups `config.yml.<stamp>.bak`, `KEEP_BACKUPS = 10`, `read_config(path) -> ConfigRead(data, problem, ...)`); `modules/location/places.py::Places` (`survey_bearings` keyed `(survey_id, sensor_type, sensor_name)`); `modules/location/router.py` (the write pattern: `with app_state.reconcile_lock`, load, edit, save, then the store, then `Audit(...).record(admin.id, action, detail)`); `modules/apps/contracts.py` (`cameras_in_config`, `zones`, `radar_names`, `ZONES`, `env_radar_names(manifest)`, `_sensors`, `_enabled`, `listed`); `modules/apps/probes.py` (`frigate_config(context)`, `frigate_safe_mode(config)`, `frigate_cameras(config)` which drops `enabled: false`, `mapping`, `config_yml(context)`); `adapters/frigate.py::config()`; `adapters/nodered.py::NodeRed.report()` (the `/tm-internal/status` body: `radars.<name>.port_open`); `modules/system/diagnostics.py::build` (ends `redact(text, secret_values(app_state))`); `adapters/redact.py` (`REDACTED`, `redact(text, values)`); `fake.py` (`frigate_answer(settings)`, `FakeNodeRed._engine`, `seed_config`); `manifest.options["plate_recognizer"]`; `app_state.config_path`.
- Backend tests: `tests/conftest.py` (`claimed_client` in fake mode with the seeded `fixtures/node_red_config_ok.yml`: camera `picam_h265` and radar `TM_RADAR_SERIAL_PORT_00`, both enabled; `apps` + `device_client` for the checks, with `edit_json(url, fn)` and `edit_config_yml(fn)`); `tests/test_api_surveys.py` is the pattern for an admin-only API (`ORIGIN`, `JSON_HEADERS`, `ADMIN`, `VIEWER`, `test_no_coordinate_in_any_log_line`); `tests/test_contract_checks.py`; `tests/test_api_status.py` pins the fake report's fix kinds and link hrefs; `tests/test_openapi_document.py` fails until `python -m tm_control dump-openapi > tm-control/ui/src/api/openapi.json && (cd tm-control/ui && npm run api:generate)`.
- UI: `src/modules/location/index.ts` (an `adminOnly` route and nav item), `src/modules/index.ts` (`MODULES` in menu order), `src/modules/location/LocationPage.vue` (load, error, 409-reload pattern), `src/components/ConfirmDialog.vue`, `api/client.ts` (`api`, `messageOf`), `tests/mount.ts`, `tests/fake-api.ts` (`signedIn(user, answers)`, `ADMIN`, `VIEWER`, `apiError`), `tests/router.spec.ts`.
- Device tests: `script/devpi/tests/test_web.py` (`VIEWER_ACTIONS`, `CONFIG_CHECKS`, `admin_session`).
- Docs: `docs/use/location.md` (a page's shape), `docs/configuration/node-red-config.md` (lines 13 to 16, 64 to 73, and `## addons.plate_recognizer`), `docs/add-ons/plate-recognizer.md` (line 60), `docs/data-and-payloads/events-payload.md` and `data-overview.md`, `docs/ui/monitoring.md`, `docs/use/device-health.md`, `docs/development/tm-control.md`, `mkdocs.yml` (`nav:` under "use/").

## Global Constraints

- Neutral name: `^camera_[1-9][0-9]*_[0-9a-f]{6}$`, for example `camera_1_3fa9c2`. Letters, digits, and underscores only.
- `frigate_camera` missing, empty, or not a string means "Frigate's name is the key". No migration of `config.yml`, tmdb, or `state.sqlite`; `config.yml.j2` is not changed.
- Frigate's camera name is never written to a log line, an audit row, or an error message by tm-control or Node-RED, and never placed in `msg.payload` after "append config", in `global.config`, or in anything sent to ThingsBoard, MQTT `tm/event(s)`, or Plate Recognizer. Audit detail is the key only. It may be shown on the device behind the login (the page, the Status checks, the pickers).
- Example names in tests, docs, and screenshots are made up: `oak_ave_wide`, `oak_ave_tele`, `main_st`. Never a real site's camera name.
- `config.yml` is written only through `NodeRedConfig`/`RoundTripFile` with `mapping_indent=4`: comments, key order, and quoting kept; a backup beside the file; atomic replace; a changed file → 409 `config_changed`. Every write holds `app.state.reconcile_lock`.
- tm-control never opens `tmdb.sqlite`, and never writes Frigate's config for a camera.
- `flows.json` is edited programmatically and re-serialised with `json.dumps(flows, indent=4, ensure_ascii=False)` and no trailing newline; existing nodes keep their ids; new nodes get fresh 16-hex ids; no `CREATE`/`ALTER`/`DROP` in any flow SQL.
- No new fix kind: the checks use `Fix(kind="link", href="/cameras", text="Open the Cameras page")`.
- Every commit ends with the trailer block from the repo's `CLAUDE.md` (Assisted-by / AI-Model / AI-Effort / AI-Role); never `Co-Authored-By`. Docs follow "Writing docs" in `docs/development/contributing.md`. Nothing public names a device.
- Off-device checks before each commit, from the repo root in the dev venv: `python -m pytest container/node-red-tm/schema/tests script/tests tm-control/backend/tests`; for UI tasks also the UI build and Vitest in the pinned Node image (`CLAUDE.md`, Commands); for docs changes `~/.venvs/tm-docs/bin/mkdocs build --strict`.

## Review Focus

1. **Frigate is restarting or in safe mode when the admin acts** (a rename needs Save & Restart, so this is the usual moment). The page must not read "no cameras" as "every camera is gone": no Remove and no Point are offered, the writes that need the comparison answer 409 `frigate_unavailable`, and settings stay editable. Tests in Task 5 (`test_safe_mode_offers_no_actions`) and Task 6 (`test_remove_is_refused_while_frigate_is_down`).
2. **Odd shapes under `sensors.cameras`:** the block missing or empty (`cameras:`), an entry with nothing under it (`main_st:`), `frigate_camera:` empty or a number. Node-RED treats an empty entry as a camera that is off and never throws; the writer creates what is missing. Tests in Task 1 (`test_append_config_survives_an_empty_entry`) and Task 4 (`test_add_camera_creates_a_missing_cameras_block`).
3. **Two admins, or two cameras renamed at once:** the confirm on screen is stale by the time it is sent (the target was pointed at by another entry, or the file changed). 409 `cameras_changed` or `config_changed`, nothing written, no backup made. Test in Task 6 (`test_point_at_a_camera_another_entry_took_is_refused`).
4. **A busy road and an unlisted camera:** hundreds of events a minute from a Frigate camera no entry points at produce one warning per config load, not one per event. Test in Task 1 (`test_unknown_camera_warns_once_per_config_load`).
5. **A Frigate name that is an everyday word or has regex characters** (`front`, `a.b`): Copy diagnostics replaces whole words only and escapes the name. Test in Task 7 (`test_camera_names_are_replaced_as_whole_words`).

---

### Task 1: The name map, and "append config" that never throws (issues 54 and 255) — tricky

**Files:**
- Modify: `container/node-red-tm/data/flows.json` (nodes `94136e5a6f092bb6`, `8eaa1d06a29a5d2b`)
- Test: `script/tests/test_node_red_flows.py`
- Docs: `docs/configuration/node-red-config.md`, `docs/data-and-payloads/events-payload.md`, `docs/data-and-payloads/data-overview.md`

**Interfaces:**
- Produces: `global.frigate_cameras` (`{<Frigate's name>: <key>}`, first entry in file order wins), `global.camera_labels` (`{<key>: "<key>"}` or `"<key> (<Frigate's name>)"` when they differ), `global.tm_warned` (`{}` after each load). After "append config", `msg.frigate_event.camera` is the key.

- [ ] **Step 1: Write the failing tests.** Add `APPEND_CONFIG = "8eaa1d06a29a5d2b"` and a helper `append_config(config, camera, context=None)` that runs "init config defaults" on `config` and then "append config" on `{"frigate_event": {"camera": camera, "id": "1.0-abc"}, "payload": {}}` with `global.config` set to the first step's payload, returning the second step and the global context. Tests, all `@needs_node`:

```python
def test_init_defaults_maps_frigate_names_to_keys():
    # cameras: camera_1_3fa9c2 {frigate_camera: oak_ave_wide}, picam_h265 {} , main_st {frigate_camera: ""}
    assert context["frigate_cameras"] == {"oak_ave_wide": "camera_1_3fa9c2", "picam_h265": "picam_h265", "main_st": "main_st"}
    assert context["camera_labels"] == {"camera_1_3fa9c2": "camera_1_3fa9c2 (oak_ave_wide)", "picam_h265": "picam_h265", "main_st": "main_st"}
    assert context["tm_warned"] == {}
    assert "frigate_cameras" not in step["result"]["payload"] and "camera_labels" not in step["result"]["payload"]

def test_a_duplicate_frigate_camera_is_a_config_error_that_names_only_keys():
    # camera_1_3fa9c2 and camera_2_b07e11 both frigate_camera: oak_ave_wide
    assert context["frigate_cameras"] == {"oak_ave_wide": "camera_1_3fa9c2"}
    [(level, text, with_msg)] = [entry for entry in step["logged"] if "same Frigate camera" in entry[1]]
    assert (level, with_msg) == ("error", True) and "oak_ave_wide" not in text
    assert "camera_1_3fa9c2" in text and "camera_2_b07e11" in text

def test_append_config_records_the_key_not_frigates_name():
    assert step["result"]["frigate_event"]["camera"] == "camera_1_3fa9c2"
    assert step["result"]["enabled"] is True and step["result"]["radarEnabled"] is True
    assert "oak_ave_wide" not in json.dumps(step["result"])

def test_an_event_from_an_unlisted_camera_is_dropped_without_throwing():     # issue 54
    assert step["result"] is None

def test_unknown_camera_warns_once_per_config_load():
    # three events from two unlisted cameras in one run_functions call: one warning, which names no camera
    assert [text for level, text, _ in all_logged if level == "warn"] == [UNLISTED_WARNING]

def test_a_missing_radar_is_treated_like_a_disabled_one():                   # issue 255
    # camera_radar: TM_RADAR_SERIAL_PORT_03, which sensors.radars doesn't have
    assert step["result"]["enabled"] is True and step["result"]["radarEnabled"] is False
    assert "radarName" not in step["result"]["frigate_event"]
    assert [level for level, text, _ in step["logged"] if "TM_RADAR_SERIAL_PORT_03" in text] == ["warn"]

def test_append_config_survives_an_empty_entry():
    # sensors.cameras.main_st is null: the event is dropped by "camera enabled?" (msg.enabled is not true), no throw
    assert step["result"] is not None and step["result"].get("enabled") is not True

def test_a_new_config_load_warns_again():
    # a second "init config defaults" run resets tm_warned
```

`UNLISTED_WARNING = "An event from a Frigate camera that config.yml doesn't list was dropped. Open the control app's Cameras page."`

- [ ] **Step 2: Run them and see them fail.** `python -m pytest script/tests/test_node_red_flows.py -k "frigate or append_config or unlisted or unknown_camera or missing_radar or config_load" -v`. Expected: FAIL (no `frigate_cameras` in the context; `TypeError` from the node).

- [ ] **Step 3: Edit "init config defaults".** Before `return msg;`, build the two maps from `msg.payload.sensors.cameras` (an entry that isn't an object counts as `{}`; `frigate_camera` is used only when it is a non-empty string) and call `global.set("frigate_cameras", …)`, `global.set("camera_labels", …)`, `global.set("tm_warned", {})`. A duplicate: `node.error("Node-RED config.yml: sensors.cameras.<second> names the same Frigate camera as sensors.cameras.<first>; ignoring <second>.", msg)`. The existing sensors loop must also stop throwing on a `null` entry under `sensors.cameras` (skip it).

- [ ] **Step 4: Rewrite "append config".**
  - `const key = (global.get("frigate_cameras") || {})[msg.frigate_event.camera];` Not found: warn `UNLISTED_WARNING` once (`tm_warned.unlisted`), `return null`.
  - Set `msg.frigate_event.camera = key`, then read `config.sensors.cameras` by key from the object (not by dotted path), treating a non-object entry as `{}`.
  - `camera_radar` set but no object under `sensors.radars`: warn once per radar name (`tm_warned["radar:" + name]`) with `` `Camera ${key} is paired with radar ${name}, which isn't in config.yml; recording its events without a radar.` ``, and leave `radarEnabled` false.
  - Everything else as today (`deployment_id`, `msg.enabled`).

- [ ] **Step 5: Run the tests.** Same command; expected: PASS. Then the whole file and `python3 -m json.tool container/node-red-tm/data/flows.json >/dev/null`.

- [ ] **Step 6: Docs.** `node-red-config.md`: add the `frigate_camera` row to the camera table ("Frigate's name for this camera, when it differs from the entry's name. It stays on the device."), say the entry's name is what is recorded and shared, replace line 16's "records no events" with the new behaviour, and replace the rename paragraph (line 66) with a pointer to the Cameras page (the page's doc lands in Task 10; link it then). `events-payload.md`: `camera` is the camera's name in `config.yml`. `data-overview.md`: `sensorName` likewise. Run `mkdocs build --strict`.

- [ ] **Step 7: Commit.** `Map Frigate's camera names to config.yml's at one node, and stop it throwing (#54, #255)`

### Task 2: Plate Recognizer, `config_tm`, and the node that asks Frigate by name (issue 249)

**Files:**
- Modify: `container/node-red-tm/data/flows.json` (nodes `ce5360091646c733`, `f76c2b5b2b99096a`, `9941048ea93dc79c`, `eb140f61419c6a08`)
- Test: `script/tests/test_node_red_flows.py`
- Docs: `docs/add-ons/plate-recognizer.md`, `docs/configuration/node-red-config.md`

**Interfaces:**
- Consumes: `global.frigate_cameras` and `msg.frigate_event.camera` (the key) from Task 1.
- Produces: `run_functions(steps, env=None, context=None, flow=None)`: the harness gains a `flow` object with `get`/`set` over a dict.

- [ ] **Step 1: Write the failing tests** (`@needs_node`):

```python
def test_plate_recognizer_is_sent_the_cameras_key_and_the_configured_regions():
    # msg.frigate_event.camera = "camera_1_3fa9c2"; config.addons.plate_recognizer.regions = ["gb"]
    assert payload["camera_id"] == {"value": "camera_1_3fa9c2"} and json.loads(payload["regions"]["value"]) == ["gb"]

@pytest.mark.parametrize("regions", [MISSING, None, [], "us", [1, 2]])
def test_plate_recognizer_regions_default(regions):
    assert json.loads(payload["regions"]["value"]) == ["us", "us-or", "us-wa"]

def test_the_plate_row_stores_the_cameras_key():
    # the API's answer echoes camera_id "something-else"; the row takes msg.frigate_event.camera
    assert step["result"]["payload"]["camera_id"] == "camera_1_3fa9c2"

def test_config_tm_has_no_frigate_camera_and_leaves_the_config_alone():
    assert "oak_ave_wide" not in json.dumps(step["result"]["payload"])
    assert step["result"]["payload"]["config_tm"]["sensors"]["cameras"]["camera_1_3fa9c2"]["enabled"] is True
    assert msg_in["payload"]["sensors"]["cameras"]["camera_1_3fa9c2"]["frigate_camera"] == "oak_ave_wide"  # not edited in place

def test_the_frigate_summary_chart_follows_the_selected_cameras_key():
    # flow.camera_selection = "camera_1_3fa9c2"; Frigate's summary rows name oak_ave_wide and oak_ave_tele
    # only oak_ave_wide's counts are charted
```

Also a structure test: after reading every node whose `url` or `func` calls Frigate's API (`frigate:5000`), list here in a comment the ones that pass a camera name, and assert each reads `frigate_cameras`. If `eb140f61419c6a08` is the only one, the comment says so.

- [ ] **Step 2: Run and see them fail.** `python -m pytest script/tests/test_node_red_flows.py -k "plate or config_tm or summary" -v`.
- [ ] **Step 3: Implement.** Add `flow` to `HARNESS` and `run_functions`. `ce5360091646c733`: `camera_id` from `msg.frigate_event.camera`; regions from `global.get("config.addons.plate_recognizer.regions")` when it is a non-empty array of strings, else the default. `f76c2b5b2b99096a`: `camera_id = msg.frigate_event.camera`. `9941048ea93dc79c`: `structuredClone` (or a JSON round trip) of `msg.payload`, delete `frigate_camera` from every camera, then wrap. `eb140f61419c6a08`: compare `(global.get("frigate_cameras") || {})[myItem.camera]` with the selection.
- [ ] **Step 4: Run the tests; expected: PASS.** Whole flows test file, and `container/node-red-tm/schema/tests` (the SQL compile test).
- [ ] **Step 5: Docs.** `plate-recognizer.md` line 60: `camera_id` is the camera's name in `config.yml`; rows written before this release say `picam_h264`. `node-red-config.md`, `## addons.plate_recognizer`: add `regions` (list of Plate Recognizer region codes, default `us`, `us-or`, `us-wa`).
- [ ] **Step 6: Commit.** `Send Plate Recognizer the camera's config.yml name and configured regions (#249)`

### Task 3: The engine closes a removed sensor's row; the pickers follow `config.yml` — tricky

**Files:**
- Modify: `container/node-red-tm/data/flows.json` (node `689b64c16a889e0a`; change nodes `f50a7968e032532a`, `2e49ae46131b1b63`; one new `link out` on init-config and one new `link in` on each dashboard tab)
- Modify: `tm-control/backend/tm_control/fake.py` (`FakeNodeRed._engine`)
- Test: `script/tests/test_node_red_flows.py`, `tm-control/backend/tests/test_api_surveys.py`
- Docs: `docs/data-and-payloads/data-overview.md`, `docs/ui/monitoring.md`

**Interfaces:**
- Consumes: `global.camera_labels` from Task 1.
- Produces: an open deployment row whose `sensorType.sensorName` is not under `msg.sensors` is closed on the next config load, in Node-RED and in `FakeNodeRed`.

- [ ] **Step 1: Write the failing tests.**

```python
@needs_node
def test_engine_closes_the_row_of_a_sensor_that_left_the_file():
    gone = open_row("cameras", "main_st", "n")
    run = engine(engine_sensors(), [camera_row(), radar_row(), gone], ENGINE_PLACE)
    assert [c["params"]["$id"] for c in run.close] == [gone["id"]] and run.insert == []
    assert gone["id"] in {row["id"] for row in run.payload["updatedDeployment"]}

@needs_node
@pytest.mark.parametrize("sensors", [None, "broken"])
def test_engine_closes_nothing_without_a_sensors_object(sensors):
    assert engine(sensors, [camera_row()], ENGINE_PLACE).written() == []

# test_engine_skips_disabled_sensors stays as it is: a listed, disabled sensor keeps its row

def test_the_pickers_refill_on_every_config_load():
    # a link out wired from SET_CONFIG reaches a link in on ui-monitoring wired to f50a7968e032532a,
    # and a link in on "Dashboard 2 - Monitoring" wired to 2e49ae46131b1b63

def test_the_pickers_keep_a_selection_that_is_still_there_and_label_from_camera_labels():
    # both change nodes: the options rule reads $globalContext("camera_labels"); the payload rule reads the tab's
    # camera_selection and falls back to the first key of config.sensors.cameras
```

In `test_api_surveys.py`: `test_the_fake_engine_closes_a_removed_sensors_row` (remove the camera from the seeded file, call `after_config_write()`, the camera's row has an end and no new row starts).

- [ ] **Step 2: Run and see them fail.**
- [ ] **Step 3: Implement the engine rule.** After the per-sensor loop, when `msg.sensors` is an object: for each `openRows` key with no entry at `msg.sensors[type][name]`, `closeRow` every row. Mirror it in `FakeNodeRed._engine`.
- [ ] **Step 4: Implement the pickers.** Options: legacy `ui_dropdown` takes `msg.options` as a list of `{<label>: <value>}`; Dashboard 2.0's `ui-dropdown` takes `msg.ui_update.options` as a list of `{"label", "value"}`. Build both from `camera_labels` (always an array, also for one camera). The value stays the key. The start-up injects stay.
- [ ] **Step 5: Run the tests; expected: PASS.** Whole flows file and the backend suite.
- [ ] **Step 6: Docs.** `data-overview.md`: a sensor removed from `config.yml` ends its deployment. `monitoring.md` (line 14): the pickers follow `config.yml` and show Frigate's name in brackets when it differs.
- [ ] **Step 7: Commit.** `Close a removed sensor's deployment and refill the camera pickers on a config load`

**Stop here for the maintainer's review of the flows.**

### Task 4: Camera edits in `NodeRedConfig`, the neutral name, and the store's rename — tricky

**Files:**
- Create: `tm-control/backend/tm_control/modules/cameras/__init__.py` (empty for now), `tm-control/backend/tm_control/modules/cameras/names.py`
- Modify: `tm-control/backend/tm_control/modules/location/config.py`, `tm-control/backend/tm_control/modules/location/places.py`
- Test: `tm-control/backend/tests/test_cameras_config.py` (new), `tm-control/backend/tests/test_places.py`

**Interfaces:**
- Produces:

```python
# modules/cameras/names.py
NEUTRAL = re.compile(r"camera_([1-9][0-9]*)_[0-9a-f]{6}")
def is_neutral(name: str) -> bool: ...                      # fullmatch
def new_name(existing: Iterable[str], token: Callable[[int], str] = secrets.token_hex) -> str: ...
    # "camera_<N>_<token(3)>": N is one above the highest N among existing neutral names (1 when none);
    # the token is drawn again while an existing neutral name ends with the same six characters

# modules/location/config.py
@dataclass(frozen=True)
class CameraEntry:
    name: str                    # the key
    frigate_camera: str          # the field when it is a non-empty string, else the key
    enabled: bool                # enabled is True
    camera_radar: str | None
    plate_recognizer: bool

class NodeRedConfig:
    def cameras(self) -> list[CameraEntry]: ...             # file order; a non-mapping entry reads as all defaults
    def radars(self) -> dict[str, bool]: ...                # name -> enabled is True
    def add_camera(self, name: str, frigate_camera: str, enabled: bool, camera_radar: str | None, plate_recognizer: bool | None) -> None: ...
    def set_camera(self, name: str, enabled: bool, camera_radar: str | None, plate_recognizer: bool | None) -> None: ...
    def point_camera(self, name: str, frigate_camera: str) -> None: ...
    def rename_camera(self, old: str, new: str) -> None: ...
    def remove_camera(self, name: str) -> None: ...

# modules/location/places.py
class Places:
    def rename_sensor(self, sensor_type: str, old: str, new: str) -> None: ...
```

  `KeyError` for a camera that isn't in the file; `ValueError` when `add_camera`'s or `rename_camera`'s new name is already a key. `camera_radar=None` removes the key; `plate_recognizer=None` leaves the key as it is.

- [ ] **Step 1: Write the failing tests.** In `test_cameras_config.py`, each on a temp copy of `fixtures/node_red_config_ok.yml` (helper `config_text(edit)` to shape it):

```python
def test_new_name_counts_up_and_redraws_a_taken_token():
    assert new_name([], token=lambda n: "3fa9c2") == "camera_1_3fa9c2"
    assert new_name(["camera_4_aaaaaa", "main_st"], token=lambda n: "3fa9c2") == "camera_5_3fa9c2"
    tokens = iter(["aaaaaa", "b07e11"])
    assert new_name(["camera_1_aaaaaa"], token=lambda n: next(tokens)) == "camera_2_b07e11"  # no two cameras share a token
def test_is_neutral():  # camera_1_3fa9c2 yes; camera_1, camera_0_3fa9c2, camera_1_3FA9C2, picam_h265, xcamera_1_3fa9c2x no

def test_cameras_reads_the_field_or_the_key():
def test_add_camera_writes_the_entry_in_key_order():        # frigate_camera, enabled, camera_radar, plate_recognizer
def test_add_camera_creates_a_missing_cameras_block():      # sensors: has no cameras key, and cameras: is empty
def test_set_camera_removes_camera_radar_for_none_and_leaves_plates_for_none():
def test_point_camera_changes_one_line():                   # the saved text differs from the loaded text in that line only
def test_rename_camera_keeps_place_comments_and_subkeys():
    # main_st: between two other entries, a comment above it and one on its enabled line, deployment.bearing 'n'
    # after rename_camera("main_st", "camera_1_3fa9c2"): same position, both comments, frigate_camera: main_st first,
    # every other sub-key as it was
def test_rename_camera_keeps_an_existing_frigate_camera():
def test_remove_camera_takes_its_comment_and_leaves_the_blank_line_layout():
def test_the_edited_file_still_loads_in_safe_mode():        # read_config(path).data has the expected mapping
def test_rename_sensor_moves_every_places_bearing():        # test_places.py: two places; a place that already has the new name keeps that row
```

- [ ] **Step 2: Run and see them fail.** `python -m pytest tm-control/backend/tests/test_cameras_config.py tm-control/backend/tests/test_places.py -v`.
- [ ] **Step 3: Implement.** `rename_camera` re-keys in place on the ruamel `CommentedMap` (`insert` at the old position, and move the old key's entry in `.ca.items` so the comments follow). The `sensors.cameras` block is created like `_deployment_block` creates its block. Blank-line handling follows `put_after` and `blank_line_after`.
- [ ] **Step 4: Run the tests; expected: PASS.** Then the whole backend suite.
- [ ] **Step 5: Commit.** `Add the camera edits to config.yml's writer, and the neutral camera name`

### Task 5: The comparison and `GET /cameras`

**Files:**
- Create: `tm-control/backend/tm_control/modules/cameras/state.py`, `tm-control/backend/tm_control/modules/cameras/router.py`, `tm-control/backend/tm_control/modules/location/access.py`
- Modify: `tm-control/backend/tm_control/modules/cameras/__init__.py`, `tm-control/backend/tm_control/modules/__init__.py` (after `location.module`), `tm-control/backend/tm_control/modules/location/router.py` (imports the three helpers), `tm-control/backend/tm_control/fake.py`, `tm-control/ui/src/api/openapi.json`, `tm-control/ui/src/api/schema.d.ts`
- Test: `tm-control/backend/tests/test_cameras_state.py` (new), `tm-control/backend/tests/test_api_cameras.py` (new)

**Interfaces:**
- Consumes: `CameraEntry`, `NodeRedConfig.cameras()`, `.radars()` from Task 4.
- Produces:

```python
# modules/cameras/state.py
class CameraRow(BaseModel):
    name: str | None                          # the key; None for a Frigate camera no entry points at
    frigate_camera: str
    in_frigate: Literal["on", "off", "absent", "unknown"]   # "unknown" while Frigate is down or in safe mode
    neutral: bool | None                      # is_neutral(name); None when name is None
    duplicate_of: str | None                  # the earlier key that names the same Frigate camera
    enabled: bool | None
    camera_radar: str | None
    plate_recognizer: bool | None
    zones_missing: list[str] | None           # of ZONES; None when the camera isn't in Frigate

def compare(entries: list[CameraEntry], frigate_cameras: dict[str, dict] | None) -> list[CameraRow]: ...
    # entries in file order, then Frigate's unpointed cameras in Frigate's order; frigate_cameras None (down or
    # safe mode) gives every entry in_frigate "unknown" and zones_missing None, and no unpointed rows

class CameraRadar(BaseModel): name: str; in_config: bool; enabled: bool; port_open: bool | None
class CamerasState(BaseModel):
    frigate: Literal["ok", "down", "safe_mode"]
    plates: bool                              # manifest.options.get("plate_recognizer") is True
    rows: list[CameraRow]
    radars: list[CameraRadar]                    # env_radar_names(manifest) order

# modules/cameras/router.py
def cameras_state(request: Request) -> CamerasState: ...    # also what every write returns
# modules/location/access.py
def load_config(app_state) -> NodeRedConfig: ...
def save_config(app_state, config: NodeRedConfig) -> bool: ...
def config_error(error: ConfigError) -> ApiError: ...
# fake.py: frigate_answer's config gains a second camera, "oak_ave_tele", a copy of the fixture's first
```

- [ ] **Step 1: Write the failing tests.** `test_cameras_state.py` (pure): in step; Off in Frigate (`enabled: false`) → `"off"`; an entry whose camera is gone → `"absent"`; an unpointed Frigate camera → a row with `name is None`; a duplicate → `duplicate_of`; `zones_missing` lists what Frigate's `zones` lacks; `frigate_cameras=None` → every entry `"unknown"`, never `"absent"`, and no unpointed rows. `test_api_cameras.py` (on `claimed_client`, in the shape of `test_api_surveys.py`):

```python
def test_a_viewer_and_a_signed_out_caller_are_refused():       # 403 "Only an admin can do this.", 401
def test_get_lists_the_seeded_camera_and_the_fake_frigates_new_one():
    # rows: picam_h265 (in_frigate "on", neutral False, enabled True, camera_radar TM_RADAR_SERIAL_PORT_00,
    # zones_missing []), then name None / frigate_camera "oak_ave_tele"
def test_radars_carry_config_and_port_state():
def test_safe_mode_offers_no_actions(monkeypatch):             # frigate == "safe_mode"; rows are the file's entries, each in_frigate "unknown"
def test_frigate_down_still_lists_the_files_cameras(monkeypatch):
def test_an_unreadable_config_is_a_500_config_error():
```

- [ ] **Step 2: Run and see them fail.**
- [ ] **Step 3: Implement.** Frigate's cameras are `probes.mapping(config.get("cameras"))`, unfiltered; `"off"` is `enabled is False`. In fake mode the config comes from `fake.frigate_answer(settings)`; on a device from `adapters.frigate.config()` (None → `"down"`; `probes.frigate_safe_mode` → `"safe_mode"`). `port_open` comes from `app_state.nodered.report()`, None when Node-RED doesn't answer. Register `Module("cameras", router)`. Regenerate `openapi.json` and `schema.d.ts`.
- [ ] **Step 4: Run the tests; expected: PASS.** Whole backend suite (the Location tests prove the helper move).
- [ ] **Step 5: Commit.** `Add the cameras module: compare Frigate's cameras with config.yml and list them`

### Task 6: The writes

**Files:**
- Modify: `tm-control/backend/tm_control/modules/cameras/router.py`, `tm-control/ui/src/api/openapi.json`, `tm-control/ui/src/api/schema.d.ts`
- Test: `tm-control/backend/tests/test_api_cameras.py`

**Interfaces:**
- Consumes: Tasks 4 and 5.
- Produces, all `require_admin`, all answering `CamerasState`:

| Route | Body | Refuses with |
|---|---|---|
| `POST /cameras` | `{frigate_camera: str, enabled: bool, camera_radar: str \| None, plate_recognizer: bool \| None}` (null writes no plates key) | 409 `cameras_changed` unless `frigate_camera` is a Frigate camera no entry points at |
| `PUT /cameras/{name}` | `{enabled: bool, camera_radar: str \| None, plate_recognizer: bool \| None}` | 404 `not_found`; 422 `validation` (field `camera_radar`) unless the radar is one of the unit's and under `sensors.radars` |
| `POST /cameras/{name}/frigate-camera` | `{to: str}` | 404; 409 `cameras_changed` unless the entry's camera is absent from Frigate and `to` is unpointed |
| `POST /cameras/{name}/neutral-name` | none | 404; 409 `cameras_changed` when the name is already neutral |
| `DELETE /cameras/{name}` | none | 404; 409 `cameras_changed` unless the entry's camera is absent or the entry is a duplicate |

  Every route but `PUT` answers 409 `frigate_unavailable` ("Frigate isn't answering, so its cameras can't be compared. Try again when it is running.") while Frigate is down or in safe mode. `cameras_changed`: "Frigate's cameras or config.yml changed. Reload the page and try again." Audit actions: `camera.add`, `camera.update`, `camera.point`, `camera.neutral_name`, `camera.remove`; the detail is the key (for `neutral_name`, the new one).

- [ ] **Step 1: Write the failing tests** (helper `rekey(old, new)` edits the seeded file so an entry's camera is gone):

```python
def test_add_assigns_a_neutral_name_and_points_it():           # monkeypatch names.secrets.token_hex -> "3fa9c2"; the file has camera_1_3fa9c2 with frigate_camera: oak_ave_tele
def test_add_refuses_a_camera_an_entry_already_points_at():    # 409 cameras_changed, file untouched
def test_put_sets_the_three_settings():
def test_put_with_no_radar_removes_the_key():
def test_put_refuses_a_radar_the_file_doesnt_have():           # 422, field camera_radar
def test_put_leaves_plates_alone_for_null():
def test_point_changes_only_frigate_camera_and_starts_no_deployment():
    # the fake Node-RED's open row for the entry has the same id before and after
def test_point_at_a_camera_another_entry_took_is_refused():
def test_point_is_refused_while_the_entrys_camera_is_still_in_frigate():   # also when it is Off
def test_neutral_name_rekeys_moves_the_bearings_and_starts_a_deployment():
    # the file's key is camera_1_3fa9c2 with frigate_camera: picam_h265; Places has the bearing under the new name;
    # the fake Node-RED closed picam_h265's row and opened one for the new name
def test_remove_only_for_a_gone_or_duplicate_entry():
def test_remove_is_refused_while_frigate_is_down(monkeypatch):  # 409 frigate_unavailable
def test_a_changed_file_is_a_409_and_nothing_is_written(monkeypatch):
def test_every_write_is_audited_with_the_key_only():
def test_no_frigate_name_in_any_log_line_or_audit_row(caplog):  # oak_ave_tele and picam_h265-as-Frigate-name never appear after add, point, neutral-name
def test_a_viewer_is_refused_every_write():
```

- [ ] **Step 2: Run and see them fail.**
- [ ] **Step 3: Implement.** Each write: `with app_state.reconcile_lock:` → `load_config` → `compare` against Frigate now → check the precondition → edit → `save_config` → (neutral-name only) `Places(...).rename_sensor("cameras", old, new)` → audit → `cameras_state(request)`. Regenerate the API files.
- [ ] **Step 4: Run the tests; expected: PASS.** Whole backend suite.
- [ ] **Step 5: Commit.** `Add, point, re-key, remove, and set a camera's settings from the control app`

### Task 7: The Status checks link to the page, and Copy diagnostics replaces Frigate's names

**Files:**
- Modify: `tm-control/backend/tm_control/modules/apps/contracts.py`, `tm-control/backend/tm_control/modules/system/diagnostics.py`, `tm-control/backend/tm_control/adapters/redact.py`, `tm-control/backend/tests/fixtures/status_fake.json`
- Test: `tm-control/backend/tests/test_contract_checks.py`, `tm-control/backend/tests/test_api_status.py`, `tm-control/backend/tests/test_redact.py`, the diagnostics test file (grep `diagnostics` under `tests/`)
- Docs: `docs/use/device-health.md`

**Interfaces:**
- Consumes: `compare`, `CameraRow` from Task 5.
- Produces: `CAMERAS_LINK = Fix(kind="link", href="/cameras", text="Open the Cameras page")` in `contracts.py`; `redact_words(text: str, words: Iterable[str]) -> str` in `adapters/redact.py` (whole words: not preceded or followed by `[A-Za-z0-9_]`; escaped; longest first; empty strings ignored); `camera_names(app_state) -> set[str]` in `diagnostics.py`.

- [ ] **Step 1: Write the failing tests.**

```python
# test_contract_checks.py
def test_cameras_match_through_frigate_camera():                # key camera_1_3fa9c2, frigate_camera picam_h265: ok
def test_a_renamed_camera_is_an_error_with_the_link():          # existing test: now also check.fix == CAMERAS_LINK
def test_a_duplicate_frigate_camera_is_an_error():
def test_an_entry_whose_camera_is_gone_is_a_warning_with_the_link():
def test_record_off_is_a_warning_not_an_error():                # replaces test_disabled_camera_is_an_error
def test_zones_are_checked_through_frigate_camera():
def test_a_missing_or_disabled_radar_is_a_warning_with_the_link():
    # detail says the camera "gets no speed or direction from a radar"; no "dropped", no "#255"

# test_redact.py
def test_camera_names_are_replaced_as_whole_words():
    assert redact_words("front_door: frontage at front. a.b axb", ["front", "a.b"]) == "front_door: frontage at <redacted>. <redacted> axb"

# diagnostics
def test_diagnostics_replace_frigates_camera_names():
    # frigate_camera oak_ave_wide under camera_1_3fa9c2, an unpointed Frigate camera oak_ave_tele, and a backup
    # beside config.yml whose entry said frigate_camera: main_st; a journal line naming all three and picam_h265
    # (an entry whose key is its Frigate name): the three are replaced, picam_h265 and camera_1_3fa9c2 are not
```

`test_api_status.py`: the fake report's link hrefs gain `/cameras`.

- [ ] **Step 2: Run and see them fail.**
- [ ] **Step 3: Implement the checks.** `cameras_in_config` and `zones` go through `compare` (the statuses and order of precedence are in the design, section 6). Text names the key, with Frigate's name in brackets when it differs.
- [ ] **Step 4: Implement the diagnostics.** `camera_names`: every Frigate name that differs from its entry's key, every unpointed Frigate camera, and from each `config.yml.*.bak` beside the file (read with `read_config`, unreadable ones skipped) every `frigate_camera` value and every key that is neither neutral nor a key of the current file. `build` applies `redact_words` after `redact`, and the header gains "Camera names from Frigate are replaced too."
- [ ] **Step 5: Run the tests; expected: PASS.** Whole backend suite.
- [ ] **Step 6: Docs.** `device-health.md`: the Cameras check's meanings and its link; what Copy diagnostics replaces, and the three limits from the design's section 6.
- [ ] **Step 7: Commit.** `Point the camera checks at the Cameras page and keep Frigate's names out of diagnostics`

### Task 8: The Cameras page: the list and the settings dialog

**Files:**
- Create: `tm-control/ui/src/modules/cameras/index.ts`, `CamerasPage.vue`, `CameraEdit.vue`, `rows.ts`
- Modify: `tm-control/ui/src/modules/index.ts` (after `detection`), `tm-control/ui/tests/fake-api.ts`, `tm-control/ui/README.md`
- Test: `tm-control/ui/tests/cameras-page.spec.ts`, `tm-control/ui/tests/camera-edit.spec.ts`, `tm-control/ui/tests/camera-rows.spec.ts`, `tm-control/ui/tests/router.spec.ts`

**Interfaces:**
- Consumes: `GET /cameras`, `PUT /cameras/{name}` and the generated `CamerasState`, `CameraRow`, `CameraRadar` types.
- Produces: `CameraEdit` props `{ row: CameraRow; radars: CameraRadar[]; plates: boolean; adding: boolean }`, emits `save: [{ enabled: boolean; camera_radar: string | null; plate_recognizer: boolean | null }]` and `cancel: []`; `rows.ts`: `rowState(row): 'in-step' | 'off' | 'new' | 'gone' | 'duplicate' | 'unknown'` (`'unknown'` shows the settings and nothing about Frigate), `zonesText(row): string`, `radarChoices(row, radars): { title: string; value: string | null; subtitle?: string; disabled?: boolean }[]`.

- [ ] **Step 1: Write the failing tests.** `camera-rows.spec.ts`: each state; `zonesText` gives "Zones: all four" or "Missing in Frigate: zone_near, zone_far"; `radarChoices` starts with "No radar", marks a radar "off in config.yml", "port closed", or "not set up in config.yml" (disabled), and adds "`<name>` (missing)" for a current value that isn't a radar. `cameras-page.spec.ts`: an admin sees one row per camera with the key in bold and Frigate's name beside it; the intro text; the link to `/frigate/`; "Off in Frigate" on an off camera; the alert when `frigate` is `down` or `safe_mode` and no action buttons then; a load error shows the API's message. `camera-edit.spec.ts`: the three fields; no plates switch when `plates` is false, and `plate_recognizer: null` in the emitted value then; Save emits the edited values; a 422 from the page's PUT shows under the Radar field. `router.spec.ts`: `/cameras` sends a viewer to `/`.

  Copy the page uses: title "Cameras"; intro "Frigate owns each camera: its name, streams, and zones. This page sets what the Traffic Monitor does with it. The name in bold is the one saved with the data. Frigate's name stays on this device."; down "Frigate isn't answering, so its cameras can't be compared. You can still change a camera's settings."; safe mode "Frigate is in safe mode, with no cameras; see the Status page. You can still change a camera's settings."; dialog title "Settings for `<name>`"; fields "Record events", "Radar", "Send plates to Plate Recognizer"; buttons "Cancel", "Save".

- [ ] **Step 2: Run and see them fail.** The Vitest command from `CLAUDE.md`.
- [ ] **Step 3: Implement** in the Location page's conventions (the load, error, and 409-reload pattern; `v-list` rows; one `v-dialog`). Icon `mdiCctv`; nav item and route `adminOnly`. Add the module to the README's module list with one paragraph of design notes.
- [ ] **Step 4: Run the tests and the build; expected: PASS,** `vue-tsc` clean.
- [ ] **Step 5: Commit.** `Add the Cameras page: each camera's settings, with the radar as a drop-down`

### Task 9: The Cameras page: point, add, use a neutral name, remove

**Files:**
- Modify: `tm-control/ui/src/modules/cameras/CamerasPage.vue`, `rows.ts`, `tm-control/ui/tests/fake-api.ts`
- Test: `tm-control/ui/tests/cameras-page.spec.ts`

**Interfaces:**
- Consumes: Task 6's four routes, `CameraEdit` with `adding: true`, `ConfirmDialog`.
- Produces: `rows.ts`: `pointChoices(row, rows): CameraRow[]` (the entries whose camera is gone, for a new row).

- [ ] **Step 1: Write the failing tests.**
  - A new row shows "`<frigate_camera>` is new in Frigate and isn't recorded.", one "Point `<entry>` at this" button per gone entry, and "Add as new".
  - With two new rows and two gone entries, each new row offers both entries.
  - Point confirms with title "Point `<name>` at `<to>`?" and text "Events from `<to>` will be recorded as `<name>`, with the same settings. Nothing already recorded changes.", then posts `{to}`.
  - "Add as new" opens the dialog titled "Add `<frigate_camera>`" with Record events on, No radar, plates off, and posts on "Add".
  - A row whose `neutral` is false shows "Use a neutral name"; its confirm text is "New records will be saved under a name like camera_1_3fa9c2 instead of `<name>`. Records already saved keep the name `<name>`, and the dashboards' charts start again under the new name. A new deployment starts for this camera."
  - A gone or duplicate row shows "Remove"; its confirm text is "Its settings are removed from config.yml. Records already saved are kept."
  - A gone row says "Frigate no longer has `<frigate_camera>`."; a duplicate says "`<duplicate_of>` already records this Frigate camera."
  - A 409 shows the API's message and reloads the list.
  - Each success replaces the list with the answer's rows.
- [ ] **Step 2: Run and see them fail.**
- [ ] **Step 3: Implement.** `ConfirmDialog`'s `confirmColor` is `'error'` only for Remove.
- [ ] **Step 4: Run the tests and the build; expected: PASS.**
- [ ] **Step 5: Commit.** `Point, add, re-key, and remove cameras on the Cameras page`

### Task 10: The page's docs, and the rest that describes cameras

**Files:**
- Create: `docs/use/cameras.md`, phone-width screenshots in `docs/assets/images/` (from fake mode, made-up names)
- Modify: `mkdocs.yml` (`nav:`, before "Places and location", as the app's menu lists them), `docs/configuration/node-red-config.md` (link the page), `docs/setup-guide.md` (lines 74 to 97: the settings are on the page), `docs/use/control-app.md`, `docs/development/tm-control.md` (the module, the comparison, the globals), `CLAUDE.md` (the `tm-control/` bullet, "Cross-component name contracts": Frigate's name matches `frigate_camera`, else the key; the three globals; `/cameras` routes)

- [ ] **Step 1: Write `docs/use/cameras.md`** in `location.md`'s shape: what the page is for; the two names and which one is saved with the data; after renaming a camera in Frigate (Save & Restart, then Point); a new camera; settings; using a neutral name and what it leaves behind; removing an entry; a "What still carries Frigate's name" section with the design's three limits. Follow the Style rules in `docs/development/contributing.md`.
- [ ] **Step 2: Update the other pages.**
- [ ] **Step 3: Verify.** `~/.venvs/tm-docs/bin/mkdocs build --strict`. Expected: no warnings.
- [ ] **Step 4: Commit.** `Document the Cameras page and neutral camera names`

**Stop here for the maintainer.**

### Task 11: Device tests, the Pi test plan, and the PR

**Files:**
- Modify: `script/devpi/tests/test_web.py`
- Create: the PR body from `.github/pull_request_template.md`; last commit: this plan at `design/plans/2026-11-11-cameras-page.md`

- [ ] **Step 1: Device tests.** Add to `VIEWER_ACTIONS`: `("GET", f"{API}/cameras", 403)`, `("POST", f"{API}/cameras", 403)`, `("PUT", f"{API}/cameras/picam_h265", 403)`, `("POST", f"{API}/cameras/picam_h265/frigate-camera", 403)`, `("POST", f"{API}/cameras/picam_h265/neutral-name", 403)`, `("DELETE", f"{API}/cameras/picam_h265", 403)`; the neutral name is sent only after the re-scan guard, as reboot and power-off are, because it would re-key the camera if a viewer got through. Add `test_cameras_page_agrees_with_the_status_check` (admin `GET /cameras`: `frigate == "ok"`, and when `config.cameras` is ok: no enabled Frigate camera without an entry, no duplicate, and no enabled entry whose camera Frigate doesn't have on, the check's own rules).
- [ ] **Step 2: The Pi test plan**, run with `tmdev.py check start|item|status|end` on a `pii_free` bench unit after a full `tmdev.py deploy` (never two hosts at once):
  1. The untouched unit (`picam_h265`, no `frigate_camera`) records events as before; the device suite passes.
  2. Rename the camera in Frigate to `oak_ave_wide` (Save & Restart): the Status check is an error with the link.
  3. Point on the page: new events have `camera = picam_h265`; no new deployment row; `oak_ave_wide` appears in none of the `events` rows, a `tm/event` message, or the Copy diagnostics text.
  4. A second camera block in Frigate, and both renamed: each is paired by hand.
  5. Use a neutral name: new rows say `camera_1_…`; the old deployment row has an end and a new one is open; the Location page shows the bearing under the new name; both pickers show `camera_1_… (oak_ave_wide)` without a Node-RED restart.
  6. Add a camera that is Off in Frigate; edit its settings; pick each radar choice.
  7. An event from a Frigate camera no entry points at: nothing in the catch's debug, one warning in `journalctl -u node-red-tm.service`.
  8. `camera_radar` naming a radar the file doesn't have: the event is recorded with no radar, one warning.
  9. Remove a gone entry: its deployment row closes.
  10. A viewer gets 403 on every write and is sent home from `/cameras`.
  11. Put the unit back: `picam_h265` in both files.
- [ ] **Step 3: The PR.** Base `dev`. "Closes #54, #249, #255" and the stub issue. Fill the template's Docs and "AI assistance" sections. Say where the PR differs from the public issues' wording: 249 asked for the event's camera name and gets the `config.yml` name; 255's missing radar keeps recording. Say what the fresh install default stays (`picam_h265`).
- [ ] **Step 4: Stop.** The maintainer reads the commits and the PR text before anything is pushed.
