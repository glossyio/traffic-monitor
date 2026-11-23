# Time Stopped and Time in Each Zone Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Each event's row says how long the object stood still, how many times it stopped, and how long it spent in each zone, in seconds, so a reader can study a stop sign, a queue, or a parking bay from the database alone.

**Architecture:** Frigate sends no such times, only a yes-or-no `stationary` flag, the zones the object is in, and a frame time on every `frigate/events` message. One new function node on the flows' `capture-events` tab reads every `new`, `update`, and `end` message before anything else does, keeps a small tally for each object in flow context (memory), and hands the totals to the `end` message. Three new columns on `events` hold them, and they join the event fields that are uploaded. The radar query leaves out the stretches an object stood still in, and a new index on the radar readings' time lets it stop reading the whole table for every event. The control app changes only in the sharing notice and its example.

**Tech Stack:** Node-RED 5.0.10 function nodes (JavaScript in `flows.json`), a SQLite migration run by `tmdb_migrate.py`, pytest with the function-node harness in `script/tests/test_node_red_flows.py`, the device tests in `script/devpi/tests`, MkDocs.

**Spec:** "What it must do" below.

**Repo:** `glossyio/traffic-monitor`, branch `feature/time-stopped/347` off `feature/watch-log/340` (PR 343), in its own worktree, as a PR stacked on PR 343, which is itself stacked on PR 339. Issue 347 is this change's issue. Branch from whatever has merged by then: from `dev` if PR 339 and PR 343 both have. All paths below are relative to the repo root.

## What it must do

1. **Three columns on `events`.** `stationary_time` (REAL): the total seconds Frigate held the object as stationary. `stops` (INTEGER): how many separate times it became stationary. `zone_times` (TEXT, JSON): for each zone Frigate listed the object in, the seconds in it and the seconds stationary in it, `{"zone_stop_sign_e": {"time": 3.4, "stationary": 0}}`.
2. **Frigate's own flags, added up.** One function reads every `new`, `update`, and `end` message. Between one message and the next, the time that passed is added to whatever the earlier message said was true: to `stationary_time` when the object was stationary, to each zone it was in, and to that zone's `stationary` figure when both held. Nothing is estimated or put back.
3. **The clock is `after.frame_time`**, the last frame Frigate saw the object in, on all three kinds of message. At `end` that is not `end_time`: Frigate ends an event up to about five seconds after it last saw the object, and those seconds are not counted.
4. **A tally starts only at an object's `new` message.** An `update` or `end` for an object with no tally starts none. So after a restart of Node-RED, an event already in progress is saved with the three columns empty, never with part of a figure.
5. **A missed message empties the figures too.** Each message's `before.frame_time` is the frame time of the message Frigate sent before it. When that isn't the time of the last message the tally saw, or time runs backwards, the tally is marked broken and its event is saved with the three columns empty. The same goes when more than 300 seconds of frame time passed since the last message: Frigate sends an update for an object it is following at least once a minute, so a longer gap means the clock was set or the camera stalled, not that the object was watched for that long. (The 300 seconds were added after the whole-branch review; see "Review fixes".)
6. **All three or none.** An event has all three columns filled or all three empty.
7. **Six hours is the most any figure says.** `stationary_time` and each figure in `zone_times` stop at 21,600 seconds. Figures are rounded to two decimals. `stops` has no limit.
8. **Bounded by number.** At most 300 tallies are kept, the least recently updated going first. A tally that has had no message for more than 86,400 seconds of Frigate's frame time is dropped. A tally keeps at most 50 zones and the 20 longest stretches the object stood still.
9. **The tally can't stop an event being recorded.** Every message goes on to the next node with its payload as it came, whatever its shape, and the function never throws.
10. **An object that stopped takes its radar readings only from when it was moving.** The radar query for an event leaves out each stretch the object was stationary, less two seconds at each end, the same margin the whole window has. An event that never stopped, or has no tally, gets exactly the query it gets today.
11. **Upload.** The three columns join the `event` list in `upload-lists.json`, so they are sent with **Share data**. The notice and the Sharing page's example say so.
12. **The field rule holds.** `test_event_fields_agree` still ties what the finalize node builds, the INSERT, its parameters, the table, and the upload list together, with the three new fields in all five.
13. **Two migrations, neither rewriting a row.** `0005` adds the three columns. `0006` adds an index on `radar_dov(time)`, so an event's radar query reads only its own seconds; today it reads every radar reading the device has for every event. They are two files so that a card too full to build the index still gets the columns.
14. **Docs** say what is recorded, its limits, and how to use it, in the same PR.

Not in this change: recording events that end while the object is stationary (they are still dropped, as today); a setting for how soon an object counts as stopped; a table with a row for each visit to a zone; a dashboard or a Status page check; any change to which events are recorded or to `direction_calc`.

## Global Constraints

