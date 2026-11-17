# Zone Name Check Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The Cameras page lists each camera's zones beyond the four fixed ones, says their names are saved with every event, and warns about a name that looks like an address or a person; the Status page counts such names.

**Architecture:** One leaf module holds two hand-written word lists and one function, `check_name`. `compare()` in the cameras module, which already holds each Frigate camera's whole zone mapping, puts the camera's other zones and what the check found on each row, and raises one new row issue. The Status check and the Cameras page both read the rows, so they can't disagree. No Frigate call is added, nothing is blocked or renamed, and no flow or schema changes.

**Tech Stack:** Python 3.13 standard library, FastAPI and pydantic (tm-control backend), Vue 3 + Vuetify 3 + TypeScript (tm-control UI), pytest, Vitest, MkDocs.

**Spec:** "What it must do" below.

**Repo:** `glossyio/traffic-monitor`, branch `feature/zone-name-check/306` off `dev` (`b4a26f1` when this was written), in its own worktree. All paths below are relative to the repo root.

## What it must do

1. Zone names stay as an operator typed them. Nothing is blocked, dropped, or renamed.
2. The Cameras page shows, for each camera, its zones other than `zone_capture`, `zone_near`, `zone_far`, and `zone_radar`, and says their names are saved with every event.
3. A zone name with a word the lists don't know gets a grey note on the Cameras page. It is not a problem and raises nothing on the Status page.
4. A zone name that looks like an address or a person's name gets an amber warning on the Cameras page and one line on the Status page.
5. The Status line counts such names and never quotes one, because check details go into Copy diagnostics.
6. The check works offline, from two lists in one file: about 150 to 200 known English words, and the address words and street abbreviations.
7. The docs say that zone names are saved with every event and shared with the data, and suggest compass names.

Not in this change: the same check on a detection model's title (planned for a later change; model file names carry numbers such as `512`, so the three-digit rule below can't apply to them as it is), and anything about `sub_label`.

## Global Constraints

- `tm_control/modules/apps/name_check.py` imports nothing from `tm_control` and uses only the standard library. No new dependency anywhere.
- A warning is raised only for a camera whose events are recorded: its entry is enabled, Frigate has the camera on, and the entry isn't a duplicate. This is the rule the existing `zones` issue uses.
- Only zones that are on are listed and checked. Frigate ignores a zone that is off, so its name reaches no event.
- The Status check's detail names cameras the way the other checks do (`_label`) and never contains a zone name.
- UI: conventional Vuetify components, no custom CSS beyond spacing classes, wording in `rows.ts`, rules in the backend. The UI task's implementer loads `frontend-design:frontend-design`, `superpowers:test-driven-development`, and `superpowers:verification-before-completion`; these constraints win over the design skill's push for distinctiveness.
- Docs ride with the code and follow "Writing docs" in `docs/development/contributing.md`. `mkdocs build --strict` must pass.
- On a bench unit this change adds and removes zones in Frigate and nothing else. Never turn on Frigate's detection, snapshots, or recording.
- Commit messages end with the trailer block in the repo's `CLAUDE.md`. No device names or addresses in commits or PR text.
- Nothing is pushed. The maintainer reads the commits, the PR text, and the issue comment first.
- Open PRs 321 and 318 also edit `contracts.py`'s `GROUP`, `status_fake.json`, `docs/use/device-health.md`, `docs/use/cameras.md`, and `CLAUDE.md`; PR 326 edits `docs/data-and-payloads/data-overview.md`. If one merges into `dev` first, merge `dev` in and keep both sides.

## Review Focus

Inputs the requirements imply and a person will meet; each has a test in the task named.

1. A zone name in another script or with accents (`зона_север`, `zone_café`): a grey note, never a crash or a silent pass. Task 1.
2. A zone that is off, an entry that is off, a Frigate camera no entry points at, a duplicate entry: no amber warning and no Status line, because the name isn't being saved. Task 2.
3. Frigate's `zones` in an odd shape (missing, a list, a string, a zone whose value isn't a mapping): no other zones, no crash. Task 2.
4. Twenty flagged names on one camera: the Status detail is still one count and quotes none. Task 3.
5. A near miss of a fixed name (`Zone_Capture`): it is another zone, and `zone_capture` is still reported missing. Task 2.

## Files

| File | Change |
|---|---|
| `tm-control/backend/tm_control/modules/apps/name_check.py` | New: the two lists, the abbreviations, `check_name` |
| `tm-control/backend/tm_control/modules/cameras/state.py` | `ZoneName`, `CameraRow.zone_names`, issue code `zone_names` |
| `tm-control/backend/tm_control/modules/apps/contracts.py` | Check `config.zone_names`, added to `GROUP` after `zones` |
| `tm-control/backend/tm_control/fake.py` | Three more zones on the fake Frigate's first camera |
| `tm-control/backend/tests/fixtures/status_fake.json` | The new check's entry and the summary count |
| `tm-control/ui/src/api/openapi.json`, `schema.d.ts` | Regenerated, never edited by hand |
| `tm-control/ui/src/modules/cameras/rows.ts`, `CamerasPage.vue` | The line, the note, the issue's wording |
| `script/devpi/tests/test_web.py` | `CONFIG_CHECKS` gains the new id |
| Tests | `tm-control/backend/tests/test_name_check.py` (new), `test_cameras_state.py`, `test_contract_checks.py`, `tm-control/ui/tests/camera-rows.spec.ts`, `cameras-page.spec.ts`, `fake-api.ts` |
| Docs | `docs/use/cameras.md`, `docs/setup-guide.md`, `docs/data-and-payloads/events-payload.md`, `docs/data-and-payloads/data-overview.md`, `docs/use/device-health.md`, `docs/development/tm-control.md`, `tm-control/ui/README.md`, `CLAUDE.md` |

## Commands

```bash
. .venv/bin/activate                                   # the dev venv from CLAUDE.md, in the same shell call
python -m pytest tm-control/backend/tests -q           # backend
python -m pytest container/node-red-tm/schema/tests script/tests tm-control/backend/tests -q   # everything off-device
PYTHONPATH=tm-control/backend python -m tm_control dump-openapi > tm-control/ui/src/api/openapi.json
podman run --rm -v "$PWD/tm-control/ui:/ui:Z" -w /ui docker.io/library/node:22.23.4-alpine sh -c 'npm ci && npm run api:generate && npm run build && npm test'
~/.venvs/tm-docs/bin/mkdocs build --strict
```

---

### Task 1: The name check

**Files:**
- Create: `tm-control/backend/tm_control/modules/apps/name_check.py`
- Test: `tm-control/backend/tests/test_name_check.py`

**Interfaces:**
- Produces: `check_name(name: str) -> Literal["unknown_word", "pattern"] | None`, and the frozensets `KNOWN_WORDS`, `ADDRESS_WORDS`, `STREET_ABBREVIATIONS`.

- [ ] **Step 1: Write the failing tests**

```python
"""check_name: what the offline name check says about a name an operator typed."""

import pytest

from tm_control.modules.apps.name_check import ADDRESS_WORDS, KNOWN_WORDS, STREET_ABBREVIATIONS, check_name


@pytest.mark.parametrize("name", [
    "zone_north", "zone_lane_bus", "zone_capture", "zone_near", "zone_far", "zone_radar", "zone_2", "lane_12",
    "zone_a", "Zone_NORTH", "zone-north east", "zone_bus_lane", "zone_main_road", "crosswalk_north", "", "___",
])
def test_a_name_made_of_known_words_passes(name):
    assert check_name(name) is None


@pytest.mark.parametrize("name", ["zone_maple", "zone_nord", "zone_smith", "zone_bergstrasse", "зона_север", "zone_café"])
def test_a_word_the_lists_dont_know_is_a_note(name):
    assert check_name(name) == "unknown_word"


@pytest.mark.parametrize("name", [
    "zone_1420_oak_st", "zone_main_st", "zone_first_ave", "zone_oak_lane", "zone_berg_strasse", "zone_smiths_house",
    "john's_drive", "john’s_drive", "zone_100",
])
def test_what_looks_like_an_address_or_a_person_is_a_warning(name):
    assert check_name(name) == "pattern"


def test_the_lists_are_small_lower_case_and_apart():
    for words in (KNOWN_WORDS, ADDRESS_WORDS, STREET_ABBREVIATIONS):
        assert all(word.isalpha() and word == word.casefold() for word in words)
    assert 150 <= len(KNOWN_WORDS) <= 220
    assert not KNOWN_WORDS & ADDRESS_WORDS
    assert not STREET_ABBREVIATIONS & (KNOWN_WORDS | ADDRESS_WORDS)
```

- [ ] **Step 2: Run them and see them fail**

Run: `python -m pytest tm-control/backend/tests/test_name_check.py -q`
Expected: an import error, `No module named 'tm_control.modules.apps.name_check'`.

