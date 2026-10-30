# tm-control M3: a forward clock jump stalls Frigate's camera feed (design question)

**Status:** approved 2026-10-30. Tasks 1–5 are done in this series' commits ("Offer Restart Frigate when a stream it
reads has no reader", "Restart Frigate after the clock moves ahead by more than 20 seconds", "Say on the page when
Frigate restarts after the clock moved ahead", "Say the device restarts Frigate after the clock moves ahead", "Check
that a step ahead restarts Frigate and the feed comes back"). Tasks 6 and 7 ran on the bench on 2026-10-30 and passed; a
hand-made 5-minute step stalled the feed for good in 1 of 2 tries, so the stall is likely, not certain. Task 8 is
pending. Found during the bench re-check of PR #269's review fixes (`1080421`). The maintainer chose all three options
below and folds them into PR #269, not a new branch or stacked PR.

## What was seen

Two bench checks on a Raspberry Pi 5 dev unit (Pi camera through go2rtc's `exec:rpicam-vid` source, Frigate 0.18.1
reading `picam_h265_detect` over RTSP from go2rtc). Both are logged in the local dev-test run log on 2026-10-30, about
03:00Z and 03:19Z. Feed health was judged from go2rtc's `/api/streams` only: the detect stream's readers
(`consumers`) and its source's `bytes_recv`. No images were read.

1. **One forward jump of 5 minutes** (`timedatectl set-ntp false`, then `set-time` 5 minutes ahead) stalls the feed.
   About 27 s later Frigate logs `picam_h265: ffmpeg process is not running. exiting capture thread`. Within 30 s
   go2rtc has no reader, and with no reader go2rtc stops `rpicam-vid`. For 6 minutes nothing recovers. Frigate's
   watchdog never restarts ffmpeg (no "No frames received" line, same ffmpeg PID), and Frigate's `/api/stats` freezes
   (`camera_fps` stays at an impossible 53.7 for a 10 fps camera).
2. **Restarting go2rtc doesn't help** (the earlier check: restarted through `POST /services/go2rtc_server.service/restart`,
   still no reader a minute later). **Restarting Frigate does** (`POST /services/frigate.service/restart`): with the
   clock still 5 minutes ahead, the feed is healthy again within 60 s.
3. **One backward jump of 5 minutes** (`POST /time` with NTP off, so a single `set-time`) does **not** stall the feed:
   the same reader, growing bytes, and the same ffmpeg PID for 8 minutes. `camera_fps` dipped once, to 0.6, about when
   the wall clock passed the earlier "ahead" time.
4. In the first check, after several jumps (the offline put-back cases), the non-disruptive device suite failed only
   `test_status_report_agrees_with_the_inventory`, on `apps.go2rtc.streams` ("Stream picam_h265_detect for camera
   picam_h265 has no running source. Restart go2rtc; …"). The **Cameras** check (`apps.frigate.cameras`, camera_fps
   above 0) stayed ok, because Frigate's frozen stats still showed a nonzero fps.

