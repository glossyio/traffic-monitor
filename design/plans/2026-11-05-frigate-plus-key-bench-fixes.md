# Frigate+ key: fixes from the bench run (Task 9 of the Frigate+ key plan)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Status page tell the truth about the two states the bench run of 2026-11-04 found: Frigate crash-looping over a `plus://` model it can't fetch (the unit stays active, and the log lines carry a second timestamp), and Frigate in safe mode (the camera checks blame the config). Then re-bench those two items.

**Architecture:** The journal probe picks its source by the unit's restart counter rather than by `ActiveState` alone: a run with no failure restarts reads its own messages, anything else reads the journal's tail, where the run that failed left its traceback. The log helpers strip the s6 timestamp Frigate's supervisor puts in front of every line. The Frigate+ check's rule 7 runs whenever Frigate doesn't answer, and names a refused key when Frigate's own "Unable to refresh API token" line is the last error. The Apps group's Frigate check quotes the same line, since a crash loop with no Frigate+ model has no other check to name its cause. In safe mode, the four checks that read Frigate's camera list say "unknown" and point at the Frigate check instead of comparing an empty list with `config.yml`. The docs say that Frigate's editor checks a model before it saves, how a failing model reaches Frigate anyway, and how to get out of it.

**Tech Stack:** Python 3.11 (the tm-control backend and its pytest suite), Material for MkDocs, the dev-Pi tooling (`script/devpi/tmdev.py check`).