- [ ] **Step 3: Write `name_check.py`**

The lists, exactly (each a `frozenset` of these words):

```text
KNOWN_WORDS
zone zones area areas region section segment side sides part line lines point spot box strip edge corner center centre
middle mid whole half full
capture radar near far
north south east west northeast northwest southeast southwest ne nw se sw northbound southbound eastbound westbound
nb sb eb wb
left right top bottom upper lower front back rear inner outer inside outside in out inbound outbound entry exit enter
leave start end first second third last main this that other both all across opposite
lanes roads roadway sidewalk pavement footpath path crosswalk crossing zebra intersection junction roundabout curb kerb
shoulder median island verge driveway entrance parking parked bay stop sign signal light lights yield turn turning merge
ramp bridge tunnel track tracks rail tram busway bikeway cycleway greenway shared mixed travel traffic through thru
oncoming direction flow
car cars truck trucks lorry van vans bus buses bike bikes bicycle bicycles motorcycle motorbike scooter person people
pedestrian pedestrians ped peds cyclist cyclists vehicle vehicles rider riders
count counting counter speed slow fast test temp new old one two three four five six and or of the to from at on by for
with no not school loading delivery taxi

ADDRESS_WORDS
street road lane way drive avenue boulevard court place square circle terrace highway parkway alley trail route row
close crescent grove hill park plaza house home residence apartment flat unit suite building number
strasse weg gasse platz allee rue chemin calle avenida via viale straat laan gata vej

STREET_ABBREVIATIONS
st ave av rd blvd dr ln ct pl hwy pkwy cir ter sq trl rte str apt bldg
```

`check_name(name: str) -> Literal["unknown_word", "pattern"] | None`:

- Words are the runs of letters and the runs of digits in `name.casefold()`: `re.findall(r"[^\W\d_]+|\d+", ...)`. That splits on every separator and between a letter and a digit, and keeps letters of any script.
- A word is known when it is in `KNOWN_WORDS` or `ADDRESS_WORDS`, is a single letter, or is a number of one or two digits.
- `"pattern"` when any of these holds: a number of three or more digits; an apostrophe (`'` or `’`) anywhere in the name; a word in `STREET_ABBREVIATIONS`; a word in `ADDRESS_WORDS` together with a word that isn't known.
- Otherwise `"unknown_word"` when a word isn't known, and `None` when every word is.

The module's docstring says what the check is for, that it warns and never blocks, and that it can't know whether a word is a street's name, which is why an unknown word is only a note.

- [ ] **Step 4: Run the tests and see them pass**

Run: `python -m pytest tm-control/backend/tests/test_name_check.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add tm-control/backend/tm_control/modules/apps/name_check.py tm-control/backend/tests/test_name_check.py
git commit   # subject: Add the offline check of names an operator typed
```

---

### Task 2: A row's other zones, and the issue

**Files:**
- Modify: `tm-control/backend/tm_control/modules/cameras/state.py`
- Modify: `tm-control/backend/tm_control/fake.py` (`frigate_answer`)
- Modify: `tm-control/ui/src/api/openapi.json` (regenerated)
- Test: `tm-control/backend/tests/test_cameras_state.py`

**Interfaces:**
- Consumes: `check_name` from Task 1.
- Produces, for Tasks 3 and 4:
  - `class ZoneName(BaseModel)` with `name: str` and `check: Literal["unknown_word", "pattern"] | None`.
  - `CameraRow.zone_names: list[ZoneName] | None`: the camera's zones other than `ZONES` that are on, in Frigate's order; `None` when the camera isn't in Frigate (as `zones_missing`).
  - `CameraIssue.code` gains `"zone_names"`, always at level `"warn"`.

- [ ] **Step 1: Write the failing tests** (append to `test_cameras_state.py`; `entry` and `ZONES` are its helpers)

```python
def test_other_zones_that_are_on_are_listed_with_what_the_check_found():
    zones = ZONES | {"zone_lane_bus": {}, "zone_maple": {}, "zone_1420_oak_st": {"enabled": True},
                     "zone_old_st": {"enabled": False}}
    [row] = compare([entry("camera_1_3fa9c2", "oak_ave_wide")], {"oak_ave_wide": {"zones": zones}})
    assert [(zone.name, zone.check) for zone in row.zone_names] == [
        ("zone_lane_bus", None), ("zone_maple", "unknown_word"), ("zone_1420_oak_st", "pattern"),
    ]
    assert [(issue.level, issue.code) for issue in row.issues] == [("warn", "zone_names")]


def test_an_unknown_word_alone_is_no_issue():
    cameras = {"oak_ave_wide": {"zones": ZONES | {"zone_maple": {}}}}
    [row] = compare([entry("camera_1_3fa9c2", "oak_ave_wide")], cameras)
    assert row.zone_names[0].check == "unknown_word" and row.issues == []


def test_a_zone_name_raises_no_issue_on_a_camera_that_isnt_recorded():
    cameras = {"oak_ave_wide": {"zones": ZONES | {"zone_main_st": {}}}}

    def codes(row):
        return {issue.code for issue in row.issues}

    [off] = compare([entry("camera_1_3fa9c2", "oak_ave_wide", enabled=False)], cameras)
    assert off.zone_names[0].check == "pattern" and "zone_names" not in codes(off)
    [unpointed] = compare([], cameras)
    assert unpointed.zone_names[0].check == "pattern" and "zone_names" not in codes(unpointed)
    first, second = compare([entry("camera_1_3fa9c2", "oak_ave_wide"), entry("main_st", "oak_ave_wide")], cameras)
    assert "zone_names" in codes(first) and "zone_names" not in codes(second)


def test_zone_names_is_none_without_the_camera_and_empty_for_an_odd_shape():
    [gone] = compare([entry("camera_1_3fa9c2", "oak_ave_wide")], {})
    assert gone.zone_names is None
    for zones in (None, [], "zone_maple", {"zone_capture": None}):
        [row] = compare([entry("camera_1_3fa9c2", "oak_ave_wide")], {"oak_ave_wide": {"zones": zones}})
        assert row.zone_names == []


def test_a_near_miss_of_a_fixed_name_is_another_zone():
    [row] = compare([entry("camera_1_3fa9c2", "oak_ave_wide")], {"oak_ave_wide": {"zones": {"Zone_Capture": {}}}})
    assert "zone_capture" in row.zones_missing
    assert [(zone.name, zone.check) for zone in row.zone_names] == [("Zone_Capture", None)]
```

- [ ] **Step 2: Run them and see them fail**

Run: `python -m pytest tm-control/backend/tests/test_cameras_state.py -q`
Expected: the five new tests fail with `AttributeError` or a validation error on `zone_names`.

- [ ] **Step 3: Change `state.py`**

- Add `ZoneName` and the `zone_names` field with the comments from "Interfaces", and the `"zone_names"` code with a comment in the style of its neighbours: a captured camera has a zone that is on whose name looks like an address or a person's name.
- Add `_zone_names(camera: dict) -> list[ZoneName]` beside `_zones_off`, reading `probes.mapping(camera.get("zones"))`: every key not in `ZONES` whose value's `enabled` is not `False`, as `str(key)`, with `check_name` of it.
- Both `CameraRow(...)` calls in `compare` set `zone_names` (`None` where they set `zones_missing` to `None`).
- `_issues` appends `issue("warn", "zone_names")` under the same condition as the `zones` issue, when any of the row's zone names has `check == "pattern"`.

- [ ] **Step 4: Give fake mode zones to show**

In `fake.frigate_answer`, after `oak_ave_tele` is copied from the first camera, add `zone_lane_bus`, `zone_maple`, and `zone_1420_oak_st` (each `{}`) to the first camera's `zones`, and say so in the docstring. Fake mode's Cameras page then shows the line, the note, and the warning on its recorded camera. Do not change `tests/fixtures/frigate_api_config.json`: the other tests read it.

- [ ] **Step 5: Regenerate `openapi.json`**

Run the `dump-openapi` command from "Commands". Leave `schema.d.ts` for Task 4, so the UI still builds after this task.

- [ ] **Step 6: Run the backend tests**

Run: `python -m pytest tm-control/backend/tests -q`
Expected: all pass. A test that asserts the fake device's camera rows or issues now sees the three zones and the `zone_names` issue; update its expectation, not the code.

- [ ] **Step 7: Commit**

```bash
git add tm-control/backend tm-control/ui/src/api/openapi.json
git commit   # subject: List a camera's other zones on its row, with what the name check found
```

---

### Task 3: The Status check

**Files:**
- Modify: `tm-control/backend/tm_control/modules/apps/contracts.py`
- Modify: `tm-control/backend/tests/fixtures/status_fake.json`
- Modify: `script/devpi/tests/test_web.py` (`CONFIG_CHECKS`)
- Test: `tm-control/backend/tests/test_contract_checks.py`

