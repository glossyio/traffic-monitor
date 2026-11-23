# Event Fields and the Field Rule Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Each event row also holds the object's path, its boxes, Frigate's own speed, and the unit and source of `speed_calc`; a camera with no radar gets a direction and, where a speed zone is drawn, a speed; `sub_label` keeps only vetted values; and one tested list decides which event fields are saved and which are uploaded.

**Architecture:** All of it is in the Node-RED flows, a new migration, and one new JSON file. Two small function nodes at the head of the `capture-events` chain vet `sub_label` and turn Frigate's message into the new fields while Frigate's camera name is still on it. The existing direction and speed nodes are corrected in place, and "event finalize output" chooses the speed. The upload gate's lists move out of its function into `upload-lists.json`, which `settings.js` loads, and the gate gains a list of event fields. One test ties the finalize keys, the INSERT, its parameters, the schema, and the upload list together.

**Tech Stack:** Node-RED 5.0.8 function nodes (JavaScript in `flows.json`), SQLite migrations run by `tmdb_migrate.py`, pytest with the function-node harness in `script/tests/test_node_red_flows.py`, Ansible (one copy-loop entry), Vue (one example on the Sharing page), MkDocs.

**Spec:** "What it must do" below.

**Repo:** `glossyio/traffic-monitor`, branch `feature/event-fields/336` off `feature/sharing-page/314` (PR 321, `4eb6ed6` when this was written), in its own worktree, as a PR stacked on PR 321. If PR 321 has merged by the time work starts, branch from `dev` instead. All paths below are relative to the repo root.

## What it must do

1. **Path.** `events.path_data` holds Frigate's `path_data` as sent: a JSON list of `[[x, y], t]` points, capped at 100 points. Only points that are three finite numbers are kept.
2. **Boxes.** `events.box` (last frame) and `events.best_box` (best frame, `snapshot.box`) hold `[left, top, width, height]` as fractions of the frame. `events.best_frame_time` holds `snapshot.frame_time`.
3. **Frigate's facts.** Node-RED reads two facts from Frigate's `/api/config` and keeps them in memory: each camera's detect width and height, and `ui.unit_system`. It reads them when it starts, when Frigate comes back (`frigate/available`), and every ten minutes. An event saved before the first read gets no boxes and no Frigate unit.
4. **Frigate's speed.** `frigate_speed`, `frigate_speed_unit` (`kph` or `mph`), and `frigate_velocity_angle` hold Frigate's average estimated speed, its unit, and its angle, raw, whether or not the radar gave a speed. Frigate sends 0 when it made no estimate; that is stored as empty.
5. **`speed_calc` falls back to Frigate's speed** when the radar gave none, converted to the device's speed unit, signed like the radar's (negative for outbound, positive otherwise). `speed_unit` names the unit of `speed_calc`, `speed_source` is `radar` or `frigate`, and `radar_readings` is how many radar readings stand behind a radar speed. All three are empty when there is no speed (`radar_readings` also when the speed is Frigate's).
6. **The device's speed unit** is the unit its radar reports. Node-RED remembers the last unit seen for each radar and assumes `mph` until a reading arrives. A device with no enabled radar uses Frigate's unit.
7. **A camera with no enabled radar gets its direction from the zones** (issue 243). Today both direction and speed need a radar.
8. **A speed of exactly 0 from the radar is a speed.** Two nodes treat it as none today.
9. **`sub_label` is a vetted field.** A value is kept only when it is exactly one of Frigate 0.18.1's built-in logo labels: `amazon`, `an_post`, `canada_post`, `dhl`, `dpd`, `fedex`, `gls`, `nzpost`, `postnl`, `postnord`, `purolator`, `royal_mail`, `ups`, `usps`. Frigate sends `[text, score]`; the text is kept and the score is not. Anything else is dropped at one node. Rows already written keep what they have.
10. **`attributes` and `entered_zones` stay as they are.**
11. **The upload gate lists event fields.** An event field uploads only when it is on the list, and the gate's lists live in a file later changes can add a line to. This change uploads all ten new fields.
12. **The field rule has a test.** The finalize keys, the INSERT's columns and parameters, the `events` table, and the upload list can't drift apart without a test failing.
13. **The speed statistics use `speed_calc`,** so they include Frigate's speed, and they say how many speeds came from each source.
14. **The migration only adds columns.** Nothing is rewritten.
15. **Docs and the sharing notice** say what is recorded and what is sent, in the same PR.

Not in this change: the gate comparing the accepted notice version with the version a field arrived in (needed by the release, not on `dev`); any store for the sub-labels that are dropped; Frigate's timeline; a change to which events are recorded or counted.

## Global Constraints