**Spec:** `design/plans/2026-11-04-frigate-plus-key.md` (the plan this amends; its Task 5 rules and its Task 9 step 3, which says to adjust rules 6 and 7 to the real journal and say so in the PR), [issue 279](https://github.com/glossyio/traffic-monitor/issues/279), and the bench findings recorded in the SDD ledger's "Task 9" section (`.superpowers/sdd/2026-11-04-frigate-plus-key/progress.md`, untracked). The maintainer's answers of 2026-11-05 are in "Decisions" below.

**Status:** written 2026-11-05 against `feature/frigate-plus-key/279` at `52b1ebe` (unpushed; stacked on `feature/entered-secrets/95`, PR 278). This file is added in the same PR as the plan it amends.

**Why a separate file:** the original plan stays the record of what was planned and why; Task 9 step 3 anticipated that the bench would change rules 6 and 7, and this file is that change in one place a reviewer reads top to bottom. The implementer gets one short file instead of a 490-line plan with a patch at the end. Task 5 adds a pointer from the original plan's Status paragraph to this one.

## What the bench showed

Bench A (Pi 5, Coral, Frigate 0.18.1), items A3 and A5, at `52b1ebe`:

1. **Frigate's editor validates before it saves.** `POST /api/config/save` parses the new config with `FrigateConfig.parse_yaml`, and parsing a `plus://` model calls `check_and_load_plus_model`, which downloads the model when either of its two files is missing. So a model Frigate can't fetch (wrong key, no key, no internet, unknown id) gets a 400 with the reason, nothing is saved, and Frigate keeps running. The same for an unknown detector type. A failing config reaches Frigate only from disk: a hand edit, a `model:` section `-f` kept after the key was removed, or a key removed or changed while the model's files aren't in `model_cache`.
2. **The unit stays active while Frigate crash-loops.** With an unfetchable `plus://` model, s6 inside the container logs `Service Frigate exited with code 1` and halts the container, which exits about every 10 s; systemd restarts it (`Restart=on-failure`), so `NRestarts` climbs while `ActiveState` is nearly always `active`. Rule 7's "not in RUNNING" gate never opened: `config.frigate_plus` said "unknown: Frigate isn't answering…", `apps.frigate.reachable` said "isn't answering", and only the Services row ("restarted N times after failures") hinted at a loop.
3. **Journal lines carry two timestamps.** After journalctl's `short-iso` prefix comes Frigate's own s6 timestamp, so the real lines are `frigate[N]: 2026-11-04 18:07:36.850573607  Exception: Unable to refresh API token: {"message":"User not found"}` (wrong key) and `… Exception: Plus API key not set. See https://docs.frigate.video/integrations/plus#set-your-api-key` (no key). `traceback_last_line` strips only journalctl's prefix, so `TRACEBACK_END.fullmatch` fails and it returns None (reproduced off-device). Validation-block lines carry the same timestamp; `validation_messages` partitions on `Message : `, so it copes.
4. **Safe mode blames the config.** With `detectors: coral: type: nope` on disk, Frigate started in safe mode with an empty camera list. `apps.frigate.reachable` errored and quoted the message, and `config.frigate_plus` said "isn't in use" (both right). But `config.cameras` warned "config.yml enables picam_h265, which Frigate doesn't have… Rename it", `apps.frigate.cameras` warned "Frigate has no enabled camera… Enable one", `config.zones` passed with nothing to check, and so did `apps.go2rtc.streams` ("No camera in Frigate reads a go2rtc stream"). The plan expected "nothing to compare".
5. **Restart time:** 15.6 s and 16.6 s from the secret's POST/DELETE to the Coral detector's new pid. `RESTART_SECONDS['frigate.service']` stays 60 and the docs keep "about a minute"; the PR gives the measured figure.

Also confirmed from Frigate 0.18.1's source (`frigate/plus.py`, `frigate/detectors/detector_config.py`): Frigate contacts Frigate+ only when a `plus://` model's file or JSON is missing from `model_cache`, or on explicit use (the picker's model list, a snapshot submission). A bad key on its own never stops Frigate; A1 and the device test ran Frigate with the placeholder key. So the crash loop needs an uncached `plus://` model, and removing the key from a crash-looping unit only changes the error to "Plus API key not set".

## Decisions

The maintainer decided 1 to 5 on 2026-11-05; 6 to 9 are calls made here, open to change.

1. **Rule 7 wording is hedged and generic**, since the tail shows how Frigate stopped, not why. When the last error line holds Frigate's own string `Unable to refresh API token`, the detail says Frigate+ didn't accept the key and offers the **Set the key** link. **No automatic removal of the key:** it wouldn't start Frigate (see above), and a key a person just entered can't take a running Frigate down. A key check at save time (tm-control asking Frigate's `GET /api/plus/models` after the restart) is a candidate for the planned Detection page, where the key form moves; not in this PR.
2. **The Apps group's Frigate check quotes the last error too** when Frigate isn't answering and the journal has one. A crash loop with no `plus://` model then shows its cause somewhere; the Frigate+ check adds the model-specific advice. Two checks quoting one line is what the original plan's decision 8 already allows.
3. **Safe mode makes the camera checks "unknown"**, pointing at the Frigate check, rather than "passed, nothing to compare": nothing can be compared, and a passed check beside a broken Frigate reads oddly. Same shape as ruling R13.
4. **The docs keep both routes** (picker and editor) and explain that Frigate checks a model when you save, so a wrong key or id is refused and nothing changes. They add how a failing config reaches Frigate anyway, and how to get out.
5. **The plan's `plus://`-without-a-key wording stands.** A `plus://` model needs no key once both files are in `model_cache`: rule 5 fires only when they aren't (which is why A4a's key removal gave "Set the key": the placeholder model was never downloaded), and rule 8 says "loaded from the files on the device". The planned offline route rests on exactly that.
6. **The journal's source is chosen by the restart counter, not by `ActiveState`.** While the unit is in `RUNNING` and either Frigate answers or `NRestarts` is 0, the probe reads the current run's own messages, as now (safe mode's validation block is in the current run; a unit starting after a hand restart has nothing to quote, so no stale crash is quoted). Otherwise, the unit stopped or systemd restarted it after failures, and the probe reads the journal's tail, where the failed run left its traceback. Reading only the current invocation (the bench session's suggestion) would miss the traceback for the first seconds of each 10 s run, so the check would flap between error and unknown.
7. **A recovery recipe goes in the docs, not in a check's fix button.** Frigate's editor can't be used while Frigate isn't answering, and `tmsetup.sh -f` keeps the `model:` section, so the ways out are the right key, the two files over SSH, or the installer's `model:` section put back over SSH. The check names them in one sentence; the docs give the steps. The planned Detection page has a disk-write fallback for this; this PR doesn't.
8. **`apps.go2rtc.streams` joins the safe-mode set**, though the bench didn't record it: it reads the same empty camera list and passes with "No camera in Frigate reads a go2rtc stream", which is the same vacuous pass as the zones check.
9. **The Remove dialog's text stays** ("A Frigate+ model already on the device keeps running"). It's true; the docs' Tokens and keys bullet adds that a model not yet downloaded stops Frigate until a key is set again, and the Frigate+ check says so.
10. **Earlier rulings checked.** R7's regex (`(\w+\.)*(\w+Error|\w*Exception)\b.*`) stands: both real lines are bare `Exception:` lines, which it matches once the s6 stamp is gone. The parked note (module-qualified bare `Error` classes such as `binascii.Error` don't match) stays parked; the bench showed none, and such a crash falls back to "isn't answering". R13 (safe mode with no model message is `unknown`) stands and now has company: decision 3 gives the camera checks the same shape. `FRIGATE_SAFE_MODE_FIX` ("Fix it in Frigate's configuration editor… Save & Restart") stays: in safe mode Frigate answers, so the editor works, and its validation means a still-broken config isn't saved.

## Global Constraints

- No secret value in any output. Quoted log lines pass through `redact()` as before; new test lines use `PLACEHOLDER_KEY` from `tests/placeholders.py` where a key appears, and the real journal lines hold no key.
- Detail wording is fixed by this plan's Interfaces blocks; tests assert whole details, as the existing ones do, so a wording change is a deliberate test change.
- Nothing here changes the role, the UI, or any pinned version. The journal is read at most once per status report, as before.
- Docs follow "Writing docs" in `docs/development/contributing.md`; `mkdocs build --strict` must pass. Say "planned" for the Detection page; never name it or the private planning repo.
- Commits end with the trailer block from CLAUDE.md ("AI use in this repository"). Say `PUBLIC push →` before any push. Device names and addresses stay out of repo text and the PR.

## Review Focus

1. **A run that is starting after a hand restart** (active, `NRestarts` 0, not answering for up to about 16 s): both checks must say "isn't answering" without quoting an older run's traceback. Task 2's probe test and Task 3's `test_frigate_starting_after_a_hand_restart_quotes_nothing`.
2. **A key-shaped string in the s6-stamped line** must still be redacted after both prefixes are stripped. Task 1's `test_the_s6_timestamp_is_stripped_before_the_line_is_matched` includes one.
3. **Safe mode after a Save & Restart** (`NRestarts` 1, Frigate answering): the validation block quoted must be this run's. Task 2's probe test pins "answering and running reads the current run" whatever the counter says.
4. **A crash loop whose tail has no exception line** (the 400-line tail scrolled past it, or a different failure): rule 7 and the Apps check fall back to "isn't answering" wording, never an empty quote. Task 3's `test_a_crash_loop_without_an_exception_line_is_unknown`.
5. **Safe mode with `config.yml` itself broken**: the camera checks' YAML-error "unknown" must win, as the existing `test_every_check_is_unknown_when_config_yml_has_a_yaml_error` pins; Task 4 extends it with `safe_mode` true.

---

### Task 1: The log helpers read Frigate's real journal lines

**Files:**
- Modify: `tm-control/backend/tm_control/modules/apps/checks.py` (`JOURNAL_PREFIX`, a new `S6_TIMESTAMP`, `traceback_last_line`, a new `REFUSED_KEY`)
- Modify: `tm-control/backend/tests/frigate_log.py` (new fixtures)
- Test: `tm-control/backend/tests/test_contract_checks.py` (`test_the_log_helpers` and two new tests)

**Interfaces:**
- Produces: `S6_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{1,9}\s+")` (Frigate's s6 supervisor stamps each line it forwards; two spaces follow it). `traceback_last_line(lines)` strips `JOURNAL_PREFIX` then `S6_TIMESTAMP`, each at most once, before `TRACEBACK_END.fullmatch`; its result never starts with either. `REFUSED_KEY = "Unable to refresh API token"` (Frigate's own string in `PlusApi._refresh_token_if_needed`; the server's JSON after it isn't matched). In `frigate_log.py`: `REFUSED_KEY_LINE = 'Exception: Unable to refresh API token: {"message":"User not found"}'`, `NO_KEY_LINE = "Exception: Plus API key not set. See https://docs.frigate.video/integrations/plus#set-your-api-key"`, and `crash_loop_tail(last_line: str) -> list[str]`: the end of a run as `journalctl -o short-iso` printed it on the bench, with `tm-test` as the host and a placeholder pid: a `Traceback (most recent call last):` line, two frame lines, `last_line`, then `Service Frigate exited with code 1 (by signal 0)`, each as `2026-11-04T18:07:36+0000 tm-test frigate[2201]: 2026-11-04 18:07:36.850573607  <text>`, followed by systemd's `Main process exited, code=exited, status=1/FAILURE`, `Failed with result 'exit-code'.`, and `Scheduled restart job, restart counter is at 3.` lines without the s6 stamp. `CRASH_LOOP_TAIL = crash_loop_tail(REFUSED_KEY_LINE)`.

- [ ] **Step 1: Write the failing tests**

In `test_contract_checks.py`:

```python
def test_the_s6_timestamp_is_stripped_before_the_line_is_matched():
    """On a Pi, Frigate's supervisor stamps each line after journalctl's own prefix (bench A3)."""
    assert apps_checks.traceback_last_line(CRASH_LOOP_TAIL) == REFUSED_KEY_LINE
    assert apps_checks.traceback_last_line(crash_loop_tail(NO_KEY_LINE)) == NO_KEY_LINE
    # journal_lines gives MESSAGE fields: the s6 stamp alone
    assert apps_checks.traceback_last_line([f"2026-11-04 18:07:36.850573607  {NO_KEY_LINE}"]) == NO_KEY_LINE
    stamped_key = f"2026-11-04T18:07:36+0000 tm-test frigate[2201]: 2026-11-04 18:07:36.850573607  Exception: {PLACEHOLDER_KEY}"
    assert apps_checks.traceback_last_line([stamped_key]) == "Exception: <key>"


def test_a_date_inside_a_message_is_not_a_timestamp():
    line = "Exception: expired on 2026-11-04 18:07:36.850573607  at the server"
    assert apps_checks.traceback_last_line([line]) == line
```

Extend `test_the_log_helpers` with `assert apps_checks.REFUSED_KEY in REFUSED_KEY_LINE`.

- [ ] **Step 2: Run them to see them fail**

Run: `python -m pytest tm-control/backend/tests/test_contract_checks.py -k "s6_timestamp or date_inside or log_helpers" -q`
Expected: FAIL (ImportError on the fixtures, then None from `traceback_last_line`).

- [ ] **Step 3: Add the fixtures, `S6_TIMESTAMP`, `REFUSED_KEY`, and the second strip in `traceback_last_line`.** Update the function's docstring ("without journalctl's prefix and Frigate's s6 timestamp"). Keep `TRACEBACK_END` and `JOURNAL_PREFIX` as they are.

- [ ] **Step 4: Run the file**

Run: `python -m pytest tm-control/backend/tests/test_contract_checks.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tm-control/backend/tm_control/modules/apps/checks.py tm-control/backend/tests/frigate_log.py tm-control/backend/tests/test_contract_checks.py
git commit -m "Read the s6 timestamp Frigate puts in front of each journal line"
```

### Task 2: The journal probe reads the tail after failure restarts

**Files:**
- Modify: `tm-control/backend/tm_control/modules/apps/probes.py` (`frigate_journal`)
- Test: `tm-control/backend/tests/test_contract_checks.py` (`test_the_journal_probe_reads_the_current_run_when_frigate_runs_and_the_tail_when_it_doesnt`)

**Interfaces:**
- Consumes: `units.restarts(values) -> int` (`modules/services/units.py`), `frigate_version(context)` (same module, memoized).
- Produces: `frigate_journal(context) -> list[str]` reads the current run (`journal_lines` with the unit's `InvocationID`, since a minute before it started, as now) when the unit's `ActiveState` is in `RUNNING` and either `frigate_version(context)` is not None or `restarts(values) == 0`; otherwise `journal_tail(FRIGATE_UNIT, JOURNAL_LINES) or []`. The docstring says why: a unit systemd restarted after failures is active between crashes, and the run that failed is in the tail, not in the current invocation.

- [ ] **Step 1: Extend the probe test**

Add two cases to the existing test, after the three it has, with `apps.answers[FRIGATE_VERSION] = (None, None)` for "not answering" (the fixture's default answers for "answering"):

```python
    # Active with failure restarts and not answering: a crash loop, whose last failed run is in the tail
    calls.clear()
    apps.answers[FRIGATE_VERSION] = (None, None)
    context = apps.context()
    context.probes[units.SHOW_UNITS] = {"frigate.service": dict(running, NRestarts="3")}
    probes.frigate_journal(context)
    assert calls == [("tail", "frigate.service", 400)]

    # Active with failure restarts but answering (safe mode after a Save & Restart): this run's own block
    calls.clear()
    apps.answers[FRIGATE_VERSION] = answering  # the fixture's original answer, saved before the first change
    context = apps.context()
    context.probes[units.SHOW_UNITS] = {"frigate.service": dict(running, NRestarts="1")}
    probes.frigate_journal(context)
    assert calls == [("lines", "frigate.service", "@1699999940", 400, "abc")]
```

Also assert the first case (active, `NRestarts` 0) still reads the current run when Frigate isn't answering (review focus 1): set the answer to `(None, None)` before it as well.

- [ ] **Step 2: Run it to see it fail**

Run: `python -m pytest tm-control/backend/tests/test_contract_checks.py -k journal_probe -q`
Expected: FAIL on the crash-loop case (`lines` instead of `tail`).

- [ ] **Step 3: Change `read()` in `frigate_journal` as the Interfaces block says.**

- [ ] **Step 4: Run the backend suite**

Run: `python -m pytest tm-control/backend/tests -q`
Expected: PASS. (`test_a_plus_model_and_frigate_silent_is_unknown`'s second case presets the journal, so it still passes here; Task 3 rewrites it.)

- [ ] **Step 5: Commit**

```bash
git add tm-control/backend/tm_control/modules/apps/probes.py tm-control/backend/tests/test_contract_checks.py
git commit -m "Read Frigate's journal tail while systemd restarts it after failures"
```

### Task 3: Rule 7 runs whenever Frigate doesn't answer, and the Apps check quotes the log

**Files:**
- Modify: `tm-control/backend/tm_control/modules/apps/contracts.py` (`frigate_plus`, the `running is None` branch; a new `WAYS_OUT` constant)
- Modify: `tm-control/backend/tm_control/modules/apps/checks.py` (`frigate`, the `version is None` branch)
- Test: `tm-control/backend/tests/test_contract_checks.py`, `tests/test_app_checks.py`

**Interfaces:**
- Consumes: `traceback_last_line`, `REFUSED_KEY`, `quoted`, `SET_THE_KEY`, `DIAGNOSTICS`, `probes.frigate_journal` (Task 2's source rule), `CRASH_LOOP_TAIL`, `crash_loop_tail`, `NO_KEY_LINE`, `REFUSED_KEY_LINE`.
- Produces, in `contracts.py`: `WAYS_OUT = "enter the right key on the Device page, copy the model's two files into Frigate's model_cache directory, or put the installer's model section back in Frigate's config.yml over SSH, then restart Frigate"`. The `running is None` branch no longer reads `unit_states` (drop the import if unused): `line = traceback_last_line(probes.frigate_journal(context))`, then
  - `line is None` → `unknown`: "Frigate isn't answering, so whether it loaded the Frigate+ model <id> is unknown." (unchanged)
  - `REFUSED_KEY in line` → `error`, fix `SET_THE_KEY`: "Frigate isn't answering: Frigate+ didn't accept the key when Frigate fetched the model <id>. Its log's last error is: <quoted line>. To get Frigate running, <WAYS_OUT>."
  - otherwise → `error`, no fix: "Frigate isn't answering, and the last error in its log is: <quoted line>. If it stopped while fetching the Frigate+ model <id>, check that the device is online, then <WAYS_OUT>."
- Produces, in `checks.py`, the `version is None` branch of `frigate`: `line = traceback_last_line(probes.frigate_journal(context))`; with a line → `error`, fix `DIAGNOSTICS`: "Frigate isn't answering, and the last error in its log is: <quoted line>. If it keeps stopping, download the diagnostics on the Device page."; without → the current detail and restart fix, unchanged.

- [ ] **Step 1: Write the failing tests**

In `test_contract_checks.py`, change `frigate_stopped(apps, journal)` to take `state: dict | None = None` merged over its unit values, and rewrite or add:

```python
def test_a_refused_key_is_named_with_the_link_while_frigate_crash_loops(apps):
    """Bench A3: the unit is active between crashes, so the check can't gate on ActiveState."""
    set_key(apps)
    with_model(apps, f"plus://{MODEL_ID}")
    active = {"ActiveState": "active", "SubState": "running", "NRestarts": "3"}
    check = frigate_plus_check(apps, **frigate_stopped(apps, CRASH_LOOP_TAIL, active))
    assert check.status == "error" and check.fix == SET_THE_KEY
    assert check.detail == (
        f"Frigate isn't answering: Frigate+ didn't accept the key when Frigate fetched the model {MODEL_ID}. Its "
        f"log's last error is: {REFUSED_KEY_LINE}. To get Frigate running, {contracts.WAYS_OUT}."
    )


def test_another_exception_is_quoted_without_a_claim(apps):
    set_key(apps)
    with_model(apps, f"plus://{MODEL_ID}")
    check = frigate_plus_check(apps, **frigate_stopped(apps, crash_loop_tail(NO_KEY_LINE)))
    assert check.status == "error" and check.fix is None
    assert check.detail == (
        f"Frigate isn't answering, and the last error in its log is: {NO_KEY_LINE}. If it stopped while fetching "
        f"the Frigate+ model {MODEL_ID}, check that the device is online, then {contracts.WAYS_OUT}."
    )


def test_a_crash_loop_without_an_exception_line_is_unknown(apps):
    set_key(apps)
    with_model(apps, f"plus://{MODEL_ID}")
    check = frigate_plus_check(apps, **frigate_stopped(apps, CRASH_LOOP_TAIL[-3:]))  # systemd's lines only
    assert (check.status, check.detail) == (
        "unknown", f"Frigate isn't answering, so whether it loaded the Frigate+ model {MODEL_ID} is unknown.")


def test_frigate_starting_after_a_hand_restart_quotes_nothing(apps):
    """Active, no failure restarts, not answering yet: the journal probe reads this run, which has no traceback."""
    set_key(apps)
    with_model(apps, f"plus://{MODEL_ID}")
    starting = {"ActiveState": "active", "SubState": "running", "NRestarts": "0"}
    check = frigate_plus_check(apps, **frigate_stopped(apps, ["Starting Frigate (0.18.1-cf67f08)"], starting))
    assert check.status == "unknown"
```

Replace `test_a_plus_model_and_frigate_stopped_with_a_traceback_is_an_error` (its wording changes: `TRACEBACK_TAIL`'s `Exception: {"message":"Unauthorized"}` now gets the generic detail) and `test_a_plus_model_and_frigate_silent_is_unknown` (its second case, "running as systemd sees it, so the journal isn't read", is now the hand-restart test above). Keep `test_quoted_log_lines_never_hold_a_key` passing: its traceback case asserts `<key>` in the detail and the placeholder absent, which still holds.

In `test_app_checks.py`:

```python
def test_frigate_not_answering_quotes_the_logs_last_error(apps):
    apps.answers[VERSION] = (None, None)
    states = {"frigate.service": {"ActiveState": "active", "SubState": "running", "NRestarts": "3",
                                  "ActiveEnterTimestamp": "", "InvocationID": ""}}
    check = apps_group_with(apps, {units.SHOW_UNITS: states, probes.FRIGATE_JOURNAL: CRASH_LOOP_TAIL})["apps.frigate.reachable"]
    assert check.status == "error"
    assert check.detail == (f"Frigate isn't answering, and the last error in its log is: {REFUSED_KEY_LINE}. If it "
                            "keeps stopping, download the diagnostics on the Device page.")
    assert check.fix == DIAGNOSTICS
```

Extend `test_frigate_down_has_a_restart_fix` to preset `probes.FRIGATE_JOURNAL: []` and assert the detail and the restart fix are as today.

- [ ] **Step 2: Run them to see them fail**

Run: `python -m pytest tm-control/backend/tests/test_contract_checks.py tm-control/backend/tests/test_app_checks.py -q`
Expected: the new tests FAIL on wording and status.

- [ ] **Step 3: Implement both branches as the Interfaces block says.** In `contracts.py`, delete the `unit_states`/`RUNNING` import if nothing else uses it. Update `frigate_plus`'s docstring and the module docstring's last sentence ("quoted … whenever Frigate doesn't answer").

- [ ] **Step 4: Run the backend suite**

Run: `python -m pytest tm-control/backend/tests -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tm-control/backend/tm_control/modules/apps tm-control/backend/tests
git commit -m "Quote Frigate's last error whenever it isn't answering, and name a refused Frigate+ key"
```

### Task 4: Safe mode makes the camera checks unknown

**Files:**
- Modify: `tm-control/backend/tm_control/modules/apps/probes.py` (a new `frigate_safe_mode(config) -> bool`)
- Modify: `tm-control/backend/tm_control/modules/apps/checks.py` (`frigate` uses the helper; `cameras`, `camera_streams`)
- Modify: `tm-control/backend/tm_control/modules/apps/contracts.py` (`cameras_in_config`, `zones`)
- Test: `tm-control/backend/tests/test_app_checks.py`, `tests/test_contract_checks.py`

**Interfaces:**
- Produces: `probes.frigate_safe_mode(config) -> bool`: `mapping(config).get("safe_mode") is True`. Each of the four checks tests it right after its "Frigate isn't answering" branch and returns `unknown` with:
  - `config.cameras`: "Frigate is in safe mode, with no cameras, so its cameras can't be compared with config.yml; see the Frigate check under Apps."
  - `config.zones`: "Frigate is in safe mode, with no cameras, so the cameras' zones can't be checked; see the Frigate check under Apps."
  - `apps.frigate.cameras`: "Frigate is in safe mode, with no cameras, so its cameras can't be checked; see the Frigate check."
  - `apps.go2rtc.streams`: "Frigate is in safe mode, with no cameras, so the streams its cameras read can't be listed; see the Frigate check." (after the go2rtc-not-answering error, which still wins)
  
  `checks.frigate`'s own safe-mode branch uses the helper instead of its inline test; its wording doesn't change.

- [ ] **Step 1: Write the failing tests**

In `test_contract_checks.py`, with `safe_mode(apps)` (exists) and the fixture's `config.yml` enabling `picam_h265`:

```python
def test_cameras_and_zones_are_unknown_in_safe_mode(apps):
    """Bench A5: an empty camera list isn't a renamed camera (the fixture's config.yml still enables picam_h265)."""
    safe_mode(apps)
    apps.edit_json(FRIGATE_CONFIG, lambda config: config.update(cameras={}))
    checks = config_group_with(apps, {probes.FRIGATE_JOURNAL: SAFE_MODE_LINES})
    assert checks["config.cameras"].status == "unknown" and "safe mode" in checks["config.cameras"].detail
    assert checks["config.zones"].status == "unknown" and "safe mode" in checks["config.zones"].detail
    assert checks["config.frigate_plus"].detail == "Frigate+ isn't in use."
```

Extend `test_every_check_is_unknown_when_config_yml_has_a_yaml_error` with `safe_mode(apps)` before the run: the YAML-error wording must still be the one quoted (review focus 5).

In `test_app_checks.py`:

```python
def test_safe_mode_leaves_the_camera_and_stream_checks_unknown(apps):
    apps.edit_json(CONFIG, lambda config: config.update(safe_mode=True, cameras={}))
    checks = apps_group_with(apps, {probes.FRIGATE_JOURNAL: SAFE_MODE_LINES})
    assert checks["apps.frigate.reachable"].status == "error"
    assert checks["apps.frigate.cameras"].status == "unknown" and "safe mode" in checks["apps.frigate.cameras"].detail
    assert checks["apps.go2rtc.streams"].status == "unknown" and "safe mode" in checks["apps.go2rtc.streams"].detail
```

Assert each detail in full, as the Interfaces block fixes them.

- [ ] **Step 2: Run them to see them fail**

Run: `python -m pytest tm-control/backend/tests/test_app_checks.py tm-control/backend/tests/test_contract_checks.py -k "safe_mode" -q`
Expected: FAIL (warn and ok instead of unknown).

- [ ] **Step 3: Add the helper and the four branches.**

- [ ] **Step 4: Run the backend suite**

Run: `python -m pytest tm-control/backend/tests -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tm-control/backend/tm_control/modules/apps tm-control/backend/tests
git commit -m "Leave the camera checks unknown while Frigate is in safe mode"
```

### Task 5: Docs and the plan pointer

**Files:**
- Modify: `docs/configuration/frigate-config.md` ("Use a model", "A device without internet", "The Frigate+ check", a new "If Frigate stops over a model")
- Modify: `docs/use/device-health.md` (the Apps row; the Tokens and keys "Remove" bullet)
- Modify: `docs/reference/tmsetup.md` ("What `-f` replaces")
- Modify: `docs/development/tm-control.md` (the two check bullets)
- Modify: `design/plans/2026-11-04-frigate-plus-key.md` (Status paragraph)

**Interfaces:** none; the pages describe Tasks 1 to 4. Prose for operators, per "Writing docs"; no device names.

- [ ] **Step 1: Write the pages**

`frigate-config.md`:
- "Use a model": after the two routes, one paragraph: Frigate checks the model when you save, whichever route you use: it fetches it with your key, and if the key or the id is wrong, or the device is offline, it refuses the change, shows the reason, and changes nothing.
- "A device without internet", step 3: add that Frigate loads the two files when you save, without contacting Frigate+; with either file missing it refuses the change, because it would have to download the model.
- "The Frigate+ check", Problem row: replace "Frigate isn't running and its log ends with an error, which can mean it couldn't download the model (the check quotes that line)" with: Frigate isn't answering and its log's last error is quoted; when Frigate+ didn't accept the key, the check says so and **Set the key** opens Tokens and keys.
- New subsection "If Frigate stops over a model", after the check table: how it happens (Frigate's editor refuses a model it can't fetch, so a model Frigate can't load reaches it only from disk: an edit of `config.yml` over SSH, a `model:` section the installer kept across `-f` after the key was removed, or a key removed or changed while the model's files aren't on the device yet); what you see (Frigate restarts every few seconds and counts nothing; the Services row shows the restarts; the Frigate and Frigate+ checks quote the log's last error); the three ways out, as numbered steps: enter the right key on the Device page; or copy the two files as in "A device without internet"; or over SSH, replace the `model:` section in `/opt/traffic-monitor/frigate/config/config.yml` with the installer's, from the backup the installer keeps beside it or from the [default Frigate config](https://github.com/glossyio/traffic-monitor/blob/main/container/frigate/config/config.yml.j2), then `sudo systemctl restart frigate.service`. Say that running the installer with `-f` doesn't help here, because it keeps the `model:` section. A `!!! info` admonition: a wrong key on its own never stops Frigate; it only fails when Frigate has to download a model. The planned Detection page will let you change the model from the control app while Frigate is down.

`device-health.md`: the Apps row adds "When Frigate isn't answering after failures, the check quotes its log's last error." and the Configuration row's camera sentence gains "while Frigate runs; in safe mode they report unknown and point at the Frigate check" (or equivalent, short). The "Remove" bullet: after "a Frigate+ model whose files are already on the device keeps running", add "one that isn't downloaded yet stops Frigate until a key is set again; the Frigate+ check says so".

`tmsetup.md`, "What `-f` replaces": after the kept-section sentence, add that it's kept even when Frigate can't load it, and link "If Frigate stops over a model".

`tm-control.md`: the first bullet: safe mode makes `config.cameras`, `config.zones`, `apps.frigate.cameras`, and `apps.go2rtc.streams` unknown (`probes.frigate_safe_mode`). The second bullet: rule 7 runs whenever Frigate doesn't answer, names a refused key by Frigate's `Unable to refresh API token`, and the Apps Frigate check quotes the same line; the journal probe's source rule (current run while active and answering or never restarted after a failure; the tail otherwise); `S6_TIMESTAMP`.

`2026-11-04-frigate-plus-key.md`, Status paragraph: one sentence: "The bench run changed rules 6 to 8's surroundings and the safe-mode checks; see `2026-11-05-frigate-plus-key-bench-fixes.md`, which supersedes this plan's rule 7 and Task 9 step 3."

- [ ] **Step 2: Build the docs strictly**

Run: `~/.venvs/tm-docs/bin/mkdocs build --strict`
Expected: no warnings, exit 0.

- [ ] **Step 3: Commit**

```bash
git add docs design/plans/2026-11-04-frigate-plus-key.md
git commit -m "Say how a model Frigate can't fetch reaches it, and how to get out"
```

### Task 6: Re-bench A3 and A5, and the PR text

Through `tmdev.py check start|item|status|end` on the Coral unit from the inventory (`script/devpi/README.md`); one host at a time; every value a placeholder; no file contents printed. Deploy the branch with `tmdev.py deploy <host> -- -t tm-control` first (tm-control only; the role and the containers are unchanged).

- [ ] **A3 again.** Set the placeholder key on the Device page. Write `model: {path: plus://tmdevplaceholder0001}` into `config.yml` over SSH (the editor refuses it) and `sudo systemctl restart frigate.service`. Within the first 15 s (active, `NRestarts` 0): both the Frigate and Frigate+ checks say "isn't answering" with no quote. Once `NRestarts` is above 0: `config.frigate_plus` is an error with the refused-key wording and the **Set the key** link; `apps.frigate.reachable` is an error quoting the same `Unable to refresh API token` line; the Services row warns "restarted N times after failures"; neither detail holds the key (grep the status JSON for the placeholder). Remove the key: `config.frigate_plus` becomes rule 5's "Set the key" error; `apps.frigate.reachable` quotes `Plus API key not set`. Restore the installer's `model:` section from the backup, restart Frigate, confirm "isn't in use" and ok everywhere.
- [ ] **A5 again.** Write `detectors: coral: type: nope` over SSH, restart: `apps.frigate.reachable` errors and quotes the message; `config.cameras`, `config.zones`, `apps.frigate.cameras`, and `apps.go2rtc.streams` are unknown and point at the Frigate check; `config.frigate_plus` is ok. Restore and restart.
- [ ] **Device tests:** `tmdev.py test <host> -- -k "status or frigate_plus"`, then the full non-disruptive suite.
- [ ] **Off-device:** the backend suite, `mkdocs build --strict`, and `python -m pytest script/tests -q` (unchanged, as a regression check).
- [ ] **PR text additions** (Task 10 of the original plan): the measured restart (15.6 s and 16.6 s; `RESTART_SECONDS` kept at 60); what the bench changed and why (this file's "What the bench showed" and "Decisions", in two short paragraphs); that the original plan's rules 3, 7, and 8, its regex, and its safe-mode camera expectation differ from the code, with this file as the record; the "Limits" item that `-f` keeps a `model:` section Frigate can't load, and the docs' way out; and that a key check at save time is left to the planned Detection page.
