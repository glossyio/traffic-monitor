# Detection page sections: status, the model in use, the other models, and Frigate+

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. UI tasks also load frontend-design and superpowers:test-driven-development before the template work, and superpowers:verification-before-completion before any "done". Conventional Vuetify wins over novelty.

**Goal:** Reshape the Detection page the maintainer reviewed on 2026-11-08 into four sections (Object detection, Model in use, Other models on this device, Frigate+), with "Upload a model" always visible, the same compact card and closed fold for every model, each model's own object list, and a visible highlight wherever the tracked objects and a model's objects don't match.

**Architecture:** `DetectionPage.vue` changes shape; its actions, polling, and dialogs stay. `ModelBlock.vue` becomes a compact card with a closed fold for its files and objects. `LabelChips.vue` learns to mark chips. One API addition: `GET /models` gives each model its `labels`, read from the sidecar the inventory already parses (or the installer's labels file), because today it sends an object list only for the running model.

**Tech Stack:** Vue 3.5 + Vuetify 3.13 + TypeScript (Vitest in `tm-control/ui/tests`), the FastAPI backend and pytest, Material for MkDocs for the docs.

**Spec:** the maintainer's review on 2026-11-08, recorded under "Decisions" and "The layout" below, with the calls made while planning marked "(call)". This amends "The layout" of `2026-11-06-detection-page-layout.md`; what that plan and `2026-11-06-detection-models.md` say about the page's data, actions, and copy stands unless a line here changes it.

**Status:** written 2026-11-08 against `feature/detection-page/283` at `0529e11` (PR 284). The next PR in the stack is built on this branch and needs it merged in afterwards.

## Decisions

From the maintainer (2026-11-08):

1. Model cards are listed directly under their h2, with no outer accordion. Each card has its own closed fold.
2. Each model in `GET /models` gains `labels`, read by tm-control from the model's `.json`.
3. Frigate's own lists (what the running model recognises, what the device tracks) go at the top, under the status facts. The card of the model in use also gets the same closed fold as the other cards, fed by the per-model `labels`. The two mechanisms are shown separately on purpose: they should agree, but they are read in different ways, and the card of the model in use then looks like every other card.
4. Four extras: flag the mismatches between tracked and recognised objects, show the model kind on each card, give the card buttons a hierarchy, and title the section "Model in use".
5. A tracked object that a model doesn't recognise is highlighted, not only named in a sentence.

Calls made while planning:

- (call) The top list is titled "Objects the running model recognises (N)". A caption inside says where it came from, using `labels.source`, which the page ignored until now: "As Frigate reports them." (`frigate`), "From the model's .json, because Frigate didn't say." (`sidecar`), "From the installer's labels file, because Frigate didn't say." (`labels_file`). The top list is the only one a model without a `.json` can have, such as Frigate's built-in model.
- (call) When `labels.source` is `frigate`, the model in use has `labels`, and the two differ, one visible `text-body-2` line under the facts says "Frigate reports a different list than this model's .json." It has no alert colour: it is rare and usually a deliberate label-map edit. Compare as sets, ignoring entries named `unknown`: Frigate's merged label map is padded to 91 entries on a stock unit. **Check this on the bench (Task 6) before keeping the line.** If a stock unit shows the line, drop the line and say so in the hand-back.
- (call) The mismatch highlight uses the theme's `warning` colour, which the design notes already allow for status marks. A flagged chip is `variant="outlined" color="warning"`, and every place that flags chips has a legend line in words, so colour is never the only cue.
- (call) The Frigate+ panel's title becomes "Frigate+", and its state reads "API key not set", "API key set", or "API key set, ending in ab12", plus ", in use" while Frigate runs a Frigate+ model. The section id `frigate-plus` and the Status page's link stay.
- (call) A card's fold is titled "Files and objects", or "Files" when the model has no `labels`. A block the page makes for a default with no file on the device has no fold.
- (call) Each other-model card's fold names what a switch would lose, when anything: "Doesn't recognise 2 objects tracked on this device:" followed by those objects as flagged chips.
- (call) Card titles become `h3` with their current look, so a screen reader can step between models. The fold's title is a plain button, not a heading. The label list inside a fold is titled with an `h4`.
- (call) There is no "Model in use" section when the running model is unknown. Every model then lists under "Other models on this device", as today.

## The layout

The admin's view at 375 px. A viewer sees the same page without Upload, the card buttons, the key's state, and the key's form.

```text
+------------------------------------+
| Detection                     (h1) |
| See which model Frigate detects ...|
|                                    |
| Object detection              (h2) |
| [! Frigate isn't answering; ...]   |
| Detector        Running model      |
| edgetpu         My model, a local  |
|                 model              |
| (Frigate reports a different list  |
|  than this model's .json.)         |
| Frigate tracks only the objects    |
| that are in both lists.            |
| > Objects the running model        |  <- h3 panel, closed
|   recognises (3)                   |
|     As Frigate reports them.       |
|     [Copy] [person] [bicycle] (car)|  <- [filled] = tracked
|     Filled: tracked on this device.|
| > Objects tracked on this device   |  <- h3 panel, closed
|   (6, 2 not recognised)            |
|     [Copy] (person) (car) !dog!    |  <- !amber! = not recognised
|     Amber: the running model       |
|     doesn't recognise it.          |
| Tracked but not recognised by the  |  <- visible while the panels are closed
| running model: !dog! !cat!         |
|                                    |
| Model in use                  (h2) |
| +--------------------------------+ |
| | My model  (In use)        (h3) | |  <- tinted
| | Local model, trained 2026-10.. | |
| | [Download]                     | |
| | (Frigate runs My model.)       | |
| | > Files and objects            | |  <- closed
| +--------------------------------+ |
|                                    |
| Other models on this device (2)(h2)|
| [Upload a model]                   |
| (Deleted ... result, if any)       |
| +--------------------------------+ |
| | The installer's model     (h3) | |
| | yolov9-s-...edgetpu.tflite     | |
| | [Use]                          | |  <- filled
| | > Files and objects            | |
| +--------------------------------+ |
| +--------------------------------+ |
| | Test site yolov9          (h3) | |
| | Frigate+ model, trained ...    | |
| | [Use] [Download] [Delete]      | |  <- filled, outlined, error outlined
| | v Files and objects            | |
| |   0123...cdef, 4.0 KB, SHA-256 | |
| |   0123...cdef.json, 433 bytes  | |
| |   Objects it recognises (3)(h4)| |
| |   [Copy] [person] [bicycle] .. | |
| |   Filled: tracked on this      | |
| |   device.                      | |
| |   Doesn't recognise 2 objects  | |
| |   tracked on this device:      | |
| |   !dog! !cat!                  | |
| +--------------------------------+ |
| (No other models on this device.)  |  <- when there are none
|                                    |
| > Frigate+      API key not set    |  <- h2 panel, closed
+------------------------------------+
```

## Tasks

Work in the branch's worktree and check `git branch --show-current` first. For each task: change the test, see it fail, then change the code.

### Task 1: The API gives each model its labels

**Files:**
- Modify: `tm-control/backend/tm_control/modules/detection/labels.py`, `tm-control/backend/tm_control/modules/detection/router.py`
- Modify: `tm-control/backend/tests/test_api_models.py`
- Regenerate: `tm-control/ui/src/api/openapi.json`, `tm-control/ui/src/api/schema.d.ts`
- Modify: `docs/development/tm-control.md` (the `GET /models` row)

- [ ] **Step 1: Tests.** A model with a sidecar lists its labels in label-map index order. The installer's model lists its labels file. A model file without a `.json` gives `null`.
- [ ] **Step 2:** In `labels.py`, add `of_model(model, installer)`: `list(model.sidecar.labels)` when the model has a sidecar, the existing `_labels_file(installer.labels_file)` for the `installer_default` model, else `None`. Have `recognised()` use it for its two fallbacks.
- [ ] **Step 3:** In `router.py`, add `labels: list[str] | None` to `ModelOut`, and have `_model_out` take `installer` and fill it.
- [ ] **Step 4:** Regenerate the client types with the two commands in `tm-control/ui/README.md` ("Run it on a laptop", step 4). Add `labels` to the models in the UI tests' fixtures so they type-check.
- [ ] **Step 5:** Run `python -m pytest tm-control/backend/tests` and `npm test`, then commit.

### Task 2: `LabelChips.vue` marks chips

**Files:**
- Modify: `tm-control/ui/src/modules/detection/LabelChips.vue`
- Modify: `tm-control/ui/tests/detection-page.spec.ts`

- [ ] **Step 1:** Add two optional props. `marked?: string[]`: a chip whose label is in it renders `variant="tonal" color="primary"`. `flagged?: string[]`: a chip whose label is in it renders `variant="outlined" color="warning"`, and wins over `marked`.
- [ ] **Step 2:** Add two optional legend props, `markedLegend?: string` and `flaggedLegend?: string`. Each shows as a `text-body-2 text-secondary` line under the chips only when at least one chip has that mark.
- [ ] **Step 3:** Render the optional `title` as an `h4`. The prop is unused today, so nothing else changes.
- [ ] **Step 4:** Test the two chip looks by class or prop, both legends, and that Copy still copies every label. Commit.

### Task 3: `ModelBlock.vue` becomes a compact card with a fold

**Files:**
- Modify: `tm-control/ui/src/modules/detection/ModelBlock.vue`
- Modify: `tm-control/ui/tests/detection-page.spec.ts`

- [ ] **Step 1:** Put the title in an `h3` with its current classes. The facts line, the API's problem line, the buttons, the reason a Use can't work, and the action's result stay outside the fold.
- [ ] **Step 2:** Move the file lines into a `v-expansion-panels` fold: flat, transparent background, closed, `eager`, titled "Files and objects" or "Files". Its open state is local to the block. A block with no `model` has no fold.
- [ ] **Step 3:** New props `tracked: string[]` and `missing: string[]`. In the fold, after the files and when the model has `labels`: `LabelChips` with `title="Objects it recognises (N)"`, `:marked="tracked"`, and `marked-legend="Filled: tracked on this device."` Then, when `missing` isn't empty, the sentence "Doesn't recognise N objects tracked on this device:" (singular for one) followed by those labels as `variant="outlined" color="warning"` chips.
- [ ] **Step 4:** Buttons: Use is `variant="flat" color="primary"`, Download is unchanged, and Delete is `variant="outlined" color="error"`. All keep `min-height="44"`.
- [ ] **Step 5:** Tests for the fold's title in each case, the files inside it, the missing-objects line, and the three buttons' looks. Commit.

### Task 4: `DetectionPage.vue` gets the four sections

**Files:**
- Modify: `tm-control/ui/src/modules/detection/DetectionPage.vue`
- Modify: `tm-control/ui/tests/detection-page.spec.ts`

- [ ] **Step 1: Facts line.** `facts()` starts with "Frigate+ model" or "Local model" for the two kinds that aren't defaults.
- [ ] **Step 2: Object detection.** In order: the two alerts, the facts grid, the difference line (see the call above), the "both lists" sentence, the recognised panel, the tracked panel, and the visible mismatch line.
  - The recognised panel is titled "Objects the running model recognises (N)", opens with its source caption, and passes `:marked="state.labels.tracked"` with the "Filled" legend. Keep the two existing texts for when the labels aren't known.
  - `unrecognised` is the tracked labels that aren't in `labels.recognised`, and is empty when `recognised` is null.
  - The tracked panel is titled "Objects tracked on this device (N)", or "(N, M not recognised)" when `unrecognised` isn't empty, and passes `:flagged="unrecognised"` with the legend "Amber: the running model doesn't recognise it."
  - Under the panels, when `unrecognised` isn't empty: "Tracked but not recognised by the running model:" followed by those labels as warning chips.
- [ ] **Step 3: Model in use.** An `h2` section with the in-use `ModelBlock`, rendered only when `inUse` is set.
- [ ] **Step 4: Other models on this device (N).** An `h2`, then "Upload a model" for admins, the `LIST` result, and the cards in a `d-flex flex-column ga-3`, or "No other models on this device." Remove `modelsOpen` and the outer panel.
- [ ] **Step 5: Frigate+.** Retitle the panel and reword `keyState` (see the call above). The `linkedToKey` scroll is unchanged.
- [ ] **Step 6:** `blockProps` adds `tracked` (the device's tracked labels) and `missing` (tracked labels not in the block's `model.labels`; empty when the labels are null or the block is in use).
- [ ] **Step 7: Tests.** Update the headings list, the panel helpers and titles, and the upload test (the button is visible with nothing to open). Add cases for the source captions, the difference line, both mismatch highlights, the empty state, the kind in the facts line, and the key's new state words. Run `npm test` and `npm run build`, then commit.

### Task 5: Docs and design notes

**Files:**
- Modify: `docs/use/detection.md`, `tm-control/ui/README.md`
- Replace: `docs/assets/images/detection-page-models.png`, `docs/assets/images/detection-page-frigate-plus-key.png`

- [ ] **Step 1:** `docs/use/detection.md`: "The Detection page" (the four sections, Upload always visible, the fold on each model), "What the model recognises" (the two places a list appears, why they can differ, the filled and amber objects, and the two sentences), and "Frigate+" (the new title and state words). Follow "Writing docs" and its Style rules in `docs/development/contributing.md`.
- [ ] **Step 2:** `tm-control/ui/README.md`, "### Detection": replace the mockup with the one above and update the bullets (no outer panel, the fold per card, the button hierarchy, the two label sources, the two marks and why each has a legend). Under "Defaults rejected", add "One accordion for all the other models: it hid Upload and put a fold inside a fold."
- [ ] **Step 3:** `~/.venvs/tm-docs/bin/mkdocs build --strict`, then commit.

### Task 6: Look at it, bench it, and retake the screenshots

- [ ] **Step 1: Fake mode at 375 px and 1366 px**, as an admin and as a viewer, and through `/detection#frigate-plus`. Check that Upload is visible without opening anything, each card's fold, a Use from an other-model card (the card moves to "Model in use" with its result), a Delete (its result above the cards), the filled and amber chips against the page and against the tinted card, and the focus ring on a fold's title. Fix what reads badly.
- [ ] **Step 2: Bench**, one host at a time and logged with `tmdev.py check`, because the API changed. Deploy `-t tm-control -t revproxy`, confirm `GET /api/v1/models` carries `labels` for each model, and open the page. Record what a stock unit's top list holds (its count, and whether it has `unknown` entries) and whether the difference line shows. Run `tmdev.py test <host>`.
- [ ] **Step 3:** Retake the two screenshots in fake mode at 375 px and fix their alt text in `docs/use/detection.md`. Add what Steps 1 and 2 changed to "What the screenshot review changed" in `tm-control/ui/README.md`. Commit.

## Verification

```bash
. .venv/bin/activate
python -m pytest tm-control/backend/tests
(cd tm-control/ui && npm test && npm run build)
~/.venvs/tm-docs/bin/mkdocs build --strict
```

Commits stay local until the maintainer has read the commit messages and the change to the PR's text. The PR's "Limits" and its screenshots need updating after the push.