- `flows.json` is edited by a script and written back with `json.dumps(flows, indent=4, ensure_ascii=False)` and no trailing newline. `test_flows_json_round_trips_through_json_dumps` must keep passing.
- Existing nodes keep their ids. A new node gets a new 16-hex id, sits in a group on its tab (in the group's `nodes` list, with `x`/`y` inside the group's box, the box widened if needed), and is found by name in tests.
- Function nodes run in Node-RED's sandbox: no `structuredClone`, no `fetch`. The test harness enforces this.
- No log line, warning, or status text holds a `sub_label` value, a path, a box, or a host. Warnings name keys and units only, once per config load through `tm_warned`, as the upload gate does.
- Frigate's camera name stays where it is today plus one place: the `frigate_facts` flow context on `capture-events`. No message that leaves "append config, deployment properties" carries it (`test_append_config_records_the_key_not_frigates_name` keeps passing).
- The upload gate fails closed: when its lists can't be read it sends nothing.
- Every new column is numbers, a JSON list of numbers, or one of a fixed set of words (`kph`, `mph`, the radar's unit, `radar`, `frigate`).
- The migration is `ALTER TABLE ... ADD COLUMN` only, numbered `0003`. Never edit `0001` or `0002`.
- Docs ride with the code and follow "Writing docs" in `docs/development/contributing.md`. `mkdocs build --strict` must pass.
- On a bench unit this change publishes made-up `frigate/events` messages on the device's broker, which turn nothing on. Never turn on Frigate's detection, snapshots, or recording.
- Commit messages end with the trailer block in the repo's `CLAUDE.md`. No device names or addresses in commits or PR text.
- Nothing is pushed. The maintainer reads the commits and the PR text first.
- Open PRs that touch the same files: PR 326 (stacked on PR 321) adds a key to `functionGlobalContext` in `settings.js`, appends to `script/tests/test_node_red_flows.py`, and edits `docs/data-and-payloads/data-overview.md` and `CLAUDE.md`; it changes no node this plan changes. PR 332 edits one row of `docs/data-and-payloads/events-payload.md` (`entered_zones`), `data-overview.md`, `docs/setup-guide.md`, and `CLAUDE.md`. PR 333 adds lines to `settings.js` and `CLAUDE.md`. If one merges first, merge it in and keep both sides. If another migration merges first, renumber this one and regenerate `schema.sql`.

## Review Focus

Inputs the requirements imply and a person will meet; each has a test in the task named.

1. A recognized person's or known plate's name as the sub-label (`["Jane Doe", 0.97]`): it reaches no row, no dashboard message, and no upload, and no log line quotes it. Task 4.
2. Node-RED starts before Frigate, or Frigate answers 500: events are still saved, with no boxes, no Frigate unit, and no fallback speed; never a pixel box or a speed under the wrong unit. Tasks 5, 6, and 8.
3. A path of thousands of points, or one holding something that isn't a number: at most 100 points, first and last kept, numbers only. Task 6.
4. A radar median of exactly 0, and Frigate's 0: the first is a speed, the second is no estimate. Tasks 6, 7, and 8.
5. `upload-lists.json` missing, unreadable, or in the wrong shape on a device: nothing is uploaded, with one warning, and Node-RED still starts. Task 2.

## Files

| File | Change |
|---|---|
| `container/node-red-tm/schema/migrations/0003_event_fields.sql` | New: ten `ADD COLUMN` statements |
| `container/node-red-tm/schema/schema.sql` | Regenerated |
| `container/node-red-tm/data/upload-lists.json` | New: the upload gate's three lists (`telemetry`, `attributes`, `event`) |
| `container/node-red-tm/data/settings.js` | `functionGlobalContext.upload_lists`, loaded from the file, `null` when it can't be read |
| `script/ansible/roles/tmsetup/tasks/node-red-tm_setup.yml` | The file joins the static-files copy loop |
| `container/node-red-tm/data/flows.json` | Changed nodes: `ae3349867027d005` (upload gate), `a96d834e3571c549` (write params for events insert), `61d6a19c99c60e0b` (the INSERT), `a8aeffd2e5bc17f2` (event finalize output), `c123fc5ed5e14e8a` (calculate median per direction), `673e45159a2dfccf` (match radar speed to event, assign direction), `1acba66197b7b0fa` (write params for radar_dov insert), `584504e6c8935eaf` (the car speed statistics query), `76911cc7f28e7da2` (rewired). New nodes on `capture-events`: "vet sub_label", "frigate fields", and the group "frigate facts" (an inject, an `mqtt in`, a switch, an `http request`, "keep frigate facts") |
| `tm-control/backend/tm_control/modules/sharing/NOTICE.md` | What "Share data" sends (the maintainer's wording) |
| `tm-control/ui/src/modules/sharing/examples.ts` | The Share data example gains new fields |
| `script/devpi/tests/devpi_checks.py`, `test_disruptive.py`, `script/devpi/README.md` | A helper that publishes a made-up event on the Pi, and one device test |
| Tests | `container/node-red-tm/schema/tests/helpers.py`, `test_0003_event_fields.py` (new), `script/tests/test_node_red_flows.py`, `test_node_red_settings.py`, `test_tmsetup_tasks.py`, `tm-control/ui/tests/` where the example is pinned |
| Docs | `docs/data-and-payloads/events-payload.md`, `object-paths.md` (new), `data-overview.md`, `integrations.md`, `docs/use/sharing.md`, `docs/ui/monitoring.md`, `docs/get-started/how-it-works.md`, `docs/configuration/frigate-config.md`, `docs/development/tm-control.md`, `mkdocs.yml`, `container/node-red-tm/data/README.md`, `CLAUDE.md` |

## Commands

```bash
. .venv/bin/activate                                   # the dev venv from CLAUDE.md, in the same shell call
python -m pytest container/node-red-tm/schema/tests -q
python -m pytest script/tests/test_node_red_flows.py script/tests/test_node_red_settings.py -q
python -m pytest container/node-red-tm/schema/tests script/tests tm-control/backend/tests -q   # everything off-device
python3 container/node-red-tm/schema/tmdb_migrate.py --dump-schema > container/node-red-tm/schema/schema.sql
podman run --rm -v "$PWD/tm-control/ui:/ui:Z" -w /ui docker.io/library/node:22.23.4-alpine sh -c 'npm ci && npm run build && npm test'
~/.venvs/tm-docs/bin/mkdocs build --strict
```

The flows tests need `node` on the path; without it they skip, and CI fails a skip.

## Names used across tasks

| Name | What it is |
|---|---|
| `EVENT_COLUMNS` (tests) | The event's fields in order: today's twenty, then `path_data`, `box`, `best_box`, `best_frame_time`, `frigate_speed`, `frigate_speed_unit`, `frigate_velocity_angle`, `speed_unit`, `speed_source`, `radar_readings` |
| `global.upload_lists` | `{telemetry: [...], attributes: [...], event: [...]}`, from `upload-lists.json` |
| `flow.frigate_facts` (`capture-events`) | `{unit_system: "metric" \| "imperial" \| null, detect: {<Frigate camera name>: {width, height}}}` |
| `msg.frigate_fields` | `{path_data, box, best_box, best_frame_time, frigate_speed, frigate_speed_unit, frigate_velocity_angle}`, each `null` when there is none |
| `msg.radar_reading_counts` | `{<direction>: <number of radar_dov rows>}`, beside the medians |
| `msg.event_direction_speed.calc_radar_readings` | The count for the direction the speed was taken from |
| `global.radar_units` | `{<radar name>: <last unit seen>}` |

The chain on `capture-events` after this change: `set frigate_event from payload.after` → **vet sub_label** → **frigate fields** → `append config, deployment properties` → the rest as today.

---

### Task 1: The migration

**Files:**
- Create: `container/node-red-tm/schema/migrations/0003_event_fields.sql`, `container/node-red-tm/schema/tests/test_0003_event_fields.py`
- Modify: `container/node-red-tm/schema/schema.sql`, `container/node-red-tm/schema/tests/helpers.py`

**Interfaces:**
- Produces: the ten columns on `events`, in the order of `EVENT_COLUMNS`; `LATEST_VERSION = 3`.

- [ ] **Step 1: Write the failing test**

```python
"""0003 adds the event fields: columns only, and the rows already there are left as they are."""

import sqlite3

from helpers import LATEST_VERSION, SCHEMA_DIR, columns, migrate, query, user_version

NEW_COLUMNS = {
    "path_data": "TEXT", "box": "TEXT", "best_box": "TEXT", "best_frame_time": "REAL", "frigate_speed": "REAL",
    "frigate_speed_unit": "TEXT", "frigate_velocity_angle": "REAL", "speed_unit": "TEXT", "speed_source": "TEXT",
    "radar_readings": "INTEGER",
}


def at_version_2(tmp_path):
    """A database migrated through 0002 only, with one event that has a radar speed."""
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    for name in ("0001_baseline.sql", "0002_deployment_survey.sql"):
        (migrations / name).write_text((SCHEMA_DIR / "migrations" / name).read_text())
    db_path = tmp_path / "tmdb.sqlite"
    assert migrate("--db", db_path, "--migrations", migrations) == 0
    con = sqlite3.connect(db_path)
    con.execute("INSERT INTO events (id, camera, label, sub_label, speed_calc) VALUES (?, ?, ?, ?, ?)",
                ("1761800000.1-abc123", "camera_1_3fa9c2", "car", "a name from before", 22.5))
    con.commit()
    con.close()
    return db_path


def test_0003_adds_the_columns_and_rewrites_nothing(tmp_path):
    db_path = at_version_2(tmp_path)
    assert user_version(db_path) == 2
    assert migrate("--db", db_path, "--backup-dir", tmp_path / "backup") == 0
    assert user_version(db_path) == LATEST_VERSION == 3
    assert columns(db_path, "events")[-len(NEW_COLUMNS):] == list(NEW_COLUMNS)
    types = {row[1]: row[2] for row in query(db_path, "PRAGMA table_info(events)")}
    assert {name: types[name] for name in NEW_COLUMNS} == NEW_COLUMNS
    assert query(db_path, "SELECT sub_label, speed_calc, speed_unit, speed_source, path_data FROM events") == [
        ("a name from before", 22.5, None, None, None)]
```

- [ ] **Step 2: Run it and see it fail**

Run: `python -m pytest container/node-red-tm/schema/tests/test_0003_event_fields.py -q`
Expected: FAIL, `assert 2 == 3` (there is no `0003`).

- [ ] **Step 3: Write the migration.** Ten statements, `ALTER TABLE events ADD COLUMN <name> <type>;`, in the order and with the types of `NEW_COLUMNS`, under a comment that says what the columns are and that rows written earlier keep them empty. No `BEGIN`, `COMMIT`, or `PRAGMA`.

- [ ] **Step 4: Set `LATEST_VERSION = 3` in `helpers.py` and regenerate `schema.sql`** with the command under "Commands".

- [ ] **Step 5: Run the schema suite**

Run: `python -m pytest container/node-red-tm/schema/tests -q`
Expected: all pass, including `test_schema_sql_matches_the_migrations`.

- [ ] **Step 6: Check the control app's fake mode.** Run `python -m pytest tm-control/backend/tests -q`. If a test now reports the fake unit's schema as behind, raise `SCHEMA_VERSION` in `tm-control/backend/tm_control/fake.py` to 3 and say so in the commit.

- [ ] **Step 7: Commit**

```bash
git add container/node-red-tm/schema tm-control/backend
git commit   # subject: Add the event field columns to tmdb (migration 0003)
```

---

### Task 2: The upload lists move to a file, and the gate lists event fields

**Files:**
- Create: `container/node-red-tm/data/upload-lists.json`
- Modify: `container/node-red-tm/data/settings.js`, `container/node-red-tm/data/flows.json` (`ae3349867027d005`), `script/ansible/roles/tmsetup/tasks/node-red-tm_setup.yml`
- Test: `script/tests/test_node_red_flows.py`, `script/tests/test_node_red_settings.py`, `script/tests/test_tmsetup_tasks.py`

**Interfaces:**
- Produces: `upload-lists.json` with exactly the keys `telemetry`, `attributes`, `event`, each a list of strings, one name per line; `global.get("upload_lists")` in every function node.
- `event` holds today's twenty fields here; Task 8 adds ten.

- [ ] **Step 1: Write the failing tests** in `test_node_red_flows.py`. Add near the gate's constants:

```python
UPLOAD_LISTS = FLOWS.parent / "upload-lists.json"
EVENT_COLUMNS = [
    "id", "camera", "label", "sub_label", "top_score", "frame_time", "start_time", "end_time", "entered_zones",
    "score", "area", "ratio", "motionless_count", "position_changes", "attributes", "direction_calc", "speed_calc",
    "provenance", "deployment_id", "radarName",
]
KEPT_ON_THE_UNIT = set()  # event fields that are saved and never uploaded; adding one is a decision
LISTS_WARNING = "ThingsBoard upload: the lists of what is shared didn't load, so nothing is sent."


def upload_lists():
    return json.loads(UPLOAD_LISTS.read_text())
```

`gate_run` and `gate` take one more argument, `lists=MISSING`, and put `upload_lists()` (or `lists` when given; nothing when it is `None`) in the context as `upload_lists`. Replace `test_gate_lists` with:

```python
def test_upload_lists_file():
    lists = upload_lists()
    assert list(lists) == ["telemetry", "attributes", "event"]
    assert lists["telemetry"] == ["event", "radar", "airquality", "system_metrics", "deployments"]
    assert lists["attributes"] == ["deployments", "radarinfo", "sysinfo_tmVersion", "sysinfo_osHostname",
                                   "sysinfo_osRelease", "sysinfo_osTimeZone", "sysinfo_deviceName",
                                   "sysinfo_frigateVersion"]
    assert lists["event"] == [name for name in EVENT_COLUMNS if name not in KEPT_ON_THE_UNIT]
    assert all(len(names) == len(set(names)) for names in lists.values())
    # one name per line, so two changes that each add a field merge without touching the same line
    assert all(line.count('"') <= 2 for line in UPLOAD_LISTS.read_text().splitlines())


def test_the_gate_holds_no_list_of_its_own():
    func = gate_node()["func"]
    assert 'global.get("upload_lists")' in func
    assert "const TELEMETRY" not in func and "const ATTRIBUTES" not in func and '"sysinfo_tmVersion"' not in func


@needs_node
@pytest.mark.parametrize("lists", [
    None, {}, [], "event", {"telemetry": ["event"], "attributes": []},
    {"telemetry": "event", "attributes": [], "event": []},
    {"telemetry": ["event"], "attributes": [], "event": ["id", 7]},
], ids=["missing", "empty", "list", "text", "no-event-list", "telemetry-not-a-list", "a-name-that-is-not-text"])
def test_gate_sends_nothing_without_readable_lists(lists):
    msgs = [{"type": "telemetry", "payload": {"ts": TS, "values": {"event": GATE_TELEMETRY["event"]}}},
            {"type": "attributes", "payload": {"sysinfo_tmVersion": "0.9.0"}}]
    run = gate_run(msgs, lists=lists)
    assert [step["result"] for step in run["results"]] == [None, None]
    assert [entry for step in run["results"] for entry in step["logged"]] == [["warn", LISTS_WARNING, False]]
    assert run["global"]["tm_warned"] == {"upload:lists": True}


@needs_node
def test_gate_keeps_only_the_listed_event_fields():
    event = {**GATE_TELEMETRY["event"], "surprise": "kept-on-the-unit"}
    item = {"type": "telemetry", "payload": {"ts": TS, "values": {"event": event}}}
    run = gate_run([item, item])
    for step in run["results"]:
        assert step["result"]["payload"] == {"ts": TS, "values": {"event": GATE_TELEMETRY["event"]}}
    warnings = [text for step in run["results"] for _, text, _ in step["logged"]]
    assert warnings == ["ThingsBoard upload: left out event.surprise, which isn't on the list of what is shared."]
    assert "kept-on-the-unit" not in json.dumps(run["results"])
    assert run["global"]["tm_warned"] == {"upload:event.surprise": True}


@needs_node
@pytest.mark.parametrize("event", ["text", ["id"], None, 7, {"surprise": 1}],
                         ids=["text", "list", "null", "number", "no-listed-field"])
def test_gate_leaves_out_an_event_it_cannot_read(event):
    radar = GATE_TELEMETRY["radar"]
    out, _ = gate({"type": "telemetry", "payload": {"ts": TS, "values": {"event": event, "radar": radar}}})
    assert out["payload"] == {"ts": TS, "values": {"radar": radar}}
    out, _ = gate({"type": "telemetry", "payload": {"ts": TS, "values": {"event": event}}})
    assert out is None
```

In `test_node_red_settings.py`:

```python
@needs_node
def test_settings_load_the_upload_lists():
    out = run_node("console.log(JSON.stringify(s.functionGlobalContext.upload_lists));")
    assert json.loads(out) == json.loads((SETTINGS.parent / "upload-lists.json").read_text())


@needs_node
def test_settings_survive_a_missing_or_broken_upload_lists_file(tmp_path):
    """Node-RED must still start; the upload gate then sends nothing."""
    for name, content in (("missing", None), ("broken", "{not json")):
        folder = tmp_path / name
        folder.mkdir()
        (folder / "settings.js").write_text(SETTINGS.read_text())
        if content is not None:
            (folder / "upload-lists.json").write_text(content)
        result = subprocess.run(
            ["node", "-e", f"const s = require({json.dumps(str(folder / 'settings.js'))});\n"
                           "console.log(JSON.stringify(s.functionGlobalContext.upload_lists));"],
            capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "null"
```

In `test_tmsetup_tasks.py`, with that file's way of loading a task file: the task "TMSetup - Node-RED-TM Setup - Copy relevant static files for node red deployment" lists `node-red-tm/data/upload-lists.json` in its loop.

- [ ] **Step 2: Run them and see them fail**

Run: `python -m pytest script/tests/test_node_red_flows.py script/tests/test_node_red_settings.py script/tests/test_tmsetup_tasks.py -q`
Expected: the new tests fail (`upload-lists.json` doesn't exist), and the existing gate tests pass.

- [ ] **Step 3: Write `upload-lists.json`** with the three lists from `test_upload_lists_file`, indented four spaces, one name per line, ending in a newline.

- [ ] **Step 4: Load it in `settings.js`.** Add `upload_lists` to `functionGlobalContext`: the parsed file `upload-lists.json` from the directory `settings.js` is in (`path.join(__dirname, "upload-lists.json")`), or `null` when reading or parsing throws. A comment says what reads it and that `null` makes the upload gate send nothing.

- [ ] **Step 5: Change the upload gate (`ae3349867027d005`).**
  - Remove the two constants. After the check that the upload is on (so a unit that isn't sharing logs nothing), read `global.get("upload_lists")`. If it isn't a mapping whose `telemetry`, `attributes`, and `event` are each an array of strings, call `warnOnce("upload:lists", LISTS_WARNING)` and return `null`.
  - `telemetryItem` and `attributes` use the lists read.
  - In `telemetryItem`, when `event` is among the values: if it isn't a mapping, leave it out with `warnOnce("upload:event", "ThingsBoard upload: left out an event that isn't a mapping.")`; otherwise keep only the listed fields, calling `leftOut("event." + key)` for each other key, and leave the event out when no field is left. An item with no value left is `null`, as today.
  - Update the comment at the top of the function: the lists are in `upload-lists.json`.

- [ ] **Step 6: Add the file to the copy loop** in `node-red-tm_setup.yml`. That task has no `notify`. Read `start_services.yml` to see how a changed `flows.json` reaches a running Node-RED, and make sure the same holds for this file: `settings.js` reads it only when Node-RED starts. If nothing restarts Node-RED for a changed file in that loop, add `notify: Restart node-red-tm.service` to the task and say so in the PR.

- [ ] **Step 7: Run the tests**

Run: the command from Step 2.
Expected: all pass. `test_everything_uploaded_passes_the_gate` still passes unchanged (the gate has no On Start code).

- [ ] **Step 8: Commit**

```bash
git add container/node-red-tm/data script/ansible script/tests
git commit   # subject: Move the upload gate's lists to a file, and list the event fields it sends
```

---

### Task 3: The field rule

**Files:**
- Modify: `container/node-red-tm/data/flows.json` (`a96d834e3571c549`)
- Test: `script/tests/test_node_red_flows.py` (and its `HARNESS`)

**Interfaces:**
- Consumes: `EVENT_COLUMNS`, `KEPT_ON_THE_UNIT`, `upload_lists()` from Task 2.
- Produces: `event_keys()`, `event_insert()`, `finalize_msg()` test helpers; in the harness, each result gains `keys`. "write params for events insert" binds exactly the INSERT's columns.

- [ ] **Step 1: Let the harness report keys.** A key whose value is `undefined` vanishes in JSON, and the finalize node sets several. In `HARNESS`, each pushed result gains `keys`: `Object.keys(result.payload)` when the result's `payload` is a plain object, else `null`.

- [ ] **Step 2: Write the failing tests**

```python
FINALIZE = "a8aeffd2e5bc17f2"  # capture-events: event finalize output
EVENT_PARAMS = "a96d834e3571c549"  # capture-events: write params for events insert
EVENT_INSERT = "61d6a19c99c60e0b"  # capture-events: tmdb.events, Prepared Statement
JSON_COLUMNS = {"entered_zones", "attributes", "provenance"}
SCHEMA_SQL = FLOWS.parents[1] / "schema" / "schema.sql"
EVENT = {
    "id": "1761800000.123456-abc123", "camera": "camera_1_3fa9c2", "label": "car", "sub_label": None,
    "top_score": 0.91, "frame_time": 1761800004.2, "start_time": 1761800000.1, "end_time": 1761800004.3,
    "entered_zones": ["zone_near", "zone_far"], "score": 0.88, "area": 57600, "ratio": 1.78, "motionless_count": 0,
    "position_changes": 3, "attributes": {}, "deployment_id": "1761800000000-0a1b2c3d-d",
}


def finalize_msg(direction=None, speed=None, readings=None, radar="TM_RADAR_SERIAL_PORT_00", fields=MISSING):
    """The message "event finalize output" gets: the event under its camera's key, and what the speed nodes found."""
    found = {"status_radarMatch": speed is not None, "calc_event_direction": direction, "calc_event_speed": speed,
             "calc_radar_readings": readings}
    msg = {"frigate_event": {**EVENT, **({"radarName": radar} if radar else {})}, "radarEnabled": radar is not None,
           "payload": found, "event_direction_speed": found}
    if fields is not MISSING:
        msg["frigate_fields"] = fields
    return msg


def event_keys():
    [step] = run_functions([(node_by_id(FINALIZE), finalize_msg("inbound", 22.5, 7))])["results"]
    return step["keys"]


def event_insert():
    """The INSERT's columns and the parameter each one takes."""
    match = re.fullmatch(r"\s*INSERT INTO events \(([^)]*)\)\s*VALUES \((.*)\);\s*", node_by_id(EVENT_INSERT)["sql"],
                         re.DOTALL)
    return ([name.strip() for name in match[1].split(",")], [value.strip() for value in match[2].split(",")])


@needs_node
def test_event_fields_agree():
    """One list of event fields, in one order: what finalize builds, what the INSERT names, what its parameters are,
    what the table has, and (less what is kept on the unit) what the upload gate lets through."""
    assert event_keys() == EVENT_COLUMNS
    names, values = event_insert()
    assert names == EVENT_COLUMNS
    assert all(value in (f"${name}", f"json(${name})") for name, value in zip(names, values, strict=True))
    [step] = run_functions([(node_by_id(EVENT_PARAMS), {"payload": {name: None for name in EVENT_COLUMNS}})])["results"]
    assert list(step["result"]["params"]) == [f"${name}" for name in EVENT_COLUMNS]
    con = sqlite3.connect(":memory:")
    con.executescript(SCHEMA_SQL.read_text())
    assert {row[1] for row in con.execute("PRAGMA table_info(events)")} >= set(EVENT_COLUMNS)
    assert upload_lists()["event"] == [name for name in EVENT_COLUMNS if name not in KEPT_ON_THE_UNIT]


@needs_node
def test_event_params_bind_only_the_columns():
    payload = {**EVENT, "direction_calc": "inbound", "provenance": ["frigate"], "surprise": "no column"}
    del payload["sub_label"]
    [step] = run_functions([(node_by_id(EVENT_PARAMS), {"payload": payload})])["results"]
    params = step["result"]["params"]
    assert "$surprise" not in params and len(params) == len(EVENT_COLUMNS)
    assert params["$sub_label"] is None and params["$speed_calc"] is None and params["$radarName"] is None
    assert params["$entered_zones"] == '["zone_near","zone_far"]'
    assert params["$attributes"] == "{}" and params["$provenance"] == '["frigate"]'
    assert params["$top_score"] == 0.91 and params["$motionless_count"] == 0
    assert step["result"]["payload"]["entered_zones"] == ["zone_near", "zone_far"]  # the payload isn't changed


@needs_node
@pytest.mark.parametrize("column", sorted(JSON_COLUMNS))
@pytest.mark.parametrize("absent", [True, False], ids=["absent", "null"])
def test_event_params_keep_a_missing_json_column_empty(column, absent):
    """Today an absent one becomes the text "undefined", which json() refuses, so the row is lost, and a null one
    becomes the text "null"."""
    payload = {name: None for name in EVENT_COLUMNS if not (absent and name == column)}
    [step] = run_functions([(node_by_id(EVENT_PARAMS), {"payload": payload})])["results"]
    assert step["result"]["params"][f"${column}"] is None
```

Add `import re` and `import sqlite3` at the top of the file if they aren't there.

- [ ] **Step 3: Run them and see them fail**

Run: `python -m pytest script/tests/test_node_red_flows.py -q -k "event_fields_agree or event_params"`
Expected: `test_event_fields_agree` passes already: it pins what is there, and it is the test that fails when a later change adds a field in one place only. `test_event_params_bind_only_the_columns` fails on `$surprise`. The JSON column tests fail with `'undefined'` and `'null'`.

- [ ] **Step 4: Rewrite "write params for events insert" (`a96d834e3571c549`).** It holds the column list as a constant, in `EVENT_COLUMNS` order, and a second constant naming the JSON columns. `msg.params` gets one `$name` per column and nothing else: `null` for a value that is `undefined` or `null`, `JSON.stringify(value)` for a JSON column, the value itself otherwise. It doesn't change `msg.payload`. A comment says why the list is fixed: SQLite refuses a parameter the statement doesn't name, and a test compares this list with the INSERT.

- [ ] **Step 5: Run the flows tests**

Run: `python -m pytest script/tests/test_node_red_flows.py container/node-red-tm/schema/tests -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add container/node-red-tm/data/flows.json script/tests/test_node_red_flows.py
git commit   # subject: Bind the events INSERT from a fixed column list, and test that the event's field lists agree
```

---

### Task 4: `sub_label` is a vetted field

**Files:**
- Modify: `container/node-red-tm/data/flows.json` (new node "vet sub_label"; `76911cc7f28e7da2` rewired)
- Test: `script/tests/test_node_red_flows.py`

**Interfaces:**
- Produces: function node "vet sub_label" in the group "frigate event mqtt end", wired `76911cc7f28e7da2` → it → `8eaa1d06a29a5d2b`. After it, `msg.frigate_event.sub_label`, `msg.payload.after.sub_label`, and `msg.payload.before.sub_label` are each a vetted text or `null`.

- [ ] **Step 1: Write the failing tests**

```python
SET_FRIGATE_EVENT = "76911cc7f28e7da2"  # capture-events: set frigate_event from payload.after
VETTED = ["amazon", "an_post", "canada_post", "dhl", "dpd", "fedex", "gls", "nzpost", "postnl", "postnord",
          "purolator", "royal_mail", "ups", "usps"]


def vet(sub_label):
    after = {"camera": "oak_ave_wide", "id": "1.0-abc", "sub_label": sub_label}
    msg = {"frigate_event": dict(after), "payload": {"type": "end", "before": dict(after), "after": dict(after)}}
    [step] = run_functions([(named(json.loads(FLOWS.read_text()), "vet sub_label"), msg)])["results"]
    return step


@needs_node
@pytest.mark.parametrize("given, kept", [
    (["amazon", 0.91], "amazon"), ("ups", "ups"), (["royal_mail", 0.5], "royal_mail"),
    (["Jane Doe", 0.97], None), ("ABC123", None), (["Amazon", 0.9], None), (["amazon ", 0.9], None),
    (["my_custom_class", 0.8], None), (None, None), ([], None), ([["amazon"], 0.9], None),
    ({"text": "amazon"}, None), (42, None), ("", None),
])
def test_only_a_vetted_sub_label_is_kept(given, kept):
    step = vet(given)
    result = step["result"]
    assert result["frigate_event"]["sub_label"] == kept
    assert result["payload"]["after"]["sub_label"] == kept and result["payload"]["before"]["sub_label"] == kept
    assert step["logged"] == []
    if kept is None and given:
        assert "Jane Doe" not in json.dumps(step) and "ABC123" not in json.dumps(step)


@needs_node
def test_vetting_survives_a_message_without_before_or_after():
    node = named(json.loads(FLOWS.read_text()), "vet sub_label")
    for payload in ({}, {"before": None, "after": None}, "text", None):
        [step] = run_functions([(node, {"frigate_event": {"sub_label": ["Jane Doe", 0.9]}, "payload": payload})])["results"]
        assert step["result"]["frigate_event"]["sub_label"] is None


def test_the_vetted_list_is_frigates_logo_labels():
    func = named(json.loads(FLOWS.read_text()), "vet sub_label")["func"]
    assert "const VETTED = " + json.dumps(VETTED) + ";" in func


def test_every_event_is_vetted_before_any_other_node_reads_it():
    flows = json.loads(FLOWS.read_text())
    by_id = {node["id"]: node for node in flows}
    vetting = named(flows, "vet sub_label")
    assert by_id[SET_FRIGATE_EVENT]["wires"] == [[vetting["id"]]]
    assert (vetting["type"], vetting["outputs"], vetting["z"]) == ("function", 1, tab_id(flows, "capture-events"))
    assert [node["id"] for node in flows if vetting["id"] in sum(node.get("wires", []), [])] == [SET_FRIGATE_EVENT]
    assert APPEND_CONFIG in {node["id"] for node in reachable(by_id, [vetting["id"]])}
```

- [ ] **Step 2: Run them and see them fail**

Run: `python -m pytest script/tests/test_node_red_flows.py -q -k "vet"`
Expected: FAIL, no node named "vet sub_label".

- [ ] **Step 3: Add the node.** Its `func` starts with `const VETTED = [...]` exactly as `json.dumps(VETTED)` prints it. The rule: take the first member when the value is an array, the value itself otherwise; keep it only when it is a string that is in `VETTED`; else `null`. Apply it to `msg.frigate_event` and, where each is an object, to `msg.payload.after` and `msg.payload.before` (in the live flow `frigate_event` and `payload.after` are one object; in the tests they are copies). It logs nothing. A comment says this is the one place a sub-label is sorted, that the list changes only by a change to the flows, and that a store for the rest would take them here. Wire it as under "Interfaces" for this task; `8eaa1d06a29a5d2b` is the target for now.

- [ ] **Step 4: Run the flows tests**

Run: `python -m pytest script/tests/test_node_red_flows.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add container/node-red-tm/data/flows.json script/tests/test_node_red_flows.py
git commit   # subject: Keep a sub_label only when it is one of Frigate's logo labels
```

---

### Task 5: Frigate's facts

**Files:**
- Modify: `container/node-red-tm/data/flows.json` (new group "frigate facts" on `capture-events`)
- Test: `script/tests/test_node_red_flows.py`

**Interfaces:**
- Produces: `flow.frigate_facts` on `capture-events`, in the shape under "Names used across tasks". It is absent until the first good read.

The five new nodes:

| Node | Settings |
|---|---|
| inject "read frigate facts" | once, 10 seconds after start, then every 600 seconds |
| `mqtt in` | topic `frigate/available`, broker `a5d65dd0e3566daa` (the existing broker node; no credential file changes) |
| switch "frigate is online" | `msg.payload` equals the string `online` |
| `http request` "frigate api/config" | `GET http://frigate:5000/api/config`, returns a parsed JSON object |
| function "keep frigate facts" | below |

The inject and the switch both feed the request; the request feeds the function.

- [ ] **Step 1: Write the failing tests**

```python
FRIGATE_CONFIG = {
    "ui": {"unit_system": "imperial", "timezone": None},
    "cameras": {
        "oak_ave_wide": {"detect": {"width": 1280, "height": 720, "fps": 10}, "zones": {}},
        "side_gate": {"detect": {"width": 1920, "height": 1080}},
        "no_size": {"detect": {"width": 0, "height": None}},
        "text_size": {"detect": {"width": "1280", "height": "720"}},
        "odd": "text",
    },
}
FACTS = {"unit_system": "imperial", "detect": {"oak_ave_wide": {"width": 1280, "height": 720},
                                                "side_gate": {"width": 1920, "height": 1080}}}


def keep_facts(msg, flow=None):
    node = named(json.loads(FLOWS.read_text()), "keep frigate facts")
    run = run_functions([(node, msg)], flow={} if flow is None else flow)
    return run["results"][0], run["flow"]


@needs_node
def test_frigate_facts_are_kept():
    step, flow = keep_facts({"statusCode": 200, "payload": FRIGATE_CONFIG})
    assert flow == {"frigate_facts": FACTS}
    assert step["result"] is None and step["logged"] == []


@needs_node
@pytest.mark.parametrize("ui, expected", [
    ({"unit_system": "metric"}, "metric"), ({"unit_system": "imperial"}, "imperial"), ({"unit_system": "Metric"}, None),
    ({"unit_system": None}, None), ({}, None), (None, None), ("metric", None),
])
def test_the_unit_system_is_one_of_frigates_two_or_unknown(ui, expected):
    _, flow = keep_facts({"statusCode": 200, "payload": {**FRIGATE_CONFIG, "ui": ui}})
    assert flow["frigate_facts"]["unit_system"] == expected


@needs_node
@pytest.mark.parametrize("msg", [
    {"statusCode": 500, "payload": FRIGATE_CONFIG}, {"statusCode": 200, "payload": "<html>"},
    {"statusCode": 200, "payload": None}, {"statusCode": 200, "payload": []}, {"payload": FRIGATE_CONFIG},
    {"statusCode": 200, "payload": {"ui": {"unit_system": "metric"}}},
], ids=["error", "text", "null", "list", "no-status", "no-cameras"])
def test_an_answer_that_cannot_be_read_keeps_the_last_facts(msg):
    before = {"frigate_facts": {"unit_system": "metric", "detect": {"oak_ave_wide": {"width": 640, "height": 360}}}}
    step, flow = keep_facts(msg, flow=json.loads(json.dumps(before)))
    assert flow == before and step["result"] is None and step["logged"] == []


def test_frigate_facts_are_read_at_start_when_frigate_comes_back_and_every_ten_minutes():
    flows = json.loads(FLOWS.read_text())
    by_id = {node["id"]: node for node in flows}
    keep = named(flows, "keep frigate facts")
    [request] = [node for node in flows if node["type"] == "http request" and keep["id"] in sum(node["wires"], [])]
    assert (request["method"], request["url"], request["ret"]) == ("GET", "http://frigate:5000/api/config", "obj")
    sources = [node for node in flows if request["id"] in sum(node.get("wires", []), [])]
    assert sorted(node["type"] for node in sources) == ["inject", "switch"]
    inject = next(node for node in sources if node["type"] == "inject")
    assert (inject["once"], str(inject["onceDelay"]), str(inject["repeat"])) == (True, "10", "600")
    switch = next(node for node in sources if node["type"] == "switch")
    assert (switch["property"], switch["rules"]) == ("payload", [{"t": "eq", "v": "online", "vt": "str"}])
    [available] = [node for node in flows if switch["id"] in sum(node.get("wires", []), [])]
    assert (available["type"], available["topic"], available["broker"]) == ("mqtt in", "frigate/available",
                                                                           "a5d65dd0e3566daa")
    capture = tab_id(flows, "capture-events")
    assert {node["z"] for node in (keep, request, inject, switch, available)} == {capture}
    assert keep["wires"] == [[]]
```

- [ ] **Step 2: Run them and see them fail**

Run: `python -m pytest script/tests/test_node_red_flows.py -q -k "frigate_facts or unit_system or last_facts"`
Expected: FAIL, no node named "keep frigate facts".

- [ ] **Step 3: Add the group and its five nodes.** "keep frigate facts" sets `flow.frigate_facts` only when `msg.statusCode` is 200 and the payload is a mapping whose `cameras` is a mapping. `unit_system` is `ui.unit_system` when it is `"metric"` or `"imperial"`, else `null`. `detect` gets an entry for each camera whose `detect.width` and `detect.height` are finite numbers above 0, holding only those two. It returns `null` and logs nothing: Frigate restarting is normal. A comment says the facts serve only the box and unit conversion in "frigate fields", and that the keys of `detect` are Frigate's camera names, which stay in this flow context.

- [ ] **Step 4: Run the flows tests**

Run: `python -m pytest script/tests/test_node_red_flows.py -q`
Expected: all pass, including `test_mqtt_nodes_keep_their_ids` and `test_flows_cred_is_still_encrypted`.

- [ ] **Step 5: Commit**

```bash
git add container/node-red-tm/data/flows.json script/tests/test_node_red_flows.py
git commit   # subject: Read each camera's detect size and Frigate's unit system into Node-RED
```

---

### Task 6: Frigate's fields

**Files:**
- Modify: `container/node-red-tm/data/flows.json` (new node "frigate fields"; "vet sub_label" rewired to it)
- Test: `script/tests/test_node_red_flows.py`

**Interfaces:**
- Consumes: `flow.frigate_facts` (Task 5); `msg.frigate_event` with Frigate's camera name still on it.
- Produces: `msg.frigate_fields`, always with all seven keys. Wired "vet sub_label" → it → `8eaa1d06a29a5d2b`.

The rules:

| Field | From | Kept when |
|---|---|---|
| `path_data` | `after.path_data` | It is an array. Points that aren't `[[x, y], t]` with three finite numbers are left out. If more than 100 are left, keep 100: for `i` from 0 to 99, the point at index `Math.round(i * (n - 1) / 99)`. No point left: `null`. |
| `box` | `after.box` | `[x1, y1, x2, y2]` are four finite numbers with `x2 >= x1` and `y2 >= y1`, and the facts hold this camera's size. Stored as `[x1 / W, y1 / H, (x2 - x1) / W, (y2 - y1) / H]`, each rounded to four decimals. |
| `best_box` | `after.snapshot.box` | The same rule. |
| `best_frame_time` | `after.snapshot.frame_time` | It is a finite number. |
| `frigate_speed` | `after.average_estimated_speed` | It is a finite number above 0. |
| `frigate_velocity_angle` | `after.velocity_angle` | It is a finite number and `frigate_speed` was kept. |
| `frigate_speed_unit` | the facts' `unit_system` | `frigate_speed` was kept: `kph` for `metric`, `mph` for `imperial`, `null` when the facts aren't read. |

- [ ] **Step 1: Write the failing tests**

```python
AFTER = {
    "id": "1761800000.123456-abc123", "camera": "oak_ave_wide", "label": "car", "sub_label": None,
    "frame_time": 1761800004.2, "start_time": 1761800000.1, "end_time": 1761800004.3,
    "box": [960, 360, 1280, 540], "snapshot": {"frame_time": 1761800002.1, "box": [320, 180, 640, 360], "score": 0.9},
    "average_estimated_speed": 38.6, "velocity_angle": 172.4, "entered_zones": ["zone_near", "zone_far"],
    "path_data": [[[0.25, 0.5], 1761800000.1], [[0.5, 0.52], 1761800002.1], [[0.8751, 0.55], 1761800004.2]],
}
METRIC = {"unit_system": "metric", "detect": {"oak_ave_wide": {"width": 1280, "height": 720}}}
FIELDS = {
    "path_data": AFTER["path_data"], "box": [0.75, 0.5, 0.25, 0.25], "best_box": [0.25, 0.25, 0.25, 0.25],
    "best_frame_time": 1761800002.1, "frigate_speed": 38.6, "frigate_speed_unit": "kph",
    "frigate_velocity_angle": 172.4,
}
NO_FIELDS = dict.fromkeys(FIELDS)


def frigate_fields(facts=METRIC, **changes):
    node = named(json.loads(FLOWS.read_text()), "frigate fields")
    msg = {"frigate_event": {**AFTER, **changes}, "payload": {"type": "end"}}
    [step] = run_functions([(node, msg)], flow={} if facts is None else {"frigate_facts": facts})["results"]
    assert step["logged"] == []
    assert step["result"]["frigate_event"] == msg["frigate_event"]  # the event itself is left alone
    return step["result"]["frigate_fields"]


@needs_node
def test_frigate_fields_from_an_end_message():
    fields = frigate_fields()
    assert fields == FIELDS and list(fields) == list(FIELDS)
    assert "oak_ave_wide" not in json.dumps(fields)


@needs_node
@pytest.mark.parametrize("facts", [None, {"unit_system": None, "detect": {}},
                                   {"unit_system": "metric", "detect": {"another_camera": {"width": 1280, "height": 720}}}],
                         ids=["not-read-yet", "empty", "another-camera"])
def test_without_the_cameras_facts_there_are_no_boxes(facts):
    fields = frigate_fields(facts)
    assert fields["box"] is None and fields["best_box"] is None
    assert fields["path_data"] == AFTER["path_data"] and fields["best_frame_time"] == 1761800002.1
    assert fields["frigate_speed"] == 38.6 and fields["frigate_velocity_angle"] == 172.4
    assert fields["frigate_speed_unit"] == ("kph" if facts and facts["unit_system"] else None)


@needs_node
def test_imperial_is_mph():
    assert frigate_fields({**METRIC, "unit_system": "imperial"})["frigate_speed_unit"] == "mph"


@needs_node
@pytest.mark.parametrize("speed", [0, 0.0, -3.2, None, "38", MISSING])
def test_frigates_zero_is_no_estimate(speed):
    after = dict(AFTER)
    if speed is MISSING:
        del after["average_estimated_speed"]
    else:
        after["average_estimated_speed"] = speed
    node = named(json.loads(FLOWS.read_text()), "frigate fields")
    [step] = run_functions([(node, {"frigate_event": after})], flow={"frigate_facts": METRIC})["results"]
    fields = step["result"]["frigate_fields"]
    assert (fields["frigate_speed"], fields["frigate_speed_unit"], fields["frigate_velocity_angle"]) == (None, None, None)
    assert fields["box"] == FIELDS["box"]


@needs_node
def test_a_long_path_keeps_a_hundred_points_first_and_last():
    path = [[[round(index / 250, 4), 0.5], 1761800000.0 + index] for index in range(250)]
    kept = frigate_fields(path_data=path)["path_data"]
    assert kept == [path[int(index * 249 / 99 + 0.5)] for index in range(100)]
    assert kept[0] == path[0] and kept[-1] == path[-1]
    assert frigate_fields(path_data=path[:100])["path_data"] == path[:100]
    assert len(frigate_fields(path_data=path[:101])["path_data"]) == 100


@needs_node
def test_a_path_holds_numbers_only():
    good = AFTER["path_data"]
    mixed = [good[0], [[0.1, 0.2], "t"], ["x"], [[0.1], 1.0], [[None, 0.2], 1.0], {"a": 1}, "Jane Doe", good[1],
             [[0.1, 0.2, 0.3], 1.0], [[0.1, 0.2], 1.0, 2.0], good[2]]
    assert frigate_fields(path_data=mixed)["path_data"] == good
    for path in ("Jane Doe", None, {}, [], [["x"]], 7):
        assert frigate_fields(path_data=path)["path_data"] is None


@needs_node
@pytest.mark.parametrize("box", [[960, 360, 1280], [960, 360, 1280, "540"], [1280, 360, 960, 540], None, "box",
                                 [960, 360, 1280, 540, 1], [960, 360, 1280, None]])
def test_a_box_that_is_not_four_numbers_in_order_is_empty(box):
    fields = frigate_fields(box=box, snapshot={"frame_time": "soon", "box": box})
    assert (fields["box"], fields["best_box"], fields["best_frame_time"]) == (None, None, None)


@needs_node
@pytest.mark.parametrize("snapshot", [None, "text", {}, MISSING])
def test_an_event_without_a_best_frame(snapshot):
    after = {key: value for key, value in AFTER.items() if key != "snapshot"}
    node = named(json.loads(FLOWS.read_text()), "frigate fields")
    event = after if snapshot is MISSING else {**after, "snapshot": snapshot}
    [step] = run_functions([(node, {"frigate_event": event})], flow={"frigate_facts": METRIC})["results"]
    fields = step["result"]["frigate_fields"]
    assert (fields["best_box"], fields["best_frame_time"], fields["box"]) == (None, None, FIELDS["box"])


@needs_node
def test_frigate_fields_survive_an_event_that_is_not_a_mapping():
    node = named(json.loads(FLOWS.read_text()), "frigate fields")
    for event in (None, "text", []):
        [step] = run_functions([(node, {"frigate_event": event})], flow={"frigate_facts": METRIC})["results"]
        assert step["result"]["frigate_fields"] == NO_FIELDS


def test_frigate_fields_are_worked_out_while_frigates_name_is_on_the_event():
    flows = json.loads(FLOWS.read_text())
    fields, vetting = named(flows, "frigate fields"), named(flows, "vet sub_label")
    assert vetting["wires"] == [[fields["id"]]] and fields["wires"] == [[APPEND_CONFIG]]
    assert [node["id"] for node in flows if APPEND_CONFIG in sum(node.get("wires", []), [])] == [fields["id"]]
```

- [ ] **Step 2: Run them and see them fail**

Run: `python -m pytest script/tests/test_node_red_flows.py -q -k "frigate_fields or boxes or mph or estimate or path or box or best_frame"`
Expected: FAIL, no node named "frigate fields".

- [ ] **Step 3: Add the node** by the rules in the table. It reads the facts with `flow.get("frigate_facts")`, looks the size up by `msg.frigate_event.camera`, sets `msg.frigate_fields` with the seven keys in the table's order, changes nothing else, and logs nothing. Rewire "vet sub_label" to it and it to `8eaa1d06a29a5d2b`.

- [ ] **Step 4: Run the flows tests**

Run: `python -m pytest script/tests/test_node_red_flows.py -q`
Expected: all pass. In Task 4's `test_every_event_is_vetted_before_any_other_node_reads_it`, `APPEND_CONFIG` is still reached.

- [ ] **Step 5: Commit**

```bash
git add container/node-red-tm/data/flows.json script/tests/test_node_red_flows.py
git commit   # subject: Work out an event's path, boxes, and Frigate speed from Frigate's message
```

---

### Task 7: Direction without a radar, a speed of 0, and what the radar's readings say

**Files:**
- Modify: `container/node-red-tm/data/flows.json` (`c123fc5ed5e14e8a`, `673e45159a2dfccf`, `1acba66197b7b0fa`)
- Test: `script/tests/test_node_red_flows.py`

**Interfaces:**
- Produces: `msg.radar_reading_counts` from `c123fc5ed5e14e8a` (its `msg.payload` is unchanged); `calc_radar_readings` in the payload of `673e45159a2dfccf`; `global.radar_units`.

What `673e45159a2dfccf` gets today: with a radar, the medians by direction; without one, the "radar enabled?" switch sends it Frigate's whole message, whose three keys it reads as three radar directions, so the zones' direction is thrown away.

- [ ] **Step 1: Write the failing tests**

```python
MEDIAN = "c123fc5ed5e14e8a"  # capture-events: calculate median per direction
MATCH = "673e45159a2dfccf"  # capture-events: match radar speed to event, assign direction
DOV_PARAMS = "1acba66197b7b0fa"  # capture-radar: write params for radar_dov insert
FRIGATE_MESSAGE = {"type": "end", "before": {"id": "1.0-abc"}, "after": {"id": "1.0-abc"}}


def match(zone_direction, medians, counts=None, radar=True):
    event = {"id": "1.0-abc", **({"calc_zone_direction": zone_direction} if zone_direction else {})}
    msg = {"frigate_event": event, "radarEnabled": radar, "payload": medians if radar else FRIGATE_MESSAGE,
           "radar_reading_counts": counts or {}}
    [step] = run_functions([(node_by_id(MATCH), msg)])["results"]
    found = step["result"]["payload"]
    return (found.get("calc_event_direction"), found.get("calc_event_speed"), found["status_radarMatch"],
            found.get("calc_radar_readings"))


@needs_node
@pytest.mark.parametrize("zones, medians, counts, expected", [
    ("inbound", {"inbound": 22.5, "outbound": -30.0}, {"inbound": 7, "outbound": 2}, ("inbound", 22.5, True, 7)),
    ("inbound", {"inbound": 22.5}, {"inbound": 4}, ("inbound", 22.5, True, 4)),
    ("inbound", {"outbound": -30.0}, {"outbound": 5}, (None, None, False, None)),
    (None, {"outbound": -30.0}, {"outbound": 5}, ("outbound", -30.0, True, 5)),
    (None, {"inbound": 22.5, "outbound": -30.0}, {"inbound": 7, "outbound": 2}, (None, None, False, None)),
    ("outbound", {}, {}, ("outbound", None, False, None)),
    (None, {}, {}, (None, None, False, None)),
    ("inbound", {"inbound": 0}, {"inbound": 3}, ("inbound", 0, True, 3)),
    (None, {"outbound": 0}, {"outbound": 1}, ("outbound", 0, True, 1)),
    ("inbound", {"inbound": 0, "outbound": -30.0}, {"inbound": 3, "outbound": 2}, ("inbound", 0, True, 3)),
], ids=["match-of-two", "match", "other-direction-only", "radars-direction", "two-and-no-zones", "none", "nothing",
        "zero-match", "zero-assigned", "zero-of-two"])
def test_direction_and_speed_with_a_radar(zones, medians, counts, expected):
    assert match(zones, medians, counts) == expected


@needs_node
@pytest.mark.parametrize("zones", ["inbound", "outbound", None])
def test_a_camera_without_a_radar_gets_its_direction_from_the_zones(zones):
    assert match(zones, None, radar=False) == (zones, None, False, None)


@needs_node
def test_medians_come_with_the_number_of_readings():
    rows = [{"direction": "inbound", "velocity": value, "unit": "mph"} for value in (21.0, 22.0, 26.0)]
    rows += [{"direction": "outbound", "velocity": value, "unit": "mph"} for value in (-30.0, -32.0)]
    [step] = run_functions([(node_by_id(MEDIAN), {"payload": rows})])["results"]
    assert step["result"]["payload"] == {"inbound": 22.0, "outbound": -31.0}
    assert step["result"]["radar_reading_counts"] == {"inbound": 3, "outbound": 2}
    [step] = run_functions([(node_by_id(MEDIAN), {"payload": []})])["results"]
    assert step["result"]["payload"] == {} and step["result"]["radar_reading_counts"] == {}


@needs_node
def test_the_last_unit_each_radar_reported_is_remembered():
    reading = {"time": 1761800000.5, "unit": "mph", "direction": "inbound", "DetectedObjectVelocity": 21.3,
               "radarName": "TM_RADAR_SERIAL_PORT_00", "deployment_id": "1761800000000-0a1b2c3d-d"}
    other = {**reading, "radarName": "TM_RADAR_SERIAL_PORT_01", "unit": "kmph"}
    no_unit = {key: value for key, value in reading.items() if key != "unit"}
    node = node_by_id(DOV_PARAMS)
    run = run_functions([(node, dict(reading)), (node, other), (node, no_unit)])
    assert run["global"]["radar_units"] == {"TM_RADAR_SERIAL_PORT_00": "mph", "TM_RADAR_SERIAL_PORT_01": "kmph"}
    assert run["results"][0]["result"]["params"] == {
        "$time": 1761800000.5, "$unit": "mph", "$direction": "inbound", "$velocity": 21.3,
        "$radarName": "TM_RADAR_SERIAL_PORT_00", "$deployment_id": "1761800000000-0a1b2c3d-d"}
```

- [ ] **Step 2: Run them and see them fail**

Run: `python -m pytest script/tests/test_node_red_flows.py -q -k "radar or readings or unit_each"`
Expected: every case that expects a count, a speed of 0, or a direction without a radar fails, and so do the counts and the units; the cases with no speed and no count pass.

- [ ] **Step 3: Change the three nodes.**
  - `c123fc5ed5e14e8a`: also set `msg.radar_reading_counts`, the number of rows in each direction's group.
  - `673e45159a2dfccf`: read the medians only when `msg.radarEnabled === true` and the payload is a mapping; otherwise there are none. Decide "this direction has a median" by whether the key is there with a number, never by truthiness. Set `calc_radar_readings` to `msg.radar_reading_counts[<the direction used>]` when a speed is matched. The statuses and every other outcome stay as the table has them.
  - `1acba66197b7b0fa`: when `msg.payload.unit` and `msg.payload.radarName` are non-empty strings, store the unit under that name in `global.radar_units` (read the object, set the key, write it back). Its parameters are unchanged.

- [ ] **Step 4: Run the flows tests**

Run: `python -m pytest script/tests/test_node_red_flows.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add container/node-red-tm/data/flows.json script/tests/test_node_red_flows.py
git commit   # subject: Give a camera without a radar its direction, and count a radar speed of 0 as a speed
```

---

### Task 8: The speed that is saved, and the ten columns (tricky: Opus 5.5 at xhigh)

**Files:**
- Modify: `container/node-red-tm/data/flows.json` (`a8aeffd2e5bc17f2`, `a96d834e3571c549`, `61d6a19c99c60e0b`), `container/node-red-tm/data/upload-lists.json`
- Test: `script/tests/test_node_red_flows.py`

**Interfaces:**
- Consumes: `msg.frigate_fields` (Task 6), `calc_radar_readings` and `global.radar_units` (Task 7), `global.config.sensors.radars`, `msg.radarEnabled`, `msg.frigate_event.radarName`.
- Produces: the event payload with all thirty fields in `EVENT_COLUMNS` order, saved and uploaded.

The rules for "event finalize output":

1. **The device's speed unit.** If this camera's radar is enabled (`msg.radarEnabled === true`), it is `radar_units[<its name>]`, or `mph` when no reading has come yet. Otherwise, if any radar in `config.sensors.radars` is enabled, it is that radar's (the first by name), found the same way. Otherwise it is the event's `frigate_speed_unit`, which can be `null`.
2. **A radar speed** (`calc_event_speed` is a number, 0 included): `speed_calc` is it, `speed_source` is `radar`, `speed_unit` is the device's unit, `radar_readings` is `calc_radar_readings`.
3. **Otherwise Frigate's speed**, when `frigate_speed` is a number, `frigate_speed_unit` is known, and the device's unit is one of the table below: `speed_calc` is `frigate_speed` converted and rounded to two decimals, negative when `direction_calc` is `outbound` and positive otherwise; `speed_source` is `frigate`; `speed_unit` is the device's unit; `radar_readings` is empty.
4. **Otherwise no speed:** `speed_calc`, `speed_unit`, `speed_source`, and `radar_readings` are empty.
5. **Conversion** goes through metres per second: `value * PER[from] / PER[to]` with `PER = {mps: 1, mph: 0.44704, kph: 1 / 3.6, kmph: 1 / 3.6, fps: 0.3048, cmps: 0.01}`. Before writing the table, read the radar's unit names in the maker's API note (AN-010, the `U?` answer and the `unit` field of a speed report) and make the keys match what the radar prints; keep `kph` for Frigate.
6. **A unit the table lacks:** no fallback, and one warning per config load through `tm_warned` (key `speed_unit:<unit>`): `Frigate's speed wasn't used for speed_calc: this flow can't convert to the radar's unit <unit>.`
7. `direction_calc`, `provenance`, and the other seventeen fields are as today. The seven Frigate fields are copied from `msg.frigate_fields`; when that isn't a mapping they are all `null`.

- [ ] **Step 1: Extend the lists in the tests.** `EVENT_COLUMNS` gains the ten names in the order under "Names used across tasks". `JSON_COLUMNS` gains `path_data`, `box`, `best_box`.

- [ ] **Step 2: Write the failing tests**

```python
RADARS_ON = {"TM_RADAR_SERIAL_PORT_00": {"enabled": True}}
NO_SPEED = {"speed_calc": None, "speed_unit": None, "speed_source": None, "radar_readings": None}


def finalize(msg, radars=None, units=None):
    context = {"config": {"sensors": {"radars": RADARS_ON if radars is None else radars}},
               "radar_units": units or {}, "tm_warned": {}}
    run = run_functions([(node_by_id(FINALIZE), msg)], context=context)
    [step] = run["results"]
    payload = step["result"]["payload"]
    return {key: payload.get(key) for key in step["keys"]}, step, run["global"]


def speed_of(payload):
    return {key: payload[key] for key in NO_SPEED}


@needs_node
def test_a_radar_speed_is_saved_with_frigates_beside_it():
    payload, step, _ = finalize(finalize_msg("inbound", 22.5, 7, fields=FIELDS), units={"TM_RADAR_SERIAL_PORT_00": "mph"})
    assert list(payload) == EVENT_COLUMNS and step["logged"] == []
    assert speed_of(payload) == {"speed_calc": 22.5, "speed_unit": "mph", "speed_source": "radar", "radar_readings": 7}
    assert {key: payload[key] for key in FIELDS} == FIELDS
    assert payload["direction_calc"] == "inbound" and payload["provenance"] == ["frigate", "radar"]


@needs_node
@pytest.mark.parametrize("direction, units, expected", [
    ("outbound", {}, {"speed_calc": -23.98, "speed_unit": "mph"}),
    ("inbound", {}, {"speed_calc": 23.98, "speed_unit": "mph"}),
    (None, {}, {"speed_calc": 23.98, "speed_unit": "mph"}),
    ("outbound", {"TM_RADAR_SERIAL_PORT_00": "mps"}, {"speed_calc": -10.72, "speed_unit": "mps"}),
])
def test_frigates_speed_fills_in_when_the_radar_gave_none(direction, units, expected):
    payload, step, _ = finalize(finalize_msg(direction, None, None, fields=FIELDS), units=units)
    assert speed_of(payload) == {**expected, "speed_source": "frigate", "radar_readings": None}
    assert payload["frigate_speed"] == 38.6 and payload["frigate_speed_unit"] == "kph"
    assert payload["provenance"] == ["frigate"] and step["logged"] == []


@needs_node
@pytest.mark.parametrize("radars", [{}, {"TM_RADAR_SERIAL_PORT_00": {"enabled": False}},
                                    {"TM_RADAR_SERIAL_PORT_00": None}, "text"],
                         ids=["none", "disabled", "empty-entry", "not-a-mapping"])
def test_a_device_without_a_radar_keeps_frigates_unit(radars):
    msg = finalize_msg("outbound", None, None, radar=None, fields=FIELDS)
    payload, _, _ = finalize(msg, radars=radars)
    assert speed_of(payload) == {"speed_calc": -38.6, "speed_unit": "kph", "speed_source": "frigate",
                                 "radar_readings": None}
    assert payload["radarName"] is None


@needs_node
def test_a_camera_without_a_radar_uses_the_units_of_the_devices_radar():
    """One device's speed_calc stays in one unit."""
    imperial = {**FIELDS, "frigate_speed": 30.0, "frigate_speed_unit": "mph"}
    msg = finalize_msg("inbound", None, None, radar=None, fields=imperial)
    radars = {"TM_RADAR_SERIAL_PORT_01": {"enabled": True}, "TM_RADAR_SERIAL_PORT_00": {"enabled": False}}
    payload, _, _ = finalize(msg, radars=radars, units={"TM_RADAR_SERIAL_PORT_01": "kmph"})
    assert speed_of(payload) == {"speed_calc": 48.28, "speed_unit": "kmph", "speed_source": "frigate",
                                 "radar_readings": None}


@needs_node
def test_a_radar_speed_of_zero_is_saved():
    payload, _, _ = finalize(finalize_msg("inbound", 0, 3, fields=FIELDS))
    assert speed_of(payload) == {"speed_calc": 0, "speed_unit": "mph", "speed_source": "radar", "radar_readings": 3}


@needs_node
@pytest.mark.parametrize("fields", [
    {**FIELDS, "frigate_speed_unit": None}, {**FIELDS, "frigate_speed": None, "frigate_speed_unit": None,
                                             "frigate_velocity_angle": None}, NO_FIELDS, MISSING, None, "text",
], ids=["unit-not-read", "no-estimate", "nothing", "missing", "null", "text"])
def test_no_speed_without_a_radar_speed_or_a_usable_frigate_speed(fields):
    payload, step, _ = finalize(finalize_msg("inbound", None, None, fields=fields))
    assert speed_of(payload) == NO_SPEED and step["logged"] == []
    assert list(payload) == EVENT_COLUMNS
    expected = fields if isinstance(fields, dict) else NO_FIELDS
    assert {key: payload[key] for key in FIELDS} == expected


@needs_node
def test_a_radar_unit_the_flow_cannot_convert_to_gets_no_fallback_and_one_warning():
    msg = finalize_msg("inbound", None, None, fields=FIELDS)
    context = {"config": {"sensors": {"radars": RADARS_ON}}, "radar_units": {"TM_RADAR_SERIAL_PORT_00": "furlongs"},
               "tm_warned": {}}
    run = run_functions([(node_by_id(FINALIZE), msg), (node_by_id(FINALIZE), msg)], context=context)
    for step in run["results"]:
        assert step["result"]["payload"].get("speed_calc") is None
        assert step["result"]["payload"].get("speed_source") is None
    warnings = [text for step in run["results"] for _, text, _ in step["logged"]]
    assert warnings == ["Frigate's speed wasn't used for speed_calc: this flow can't convert to the radar's unit furlongs."]
    assert run["global"]["tm_warned"] == {"speed_unit:furlongs": True}


@needs_node
def test_event_params_turn_the_new_lists_into_json_text():
    payload, _, _ = finalize(finalize_msg("inbound", 22.5, 7, fields=FIELDS))
    [step] = run_functions([(node_by_id(EVENT_PARAMS), {"payload": payload})])["results"]
    params = step["result"]["params"]
    assert json.loads(params["$path_data"]) == FIELDS["path_data"]
    assert params["$box"] == "[0.75,0.5,0.25,0.25]" and params["$best_box"] == "[0.25,0.25,0.25,0.25]"
    assert params["$radar_readings"] == 7 and params["$speed_source"] == "radar"


def run_chain(names_or_ids, msg, context, flow):
    """Run nodes one after another, each on the message the one before returned; None if one of them drops it."""
    flows = json.loads(FLOWS.read_text())
    by_id = {node["id"]: node for node in flows}
    for name in names_or_ids:
        node = by_id.get(name) or named(flows, name)
        run = run_functions([(node, msg)], context=context, flow=flow)
        msg, context, flow = run["results"][0]["result"], run["global"], run["flow"]
        if msg is None:
            return None
    return msg


@needs_node
def test_a_made_up_event_on_a_camera_without_a_radar_becomes_a_row():
    """The whole chain of function nodes, then the node's own INSERT against the migrated schema."""
    config = config_with_cameras({"camera_1_3fa9c2": {"frigate_camera": "oak_ave_wide", "enabled": True}})
    config["sensors"]["radars"] = {}
    _, context = load_config(config)
    after = {**AFTER, "sub_label": ["Jane Doe", 0.97], "entered_zones": ["zone_near", "zone_far"], "top_score": 0.91,
             "score": 0.88, "area": 57600, "ratio": 1.78, "motionless_count": 0, "position_changes": 3,
             "attributes": {}}
    msg = {"frigate_event": after, "payload": {"type": "end", "before": dict(after), "after": after}}
    msg = run_chain(["vet sub_label", "frigate fields", APPEND_CONFIG,
                     "calculate direction based on frigate event zones", MATCH], msg, context,
                    {"frigate_facts": METRIC})
    msg = {**msg, "event_direction_speed": msg["payload"]}
    msg = run_chain([FINALIZE, EVENT_PARAMS], msg, context, {})
    con = sqlite3.connect(":memory:")
    con.executescript(SCHEMA_SQL.read_text())
    con.execute(node_by_id(EVENT_INSERT)["sql"], {key[1:]: value for key, value in msg["params"].items()})
    row = con.execute("SELECT camera, sub_label, direction_calc, speed_calc, speed_unit, speed_source, radar_readings, "
                      "frigate_speed, frigate_speed_unit, json_array_length(path_data), json_extract(box, '$[0]'), "
                      "best_frame_time, radarName FROM events").fetchone()
    assert row == ("camera_1_3fa9c2", None, "outbound", -38.6, "kph", "frigate", None, 38.6, "kph", 3, 0.75,
                   1761800002.1, None)
    assert "Jane Doe" not in json.dumps(msg) and "oak_ave_wide" not in json.dumps(msg["payload"])
```

- [ ] **Step 3: Run them and see them fail**

Run: `python -m pytest script/tests/test_node_red_flows.py -q -k "speed or event_fields_agree or made_up or event_params"`
Expected: FAIL; `test_event_fields_agree` fails first, on the finalize keys. If "init config defaults" objects to the empty `radars` block in the last test's config, disable the template's radar there instead of emptying the block.

- [ ] **Step 4: Change "event finalize output" (`a8aeffd2e5bc17f2`)** by the seven rules. The payload's keys are in `EVENT_COLUMNS` order. Keep `direction_calc` as it is built today. Drop `|| undefined` from `speed_calc`: a speed is a number or it is absent.

- [ ] **Step 5: Extend the INSERT (`61d6a19c99c60e0b`)** with the ten columns and their `$name` parameters (no `json()` around the three lists: the parameter is already JSON text or `NULL`), **the column and JSON lists in `a96d834e3571c549`**, and **`upload-lists.json`'s `event` list**, each in `EVENT_COLUMNS` order.

- [ ] **Step 6: Run everything off-device**

Run: `python -m pytest container/node-red-tm/schema/tests script/tests tm-control/backend/tests -q`
Expected: all pass, including `test_flow_sql_compiles_against_schema` for the INSERT.

- [ ] **Step 7: Commit**

```bash
git add container/node-red-tm/data script/tests/test_node_red_flows.py
git commit   # subject: Save and upload an event's path, boxes, both speeds, and where speed_calc came from
```

Stop here. Every flow change but the statistics query is in. Set up the maintainer's flows review, so they can read the changed and new nodes in the Node-RED editor before the rest.

---

### Task 9: The speed statistics say where the speeds came from

**Files:**
- Modify: `container/node-red-tm/data/flows.json` (`584504e6c8935eaf`)
- Test: `script/tests/test_node_red_flows.py`

**Interfaces:**
- Produces: two more result columns, `count_radar` and `count_frigate`, right after `count`. The two cards that show the result (`5417aae0d14fa661` on the legacy dashboard and `c0e4e6adcc7a5782` on Dashboard 2.0) list whatever columns the query returns, so they need no change.

- [ ] **Step 1: Write the failing test**

```python
SPEED_STATS = "584504e6c8935eaf"  # ui-monitoring: query events, daily cum car counts in zone_radar with speed_calc


@needs_node
def test_the_car_speed_statistics_count_each_source():
    [step] = run_functions([(node_by_id(SPEED_STATS), {"payload": {}})],
                           flow={"camera_selection": "camera_1_3fa9c2"})["results"]
    con = sqlite3.connect(":memory:")
    con.executescript(SCHEMA_SQL.read_text())
    # 05:00 today, local time: inside "since 04:00 today" whenever the test runs
    today = datetime.now().replace(hour=5, minute=0, second=0, microsecond=0).timestamp()
    zones = '["zone_capture", "zone_radar"]'
    rows = [("a", 22.0, "radar"), ("b", -31.0, "radar"), ("c", 27.0, None), ("d", 24.5, "frigate"),
            ("e", -19.0, "frigate"), ("f", None, None)]
    con.executemany("INSERT INTO events (id, camera, label, frame_time, entered_zones, speed_calc, speed_source) "
                    "VALUES (?, 'camera_1_3fa9c2', 'car', ?, ?, ?, ?)",
                    [(name, today, zones, speed, source) for name, speed, source in rows])
    con.row_factory = sqlite3.Row
    result = dict(con.execute(step["result"]["topic"]).fetchone())
    assert list(result)[:3] == ["count", "count_radar", "count_frigate"]
    assert (result["count"], result["count_radar"], result["count_frigate"]) == (5, 3, 2)
    assert result["max_speed"] == 31.0
```

Add `from datetime import datetime` if the file doesn't import it. A row from before this change has no `speed_source`; its speed came from the radar, so it counts as the radar's.

- [ ] **Step 2: Run it and see it fail**

Run: `python -m pytest script/tests/test_node_red_flows.py -q -k car_speed_statistics`
Expected: FAIL on the column names.

- [ ] **Step 3: Change the query.** The inner SELECT also returns `speed_source`. The outer one adds, after `COUNT(*) AS count`, `SUM(CASE WHEN speed_source = 'frigate' THEN 0 ELSE 1 END) AS count_radar` and `SUM(CASE WHEN speed_source = 'frigate' THEN 1 ELSE 0 END) AS count_frigate`. Nothing else changes.

- [ ] **Step 4: Run the flows tests, and commit**

Run: `python -m pytest script/tests/test_node_red_flows.py -q`
Expected: all pass.

```bash
git add container/node-red-tm/data/flows.json script/tests/test_node_red_flows.py
git commit   # subject: Show how many of the day's car speeds came from the radar and from Frigate
```

---

### Task 10: The notice and the Sharing page's example

**Files:**
- Modify: `tm-control/backend/tm_control/modules/sharing/NOTICE.md`, `tm-control/ui/src/modules/sharing/examples.ts`, the UI test that pins the example if one does

- [ ] **Step 1: The example.** In `SHARE_DATA_EXAMPLE`, the event gains `speed_unit: 'mph'`, `speed_source: 'radar'`, `radar_readings: 7`, `path_data: [[[0.25, 0.5], 1_793_000_000.2], [[0.75, 0.55], 1_793_000_003.9]]`, and `box: [0.75, 0.5, 0.25, 0.25]`. Run the UI build and tests (the command under "Commands") and bring any test that pins the example in line.

- [ ] **Step 2: Draft the notice's sentence, and stop.** The notice is the maintainer's text. Propose, for the first paragraph under "Share data", after "its counts, speeds, radar and air-quality readings": "For each object it counted, that includes the path it took across the camera's picture and the outline of its box, as numbers, never a picture." Show the maintainer the paragraph before and after, and take their wording. The notice's version stays `2026-11`: no release has carried it yet (the maintainer's decision, 2026-11-17).

- [ ] **Step 3: Commit** after the maintainer's answer.

```bash
git add tm-control
git commit   # subject: Say in the sharing notice and its example that an event's path and box are sent
```

---

### Task 11: Docs

**Files:** the twelve under "Docs" in the table above.

- [ ] **Step 1: `docs/data-and-payloads/events-payload.md`**
  - "How an event is made", step 3: the direction comes from the zones on any camera; the speed comes from the camera's radar, or from Frigate when the radar gave none.
  - "Direction and speed": keep the table for a camera with a radar, and add the rows for a camera without one (the zones' direction; Frigate's speed or none). A new paragraph on Frigate's speed: Frigate estimates one only for an object that crossed a zone drawn with four corners and the real length of each side, so nothing is estimated unless you set that up; it is converted to the device's speed unit; `speed_source` says which it was; both are in the row when both exist. Replace the sentence that says a camera without a radar has no direction and no speed.
  - "Columns": the ten new rows. Correct `frame_time`: read Frigate 0.18.1's source or docs first, then say what it is (the last frame Frigate processed for the object) and that `best_frame_time` is the best frame's. `sub_label`: one of the fourteen logo labels or empty; anything else Frigate sends is not saved; rows written by earlier versions can hold other text. `speed_calc`: its unit is in `speed_unit`; positive when the direction isn't known. `frigate_velocity_angle`: check its unit and zero direction in Frigate's source before describing it. Rows written before this version have the new columns empty, and their speed came from the radar.
  - A note that the JSON columns arrive as text in the JSON export, as `entered_zones` does.
- [ ] **Step 2: `docs/data-and-payloads/object-paths.md`** (new, in `mkdocs.yml` under the same section as Events, and in the `llmstxt` plugin's section if that folder isn't matched already). What a path is; the format (`[[x, y], t]`, fractions of the frame from the top-left corner, the bottom-centre of the box, Unix seconds); how dense it is (a point after the object moved 5% of the frame's diagonal) and the 100-point limit; how to redraw it the way Frigate's Tracking Details does; that turning picture positions into positions on the road needs a mapping for that camera view, and why error grows with distance and at the frame's edges; what else is in the row (the two boxes, Frigate's speed and angle). Only what this version stores; nothing about work that isn't built.
- [ ] **Step 3: `docs/data-and-payloads/data-overview.md`**: the Privacy paragraph's list of what is recorded gains the path across the picture; the bullet about Frigate features that add sub-labels now says names and plates in a sub-label aren't saved from this version on, and that a database which recorded them earlier still holds them; the `events` row of the tables list follows.
- [ ] **Step 4: `docs/data-and-payloads/integrations.md`**: the ThingsBoard bullet says the event's listed fields are sent, links to `upload-lists.json` in the repository, and says a field not on the list stays on the device.
- [ ] **Step 5: `docs/use/sharing.md`**: the **Share data** row names the path and the box.
- [ ] **Step 6: `docs/ui/monitoring.md`**, item 2: the statistics cover cars with a speed, the radar's or Frigate's; the table gains `count_radar` and `count_frigate`; `count_over_25` is in the device's speed unit.
- [ ] **Step 7: `docs/get-started/how-it-works.md`**: replace "Without a radar, events have no direction or speed."
- [ ] **Step 8: `docs/configuration/frigate-config.md`**: a short section "Speed without a radar": draw a speed zone in Frigate (link to Frigate's page on speed estimation), what the device records from it, that Frigate's unit setting decides `kph` or `mph`, and that the estimate is rougher than a radar's.
- [ ] **Step 9: `docs/development/tm-control.md`** (the paragraph on where Frigate's camera name lives), **`container/node-red-tm/data/README.md`** (the new file), and **`CLAUDE.md`**: the `capture-events` bullet (direction without a radar, the speed's two sources, the two new nodes, `frigate_facts`), the field rule (finalize, the INSERT, its parameters, the table, and `upload-lists.json` change together; `test_event_fields_agree`), `upload-lists.json` in the list of files overwritten on every run and as a contract with `settings.js`, and the camera-name contract's one new place.
- [ ] **Step 10: Build the docs**

Run: `~/.venvs/tm-docs/bin/mkdocs build --strict`
Expected: it builds with no warning.

- [ ] **Step 11: Commit**

```bash
git add docs mkdocs.yml CLAUDE.md container/node-red-tm/data/README.md
git commit   # subject: Document the event's new columns, object paths, and speed without a radar
```

---

### Task 12: A device test with a made-up event

**Files:**
- Modify: `script/devpi/tests/devpi_checks.py`, `script/devpi/tests/test_disruptive.py`, `script/devpi/README.md`

**Interfaces:**
- Produces: `publish_on_pi(host, topic, payload: dict) -> None` in `devpi_checks.py`; `test_a_made_up_event_is_recorded_with_its_path_and_boxes` in `test_disruptive.py`.

- [ ] **Step 1: `publish_on_pi`.** It runs a short `python3 -c` script on the Pi that opens `127.0.0.1:1883`, sends an MQTT 3.1.1 CONNECT with no login (as `PI_MQTT_CONNACK` in `test_web.py` does), checks the CONNACK is 0, sends one QoS 0 PUBLISH of the JSON payload, and disconnects. The payload travels as a base64 argument, so nothing needs quoting. It raises with the CONNACK code when the broker refuses.

- [ ] **Step 2: The test.** It runs only with `--disruptive` (it writes one row) and only on a unit marked `pii_free` (it reads `config.yml` and `tmdb.sqlite`).
  - Skip when the unit's broker has a login (`broker_login` in `test_web.py` shows how to read whether one is set; move it to `devpi_checks.py` to share it): a made-up event is published without one.
  - Pick the first enabled entry under `sensors.cameras` whose Frigate camera (`frigate_camera`, or its key) is in Frigate's config; read that camera's detect width `W` and height `H` from the `frigate_config` fixture.
  - Publish on `frigate/events` an `end` message whose `after` has: an id of the Pi's time and `-tmdev0`; `label: "tmdev_check"`; `sub_label: ["tmdev person", 0.99]`; `stationary: false`; `position_changes: 2`; `entered_zones: ["zone_tmdev"]`; `box: [W / 2, H / 2, W, H]`; `snapshot: {frame_time: <time - 1>, box: [0, 0, W / 2, H / 2]}`; `average_estimated_speed: 0`; three path points; and the other fields the flows read (`top_score`, `frame_time`, `start_time`, `end_time`, `score`, `area`, `ratio`, `motionless_count`, `attributes: {}`).
  - Wait up to 15 seconds for the row, then assert: `sub_label` is NULL; `json_array_length(path_data)` is 3; `box` is `[0.5,0.5,0.5,0.5]` and `best_box` is `[0,0,0.5,0.5]`; `best_frame_time` is set; `frigate_speed`, `speed_calc`, and `speed_source` are NULL; `camera` is the entry's key.
  - The zone name and label keep the row out of every dashboard count. The row stays; the docstring and the README's table say so.

- [ ] **Step 3: Check it collects and skips cleanly off-device**

Run: `python -m pytest script/devpi/tests --collect-only -q | grep made_up`
Expected: the test is listed.

- [ ] **Step 4: Commit**

```bash
git add script/devpi
git commit   # subject: Add a device test that sends a made-up event and reads its row
```

---

### Task 13: Bench, the plan copy, and the text for review

- [ ] **Step 1: Run everything off-device once more** (pytest, the UI, the docs, from "Commands"), and the checks in `CLAUDE.md` that touch what changed: `python3 -m json.tool container/node-red-tm/data/flows.json >/dev/null` and the Ansible syntax check. All pass.

- [ ] **Step 2: Bench run, logged with `tmdev check`**, on a bench unit marked `pii_free`, at the branch head, from a worktree (`script/devpi/README.md`). Nothing here turns on Frigate's detection, snapshots, or recording; say so in the check. Use the whole installer, not one tag: the unit must be on this branch's base. Items:
  1. Before the deploy: `tmdb_migrate.py --check` says the database is up to date at version 2, and the control app's Location page has been opened on this unit at least once. (This migration's backup replaces the older copies in `db/backup/`, which the one-time import of past places reads.)
  2. Deploy. The journal shows `backed up … tmdb-v2-…`, `applied 0003_event_fields.sql`, and `migrated … from version 2 to 3`, with no new `DRIFT` line. `--check` says version 3. The Status page's **Database schema** is ok. Record how long the migration took and the database's size.
  3. `tmdev.py test <host>` passes. Then `tmdev.py test <host> --disruptive -- -k made_up_event` passes.
  4. A made-up event that entered `zone_near` then `zone_far` with `average_estimated_speed: 30`: on a camera without an enabled radar the row has `direction_calc` `outbound`, `speed_source` `frigate`, `speed_calc` −30 in Frigate's unit, and `speed_unit` saying so. On a camera with a radar and nothing passing, the row has the speed converted to the radar's unit. Record the unit the radar's rows carry (`SELECT DISTINCT unit FROM radar_dov`).
  5. A made-up event with 300 path points: the row has 100, and the first and last are the ones sent.
  6. Stop Frigate, restart Node-RED, and send a made-up event: the row is saved with no boxes and no `frigate_speed_unit`. Start Frigate, wait a minute, send another: the boxes are back, which shows the read on `frigate/available`.
  7. Both dashboards open. The car speed card shows `count_radar` and `count_frigate`, and Latest observations still fills in when a made-up event enters `zone_radar` (it asks Frigate for a thumbnail that doesn't exist; record what the card does, and compare with the same event on the base branch if it looks wrong).
  8. The Data export page's JSON export of events downloads and holds the new columns.
  9. The Sharing page's **See an example** shows the new fields, and the notice reads as agreed.
  10. With sharing on to a ThingsBoard server (the maintainer's step, with their token): the server's latest `event` telemetry holds the new fields, and Node-RED's log has no "left out" or "didn't load" warning. Afterwards the unit is left not sharing.
  11. Cleanup, recorded in the check: Frigate's `/api/config` (sent with `X-Cache-Bypass: 1`) still shows detection off for the bench camera; the rows labelled `tmdev_check` stay.

- [ ] **Step 3: The public plan copy.** Copy this plan to `design/plans/2026-11-17-event-fields.md`, and commit it last.

- [ ] **Step 4: Write the text, and stop.** Write, for the maintainer to read before anything is pushed: the PR title and body from `.github/PULL_REQUEST_TEMPLATE.md`, against `feature/sharing-page/314` (or `dev` if PR 321 has merged), with the issue references below, the bench check's id, that the migration is additive, how long it took, and the template's "Docs" and "AI assistance" sections filled in. Under limits, say: a unit-system change in Frigate is seen within ten minutes, and events in between carry the old unit; rows written before this version keep their `sub_label`; the gate doesn't yet hold a new field back until the notice is read again.
  - Closes issue 336 (this work), issue 166 (Frigate's speed when there is no radar), and issue 243 (no direction without a radar).
  - Refs issue 306 for `sub_label`. If PR 332 has merged, this PR closes it.
  - Refs issue 175.

---

## Room for the planned follow-up

A planned change adds more event columns worked out from Frigate's `new` and `update` messages, and narrows which radar readings an event takes. This plan leaves it these places, and it should need no other:

- **A new column** is one line in each of: a migration, `EVENT_COLUMNS` in the tests, "event finalize output", the INSERT, the column list in "write params for events insert", and `upload-lists.json` (or `KEPT_ON_THE_UNIT`). `test_event_fields_agree` fails until all of them agree.
- **Messages other than `end`** are available at the `mqtt in` node `f20c74c0ccfd256c`, before the `payload.type == "end"` switch. A node there can keep its own state and put its result on the `end` message; "vet sub_label" and "frigate fields" pass every property of the message through.
- **Which radar readings count** is decided in two nodes only: `b39062019fac1a66` builds the query's time window, and `c123fc5ed5e14e8a` groups the rows it returns. `radar_readings` is counted from the rows that node grouped, so it stays right when the rows are narrowed.