**Interfaces:**
- Consumes: the rows' `zone_names` issue and `zone_names` list from Task 2, through `_compared`.
- Produces: `zone_names(context: Context) -> list[Check]` with id `config.zone_names` and title `Zone names`, in `GROUP` right after `zones`.

- [ ] **Step 1: Write the failing tests** (in `test_contract_checks.py`)

```python
def add_zones(apps, *names, camera="picam_h265"):
    apps.edit_json(FRIGATE_CONFIG, lambda config: config["cameras"][camera]["zones"].update(dict.fromkeys(names, {})))


def test_zone_names_of_known_and_unknown_words_are_fine(apps):
    add_zones(apps, "zone_lane_bus", "zone_maple")
    check = config_group(apps)["config.zone_names"]
    assert (check.title, check.status, check.fix) == ("Zone names", "ok", None)
    assert check.detail == "No zone name looks like an address or a person's name."


def test_a_zone_name_like_an_address_is_a_warning_that_doesnt_quote_it(apps):
    add_zones(apps, "zone_1420_oak_st")
    check = config_group(apps)["config.zone_names"]
    assert check.status == "warn" and check.fix == contracts.CAMERAS_LINK
    assert check.detail == (
        "1 zone name on camera picam_h265 looks like an address or a person's name. A zone's name is saved with "
        "every event that enters it and shared with the data. The Cameras page shows which; rename it in Frigate."
    )


def test_twenty_zone_names_are_one_count(apps):
    add_zones(apps, "zone_main_st", "zone_first_ave", *[f"zone_{number}00_elm_st" for number in range(1, 19)])
    detail = config_group(apps)["config.zone_names"].detail
    assert detail.startswith("20 zone names on camera picam_h265 look like an address or a person's name.")
    assert detail.endswith("The Cameras page shows which; rename them in Frigate.")
    assert "elm" not in detail and "main_st" not in detail and "first_ave" not in detail


def test_zone_names_of_a_camera_disabled_in_config_yml_arent_checked(apps):
    add_zones(apps, "zone_1420_oak_st")
    apps.edit_config_yml(lambda data: data["sensors"]["cameras"]["picam_h265"].update(enabled=False))
    assert config_group(apps)["config.zone_names"].status == "ok"
```

Also:
- `test_cameras_match`: the ids gain `"config.zone_names"` after `"config.zones"`, and the titles gain `"Zone names"` after `"Zones"`.
- The three tests that make the camera checks `unknown` (Frigate down, safe mode, a YAML error in `config.yml`) assert the new check too, with these details: `"Frigate isn't answering, so the zone names can't be checked."`, `"Frigate is in safe mode, with no cameras, so the zone names can't be checked; see the Frigate check under Apps."`, and `f"{CONFIG_YML_PROBLEM[...]}, so the zone names can't be checked."`.
- One test with two recorded cameras, set up as `test_zones_of_several_cameras_link_to_the_cameras_page` does, asserting the detail starts with `"2 zone names on cameras "` and names both cameras through `listed`.

- [ ] **Step 2: Run them and see them fail**

Run: `python -m pytest tm-control/backend/tests/test_contract_checks.py -q`
Expected: `KeyError: 'config.zone_names'` and the changed lists.

- [ ] **Step 3: Write `zone_names` in `contracts.py`** and add it to `GROUP` after `zones`

It follows `zones`: the same three `unknown` answers with the wording above, then the rows from `_compared`. It counts, over the rows that carry the `zone_names` issue, the zone names whose `check` is `"pattern"`, and collects each such row's `_label`. With none, the `ok` detail above. Otherwise `warn` with `CAMERAS_LINK` and the detail built as in the tests: the count, `name`/`names`, `camera`/`cameras` with `listed(labels)`, `looks`/`look`, the fixed middle sentence, and `it`/`them`. Update the module docstring's list of what details name: zone names are counted, never quoted.

- [ ] **Step 4: Keep the fake Status page and the device test in step**

- `status_fake.json`: add the check after `config.zones`, as the fake cameras from Task 2 would give it: status `warn`, the one-name detail above, and the Cameras page link as the other entries write a link. Raise the summary's `warn` count by one.
- `script/devpi/tests/test_web.py`: add `"config.zone_names"` to `CONFIG_CHECKS` after `"config.zones"`.

- [ ] **Step 5: Run the off-device suites**

Run: `python -m pytest container/node-red-tm/schema/tests script/tests tm-control/backend/tests -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add tm-control/backend script/devpi/tests/test_web.py
git commit   # subject: Add the Zone names check to the Status page
```

---

### Task 4: The Cameras page

Load `frontend-design:frontend-design`, `superpowers:test-driven-development`, and `superpowers:verification-before-completion` first.

**Files:**
- Modify: `tm-control/ui/src/api/schema.d.ts` (regenerated)
- Modify: `tm-control/ui/src/modules/cameras/rows.ts`, `CamerasPage.vue`
- Modify: `tm-control/ui/tests/fake-api.ts` (`cameraRow` gains `zone_names: []`)
- Modify: `tm-control/ui/README.md` (two lines under its design notes)
- Test: `tm-control/ui/tests/camera-rows.spec.ts`, `cameras-page.spec.ts`

**Interfaces:**
- Consumes: `CameraRow.zone_names` and the `zone_names` issue code, from the regenerated schema.
- Produces, in `rows.ts`:
  - `otherZonesText(row: CameraRow): string`
  - `zoneNote(row: CameraRow): { text: string; link: { href: string; text: string } } | null`
  - a `zone_names` entry in `issueBoxes`' `words`.

The copy, exactly (`names` joined with `', '`; the link is `{ href: frigateZonesHref(row), text: 'Edit its zones in Frigate' }`):

| Where | Text |
|---|---|
| `otherZonesText` | `Other zones, saved by name with every event: ${names}` (every name in `zone_names`); `''` when `zone_names` is `null` or empty |
| `zoneNote` | `Zone names with words the Traffic Monitor doesn't know: ${names}. Check that they don't name a street, an address, or a person. Zone names are saved with every event and shared with the data.` (the names whose `check` is `'unknown_word'`); `null` when there are none |
| issue `zone_names` | `Zone names that look like an address or a person's name: ${names}. Zone names are saved with every event and shared with the data. Rename them in Frigate, for example by compass direction (zone_north).` (the names whose `check` is `'pattern'`) |

The maintainer's review of the page in fake mode changed this copy, the zones line ("Recommended zones present: ..."), and the button "Use a neutral name" ("Use a neutral camera name"). `rows.ts` and its tests hold the wording as built.

- [ ] **Step 1: Regenerate the types**

Run `npm run api:generate` in the Node image (see "Commands"). `npm run build` now fails in `rows.ts`: the `words` record has no `zone_names`. That is the failing state this task starts from.

- [ ] **Step 2: Write the failing tests**

In `camera-rows.spec.ts`:

```ts
const ZONE_NAMES = [
  { name: 'zone_lane_bus', check: null },
  { name: 'zone_maple', check: 'unknown_word' as const },
  { name: 'zone_nord', check: 'unknown_word' as const },
  { name: 'zone_1420_oak_st', check: 'pattern' as const },
]

describe('otherZonesText', () => {
  it('is empty without other zones', () => {
    expect(otherZonesText(cameraRow())).toBe('')
    expect(otherZonesText(cameraRow({ zone_names: null }))).toBe('')
  })

  it('lists every other zone', () => {
    expect(otherZonesText(cameraRow({ zone_names: ZONE_NAMES }))).toBe(
      'Other zones, saved by name with every event: zone_lane_bus, zone_maple, zone_nord, zone_1420_oak_st',
    )
  })
})

describe('zoneNote', () => {
  it('is null when every word is known', () => {
    expect(zoneNote(cameraRow({ zone_names: [ZONE_NAMES[0], ZONE_NAMES[3]] }))).toBeNull()
  })

  it('names the zones with unknown words and links to Frigate', () => {
    const note = zoneNote(cameraRow({ zone_names: ZONE_NAMES }))
    expect(note?.text).toBe(
      "Zone names with words the Traffic Monitor doesn't know: zone_maple, zone_nord. Check that they don't name " +
        'a street, an address, or a person. Zone names are saved with every event and shared with the data.',
    )
    expect(note?.link).toEqual({
      href: '/frigate/settings?page=masksAndZones&camera=oak_ave_wide',
      text: 'Edit its zones in Frigate',
    })
  })
})

describe('issueBoxes, zone names', () => {
  it('names the zones that look like an address, as a warning with the link', () => {
    const row = cameraRow({ zone_names: ZONE_NAMES, issues: [{ level: 'warn', code: 'zone_names' }] })
    expect(issueBoxes(row)).toEqual([
      {
        level: 'warning',
        text:
          "Zone names that look like an address or a person's name: zone_1420_oak_st. Zone names are saved with " +
          'every event and shared with the data. Rename them in Frigate, for example by compass direction (zone_north).',
        link: { href: '/frigate/settings?page=masksAndZones&camera=oak_ave_wide', text: 'Edit its zones in Frigate' },
      },
    ])
  })
})
```

