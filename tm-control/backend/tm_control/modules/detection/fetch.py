"""A Frigate+ model used by its ID: Frigate downloads the model while it validates a config whose `model:` path is
plus://<id>, so its save holds the answer for minutes. tm-control follows that save on a thread of its own and keeps
one record of it, which the Detection page reads.

Only a 200 or a 400 is Frigate's answer. Port 5000 is Frigate's own nginx, which gives up on a request after 6 minutes
and answers 504 while Frigate's save goes on downloading, then writes config.yml; a 502 means it lost Frigate. So after
no answer, a 502, or a 504 the save is followed by reading config.yml back until it holds the text sent, Frigate stops
answering, or WAIT has passed. Until then the record stays downloading, so a second save can't start beside it.

No message here holds Frigate's own text other than its refusal lines (redacted), and an exception is named by its
class only: either could hold a Frigate+ key.
"""

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Literal

from tm_control.adapters import frigate
from tm_control.modules.detection.picker import refusal_lines

log = logging.getLogger(__name__)

WAIT = 600  # seconds tm-control waits for Frigate's save, which holds the download
POLL = 5  # seconds between looks at config.yml while Frigate saves without an answer
State = Literal["downloading", "saved", "refused", "failed"]

TOO_LONG = ("Frigate didn't finish downloading the model in 10 minutes. Check the device's internet connection, then "
            "try again.")
STOPPED = "Frigate stopped before the download finished. Try again once Frigate is running."


@dataclass(frozen=True)
class Fetch:
    model_id: str
    state: State
    message: str | None  # for refused and failed


class Fetches:
    """The one download a device follows at a time, and how the last one ended. One per app; every method takes one
    lock."""

    def __init__(self):
        self._lock = threading.Lock()
        self._current: Fetch | None = None

    def current(self) -> Fetch | None:
        with self._lock:
            return self._current

    def downloading(self) -> bool:
        with self._lock:
            return self._current is not None and self._current.state == "downloading"

    def start(self, model_id: str) -> bool:
        """Record a new download; False, and nothing changes, while one is downloading."""
        with self._lock:
            if self._current is not None and self._current.state == "downloading":
                return False
            self._current = Fetch(model_id, "downloading", None)
            return True

    def finish(self, state: State, message: str | None = None) -> None:
        """End the download that runs; nothing when none does."""
        with self._lock:
            if self._current is not None and self._current.state == "downloading":
                self._current = replace(self._current, state=state, message=message)

    def clear(self) -> None:
        """Drop a finished record; a downloading one stays."""
        with self._lock:
            if self._current is not None and self._current.state != "downloading":
                self._current = None


def spawn(target: Callable[[], None]) -> None:
    threading.Thread(target=target, daemon=True).start()


def _follow(
    text: str, on_saved: Callable[[], None], clock: Callable[[], float], sleep: Callable[[float], None]
) -> tuple[State, str | None]:
    started = clock()
    status, message = frigate.save_config(text, timeout=WAIT)
    if status == 200:
        on_saved()
        return "saved", None
    if status == 400:
        lines = refusal_lines(message) if message else ""
        return "refused", f"Frigate refused the model: {lines}" if lines else "Frigate refused the model."
    if status not in (None, 502, 504):
        return "failed", f"Frigate answered {status} to the save."
    # Frigate validates, writes the file, then answers: the file holding exactly the text sent means it saved
    while True:
        raw = frigate.config_raw()
        if raw == text:
            on_saved()
            return "saved", None
        if raw is None:  # Frigate stopped or is restarting, and its save with it
            return "failed", STOPPED
        if clock() - started >= WAIT - 5:
            return "failed", TOO_LONG
        sleep(POLL)


def wait(
    fetches: Fetches, text: str, on_saved: Callable[[], None], clock=time.monotonic, sleep=time.sleep
) -> None:
    """Send text as Frigate's config, wait for its answer (the download) or follow the save without one, call on_saved
    once it is saved, and record how it ended. Always ends the record: nothing it calls can leave it downloading."""
    state: State = "failed"
    message: str | None = "The download couldn't be followed."
    try:
        state, message = _follow(text, on_saved, clock, sleep)
    except Exception as error:
        name = type(error).__name__
        log.warning("A Frigate+ model's download couldn't be followed: %s", name)
        message = f"The download couldn't be followed: {name}"
    finally:
        fetches.finish(state, message)
