# Frigate+ key: fixes from the bench run (Task 9 of the Frigate+ key plan)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Status page tell the truth about the two states the bench run of 2026-11-04 found: Frigate crash-looping over a `plus://` model it can't fetch (the unit stays active, and the log lines carry a second timestamp), and Frigate in safe mode (the camera checks blame the config). Then re-bench those two items.

**Architecture:** The journal probe picks its source by the unit's restart counter rather than by `ActiveState` alone: a run with no failure restarts reads its own messages, anything else reads the journal's tail, where the run that failed left its traceback. The log helpers strip the s6 timestamp Frigate's supervisor puts in front of every line. The Frigate+ check's rule 7 runs whenever Frigate doesn't answer, and names a refused key when Frigate's own "Unable to refresh API token" line is the last error. The Apps group's Frigate check quotes the same line, since a crash loop with no Frigate+ model has no other check to name its cause. In safe mode, the four checks that read Frigate's camera list say "unknown" and point at the Frigate check instead of comparing an empty list with `config.yml`. The docs say that Frigate's editor checks a model before it saves, how a failing model reaches Frigate anyway, and how to get out of it.

**Tech Stack:** Python 3.11 (the tm-control backend and its pytest suite), Material for MkDocs, the dev-Pi tooling (`script/devpi/tmdev.py check`).

**Spec:** `design/plans/2026-11-04-frigate-plus-key.md` (the plan this amends; its Task 5 rules and its Task 9 step 3, which says to adjust rules 6 and 7 to the real journal and say so in the PR), [issue 279](https://github.com/glossyio/traffic-monitor/issues/279), and the bench findings recorded in the SDD ledger's "Task 9" section (`.superpowers/sdd/2026-11-04-frigate-plus-key/progress.md`, untracked). The maintainer's answers of 2026-11-05 are in "Decisions" below.

**Status:** written 2026-11-05 against `feature/frigate-plus-key/279` at `52b1ebe` (unpushed; stacked on `feature/entered-secrets/95`, PR 278). This file is added in the same PR as the plan it amends. Tasks 1 to 6 were done at `bf0155f`; Task 7, bench item 6, decision 11, and review focus 6 were added on 2026-11-05 after the re-bench, for Frigate's own restart quoting its shutdown tracebacks. Task 8, bench item 7, decision 12, and review focus 7 were added on 2026-11-05 after PR 280 was opened at `c8981f0`, for [issue 281](https://github.com/glossyio/traffic-monitor/issues/281): the restart Frigate's watchdog makes when a detector process dies reads as a config save on the Status page. Decision 13 was added on 2026-11-05 after Task 8's bench, which confirmed that Frigate's stats keep a dead detector's pid.

**Why a separate file:** the original plan stays the record of what was planned and why; Task 9 step 3 anticipated that the bench would change rules 6 and 7, and this file is that change in one place a reviewer reads top to bottom. The implementer gets one short file instead of a 490-line plan with a patch at the end. Task 5 adds a pointer from the original plan's Status paragraph to this one.

## What the bench showed

Bench A (Pi 5, Coral, Frigate 0.18.1), items A3 and A5, at `52b1ebe`:

1. **Frigate's editor validates before it saves.** `POST /api/config/save` parses the new config with `FrigateConfig.parse_yaml`, and parsing a `plus://` model calls `check_and_load_plus_model`, which downloads the model when either of its two files is missing. So a model Frigate can't fetch (wrong key, no key, no internet, unknown id) gets a 400 with the reason, nothing is saved, and Frigate keeps running. The same for an unknown detector type. A failing config reaches Frigate only from disk: a hand edit, a `model:` section `-f` kept after the key was removed, or a key removed or changed while the model's files aren't in `model_cache`.
2. **The unit stays active while Frigate crash-loops.** With an unfetchable `plus://` model, s6 inside the container logs `Service Frigate exited with code 1` and halts the container, which exits about every 10 s; systemd restarts it (`Restart=on-failure`), so `NRestarts` climbs while `ActiveState` is nearly always `active`. Rule 7's "not in RUNNING" gate never opened: `config.frigate_plus` said "unknown: Frigate isn't answering…", `apps.frigate.reachable` said "isn't answering", and only the Services row ("restarted N times after failures") hinted at a loop.
3. **Journal lines carry two timestamps.** After journalctl's `short-iso` prefix comes Frigate's own s6 timestamp, so the real lines are `frigate[N]: 2026-11-04 18:07:36.850573607  Exception: Unable to refresh API token: {"message":"User not found"}` (wrong key) and `… Exception: Plus API key not set. See https://docs.frigate.video/integrations/plus#set-your-api-key` (no key). `traceback_last_line` strips only journalctl's prefix, so `TRACEBACK_END.fullmatch` fails and it returns None (reproduced off-device). Validation-block lines carry the same timestamp; `validation_messages` partitions on `Message : `, so it copes.
4. **Safe mode blames the config.** With `detectors: coral: type: nope` on disk, Frigate started in safe mode with an empty camera list. `apps.frigate.reachable` errored and quoted the message, and `config.frigate_plus` said "isn't in use" (both right). But `config.cameras` warned "config.yml enables picam_h265, which Frigate doesn't have… Rename it", `apps.frigate.cameras` warned "Frigate has no enabled camera… Enable one", `config.zones` passed with nothing to check, and so did `apps.go2rtc.streams` ("No camera in Frigate reads a go2rtc stream"). The plan expected "nothing to compare".
5. **Restart time:** 15.6 s and 16.6 s from the secret's POST/DELETE to the Coral detector's new pid. `RESTART_SECONDS['frigate.service']` stays 60 and the docs keep "about a minute"; the PR gives the measured figure.
6. **Frigate's own restart quotes its shutdown tracebacks** (re-bench at `bf0155f`, check item 2, the one failure of 11). A Save & Restart of an unchanged config, and `POST /api/restart`, each stop Frigate's container with SIGTERM. Frigate's nginx exits at once, so Frigate stops answering; 4 s later Frigate logs two tracebacks of its own (`AttributeError: 'ForkAwareLocal' object has no attribute 'connection'`, then `FileNotFoundError: [Errno 2] No such file or directory`); s6 logs `[INFO] Service Frigate exited with code 0 (by signal 0)` 0.6 s after them; systemd sees the unit's exit 143 about 3 s after that, schedules the restart, and the new run is started within 2 s. For about 5 s, `apps.frigate.reachable` quoted the `FileNotFoundError` line with the Diagnostics fix, while the Services row said "Running" with the old start time and no restart, then "restarted itself 1 time". The Frigate+ check, with the installer's model, quoted nothing. Settled from the code and the poll log (2026-11-05): the unit stays `active` until the container has halted, so decision 6's first branch read the run that was stopping, whose own journal holds the tracebacks; both quoting reports had Services rows that only an `active` unit gets, and a report reads the unit states once. The tail, read between the exit and "Started", holds them as well. The Services row's lag is `StatusCache`'s 5 s reuse of a report, not systemd: the poll ran every 2 s and each report was served two or three times. Frigate 0.18.1's s6 finish script (`docker/main/rootfs/etc/s6-overlay/s6-rc.d/frigate/finish`) prints `[INFO] Service Frigate exited with code <code> (by signal <signal>)`; it writes a nonzero code as the container's exit code, 128 + the signal for a kill (143 for SIGTERM), and nothing for code 0. So a stop or restart through SIGTERM ends with code 0 or signal 15, and that includes the restart Frigate's watchdog makes when a detector process dies; a crash of Frigate's own process ends with a nonzero code (1 on the bench); and a container podman kills after its stop timeout logs no line.
7. **Frigate's watchdog restart, from Frigate 0.18.1's source; none of it benched yet** (Task 8 step 7 does). The thread in `frigate/watchdog.py` sleeps 10 s, then every 10 s looks at each detector. A detection older than 10 s (`detection_start` set and stale) logs `Detection appears to be stuck. Restarting detection process...` and restarts only the detector process. A detector process that isn't alive logs `Detection appears to have stopped. Exiting Frigate...` and calls `restart_frigate()` (`frigate/util/services.py`), which sends SIGTERM to PID 1 when that is `s6-svscan`: the path a Save & Restart and `POST /api/restart` take, so s6 logs `[INFO] Service Frigate exited with code 0 (by signal 0)`, the container exits 143, and systemd restarts the unit and counts it. The detector process is a `DetectorRunner` titled `frigate.detector:<name>` (`frigate/object_detection/base.py`, setproctitle), and it builds the detector inside its own `run()`: for `edgetpu`, `load_delegate("libedgetpu.so.1.0", device)` in `frigate/detectors/plugins/edgetpu_tfl.py` raises `ValueError` after logging `No EdgeTPU was detected. If you do not have a Coral device yet, you must configure CPU detectors.`, so the child dies with a traceback as soon as it starts; `detect_process` stays set and `detection_start` stays 0, so the watchdog's "stopped" branch fires 10 to 20 s after the thread starts, and the next run does the same. A dead or unplugged USB Coral makes that loop (`/dev/bus/usb` still exists, so the container starts); a PCIe Coral that is present but can't be opened does too; an unplugged PCIe Coral doesn't, because `AddDevice=/dev/apex_0` keeps the container from starting, a nonzero failure loop the Services row already warns about. Expected period: Frigate's ~15 s start, the watchdog's 10 to 20 s, the ~7 s stop, and the ~2 s restart gap, so 35 to 45 s, of which Frigate answers for 15 to 25 s. While it answers, `/api/stats` gives the dead detector process's pid (`frigate/stats/util.py` reads `detect_process.pid`, which keeps the last process's), the initial `inference_speed` of 10.0 ms, and `cpu` and `mem` of null for it, since `get_cpu_stats` (`frigate/util/services.py`) walks the live process table and the pid is gone, where a live detector shows numbers as strings. So the last layer of `hardware.detector.*`, which looks at the pid alone, would say "Frigate detects with it, 10.0 ms per detection", while the null `cpu` would say the detector isn't running: predictions the bench records, not claims. Frigate's own log format puts `[<time>] frigate.watchdog <padding> INFO    : ` before the message, behind the s6 stamp. Recorded for the alternative decision 12 weighed, not used by the rule: journalctl's `--grep` needs a systemd built with PCRE2 (`journalctl --version` lists `+PCRE2`; Debian's builds have it, and so does the dev machine's systemd 259), and with no match it exits 1 with no output (dev machine, 2026-11-05).

