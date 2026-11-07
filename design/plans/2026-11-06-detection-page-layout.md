# Detection page layout: facts, one model in use, and closed sections

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. UI tasks also load frontend-design before the template work, and superpowers:verification-before-completion before any "done".

**Goal:** Reshape the Detection page the maintainer reviewed on 2026-11-06 so that it opens with a one-line purpose, the detector and the running model as two facts, the model in use as one bordered block, and the rest (the other models, the two label lists, the Frigate+ API key) in sections that are closed until tapped and say in their title what they hold.

**Architecture:** One page component changes shape (`DetectionPage.vue`); its data, the API, and every action stay as they are. Each model becomes a bordered block (`.model`), the one in use tinted with the theme's `surface` color above the fold, the others inside a Vuetify expansion panel. The two label lists and the key form each move into a panel of their own, built the way the Device page's "Tokens and keys" already is: the heading element wraps the panel title, so the page outline is unchanged for screen readers. The Status page's `#frigate-plus` link opens its panel. One optional task lets the bare-file form set the sidecar's `name`, a key the backend already writes.

**Tech Stack:** Vue 3.5 + Vuetify 3.13 + TypeScript (Vitest 4 in `tm-control/ui/tests`), the FastAPI backend and pytest for the optional Task 5, Material for MkDocs for the docs.

**Spec:** the maintainer's review of the page in fake mode on 2026-11-06, recorded as "The layout" below, with the calls made while planning marked "(call)". This amends Tasks 9 and 10 of the Detection page plan (`design/plans/2026-11-06-detection-models.md`, which its Task 14 copies into this directory); everything that plan says about the page's data, actions, and copy stands unless a line here changes it.