- `flows.json` is edited by a script and written back with `json.dumps(flows, indent=4, ensure_ascii=False)` and no trailing newline. `test_flows_json_round_trips_through_json_dumps` must keep passing.
- Existing nodes keep their ids. The one new node gets a new 16-hex id, sits in the group "frigate event mqtt end" (`0a5faeac9fbd6d55`; in its `nodes` list, with `x`/`y` inside the group's box), and is found by name in tests.
- Function nodes run in Node-RED's sandbox: no `structuredClone`, no `fetch`. The test harness enforces this.
- The tally holds an event id, numbers, and zone names, and nothing else. Frigate's name for a camera, a sub-label, a plate, and a box are never copied into flow context, a log line, or `msg.time_tally`. Zone names are already saved and uploaded with every event in `entered_zones`.
- No log line, warning, or status text names a camera, a zone, or an event id, or quotes a value. A warning is given once per config load through `tm_warned`, as "event finalize output" does.
- The flow context key is `time_tallies` on the `capture-events` tab. Context is in memory (`contextStorage` in `settings.js`); nothing is written to the card.
- Two migrations: `0005` is three `ALTER TABLE events ADD COLUMN` statements and nothing else, and `0006` is one `CREATE INDEX IF NOT EXISTS` and nothing else. Never edit `0001` to `0004`. If the base or the merge order changes the numbers, see "Migration numbers" under "Names used across tasks".
- The upload gate's function (`ae3349867027d005`) doesn't change: the three fields are sent because they are listed.
- Docs ride with the code and follow "Writing docs" in `docs/development/contributing.md`. `mkdocs build --strict` must pass.
- The bench run needs real Frigate events, so Frigate's detection has to be on for it. It is turned on only for a bench-only camera, `tmdev_loop`, that plays a video file the maintainer supplies and has checked for faces and anything else that identifies a person. The live camera's detection stays off throughout. Never turn detection on without the maintainer's consent first, asked for this run, saying how many times (once, for one session). Recording and snapshots are off for the loop camera, so Frigate keeps no picture. Never open the clip, a frame, a snapshot, a thumbnail, or the camera's live view: only the maintainer looks at the picture. Afterwards set detection back to false, confirm it in Frigate's `/api/config` (sent with `X-Cache-Bypass: 1`), and record it in the check. Made-up `frigate/events` messages on the device's broker turn nothing on and need no consent.
- Commit messages end with the trailer block in the repo's `CLAUDE.md`. No device names or addresses in commits or PR text.
- Nothing is pushed. The maintainer reads the commits and the PR text first.
- Open PRs that touch the same files: PR 343 is the base and PR 339 is under it. PR 343 is a draft whose `0004` and watch tables are still changing; merge its branch in whenever it moves, and once more just before the text is written in Task 9. It changes no node on `capture-events`, and nothing here reads its tables. PR 326 (draft, on `dev`) adds nodes on `ui-database` and `init-config`, tests at the end of `script/tests/test_node_red_flows.py`, and lines in `docs/data-and-payloads/data-overview.md`, `docs/use/sharing.md`, and `CLAUDE.md`; it adds no migration and changes no node this plan changes. PR 344 is control app only and shares `CLAUDE.md` and `script/devpi/tests/test_web.py`. PR 335 and PR 342 share nothing. If one merges first, merge it in and keep both sides.

## Review Focus

Inputs the requirements imply and a person will meet; each has a test in the task named.

1. Node-RED restarted, or the unit rebooted, while Frigate was following objects: each of those events is saved with the three columns empty and everything else as before, and an object that was parked through the restart isn't given the hours since. Task 3.
2. A message lost between Frigate and the flows, as when Frigate's broker connection drops for a moment: the event's figures are empty, not one state stretched across the gap. Task 3.
3. A vehicle parked for a day, or a fixed thing Frigate takes for one and flags on and off for a week: no figure says more than 21,600, and the tally doesn't grow (20 stretches, 50 zones, 300 tallies). Task 3.
4. A message on the broker that isn't Frigate's shape (text, no `after`, a frame time that is text, a zone list with junk in it), or junk already in flow context: the message goes on unchanged, the event is recorded as today, and nothing is logged for every message. Task 3.
5. A car that stopped for a minute beside a road the radar kept measuring: its speed comes from the readings while it moved, and an event that never stopped gets exactly the readings it gets today. Task 5.
6. The clock is set forward while an object is being followed, as when a unit boots without a network and the time arrives later, or an admin sets it: the event's figures are empty, not the hours the clock moved. Task R1.

## Files

| File | Change |
|---|---|
| `container/node-red-tm/schema/migrations/0005_time_stopped.sql` | New: three `ALTER TABLE` statements |
| `container/node-red-tm/schema/migrations/0006_radar_dov_time_index.sql` | New: one `CREATE INDEX` statement |
| `container/node-red-tm/schema/schema.sql` | Regenerated |
| `container/node-red-tm/data/flows.json` | New node "tally time stopped and time in zones" in the group `0a5faeac9fbd6d55`. Changed nodes: `f20c74c0ccfd256c` (the `frigate/events` node, `wires` only), `b39062019fac1a66` (the radar query), `a8aeffd2e5bc17f2` (event finalize output), `a96d834e3571c549` (write params), `61d6a19c99c60e0b` (the INSERT) |
| `container/node-red-tm/data/upload-lists.json` | Three names at the end of `event` |
| `tm-control/backend/tm_control/modules/sharing/NOTICE.md` | What "Share data" sends (the maintainer's wording) |
| `tm-control/ui/src/modules/sharing/examples.ts` | The Share data example's event gains the three fields |
| `script/devpi/tests/test_disruptive.py`, `script/devpi/README.md` | One device test, and one assertion more in the made-up event test |
| Tests | `container/node-red-tm/schema/tests/helpers.py`, `test_0003_event_fields.py`, `test_0004_watch_log.py`, `test_0005_time_stopped.py` and `test_0006_radar_dov_time_index.py` (new), `script/tests/test_node_red_flows.py`, `tm-control/ui/tests/` where the example is pinned |
| Docs | `docs/data-and-payloads/events-payload.md`, `docs/help-and-faq/use-cases-and-scenarios.md`, `docs/configuration/frigate-config.md`, `docs/data-and-payloads/integrations.md`, `docs/use/sharing.md`, `CLAUDE.md` |
| `design/plans/2026-11-19-time-stopped.md` | The public copy of this plan (Task 9) |

## Commands

```bash
. .venv/bin/activate                                   # the dev venv from CLAUDE.md, in the same shell call
python -m pytest container/node-red-tm/schema/tests -q
python -m pytest script/tests/test_node_red_flows.py -q
python -m pytest container/node-red-tm/schema/tests script/tests tm-control/backend/tests -q   # everything off-device
python3 container/node-red-tm/schema/tmdb_migrate.py --dump-schema > container/node-red-tm/schema/schema.sql
podman run --rm -v "$PWD/tm-control/ui:/ui:Z" -w /ui docker.io/library/node:22.23.4-alpine sh -c 'npm ci && npm run build && npm test'
~/.venvs/tm-docs/bin/mkdocs build --strict
```

The flows tests need `node` on the path; without it they skip, and CI fails a skip.

## Names used across tasks

| Name | What it is |
|---|---|
| "tally time stopped and time in zones" | The new function node, one output. Called "the tally node" below. |
| `flow.time_tallies` (`capture-events` tab) | `{<event id>: <tally>}`, in the order the tallies were last updated, oldest first |
| A tally | `{at, stationary, zones, stationary_time, stops, zone_times, stopped, stopped_since, broken}`. `at` is the frame time of the last message; `stationary` and `zones` are what that message said; `stationary_time` and `zone_times` are the sums so far, unrounded and without the six-hour limit; `stopped` is a list of `[from, to]` frame times, the stretches the object stood still that have ended; `stopped_since` is the frame time the open stretch began at, or `null`; `broken` is `true` once a message was missed. |
| `msg.time_tally` | Set by the tally node on every message it passes on: `null`, except on an `end` message whose tally is whole, where it is `{stationary_time, stops, zone_times, stopped}` with the limit and the rounding applied to the first and third |
| `MAX_TALLIES`, `DEAD_AFTER`, `MAX_SECONDS`, `MAX_STOPPED`, `MAX_ZONES` | Constants at the top of the tally node: 300, 86400, 21600, 20, 50 |
| `MAX_GAP` | One more constant, added by Task R1: 300, the most seconds of frame time between two messages about one object |
| `tm_warned` id | `time_tally:error` |

**Migration numbers.** `0005` and `0006` follow the watch log's `0004`. If this branch has to go ahead of the watch log (PR 343 dropped or delayed), rebase onto PR 339's branch or `dev`, rename the two files and their tests to `0004` and `0005`, set `LATEST_VERSION` to 5, and regenerate `schema.sql`; the watch log then takes `0006`. If any other migration merges first, take the next two numbers the same way. Never renumber a migration that has merged.

In tests, `T0 = 1761800000.0` is the first frame's time and `TALLY_ID = "1761800000.0-abc123"`.

The chain after this change: `frigate/events` → **tally time stopped and time in zones** → `payload.type == "end"` → `after.stationary is false` → `after.position_changes > 0` → set frigate_event → vet sub_label → frigate fields → append config → … → pull speed, direction for event period → … → event finalize output → write params → the INSERT. Every node between the tally node and the finalize node passes the message's other properties on, so `msg.time_tally` arrives.

What Frigate 0.18.2 does, read from its source (`frigate/track/tracked_object.py`, `frigate/camera/state.py`, `frigate/track/object_processing.py`, `frigate/track/norfair_tracker.py`, `frigate/video/detect.py`, `frigate/config/config.py`):

- A message is `{type, before, after}`. `after` is the object now; `before` is the `after` of the message Frigate published before this one for the same object. The first message for an object is `new`, sent once Frigate is sure the object is real; before that it sends nothing.
- `after.frame_time` is the time of the last frame the object was detected in. A stationary object is carried forward frame by frame, so its frame time keeps moving. At `end`, `after.end_time` is the frame Frigate gave the object up in, up to `detect.max_disappeared` frames later (five seconds unless set).
- `after.stationary` is true once the object has gone more than `detect.stationary.threshold` frames without changing position (ten seconds unless set). `after.motionless_count` is the current run of such frames and goes back to 0 when the object moves.
- `after.current_zones` lists the zones the object is in now. A zone lists an object after it has been inside for `inertia` frames in a row (3 unless set) and, when the zone has a loitering time, after that many seconds in it. A zone with side lengths (`distances`) lists an object only in a frame where it was detected and is not stationary.
- Frigate publishes an `update` in the frame the stationary flag flips, in the frame the set of current zones changes, at each new point of the object's path, when a new attribute appears, about every five seconds after a better snapshot, and at least once a minute.

---

### Task 1: The columns (migration 0005)

**Files:**
- Create: `container/node-red-tm/schema/migrations/0005_time_stopped.sql`, `container/node-red-tm/schema/tests/test_0005_time_stopped.py`
- Modify: `container/node-red-tm/schema/schema.sql`, `container/node-red-tm/schema/tests/helpers.py`, `test_0003_event_fields.py`, `test_0004_watch_log.py`

**Interfaces:**
- Produces: the columns `stationary_time` REAL, `stops` INTEGER, `zone_times` TEXT, the last three of `events`, in that order; `LATEST_VERSION = 5` (Task 2 makes it 6).

- [ ] **Step 1: Write the failing test**

```python
"""0005 adds the time stopped and the time in each zone: columns only, and the rows already there are left as they are."""

import sqlite3

from helpers import LATEST_VERSION, SCHEMA_DIR, columns, migrate, query, user_version

NEW_COLUMNS = {"stationary_time": "REAL", "stops": "INTEGER", "zone_times": "TEXT"}


def at_version_4(tmp_path):
    """A database migrated through 0004 only, with one event."""
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    for path in sorted((SCHEMA_DIR / "migrations").glob("000[1-4]_*.sql")):
        (migrations / path.name).write_text(path.read_text())
    db_path = tmp_path / "tmdb.sqlite"
    assert migrate("--db", db_path, "--migrations", migrations) == 0
    con = sqlite3.connect(db_path)
    con.execute("INSERT INTO events (id, camera, label, speed_calc, direction_source) VALUES (?, ?, ?, ?, ?)",
                ("1761800000.1-abc123", "camera_1_3fa9c2", "car", 22.5, "zones_radar"))
    con.commit()
    con.close()
    return db_path


def test_0005_adds_the_columns_and_rewrites_nothing(tmp_path):
    db_path = at_version_4(tmp_path)
    before = query(db_path, "SELECT * FROM events")
    assert user_version(db_path) == 4
    assert migrate("--db", db_path, "--backup-dir", tmp_path / "backup") == 0
    assert user_version(db_path) == LATEST_VERSION
    names = columns(db_path, "events")
    start = names.index("stationary_time")
    assert names[start:start + len(NEW_COLUMNS)] == list(NEW_COLUMNS)
    types = {row[1]: row[2] for row in query(db_path, "PRAGMA table_info(events)")}
    assert {name: types[name] for name in NEW_COLUMNS} == NEW_COLUMNS
    assert query(db_path, "SELECT * FROM events") == [before[0] + (None, None, None)]
```

- [ ] **Step 2: Run it and see it fail**

Run: `python -m pytest container/node-red-tm/schema/tests/test_0005_time_stopped.py -q`
Expected: FAIL: there is no `0005`, so `events` has no `stationary_time`.

- [ ] **Step 3: Write the migration.** Under a comment in the style of `0003_event_fields.sql` that says what each column holds, that the figures are seconds, that 21600 means six hours or more, that the three are empty together, and that rows written before it keep them empty:

```sql
ALTER TABLE events ADD COLUMN stationary_time REAL;
ALTER TABLE events ADD COLUMN stops INTEGER;
ALTER TABLE events ADD COLUMN zone_times TEXT;
```

- [ ] **Step 4: Bring the older tests in line.** `LATEST_VERSION = 5` in `helpers.py`. Two tests pinned things that are no longer last:
  - `test_0003_event_fields.py` compares the last eleven columns of `events` with its `NEW_COLUMNS`. Compare the eleven that start at `path_data` instead, as the new test does from `stationary_time`.
  - `test_0004_watch_log.py` asserts `user_version(db_path) == LATEST_VERSION == 4`. Drop the `== 4`.

- [ ] **Step 5: Regenerate `schema.sql`** with the command under "Commands", then run the schema suite and the control app's.

Run: `python -m pytest container/node-red-tm/schema/tests tm-control/backend/tests -q`
Expected: all pass, including `test_schema_sql_matches_the_migrations`.

- [ ] **Step 6: Commit**

```bash
git add container/node-red-tm/schema
git commit   # subject: Add time stopped and time in each zone to the events table (migration 0005)
```

---

### Task 2: An index on the radar readings' time (migration 0006)

**Files:**
- Create: `container/node-red-tm/schema/migrations/0006_radar_dov_time_index.sql`, `container/node-red-tm/schema/tests/test_0006_radar_dov_time_index.py`
- Modify: `container/node-red-tm/schema/schema.sql`, `container/node-red-tm/schema/tests/helpers.py`

**Interfaces:**
- Produces: the index `index_radar_dov_time` on `radar_dov(time)`; `LATEST_VERSION = 6`. Task 5 checks that the event's radar query uses it.

`radar_dov` has no index today, so the radar query each event runs reads the whole table. The other readers of the table gain too: the newest-five query on `capture-radar` and the date-range export on `ui-database`.

- [ ] **Step 1: Write the failing test**

```python
"""0006 adds an index on radar_dov(time), so a query for a stretch of time no longer reads the whole table."""

import sqlite3

from helpers import LATEST_VERSION, SCHEMA_DIR, migrate, query, user_version

EVENT_QUERY = ("SELECT * FROM radar_dov WHERE time BETWEEN 1761800000 AND 1761800009 "
               "AND radarName = 'TM_RADAR_SERIAL_PORT_00'")


def at_version_5(tmp_path):
    """A database migrated through 0005 only, with a few radar readings."""
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    for path in sorted((SCHEMA_DIR / "migrations").glob("000[1-5]_*.sql")):
        (migrations / path.name).write_text(path.read_text())
    db_path = tmp_path / "tmdb.sqlite"
    assert migrate("--db", db_path, "--migrations", migrations) == 0
    con = sqlite3.connect(db_path)
    con.executemany("INSERT INTO radar_dov (time, unit, direction, velocity, radarName) VALUES (?, 'mph', 'inbound', ?, ?)",
                    [(1761800000 + second, 20 + second, "TM_RADAR_SERIAL_PORT_00") for second in range(20)])
    con.commit()
    con.close()
    return db_path


def plan(db_path, sql):
    return " ".join(row[3] for row in query(db_path, "EXPLAIN QUERY PLAN " + sql))


def test_0006_adds_the_index_and_changes_no_row(tmp_path):
    db_path = at_version_5(tmp_path)
    before = query(db_path, "SELECT * FROM radar_dov ORDER BY time")
    assert user_version(db_path) == 5 and "USING INDEX" not in plan(db_path, EVENT_QUERY)
    assert migrate("--db", db_path, "--backup-dir", tmp_path / "backup") == 0
    assert user_version(db_path) == LATEST_VERSION
    assert query(db_path, "SELECT tbl_name FROM sqlite_master WHERE type = 'index' AND name = 'index_radar_dov_time'") == [
        ("radar_dov",)]
    assert [row[2] for row in query(db_path, "PRAGMA index_info(index_radar_dov_time)")] == ["time"]
    assert query(db_path, "SELECT * FROM radar_dov ORDER BY time") == before


def test_queries_for_a_stretch_of_time_use_the_index(tmp_path):
    db_path = tmp_path / "tmdb.sqlite"
    assert migrate("--db", db_path) == 0
    for sql in (EVENT_QUERY, EVENT_QUERY + " AND NOT (time > 1761800003 AND time < 1761800006)",
                "SELECT * FROM radar_dov ORDER BY time DESC LIMIT 5"):
        assert "USING INDEX index_radar_dov_time" in plan(db_path, sql)
    assert len(query(db_path, EVENT_QUERY)) == 0
```

- [ ] **Step 2: Run it and see it fail**

Run: `python -m pytest container/node-red-tm/schema/tests/test_0006_radar_dov_time_index.py -q`
Expected: FAIL: there is no `0006`, so there is no index.

- [ ] **Step 3: Write the migration.** Under a comment that says what the index is for (an event's radar query, the newest readings, and a date-range export read only their own stretch of time), that building it reads the whole table once, and that it takes about a fifth of the table's size on the card:

```sql
CREATE INDEX IF NOT EXISTS index_radar_dov_time ON radar_dov(time);
```

  The name follows the baseline's `index_radar_singleton_time`. Set `LATEST_VERSION = 6` in `helpers.py` and regenerate `schema.sql`.

- [ ] **Step 4: Run the suites**

Run: `python -m pytest container/node-red-tm/schema/tests tm-control/backend/tests -q`
Expected: all pass. A schema test that lists the indexes by hand gains this one.

- [ ] **Step 5: Time it on a made-up database,** as the schema `README.md` asks of a heavy migration. In a scratch directory, make a database from `schema.sql` at version 5 with ten million made-up `radar_dov` rows (increasing times, one radar name, a deployment id), run `tmdb_migrate.py --db <it> --backup-dir <scratch>/backup`, and note the whole time, the index's size, and the time of `EVENT_QUERY`-shaped query before and after. Put the figures in the commit message. (On a laptop: the index built in about 3 seconds and took 164 MB beside an 837 MB table, and the query went from about 480 ms to under 1 ms.) The bench times it on a Pi's card.

- [ ] **Step 6: Commit**

```bash
git add container/node-red-tm/schema
git commit   # subject: Index the radar readings by time (migration 0006)
```

---

### Task 3: The tally

**Files:**
- Modify: `container/node-red-tm/data/flows.json` (the new node; the `wires` of `f20c74c0ccfd256c`)
- Test: `script/tests/test_node_red_flows.py`

**Interfaces:**
- Consumes: `msg.payload` as Frigate sends it on `frigate/events`; `global.tm_warned`.
- Produces: the tally node, which passes every message on with `msg.time_tally` set as under "Names used across tasks", and keeps `flow.time_tallies`.

- [ ] **Step 1: Write the failing tests.** Add a section "Time stopped and time in each zone" at the end of `test_node_red_flows.py`.

```python
TALLY = "tally time stopped and time in zones"
T0 = 1761800000.0  # the first frame's time
TALLY_ID = "1761800000.0-abc123"


def frigate_message(kind, at, before_at, stationary=False, zones=(), event_id=TALLY_ID):
    """One frigate/events message, cut down to what the tally reads, with a camera name and a sub-label that must go
    no further. Times are seconds after T0. An end message's end_time is five seconds after its last frame."""
    after = {"id": event_id, "camera": "oak_ave_wide", "sub_label": ["Jane Doe", 0.97], "frame_time": T0 + at,
             "end_time": T0 + at + 5 if kind == "end" else None, "stationary": stationary,
             "current_zones": list(zones)}
    return {"topic": "frigate/events",
            "payload": {"type": kind, "before": {"id": event_id, "frame_time": T0 + before_at}, "after": after}}


def one_object(steps, event_id=TALLY_ID):
    """Frigate's messages for one object, from (type, seconds after T0, stationary, zones) steps. Each message's
    `before` holds the frame time of the message before it, as Frigate's does."""
    messages, last = [], steps[0][1]
    for kind, at, stationary, zones in steps:
        messages.append(frigate_message(kind, at, last, stationary, zones, event_id))
        last = at
    return messages


def run_tally(messages, flow=None):
    """Run the tally node on each message in turn. Returns the message the last one sent on and the flow context
    after. Every message must go on with its payload as it came, and nothing may be logged."""
    node = named(json.loads(FLOWS.read_text()), TALLY)
    run = run_functions([(node, copy.deepcopy(msg)) for msg in messages], context={"tm_warned": {}}, flow=flow or {})
    for step, msg in zip(run["results"], messages, strict=True):
        assert step["logged"] == [] and step["result"]["payload"] == msg["payload"]
    return run["results"][-1]["result"], run["flow"]


DRIVE_THROUGH = [("new", 0, False, []), ("update", 1, False, ["zone_far"]),
                 ("update", 2.5, False, ["zone_far", "zone_radar"]), ("update", 4, False, ["zone_near"]),
                 ("end", 5.5, False, ["zone_near"])]
STOP = [("new", 0, False, []), ("update", 2, False, ["zone_stop"]), ("update", 14, True, ["zone_stop"]),
        ("update", 40, False, ["zone_stop"]), ("update", 43, False, []), ("end", 45, False, [])]
STOP_TALLY = {"stationary_time": 26, "stops": 1, "zone_times": {"zone_stop": {"time": 41, "stationary": 26}},
              "stopped": [[T0 + 14, T0 + 40]]}


@needs_node
def test_a_drive_through_has_its_time_in_each_zone_and_no_stop():
    """The last stretch ends at the last frame the object was seen in: zone_near has 1.5 seconds, not 6.5."""
    out, flow = run_tally(one_object(DRIVE_THROUGH))
    assert out["time_tally"] == {"stationary_time": 0, "stops": 0, "stopped": [], "zone_times": {
        "zone_far": {"time": 3, "stationary": 0}, "zone_radar": {"time": 1.5, "stationary": 0},
        "zone_near": {"time": 1.5, "stationary": 0}}}
    assert flow["time_tallies"] == {}


@needs_node
def test_a_stop_in_a_zone_runs_from_frigates_flag_to_the_frame_the_object_moved_in():
    out, flow = run_tally(one_object(STOP))
    assert out["time_tally"] == STOP_TALLY and flow["time_tallies"] == {}


@needs_node
def test_until_the_end_the_figures_stay_in_the_tally():
    out, flow = run_tally(one_object(STOP)[:-1])
    assert out["time_tally"] is None
    assert flow["time_tallies"] == {TALLY_ID: {
        "at": T0 + 43, "stationary": False, "zones": [], "stationary_time": 26, "stops": 1,
        "zone_times": {"zone_stop": {"time": 41, "stationary": 26}}, "stopped": [[T0 + 14, T0 + 40]],
        "stopped_since": None, "broken": False}}
    # Frigate's name for the camera and the sub-label are kept nowhere
    assert "oak_ave_wide" not in json.dumps(flow) and "Jane Doe" not in json.dumps(flow)


@needs_node
def test_two_stops_are_counted_and_added_up():
    steps = [("new", 0, False, ["zone_a"]), ("update", 12, True, ["zone_a"]), ("update", 20, False, ["zone_a"]),
             ("update", 30, False, ["zone_b"]), ("update", 45, True, ["zone_b"]), ("update", 50, False, ["zone_b"]),
             ("end", 52, False, ["zone_b"])]
    out, _ = run_tally(one_object(steps))
    assert out["time_tally"] == {"stationary_time": 13, "stops": 2, "stopped": [[T0 + 12, T0 + 20], [T0 + 45, T0 + 50]],
                                 "zone_times": {"zone_a": {"time": 30, "stationary": 8},
                                                "zone_b": {"time": 22, "stationary": 5}}}


@needs_node
def test_an_object_that_is_stationary_when_first_heard_of_has_one_stop():
    out, _ = run_tally(one_object([("new", 0, True, ["zone_bay"]), ("update", 30, False, ["zone_bay"]),
                                   ("end", 34, False, [])]))
    assert out["time_tally"] == {"stationary_time": 30, "stops": 1, "stopped": [[T0, T0 + 30]],
                                 "zone_times": {"zone_bay": {"time": 34, "stationary": 30}}}


@needs_node
def test_no_figure_says_more_than_six_hours():
    out, _ = run_tally(one_object([("new", 0, False, ["zone_bay"]), ("update", 12, True, ["zone_bay"]),
                                   ("update", 30012, False, ["zone_bay"]), ("end", 30020, False, [])]))
    assert out["time_tally"] == {"stationary_time": 21600, "stops": 1, "stopped": [[T0 + 12, T0 + 30012]],
                                 "zone_times": {"zone_bay": {"time": 21600, "stationary": 21600}}}


@needs_node
def test_figures_are_rounded_to_two_decimals():
    out, _ = run_tally(one_object([("new", 0, False, ["zone_a"]), ("end", 0.123456, False, ["zone_a"])]))
    assert out["time_tally"]["zone_times"] == {"zone_a": {"time": 0.12, "stationary": 0}}


@needs_node
def test_an_object_first_heard_of_after_a_restart_gets_no_figures():
    """Node-RED restarted while Frigate was following it: no tally is started by an update or an end."""
    for count in (1, 2, 5):
        out, flow = run_tally(one_object(STOP)[count:])
        assert out["time_tally"] is None and flow.get("time_tallies", {}) == {}


@needs_node
def test_a_missed_message_leaves_the_figures_empty():
    messages = one_object(STOP)
    del messages[3]  # the update at 40 never arrived, so the next one's `before` isn't the last message seen
    _, flow = run_tally(messages[:-1])
    assert flow["time_tallies"][TALLY_ID]["broken"] is True
    out, flow = run_tally(messages)
    assert out["time_tally"] is None and flow["time_tallies"] == {}


@needs_node
def test_time_running_backwards_leaves_the_figures_empty():
    messages = [frigate_message("new", 3, 3), frigate_message("update", 1, 3), frigate_message("end", 5, 1)]
    out, _ = run_tally(messages)
    assert out["time_tally"] is None


@needs_node
def test_a_second_new_message_starts_the_tally_again():
    steps = [("new", 0, False, ["zone_a"]), ("update", 5, False, ["zone_a"]), ("new", 6, False, []),
             ("end", 8, False, [])]
    out, _ = run_tally(one_object(steps))
    assert out["time_tally"] == {"stationary_time": 0, "stops": 0, "stopped": [], "zone_times": {}}


@needs_node
def test_at_most_300_objects_are_followed_and_the_one_heard_of_longest_ago_goes_first():
    ids = [f"{T0 + i}-{i:06d}" for i in range(301)]
    messages = [frigate_message("new", i, i, event_id=ids[i]) for i in range(300)]
    messages.append(frigate_message("update", 300, 0, event_id=ids[0]))
    messages.append(frigate_message("new", 301, 301, event_id=ids[300]))
    _, flow = run_tally(messages)
    assert len(flow["time_tallies"]) == 300
    assert ids[1] not in flow["time_tallies"] and {ids[0], ids[2], ids[300]} <= set(flow["time_tallies"])


@needs_node
@pytest.mark.parametrize("later, kept", [(86400, True), (86401, False)])
def test_an_object_not_heard_of_for_more_than_a_day_is_dropped(later, kept):
    messages = [frigate_message("new", 0, 0), frigate_message("new", later, later, event_id="1761886400.0-zzz999")]
    _, flow = run_tally(messages)
    assert (TALLY_ID in flow["time_tallies"]) is kept and "1761886400.0-zzz999" in flow["time_tallies"]


@needs_node
def test_only_the_twenty_longest_stops_are_kept():
    steps = [("new", 0, False, [])]
    at = 0
    for length in [30, 5] + [40] * 20:  # the 5-second stop is the shortest of 22, then the 30-second one
        steps += [("update", at + 10, True, []), ("update", at + 10 + length, False, [])]
        at += 10 + length
    steps.append(("end", at + 1, False, []))
    out, _ = run_tally(one_object(steps))
    lengths = sorted(round(to - start) for start, to in out["time_tally"]["stopped"])
    assert lengths == [40] * 20 and out["time_tally"]["stops"] == 22
    assert out["time_tally"]["stationary_time"] == 835


@needs_node
@pytest.mark.parametrize("zones, expected", [
    ("zone_a", []), (None, []), ({"zone_a": 1}, []),
    (["zone_a", 7, None, "zone_a", "zone_b", ""], ["zone_a", "zone_b"]),
    ([f"zone_{i}" for i in range(60)], [f"zone_{i}" for i in range(50)]),
], ids=["text", "null", "mapping", "junk-in-the-list", "more-than-fifty"])
def test_only_zone_names_are_tallied_and_at_most_fifty(zones, expected):
    messages = one_object([("new", 0, False, []), ("end", 2, False, [])])
    for msg in messages:
        msg["payload"]["after"]["current_zones"] = zones
    out, _ = run_tally(messages)
    assert list(out["time_tally"]["zone_times"]) == expected


@needs_node
@pytest.mark.parametrize("payload", [
    "online", None, 7, [], {}, {"type": "end"}, {"type": "end", "after": None},
    {"type": "end", "after": {"id": "", "frame_time": T0}}, {"type": "end", "after": {"id": 7, "frame_time": T0}},
    {"type": "end", "after": {"id": TALLY_ID, "frame_time": "soon"}},
    {"type": "sideways", "before": {"frame_time": T0}, "after": {"id": TALLY_ID, "frame_time": T0}},
], ids=["text", "null", "number", "list", "empty", "no-after", "after-null", "no-id", "id-number", "time-text",
        "unknown-type"])
def test_a_message_that_is_not_frigates_shape_goes_on_untouched(payload):
    out, flow = run_tally([{"topic": "frigate/events", "payload": payload, "time_tally": {"stationary_time": 999}}])
    assert out["time_tally"] is None and flow.get("time_tallies", {}) == {}


@needs_node
@pytest.mark.parametrize("flow", [{"time_tallies": "junk"}, {"time_tallies": [1]}, {"time_tallies": {TALLY_ID: "junk"}}])
def test_junk_in_flow_context_is_replaced(flow):
    out, _ = run_tally(one_object(STOP), flow=flow)
    assert out["time_tally"] == STOP_TALLY


def test_every_frigate_event_message_passes_the_tally_first():
    flows = json.loads(FLOWS.read_text())
    by_id = {node["id"]: node for node in flows}
    tally, source, switch = named(flows, TALLY), by_id["f20c74c0ccfd256c"], by_id["2deec9d340d5ed26"]
    assert (source["type"], source["topic"]) == ("mqtt in", "frigate/events")
    assert source["wires"] == [["86c86b0d82d13028", tally["id"]]] and by_id["86c86b0d82d13028"]["type"] == "debug"
    assert tally["wires"] == [[switch["id"]]] and switch["name"] == 'payload.type == "end"'
    assert [node["id"] for node in flows if switch["id"] in sum(node.get("wires", []), [])] == [tally["id"]]
    assert (tally["type"], tally["outputs"], tally["initialize"], tally["finalize"]) == ("function", 1, "", "")
    group = by_id[tally["g"]]
    assert group["id"] == "0a5faeac9fbd6d55" and tally["id"] in group["nodes"] and tally["z"] == source["z"]
    assert group["x"] < tally["x"] < group["x"] + group["w"] and group["y"] < tally["y"] < group["y"] + group["h"]
```

Add `import copy` at the top of the file if it isn't there.

- [ ] **Step 2: Run them and see them fail**

Run: `python -m pytest script/tests/test_node_red_flows.py -q`
Expected: the new section's tests fail (no node named "tally time stopped and time in zones"); everything else passes.

- [ ] **Step 3: Add the node and rewire.** With a script, add the function node "tally time stopped and time in zones" (one output) to the group `0a5faeac9fbd6d55`, placed between the `frigate/events` node and the `payload.type == "end"` switch, and wire it to that switch. In the `wires` of `f20c74c0ccfd256c`, put the new node's id where the switch's was; the debug node stays. Nothing else moves unless it would overlap.

- [ ] **Step 4: Write the tally node.** `(msg) -> msg`, always the message it was given. Its rules, in order:
  1. Set `msg.time_tally = null`. Everything after this is inside one `try`; the `catch` warns once (`time_tally:error`: "The time an object stopped couldn't be worked out for some events; they are saved without it.") and falls through to `return msg`. The warning holds no value from the message.
  2. Return when `msg.payload` isn't a mapping, its `type` isn't `new`, `update`, or `end`, its `after` isn't a mapping, `after.id` isn't a non-empty text, or `after.frame_time` isn't a finite number.
  3. Read the message's state: `at = after.frame_time`; `stationary = after.stationary === true`; `zones` = the non-empty texts in `after.current_zones` when that is a list, each once, in its order (else none).
  4. Take `flow.get("time_tallies")`; when it isn't a mapping, start with an empty one. A stored tally that isn't a mapping counts as absent.
  5. **`new`:** store a fresh tally under the id, replacing any that is there: `at`, `stationary`, `zones` (the first `MAX_ZONES`), `stationary_time` 0, `stops` 1 when stationary else 0, a `{time: 0, stationary: 0}` entry in `zone_times` for each zone, `stopped` empty, `stopped_since` `at` when stationary else `null`, `broken` false. Then drop every tally whose `at` is more than `DEAD_AFTER` before this message's `at`, and while there are more than `MAX_TALLIES`, drop the one updated longest ago.
  6. **`update` or `end` with no tally:** nothing is stored. Return.
  7. **`update` or `end` with a tally:**
     - Mark it broken when `payload.before` isn't a mapping, `before.frame_time !== tally.at`, or `at < tally.at`. A broken tally takes no more sums, and stays until its `end` so that no later message starts a new one.
     - Otherwise, with `seconds = at - tally.at`: add `seconds` to `stationary_time` when the tally says stationary; for each zone the tally says the object is in, add `seconds` to its `time`, and to its `stationary` when the tally says stationary.
     - Then the flips. Moving to stationary: `stops` plus 1, `stopped_since = at`. Stationary to moving: add `[stopped_since, at]` to `stopped`, and when that makes more than `MAX_STOPPED`, drop the shortest; `stopped_since = null`.
     - Give each zone not yet in `zone_times` a zero entry, while `zone_times` has fewer than `MAX_ZONES`; a zone beyond that is ignored.
     - Set `at`, `stationary`, and `zones` from the message (of the zones, only those that have an entry in `zone_times`), and move the tally to the end of `time_tallies` (delete the key and set it again, so the order of the keys is the order of the last update).
  8. **`end`:** after rule 7, close an open stretch the same way, remove the tally, and when it isn't broken set `msg.time_tally = {stationary_time, stops, zone_times, stopped}`, with `stationary_time` and each `time` and `stationary` cut to `MAX_SECONDS` and rounded to two decimals. `stopped` is passed as it is.
  9. `flow.set("time_tallies", tallies)`; `return msg`.

  A comment at the top says what the node is for, that Frigate sends no times so they are added up from its flags, that a tally starts only at `new` (so a restart leaves an event's figures empty, never part of them), that the clock is the last frame the object was seen in, and that only an id, numbers, and zone names are kept. `warnOnce` is the helper "event finalize output" has; copy it.

- [ ] **Step 5: Run the tests**

Run: `python -m pytest script/tests/test_node_red_flows.py -q`
Expected: all pass. A test that pinned the `frigate/events` node's wires, or walks from it to the switch, now goes through the new node.

- [ ] **Step 6: Commit**

```bash
git add container/node-red-tm/data/flows.json script/tests/test_node_red_flows.py
git commit   # subject: Add up how long each object stood still and spent in each zone
```

---

### Task 4: The three figures are saved and uploaded with the event

**Files:**
- Modify: `container/node-red-tm/data/flows.json` (`a8aeffd2e5bc17f2`, `a96d834e3571c549`, `61d6a19c99c60e0b`), `container/node-red-tm/data/upload-lists.json`, `container/node-red-tm/data/README.md`
- Test: `script/tests/test_node_red_flows.py`

**Interfaces:**
- Consumes: `msg.time_tally` from Task 3; the columns from Task 1.
- Produces: the finalize payload's last three keys, `stationary_time`, `stops`, `zone_times`, after `direction_source`; the same three as the INSERT's last columns and parameters and as the last names of the upload's `event` list.

- [ ] **Step 1: Write the failing tests.** Change the constants and the helper:
  - `EVENT_COLUMNS` ends with `"stationary_time", "stops", "zone_times"`.
  - `JSON_COLUMNS` gains `"zone_times"`.
  - `finalize_msg` gains `tally=MISSING`, and sets `msg["time_tally"] = tally` unless it is `MISSING`.

  And add, in the new section:

```python
def saved_times(tally=MISSING):
    [step] = run_functions([(node_by_id(FINALIZE), finalize_msg("inbound", 22.5, 7, tally=tally))])["results"]
    payload = step["result"]["payload"]
    assert step["logged"] == [] and "stopped" not in payload
    return payload["stationary_time"], payload["stops"], payload["zone_times"]


@needs_node
def test_the_times_are_saved_with_the_event():
    assert saved_times(STOP_TALLY) == (26, 1, {"zone_stop": {"time": 41, "stationary": 26}})
    assert saved_times({**STOP_TALLY, "stationary_time": 0, "stops": 0, "zone_times": {}}) == (0, 0, {})


@needs_node
@pytest.mark.parametrize("tally", [
    MISSING, None, "text", [], {}, {key: value for key, value in STOP_TALLY.items() if key != "stops"},
    {**STOP_TALLY, "stops": 1.5}, {**STOP_TALLY, "stops": -1}, {**STOP_TALLY, "stationary_time": "26"},
    {**STOP_TALLY, "stationary_time": -1}, {**STOP_TALLY, "zone_times": []}, {**STOP_TALLY, "zone_times": None},
    {**STOP_TALLY, "zone_times": {"zone_stop": {"time": 41}}},
    {**STOP_TALLY, "zone_times": {"zone_stop": {"time": "41", "stationary": 0}}},
    {**STOP_TALLY, "zone_times": {"zone_stop": 41}},
])
def test_times_that_are_not_whole_are_all_left_empty(tally):
    assert saved_times(tally) == (None, None, None)


@needs_node
def test_zone_times_is_stored_as_json_text():
    payload = {name: None for name in EVENT_COLUMNS} | {"zone_times": STOP_TALLY["zone_times"], "stops": 1,
                                                        "stationary_time": 26}
    [step] = run_functions([(node_by_id(EVENT_PARAMS), {"payload": payload})])["results"]
    params = step["result"]["params"]
    assert (params["$stationary_time"], params["$stops"]) == (26, 1)
    assert json.loads(params["$zone_times"]) == STOP_TALLY["zone_times"]
```

  Then a whole-chain test beside `test_a_made_up_event_on_a_camera_without_a_radar_becomes_a_row`, named `test_a_made_up_run_of_messages_becomes_a_row_with_its_times`: build the messages of `STOP` with `one_object`, give the last one's `after` the fields that test's `after` has, run all of them through the tally node, then the last result through the same chain of nodes and the node's own INSERT against `schema.sql`. Assert the row's `stationary_time`, `stops`, `json_extract(zone_times, '$.zone_stop.time')`, and `json_extract(zone_times, '$.zone_stop.stationary')` are `(26.0, 1, 41, 26)`. In the existing made-up event test, which sends an `end` alone, add the three columns to the SELECT and assert all three are `None`.

- [ ] **Step 2: Run them and see them fail**

Run: `python -m pytest script/tests/test_node_red_flows.py -q`
Expected: the new tests and `test_event_fields_agree` fail.

- [ ] **Step 3: "event finalize output" (`a8aeffd2e5bc17f2`).** Before `newPayload`, read `msg.time_tally` into three values that are all set or all `null`. They are set only when it is a mapping whose `stationary_time` is a finite number of 0 or more, whose `stops` is a whole number of 0 or more, and whose `zone_times` is a mapping in which every value is a mapping with finite numbers `time` and `stationary`. Add the three keys after `direction_source`, in the order of `EVENT_COLUMNS`. `stopped` is not copied. Add a line to the comment at the top: the three come from the tally node, all or none.

- [ ] **Step 4: "write params for events insert" (`a96d834e3571c549`) and the INSERT (`61d6a19c99c60e0b`).** The three names join `COLUMNS`, and `zone_times` joins `JSON_COLUMNS`. The INSERT gains the three columns and `$stationary_time, $stops, $zone_times`, as `$path_data` is written (the parameter is already JSON text).

- [ ] **Step 5: `upload-lists.json`.** Add the three names at the end of `event`, one per line. In `container/node-red-tm/data/README.md`, nothing lists the event fields by name; change it only if a count or an example there is now wrong.

- [ ] **Step 6: Run the tests**

Run: `python -m pytest script/tests container/node-red-tm/schema/tests -q`
Expected: all pass, including `test_event_fields_agree`, `test_upload_lists_file`, `test_everything_uploaded_passes_the_gate`, and `test_flow_sql_compiles_against_schema`. Bring a test that lists the event fields by hand in line.

- [ ] **Step 7: Commit**

```bash
git add container/node-red-tm/data script/tests
git commit   # subject: Save and upload the time stopped and the time in each zone with each event
```

---

### Task 5: Radar readings only from when the object was moving

**Files:**
- Modify: `container/node-red-tm/data/flows.json` (`b39062019fac1a66`)
- Test: `script/tests/test_node_red_flows.py`

**Interfaces:**
- Consumes: `msg.time_tally.stopped` from Task 3; `msg.frigate_event.start_time`, `end_time`, `radarName`; the index from Task 2.
- Produces: `msg.topic`, the query "query radar readings around event time" runs.

- [ ] **Step 1: Write the failing tests**

```python
PULL_SPEED = "b39062019fac1a66"  # capture-events: pull speed, direction for event period


def radar_query(tally=MISSING):
    msg = {"frigate_event": {"start_time": T0 + 0.4, "end_time": T0 + 49.6, "radarName": "TM_RADAR_SERIAL_PORT_00"}}
    if tally is not MISSING:
        msg["time_tally"] = tally
    [step] = run_functions([(node_by_id(PULL_SPEED), msg)])["results"]
    assert step["logged"] == []
    return step["result"]["topic"]


def radar_seconds(tally=MISSING):
    """Which readings the event's query returns, out of one a second from 10 before T0 to 70 after, for this radar
    and for another one. As whole seconds after T0."""
    con = sqlite3.connect(":memory:")
    con.executescript(SCHEMA_SQL.read_text())
    con.executemany("INSERT INTO radar_dov (time, radarName, direction, velocity) VALUES (?, ?, 'inbound', 20)",
                    [(T0 + second, name) for second in range(-10, 71)
                     for name in ("TM_RADAR_SERIAL_PORT_00", "TM_RADAR_SERIAL_PORT_01")])
    # the flow's query names the radar in double quotes, which not every build of SQLite takes as text
    rows = con.execute(radar_query(tally).replace('"', "'")).fetchall()
    assert {row[4] for row in rows} <= {"TM_RADAR_SERIAL_PORT_00"}
    return sorted(round(row[0] - T0) for row in rows)


WHOLE_WINDOW = list(range(-2, 53))  # two seconds before the start to two after the end


@needs_node
def test_an_event_that_never_stopped_gets_the_query_it_gets_today():
    assert radar_seconds() == WHOLE_WINDOW
    for tally in (None, {**STOP_TALLY, "stopped": []}, {"stationary_time": 0}):
        assert radar_query(tally) == radar_query() and "NOT" not in radar_query(tally)


@needs_node
def test_the_readings_while_the_object_stood_still_are_left_out():
    """Stopped from 14 to 40: the readings after 16 and before 38 are left out, two seconds kept at each end."""
    assert radar_seconds(STOP_TALLY) == list(range(-2, 17)) + list(range(38, 53))
    two = {**STOP_TALLY, "stopped": [[T0 + 5.5, T0 + 12.5], [T0 + 30, T0 + 44]]}
    # 5.5 to 12.5 leaves out only second 9, and 30 to 44 leaves out 33 to 41
    assert radar_seconds(two) == list(range(-2, 9)) + list(range(10, 33)) + list(range(42, 53))


@needs_node
@pytest.mark.parametrize("stopped", [
    [[T0 + 14, T0 + 18]], [[T0 + 40, T0 + 14]], "text", None, [[T0 + 14]], [None, "text", 7],
    [["1; DROP TABLE radar_dov", T0 + 40]], [[T0 + 14, "40"]], [[T0 + 14, None]],
], ids=["too-short", "backwards", "text", "null", "one-number", "not-pairs", "text-in-a-pair", "text-end", "null-end"])
def test_a_stretch_that_cannot_be_used_leaves_the_whole_window(stopped):
    assert radar_seconds({**STOP_TALLY, "stopped": stopped}) == WHOLE_WINDOW


@needs_node
def test_the_events_radar_query_reads_only_its_own_stretch_of_time():
    """Task 2's index is used by the query as the flow writes it, with and without stretches left out."""
    con = sqlite3.connect(":memory:")
    con.executescript(SCHEMA_SQL.read_text())
    for tally in (MISSING, STOP_TALLY):
        plan = con.execute("EXPLAIN QUERY PLAN " + radar_query(tally).replace('"', "'")).fetchall()
        assert "USING INDEX index_radar_dov_time" in " ".join(row[3] for row in plan)


@needs_node
def test_at_most_twenty_stretches_are_left_out():
    stopped = [[T0 + second, T0 + second + 6] for second in range(0, 44, 2)]  # 22 stretches
    assert radar_query({**STOP_TALLY, "stopped": stopped}).count("NOT") == 20
```

- [ ] **Step 2: Run them and see them fail**

Run: `python -m pytest script/tests/test_node_red_flows.py -q -k "never_stopped or stood_still or stretch"`
Expected: the stood-still test and the twenty test fail; the others pass, since today's query ignores the tally and Task 2 added the index.

- [ ] **Step 3: Change "pull speed, direction for event period".** Build today's query exactly as now. Then, when `msg.time_tally` is a mapping whose `stopped` is a list, for each of its first 20 entries that is a pair of finite numbers `[from, to]` with `Math.floor(to) - 2 > Math.ceil(from) + 2`, add before the closing `;`:

```
AND NOT (time > ${Math.ceil(from) + 2} AND time < ${Math.floor(to) - 2})
```

  Only whole numbers worked out here go into the text. With nothing to add, the query is today's, character for character. A comment says why: a parked car's radar speed would otherwise be the median of everything that passed while it stood.

- [ ] **Step 4: Run the tests**

Run: `python -m pytest script/tests -q`
Expected: all pass.

- [ ] **Step 5: Stop for a look at the flows.** The flow changes are complete here. Tell the maintainer, who reads them in Node-RED before the docs are written.

- [ ] **Step 6: Commit**

```bash
git add container/node-red-tm/data/flows.json script/tests/test_node_red_flows.py
git commit   # subject: Take a stopped object's radar speed only from when it was moving
```

---

### Task 6: The notice and the Sharing page's example

**Files:**
- Modify: `tm-control/backend/tm_control/modules/sharing/NOTICE.md`, `tm-control/ui/src/modules/sharing/examples.ts`, the UI test that pins the example if one does

- [ ] **Step 1: The example.** In `SHARE_DATA_EXAMPLE`, the event gains, after `box`:

```ts
      stationary_time: 0,
      stops: 0,
      zone_times: { zone_near: { time: 1.2, stationary: 0 }, zone_far: { time: 1.4, stationary: 0 } },
```

  The comment above the constant names them. Run the UI build and tests (the command under "Commands") and bring any test that pins the example in line.

- [ ] **Step 2: Draft the notice's sentence, and stop.** The notice is the maintainer's text. Propose, in the first paragraph under "Share data", changing the sentence about the path to: "For each object it counted, it also sends the path the object took across the camera's picture and the box around it, as numbers, never a picture, and how long the object stood still and how long it spent in each zone." Show the maintainer the paragraph before and after, and take the maintainer's wording and decision on the notice's version (`2026-11` today; no release has carried it yet).

- [ ] **Step 3: Commit** after the maintainer's answer.

```bash
git add tm-control
git commit   # subject: Say in the sharing notice and its example that the time stopped is sent
```

---

### Task 7: Docs

**Files:** the six under "Docs" in the table above.

- [ ] **Step 1: `docs/data-and-payloads/events-payload.md`.**
  - "How an event is made", step 1: Frigate also sends `new` and `update` messages while it follows the object, and the Traffic Monitor adds up from them how long the object stood still and how long it was in each zone.
  - "Direction and speed", the radar paragraph: for an object that stopped, the readings from while it stood still are left out, with the same two-second margin.
  - Three rows in "Columns", after `frigate_velocity_angle`: `stationary_time` (REAL; seconds; at most 21600, which means six hours or more), `stops` (INTEGER), `zone_times` (TEXT; a JSON object with an example; each figure at most 21600). Each says it is empty when the figures couldn't be worked out, and links to the new section.
  - Correct `end_time`'s meaning: it is when Frigate stopped following the object, which is up to about five seconds after it last saw it; `frame_time` is the last frame it was seen in.
  - A new section, "Time stopped and time in each zone", after "Direction and speed", for a person reading the database:
    - Where the figures come from: Frigate says with each message whether the object is stationary and which zones it is in, and the device adds up the time between messages.
    - What "stationary" means: Frigate flags an object once it hasn't moved for about ten seconds (its [stationary objects](https://docs.frigate.video/configuration/stationary_objects) setting), so `stationary_time` starts ten seconds into each stop. To get the whole stop, add ten seconds for each of `stops`. A stop shorter than that doesn't show here; for those, use a zone's time.
    - What a zone's time is: from when Frigate lists the object in the zone to when it stops. Three things to know: Frigate lists an object after three frames in a row inside (the zone's inertia); a zone with a loitering time lists it only after that time, so its figure is the time beyond it; and a zone with side lengths for speed estimation lists an object only while it moves, so it never has stopped time. Draw a stop or parking zone without side lengths.
    - The figures run to the last frame the object was seen in, so they add up to a little less than `end_time` minus `start_time`.
    - Six hours is the most a figure says.
    - When the three are empty: Node-RED restarted while the object was being followed, a message from Frigate was missed, more than 300 objects were being followed at once, or the row is from an earlier version. They are empty together.
    - Parked vehicles: one that drives in, parks, and drives off is one event, saved when it leaves, with the time it was parked. If Frigate loses sight of a parked vehicle and finds it again, the time before is lost, because an event that ends while the object is stationary isn't recorded.
    - One SQL example: the stopped time in a zone for each car of a day, with `json_extract(zone_times, '$.zone_stop_sign_e.time')`.
  - The sentence about rows from an earlier version names the three columns, and the sentence listing the JSON columns gains `zone_times`.
- [ ] **Step 2: `docs/help-and-faq/use-cases-and-scenarios.md`.**
  - In "Vehicles that don't stop at a stop sign", after the steps: a second way that needs no time chosen in advance. Give the stop-sign zone no loitering time and no side lengths; every vehicle's event then has its seconds in the zone in `zone_times`, and you can try one, two, or three seconds afterwards. Say that Frigate's own stationary flag is no help here, because it needs ten seconds, and that a zone with a loitering time records only the time beyond it.
  - A new section, "How long vehicles stay parked": draw a zone over the parking bays, without side lengths; a vehicle that parks and leaves is one event, and `zone_times` has its time in the bay and how much of it stationary. An example for a 15-minute bay (events with more than 900 seconds stationary in the zone). The limits: six hours is the most a figure says; a vehicle already parked when the device started, or still parked, has no event yet; one Frigate lost and found again is recorded only from where it was found.
  - The page's `description:` names parking.
- [ ] **Step 3: `docs/configuration/frigate-config.md`**, in "Speed without a radar": one sentence, that a zone with side lengths lists an object only while it moves, so its time in `zone_times` leaves out any time stopped (link to the events page's section).
- [ ] **Step 4: `docs/data-and-payloads/integrations.md`**: the `frigate/events` row says the device records the `end` messages as events and reads the `new` and `update` messages for the time stopped and the time in each zone.
- [ ] **Step 5: `docs/use/sharing.md`**: the **Share data** row names how long each object stood still and spent in each zone.
- [ ] **Step 6: `CLAUDE.md`**: the `capture-events` bullet gains the tally: the node "tally time stopped and time in zones" reads every `frigate/events` message before the `end` switch, keeps `flow.time_tallies` (memory; starts at `new` only; `before.frame_time` checked against the last message; 300 tallies), and sets `msg.time_tally` on the `end` message; and the speed sub-bullet says the readings from while the object was stationary are left out. Under storage, `radar_dov` is indexed by `time` (`0006`), and a query on it should name a stretch of time.
- [ ] **Step 7: Build the docs**

Run: `~/.venvs/tm-docs/bin/mkdocs build --strict`
Expected: it builds with no warning.

- [ ] **Step 8: Commit**

```bash
git add docs CLAUDE.md
git commit   # subject: Document the time stopped and the time in each zone
```

---

### Task 8: A device test

**Files:**
- Modify: `script/devpi/tests/test_disruptive.py`, `script/devpi/README.md`

**Interfaces:**
- Produces: `test_a_made_up_run_of_messages_is_recorded_with_its_times(host, expect, codedir, node_red_config, frigate_config)`.

- [ ] **Step 1: The test.** Beside `test_a_made_up_event_is_recorded_with_its_path_and_boxes`, with the same skips (`pii_free`, no broker login, an enabled camera entry Frigate has) and the same `after` fields, label `tmdev_check`, and zone `zone_tmdev`; the id ends in `-tmdev1`. Take the helpers the two tests share out into one function. It publishes five messages on the Pi's broker, each one's `before` the `after` of the one before, with made-up frame times counted from `t = round(pi_now(host)) - 60` (the tally reads frame times, not the clock, so nothing waits):

  | Type | `frame_time` | `stationary` | `current_zones` |
  |---|---|---|---|
  | `new` | t | false | none |
  | `update` | t + 2 | false | `zone_tmdev` |
  | `update` | t + 14 | true | `zone_tmdev` |
  | `update` | t + 40 | false | `zone_tmdev` |
  | `end` | t + 45 (`end_time` t + 50) | false | `zone_tmdev` |

  It waits for the row as the other test does and asserts `stationary_time` is 26, `stops` is 1, and `zone_times` parsed as JSON is `{"zone_tmdev": {"time": 43, "stationary": 26}}`. The other test, which sends an `end` alone, also asserts that its row's three columns are empty.

- [ ] **Step 2: Check it collects**

Run: `python -m pytest script/devpi/tests --collect-only -q | grep made_up`
Expected: both tests are listed.

- [ ] **Step 3: `script/devpi/README.md`**: the test joins the `test_disruptive.py` row and the paragraph "The made-up event test" (two ids now, `-tmdev0` and `-tmdev1`; five messages; the rows stay).

- [ ] **Step 4: Commit**

```bash
git add script/devpi
git commit   # subject: Add a device test that sends a made-up object's messages and reads its times
```

---

### Review fixes (Tasks R1 to R3)

Added on 2026-11-19, after the whole-branch review of Tasks 1 to 8 (`c379c88b..55cb70c`). The review found one way to save a wrong figure and three places where the text says more than the code does. The maintainer took all four, with a limit of 300 seconds. They are done after Task 8 and before Task 9, as three commits. Where a task below differs from Task 3 or Task 7 above, the task below is the one that holds.

Left as they are (the review's nits): a frame time of 1e21 or more goes into the radar query in exponent form, which is still a number; the never-stopped test compares the new node with itself; the tally node sits to the right of the switch it feeds; the six-hour limit is said in more than one place in the docs.

### Task R1: More than five minutes between two messages empties the figures

**Files:**
- Modify: `container/node-red-tm/data/flows.json` (the tally node, `1d7d59fbe4e3114d`, its `func` only), `script/tests/test_node_red_flows.py`, `docs/data-and-payloads/events-payload.md`, `CLAUDE.md`

What was found: the tally breaks when time runs backwards, but a clock set forward between two chained messages is added as if the object had been watched all that time. A car in a zone across a two-hour step got 7,201 seconds in the zone, and a parked one got 21,600 in all three places. Frigate's frame time is the device's clock, so this happens when the time arrives late after a boot, or an admin sets it.

- [ ] **Step 1: Write the failing tests,** in the section "Time stopped and time in each zone".

```python
@needs_node
@pytest.mark.parametrize("stationary", [False, True], ids=["moving", "stationary"])
@pytest.mark.parametrize("gap, whole", [(300, True), (300.5, False), (7200, False)])
def test_more_than_five_minutes_between_two_messages_leaves_the_figures_empty(stationary, gap, whole):
    """The clock was set forward, or the camera stalled: Frigate's chain of messages is whole, but the time between
    two of them isn't time the object was watched."""
    steps = [("new", 0, False, ["zone_bay"]), ("update", 12, stationary, ["zone_bay"]),
             ("update", 12 + gap, stationary, ["zone_bay"]), ("update", 14 + gap, False, ["zone_bay"]),
             ("end", 16 + gap, False, [])]
    out, flow = run_tally(one_object(steps))
    assert (out["time_tally"] is not None) is whole and flow["time_tallies"] == {}
    if whole:
        assert out["time_tally"]["zone_times"] == {
            "zone_bay": {"time": 16 + gap, "stationary": 2 + gap if stationary else 0}}


@needs_node
def test_a_gap_before_the_end_message_counts_too():
    out, _ = run_tally(one_object([("new", 0, False, ["zone_bay"]), ("end", 301, False, ["zone_bay"])]))
    assert out["time_tally"] is None
```

  And replace `test_no_figure_says_more_than_six_hours`, whose one step of 30,000 seconds is now a gap, with a stay that has an update a minute, as Frigate sends them:

```python
@needs_node
def test_no_figure_says_more_than_six_hours():
    """Parked for a little over six hours, with an update a minute, as Frigate sends them."""
    steps = [("new", 0, False, ["zone_bay"]), ("update", 12, True, ["zone_bay"])]
    steps += [("update", 12 + 60 * minute, True, ["zone_bay"]) for minute in range(1, 362)]
    steps += [("update", 21700, False, ["zone_bay"]), ("end", 21708, False, [])]
    out, _ = run_tally(one_object(steps))
    assert out["time_tally"] == {"stationary_time": 21600, "stops": 1, "stopped": [[T0 + 12, T0 + 21700]],
                                 "zone_times": {"zone_bay": {"time": 21600, "stationary": 21600}}}
```

  No other test in the section has two messages for one object more than 300 seconds apart (the 300-objects test has exactly 300, which is kept). If one turns up, give it steps a minute apart; don't loosen the rule.

- [ ] **Step 2: Run them and see them fail**

Run: `python -m pytest script/tests/test_node_red_flows.py -q -k "five_minutes or gap_before or six_hours"`
Expected: the `300.5` and `7200` cases and the end case fail (the figures are there); the `300` cases and the six-hour test pass.

- [ ] **Step 3: Change the tally node,** with a script, written back as under Global Constraints. Three changes to its `func` and nothing else in `flows.json`:
  - A constant after `MAX_ZONES`: `const MAX_GAP = 300;` with a comment in the style of the others: seconds of frame time between two messages about one object; more empties its figures.
  - The broken test gains a fourth condition: `if (!isMapping(before) || before.frame_time !== tally.at || at < tally.at || at - tally.at > MAX_GAP) {`.
  - The comment at the top gains one sentence after the one about a missed message: Frigate sends an update for an object it is following at least once a minute, so more than five minutes between two messages means the clock was set or the camera stalled, and the event gets no figures either.

- [ ] **Step 4: The docs that go with it.**
  - `docs/data-and-payloads/events-payload.md`, in "When the three columns are empty", after the bullet about a message that didn't arrive: "More than five minutes passed between two of Frigate's messages about the object, as when the device's clock was set or the camera sent no frames for a while."
  - `CLAUDE.md`, the tally's sub-bullet under `capture-events`: where it says `before.frame_time` must equal the last message's frame time or the tally is broken, say that the message must also come at most 300 s of frame time after the last one.

- [ ] **Step 5: Run the tests and the docs build**

Run: `python -m pytest script/tests -q` and `~/.venvs/tm-docs/bin/mkdocs build --strict`
Expected: all pass, including `test_flows_json_round_trips_through_json_dumps`.

- [ ] **Step 6: Commit**

```bash
git add container/node-red-tm/data/flows.json script/tests/test_node_red_flows.py docs/data-and-payloads/events-payload.md CLAUDE.md
git commit   # subject: Leave the times empty when more than five minutes pass between two messages
```

### Task R2: The docs say what a parked vehicle's time counts from, and what the radar rule leaves in

**Files:**
- Modify: `docs/data-and-payloads/events-payload.md`, `docs/help-and-faq/use-cases-and-scenarios.md`

What was found: a vehicle already parked when the device started does get a row when it leaves, timed only from the start, and a restart of Frigate alone does the same (the old object never ends, and a new one begins). Nothing marks such a row, and the docs said only that the vehicle "has no event yet". And the radar sentence said a parked car's speed doesn't come from the traffic that passed it, when about the first twelve seconds of each stop still count (Frigate's flag starts about ten seconds in, and the rule keeps two more).

- [ ] **Step 1: `docs/help-and-faq/use-cases-and-scenarios.md`,** the limits under "How long vehicles stay parked". The bullet "A vehicle that was already parked when the device started, or is still parked, has no event yet." becomes two:
  - "A vehicle that is still parked has no event yet."
  - "A vehicle that was already parked when the device or Frigate started is timed only from then."

  The bullet about Frigate losing sight of a vehicle stays as it is.

- [ ] **Step 2: `docs/data-and-payloads/events-payload.md`.**
  - In "Time stopped and time in each zone", the paragraph that begins "A vehicle that drives in, parks, and drives off is one event" gains a last sentence: "A vehicle that was already parked when the device or Frigate started is timed only from then."
  - In "Direction and speed", the sentence "For an object that stood still, the readings from while it was stationary are left out, with the same two-second margin, so a parked car's speed doesn't come from the traffic that passed it." becomes: "For an object that stood still, the readings from while Frigate held it as stationary are left out, with the same two-second margin, so most of the traffic that passed a parked car doesn't count toward its speed. Frigate's flag starts about ten seconds into a stop, so the readings from those first seconds stay in."

- [ ] **Step 3: Build the docs**

Run: `~/.venvs/tm-docs/bin/mkdocs build --strict`
Expected: it builds with no warning.

- [ ] **Step 4: Commit**

```bash
git add docs
git commit   # subject: Say what a parked vehicle's time counts from and what the radar rule leaves in
```

### Task R3: Say what a card too full for the index costs

**Files:**
- Modify: `container/node-red-tm/schema/migrations/0006_radar_dov_time_index.sql` (its comment only; the file has been applied to no device and merged nowhere)

What was found: the comment says the device "then works as before and tries again at each start". It does keep recording, but every start of Node-RED then repeats the backup and the failed build, with Node-RED and its broker down meanwhile, and the Status page reports the schema as behind.

- [ ] **Step 1: The comment's last paragraph becomes:**

```sql
-- This migration changes no row. It is a file of its own so that a card too full to build the
-- index still gets 0005's columns. The device then records as before without the index; each
-- start of Node-RED tries again, which makes the start longer, and the Status page reports the
-- database schema as behind until the index is built.
```

- [ ] **Step 2: Check that nothing else moved**

Run: `python3 container/node-red-tm/schema/tmdb_migrate.py --dump-schema | diff - container/node-red-tm/schema/schema.sql` and `python -m pytest container/node-red-tm/schema/tests -q`
Expected: no difference, and all pass.

- [ ] **Step 3: Commit**

```bash
git add container/node-red-tm/schema/migrations/0006_radar_dov_time_index.sql
git commit   # subject: Say what a card too full for the radar index costs at each start
```

- [ ] **Step 4: Run everything off-device once** (the three pytest suites and the docs build under "Commands"; the UI didn't change), write the ledger's lines, and stop for the maintainer.

---

### Task 9: Bench, the plan copy, and the text for review

- [ ] **Step 1: Merge the base branch in if it has moved, and run everything off-device once more** (pytest, the UI, the docs, from "Commands"), and the checks in `CLAUDE.md` that touch what changed: `python3 -m json.tool container/node-red-tm/data/flows.json >/dev/null` and the Ansible syntax check. All pass.

- [ ] **Step 2: Bench run, logged with `tmdev check`**, on a bench unit marked `pii_free` that has a camera and a radar, at the branch head, from a worktree (`script/devpi/README.md`). Look for an open check in the run log first; if one is open, ask the maintainer and use a separate log directory. Use the whole installer, not one tag. Deploy to one unit at a time. Items 1 to 5 need nothing turned on. Items 6 to 13 are one detection-on session of about 45 minutes on a bench-only camera that plays the maintainer's video file in a loop ("The loop camera" below).
  1. Before the deploy: record the schema version `tmdb_migrate.py --check` reports (this branch expects 4; anything else, stop and ask), the database's size, how many rows `radar_dov` has, and from Frigate's `/api/config` that detection is off for the live camera.
  2. Deploy. The journal shows the backup, `applied 0005_time_stopped.sql`, `applied 0006_radar_dov_time_index.sql`, and the version going to 6, with no new `DRIFT` line. The Status page's **Database schema** is ok. Record how long the migrations took.
  3. The index on a large database, timed on the unit's card as the schema `README.md` asks: make a database at version 5 with 30 million made-up `radar_dov` rows in a directory on the card, run `tmdb_migrate.py --db <it> --backup-dir <a directory beside it>`, and record the whole time, the backup's share of it, and the index's size. Also record the least free space the card had during the build (read `df` once a second while it runs), to learn how much room the build needs beyond the index itself; SQLite is expected to sort in temporary files about the index's size, which nobody has measured. It must be well under the runner's 25 minutes. Delete the directory.
  4. `tmdev.py test <host>` passes, and `tmdev.py test <host> --disruptive -- -k made_up` passes: the run of five messages gives its three figures, and the lone `end` gives none. Do this before item 6, because restarting Frigate from its editor counts as a restart in the device tests.
  5. A restart in the middle, with made-up messages: publish the `new` and the first `update` of a run like the device test's (id ending `-tmdev2`), restart `node-red-tm.service`, wait for it, publish the rest. The row is there with the three columns empty and its other fields filled.
  6. The loop camera is set up, with detection off, as under "The loop camera" below: the maintainer copies the clip to the unit, adds the camera to Frigate's config, draws its three zones, and adds its entry on the Cameras page, paired with the unit's radar. Keep a copy of Frigate's `config.yml` and Node-RED's `config.yml` from before, beside each file.
  7. Ask the maintainer for consent to turn detection on, once, for this session, on `tmdev_loop` only. The maintainer turns it on with the Cameras page's switch. Frigate's `/api/config` then shows detection on for `tmdev_loop` and off for the live camera, and recording and snapshots off for `tmdev_loop`. Record the consent and the time in the check.
  8. Start a listener on the Pi for `frigate/events` that writes one line for each message to a file under `/var/tmp`, cut down on the Pi to `id`, `type`, `after.frame_time`, `before.frame_time`, `after.end_time`, `after.stationary`, `after.current_zones`, `after.motionless_count`, and `after.position_changes`. Nothing else leaves the message. Only that file is read.
  9. Passing cars: for the first ten new rows in `events` that entered `zone_tmdev_lane`, work the three figures out again from the listener's lines with a short script and compare them with the row (equal to 0.01 s). Record for each event how many messages Frigate sent and how long it was in view, and for the session the count of rows whose three columns are empty and why (expected: none, or objects in view at a restart).
  10. The car that drives away: each pass of the loop gives one row. It has `stops` 1, a `stationary_time` that is the time from the start of the loop to the car moving, less about ten seconds, and the same figure as `zone_tmdev_bay`'s `stationary`. The rows of two passes agree to within a second. Record the time Frigate took to flag the car. `zone_tmdev_speed`, drawn over the same spot with side lengths, has no key or a `stationary` of 0 and a far shorter `time`: that is what Frigate's source says of a zone with side lengths, seen for the first time.
  11. The car parked throughout: the listener shows an `update` for it about once a minute. Record the interval, and whether Frigate kept one id for it through the end of the clip or started a new one at each pass. From the listener's lines for the whole session, record the longest time between two messages in a row for any one object: Task R1's limit of 300 seconds rests on it being about 60, and if any gap is over 120, stop and tell the maintainer.
  12. The radar rule, on a row from item 10: its `radar_readings` equals the count of the paired radar's rows in the event's window in the chosen direction, less those from the stopped stretch (count them with SQL). The radar measures the street outside, not the clip, so the readings are whatever passed; if none did, then with the maintainer's OK insert made-up `radar_dov` rows, one a second, across the next pass's window before that pass ends, check that pass's row the same way, and delete them.
  13. Cleanup, recorded in the check: detection is set back to false for `tmdev_loop`, and Frigate's `/api/config` (sent with `X-Cache-Bypass: 1`) shows it off there and on the live camera. Count the listener's `end` lines with `stationary` true (objects that ended while stationary, which are not recorded), then stop the listener and delete its file. The maintainer removes the camera's entry on the Cameras page and the camera from Frigate's config and restarts Frigate; `/api/config` then lists only the live camera, detection off. The clip is the maintainer's to remove. The rows the session wrote stay: events with the label `car` and only `zone_tmdev_` zones (so they are in no dashboard count), and the watch log's and deployment's rows for `tmdev_loop`.
  14. The Sharing page's **See an example** shows the three fields, and the notice reads as agreed.
  15. With sharing on to a ThingsBoard server (the maintainer's step, with the maintainer's token): the server's latest `event` telemetry holds the three fields, and Node-RED's log has no "left out" or "didn't load" warning. Afterwards the unit is left not sharing.

  **The loop camera.** A camera in Frigate that reads a video file instead of a camera, as Frigate's own contributor docs set one up. It exists only for the bench.
  - The clip: one continuous take from a camera that doesn't move, three to five minutes, MP4 with H.264 video, 16:9, ideally 1536×864 at 10 frames a second (1920×1080 at up to 30 works, with more decoding work), no sound needed. The maintainer has checked that it shows nobody's face and nothing else that identifies a person. It goes on the unit at `frigate/storage/tmdev/loop.mp4` under the install directory, which Frigate sees as `/media/frigate/tmdev/loop.mp4`.
  - What the clip should show: (a) a car parked for the whole clip, in the same place in the first and last frame; (b) a parked car that starts to drive away no earlier than 45 seconds in and is out of the picture at least 15 seconds before the end; (c) at least five vehicles passing without stopping. Welcome if it is there, not needed: a car that arrives and parks, and a vehicle that stops in the lane for 20 seconds or more and goes on.
  - The camera, added to `cameras:` in Frigate's config (the maintainer pastes it in Frigate's configuration editor and chooses **Save & Restart**):

    ```yaml
      tmdev_loop:
        enabled: true
        type: generic
        mqtt:
          enabled: false
        ffmpeg:
          hwaccel_args: []
          inputs:
            - path: /media/frigate/tmdev/loop.mp4
              input_args: -re -stream_loop -1 -fflags +genpts
              roles:
                - detect
        detect:
          enabled: false
          width: 1536
          height: 864
          fps: 10
        record:
          enabled: false
        snapshots:
          enabled: false
        objects:
          track:
            - car
    ```

    `hwaccel_args: []` makes Frigate decode the file in software, since the device's hardware decoder is set up for the camera's HEVC stream. Only cars are tracked, so a person in the clip is never an object.
  - Three zones, drawn by the maintainer in Frigate's zone editor on `tmdev_loop`, each with no loitering time: `zone_tmdev_bay` over the road where the parked cars stand (the bottom middle of each car's box must be inside it), with no side lengths; `zone_tmdev_lane` across the lane the passing cars use, with no side lengths; and `zone_tmdev_speed`, four corners over the spot where car (b) is parked, inside `zone_tmdev_bay`, with speed estimation on and any side lengths (10, 5, 10, 5).
  - The entry in Node-RED's `config.yml`, added on the control app's Cameras page: the key `tmdev_loop`, enabled, paired with the unit's radar.

- [ ] **Step 3: The public plan copy.** Copy this plan to `design/plans/2026-11-19-time-stopped.md`, and commit it last.

- [ ] **Step 4: Write the text, and stop.** Write, for the maintainer to read before anything is pushed: the PR title and body from `.github/PULL_REQUEST_TEMPLATE.md`, against `feature/watch-log/340` (or whatever this branch was cut from), closing issue 347, with the bench check's id, that the two migrations add three columns and one index and rewrite no row, how long they took on the bench unit and on the made-up 30-million-row database, what the bench measured (messages for each event, the lag of Frigate's flag, the once-a-minute update) and that it was run on a video file, and the template's "Docs" and "AI assistance" sections filled in. Under limits, say: the figures are Frigate's flags added up, so a stop is counted from about ten seconds in and a stop shorter than that only shows as time in a zone; a zone with side lengths has no stopped time; the figures are empty for an event in progress at a restart of Node-RED, for one with a missed message, and for one with more than five minutes between two messages (the clock was set, or the camera stalled); no figure says more than six hours; an event that ends while the object is stationary is still not recorded, so a parked vehicle Frigate lost and found is timed only from where it was found, and one already parked when the device or Frigate started only from then; the radar rule leaves a stop out only from about twelve seconds in, and only the 20 longest stretches; the tallies are in memory; the index takes about a fifth of the radar readings table's size on the card, and on a card too full to build it the device keeps recording without it, while each start of Node-RED tries again and takes longer for it and the Status page shows the schema as behind; the gate doesn't yet hold a new field back until the notice is read again.
