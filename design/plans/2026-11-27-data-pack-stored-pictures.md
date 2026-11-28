# Stored reference pictures

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Series:** `data-pack`. This plan is PR 3, built as two PRs, **3a** and **3b** (Decision 1), which makes five planned. PR 1 = Download your data (#375, merged), PR 2 = the people check (#386, merged), PR 3a = reference pictures an administrator keeps on the device, PR 3b = reference pictures the device takes on its own, PR 4 = stored pictures in the database download.

**Goal:** A reference picture can stay on the device. An administrator can keep a take, see what is stored for each place, download it after looking at it, and delete it (3a). At a place an administrator opted in, the device takes the picture itself: after a deploy and after a camera's mounting or setup changes, when nobody is in view, and again in daylight (3b).

**Why two PRs:** 3a is everything an administrator does by hand. It has no thread, no clock rule, and no change to `flows.json`, and it is the smallest form of the rule change ("a picture may be written to the card"). 3b is the automation: the opt-in, the waiting takes, restarts, daylight, the ceiling, and the one flows edit. PR 4 needs only 3a (the store and the review step), so it can be built beside 3b.

**Architecture:**
- **One take, two users.** The manual take's reading of Frigate (its checks, the two frames, the people check, the facts) moves into one function, `shoot`. The manual dialog holds the result in memory under a ticket, as now. The store writes it to the card.
- **The store.** Frames are files in the control app's state directory, `pictures/<id>/clean.jpg` and `zones.jpg`. Facts are a row in `state.sqlite`. Files are written before their row and deleted before it, and a sweep at start removes whatever a crash or a restore left on one side only.
- **Leaving the device.** A download is one picture: its two views, its data file, and its drawing, the zip a manual take gives. It goes through a review step that shows both views and needs a tick before it works.
- **The automatic take (3b).** A loop in the control app beside the setup-history poster. A waiting take is a row that carries the kernel's boot id and times on the boot clock, so a restart of the control app keeps it and a reboot drops it. What starts one: the control app's own writes (deploy, the switch, a mounting save), and Node-RED's answer to the setup-history post, which gains the keys of the cameras whose `setup_camera` row it opened.

**Tech Stack:** Python (FastAPI, pydantic 2, `sqlite3`, `zipfile`, `zoneinfo`; no new dependency); Vue 3 + Vuetify 3 + TypeScript (Vitest, jsdom; no new package); one Node-RED function node edited in `flows.json` (3b); pytest with the function-node harness in `script/tests/test_node_red_flows.py`; the device tests in `script/devpi/tests`; Material for MkDocs.

**Spec:** "What it must do" below. The design it comes from is the maintainer's and isn't published.

**Repo:** `glossyio/traffic-monitor`, off `dev`. 3a on `feature/data-pack-kept-pictures/387`, 3b on `feature/data-pack-automatic-pictures/<issue b>`, each issue a sub-issue of #371. All paths below are relative to the repo root.

**Status:** written 2026-11-27 against `dev` as it will be once #386 merges: the tree of #386's head `5bb9e9d6`, which already holds `dev` at `9b974336` (#382).
- **Now:** #386 has merged, and the build of 3a started on `dev` at `1f29b34f`.
- **The build starts only after #386 merges.** `people.ask`, `people.facts`, `Reference.objects`, and `NodeRed.tracked` are #386's.
- **`state.sqlite` has 8 migrations** there (the eighth is the place's time zone). 3a adds the ninth and 3b the tenth. No open branch adds one. Count them again when the build starts and take the next free number.
- **The place's time zone is in `dev`** (#377, #382), so the daylight window uses it.
- **radar-aim PR 1 (#385, open) and PR 2 (being built on it):** `flows.json` (the radar nodes, "init config defaults", "tm-internal: build status", the deployment engine and its queries), tmdb migrations 0013 and 0014, `modules/location/mounting.py` and `router.py`, `adapters/nodered.py`, `fake.py`, `docs/development/tm-control.md`, `CLAUDE.md`. Neither touches the setup engine (`02692ea73db6605b`) or its group, `modules/cameras/`, or `core/state.py`.
- **tmupdate PR 3 (being built, not open):** `app.py`, `modules/__init__.py`, `fake.py`, `core/settings.py`, `modules/system/diagnostics.py`, a new `modules/update/`, the UI's module list, `docs/development/software-update.md`, `CLAUDE.md`. It owns the update's restore point, which copies `state.sqlite` alone. Pictures stay out of it.
- **`flows.json` merges one PR at a time.** Only 3b edits it, and only one function's code. Whichever PR merges after another redoes its own edit on the new file with a script. Nobody resolves the JSON's text conflict by hand.
- **Text files that will need a rebase** after one of those merges: `CLAUDE.md`, `docs/development/tm-control.md`, `app.py`, `modules/__init__.py`, `fake.py`, `modules/location/router.py`, `adapters/nodered.py`, the UI's README. The API files are regenerated, never merged.

**Bench needs:** a unit marked `pii_free` with a camera that is sending.
- 3a: about 2 hours, most of it Task A1's samples in two kinds of light. Nothing disruptive.
- 3b: about 3 hours across two reboots. It edits one zone in Frigate and the place's time zone and puts both back. One optional item, the maintainer's, turns Frigate's detection on once, with his consent.

**Size** (estimates):
- 3a: about 45 files, +2,200 to 2,700 lines, a little over half of it tests and docs.
- 3b: about 35 files, +1,800 to 2,300 lines.
- To maintain afterwards: one more module (`modules/pictures`), two tables, a directory of files that no backup holds, a thread, and a second field in the setup engine's answer.

**Decisions.** The maintainer's are marked. The rest are calls made while writing this, open to change.

1. **Two PRs, 3a and 3b (maintainer, 2026-11-27),** split between what an administrator does by hand and what the device does on its own.
2. **Opt-in per place, unticked, covering the whole stay (maintainer, the design).**
3. **A take is due 10 minutes after the last change; a person in view means try again; a picture kept outside 10:00 to 14:00 gets one daylight round (maintainer, the design).**
4. **A picture stays until an administrator deletes it or its place (maintainer, the design).** The device deletes none on its own.
5. **Both frames are stored, and both are shown before any download, which needs a tick that they were looked at (maintainer, the design).**
6. **A waiting take belongs to one power-on; the device never replaces a picture after a shutdown (maintainer approved, the design).**
7. **Nothing is uploaded, and no picture, point, or ticket reaches a log line, an audit row, an error, the diagnostics, tmdb, or an upload (maintainer, the design).**
8. **The words on every screen are drafts for the maintainer to edit** before the screen is built (Task A5 Step 1, Task B5 Step 1).
9. **The ceiling's two numbers are set from Task A1's measurement,** at a stop for the maintainer, sized from twice the largest pair measured, because a bench scene has less detail than a street (maintainer, 2026-11-27). The maintainer set them to 200 pictures and 500 MB free on 2026-11-27, after Task A1's measurement: the largest pair measured was 715 KB, about 1.43 MB at twice that.
10. **A picture's id is 16 random hex characters,** not a counter. A restore brings back an older `state.sqlite`; a counter would then hand a new picture the id of files already on the card.
11. **Waits run on the boot clock; the daylight window is read from the wall clock each time.** A unit with no clock battery starts with a stale clock and jumps when it syncs. A wait counted on `CLOCK_BOOTTIME` doesn't move with it, and that clock means the same thing to a control app that restarted, which is what lets a waiting take outlive it.
12. **The daylight window is 10:00 to 14:00 in the place's time zone,** or the device clock's zone for a place with none. With neither readable there is no daylight round.
13. **No frame is held between tries.** "The last pair is kept" is the pair of the last try: once a person has been in view for an hour, the next pair is kept whatever it shows.
14. **The first automatic picture of a camera in a power-on in which no administrator deployed, opted in, or saved the mounting at that place carries a quiet note, "the unit restarted before this picture" (maintainer, 2026-11-27).** Only the first, per camera. It is plain information on that one picture: not a warning, and not sorted with the marked pictures. A restart by itself shows nothing on any page.
15. **A new change to a camera ends that camera's daylight round.** The round would otherwise replace a picture of the old setup with one of the new.
16. **A mounting save starts a take for each camera whose five values changed, unless the answer to "Did the unit move or turn?" was "measured better" (maintainer, 2026-11-27).** That answer says the view is the same, and one good picture of a deployment is enough. A heading correction on a deployment starts none (the design).
17. **Turning a camera's entry on at an opted-in place starts a take (maintainer, 2026-11-27).** Node-RED starts a deployment row for it, and the design wants a picture for each camera deployment row. This goes past the design's table.
18. **At the ceiling, or with a camera that isn't sending, a take tries every 5 minutes for a day and then gives up (maintainer, 2026-11-27).** One rule for both.
19. **A download is one picture, never several (maintainer, 2026-11-27).** The operator looks at both views of that picture first. A place keeps its history, so it can hold several pictures of a camera; the newest is the one that shows the zones as they are. PR 4 carries many at once, through the database archive.
20. **The data file stays at `format_version` 2.** It doesn't say why a stored picture was taken (see Later).
21. **Keeping a manual take needs free space, not the count.** It is an administrator's explicit act; the count limits only what the device takes on its own.
22. **The names are this plan's:** the routes, `modules/pictures`, the tables `pictures` and `picture_takes`, `Shot`, `shoot`, `Pictures`, `Taker`, and the answer's `cameras`.
23. **Plate Recognizer is shelved and is the exception here:** no change, pin, or bench item for it.

## What it must do

### 3a: pictures an administrator keeps

1. **The rule.** A picture is stored only when an administrator chose it. It is stored only on the device, under the control app's state directory. Only an administrator can see, download, or delete it. A picture leaves the device only in a download an administrator confirmed after looking at it. A manual take that isn't kept is held in memory only, as now.
2. **Where.** `<state directory>/pictures/<id>/clean.jpg` and `zones.jpg`. The directory `pictures` and each `<id>` are mode 0700 and each file 0600, the service user's. `<id>` is 16 lowercase hex characters from `secrets.token_hex(8)`. The bytes stored are the bytes Frigate sent.
3. **The row,** in a table `pictures`: the id, the place, the camera's `sensors.cameras` key, why (`deployed`, `opted_in`, `mounting`, `setup`, `daylight`, `manual`), the mark (`clear`, `person`, `unchecked`), whether it is the first after a restart, the boot id, each frame's time and size in bytes, the administrator who kept it (manual only), and `facts`: a JSON object with what the data file needs (`width`, `height`, `unit`, `zones`, `objects`, `tm_version`, `frigate_version`, `pose`, `deployment_id`). The place's point is not stored with the picture.
4. **The mark** comes from the take's `objects` block: `person` true is `person`, false is `clear`, `null` is `unchecked`.
5. **Order.** A picture's files are written and synced before its row is inserted. They are removed before its row is deleted. A write that fails leaves no row and no directory.
6. **The sweep,** once when the control app starts, before it serves: every directory under `pictures` with no row is removed, and every row whose directory or either file is missing is deleted. It logs two counts and nothing else.
7. **Keep on this device.** `POST /api/v1/cameras/{name}/reference/{ticket}/keep` stores the held take for the place in use, with reason `manual`, and answers 201 with the picture. It needs no opt-in and changes none. Refused with:
   - 404 `reference_expired`, as the other ticket routes;
   - 409 `no_place` when the take had no place, or its place is no longer the one in use;
   - 409 `already_kept` for a ticket kept before;
   - 409 `no_space` when less than `FREE_MIN` is free where the state directory is.
   The ticket stays good for Save the zip.
8. **The list.** `GET /api/v1/pictures`, with `?survey_id=` for one place, answers `pictures` (newest first; each with `id`, `survey_id`, `camera`, `taken_at`, `reason`, `mark`, `after_restart`, `bytes`), and for the whole device `stored` and `stored_bytes`.
9. **The frames.** `GET /api/v1/pictures/{id}/clean.jpg` and `zones.jpg`: `image/jpeg`, `Cache-Control: no-store`. 404 for an id that isn't 16 hex characters, has no row, or has lost a file. No path is built from an id that didn't match.
10. **Delete.** `DELETE /api/v1/pictures/{id}`: 204, whether or not it existed. Deleting a place (`DELETE /surveys/{id}`) removes its pictures' files first, then the place; the rows go with it.
11. **Download.** `POST /api/v1/pictures/{id}/package` with `{"location": bool, "looked": true}` answers a zip of that one picture.
    - 422 for `looked` anything but `true`. 404 `not_found` for an id with no picture.
    - The four files a manual take's zip holds, under the same names, in a zip named `<stem>.zip`, built in memory as the manual zip is.
    - The data file holds the place's point as it is now, only when `location` is true and the place has one.
    - The JPEG entries are the stored bytes.
    - No route gives more than one picture.
12. **Take a reference picture from the Location page.** The place in use offers the dialog for each enabled camera. The Cameras page keeps its button.
13. **The dialog.** After a take at a place, **Keep on this device** sits beside **Save the zip**. Once kept, a line says so and the button is off. A take with no place has no such button.
14. **A place's pictures.** Each place's panel lists its pictures, newest first: both frames, the time, the camera, why, and the mark, with **Download** and **Delete** on each. Delete asks first.
15. **The review step,** before a download:
    - both frames of the picture, each at the full width of the dialog's column;
    - above them the mark's line for a `person` or `unchecked` picture, and under them the note for a picture taken after a restart, as plain text;
    - the box "Include this place's exact location", as the manual dialog has it;
    - a tick, "I have looked at both views", without which **Download** is off. It starts unticked for every picture.
16. **Counts.** The Location page says how many pictures the device stores, and the Sharing page's download card says the same with a line that they aren't part of that download.
17. **A camera re-keyed to a neutral name** takes its pictures with it, at every place.
18. **Audit rows:** `picture.keep` (`<survey id> <camera>`), `picture.delete` (`<survey id> <camera> <reason>`), `picture.download` and `picture.download_with_location` (`<survey id> <camera>`). No id, no time, no object.
19. **Fake mode.** Keep, the list, the review step, download, and delete all work on a laptop, on fake mode's drawings.
20. **What doesn't change in 3a:** the take's refusals and their words; the ticket and its ten minutes; the manual zip; the data file (`format_version` 2); the places CSV; the plain database download and the copy with exact locations; `flows.json`; Frigate's settings.

### 3b: pictures the device takes

21. **The opt-in** is a flag on the place, `keep_pictures`, off for every place until an administrator turns it on.
    - The Deploy here review has the box "Keep reference pictures at this place", showing the place's flag as it was left. `POST /surveys/{id}/deploy` takes `keep_pictures` (true, false, or absent for "as it is").
    - `PUT /api/v1/surveys/{id}/pictures` with `{"keep": bool, "delete_stored": bool}` switches the place in use (409 `not_in_use` for another). Turning it off drops the place's waiting takes and keeps its pictures, unless `delete_stored` is true.
    - Audit rows `survey.pictures_on` and `survey.pictures_off` (`<survey id>`, and ` deleted <n>` when pictures went).
22. **What starts a take,** for the place in use while its flag is on, for a camera whose entry is enabled:

    | What happened | Reason | Which cameras |
    | --- | --- | --- |
    | Deploy here | `deployed` | each camera whose deployment the deploy starts: all of them when the place changes, else those whose heading changed |
    | The switch turned on | `opted_in` | all |
    | A mounting save | `mounting` | each camera the save wrote whose heading, tilt, height, distance, or mount changed, unless the save's answer was "measured better" |
    | Node-RED opened a `setup_camera` row | `setup` | the keys in its answer |
    | A camera's entry turned on (Cameras page) | `deployed` | that camera |

    A heading correction, a radar's change, a new `setup_device` row, and a location or time zone correction start nothing.
23. **One waiting take per place and camera.** A new start while one waits moves it to 10 minutes from now and keeps its first reason. A new start ends that camera's daylight round and clears a give-up.
24. **A try,** when a take is due:
    1. The take is dropped when its boot id isn't this boot's, its place isn't in use or its flag is off, or the camera's entry is gone or off.
    2. At the ceiling (item 29) there is no picture: go to step 5.
    3. `shoot` (the manual take's checks, the people check, the two frames, the people check). Refused for any reason: go to step 5.
    4. With a pair:
       - `clear` or `unchecked`: it is stored.
       - `person`: the pair is discarded and the take tries again in 5 minutes. Once an hour has passed since the first such try, the pair is stored instead, marked `person`.
    5. With no pair: try again in 5 minutes. Once a day has passed since the first of an unbroken run of such tries, the take gives up: it stays, tries no more, and the Status page says so.
25. **Stored inside the same transaction that checks it.** The row is inserted only if the take still waits and the place is still in use with its flag on. Otherwise the files just written are removed. A take in flight when the switch goes off stores nothing.
26. **Daylight.** When a stored automatic picture's time is outside 10:00 to 14:00 (Decision 12 for the zone), its take becomes a daylight round for that picture:
    - It waits for the window, looking every 5 minutes.
    - In the window it tries every 5 minutes. A `clear` pair replaces the picture and ends the round. So does an `unchecked` pair when the picture is itself marked.
    - Any other pair is discarded. On the last try of the window (the next would be at or after 14:00) a `person` pair replaces the picture only if the picture is itself marked.
    - The round ends when that window closes, whatever happened. A camera that sent nothing in the window gets no second one.
    - A replacement is a new picture with reason `daylight`, which carries the old one's "after a restart" and takes its place in one transaction; the old files go after. A `daylight` picture gets no round.
    - A picture deleted by an administrator takes its round with it.
27. **Restarts.**
    - At start the control app drops every waiting take whose boot id isn't this boot's. A restart of the control app alone keeps them all.
    - A replacement happens only in the round started for that picture, so only in the same power-on.
    - Each place records the boot id of its last deploy, opt-in, or mounting save by an administrator. An automatic picture is marked `after_restart` when this boot's id differs from that one and the camera has no stored automatic picture at the place from this boot. It replaces nothing.
28. **Times.** The 10 minutes, the 5 minutes, the hour, and the day are counted on the boot clock. The window is read from the wall clock at each look.
29. **The ceiling.** With `PICTURES_MAX` pictures stored, or less than `FREE_MIN` free where the state directory is, no automatic picture is stored and the Status page says so. Nothing is deleted. A daylight replacement is refused the same way.
30. **The engine's answer.** `POST /tm-internal/setup` answers `{"changed": n, "cameras": [...]}`: `cameras` holds the key of each camera whose `setup_camera` row this run opened, sorted. A device row, a row that only closed, and an incomplete snapshot add none. An answer without `cameras` (older flows, mid-update) starts nothing and is no error.
31. **Waiting takes in the list.** `GET /api/v1/pictures` gains `limit` and `waiting`: for each take its `survey_id`, `camera`, `reason`, `state` (`waiting`, `person`, `no_picture`, `daylight`, `gave_up`), and `due_in` (seconds to the next look; `null` once it gave up). The place in use shows a line for each.
32. **The Status page.** One check, in the Apps group:
    - `ok` when no place keeps pictures, or pictures are kept and nothing is wrong;
    - `warn` at the ceiling, naming which limit;
    - `warn` for a take that gave up, naming the camera's key.
    It links to the Location page.
33. **Audit rows** with no user: `picture.taken` (`<survey id> <camera> <reason> <mark>`) and `picture.replaced` (the same, for a daylight replacement).
34. **Logs.** The loop logs a failure by its exception's class, once when it starts or changes and once when it ends, as the poster does. No camera, place, id, mark, or object is logged.
35. **Fake mode.** The thread doesn't run. The tests drive `Taker.step()` with their own clock, and `FakeNodeRed` answers the people check and the setup post. Started with `TM_CONTROL_FAKE_PICTURES=1`, fake mode runs the thread with every wait divided by 60, for screenshots.

## Where the code stands that this plan touches

Read in #386's head, `5bb9e9d6`.

- **The take** (`tm-control/backend/tm_control/modules/cameras/router.py`): `take_reference` does everything in one function: it reads `config.yml` and Frigate's config, refuses with `_unavailable`, `_changed`, `_camera_off`, or `_no_picture`, checks `_sending` and `_live`, asks `people.ask` before the first frame and after the second, reads the mounting, the place in use, and `_open_deployment`, and calls `app_state.references.keep(time.monotonic(), user_id=…, …)`. In fake mode it reads `fake.frigate_answer`, `fake.frigate_stats`, and `fake.frigate_frame`.
- **The held take** (`modules/cameras/reference.py`): the frozen dataclass `Reference` (ticket, user, the facts, the two frames, `expires`); `References` (`keep`, `get`, `drop`; `TTL = 600`, `LIMIT = 2`); `stem`, `data_file`, `caption`, and `package`, which read a `Reference`'s facts and frames and nothing of its ticket; `FORMAT_VERSION = 2`; `HideTickets`. `people.py` has `ask`, `facts`, `result`.
- **The poster** (`modules/setup_history/poster.py`): `Poster(gather, post, interval=300, retry=30)`, `run_once`, `wake`, `wake_soon`, `start`, `stop`, and `_note`, which logs a failure's class once. `app.py` builds it in both modes as `app.state.setup_poster`, with `post = lambda body: app.state.nodered.post_setup(body)`; `cli.serve` starts it on a device only.
- **`adapters/nodered.py`:** `NodeRed.post_setup(body) -> None` calls `_call("POST", "/setup", body=body)` and drops the answer. `fake.py`'s `FakeNodeRed.post_setup` keeps the body.
- **The state database** (`core/state.py`): `MIGRATIONS`, eight entries; `State.connect` gives a new connection with foreign keys on. `core/auth.py` has `_reading`, `_writing` (one `BEGIN IMMEDIATE` transaction), `_timestamp`, and `Audit.record(user_id, action, detail)`.
- **The state directory:** `Settings.state_dir`, made 0700 in `create_app`; on a device it is systemd's `StateDirectory=tm-control` (`/var/lib/tm-control`). `modules/detection/upload.py` has `free_space_ok(path, needed)` over `os.statvfs`.
- **Places** (`modules/location/places.py`): `Survey`, `_SURVEY_COLUMNS`, `Places` (`get`, `in_use`, `list`, `set_in_use`, `delete`, `rename_sensor`, `set_timezone`). The class has a method named `list`, so a `list[...]` annotation in a later signature needs the module-level aliases it defines.
- **The Location router** (`modules/location/router.py`):
  - `deploy_place`: under `reconcile_lock` it works out `chosen` (each enabled sensor's heading), `switching`, `moving`, and `waiting` (the sensors whose rows it waits for), writes `config.yml`, then the store.
  - `save_mounting`: `old`, `new`, `written` (the sensors the save writes), `before`, `starting`, `_five`, `_differs`.
  - `correct_heading`, `correct_location`, `set_place_timezone`, `delete_place`.
  - `_in_use`, `_place`, `_reconciled`, `_clock_zone` (the device clock's zone, fake mode's own).
  - `SurveyOut`, `DeployIn`, `PlacesState`.
- **The Cameras router's writes:** `set_camera` (the entry's `enabled`), `add_camera`, `neutral_name` (which calls `Places.rename_sensor`), `remove_camera`.
- **The Sharing card:** `modules/sharing/download.py` has `DownloadFacts` (`database_bytes`, `exact_places`) and `facts(app_state, report)`.
- **Status checks:** `core/checks.py` (`Check`, `Fix`, `Context` with `settings`, `state`, `setup`); `modules/apps/checks.py` ends with `GROUP = CheckGroup("apps", "Apps", [..., setup_history])`.
- **The service** (`script/ansible/roles/tmsetup/templates/tm-control/tm-control.service.j2`): `StateDirectoryMode=0700`, `ProtectSystem=strict`. `/proc/sys/kernel/random/boot_id` is readable under it.
- **The setup engine** (`container/node-red-tm/data/flows.json`, function `02692ea73db6605b` on `init-config`, in the group `fc8558ca801e2e70`): it builds `insertCamera`, a list of inserts whose `params.$camera` is the camera's key, and ends

  ```javascript
  msg.statusCode = 200;
  msg.payload = { changed: insertDevice.length + insertCamera.length };
  return [closeDevice, insertDevice, closeCamera, insertCamera, msg, upload];
  ```

  Its fifth output goes to the `http response` `1e23d3f89be4f296`. Its header comment lists the six outputs.
- **Flows tests** (`script/tests/test_node_red_flows.py`): `setup_engine(setup, devices, cameras, context, flow)` returns a `SetupRun` (`answer`, `written()`, `insert_camera`); `SETUP_SNAPSHOT`, `open_device`, `open_camera`, `open_cam_b`. Seven tests compare `run.answer["payload"]` with `{"changed": n}` exactly.
- **Backend tests:** `test_api_cameras_reference.py` (`admin`, `take`, `taken`, `package`, `files`, `audit_rows`, `frames`, `deploy_new_place`), `test_cameras_reference.py` (`reference(**changes)`), `test_setup_poster.py`, `test_api_surveys.py` (`create`, `deploy`, `places`), `test_api_mounting.py` (`put`, `saved`), `test_state.py`, `test_fake_nodered.py`, `tests/jpegs.py`.
- **The UI** (`tm-control/ui/`):
  - `src/modules/cameras/ReferencePicture.vue`: the dialog, two steps; `take`, `save` (a blob through `saveBlob`), `drop`; the box `withLocation`; buttons Close, Take again, Save the zip. `reference.ts`: `pictureUrl`, `legendRows`, `peopleLine`. It is opened by `CamerasPage.vue` with `v-model:open` and `:name`.
  - `src/modules/location/LocationPage.vue`: one expansion panel per place, `<PlaceDetails>` and the place's buttons in each; `loadDetails(id)`; the dialogs. `PlaceDetails.vue`: the facts and the deployments. `DeployReview.vue`: the review (sensors, the time zone pick, the stored line, `sharingLine`, "Counts from now on attach to the new deployment.") and `deploy()`, which posts `{headings}`.
  - `src/modules/sharing/DownloadCard.vue`: a `StatusCard` with the item "Database size", from `facts`.
  - `src/components/download.ts`: `saveBlob`, `openDownload`. `src/components/ConfirmDialog.vue`.
  - Tests: `tests/reference-picture.spec.ts`, `place-details.spec.ts`, `deploy-review.spec.ts`, `location-page.spec.ts`, `download-card.spec.ts`; `tests/fake-api.ts` (`fakeApi`, `referenceOut`, `DOWNLOAD_FACTS`); `tests/mount.ts` (`mountApp`, `mountAlone`, `clickInDialog`, `dialogText`).
  - The only `<img>` elements in the app are the dialog's two. There is no gallery.
- **Device tests** (`script/devpi/tests/`): `devpi_checks.py` (`require_pii_free`, the `python3 -c` helpers run on the Pi); `test_cameras.py` (`cameras`, `frigate_config`); `test_web.py` (`test_a_reference_picture_is_a_zip_of_four_files`, which signs in as an administrator).
- **Docs:** `docs/use/cameras.md` ("Take a reference picture", which says the device "never saves them"), `docs/use/location.md`, `docs/use/sharing.md`, `docs/data-and-payloads/data-overview.md` ("Images do exist on the device"), `docs/data-and-payloads/setup-history.md`, `docs/development/tm-control.md` (the reference picture's rows and its paragraph, "live only in `app.state.references`"), `docs/development/software-update.md` ("Restoring by hand"), `docs/use/device-health.md`, `CLAUDE.md` (the control app's paragraph: "no picture is written to disk or logged").

## Global Constraints

- **The names, the shapes, and the rules are those in "What it must do".** No task picks another, and the words on a screen change only by the maintainer's edit.
- **No session looks at a picture.** Tests use `tests/jpegs.py` and fake mode's drawings. Bench checks and device tests read statuses, headers, sizes, modes, keys, and counts; a JPEG from a device is never opened, decoded, described, or copied off it. What a picture shows is for the maintainer's eyes.
- **Nothing here turns Frigate's detection, snapshots, or recording on or off.** On a dev Pi they stay off, except for Task B7's one optional item, which is the maintainer's to consent to each time, with a count, for a bench test only; detection goes back to false after, confirmed in Frigate's `/api/config` with `X-Cache-Bypass: 1`, and recorded in the `tmdev check`.
- **Nothing about a picture in a log line, an error message, or the diagnostics:** no id, place, point, camera, mark, object, or byte. An audit row holds what items 18, 21, and 33 list and nothing else.
- **Frigate's name for a camera stays where it is today.** A picture, a take, a route, and a file name carry the `sensors.cameras` key.
- **A path under `pictures` is built only from an id that matched `[0-9a-f]{16}`.**
- **The control app never opens `tmdb.sqlite`,** and Node-RED never opens the pictures.
- **`flows.json` (3b only):** only the `func` of `02692ea73db6605b` changes. Edit the file with a script and write it back with `json.dumps(flows, indent=4, ensure_ascii=False)` and no trailing newline. Don't open the Node-RED editor on it. `flows_cred.json` is not touched.
- **No coordinate in any fixture, commit, PR text, or screenshot** other than the docs' example `45.52252, -122.69120` and the fixtures' `45.0, -122.0`.
- **Python:** CI and the devices run 3.13, where annotations are read when a class is made. Run the backend suite once under Python 3.13 or older before each hand-off.
- **UI work follows `tm-control/ui/README.md`:** conventional Vuetify, the one dark theme, system fonts, 44 px buttons, results beside the form, no toasts, sentence case. Each UI task's implementer loads the `frontend-design` skill and works test-first; the README's rules win over the skill's taste. New design notes go in the README.
- The API files (`tm-control/ui/src/api/openapi.json`, `schema.d.ts`) are regenerated in the same commit as any model change.
- Plate Recognizer is shelved: no change, pin, or bench item for it.
- Every commit ends with the trailer block from the repo's `CLAUDE.md` (Assisted-by / AI-Model / AI-Effort / AI-Role); never `Co-Authored-By`. Docs follow "Writing docs" in `docs/development/contributing.md`; `mkdocs build --strict` passes. Nothing public names a device, a bench site, a partner, or a tool.
- Each PR's title starts `data-pack PR 3a: ` or `data-pack PR 3b: `, and its first body line is the `Series:` line.
- Off-device checks before each commit, from the repo root in the dev venv: `python -m pytest container/node-red-tm/schema/tests script/tests tm-control/backend/tests`; for a UI task also the pinned Node image's `npm ci && npm run build && npm test`; for a docs task `~/.venvs/tm-docs/bin/mkdocs build --strict`.

## Review Focus

1. **A take in flight when the administrator turns the switch off, deploys another place, or deletes the place.** Nothing may be stored for a place that isn't opted in at that moment. Tests in Task B3 (`test_a_take_in_flight_when_the_switch_goes_off_stores_nothing`, `test_a_take_for_a_place_no_longer_in_use_is_dropped`).
2. **The unit switched off and started somewhere else.** No take from before the shutdown runs, no picture from before it is replaced, and the first picture after it says so. Tests in Task B3 (`test_takes_from_another_boot_are_dropped_at_start`, `test_a_restart_of_the_control_app_keeps_the_takes`, `test_the_first_picture_after_a_restart_is_marked`, `test_a_daylight_round_never_crosses_a_boot`).
3. **Detection off, which is how every unit is installed.** Every pair is `unchecked`: it is stored at the first try, and a daylight pair replaces it at the first try in the window, with no hours of discarded frames. Tests in Task B3 (`test_an_unchecked_pair_is_stored_at_once`, `test_an_unchecked_daylight_pair_replaces_a_marked_picture_at_once`).
4. **Power lost mid-write, a card that fills, or a restore that brings back an older database.** No row without both files is ever served, and nothing is left that no row names. Tests in Task A3 (`test_a_write_that_fails_leaves_nothing`, `test_the_sweep_removes_files_with_no_row_and_rows_with_no_files`, `test_a_row_whose_file_is_gone_is_a_404`).
5. **An id that isn't one.** `..`, an encoded slash, 15 or 17 characters, capitals: 404 before anything touches the disk. Tests in Task A3 (`test_only_an_id_makes_a_path`) and Task A4 (`test_a_frame_under_a_made_up_id_is_a_404`).
6. **The clock jumps.** A unit with no clock battery syncs minutes after start and the wall clock moves by months. A waiting take is due when it was due. Test in Task B3 (`test_a_wall_clock_jump_moves_no_wait`).
7. **Older flows, or a lost answer.** During an update the new control app meets flows whose answer has no `cameras`; a timeout loses an answer. No take, no error, and the poster's failure count is unchanged. Tests in Task B2 (`test_post_setup_without_cameras_is_an_empty_list`, `test_a_hook_that_raises_is_not_a_failed_snapshot`).
8. **A person-marked picture in a download.** The review shows the warning above the views, the tick starts off as for every picture, and the download is still the administrator's to make. Test in Task A5 (`a person picture shows its warning and still needs the tick`).
9. **A release that changes how a camera fact is worked out** opens a `setup_camera` row for every camera, and so one take per camera on every opted-in unit. Accepted; `docs/development/tm-control.md` says so beside the snapshot's facts (Task B6).

A viewer is covered by a test per route (Task A4, Task B4): every route here is admin-only.

---

## Part A: PR 3a, pictures an administrator keeps

### Task A1: Measure two frames on a bench unit

This comes first because the ceiling's numbers rest on it. It needs no deploy and no consent: it reads Frigate as installed, with detection off, and counts bytes.

**Files:**
- Modify: `script/devpi/tests/devpi_checks.py`, `script/devpi/tests/test_cameras.py`, `script/devpi/README.md` (the row for `test_cameras.py`)
- Test: `script/tests/test_devpi_frames.py` (new, on the model of `script/tests/test_devpi_ask.py`)

**Interfaces:**
- Produces, `devpi_checks.py`:
  - `PI_FRAME_SIZES`: a script run on the Pi with `python3 -c`. It reads `http://127.0.0.1:5000/api/config` (with `X-Cache-Bypass: 1`), and for each camera, in the config's order, fetches `latest.jpg?quality=95` and `latest.jpg?quality=95&zones=1` (the adapter's two requests) into memory. It prints one JSON line and nothing else: a list with, for each camera, `{"detect": [width, height], "clean": {"status": …, "type": …, "bytes": …, "size": [w, h] or null, "offline": bool}, "zones": {…}}`. `size` is read from the JPEG's frame header. No name, no byte of a picture, and nothing written to disk.
  - `frame_sizes_on_pi(host) -> list[dict]`.
- Produces, `test_cameras.py`: `test_reference_frames_are_whole_jpegs_at_the_detect_size(host, expect, cameras, frigate_config)`: for each camera that is on and sending, both answers are 200 `image/jpeg`, not offline, and at the detect size. It prints each camera's four numbers (two byte counts, the width, the height) and keeps nothing else. A failure names numbers only.

- [ ] **Step 1: Write the helper, its off-device test, and the device test.** The off-device test runs `PI_FRAME_SIZES` against a small local HTTP server that answers a config and two JPEGs from `tests/jpegs.py`, and checks the line's shape and that it holds no camera name.
- [ ] **Step 2: Run** `python -m pytest script/tests`. PASS.
- [ ] **Step 3: Sample on the bench unit** from this branch's worktree: `tmdev.py test <host> -- -k reference_frames_are_whole -s`, 10 times a minute apart with the scene lit, and 10 times with it dark. Record the 40 byte counts in the `tmdev check`.
- [ ] **Step 4: Stop for the maintainer** with a table: the detect size; the smallest, median, and largest clean frame, zones frame, and pair, lit and dark; what 200 pairs of the largest would take; and a proposal for `PICTURES_MAX` and `FREE_MIN`. A bench scene has less detail than a street, so the largest pair is a floor: the proposal is worked out from twice the largest pair (Decision 9). He sets both, and they go into item 29 and Task A3.
- [ ] **Step 5: Commit** ("Check on a device that Frigate's frames are whole JPEGs at the detect size").

### Task A2: One take, shared

A refactor. The manual take answers exactly as before.

**Files:**
- Create: `tm-control/backend/tm_control/modules/cameras/shoot.py`
- Modify: `tm-control/backend/tm_control/modules/cameras/reference.py`, `tm-control/backend/tm_control/modules/cameras/router.py`
- Test: `tm-control/backend/tests/test_cameras_shoot.py` (new), `test_cameras_reference.py`, `test_api_cameras_reference.py`

**Interfaces:**
- Produces, `reference.py`:
  - `Shot`: a frozen dataclass with the fields of today's `Reference` other than `ticket`, `user_id`, and `expires`, in today's order: `camera`, `survey_id`, `point`, `deployment_id`, `pose`, `clean`, `zones_picture`, `clean_at`, `zones_at`, `width`, `height`, `unit`, `zones`, `objects`, `tm_version`, `frigate_version`.
  - `Reference(Shot)`: adds `ticket`, `user_id`, `expires`.
  - `stem`, `data_file`, `caption`, and `package` take a `Shot`.
  - `References.keep(self, now: float, user_id: int, shot: Shot) -> Reference`.
  - `Mark = Literal["clear", "person", "unchecked"]` and `mark_of(objects: dict) -> Mark` (item 4).
- Produces, `shoot.py`:
  - `class NoShot(Exception)` with `code`: `not_found`, `unavailable`, `changed`, `camera_off`, or `no_picture`.
  - `shoot(app_state, name: str) -> Shot`: everything `take_reference` does today between reading `config.yml` and calling `references.keep`, in the same order, raising `NoShot` where the route raises. It reads the place in use for `survey_id`, `point`, and `deployment_id`. It logs nothing and audits nothing.
- Produces, `router.py`: `take_reference` calls `shoot`, maps a `NoShot` to the same `ApiError` as today by its code, and keeps, audits, and answers as today. `_live`, `_sending`, and `_open_deployment` move to `shoot.py`.

- [ ] **Step 1: Write the failing tests.**
  - `test_cameras_shoot.py`: `test_a_shot_holds_what_the_take_held` (the fields, with the fake's frames); `test_a_refusal_is_a_code(case, code)` for the five codes; `test_the_questions_come_before_the_first_frame_and_after_the_second`; `test_shoot_logs_and_audits_nothing` (with `caplog`, and the audit table's count unchanged).
  - `test_cameras_reference.py`: `test_mark_of(person, mark)` for true, false, and `None`; `reference()` builds a `Reference` by keyword as before.
- [ ] **Step 2: Run them.** They fail.
- [ ] **Step 3: Move the code.** No route's answer, status, or words change.
- [ ] **Step 4: Run** `python -m pytest tm-control/backend/tests`. PASS, with every test in `test_api_cameras_reference.py` unchanged except where it built a `Reference` or called `keep` by the old signature.
- [ ] **Step 5: Commit** ("Share one take between the reference picture's dialog and what comes next").

### Task A3: The store (tricky)

**Files:**
- Create: `tm-control/backend/tm_control/modules/pictures/__init__.py`, `tm-control/backend/tm_control/modules/pictures/store.py`, `tm-control/backend/tm_control/modules/pictures/clock.py`
- Modify: `tm-control/backend/tm_control/core/state.py`, `tm-control/backend/tm_control/app.py`, `tm-control/backend/tm_control/cli.py`
- Test: `tm-control/backend/tests/test_pictures_store.py` (new), `test_state.py`

**Interfaces:**
- Produces, `core/state.py`, the ninth migration, with a comment that says what the table is, that the frames are files beside the database, and that the place's point is never stored here:

  ```sql
  CREATE TABLE pictures (
      id TEXT PRIMARY KEY,  -- 16 hex; also the directory's name
      survey_id TEXT NOT NULL REFERENCES surveys(id) ON DELETE CASCADE,
      camera TEXT NOT NULL,  -- the sensors.cameras key
      reason TEXT NOT NULL CHECK (reason IN ('deployed', 'opted_in', 'mounting', 'setup', 'daylight', 'manual')),
      mark TEXT NOT NULL CHECK (mark IN ('clear', 'person', 'unchecked')),
      after_restart INTEGER NOT NULL DEFAULT 0 CHECK (after_restart IN (0, 1)),
      boot_id TEXT NOT NULL,
      clean_at REAL NOT NULL,  -- Unix seconds
      zones_at REAL NOT NULL,
      clean_bytes INTEGER NOT NULL,
      zones_bytes INTEGER NOT NULL,
      facts TEXT NOT NULL,  -- JSON: what the data file needs
      kept_by INTEGER REFERENCES users(id) ON DELETE SET NULL
  );
  CREATE INDEX pictures_survey ON pictures (survey_id, clean_at);
  ```
- Produces, `clock.py`:
  - `class Clock` with `boot_id() -> str` (the text of `/proc/sys/kernel/random/boot_id`, read once), `boot() -> float` (`time.clock_gettime(time.CLOCK_BOOTTIME)`), and `wall() -> float` (`time.time()`).
  - `class ManualClock(Clock)`: built with `boot_id`, `boot`, and `wall`, which a test sets. Fake mode on a machine without `/proc` or the boot clock uses the id `"fake"` and `time.monotonic()`.
- Produces, `store.py`:
  - `PICTURES = "pictures"`, `ID = re.compile(r"[0-9a-f]{16}")`, `FREE_MIN` and `PICTURES_MAX` (Task A1's numbers), `Reason`, `FACTS` (the nine keys of item 3).
  - `Stored`: a frozen dataclass of the row: `id`, `survey_id`, `camera`, `reason`, `mark`, `after_restart: bool`, `boot_id`, `clean_at`, `zones_at`, `clean_bytes`, `zones_bytes`, `facts: dict`.
  - `class Pictures(state: State, state_dir: Path)`:
    - `add(self, shot: Shot, reason: Reason, boot_id: str, *, after_restart: bool = False, kept_by: int | None = None, guard: Callable[[sqlite3.Connection], bool] | None = None, replaces: str | None = None) -> Stored | None`. It writes the two files (item 2, item 5), then in one transaction runs `guard` (a `False` ends it), inserts the row, and deletes the row `replaces` names. On a refusal or any error it removes the directory it made and, for an error, raises. After a replacement it removes the old directory.
    - `all(self, survey_id: str | None = None) -> _StoredList`, newest first.
    - `get(self, picture_id: str) -> Stored | None`.
    - `frame(self, picture_id: str, name: Literal["clean.jpg", "zones.jpg"]) -> bytes | None`.
    - `shot(self, stored: Stored, point: tuple[float, float] | None) -> Shot`: the row, its facts, and both files as a `Shot`; `None` when a file is gone.
    - `delete(self, picture_id: str) -> Stored | None`: files, then the row.
    - `delete_place(self, survey_id: str) -> int`: every picture of the place.
    - `counts(self) -> dict[str, int]` by place; `total(self) -> tuple[int, int]` (pictures, bytes).
    - `has_room(self) -> bool`: at least `FREE_MIN` free where `state_dir` is (`os.statvfs`).
    - `rename_camera(self, old: str, new: str) -> None`.
    - `sweep(self) -> tuple[int, int]`: directories removed, rows deleted (item 6). An entry under `pictures` that isn't a directory named by an id is removed too.
  - The method is `all`, not `list`, so the class has no name that hides the builtin.
- Produces, `app.py`: `app.state.pictures = Pictures(state, settings.state_dir)` and `app.state.clock`. `cli.serve` calls `app.state.pictures.sweep()` before it starts uvicorn, in both modes, and logs the two counts.

- [ ] **Step 1: Write the failing tests,** with a `shot(**changes)` helper that builds a `Shot` from `tests/jpegs.py`'s frames.
  - `test_state.py`: the version is 9; the `pictures` table's columns; a place's deletion takes its picture rows.
  - `test_add_writes_two_files_then_the_row`: both files hold the shot's bytes; the modes are 0700, 0700, 0600, 0600; the row's sizes are the byte counts; `facts` holds exactly `FACTS`; no column and no fact holds the point.
  - `test_the_id_is_sixteen_hex_and_never_a_counter`: two adds give two ids that match `ID`.
  - `test_a_write_that_fails_leaves_nothing`: with `os.fsync` patched to raise on the second file: `add` raises, no row, no directory.
  - `test_a_guard_that_refuses_leaves_nothing`: `add` returns `None`, no row, no directory.
  - `test_a_replacement_swaps_rows_in_one_transaction_and_removes_the_old_files`.
  - `test_only_an_id_makes_a_path(bad)`: for `..`, `../x`, `a` * 15, `a` * 17, `A` * 16, `%2e%2e`, and `""`: `get`, `frame`, `delete`, and `shot` answer `None` and `os.open`, `open`, and `os.scandir` are never called.
  - `test_a_row_whose_file_is_gone_is_a_404`: with `zones.jpg` removed, `frame` gives `None` for both names and `shot` gives `None`.
  - `test_delete_removes_the_files_first`: with the row's delete patched to raise, the files are already gone.
  - `test_delete_place_takes_every_picture_of_the_place_and_no_other`.
  - `test_the_sweep_removes_files_with_no_row_and_rows_with_no_files`: an orphan directory, a row with no directory, a row with one file, a stray file under `pictures`, and one whole picture: the sweep answers `(3, 2)` and the whole picture is untouched.
  - `test_has_room(free, expected)`, with `os.statvfs` patched just under and just over `FREE_MIN`.
  - `test_rename_camera_moves_every_place`.
  - `test_the_store_logs_nothing` (with `caplog`, across every test above).
- [ ] **Step 2: Run them.** They fail.
- [ ] **Step 3: Write the migration, the clock, and the store.**
- [ ] **Step 4: Run** `python -m pytest tm-control/backend/tests`, and once under Python 3.13 or older. PASS.
- [ ] **Step 5: Commit** ("Store a reference picture's frames and facts on the device").

### Task A4: The routes

**Files:**
- Create: `tm-control/backend/tm_control/modules/pictures/router.py`
- Modify: `tm-control/backend/tm_control/modules/pictures/__init__.py`, `tm-control/backend/tm_control/modules/__init__.py`, `tm-control/backend/tm_control/modules/cameras/router.py`, `tm-control/backend/tm_control/modules/cameras/reference.py` (`References` only), `tm-control/backend/tm_control/modules/location/router.py`, `tm-control/backend/tm_control/modules/sharing/download.py`, `tm-control/ui/src/api/openapi.json`, `tm-control/ui/src/api/schema.d.ts`, `tm-control/ui/tests/fake-api.ts`
- Test: `tm-control/backend/tests/test_api_pictures.py` (new), `test_api_cameras_reference.py`, `test_api_surveys.py`, `test_api_cameras.py`, `test_api_sharing_download.py`, `test_openapi_document.py`

**Interfaces:**
- Consumes: Task A2's `Shot`, `mark_of`, `package`; Task A3's `Pictures`, `Clock`.
- Produces, `pictures/router.py`, `APIRouter(prefix="/pictures", tags=["pictures"])`, every route `Depends(require_admin)`:
  - `PictureOut` (`id`, `survey_id`, `camera`, `taken_at` as `reference.iso` gives it, `reason`, `mark`, `after_restart`, `bytes`) and `PicturesState` (`pictures`, `stored`, `stored_bytes`).
  - `GET ""` (item 8), `GET "/{picture_id}/{picture}"` (item 9), `DELETE "/{picture_id}"` (item 10), `POST "/{picture_id}/package"` with `PackageIn` (`location: bool`, `looked: Literal[True]`) (item 11), which answers `reference.package(shot, with_location)` as the manual route does.
  - `picture_out(stored: Stored) -> PictureOut`, which the keep route uses too.
- Produces, `cameras/router.py`:
  - `POST "/{name}/reference/{ticket}/keep"`, 201, `response_model=PictureOut` (item 7). It holds `reconcile_lock` while it checks the place in use and stores.
  - `References.kept(ticket) -> bool` and `References.mark_kept(ticket)`, in memory, so a second keep is `already_kept`.
  - `neutral_name` also calls `app_state.pictures.rename_camera(name, new)`, after the places store.
- Produces, `location/router.py`: `SurveyOut.pictures: int` (the place's count); `delete_place` calls `app_state.pictures.delete_place(place.id)` before `Places.delete`, inside the lock.
- Produces, `sharing/download.py`: `DownloadFacts.pictures: int`, the device's count.
- Produces, `tests/fake-api.ts`: `pictureOut(changes)` and `picturesState(pictures)`; `DOWNLOAD_FACTS` gains `pictures: 0`.

- [ ] **Step 1: Write the failing tests.**
  - `test_api_pictures.py`, with helpers `kept(client)` (a take, then keep) and `listed(client, survey_id=None)`:
    - `test_every_route_needs_an_admin(method, path)`: a viewer gets 403 and nobody signed in 401, for the four routes here and the keep route.
    - `test_keep_stores_the_take_for_the_place_in_use`: 201; reason `manual`; the mark by the take's `people`; the files hold the bytes the dialog showed; `kept_by` is the admin.
    - `test_keep_refusals(case, status, code)`: an unknown ticket; a ticket under another camera's name; a take with no place in use; a take whose place was replaced by a deploy since; a second keep; no room.
    - `test_the_ticket_still_saves_the_zip_after_a_keep`.
    - `test_the_list_is_newest_first_and_can_be_one_places`; `stored` and `stored_bytes` count the whole device.
    - `test_a_frame_is_the_stored_bytes_with_no_store`.
    - `test_a_frame_under_a_made_up_id_is_a_404(bad)`, with Task A3's bad ids as the path, percent-encoded where needed.
    - `test_delete_is_a_204_twice_and_the_files_are_gone`.
    - `test_a_pictures_zip_is_the_manual_takes_zip`: the same four names, the JPEG entries byte for byte the stored files, and the data file equal to the manual zip's for the same take.
    - `test_no_route_gives_two_pictures`: the app's routes under `/pictures` are the four of this task, and none takes a list of ids.
    - `test_the_location_is_the_places_now`: correct the place's location after the keep; the data file holds the new point with `location` true, and `null` with it false or for a place with no point.
    - `test_package_refusals(case, status)`: an unknown id and a made-up one (404); `looked` false or missing (422); `location` missing (422).
    - `test_audit_rows_hold_keys_and_reasons`: the four actions' details by item 18, and no row holds an id.
    - `test_no_picture_fact_reaches_a_log_line`: with `caplog` across a keep, a list, a frame, a download, and a delete: no record holds an id, the place's id, the camera's key, or a coordinate, and uvicorn's access records are the only ones that hold a path.
  - `test_api_surveys.py`: `test_deleting_a_place_removes_its_pictures_files_first`; `test_a_place_says_how_many_pictures_it_has`.
  - `test_api_cameras.py`: `test_a_neutral_name_takes_the_cameras_pictures_with_it`.
  - `test_api_sharing_download.py`: the facts hold `pictures`.
- [ ] **Step 2: Run them.** They fail.
- [ ] **Step 3: Write the routes,** register `pictures.module` in `MODULES` after `cameras.module`, and regenerate the API files (the UI README's two commands). Add the two fixtures to `fake-api.ts`.
- [ ] **Step 4: Run** `python -m pytest tm-control/backend/tests script/tests`, once more under Python 3.13 or older, and the UI's build and tests in the pinned Node image. PASS, with no component changed.
- [ ] **Step 5: Commit** ("Keep, list, download, and delete stored reference pictures").

### Task A5: The screens

**Files:**
- Create: `tm-control/ui/src/modules/location/PlacePictures.vue`, `tm-control/ui/src/modules/location/PictureReview.vue`, `tm-control/ui/src/modules/location/pictures.ts`, `tm-control/ui/tests/place-pictures.spec.ts`, `tm-control/ui/tests/picture-review.spec.ts`, `tm-control/ui/tests/pictures.spec.ts`
- Modify: `tm-control/ui/src/modules/cameras/ReferencePicture.vue`, `tm-control/ui/src/modules/location/PlaceDetails.vue`, `tm-control/ui/src/modules/location/LocationPage.vue`, `tm-control/ui/src/modules/sharing/DownloadCard.vue`, `tm-control/ui/tests/reference-picture.spec.ts`, `tm-control/ui/tests/location-page.spec.ts`, `tm-control/ui/tests/download-card.spec.ts`, `tm-control/ui/README.md`
- Create: `docs/assets/images/location-pictures.png`, `docs/assets/images/location-picture-review.png`

**Interfaces:**
- Consumes: Task A4's routes and types.
- Produces, `pictures.ts`:
  - `storedUrl(id: string, picture: 'clean.jpg' | 'zones.jpg'): string`.
  - `reasonWords(reason): string` and `markLine(picture): { type: 'warning' | 'info'; text: string } | null`, with the words of Step 1: a warning for `person`, information for `unchecked`, `null` for `clear`.
  - `restartNote(picture): string | null`: Step 1's note for a picture with `after_restart`. It is shown as plain text under the picture's reason, never as an alert.
- Produces, `PlacePictures.vue`: props `place: SurveyOut`, `pictures: PictureOut[] | undefined`, `cameras: string[]` (the enabled cameras' keys when this is the place in use, else empty); emits `changed` (after a delete or a keep, so the page reloads the list and the counts). It holds the list, each picture's Download and Delete, and for the place in use a **Take a reference picture** button per camera, which opens `ReferencePicture`.
- Produces, `PictureReview.vue`: `v-model:open`, props `picture: PictureOut | null` and `hasLocation: boolean`; it shows item 15's step for that one picture, posts the package, and saves the blob with `saveBlob` under the name in the answer's `Content-Disposition`.
- Produces, `ReferencePicture.vue`: the Keep button and its line (item 13), and an emit `kept`.
- Produces, `PlaceDetails.vue`: a section "Reference pictures (n)" that renders `PlacePictures`. `LocationPage.vue` loads `GET /pictures?survey_id=` with a panel's other details, shows the device's count above the list of places, and passes the enabled cameras for the place in use.
- Produces, `DownloadCard.vue`: an item "Reference pictures stored" with the count and Step 1's line, shown when the count is above 0.

- [ ] **Step 1: Show the maintainer the words and the design note, and stop.** The drafts:
  - The Keep line, under the dialog's buttons: "Keep on this device stores both pictures on the device's card, under this place. They stay until you delete them or the place. Anyone who takes the card can read them."
  - Once kept: "Kept on this device. You can find it under this place on the Location page."
  - The section: "Reference pictures (n)"; empty: "No reference picture is stored for this place."
  - Why: `deployed` "The unit was deployed here"; `opted_in` "Pictures were turned on for this place"; `mounting` "The camera's mounting changed"; `setup` "The camera's setup changed in Frigate"; `daylight` "Taken again in daylight"; `manual` "Kept by an administrator".
  - The marks: `person` "Frigate was tracking a person. Blur them before you share it, or leave it out."; `unchecked` "The device couldn't check for people. Look closely before you share it."
  - The note on the first picture after a restart, plain text and no alert: "The unit restarted before this picture, so it may not show this place."
  - Delete: "Delete this picture? Both views are removed from the device. This can't be undone."
  - The review step's title: "Look at both views before this picture leaves the device". Its intro: "This picture shows your street and whoever was in view. Anyone who has it can tell where the unit is. Look at both views before you download it." The tick: "I have looked at both views".
  - The Location page's count: "The device stores n reference pictures."
  - The Sharing card's line: "They aren't part of this download. Download or delete them under each place on the Location page."
  - The design note, for the README's Location section: the pictures sit in the place's panel because a picture belongs to a place and is deleted with it; each row shows both views at a width where a person can be seen, never a thumbnail, because the list is also where an administrator decides what to delete; a download is one picture, so the review step shows one pair and its tick starts off every time, a `person` picture's warning sitting above the views where it is read first (PR 4 extends this dialog to many pictures); the images are plain `<img loading="lazy">` on the device's addresses, authorized by the session cookie, and the page keeps no copy.
  Take his edits into this step's list before any test is written.
- [ ] **Step 2: Write the failing tests.**
  - `pictures.spec.ts`: `reasonWords` for the six; `markLine` for the three marks; `restartNote`, and that `after_restart` doesn't change `markLine`.
  - `place-pictures.spec.ts`: lists both views of each picture with the time, camera, why, and mark; says so when there are none; Delete asks, deletes, and emits `changed`; Delete that fails shows the API's message beside the row; the place in use offers Take a reference picture for each enabled camera and another place offers none; Download opens the review with that picture; the list is newest first, and there is no button for several.
  - `picture-review.spec.ts`: shows both views of the one picture; Download is off until the tick; `a person picture shows its warning and still needs the tick`; `a picture taken after a restart shows its note outside any alert`; the request names that picture's id and its body holds the location box's value and `looked: true`; the box is off with no location; the blob is saved under the answer's file name; a 404 says the picture is gone and asks for a reload; closing the dialog, or opening it for another picture, clears the tick.
  - `reference-picture.spec.ts`: Keep on this device shows after a take at a place and not for a take with none; it posts the keep, shows the line, and turns off; `already_kept` and `no_space` show the API's message; Save the zip still works after a keep; Take again brings the button back.
  - `location-page.spec.ts`: the device's count above the places; a panel loads its pictures; a `changed` reloads them and the count.
  - `download-card.spec.ts`: the item and its line show with a count above 0 and not at 0.
- [ ] **Step 3: Run them.** They fail.
- [ ] **Step 4: Write the components.**
- [ ] **Step 5: Run** the UI's build and tests in the pinned Node image. PASS.
- [ ] **Step 6: Screenshots in fake mode** at 375 px and 1280 px: a place's pictures with one of each mark, the review step for a `person` picture, and the dialog after a keep. Fake mode's pictures are drawings, so these can be looked at. The two docs images come from the 1280 px set.
- [ ] **Step 7: Commit** ("Show, download, and delete a place's stored reference pictures").

### Task A6: Docs, device tests, and the plan's public copy

**Files:**
- Modify: `docs/use/cameras.md`, `docs/use/location.md`, `docs/use/sharing.md`, `docs/data-and-payloads/data-overview.md`, `docs/development/tm-control.md`, `docs/development/software-update.md`, `CLAUDE.md`, `script/devpi/README.md`
- Modify: `script/devpi/tests/test_web.py`
- Create: `design/plans/2026-11-27-data-pack-stored-pictures.md`

- [ ] **Step 1: The device tests,** in `test_web.py`, on `pii_free` units only.
  - `test_a_kept_picture_is_listed_downloaded_and_deleted`: take, keep, and in a `finally` delete. The list holds it with `bytes` equal to the two frames' `Content-Length`s; the directory and its files have the modes of item 2 and the service user as owner (read with `stat`, never opened); the package's zip has four entries whose JPEG sizes are the stored sizes; after the delete the frame is a 404 and the directory is gone. A failure names statuses, sizes, and modes only.
  - `test_pictures_need_an_admin_on_the_pi`: no session gets a redirect or a 401 for the list and a frame.
- [ ] **Step 2: `docs/use/cameras.md`,** "Take a reference picture": the dialog's Keep on this device, what it stores and where, and that the sentence "never saves them" now reads: the device holds a take in memory for 10 minutes and saves it only when you choose Keep on this device.
- [ ] **Step 3: `docs/use/location.md`:** a new section, "Reference pictures": the list under each place, taking one from the place in use, the review step and why both views have to be looked at, that a download is one picture and the newest shows the zones as they are, Delete, and that deleting a place deletes its pictures. An admonition says what is new: stored pictures are ordinary files on the device's card; anyone who takes the card can read them, as they can read Frigate's snapshots; they are in no backup, so a reflashed card loses them.
- [ ] **Step 4: The other pages.**
  - `sharing.md`: the card's count and that pictures aren't in that download.
  - `data-overview.md`, "Images do exist on the device": a kept reference picture is an image the device keeps until you delete it; where; who can see it; that it is never uploaded and never part of the database.
  - `software-update.md`, "Restoring by hand": the restore point holds the control app's database and no picture; after a restore, pictures kept since the restore point are removed when the control app starts.
  - `tm-control.md`: the reference picture's rows (the keep route) and paragraph (what is in memory and what is on the card); a new part for the Pictures module: the routes, the table, the directory and its modes, the order of writes and deletes, the sweep, the id rule, the audit rows, and what never reaches a log.
  - `CLAUDE.md`: the `tm-control/` bullet (the Pictures routes and the Location page's list); the control app's paragraph, where "no picture is written to disk or logged" becomes the rule of item 1 with the directory's path; the state database's list of what it holds; the service's bullet (the state directory now holds pictures, in no backup and no restore point).
  - `script/devpi/README.md`: the rows for `test_cameras.py` and `test_web.py`.
- [ ] **Step 5: The plan's public copy:** this file, with Part B kept and marked as the next PR.
- [ ] **Step 6: Run** every off-device check and `mkdocs build --strict`. PASS.
- [ ] **Step 7: Commit** the device tests, then the docs, then the plan's copy.

### Task A7: Pi plan and the PR (3a)

- [ ] **Step 1: Pi plan,** as a logged `tmdev check` on the bench unit, after `tmdev deploy <host> -- -t tm-control -t revproxy`. Frigate's detection stays off throughout; say so in the check. No item opens a picture.
  1. The device suite passes, with Task A1's test and Task A6's two among them.
  2. The control app's journal since the deploy has the sweep's line with `0` and `0`, and `state.sqlite`'s `user_version` is 9.
  3. Keep a take through the API. `sudo stat` on the directory and both files: the modes and owner of item 2, and sizes equal to the list's `bytes`.
  4. The list, both frames (status, type, `Content-Length`, `Cache-Control`), and a one-picture package: `unzip -l` shows four entries, and the two JPEG sizes are the stored sizes.
  5. Keep a second take: the list has two, newest first, and each downloads alone as its own zip of four entries.
  6. The sweep: stop the control app; make an empty directory under `pictures` with a 16-hex name and remove one picture's `zones.jpg`; start it. The journal's line reads `2` and `1` (the empty directory and the broken picture's own directory, and its row), the list has one picture, and the directory count is one.
  7. Delete a place that has a picture (deploy another place first): its directory is gone and the list is empty for it.
  8. In the control app's journal since the deploy, and in **Download diagnostics**: count lines that hold `pictures/` followed by 16 hex outside an access-log path, a `.jpg` name outside one, or a coordinate. Expect 0. The diagnostics text doesn't list the state directory.
  9. **Manual, the maintainer's:** on a phone, on the unit's hotspot: keep a take, find it under the place, open the review step, and download it. He says whether both views are large enough to see a person.
- [ ] **Step 2: Every off-device check once more** on the final branch; `git grep` the branch and its messages for anything that must stay out of public text: device names, addresses, and any coordinate that isn't allowed.
- [ ] **Step 3: The PR's text,** the template filled in, "Closes" this PR's issue and "Part of #371".
  - Title: `data-pack PR 3a: Keep reference pictures on the device, and download or delete them from the Location page`.
  - First body line: `Series: data-pack PR 3a of 5 · stacked on dev · next: PR 3b, reference pictures the device takes on its own · map: #371`.
  - The release note: "A reference picture can now stay on the device. After you take one, **Keep on this device** stores both views under the place in use. Each place on the Location page lists its pictures, with the time, the camera, and whether Frigate was tracking a person. Before a picture leaves the device you look at both views and confirm it. Kept pictures are ordinary files on the device's card: only an administrator can open them in the app, but anyone who takes the card can read them, and no backup holds them. Nothing is uploaded."
  - Also: the Docs list; the screenshots; Task A1's table and the two numbers chosen; the Pi plan's results; and the AI-assistance section.
  - #386's body says "PR 2 of 4 · next: PR 3". If it is still open when this PR opens, its `Series:` line and #371's list change to five with 3a and 3b, with the maintainer's read.
  - The maintainer reads the commit messages and the PR text before any push.

---

## Part B: PR 3b, pictures the device takes (the next PR; not built here)

Part B starts from `dev` once 3a has merged.

### Task B1: The engine's answer names the cameras

**Files:**
- Modify: `container/node-red-tm/data/flows.json`
- Test: `script/tests/test_node_red_flows.py`

**Interfaces:**
- Produces, the function `02692ea73db6605b`: its last statement before the `return` becomes

  ```javascript
  msg.payload = {
      changed: insertDevice.length + insertCamera.length,
      cameras: insertCamera.map((item) => item.params.$camera).sort(),
  };
  ```

  and the header comment's "5 the answer" says what the answer holds: how many rows opened, and the key of each camera whose row opened, which the control app takes a reference picture of at a place that keeps them; the keys go nowhere else and are not logged.

- [ ] **Step 1: Write the failing tests.**
  - The seven tests that compare the payload with `{"changed": n}` compare it with the pair: `["cam_a"]` where a camera row opened, `[]` where none did.
  - `test_setup_engine_answers_the_cameras_whose_row_opened`: two open cameras, one whose zones differ: `{"changed": 1, "cameras": ["cam_b"]}`.
  - `test_setup_engine_answers_every_camera_on_an_empty_database`, sorted, with two cameras in the snapshot in the other order.
  - `test_setup_engine_answers_no_camera_for_a_device_row`: the Frigate version differs: `{"changed": 1, "cameras": []}`.
  - `test_setup_engine_answers_no_camera_for_a_row_that_only_closed`: a camera that left `config.yml`.
  - `test_setup_engine_answers_no_camera_for_an_incomplete_snapshot`.
  - `test_the_setup_answer_holds_two_keys`: `set(payload) == {"changed", "cameras"}`, and the upload's message (output 6) is what it was.
- [ ] **Step 2: Run** `python -m pytest script/tests/test_node_red_flows.py -k setup`. The new and the changed ones fail.
- [ ] **Step 3: Edit the function** with a script, and check `python3 -m json.tool container/node-red-tm/data/flows.json >/dev/null`.
- [ ] **Step 4: Run** `python -m pytest script/tests`. PASS. `git diff --stat` shows `flows.json` and the test file only, and the diff of `flows.json` is one line: that function's `func`.
- [ ] **Step 5: Commit** ("Name the cameras whose setup row opened in the setup engine's answer").

### Task B2: The opt-in, the takes table, and the poster's hook

**Files:**
- Create: `tm-control/backend/tm_control/modules/pictures/takes.py`
- Modify: `tm-control/backend/tm_control/core/state.py`, `tm-control/backend/tm_control/modules/location/places.py`, `tm-control/backend/tm_control/adapters/nodered.py`, `tm-control/backend/tm_control/modules/setup_history/poster.py`, `tm-control/backend/tm_control/fake.py`
- Test: `tm-control/backend/tests/test_pictures_takes.py` (new), `test_state.py`, `test_places.py`, `test_nodered_adapter.py`, `test_setup_poster.py`, `test_fake_nodered.py`

**Interfaces:**
- Produces, `core/state.py`, the tenth migration:

  ```sql
  ALTER TABLE surveys ADD COLUMN keep_pictures INTEGER NOT NULL DEFAULT 0 CHECK (keep_pictures IN (0, 1));
  ALTER TABLE surveys ADD COLUMN pictures_boot_id TEXT;  -- the power-on of the last deploy, opt-in, or mounting save here
  CREATE TABLE picture_takes (
      survey_id TEXT NOT NULL REFERENCES surveys(id) ON DELETE CASCADE,
      camera TEXT NOT NULL,
      reason TEXT NOT NULL CHECK (reason IN ('deployed', 'opted_in', 'mounting', 'setup', 'daylight')),
      boot_id TEXT NOT NULL,
      due REAL NOT NULL,  -- seconds on the boot clock: the next look
      person_since REAL,  -- boot clock: the first try that saw a person
      failing_since REAL,  -- boot clock: the first try in a row that gave no pictures
      replaces TEXT REFERENCES pictures(id) ON DELETE CASCADE,  -- a daylight round's picture
      window_day TEXT,  -- a daylight round's window, as the local date, once it has begun
      gave_up INTEGER NOT NULL DEFAULT 0 CHECK (gave_up IN (0, 1)),
      PRIMARY KEY (survey_id, camera)
  );
  ```
- Produces, `places.py`: `Survey.keep_pictures: bool`; `Places.set_keep_pictures(survey_id, keep: bool)`; `Places.affirm(survey_id, boot_id: str)`; `Places.affirmed(survey_id) -> str | None`.
- Produces, `takes.py`:
  - `Take`: a frozen dataclass of the row.
  - `class Takes(state: State)`: `start(survey_id, camera, reason, boot_id, due)` (item 23: a new row, or the waiting one moved with its first reason, or a daylight or given-up one replaced whole); `due(now: float) -> list[Take]` (not given up, `due <= now`, oldest first); `save(take: Take)`; `drop(survey_id, camera)`; `drop_place(survey_id)`; `keep_only(survey_id | None)` (drop every take of another place); `drop_other_boots(boot_id) -> int`; `waiting() -> list[Take]`.
- Produces, `adapters/nodered.py`: `post_setup(self, body: dict) -> _Keys` (`_Keys = list[str]`): the answer's `cameras` when it is a list of strings, else `[]`. It raises as before when the call fails.
- Produces, `poster.py`: `Poster(gather, post, interval, retry, opened: Callable[[list[str]], None] | None = None)`. After a post that returned keys, `run_once` calls `opened(keys)`. Whatever `opened` raises is dropped and is not a failed snapshot.
- Produces, `fake.py`: `FakeNodeRed.post_setup` returns the keys of the cameras whose posted facts differ from the last post's, and `[]` for the first post.

- [ ] **Step 1: Write the failing tests.**
  - `test_state.py`: the version is 10; every place from before has `keep_pictures` 0; a picture's deletion takes its daylight round.
  - `test_places.py`: `test_keep_pictures_and_the_affirmed_boot`.
  - `test_pictures_takes.py`: `test_a_start_makes_a_take_due_then`; `test_a_second_start_moves_it_and_keeps_the_first_reason`; `test_a_start_replaces_a_daylight_round_and_a_give_up`; `test_due_leaves_out_later_and_given_up_takes`; `test_keep_only_drops_other_places`; `test_drop_other_boots`.
  - `test_nodered_adapter.py`: `test_post_setup_answers_the_cameras`; `test_post_setup_without_cameras_is_an_empty_list(body)` for `{"changed": 1}`, `{"changed": 1, "cameras": "cam_a"}`, `{"changed": 1, "cameras": [1]}`, an empty body, and a list.
  - `test_setup_poster.py`: `test_the_hook_gets_the_cameras_of_a_post`; `test_no_cameras_no_call`; `test_a_hook_that_raises_is_not_a_failed_snapshot` (`run_once` is true, nothing is logged, and the next wait is the interval).
  - `test_fake_nodered.py`: `test_the_fake_answers_the_cameras_that_changed`.
- [ ] **Step 2: Run them.** They fail.
- [ ] **Step 3: Write** the migration, the two `Places` methods, `takes.py`, the adapter's answer, the hook, and the fake's answer. `app.py` is wired in Task B4.
- [ ] **Step 4: Run** `python -m pytest tm-control/backend/tests`, and once under Python 3.13 or older. PASS.
- [ ] **Step 5: Commit** ("Record a place's choice to keep reference pictures, and the takes that wait").

### Task B3: The taker (tricky)

**Files:**
- Create: `tm-control/backend/tm_control/modules/pictures/taker.py`, `tm-control/backend/tm_control/modules/pictures/window.py`
- Test: `tm-control/backend/tests/test_pictures_taker.py` (new), `tm-control/backend/tests/test_pictures_window.py` (new)

**Interfaces:**
- Consumes: `shoot` and `NoShot` (Task A2); `Pictures`, `Clock`, `ManualClock` (Task A3); `Takes`, `Places.affirmed` (Task B2).
- Produces, `window.py`:
  - `OPENS = 10`, `CLOSES = 14` (local hours).
  - `local(wall: float, zone: str) -> datetime | None`: `None` for a zone `zoneinfo` doesn't know.
  - `inside(when: datetime) -> bool`: from 10:00:00 up to and not including 14:00:00.
  - `last_try(when: datetime, retry: float) -> bool`: `when + retry` is at or after 14:00 that day.
- Produces, `taker.py`:
  - `WAIT = 600.0`, `RETRY = 300.0`, `PERSON_FOR = 3600.0`, `FAILING_FOR = 86400.0`, `TICK = 30.0`.
  - `class Taker(app_state, clock: Clock, *, wait=WAIT, retry=RETRY, person_for=PERSON_FOR, failing_for=FAILING_FOR, tick=TICK, zone: Callable[[], str | None])`. `zone` gives the device clock's zone.
    - `request(self, survey_id: str, cameras: Iterable[str], reason: str) -> None`.
    - `sweep(self) -> int`: `Takes.drop_other_boots`.
    - `step(self) -> None`: one look at every due take, by items 24 to 29. It never raises: a take whose try raised is left for the next look, 5 minutes on, and the failure is noted by its class as the poster notes one.
    - `start(self)`, `stop(self)`, `wake(self)`: one daemon thread named `picture-taker` that calls `sweep` once and then `step` every `tick`.
  - `start_takes(app_state, cameras: Iterable[str], reason: str) -> None`: for the place in use, when its flag is on, asks `request` for each of `cameras` whose entry in `config.yml` is enabled. It never raises, and does nothing when `config.yml` can't be read.

  The rule a step applies to a pair, which the tests pin:

  | Take | Pair | Result |
  | --- | --- | --- |
  | first picture | `clear` or `unchecked` | stored |
  | first picture | `person`, under an hour since the first | discarded; again in 5 minutes |
  | first picture | `person`, an hour or more since the first | stored, marked `person` |
  | daylight | `clear` | replaces |
  | daylight | `unchecked`, and the picture is marked | replaces |
  | daylight | `unchecked`, and the picture is `clear` | discarded; again in 5 minutes, until the window closes |
  | daylight | `person`, not the window's last try | discarded; again in 5 minutes |
  | daylight | `person`, the last try, and the picture is marked | replaces |
  | daylight | `person`, the last try, and the picture is `clear` | discarded; the round ends |

- [ ] **Step 1: Write the failing tests.** `test_pictures_taker.py` builds an app in fake mode, opts the place in, patches `shoot` to return a `Shot` with a chosen `objects` block or raise a `NoShot`, and drives a `Taker` with a `ManualClock`. A helper `advance(seconds)` moves both of the clock's times.
  - `test_pictures_window.py`: `test_inside(time, expected)` for 09:59:59, 10:00:00, 13:59:59, 14:00:00; `test_last_try` for 13:54:59, 13:55:00, 13:59:00; `test_local_in_a_zone_and_across_a_dst_change`; `test_an_unknown_zone_is_none`.
  - Waiting: `test_nothing_happens_before_ten_minutes`; `test_a_change_inside_the_wait_moves_it`; `test_a_take_is_tried_at_ten_minutes`.
  - The first picture: `test_a_clear_pair_is_stored` (reason, mark, the files, the audit row `picture.taken`); `test_an_unchecked_pair_is_stored_at_once`; `test_a_person_means_again_in_five_minutes_and_nothing_stored`; `test_the_first_clear_pair_within_the_hour_is_kept`; `test_after_an_hour_of_people_the_next_pair_is_kept_marked_person`.
  - No pair: `test_a_camera_that_isnt_sending_is_tried_every_five_minutes` (for each `NoShot` code); `test_a_pair_between_failures_starts_the_day_again`; `test_after_a_day_the_take_gives_up_and_stays`; `test_a_new_start_clears_a_give_up`.
  - Dropped: `test_a_take_for_a_place_no_longer_in_use_is_dropped`; `test_a_take_for_a_place_switched_off_is_dropped`; `test_a_take_for_a_camera_turned_off_or_gone_is_dropped`; `test_a_take_whose_shot_names_another_place_stores_nothing`.
  - The anti-goal: `test_a_take_in_flight_when_the_switch_goes_off_stores_nothing`: `shoot` is patched to turn the place's flag off and drop its takes before it returns; no row, no directory.
  - The ceiling: `test_at_the_count_no_picture_is_stored_and_the_take_retries`; `test_under_the_free_space_floor_the_same`; `test_room_again_within_the_day_stores_it`; `test_a_daylight_replacement_at_the_ceiling_is_refused`.
  - Daylight, with a place whose zone is `America/Los_Angeles` and a clock set by local time:
    - `test_a_picture_kept_in_the_window_gets_no_round`, at 10:00 and 13:59.
    - `test_a_picture_kept_outside_it_gets_one`, at 09:59 and 14:00 and 21:00.
    - `test_the_round_waits_for_the_window_then_tries`.
    - `test_a_clear_daylight_pair_replaces_the_picture`: one row for the camera, reason `daylight`, a new id, the old directory gone, the audit row `picture.replaced`.
    - `test_an_unchecked_daylight_pair_replaces_a_marked_picture_at_once` and `test_an_unchecked_daylight_pair_never_replaces_a_clear_one`.
    - `test_a_person_at_the_last_try_replaces_only_a_marked_picture(original, replaced)`.
    - `test_the_round_ends_with_its_window`: a camera that sends nothing from 10:00 to 14:00 has no take at 14:00 and none the next day.
    - `test_a_daylight_picture_gets_no_second_round`.
    - `test_a_new_change_ends_the_cameras_daylight_round_and_keeps_its_picture`.
    - `test_deleting_the_picture_ends_its_round`.
    - `test_the_window_is_the_places_zone_then_the_devices_then_none`: with the place's zone set; with it empty and the device's given; with neither, the picture is kept and no round starts.
  - Restarts:
    - `test_takes_from_another_boot_are_dropped_at_start`: a waiting take, a people retry, and a daylight round; a new `Taker` with another boot id sweeps three.
    - `test_a_restart_of_the_control_app_keeps_the_takes`: a new `Taker` and a new `Takes` over the same database, the same boot id, the boot clock 3 minutes on: the take is tried at its own 10 minutes.
    - `test_a_daylight_round_never_crosses_a_boot`: after the sweep the evening picture is still the place's only one, whatever the next days bring.
    - `test_the_first_picture_after_a_restart_is_marked`: the place affirmed in boot `a`; a `setup` take stored in boot `b` has `after_restart`; the same camera's next in boot `b` hasn't; another camera's first in boot `b` has.
    - `test_an_admins_deploy_opt_in_or_mounting_save_in_this_boot_means_no_mark`.
    - `test_a_replacement_carries_the_mark`.
  - Clocks: `test_a_wall_clock_jump_moves_no_wait`: the wall clock jumps a year forward and back between looks; the take is tried when the boot clock says.
  - `test_a_step_never_raises_and_logs_a_class_once`: `shoot` raises a `RuntimeError("cam_a at 45.0")`; ten steps log one warning that holds `RuntimeError` and not the text.
  - `test_the_taker_logs_no_camera_place_id_or_mark` (with `caplog`, across the file).
  - `test_start_takes`: only for the place in use with its flag on; only enabled cameras; nothing with `config.yml` unreadable; never raises.
- [ ] **Step 2: Run them.** They fail.
- [ ] **Step 3: Write `window.py` and `taker.py`.** The store's `guard` (Task A3) is where item 25's check runs; the "after a restart" rule (item 27) is worked out inside the same transaction.
- [ ] **Step 4: Run** `python -m pytest tm-control/backend/tests`, and once under Python 3.13 or older. PASS.
- [ ] **Step 5: Commit** ("Take a reference picture when nobody is in view, and again in daylight").

### Task B4: What starts a take, the waiting list, and the Status check

**Files:**
- Create: `tm-control/backend/tm_control/modules/pictures/checks.py`
- Modify: `tm-control/backend/tm_control/app.py`, `tm-control/backend/tm_control/cli.py`, `tm-control/backend/tm_control/modules/location/router.py`, `tm-control/backend/tm_control/modules/cameras/router.py`, `tm-control/backend/tm_control/modules/pictures/router.py`, `tm-control/backend/tm_control/modules/apps/checks.py`, `tm-control/backend/tests/fixtures/status_fake.json`, `tm-control/ui/src/api/openapi.json`, `tm-control/ui/src/api/schema.d.ts`, `tm-control/ui/tests/fake-api.ts`
- Test: `tm-control/backend/tests/test_api_pictures_automatic.py` (new), `test_api_surveys.py`, `test_api_mounting.py`, `test_api_cameras.py`, `test_app_checks.py`

**Interfaces:**
- Consumes: `Taker`, `start_takes` (Task B3); the poster's `opened` (Task B2).
- Produces, `app.py`: `app.state.picture_taker = Taker(app.state, app.state.clock, zone=…)`, built in both modes; the poster is built with `opened=lambda keys: start_takes(app.state, keys, "setup")`. `cli.serve` starts the taker on a device, and in fake mode only when `TM_CONTROL_FAKE_PICTURES=1`, with `wait`, `retry`, `person_for`, and `failing_for` divided by 60.
- Produces, `location/router.py`:
  - `DeployIn.keep_pictures: bool | None = None`. In `deploy_place`, inside the lock after the store is written: set the flag when it was sent; `Places.affirm` with this boot's id; `Takes.keep_only(place.id)`; then, with the flag on, `request` for each camera in `waiting` with reason `deployed`; with it off, `Takes.drop_place`. A deploy that turns the flag on for a place already in use is an opt-in: every enabled camera, reason `opted_in`.
  - `PUT "/{survey_id}/pictures"` with `PicturesIn` (`keep: bool`, `delete_stored: bool = False`), `response_model=SurveyOut` (item 21). Turning it on affirms and requests every enabled camera with reason `opted_in`; turning on what is on does nothing.
  - `save_mounting`, after a save that wrote: `Places.affirm`, then, unless `body.moved` is `False` (the answer "measured better"), `start_takes` for each camera in `written` whose `_five` differs from `before`, with reason `mounting`.
- Produces, `cameras/router.py`: `set_camera` calls `start_takes(app_state, [name], "deployed")` when the entry went from off to on.
- Produces, `pictures/router.py`: `PicturesState` gains `limit: int` and `waiting: list[WaitingOut]` (`survey_id`, `camera`, `reason`, `state`, `due_in`) (item 31). `state` is `gave_up` for a take that gave up, else `daylight` for a daylight round, else `no_picture` while `failing_since` is set, else `person` while `person_since` is set, else `waiting`.
- Produces, `pictures/checks.py`: `reference_pictures(context) -> list[Check]`, one check with the id `apps.reference_pictures` (item 32), which joins the Apps group after `setup_history`. Its words are Task B5 Step 1's.

- [ ] **Step 1: Write the failing tests.**
  - `test_api_surveys.py`:
    - `test_a_place_keeps_no_pictures_until_asked`.
    - `test_deploy_with_the_box_ticked_starts_a_take_for_each_camera`; `test_deploy_without_the_key_keeps_the_places_choice`; `test_deploy_with_it_off_drops_the_places_takes`.
    - `test_a_redeploy_that_changes_one_heading_starts_that_cameras_take_only`; `test_a_redeploy_that_turns_the_box_on_is_an_opt_in`; `test_a_radar_gets_no_take`.
    - `test_deploying_another_place_drops_the_old_places_takes`.
    - `test_the_switch(case)`: on starts takes with reason `opted_in`; on twice starts none the second time; off drops takes and keeps pictures; off with `delete_stored` removes them and their files; another place is 409 `not_in_use`; a viewer is 403.
    - `test_the_switchs_audit_rows`.
    - `test_a_heading_correction_starts_nothing`; `test_a_location_or_time_zone_correction_starts_nothing`.
  - `test_api_mounting.py`: `test_a_save_starts_a_take_for_a_camera_whose_values_changed`, for the answer "moved" and for a save the question wasn't asked of; `test_a_save_answered_measured_better_starts_none_and_still_affirms`; `test_a_save_that_changes_only_measured_or_a_radar_starts_none`; `test_a_dry_run_starts_none`; `test_a_save_at_a_place_that_keeps_none_starts_none`.
  - `test_api_cameras.py`: `test_turning_an_entry_on_starts_a_take`; `test_saving_an_entry_that_was_on_starts_none`.
  - `test_api_pictures_automatic.py`: `test_the_setup_answers_cameras_start_takes` (through `app.state.setup_poster.run_once()` with `post_setup` patched); `test_a_key_that_is_no_enabled_camera_starts_none`; `test_the_list_says_what_waits(state)` for the five states; `test_due_in_counts_down_on_the_boot_clock`; `test_the_limit_is_the_ceiling`.
  - `test_app_checks.py`: `test_reference_pictures_check(case, status)`: no place keeps pictures; kept and fine; at the count; under the floor; a take that gave up (the detail names the camera's key and no place).
- [ ] **Step 2: Run them.** They fail.
- [ ] **Step 3: Wire it,** add the check to `status_fake.json`, and regenerate the API files.
- [ ] **Step 4: Run** `python -m pytest tm-control/backend/tests script/tests`, once more under Python 3.13 or older, and the UI's build and tests. PASS.
- [ ] **Step 5: Commit** ("Start a reference picture after a deploy and after a camera's mounting or setup changes").

### Task B5: The box, the switch, and what waits

**Files:**
- Modify: `tm-control/ui/src/modules/location/DeployReview.vue`, `tm-control/ui/src/modules/location/PlacePictures.vue`, `tm-control/ui/src/modules/location/pictures.ts`, `tm-control/ui/src/modules/location/LocationPage.vue`, `tm-control/ui/tests/deploy-review.spec.ts`, `tm-control/ui/tests/place-pictures.spec.ts`, `tm-control/ui/tests/pictures.spec.ts`, `tm-control/ui/tests/location-page.spec.ts`, `tm-control/ui/README.md`
- Modify: `docs/assets/images/location-pictures.png`; create `docs/assets/images/location-deploy-pictures.png`

**Interfaces:**
- Consumes: Task B4's `keep_pictures`, the switch's route, and `waiting`.
- Produces, `DeployReview.vue`: a `v-checkbox` after `sharingLine`, starting at `place.keep_pictures`, with the two lines under it; `deploy()` posts `{headings, keep_pictures}`.
- Produces, `PlacePictures.vue`: for the place in use, a line that says whether pictures are kept, a button that turns it on, or one that turns it off through a `ConfirmDialog` with the box "Delete this place's pictures too"; and a line for each waiting take. New prop `waiting: WaitingOut[]`.
- Produces, `pictures.ts`: `waitingLine(take): string`.

- [ ] **Step 1: Show the maintainer the words and the design note, and stop.** The drafts:
  - The box: "Keep reference pictures at this place". Under it: "About 10 minutes after you deploy, and after a camera's mounting or its setup in Frigate changes, the device takes a picture of each camera's view and keeps it on its card. It waits until Frigate tracks nobody in view, and takes it again in daylight. The pictures show your street. They stay on the device until you delete them."
  - On the place in use: "The device keeps reference pictures at this place." with **Stop keeping pictures**, or "The device doesn't keep reference pictures at this place." with **Keep pictures here**.
  - Turning it off: "Stop keeping reference pictures at this place? The device takes no more here. The n it has stay until you delete them."
  - What waits: `waiting` "A picture of <camera> is due about 10 minutes after the last change."; `person` "Someone was in view of <camera>. The device tries again every 5 minutes."; `no_picture` "<camera> gave no picture. The device tries again every 5 minutes, for a day."; `daylight` "<camera>'s picture will be taken again between 10:00 and 14:00."; `gave_up` "The device stopped trying for a picture of <camera>. Change something, or take one yourself."
  - The Status check: its title "Reference pictures"; `ok` "No place keeps reference pictures." or "Reference pictures are kept at the place in use. n are stored."; at the count "The device has stopped taking reference pictures: it stores n, the most it keeps. Delete some on the Location page."; under the floor "The device has stopped taking reference pictures: less than <size> is free on its card."; gave up "The device stopped trying for a picture of <camera>: for a day the camera gave none."
  - The design note, for the README: the box is in the review because that is the one step that says what will be recorded from now on, and it shows the place's last choice so that a place deployed again keeps none or keeps them knowingly; the switch sits with the pictures, not with the place's buttons, because it is about them; turning it off never deletes unless the box is ticked.
  Take his edits into this step's list, and Task B4's check, before any test is written.
- [ ] **Step 2: Write the failing tests.**
  - `deploy-review.spec.ts`: the box starts as the place's choice; ticked, the deploy's body holds `keep_pictures: true`; unticked, `false`; the two lines are there; the box is off while deploying.
  - `place-pictures.spec.ts`: the place in use says which and offers the other; turning on posts `{keep: true, delete_stored: false}`; turning off asks, with the count, and posts the box's value; a place that isn't in use has neither; a line per waiting take.
  - `pictures.spec.ts`: `waitingLine` for the five states.
  - `location-page.spec.ts`: after a deploy with the box ticked, the place's panel shows what waits.
- [ ] **Step 3: Run them.** They fail.
- [ ] **Step 4: Write the changes.**
- [ ] **Step 5: Run** the UI's build and tests in the pinned Node image. PASS.
- [ ] **Step 6: Screenshots in fake mode** (started with `TM_CONTROL_FAKE_PICTURES=1`) at 375 px and 1280 px: the review with the box; the place in use with a waiting take, then with its picture; the confirmation for turning it off.
- [ ] **Step 7: Commit** ("Let an administrator choose to keep reference pictures at a place").

### Task B6: Docs, device tests, and the plan's public copy

**Files:**
- Modify: `docs/use/location.md`, `docs/use/cameras.md`, `docs/use/device-health.md`, `docs/data-and-payloads/data-overview.md`, `docs/data-and-payloads/setup-history.md`, `docs/development/tm-control.md`, `CLAUDE.md`, `script/devpi/README.md`, `design/plans/2026-11-27-data-pack-stored-pictures.md`
- Modify: `script/devpi/tests/test_web.py`

- [ ] **Step 1: The device tests,** on `pii_free` units only: `test_pictures_say_what_waits_and_the_limit` (the list answers `limit` and a `waiting` list whose entries have the five keys); `test_the_boot_id_is_readable_by_the_control_app` (as the service user: 36 characters).
- [ ] **Step 2: `docs/use/location.md`,** "Reference pictures", a part "Pictures the device takes on its own":
  - the box and the switch, and that a place nobody opted in stores nothing;
  - what starts a picture, as a list;
  - when: 10 minutes after the last change; nobody in view, or again every 5 minutes for an hour; again in daylight, between 10:00 and 14:00 in the place's time zone, with a link to the time zone's section;
  - the three marks and what to do about each;
  - restarts: what the device drops, why it never replaces a picture after a shutdown, what "the unit restarted before this picture" means, and the cost: a unit that loses power overnight after an evening deploy keeps its evening picture;
  - the limit and what the Status page says at it;
  - that the people check needs Frigate's detection on, so on a unit as installed every picture is marked "couldn't check", with a link to the check's limits on the Cameras page.
- [ ] **Step 3: The other pages.**
  - `cameras.md`: one sentence under "Take a reference picture" that the device can take them itself, with the link.
  - `device-health.md`: the new check.
  - `data-overview.md`: the kept pictures' paragraph says the device can take them on its own at a place you opted in.
  - `setup-history.md`: nothing in the tables changes; one sentence under how the rows start that a new camera row is also what makes the device take a reference picture at a place that keeps them.
  - `tm-control.md`: the taker (the loop, the table, the two clocks, the boot id, the rule table of Task B3, the guard, the ceiling); what starts a take, by route; the engine's answer and its `cameras`; the poster's hook; the Status check; fake mode's switch; and beside the snapshot's facts, Review Focus 9's sentence.
  - `CLAUDE.md`: the Location clause of the `tm-control/` bullet (the opt-in and the switch); the control app's paragraph (the taker beside the poster, the boot id, what is dropped at start); a name contract: the setup engine's answer (`changed`, `cameras`) with `NodeRed.post_setup`, pinned by `script/tests/test_node_red_flows.py` and `test_nodered_adapter.py`; the state database's list (migration 10).
  - `script/devpi/README.md`: the row for `test_web.py`.
- [ ] **Step 4: The plan's public copy** loses its "next PR" mark on Part B.
- [ ] **Step 5: Run** every off-device check and `mkdocs build --strict`. PASS.
- [ ] **Step 6: Commit** the device tests, then the docs, then the plan's copy.

### Task B7: Pi plan and the PR (3b)

- [ ] **Step 1: Pi plan,** as a logged `tmdev check` on the bench unit, after `tmdev deploy <host> -- -t node-red-tm -t tm-control -t revproxy`. Items 1 to 9 run with Frigate's detection off; say so in the check. No item opens a picture. Where an item waits 10 minutes, say so in the check and go on with the next reading.
  1. The device suite passes. Node-RED's journal has a "Flows file" line that names the installed `flows.json`, and `state.sqlite`'s `user_version` is 10.
  2. Deploy a place with the box ticked. The list's `waiting` has a take for each enabled camera, `state` `waiting`, `due_in` near 600. About 10 minutes later each has a picture: reason `deployed`, mark `unchecked`, `after_restart` false. Record sizes and counts.
  3. The time zone trick, for daylight without waiting a day: if the place's local time is outside 10:00 to 14:00, the take is now `daylight`. Set the place's time zone to one where it is between 10:00 and 13:30 now. Within 5 minutes the picture is replaced: the same count, a new id, reason `daylight`. Put the time zone back. If the local time was inside the window, do it the other way round: confirm no round started, then deploy again in a zone where it is night and watch one start.
  4. Change one zone's corner in Frigate's editor. Within about 15 minutes (the poster's 5 and the take's 10) a picture with reason `setup` is stored. Put the corner back; that stores another. Record both.
  5. Restart the control app in the middle of a wait (`sudo systemctl restart tm-control.service` 3 minutes after a mounting save). The take is still listed, and its picture arrives at its own 10 minutes.
  6. Reboot in the middle of a wait. After the start the take is gone and no picture comes. The journal has the taker's sweep line with a count of 1.
  7. After that reboot, change a zone's corner again: the picture has `after_restart` true. Change it back: the next hasn't.
  8. Turn the switch off during a wait: the take is gone, the pictures stay, and none arrives. Turn it on: takes with reason `opted_in`. Turn it off with the box ticked: the pictures and their directories are gone.
  9. The Status page's check reads `ok` with the count. In both journals since the deploy, and in **Download diagnostics**: count lines that hold a 16-hex picture id outside an access-log path, a camera's key next to "picture", or a coordinate. Expect 0.
  10. **Optional, the maintainer's, and it needs his consent first, each time, for a bench test only.** It turns Frigate's detection on once, on one camera, and off again. Before asking, say that count.
      1. With his consent, switch detection on for the camera on the Cameras page. Snapshots and recording stay off.
      2. Start a take (a mounting save) and, at its 10 minutes, he stands in the camera's view for a minute. Expected: `waiting` shows `person`, and no picture is stored.
      3. He leaves. At the next try, 5 minutes on, a picture is stored with mark `clear`. A session reads the two list answers only.
      4. Switch detection off. Confirm `detect.enabled` is false for the camera in Frigate's `/api/config`, read with `X-Cache-Bypass: 1`. Record the consent, the one turn-on, and the confirmation in the `tmdev check`.
  11. **Manual, the maintainer's:** the review box and the place's switch on a phone, on the unit's hotspot; and his look at one automatic picture.
  12. Leave the unit as it was: the test places' pictures deleted, the zone as it was, the place's time zone as it was.
- [ ] **Step 2: Every off-device check once more** on the final branch; `git grep` the branch and its messages for anything that must stay out of public text.
- [ ] **Step 3: The PR's text,** the template filled in, "Closes" this PR's issue and "Part of #371".
  - Title: `data-pack PR 3b: Take reference pictures on the device's own, at a place that keeps them`.
  - First body line: `Series: data-pack PR 3b of 5 · stacked on dev · next: PR 4, stored pictures in the database download · map: #371`.
  - The release note: "The device can now take reference pictures itself. Tick **Keep reference pictures at this place** when you deploy, and about 10 minutes later, and after a camera's mounting or its setup in Frigate changes, the device takes a picture of each camera's view and keeps it under that place. If Frigate is tracking a person it waits and tries again, and a picture taken outside the middle of the day is taken once more in daylight. A place you haven't ticked stores nothing. After a shutdown the device takes no picture it was waiting for and replaces none, because it can't tell whether it was moved. The people check needs Frigate's detection to be on; without it every picture is marked as unchecked."
  - Also: the Docs list; the screenshots; the Pi plan's results, with item 10 marked as done with the maintainer's consent and detection confirmed off, or as not run; the limits (the ceiling was tested off the device only; a release that changes a camera fact takes one picture per camera); and the AI-assistance section.
  - The maintainer reads the commit messages and the PR text before any push.

## Later

- **PR 4** puts stored pictures in the database archive: `PictureReview.vue` extended to many pictures with a tick each, `Pictures.shot` for the handover folder, and the Sharing card's count becoming its tick box.
- **Why a picture was taken, in the data file.** A zip doesn't say whether a picture was automatic, taken in daylight, or after a restart. It would be `format_version` 3.
- **A daylight replacement forgets its first reason.** The row says `daylight`, not `deployed`. A second column would keep both.
- **A camera turned on by a hand edit of `config.yml`** gets no take: only the Cameras page's write is seen.
- **A corrected heading, or a mounting "measured better", leaves a stored picture's pose as it was taken.** The data file is a record of the take.
- **A give-up is forgotten at a reboot,** with every other waiting take.
- **A Status check that says how many places hold pictures the device is no longer at,** so that old pictures aren't forgotten.

