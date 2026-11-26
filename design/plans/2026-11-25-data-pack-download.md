# Download your data, on the Sharing page

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Series:** `data-pack`, four planned. This plan is PR 1. PR 2 = a people check for the reference picture, PR 3 = reference pictures the device takes and keeps, PR 4 = those pictures in the download.

**Goal:** The Sharing page starts with a **Download your data** card for admins: the database's size, a box to include each place's exact location, and one Download button that asks first. The Location page's "Download the database with exact locations" button moves there.

**Architecture:**
- The card adds no new way to make a file. Both downloads are the ones the device has: Node-RED's `/storefiles` download of the whole database, and the copy with exact locations that `POST /surveys/database-copy` starts. The card is a new front for them.
- The size is Node-RED's to read, because the control app never opens the database. Node-RED's internal status gains one field, and `GET /sharing` passes it on to admins with a count of the places that have an exact location.
- One new route, `POST /sharing/download`, makes the one-time link for the plain download. The download with exact locations keeps its route and its code.
- The Dashboard's Data export page is not changed. It and the card both offer the plain download; that duplication is accepted.

**Tech Stack:** Node-RED 5.0.10 function nodes (JavaScript in `flows.json`), Python (FastAPI, pydantic 2; no new dependency), Vue 3 + Vuetify 3 + TypeScript (Vitest, jsdom; no new package), pytest with the function-node harness in `script/tests/test_node_red_flows.py`, the device tests in `script/devpi/tests`, Material for MkDocs.

**Spec:** "What it must do" below. The design it comes from is not published.

**Repo:** `glossyio/traffic-monitor`, on `feature/data-pack-download/<issue>` off `dev`. `<issue>` is this PR's own issue, a sub-issue of #371. All paths below are relative to the repo root.

