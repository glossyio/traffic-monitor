"""The poster: a background thread that gathers the setup snapshot and posts it to Node-RED when the control app
starts, whenever something wakes it (a model used, a camera entry saved), and every five minutes. After a snapshot that
couldn't be completed or posted it tries again in 30 seconds.

Nothing here logs a camera, a zone, a title, a profile, or a value: a failure is logged by its exception's class only,
once when it starts or its class changes (a warning) and once when it ends (info), never once per attempt. A failure is a
gather that raised or a post that failed; a snapshot that is merely incomplete (Frigate down) and posted fine is not one.
"""

import logging
import threading
import time
from collections.abc import Callable

from tm_control.modules.setup_history.snapshot import Snapshot

log = logging.getLogger(__name__)

INTERVAL = 300.0  # seconds to wait after a complete snapshot was accepted
RETRY = 30.0  # seconds to wait after one that wasn't complete or couldn't be posted


class Poster:
    def __init__(
        self,
        gather: Callable[[], Snapshot],
        post: Callable[[dict], None],
        interval: float = INTERVAL,
        retry: float = RETRY,
    ):
        self._gather = gather
        self._post = post
        self._interval = interval
        self._retry = retry
        self._stopped = threading.Event()
        self._lock = threading.Condition()  # guards everything below; the loop waits on it
        self._now = False  # a wake() came: the next wait ends at once
        self._soon: float | None = None  # a wake_soon()'s deadline (monotonic), set by the latest call
        self._thread: threading.Thread | None = None
        self._summary = {"gathered": False, "flagged": []}
        self._failure: str | None = None  # the class name of the failure last logged, until it ends

    def run_once(self) -> bool:
        """Gather a snapshot and post it, an incomplete one too. True only when a complete snapshot was accepted.
        Never raises: a failure counts as not done, and is logged by its class once (see _note)."""
        failure = None
        complete = False
        try:
            snapshot = self._gather()
            failure = snapshot.error
            with self._lock:
                complete = snapshot.body.get("complete") is True
                self._summary = {"gathered": complete, "flagged": list(snapshot.flagged) if complete else []}
            self._post(snapshot.body)
        except Exception as error:  # noqa: BLE001: the thread must go on; the text could name a camera
            failure = failure or type(error).__name__
            complete = False
        self._note(failure)
        return complete

    def _note(self, failure: str | None) -> None:
        """Log a failure's class when it starts or changes, and once when it ends. `failure` is the class name of
        this attempt's failure, or None when it went through."""
        with self._lock:
            before, self._failure = self._failure, failure
        if failure is not None and failure != before:
            log.warning("The setup snapshot failed: %s", failure)
        elif failure is None and before is not None:
            log.info("The setup snapshot works again (it had failed: %s)", before)

    def summary(self) -> dict:
        """What the last snapshot found, for the status report: whether it was whole, and which facts the name check
        flagged."""
        with self._lock:
            return {"gathered": self._summary["gathered"], "flagged": list(self._summary["flagged"])}

    def start(self) -> None:
        """Run the loop on one daemon thread; a second call does nothing."""
        with self._lock:
            if self._thread is not None:
                return
            self._thread = threading.Thread(target=self._loop, name="setup-poster", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        with self._lock:
            self._stopped.set()
            self._lock.notify_all()

    def wake(self) -> None:
        """End the current wait, so the next snapshot is made now."""
        with self._lock:
            self._now = True
            self._lock.notify_all()

    def wake_soon(self) -> None:
        """End the current wait after the retry delay, so the next snapshot is made then. For a change that only queued
        a restart: a snapshot right now could still see the old state. A wake() or stop() in the meantime still ends the
        wait at once (the deadline is kept for the wait after it). A second call while one is pending moves the deadline
        to the retry delay after it: each caller wants its snapshot no sooner than that after its own change."""
        with self._lock:
            self._soon = time.monotonic() + self._retry
            self._lock.notify_all()

    def _wait(self, seconds: float) -> None:
        with self._lock:
            end = time.monotonic() + seconds
            while not self._now and not self._stopped.is_set():
                target = end if self._soon is None else min(end, self._soon)
                remaining = target - time.monotonic()
                if remaining <= 0:
                    break
                self._lock.wait(remaining)
            self._now = False
            if self._soon is not None and time.monotonic() >= self._soon:
                self._soon = None  # its snapshot is due; a wait that ended for another reason keeps it

    def _loop(self, wait: Callable[[float], None] | None = None) -> None:
        wait = wait or self._wait
        while not self._stopped.is_set():
            ok = self.run_once()
            if self._stopped.is_set():
                break
            wait(self._interval if ok else self._retry)