Earlier in M3 (PR #269's Testing section, "Moving the clock"), a 2-minute forward jump did trip Frigate's 20-second
watchdog, and the feed came back by itself after about two minutes. So small jumps recover, and at least one of 5
minutes doesn't. Where the boundary is, and why, is unknown.

## Why it matters

- The usual offline case is a device whose clock is **behind** after a power-off (no clock battery). There, "Set from
  this browser" is a forward jump, so setting the time can stop the camera, and traffic isn't counted until someone
  restarts Frigate.
- The Status page then offers the wrong fix: Camera streams says "Restart go2rtc", which doesn't help, and Cameras says
  all is well.
- `docs/use/device-health.md` ("Moving the clock ahead by more than about 20 seconds … Frigate does this by itself; you
  don't need to restart it.") and PR #269's Testing text say the opposite of what was seen with 5 minutes.
- NTP's own corrections are jumps too, such as the first sync once an offline device gets online. tm-control doesn't
  make those, so only the Status check would catch them.

## The options the maintainer chose (all three)

1. **Restart Frigate after a time change that can stall it.** `POST /time` queues `frigate.service` the way a zone
   change queues the pod and revproxy (`CONTAINERS`, `_restart_containers`, `BackgroundTasks`), and lists it in the
   result's `restarting`.
2. **Point the Camera streams check at the right unit.** When a stream Frigate reads has no reader, the fix restarts
   Frigate. When it has a reader but no running source, it restarts go2rtc, as today.
3. **Correct the docs note and PR #269's Testing text.**

## Open questions to decide

1. **What triggers option 1?**
   - Candidates: any `set-time` that ran; only a net forward move over a threshold; or any move over a threshold in
     either direction.
   - A backward 5-minute jump didn't stall. A 2-minute forward jump recovered by itself. Is a fixed threshold, such as
     the watchdog's 20 s, safe, or is "always restart after set-time" simpler and safe enough? A restart costs about
     30–60 s of uncounted traffic.
   - How is the move measured: the device clock read before the change vs. after the last `set-time`, or vs. `when`?
     `before.device_time` has only whole seconds; `clock.now()` is available.
2. **Transient forward jumps inside one request.** In the offline put-back case, systemd-timesyncd moves the clock
   forward to its saved time for about 1.7 s before `_hold_time` sets it back. The net move can be backward, with a
   forward step in between. Does that step alone stall Frigate? This is untested. It decides whether the trigger
   looks at the net move or at any forward step, including `ntp_took_over`, where NTP sets the real time.
3. **Which unit to restart:** `frigate.service` alone, which was seen to fix it, or the pod? With a zone change in the
   same request, the pod restart already covers Frigate, so avoid restarting twice.
4. **What the page says:** `restarting` is already `list[str]`, so the OpenAPI document shouldn't change. The UI's
   result text knows "Frigate and Node-RED are restarting." for a zone change. A time-only Frigate restart needs its
   own sentence. List it in `tm-control/ui/README.md`'s result texts.
5. **Option 2's details:**
   - Use go2rtc's `consumers` count, which the check doesn't read today; `_running` reads only `producers`.
   - go2rtc starts `exec:` sources only while a reader exists, so "no reader" also means "no running source". Is
     "no reader" alone a sound signal to restart Frigate?
   - Should the Cameras check also stop trusting `camera_fps` when go2rtc has no reader, since Frigate's stats freeze?
   - Pin any new go2rtc field in `tests/fixtures`, as the other contract fields are.
6. **NTP's own jumps** (boot, coming online later): leave them to option 2, plus a follow-up issue for automatic
   recovery? Is there a Frigate or ffmpeg setting that keeps the capture alive across a jump, and is it worth a
   look now or later?
7. **Tests:**
   - Off-device: the router queues the Frigate restart, or doesn't, per the trigger rule, with the fake clock in
     `tests/test_api_time.py`. The check offers the right fix per go2rtc's answer, in `tests/test_app_checks.py`.
   - On the device: possibly a disruptive device test, "a forward set through `POST /time` leaves the feed healthy
     within N s".
   - The bench repro for question 2 (one put-back with the clock ahead, offline) should run before the trigger rule
     is final.

## Constraints

- Fold everything into PR #269 (`feature/tm-control-status-system/201`, local head `1080421`, pushed head
  `11eca8b`). No new branch.
- Don't change `SYNC_SECONDS` or the leave-NTP-off-after-a-failed-sync policy; the maintainer decides those separately.
- Restarts go through `restart_or_log` (`modules/services/units.py`). Frigate is in `tmsetup_tm_control_polkit`, so no
  new polkit rule is needed. Never give tm-control sudo.
- Docs follow `docs/development/contributing.md` (Writing docs, Style) and `mkdocs build --strict`.
- Bench work goes through `script/devpi/tmdev.py check` on a `pii_free` dev unit. Keep device names and addresses out
  of the repo, commits, and PR text.
- TDD. One commit per change, with the AI trailer block from CLAUDE.md. The maintainer reviews every diff and all
  commit and PR text before anything is pushed.

## Decisions

Written 2026-10-30 against local head `1080421`, and approved by the maintainer the same day.

1. **Trigger: the largest forward step the clock made during the request is more than 20 seconds.** Not "any
   set-time" (a 10-second correction would cost a minute of counting for nothing), and not the net move (see 2).
   The threshold is Frigate's 20-second no-frames watchdog, `FRIGATE_JUMP_SECONDS = 20` in `time/router.py`: a
   smaller step trips nothing, and for any larger one a restart (about a minute) is at least as quick as the
   watchdog's own recovery (about two minutes at 2 minutes ahead), and the only recovery at 5 minutes. Where
   self-recovery stops between 2 and 5 minutes is unknown, so no attempt is made to find it. Backward moves don't
   restart: a 5-minute step back was harmless, and the mechanism (the watchdog compares the last frame's wall-clock
   time with now) can't fire when now moves back. Large backward moves (hours) are untested; the Camera streams check
   (option 2) is the backstop, and the docs don't claim they're safe.

   Measuring: the request reads `clock.now()` (`timedate.now()`, microseconds; not `before.device_time`, whole
   seconds) at the start, after each `set-time`, on each read inside `_put_back`, once after `_synced` reports a
   sync, every `SETTLE_INTERVAL` for `SETTLE_SECONDS` after a request that only turns NTP on (timesyncd's put-back),
   and once at the end, and records `now().timestamp() - time.monotonic()` at each read. A step is the change
   in that difference between two reads; the request keeps the largest positive one. This counts the steps tm-control
   makes and the ones systemd-timesyncd makes while the request watches (put-back, take-over), and ignores how long
   the request took. One small class, `ClockSteps`, in `time/router.py`; `_put_back` and `_hold_time` take it the way
   they take `changed`.
2. **Transient forward steps count.** A put-back is a forward step to timesyncd's saved time, undone 1 to 3 seconds
   later. Whether it stalls Frigate by itself is untested and probabilistic (the watchdog looks every 10 seconds), and
   a take-over is the same shape with the forward step staying (set back 5 minutes, then NTP corrects forward 5
   minutes: net zero, but the forward step is exactly the one that stalled the bench unit). So the rule in 1 looks at
   each step, not the net, and a put-back of more than 20 seconds restarts Frigate even when the time is then set
   back. The cost of being wrong here is one unneeded minute of counting on a rare path (offline, clock ahead); the
   cost of the other mistake is a camera that stays off until someone notices. **Bench repro, for the maintainer's
   approval (Task 7):** if the put-back alone leaves the feed healthy in every one of several tries, a follow-up
   commit can exclude a step that is undone within `SETTLE_SECONDS`; the rule ships conservative either way.
3. **Unit: `frigate.service` alone**, which was seen to fix it. When the same request changes the time zone, the pod
   restart already covers Frigate, so only `CONTAINERS` is queued and listed; Frigate is never restarted twice. One
   background task `_restart_units(units)` replaces `_restart_containers()`, and `restarting` is that list:
   `CONTAINERS`, `["frigate.service"]`, or `[]`. The restart is queued after the response, as the zone's is, and goes
   through `restart_or_log`. `frigate.service` is already in the polkit list. Fake mode queues nothing, as now; its
   `set_time` doesn't move its clock, so a fake "Set from this browser" never lists Frigate.
4. **The page says:** when `restarting` holds `traffic-monitor.service`, the existing "Frigate and Node-RED are
   restarting."; when it holds `frigate.service`, "The clock moved ahead, so Frigate is restarting. The camera view is
   back in about a minute." (the wording of `restarts.ts`'s Frigate result). It follows whatever the result already
   says, including the `ntp_took_over` sentence, since NTP's own correction can be the step. `restarting` stays
   `list[str]`; the OpenAPI document doesn't change. `TimeResult.restarting`'s comment and `tm-control/ui/README.md`'s
   result texts say both.
5. **Camera streams check:** a stream Frigate reads must have a reader (a non-empty `consumers` list) before its
   source is judged. No reader → `error` "Frigate isn't reading stream X for camera Y, so it gets no video", fix
   `restart_fix("frigate.service")`. A reader but no running producer → the existing "has no running source" with
   `Restart Camera streams (go2rtc)`. Both kinds in one report: the detail lists all problems, and the fix is
   Frigate's (without a reader go2rtc never starts an `exec:` source, so the reader comes first). Any consumer counts
   as a reader; go2rtc's `format_name` isn't read, because a false "Restart Frigate" on every device after a go2rtc
   change would cost more than the corner it buys (a `/feeds` viewer masking a stalled Frigate, which the next
   refresh after they leave shows). The Cameras check keeps trusting `camera_fps`: one cause, one check, and its
   detail already points to Camera streams; a frozen-stats signal (`service.last_updated`) is noted in 6, not built.
   The fixture already pins `consumers` (a `rtsp` consumer on the detect stream, `null` on the unread one); the new
   tests edit it, and `test_go2rtc_stream_without_producer_is_an_error` keeps its consumer so it still tests go2rtc's
   fix.
6. **NTP's own jumps** (boot, coming online later) are left to the check: the Status page shows the stall with the
   right button. No automatic recovery now: tm-control restarting a service on its own, or a clock watcher outside a
   request, is a policy question for its own design, and the Frigate side (why ffmpeg exits and the watchdog doesn't
   restart it after a 5-minute step; whether `ffmpeg.retry_interval` or an input `-timeout` matters) is a Frigate
   question. After the PR: one public issue, "Frigate's camera feed doesn't recover from a large forward clock jump
   made by NTP; the Status page offers the restart", with the evidence from "What was seen" and the two follow-ups
   (recovery policy; a stale-stats signal from Frigate's `service.last_updated`). The maintainer writes or approves
   the issue text; this file doesn't.
7. **Tests.** Off-device, with `FakeTimedatectl` (set-time moves `now()`; the put-back and the sync are steps the
   fake already makes): forward 5 minutes with NTP off → Frigate queued and listed; backward 5 minutes → nothing;
   forward 10 seconds → nothing; forward 5 minutes with a new zone → `CONTAINERS` only; a put-back (saved time 5
   minutes ahead, net zero) → Frigate; a take-over that corrects forward 5 minutes → Frigate; the three asserts in the
   existing tests that pin `restarting == []` are checked against the rule. The check: no reader → Frigate's fix; a
   reader and an idle producer → go2rtc's; a running producer and no reader → Frigate's. UI: one Vitest case per
   sentence. On the device: `test_set_time_from_the_api` already moves the clock 2 minutes ahead, so it now also
   asserts `restarting == ["frigate.service"]`, waits for Frigate's new `InvocationID`, and waits for
   `apps.frigate.cameras` and `apps.go2rtc.streams` to be ok; its step back asserts `restarting == []`. The 5-minute
   stall, the check's new sentence and button, and the repro from 2 are logged `tmdev check` items (Task 7), because
   they need a person and a deliberately stalled Frigate.

Docs (option 3): `docs/use/device-health.md` loses the "Frigate does this by itself" paragraph for one that says the
device restarts Frigate after the clock moves ahead by more than about 20 seconds and what the page says; the offline
info box says the same in its own words, since setting the time after a power-off is that case; the Apps row says
Frigate reads the streams. `docs/development/tm-control.md` adds the Frigate restart beside the zone restart. The M3
plan's status note that says the feed recovers by itself gets one sentence pointing here. PR #269's "Moving the clock"
item is replaced (text in Task 8); the maintainer edits the PR.

## Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After a time change that moved the clock ahead by more than 20 seconds, tm-control restarts Frigate and
says so; the Camera streams check offers Restart Frigate when Frigate isn't reading its stream; the docs and PR text
say what happens.

**Architecture:** `POST /time` measures the clock's steps during the request with `ClockSteps` and queues
`frigate.service` through the same background restart as the zone change, listing it in `restarting`. The Camera
streams check reads go2rtc's `consumers` before `producers`. The UI derives its sentence from the units in
`restarting`. No new endpoint, field, unit, or polkit rule.

**Tech stack:** FastAPI + pydantic (backend), pytest with `FakeTimedatectl` and `FakeApps`, Vue 3 + Vitest (UI),
MkDocs (docs), `tmdev.py` (bench).

**Spec:** this file, "Decisions". **Branch:** `feature/tm-control-status-system/201` in the `tm-control-m3`
worktree; every commit goes on top of `1080421` and is reviewed by the maintainer before any push.

### Global constraints

- `SYNC_SECONDS`, `SETTLE_*`, and the leave-NTP-off-after-a-failed-sync policy don't change.
- Restarts go through `restart_or_log`; `frigate.service` only; never sudo.
- Check details name cameras and streams, never a URL, path, or port (`checks.py`'s docstring; the existing test
  asserts `exec:`, `rtsp://`, and `8554` are absent).
- Commit messages: imperative subject, the AI trailer block from CLAUDE.md (`Assisted-by`, `AI-Model`, `AI-Effort`,
  `AI-Role: drafted`); no `Co-Authored-By`. Ask for the CLI version and effort level if unknown.
- Device names and addresses stay out of the repo, commits, and PR text.
- Run the whole off-device suite before each commit:
  `. .venv/bin/activate && python -m pytest container/node-red-tm/schema/tests script/tests tm-control/backend/tests`.

### Review focus

Inputs the spec implies that no test here exercises, most likely to bite first:

1. A browser 20 to 30 seconds ahead: the restart costs a minute where the watchdog might have cost two. Accepted;
   `test_a_forward_step_of_ten_seconds_restarts_nothing` pins the lower side only.
2. While Frigate restarts (about a minute), Camera streams reads "Frigate isn't reading …" with a Restart Frigate
   button, as Cameras already does with `camera_fps` 0. The page's restart result stays under the button meanwhile.
3. A `/feeds` viewer keeps a consumer on the stream while Frigate is stalled: the check says ok until they leave.
   Noted in the check's docstring, not fixed.
4. A failed `systemctl restart frigate.service` after the response is only logged, as for the zone's restart; the
   page still says Frigate is restarting. `restart_or_log`'s existing behaviour; no new test. A request that fails
   after the clock moved ahead answers with its error, which runs no background task, so Frigate is restarted at once
   (`test_a_forward_step_before_a_failure_still_restarts_frigate`).
5. A backward move of hours is untested. The docs say ahead; they don't say back is safe.

---

### Task 1: Camera streams check reads go2rtc's consumers and offers the right restart

**Files:**
- Modify: `tm-control/backend/tm_control/modules/apps/checks.py:187-223` (`_running`, `camera_streams`)
- Modify: `tm-control/backend/tm_control/adapters/go2rtc.py:9-13` (docstring: a consumer is a reader)
- Test: `tm-control/backend/tests/test_app_checks.py:251-290`

**Interfaces:**
- Consumes: `probes.go2rtc_streams(context)`, `probes.frigate_config(context)`, `restart_fix(unit)`.
- Produces: `apps.go2rtc.streams` with `fix.unit == "frigate.service"` when a stream Frigate reads has no consumer;
  unchanged otherwise. A helper `_read(stream) -> bool` (a non-empty `consumers` list) beside `_running`.

- [ ] **Step 1: Change the existing test so it still tests go2rtc's fix, and add the reader tests**

In `test_go2rtc_stream_without_producer_is_an_error`, drop `consumers=None` from the `update(...)` call (the fixture's
consumer stays) and change the comment to "An idle producer is listed with only its source URL; Frigate is still
reading, so the source is go2rtc's to fix." Then add:

```python
def test_a_stream_frigate_isnt_reading_asks_for_a_frigate_restart(apps):
    """go2rtc starts an exec: source only while someone reads the stream, so no reader means Frigate's capture
    stopped: restarting go2rtc doesn't help, restarting Frigate does (seen on a bench unit after a clock jump)."""
    apps.edit_json(GO2RTC_STREAMS, lambda streams: streams["picam_h265_detect"].update(
        producers=[{"url": "exec:rpicam-vid --camera 0 -o -"}], consumers=None,
    ))
    check = apps_group(apps)["apps.go2rtc.streams"]
    assert check.status == "error"
    assert check.detail.startswith("Frigate isn't reading stream picam_h265_detect for camera picam_h265")
    assert "exec:" not in check.detail and "rtsp://" not in check.detail and "8554" not in check.detail
    assert check.fix == Fix(kind="restart", text="Restart Frigate", unit="frigate.service")


def test_a_running_stream_without_a_reader_is_still_frigates(apps):
    apps.edit_json(GO2RTC_STREAMS, lambda streams: streams["picam_h265_detect"].update(consumers=[]))
    check = apps_group(apps)["apps.go2rtc.streams"]
    assert check.status == "error" and check.fix.unit == "frigate.service"


def test_a_stream_nobody_reads_and_one_without_a_source_name_both_and_fix_frigate_first(apps):
    def edit(config):
        camera = config["cameras"]["picam_h265"]
        config["cameras"]["second"] = {**camera, "ffmpeg": {"inputs": [
            {"path": "rtsp://*:*@host.containers.internal:8554/second_detect", "roles": ["detect"]}]}}

    apps.edit_json(CONFIG, edit)
    apps.edit_json(GO2RTC_STREAMS, lambda streams: streams.update(
        picam_h265_detect={**streams["picam_h265_detect"], "consumers": None},
        second_detect={"producers": [{"url": "exec:x"}], "consumers": [{"id": 9, "format_name": "rtsp"}]},
    ))
    check = apps_group(apps)["apps.go2rtc.streams"]
    assert check.status == "error" and check.fix.unit == "frigate.service"
    assert "Frigate isn't reading stream picam_h265_detect" in check.detail
    assert "stream second_detect for camera second has no running source" in check.detail
```

- [ ] **Step 2: Run the three new tests and the changed one; expect the new ones to fail**

Run: `python -m pytest tm-control/backend/tests/test_app_checks.py -k go2rtc -v`
Expected: the new tests FAIL (fix is go2rtc's, detail starts with "Stream …"); the changed one PASSES.

- [ ] **Step 3: Implement**

In `checks.py`: add `_read(stream) -> bool` ("go2rtc lists the stream's readers under consumers; null or empty means
nobody, Frigate included, reads it"). In `camera_streams`, for each stream Frigate reads, in this order: missing →
the existing sentence; `not _read(...)` → `f"Frigate isn't reading stream {stream} for camera {camera_name}, so it
gets no video"` and remember that Frigate is to blame; no running producer → the existing sentence. When there are
problems: if any is Frigate's, the fix is `restart_fix("frigate.service")` and the trailing advice is "Restart
Frigate; if that doesn't help, download the diagnostics on the Device page."; else the existing go2rtc advice and
fix. Update the function's docstring: "Each go2rtc stream that a camera enabled in Frigate reads has a reader (Frigate
itself; a `/feeds` viewer also counts) and a running source. Without a reader go2rtc never starts an `exec:` source,
so the reader is judged first." Update `go2rtc.streams`'s docstring with the consumers line.

- [ ] **Step 4: Run the file, then the whole suite**

Run: `python -m pytest tm-control/backend/tests/test_app_checks.py -v`, then the full off-device command.
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add tm-control/backend/tm_control/modules/apps/checks.py tm-control/backend/tm_control/adapters/go2rtc.py tm-control/backend/tests/test_app_checks.py
git commit -m "Offer Restart Frigate when a stream it reads has no reader" -m "<why: go2rtc restarts don't bring back a Frigate capture that stopped; a bench unit after a 5-minute clock jump>" -m "<trailer block>"
```

### Task 2: POST /time restarts Frigate after a forward step of more than 20 seconds

**Files:**
- Modify: `tm-control/backend/tm_control/modules/time/router.py` (module docstring, `TimeResult.restarting` comment,
  `CONTAINERS` block, `_put_back`, `_hold_time`, `_restart_containers`, `change`)
- Test: `tm-control/backend/tests/test_api_time.py`

**Interfaces:**
- Consumes: `restart_or_log(unit)`, `BackgroundTasks`, `clock.now()`.
- Produces: `FRIGATE_JUMP_SECONDS = 20`; `FRIGATE = "frigate.service"`; `class ClockSteps` with
  `__init__(self, clock)`, `read(self) -> datetime` (reads the clock, records the step, returns the time), and
  `forward: float` (the largest positive step in seconds, 0.0 when none); `_put_back(clock, when, set_at, steps)`
  and `_hold_time(clock, when, set_at, changed, steps)` read through `steps.read()` instead of `clock.now()`;
  `_restart_units(units: list[str]) -> None`; `TimeResult.restarting` is `CONTAINERS` after a zone change, else
  `[FRIGATE]` when `steps.forward > FRIGATE_JUMP_SECONDS`, else `[]`.

- [ ] **Step 1: Write the failing tests** (after `test_set_time_with_ntp_off_leaves_ntp_alone`)

```python
# Frigate after a forward step (FRIGATE_JUMP_SECONDS): a clock that moves ahead by more than Frigate's 20-second
# no-frames watchdog stops its camera feed, and from a few minutes it doesn't come back without a restart.

FRIGATE = ["frigate.service"]


def test_a_forward_step_of_five_minutes_restarts_frigate(device_client, login, timedatectl, systemctl):
    timedatectl.props |= {"NTP": "no", "NTPSynchronized": "no"}
    login(device_client, *ADMIN)
    r = change(device_client, {"time": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()})
    assert r.status_code == 200, r.text
    assert r.json()["restarting"] == FRIGATE
    assert systemctl == [["systemctl", "restart", "--no-block", "frigate.service"]]


def test_a_backward_step_of_five_minutes_restarts_nothing(device_client, login, timedatectl, systemctl):
    timedatectl.props |= {"NTP": "no", "NTPSynchronized": "no"}
    login(device_client, *ADMIN)
    r = change(device_client, {"time": (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()})
    assert r.status_code == 200, r.text
    assert r.json()["restarting"] == [] and systemctl == []


def test_a_forward_step_of_ten_seconds_restarts_nothing(device_client, login, timedatectl, systemctl):
    timedatectl.props |= {"NTP": "no", "NTPSynchronized": "no"}
    login(device_client, *ADMIN)
    r = change(device_client, {"time": (datetime.now(timezone.utc) + timedelta(seconds=10)).isoformat()})
    assert r.status_code == 200, r.text
    assert r.json()["restarting"] == [] and systemctl == []


def test_a_forward_step_with_a_new_zone_restarts_the_pod_once(device_client, login, timedatectl, systemctl, tzset):
    """The pod restart covers Frigate: it isn't restarted twice, and restarting lists the pod and nginx only."""
    timedatectl.props |= {"NTP": "no", "NTPSynchronized": "no"}
    login(device_client, *ADMIN)
    r = change(device_client, {"time": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
                               "timezone": "Europe/Berlin"})
    assert r.status_code == 200, r.text
    assert r.json()["restarting"] == CONTAINERS
    assert systemctl == [["systemctl", "restart", "--no-block", unit] for unit in CONTAINERS]


def test_a_put_back_that_is_undone_still_restarts_frigate(device_client, login, timedatectl, systemctl):
    """Offline, clock ahead: timesyncd steps the clock forward to its saved time for a moment before the time is set
    back. The net move is nothing; the forward step may still have stopped Frigate's feed, so Frigate restarts."""
    timedatectl.props["NTPSynchronized"] = "no"
    sent = datetime.now(timezone.utc).replace(microsecond=0)
    timedatectl.saved = sent + timedelta(minutes=5)
    login(device_client, *ADMIN)
    r = change(device_client, {"time": sent.isoformat()})
    assert r.status_code == 200, r.text
    assert r.json()["ntp_left_off"] is True and r.json()["restarting"] == FRIGATE
    assert systemctl == [["systemctl", "restart", "--no-block", "frigate.service"]]


def test_a_take_over_that_corrects_the_clock_forward_restarts_frigate(device_client, login, timedatectl, systemctl):
    """The browser was 5 minutes behind and NTP corrected the clock forward while the time was being set: the step
    is NTP's, and it's the one that stops the feed."""
    timedatectl.props["NTPSynchronized"] = "no"
    timedatectl.online = True
    login(device_client, *ADMIN)
    r = change(device_client, {"time": (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()})
    assert r.status_code == 200, r.text
    assert r.json()["ntp_took_over"] is True and r.json()["restarting"] == FRIGATE


def test_clock_steps_keep_the_largest_forward_step():
    offsets = iter([0.0, 300.0, 0.0, 120.0])  # the clock's offset from a steady one at each read, in seconds
    clock = SimpleNamespace(now=lambda: datetime.now(timezone.utc) + timedelta(seconds=next(offsets)))
    steps = time_router.ClockSteps(clock)  # the first read
    for _ in range(3):
        steps.read()
    assert 299 < steps.forward < 301  # +300, -300, +120: the largest, not the sum or the net
```

Also, in `test_set_from_browser_without_ntp_sync_sets_the_time_turns_ntp_back_on_then_the_zone` and
`test_offline_a_time_that_stays_keeps_ntp_on`, the times sent are in the past relative to the fake's clock, so
`restarting` stays as asserted; in `test_online_a_sync_just_after_the_put_back_keeps_ntp_on` the put-back is a
5-minute step, so add `assert r.json()["restarting"] == ["frigate.service"]` there.

`test_offline_a_time_put_back_a_moment_later_is_caught` counts `timedate.now()` reads and moves the clock on the third
(`len(reads) == 3`). `show()` reads `now()` once for `device_time`, and Task 2 adds a read when `ClockSteps` is made
and one after `set-time`, so the watch's first read becomes the fourth and its second the fifth. Change the condition
to `len(reads) == 5` and the comment to name the reads: the state before the change, the step tracker's first, the
one after set-time, then the watch's first and second.

- [ ] **Step 2: Run the new tests; expect failure**

Run: `python -m pytest tm-control/backend/tests/test_api_time.py -k "step or put_back_that or take_over_that or clock_steps" -v`
Expected: FAIL (`restarting == []`, `ClockSteps` undefined).

- [ ] **Step 3: Implement in `router.py`**

Add after `SYNC_SECONDS`, with a comment that names the watchdog, the 2-minute recovery and the 5-minute stall from
"What was seen", and that backward moves don't restart:

```python
FRIGATE = "frigate.service"
FRIGATE_JUMP_SECONDS = 20
```

Add `class ClockSteps` as in Interfaces: `__init__` stores the clock, takes the first read, sets `forward = 0.0`;
`read()` computes `offset = now.timestamp() - time.monotonic()`, sets `forward = max(forward, offset - last)`, stores
`last`, returns `now`. Change `_put_back(clock, when, set_at, steps)` to read with `steps.read()`; `_hold_time(clock,
when, set_at, changed, steps)` passes it on and calls `steps.read()` once after `_synced` returns True. Replace
`_restart_containers()` with `_restart_units(units: list[str])` ("run after the response has been sent: nginx
carries it, and a Frigate restart after a clock step should be reported before it begins"). In `change`: create
`steps = ClockSteps(clock)` right after `before = _show(clock)`; call `steps.read()` after each `set_time` that
succeeded (three places); pass `steps` to both `_hold_time` calls; after the zone block, before `finished = True`:

```python
        steps.read()
        if zone_changed:
            units = list(CONTAINERS)  # the pod restart covers Frigate
        elif steps.forward > FRIGATE_JUMP_SECONDS:
            units = [FRIGATE]
        else:
            units = []
        if units and not app_state.settings.fake:
            background.add_task(_restart_units, units)
```

and `restarting=units` in the result (drop the `restarting = ...` line and the zone block's `background.add_task`;
`time.tzset()` stays there). Update the module docstring's last sentences ("A new time zone restarts the pod and nginx after the response,
so the containers see it; a clock that moved ahead by more than 20 seconds during the request, by set-time or by
NTP, restarts Frigate, whose camera feed stops on such a step and from a few minutes doesn't come back on its own.")
and `restarting`'s comment ("units restarting after the response: the pod and nginx after a new time zone, or Frigate
after the clock moved ahead").

- [ ] **Step 4: Run the file, then the whole suite**

Run: `python -m pytest tm-control/backend/tests/test_api_time.py -v`, then the full off-device command.
Expected: all PASS, including `test_openapi_declares_the_time_models` (no new field).

- [ ] **Step 5: Commit**

```bash
git add tm-control/backend/tm_control/modules/time/router.py tm-control/backend/tests/test_api_time.py
git commit -m "Restart Frigate after the clock moves ahead by more than 20 seconds" -m "<why, from What was seen>" -m "<trailer block>"
```

### Task 3: The Date and time page says Frigate is restarting after a clock step

**Files:**
- Modify: `tm-control/ui/src/modules/time/TimePage.vue:18,83-106` (`RESTARTING`, `setOutcome`, `saveZone`'s use)
- Modify: `tm-control/ui/README.md:338-345` (the result texts bullet)
- Test: `tm-control/ui/tests/time-page.spec.ts`

**Interfaces:**
- Consumes: `TimeResult.restarting: string[]` with `traffic-monitor.service` or `frigate.service`.
- Produces: `FRIGATE_RESTARTING = 'The clock moved ahead, so Frigate is restarting. The camera view is back in about a minute.'`; `restartingSentence(restarting: string[]): string` ('' when neither unit is listed).

- [ ] **Step 1: Write the failing tests** (beside "says when the device kept the time it had from the internet")

```ts
  it('says Frigate is restarting when the clock moved ahead', async () => {
    admin({ [`POST ${TIME}`]: timeResult({ device_time: '2026-10-28T14:35:12-07:00', restarting: ['frigate.service'] }) })
    const { wrapper } = await mountApp('/time')
    await click(wrapper, 'Set from this browser')
    expect(wrapper.text()).toContain(
      'Time set from this browser. The clock moved ahead, so Frigate is restarting. The camera view is back in about a minute.',
    )
    expect(wrapper.text()).not.toContain('Node-RED')
  })

  it('says Frigate is restarting after internet time corrected the clock forward', async () => {
    admin({ [`POST ${TIME}`]: timeResult({ ntp_took_over: true, restarting: ['frigate.service'] }) })
    const { wrapper } = await mountApp('/time')
    await click(wrapper, 'Set from this browser')
    expect(wrapper.text()).toContain(
      "not this browser's. The clock moved ahead, so Frigate is restarting. The camera view is back in about a minute.",
    )
  })
```

(`admin`, `mountApp`, `click`, `timeResult`, and `TIME` are the file's existing helpers.)

- [ ] **Step 2: Run Vitest; expect the two to fail**

Run: `podman run --rm -v "$PWD/tm-control/ui:/ui:Z" -w /ui docker.io/library/node:22.23.4-alpine sh -c 'npm ci && npm test -- time-page'`
Expected: FAIL (no sentence; the page shows "Frigate and Node-RED are restarting." for any non-empty list).

- [ ] **Step 3: Implement**

In `TimePage.vue`: add `FRIGATE_RESTARTING`; add
`function restartingSentence(restarting: string[]): string` returning `RESTARTING` when the list includes
`traffic-monitor.service`, `FRIGATE_RESTARTING` when it includes `frigate.service`, else `''`. In `setOutcome`,
replace `const restarting = result.restarting.length > 0 // only a time zone change restarts anything` with the pod
test (`result.restarting.includes('traffic-monitor.service')`, which is what "only the time zone changed" means), and
end with `const tail = restartingSentence(result.restarting); return tail ? `${text} ${tail}` : text`. `saveZone`
keeps its pod test. In the README bullet, after "followed by "Frigate and Node-RED are restarting." when the zone
changed", add: "or by "The clock moved ahead, so Frigate is restarting. The camera view is back in about a minute."
when the time moved ahead by more than 20 seconds (`restarting` lists `frigate.service`; the device restarts
Frigate because such a step stops its camera feed)".

- [ ] **Step 4: Build and test in the pinned Node image**

Run: `podman run --rm -v "$PWD/tm-control/ui:/ui:Z" -w /ui docker.io/library/node:22.23.4-alpine sh -c 'npm ci && npm run build && npm test'`
Expected: build ok, all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add tm-control/ui/src/modules/time/TimePage.vue tm-control/ui/tests/time-page.spec.ts tm-control/ui/README.md
git commit -m "Say on the page when Frigate restarts after the clock moved ahead" -m "<trailer block>"
```

### Task 4: Docs say the device restarts Frigate after the clock moves ahead

**Files:**
- Modify: `docs/use/device-health.md:33,77-83`
- Modify: `docs/development/tm-control.md:97`
- Modify: `design/plans/2026-10-28-tm-control-m3-status-and-system.md:35` (one sentence)

- [ ] **Step 1: Edit `device-health.md`**

Apps row: "The camera streams run, and Frigate reads them." Replace the "Moving the clock ahead …" paragraph with:

> Moving the clock ahead by more than about 20 seconds stops Frigate's camera feed, and a move of a few minutes
> stops it until Frigate restarts. So when a change moves the clock ahead by that much, the device restarts Frigate
> and the page says so. Traffic isn't counted for about a minute. Moving the clock back doesn't restart anything.

In the offline info box, after "choose **Set from this browser**": "The clock is usually behind after a power-off,
so this moves it ahead and restarts Frigate; the camera is back in about a minute." Keep the rest.

- [ ] **Step 2: Edit `tm-control.md` line 97**

After the zone-change sentence: "A time change that moved the clock ahead by more than 20 seconds (`FRIGATE_JUMP_SECONDS`
in `modules/time/router.py`), by `set-time` or by NTP while the request watched, restarts `frigate.service` the same
way, because Frigate's capture stops on such a step and, from a few minutes, doesn't recover by itself; a time zone
change in the same request restarts the pod instead, which covers Frigate."

- [ ] **Step 3: Note in the M3 plan**

At the end of the line-35 bullet: "Amended 2026-10-30: a 5-minute step didn't recover; see
`design/plans/2026-10-30-tm-control-m3-forward-clock-jump.md`."

- [ ] **Step 4: Build the docs strictly**

Run: `~/.venvs/tm-docs/bin/mkdocs build --strict`
Expected: no warnings or errors.

- [ ] **Step 5: Commit**

```bash
git add docs/use/device-health.md docs/development/tm-control.md design/plans/2026-10-28-tm-control-m3-status-and-system.md
git commit -m "Say the device restarts Frigate after the clock moves ahead" -m "<trailer block>"
```

### Task 5: The device test checks the Frigate restart and the feed after it

**Files:**
- Modify: `script/devpi/tests/test_disruptive.py:496-533` (`test_set_time_from_the_api`)

**Interfaces:**
- Consumes: `invocation(host, unit)`, the module's wait-for-new-`InvocationID` helper (lines 311-326),
  `wait_for_check(address, cookie, check_id, wanted, timeout)`, `UNIT_RESTART_SECONDS`.

- [ ] **Step 1: Extend the test**

Before the forward `post_time`, read `before = {"frigate.service": invocation(host, "frigate.service")}`. After it:
`assert result.get("restarting") == ["frigate.service"], "a 2-minute step ahead should restart Frigate"`; wait for
Frigate's new `InvocationID` within `UNIT_RESTART_SECONDS`; then `wait_for_check(address, cookie,
"apps.go2rtc.streams", "ok", FEED_BACK_SECONDS)` and the same for `apps.frigate.cameras`, with
`FEED_BACK_SECONDS = 90` beside `TIME_AHEAD_SECONDS` ("Frigate's restart, then its first frames from go2rtc").
In the `finally`, keep the step back and assert its `restarting` is `[]` when it answered 200. Update the docstring:
"… The test sets it 2 minutes ahead, which restarts Frigate, waits for the feed to be back, then sets it back …".

- [ ] **Step 2: Check the file compiles and the suite still collects**

Run: `python -m pytest script/devpi/tests --collect-only -q 2>&1 | tail -3`
Expected: collected, no errors (the tests themselves skip without `TM_DEV_HOSTS`).

- [ ] **Step 3: Commit**

```bash
git add script/devpi/tests/test_disruptive.py
git commit -m "Check that a step ahead restarts Frigate and the feed comes back" -m "<trailer block>"
```

### Task 6: Deploy to the bench unit and run the device tests

Needs the maintainer or their go-ahead; every command is logged by `tmdev.py`.

- [ ] `T=".venv/bin/python script/devpi/tmdev.py"; $T check start --host <host> --pr 269 --title "Forward clock jump: Frigate restart and the Camera streams fix"`
- [ ] `$T deploy <host> -- -t tm-control -t revproxy` (the UI is in the revproxy image; expect a rebuild, several minutes)
- [ ] `$T test <host> --disruptive -- -k "set_time or restart_from or timezone"`; expected: pass, with Frigate's
  restart and the two checks ok inside 90 s.
- [ ] `$T test <host>` (the non-disruptive suite); expected: pass, `test_status_report_agrees_with_the_inventory`
  included.

### Task 7: Bench checks that need a person (logged `tmdev check` items)

Each is one `$T check item "<text>" pass|fail --evidence cmd-NNN` after the commands below, run through `$T run <host>
-- <command>` or the API from the laptop with the unit's admin login. Internet blocked on the unit as in the earlier
checks (the temporary `nft` table). Feed health is judged from go2rtc's `/api/streams` only (a consumer, growing
`bytes_recv`) and the Status report; no images.

- [ ] **5 minutes ahead through the API** (NTP off first, as `test_set_time_from_the_api` does): `restarting` is
  `["frigate.service"]`, the page says "The clock moved ahead, so Frigate is restarting…", and within 90 s the
  stream has a reader and growing bytes, Cameras and Camera streams are ok. Then 5 minutes back: `restarting` is
  `[]` and the feed stays healthy for 2 minutes.
- [ ] **The check's new sentence and button:** with NTP off, `sudo timedatectl set-time` 5 minutes ahead on the unit
  (by hand, so tm-control doesn't restart Frigate). Within 60 s Camera streams reads "Frigate isn't reading stream
  picam_h265_detect for camera picam_h265 …" with **Restart Frigate**, and Cameras is still ok (frozen stats, as
  seen). Press Restart Frigate: healthy within 90 s. Then `set-ntp true` and confirm the clock resyncs.
- [ ] **Repro for decision 2, for the maintainer's approval (optional):** offline with the clock set 5 minutes ahead
  and `set-ntp true` so timesyncd saves it, then set the clock back by hand, `set-ntp false`, and "Set from this
  browser" from the laptop: the put-back and set-back happen (`ntp_left_off`), and with Task 2 Frigate restarts. To
  learn whether the put-back alone stalls the feed, repeat with tm-control's restart disabled for the trial
  (`FRIGATE_JUMP_SECONDS` raised in a copy of the venv's `router.py` on the unit, restored afterwards, or the same
  request made before Task 2's deploy), 5 tries, each watching the feed for 2 minutes. 5 of 5 healthy → a follow-up
  commit may ignore a step undone within `SETTLE_SECONDS`; any stall → the rule stays. Skipping the repro leaves the
  conservative rule, which is safe.
- [ ] Afterwards: NTP on, the clock synced, `$T test <host>` passes, 26 checks ok. `$T check end`.

### Task 8: PR #269 text (maintainer)

Replace the "Moving the clock" item in the Testing section, through `gh api -X PATCH repos/<owner>/<repo>/pulls/269 -f body=@-`
(`gh pr edit` fails on this repo), after the maintainer has read it:

> - [ ] **Moving the clock:** a 2-minute step ahead tripped Frigate's 20-second no-frames watchdog, and the feed came
>   back by itself after about two minutes. A 5-minute step ahead stopped the feed for good: Frigate's ffmpeg exited,
>   its watchdog didn't start it again, and its stats froze with a nonzero `camera_fps`, so the Cameras check stayed
>   ok while Camera streams said to restart go2rtc, which didn't help; only a Frigate restart did. A 5-minute step
>   back was harmless. Fixed: the control app restarts Frigate after a change that moved the clock ahead by more than
>   20 seconds, by the browser's time or by internet time while it watched, and says so on the page; a time zone
>   change in the same request restarts the pod, which covers Frigate. The Camera streams check now offers Restart
>   Frigate when Frigate isn't reading its stream, and Restart go2rtc only when it is and the stream has no source.
>   Verified on the bench unit: a 5-minute step ahead through the API restarts Frigate and the feed is healthy within
>   90 seconds; a step made by hand shows the new check and its button fixes it. The Date and time docs say so.

Tick it once Task 7's first two items pass. Also add the four commits' subjects to the PR's change list where the
other review-fix commits are listed.

### Self-review

- Spec coverage: option 1 → Task 2; option 2 → Task 1; option 3 → Tasks 4 and 8; the seven decisions each have a
  test or a logged check (decision 6 is a follow-up issue by design).
- Type consistency: `ClockSteps.read()`/`forward`, `_restart_units(units)`, `FRIGATE`, `FRIGATE_JUMP_SECONDS` are
  used with the same names in Tasks 2, 4, 5, and 7; the check's sentence in Task 1 is the one Tasks 7 and 8 quote.
- Proportion: the code in Tasks 1 to 3 is about 40 lines; the tests are most of this plan on purpose, because the
  rule's edge cases (put-back, take-over, zone in the same request) are what a reviewer can't infer.