In `cameras-page.spec.ts`, mounted the way its other tests mount the page:

- A row with `ZONE_NAMES` and the `zone_names` issue shows one `[data-other-zones]` line with the text above, one `[data-zone-note]` with the note's text and its link, and one `[data-issue]` with the warning.
- A row with no other zones shows neither `[data-other-zones]` nor `[data-zone-note]`.
- A row whose only content is other zones (no issue, no action) still has a body.

- [ ] **Step 3: Run them and see them fail**

Run: `npm test` in the Node image. Expected: the new tests fail; `npm run build` still fails as in Step 1.

- [ ] **Step 4: Write the three functions in `rows.ts`** with a comment on each in the file's style, and add `zone_names: []` to `cameraRow` in `tests/fake-api.ts`.

- [ ] **Step 5: Show them in `CamerasPage.vue`**

Inside the row's body (`<div v-if="hasBody(row)" ...>`), in this order: the issue boxes as now; the note; the Frigate line as now; the other-zones line.

- The note is a `v-alert` with no `type` (the neutral colour), `variant="tonal"`, `density="compact"`, `class="mb-2 text-body-2"`, and `data-zone-note`, with its link written as the issue boxes write theirs.
- The other-zones line is a `div` with `class="text-body-2 text-secondary"` and `data-other-zones`, like the Frigate line.
- Neither is shown while the row's state is `'unknown'`.
- `hasBody` counts both.

- [ ] **Step 6: Build, test, and look at it**

Run the full UI command from "Commands". Expected: the build and every test pass. Then run fake mode (`CLAUDE.md`, "Fake mode") and open the Cameras page at phone and desktop width: the recorded camera shows the amber box, the grey note, and the line, in that order, and the grey note reads as quieter than the amber box. Add two lines to the design notes in `tm-control/ui/README.md` saying what the grey note is and why it has no type.

- [ ] **Step 7: Commit, then stop for the maintainer**

```bash
git add tm-control/ui
git commit   # subject: Show a camera's other zones on the Cameras page, with a note or a warning about their names
```

Stop here and show the maintainer the page in fake mode (screenshots at both widths) before the docs.

---

### Task 5: Docs

**Files:** the eight under "Docs" in the table above.

- [ ] **Step 1: `docs/use/cameras.md`**
  - In the list of what a row shows: **Other zones**, the camera's zones beyond the four, which are saved by name with every event.
  - In "What needs attention", amber: a zone name looks like an address or a person's name. After the list: the grey note, which isn't a problem and doesn't count toward the line above the list.
  - A new section before "What still carries Frigate's name", titled "Zone names are saved with your data": a zone's name is saved with every event that enters it, in the database, the exports, and the upload; name zones for what they are (compass directions, `zone_lane_bus`), not for a street, a house number, or a person; what the grey note and the amber warning mean; the check knows about 200 English words and can't tell whether a word is a street's name, so a name in another language gets the note; to rename a zone, edit it in Frigate, and events already saved keep the old name; the page never changes a zone.
- [ ] **Step 2: `docs/setup-guide.md`**, the paragraph after the zones table ("Zones you draw for your own analysis..."): add that the name is saved with every event and shared with the data, suggest compass names, and link to the new section.
- [ ] **Step 3: `docs/data-and-payloads/events-payload.md`**, the `entered_zones` row: the names are as typed in Frigate; link to the new section.
- [ ] **Step 4: `docs/data-and-payloads/data-overview.md`**: in "The database stops being de-identified if you", add naming a zone after a street, a house number, or a person; in the tables list, the `events` row's last column gains "or a zone name you typed".
- [ ] **Step 5: `docs/use/device-health.md`**: the Configuration row and "The camera checks" gain the **Zone names** check: what it warns about, that it counts names and doesn't show them, and that the Cameras page shows which.
- [ ] **Step 6: `docs/development/tm-control.md`** (beside the paragraph on `state.py::compare`) and `CLAUDE.md` (the cameras bullet under "Cross-component name contracts"): `modules/apps/name_check.py`, `CameraRow.zone_names`, the `zone_names` issue, and the `config.zone_names` check.
- [ ] **Step 7: Build the docs**

Run: `~/.venvs/tm-docs/bin/mkdocs build --strict`
Expected: it builds with no warning. The Cameras page screenshot (`docs/assets/images/cameras-page.png`) is not retaken; say so in the PR's "Docs" section.

- [ ] **Step 8: Commit**

```bash
git add docs CLAUDE.md
git commit   # subject: Document that zone names are saved with every event, and the name check
```

---

### Task 6: Bench, the plan copy, and the text for review

- [ ] **Step 1: Run everything off-device once more** (the three commands under "Commands": pytest, the UI, the docs). All pass.

- [ ] **Step 2: Bench run, logged with `tmdev check`** on a bench unit marked `pii_free`, at the branch head (`script/devpi/README.md`). Deploy with the `tm-control` and `revproxy` tags. Items:
  1. With only the four zones: the Status page's **Zone names** is ok, and the device tests pass (`tmdev.py test <host>`).
  2. In Frigate's zone editor, add `zone_lane_bus`, `zone_maple`, and `zone_1420_oak_st` to the bench camera. This changes zones only; detection, snapshots, and recording stay as they are. The Cameras page shows the line with three names, the grey note naming `zone_maple`, and the amber box naming `zone_1420_oak_st`.
  3. The Status page's **Zone names** is a warning for 1 name, links to the Cameras page, and its text holds no zone name. The line in Copy diagnostics holds none either.
  4. Turn `zone_1420_oak_st` off in Frigate: the amber box goes, the name leaves the line, and **Zone names** is ok.
  5. Delete the three zones. Frigate's `/api/config` (sent with `X-Cache-Bypass: 1`) has only the four for that camera, and **Zone names** is ok. Record the cleanup in the check.

- [ ] **Step 3: The public plan copy.** Copy this plan to `design/plans/2026-11-16-zone-name-check.md`, and commit it last.

