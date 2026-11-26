# A people check for the reference picture

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Series:** `data-pack`, four planned. This plan is PR 2. PR 1 = Download your data, on the Sharing page (#375), PR 3 = reference pictures the device takes and keeps, PR 4 = those pictures in the download.

**Goal:** When an admin takes a reference picture, the device says whether Frigate was tracking a person on that camera, including a person standing still, and the picture's data file lists what Frigate was tracking. It blocks nothing: the admin still looks at both pictures.

**Why it is its own PR:** PR 3 depends on it. With no admin watching, this check is what makes the device discard a pair of pictures with a person in it and try again, and what marks a stored picture `clear`, `person`, or `unchecked`. PR 2 on its own changes only the manual dialog and the data file.

**Architecture:**
- The check runs over MQTT. Frigate answers a message on `frigate/onConnect` with one on `frigate/camera_activity` that lists every object it is tracking on each camera, whether or not the object has moved. The broker is inside Node-RED, so Node-RED asks.
- Node-RED gets one more token-checked route under `/tm-internal`, for one camera key. It publishes the question, waits up to 3 seconds, and answers with that camera's objects: `label` and `stationary` only. Frigate's name for the camera, object ids, sub-labels, scores, and zones stay in Node-RED.
- The control app asks before the first frame and after the second. A `person` in either list is "seen". The result rides on the take's answer, and the two lists go into the data file, which becomes `format_version` 2.
- The first attempt at this check, dropped during #338, asked Frigate's `/api/events`, which lists an object only once it has a snapshot or a clip, and so never listed a person who hadn't moved.

**Tech Stack:** Node-RED 5.0.10 function nodes (JavaScript in `flows.json`) and its core `mqtt in`, `mqtt out`, and `delay` nodes; Python (FastAPI, pydantic 2; no new dependency); Vue 3 + Vuetify 3 + TypeScript (Vitest, jsdom; no new package); pytest with the function-node harness in `script/tests/test_node_red_flows.py`; the device tests in `script/devpi/tests`; Material for MkDocs.

**Spec:** "What it must do" below. The design it comes from is the maintainer's and isn't published.

**Repo:** `glossyio/traffic-monitor`, on `feature/data-pack-people-check/379` off `dev`. #379 is this PR's own issue, a sub-issue of #371. All paths below are relative to the repo root.

**Status:** written 2026-11-26 against `dev` at `f0c360a4` (#369 merged). Three PRs are open against `dev`, and this one needs none of them:
- **data-pack PR 1 (#375):** edits `flows.json` (two functions: "tm-internal: build status" on `init-config`, "Validate filenames, setup tar" on `ui-database`), `fake.py`, `test_fake_nodered.py`, `test_node_red_flows.py`, `test_web.py`, the API files, `tests/fake-api.ts`, the UI's README, `docs/development/tm-control.md`, and `CLAUDE.md`.
- **setup-history PR 2 (#373):** edits `flows.json` (on `init-config`, the "setup engine" function, a new `link out`, and the setup group's `nodes`; on `thingsboard`, the upload gate and a new group), `test_node_red_flows.py`, one sentence of `docs/use/cameras.md` (under "Zone names are saved with your data"), and `CLAUDE.md`.
- **mounting PR 3 (#374):** the Location module's UI, `docs/development/tm-control.md`, the UI's README, and `CLAUDE.md`.
- **None of the three touches** `modules/cameras/`, `ReferencePicture.vue`, `reference.ts`, the reference picture's tests, or `adapters/nodered.py`.
- **`flows.json` merges one at a time.** #373 and #375 each change nodes that exist; this PR only adds nodes and lengthens one group's `nodes` list (the status group, `d9d94c0d493873b9`, which neither of them edits). Whichever PR merges after another redoes its own edit on the new file with a script. Nobody resolves the JSON's text conflict by hand. For this PR that means: run Task 2's edit again on the new `dev`, with the same node ids, and place the group below whatever is lowest on the tab then.
- **Text files that will need a rebase** after one of them merges: `CLAUDE.md`, `docs/development/tm-control.md`, `docs/use/cameras.md`, `fake.py`, `test_fake_nodered.py`, `test_node_red_flows.py`, `test_web.py`, the API files, `tests/fake-api.ts`, and the UI's README. The API files are regenerated, never merged.
- This plan adds no migration, to tmdb or to `state.sqlite`.

**Size** (estimates): about 30 files, +900 to 1100 lines, a little over half of it tests and docs. To maintain afterwards: one more internal route (eleven nodes and a group); a contract with the shape of Frigate's `camera_activity` message, which a device test checks after every Frigate upgrade; and a data file at version 2.

**Decisions.** The maintainer's are marked. The rest are calls made while writing this, open to change.

1. **The check runs over MQTT, from Node-RED (maintainer, the design).**
2. **Only `label` and `stationary` leave Node-RED (maintainer, the design).**
3. **The control app asks before the first frame and after the second (maintainer, the design).**
4. **The result blocks nothing (maintainer, the design).** Save the zip works whatever the result is.
5. **The data file gains `objects` and goes to `format_version` 2 (maintainer, the design).**
6. **The dialog and the docs state the check's limits (maintainer, the design).**
7. **The three result lines and the note are drafts for the maintainer to edit** before the dialog is built (Task 4, Step 1).
8. **The route is `GET /tm-internal/cameras/:key/objects`,** and its answer is `{"answered": …, "objects": …}`. The name and the shape are this plan's.
9. **Node-RED decides when there is no list to trust.** Frigate's answer says whether detection is on for each camera (`config.detect`). With detection off the camera's list is empty, which would read as "nobody". So Node-RED answers a list only when Frigate says detection is on, and `null` otherwise. The control app never reads Frigate's detection a second time, and nothing but the two fields leaves Node-RED.
10. **A recognized person counts as a person.** Frigate lists an object that has a sub-label as `person-verified`. Node-RED removes `-verified`, as Frigate's own counts do, so the control app compares with `person` alone.
11. **No id ties an answer to a question.** Frigate publishes `camera_activity` on the broker only as an answer to an `onConnect`, so any such message that arrives after a question is current. One answer serves every waiting question. A Frigate page that opens in a browser sends its own `onConnect`; its answer reaches the broker too and is as good.
12. **The second question is skipped when the first gave no list.** A take then waits 3 seconds at most for the check, not 6.
13. **A person in either list is "seen", even when the other question failed.** "None" needs both lists.
14. **Waiting questions are not capped.** Each lives 3 seconds, and only an admin's take asks one.
15. **The names in the control app are this plan's:** `modules/cameras/people.py`, `NodeRed.tracked`, `ReferenceOut.people` (`seen`, `none`, `unchecked`), and the data file's `objects` block (`checked`, `before`, `after`, `person`).
16. **The fallback is not built.** The design's fallback (Frigate's running counts, and "not known" until a count arrives) was for a Frigate that doesn't answer `onConnect` on the device's broker. Its source says it does (below), and Task 1 confirms it on a bench unit before anything else is built.
17. **Plate Recognizer is shelved and is the exception here:** no change, pin, or bench item for it.

## What it must do

1. **The question.** `GET /tm-internal/cameras/:key/objects` on `127.0.0.1:1880`, with `X-TM-Internal-Token`, where `:key` is a `sensors.cameras` key. Without the token: 401, as every internal route. For a key that isn't a value of the `frigate_cameras` global: 404 `{"error": "unknown_camera"}`, and nothing is published.
2. **Asking Frigate.** For a known key, Node-RED publishes one message on `frigate/onConnect` (empty payload, QoS 0, not retained) and waits up to 3 seconds for a message on `frigate/camera_activity`.
3. **The answer,** always 200:
   - `{"answered": true, "objects": [{"label": "car", "stationary": true}, …]}` when Frigate answered and has a list to trust for the camera. The objects are in Frigate's order.
   - `{"answered": true, "objects": null}` when Frigate answered and has none.
   - `{"answered": false, "objects": null}` when no `frigate/camera_activity` came within 3 seconds.
4. **A list to trust.** Frigate's message is a JSON object keyed by Frigate's camera names. The camera's entry is the one whose name `frigate_cameras` maps to the key. There is a list only when all of these hold: the entry is an object; its `config` is an object with `detect` exactly `true` and `enabled` not `false`; the entry's own `enabled` is not `false`; and its `objects` is an array. Anything else, the message not being an object included, is "none".
5. **Each object.** `label` is the object's `label` when that is a string of 1 to 64 characters, with one trailing `-verified` removed; otherwise `"unknown"`. `stationary` is `true` only when the object's `stationary` is exactly `true`. An element that isn't an object is listed as `{"label": "unknown", "stationary": false}`, so the count stays right. No other field is read.
6. **What stays in Node-RED.** Frigate's camera name, object ids, sub-labels, scores, areas, ratios, and zones are in no answer, no log line, and no message that leaves the three functions. The functions log nothing and never throw: a message they can't read is "none".
7. **The control app's two questions.** `POST /api/v1/cameras/{name}/reference` asks Node-RED once after the take's existing checks and before the first frame, and once after the second frame. When the first gives no list, the second isn't asked. A question that Node-RED refuses, doesn't answer within 5 seconds, or answers in another shape gives no list. The take never fails because of the check.
8. **The result.** With the two lists `before` and `after`:
   - `person` is `true` when either list holds an object whose label is `person`; `false` when both are lists and neither does; `null` otherwise.
   - `checked` is `true` when both are lists.
   - The take's answer gains `people`: `seen` for `person` true, `none` for false, `unchecked` for `null`.
9. **The data file.** `format_version` is 2. After `zones` it gains:

   ```json
   "objects": {
     "checked": true,
     "before": [{"label": "car", "stationary": true}],
     "after": [{"label": "car", "stationary": true}, {"label": "person", "stationary": false}],
     "person": true
   }
   ```

   `before` and `after` are `null` when that question gave no list. Nothing else in the file, the zip, or the drawing changes.
10. **The dialog.** After a take, one line sits above the two pictures and below the note: a warning for `seen`, a plain information line for `none` and for `unchecked`. It follows the newest take. Before a take there is no line. Close, Take again, and Save the zip work the same for all three.
11. **The words** (drafts, Decision 7).
    - `seen`: "Frigate was tracking a person on this camera when the pictures were taken. Wait until nobody is in view, then take them again."
    - `none`: "Frigate wasn't tracking a person when the pictures were taken. It can miss people, so look at both pictures yourself."
    - `unchecked`: "The device couldn't check for people, because Frigate's detection is off for this camera or Frigate didn't answer. Look at both pictures yourself."
    - The note, shown on both steps: "This picture shows your street. Anyone who has it can tell where the unit is, and it shows whoever was in view. When the pictures are taken, the device asks Frigate whether it is tracking a person on this camera, and says so above them. That works only while Frigate's detection is on for the camera. Frigate can miss a person who is far away, half hidden, or in poor light, or who walks in between the two pictures. You are still responsible for making sure nobody is in either picture before you save them: look at both, and if anyone is in them, wait and take them again. Share them only with people you would give the unit's exact location. The data file also holds that location unless you clear the box below."
12. **The limits,** said in the note and in the docs:
    - It works only while Frigate's detection is on for the camera. A unit as installed has detection off, so there the line is the `unchecked` one.
    - Frigate lists an object only once it is confident of it. A person far away, half hidden, or in poor light can be missed, and so can one who walks in between the two pictures and the two questions.
    - A person standing still is listed.
13. **Fake mode.** `FakeNodeRed` answers the question, so the whole take works on a laptop, and each of the three lines can be reached there without changing code.
14. **What doesn't change:** the take's refusals and their words; the tickets and the ten minutes; the zip's four files and their names; the drawing and its caption; the audit rows (`camera.reference`, `camera.reference_saved`, `camera.reference_saved_with_location`, each with the camera's key and nothing else); Frigate's settings. Nothing here turns detection on or off.

## Where the code stands that this plan touches

Read at `dev` `f0c360a4`.

- **Frigate 0.18.2** (the version `vars/main.yml` pins), in the image's `/opt/frigate/frigate/`. The six files below are byte for byte the same in 0.18.1 and 0.18.2.
  - `comms/mqtt.py`: `_on_connect` subscribes to `frigate/#` (line 229). `_start` registers `frigate/onConnect` with `message_callback_add` (lines 329 to 331), so it reaches `on_mqtt_command` (line 192), which hands the topic to the dispatcher. `publish` (line 28) sends to `frigate/<topic>`.
  - `comms/dispatcher.py`: `handle_on_connect` (line 270) is in `topic_handlers` under `"onConnect"` (line 353). It publishes `camera_activity` (line 312) with `self.publish` (line 396), which sends to every communicator, the MQTT client included, not retained. It adds a `config` block to each camera, with `detect` and `enabled` among its keys. It also publishes `model_state`, `embeddings_reindex_progress`, `birdseye_layout`, `audio_detections`, and a retained `profile/state`, which nothing on the device reads.
  - `camera/state.py` (lines 504 to 533): a camera's entry is `motion` and `objects`. Each object has `id`, `label`, `stationary`, `area`, `ratio`, `score`, `sub_label`, and `current_zones`, and only objects that aren't a false positive are listed. An object with a sub-label that isn't one of the model's attributes is labelled `<label>-verified` (line 521).
  - `track/tracked_object.py` (`_is_false_positive`): an object stops being a false positive once the median of its scores reaches the label's threshold. It need not have moved, entered a zone, or been saved.
  - `video/detect.py` (line 299): with detection off the tracker is fed an empty list each frame, so the camera's `objects` empties.
  - `camera/activity_manager.py`: `last_camera_activity` is what `handle_on_connect` reads. A camera that has processed no frame yet has an entry with no `objects`.
- **Flows** (`container/node-red-tm/data/flows.json`).
  - The `init-config` tab is `3dae026ab340962a`. The status group `d9d94c0d493873b9` ("tm-control status: GET /tm-internal/status") holds the status route's nodes and two groups, the surveys group `3da2c0e89c06736d` and the setup-history group `fc8558ca801e2e70`, which carries `"g": "d9d94c0d493873b9"`.
  - Every internal route starts `http in` → "tm-internal: check token" (two outputs; the second to an `http response` with `statusCode` `"401"`). The token check's code is the same in each; `cbc268130cc14c58` is the status route's.
  - A route with a path to check goes on to a validator function with two outputs, the second to an `http response` with a fixed status. `/tm-internal/surveys/:id/recorded` (`1302b2050d34200f`) is the newest example.
  - The broker's configuration node is `a5d65dd0e3566daa` ("mqtt-broker-local"). `mqtt in` nodes use it for `frigate/events` (`f20c74c0ccfd256c`), `frigate/stats` (`1c84b05d58e12d41`), and `frigate/available` (`e17b4d90c6a3f528`). The only `mqtt out` is `tm/events` (`d856c68660eb2202`). The login lives on the configuration node, so `flows_cred.json` knows nothing about `mqtt in` or `mqtt out` nodes.
  - "try again in 15 s" (`4c7e2a9b6d1f3085`) is a `delay` node, the model for the timer.
  - "tm-internal: keep exact copy list" (`74bbeec1de9cbb88`) keeps a request's data in flow context, the model for the waiting questions.
  - "init config defaults" (`94136e5a6f092bb6`) sets the global `frigate_cameras`: Frigate's name to the `sensors.cameras` key, for every entry, on or off. "keep frigate camera switch" (`8fab4008b7bc52b7`) is the model for reading it: `isMapping`, an own-property check, and a string check.
  - `settings.js` keeps context in memory (`contextStorage.default.module: "memory"`) and sets `functionTimeout: 0`.
- **Flows tests** (`script/tests/test_node_red_flows.py`): `run_functions(steps, env=, context=, flow=, modules=)` runs function nodes in turn over one global context and one flow context; `named(flows, name)`; `tab_id`; `reachable`; `TM_INTERNAL_PATHS`, `TM_INTERNAL_METHODS`, `VALIDATORS`, and `REFUSAL_STATUS`, which `test_every_tm_internal_endpoint_checks_the_token_first` and `test_refused_requests_reach_no_sql` read. The harness has no `node.send` and no node context: a function under test returns its messages and keeps state in flow context.
- **The control app** (`tm-control/backend/tm_control/`).
  - `adapters/nodered.py`: `NodeRed._call(method, path, query, body)` raises `NodeRedError` (`unreachable`, `refused`, `bad_request`, `database_error`, `unexpected`); `_object(path, query)`. `adapters/httpjson.py`: `TIMEOUT = 3` seconds, and `get` and `post` take a `timeout`.
  - `modules/cameras/router.py`: `take_reference` reads Frigate's config, refuses with `_changed`, `_camera_off`, or `_no_picture`, takes the two frames (`clean_at`, `zones_at`), and keeps them with `app_state.references.keep(...)`. `ReferenceOut` is its answer. `_open_deployment` already calls `app_state.nodered` and lives with a Node-RED that doesn't answer.
  - `modules/cameras/reference.py`: `FORMAT_VERSION = 1`, the frozen dataclass `Reference`, and `data_file(reference, with_location)`.
  - `fake.py`: `FakeNodeRed(config_path)`, built in `app.py` for fake mode; `frigate_answer(settings)`, which applies the fake detection switches (`_detect_switches`).
- **Backend tests:** `test_api_cameras_reference.py` (`admin`, `take`, `taken`, `data`, `audit_rows`, `frames`, `test_audit_rows_carry_the_key_and_no_log_holds_a_ticket_point_or_frigate_name`), `test_cameras_reference.py` (`reference(**changes)`, `test_the_data_file`), `test_nodered_adapter.py` (the `wire` fixture, `answer`), `test_fake_nodered.py`.
- **The UI** (`tm-control/ui/`): `src/modules/cameras/ReferencePicture.vue` (`INTRO`, `NOTE`, the alert marked `data-note`, the two pictures in a `v-row`), `src/modules/cameras/reference.ts` (`ReferenceOut`, `legendRows`), `tests/reference-picture.spec.ts` (`NOTE`, `dialog()`, `pictures()`), `tests/fake-api.ts` (`referenceOut(changes)`), and the README's paragraph that starts "Reference picture: an entry in step offers it".
- **Device tests** (`script/devpi/tests/`): `devpi_checks.py` has `require_pii_free`, `broker_login(host, expect, codedir)`, `PI_MQTT_PUBLISH` and `publish_on_pi` (a raw MQTT 3.1.1 client run on the Pi with `python3 -c`), and `tm_internal_answer(host, token, url, body)`. `test_cameras.py` has the `cameras`, `frigate_config`, and `frigate_stats` fixtures in use. `test_web.py` has `test_a_reference_picture_is_a_zip_of_four_files`, `test_tm_internal_is_hidden_behind_the_proxy`, and `test_tm_internal_needs_the_token_on_the_pi`.
- **Docs.** `docs/use/cameras.md`: "Take a reference picture" (its steps, "What the picture gives away" with the note quoted, "The data file"). `docs/data-and-payloads/integrations.md`: the MQTT topics table. `docs/development/tm-control.md`: the reference picture's paragraph (it starts "The reference picture's pictures live only in") and the tables of internal routes. `CLAUDE.md`: the Cameras clause of the `tm-control/` bullet, the `frigate_cameras` name contract, and "Node-RED's internal status".

## Global Constraints

- **The names, the answer's shape, and the words are those in "What it must do".** No task picks another, and the words change only by the maintainer's edit.
- **`flows.json`:** only the nodes in Task 2's list are added, and only the status group `d9d94c0d493873b9` is edited. Edit the file with a script and write it back with `json.dumps(flows, indent=4, ensure_ascii=False)` and no trailing newline. Don't open the Node-RED editor on it. `flows_cred.json` is not touched.
- **Frigate's name for a camera stays where it is today:** the `frigate_cameras` and `camera_labels` globals and the `frigate_facts` flow context. It goes on no message and in no flow context here. A waiting question holds the camera's key.
- **Nothing about an object in a log line, an audit row, or an error message,** in Node-RED or the control app: no list, label, or count.
- **The control app never talks to the broker.** It asks Node-RED.
- **Nothing here turns Frigate's detection, snapshots, or recording on or off.** On a dev Pi they stay off, except for Task 6's one item, which is the maintainer's to consent to each time, with a count, for a bench test only; detection goes back to false after, confirmed in Frigate's `/api/config` with `X-Cache-Bypass: 1`, and recorded in the `tmdev check`.
- **No session looks at a picture.** Bench checks and device tests read statuses, headers, sizes, keys, and counts. What a picture shows is for the maintainer's eyes.
- **No coordinate in any fixture, commit, PR text, or screenshot** other than the docs' example `45.52252, -122.69120` and the fixtures' `45.0, -122.0`.
- **Python:** CI and the devices run 3.13, where annotations are read when a class is made. Run the backend suite once under Python 3.13 or older before the hand-off.
- **UI work follows `tm-control/ui/README.md`:** conventional Vuetify, the one dark theme, system fonts, 44 px buttons, results beside the form, no toasts, sentence case. The UI task's implementer loads the `frontend-design` skill and works test-first; the README's rules win over the skill's taste. New design notes go in the README.
- The API files (`tm-control/ui/src/api/openapi.json`, `schema.d.ts`) are regenerated in the same commit as any model change.
- Plate Recognizer is shelved: no change, pin, or bench item for it.
- Every commit ends with the trailer block from the repo's `CLAUDE.md` (Assisted-by / AI-Model / AI-Effort / AI-Role); never `Co-Authored-By`. Docs follow "Writing docs" in `docs/development/contributing.md`; `mkdocs build --strict` passes. Nothing public names a device, a bench site, a partner, or a tool.
- The PR's title starts `data-pack PR 2: `, and its first body line is the `Series:` line.
- Off-device checks before each commit, from the repo root in the dev venv: `python -m pytest container/node-red-tm/schema/tests script/tests tm-control/backend/tests`; for the UI task also the pinned Node image's `npm ci && npm run build && npm test`; for the docs task `~/.venvs/tm-docs/bin/mkdocs build --strict`.

## Review Focus

1. **Detection is off, which is how every unit is installed.** Frigate still answers, with an empty list. That must read as `unchecked`, never as "Frigate wasn't tracking a person". Tests in Task 2 (`test_no_list_when_frigate_has_none_to_trust`, the `detect: false` row), Task 3 (`test_no_list_is_unchecked_and_the_second_question_is_not_asked`), and Task 5 (the device test on a unit as installed).
2. **Frigate is restarting or isn't on the broker; Node-RED is stopped; or, during an update, the new control app meets flows without the route.** The take still gives its pictures, with the `unchecked` line, after at most one wait. Tests in Task 2 (`test_the_timer_answers_a_question_frigate_left_unanswered`) and Task 3 (`test_node_red_failing_is_unchecked_and_the_take_still_works`, for `unreachable`, `refused`, and `unexpected`).
3. **A message that isn't what the source promises:** not an object, the camera missing, `objects` not a list, an element that isn't an object, a label that isn't a string, a very long label, `person-verified`. None may throw, log, or hide an object. Tests in Task 2 (`test_no_list_when_frigate_has_none_to_trust`, `test_an_odd_object_is_listed_as_unknown`, `test_person_verified_is_person`).
4. **A person seen by one question only, or a second question that fails.** A person in either list is `seen`; a clean first list with no second is `unchecked`, not `none`. Tests in Task 3 (`test_facts`, `test_a_person_in_either_list_is_seen`).
5. **More than one question waiting, a stray answer, and a late timer.** Two takes at once each get their own camera's list from one answer; an answer with nobody waiting does nothing; a timer for a question already answered does nothing. Tests in Task 2 (`test_one_answer_serves_every_waiting_question`, `test_a_late_timer_or_a_stray_answer_does_nothing`).
6. **A reader of the data file written for version 1.** Every version 1 key keeps its name, its meaning, and its place; `objects` comes last. Test in Task 3 (`test_the_data_file_keeps_version_1s_keys_in_order`), and the docs say what changed.

A viewer is covered already: the take is admin-only, and its tests stand.

---

### Task 1: Confirm on a bench unit that Frigate answers

This task comes first because the rest of the plan rests on it. It needs no deploy: it tests Frigate and the broker as installed. Detection stays off, so the answer lists no object and the item needs no consent.

**Files:**
- Modify: `script/devpi/tests/devpi_checks.py`, `script/devpi/tests/test_cameras.py`, `script/devpi/README.md` (the row for `test_cameras.py`)

**Interfaces:**
- Produces, `devpi_checks.py`:
  - `PI_MQTT_ASK`: a script run on the Pi with `python3 -c`, on the model of `PI_MQTT_PUBLISH`. Arguments: the topic to publish on, the topic to wait on, the port, and the seconds to wait. The broker's login, when one is set, comes on standard input as two lines, never as an argument. It connects (MQTT 3.1.1, clean session, client id `tmdev-ask`), subscribes to the second topic at QoS 0, waits for the SUBACK, publishes an empty message on the first, and reads packets until a PUBLISH on the second topic or the time is up. It prints one JSON line and nothing else: `{"connack": <code>, "cameras": null}` when no answer came, else `{"connack": 0, "cameras": {"<name>": {"objects": <the list's length, or null when it isn't a list>, "detect": <config.detect when it is a boolean, else null>}}}`. A packet's remaining length can take up to four bytes, and a PUBLISH can arrive in several reads.
  - `ask_frigate_on_pi(host, login, wait=5) -> dict | None`: runs it for `frigate/onConnect` and `frigate/camera_activity` on port 1883 and returns `cameras`. It raises with the CONNACK code when the broker refuses.
- Produces, `test_cameras.py`: `test_frigate_answers_on_connect(host, expect, codedir, cameras, frigate_config)`.

- [ ] **Step 1: Write the helper and the test.** The test:
  - calls `require_pii_free(expect)` first, because it reads the broker's login and Frigate's camera names;
  - asserts an answer came within 5 seconds, with the message "Frigate didn't answer frigate/onConnect on the Pi's broker within 5 s: the people check has nothing to ask";
  - asserts every camera in Frigate's config is in the answer and has a boolean `detect`;
  - asserts that a camera whose `detect` is false has an `objects` count of 0 or `null`;
  - keeps and prints counts and booleans only.
- [ ] **Step 2: Run it on the bench unit** from this branch's worktree: `tmdev.py test <host> -- -k frigate_answers_on_connect`. Expected: PASS, with detection off on every camera.
- [ ] **Step 3: If it fails because no answer came, stop and hand back.** The design's fallback (Frigate's running counts) would change this plan's shape, so the maintainer decides before anything else is built.
- [ ] **Step 4: Run** `python -m pytest script/tests`. PASS.
- [ ] **Step 5: Commit** ("Check on a device that Frigate answers frigate/onConnect").

### Task 2: The route in the flows (tricky)

**Files:**
- Modify: `container/node-red-tm/data/flows.json`
- Test: `script/tests/test_node_red_flows.py`

**The node list.** All new, on `init-config`, in one new group. Each id was made with `secrets.token_hex(8)` and checked against the file; the ids are in the table.

| # | Id | Node | Type | Wired to |
| --- | --- | --- | --- | --- |
| 1 | `969b8b5120b7e87b` | `GET /tm-internal/cameras/:key/objects` | `http in` | 2 |
| 2 | `7b59c1b92c0c6cb6` | "tm-internal: check token" (the code of `cbc268130cc14c58`, unchanged) | function, 2 outputs | 4; 3 |
| 3 | `68333edaabc5064f` | status `401` | `http response` | |
| 4 | `53992660181dd7d9` | "tm-internal: validate objects path" | function, 2 outputs | 6; 5 |
| 5 | `c6ff13ce34c4714d` | status `404` | `http response` | |
| 6 | `2281542cb441d61c` | "tm-internal: start objects ask" | function, 2 outputs | 7; 8 |
| 7 | `4e60c2599c2da813` | "ask frigate what it is tracking": topic `frigate/onConnect`, QoS 0, not retained, broker `a5d65dd0e3566daa` | `mqtt out` | |
| 8 | `1bde3531c63931aa` | "no answer after 3 s": `pauseType` `delay`, `timeout` `3`, `timeoutUnits` `seconds`, as "try again in 15 s" is set | `delay` | 10 |
| 9 | `96980e66c68fe282` | `frigate/camera_activity`: QoS 0, broker `a5d65dd0e3566daa`, `datatype` `auto-detect` as `frigate/events` has, so the JSON arrives parsed | `mqtt in` | 10 |
| 10 | `8bf2df3d3181c2e3` | "tm-internal: answer objects asks" | function, 1 output | 11 |
| 11 | `39ff6f00770ddc9e` | the answer, no fixed status | `http response` | |
| 12 | `84a83f7efd9a8e45` | "tm-control people check: GET /tm-internal/cameras/:key/objects", with `"g": "d9d94c0d493873b9"` | group | |

Edited: the status group `d9d94c0d493873b9`, whose `nodes` gains the new group's id and whose size grows to hold it. Place the new group below the lowest group inside it.

**Interfaces:**
- Produces, node 4: for a key that is a string and a value of the `frigate_cameras` global, output 1 with `msg.cameraKey` set to it. Otherwise output 2 with `msg.payload = {error: "unknown_camera"}`. A Frigate name that isn't also a key is unknown.
- Produces, node 6: it takes the next number from the flow context `objects_ask_seq`, keeps the request message under it in the flow context `objects_asks` as `{key, msg}`, and returns two new messages: `{topic: "frigate/onConnect", payload: ""}` on output 1 and `{ask: <number>}` on output 2. The request message itself is sent nowhere until it is answered, because it waits there until an answer or the timer comes, and only then goes to the response node.
- Produces, node 10: one function for both inputs.
  - A message with `topic` `frigate/camera_activity`: for every waiting question, the kept request message with `payload` set by items 3 to 5 of "What it must do" and `statusCode` 200; `objects_asks` is then empty. With nobody waiting it returns nothing.
  - A message with `ask`: when that question still waits, its request message with `payload = {answered: false, objects: null}` and `statusCode` 200, and the question is removed. Otherwise nothing.
  - It returns an array of messages on its one output, logs nothing, and never throws.
- Each function opens with a comment that says what it is for, that only `label` and `stationary` leave, and why detection off is "no list".

- [ ] **Step 1: Write the failing tests.**
  - The constants: the path joins `TM_INTERNAL_PATHS`, `TM_INTERNAL_METHODS` (`"get"`), `VALIDATORS` (`"tm-internal: validate objects path"`), and `REFUSAL_STATUS` (`"404"`).
  - `test_the_objects_route_is_wired`: the table above, node by node: types, names, the wires, the `mqtt out`'s topic, QoS, and retain, the `mqtt in`'s topic and QoS, both brokers `a5d65dd0e3566daa`, the delay's 3 seconds, every node's `z` the `init-config` tab and `g` the new group, and the group's `g` the status group.
  - `test_objects_validator(key, known)`, with `frigate_cameras = {"picam_h265": "camera_1_3fa9c2"}`: `camera_1_3fa9c2` passes with `cameraKey`; `picam_h265`, `""`, a missing parameter, and `__proto__` are refused with 404's payload; with the global unset, or set to a list, every key is refused. Nothing is logged.
  - `test_a_question_publishes_on_connect_and_starts_the_timer`: output 1 is exactly `{"topic": "frigate/onConnect", "payload": ""}`; output 2 is exactly `{"ask": 1}`; `objects_asks` holds the request under 1 with the key; a second question gets 2.
  - `test_an_answer_lists_label_and_stationary_only`: a payload whose object has an id, a score, an area, a ratio, a sub-label "A Name", and a zone gives `{"answered": true, "objects": [{"label": "person", "stationary": true}]}` with status 200, and the answering message's JSON holds none of "A Name", the id, the zone, or `picam_h265`. `objects_asks` is empty after.
  - `test_person_verified_is_person`: `person-verified` gives `person`; `car-verified` gives `car`; a label that is only `-verified` gives `unknown`.
  - `test_no_list_when_frigate_has_none_to_trust(payload)`: each gives `{"answered": true, "objects": null}`:
    - `config.detect` false with `objects` `[]`;
    - `config.detect` false with a person listed;
    - `config` missing; `config.detect` the string `"true"`;
    - `config.enabled` false; the entry's own `enabled` false;
    - `objects` missing; `objects` an object;
    - the camera not in the message; a camera under a name `frigate_cameras` doesn't hold;
    - the payload a string, `null`, a number, and a list.
  - `test_an_odd_object_is_listed_as_unknown`: the elements `7`, `null`, `{}`, `{"label": 5}`, and a label of 65 characters each give `{"label": "unknown", "stationary": false}`, in place; `stationary` of `"true"` or `1` gives `false`.
  - `test_one_answer_serves_every_waiting_question`: two questions for two cameras; one message; two answers, each with its own camera's list.
  - `test_the_timer_answers_a_question_frigate_left_unanswered`: `{"ask": 1}` gives `{"answered": false, "objects": null}` with status 200, and the question is gone.
  - `test_a_late_timer_or_a_stray_answer_does_nothing`: a timer for a question already answered, and a `camera_activity` with nobody waiting, each return nothing and log nothing.
  - `test_the_objects_functions_log_nothing`: none of the three functions' code holds `node.warn`, `node.error`, `node.log`, or `console.`.
- [ ] **Step 2: Run** `python -m pytest script/tests/test_node_red_flows.py -k "objects or tm_internal or refused"`. The new ones fail.
- [ ] **Step 3: Add the nodes** with a script, and check `python3 -m json.tool container/node-red-tm/data/flows.json >/dev/null`.
- [ ] **Step 4: Run** `python -m pytest script/tests`. PASS. `git diff --stat` shows `flows.json` and the test file only, and the diff of `flows.json` holds added lines and the status group's two changes, nothing else.
- [ ] **Step 5: Commit** ("Ask Frigate what it is tracking on a camera, from Node-RED").

### Task 3: The control app asks, and the data file says

**Files:**
- Create: `tm-control/backend/tm_control/modules/cameras/people.py`, `tm-control/backend/tests/test_cameras_people.py`
- Modify: `tm-control/backend/tm_control/adapters/nodered.py`, `tm-control/backend/tm_control/fake.py`, `tm-control/backend/tm_control/modules/cameras/reference.py`, `tm-control/backend/tm_control/modules/cameras/router.py`, `tm-control/ui/src/api/openapi.json`, `tm-control/ui/src/api/schema.d.ts`, `tm-control/ui/tests/fake-api.ts` (`referenceOut` gains `people: 'none'`)
- Test: `tm-control/backend/tests/test_nodered_adapter.py`, `test_fake_nodered.py`, `test_cameras_reference.py`, `test_api_cameras_reference.py`

**Interfaces:**
- Consumes: Task 2's route and answer.
- Produces, `adapters/nodered.py`:
  - `OBJECTS_TIMEOUT = 5.0`: longer than Node-RED's 3-second wait; the adapter's default is 3.
  - `NodeRed._call(self, method, path, query=None, body=None, timeout: float | None = None)`, which passes `timeout` to `httpjson`.
  - `NodeRed.tracked(self, camera: str) -> _Tracked | None` (`_Tracked = list[dict]`, a module-level alias): `GET /cameras/<the key, quoted with safe="">/objects` with `OBJECTS_TIMEOUT`. It returns the list as `{"label": str, "stationary": bool}` dicts with no other key, or `None` when `objects` is `null`. It raises `NodeRedError("unexpected")` unless the body is an object whose `answered` is a boolean and whose `objects` is `null` or a list of objects, each with a string `label` and a boolean `stationary`.
- Produces, `modules/cameras/people.py`:
  - `PERSON = "person"`
  - `Result = Literal["seen", "none", "unchecked"]`
  - `ask(nodered, camera: str) -> list[dict] | None`: `nodered.tracked(camera)`, or `None` on a `NodeRedError`. It logs nothing.
  - `facts(before: list[dict] | None, after: list[dict] | None) -> dict`: the data file's `objects` block, by item 8.
  - `result(objects: dict) -> Result`
- Produces, `reference.py`: `FORMAT_VERSION = 2`; `Reference.objects: dict`, after `zones`; `data_file` adds `"objects": reference.objects` as its last key. The module's opening comment and `data_file`'s say what the block is.
- Produces, `router.py`:
  - `ReferenceOut.people: people.Result`, with a comment: what Frigate was tracking when the pictures were taken.
  - In `take_reference`: `before = people.ask(app_state.nodered, name)` after the `_sending` check and before the first frame; after `zones_at`, `after = people.ask(app_state.nodered, name) if before is not None else None`; the reference is kept with `objects=people.facts(before, after)`.
  - The module's opening comment loses "The device doesn't check the pictures for people" and says what the check is, that it blocks nothing, and that no list is logged or audited.
- Produces, `fake.py`: `FakeNodeRed.tracked_objects: list[dict] | None`, starting as `[{"label": "car", "stationary": True}]`, and `FakeNodeRed.tracked(camera)`, which answers a copy of it, or `None` when it is `None`. In fake mode it also answers `None` for a camera whose fake detection switch is off, so the Cameras page's switch gives the `unchecked` line. How fake mode is told to list a person is the builder's choice; an environment variable read where `app.py` builds the fake is enough. Say it in the UI's README beside the other fake-mode notes.

- [ ] **Step 1: Write the failing tests.**
  - `test_nodered_adapter.py`:
    - `test_tracked_asks_by_the_key_and_keeps_two_fields`: for the key `camera 1/a`, the URL ends `/tm-internal/cameras/camera%201%2Fa/objects`, the token header is sent, the timeout is 5, and an object answered with an extra `score` comes back without it.
    - `test_tracked_is_none_without_a_list`: `{"answered": true, "objects": null}` and `{"answered": false, "objects": null}`.
    - `test_tracked_refuses_another_shape(body)`: a list, `{}`, `{"answered": "yes", "objects": []}`, `{"answered": true, "objects": {}}`, an object with no `label`, a `label` of 5, a `stationary` of `"true"`: each raises `unexpected`.
    - `test_tracked_raises_when_node_red_refuses_or_is_silent`: 401 gives `refused`; a 404 (flows without the route) gives `unexpected`; no answer gives `unreachable`.
  - `test_cameras_people.py`:
    - `test_facts(before, after, expected)`, with `car = {"label": "car", "stationary": True}` and `walker = {"label": "person", "stationary": False}`:

      | before | after | checked | person |
      | --- | --- | --- | --- |
      | `[car]` | `[car]` | true | false |
      | `[]` | `[]` | true | false |
      | `[car]` | `[car, walker]` | true | true |
      | `[walker]` | `[]` | true | true |
      | `[walker]` | `None` | false | true |
      | `[car]` | `None` | false | `None` |
      | `None` | `None` | false | `None` |

      and the block's `before` and `after` are the lists given.
    - `test_a_person_standing_still_is_a_person`: `{"label": "person", "stationary": True}`.
    - `test_only_the_label_person_counts`: `person-verified`, `Person`, and `unknown` are not a person.
    - `test_result`: true gives `seen`, false `none`, `None` `unchecked`.
    - `test_ask_is_none_when_node_red_fails(code)`, for `unreachable`, `refused`, and `unexpected`, with nothing in `caplog`.
  - `test_cameras_reference.py`: `reference()` gains a default `objects`; `test_the_data_file` expects `format_version == 2` and the block; `test_the_data_file_keeps_version_1s_keys_in_order`: the keys are version 1's thirteen, in their order, then `objects`.
  - `test_api_cameras_reference.py`, with `tracked` patched on the app's Node-RED:
    - `test_a_take_with_nobody_tracked`: `people == "none"`; the data file's block has `checked` true, both lists, and `person` false.
    - `test_a_person_in_either_list_is_seen(before, after)`: a person first only, and second only.
    - `test_no_list_is_unchecked_and_the_second_question_is_not_asked`: `tracked` returns `None`; `people == "unchecked"`; it was called once; the block is `{"checked": false, "before": null, "after": null, "person": null}`.
    - `test_node_red_failing_is_unchecked_and_the_take_still_works(code)`: for `unreachable`, `refused`, and `unexpected`: 200, both pictures held, `unchecked`.
    - `test_the_second_question_failing`: a clean first list and a second that raises give `unchecked`; a first list with a person and a second that raises give `seen`.
    - `test_the_questions_come_before_the_first_frame_and_after_the_second`: with the frames and `tracked` recording their order: ask, clean, zones, ask.
    - `test_node_red_is_asked_by_the_key`: on an entry whose `frigate_camera` differs from its key, `tracked` is called with the key.
    - `test_a_refused_take_asks_nothing`: a camera that isn't sending gets `no_picture`, and `tracked` was never called.
    - `test_no_object_reaches_a_log_line_or_an_audit_row`: with `caplog` and a list holding a label `zebra`: `zebra` is in no record and no audit row, and the audit rows are the ones the take wrote before.
  - `test_fake_nodered.py`: `test_the_fake_answers_the_people_check`: the starting list; a list set by the test; `None`.
- [ ] **Step 2: Run them.** They fail.
- [ ] **Step 3: Write** the adapter's method, `people.py`, the reference's field and the data file's block, the two questions in the take, and the fake's answer.
- [ ] **Step 4: Regenerate the API files** (the UI README's two commands), add `people: 'none'` to `referenceOut`, and run the UI's build and tests in the pinned Node image. PASS, with no component changed.
- [ ] **Step 5: Run** `python -m pytest tm-control/backend/tests script/tests`, and the backend suite once more under Python 3.13 or older. PASS.
- [ ] **Step 6: Commit** ("Say in a reference picture's answer and data file what Frigate was tracking").

### Task 4: The dialog's line

**Files:**
- Modify: `tm-control/ui/src/modules/cameras/ReferencePicture.vue`, `tm-control/ui/src/modules/cameras/reference.ts`, `tm-control/ui/tests/reference-picture.spec.ts`, `tm-control/ui/tests/camera-reference.spec.ts`, `tm-control/ui/README.md`
- Modify: `docs/assets/images/cameras-reference.png`

**Interfaces:**
- Consumes: Task 3's `ReferenceOut.people`.
- Produces, `reference.ts`: `peopleLine(people: ReferenceOut['people']): { type: 'warning' | 'info'; text: string }`, with item 11's three lines; `warning` for `seen`, `info` for the other two.
- Produces, `ReferencePicture.vue`: `NOTE` is item 11's note. Inside the `v-if="reference"` block, above the pictures' row, a `v-alert` marked `data-people`, `variant="tonal"`, with the line's type and text. The header comment says the device asks Frigate and what the line is.

- [ ] **Step 1: Show the maintainer item 11's four texts and the design note, and stop.** The note, for the UI README's reference picture paragraph: the line sits between the note and the pictures, because it is about these pictures and is read before them; `seen` is a warning and the other two are information, because neither of them is a finding; the line never disables a button, because the admin answers for the pictures; in fake mode, how each line is reached. Take his edits into item 11 before any test is written.
- [ ] **Step 2: Write the failing tests.**
  - `camera-reference.spec.ts`: `peopleLine` gives each line and its type.
  - `reference-picture.spec.ts`:
    - `opens from the row with the intro and the note, and no picture yet` also expects no `[data-people]`, and `NOTE` is the new text.
    - `warns above the pictures when Frigate was tracking a person`: the `seen` text, in an alert of type warning, before the first picture in the dialog.
    - `says when Frigate wasn't tracking a person`
    - `says when the device couldn't check`
    - `keeps Save the zip for every result`: for each of the three, Save the zip is there and enabled.
    - `shows the newest take's result after Take again`: `seen`, then a take that answers `none`: one line, the `none` one.
    - `drops the result line with the pictures`: after Save answers 404 the dialog is at its first step with no `[data-people]`.
- [ ] **Step 3: Run them.** They fail.
- [ ] **Step 4: Write `peopleLine`, the alert, and the new note.**
- [ ] **Step 5: Run** the UI's build and tests in the pinned Node image. PASS.
- [ ] **Step 6: Screenshots in fake mode** at 375 px and 1280 px: the first step with the new note, and the second step with each of the three lines. Retake `docs/assets/images/cameras-reference.png` at the width the old one has, with the `none` line. Fake mode's pictures are drawings, so these can be looked at.
- [ ] **Step 7: Commit** ("Show in the reference picture dialog whether Frigate was tracking a person").

### Task 5: Docs, the route's device tests, and the plan's public copy

**Files:**
- Modify: `docs/use/cameras.md`, `docs/data-and-payloads/integrations.md`, `docs/development/tm-control.md`, `CLAUDE.md`, `script/devpi/README.md`
- Modify: `script/devpi/tests/test_web.py`
- Create: `design/plans/2026-11-26-data-pack-people-check.md`

- [ ] **Step 1: The device tests,** in `test_web.py`.
  - `/nr/tm-internal/cameras/x/objects` joins the paths of `test_tm_internal_is_hidden_behind_the_proxy`.
  - `test_tm_internal_objects_needs_the_token_on_the_pi(host, expect, node_red_config)`: for the first `sensors.cameras` key, no token and a wrong one each answer 401.
  - `test_tm_internal_objects_answers_for_each_camera(host, expect, node_red_config, frigate_config)`, on `pii_free` units only:
    - an unknown key answers 404;
    - each `sensors.cameras` key whose camera is in Frigate answers 200 with `answered` true;
    - where Frigate's config has detection off for the camera, `objects` is `null`;
    - where it is on, `objects` is a list whose elements have the keys `label` and `stationary` and no other;
    - the test keeps the status, the booleans, and the list's length, and a failure names those only.
  - `test_a_reference_picture_is_a_zip_of_four_files` also checks: the take's `people` is one of the three values; the data file's `format_version` is 2; its `objects` has exactly the four keys; and on a camera with detection off, `people` is `unchecked` and `before` and `after` are `null`.
- [ ] **Step 2: `docs/use/cameras.md`,** "Take a reference picture".
  - The steps: step 2 says the dialog then shows, above the pictures, whether Frigate was tracking a person; step 3 says to look at both pictures whatever the line says, and that a warning means wait and choose **Take again**.
  - "What the picture gives away": the quoted note is item 11's.
  - A new section after it, "The people check": what the device asks and when (before the first picture and after the second); the three lines and what each means; the limits of item 12, as a list; that a unit as installed has detection off and so always shows the third line, with a link to where detection is switched on; that the check never stops a save.
  - "The data file": `format_version` is `2`, with a sentence on what changed since `1` (the `objects` field; nothing else). A new row, `objects`, and under the Zone field table an Objects field table: `checked`, `before`, `after`, `person`, and for each listed object `label` (Frigate's label for it; a recognized person is `person`) and `stationary`. One sentence says the list holds no picture, position, or name.
- [ ] **Step 3: The other pages.**
  - `integrations.md`, the MQTT topics table: `frigate/onConnect` (the Traffic Monitor to Frigate; sent when a reference picture is taken, to ask what Frigate is tracking) and `frigate/camera_activity` (Frigate to the Traffic Monitor; Frigate's answer, each camera's tracked objects. The Traffic Monitor keeps each object's label and whether it is standing still, for the picture's data file, and nothing else. Like `frigate/events`, the message itself can hold a recognized name when Frigate's face recognition is on, and a client that holds the broker's login can read it).
  - `tm-control.md`: the reference picture's paragraph (the two questions, `people.py`, the three results, version 2, that no list is logged or audited); the Cameras module's Node-RED route, with its answer and the rule for "no list"; `NodeRed.tracked` and its timeout; fake mode's answer.
  - `CLAUDE.md`: the Cameras clause of the `tm-control/` bullet (the take asks Node-RED what Frigate is tracking, before and after); "Node-RED's internal status" (the route, its three answers, the 404, and the rule that only `label` and `stationary` leave); the `frigate_cameras` contract (the route reads it, and a waiting question holds the key); and one sentence in "Node-RED flows" that `init-config` publishes `frigate/onConnect` and reads `frigate/camera_activity`, a contract with Frigate's `handle_on_connect` that `script/devpi/tests/test_cameras.py` checks on a device.
  - `script/devpi/README.md`: the rows for `test_cameras.py` and `test_web.py`.
- [ ] **Step 4: The plan's public copy:** the public copy is this file, with Task 2's node ids filled in.
- [ ] **Step 5: Run** every off-device check and `mkdocs build --strict`. PASS.
- [ ] **Step 6: Commit** the device tests, then the docs, then the plan's copy.

### Task 6: Pi plan and the PR

- [ ] **Step 1: Pi plan,** as a logged `tmdev check` on a bench unit marked `pii_free` that has a camera, after `tmdev deploy <host> -- -t node-red-tm -t tm-control -t revproxy`. Items 1 to 6 run with Frigate's detection off; say so in the check.
  1. The device suite passes, with `test_frigate_answers_on_connect` and the three new tests in `test_web.py` among them.
  2. Node-RED's journal has a "Flows file" line that names the installed `flows.json`, and no error from the new nodes since the deploy.
  3. On the Pi, with the token: the route answers `{"answered": true, "objects": null}` for the camera's key, 404 for a made-up key, and 401 without the token. Record the time each answer took; each is well under a second.
  4. A reference picture taken on the Cameras page: the dialog shows the "couldn't check" line (the maintainer reads it, or a session reads the take's `people` field); the zip's data file has `format_version` 2 and `objects` equal to `{"checked": false, "before": null, "after": null, "person": null}`. The pictures are not opened.
  5. In Node-RED's and the control app's journals since the deploy, and in **Download diagnostics**: no line holds `camera_activity`, `stationary`, or an object's label from a check. Count the matches; expect 0.
  6. `sudo systemctl stop node-red-tm.service`, take a reference picture: it still gives its pictures, with the "couldn't check" line, after about 3 seconds. Start the service again. (Stopping Frigate alone also stops the pod, so "Frigate didn't answer" is covered by the off-device tests only.)
  7. **The maintainer's, and it needs his consent first, each time, for a bench test only.** It turns Frigate's detection on once, on one camera, and off again. Before asking, say that count.
     1. With his consent, switch detection on for the camera on the Cameras page. Snapshots and recording stay off.
     2. He stands in the camera's view, still, for 20 seconds. Meanwhile a session asks the route on the Pi, with the token, and then takes a reference picture through the API (`POST /api/v1/cameras/<key>/reference`). Expected: the route's list holds `{"label": "person", …}`, and the take's `people` is `seen`. The session reads those two JSON answers only. It fetches neither picture and no zip, and deletes the ticket at once (`DELETE`), so no picture of him is held.
     3. He leaves the view and waits 30 seconds. The same two requests. Expected: no `person` in the route's list, and `people` is `none`. The ticket is deleted again.
     4. If he wants to see the warning line himself, he takes a picture in the dialog while in view and closes it without saving. What the pictures show is for his eyes only.
     5. Switch detection off. Confirm `detect.enabled` is false for the camera in Frigate's `/api/config`, read with `X-Cache-Bypass: 1`. Record the consent, the one turn-on, and the confirmation in the `tmdev check`.
  8. **Manual, the maintainer's:** the dialog on a phone, on the unit's hotspot: the note and each line he has seen read well at that width.
- [ ] **Step 2: Every off-device check once more** on the final branch; `git grep` the branch and its messages for anything that must stay out of public text: device names, addresses, the names and numbers of any internal notes, and any coordinate that isn't allowed.
- [ ] **Step 3: The PR's text,** the template filled in, "Closes" this PR's issue and "Part of #371".
  - Title: `data-pack PR 2: Say whether Frigate was tracking a person when a reference picture is taken`.
  - First body line: `Series: data-pack PR 2 of 4 · stacked on dev · next: PR 3, stored reference pictures · map: #371`.
  - The release note: "When you take a reference picture, the device now asks Frigate what it is tracking on that camera, before the first picture and after the second, and says above the pictures whether a person was among them. A person standing still counts. The picture's data file lists what Frigate was tracking and is now `format_version` 2. The check needs Frigate's detection to be on for the camera, and Frigate can miss a person, so the dialog still asks you to look at both pictures. It never stops you saving them."
  - Also: the Docs list; the screenshots; the Pi plan's results, with item 7 marked as done with the maintainer's consent and detection confirmed off; the limits (item 12; "Frigate didn't answer" was tested off the device only; each question also makes Frigate send its state to any open Frigate page, which is harmless); and the AI-assistance section.
  - The maintainer reads the commit messages and the PR text before any push.

## Later

- **PR 3 uses this check for the pictures the device takes on its own:** `people.ask` and `people.facts` are written to be called from there, and its marks `clear`, `person`, and `unchecked` are this plan's three results.
- **A Status check that Frigate answers `onConnect`.** Today a Frigate upgrade that changed the message would show only in the device test and as a permanent "couldn't check" line.
- **Saying why the check couldn't run.** Node-RED's `answered` already tells detection off from a silent Frigate; the control app doesn't pass it on yet, because the draft has one line for both.
- **Frigate's running counts** (`frigate/<camera>/<label>`), the design's fallback, are not read.
