"""The status check core: running a module's check functions with timeouts, the summary, the cache, and probe memos."""

import threading
import time
from datetime import datetime

import pytest

from tm_control.core.checks import Check, CheckGroup, Context, StatusCache, run_group


def context():
    return Context(settings=None, manifest=None, secrets=None)


def ok_check(check_id, status="ok"):
    return Check(id=check_id, title=check_id, status=status, detail=f"{check_id} detail")


def counting(fn):
    """fn wrapped so that wrapper.calls counts its calls."""

    def wrapper(*args):
        wrapper.calls += 1
        return fn(*args)

    wrapper.calls = 0
    return wrapper


def test_run_group_collects_each_functions_checks():
    def first(ctx):
        return [ok_check("demo.first")]

    def second(ctx):
        return [ok_check("demo.second", "warn")]

    group = run_group(CheckGroup("demo", "Demo", [first, second]), context())
    assert group.id == "demo" and group.title == "Demo"
    assert [c.id for c in group.checks] == ["demo.first", "demo.second"]
    assert [c.status for c in group.checks] == ["ok", "warn"]


def test_a_check_that_raises_becomes_unknown_without_a_traceback():
    def broken(ctx):
        raise RuntimeError("secret-value")

    group = run_group(CheckGroup("demo", "Demo", [broken]), context())
    [check] = group.checks
    assert check.id == "demo.broken"
    assert check.status == "unknown"
    assert check.detail == "The check failed (RuntimeError)."
    assert "secret-value" not in check.detail


def test_a_check_that_hangs_becomes_unknown_within_the_timeout():
    def hangs(ctx):
        time.sleep(3)
        return [ok_check("demo.hangs")]

    def quick(ctx):
        return [ok_check("demo.quick")]

    started = time.monotonic()
    group = run_group(CheckGroup("demo", "Demo", [hangs, quick]), context(), timeout=0.2)
    assert time.monotonic() - started < 1
    hung, done = group.checks
    assert hung.id == "demo.hangs"
    assert hung.status == "unknown"
    assert hung.detail == "The check didn't finish within 0.2 seconds."
    assert done.id == "demo.quick" and done.status == "ok"


def test_a_check_that_raises_timeout_error_is_a_failure_not_a_timeout():
    def times_out_itself(ctx):
        raise TimeoutError("socket")

    [check] = run_group(CheckGroup("demo", "Demo", [times_out_itself]), context()).checks
    assert check.status == "unknown" and check.detail == "The check failed (TimeoutError)."


def test_a_check_that_returns_something_else_becomes_unknown():
    def not_a_list(ctx):
        return {"status": "ok"}

    [check] = run_group(CheckGroup("demo", "Demo", [not_a_list]), context()).checks
    assert check.status == "unknown" and check.detail == "The check failed (TypeError)."


def test_summary_counts_every_status():
    def oks(ctx):
        return [ok_check("a.one"), ok_check("a.two")]

    def others(ctx):
        return [ok_check("b.warn", "warn"), ok_check("b.error", "error"), ok_check("b.unknown", "unknown")]

    cache = StatusCache([CheckGroup("a", "A", [oks]), CheckGroup("b", "B", [others])], context)
    report = cache.report()
    assert report.summary == {"ok": 2, "warn": 1, "error": 1, "unknown": 1}
    assert [g.id for g in report.groups] == ["a", "b"]


def test_summary_has_every_key_when_a_status_is_absent():
    report = StatusCache([], context).report()
    assert report.summary == {"ok": 0, "warn": 0, "error": 0, "unknown": 0}
    assert report.groups == []


def test_generated_at_is_iso_8601_with_an_offset_to_the_second():
    generated = datetime.fromisoformat(StatusCache([], context).report().generated_at)
    assert generated.utcoffset() is not None
    assert generated.microsecond == 0


def test_cache_reuses_a_fresh_report_and_force_bypasses_it():
    fn = counting(lambda ctx: [ok_check("demo.count")])
    fn.__name__ = "count"
    cache = StatusCache([CheckGroup("demo", "Demo", [fn])], context, ttl=5.0)
    first = cache.report()
    assert cache.report() is first
    assert fn.calls == 1
    cache.report(force=True)
    assert fn.calls == 2


def test_cache_runs_the_checks_again_after_the_ttl():
    fn = counting(lambda ctx: [ok_check("demo.count")])
    fn.__name__ = "count"
    cache = StatusCache([CheckGroup("demo", "Demo", [fn])], context, ttl=0.05)
    cache.report()
    time.sleep(0.1)
    cache.report()
    assert fn.calls == 2


def test_probes_memo_is_per_report():
    counter = counting(lambda: "Bus 001 Device 001: ID 1d6b:0002")

    def first(ctx):
        return [ok_check("demo.first", "ok" if ctx.probe("lsusb", counter) else "error")]

    def second(ctx):
        return [ok_check("demo.second", "ok" if ctx.probe("lsusb", counter) else "error")]

    cache = StatusCache([CheckGroup("demo", "Demo", [first]), CheckGroup("other", "Other", [second])], context)
    cache.report()
    assert counter.calls == 1
    cache.report(force=True)
    assert counter.calls == 2


def test_concurrent_probe_callers_wait_for_the_first():
    ctx = context()
    started = threading.Event()

    def slow():
        started.set()
        time.sleep(0.1)
        return None  # a None result is memoized too

    slow = counting(slow)
    results = []
    threads = [threading.Thread(target=lambda: results.append(ctx.probe("lspci", slow))) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert slow.calls == 1
    assert results == [None] * 4
    assert ctx.probes == {"lspci": None}


def test_a_probe_that_raises_raises_the_same_error_for_every_caller():
    ctx = context()
    failing = counting(lambda: (_ for _ in ()).throw(OSError("lsusb missing")))
    with pytest.raises(OSError) as first:
        ctx.probe("lsusb", failing)
    with pytest.raises(OSError) as second:
        ctx.probe("lsusb", failing)
    assert first.value is second.value
    assert failing.calls == 1


def test_groups_run_concurrently_so_a_report_takes_about_one_timeout():
    def hangs(ctx):
        time.sleep(1)
        return []

    def hangs_too(ctx):
        time.sleep(1)
        return []

    groups = [CheckGroup("a", "A", [hangs]), CheckGroup("b", "B", [hangs_too])]
    cache = StatusCache(groups, context, timeout=0.3)
    started = time.monotonic()
    report = cache.report()
    assert time.monotonic() - started < 0.6  # one timeout and room to spare; two in series take at least 0.6 s
    assert [c.status for g in report.groups for c in g.checks] == ["unknown", "unknown"]
