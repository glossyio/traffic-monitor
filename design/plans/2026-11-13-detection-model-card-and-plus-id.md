# The Detection page: one card for the running model, and a Frigate+ model by its ID

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fold the Detection page's two label lists into the "Model in use" card, move Frigate+ above "Other models on this device", and let an admin paste a Frigate+ model ID that Frigate downloads, checks, and switches to.

**Architecture:**
- PR 1 is UI and docs only. `GET /models` already carries everything; the page stops showing the lists at the top and shows them in the card in use, and the Frigate+ section moves up with its heading outside the panel.
- PR 2 adds `POST /models/plus/{model_id}/use`. For a model that isn't on the device, tm-control sends Frigate the config with `model:` set to only `path: plus://<id>`, through the config API that Use calls. Frigate downloads the model with its own key while it validates that config.
- The download can take minutes, so tm-control waits for Frigate's answer on a background thread and keeps one in-memory record of it. `GET /models` shows the record to admins as `fetch`, the page follows it, and the three use routes are refused while it says `downloading`.

**Tech Stack:** Python 3.11 (FastAPI, pydantic 2, ruamel.yaml; no new dependency), Vue 3 + Vuetify 3 + TypeScript (Vitest, `openapi-fetch`), Material for MkDocs, the dev-Pi tooling (`script/devpi/tmdev.py`).

