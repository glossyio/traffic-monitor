# Network page: the hotspot's fallback note: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** While the unit is on a Wi-Fi network, the Network page's Hotspot panel says the hotspot is only a fallback, names the network the unit is on, and says when the hotspot would start and how the unit gets back.

**Architecture:** UI only. `GET /network` already answers with `wifi.mode`, `wifi.network`, and `hotspot.enabled`, so no backend, API, or installer file changes. The words live in `summary.ts` with the page's other words, and `NetworkPage.vue` places them: one grey line in the folded panel's summary, one sentence at the top of the open panel.

**Tech Stack:** Vue 3 + Vuetify 3 + Vitest (`tm-control/ui`), Material for MkDocs (`docs/`).

**Spec:** this file. The maintainer approved the design and the wording on 2026-11-14.

**Status:** written 2026-11-14 against `origin/dev` at `b4a26f1`, in the worktree `~/code/tm-hotspot-note`, branch `feature/hotspot-fallback-note/323`, for [issue 323](https://github.com/glossyio/traffic-monitor/issues/323). This file is not committed yet (Task 1, Step 1). No open PR touches the files below.

## Design

**Why:** the folded Hotspot panel shows only the hotspot's name (`TM-AB12`). On a unit that is on a Wi-Fi network the hotspot isn't on air, but the panel reads as if it were, and nothing says when it would start.

**When the note shows:** `wifi.mode === 'network'` and `hotspot.enabled` (the hotspot starts by itself). Viewers and administrators both see it. It never shows while the unit is on its hotspot, joining, idle, or with the radio off, nor while the hotspot is off (the summary says "Hotspot off" then), nor on a unit without a hotspot.

**Folded**, a second line under the name, grey like the address line of This device:

```text
| Hotspot                               v |
| TM-AB12                                 |
| Fallback only. This unit is on HomeNet. |
```

**Open**, a grey sentence at the top of the panel, above the "Hotspot on" switch (admins) or the State row (viewers):

> The hotspot is a fallback. If this unit loses HomeNet, the hotspot starts about a minute later. While nobody is joined to the hotspot, the unit looks for its saved networks every 5 minutes and joins one that is back.

**What the unit does, which the words must match** (`tm-control/jobs/tm-network-retry`, and "When the hotspot runs" in `docs/use/wifi-hotspot.md`):

- The hotspot starts when the radio loses its Wi-Fi network, about 75 seconds later. Nothing reacts to the internet being unreachable, so the words say "loses `<network>`", never "loses internet".
- The way back isn't tied to one network: every 5 minutes, while nobody is joined to the hotspot, the unit joins the first saved network it hears. So the words say "its saved networks", not the network's name.

**Approaches considered:**

1. **The page works it out from `GET /network`** (chosen): the answer has everything, so the change is about 15 lines of UI.
2. **A new field in the API** (`hotspot.standby`, or the timings): one more contract to keep for words the page can already derive. Not needed.
3. **Timings read from the device** instead of written in the sentence: the 75 seconds is NetworkManager's behaviour, measured on a bench, not a setting anyone can read. The cost of approach 1 is that the sentence repeats two timings (about a minute, 5 minutes); if `tm-network-retry`'s timer or the docs table changes, the sentence changes too.

## Global Constraints

- The wording is fixed. Copy the strings in Task 1 exactly; the maintainer approved them.
- No file under `tm-control/backend`, `tm-control/jobs`, `script/`, or `container/` changes, and `src/api/schema` is not regenerated.
- Conventional Vuetify only: text classes (`text-body-2 text-secondary text-break`, `mb-4`), no new component, no custom CSS, no icon, no alert. The note is information, not a warning: it must not open the panel or set the panel's warning mark.
- The network's name is shown as text (`{{ }}`), never with `v-html`.
- The Device page's network card (`summaryFacts`) stays as it is.
- For the UI task, load `frontend-design:frontend-design`, `superpowers:test-driven-development`, and `superpowers:verification-before-completion`. These constraints win over the design skill's push for distinctiveness.
- Docs follow "Writing docs" and its "Style" rules in `docs/development/contributing.md`. Read them before Task 2.
- Commit trailers and the PR's "AI assistance" section follow `CLAUDE.md` ("AI use in this repository"). Ask the maintainer for the interface and effort level; never guess. No message line may start with `#`.
- Keep device names and addresses out of commits, the PR, and this file.
- Nothing is pushed until the maintainer has read the commit messages and the PR text.

## Review Focus

1. **A network with no name in the answer** (`wifi.network` is `null` while `mode` is `network`): the words say "a Wi-Fi network" and "its Wi-Fi network". No "null", no empty gap. Pinned in Task 1, Step 2.
2. **A name that looks like markup, or 32 characters with no space:** shown as text, and it wraps. Pinned in Task 1, Step 4 (markup); the wrap is `text-break`, checked by eye at 375 px in Task 3.
3. **The hotspot is off while the unit is on a network:** the summary is exactly "Hotspot off" and the open panel has no fallback sentence, because nothing would start. Pinned in Task 1, Step 4.
4. **The unit is on its hotspot:** the summary is exactly the name, as today. Already pinned by `starts with This device and Hotspot collapsed, each with its summary`; Step 4 adds the open panel.
5. **A Wi-Fi join is under way:** the note follows the last `GET /network` answer, which the page doesn't reload while the test runs. A unit that was on a network keeps its note through the test and the countdown, which is right: it is still on that network until the switch. A unit that was on its hotspot has none. No code for this; the join card above says what is happening.
6. **Ethernet and Wi-Fi together:** the note depends on the radio only, so it shows. A unit on a cable with the radio idle or off has none.
7. **The network service didn't answer** (`readable: false`): the Hotspot column isn't drawn at all, as today.

---

### Task 1: The words and where they show

**Files:**
- Modify: `tm-control/ui/src/modules/network/summary.ts`
- Modify: `tm-control/ui/src/modules/network/NetworkPage.vue` (the Hotspot `CollapsePanel`, and the comment at the top of the file)
- Modify: `tm-control/ui/README.md` ("The page's layout: one screen", under the Network page's design notes)
- Test: `tm-control/ui/tests/network-summary.spec.ts`, `tm-control/ui/tests/network-page.spec.ts`

**Interfaces:**
- Produces, in `summary.ts`:

  ```ts
  // What the Hotspot panel says while the unit is on a Wi-Fi network and the hotspot would start by itself;
  // null at any other time.
  export function fallbackNote(wifi: Wifi | null, hotspot: HotspotState | null): { line: string; detail: string } | null
  ```

- [ ] **Step 1: Commit this plan by itself** — `Add the hotspot fallback note plan`. The plan was drafted with Claude Fable 5.2 (`claude-fable-5-2`), so that commit's `AI-Model` line names it; ask the maintainer for the interface and the effort level of that session.

- [ ] **Step 2: Write the failing test for the words** in `tests/network-summary.spec.ts` (import `fallbackNote`; `wifi` and `hotspot` are the file's own constants):

```ts
it('says the hotspot is only a fallback while the unit is on a Wi-Fi network', () => {
  const joined = { ...wifi, mode: 'network' as const, network: 'HomeNet', signal: 72 }
  const after =
    ', the hotspot starts about a minute later. While nobody is joined to the hotspot, the unit looks for its saved networks every 5 minutes and joins one that is back.'
  expect(fallbackNote(joined, hotspot)).toEqual({
    line: 'Fallback only. This unit is on HomeNet.',
    detail: `The hotspot is a fallback. If this unit loses HomeNet${after}`,
  })
  expect(fallbackNote({ ...joined, network: null }, hotspot)).toEqual({
    line: 'Fallback only. This unit is on a Wi-Fi network.',
    detail: `The hotspot is a fallback. If this unit loses its Wi-Fi network${after}`,
  })
})

it('has no fallback note at any other time', () => {
  const joined = { ...wifi, mode: 'network' as const, network: 'HomeNet', signal: 72 }
  expect(fallbackNote(wifi, hotspot)).toBeNull() // on its hotspot
  for (const mode of ['joining', 'idle', 'off'] as const) expect(fallbackNote({ ...wifi, mode }, hotspot), mode).toBeNull()
  expect(fallbackNote(joined, { ...hotspot!, enabled: false, active: false })).toBeNull()
  expect(fallbackNote(joined, null)).toBeNull()
  expect(fallbackNote(null, hotspot)).toBeNull()
})
```

- [ ] **Step 3: Run it, see it fail, write `fallbackNote`, see it pass.**

Run (from the repo root; Node 22 on the machine works too, with `npm ci && npx vitest run tests/network-summary.spec.ts` in `tm-control/ui`):
`podman run --rm -v "$PWD/tm-control/ui:/ui:Z" -w /ui docker.io/library/node:22.23.4-alpine sh -c 'npm ci && npx vitest run tests/network-summary.spec.ts'`
Expected first: FAIL, `fallbackNote` is not exported. After the function: PASS.

- [ ] **Step 4: Write the failing page tests** in the `the Network page layout` block of `tests/network-page.spec.ts`, with that block's `openAdmin` and `toggle` helpers and the file's `JOINED`:

```ts
const LINE = 'Fallback only. This unit is on HomeNet.'
const DETAIL =
  'The hotspot is a fallback. If this unit loses HomeNet, the hotspot starts about a minute later. While nobody is joined to the hotspot, the unit looks for its saved networks every 5 minutes and joins one that is back.'
const STANDBY = { ...NETWORK_STATE.hotspot!, active: false }

it('says under the folded Hotspot name that it is only a fallback while the unit is on a Wi-Fi network', async () => {
  const { wrapper } = await openAdmin({ [NETWORK]: networkState({ wifi: JOINED, hotspot: STANDBY }) })
  const summary = wrapper.find('#hotspot-summary')
  expect(summary.text()).toContain('TM-AB12')
  expect(summary.find('.text-secondary').text()).toBe(LINE)
  expect(isOpen(wrapper, 'hotspot')).toBe(false) // information, not news: the panel stays folded
  expect(wrapper.find(WARNING).exists()).toBe(false)
})

it('starts the open Hotspot panel with when the hotspot would start, for an admin and for a viewer', async () => {
  const routes = { [NETWORK]: networkState({ wifi: JOINED, hotspot: STANDBY }) }
  const admin = await openAdmin(routes)
  await toggle(admin.wrapper, 'hotspot').trigger('click')
  expect(admin.wrapper.find('#hotspot-body p').text()).toBe(DETAIL)
  expect(admin.wrapper.find('#hotspot-summary').exists()).toBe(false)

  document.body.replaceChildren()
  signedIn(VIEWER, { [WIFI]: WIFI_NETWORKS, ...routes })
  const viewer = await mountApp('/network')
  expect(viewer.wrapper.find('#hotspot-body p').text()).toBe(DETAIL)
})

it('has no fallback note on the hotspot, or with the hotspot off', async () => {
  const onHotspot = await openAdmin()
  expect(onHotspot.wrapper.find('#hotspot-body').text()).not.toContain('fallback')

  document.body.replaceChildren()
  const off = { ...NETWORK_STATE.hotspot!, enabled: false, active: false }
  const { wrapper } = await openAdmin({ [NETWORK]: networkState({ wifi: JOINED, hotspot: off }) })
  expect(wrapper.find('#hotspot-summary').text()).toBe('Hotspot off')
  expect(wrapper.find('#hotspot-body').text()).not.toContain('fallback')
})

it("shows a network's name as text", async () => {
  const odd = { ...JOINED, network: '<b>Cafe</b>' }
  const { wrapper } = await openAdmin({ [NETWORK]: networkState({ wifi: odd, hotspot: STANDBY }) })
  expect(wrapper.find('#hotspot-summary').text()).toContain('This unit is on <b>Cafe</b>.')
  expect(wrapper.find('#hotspot b').exists()).toBe(false)
})
```

If `openAdmin` doesn't take a routes argument shaped like this, follow how the block's own tests pass `[NETWORK]` (see `summarises the addresses in use`). `#hotspot-body p` is the first paragraph in the panel's body, which is what "at the top" means here; the body stays mounted while the panel is folded, so the viewer half needs no click.

- [ ] **Step 5: Run them, see them fail, then place the note in `NetworkPage.vue`.**
  - A computed `fallback` from `fallbackNote(state.value?.wifi ?? null, state.value?.hotspot ?? null)`.
  - In the Hotspot panel's `#summary` slot, after the name: `<div v-if="fallback" class="text-body-2 text-secondary text-break">{{ fallback.line }}</div>`.
  - First in the panel's default slot, before `HotspotSettings` and the viewer's facts: `<p v-if="fallback" class="text-body-2 text-secondary text-break mb-4">{{ fallback.detail }}</p>`.
  - Add one sentence about the note to the comment at the top of the file, where it describes the folded panels.

- [ ] **Step 6: Update the design notes** in `tm-control/ui/README.md`, section "The page's layout: one screen": the sketch's Hotspot panel gets the second line, the sketch's legend and the bullet "The summary is two short lines at most" say that Hotspot's second line is the fallback line and when it shows, and one new bullet says why the sentence in the open panel is grey text and not an alert (it is how the unit normally works, and alerts on this page mean something needs doing).

- [ ] **Step 7: Run the whole UI check.**

Run: `podman run --rm -v "$PWD/tm-control/ui:/ui:Z" -w /ui docker.io/library/node:22.23.4-alpine sh -c 'npm ci && npm run build && npm test'`
Expected: the build succeeds and every Vitest file passes, the new tests among them.

- [ ] **Step 8: Commit** — `Network page: say the hotspot is only a fallback while the unit is on Wi-Fi`

### Task 2: Docs

**Files:**
- Modify: `docs/use/wifi-hotspot.md`

- [ ] **Step 1: Describe the note** in the paragraph that begins "**This device** and **Hotspot** sit side by side": after the sentence on what each folded panel shows, say that while the unit is on a Wi-Fi network, a grey line under the hotspot's name says the hotspot is only a fallback and names that network, and that the open panel then starts with a sentence on when the hotspot would start, with a link to [When the hotspot runs](#when-the-hotspot-runs). Don't repeat the timings there; that section's table is their one home in the docs.

- [ ] **Step 2: Look for other pages that describe the folded Hotspot panel.**

Run: `git grep -n -i "hotspot off\|folded" -- docs tm-control/ui/README.md docs/development`
Expected: `docs/use/wifi-hotspot.md` and the UI README only. Update any other page that states what the folded panel shows.

- [ ] **Step 3: Build the docs.**

Run: `~/.venvs/tm-docs/bin/mkdocs build --strict` (set the venv up as `CLAUDE.md`'s Commands section says if it's missing)
Expected: builds with no warnings.

- [ ] **Step 4: Commit** — `Docs: the Hotspot panel's fallback note`

### Task 3: See it, then hand over for review

- [ ] **Step 1: Look at the page in fake mode** at 375 px and at a laptop width (`CLAUDE.md`, "Fake mode"). Fake mode's network state is in `tm-control/backend/tm_control/modules/network/state.py`; it reports a network after a join from the page, so join `HomeNet` and choose **Switch now**. Check: the folded line is grey, sits under the name, and wraps without widening the panel; the open panel's sentence comes first and reads as body text; on the hotspot (after `fake-reset`) neither shows. Take a screenshot of each width for the PR.

- [ ] **Step 2: Ask the maintainer whether they want a bench run.** The change is text on one page and no device file changes, so the off-device checks may be enough. If they want one, read `script/devpi/README.md`, make sure no other check is open (`tmdev.py check status`), and record, on a bench unit that is on a Wi-Fi network and after the whole installer has run from this worktree:

| # | Item | How |
|---|---|---|
| B1 | Folded, the Hotspot panel shows the fallback line with the unit's network | manual, by the maintainer, in a browser |
| B2 | Open, the sentence is first, for an administrator and for a viewer | manual |

Turning the hotspot off or taking the unit off its network to see the other states isn't worth a bench change; Vitest pins those.

- [ ] **Step 3: Run the repo's off-device checks that the diff touches** and keep the output for the PR: the UI build and Vitest (Task 1, Step 7) and `mkdocs build --strict` (Task 2, Step 3).

- [ ] **Step 4: Stop for review.** Give the maintainer the commit messages and a PR draft against `dev` that fills in the template: the why in two sentences, that it closes issue 323, the docs page changed, the screenshots, the checks run, and the "AI assistance" section. Suggest a fresh Fable 5.2 session for the final review of the diff. Push nothing until they say so.