- [ ] **Step 4: Write the text, and stop.** Write, for the maintainer to read before anything is pushed:
  - the PR title and body from `.github/PULL_REQUEST_TEMPLATE.md`, against `dev`, with "Refs #306" (it doesn't close the issue: `sub_label` is still to do), the bench check's id, and the template's "Docs" and "AI assistance" sections filled in;
  - a comment for issue 306 saying what was decided for zone names and why: they stay as typed because the Movements page and lane counting use custom names; the names are documented and checked; `sub_label` is handled in a later change.

---

## Review fixes (added 2026-11-16, after the whole-branch review)

The review of `b4a26f1..0e7497a` found three things to fix before the PR. Tasks 7 to 11 are new commits on top of `0e7497a`; no earlier commit is rewritten. Tasks 1 to 6 above stay as they were built.

### What the review found in Frigate

Read from Frigate's source at tag `v0.18.1` (`web/src/components/settings/ZoneEditPane.tsx`, `web/src/components/input/NameAndIdFields.tsx`, `web/src/utils/stringUtil.ts`, `frigate/track/tracked_object.py`). The first bench run added zones through the config API, so it never met this.

- In the zone editor the operator types a **Name**, which Frigate stores as the zone's `friendly_name`. The zone's key (Frigate calls it the ID) is made from the name: lower-cased, with `_` for each run of spaces.
- When the result has a character outside `a-z`, `0-9`, `_`, and `-`, the key is instead `zone_` and 8 hex characters (a hash of the typed name, its first character always a letter). `Bus lane (north)` gives `zone_a9bacc03`.
- `entered_zones` carries the key, never `friendly_name`. `/api/config` gives each zone's `friendly_name`, or null.
- The editor changes the key with the name when a zone is renamed, except while the zone is in a `required_zones` list or a profile overrides it; then only `friendly_name` changes.

So a made-up key is neutral, and `check_name` must not read its hex as a house number: of 20,000 simulated keys, 59% drew the amber warning and 33% the note.

### What changes

1. A key Frigate made up gets no note and no warning, and the page shows Frigate's name beside it so the operator can tell which zone it is.
2. A single character counts as known only when it is ASCII. `北`, `김`, and `李_家` get the note.
3. An ordinal (`1st`, `22nd`, `3rd`, `4th`) is one word. Alone it is known, with the number's rule (three or more digits is still a pattern). Together with an address word it is a pattern, as `zone_5th_street` and `zone_1st_lane` are today.

### Constraints

- The Global Constraints above still hold. `name_check.py` stays a leaf; the made-up-key rule lives in `state.py`, because it is about Frigate, not about names.
- `friendly_name` is shown only on the Cameras page (admins). It never goes into a check's detail, a log line, or anything saved.
- The editor's page shows the camera's picture. Never take or read a screenshot of Frigate's zone editor on a bench unit; the maintainer does the editor steps by hand, and the agent reads `/api/config` and the Cameras page.

### Task 7: Single characters and ordinals in `check_name`

**Files:** `tm-control/backend/tm_control/modules/apps/name_check.py`, `tm-control/backend/tests/test_name_check.py`. Two commits, one per rule, each test-first.

- [ ] **Step 1: Single characters.** Add `"北"`, `"김"`, `"李_家"` to the `unknown_word` test's names; see them fail (`None`). In `_known`, a single letter is known only when `word.isascii()`. Commit: `Count a single letter as known only when it is ASCII`.
- [ ] **Step 2: Ordinals.** Tests first:
  - passes (`None`): `zone_1st`, `zone_2nd`, `zone_3rd`, `zone_4th`, `zone_22ND`
  - `"pattern"`: `zone_1st_lane`, `zone_5th_street`, `zone_3rd_ave`, `zone_100th`, `lane_1st`, `zone_1_st`

  Today `zone_1st` and `zone_3rd` are `"pattern"` and `zone_2nd` and `zone_4th` are `"unknown_word"`; the rest already hold and must keep holding.

  Then the code:
  - `_WORDS` becomes `r"\d+(?:st|nd|rd|th)(?![^\W\d_])|[^\W\d_]+|\d+"`: an ordinal first, then runs of letters, then runs of digits.
  - `_NUMBER = re.compile(r"(\d+)(st|nd|rd|th)?")`, matched with `fullmatch`, gives a word's digits and whether it is an ordinal.
  - A number or an ordinal is known when it has one or two digits, and a pattern when it has three or more.
  - The last pattern rule becomes: an address word together with a word that isn't known **or an ordinal**.

  Update the docstring ("together with", not "beside": the rule isn't adjacency). Commit: `Read an ordinal as one word in the name check`.
- [ ] **Step 3:** `python -m pytest tm-control/backend/tests/test_name_check.py -q` passes.

### Task 8: Zone keys Frigate made up

**Files:** `tm-control/backend/tm_control/modules/cameras/state.py`, `tm-control/backend/tm_control/fake.py`, `tm-control/ui/src/api/openapi.json` (regenerated); tests in `test_cameras_state.py`, `test_contract_checks.py`.

**Interfaces:** `ZoneName` gains `friendly_name: str | None`: Frigate's name for a zone whose key Frigate made up from it; `None` for every other zone.

- [ ] **Step 1: Failing tests** in `test_cameras_state.py`:

```python
def test_a_key_frigate_made_up_is_not_checked_and_carries_frigates_name():
    zones = ZONES | {
        "zone_a6669b83": {"friendly_name": "Main St."},  # made up: three digits in a row, and not an address
        "zone_a9bacc03": {"friendly_name": "Bus lane (north)"},
        "zone_deadbeef": {"friendly_name": None},  # typed by hand: no name beside it, so it is checked
        "zone_a2939495": {"friendly_name": "zone_a2939495"},  # the name is the key: checked
        "1420_oak_st": {"friendly_name": "1420 Oak St"},  # a key made from the name: checked, name not carried
    }
    [row] = compare([entry("camera_1_3fa9c2", "oak_ave_wide")], {"oak_ave_wide": {"zones": zones}})
    assert [(zone.name, zone.check, zone.friendly_name) for zone in row.zone_names] == [
        ("zone_a6669b83", None, "Main St."),
        ("zone_a9bacc03", None, "Bus lane (north)"),
        ("zone_deadbeef", "unknown_word", None),
        ("zone_a2939495", "pattern", None),
        ("1420_oak_st", "pattern", None),
    ]


def test_made_up_keys_alone_raise_no_issue():
    zones = ZONES | {"zone_a6669b83": {"friendly_name": "Main St."}}
    [row] = compare([entry("camera_1_3fa9c2", "oak_ave_wide")], {"oak_ave_wide": {"zones": zones}})
    assert row.issues == []


def test_a_friendly_name_of_an_odd_shape_is_no_name():
    for name in ("", 12, [], {}):
        zones = ZONES | {"zone_a6669b83": {"friendly_name": name}}
        [row] = compare([entry("camera_1_3fa9c2", "oak_ave_wide")], {"oak_ave_wide": {"zones": zones}})
        assert (row.zone_names[0].check, row.zone_names[0].friendly_name) == ("pattern", None)
```

  And in `test_contract_checks.py`, one test: a recorded camera whose only other zone is `zone_a6669b83` with `friendly_name` `"Main St."` leaves `config.zone_names` `ok`, and with `zone_1420_oak_st` beside it the detail counts 1 and holds neither `Main` nor `a6669b83`.

- [ ] **Step 2: `state.py`.** `_MADE_UP = re.compile(r"zone_[0-9a-f]{8}")`, with a comment saying where the shape comes from (Frigate's zone editor, for a name it can't use as a key). In `_zone_names`, a zone is made up when its key `fullmatch`es and its `friendly_name` is a non-empty `str` other than the key; then `check` is `None` and `friendly_name` is carried. Otherwise `check_name(key)` and `friendly_name=None`. Update the `ZoneName` comments.
- [ ] **Step 3: Fake mode.** In `fake.frigate_answer`, the first camera also gets `"zone_a9bacc03": {"friendly_name": "Bus lane (north)"}`; say so in the docstring. The fake Status page's count stays 1.
- [ ] **Step 4:** Regenerate `openapi.json`. Run `python -m pytest tm-control/backend/tests -q`; all pass.
- [ ] **Step 5: Commit:** `Leave zone keys Frigate made up out of the name check, and carry Frigate's name for them`.

### Task 9: Show Frigate's name beside a made-up key

Load the three skills Task 4 names. **Files:** `schema.d.ts` (regenerated), `rows.ts`, `tests/fake-api.ts`, `camera-rows.spec.ts`, `cameras-page.spec.ts`, `tm-control/ui/README.md`.

- [ ] **Step 1:** `npm run api:generate`. `ZONE_NAMES` and every `zone_names` literal in the tests gain `friendly_name: null`.
- [ ] **Step 2: Failing test** in `camera-rows.spec.ts`: with `{ name: 'zone_a9bacc03', check: null, friendly_name: 'Bus lane (north)' }` after `zone_lane_bus`, `otherZonesText` is `Other zones enabled: zone_lane_bus, zone_a9bacc03 ("Bus lane (north)" in Frigate)`, and `zoneNote` is `null`. One page test: the `[data-other-zones]` line shows it.
- [ ] **Step 3:** `otherZonesText` writes a zone with a `friendly_name` as `` `${name} ("${friendly_name}" in Frigate)` ``. Vue's text interpolation escapes it; never use `v-html`. Update the function's comment, and add one line to the README's design note: the key is what is saved, Frigate's name is shown so the operator can find the zone.
- [ ] **Step 4:** The full UI command from "Commands" passes. Retake the two fake-mode screenshots (phone and desktop width) for the PR.
- [ ] **Step 5: Commit:** `Show Frigate's name beside a zone key it made up`. Then show the maintainer the line in fake mode; the wording is theirs to change.

### Task 10: Docs

- [ ] **`docs/use/cameras.md`**, "Zone names are saved with your data":
  - Say what is saved: the zone's ID, which Frigate makes from the name you type (lower case, `_` for spaces), so `1420 Oak St` is saved as `1420_oak_st`.
  - A name with other punctuation, or with letters outside a to z, gets an ID Frigate makes up, such as `zone_a9bacc03`. The page shows your name beside it and doesn't check it, because the ID says nothing about the place.
  - Replace "A name in another language gets the note too" with what is true: a word in another language written in a to z, such as `nord`, gets the note.
  - The amber rule's list: "together with a word the check doesn't recognize, or an ordinal such as `5th`".
  - Renaming: change the zone's name in Frigate and its ID follows. Add the `required_zones` sentence only if bench item 4 shows it.
  - The row list's **Other zones enabled** bullet: mention the name beside a made-up ID.
- [ ] **`docs/development/tm-control.md`** and **`CLAUDE.md`** (the paragraphs Task 5 edited): `ZoneName.friendly_name` and the made-up-key rule, in a clause each.
- [ ] `mkdocs build --strict` passes. **Commit:** `Document zone IDs, and the ones Frigate makes up`.

### Task 11: Bench, the plan copy, and the drafts

- [ ] **Step 1:** The three off-device commands pass at the head.
- [ ] **Step 2: Bench**, a new `tmdev check` on a `pii_free` unit at the head, `-t tm-control -t revproxy`. Record detection, snapshots, and recording before and after; they stay off. Restore the unit's earlier branch after.
  1. Through the config API (as the first run did): add `zone_a9bacc03` with `friendly_name` `Bus lane (north)`, and `zone_3rd`. The Cameras page shows the line with both, the name beside the first, and no note or box; **Zone names** is ok.
  2. **Maintainer, by hand in Frigate's zone editor:** add a zone named `Bus lane (north)` and one named `1420 Oak St`. The agent then reads `/api/config`: the keys are `zone_` plus 8 hex with that `friendly_name`, and `1420_oak_st`. The page shows the first with its name and no note, and the amber box names `1420_oak_st`; **Zone names** warns for 1.
  3. **Maintainer:** rename `1420 Oak St` to `North side` in the editor. The key becomes `north_side`, the box goes, **Zone names** is ok.
  4. **Maintainer, optional:** with a zone listed under `review.alerts.required_zones` (set through the config API; it turns nothing on), the editor doesn't offer to change its ID. If so, add the docs sentence in Task 10; if not, leave it out and say so.
  5. Delete every added zone and the `required_zones` entry. `/api/config` (with `X-Cache-Bypass: 1`) has only the four zones. Record the cleanup.

  If item 2 doesn't give those keys, stop and report: Task 8's rule rests on it.

  The bench run found two things this plan didn't know. In item 2 the editor gave `zone_a647021c` for `Bus lane (north)`, not `zone_a9bacc03`. The key has the shape Task 8 reads, which is all the rule uses. The source's hash is of the typed name alone and gives `zone_a9bacc03` for that name, so why the unit's differed was not found; `zone_a9bacc03` in the docs and tests is only an example. Item 4 showed the `required_zones` behaviour, so its docs sentence is a commit of its own after Task 10's.
- [ ] **Step 3: The public plan copy.** Copy this plan again to `design/plans/2026-11-16-zone-name-check.md`, with the same edits as the first copy, and no blank line at the end of the file. Commit it last: `Add the review fixes to the zone name check's plan`.
- [ ] **Step 4: The drafts**, in the SDD workspace, for the maintainer to read. Nothing is pushed.
  - `pr-body.md`: add a title line; the new behaviour (made-up keys, ordinals, single characters) and the second bench check by its time only; new test counts; the AI section names each model's part, as PR 326's does (Fable 5.2 for the plan and the whole-branch review, the implementing model for the code).
  - Correct two sentences the review found wrong: the docs screenshot shows the old zones line ("Zones: all four") and the old button name; and the pattern rule is "together with", not "next to".
  - `issue-306-comment.md`: one sentence on Frigate's IDs and the made-up ones; "together with".
  - Attach one bench screenshot of the Cameras page, not two: the first run's "phone" file was a copy of the desktop one.

---

## Second review fixes (added 2026-11-16, after the review of Tasks 7 to 11)

The review of `0e7497a..c47d463` found no fault in the code of Tasks 7 to 10. It found one thing the device does that the branch's promise doesn't cover, three sentences to correct, and a rule to tighten. Task 12 is new commits on top of `c47d463`; no earlier commit is rewritten.

### What the review found

Read from Frigate's source at tag `v0.18.1` (`web/src/components/settings/ZoneEditPane.tsx`, `web/src/utils/stringUtil.ts`) and the second bench run's record.

- The zone editor saves with `PUT config/set?cameras.<camera>.zones.<key>.coordinates=…&…friendly_name=<the typed name, URL-encoded>`. The key and the typed name are in the query string; the body holds two flags. nginx's access log (`revproxy.service`) and Frigate's own journal keep the request line, and Copy diagnostics takes the last 50 lines of each unit. The bench found the typed name there (`Oak`, with its capital).
- Frigate replaces a made-up ID's first hex character with `a` when it is a digit, so the shape is `zone_`, a letter `a` to `f`, and 7 hex characters.
- The editor keeps a zone's ID on rename while the zone is in any of six `required_zones` lists (`review.alerts`, `review.detections`, `snapshots`, `mqtt`, `objects.genai`, `onvif.autotracking`) or a profile overrides it.

### Task 12: Diagnostics, the made-up shape, and three sentences

The Global Constraints and the review fixes' constraints still hold. Each code step is test-first.

- [ ] **Step 1: Copy diagnostics.** Files: `tm-control/backend/tm_control/modules/system/diagnostics.py`, `tm-control/backend/tests/test_api_system_info.py`.

  Failing test first, beside `test_diagnostics_replace_frigates_camera_names`, with `host.journal` giving three lines:

  ```python
  host.journal = lambda unit, lines: [
      '192.0.2.10 - - [16/Nov/2026:22:04:11 -0800] "PUT /frigate/api/config/set?cameras.picam_h265.zones.1420_oak_st.'
      'coordinates=0.1,0.2&cameras.picam_h265.zones.1420_oak_st.friendly_name=1420%20Oak%20St HTTP/1.1" 200 61',
      'PUT /api/config/set?cameras.picam_h265.zones.zone_a9bacc03.friendly_name=Bus%20lane%20(north) HTTP/1.1',
      '192.0.2.10 - - [16/Nov/2026:22:04:12 -0800] "GET /frigate/api/stats?fresh=1 HTTP/1.1" 200 512',
  ]
  ```

  The text holds `config/set?<redacted> HTTP/1.1` for both, holds none of `oak_st`, `Oak`, `a9bacc03`, `Bus%20lane`, and still holds `stats?fresh=1`.

  Then the code: in `diagnostics.py`, `_CONFIG_SET = re.compile(r"(config/set\?)\S+")`, with a comment saying why (a change to Frigate's settings carries what it sets in the query string; the zone editor's holds a zone's key and the name typed for it). `build` replaces each match with the group and `REDACTED` (imported from `adapters.redact`) before the other two redactions. Add a sentence to the module docstring.

  Docs in the same commit:
  - `docs/use/device-health.md`, "Download diagnostics": one sentence after the camera names one. What a saved change to Frigate's settings held, such as a zone's name, is replaced too.
  - `docs/development/tm-control.md` (the Copy diagnostics bullet) and `CLAUDE.md` (the zone names sentence of the camera contract): a clause each.

  Commit: `Leave what a change to Frigate's settings held out of Copy diagnostics`.

  Not in this step: Frigate's own pages may put a zone's ID in other query strings (a filter by zone). Those hold the ID, which is saved with the data anyway, never the typed name. Say so in the PR body's limit.
- [ ] **Step 2: The made-up shape.** Files: `tm-control/backend/tm_control/modules/cameras/state.py`, `tm-control/backend/tests/test_cameras_state.py`.

  Add to `test_a_key_frigate_made_up_is_not_checked_and_carries_frigates_name`: `"zone_00001420": {"friendly_name": "Zone 00001420"}` gives `("zone_00001420", "pattern", None)`; see it fail. Then `_MADE_UP = re.compile(r"zone_[a-f][0-9a-f]{7}")`, and its comment says Frigate turns a leading digit into `a`. In `docs/development/tm-control.md` and `CLAUDE.md`, "`zone_` and 8 hex characters" gains "the first a letter". Commit: `Read a made-up zone key's first character as a letter`.
- [ ] **Step 3: Two sentences in `docs/use/cameras.md`.**
  - The amber rule: "…or a street word such as `lane` or `strasse` together with an ordinal such as `5th` or a word the check doesn't recognize." An ordinal alone is not amber.
  - Renaming: "While the zone is on one of the camera's required-zones lists in Frigate (for reviews, snapshots, MQTT, and a few others), or a Frigate profile changes it, Frigate keeps its ID and changes only its name, and the page goes on showing the old ID: take the zone off those lists, rename it, then add it back under its new ID."

  `mkdocs build --strict` passes. Commit: `Correct two sentences about zone names in the Cameras docs`.
- [ ] **Step 4:** The three off-device commands pass at the head; `dump-openapi` and `api:generate` leave no diff.
- [ ] **Step 5: Bench**, only after the maintainer says go: a new `tmdev check` on a `pii_free` unit at the head, `-t tm-control -t revproxy`. Record detection, snapshots, and recording before and after; they stay off. Restore the unit's earlier branch after.
  1. Through the proxy, send the editor's own form of request (the values in the query string) to add one zone with a `friendly_name`. Copy diagnostics shows `config/set?<redacted>` in the `revproxy.service` and `frigate.service` sections, and holds neither the zone's key nor its name.
  2. Delete the zone. `/api/config` (with `X-Cache-Bypass: 1`) has only the four zones. Record the cleanup.

  If the journals' lines don't have the shape Step 1's test assumes, stop and report.
- [ ] **Step 6: The public plan copy.** Copy this plan again to `design/plans/2026-11-16-zone-name-check.md`, with the same edits as before, and no blank line at the end of the file. The copy now carries the corrected bench paragraph in Task 11 Step 2. Commit it last: `Add the second review's fixes to the zone name check's plan`.
- [ ] **Step 7: The drafts**, in the SDD workspace. Nothing is pushed.
  - `pr-body.md`: the diagnostics change (in the summary, "Choices worth a look", Docs, and the bench section if Step 5 ran, by its time only; say so if it didn't run); new test counts and the commit they were run at; the limit gains `zone_3rd_main` and the zone IDs in Frigate's other query strings; the Docs section's "the names are saved as typed" becomes what is true (the ID Frigate makes from the name); the AI section says the plan was drafted at effort xhigh and names the second review.
  - `issue-306-comment.md`: one sentence on Copy diagnostics.
  - Screenshots to attach: `bench-desktop.png`, `cameras-desktop.png`, `cameras-phone.png`. Not the two `bench-added-*.png` files.

---

## Third review fixes (added 2026-11-17, after the review of Task 12)

The review of `c47d463..5c37472` found Task 12 built as planned. It found one request line the new pattern misses, and one kind of log line no request-line pattern can reach. Task 13 is new commits on top of `5c37472`; no earlier commit is rewritten.

### What the review found

Read from `tm-control/backend/tm_control/modules/auth/router.py` and from Frigate's source at tag `v0.18.1` (`frigate/comms/dispatcher.py`, `frigate/__main__.py`, `frigate/config/config.py`, `frigate/api/app.py`).

- **A save sent to the login page.** verify answers a request that has no session with a redirect to `/login?next=` and the original address percent-encoded (`quote(..., safe="/")`). nginx sends it as a 302, and a browser repeats a PUT at the new address. So a zone save pressed after the session ended (a logout in another tab, a changed password, an expired cookie) leaves this in the proxy's access log:

  `"PUT /login?next=/frigate/api/config/set%3Fcameras.<camera>.zones.1420_oak_st.coordinates%3D…%26…friendly_name%3D1420%2520Oak%2520St HTTP/1.1"`

  `config/set%3F` is not `config/set?`, so the zone's ID and the typed name stay in Copy diagnostics.
- **Frigate's own error lines.** They are not request lines, and they hold a zone's ID: a zone on/off command that fails (`Unknown zone: <ID>`), the startup block for a config that doesn't validate (its `Key` line, and three `Message` lines that name a zone), and the traceback of a save Frigate refuses. For a zone that doesn't validate, the startup block's `Value` line can print the whole zone, the typed name included. The Status page's Frigate check quotes the `Message` lines of a safe-mode start. An operator in that state needs those lines read by whoever helps them, so they stay; the PR says so, and a follow-up issue records it.

### Task 13: The encoded address, and what the PR says about Frigate's error lines

The Global Constraints and the review fixes' constraints still hold. The code step is test-first.

- [ ] **Step 1: The encoded address.** Files: `tm-control/backend/tm_control/modules/system/diagnostics.py`, `tm-control/backend/tests/test_api_system_info.py`.

  Failing test first, after `test_diagnostics_leave_out_what_a_change_to_frigates_settings_held`. It takes the redirect from verify itself, so it follows the encoding if verify's ever changes:

  ```python
  def test_diagnostics_leave_out_a_change_to_frigates_settings_sent_to_the_login_page(device_client, login, host):
      """A save made after the session ended is sent to /login?next=<its address, percent-encoded>, and the browser
      repeats the PUT there, so the proxy's access log holds config/set%3F and the encoded query string. It is replaced
      like the plain form, in either letter case and with the slash encoded too."""
      saved = ("/frigate/api/config/set?cameras.picam_h265.zones.1420_oak_st.coordinates=0.1,0.2"
               "&cameras.picam_h265.zones.1420_oak_st.friendly_name=1420%20Oak%20St")
      r = device_client.get("/api/v1/auth/verify", headers={"X-Original-URI": saved, "X-TM-Required-Role": "viewer"})
      assert r.status_code == 401
      redirect = r.headers["X-TM-Redirect"]
      assert redirect.startswith("/login?next=/frigate/api/config/set%3Fcameras.picam_h265.zones.1420_oak_st.")
      host.journal = lambda unit, lines: [
          f'192.0.2.10 - - [17/Nov/2026:09:15:02 -0800] "PUT {redirect} HTTP/1.1" 405 157',
          '192.0.2.10 - - [17/Nov/2026:09:15:03 -0800] "GET /login?next=%2ffrigate%2fapi%2fconfig%2fset%3fcameras.'
          'picam_h265.zones.1420_oak_st.friendly_name%3d1420%2520Oak%2520St HTTP/1.1" 200 612',
          '192.0.2.10 - - [17/Nov/2026:09:15:04 -0800] "GET /frigate/api/config/schema.json HTTP/1.1" 200 2048',
      ]
      login(device_client, *ADMIN)
      text = diagnostics(device_client).text
      assert '"PUT /login?next=/frigate/api/config/set%3F<redacted> HTTP/1.1" 405 157' in text
      assert '"GET /login?next=%2ffrigate%2fapi%2fconfig%2fset%3f<redacted> HTTP/1.1" 200 612' in text
      for held in ("oak_st", "Oak"):
          assert held not in text, held
      assert "GET /frigate/api/config/schema.json HTTP/1.1" in text
  ```

  See it fail on the first `<redacted>` line. Then the code: `_CONFIG_SET = re.compile(r"(config(?:/|%2F)set(?:\?|%3F))\S+", re.IGNORECASE)`. Its comment gains a sentence saying why (a save made without a session is sent to the login page with its address percent-encoded in `next=`), and the module docstring a clause. `build` doesn't change. Both tests pass.

  Docs in the same commit, a clause each: `docs/development/tm-control.md` (the Copy diagnostics bullet) and `CLAUDE.md` (the zone names sentence of the camera contract) say the query string is replaced after `config/set?` and after its percent-encoded form, which a login redirect's `next=` carries. `docs/use/device-health.md` stays as it is.

  Commit: `Replace a percent-encoded config/set address in Copy diagnostics too`.
- [ ] **Step 2:** The three off-device commands pass at the head; `dump-openapi` and `api:generate` leave no diff.
- [ ] **Step 3: Bench**, only after the maintainer says go: a new `tmdev check` on a `pii_free` unit at the head, `-t tm-control -t revproxy`. This run changes nothing in Frigate: the request has no session, so the proxy never passes it on. Record detection, snapshots, and recording, and the camera's zones, before and after; they stay off, and the zones stay the four. Restore the unit's earlier branch after.
  1. Through the proxy, with no session cookie, send the editor's form of request for a zone `1420_oak_st` named `1420 Oak St`. The answer is a 302 whose `Location` is `/login?next=/frigate/api/config/set%3F…`. Send the same PUT to that address, as a browser does (Python's `urllib` won't follow a 302 for a PUT, so the script sends it).
  2. Count, without printing them, the `revproxy.service` journal lines that hold `config/set%3F` and the ID: at least 1. With an admin session, Copy diagnostics shows `config/set%3F<redacted>` for that line and `config/set?<redacted>` for the first request's line, and holds neither the ID nor the name.

  If the `Location` or the journal's line doesn't have the shape Step 1's test assumes, stop and report.
- [ ] **Step 4: The public plan copy.** Copy this plan again to `design/plans/2026-11-16-zone-name-check.md`, with the same edits as before, and no blank line at the end of the file. Commit it last: `Add the third review's fixes to the zone name check's plan`.
- [ ] **Step 5: The drafts**, in the SDD workspace. Nothing is pushed.
  - `pr-body.md`:
    - The Copy diagnostics bullet says the percent-encoded form is replaced too, and when it arises.
    - "Limits" gains: "A line Frigate logs about an error in a zone's settings can name the zone's ID, and for a zone that doesn't validate, the name typed for it. Copy diagnostics keeps those lines, because whoever helps needs them."
    - Testing: the new counts and the commit they were run at; the bench run by its time only if Step 3 ran, and if it didn't, that the third run was at `082c8c3` and what the one later code commit changes.
    - The AI section names the third review and what it found, and no longer says "both" reviews.
  - `issue-306-comment.md`: the Copy diagnostics sentence says what is replaced (what a zone's save held, in the request's plain and percent-encoded forms), not that the diagnostics never carry a zone's name.
  - `followup-issue.md`, new, for the maintainer to file: "Copy diagnostics: Frigate's config-error lines can hold a zone's ID or name". It says which lines (from "What the review found" above), that it was found by reading Frigate's source during an AI-assisted review and not seen on a device, and one way to fix it: replace each zone's `friendly_name` by value, read from Frigate's running config and its config file as the camera names are, which can't cover a name that was renamed away. No device names or addresses.

---

## Fourth review fix (added 2026-11-17, after the review of the whole branch)

The review of `b4a26f1..c1c1d6a` found nothing to fix in the branch's code, tests, or docs. It found one gap that `dev` already has, of the same kind as Task 13's, in how Copy diagnostics replaces Frigate's camera names. Task 14 is new commits on top of `c1c1d6a`; no earlier commit is rewritten.

### What the review found

Read from `tm-control/backend/tm_control/adapters/redact.py` and `tm-control/backend/tm_control/modules/auth/router.py`, and run through `diagnostics.build` in a scratch test.

- verify answers a request that has no session with a redirect to `/login?next=` and the original address percent-encoded (`quote(..., safe="/")`). For Frigate's settings page of one camera, which is where the Cameras page's "Edit its zones in Frigate" links go, that is:

  `/login?next=/frigate/settings%3Fpage%3DmasksAndZones%26camera%3Doak_ave_wide`

- `redact_words` replaces a camera name only where no letter, digit, or underscore stands directly before it. The `D` of `%3D` is a letter, so the name stays. The plain request line (`camera=oak_ave_wide`) is replaced, and so is a name in the path (`/frigate/api/oak_ave_wide/latest.webp`), because `/` stays unencoded.
- So an admin whose session ended, who follows that link from a stale Cameras page or opens a bookmark to Frigate's settings or review for one camera, leaves Frigate's name for the camera in the proxy's access log in a form Copy diagnostics keeps.
- The UI's router, when it rewrites `next`, writes `=` plain, so its forms were already replaced.
- This branch adds two more of those links (the grey note and the zone names box), and `5804df5` fixed the same redirect for zone names, which is why the fix is taken here.

### Task 14: A camera name after a percent escape

The Global Constraints and the review fixes' constraints still hold. The code step is test-first. Both tests below were tried on a scratch copy at `c1c1d6a`: they fail there, and pass with Step 2's one-line change.

- [ ] **Step 1: The failing tests.** Files: `tm-control/backend/tests/test_redact.py`, `tm-control/backend/tests/test_api_system_info.py`.

  In `test_redact.py`, after `test_redact_words_prefers_the_longest_and_ignores_empty_words`:

  ```python
  def test_redact_words_reads_a_percent_escape_as_an_edge():
      line = '"GET /login?next=/frigate/settings%3Fpage%3DmasksAndZones%26camera%3Doak_ave_wide HTTP/1.1" 200 612'
      assert redact_words(line, ["oak_ave_wide"]) == line.replace("oak_ave_wide", "<redacted>")
      assert redact_words("next=%2ffrigate%2freview%3fcameras%3doak_ave_wide%26zones%3dx", ["oak_ave_wide"]) == (
          "next=%2ffrigate%2freview%3fcameras%3d<redacted>%26zones%3dx"
      )
      # Not an escape: a letter and a digit before the name, without the percent sign
      assert redact_words("A3Doak_ave_wide %3Doak_ave_wide_2", ["oak_ave_wide"]) == "A3Doak_ave_wide %3Doak_ave_wide_2"
  ```

  In `test_api_system_info.py`, after `test_diagnostics_replace_frigates_camera_names`. It takes the redirect from verify itself, as Task 13's test does:

  ```python
  def test_diagnostics_replace_a_camera_name_in_a_login_redirect(device_client, login, host, tmp_path, monkeypatch):
      """A page asked for after the session ended is sent to /login?next=<its address, percent-encoded>, so the proxy's
      access log holds Frigate's name for the camera after %3D. It is replaced like the plain form."""
      config_dir = tmp_path / "nr"
      config_dir.mkdir()
      config = config_dir / "config.yml"
      config.write_text(
          "sensors:\n  cameras:\n    camera_1_3fa9c2:\n      frigate_camera: oak_ave_wide\n      enabled: true\n"
      )
      device_client.app.state.config_path = config
      monkeypatch.setattr(frigate, "config", lambda: {"cameras": {"oak_ave_wide": {"enabled": True}}})
      page = "/frigate/settings?page=masksAndZones&camera=oak_ave_wide"
      r = device_client.get("/api/v1/auth/verify", headers={"X-Original-URI": page, "X-TM-Required-Role": "viewer"})
      assert r.status_code == 401
      redirect = r.headers["X-TM-Redirect"]
      assert redirect == "/login?next=/frigate/settings%3Fpage%3DmasksAndZones%26camera%3Doak_ave_wide"
      host.journal = lambda unit, lines: [
          f'192.0.2.10 - - [17/Nov/2026:10:02:11 -0800] "GET {page} HTTP/1.1" 302 145',
          f'192.0.2.10 - - [17/Nov/2026:10:02:11 -0800] "GET {redirect} HTTP/1.1" 200 612',
      ]
      login(device_client, *ADMIN)
      text = diagnostics(device_client).text
      assert '"GET /frigate/settings?page=masksAndZones&camera=<redacted> HTTP/1.1" 302 145' in text
      assert '"GET /login?next=/frigate/settings%3Fpage%3DmasksAndZones%26camera%3D<redacted> HTTP/1.1" 200 612' in text
      assert "oak_ave_wide" not in text
  ```

  Run `python -m pytest tm-control/backend/tests/test_redact.py tm-control/backend/tests/test_api_system_info.py -q` and see both fail: the first on its first line, the second on the `/login?next=` line.
- [ ] **Step 2: The code.** File: `tm-control/backend/tm_control/adapters/redact.py`, `redact_words` only.

  The left edge becomes `(?:(?<![{_WORD_EDGE}])|(?<=%[0-9A-Fa-f]{{2}}))` in place of `(?<![{_WORD_EDGE}])` (the braces doubled because the pattern is an f-string). The right edge and the rest stay. Its docstring gains a sentence: a percent escape directly before a word counts as an edge too, because an escape ends in a letter or a digit, and a login redirect's `next=` holds a camera's name after `%3D`. `diagnostics.py` doesn't change. Both tests pass, and so does the rest of `test_redact.py`.

  Docs in the same commit: `docs/development/tm-control.md`, the Copy diagnostics bullet, one clause after "(whole words, longest first)": a percent escape before a name counts as an edge, so a name in a login redirect's `next=` is replaced too. `CLAUDE.md` and `docs/use/device-health.md` stay as they are: they say the names are replaced, which is now true of this form too.

  Commit: `Replace a Frigate camera name after a percent escape in Copy diagnostics`.

  Not in this step: a name directly after another kind of escape, such as nginx's `\x22` for a raw quote or a `\n` inside a printed string. No request a browser sends puts one there.
- [ ] **Step 3:** The three off-device commands pass at the head (expected: 3092 passed, 1 skipped; UI 591; `mkdocs build --strict` clean); `dump-openapi` and `api:generate` leave no diff.
- [ ] **Step 4: Bench: none is planned.** `redact_words` is a function of text, its test takes the redirect from verify, and the fourth bench run already showed that the proxy's journal keeps a login redirect's line in this shape. A bench unit can show the replacement only if it has a camera whose name in Frigate differs from its entry's key; never change a unit's cameras to make one. If the maintainer asks for a run anyway, it is a new `tmdev check` at the head with `-t tm-control -t revproxy`, the device tests, detection, snapshots, and recording read before and after, and the unit's earlier branch restored.
- [ ] **Step 5: The public plan copy.** Copy this plan again to `design/plans/2026-11-16-zone-name-check.md`, with the same edits as before, and no blank line at the end of the file. Commit it last: `Add the fourth review's fix to the zone name check's plan`.
- [ ] **Step 6: The drafts, then stop.** In the SDD workspace. Nothing is pushed, and the PR's body on GitHub is not changed, until the maintainer has read the two commits and the draft.
  - `pr-body.md` (start from the PR's body as posted, `gh pr view 332 --json body`, which has two mentions of the follow-up issue the draft lacks):
    - The release note's last sentence gains: "and it now replaces a Frigate camera name inside a login redirect too."
    - The Copy diagnostics bullet gains: "The same redirect holds Frigate's name for a camera after `%3D` (`…camera%3D<name>`), which the camera-name replacement on `dev` missed because it took the escape's last character for part of a word; a percent escape now counts as a word's edge."
    - Docs: `docs/development/tm-control.md` gains the clause.
    - Testing: the new counts and the commit they were run at; one sentence saying the head is one code commit past the fourth bench run and what that commit changes (one pattern in `redact_words`, no bench run, and why).
    - The screenshots line becomes "Screenshots are in the first comment." and its hidden `attach:` comment goes.
    - The AI section names the fourth review (of the whole branch at `c1c1d6a`): it found nothing to fix in the branch and this gap on `dev`, fixed in the new commit. "The three whole-branch reviews" becomes four.
  - `issue-306-comment.md` and `followup-issue.md` stay as they are.
