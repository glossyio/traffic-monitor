"""The poster: the thread that gathers the setup snapshot and posts it to Node-RED. gather and post are plain
functions here, and the loop's waits are injected, so nothing sleeps for real except the one thread test."""

import logging
import threading

import pytest

from tm_control.adapters.nodered import NodeRedError
from tm_control.modules.setup_history.poster import INTERVAL, RETRY, Poster
from tm_control.modules.setup_history.snapshot import INCOMPLETE, Snapshot

COMPLETE = Snapshot({"complete": True, "device": {}, "cameras": {}}, ("model_title",))


def test_the_intervals():
    assert (INTERVAL, RETRY) == (300.0, 30.0)


def test_run_once_posts_the_body_and_reports_complete():
    posted = []
    poster = Poster(lambda: COMPLETE, posted.append)
    assert poster.summary() == {"gathered": False, "flagged": []}
    assert poster.run_once() is True
    assert posted == [COMPLETE.body]
    assert poster.summary() == {"gathered": True, "flagged": ["model_title"]}


def test_run_once_posts_an_incomplete_snapshot_too():
    posted = []
    poster = Poster(lambda: INCOMPLETE, posted.append)
    assert poster.run_once() is False
    assert posted == [INCOMPLETE.body]
    assert poster.summary()["gathered"] is False


@pytest.mark.parametrize("failing", ["gather", "post"])
def test_run_once_never_raises(failing, caplog):
    def gather():
        if failing == "gather":
            raise RuntimeError("secret text")
        return COMPLETE

    def post(body):
        if failing == "post":
            raise NodeRedError("unreachable")

    poster = Poster(gather, post)
    with caplog.at_level(logging.DEBUG):
        assert poster.run_once() is False
    assert len(caplog.records) == 1
    text = caplog.records[0].getMessage()
    assert ("RuntimeError" if failing == "gather" else "NodeRedError") in text
    assert "secret text" not in caplog.text and "unreachable" not in caplog.text


def test_a_failed_post_still_reports_what_was_gathered():
    answers = iter([None, NodeRedError("unreachable")])

    def post(body):
        outcome = next(answers)
        if outcome:
            raise outcome

    poster = Poster(lambda: COMPLETE, post)
    assert poster.run_once() is True
    assert poster.run_once() is False
    assert poster.summary() == {"gathered": True, "flagged": ["model_title"]}  # what was gathered, posted or not


def test_the_loop_waits_the_interval_after_a_complete_post_and_the_retry_otherwise():
    results = iter([COMPLETE, INCOMPLETE, COMPLETE])
    waits = []
    poster = Poster(lambda: next(results), lambda body: None)

    def wait(seconds):
        waits.append(seconds)
        if len(waits) == 3:
            poster.stop()

    poster._loop(wait)
    assert waits == [300.0, 30.0, 300.0]


def test_wake_ends_the_wait():
    calls = threading.Semaphore(0)

    def gather():
        calls.release()
        return COMPLETE

    poster = Poster(gather, lambda body: None, interval=60.0)
    poster.start()
    try:
        assert calls.acquire(timeout=2)
        assert not calls.acquire(timeout=0.2)  # it is waiting out the interval
        poster.wake()
        assert calls.acquire(timeout=1)
    finally:
        poster.stop()
    assert poster._thread is not None
    poster._thread.join(2)
    assert not poster._thread.is_alive()


def test_start_twice_runs_one_thread():
    before = threading.active_count()
    poster = Poster(lambda: COMPLETE, lambda body: None, interval=60.0)
    poster.start()
    try:
        first = poster._thread
        poster.start()
        assert poster._thread is first
        assert threading.active_count() == before + 1
        assert first.daemon
    finally:
        poster.stop()
        first.join(2)
    assert not first.is_alive()
