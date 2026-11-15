# Location 4: the upload gate and the Sharing page

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Nothing leaves a unit for a ThingsBoard server except what an admin chose on a Sharing page: counts and readings with the location as the database stores it, and, only by a separate recorded choice, the exact location. The page also holds the server's settings and token, so `config.yml` is never edited by hand to share.

**Architecture:**
- Node-RED gets an **upload gate**: one function node on the `thingsboard` tab that every telemetry and attribute message passes before the rate limit. It lets through a fixed list of payload kinds, re-rounds every deployment row to the precision the row was stored at, and adds three attributes from a new `sharing:` block in `config.yml`: `consents`, `exact_location`, and `public_map`. The upload of the settings (`config_tm`) and Backup & Restore to ThingsBoard are removed; both are being reworked separately. A second small node records how the server answered each upload (the status code's class and the time, nothing else) in the status Node-RED already reports to tm-control, which shows it as a "Sharing server" check and on the Sharing page.
- tm-control gets a `sharing` module: `state.sqlite` migration 4 (`sharing_consents`), a versioned notice served like the EULA, a follow step that keeps the `sharing:` block equal to the recorded consents (and records what it finds on an upgraded unit), and `/api/v1/sharing`. It writes the `thingsboard:` and `sharing:` blocks through the existing round-trip writer; Node-RED's watch node does the rest.
- The UI gets a Sharing page (server, token, the choices with an example of what each sends, the notice) whose form is also the last first-run step. The token form moves there from the Device page.

**Tech Stack:** Python 3.11 (FastAPI, pydantic 2, ruamel.yaml, sqlite3 and `csv` from the standard library; no new dependency), Node-RED 5 flows (one new function node), Ansible (the tmsetup role), Jinja2, Vue 3 + Vuetify 3 + TypeScript (Vitest, `openapi-fetch`; no new npm dependency), Material for MkDocs, the dev-Pi tooling (`script/devpi/tmdev.py`).

**Spec:** the location and survey-id design (not yet published; the public record is the privacy design, `design/specs/2026-10-26-location-privacy-design.md`, from PR 260, and [issue 314](https://github.com/glossyio/traffic-monitor/issues/314)), sections 6 (the upload gate and the `sharing:` block), 8, 12, 13, and "Before it goes public". Its "(maintainer)" items stand. Its "(call)" items are kept or changed in "Decisions" below, which also records the maintainer's answers of 2026-11-13. Sections 9 (the map) and 10 (the database copy with exact locations) are later plans; see "Later". Read the design with this plan. Where this plan goes beyond the design, say so in the PR rather than picking silently.

**Status:** written 2026-11-13 against `dev` at `b4a26f1` (plans 1 to 3, entered secrets, the Cameras page, and the Wi-Fi stack are all merged; no PR is open). Branch: `feature/sharing-page/314`, off `dev`; this file was added in the PR that implements it. [Issue 314](https://github.com/glossyio/traffic-monitor/issues/314) tracks this work.

**Decisions** (the maintainer's of 2026-11-13 are marked; the rest are calls, open to change):
1. **Three plans, not one (maintainer).** This plan is the gate, the Sharing page, and the consents. The database copy with exact locations (design section 10) is the next plan, and the map pin and block picker (section 9) the one after. Each ships on its own.
2. **The settings upload and Backup & Restore are removed (maintainer).** The `config_tm` attribute, the two Backup & Restore groups with their legacy-dashboard buttons, and the never-filled `sysinfo_ssid` and `sysinfo_ipv4Address` slots go in Task 1, as one commit. The maintainer reworks backup and the settings upload afterwards; a new upload then joins the gate's list.
3. **The gate is an allow-list.** Telemetry `values` keys: `event`, `radar`, `airquality`, `system_metrics`, `deployments`. Attribute keys: `deployments`, `radarinfo`, and the six `sysinfo_*` keys that remain. Anything else is dropped with one warning per config load that names the key only. A test pins both lists.
4. **The gate re-rounds deployment rows.** The engine already sends what tmdb stores. The gate rounds each row's `lat` and `lon` again, to the row's `location_precision` or the unit's `database_precision`, whichever is coarser, so a later change to the flows can't send a finer point.
5. **The `sharing:` block names the server its choices were made for.** Keys: `target`, `host`, `exact_location`, `public_map`, `notice_version`. The gate sends the exact location only when the block's `host` equals the upload host and the upload URL is https. A hand edit of `thingsboard.host` therefore never carries the exact location to another server, even before tm-control notices the edit.
6. **A missing `sharing:` block means rounded only.** That is the state of an upgraded unit and of a unit after `tmsetup.sh -f`. After `-f` the upload is off, as it is today, and every recorded choice for that server is withdrawn; nothing turns sharing back on.
7. **Consents are recorded in `state.sqlite`; the server's settings live in `config.yml`.** A consent can't be given by editing the file: the follow step writes a hand-set `exact_location: true` back to false. On save, the file is written first and the consent rows second, so a failure between the two leaves less shared, never more.
8. **"Share data" is the upload being on.** The `share_data` consent row is the record of who turned it on and under which notice; it is not a second switch. Changing the server withdraws the other two choices.
9. **Upgrade.** A unit whose upload is already on gets a `share_data` row with notice version `pre-consent`, no user, and a note; the exact location stops (the gate, and Task 1's removal). The Status page shows "Review sharing" until an admin presses "I've reviewed this" on the Sharing page or saves it. Opening the page is not enough.
10. **Withdrawing overwrites.** While a choice is off, the gate sends `exact_location: {}` and `public_map: {}`, so the server's latest value isn't the old point. The `consents` attribute carries the state; what the server does with it is the server's side.
11. **The public map choice is built but not offered yet.** An install flag (`tmsetup_sharing_public_map_live`, false) makes the page show the box as "Not live yet" and the API refuse it. Only the rounded-point form exists here; the block form comes with the map plan.
12. **The first-run step is the last one,** after the system password, because a consent row needs the admin the claim creates. With no token set it is one paragraph and a button.
13. **The token form moves to the Sharing page,** as the entered-secrets plan foresaw. The Device page no longer lists the ThingsBoard token; the Status check's link follows.
14. **"Export exact locations" goes on the Location page,** not the Sharing page as the design has it: the places and the admin-only guard are there, and viewers can open the Sharing page. Descriptions are left out of the file, since a description never leaves the device.
15. **The maintainer's server is the default (maintainer).** `tb.roadwaybiome.com` ships as the default host and as the constant that marks the "maintainer" target. For any other server the notice and the map don't apply, and the page and the docs say that once data leaves the unit, making that server honour these choices is the operator's responsibility.
16. **A correction of a past place stays on the device (maintainer).** The gate re-sends the place in use after a correction, for free: the `config.yml` write reloads the config and the engine emits the rows again. Re-sending or backfilling past places is a later feature.
17. **Texts follow the code's default precision.** `database_precision` defaults to `'2'`, about 1 km, so the page says "as the database stores it (about 1 km unless you changed it)", not the design's "about 10 km".
18. **The upload URL already honours `protocol`** (entered secrets, issue 95), so the design's URL-builder change isn't needed. The gate only adds the https rule for the exact location.
19. **The server's status is read from the uploads themselves (maintainer, 2026-11-13).** Node-RED records the result of each upload: accepted, or one of four failure kinds taken from the HTTP status code or the lack of an answer, never from a message's text. tm-control reads it from `/tm-internal/status` and never contacts the server itself, so there is no extra request, no second place that holds the token, and a unit that isn't sharing sends nothing. System metrics go every five minutes, so the status is at most that old. A server that can't be reached is a warning, not an error: a field unit is offline often. A refused token is an error.

**Where the code stands that this plan touches:**
- `flows.json`, `thingsboard` tab (`f7932be9acc7391c`): every payload reaches `msg.type = telemetry` (`221ddfedf40c108f`) or `msg.type = attributes` (`75f7976086cc9838`), then the switch `thingsboard.enabled` (`93aa421659d2c20b`), the rate limit (`21944450ecc08385`, a `delay` node), `tb protocol?`, the URL templates (which read `global.config.thingsboard.url` and `env.TM_THINGSBOARD_ACCESS_TOKEN`), and `tb post http api` (`677a57bbf3619854`). Telemetry is `{ts, values: {<kind>: …}}`; the high-rate radar readings arrive as an array of those from the join node `ff1719e60656a2e6`. `format deployment telemetry` (`c6ff73faf6fa9e98`) sends `values.deployments = {updatedDeployment: [...], currentDeployment: [...]}` with rows as the engine returns them (`lat`, `lon`, `location_precision`, `survey_id`, `bearing`, …). The `deployments` attribute is a mustache template (`9b0f7197fe82bbfa`): per sensor `{sensorType, lat, lon, bearing, id}` with `lat` and `lon` as strings, plus `deploymentTopLevel: {survey_id, database_precision}`. `format system info client-side attributes` (`e507fdc9cbf67095`) sends eight `sysinfo_*` keys. `format init-config client-side attributes` (`9941048ea93dc79c`, fed by link in `c49d311e5668de52` from `init-config link out` `2fa46892748adc43`, which also feeds capture-radar) sends the whole config as `config_tm`. The Backup & Restore groups are `b781cb3d6df38fed`, `a38a90c36a0abfc3`, and `23636f4163fa6e3b`; their `ui_button`s and `ui_template` sit in the dashboard group "Backup & Restore" (`941fb260d6cfb5a2`).
- `init config defaults` (`94136e5a6f092bb6`): builds `thingsboard.url`, folds `protocol` to `http` for the switch, turns the upload off without a host or token, normalises `deployment`, and sets the globals `frigate_cameras`, `camera_labels`, `tm_warned` last. The engine (`689b64c16a889e0a`) emits the deployment rows on every config load.
- `/tm-internal/status` is built by "tm-internal: build status" (`a88895e60521585e`) from `global.tm_status`, which each config load resets; its fields are a contract pinned by the flows tests and `tests/fixtures/nodered_status.json`, and `modules/apps/checks.py` reads it for the Node-RED, configuration, schema, and radar checks (`GROUP` there is the Apps group). On the thingsboard tab, `tb post http api` feeds only a debug node, and the tab has one `catch` node (`695200d405f2d323`).
- `script/tests/test_node_red_flows.py`: `run_functions(steps, env, context)`, `named(flows, name)`, `node_by_id`, `tab_id`, `reachable(by_id, start_ids)`, `new_device_config()`, `init_defaults_thingsboard`, `TB_ENV`, `needs_node`. `TB_CONFIG` and `test_config_tm_has_no_frigate_camera_and_leaves_the_config_alone` pin the node Task 1 removes.
- `core/state.py`: `MIGRATIONS` has three entries; `tests/test_state.py` asserts the version is 3 after a fresh migrate. `core/auth.py`: `Device` (the `device` key-value table), `Audit.record(user_id, action, detail)`, `_reading`/`_writing`, `_timestamp`. `modules/location/places.py` shows the `device`-table pattern (`kept_precision`, `keep_precision`).
- `modules/location/config.py`: `NodeRedConfig(path)` with `deployment()`, `sensors()`, `sharing() -> "data" | "none"` (from `thingsboard.enabled`), the `set_*` editors, and `save() -> bool`; `put_after(block, key, value, after=)` and `blank_line_after` come from `adapters/yamlfile.py`. `modules/location/access.py`: `load_config(app_state)`, `save_config(app_state, config)` (tells Node-RED after a write), `config_error`. `modules/location/reconcile.py`: `ensure(app_state, user_id)` and `for_status_report(app_state)`, both under `app_state.reconcile_lock`; `_ensure` loads its own `NodeRedConfig` and may save it.
- `modules/secrets/router.py`: `ENTERED`, `SecretState(name, title, set, ends_with, restarts)`, `GET /secrets`, `POST`/`DELETE /secrets/{name}` (the `set-secret` job restarts Node-RED). `core/secrets.py`: `THINGSBOARD_ACCESS_TOKEN`, `secrets.is_set(name)`.
- `modules/setup/eula.py`: `load_eula(path) -> Eula(version, markdown)`, the version on the file's first line (`<!-- eula-version: 1 -->`); `app.state.eula`; `GET /setup/eula`.
- `modules/apps/contracts.py`: `GROUP = CheckGroup("config", "Configuration", [cameras_in_config, zones, radar_names, location, thingsboard, frigate_plus])`; `thingsboard()` answers `config.thingsboard` with a fix link to `/device#tokens-and-keys`. `tests/test_contract_checks.py` and `tests/fixtures/status_fake.json` list the group's checks; `script/devpi/tests/test_web.py::CONFIG_CHECKS` names them.
- `core/manifest.py`: `Manifest` with optional sections that have defaults (`FrigateInfo`, `NetworkInfo`); the role builds it in `tasks/tm-control_service.yml` (`tmsetup_tm_control_manifest`). `defaults/main.yml` has `tmsetup_thingsboard_server: 'tb.server.com'`, a placeholder; `config.yml.j2` renders `thingsboard:` with `enabled: false`, `host`, `protocol`, and a commented `port`. `script/tests/test_tmsetup_templates.py` asserts the template's top-level keys are exactly `thingsboard`, `deployment`, `sensors`.
- UI: `src/modules/index.ts` (`MODULES` in menu order), `src/router.ts` (`redirectFor`, `meta.adminOnly`), `src/components/{EnteredSecret,EulaText,ConfirmDialog,StatusCard}.vue`, `download.ts` (`saveBlob`), `relative-time.ts`; `modules/setup/SetupPage.vue` (`STEPS`, four steps, `finish()`); `modules/device/DevicePage.vue` (filters `frigate_plus_api_key` out of the secrets it lists); `modules/location/LocationPage.vue` and `DeployReview.vue` (read `state.sharing`). Tests: `tests/mount.ts`, `tests/fake-api.ts` (`signedIn`, `ADMIN`, `VIEWER`).

## Global Constraints

- Nothing but the gate's lists reaches ThingsBoard. No exact coordinate (finer than the stored precision) leaves the unit except in the `exact_location` attribute, and that only with the recorded consent, a matching host, and an https URL.
- The server's host, the token, coordinates, descriptions, and notes are never logged, audited, put in an error message, or shown on the Status page. Audit rows for sharing carry field names only (`sharing.update`: `enabled,exact_location`). `GET /sharing` gives a viewer no host of an operator's own server and no token state.
- Consent boxes are never pre-checked, never bundled, and each is withdrawn where it was given.
- No exact coordinate in any fixture, commit, PR text, or screenshot other than the example `45.52252, -122.69120` and the fixture's `45.0, -122.0`. Test hosts are `tb.example.invalid`; tokens are placeholders such as `tb-placeholder-0001`.
- `config.yml` is written only through `NodeRedConfig` (`RoundTripFile`, `mapping_indent=4`): comments, key order, and quoting kept; a backup beside the file; atomic replace; a changed file is 409 `config_changed`.
- tm-control never opens `tmdb.sqlite`; Node-RED never opens `state.sqlite`. tm-control never contacts the ThingsBoard server.
- `flows.json` is edited programmatically and re-serialised with `json.dumps(flows, indent=4, ensure_ascii=False)` and no trailing newline; existing nodes keep their ids; new nodes get fresh 16-hex ids; the MQTT nodes' ids stay; no id that was removed is left in any `wires`, `links`, `nodes`, `g`, or `group`.
- Every commit ends with the trailer block from the repo's `CLAUDE.md` (Assisted-by / AI-Model / AI-Effort / AI-Role); never `Co-Authored-By`. Docs follow "Writing docs" in `docs/development/contributing.md`; `mkdocs build --strict` passes. Nothing public names a device, a bench site, or how the server works inside.
- On a dev Pi: Frigate's detection, snapshots, and recording stay off; no item in this plan needs them. No real token is asked for or typed by the assistant.
- Off-device checks before each commit, from the repo root in the dev venv: `python -m pytest container/node-red-tm/schema/tests script/tests tm-control/backend/tests`; for UI tasks also `cd tm-control/ui && npm test && npm run build`; for docs tasks `~/.venvs/tm-docs/bin/mkdocs build --strict`.

## Review Focus

1. The high-rate radar readings arrive at the gate as an array of `{ts, values}`, not one object: each item is filtered on its own and the array still goes out. Test in Task 2 (`test_gate_passes_a_radar_array_item_by_item`).
2. `thingsboard.host` edited by hand to another server while the exact location is on: the exact location must not go to the new server, in the minutes before tm-control follows the edit. Tests in Task 2 (`test_gate_sends_no_exact_location_to_a_host_the_choice_was_not_made_for`) and Task 6 (`test_a_changed_host_withdraws_the_other_choices`).
3. `tmsetup.sh -f` on a unit that shares its exact location: the template has no `sharing:` block and the upload off; nothing is restored, the choices are recorded as withdrawn, and a later hand edit that turns the upload on shares rounded data only. Test in Task 6 (`test_a_reset_file_withdraws_everything_and_restores_nothing`).
4. Saving the page while `config.yml` changed underneath (another admin, a hand edit): 409, nothing written, no consent row recorded. Test in Task 7 (`test_a_changed_file_records_no_consent`).
5. A place with no coordinates, or coordinates quoted as strings in `config.yml`, with the exact location on: nothing is sent for the first (`exact_location: {}`), and the second is sent as numbers at five places. Test in Task 2 (`test_gate_exact_location_needs_a_point_and_reads_quoted_numbers`).

---

### Task 1: Flows: remove the settings upload, Backup & Restore, and the two empty slots

**Files:**
- Modify: `container/node-red-tm/data/flows.json`
- Modify: `script/tests/test_node_red_flows.py`

**Interfaces:**
- Produces: a `thingsboard` tab with no `config_tm` and no `backup_config` sender, and whose only `http request` node is `tb post http api` (`677a57bbf3619854`). `init-config link out` (`2fa46892748adc43`) links only to capture-radar's link in. `e507fdc9cbf67095` sends six keys: `sysinfo_tmVersion`, `sysinfo_osHostname`, `sysinfo_osRelease`, `sysinfo_osTimeZone`, `sysinfo_deviceName`, `sysinfo_frigateVersion`.

- [ ] **Step 1: Write the failing tests**

In `test_node_red_flows.py`: delete `TB_CONFIG` and `test_config_tm_has_no_frigate_camera_and_leaves_the_config_alone`, and reword the comment above `PR_FORMAT` (ThingsBoard gets no copy of the config). Add:
- `test_the_settings_are_not_uploaded`: no node on the thingsboard tab has `config_tm` in its `func` or `template`; `2fa46892748adc43`'s `links` all resolve to nodes on the capture-radar tab.
- `test_backup_and_restore_are_gone`: no node on the thingsboard tab is a `ui_button`, `ui_template`, or `ui_toast`; none has `backup` in its name, `func`, or `template` (case-insensitive); no `ui_group` in the file is named "Backup & Restore"; the tab's `http request` nodes are exactly `{"677a57bbf3619854"}`.
- `test_no_reference_to_a_removed_node`: every id in any node's `wires`, `links`, `nodes`, `g`, `group`, and `z` is the id of a node in the file.
- `test_system_info_attributes_have_no_network_slots` (`needs_node`): run `e507fdc9cbf67095` on a payload with all eight inputs; the result's keys are the six above.

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest script/tests/test_node_red_flows.py -k "settings_are_not or backup_and_restore or removed_node or network_slots" -v`
Expected: FAIL (the nodes are there).

- [ ] **Step 3: Edit `flows.json` with a script**

Remove `c49d311e5668de52` and `9941048ea93dc79c`, the three groups named above with every node whose `g` is one of them, and the `ui_group` `941fb260d6cfb5a2`. Take each removed id out of every remaining `links`, `nodes`, and `wires`. Delete the two `sysinfo_ssid`/`sysinfo_ipv4Address` lines from `e507fdc9cbf67095`. In `94136e5a6f092bb6`, change only the comment that says the config is uploaded: Frigate's names are kept out of `config` so no flow that reads it can pass them on. Re-serialise as the Global Constraints say.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest script/tests -v && python3 -m json.tool container/node-red-tm/data/flows.json >/dev/null`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add container/node-red-tm/data/flows.json script/tests/test_node_red_flows.py
git commit -m "Stop uploading the settings, and remove Backup & Restore to ThingsBoard"
```

### Task 2: Flows: the `sharing:` defaults, the upload gate, and the upload's result

**Files:**
- Modify: `container/node-red-tm/data/flows.json` (`94136e5a6f092bb6`; two new function nodes on the thingsboard tab, "upload gate" and "record upload result"; the wires of `93aa421659d2c20b`, `677a57bbf3619854`, and `695200d405f2d323`; `a88895e60521585e`)
- Modify: `script/tests/test_node_red_flows.py`

**Interfaces:**
- Produces, in `init config defaults`: `msg.payload.sharing` is always `{target, host, exact_location, public_map, notice_version}`. `target` is `"maintainer"`, `"own"`, or `null`; `host` is the given string normalised, or `null`; `exact_location` is `true` only for the boolean `true`; `public_map` is `"rounded_point"` or `"none"`; `notice_version` is a string or `null`. A missing block, or one that isn't a mapping, gives all-off. No error is logged for a missing block.
- Produces, the host rule, shared with tm-control (Task 4): trim, lower-case, drop a leading `http://` or `https://`, drop one trailing `/`.
- Produces, the gate (`msg.type` is `telemetry` or `attributes`; reads `global.config`; one output; returns `null` when nothing is left):
  - Telemetry: `msg.payload` is `{ts, values}` or an array of them. Keep only the `values` keys `event`, `radar`, `airquality`, `system_metrics`, `deployments`; drop an item left with no values; drop the message when no item is left.
  - Attributes: keep only `deployments`, `radarinfo`, and the six `sysinfo_*` keys of Task 1.
  - A dropped key warns once per config load through `global.tm_warned` (id `upload:<name>`, with a `warnOnce(id, text)` as "append config" has), naming the key and nothing from its value.
  - Deployment rows (`values.deployments.updatedDeployment`, `.currentDeployment`, and each sensor entry of the `deployments` attribute): `lat` and `lon` rounded half away from zero to `min(row.location_precision, the unit's database_precision)` places, where a missing `location_precision` counts as the unit's and `none` or `null` means both become `null`. A value that came as a string goes out as a string; an empty string stays empty.
  - When an attributes message carries `deployments`, add:
    - `consents: {share_data: true, exact_location: <bool>, public_map: "none" | "rounded_point", notice_version, target}`. The two choices count only when `sharing.host` equals the normalised `thingsboard.host`.
    - `exact_location: {survey_id, lat, lon}` (five places, numbers) when the choice counts, `thingsboard.url` starts with `https://`, and the place has a survey id and both coordinates; otherwise `{}`.
    - `public_map: {survey_id, mode: "rounded_point", lat, lon}` (three places) when the choice counts, `sharing.target` is `maintainer`, and the place has both coordinates; otherwise `{}`.
- Wiring: `93aa421659d2c20b` → the gate → `21944450ecc08385`.
- Produces, "record upload result" (no output; fed by `677a57bbf3619854` and by the tab's catch node): sets `global.tm_status.upload` to `{last_ok_at, last_failure_at, last_failure}`. A numeric `msg.statusCode` from 200 to 299 sets `last_ok_at` (ISO time). Anything else sets `last_failure_at` and `last_failure`: `refused` for 401 or 403, `rejected` for any other 4xx, `server_error` for 5xx, `unreachable` for a status code that isn't a number or a message from the catch node whose `error.source.id` is the http request's. A catch message from any other node is ignored. It reads nothing else from the message: not the payload, not the URL (which holds the token), not the error's text.
- Produces, in `/tm-internal/status`: `upload: {enabled, last_ok_at, last_failure_at, last_failure}`, where `enabled` is `global.config.thingsboard.enabled` after the defaults (so false without a host or a token) and the other three are `null` until an upload has been tried since the config last loaded. A config load clears them, so a result is always about the current server and token.

- [ ] **Step 1: Write the failing tests**

All `needs_node`, through `run_functions` with a `context={"config": …, "tm_warned": {}}` built by a helper `gate(msg, sharing=None, thingsboard=None, deployment=None)` whose defaults are `thingsboard = {"host": "tb.example.invalid", "url": "https://tb.example.invalid"}`, `deployment = {"survey_id": "3f9a1c2e-si", "lat": 45.52252, "lon": -122.69120, "database_precision": "2"}`, and all-off sharing:
- `test_init_config_defaults_sharing` (parametrised): missing → all-off; `{"target": "maintainer", "host": "HTTPS://TB.Example.invalid/", "exact_location": True, "public_map": "rounded_point", "notice_version": "2026-11"}` → the same with `host: "tb.example.invalid"`; `exact_location: "true"` → `False`; `public_map: "block"` → `"none"`; a list instead of a mapping → all-off.
- `test_gate_passes_each_listed_kind`: one message per telemetry kind and per attribute key comes out unchanged.
- `test_gate_drops_an_unlisted_key_and_warns_once`: telemetry `{values: {event: {...}, surprise: 1}}` → only `event`; attributes `{config_tm: {...}}` → `null`; the log has one warning naming `surprise` across two messages, and no part of the value.
- `test_gate_passes_a_radar_array_item_by_item`: an array of three items, one with an unlisted key only → two items out.
- `test_gate_re_rounds_deployment_rows`: a row with `lat: 45.52252, location_precision: 1` → `45.5`; with `location_precision: 2` and the unit at `"1"` → `45.5`; the unit at `"none"` → `null`; the attribute's string `"45.52252"` → `"45.52"`; `""` stays `""`; `-0.05` at one place → `-0.1`.
- `test_gate_adds_the_three_attributes_to_the_deployments_attribute` (all off): `consents == {"share_data": True, "exact_location": False, "public_map": "none", "notice_version": None, "target": None}`, `exact_location == {}`, `public_map == {}`; a `sysinfo_*` attributes message gets none of the three.
- `test_gate_sends_the_exact_location_with_consent_a_matching_host_and_https`: on → `{"survey_id": "3f9a1c2e-si", "lat": 45.52252, "lon": -122.6912}`; with `url: "http://tb.example.invalid"` → `{}` while `consents.exact_location` stays `True`.
- `test_gate_sends_no_exact_location_to_a_host_the_choice_was_not_made_for`: `sharing.host: "tb.example.invalid"`, `thingsboard.host: "other.example.invalid"` → `{}`, `consents.exact_location` `False`, `consents.public_map` `"none"`.
- `test_gate_exact_location_needs_a_point_and_reads_quoted_numbers`: `lat: ""` → `{}`; `lat: "45.522520", lon: "-122.69120"` → the numbers `45.52252`, `-122.6912`; no `survey_id` → `{}`.
- `test_gate_public_map_is_a_rounded_point_for_the_maintainer_target_only`: `target: "maintainer"` → `{"survey_id": …, "mode": "rounded_point", "lat": 45.523, "lon": -122.691}`; `target: "own"` → `{}`.
- `test_everything_uploaded_passes_the_gate`: the gate's only input wire comes from `93aa421659d2c20b`; that switch's only wire goes to the gate; the gate's only wire goes to `21944450ecc08385`; and `677a57bbf3619854` is not reachable from any node on the tab when the gate's wires are cut (`reachable`).
- `test_gate_lists` pins the two lists as literals.
- `test_upload_result_is_classed_by_status_code` (parametrised): `200` and `204` → `last_ok_at` set and `last_failure` untouched; `401`, `403` → `refused`; `400`, `404`, `429` → `rejected`; `500`, `503` → `server_error`; `"ECONNREFUSED"` and a missing status code → `unreachable`.
- `test_upload_result_keeps_nothing_else`: a message whose payload and `url` hold `tb-placeholder-0001` leaves no trace of it in the global context or the log.
- `test_a_caught_error_counts_only_when_it_came_from_the_upload`: a catch message with the http request's id as its source → `unreachable`; with another node's id → nothing set.
- `test_status_reports_the_upload`: the status builder answers `upload` with `enabled` from the config and three nulls before any upload; after a recorded failure, the same values; and the config-load nodes clear them (extend `test_each_config_load_resets_the_status_and_reads_the_schema_version`).
- `test_upload_result_wiring`: `677a57bbf3619854` and `695200d405f2d323` both wire to the new node, and it has no wires out.

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest script/tests/test_node_red_flows.py -k "gate or sharing" -v`
Expected: FAIL (no node named "upload gate").

- [ ] **Step 3: Implement**

Add the `sharing` normalisation to `94136e5a6f092bb6` beside the thingsboard part, before the globals are set. Add the function node (one output, no setup or close code, placed between the switch and the delay) and rewire. The gate copies the payload it changes (`JSON.parse(JSON.stringify(...))`); function nodes have no `structuredClone`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest script/tests -v`
Expected: PASS, including `test_flows_json_round_trips_through_json_dumps`.

- [ ] **Step 5: Commit**

```bash
git add container/node-red-tm/data/flows.json script/tests/test_node_red_flows.py
git commit -m "Pass every ThingsBoard upload through a gate that sends only what was chosen, and record how the server answered"
```

**Stop for review** after this task: the three attribute shapes are what the server reads, the `upload` status is a contract with tm-control, and everything after builds on the `sharing:` block.

### Task 3: Role: the maintainer's server, the map flag, and the manifest

**Files:**
- Modify: `script/ansible/roles/tmsetup/vars/main.yml`, `defaults/main.yml`, `tasks/tm-control_service.yml` (the manifest fact), `container/node-red-tm/config/config.yml.j2` (two comments)
- Modify: `tm-control/backend/tm_control/core/manifest.py`, `tm-control/backend/tests/fixtures/manifest.json`
- Test: `script/tests/test_tmsetup_templates.py`, `script/tests/test_tmsetup_tasks.py`, `tm-control/backend/tests/test_settings_and_manifest.py`

**Interfaces:**
- Produces: `tmsetup_sharing_maintainer_host: 'tb.roadwaybiome.com'` and `tmsetup_sharing_public_map_live: false` in `vars/main.yml`; `tmsetup_thingsboard_server: 'tb.roadwaybiome.com'` in `defaults/main.yml` (a literal, so the template tests keep rendering from the defaults alone); the manifest's `sharing: {maintainer_host, public_map_live}`.
- Produces, in `manifest.py`: `SharingInfo` (frozen dataclass: `maintainer_host: str = "tb.roadwaybiome.com"`, `public_map_live: bool = False`) and `Manifest.sharing: SharingInfo = SharingInfo()`, so a manifest written before this change still loads.

- [ ] **Step 1: Write the failing tests**

- `test_tmsetup_tasks.py::test_the_default_upload_host_is_the_maintainers_server`: the two role values are equal and neither is `tb.server.com`.
- `test_tmsetup_templates.py`: the manifest fact (as the existing manifest test reads it) has `sharing` with the two keys; `config.yml.j2` still has exactly the three top-level keys, `enabled: false`, and its comments name the Sharing page and not the Device page.
- `test_settings_and_manifest.py`: the fixture loads with `manifest.sharing.maintainer_host == "tb.example.invalid"` (set so in the fixture) and a manifest without the section loads with the defaults.

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest script/tests -k "manifest or upload_host or config_template" tm-control/backend/tests/test_settings_and_manifest.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement**

The template's first comment becomes "The access token isn't kept in this file. Set it, and choose what's shared, on the control app's Sharing page."

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest script/tests tm-control/backend/tests -v && (cd script/ansible && ansible-playbook -i localhost setup.yml --syntax-check </dev/null)`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add script/ansible container/node-red-tm/config/config.yml.j2 script/tests tm-control/backend
git commit -m "Ship the maintainer's server as the default upload host and record it in the manifest"
```

### Task 4: Migration 4 and the consents store

**Files:**
- Modify: `tm-control/backend/tm_control/core/state.py` (append `MIGRATIONS[3]`), `tests/test_state.py` (the version is 4)
- Create: `tm-control/backend/tm_control/modules/sharing/__init__.py`, `consents.py`
- Test: `tm-control/backend/tests/test_sharing_consents.py` (create)

**Interfaces:**
- Produces, migration 4:

```sql
CREATE TABLE sharing_consents (
    id INTEGER PRIMARY KEY,
    target TEXT NOT NULL,              -- 'maintainer' | 'own:<host>'
    consent TEXT NOT NULL CHECK (consent IN ('share_data', 'exact_location', 'public_map')),
    granted INTEGER NOT NULL CHECK (granted IN (0, 1)),
    notice_version TEXT NOT NULL,      -- the notice's version, 'own-server', or 'pre-consent'
    at TEXT NOT NULL,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    note TEXT
);
```

- Produces, in `consents.py`:
  - `CONSENTS = ("share_data", "exact_location", "public_map")`, `MAINTAINER = "maintainer"`, `OWN_SERVER = "own-server"`, `PRE_CONSENT = "pre-consent"`.
  - `normalize_host(value) -> str | None` (the rule of Task 2; `None` for a blank or non-string value).
  - `target_key(host, maintainer_host: str) -> str | None`: `None` for no host, `"maintainer"` when the normalised hosts are equal, else `"own:" + normalize_host(host)`.
  - `class Consent(BaseModel)`: `consent: str`, `granted: bool`, `notice_version: str`, `at: str`, `user_id: int | None`, `note: str | None`.
  - `class Consents`, built with a `State`: `latest(target: str) -> dict[str, Consent]` (the newest row per consent; a consent never recorded is absent), `granted(target: str, consent: str) -> bool`, `record(target, consent, granted: bool, notice_version, user_id: int | None, note: str | None = None, now: float | None = None) -> None`, `withdraw_all(target, user_id, note, now=None) -> list[str]` (a withdrawal row for each consent whose latest row is granted; returns their names), `review_needed() -> bool`, `set_review_needed(needed: bool) -> None` (the `device` key `sharing_review_needed`, as `Places.keep_precision` stores its key).

- [ ] **Step 1: Write the failing tests**

`test_state.py`: the fresh-migrate assertion becomes 4. `test_sharing_consents.py`:
- `test_latest_is_the_newest_row_per_consent_and_target`.
- `test_granted_is_false_for_a_consent_never_recorded`.
- `test_withdraw_all_writes_a_row_only_for_what_is_granted`.
- `test_a_deleted_user_leaves_the_row_with_no_user`.
- `test_target_key` (parametrised): `("TB.Example.invalid", "tb.example.invalid")` → `"maintainer"`; `("https://tb.example.invalid/", …)` → `"maintainer"`; `("other.example.invalid", …)` → `"own:other.example.invalid"`; `(None, …)` and `("  ", …)` → `None`.
- `test_review_flag_round_trips`.
- `test_the_host_rule_matches_node_reds`: the same table of inputs as `test_init_config_defaults_sharing` uses for `host`, kept as one literal list in this test file with a comment naming the flows test.

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tm-control/backend/tests/test_state.py tm-control/backend/tests/test_sharing_consents.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement**

- [ ] **Step 4: Run the tests to verify they pass**

Run: the Step 2 command.
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tm-control/backend
git commit -m "Record sharing consents in the state database"
```

### Task 5: The `thingsboard:` and `sharing:` edits to `config.yml`

**Files:**
- Modify: `tm-control/backend/tm_control/modules/location/config.py`
- Test: `tm-control/backend/tests/test_location_config.py`

**Interfaces:**
- Produces, in `config.py`:
  - `class Upload(BaseModel)`: `enabled: bool` (true only for the boolean), `host: str | None` (as written, trimmed; `None` when blank), `protocol: Literal["http", "https"]` (`https` when missing or anything else), `port: int | None`, `host_has_scheme: bool`.
  - `class SharingBlock(BaseModel)`: `target: Literal["maintainer", "own"] | None = None`, `host: str | None = None`, `exact_location: bool = False`, `public_map: Literal["none", "rounded_point"] = "none"`, `notice_version: str | None = None`; parsed as leniently as Node-RED parses it (Task 2).
  - `NodeRedConfig.upload() -> Upload`; `NodeRedConfig.sharing_block() -> SharingBlock | None` (`None` when the file has no `sharing:` key).
  - `NodeRedConfig.set_upload(enabled: bool, host: str, protocol: str, port: int | None) -> None`: writes the four keys in `thingsboard:` (creating the block first in the file when it is missing), `port` removed when `None`; a commented `# port:` line stays a comment.
  - `NodeRedConfig.set_sharing(block: SharingBlock) -> None`: writes the five keys in that order in a `sharing:` block placed after `thingsboard:`, with the comment "Written by the control app's Sharing page. A choice made here isn't recorded: use the page." above its first key; `notice_version` single-quoted; `None` values written as empty keys.
  - `NodeRedConfig.sharing() -> Literal["none", "data", "exact"]`: `none` with the upload off; `exact` when the block's `exact_location` is true and its `host` equals the upload's normalised host; else `data`.

- [ ] **Step 1: Write the failing tests**

In `test_location_config.py`, against `tests/fixtures/node_red_config_ok.yml` copied to `tmp_path`:
- `test_upload_reads_the_block_leniently` (parametrised: `enabled: 'true'` → off; no `protocol` → `https`; `host: https://tb.example.invalid` → `host_has_scheme`).
- `test_set_upload_keeps_comments_and_writes_the_port_only_when_given`.
- `test_set_sharing_creates_the_block_after_thingsboard_and_keeps_the_blank_lines` (the text between `thingsboard:` and `deployment:` is the new block and one blank line each side).
- `test_set_sharing_twice_changes_only_values` (the second `save()` with the same block returns `False`).
- `test_sharing_is_exact_only_for_the_host_the_choice_was_made_for`.
- `test_the_saved_file_loads_as_node_red_would` (`yaml.safe_load` of the result has `sharing` as a mapping with the five keys).

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tm-control/backend/tests/test_location_config.py -k "upload or sharing" -v`
Expected: FAIL.

- [ ] **Step 3: Implement**

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tm-control/backend/tests -v`
Expected: PASS (the API test that reads `sharing` still sees `"none"`).

- [ ] **Step 5: Commit**

```bash
git add tm-control/backend
git commit -m "Read and write the upload and sharing blocks of Node-RED's config.yml"
```

### Task 6: The notice and the follow step

**Files:**
- Create: `tm-control/backend/tm_control/modules/sharing/NOTICE.md` (the draft in "Notice draft" below), `notice.py`, `follow.py`
- Modify: `tm-control/backend/tm_control/modules/setup/eula.py` (the loader takes the marker's name), `app.py` (`app.state.notice`), `modules/location/reconcile.py` (`ensure` and `for_status_report` call the follow step)
- Test: `tm-control/backend/tests/test_sharing_follow.py` (create), `tests/test_api_setup.py` (the EULA still loads)

**Interfaces:**
- Produces: `setup/eula.py::load_versioned(path, name: str) -> Eula` (first line `<!-- <name>-version: … -->`); `load_eula(path)` stays and calls it with `"eula"`. `sharing/notice.py::load_notice(path=NOTICE_PATH) -> Eula` with `"notice"`. `app.state.notice`.
- Produces, in `follow.py`: `run(app_state) -> bool` (whether it wrote the file). The caller holds `app_state.reconcile_lock`. It loads its own `NodeRedConfig`; an unreadable file returns `False`. Rules, in order, with `target = target_key(upload.host, manifest.sharing.maintainer_host)`:
  1. **The upload is off:** `withdraw_all(target, None, "the upload was off in config.yml")` when there is a target.
  2. **The upload is on and `share_data` isn't granted for the target:** record it granted with `PRE_CONSENT`, no user, the note "the upload was on in config.yml with no choice recorded on the Sharing page", and `set_review_needed(True)`.
  3. **The file's block names another host than the upload's:** `withdraw_all(target_key(block.host, …), None, "the server changed in config.yml")`.
  4. **The block the store asks for** (`wanted_block(target: str | None, host: str | None, share_data: Consent | None, exact_location: bool, public_map: bool) -> SharingBlock`, which Task 7's save also calls, so a save leaves the follow step nothing to rewrite): `target` kind, `host` the upload's normalised host, the two choices as granted for the target, and `notice_version` the version of the `share_data` row when that row is granted, else `None`. Write it when the file has a block that differs, or has none and the wanted block grants either choice; then `save()` and `app_state.nodered.after_config_write()`.
  Nothing here logs a host, a version, or a note: only counts and exception class names.
- Produces, in `reconcile.py`: `ensure` and `for_status_report` call `follow.run(app_state)` after `_ensure`, inside the lock, whatever `_ensure` returned; in `for_status_report` an error from it is logged by class name, as the places' is.

- [ ] **Step 1: Write the failing tests**

`test_sharing_follow.py` (the `claimed_client` app's state, a config in `tmp_path`, `maintainer_host` `tb.example.invalid`):
- `test_an_upload_already_on_is_recorded_and_flagged`: upload on, no rows → one `share_data` row, `pre-consent`, no user, `review_needed()`; no `sharing:` block is written; a second run records nothing.
- `test_an_untouched_unit_gets_no_block_and_no_row`: upload off, the placeholder host → nothing written, no row.
- `test_a_reset_file_withdraws_everything_and_restores_nothing`: grant all three, write the block, then replace the file with the fixture (upload off, no block) → three withdrawal rows, the file unchanged; then set `enabled: true` by hand → `share_data` is `pre-consent` again, `exact_location` not granted, no block written.
- `test_a_changed_host_withdraws_the_other_choices`: granted for the maintainer; the file's `thingsboard.host` edited to `other.example.invalid` → the old target's `exact_location` withdrawn, the block rewritten with the new host and `exact_location: false`.
- `test_a_hand_set_exact_location_is_written_back`: the block edited to `exact_location: true` with no grant → `false` after the run, and `after_config_write` called once.
- `test_an_unreadable_file_is_left_alone`.
- `test_no_host_in_any_log_line` (`caplog`).
- In `test_reconcile.py`: `test_ensure_runs_the_sharing_follow_while_node_red_is_down` (the places part answers `waiting_nodered`; the sharing row is still recorded).

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tm-control/backend/tests/test_sharing_follow.py tm-control/backend/tests/test_reconcile.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement**

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tm-control/backend/tests -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tm-control/backend
git commit -m "Keep config.yml's sharing block equal to the recorded consents, and record an upload found on"
```

### Task 7: The API: `/api/v1/sharing`

**Files:**
- Create: `tm-control/backend/tm_control/modules/sharing/router.py`, `server.py`
- Modify: `modules/sharing/__init__.py` (`module = Module("sharing", router)`), `modules/__init__.py` (`sharing.module` after `location.module`), `modules/secrets/router.py` (a `secret_state(app_state, name) -> SecretState` helper that `get_secrets` also uses), `modules/location/router.py` (`PlacesState.sharing: Literal["none", "data", "exact"]`), `fake.py` (`FakeNodeRed.report()` answers `upload`: enabled from the seeded file, an accepted upload a minute ago when it is on), `tests/fixtures/nodered_status.json` (an `upload` section, off, three nulls)
- Test: `tm-control/backend/tests/test_api_sharing.py` (create), `tests/test_openapi_document.py`, `tests/test_api_surveys.py` (the widened literal)

**Interfaces:**
- Produces, in `server.py`: `class ServerStatus(BaseModel)`: `state: Literal["off", "waiting", "ok", "stale", "unreachable", "refused", "rejected", "server_error", "unknown"]`, `at: str | None`. `server_status(report: dict | None, now: float) -> ServerStatus` from Node-RED's status body: `unknown` when there is no body or no `upload` section; `off` when `enabled` is false; `waiting` when both times are null; the failure kind, with `last_failure_at`, when the failure is newer than the last accepted upload or there is none; else `ok` with `last_ok_at`, or `stale` when that is more than 15 minutes old (three of the five-minute system metrics missed). `STALE_AFTER = 900`.
- Produces (`APIRouter(prefix="/sharing", tags=["sharing"])`):
  - `ConsentOut(granted: bool, at: str | None, notice_version: str | None)`.
  - `SharingState(enabled: bool, target: Literal["maintainer", "own"] | None, host: str | None, protocol: Literal["http", "https"], port: int | None, maintainer_host: str, token: SecretState | None, share_data: ConsentOut, exact_location: ConsentOut, public_map: ConsentOut, public_map_live: bool, notice_version: str, notice_current: bool, review_needed: bool, has_location: bool, precision: Literal["none", "1", "2"], writable: bool, server: ServerStatus)`. `server` comes from `app.state.nodered.report()`, with `unknown` when Node-RED doesn't answer; viewers see it too, since it names no host. For a viewer: `host` is `None` unless the target is the maintainer's, `token` is `None`, `writable` is `False`. `notice_current` is true for an operator's own server, and for the maintainer's when the latest `share_data` row's version is the notice's. `has_location` says whether the place in use has a point.
  - `GET /sharing` (any signed-in user) → `SharingState`, after `follow.run` under the lock.
  - `GET /sharing/notice` (any signed-in user) → `{version, markdown}`.
  - `SharingIn(target: Literal["maintainer", "own"], host: str | None = Field(None, max_length=253), protocol: Literal["http", "https"] = "https", port: int | None = Field(None, ge=1, le=65535), enabled: bool, exact_location: bool, public_map: Literal["none", "rounded_point"], notice_version: str | None = Field(None, max_length=64))`.
  - `PUT /sharing` (admin) → `SharingState`. Checks, each a 422 `validation` naming the field unless a code is given:
    - `target: "own"` needs a `host` that, normalised, matches `[a-z0-9]([a-z0-9.-]{0,251}[a-z0-9])?`; a host equal to the maintainer's is the maintainer target. For the maintainer target the host is the manifest's, the protocol `https`, and the port none, whatever was sent.
    - `enabled` with no token set: 409 `no_token`, "Set the access token first."
    - `exact_location` or a `public_map` other than `none` with `enabled` false; `exact_location` with `protocol: "http"` ("The exact location is only sent over https.").
    - `public_map` other than `none` for an own server, or while `public_map_live` is false: 409 `map_not_live`.
    - For the maintainer target with `enabled`: `notice_version` must be the current notice's ("That isn't the current notice. Reload the page to read it.").
    Then, under the lock: load the file (`load_config`), `set_upload`, `set_sharing`, `save_config` (409 `config_changed` records nothing); then the rows: when the target changed, `withdraw_all(old target, admin.id, "the server changed")`; for each consent whose wanted state differs from `latest(target)`, or whose granted row carries another notice version, `record(…)` with the notice's version (or `OWN_SERVER`); `set_review_needed(False)`; audit `sharing.update` with the names of the fields that changed, comma-joined, never a value.
  - `POST /sharing/reviewed` (admin) → 204; `set_review_needed(False)`; audit `sharing.reviewed`.

- [ ] **Step 1: Write the failing tests**

`test_api_sharing.py` (the `claimed_client` fixture; a `put(**changes)` helper over a valid maintainer body; the fake secrets' `entered` for the token):
- `test_sharing_needs_a_login_and_put_needs_an_admin` (401; a viewer's `GET` is 200 with `writable False`, `token None`; a viewer's `PUT` is 403).
- `test_a_viewer_never_sees_an_own_servers_host`.
- `test_a_new_unit_shares_nothing`: `enabled False`, the three consents `granted False`, no rows.
- `test_turning_on_needs_a_token` (409 `no_token`).
- `test_turning_on_records_share_data_under_the_notice_version` and writes `enabled: true` and the `sharing:` block.
- `test_the_exact_location_needs_https_and_the_upload_on` (two 422s).
- `test_exact_location_is_recorded_and_written`; then `exact_location False` → a withdrawal row and `false` in the file.
- `test_the_map_is_refused_until_it_is_live` (409 `map_not_live`); with the manifest's flag on, granted and written.
- `test_an_old_notice_version_is_refused`.
- `test_changing_the_server_withdraws_the_other_choices` (maintainer with exact on → own server: the old target's `exact_location` withdrawn with the admin's id; the new target's `share_data` recorded as `own-server`).
- `test_an_own_server_host_is_validated` (parametrised: `https://x` and `a b` and `x/y` refused; `tb.example.invalid` accepted; the maintainer's host sent as own becomes the maintainer target).
- `test_a_changed_file_records_no_consent`: monkeypatch `save_config` to raise the 409 → no new row, the review flag untouched.
- `test_a_save_leaves_nothing_for_the_follow_step_to_rewrite`: after each of three saves (on, exact on, off), `follow.run` returns `False` and the file has no new backup.
- `test_reviewed_clears_the_flag`.
- `test_server_status` (parametrised over `server_status`): no body → `unknown`; `enabled False` → `off`; three nulls → `waiting`; a failure newer than the last accepted upload → its kind and time; an accepted upload newer than the failure → `ok`; accepted 16 minutes ago → `stale`.
- `test_get_sharing_reports_the_server_and_survives_node_red_being_down` (the fake's `report` raising `NodeRedError("unreachable")` → 200 with `server.state == "unknown"`).
- `test_the_audit_row_names_fields_only` (no host, no version in `detail`).
- `test_no_host_or_token_in_any_log_line` (`caplog` over the module).
- `test_openapi_document.py`: the paths are declared with their response models.

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tm-control/backend/tests/test_api_sharing.py -v`
Expected: FAIL (404s).

- [ ] **Step 3: Implement**

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tm-control/backend/tests -v`
Expected: PASS.

- [ ] **Step 5: Regenerate the API description and commit**

Run: `PYTHONPATH=tm-control/backend python -m tm_control dump-openapi > tm-control/ui/src/api/openapi.json && (cd tm-control/ui && npm run api:generate)`

```bash
git add tm-control/backend tm-control/ui/src/api
git commit -m "Add the sharing API: the server, the choices, and the notice"
```

### Task 8: The Sharing and server checks, the token link, and the exact-locations file

**Files:**
- Modify: `tm-control/backend/tm_control/modules/apps/contracts.py` (`sharing`, `thingsboard`, `GROUP`), `modules/apps/checks.py` (`sharing_server`, its `GROUP`), `modules/location/router.py` (`GET /surveys/export`)
- Modify: `tm-control/backend/tests/fixtures/status_fake.json`, `tests/test_contract_checks.py`, `tests/test_app_checks.py`, `tests/test_api_surveys.py`, `script/devpi/tests/test_web.py` (`CONFIG_CHECKS`)

**Interfaces:**
- Produces, `contracts.sharing(context) -> list[Check]`, id `config.sharing`, title "Sharing", placed after `thingsboard` in `GROUP`:
  - `unknown` when `config.yml` can't be read.
  - `warn`, with `Fix(kind="link", href="/sharing", text="Review sharing")`: the review flag is set ("This device was sharing before the sharing choices existed. It keeps sharing data with the location as the database stores it. Review the choices."); or the upload is on for the maintainer's server and the recorded notice version isn't the current one ("The sharing notice has changed. Read it and save your choices again."); or the `sharing:` block holds a value the device ignores ("config.yml's sharing block has a value the device ignores. Save the Sharing page to rewrite it.").
  - `ok`: "Not sharing.", "Sharing data, with the location as the database stores it.", or "Sharing data and the exact location.", with " The public map is on." appended when it is.
  - Never a host, a version, or a note. Without `context.state` the flag and version parts are skipped.
- Produces, `checks.sharing_server(context) -> list[Check]`, id `apps.sharing_server`, title "Sharing server", last in the Apps group, from `server_status` on the same Node-RED status probe the other Apps checks use: `off` → ok "Nothing is being uploaded."; `waiting` → ok "Waiting for the first upload since the settings loaded."; `ok` → ok "The server accepted an upload <duration> ago."; `stale` → warn "The server hasn't accepted an upload for <duration>."; `unreachable` → warn "The server can't be reached. The device keeps recording; uploads that fail aren't sent again."; `refused` → error "The server refused this device's token." with `Fix(kind="link", text="Check the token", href="/sharing#token")`; `rejected` → error "The server refused an upload."; `server_error` → warn "The server answered with an error."; `unknown` → unknown "Node-RED didn't answer, so the server's status isn't known." Never the host, a status code's body, or any text from Node-RED's log.
- Produces, `thingsboard()`: the missing-token fix is `Fix(kind="link", text="Set the token", href="/sharing#token")`, and its former-key warning says "Sharing page" for `thingsboard.access_token` and still "Device page" for the Plate Recognizer key.
- Produces, `GET /surveys/export` (admin; declared before the `{survey_id}` routes): `text/csv; charset=utf-8`, `Content-Disposition: attachment; filename="traffic-monitor-places.csv"`, header `survey_id,lat,lon,status,created_at,updated_at`, one row per place in the list's order, coordinates with five decimals or empty, no description; audit `survey.export` with the row count.

- [ ] **Step 1: Write the failing tests**

- `test_contract_checks.py`: the group's id list gains `config.sharing` after `config.thingsboard`; `test_sharing_check_says_what_is_shared` (parametrised over the three ok texts); `test_sharing_check_asks_for_a_review`; `test_sharing_check_notices_a_new_notice_version`; `test_sharing_check_flags_an_ignored_value`; `test_the_token_link_goes_to_the_sharing_page`; `test_sharing_check_shows_no_host`.
- `test_app_checks.py`: `test_sharing_server_check` (parametrised over the nine states: the status, a phrase of the text, and the fix link for `refused` only); `test_sharing_server_check_shows_no_host`.
- `status_fake.json`: a `config.sharing` entry, ok, "Not sharing.", and an `apps.sharing_server` entry, ok, "Nothing is being uploaded.".
- `test_api_surveys.py`: `test_export_is_admin_only_and_has_no_description` (a place with a description and `45.52252, -122.69120` → the line `<id>,45.52252,-122.69120,planned,…`; the description isn't in the body; a viewer gets 403); `test_export_writes_an_empty_pair_for_no_location`.

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tm-control/backend/tests -k "contract or export or status" -v`
Expected: FAIL.

- [ ] **Step 3: Implement**

- [ ] **Step 4: Run the tests to verify they pass, regenerate the API description**

Run: `python -m pytest tm-control/backend/tests script/tests -v`, then the regeneration command of Task 7.
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tm-control/backend tm-control/ui/src/api script/devpi/tests/test_web.py
git commit -m "Report sharing and the server's answer on the Status page, and export the places with exact locations"
```

**Stop for review** after this task: the backend is complete and the page is built on it.

### Task 9: The Sharing page

**Files:**
- Create: `tm-control/ui/src/modules/sharing/index.ts`, `SharingPage.vue`, `SharingForm.vue`, `ConsentBox.vue`, `examples.ts`
- Modify: `tm-control/ui/src/modules/index.ts` (`sharing` after `location`)
- Test: `tm-control/ui/tests/sharing-page.spec.ts`, `tests/sharing-form.spec.ts`, `tests/router.spec.ts`

The implementer loads `frontend-design:frontend-design`, `superpowers:test-driven-development`, and `superpowers:verification-before-completion`, adds short design notes to `tm-control/ui/README.md`, and screenshots the page at phone and desktop width in fake mode. Conventional Vuetify components; no custom CSS beyond spacing.

**Interfaces:**
- Produces: route `/sharing` (no `adminOnly`), nav `{ title: 'Sharing', to: '/sharing', icon: mdiShareVariantOutline }`.
- Produces, `examples.ts`: three constant strings of pretty-printed JSON built from the flows tests' shapes: `SHARE_DATA_EXAMPLE` (one event with placeholder values and one deployment row with `lat: 45.52, lon: -122.69, location_precision: 2`), `EXACT_LOCATION_EXAMPLE` (`{"survey_id": "3f9a1c2e-si", "lat": 45.52252, "lon": -122.6912}`), `PUBLIC_MAP_EXAMPLE` (`{"survey_id": "3f9a1c2e-si", "mode": "rounded_point", "lat": 45.523, "lon": -122.691}`).
- Produces, `ConsentBox.vue`: props `title`, `text`, `example`, `modelValue: boolean`, `disabled?: boolean`, `disabledReason?: string`, `recorded: ConsentOut`; a checkbox (never pre-checked beyond `modelValue`), the text, the reason line when disabled, a "See an example" disclosure with the example in a `<pre>`, and "On since <relative time>" when `recorded.granted`.
- Produces, `SharingForm.vue`: props `state: SharingState`, `firstRun?: boolean`; emits `saved` with the new state. Sections:
  - **Server.** A radio group: "Traffic Monitor's server (<maintainer_host>)" or "Your own ThingsBoard server". For your own: Host, Protocol (https, http), Port (optional), and the paragraph "Your own server is yours to run. The notice below doesn't apply to it, and once data leaves this device, making sure that server honours the choices you make here is your responsibility."
  - **Access token** (`id="token"`): `EnteredSecret` with `hideTitle` on `state.token`; on `changed` the page reloads its state. The line "The server gives each device a token. Saving it restarts Node-RED, which takes about thirty seconds."
  - **What this device shares.** Three `ConsentBox`es:
    1. "Share data": "Counts, speeds, radar and air-quality readings, and system health, with the location as the database stores it (about 1 km unless you changed it on the Location page). Turning this off stops all uploads." Disabled with "Set the access token first." when no token is set.
    2. "Share the exact location": "This device's exact coordinates, for the server's operator to use and not to publish. Turning this off stops it." Disabled with "Turn on Share data first.", or "The exact location is only sent over https." The line "Nothing is sent until the place in use has a location." when `!state.has_location`.
    3. "Show this device on the public map": shown for the maintainer's server only; disabled with "Not live yet." while `!state.public_map_live`; otherwise "A point rounded to about 100 m, and nothing else about where the device is."
  - **The notice** (maintainer's server): "Read the sharing notice (version <notice_version>)" opening `EulaText` on `GET /sharing/notice`; a checkbox "I've read the notice" that Save needs whenever the upload is on and `!state.notice_current` or it is being turned on.
  - Save → `PUT /api/v1/sharing` with `notice_version` when the box is ticked. Changing the server while the exact location or the map is on asks first (`ConfirmDialog`: "Changing the server turns off the exact location and the public map. You can turn them on again for the new server."). A 409 `config_changed` shows the API's message and reloads. With `firstRun`, the button reads "Save and finish".
- Produces, `SharingPage.vue`: `GET /api/v1/sharing` on mount (the Device page's load/error/progress pattern); `h1` "Sharing"; when `review_needed`, an alert with the Status check's text and, for admins, a button "I've reviewed this" (`POST /sharing/reviewed`, then reload); a `StatusCard` with "Sharing" ("Off" / "Data" / "Data and the exact location"), "Server" ("Traffic Monitor's server", "Your own server", or "Not chosen"), "Server status" (from `state.server`: "Off", "Waiting for the first upload", "Accepted an upload <relative time>", "No upload accepted since <relative time>", "Can't be reached", "Refused the token", "Refused an upload", "Answered with an error", or "Not known: Node-RED didn't answer"), and "Location sent" ("As the database stores it" / "Exact"); after a save that leaves the upload on, the page reads `GET /sharing` again every 5 seconds for up to a minute while the state is `waiting` or `unknown`, so the admin sees whether the server took the first upload; for admins the form; for viewers the sentence "An administrator chooses what this device shares."

- [ ] **Step 1: Write the failing tests**

`tests/sharing-page.spec.ts` (`signedIn(ADMIN | VIEWER, { 'GET /api/v1/sharing': STATE })`):
- `it('is in the menu for everyone and shows a viewer no form')`.
- `it('shows what is shared in the summary')`.
- `it('asks for a review and clears it')` (the `POST` in `sent`).
- `it('says how the server answered, to viewers too')` (parametrised over `refused`, `unreachable`, and `ok`).
- `it('checks again after a save until the first upload has an answer')` (fake timers: `waiting`, then `ok`; the polling stops).
`tests/sharing-form.spec.ts` (`mountAlone`):
- `it('starts with every box unchecked on a new device')`.
- `it('disables Share data until a token is set')`.
- `it('needs the notice read before turning sharing on')` (Save disabled until the box is ticked; the `PUT` body has `notice_version`).
- `it('disables the exact location over http and says why')`.
- `it('shows the map as not live')`.
- `it('hides the notice and the map for your own server and shows the responsibility text')`.
- `it('asks before changing the server while the exact location is on')`.
- `it('withdraws by unticking and saving')` (`exact_location: false` in the body).
`tests/router.spec.ts`: a viewer may open `/sharing`.

- [ ] **Step 2: Run them to verify they fail**

Run: `cd tm-control/ui && npx vitest run tests/sharing-page.spec.ts tests/sharing-form.spec.ts tests/router.spec.ts`
Expected: FAIL (no module).

- [ ] **Step 3: Implement**

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd tm-control/ui && npm test && npm run build`
Expected: PASS, build clean.

- [ ] **Step 5: Commit**

```bash
git add tm-control/ui
git commit -m "Add the Sharing page: the server, the token, and what the device shares"
```

### Task 10: First run, the Device page, and the Location page

**Files:**
- Modify: `tm-control/ui/src/modules/setup/SetupPage.vue`, `modules/device/DevicePage.vue`, `modules/location/LocationPage.vue`, `modules/location/DeployReview.vue`
- Test: `tm-control/ui/tests/setup-flow.spec.ts`, `tests/device-page.spec.ts`, `tests/location-page.spec.ts`, `tests/deploy-review.spec.ts`

**Interfaces:**
- Produces, `SetupPage.vue`: `STEPS` ends with `'Sharing'`. Step 4's "Go to the home page" buttons become "Continue", and "Skip for now" also goes to step 5. Step 5 (`h1` "Sharing") loads `GET /api/v1/sharing`: the paragraph "This device shares nothing unless you turn it on. You can send its counts and speeds to Traffic Monitor's server or to your own, and choose how much of its location goes with them. You can do this now or later on the Sharing page."; with a token set, `SharingForm` with `firstRun`, whose `saved` calls `finish()`; always a "Not now" button that calls `finish()`. A failed load shows the paragraph and "Not now" only.
- Produces, `DevicePage.vue`: the secrets it lists leave out `thingsboard_access_token` too; the section's text gains "The ThingsBoard token is on the Sharing page." with a link.
- Produces, the Location page: the "Sharing" item reads "Not sharing", "Sharing: data", or "Sharing: data and the exact location" for `none`/`data`/`exact`; `DeployReview`'s line reads "Not sharing", "Sharing: data, rounded location", or "Sharing: data and the exact location". A section "Exact locations" below "Places": the sentence "The database keeps a rounded location. This file lists each place's exact one, by place id.", a button "Export exact locations", and a `ConfirmDialog` ("This file says exactly where the device has been. Anyone you give it to can match it to the database by place id.") before `GET /api/v1/surveys/export` and `saveBlob(blob, 'traffic-monitor-places.csv')`.

- [ ] **Step 1: Write the failing tests**

- `setup-flow.spec.ts`: the flow has five steps; after the system password (set or skipped) the Sharing step shows; "Not now" goes home; with a token set the form shows and "Save and finish" sends the `PUT` and goes home.
- `device-page.spec.ts`: the ThingsBoard token isn't listed; the link to `/sharing` is.
- `location-page.spec.ts`: the three sharing texts; the export asks first and fetches the file (`saveBlob` stubbed).
- `deploy-review.spec.ts`: the `exact` line.

- [ ] **Step 2: Run them to verify they fail**

Run: `cd tm-control/ui && npx vitest run tests/setup-flow.spec.ts tests/device-page.spec.ts tests/location-page.spec.ts tests/deploy-review.spec.ts`
Expected: FAIL.

- [ ] **Step 3: Implement**

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd tm-control/ui && npm test && npm run build`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tm-control/ui
git commit -m "Offer sharing at first run, move the ThingsBoard token to the Sharing page, and export exact locations"
```

### Task 11: Docs, CLAUDE.md, and the READMEs

**Files:**
- Create: `docs/use/sharing.md` ("Share data"), `docs/assets/images/sharing-page.png` (a phone screenshot from fake mode, placeholder values only)
- Modify: `mkdocs.yml` (nav: after "Places and location"), `docs/use/control-app.md` (the pages list; first run has five steps), `docs/use/device-health.md` (the Sharing and Sharing server checks, with what each state means and what to do; the token's new home), `docs/use/home-page.md` and `docs/use/cameras.md` (the lines that describe Backup & Restore and the settings copy), `docs/use/location.md` (the export; the sharing line), `docs/data-and-payloads/integrations.md` (turning the upload on is done on the Sharing page; the list of what is sent; the "Config backup" section goes), `docs/configuration/node-red-config.md` (a `## sharing` section: written by the page, what a missing block means, that a choice can't be made in the file; the `thingsboard` section points at the page), `docs/build-your-own-device-diy/update.md` (what the upgrade does to a unit that already uploads, and that Backup & Restore and the settings upload are gone), `docs/help-and-faq/frequently-asked-questions.md` if it describes sharing, `docs/development/tm-control.md` (the `sharing` module, the follow step, the gate and its lists, the `upload` section of Node-RED's status and why tm-control never calls the server, the paragraph that says `config_tm` uploads the config), `tm-control/ui/README.md`, `CLAUDE.md` (the thingsboard tab's description, the camera-name contract's `config_tm` clause, the `sharing:` block and who writes it, `state.sqlite` holds the consents, the manifest's `sharing` section, the first-run steps)
- Test: `~/.venvs/tm-docs/bin/mkdocs build --strict`

- [ ] **Step 1: Write the page and the edits**

`docs/use/sharing.md`, in operator words: sharing is off until you turn it on; the two kinds of server and what differs (the notice, the map, and the responsibility sentence of decision 15); the token; the three choices with what each sends and doesn't, and that each is turned off where it was turned on; what the server already has stays there, and who to ask; how to tell whether the server is getting the data (the "Server status" line and the Status page's check), and that uploads that fail while the device is offline aren't sent again; what an upgraded device does and the "Review sharing" item; what `tmsetup.sh -f` does to sharing; that the exact location needs https. No server internals.

- [ ] **Step 2: Hand the notice to the maintainer**

Stop and show the maintainer `modules/sharing/NOTICE.md` (the draft below) and the page's three box texts. The PR stays a draft until they've edited them; a change to the notice's text after that is a new version.

- [ ] **Step 3: Build strictly**

Run: `~/.venvs/tm-docs/bin/mkdocs build --strict`
Expected: no warnings.

- [ ] **Step 4: Commit**

```bash
git add docs mkdocs.yml CLAUDE.md tm-control/ui/README.md tm-control/backend/tm_control/modules/sharing/NOTICE.md
git commit -m "Document sharing and the Sharing page"
```

### Task 12: Device tests

**Files:**
- Modify: `script/devpi/tests/test_web.py`, `test_dataflow.py`

**Interfaces:**
- Consumes: `admin_session`, `viewer_session`, `expect`, `node_red_config` (pii_free hosts), `host`.

- [ ] **Step 1: Write the tests**

`test_web.py`: `CONFIG_CHECKS` has `config.sharing` (Task 8); the status report has `apps.sharing_server` and it is `ok` on a unit that isn't sharing; the `/tm-internal/status` shape test expects `upload` with its four keys; `test_sharing_is_readable_by_a_viewer_and_writable_by_an_admin_only` (a viewer's `GET` has `writable` false and no token; a viewer's `PUT` is 403; the admin's `GET` is 200); `test_the_notice_is_served` (a version and non-empty markdown); `test_sharing_matches_config_yml` (pii_free: `enabled` equals the file's `thingsboard.enabled`, and with no `sharing:` block in the file the two choices are off). `test_dataflow.py`: `test_no_upload_node_sends_the_settings` (the deployed `flows.json`, read over SSH, has no `config_tm`).

- [ ] **Step 2: Check them off-device**

Run: `python -m pytest script/devpi/tests --collect-only -q 2>&1 | tail -3`
Expected: collected, no errors.

- [ ] **Step 3: Commit**

```bash
git add script/devpi/tests
git commit -m "Check the Sharing API and the removed settings upload on a device"
```

**Stop for review** before the Pi plan.

### Task 13: The Pi plan

Through `tmdev.py check start|item|status|end`, one host at a time, from a worktree (`script/devpi/README.md`). Deploy with `tmdev.py deploy <host> -- -t tm-control -t node-red-tm`. Frigate's detection, snapshots, and recording stay off throughout; no item needs them (system metrics and the deployment rows are uploaded without any event). Nothing printed may hold a token or a coordinate's digits.

Most items watch what the unit sends with a **capture listener**: a throwaway script run on the Pi through `tmdev.py run`, listening on the address `host.containers.internal` resolves to inside the pod, plain http, that answers 200 (or, when started with a flag, 401) and prints, per request, only: `telemetry` or `attributes`, the sorted top-level keys, for each deployment row the number of decimals in `lat` and `lon`, and whether `exact_location` and `public_map` are empty. The upload is pointed at it as an own server with a placeholder token typed on the page. The listener and the placeholder are removed at the end.

- [ ] **Bench A** (the pii_free unit with a camera and radar, on today's `dev`, with a place that has the example coordinates):
  1. **Upgrade with the upload on.** Before deploying the branch, turn the upload on by hand in `config.yml` toward the listener, with the placeholder token. Deploy. The Status page shows "Review sharing"; `GET /sharing` shows `share_data` granted as `pre-consent`; the listener sees no `config_tm`, no `sysinfo_ssid`, a `consents` attribute, and empty `exact_location` and `public_map`; deployment rows have at most two decimals.
  2. "I've reviewed this" clears the Status item.
  2a. **The server's status.** With the listener answering 200: the Sharing page and the Status page say an upload was accepted within a minute of the save. Stop the listener: within six minutes both say the server can't be reached (this also proves the http request node reports a connection that fails; if neither changes, stop and record it). Start it answering 401: both say the token was refused, with the link to the token. Back to 200: accepted again.
  3. The exact location over http is refused by the page with its reason; the box is disabled.
  4. Lower the precision to `1` on the Location page: the next deployment rows at the listener have one decimal. Set it back.
  5. Withdraw: turn "Share data" off; the listener goes quiet; `config.yml` has `enabled: false`; a withdrawal row exists (a count through `sqlite3` on `state.sqlite` as the code owner).
  6. `tmsetup.sh -f -t node-red-tm` with sharing on: afterwards the upload is off, the choices show as off on the page, and nothing was restored.
  7. A hand edit of `thingsboard.host` to a second listener port's host name while sharing is on: the page shows the new server with `share_data` as `pre-consent` and asks for a review.
  8. First run: `sudo tm-control reset-admin`, claim again: step 5 shows the paragraph and "Not now" without a token, and the form with one.
  9. A viewer opens `/sharing`, sees no form and no host; the Device page no longer lists the ThingsBoard token; the legacy dashboard's System Settings tab has no Backup & Restore section.
  10. "Export exact locations" downloads a file whose first line is the header (the header only is recorded).
  11. Device tests: `tmdev.py test <host> -- -k "sharing or notice or settings"`, then the full non-disruptive suite.
  12. Leave the unit not sharing, with no token, the listener gone, and the `.bak` files removed.
- [ ] **Bench B** (the maintainer, on the same unit): with a device token for the maintainer's server typed on the page by the maintainer, turn on "Share data" and "Share the exact location" over https; the Sharing page says the server accepted an upload; the maintainer confirms on the server that `consents`, `exact_location` (five decimals), and the rounded deployment rows arrived, then turns the exact location off and confirms `exact_location` is empty. The token is removed afterwards. Recorded as a maintainer-observed item.
- [ ] Record each item with `tmdev.py check item`, and end with `tmdev.py check end`.

### Task 14: Pull request

- [ ] Run every off-device check in Global Constraints once more on the final branch; `npm run build`; `git grep` the branch for device names and any coordinate other than the two allowed.
- [ ] Copy this plan to `design/plans/2026-11-13-location-4-upload-gate-and-sharing.md` and commit it ("Add the Sharing page plan").
- [ ] Open the PR against `dev` as a draft with the template filled in: the release-note paragraph ("The control app gains a Sharing page: choose the server, enter its token, and choose what the device shares. Uploads now carry the location as the database stores it; the exact location is sent only if an admin turns it on, and only over https. A device that already uploads keeps uploading and asks an admin to review. The upload of the device's settings and Backup & Restore to ThingsBoard are removed while they are reworked. The default server is tb.roadwaybiome.com; for any other server, making it honour these choices is the operator's responsibility."), the migration, the manifest's new section, the Docs list from Task 11, the Pi plan's results, the follow-ups (the database copy with exact locations, the map pin and block picker, re-sending corrections of past places, the reworked backup and settings upload), and the AI-assistance section. It leaves draft once the maintainer has edited the notice.

## Notice draft

For `modules/sharing/NOTICE.md`. A draft for the maintainer to edit; the first line is the version marker.

```markdown
<!-- notice-version: 2026-11 -->
# Sharing with Traffic Monitor's server

This notice covers what your device sends to Traffic Monitor's server (tb.roadwaybiome.com) and what is done with it. It doesn't cover a server you run yourself.

Sharing is off until you turn it on. Each choice below is separate, and you can turn each one off on this page at any time.

## Share data

Your device sends its counts, speeds, radar and air-quality readings, and its system health (versions, temperature, disk use, its name on your network, and its serial number). With them goes the location as your database stores it: rounded to about 1 km unless you chose otherwise on the Location page, or no location at all.

It doesn't send images, video, plate reads, your device's settings, your Wi-Fi details, or anything you typed as a description.

The data is used to operate the service and to study traffic. [Maintainer: who can see it, how long it is kept, and whether rounded data may be published.]

## Share the exact location

Your device also sends the exact coordinates of the place it is at. They are used to [maintainer: purpose], and they are not published.

Turning this off stops your device sending them. [Maintainer: what happens to exact locations already received.]

## Show this device on the public map

Not offered yet.

## Turning sharing off

Turning off "Share data" stops every upload. What the server already has stays there. To ask for it to be deleted, [maintainer: contact].

## Changes to this notice

If this notice changes, your device asks an administrator to read the new version. Sharing continues as you set it; anything new waits for your choice.
```

## Later

- **The database copy with exact locations** (design section 10), next: Node-RED makes the copy the download flow already makes and rewrites that copy's deployment rows from a list tm-control posts over the loopback; the live database is never touched. The download uses the existing `/storefiles` path. Its button goes beside "Export exact locations".
- **The map pin and the block picker** (design section 9), after that: a map library loaded only when an admin opens the map, the pin on the place form, the per-sensor block picker on the Sharing page, the block form of `public_map`, and the "Check your street" flag. The map needs the phone to have internet, which it doesn't have on the device's own hotspot.
- **Re-sending and backfilling** (the maintainer's feature): a correction of a past place, and history from before a consent, stay on the device until then.
- **Backup and the settings upload**, reworked by the maintainer; a new upload joins the gate's lists with a test.