**Status:** written 2026-11-06 against `feature/detection-page/283` at `6306d65` (unpushed; stacked on PR 280's branch). To be done before the branch's final review and its PR (that plan's Task 14). The page's screenshots for the PR are taken again at the end of this plan (Task 6), replacing Task 10's.

## The layout

The admin's view at 375 px. A viewer sees the same page with no buttons but the two Copy buttons, no status in the key panel's title, and no form.

```text
+----------------------------------+
| Detection                   (h5) |
| See which model Frigate detects  |
| objects with and what it         |
| recognises. Administrators can   |
| switch models and set the        |
| Frigate+ API key.                |
|                                  |
| Object detection            (h2) |
| [! Frigate isn't answering; ...] |
| Detector        Running model    |
| edgetpu         Test site yolov9,|
|                 a Frigate+ model |
| +------------------------------+ |
| | Test site yolov9  (In use)   | |  <- .model.in-use, bg-surface
| | trained 2026-10-01, ...      | |
| | 0123...cdef, 4.0 KB, SHA-256 | |
| | 0123...cdef.json, 433 bytes  | |
| | [Download]                   | |
| +------------------------------+ |
| > Other models on this device (2)|  <- panel, closed; h3 in the title
|   [Upload a model]               |
|   (Deleted ... result, if any)   |
|   +----------------------------+ |
|   | My model                   | |
|   | trained ..., for edgetpu   | |
|   | mine.tflite, 2.0 KB, ...   | |
|   | [Use] [Download] [Delete]  | |
|   +----------------------------+ |
|   +----------------------------+ |
|   | The installer's model      | |
|   | yolov9-s-...tflite         | |
|   | 1.0 KB, SHA-256 5f70bf18...| |
|   | [Use]                      | |
|   +----------------------------+ |
|                                  |
| What the model recognises   (h2) |
| Frigate tracks only the objects  |
| that are in both lists.          |
| > All objects the model          |  <- panel, closed; h3
|   recognises (3)                 |
|   [Copy]  (person) (bicycle) ... |
| > Objects tracked on this        |  <- panel, closed; h3
|   device (6)                     |
|   [Copy]  (bicycle) (person) ... |
|                                  |
| > Frigate+ API key      Not set  |  <- panel, closed; the h2 is the title
|   (the two sentences on the      |
|    online and offline routes)    |
|   [ Frigate+ API key        (o)] |
|   [Save]                         |
+----------------------------------+
```

What the maintainer asked for, and the calls made here:

1. **A one-line purpose under the title**, `text-body-1`: "See which model Frigate detects objects with and what it recognises. Administrators can switch models and set the Frigate+ API key." (call: two short sentences rather than the longer single one proposed, so a viewer isn't told the page lets them switch).
2. **Two facts, label above value**, in the Device page's Software grid (`v-row dense`, `v-col cols="6" sm="4"`, label `text-body-2 text-secondary`, value `text-body-1 text-break`): **Detector** with the detector type, or "Unknown"; **Running model** with the title and kind in words. The sentences "This device detects with edgetpu." and "Frigate runs …" go. (call: "Detector" not "Hardware detector", since the value is `cpu` on a device without an accelerator; "Running model" not "Current model", since the page's verb for the state is "runs" and the button is "Use".)
3. **Each model is a bordered block** holding its title, chip, facts, files, problem, buttons, reason, and result: `class="model border rounded-lg pa-4"`. The one Frigate runs is the only block above the fold, with the chip **In use** (primary color) and `bg-surface in-use` added to its classes; no other block is tinted. (The design notes' "no card per model" is revised in Task 4: these aren't `v-card`s and open nothing; the border says each is one choice.)
4. **The other models sit in a closed panel titled "Other models on this device (N)"**, N the number of blocks inside. **Upload a model** is the first thing in it, then the list-level result ("Deleted …"), then the blocks in the API's order. The installer's model and Frigate's built-in model are blocks like the others, each with its own **Use** button when it is the device's default and isn't running, instead of a lone "Use the installer's model" button under the list. (call: "Use" on every block; the confirmation keeps naming it, "Use the installer's model?".)
5. **A default that has no file in `model_cache`** (Frigate's built-in model on a device without a Coral, which the API can't list) still gets a block, made by the page: title "Frigate's built-in model", facts line "Built into Frigate.", no files. It is the in-use block when `running.kind` says so, else a panel block with Use when it is the device's default. The same for `installer_default`, titled "The installer's model" with the facts line "Set up by the installer." (call: without this, a CPU device's one choice would be a button with no block.)
6. **"What the model recognises"** keeps its sentence above the fold and puts each list in a closed panel: **All objects the model recognises (N)** and **Objects tracked on this device (N)**. When the recognised list is unknown, the first title has no count and the panel holds the existing sentence. (call: "on this device" rather than the maintainer's "by this model", because the tracked list is Frigate's `objects: track` config, not the model's; the wording sends someone to the right place to change it.)
7. **The last section is "Frigate+ API key"**, a closed panel whose title is the h2, as on the Device page. For an admin the title also carries the key's state: "Not set", "Set", "Set, ending in ab12", with ", in use" appended when `running.kind` is `frigate_plus`; while the secrets haven't answered, or a viewer is looking, nothing. Inside: the two sentences on the online and offline routes (everyone), then the admin's form. The form's own heading and state line are hidden, since the title has them. The Status page's **Set the key** link, `/detection#frigate-plus`, opens the panel and scrolls to it.
8. **Panels open independently** (`multiple`), so both label lists can be open at once. Panel content is rendered eagerly (`eager`), so the page's height is known when the `#frigate-plus` link scrolls, and the tests read the content without opening every panel. (call.)
9. **The page title stays "Detection"**; "Object detection" is the first h2, and a later kind of detection would be another h2 beside it. Nothing else on the page moves.

## Global Constraints

- The design notes in `tm-control/ui/README.md` hold: no new colors (the tint is the theme's `surface`; the chip and buttons use `primary`), system fonts, Vuetify's typography classes (`text-h6` for h2s, `text-subtitle-1 font-weight-medium` for h3s), buttons at least 44 px tall, sentence case, results where the action was and never a toast, nothing that depends on hover, a visible focus ring, readable at 375 px with no horizontal scroll.
- The accessible accordion pattern as the Device page has it: the heading element wraps `v-expansion-panel-title`, which is the button; `aria-expanded` is Vuetify's.
- No API change in Tasks 1 to 4 and 6. Task 5 adds one optional field to one request body and writes only a key the sidecar already has (`name`); nothing Frigate doesn't define goes into a `.json`.
- The Detection page plan's constraints stand: no secret value and no `verifiedCounts` anywhere, commits with the trailer block from `CLAUDE.md`, `PUBLIC push →` before any push, and its off-device checks before the PR (`npm test && npm run build` in `tm-control/ui`, the backend suite for Task 5, `mkdocs build --strict`).
- Tests assert whole strings of copy, so a wording change is a deliberate test change.

## Review Focus

1. **Frigate's model is unknown** (`running.kind` null, as after a config Frigate can't read): no block is tinted, "Running model" says "Unknown", every listed model is in the panel and its count says so. Task 1's `'puts every model in the panel when Frigate's model is unknown'`.
2. **A viewer follows `/detection#frigate-plus`**: the panel opens with the two sentences, no state in the title, no form, and no request to `GET /secrets`. Task 3's `'opens the key panel for a viewer without asking for the secrets'`.
3. **Deleting the last other model**: the title reads "(0)", the panel stays open, and "Deleted My model." is inside it. Task 1's delete test, extended.
4. **Frigate isn't answering**: the warning sits above the facts, the facts still show what the config file says, and the in-use block is the config file's model. The existing `'says when Frigate is not answering…'`, extended in Task 1.
5. **A key set while Frigate runs a local model**: the title says "Set, ending in ab12" and not "in use". Task 3's `'says the key is in use only while Frigate runs a Frigate+ model'`.

---

### Task 1: The Object detection section: purpose line, facts, the block in use, and the other-models panel

**Files:**
- Modify: `tm-control/ui/src/modules/detection/DetectionPage.vue` (the script's `detectorLine`, `runningLine`, `defaultOffer`, `mark`; the template's first `<section>`)
- Create: `tm-control/ui/src/modules/detection/ModelBlock.vue`
- Test: `tm-control/ui/tests/detection-page.spec.ts`

**Interfaces:**
- Consumes: `ModelsState`, `ModelOut`, `ActionResult`, `UploadModel`, `ConfirmDialog`, `use(model | null)`, `remove`, `download`, `result.at` (`DEFAULT = '#default'`, `LIST = '#list'`), as the page has them now.
- Produces, in the page's script:
  - `const open = ref<string[]>([])`, the open panels' values; this task adds `'other-models'`, Task 2 `'recognised'` and `'tracked'`, Task 3 `FRIGATE_PLUS_ID`. The template's one `<v-expansion-panels v-model="open" multiple flat>` per section.
  - `type Block = { key: string; title: string; facts: string; model: ModelOut | null; kind: ModelOut['kind']; inUse: boolean }`, one per bordered block; `model` is null for a block the page makes (item 5 of the layout). `key` is `model.name`, or `'#frigate_default'` / `'#installer_default'` for a made block (a name can't start with `#`).
  - `const inUse = computed<Block | null>()`: the model with `running` true, else a made block when `running.kind` is `installer_default` or `frigate_default`, else null.
  - `const others = computed<Block[]>()`: every listed model that isn't `inUse`, in the API's order, plus a made block for `state.default` when no listed model has that kind and `running.kind !== state.default`.
  - `function canUseDefault(block: Block): boolean`: `block.kind === state.default && state.running.kind !== state.default && !block.inUse`, the old `defaultOffer` condition per block. Use on such a block calls `use(null)`; its result shows at `DEFAULT`.
  - `const detectorValue = computed(() => state.detector ?? 'Unknown')` and `const runningValue = computed<string>()`: "Test site yolov9, a Frigate+ model" / "My model, a local model" / "The installer's model" / "Frigate's built-in model" / "A Frigate+ model" or "A local model" when the kind is known and the name isn't / "Unknown".
  - `mark(model)` returns `'In use'` instead of `'running'`.
  - A made block's `facts`: "Built into Frigate." for `frigate_default`, "Set up by the installer." for `installer_default`.
- The template's hooks the tests use: `.model` on every block, `.model.in-use` on the tinted one, `.v-expansion-panel-title` on each panel's button, `h3` inside the title for this panel.

- [ ] **Step 1: Rewrite the tests of the first `describe` that read the section, and add two**

Helpers at the top of the file: `item()` finds `.model` instead of `.v-list-item`; add `actions(wrapper)` returning the trimmed text of every `main button` that isn't a `.v-expansion-panel-title`; `panel(wrapper, title)` returning the `.v-expansion-panel-title` whose trimmed text starts with `title` (one, asserted); and `fact(wrapper, label)` returning the value under that label in the facts grid (the `.v-col` whose first `div` reads `label`; one, asserted; returns its second `div`'s trimmed text). Hoist the actions `describe`'s `running()` helper above the first `describe`. The test file's `headings()` stays.

`'lists the models with the running one marked and the detector named'` becomes `'shows the facts, the model in use, and the others behind a closed panel'`:

```ts
expect(headings(wrapper)).toEqual(['Object detection', 'What the model recognises', 'Frigate+ API key'])
expect(wrapper.text()).toContain('See which model Frigate detects objects with and what it recognises.')
expect(fact(wrapper, 'Detector')).toBe('edgetpu')
expect(fact(wrapper, 'Running model')).toBe('Test site yolov9, a Frigate+ model')
const plus = wrapper.find('.model.in-use')
expect(plus.text()).toContain('Test site yolov9')
expect(plus.text()).toContain('In use')
// facts, files, and the hash's title as before, on `plus`
const toggle = panel(wrapper, 'Other models on this device (2)')
expect(toggle.attributes('aria-expanded')).toBe('false')
expect(wrapper.findAll('.model.in-use')).toHaveLength(1)
await toggle.trigger('click')
expect(toggle.attributes('aria-expanded')).toBe('true')
expect(wrapper.findAll('.v-expansion-panel .model').map((m) => m.find('.text-body-1').text())).toEqual(["The installer's model", 'My model'])
// the installer's block: its file name once, no "trained", "1.0 KB, SHA-256 5f70bf18a086", as before
```

`'shows a viewer the page without the key form or any action'`: `expect(actions(wrapper)).toEqual(['Copy', 'Copy'])` in place of the `main button` line, and `'Frigate+ API key'` in place of `'Frigate+'` in the headings line; the rest stands (Task 3 adjusts its key lines).

`'names the installer model and an unknown detector in words'`: `fact(wrapper, 'Detector')` is `'Unknown'` and `fact(wrapper, 'Running model')` is `"The installer's model"`; `wrapper.find('.model.in-use').text()` contains `"The installer's model"`.

`'never names a model it does not know'`: first mount, `fact(wrapper, 'Running model')` is `'Unknown'` and `wrapper.find('.model.in-use').exists()` is false; second mount, `'A Frigate+ model'` and no `'null'` anywhere.

`'says when Frigate is not answering and the labels are unknown'`: add that the warning's text comes before `'Detector'` in `wrapper.text()` (`indexOf`), and that `.model.in-use` is the Frigate+ block.

`'offers Try again when the models do not load'`: after the click, `fact(wrapper, 'Running model')` is `'Test site yolov9, a Frigate+ model'`.

New, `'puts every model in the panel when Frigate\'s model is unknown'` (Review Focus 1): `running: { name: null, kind: null, source: null }` with every model's `running` false; no `.model.in-use`; `panel(wrapper, 'Other models on this device (3)')` exists.

New, `'makes a block for Frigate\'s built-in model when the device has no file for it'` (layout item 5): detector `'cpu'`, `default: 'frigate_default'`, `running: { name: null, kind: 'frigate_default', source: 'frigate' }`, models `[MINE]` with `running` false, as a viewer: `.model.in-use` text contains `"Frigate's built-in model"` and `'Built into Frigate.'`; `fact(wrapper, 'Running model')` is `"Frigate's built-in model"`; the panel title is `'Other models on this device (1)'`.

- [ ] **Step 2: Rewrite the action tests that touch the section**

- `'uses a model after the confirm and polls until it runs'`: open the panel first (`await panel(wrapper, 'Other models').trigger('click')`), then as now; after the third poll, `wrapper.find('.model.in-use').text()` contains `'My model'` and the panel title reads `'Other models on this device (2)'`.
- `'deletes after the confirm and reloads the list'` (Review Focus 3): `gone` keeps only the installer's and the Frigate+ models; after the delete, `panel(wrapper, 'Other models on this device (1)')` has `aria-expanded` `'true'` and `wrapper.find('.v-expansion-panel').text()` contains `'Deleted My model.'`; `.model` texts don't include `'My model'`.
- `"lists Frigate's own Hailo model as its built-in model, running and with no buttons"`: `entry` is `wrapper.find('.model.in-use')`; `'In use'` instead of `'running'`.
- `"offers the installer's model when another one runs"` becomes `"uses the installer's model from its own block"`: `clickIn(item(wrapper, "The installer's model"), 'Use')`; the dialog says `"Use the installer's model?"`; the POST is `/api/v1/models/default/use`; after the polls, `.model.in-use` contains `"The installer's model"`, and the Frigate+ model's block, now in the panel, has buttons `['Use', 'Download']`.
- The `it.each` on defaults becomes `'with %s, the block %s offers Use: %s'`, rows `[state, blockTitle, offersUse]`, each state built from `MODELS` so that the `running` flags agree with `running.kind`:
  1. `{ ...MODELS, default: 'frigate_default' }`: `"Frigate's built-in model"`, true (a made block in the panel; the title counts 3).
  2. `{ ...MODELS, default: 'frigate_default', running: { name: null, kind: 'frigate_default', source: 'frigate' }, models: MODELS.models.map((m) => ({ ...m, running: false })) }`: `"Frigate's built-in model"`, false, and that block is `.in-use`.
  3. `{ ...running(MODELS.models[0].name, 'installer_default') }`: `"The installer's model"`, false, and it is `.in-use`.
  4. `{ ...MODELS, default: null }`: `"The installer's model"`, false, and no `.model` reads `"Frigate's built-in model"`.
- `'shows the results of models named "default" and "list" under those models'`: unchanged in substance; `wrapper.findAll('main .v-alert')` still equals one alert.
- `'opens the upload dialog from the button above the list'` becomes `'opens the upload dialog from inside the other-models panel'`: `panel(wrapper, 'Other models')` contains no `'Upload a model'`; after opening it, `click(wrapper, 'Upload a model')` opens the dialog as now.

- [ ] **Step 3: Run the file and see the new and changed tests fail**

Run: `cd tm-control/ui && npx vitest run tests/detection-page.spec.ts 2>&1 | tail -30`
Expected: FAIL on the rewritten tests ("Frigate+ API key" heading missing, no `.model`, no panel).

- [ ] **Step 4: Change the section**

In the script: replace `detectorLine`/`runningLine` with `detectorValue`/`runningValue`, `defaultOffer` with `inUse`/`others`/`canUseDefault`, `'running'` with `'In use'` in `mark`, and add `open`. Move `Block` to a new `ModelBlock.vue` in the same directory, which renders one block (title, chip, facts, files with the hash span, problem, the admin's buttons, the blocked reason, and the result) from props `{ block: Block; admin: boolean; busy: string | null; working: boolean; result: Result | null; useBlocked: string | null; canUse: boolean }` and emits `use`, `download`, and `remove` with no payload; the page keeps the state and the handlers and renders `<ModelBlock>` once above the fold and once per entry in the panel. `canUse` is `canUseDefault(block)` for a default or made block, else `!block.inUse`; `useBlocked` is the existing function's text for a listed model, null otherwise. In the template: the purpose paragraph under the h1 (`class="text-body-1 mb-6"`); the warning alert above the facts; the facts grid; the in-use block; then the panel: `<v-expansion-panel value="other-models" class="border" eager>` whose title is `<h3 class="text-subtitle-1 font-weight-medium"><v-expansion-panel-title class="text-subtitle-1 font-weight-medium">Other models on this device ({{ others.length }})</v-expansion-panel-title></h3>`, and whose text holds Upload, the `LIST` result, and the other blocks. Use on a made or default block: `confirming = { action: 'use', title: block.title === "The installer's model" ? "the installer's model" : "Frigate's built-in model", model: null }`, so the dialog reads as before. Default blocks show no Download or Delete; a made block shows no files.

- [ ] **Step 5: Run the file, then the suite and the build**

Run: `cd tm-control/ui && npx vitest run tests/detection-page.spec.ts 2>&1 | tail -5 && npm test 2>&1 | tail -5 && npm run build 2>&1 | tail -3`
Expected: all pass; the build finishes with no type error.

- [ ] **Step 6: Commit**

```bash
git add tm-control/ui/src/modules/detection tm-control/ui/tests/detection-page.spec.ts
git commit -m "Open the Detection page with its purpose, two facts, and the model in use, and fold the other models away"
```

### Task 2: The two label lists in closed panels

**Files:**
- Modify: `tm-control/ui/src/modules/detection/LabelChips.vue` (`title` becomes optional), `DetectionPage.vue` (the second `<section>`)
- Test: `tm-control/ui/tests/detection-page.spec.ts`

**Interfaces:**
- Produces: `LabelChips` props `{ title?: string; labels: string[] }`; with no title, the row holds only Copy and the status span. Panel values `'recognised'` and `'tracked'`; titles `All objects the model recognises (${n})` (no count while `labels.recognised` is null) and `Objects tracked on this device (${n})`.

- [ ] **Step 1: Change the tests**

- `'copies the recognised labels as comma-separated text'`: `const toggle = panel(wrapper, 'All objects the model recognises (3)')`; open it; `const recognised = toggle.element.closest('.v-expansion-panel')!` wrapped with `wrapper.find` or found via `wrapper.findAll('.v-expansion-panel').find((p) => p.text().includes('person'))`; click its Copy; `'Copied.'` and `writeText` as now.
- `'says when Frigate is not answering and the labels are unknown'`: `panel(wrapper, 'All objects the model recognises')` text is exactly `'All objects the model recognises'` (no count); the sentence is in that panel; `panel(wrapper, 'Objects tracked on this device (2)')` exists. `'Tracked by this device'` is gone from the page.
- `"says the running model's labels aren't known…"`: unchanged assertion, plus no count in the title.
- Add to the first test of Task 1: both label panels have `aria-expanded` `'false'` and `h3`s inside their titles; `wrapper.findAll('h3').map(text)` equals `['Other models on this device (2)', 'All objects the model recognises (3)', 'Objects tracked on this device (6)']`.

- [ ] **Step 2: Run the file and see them fail**

Run: `cd tm-control/ui && npx vitest run tests/detection-page.spec.ts 2>&1 | tail -20`
Expected: FAIL on the three.

- [ ] **Step 3: Change the section and `LabelChips`**

The sentence stays a `<p>` under the h2. Then one `<v-expansion-panels v-model="open" multiple flat>` with two `<v-expansion-panel class="border" eager>`; each title an `h3` as in Task 1; each text a `LabelChips` with no `title`, or, for an unknown recognised list, the existing `<p>`. `LabelChips` renders its `h3` only `v-if="title"`.

- [ ] **Step 4: Run the file, then the suite**

Run: `cd tm-control/ui && npx vitest run tests/detection-page.spec.ts 2>&1 | tail -5 && npm test 2>&1 | tail -5`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tm-control/ui/src/modules/detection tm-control/ui/tests/detection-page.spec.ts
git commit -m "Put each label list behind a title that counts it"
```

### Task 3: The Frigate+ API key panel, with the key's state in its title

**Files:**
- Modify: `tm-control/ui/src/components/EnteredSecret.vue` (an optional prop), `DetectionPage.vue` (the last `<section>`, the `linkedToKey` handling)
- Test: `tm-control/ui/tests/detection-page.spec.ts`, `tm-control/ui/tests/entered-secret.spec.ts` (one case)

**Interfaces:**
- Produces: `EnteredSecret` props `{ secret: SecretState; hideTitle?: boolean }`; with `hideTitle`, the `h3` and the state line aren't rendered, and nothing else changes. On the page: `const keyState = computed<string>()`: `''` while `key` is undefined (viewer, loading, or error); `'Not set'`; `'Set'`; `'Set, ending in ab12'`; each of the last two with `', in use'` appended when `state?.running.kind === 'frigate_plus'`. `open` starts as `[FRIGATE_PLUS_ID]` when `linkedToKey`.

- [ ] **Step 1: Change the tests**

- `'shows an admin the Frigate+ key form from GET /secrets'`: `const toggle = panel(wrapper, 'Frigate+ API key')`; `toggle.text()` contains `'Not set'`; `aria-expanded` `'false'`; `wrapper.find('#frigate-plus form').exists()` is true (eager) and `wrapper.find('#frigate-plus h3').exists()` is false; after opening, `aria-expanded` `'true'`; no `'ThingsBoard access token'`.
- New, `'says the key is in use only while Frigate runs a Frigate+ model'` (Review Focus 5): secrets with the key `{ set: true, ends_with: 'ab12' }`: with `MODELS`, the title contains `'Set, ending in ab12, in use'`; with `running('mine.tflite', 'local')` (hoist that helper above the first `describe`), `'Set, ending in ab12'` and not `'in use'`.
- `'shows a viewer the page without the key form or any action'`: `panel(wrapper, 'Frigate+ API key').text()` is exactly `'Frigate+ API key'`; the two sentences are inside `#frigate-plus` as now; no `form`.
- `'has the Frigate+ section a link can name'` becomes `'opens the key panel when a link names it, as the Status page\'s Set the key does'`: as an admin, `panel(wrapper, 'Frigate+ API key').attributes('aria-expanded')` is `'true'` and `scrolled` was called; the other three panels are closed.
- New, `'opens the key panel for a viewer without asking for the secrets'` (Review Focus 2): the same URL as a viewer: open, the sentences present, no `form`, and `api.sent` has no `/api/v1/secrets`.
- `entered-secret.spec.ts`: one case, `'hides its heading and state line when asked'`: `mountAlone(EnteredSecret, { secret, hideTitle: true })` has no `h3` and its text doesn't contain `'Not set.'`, while the field with the label is there.

- [ ] **Step 2: Run both files and see them fail**

Run: `cd tm-control/ui && npx vitest run tests/detection-page.spec.ts tests/entered-secret.spec.ts 2>&1 | tail -20`
Expected: FAIL on the changed and new cases.

- [ ] **Step 3: Change the section and the component**

The section keeps `:id="FRIGATE_PLUS_ID"` and `class="frigate-plus"` (its scroll margin). Inside: `<v-expansion-panels v-model="open" multiple flat><v-expansion-panel :value="FRIGATE_PLUS_ID" class="border" eager>`; the title: `<h2 class="text-h6"><v-expansion-panel-title class="text-h6"><span>Frigate+ API key</span><span v-if="keyState" class="text-body-2 text-secondary ms-3">{{ keyState }}</span></v-expansion-panel-title></h2>`; the text: the two paragraphs, then for admins the error alert, the progress bar, and `<EnteredSecret v-if="key" :secret="key" hide-title @changed="loadSecrets" />`. `open` is initialised from `linkedToKey`; the `scrollIntoView` after `load()` stays.

- [ ] **Step 4: Run the suite and the build**

Run: `cd tm-control/ui && npm test 2>&1 | tail -5 && npm run build 2>&1 | tail -3`
Expected: PASS; no type error.

- [ ] **Step 5: Commit**

```bash
git add tm-control/ui/src tm-control/ui/tests
git commit -m "Close the Frigate+ API key section and say in its title whether the key is set"
```

### Task 4: Docs and the design notes

**Files:**
- Modify: `docs/use/detection.md`, `docs/use/device-health.md` (line 45: "opens the Frigate+ section of the Detection page" → "opens the Frigate+ API key section of the Detection page"), `tm-control/ui/README.md` ("### Detection" and its two sub-sections)

- [ ] **Step 1: `docs/use/detection.md`**

"The Detection page": the page opens with one line on what it's for, then **Detector** and **Running model**; the model Frigate runs is shown on its own, marked **In use**; the rest of the device's models are under **Other models on this device**, which is closed until you select its heading and whose title counts them; **Upload a model** is the first thing in it. The mark table: "In use" replaces "running". The installer's paragraph: each default is a model in that list with its own **Use**, so "the **Use the installer's model** button under the list" becomes "**Use** on **The installer's model**" here, in "Use a model", and in "Delete a model". The roles paragraph follows. "What the model recognises": the two lists are **All objects the model recognises** and **Objects tracked on this device**, each closed until selected and counted in its title; keep the two definitions and the "both lists" sentence. "Frigate+": the heading stays `## Frigate+ { #frigate-plus }` (links point at it); the form paragraph becomes: administrators enter the key under **Frigate+ API key**, the last section, which is closed until selected and whose title says whether a key is set, its last four characters for a long key, and "in use" while Frigate runs a Frigate+ model; the Status page's **Set the key** opens it.

- [ ] **Step 2: `tm-control/ui/README.md`**

Replace the "### Detection" mockup with the one in "The layout" above (the README's drawing style), and its bullets with: the purpose line; the facts grid, shared with the Device page's Software section; the blocks (why a border: each is one choice; why only the one in use is tinted; `surface`, no elevation); the four panels (closed by default, counts and the key's state in the titles so a closed row still says something, independent, eager, the heading wrapping the title as on the Device page); Upload inside the models panel; Use on the defaults' own blocks; the label titles and why "on this device"; the key's state wording. Under "Defaults rejected", replace "A card per model…" with "`v-card` per model: a card reads as something to open. The blocks are a border and, for the one in use, the surface tint; the maintainer asked for the border after the first build, so that each model reads as one choice." Add: "A strict accordion (one panel open at a time): comparing the two label lists needs both open." and "'Expand for …' as a panel title: the chevron says that; the title names and counts what's inside." "What the screenshot review changed" gets its entry in Task 6.

- [ ] **Step 3: Build the docs**

Run: `~/.venvs/tm-docs/bin/mkdocs build --strict 2>&1 | tail -3`
Expected: no warning, no error.

- [ ] **Step 4: Commit**

```bash
git add docs/use/detection.md docs/use/device-health.md tm-control/ui/README.md
git commit -m "Describe the Detection page's new shape"
```

### Task 5 (optional; the maintainer decides): a name for a model uploaded as a bare file

The sidecar the form writes already has `name` (the Detection page plan's decision 13 sets it to the file name); Frigate+ records carry the same key, and the page's title for a model is that value. This task lets the person set it. It adds nothing else to the `.json`. Skip the task if the maintainer says no.

**Files:**
- Modify: `tm-control/backend/tm_control/modules/detection/router.py` (`SidecarForm`, `_form_sidecar`), `tm-control/ui/src/api/openapi.json` and `schema.d.ts` (regenerated), `tm-control/ui/src/modules/detection/ModelFields.vue`, `docs/use/detection.md` ("A model file alone")
- Test: `tm-control/backend/tests/test_api_models.py`, `tm-control/ui/tests/upload-model.spec.ts`

**Interfaces:**
- Produces: `SidecarForm.name: Title | None = None` with `Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]`; `_form_sidecar` writes `form.name or name` as `"name"`. The UI sends `name: modelName.value.trim() || null`.

- [ ] **Step 1: Backend test**

In `test_api_models.py`, `test_the_form_names_the_model_when_a_name_is_given`: PUT `named.tflite` (64 bytes), POST the sidecar with `FORM | {"name": "  Placeholder model  "}` → 201, `title` is `"Placeholder model"`, the written JSON's `"name"` is `"Placeholder model"` and its keys are exactly those of the existing bare-file test's; `FORM | {"name": "   "}` on another bare file → 422; `FORM | {"name": "x" * 65}` → 422. The existing `test_upload_a_bare_model_then_the_form_writes_a_sidecar` keeps asserting `"name": "bare.tflite"` with no name sent.

- [ ] **Step 2: Run it and see it fail**

Run: `python -m pytest tm-control/backend/tests/test_api_models.py -k names_the_model -q 2>&1 | tail -3`
Expected: FAIL (422: `name` isn't a field yet, or the title is the file name).

- [ ] **Step 3: Backend change, then regenerate the client**

Run after the change: `PYTHONPATH=tm-control/backend python -m tm_control dump-openapi > tm-control/ui/src/api/openapi.json && (cd tm-control/ui && npm run api:generate)`; then `python -m pytest tm-control/backend/tests -q 2>&1 | tail -3` (the OpenAPI pin test included).
Expected: PASS.

- [ ] **Step 4: UI test and change**

In `upload-model.spec.ts`, the case `'opens the fields form after a bare model file and posts the sidecar'` fills a field labelled `Name` with `'Placeholder model'` and asserts the posted body has `name: 'Placeholder model'`; a second case leaves it empty and asserts `name: null`. `ModelFields.vue` adds `<v-text-field v-model="modelName" label="Name" hint="Shown in the model list. Left empty, the file name is used." persistent-hint variant="outlined" />` as the first field, with `const modelName = ref('')`.

Run: `cd tm-control/ui && npx vitest run tests/upload-model.spec.ts 2>&1 | tail -5 && npm run build 2>&1 | tail -3`
Expected: PASS.

- [ ] **Step 5: Docs and commit**

`docs/use/detection.md`, "A model file alone": add "and a name for the list (the file name when left empty)" to the settings sentence. Then:

```bash
git add tm-control/backend tm-control/ui docs/use/detection.md
git commit -m "Let a model uploaded as a bare file be named for the list"
```

### Task 6: Look at it, bench the two paths that changed, and record what the screenshots changed

**Files:**
- Modify: `tm-control/ui/README.md` ("#### What the screenshot review changed" under Detection)

- [ ] **Step 1: Fake mode at 375 px and 1366 px**, as an admin and as a viewer, and through `/detection#frigate-plus`: the purpose line, the facts at both widths, the in-use block's tint against the page (the border visible on both), each panel closed on load with its title and count on one line or wrapping cleanly, Upload inside the panel, a Use from inside the panel (the result under the block, the block moving above the fold when Frigate runs it), the key's state in the title, the focus ring on a panel title. Fix what reads badly and note it. Take the PR's screenshots: admin and viewer at 375 px, the models panel open with a Use result, the key panel open.

- [ ] **Step 2: One bench item on the Coral unit**, through `tmdev.py check` from the worktree: `tmdev.py deploy <host> -- -t revproxy` (the UI's build), then on a phone or at 375 px: the Status page's **Set the key** opens the key panel with the state in its title; **Use** on **The installer's model** from inside the panel, Frigate restarts, the installer's block is in use; put the previous model back; a viewer sees no state and no form. Record the items; `tmdev.py check end`.

- [ ] **Step 3: README entry and commit**

Add what Step 1 changed to "What the screenshot review changed" (or "Nothing changed after the second review at 375 px and 1366 px." if so).

```bash
git add tm-control/ui/README.md
git commit -m "Record the Detection page's second screenshot review"
```

- [ ] **Step 4: Hand back.** The branch goes to the Detection page plan's final review and Task 14. When that task copies the Detection page plan into `design/plans/`, its Status paragraph gains one sentence: "The page's layout was reshaped after the maintainer's review of 2026-11-06; see `2026-11-06-detection-page-layout.md`."