**Spec:** the design of 2026-11-13, summarised in [issue 313](https://github.com/glossyio/traffic-monitor/issues/313). Its decisions are restated under "Decisions" and "What Frigate 0.18.1 does" below, so this plan stands on its own. Where the plan leaves something out, say so in the PR rather than picking silently.

**Status:** written 2026-11-13 against `dev` at `b4a26f1`, with no open pull requests. PR 1 is `feature/detection-model-card/313` off `dev` (Tasks 1 to 3). PR 2 is `feature/frigate-plus-model-id/313`, stacked on PR 1's branch until that merges (Tasks 4 to 9).

## Global Constraints

- tm-control never contacts Frigate+ and never reads the key to send it anywhere. It calls no Frigate route that exists for Frigate's own picker (`GET /api/plus/models`).
- A `plus://` path for a model that isn't on the device is never written to `config.yml` on disk. The fetch path has no disk fallback.
- tm-control never has two config saves running in Frigate at once.
- Neither label list may be missing from the page in any state: Frigate answering, Frigate down, safe mode, a default with no file on the device, a running model with no entry in the list, an unknown running model, a viewer.
- A viewer changes nothing and sees no key state, no ID form, and no `fetch` record.
- No message, log line, or test fixture holds a real key, model ID, or model record. Tests use `PLACEHOLDER_KEY` from `tests/placeholders.py` and `fake.FAKE_PLUS_ID`.
- UI: conventional Vuetify, as the rest of the page; every tap target at least 44 px; reads at 375 px wide. The UI tasks' implementer loads the frontend-design skill, and the page's design notes in `tm-control/ui/README.md` win over it.
- Docs follow "Writing docs" in `docs/development/contributing.md`; `mkdocs build --strict` passes.
- Commits end with the trailer block from `CLAUDE.md` ("AI use in this repository"), interface `CLI`. The maintainer reviews commit and PR text before any push.
- Tasks marked **tricky** carry the concurrency and the failure handling; they get the most careful implementation and review.

## Decisions

Made by the maintainer on 2026-11-13 unless marked **(call)**, which were chosen while writing the design and are open to change.

1. The detector and the running model stay at the top of the page, unchanged.
2. "Model in use" follows directly. Its card's fold holds the sentence about both lists, the "different list" line when it applies, the recognised list, the tracked list, then the file lines. The lists are plain headed lists, always shown inside the fold, not panels.
3. The recognised list in that fold is the one from `GET /models`' `labels` (Frigate's answer when there is one, with its source line). It replaces the card's own "Objects it recognises" list for the model in use only.
4. The "Tracked but not recognised by the running model" chips sit on the card outside the fold.
5. The section always shows a card. When no entry in `models` is running and the running kind isn't a default, the page makes one: titled with `running.name` when there is one, "Unknown model" otherwise, with no buttons and no file lines. **(call)**
6. Frigate+ is its own section above "Other models on this device". Its `h2` is plain text outside the panel. The key panel's title is "API key" followed by the grey state text: "not set", "set", "set, ending in 0001", each with ", in use" while Frigate runs a Frigate+ model.
7. The Frigate+ section renders whether or not `GET /models` answered, as today. **(call)**
8. A model is fetched by its ID through Frigate's config save. No list of the account's models, and no download by tm-control itself.
9. tm-control waits for the download in the background, up to 10 minutes. **(call for the number)**
10. The ID is 32 lowercase hex characters (the inventory's `PLUS_ID`). `contracts.MODEL_ID` is looser and stays what it is: the rule for a path someone typed into a config. **(call)**
11. `fetch` is shown to admins only, and stays until the next download starts or a Use succeeds. **(call)**
12. While a download runs, the API refuses the three use routes and leaves upload, download, and delete open. The page disables all of its actions, as it does during a Use, because `working` is one flag. **(call)**
13. Accepted gaps: a tm-control restart during a download loses the record, so a save Frigate makes afterwards gets no restart; and Frigate writes the config text it was sent, so an edit saved in Frigate's editor during the download is overwritten. Both go in the developer docs. **(call)**

## What Frigate 0.18.1 does

Read from its source at the `v0.18.1` tag on 2026-11-13 (`frigate/api/app.py`, `frigate/detectors/detector_config.py`, `frigate/plus.py`). The bench in Task 9 bears these out.

- `POST /api/config/save` is a plain `def` handler: it runs on a worker thread, and Frigate answers other requests meanwhile. It parses the body with `FrigateConfig.parse_yaml`, then writes the text it was sent to `config.yml`. It takes no lock. Only `save_option=restart` restarts Frigate.
- A `ValidationError` is a 400 whose message is two header lines and one line per error. Any other exception is a 400 with the same header and a whole traceback. `picker.refusal_lines` reads both.
- Parsing `plus://<id>` downloads the model file if `/config/model_cache/<id>` isn't a file, then the record if `<id>.json` isn't a file. A second try fetches only what's missing.
- The model file comes from one `requests.get` with no timeout and no status check, and is written to its final name in one go. An error answer would be saved as the model file and never fetched again.
- `ValueError("Model does not support detector type of <type>")` is raised after both downloads, so a refused model's files stay in `model_cache`.
- A refused key raises `Exception("Unable to refresh API token: …")`; an unknown ID raises `Exception(<Frigate+'s answer>)`.

## Review Focus

1. An ID pasted with spaces, a newline, or a leading `plus://` should work; anything else should be refused on the page before a request is made. (Task 7)
2. An admin who opens the page while another admin's download runs should see that it's running and be unable to start another. (Tasks 5 and 7)
3. Frigate restarted during a download (a key change, the Status page's Restart) should end the record as failed at once, not after 10 minutes, and release the guard. (Task 4)
4. An unexpected error in the background wait should never leave the record at `downloading`. (Task 4)
5. A running model with no entry in `models` (a `plus://` path typed into `config.yml`, files not on the device) should still get a card with both lists. (Task 1)

---

## PR 1: the layout

### Task 1: The card in use holds the two lists

**Files:**
- Create: `tm-control/ui/src/modules/detection/RunningLists.vue`
- Modify: `tm-control/ui/src/modules/detection/ModelBlock.vue`, `tm-control/ui/src/modules/detection/DetectionPage.vue`
- Test: `tm-control/ui/tests/detection-page.spec.ts`

**Interfaces:**
- Produces, in `RunningLists.vue`: props `{ labels: LabelsOut; listsDiffer: boolean; frigateAnswers: boolean }` (`LabelsOut` is `components['schemas']['LabelsOut']`). It renders, in order: the sentence, the differ line when `listsDiffer`, a `LabelChips` titled `Objects the running model recognises (N)` (no count when `labels.recognised` is null) with the source line above its chips, and a `LabelChips` titled `Objects tracked on this device (N)` or `(N, M not recognised)`.
- Produces, in `ModelBlock.vue`: `Block.kind` becomes `ModelOut['kind'] | null`; a new prop `lists: { labels: LabelsOut; listsDiffer: boolean; frigateAnswers: boolean } | null`, non-null only for the card in use.
- Every string below moves as it is today; none is reworded:
  - "Frigate tracks only the objects that are in both lists."
  - "Frigate reports a different list than this model's .json."
  - the three `SOURCES` lines, "Filled: tracked on this device.", "Amber: the running model doesn't recognise it."
  - "The running model's labels aren't known." and "Frigate isn't answering, and the running model has no sidecar on the device."
  - "Tracked but not recognised by the running model:"

- [ ] **Step 1: Write the failing tests** in `describe('the Detection page', …)`, replacing the tests that open the two top panels. Use the file's helpers (`section`, `item`, `headings`, `running`).

```ts
it('shows the two lists inside the card in use, and nowhere above it', async () => {
  // MODELS: the Frigate+ model runs
  expect(section(wrapper, 'Object detection').findAll('.v-expansion-panel').length).toBe(0)
  expect(section(wrapper, 'Object detection').text()).not.toContain('Frigate tracks only')
  const card = section(wrapper, 'Model in use').find('.model')
  const fold = card.find('.fold')
  expect(fold.find('.v-expansion-panel-title').text()).toBe('Files and objects')
  expect(fold.findAll('h4').map((h) => h.text())).toEqual([
    `Objects the running model recognises (${MODELS.labels.recognised!.length})`,
    expect.stringMatching(/^Objects tracked on this device \(6/),
  ])
  expect(fold.findAll('.v-expansion-panel').length).toBe(1) // the lists are not panels of their own
  expect(fold.text()).toContain('As Frigate reports them.')
  expect(fold.text()).not.toContain('Objects it recognises')
})
it('keeps the tracked-but-not-recognised chips on the card, outside the fold', …)
// the chips' container is in .model and not inside .fold
it('gives a default with no file on the device a fold with the lists and no file lines', …)
// running kind frigate_default, models []: fold title 'Objects', both h4 present
it('makes a card for a running model that has no entry in the list', …)
// running { name: 'abc…', kind: 'local', source: 'config_file' }, no model with running true:
// one .model in the section, h3 text is the name, no buttons outside the fold, both h4 present
it('makes an "Unknown model" card when the running model cannot be read', …)
// running { name: null, kind: null, source: null }: h3 'Unknown model', tracked list shows 'None.'
it("leaves the other models' own lists as they were", …)
// a card under Other models still has 'Objects it recognises (N)' and its "Doesn't recognise" line
```

- [ ] **Step 2: Run them and see them fail**

Run: `(cd tm-control/ui && npx vitest run tests/detection-page.spec.ts)`
Expected: the new tests fail; note which existing tests fail too, because they assert the old panels.

- [ ] **Step 3: Implement.**
  - `RunningLists.vue` as its Interfaces line says. `LabelChips` already renders its title as an `h4` with Copy.
  - `ModelBlock.vue`: the fold exists when `block.model || lists`. With `lists`, the fold shows `RunningLists`, then the file lines when there is a model, and not the model's own list or its `missing` lines; the not-recognised chips go between the facts and the buttons. The fold's title is "Files and objects" with files and lists or labels, "Objects" with lists and no files, "Files" as today otherwise. `isDefault`, `canDelete`, and `mark` treat a null kind as none of the defaults.
  - `DetectionPage.vue`: remove the sentence, the differ line, the two panels, the chips, and `labelsOpen` from the first section. `inUse` never returns null once `state` is set: a running model's entry, else a default's made block, else a made block keyed `#running` (title `running.name ?? 'Unknown model'`, facts "Named in Frigate's config; its files aren't on this device." with a name, "Frigate's model couldn't be read." without, `kind: running.kind`). `blockProps` passes `lists` for the block in use and `canUse: false` for `#running`.
  - Update the comments at the top of the three files.

- [ ] **Step 4: Update the existing tests that asserted the old panels** so each asserts the same fact where it now is (the lists' text inside the card's fold, the alerts still in the first section). Don't delete a test whose fact still holds.

- [ ] **Step 5: Run the UI suite and the build**

Run: `(cd tm-control/ui && npm test && npm run build)`
Expected: all pass, no type errors.

- [ ] **Step 6: Commit** ("Show the running model's lists in its card").

### Task 2: Frigate+ moves above the other models

**Files:**
- Modify: `tm-control/ui/src/modules/detection/DetectionPage.vue`
- Test: `tm-control/ui/tests/detection-page.spec.ts`

**Interfaces:**
- Produces: the section keeps `id="frigate-plus"` (`FRIGATE_PLUS_ID`), which stays the key panel's value. `keyState` returns `'not set'`, `'set'`, or `'set, ending in 0001'`, each with `', in use'` appended while `running.kind === 'frigate_plus'`, and `''` for a viewer or before the secrets answer.

- [ ] **Step 1: Write the failing tests**

```ts
it('orders the sections: detection, model in use, Frigate+, other models', async () => {
  expect(headings(wrapper)).toEqual([
    'Object detection', 'Model in use', 'Frigate+', expect.stringMatching(/^Other models on this device/),
  ])
})
it('puts the Frigate+ heading outside the panel and the key state in the panel title', async () => {
  const plus = wrapper.find('#frigate-plus')
  expect(plus.find('h2').text()).toBe('Frigate+')
  expect(plus.find('h2').element.closest('.v-expansion-panel')).toBeNull()
  expect(panel(wrapper, 'API key').text()).toBe('API key set, ending in 0001, in use') // key set, Frigate+ model runs
})
it('shows a viewer the Frigate+ text and no panel', …)          // #frigate-plus has the two paragraphs, 0 panels
it('keeps the Frigate+ section when the models cannot load', …) // GET /models fails: #frigate-plus exists, key form works
// and the two existing '/detection#frigate-plus' tests still pass: the key panel opens and the page scrolls
```

- [ ] **Step 2: Run them and see them fail** (same command as Task 1).

- [ ] **Step 3: Implement.** Split the `v-if="state"` template in two around the Frigate+ section, so the order holds and the section renders without state. The `h2` is plain, with `class="text-h6 mb-2"` like the others; the two paragraphs follow it for everyone, unchanged; the `v-expansion-panels` is inside `v-if="session.isAdmin"` and its panel's title is `API key` with the grey `keyState` span, as the title is built today. Keep the `h3`-less form (`hide-title`).

- [ ] **Step 4: Run the UI suite and the build** (Task 1, Step 5).

- [ ] **Step 5: Commit** ("Move Frigate+ above the other models").

### Task 3: Docs, screenshots, and the pull request

**Files:**
- Modify: `docs/use/detection.md`, `tm-control/ui/README.md` (the "### Detection" notes and sketch)
- Replace: `docs/assets/images/detection-page-models.png`, `docs/assets/images/detection-page-frigate-plus-key.png`

- [ ] **Step 1: Rewrite the pages for the new layout.** `detection.md`: the order of sections, that the two lists are in the card in use under "Files and objects", that the amber chips show while it's closed, and that the key is under Frigate+, API key. Keep every anchor (`#frigate-plus`, `#use-a-model`, `#upload-a-model`, `#download-a-model`). README: replace the sketch with the layout in this plan's Decisions 1 to 7 and add a short "What changed on 2026-11-13" note saying why (one place for the running model).
- [ ] **Step 2: Take the two screenshots again** from fake mode (`CLAUDE.md`, "Fake mode"), at 375 px wide, as the current ones were: the page from the top with the card in use open, and the Frigate+ section with the key panel open. Look at each before committing: no hostname, no real key.
- [ ] **Step 3: Build the docs.** Run: `~/.venvs/tm-docs/bin/mkdocs build --strict`. Expected: no warnings.
- [ ] **Step 4: Commit** ("Describe the Detection page's new layout").
- [ ] **Step 5: Pi check and PR.** With `tmdev check`, on one dev Pi: deploy with `-t revproxy`, open `/detection` as the admin and as the viewer, and record that the four sections are in order, the card's fold holds both lists, and `/detection#frigate-plus` from the Status page opens the key panel. Then draft the PR into `dev` from the template ("Docs" lists the two pages; "AI assistance" filled in), and give the maintainer the commit list and PR text to review before pushing.

---

## PR 2: a model by its ID

### Task 4: The download's record and the background wait (**tricky**)

**Files:**
- Create: `tm-control/backend/tm_control/modules/detection/fetch.py`
- Modify: `tm-control/backend/tm_control/adapters/frigate.py` (`save_config`), `tm-control/backend/tm_control/modules/detection/picker.py` (make `_edited` public as `edited`)
- Test: `tm-control/backend/tests/test_detection_fetch.py`

**Interfaces:**
- Produces, in `frigate.py`: `save_config(text: str, timeout: float = SAVE_TIMEOUT) -> tuple[int | None, str | None]`.
- Produces, in `picker.py`: `edited(text: str, section: dict | None) -> str` (today's `_edited`, same `UseError`s).
- Produces, in `fetch.py`:

```python
WAIT = 600  # seconds tm-control waits for Frigate's save, which holds the download
State = Literal["downloading", "saved", "refused", "failed"]

@dataclass(frozen=True)
class Fetch:
    model_id: str
    state: State
    message: str | None  # for refused and failed

class Fetches:  # one per app; every method takes one lock
    def current(self) -> Fetch | None: ...
    def downloading(self) -> bool: ...
    def start(self, model_id: str) -> bool: ...  # False, and nothing changes, while one is downloading
    def finish(self, state: State, message: str | None = None) -> None: ...
    def clear(self) -> None: ...  # drops a finished record; leaves a downloading one

def spawn(target: Callable[[], None]) -> None: ...  # a daemon thread; tests replace it with `lambda target: target()`

def wait(fetches: Fetches, text: str, on_saved: Callable[[], None], clock=time.monotonic) -> None: ...
```

- `wait` sends `text` with `frigate.save_config(text, timeout=WAIT)` and always ends in `fetches.finish(...)`:

| Frigate's answer | State | Message |
|---|---|---|
| 200 | `saved`, after `on_saved()` | none |
| no answer, and `frigate.config_raw() == text` | `saved`, after `on_saved()` | none |
| 400 | `refused` | `Frigate refused the model: <refusal_lines(message)>`, or `Frigate refused the model.` with no lines |
| no answer after `WAIT - 5` seconds or more | `failed` | `Frigate didn't finish downloading the model in 10 minutes. Check the device's internet connection, then try again.` |
| no answer sooner | `failed` | `Frigate stopped before the download finished. Try again once Frigate is running.` |
| any other status | `failed` | `Frigate answered <status> to the save.` |
| `save_config`, `config_raw`, or `on_saved` raises | `failed` | `The download couldn't be followed: <exception class name>` |

- [ ] **Step 1: Write the failing tests** in `test_detection_fetch.py`, patching `frigate.save_config` and `frigate.config_raw` with `monkeypatch`:

```python
def test_start_refuses_a_second_download_and_finish_releases_it(): ...
    # start("a"*32) True; start("b"*32) False; current().model_id == "a"*32; finish("saved"); start(...) True
def test_clear_drops_a_finished_record_but_not_a_running_one(): ...
def test_a_200_calls_on_saved_then_records_saved(monkeypatch): ...            # order: on_saved before the state changes
def test_no_answer_with_the_config_saved_counts_as_saved(monkeypatch): ...
def test_a_validation_refusal_is_recorded_with_frigates_lines(monkeypatch): ...
    # message: FRIGATE_HEADER_LINES + "Line 3: model -> path - Value error, Model does not support detector type of edgetpu\n"
    # -> ("refused", "Frigate refused the model: Line 3: model -> path - Value error, Model does not support detector type of edgetpu")
def test_a_traceback_refusal_keeps_its_last_line_and_no_key(monkeypatch): ...
    # a traceback ending f"Exception: Unable to refresh API token: {PLACEHOLDER_KEY}"; PLACEHOLDER_KEY not in message
def test_no_answer_after_the_wait_says_ten_minutes(monkeypatch): ...          # clock returns 0 then 600
def test_no_answer_sooner_says_frigate_stopped(monkeypatch): ...              # clock returns 0 then 12
def test_another_status_is_failed_with_the_status(monkeypatch): ...           # 503
def test_an_error_in_the_wait_never_leaves_it_downloading(monkeypatch): ...   # save_config raises RuntimeError
def test_an_error_in_on_saved_is_failed_too(monkeypatch): ...
def test_save_config_passes_its_timeout(monkeypatch): ...                     # httpjson.post sees timeout=600
```

- [ ] **Step 2: Run them and see them fail.** Run: `python -m pytest tm-control/backend/tests/test_detection_fetch.py -v`. Expected: import error for `fetch`.
- [ ] **Step 3: Implement** `fetch.py`, the `timeout` parameter, and the rename (update `picker`'s own callers and `test_detection_picker.py`).
- [ ] **Step 4: Run** `python -m pytest tm-control/backend/tests -q`. Expected: all pass.
- [ ] **Step 5: Commit** ("Follow a Frigate+ model's download in the background").

### Task 5: The route, the guard, and `fetch` on `GET /models` (**tricky**)

**Files:**
- Modify: `tm-control/backend/tm_control/modules/detection/router.py`, `tm-control/backend/tm_control/fake.py`, the app factory that sets `app.state` (where `app.state.secrets` is set)
- Test: `tm-control/backend/tests/test_api_models.py`

**Interfaces:**
- Consumes: Task 4's `fetch` module, `picker.edited`.
- Produces: `app.state.fetches: Fetches`.
- Produces, in `router.py`:

```python
class FetchOut(BaseModel):
    model_id: str
    state: Literal["downloading", "saved", "refused", "failed"]
    message: str | None

class ModelsState(BaseModel):
    ...
    fetch: FetchOut | None  # the last Frigate+ download, for admins; None for a viewer and when there is none

class PlusUseQueued(BaseModel):
    name: str                                # the model id
    started: Literal["restart", "download"]  # the model was on the device, or Frigate is fetching it
    restarts: list[str]                      # ["frigate.service"] for a restart, [] for a download

@router.post("/plus/{model_id}/use", status_code=202, response_model=PlusUseQueued)
def use_plus_model(model_id: str, request: Request, background: BackgroundTasks, admin: User = Depends(require_admin)): ...
```

- The route's checks, in this order, each an `ApiError`:

| Condition | Status, code | Message |
|---|---|---|
| `model_id` isn't `PLUS_ID` | 422 `bad_id` | `A Frigate+ model ID is 32 characters, each 0-9 or a-f.` |
| a download is running | 409 `downloading` | `Frigate is downloading a model; wait for it to finish.` |
| Frigate starting or stopping | 409 `restarting` | `RESTARTING`, as Use |
| the inventory has `model_id` with `complete` true | | do what `use_model` does for that name (factor its body out as `_use_named`); answer `started="restart"` |
| the key isn't set (`app.state.secrets.is_set(FRIGATE_PLUS_API_KEY)`) | 409 `no_key` | `Set the Frigate+ API key first.` |
| `frigate.config_raw()` is None | 409 `frigate_down` | `Frigate isn't answering, and it has to be running to download a model.` |
| `picker.edited(text, {"path": f"plus://{model_id}"})` raises `UseError` | as Use | as Use (`detector_model`, `config_invalid`) |

  Then `fetches.start(model_id)` (False: the 409 `downloading` again), `fetch.spawn(...)` running `fetch.wait` with an `on_saved` that records the audit row (`models.use`, detail the model id, the admin's id) and calls `restart_or_log(FRIGATE_UNIT)`, and the answer `started="download"`.
- The guard: `use_model` and `_use_default` answer the same 409 `downloading` before anything else. `_use` calls `fetches.clear()` after a use is applied.
- Fake mode: `fake.FAKE_FETCHABLE_ID = "fedcba9876543210fedcba9876543210"` and `fake.fetch_model(settings, model_id) -> str | None`, which writes that id's pair into the fake cache (the fixture sidecar with its `id` and `name` changed) and returns None, or returns `"Frigate refused the model: Exception: Model not found"` for any other id. In fake mode the spawned wait sleeps `fake.FAKE_FETCH_SECONDS = 5`, then finishes `saved` after `fake.use_model`, or `refused` with that message. Nothing is sent anywhere.

- [ ] **Step 1: Write the failing tests** in `test_api_models.py`, beside the Use tests, with their fixtures (`device_client`, `systemctl`, `frigate_api`, `device_with_codedir`, `write_pair`, `use_rows`). A `plus_use(client, model_id)` helper posts to `f"{URL}/plus/{model_id}/use"`. Every device test patches `fetch.spawn` to run inline and sets the key with `device_client.app.state.secrets.entered[FRIGATE_PLUS_API_KEY] = PLACEHOLDER_KEY` unless it tests its absence. `NEW_ID = "f" * 32`.

```python
@pytest.mark.parametrize("bad", ["abc", "F" * 32, "g" * 32, "f" * 33, "plus"])
def test_a_bad_id_is_422_and_reaches_nothing(device_client, login, tmp_path, systemctl, frigate_api, bad): ...
    # (422, "bad_id"); api.posts == []
def test_an_id_on_the_device_is_an_ordinary_use(...): ...
    # write_pair(cache, PLUS_ID, id=PLUS_ID): 202 {"name": PLUS_ID, "started": "restart", "restarts": ["frigate.service"]};
    # saved["model"] == {"path": f"plus://{PLUS_ID}"}; fetch stays None
def test_an_id_on_the_device_is_used_from_the_file_when_frigate_is_down(...): ...   # the disk fallback, short path only
def test_fetching_needs_the_key(...): ...             # (409, "no_key"); api.posts == []
def test_fetching_needs_frigate_and_writes_no_file(...): ...
    # frigate_api(None): (409, "frigate_down"); config.read_text() == PLUS_CONFIG; backups_of(config) == []
def test_a_fetch_saves_through_frigate_then_restarts_it(...): ...
    # 202 {"name": NEW_ID, "started": "download", "restarts": []}; one post, timeout 600,
    # yaml_of(body)["model"] == {"path": f"plus://{NEW_ID}"}; systemctl.restarts() == [FRIGATE_RESTART];
    # use_rows(...) == [NEW_ID]; models_of(client)["fetch"] == {"model_id": NEW_ID, "state": "saved", "message": None}
def test_a_refused_fetch_restarts_nothing_and_says_why(...): ...
    # save=(400, traceback ending "Exception: Unable to refresh API token: " + PLACEHOLDER_KEY):
    # fetch.state == "refused"; PLACEHOLDER_KEY not in the GET's text; restarts == []; use_rows == []
def test_a_fetch_is_refused_when_a_detector_sets_its_own_model(...): ...   # (409, "detector_model"); no post
def test_every_use_is_409_while_a_download_runs(...): ...
    # device_client.app.state.fetches.start(NEW_ID): use(name), the default's use, and plus_use(other id)
    # each (409, "downloading"); api.posts == []
def test_uploads_and_deletes_stay_open_while_a_download_runs(...): ...
def test_a_use_clears_a_finished_fetch(...): ...      # finish("refused", "x"); use(...) 202; fetch is None
def test_fetch_is_null_for_a_viewer(...): ...         # start(NEW_ID); the viewer's GET /models has "fetch": None
def test_use_by_id_is_admin_only(...): ...            # the viewer: 403
def test_fake_mode_fetches_its_one_id_and_refuses_others(seeded, settings, login, monkeypatch): ...
    # FAKE_FETCH_SECONDS 0, spawn inline: FAKE_FETCHABLE_ID -> saved, it runs, both files in fake.model_cache;
    # "a" * 32 -> refused with fake's message, the running model unchanged
```

- [ ] **Step 2: Run them and see them fail.** Run: `python -m pytest tm-control/backend/tests/test_api_models.py -q -k "plus or fetch or download"`.
- [ ] **Step 3: Implement.** Update the module docstring at the top of `router.py` to describe the route.
- [ ] **Step 4: Regenerate the UI's API types**, per `tm-control/ui/README.md`: `dump-openapi` into `src/api/openapi.json`, then `npm run api:generate`. Add `fetch: null` to the `ModelsState` fixtures in `tm-control/ui/tests` so the UI suite still type-checks.
- [ ] **Step 5: Run** `python -m pytest tm-control/backend/tests -q` and `(cd tm-control/ui && npm test && npm run build)`. Expected: all pass.
- [ ] **Step 6: Commit** ("Use a Frigate+ model by its ID").

### Task 6: The Status check points at the page

**Files:**
- Modify: `tm-control/backend/tm_control/modules/apps/contracts.py` (`frigate_plus`, the "key set, no Frigate+ model" warning)
- Test: `tm-control/backend/tests/test_contract_checks.py`

**Interfaces:**
- Produces: `CHOOSE_A_MODEL = Fix(kind="link", text="Choose a model", href="/detection#frigate-plus-model")`. The warning's last sentence becomes: `Once a model is trained, use it by its ID on the Detection page, under Frigate+, pick it under Settings, System, Detectors and model in Frigate, or upload it on the Detection page and choose Use.` The check's rules don't change.

- [ ] **Step 1: Change the test** that pins the warning's text to the new sentence and to `fix == CHOOSE_A_MODEL`; run it and see it fail.
- [ ] **Step 2: Implement**, then grep the repo for the old sentence (`fake` status fixtures, `script/devpi/tests`, docs) and update each copy.
- [ ] **Step 3: Run** `python -m pytest tm-control/backend/tests script/tests -q`. Expected: all pass.
- [ ] **Step 4: Commit** ("Point the Frigate+ check at the Detection page's ID box").

### Task 7: The form on the page

**Files:**
- Create: `tm-control/ui/src/modules/detection/PlusModelById.vue`
- Modify: `tm-control/ui/src/modules/detection/DetectionPage.vue`
- Test: `tm-control/ui/tests/detection-page.spec.ts`, and `tm-control/ui/tests/plus-model-by-id.spec.ts` (new)

**Interfaces:**
- Consumes: `POST /api/v1/models/plus/{model_id}/use` and `ModelsState['fetch']` from Task 5.
- Produces, in `PlusModelById.vue`: props `{ disabled: boolean; downloading: boolean; result: Result | null }`, emits `use: [id: string]`. A text field labelled "Model ID" (not hidden, `autocapitalize="off"`, `spellcheck="false"`), the button "Download and use", an info line while `downloading`, and `ActionResult` for `result`. `export function cleanId(typed: string): string | null`: trims, drops one leading `plus://`, and returns the id when it matches `/^[0-9a-f]{32}$/`, else null. The button is disabled while `cleanId` is null, and a field that isn't empty and isn't an id shows "A model ID is 32 characters, each 0-9 or a-f."
- Produces, in the page: a second panel in the Frigate+ section's `v-expansion-panels`, value `'frigate-plus-model'`, title "Use a model by its ID", admins only, `eager`. `/detection#frigate-plus-model` opens it and scrolls to the section.
- Exact copy:
  - Under the panel's title: "Copy the model's ID from your models on the Frigate+ website. Frigate downloads the model with the API key, then restarts."
  - Confirmation (title `Download and use <id>?`, button "Download and use"): "Frigate downloads the model, then restarts. The download can take a few minutes, and the restart about one. Traffic isn't counted while Frigate restarts."
  - While downloading: "Frigate is downloading the model. This can take a few minutes. You can leave this page."
  - The section's first paragraph becomes: "When the device is online and has a Frigate+ API key, an administrator can use a model by its ID below, or pick one in Frigate, under Settings, System, Detectors and model."

- [ ] **Step 1: Write the failing tests.**

```ts
// plus-model-by-id.spec.ts
it.each([
  ['0123456789abcdef0123456789abcdef', '0123456789abcdef0123456789abcdef'],
  ['  0123456789abcdef0123456789abcdef\n', '0123456789abcdef0123456789abcdef'],
  ['plus://0123456789abcdef0123456789abcdef', '0123456789abcdef0123456789abcdef'],
  ['0123456789ABCDEF0123456789ABCDEF', null],
  ['0123', null],
  ['', null],
])('cleanId(%j) is %j', (typed, id) => expect(cleanId(typed)).toBe(id))
it('emits the cleaned id, and only for an id', …)
it('disables the field and the button while downloading or disabled, and says it is downloading', …)

// detection-page.spec.ts, in "the Detection page's actions"
it('asks first, posts the id, and follows a download to the restart', async () => {
  // POST answers { name: ID, started: 'download', restarts: [] }; GET /models then answers fetch downloading,
  // downloading, saved, and then running(ID): the info line shows, every Use button is disabled meanwhile,
  // then 'Frigate is restarting.', then `Frigate runs <title>.`; the field is empty at the end
})
it('treats a model already on the device as a use', …)          // started 'restart': no downloading line
it("shows Frigate's reason under the form when the fetch is refused, and reloads the list", …)
it("shows the API's refusal under the form", …)                  // 409 no_key: 'Set the Frigate+ API key first.'
it('shows a running download to an admin who opens the page, with the panel open', …)
it('shows the last refusal to an admin who opens the page', …)   // fetch refused on first load: the message, panel open
it('opens the panel for /detection#frigate-plus-model', …)
it('shows a viewer no ID panel', …)
```

- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.** The page keeps the state and the actions, as with `ModelBlock`. A result for this form is at `'#plus'`. `working` is also true while `state.fetch?.state === 'downloading'`. One watcher on `state.fetch` drives the page: `downloading` reloads `GET /models` every `POLL_EVERY` with no limit of its own (the server ends it); a change from `downloading` to `saved` sets the "Frigate is restarting." result, calls the existing `poll` with `answer.running.name === id`, and resets the form by its `:key`; `refused` and `failed` show the message as an error. A `saved` record found on first load shows nothing.
- [ ] **Step 4: Run** `(cd tm-control/ui && npm test && npm run build)`. Expected: all pass.
- [ ] **Step 5: Try it in fake mode** (`CLAUDE.md`, "Fake mode"): `fedcba9876543210fedcba9876543210` downloads for five seconds and then runs; any other id is refused under the form; reload during the five seconds and the line is still there.
- [ ] **Step 6: Commit** ("Add the model ID form to the Detection page").

### Task 8: Docs and the device tests

**Files:**
- Modify: `docs/use/detection.md`, `docs/configuration/frigate-config.md` ("Use a model"), `docs/use/device-health.md` (the Frigate+ check's links), `docs/development/tm-control.md` (the Detection module), `tm-control/ui/README.md`, `CLAUDE.md` (the Detection page's routes), `script/devpi/README.md` if a test row changes
- Replace: `docs/assets/images/detection-page-frigate-plus-key.png` (the section with both panels)
- Test: `script/devpi/tests/test_web.py`, `script/devpi/tests/test_disruptive.py`

- [ ] **Step 1: Write the pages.**
  - `detection.md`, under Frigate+: "Use a model by its ID": where the ID is on the Frigate+ website, what Download and use does, that the page can be left, what each ending means (running; refused, with Frigate's reason; not finished in 10 minutes; Frigate stopped), that a model built for another detector is downloaded and then listed as unable to run here, and that a model Frigate won't load is fixed with Delete on its card and the ID again.
  - `frigate-config.md`: the Detection page's box is the first way to use a model; Frigate's picker and editor follow.
  - `tm-control.md`: the route, the record, the guard, no disk fallback for a model that isn't on the device, and the two accepted gaps (Decision 13).
- [ ] **Step 2: Device tests.** In `test_web.py`: an admin's `GET /models` has a `fetch` key and a viewer's is null; `POST /models/plus/not-an-id/use` is 422 for the admin and 403 for the viewer. In `test_disruptive.py`, for `pii_free` units with no key set: `POST /models/plus/<32 f's>/use` is 409 `no_key`, and `frigate.service` keeps its invocation. Neither test contacts Frigate+.
- [ ] **Step 3: Build the docs** (`mkdocs build --strict`) and run `python -m pytest script/tests -q`.
- [ ] **Step 4: Commit** ("Document using a Frigate+ model by its ID").

### Task 9: The bench and the pull request

Recorded with `tmdev check` on one `pii_free` dev Pi that has internet, one host at a time. The maintainer types the real key and the real IDs on the page; neither goes into a command, a log, the check record, or the PR.

- [ ] **Step 1: Deploy** the branch (`tmdev deploy <host> -- -t tm-control -t revproxy`), then `tmdev test <host>` and `tmdev test <host> --disruptive -- -k plus`.
- [ ] **Step 2: With the placeholder key** saved on the page: a made-up ID ends `refused` with Frigate's reason under the form; `config.yml` is unchanged; `frigate.service` keeps its invocation; the message and `journalctl -u tm-control.service` hold no key. Remove the key afterwards.
- [ ] **Step 3: With the maintainer's key and a model built for the Pi's detector:**
  1. Download and use: record the seconds from the tap to `saved` and to "Frigate runs …". The model is the card in use with its name and train date; the one it replaced is under Other models.
  2. During the download, `/detection` and `/status` load without "Frigate isn't answering" (open question 3). If they don't, stop and report: the info line needs to cover for it.
  3. A Use on another model during the download is refused with the downloading message.
  4. The same ID again takes the short path: no download, a restart.
  5. An ID of a model built for another detector: refused with the detector line; its card says it can't run on this detector; Delete removes it.
  6. Record whether each ID seen was 32 lowercase hex characters (open question 2), without recording the IDs.
  7. Put the unit back: Use the installer's model, delete the fetched models, Remove the key, and confirm the four entered-secret files are empty.
- [ ] **Step 4: End the check** (`tmdev check end`) and draft the PR into PR 1's branch (or `dev` once PR 1 has merged) from the template: the test plan's results, the measured download time, "Docs" listing the six files, "AI assistance" filled in. Give the maintainer the commit list and PR text to review before pushing.

## Open questions the bench answers

1. How long a download takes on the bench's link. If it's near or past 10 minutes, raise `fetch.WAIT` and the two sentences that say "10 minutes" (Task 4's table, `detection.md`).
2. Whether every Frigate+ model ID is 32 lowercase hex characters. If not, `PLUS_ID` follows Frigate+'s shape, in `inventory.py`, `cleanId`, and the `bad_id` message.
3. Whether Frigate answers its other API calls during a download.