Also confirmed from Frigate 0.18.1's source (`frigate/plus.py`, `frigate/detectors/detector_config.py`): Frigate contacts Frigate+ only when a `plus://` model's file or JSON is missing from `model_cache`, or on explicit use (the picker's model list, a snapshot submission). A bad key on its own never stops Frigate; A1 and the device test ran Frigate with the placeholder key. So the crash loop needs an uncached `plus://` model, and removing the key from a crash-looping unit only changes the error to "Plus API key not set".

## Decisions

The maintainer decided 1 to 5 on 2026-11-05; 6 to 9 are calls made here, open to change.

1. **Rule 7 wording is hedged and generic**, since the tail shows how Frigate stopped, not why. When the last error line holds Frigate's own string `Unable to refresh API token`, the detail says Frigate+ didn't accept the key and offers the **Set the key** link. **No automatic removal of the key:** it wouldn't start Frigate (see above), and a key a person just entered can't take a running Frigate down. A key check at save time (tm-control asking Frigate's `GET /api/plus/models` after the restart) is left to a planned update to the control app, where the key form moves; not in this PR.
2. **The Apps group's Frigate check quotes the last error too** when Frigate isn't answering and the journal has one. A crash loop with no `plus://` model then shows its cause somewhere; the Frigate+ check adds the model-specific advice. Two checks quoting one line is what the original plan's decision 8 already allows.
3. **Safe mode makes the camera checks "unknown"**, pointing at the Frigate check, rather than "passed, nothing to compare": nothing can be compared, and a passed check beside a broken Frigate reads oddly. Same shape as ruling R13.
4. **The docs keep both routes** (picker and editor) and explain that Frigate checks a model when you save, so a wrong key or id is refused and nothing changes. They add how a failing config reaches Frigate anyway, and how to get out.
5. **The plan's `plus://`-without-a-key wording stands.** A `plus://` model needs no key once both files are in `model_cache`: rule 5 fires only when they aren't (which is why A4a's key removal gave "Set the key": the placeholder model was never downloaded), and rule 8 says "loaded from the files on the device". The planned offline route rests on exactly that.
6. **The journal's source is chosen by the restart counter, not by `ActiveState`.** While the unit is in `RUNNING` and either Frigate answers or `NRestarts` is 0, the probe reads the current run's own messages, as now (safe mode's validation block is in the current run; a unit starting after a hand restart has nothing to quote, so no stale crash is quoted). Otherwise, the unit stopped or systemd restarted it after failures, and the probe reads the journal's tail, where the failed run left its traceback. Reading only the current invocation (the bench session's suggestion) would miss the traceback for the first seconds of each 10 s run, so the check would flap between error and unknown.
7. **A recovery recipe goes in the docs, not in a check's fix button.** Frigate's editor can't be used while Frigate isn't answering, and `tmsetup.sh -f` keeps the `model:` section, so the ways out are the right key, the two files over SSH, or the installer's `model:` section put back over SSH. The check names them in one sentence; the docs give the steps. A planned update to the control app covers this; this PR doesn't.
8. **`apps.go2rtc.streams` joins the safe-mode set**, though the bench didn't record it: it reads the same empty camera list and passes with "No camera in Frigate reads a go2rtc stream", which is the same vacuous pass as the zones check.
9. **The Remove dialog's text stays** ("A Frigate+ model already on the device keeps running"). It's true; the docs' Tokens and keys bullet adds that a model not yet downloaded stops Frigate until a key is set again, and the Frigate+ check says so.
10. **Earlier rulings checked.** R7's regex (`(\w+\.)*(\w+Error|\w*Exception)\b.*`) stands: both real lines are bare `Exception:` lines, which it matches once the s6 stamp is gone. The parked note (module-qualified bare `Error` classes such as `binascii.Error` don't match) stays parked; the bench showed none, and such a crash falls back to "isn't answering". R13 (safe mode with no model message is `unknown`) stands and now has company: decision 3 gives the camera checks the same shape. `FRIGATE_SAFE_MODE_FIX` ("Fix it in Frigate's configuration editor… Save & Restart") stays: in safe mode Frigate answers, so the editor works, and its validation means a still-broken config isn't saved.
11. **Frigate's own shutdown tracebacks are told apart by s6's exit line, in the helper both checks share.** `traceback_last_line` quotes nothing when the last exception line is followed by `[INFO] Service Frigate exited with code 0 (by signal 0)` or `… code 256 (by signal 15)` (`ORDERLY_EXIT`): Frigate stopped on purpose, so no exception before that line is why it isn't answering. A crash of Frigate's own process has a nonzero exit line, so that crash loop still quotes its exception (bench item 2), and so does a crash whose run hasn't logged s6's line yet. The exception is Frigate's watchdog: when a detector process dies (a dead or unplugged Coral), it logs `Detection appears to have stopped. Exiting Frigate...` and restarts Frigate the way a save does, so that loop ends with code 0 and quotes nothing; the follow-up issue "Frigate's watchdog restart looks like a config save on the Status page" covers it. This covers both of the probe's sources, which decision 6 leaves as they are: the stopping run (the unit is `active`, so the current invocation is read) and the tail (the auto-restart gap). The alternatives weighed on 2026-11-05: treating a pending 143 as a completed restart covers only the tail half, and both observed quotes came from the current invocation; ignoring exceptions after a restart request needs a request line Frigate doesn't log; accepting the gap leaves a wrong cause with a Diagnostics link after every save. What's left is the 0.6 s between the tracebacks and s6's line, and the report cache, which stretches whatever report falls in that window by up to 5 s and stays as it is; and a stop through systemd that podman kills after its 10 s stop timeout, which logs no exit line, so the tracebacks stay quoted until the next run answers (a `StopTimeout=` change is separate). The rule also closes Task 3's deferred minor (a Frigate stopped by hand quoted an older exception from the tail): a hand stop ends with the same line (from the code; the hand stop wasn't benched). `journal_lines` reads a run's first 400 lines, so a run older than that never showed its shutdown from the current invocation anyway; only the tail half did.
12. **A run of Frigate's own restarts close together is a failure loop, judged by cadence, not by Frigate's log** (issue 281; Task 8; the maintainer's call of 2026-11-05). Frigate's watchdog restarts Frigate through the same exit 143 as a save, so the Services row's rule from `adce0be` calls that loop "restarted itself … when its config is saved", and the Apps check, since decision 11, says "isn't answering" with Restart. At the service boundary (systemd's state, the exit status, Frigate's API) one 143 restart can't be told from a save; what differs is the cadence. A save is one restart, with minutes between saves; the watchdog loop restarts every 35 to 45 s (bench item 7).
    - **The rule.** `units.restart_causes` classifies each counted restart: "failure" when its exit isn't the unit's `restarts_itself_with`; otherwise "loop" when the automatic restart before it came within `RESTART_LOOP_SPACING` (120 s: the loop's period is under 60 s, and a person saving twice within two minutes is rare, since Frigate takes about 20 s to answer again after a save); otherwise "itself". All "itself" → ok, as now. Any "loop" → warn, with the counts and the Restart fix, since a hand restart is how the count is cleared once the cause is gone. Otherwise any "failure" → the current warn. The data is PID 1's restart entries, already read once per report while `NRestarts` is above 0; `automatic_restart_exits` becomes `automatic_restarts`, each restart's time beside its status. No new journal read, no log text, and nothing from Frigate's source but the period.
    - **The Apps check**, while Frigate isn't answering, says Frigate keeps stopping itself when the last counted restart was a "loop", with the count, and offers Diagnostics: systemd is starting Frigate again, so Restart is pointless, and the Services row keeps the one that clears the count. So the loop is named from its second restart on, about 90 s in; before that the check says "isn't answering" with Restart, as today. Decision 11's orderly-exit rule is right throughout: there's nothing to quote. The Frigate+ check is unchanged (it says "unknown" while Frigate isn't answering and nothing is quoted). `restarted_itself` means "every counted restart was 'itself'", so the probe reads the tail in a loop, where it finds nothing to quote either.
    - **Wording.** Services: "Running since 10:12, but it restarted 4 times, 3 of them by stopping itself within 2 minutes of the restart before, which happens when something inside it keeps failing. Check the Hardware group; if it's ok, download the diagnostics on the Device page." Apps: "Frigate isn't answering: it keeps stopping itself (4 restarts so far, the last two less than 2 minutes apart), and systemd starts it again. Check the Hardware group; if it's ok, download the diagnostics on the Device page." The last sentence is the unit's `restart_loop_hint`. No detail names a detector or a log line, since the rule knows neither.
    - **Where the cause should show.** The Hardware group's detector check should name a dead detector from Frigate's API, not from its log. Frigate's stats carry each detector's `pid` and the `cpu` and `mem` of that pid, taken from the live process table (`get_cpu_stats` in `frigate/util/services.py` walks `psutil.process_iter`, keeping command lines that contain `frigate.`), so a dead detector process is predicted to show its last pid with `cpu` and `mem` null, while a live one shows numbers as strings. Bench item 7 records the detectors section of `/api/stats` with the detector dead; if it bears that out, a follow-up gives the detector check's last layer ("Frigate's detector for it isn't running") that test. Not in this PR: none of it has been seen on a device. Superseded by decision 13 on 2026-11-05: the bench bore the prediction out, and the maintainer chose to have the check claim only the host side, with no rule on `cpu` and `mem`, so there is no follow-up.
    - **The boundary.** tm-control judges a service by systemd's state, its exit statuses, and its API; a log line is quoted to the operator, never a rule input. Decision 11's orderly-exit rule and decision 1's refused-key wording are the two exceptions this PR already carries, both about what to quote rather than what to conclude; this task adds none. Given up by this choice: a single watchdog restart followed by a healthy run stays "restarted itself 1 time", and no row can say "detector process". Gained: no dependence on Frigate's log text or on a PCRE2 journalctl, a diff about a third the size, and a rule that catches a self-restart loop with any other cause.
    - **In this PR**, as Task 8 with bench item 7, rather than a PR on top: the rule lives beside decision 11's, whose "quotes nothing" made this loop silent in the Apps row; the bench is the same unit and the same `-t tm-control` deploy; and PR 280 is still stacked on PR 278, so nothing waits on it. The PR text's Limits bullet on issue 281 goes, Testing gains the run, and the body closes 281. Alternatives weighed on 2026-11-05: matching Frigate's watchdog line, `Detection appears to have stopped. Exiting Frigate...`, with `journalctl --grep` for the Services row and a scan of the probe's lines for the Apps check (precise, names the detector, and catches a single restart, but pins tm-control's rules to Frigate 0.18.1's log text and s6's line order; the first draft of this decision, replaced at the maintainer's request); pairing by invocation id (whether PID 1's exit entries carry `INVOCATION_ID` wasn't benched); and putting the loop into the ok wording, which hides it. The fix that belongs upstream is a distinct exit status, or a stats field, for a watchdog restart.
13. **The Hardware group's accelerator check claims only the host side** (the maintainer's call of 2026-11-05, after Task 8's bench). Its ok detail is "Ready on the host and passed to Frigate.", with no inference speed. Whether detection works is Frigate's to report: when a detector process dies, Frigate restarts itself, which decision 12 reports in the Services row and the Apps group's Frigate check. The bench showed why the check can't say more: while Frigate answers between those restarts, its stats keep the dead process's pid, `inference_speed` 10.0 (the starting value, which a live detector with no traffic also shows), and `cpu` and `mem` null, so "Frigate detects with it, 10.0 ms per detection" was shown beside the loop warning that pointed at this group. The layers that err stay as they are, including "isn't running" when Frigate's stats give the detector no pid. Not used: reading the null `cpu` and `mem`, since Frigate's HTTP API documents no response schema for `/api/stats` and no detector-health field, so a rule on them rests on Frigate's internals. The fix that belongs upstream is a stats field that says a detector process died.

## Global Constraints

- No secret value in any output. Quoted log lines pass through `redact()` as before; new test lines use `PLACEHOLDER_KEY` from `tests/placeholders.py` where a key appears, and the real journal lines hold no key.
- Detail wording is fixed by this plan's Interfaces blocks; tests assert whole details, as the existing ones do, so a wording change is a deliberate test change.
- Nothing here changes the role, the UI, or any pinned version. The journal is read at most once per status report, as before.
- Docs follow "Writing docs" in `docs/development/contributing.md`; `mkdocs build --strict` must pass. Say "planned" for later features; don't name them.
- Commits end with the trailer block from CLAUDE.md ("AI use in this repository"). Say `PUBLIC push →` before any push. Device names and addresses stay out of repo text and the PR.

## Review Focus

1. **A run that is starting after a hand restart** (active, `NRestarts` 0, not answering for up to about 16 s): both checks must say "isn't answering" without quoting an older run's traceback. Task 2's probe test and Task 3's `test_frigate_starting_after_a_hand_restart_quotes_nothing`.
2. **A key-shaped string in the s6-stamped line** must still be redacted after both prefixes are stripped. Task 1's `test_the_s6_timestamp_is_stripped_before_the_line_is_matched` includes one.
3. **Safe mode after a Save & Restart** (`NRestarts` 1, Frigate answering): the validation block quoted must be this run's. Task 2's probe test pins "answering and running reads the current run" whatever the counter says.
4. **A crash loop whose tail has no exception line** (the 400-line tail scrolled past it, or a different failure): rule 7 and the Apps check fall back to "isn't answering" wording, never an empty quote. Task 3's `test_a_crash_loop_without_an_exception_line_is_unknown`.
5. **Safe mode with `config.yml` itself broken**: the camera checks' YAML-error "unknown" must win, as the existing `test_every_check_is_unknown_when_config_yml_has_a_yaml_error` pins; Task 4 extends it with `safe_mode` true.
6. **A crash loop must still quote after Task 7, and a stop through SIGTERM must not**: `test_an_orderly_exit_after_the_last_exception_quotes_nothing` has both, with the exit line's code the only difference. The marker is the whole line after both prefixes are stripped (`fullmatch`), so nginx's or go2rtc's exit lines, which name another service, don't end the search.
7. **A save must stay ok, and a loop must never be** (Task 8): `test_frigate_restarting_itself_is_ok` and `test_frigate_restarting_in_a_loop_warns` differ only in the time between PID 1's restart entries; two saves 121 s apart stay ok and 119 s apart warn, so the spacing is the one threshold, a constant with a comment. The Apps check names the loop only from the second restart on, and after a single self-restart still says "isn't answering" with Restart. A crash loop (nonzero exits) keeps today's "after failures" wording. Fake mode has no journal, so its Frigate row ("failed") is unchanged. No new journalctl call: one PID 1 read per report, as `test_the_report_reads_each_unit_once`'s neighbour asserts.

---

### Task 1: The log helpers read Frigate's real journal lines

**Files:**
- Modify: `tm-control/backend/tm_control/modules/apps/checks.py` (`JOURNAL_PREFIX`, a new `S6_TIMESTAMP`, `traceback_last_line`, a new `REFUSED_KEY`)
- Modify: `tm-control/backend/tests/frigate_log.py` (new fixtures)
- Test: `tm-control/backend/tests/test_contract_checks.py` (`test_the_log_helpers` and two new tests)

**Interfaces:**
- Produces: `S6_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{1,9}\s+")` (Frigate's s6 supervisor stamps each line it forwards; two spaces follow it). `traceback_last_line(lines)` strips `JOURNAL_PREFIX` then `S6_TIMESTAMP`, each at most once, before `TRACEBACK_END.fullmatch`; its result never starts with either. `REFUSED_KEY = "Unable to refresh API token"` (Frigate's own string in `PlusApi._refresh_token_if_needed`; the server's JSON after it isn't matched). In `frigate_log.py`: `REFUSED_KEY_LINE = 'Exception: Unable to refresh API token: {"message":"User not found"}'`, `NO_KEY_LINE = "Exception: Plus API key not set. See https://docs.frigate.video/integrations/plus#set-your-api-key"`, and `crash_loop_tail(last_line: str) -> list[str]`: the end of a run as `journalctl -o short-iso` printed it on the bench, with `tm-test` as the host and a placeholder pid: a `Traceback (most recent call last):` line, two frame lines, `last_line`, then `[INFO] Service Frigate exited with code 1 (by signal 0)`, each as `2026-11-04T18:07:36+0000 tm-test frigate[2201]: 2026-11-04 18:07:36.850573607  <text>`, followed by systemd's `Main process exited, code=exited, status=1/FAILURE`, `Failed with result 'exit-code'.`, and `Scheduled restart job, restart counter is at 3.` lines without the s6 stamp. `CRASH_LOOP_TAIL = crash_loop_tail(REFUSED_KEY_LINE)`.

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
- New subsection "If Frigate stops over a model", after the check table: how it happens (Frigate's editor refuses a model it can't fetch, so a model Frigate can't load reaches it only from disk: an edit of `config.yml` over SSH, a `model:` section the installer kept across `-f` after the key was removed, or a key removed or changed while the model's files aren't on the device yet); what you see (Frigate restarts every few seconds and counts nothing; the Services row shows the restarts; the Frigate and Frigate+ checks quote the log's last error); the three ways out, as numbered steps: enter the right key on the Device page; or copy the two files as in "A device without internet"; or over SSH, replace the `model:` section in `/opt/traffic-monitor/frigate/config/config.yml` with the installer's, from the backup the installer keeps beside it or from the [default Frigate config](https://github.com/glossyio/traffic-monitor/blob/main/container/frigate/config/config.yml.j2), then `sudo systemctl restart frigate.service`. Say that running the installer with `-f` doesn't help here, because it keeps the `model:` section. A `!!! info` admonition: a wrong key on its own never stops Frigate; it only fails when Frigate has to download a model. A planned update to the control app will let you change the model while Frigate is down.

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
- [ ] **PR text additions** (Task 10 of the original plan): the measured restart (15.6 s and 16.6 s; `RESTART_SECONDS` kept at 60); what the bench changed and why (this file's "What the bench showed" and "Decisions", in two short paragraphs); that the original plan's rules 3, 7, and 8, its regex, and its safe-mode camera expectation differ from the code, with this file as the record; the "Limits" item that `-f` keeps a `model:` section Frigate can't load, and the docs' way out; and that a key check at save time is left to a planned update to the control app.

### Task 7: Frigate's own restart quotes nothing

Bench item 6 and decision 11. Written 2026-11-05 after the re-bench at `bf0155f`.

Narrowed 2026-11-05 by the review of `bf0155f..a8f92be`: Frigate's watchdog restarts it with code 0 when a detector process dies, so "a crash has a nonzero code" holds only for a crash of Frigate's own process. The comment, docs, and PR text now say so; the Interfaces block and Step 5 below keep the wording as first written.

**Files:**
- Modify: `tm-control/backend/tm_control/modules/apps/checks.py` (`traceback_last_line`, a new `ORDERLY_EXIT`)
- Modify: `tm-control/backend/tests/frigate_log.py` (new fixtures)
- Modify: `docs/development/tm-control.md` (one sentence)
- Test: `tm-control/backend/tests/test_contract_checks.py`, `tests/test_app_checks.py`

**Interfaces:**
- Produces: `ORDERLY_EXIT = re.compile(r"\[INFO\] Service Frigate exited with code (0 \(by signal 0\)|256 \(by signal 15\))")`, with a comment: s6's finish line when Frigate's process exited 0 (a Save & Restart, its Restart button, a stop) or was killed by SIGTERM; a crash has a nonzero code, and the other services' lines name them, not Frigate. `traceback_last_line(lines)` scans backwards as now and strips both prefixes as now; it returns None as soon as `ORDERLY_EXIT.fullmatch(text)` matches, before any exception line has matched. Its docstring says so: "None when there's none, or when Frigate's supervisor logged an orderly exit after the last one, since Frigate logs tracebacks of its own while it stops". `validation_messages` is unchanged: it's quoted only while Frigate answers.
- Produces, in `frigate_log.py`: `SHUTDOWN_LAST_LINE = "FileNotFoundError: [Errno 2] No such file or directory"`, `ORDERLY_EXIT_LINE = "[INFO] Service Frigate exited with code 0 (by signal 0)"`, and `shutdown_lines(exit_line: str = ORDERLY_EXIT_LINE) -> list[str]`: what Frigate logged while stopping for a Save & Restart on the bench (2026-11-05), as the current run's MESSAGE fields, each `2026-11-05 11:47:12.065588818  <text>` (the s6 stamp alone): `[INFO] Service NGINX exited with code 0 (by signal 0)`, a `Traceback (most recent call last):` line, one frame line, `AttributeError: 'ForkAwareLocal' object has no attribute 'connection'`, another `Traceback` line and frame line, `SHUTDOWN_LAST_LINE`, `exit_line`, then `[INFO] The go2rtc service exited with code 0 (by signal 0)`. `shutdown_tail(exit_line: str = ORDERLY_EXIT_LINE) -> list[str]`: the same lines with the journalctl prefix `2026-11-05T11:47:12-0800 tm-test frigate[2201]: ` in front, followed by systemd's `frigate.service: Main process exited, code=exited, status=143/n/a`, `frigate.service: Failed with result 'exit-code'.`, and `frigate.service: Scheduled restart job, restart counter is at 1.` lines (prefix `2026-11-05T11:47:15-0800 tm-test systemd[1]: `, the last one at 11:47:16) without the s6 stamp: the tail between the exit and the new run. The frame lines are synthetic, as in `crash_loop_tail`.

- [ ] **Step 1: Write the failing tests**

In `test_contract_checks.py`, next to the other helper tests:

```python
def test_an_orderly_exit_after_the_last_exception_quotes_nothing():
    """Frigate logs two tracebacks of its own while it stops for a Save & Restart (bench 2026-11-05); s6's exit line
    with code 0 follows them, so neither is why Frigate isn't answering. A crash's exit line has a nonzero code."""
    assert apps_checks.traceback_last_line(shutdown_lines()) is None  # the stopping run, while the unit is active
    assert apps_checks.traceback_last_line(shutdown_tail()) is None  # the tail, between the exit and the new run
    killed = "[INFO] Service Frigate exited with code 256 (by signal 15)"
    assert apps_checks.traceback_last_line(shutdown_lines(killed)) is None
    crashed = "[INFO] Service Frigate exited with code 1 (by signal 0)"
    assert apps_checks.traceback_last_line(shutdown_lines(crashed)) == SHUTDOWN_LAST_LINE
    # A run that crashed after the orderly exit of the one before it is quoted
    assert apps_checks.traceback_last_line(shutdown_tail() + CRASH_LOOP_TAIL) == REFUSED_KEY_LINE
    # Another service's exit line, or more than the line itself, doesn't end the search
    nginx = "[INFO] Service NGINX exited with code 0 (by signal 0)"
    assert apps_checks.traceback_last_line(["Exception: bare", nginx]) == "Exception: bare"
    assert apps_checks.traceback_last_line(["Exception: bare", f"{ORDERLY_EXIT_LINE} and more"]) == "Exception: bare"


def test_frigate_stopping_for_its_own_restart_is_unknown(apps):
    """Decision 11: the unit is active while Frigate stops, and in auto-restart just after; neither quotes."""
    set_key(apps)
    with_model(apps, f"plus://{MODEL_ID}")
    stopping = {"ActiveState": "active", "SubState": "running", "NRestarts": "0"}
    unknown = ("unknown", f"Frigate isn't answering, so whether it loaded the Frigate+ model {MODEL_ID} is unknown.")
    check = frigate_plus_check(apps, **frigate_stopped(apps, shutdown_lines(), stopping))
    assert (check.status, check.detail) == unknown
    check = frigate_plus_check(apps, **frigate_stopped(apps, shutdown_tail()))
    assert (check.status, check.detail) == unknown
```

In `test_app_checks.py`, after `test_frigate_not_answering_quotes_the_logs_last_error` (the check doesn't read the unit's state itself; the journal is preset as the probe would give it for each source):

```python
def test_frigate_stopping_for_its_own_restart_quotes_nothing(apps):
    """A Save & Restart: Frigate's own shutdown tracebacks aren't the cause of a failure (decision 11)."""
    apps.answers[VERSION] = (None, None)
    for journal in (shutdown_lines(), shutdown_tail()):
        check = apps_group_with(apps, {probes.FRIGATE_JOURNAL: journal})["apps.frigate.reachable"]
        assert check.status == "error"
        assert check.detail == (
            "Frigate isn't answering. Restart it; if it keeps stopping, download the diagnostics on the Device page."
        )
        assert check.fix == Fix(kind="restart", text="Restart Frigate", unit="frigate.service")
```

- [ ] **Step 2: Run them to see them fail**

Run: `python -m pytest tm-control/backend/tests/test_contract_checks.py tm-control/backend/tests/test_app_checks.py -k "orderly_exit or own_restart" -q`
Expected: FAIL (ImportError on the fixtures, then `SHUTDOWN_LAST_LINE` quoted where None is expected).

- [ ] **Step 3: Add the fixtures, `ORDERLY_EXIT`, and the early return in `traceback_last_line`**, as the Interfaces block says. Keep `TRACEBACK_END`, `JOURNAL_PREFIX`, and `S6_TIMESTAMP` as they are.

- [ ] **Step 4: Run the file pair, then the backend suite**

Run: `python -m pytest tm-control/backend/tests -q`
Expected: PASS. `test_frigate_not_answering_quotes_the_logs_last_error` and the crash-loop tests still pass: `CRASH_LOOP_TAIL`'s exit line has code 1.

- [ ] **Step 5: The docs sentence**

In `docs/development/tm-control.md`, after the sentence that ends "before it matches an exception line", add: "It quotes nothing when s6's `[INFO] Service Frigate exited with code 0` line (`ORDERLY_EXIT`; a kill by SIGTERM counts too) comes after the last exception line. Frigate logs two tracebacks of its own while it stops for a Save & Restart, and the unit stays active until its container has halted, so the probe reads the run that is stopping; a crash's exit line has a nonzero code, so a crash loop still quotes." Then run `mkdocs build --strict`.

- [ ] **Step 6: Commit**

```bash
git add tm-control/backend/tm_control/modules/apps/checks.py tm-control/backend/tests/frigate_log.py tm-control/backend/tests/test_contract_checks.py tm-control/backend/tests/test_app_checks.py docs/development/tm-control.md
git commit -m "Ignore the tracebacks Frigate logs while it stops on purpose"
```

- [ ] **Step 7: Bench item 2 again**

Through `tmdev.py check start|item|status|end` on the Coral unit, as in Task 6: one host at a time, every value a placeholder, no file contents printed, and nothing after "token:" printed. Deploy with `tmdev.py deploy <host> -- -t tm-control`.

- **Save & Restart:** a Save & Restart of the unchanged config, then `POST /api/restart`, each polled every 2 s for 30 s. `apps.frigate.reachable` says "isn't answering" with the Restart fix, never quotes a line, and is ok once Frigate answers (about 19 s after the request). The Services row is as at `bf0155f`: "restarted itself N times". `config.frigate_plus`, with the installer's model, keeps its status throughout. No key in any report.
- **A3's crash loop, briefly:** with the `plus://` model on disk and the placeholder key, once `NRestarts` is above 0 both checks still quote `Unable to refresh API token` (its exit line has code 1). Restore the installer's `model:` section and restart.
- **Device tests:** `tmdev.py test <host> -- -k "status or frigate_plus"`.
- **Off-device:** the backend suite, `python -m pytest script/tests -q`, and `mkdocs build --strict`.
- **PR text:** in `pr-text-additions.md`, drop the TODO on the Testing item's Save & Restart entry and fill in what the run showed.

### Task 8: Frigate's own restarts close together are a failure loop

Bench item 7 and decision 12, for issue 281. Written 2026-11-05, with PR 280 open at `c8981f0`; rewritten the same day from a log-matching design to the cadence rule, at the maintainer's request. Nothing in this task has been seen on a device; step 6 records what the bench shows.

**Files:**
- Modify: `tm-control/backend/tm_control/adapters/systemd.py` (`AutomaticRestart`, `automatic_restarts` in place of `automatic_restart_exits`)
- Modify: `tm-control/backend/tm_control/modules/services/units.py` (`RESTART_LOOP_SPACING`, `Unit.restart_loop_hint`, the memo key, `automatic_restarts`, `restart_causes`, `restarted_itself`, `restart_loop`)
- Modify: `tm-control/backend/tm_control/modules/services/checks.py` (`unit_check`, the active branch)
- Modify: `tm-control/backend/tm_control/modules/apps/checks.py` (`frigate`, the `version is None` branch)
- Modify: `tm-control/backend/tm_control/modules/apps/probes.py` (`frigate_journal`'s docstring)
- Modify: `tm-control/backend/tests/test_api_services.py`, `tests/test_contract_checks.py` (the probe test's presets), `tests/test_app_checks.py`
- Modify: `docs/use/device-health.md` (the Services and Apps rows), `docs/development/tm-control.md` (two sentences)

No device test: a loop can't be made without breaking Frigate's config on the Pi, which the bench does by hand and puts back. The existing `test_frigate_restarting_itself_stays_ok` covers the single restart.

**Interfaces:**
- Produces, in `systemd.py`: `@dataclass(frozen=True) class AutomaticRestart: status: str | None; at: float | None`: the `EXIT_STATUS` of the main-process exit logged in the `RESTART_EXIT_WINDOW` before the restart (None when there was none, or it had no status), and the restart's seconds since boot (None when its entry had no time). `automatic_restarts(unit) -> list[AutomaticRestart] | None` is `automatic_restart_exits` with that record per restart: same query, same None rules; `automatic_restart_exits` is removed.
- Produces, in `units.py`: `RESTART_LOOP_SPACING = 120`, with the comment: seconds between two of the unit's own restarts under which they're a loop, not two saves; Frigate's watchdog restarts it every 35 to 45 s when a detector process keeps dying, and a person saving twice waits about 20 s for Frigate to answer between saves. `Unit.restart_loop_hint: str = "Download the diagnostics on the Device page to see why."`, Frigate's `"Check the Hardware group; if it's ok, download the diagnostics on the Device page."`, with the comment that it ends the loop wording. `AUTOMATIC_RESTARTS = "services.automatic_restarts"` replaces `RESTART_EXITS`, and `automatic_restarts(context, unit_name) -> list[AutomaticRestart] | None` replaces `restart_exits` (None in fake mode, memoized per unit). `restart_causes(context, unit, count) -> list[str] | None`: for each of the unit's last `count` automatic restarts, oldest first: `"failure"` when `unit.restarts_itself_with` is None or the restart's `status` differs from it; else `"loop"` when the restart before it in the whole list (any status) has a time, this one has a time, and `0 <= this.at - previous.at <= RESTART_LOOP_SPACING`; else `"itself"`. None when the list is None or shorter than `count`. `restarted_itself(context, unit, count) -> bool` is `causes is not None and all(cause == "itself" for cause in causes)`; its docstring adds that one of the unit's own restarts within the spacing of another is a loop, not its own. `restart_loop(context, unit) -> int | None`: the unit's `NRestarts` from `unit_states(context)` when it's above 0 and the last of its `restart_causes` is `"loop"`; else None.
- Produces, in `services/checks.py`, the `state == "active"` branch with `count` above 0: `causes = restart_causes(context, unit, count)`. All `"itself"` → ok, wording unchanged. Else `"loop"` in causes → `warn`, fix `restart`: `loops = causes.count("loop")`, `of_them = "" if count == 1 else ("all of them " if loops == count else f"{loops} of them ")`, `minutes = RESTART_LOOP_SPACING // 60`, detail `f"{_running(values, today)}, but it restarted {times}, {of_them}by stopping itself within {minutes} minutes of the restart before, which happens when something inside it keeps failing. {unit.restart_loop_hint}"`. Else → the current warn. So Frigate's row reads "Running since 10:12, but it restarted 4 times, 3 of them by stopping itself within 2 minutes of the restart before, which happens when something inside it keeps failing. Check the Hardware group; if it's ok, download the diagnostics on the Device page."
- Produces, in `apps/checks.py`, the `version is None` branch of `frigate()`, first: `count = restart_loop(context, probes.FRIGATE)`; with a count → `error`, fix `DIAGNOSTICS`, `f"Frigate isn't answering: it keeps stopping itself ({plural(count, 'restart')} so far, the last two less than {RESTART_LOOP_SPACING // 60} minutes apart), and systemd starts it again. {probes.FRIGATE.restart_loop_hint}"`; then the two existing branches. The comment says the loop is named from its second restart on. `frigate_journal`'s docstring: a restart that followed another within the spacing isn't Frigate's own, so the tail is read.
- Consumes: `unit_states`, `restarts`, `plural`, `DIAGNOSTICS`, `restart_fix`; the `at`, `EXITED`, `CRASHED`, `RESTARTED` entries of `test_api_services.py`.

- [ ] **Step 1: The adapter, test first**

In `test_api_services.py`, rename the four `test_automatic_restart_exits_*` tests to `test_automatic_restarts_*` and change their expected values to `AutomaticRestart` records: `[AutomaticRestart(None, 100.1), AutomaticRestart("1", 100.1)]` for the first; `[AutomaticRestart("143", 159.0), AutomaticRestart("143", 200.1), AutomaticRestart(None, 300.0)]` and, for the entries without times, `[AutomaticRestart(None, None)]` in the pairing test; None in the cut-output and failure tests. Run `python -m pytest tm-control/backend/tests/test_api_services.py -k automatic_restarts -q`: FAIL. Implement; run the file: the Services tests still pass, since `restarted_itself` keeps its meaning for restarts minutes apart (`EXITED` is at 100 s and the second save in the "crash, then a save" case has its own time).

- [ ] **Step 2: The Services row, test first**

Next to `test_frigate_restarting_itself_is_ok`:

```python
def saves(*seconds):
    """PID 1's entries for one of Frigate's own restarts (exit 143) at each time since boot."""
    return [entry for at_seconds in seconds for entry in (at(EXITED, at_seconds), at(RESTARTED, at_seconds + 0.1))]


LOOP_HINT = "Check the Hardware group; if it's ok, download the diagnostics on the Device page."


def test_frigate_restarting_in_a_loop_warns(device_client, login, systemctl):
    """Frigate's watchdog restarts it through the same exit 143 as a save when a detector process keeps dying (issue
    281), every 35 to 45 s; a save is one restart with minutes between saves. Judged by cadence, not by Frigate's log."""
    systemctl.units = {"frigate.service": {"NRestarts": "3"}}
    systemctl.journal = saves(100, 140, 180)
    login(device_client, *ADMIN)
    frigate = service_group(device_client)["services.frigate.service"]
    assert frigate["status"] == "warn" and frigate["fix"]["kind"] == "restart"
    assert frigate["detail"].endswith(
        f", but it restarted 3 times, 2 of them by stopping itself within 2 minutes of the restart before, which "
        f"happens when something inside it keeps failing. {LOOP_HINT}")


@pytest.mark.parametrize("journal, count, wording", [
    (saves(100, 221), 2, "restarted itself 2 times"),  # two saves, 121 s apart
    (saves(100, 219), 2, "restarted 2 times, 1 of them by stopping itself"),  # 119 s apart: the one threshold
    ([CRASHED, RESTARTED] + saves(130), 2, "restarted 2 times, 1 of them by stopping itself"),  # a crash, then 143 soon after
    (saves(100, 140, 180, 220), 3, "restarted 3 times, all of them by stopping itself"),  # the loop began before the counted restarts
])
def test_the_spacing_tells_a_loop_from_saves(device_client, login, systemctl, journal, count, wording):
    systemctl.units = {"frigate.service": {"NRestarts": str(count)}}
    systemctl.journal = journal
    login(device_client, *ADMIN)
    assert wording in service_group(device_client)["services.frigate.service"]["detail"]
```

In the last case `NRestarts` is 3 against four restarts in the journal: the one at 100.1 is before the counted ones, and the one at 140.1 is within the spacing of it, so all three counted restarts are "loop". Also assert, in `test_frigate_restarting_in_a_loop_warns`, that only one `journalctl` call was made (`len([c for c in systemctl.calls if c[0] == "journalctl"]) == 1`). Run the file: FAIL on the new tests. Implement `units.py` and `services/checks.py`; run the file: PASS.

- [ ] **Step 3: The Apps check and the probe, test first**

In `test_contract_checks.py`'s probe test, change the four `RESTART_EXITS` presets to `units.AUTOMATIC_RESTARTS` with records (`[AutomaticRestart("1", t) for t in (100.1, 110.1, 120.1)]`, `[AutomaticRestart("143", 100.1)]`, `[AutomaticRestart("143", 100.1), AutomaticRestart("1", 200.1)]`, None), and add one case: `NRestarts` 2, `[AutomaticRestart("143", 100.1), AutomaticRestart("143", 140.1)]`, not answering → `("tail", "frigate.service", 400)`, with the comment that Frigate's own restart within the spacing of the one before is a loop, so the run that stopped is in the tail.

In `test_app_checks.py`, after `test_frigate_stopping_for_its_own_restart_quotes_nothing`:

```python
def test_frigate_in_a_restart_loop_says_it_keeps_stopping_itself(apps):
    """Decision 12: Frigate's own restarts less than 2 minutes apart are a loop; named from the second restart on."""
    apps.answers[VERSION] = (None, None)
    loop = [units.AutomaticRestart("143", at) for at in (100.1, 140.1, 180.1, 220.1)]
    states = {"frigate.service": {"ActiveState": "activating", "SubState": "auto-restart", "NRestarts": "4",
                                  "ActiveEnterTimestamp": "", "InvocationID": ""}}
    preset = {units.SHOW_UNITS: states, f"{units.AUTOMATIC_RESTARTS}.frigate.service": loop,
              probes.FRIGATE_JOURNAL: shutdown_tail()}
    check = apps_group_with(apps, preset)["apps.frigate.reachable"]
    assert check.status == "error" and check.fix == DIAGNOSTICS
    assert check.detail == ("Frigate isn't answering: it keeps stopping itself (4 restarts so far, the last two less "
                            "than 2 minutes apart), and systemd starts it again. Check the Hardware group; if it's ok, "
                            "download the diagnostics on the Device page.")
    # After one restart of its own, nothing says loop yet
    states["frigate.service"]["NRestarts"] = "1"
    preset[f"{units.AUTOMATIC_RESTARTS}.frigate.service"] = loop[:1]
    check = apps_group_with(apps, preset)["apps.frigate.reachable"]
    assert check.detail.startswith("Frigate isn't answering. Restart it;")
    assert check.fix == Fix(kind="restart", text="Restart Frigate", unit="frigate.service")
```

(`AutomaticRestart` is imported into `units.py` from the adapter, or the test imports it from `systemd`; either way one import.) Run: `python -m pytest tm-control/backend/tests/test_contract_checks.py tm-control/backend/tests/test_app_checks.py -k "journal_probe or restart_loop" -q`: FAIL. Implement `restart_loop` and the `frigate()` branch; update the two docstrings.

- [ ] **Step 4: The backend suite**

Run: `python -m pytest tm-control/backend/tests -q`. Expected: PASS; Task 7's tests are untouched.

- [ ] **Step 5: Docs**

`docs/use/device-health.md`, Services row: after "that doesn't count as a failure.", add "When it restarts itself again and again within minutes, as when its AI accelerator has failed, that does count, and the row says so." Apps row: after "When Frigate stopped on an error, the Frigate check quotes it.", add "When Frigate isn't answering because it keeps stopping itself, the check says so and points at the Hardware group and the diagnostics."

`docs/development/tm-control.md`: in the Frigate+ bullet, after "…and the run before the save mustn't be quoted.", add: "One of Frigate's own restarts within `RESTART_LOOP_SPACING` (120 s) of the automatic restart before it is a loop, not a save (`units.restart_causes`, from PID 1's restart times alone): the Services row warns with the counts, the Apps group's Frigate check says Frigate keeps stopping itself while it isn't answering, and the probe reads the tail. The restart Frigate's watchdog makes when a detector process dies is the known case; tm-control reads no log line for it." In the paragraph after it, end the last sentence "…so that loop quotes nothing" with ", and is caught by its cadence instead."

Run: `~/.venvs/tm-docs/bin/mkdocs build --strict`. Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add tm-control/backend docs/use/device-health.md docs/development/tm-control.md
git commit -m "Warn when Frigate keeps restarting itself within minutes"
```

(The plan amendment is committed first, on its own, as `74b4d9a` was.)

- [ ] **Step 7: Bench item 7**

Through `tmdev.py check start|item|status|end` on the Coral unit, as in Task 6: one host at a time, the PLAY RECAP address checked, every value a placeholder, no file contents printed, nothing after "token:" printed, and no journal line that holds a URL. Deploy with `tmdev.py deploy <host> -- -t tm-control`. Start from a Frigate started by hand (`NRestarts` 0) with every check ok.

- **One watchdog restart:** `pgrep -af 'frigate.detector:'` shows one process; `sudo kill <pid>`. Within the next 10 s, read Frigate's stats on the Pi (`curl -s http://127.0.0.1:5000/api/stats`), and print only the `detectors` section's `pid`, `cpu`, `mem`, `inference_speed`, and `detection_start` (through `python3 -c`, nothing else from the body). Bench item 7 predicts the dead process's pid with `cpu` and `mem` null; record what it says, and what `hardware.detector.*` says at the same moment. Then poll the status every 2 s for 90 s. Expected: Frigate stops answering about 20 s after the kill; while it doesn't, `apps.frigate.reachable` says "isn't answering" with Restart (one restart isn't a loop: the accepted gap, decision 12) and never quotes a line; the Services row goes "Starting." then "restarted itself 1 time", as today. Record the journal from the kill to the next run's first line (`journalctl -u frigate.service --since <kill time> -o short-iso`, URLs dropped): the watchdog's line, what follows it, s6's exit line and its code, and systemd's 143 line, so bench item 7's account of the shape is confirmed or corrected.
- **The loop:** `sudo cp` Frigate's `config.yml` to a `.tmdev-281` backup; change the installer's detector line `device: pci` to `device: pci:1` (a second PCIe Coral that doesn't exist, so the detector fails to load each run, as a dead Coral does); `sudo systemctl restart frigate.service`. Poll every 2 s for 3 minutes. Expected: the first self-restart gives "restarted itself 1 time"; from the second on, the Services row warns with the loop wording, `NRestarts` and the "of them" count climbing, and while Frigate isn't answering `apps.frigate.reachable` has the loop wording with Diagnostics and `config.frigate_plus` is "unknown", with no quoted line at any poll; "restarted itself" appears nowhere after the second restart. Record the period between restarts (expected 35 to 45 s) and, while Frigate answers, the `detectors` section of `/api/stats` as above and what the Hardware detector check says.
- **Recovery through Frigate:** in Frigate's configuration editor put `device: pci` back and Save & Restart (a save minutes after the last loop restart, so one more "itself"). Expected: Frigate ok, the Hardware check ok, and the Services row still warns with the loop wording and Restart. Then Restart from the Status page: the row is ok, "Running since …". Confirm `config.yml` is byte-identical to the backup (`cmp`), then remove the backup. If the editor refuses or is awkward, restore over SSH and restart by hand instead, and say so.
- **Device tests:** `tmdev.py test <host> --disruptive -- -k restarting_itself` (the single self-restart stays ok), then `-k "status or frigate_plus"`, then the full non-disruptive suite.
- **Off-device:** the backend suite, `python -m pytest script/tests -q`, the schema tests, and `mkdocs build --strict`.

- [ ] **Step 8: PR text**

In `pr-text-additions.md` and the live body (`pr-body-live.md`; the maintainer OKs the change, then it's applied with `gh api` PATCH under a `PUBLIC push →` line, since `gh pr edit` fails here):
- Summary, first line: "Closes #279 and #281." The Status page bullets gain one: when Frigate restarts itself again within two minutes, as its watchdog does every 40 s or so while a detector process keeps dying, the Services row warns with the counts and the Frigate check says Frigate keeps stopping itself, both pointing at the Hardware group and the diagnostics; judged from systemd's restart times, not from Frigate's log.
- Choices worth a look: a bullet from decision 12: the cadence rule and its 120 s spacing, why the log line wasn't matched (the boundary), what the choice gives up (a single watchdog restart reads as a save), and that the Hardware detector check's API-level signal is a follow-up (superseded by decision 13 on 2026-11-05: no follow-up; the check claims only the host side).
- Limits: the bullet "When Frigate restarts itself because a detector process died…" goes. In its place: a single self-restart reads as a save, whatever caused it; two saves within two minutes read as a loop once; and whatever the bench showed for the Hardware detector check with a dead detector process, with the follow-up it leads to.
- Testing: a new item, "Frigate restarting itself in a loop (issue 281)", with what step 7 showed: the single kill, the loop and its period, the recovery, the stats and Hardware readings, and the device test's result.
- Docs: `device-health.md` (the Services and Apps rows) and `tm-control.md` (the cadence rule) added to their bullets.