**Status:** written 2026-11-25 against `dev` at `f0c360a4` (#369 merged). No public PR is open. Three pieces of work are near this one, and none is merged:
- **mounting PR 3, the form** (built, waiting for review): it edits `LocationPage.vue` (the header comment and the place panels, not the "Exact locations" section), `location-page.spec.ts`, `docs/use/location.md`, the UI's README, `docs/development/tm-control.md`, and `CLAUDE.md`. Task 4 here takes one section out of the same page and one `describe` out of the same spec. Whichever merges second rebases, and Task 4 starts by reading both files as they are then.
- **setup-history PR 2, the upload** (built, waiting for its bench items): it edits `flows.json` (the upload gate), `modules/sharing/examples.ts`, and one line of `docs/use/sharing.md`.
- **place-timezone PR 1, the records** (in progress): it edits `flows.json`, `fake.py`, `modules/location/places.py`, and `modules/location/router.py`.
- `flows.json` is edited by all three and by this plan, so they merge one at a time. This plan changes two nodes. After another one merges, redo those two edits on the new file; don't resolve the text conflict by hand.
- This plan adds no migration, to tmdb or to `state.sqlite`.

**Size** (estimates): about 35 files, +750 to 950 and −250 lines, a little over half of it tests and docs. To maintain afterwards: one more field in Node-RED's status; one more API route; one card component; and the database's `files` name written in two places (the flows and the control app), with a test that compares them.

**Decisions.** The maintainer's are marked. The rest are calls made while writing this, open to change.

1. **Download your data is the first thing on the Sharing page, above Saved settings, for admins only (maintainer).** The downloads are admin-only at nginx already.
2. **The Location page's database button and its question go; Export exact locations stays (maintainer).** The CSV is a list of places, so it belongs with the places.
3. **The Dashboard's Data export page doesn't change (maintainer).**
4. **Two requests behind one button.** Unticked, the card asks the new `POST /sharing/download`. Ticked, it asks today's `POST /surveys/database-copy`, which is not touched. The other way, one route that takes the box as a field, would move that route, its nine backend tests, its device tests, and its docs now (roughly 250 lines moved, none new), for nothing the card needs. PR 4 is where one route earns its place, because the pictures and the exact locations then share one ticket.
5. **The card's facts ride on `GET /sharing`,** as `download`, which is `null` for a viewer. The page already makes that request, and the route already reads Node-RED's status for the server's state.
6. **The status field is `database_bytes`,** the size of the main database file as the Dashboard's page reads it. It doesn't count the write-ahead log beside it, so it can be a little under what the download holds.
7. **The plain route asks Node-RED for its status before it makes a link.** With Node-RED stopped, the admin gets a message on the card instead of nginx's error page after the browser has left.
8. **Once a download has started, Download and the box stay off until the page is reloaded.** This is the Location page's rule for the copy with exact locations, now for both: the device makes a full copy of the database for each download.
9. **A plain download started here writes an audit row, `sharing.download`, with no detail.** The Dashboard's download writes none; that isn't changed.
10. **The count of places is read from the places store as it is,** without the reconcile `GET /surveys` runs. The home page's status report runs that reconcile, and the copy's own route runs it again before it reads the list.
11. **The old docs heading stays on the Location docs page as a two-sentence pointer,** so links to its anchor still land on something useful.
12. **The words in item 9 of "What it must do" were a draft for the maintainer to edit** before the card was built (Task 3, Step 1). The maintainer approved them as written on 2026-11-25.
13. **Plate Recognizer is shelved and is the exception here:** the question says nothing about plate numbers, and the docs' warning about sharing a database from a device that had the add-on stands as it is.

## What it must do

1. **The card.** On the Sharing page, above **Saved settings**, for an admin: a card titled **Download your data** with the database's size, a box **Include each place's exact location** (unticked whenever the page opens), and one **Download** button. A viewer sees no card.
2. **The size.** Node-RED's `GET /tm-internal/status` answers `database_bytes`: the size in bytes of the file `TM_DATABASE_PATH_TMDB` names, a whole number from 0 up, or `null` when it can't be read. `GET /sharing` gives an admin `download.database_bytes`, `null` when Node-RED didn't answer or gave anything but such a number. The card shows no size line for `null`.
3. **The box.** `GET /sharing` gives an admin `download.exact_places`: how many places marked in use or used have both coordinates. At 0 the box is off, with the reason under it.
4. **The question.** Download opens a question that says what the file holds and what it doesn't. Nothing is asked of the device until it is confirmed. With the box ticked it carries the warning the Location page shows today, word for word.
5. **The plain download.** `POST /api/v1/sharing/download` (admins) answers `{"url": "/storefiles?files=/db/tmdb.sqlite&tm_token=<token>"}`: a one-time link made with `DownloadGrants.issue`, as `POST /auth/download-link` makes one. `/db/tmdb.sqlite` is the name the Dashboard's download sends and "Validate filenames, setup tar" takes for the whole database.
6. **The download with exact locations.** `POST /api/v1/surveys/database-copy`, as today.
7. **Starting it.** The page opens the answered link with `openDownload`, the navigation Android's sign-in window follows. Then a note says the device is making the copy, and Download and the box stay off until the page is reloaded. A refusal shows the API's message on the card, opens nothing, and can be tried again.
8. **The Location page.** The button "Download the database with exact locations", its question, and its note go. **Export exact locations** stays as it is. The section's paragraph and the Precision paragraph each point to the Sharing page with a link.
9. **The words** (a draft until the maintainer approved them as written on 2026-11-25, Decision 12).
   - Card title: **Download your data**. Under it: "Save a copy of this device's database on the computer or phone you're using. Nothing is uploaded."
   - The size's label: "Database size". Its value: under 1 MB, "less than 1 MB"; else megabytes as a whole number while that number is under 1000 ("700 MB"); else gigabytes with one decimal ("1.4 GB"). Both count in powers of 1024, as the Device page counts storage.
   - Under the box, when it can be ticked: "Without it, the file holds each place's location rounded, as the database stores it."
   - Under the box, when it can't: "No place this device has been at has an exact location yet."
   - The question, box unticked. Title: "Download the database?" Three paragraphs:
     1. "The file holds everything in this device's database: the events, radar readings, and air quality readings it recorded, its deployments, its watch log and setup history, and any comments."
     2. "Each place's location is in it as the database stores it, rounded. The file holds no exact location, no pictures or video, and no passwords or tokens."
     3. "The device makes a copy first, so the download can take a few minutes to start."
   - The question, box ticked. Title: "Download the database with exact locations?" Four paragraphs: the first above; then "This copy of the database includes the exact location of each place the device has been at. The database on this device keeps its rounded locations. Give the copy only to someone who should know where the device was."; then "The file holds no pictures or video, and no passwords or tokens."; then the third above.
   - The question's buttons: **Cancel** and **Download**.
   - The note after a start: "The device is making a copy of the database. The download starts by itself when the copy is ready, which can take a few minutes for a large database. The file's name ends in tmdb.tar.gz." With the box ticked, the name is tmdb-exact-locations.tar.gz.
   - The Location page's "Exact locations" paragraph: "The database keeps a rounded location. You can save each place's exact one as a list here. To download the database with the exact locations in it, go to Sharing." The Precision paragraph's last sentence: "To give someone a copy of the database with each place's exact location, for analysis and mapping, tick Include each place's exact location under Download your data on the Sharing page." In each, "Sharing" or "the Sharing page" is a link to `/sharing`.
   - An exact-locations link that has run out answers: "This download link has expired. Start the download again from the Sharing page."
10. **What doesn't change:** the Dashboard's Data export page and its nodes; both archives, their names, and their contents; `POST /surveys/database-copy`; `GET /surveys/export`.

## Where the code stands that this plan touches

Read at `dev` `f0c360a4`.

- **Flows.**
  - "tm-internal: build status" (`a88895e60521585e`, tab `init-config`, group `d9d94c0d493873b9`) builds the status body: `status`, `tm_version`, `uptime_seconds`, `config`, `schema_version`, `radars`, `deployment`, `upload`, `setup`.
  - "get db size in MB" (`134adeb5116e8cea`, tab `ui-database`) is the Dashboard's read: `global.get("fs").statSync(<TM_DATABASE_PATH_TMDB>).size`.
  - "Validate filenames, setup tar" (`2398aa8b9ca25816`) takes `files == "/db/tmdb.sqlite"` as the whole database, and answers an unknown `tmdb-exact-<ticket>` with a 404 whose text ends "from the Location page."
  - `container/node-red-tm/node-red-tm.env.j2` sets `TM_DATABASE_PATH_TMDB=/db/tmdb.sqlite`.
- **Flows tests** (`script/tests/test_node_red_flows.py`): `status_step()`, `run_functions(steps, env=, context=, flow=, modules=)` (`modules=("fs",)` gives a function node Node's `fs`), `test_status_answers_before_the_first_config_load`, `EXPIRY_TEXT`, `test_validate_refuses_an_unknown_or_expired_ticket`. The file already imports from `tm_control`.
- **The control app** (`tm-control/backend/tm_control/`).
  - `modules/sharing/router.py`: `SharingState`; `_server(app_state)` reads `nodered.report()` and keeps only the upload's state; `_state(app_state, user, server)`; `get_sharing` and `save_sharing` both end in `_state`.
  - `modules/location/router.py`: `database_copy` builds its list with `place.status in ("in_use", "used") and place.lat is not None and place.lon is not None`; `NODERED_MESSAGES` holds the words for a Node-RED that didn't answer or refused.
  - `modules/location/places.py`: `Places.list()`. `list` is a method of the class, so a later method's `list[...]` annotation fails before Python 3.14; the module's `_HeadingList` alias is the pattern.
  - `core/auth.py`: `DownloadGrants.issue(user, address, files, now) -> str`, `DOWNLOAD_PATH`, `DOWNLOAD_TOKEN`. `modules/auth/deps.py`: `client_ip`, `require_admin`.
  - `fake.py`: `FakeNodeRed.report()`, with `SCHEMA_VERSION` as the model for a fixed fact.
  - `tests/fixtures/nodered_status.json` is the status body the app checks' tests read.
- **Backend tests:** `test_api_sharing.py` (`admin`, `viewer_login`, `JSON_HEADERS`), `test_api_surveys.py` (`locate_in_use`, `used_place`, `audit_rows`, `test_database_copy_needs_a_located_place` for a unit with no located place), `test_api_auth.py` (`verify`, `other_client`, `test_verify_passes_a_database_copy_link_once_without_a_session`), `test_openapi_document.py` (`test_sharing_paths_are_declared_with_their_answers`).
- **The UI** (`tm-control/ui/`).
  - `src/modules/sharing/SharingPage.vue` renders the alerts, `StatusCard title="Saved settings"`, then the form.
  - `src/components/StatusCard.vue`: `title`, `subtitle`, `items`, and a default slot at the bottom of the card.
  - `src/components/ConfirmDialog.vue`: `title`, `text` (a line break starts a paragraph), `confirm-text`, `confirm-color`.
  - `src/components/download.ts`: `openDownload(url)`.
  - `src/modules/location/LocationPage.vue`: `confirmCopy`, `copying`, `copyError`, `copyStarted`, `hasLocatedPlace`, `downloadCopy`, the second button of the "Exact locations" section, its reason line, its note, and its `ConfirmDialog`.
  - `tests/fake-api.ts`: `SHARING_STATE`, `sharingState()`, `SHARING_ON`. `tests/mount.ts`: `mountApp`, `mountAlone`, `click`, `clickInDialog`, `dialogText`, `button`, `field`. `tests/location-page.spec.ts` has `describe('the database copy')`.
- **Docs.** `docs/use/location.md` has "Download the database with exact locations" and under it "What the copy adds". Links to that anchor are in `docs/ui/database.md`, `docs/use/sharing.md`, `docs/use/wifi-hotspot.md`, `docs/data-and-payloads/data-overview.md`, and `location.md` itself.

## Global Constraints

- **The names and the words are those in "What it must do".** No task picks another, and the words change only by the maintainer's edit.
- **Only two nodes in `flows.json` change:** `a88895e60521585e` and `2398aa8b9ca25816`. No node on the Dashboard's pages is edited. Edit the file programmatically and write it back with `json.dumps(flows, indent=4, ensure_ascii=False)` and no trailing newline.
- **The control app never opens tmdb.** The size comes from Node-RED's status and nowhere else.
- **No link, token, ticket, or coordinate in a log line, an audit row, or an error message.** `sharing.download` has no detail; `survey.database_copy` keeps its count.
- **Python:** CI and the devices run 3.13, where annotations are read when a class is made. Run the backend suite once under Python 3.13 or older before the hand-off.
- **UI work follows `tm-control/ui/README.md`:** conventional Vuetify, the one dark theme, system fonts, 44 px buttons, results beside the form, no toasts, sentence case. Each UI task's implementer loads the `frontend-design` skill and works test-first; the README's rules win over the skill's taste. New design notes go in the README.
- The API files (`tm-control/ui/src/api/openapi.json`, `schema.d.ts`) are regenerated in the same commit as any model change.
- No coordinate in any fixture, commit, PR text, or screenshot other than the docs' example `45.52252, -122.69120` and the fixtures' `45.0, -122.0`.
- Plate Recognizer is shelved: no change, pin, or bench item for it.
- Every commit ends with the trailer block from the repo's `CLAUDE.md` (Assisted-by / AI-Model / AI-Effort / AI-Role); never `Co-Authored-By`. Docs follow "Writing docs" in `docs/development/contributing.md`; `mkdocs build --strict` passes. Nothing public names a device, a bench site, a partner, or a tool.
- The PR's title starts `data-pack PR 1: `, and its first body line is the `Series:` line.
- On a dev Pi: Frigate's detection, snapshots, and recording stay off. No item in this plan needs them.
- Off-device checks before each commit, from the repo root in the dev venv: `python -m pytest container/node-red-tm/schema/tests script/tests tm-control/backend/tests`; for UI tasks also the pinned Node image's `npm ci && npm run build && npm test`; for docs tasks `~/.venvs/tm-docs/bin/mkdocs build --strict`.

## Review Focus

1. **Node-RED is stopped or restarting.** At page load the card has no size line and everything else works. At Download, unticked: a 502 with "The download wasn't started." on the card, no link made, and the browser stays on the page. Tests in Task 2 (`test_the_size_is_none_when_node_red_does_not_answer`, `test_download_makes_no_link_when_node_red_does_not_answer`) and Task 3 (`shows no size when the device has none`, `shows the API's message and opens nothing when the download can't start`).
2. **A status body without the field, or with a wrong one.** During an update the new control app can meet the old flows; a string, a negative number, a fraction, or `true` must read as no size, never as an error. Tests in Task 1 (`test_status_answers_without_the_database_size`) and Task 2 (`test_database_bytes_reads_only_a_whole_number`).
3. **No place with an exact location, or the last one deleted after the page loaded.** The box is off with its reason; a box ticked on a stale page gets the route's 409, shown on the card, with nothing opened. Tests in Task 2 (`test_an_admin_gets_the_size_and_the_count`) and Task 3 (`turns the box off and says why when no place has an exact location`, `shows the API's message and opens nothing when the download can't start`, which runs for both routes).
4. **A second press.** Cancel sends nothing; after a start neither Download nor the box can be used, so a second full copy of the database isn't started by mistake. Tests in Task 3 (`sends nothing when the question is cancelled`, `keeps Download and the box off after a download has started`).
5. **The page reads its state again while the card is in use** (the Sharing page polls for a minute after a save, and reloads after "I've reviewed this"). The tick and the note stay as they were. Test in Task 3 (`keeps the tick when the page reads the state again`).

A viewer is covered by each task's own tests: `download` is `null`, the route answers 403 and makes no link, and the page shows no card.

---

### Task 1: Node-RED reports the database's size

**Files:**
- Modify: `container/node-red-tm/data/flows.json` (nodes `a88895e60521585e` and `2398aa8b9ca25816`), `tm-control/backend/tests/fixtures/nodered_status.json`
- Test: `script/tests/test_node_red_flows.py`

**Interfaces:**
- Produces: the status body's `database_bytes`, after `schema_version`: `fs.statSync(env.get("TM_DATABASE_PATH_TMDB")).size` when that is a whole number from 0 up, else `null`. The read sits in a `try`, takes `fs` from `global.get("fs")`, and logs nothing: no file, no `fs`, and no path all give `null`, and the status still answers.
- Produces: the validator's 404 text of item 9.

- [ ] **Step 1: Write the failing tests.**
  - `test_status_reports_the_database_size(tmp_path)`: a file of 5000 bytes, `env={"TM_DATABASE_PATH_TMDB": <its path>}`, `modules=("fs",)`: `body["database_bytes"] == 5000`.
  - `test_status_answers_without_the_database_size(env, modules)`, for no variable with `fs`, a path that doesn't exist with `fs`, and a real file without `fs`: `body["status"] == "ok"`, `body["database_bytes"] is None`, and the step logged nothing.
  - `test_status_answers_before_the_first_config_load` also expects `body["database_bytes"] is None`.
  - `EXPIRY_TEXT` becomes item 9's text.
- [ ] **Step 2: Run** `python -m pytest script/tests/test_node_red_flows.py -k "status or expired"`. The new and changed ones fail.
- [ ] **Step 3: Edit the two nodes.** In the builder, a comment says the size is read as the Dashboard's database page reads it. The fixture gains `"database_bytes": 734003200` after `schema_version`.
- [ ] **Step 4: Run** `python -m pytest script/tests tm-control/backend/tests`. PASS.
- [ ] **Step 5: Commit** ("Report the database's size in Node-RED's status").

### Task 2: The control app's facts and the plain download's link

**Files:**
- Create: `tm-control/backend/tm_control/modules/sharing/download.py`, `tm-control/backend/tests/test_api_sharing_download.py`
- Modify: `tm-control/backend/tm_control/modules/sharing/router.py`, `tm-control/backend/tm_control/modules/location/places.py`, `tm-control/backend/tm_control/modules/location/router.py` (`database_copy` reads `Places.located()`; nothing else), `tm-control/backend/tm_control/fake.py`, `tm-control/ui/src/api/openapi.json`, `tm-control/ui/src/api/schema.d.ts`, `tm-control/ui/tests/fake-api.ts` (`SHARING_STATE` gains `download: null`)
- Test: `tm-control/backend/tests/test_places.py`, `test_fake_nodered.py`, `test_openapi_document.py`, `script/tests/test_node_red_flows.py`

**Interfaces:**
- Consumes: Task 1's `database_bytes`.
- Produces, `places.py`: `Places.located(self) -> _SurveyList` (`_SurveyList = list[Survey]`, a module-level alias): the places whose status is `in_use` or `used` and that have both coordinates, in list order.
- Produces, `download.py`:
  - `DATABASE_FILES = "/db/tmdb.sqlite"`
  - `class DownloadFacts(BaseModel)`: `database_bytes: int | None`, `exact_places: int`
  - `database_bytes(report: dict | None) -> int | None`: the report's `database_bytes` when it is an `int`, not a `bool`, and not below 0; else `None`.
  - `facts(app_state, report: dict | None) -> DownloadFacts`
  - `link(app_state, admin: User, address: str) -> str`: calls `app_state.nodered.report()`, and on a `NodeRedError` raises `ApiError(502, "nodered_error", "The download wasn't started. " + <the location router's NODERED_MESSAGES for the error's code, or "Node-RED answered an error.">)`. Otherwise issues a grant for `DATABASE_FILES` and returns `f"{DOWNLOAD_PATH}?files={DATABASE_FILES}&{DOWNLOAD_TOKEN}={token}"`.
- Produces, `router.py`:
  - `SharingState.download: DownloadFacts | None`, `None` for a viewer.
  - `_server` becomes `_report(app_state) -> dict | None`, and `_state(app_state, user, report)` works out the server's state and, for an admin, `facts`.
  - `class DownloadOut(BaseModel)`: `url: str`
  - `POST /sharing/download` → `DownloadOut`, `Depends(require_admin)`: `link(...)`, then an audit row `sharing.download` with no detail, and `Cache-Control: no-store` on the answer.
- Produces, `fake.py`: `FakeNodeRed.DATABASE_BYTES = 734_003_200`, answered as `database_bytes` by `report()`.

- [ ] **Step 1: Write the failing tests.**
  - `test_places.py::test_located_lists_the_places_the_device_has_been_at_with_a_location`: an in-use place with a point, a used one with a point, a used one with none, and a planned one with a point give the first two ids, in list order.
  - `test_fake_nodered.py::test_the_report_has_the_database_size`.
  - `test_node_red_flows.py::test_the_control_app_names_the_database_as_the_download_flow_does`: `f'files == "{DATABASE_FILES}"'` is in the validator's `func`, and `node-red-tm.env.j2` has the line `TM_DATABASE_PATH_TMDB={DATABASE_FILES}`.
  - `test_openapi_document.py`: `("/api/v1/sharing/download", "post"): "200"` joins the Sharing paths.
  - In `test_api_sharing_download.py`:
    - `test_a_viewer_gets_no_download_facts`: `download` is `None`.
    - `test_an_admin_gets_the_size_and_the_count`: with the place in use located and a used place with no location, `download == {"database_bytes": FakeNodeRed.DATABASE_BYTES, "exact_places": 1}`; on a unit arranged as `test_database_copy_needs_a_located_place` arranges it, `exact_places == 0`. The `PUT`'s answer carries `download` too.
    - `test_the_size_is_none_when_node_red_does_not_answer`: `report` raises `NodeRedError("unreachable")`: 200, `database_bytes` is `None`, `exact_places` is still counted, and `server.state == "unknown"`.
    - `test_database_bytes_reads_only_a_whole_number(report, expected)`: `{"database_bytes": 5}` → 5 and `0` → 0; `-1`, `True`, `1.5`, `"5"`, `None`, a missing key, a report of `None`, and a report that is a list → `None`. The fixture file's body gives its own number.
    - `test_download_is_admin_only`: 401 with no session, 403 for a viewer; no grant and no audit row either time.
    - `test_download_answers_a_one_time_link_to_the_database`: 200, `cache-control: no-store`, the URL matches `^/storefiles\?files=/db/tmdb\.sqlite&tm_token=[A-Za-z0-9_-]+$`, one grant more, and the audit row `("sharing.download", None)`.
    - `test_the_link_passes_verify_once_without_a_session`: on the model of `test_verify_passes_a_database_copy_link_once_without_a_session`: 200, then 401.
    - `test_download_makes_no_link_when_node_red_does_not_answer`: 502 `nodered_error`, the message starts "The download wasn't started.", no grant, no audit row.
    - `test_no_token_reaches_a_log_line_or_an_audit_row`: with `caplog`, the link's token is in neither.
- [ ] **Step 2: Run them.** They fail.
- [ ] **Step 3: Write `download.py`, the router's changes, `Places.located`, and the fake's field;** `database_copy` takes its list from `located()`.
- [ ] **Step 4: Regenerate the API files** (the UI README's two commands), add `download: null` to `SHARING_STATE`, and run the UI's build and tests in the pinned Node image. PASS, with no component changed.
- [ ] **Step 5: Run** `python -m pytest tm-control/backend/tests script/tests`, and the backend suite once more under Python 3.13 or older. PASS.
- [ ] **Step 6: Commit** ("Add the database's size and a download link to the Sharing API").

### Task 3: The card

**Files:**
- Create: `tm-control/ui/src/modules/sharing/DownloadCard.vue`, `tm-control/ui/src/modules/sharing/size.ts`, `tm-control/ui/tests/download-card.spec.ts`, `tm-control/ui/tests/size.spec.ts`
- Modify: `tm-control/ui/src/modules/sharing/SharingPage.vue`, `tm-control/ui/src/components/download.ts` (its comments name the card), `tm-control/ui/tests/fake-api.ts`, `tm-control/ui/tests/sharing-page.spec.ts`, `tm-control/ui/README.md`

**Interfaces:**
- Consumes: Task 2's `SharingState.download`, `POST /api/v1/sharing/download`; today's `POST /api/v1/surveys/database-copy`; `openDownload`.
- Produces, `size.ts`: `sizeWords(bytes: number): string`, by item 9's rule.
- Produces, `DownloadCard.vue`: one prop, `facts: DownloadFacts`. It is a `StatusCard` (title and subtitle from item 9; the size as its one item, or no item) with the box, the line under it, the button, the error, and the note in its slot, and a `ConfirmDialog` with `confirm-color="primary"`. The tick, the error, and "started" are the card's own state, so a new `facts` changes none of them.
- Produces, `SharingPage.vue`: `<DownloadCard v-if="session.isAdmin && state.download" :facts="state.download" />` between the alerts and the Saved settings card.
- Produces, `fake-api.ts`: `DOWNLOAD_FACTS = { database_bytes: 734003200, exact_places: 2 }`.

- [ ] **Step 1: Show the maintainer item 9's words and the design note, and stop.** The note, for the UI README's Sharing section: where the card sits and why it is a `StatusCard`; that the question is `ConfirmDialog` with a primary button, because a download changes nothing; why Download stays off after a start; that in fake mode the link leads nowhere. Take his edits into item 9 before any test is written.
- [ ] **Step 2: Write the failing tests.**
  - `size.spec.ts`: `sizeWords` gives "less than 1 MB" for 0 and 1 048 575; "1 MB" for 1 048 576; "700 MB" for 734 003 200; "999 MB" for 1 047 527 424; "1.0 GB" for 1 048 576 000; "1.4 GB" for 1 503 238 554; "3.0 GB" for 3 221 225 472.
  - `download-card.spec.ts`, the card mounted with `mountAlone` and the API answered by `signedIn(ADMIN, …)`:
    - `shows the database's size`
    - `shows no size when the device has none`
    - `starts with the box unticked`
    - `turns the box off and says why when no place has an exact location`
    - `asks before a download and says what the file holds`: the title and the three paragraphs; no request yet.
    - `sends nothing when the question is cancelled`
    - `asks the Sharing API for a plain download and opens its link`: one `POST /api/v1/sharing/download`, none to `/surveys/database-copy`, `openDownload` called once with the answered URL, and the note names tmdb.tar.gz.
    - `shows the warning when the box is ticked`: the second title and the four paragraphs.
    - `asks the Location API for a download with exact locations`: the reverse of the plain one, and the note names tmdb-exact-locations.tar.gz.
    - `keeps Download and the box off after a download has started`
    - `shows the API's message and opens nothing when the download can't start`, for a 502 from the plain route and a 409 from the other; Download can be pressed again.
    - `clears an earlier message when the admin tries again`
  - `sharing-page.spec.ts`:
    - `shows an admin the download card above the saved settings`
    - `shows a viewer no download card`
    - `keeps the tick when the page reads the state again`: with `review_needed`, tick the box, choose "I've reviewed this", and the box is still ticked.
- [ ] **Step 3: Run them.** They fail.
- [ ] **Step 4: Write `size.ts`, the card, and the page's line.**
- [ ] **Step 5: Run** the UI's build and tests in the pinned Node image. PASS.
- [ ] **Step 6: Screenshots in fake mode** at 375 px and 1280 px: the card, the box off with its reason, both questions, and the note. Retake `docs/assets/images/sharing-page.png` at the width the old one has.
- [ ] **Step 7: Commit** ("Add Download your data to the Sharing page").

### Task 4: The Location page points to Sharing

**Files:**
- Modify: `tm-control/ui/src/modules/location/LocationPage.vue`, `tm-control/ui/tests/location-page.spec.ts`, `tm-control/ui/README.md` (the notes on the database copy's button)

**Interfaces:**
- Produces: the page without `confirmCopy`, `copying`, `copyError`, `copyStarted`, `hasLocatedPlace`, `downloadCopy`, the second button, its reason line, its note, its `ConfirmDialog`, and the `openDownload` import. The two paragraphs of item 9, each with a `router-link` to `/sharing`. The header comment says where the download went.

- [ ] **Step 1: Read `LocationPage.vue` and `location-page.spec.ts` as they are on the branch's base,** since mounting PR 3 may have merged.
- [ ] **Step 2: Write the failing tests.** `describe('the database copy')` goes, and these replace it:
  - `has no database download`: no button named "Download the database with exact locations", and, on a unit with no located place, no line "No place this device has been at has an exact location yet."
  - `points to the Sharing page for the database`: the section's paragraph and the Precision paragraph each hold a link whose `href` is `/sharing`.
  - `keeps Export exact locations as it was` stays, without its `openDownload` spy.
- [ ] **Step 3: Run them.** They fail.
- [ ] **Step 4: Make the change,** and bring the README's notes on the button into line: what moved, and that its design notes now describe the card.
- [ ] **Step 5: Run** the UI's build and tests. PASS.
- [ ] **Step 6: Commit** ("Move the database download from the Location page to Sharing").

### Task 5: Docs, device tests, and the plan's public copy

**Files:**
- Modify: `docs/use/sharing.md`, `docs/use/location.md`, `docs/ui/database.md`, `docs/use/wifi-hotspot.md`, `docs/use/device-health.md`, `docs/data-and-payloads/data-overview.md`, `docs/development/tm-control.md`, `CLAUDE.md`
- Modify: `script/devpi/tests/test_web.py`
- Create: `design/plans/2026-11-25-data-pack-download.md`

- [ ] **Step 1: The device tests.**
  - `test_tm_internal_status_has_the_database_size(host, expect)`, on `pii_free` units only, as `test_tm_internal_needs_the_token_on_the_pi` is: only the number is kept from the body; it is an `int`, not a `bool`, and above 0.
  - `test_the_sharing_download_is_for_admins(address, admin_session, viewer_session)`: a viewer's `GET /sharing` has `download` null and their `POST /sharing/download` is `(403, ADMIN_ONLY)`; the admin's `GET` has a whole `exact_places` from 0 up and a `database_bytes` above 0; the admin's `POST` answers 200 with a URL that starts `/storefiles?files=/db/tmdb.sqlite&tm_token=`, held as `Redacted`.
  - `test_a_sharing_download_link_works_once_without_the_cookie(host, address, admin_session)`, on the model of `test_a_download_link_works_once_without_the_cookie`.
- [ ] **Step 2: `docs/use/sharing.md`.**
  - The page's description and first paragraph also say the page is where an admin downloads the data.
  - A new first section, "Download your data": what the card shows, that only an administrator sees it, the question, the wait and the free space it needs (a link to `../ui/database.md#download-the-database`), what the browser shows when the device can't make the copy and how to get back, that Download stays off until the page is reloaded, both file names, and the link to Phones.
  - Under it, "Include each place's exact location": when the box is off, what the warning says, and who the file is for.
  - Under that, "What the copy adds", moved from `location.md` as it is, with its links fixed.
  - The box "The exact location is for you to give or keep" names the card's box and the Location page's export.
- [ ] **Step 3: The other pages.**
  - `location.md`: "Download the database with exact locations" keeps its heading and becomes two sentences that say it moved and link to the new section. "What the copy adds" is gone from here. The description, "The Location page" (its list of what the page holds), "Export the exact locations", "Choose the precision", and "What leaves the device" say where the download is now and link to the Sharing docs.
  - `device-health.md`, "What viewers see": a viewer's Sharing page has no download.
  - `database.md`: the sentence about exact locations links to the Sharing docs, and one more says the same download is on the Sharing page.
  - `wifi-hotspot.md`: the Android line names **Download** on the Sharing page, with and without exact locations.
  - `data-overview.md`: "Getting the data" starts with the Sharing page, and the two mentions of the Location page's download name the Sharing page.
  - `tm-control.md`: `database_bytes` in the status; the Sharing module's table (`download` in `GET /sharing`, `POST /sharing/download`) and a line on `download.py`; that the card starts the database copy; that three routes now make download links.
  - `CLAUDE.md`: the Sharing and Location clauses of the `tm-control/` bullet; the download-links bullet; the status fields in "Node-RED's internal status"; "the Location page's database copy" wherever the flows' section says it.
- [ ] **Step 4: The plan's public copy:** this file, as published in `design/plans/`.
- [ ] **Step 5: Run** every off-device check and `mkdocs build --strict`. PASS.
- [ ] **Step 6: Commit** the device tests, then the docs, then the plan's copy.

### Task 6: Pi plan and the PR

- [ ] **Step 1: Pi plan,** as a logged `tmdev check` on a bench unit marked `pii_free`, after `tmdev deploy <host> -- -t node-red-tm -t tm-control -t revproxy`. Frigate's detection stays off throughout; say so in the check.
  1. The device suite passes.
  2. The Sharing page's size and the Dashboard's Data export page's size agree, to the rounding.
  3. Download with the box unticked, from a desktop browser: the archive's name ends `_tmdb.tar.gz`, it holds `tmdb.sqlite` alone, and that file has no table `survey_exact_location`. One `sharing.download` audit row.
  4. Reload, tick the box, Download: the question carries the warning; the name ends `_tmdb-exact-locations.tar.gz`; `survey_exact_location` has as many rows as the card's count of places. One `survey.database_copy` audit row.
  5. After each start, Download and the box are off until the page is reloaded.
  6. `sudo systemctl stop node-red-tm.service`, then reload the Sharing page: no size line. Download, unticked: the message is on the card and the browser stays on the page. Start the service again and see the size come back.
  7. `/storefiles?files=tmdb-exact-` followed by 32 zeros answers 404 with the words "from the Sharing page".
  8. A viewer's Sharing page has no card.
  9. The Location page has no database button, its two links open the Sharing page, and **Export exact locations** still saves its file.
  10. In **Download diagnostics**, every `tm_token=` value and every `tmdb-exact-` ticket from items 3 and 4 is redacted, and the control app's own journal lines hold neither.
  11. **Manual, the maintainer's:** on an Android phone in the sign-in window on the unit's hotspot, both downloads save. The same on an iPhone, in a browser, as the Phones docs say.
- [ ] **Step 2: Every off-device check once more** on the final branch; `git grep` the branch for device names, bench sites, partner names, and any coordinate that isn't allowed.
- [ ] **Step 3: The PR's text,** the template filled in, "Closes" this PR's issue and "Part of #371".
  - Title: `data-pack PR 1: Download your data, on the Sharing page`.
  - First body line: `Series: data-pack PR 1 of 4 · stacked on dev · next: PR 2, a people check for the reference picture · map: #371`.
  - The release note: "The Sharing page now starts with **Download your data**: the database's size, a Download button, and a box to include each place's exact location. A question says what the file holds before the download starts. The Location page's **Download the database with exact locations** button moved there; **Export exact locations** stays on the Location page. The Dashboard's Data export page is unchanged."
  - Also: the Docs list; the screenshots; the Pi plan's results; the limits (the size is the main file's, without the write-ahead log; the Dashboard's download still writes no audit row; two downloads at once behave as before, #328; the card's count of places waits for the next status report on a unit that was just upgraded); and the AI-assistance section.
  - The maintainer reads the commit messages and the PR text before any push.

## Later

- **One route for every download from the card,** when the pictures join the archive (PR 4) and share a ticket with the exact locations. `POST /surveys/database-copy` moves then.
- **One size helper for the UI.** The Detection page, the Device page, and this card each format bytes their own way.
- **An audit row for the Dashboard's database download.**
- **Progress for a large copy.** The device doesn't report any, and the browser's own download bar starts only when the copy is done.
