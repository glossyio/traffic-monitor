"""Status checks: each module's check groups, run with a timeout per group, into the report behind GET /status.

A check function takes a Context and returns its Checks. Checks never raise: one that raises or doesn't finish in
time becomes a single `unknown` check that names the exception class or the timeout, never its message, which could
hold a command's output or a secret.
"""

import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import datetime
from typing import Any, Literal, NamedTuple, TypeVar

from pydantic import BaseModel

Status = Literal["ok", "warn", "error", "unknown"]
STATUSES: tuple[Status, ...] = ("ok", "warn", "error", "unknown")
TIMEOUT = 5.0  # seconds for each group, and so for a whole report: the groups run at the same time
TTL = 5.0  # seconds a report is reused before the checks run again

T = TypeVar("T")


class Fix(BaseModel):
    """What the UI offers for a check that isn't ok: restart a unit, check again, open a page, or a hint to read."""

    kind: Literal["restart", "rescan", "link", "hint"]
    text: str
    unit: str | None = None  # restart: the systemd unit
    href: str | None = None  # link: a path in tm-control's UI, such as /time


class Check(BaseModel):
    id: str
    title: str
    status: Status
    detail: str
    fix: Fix | None = None


class Group(BaseModel):
    id: str
    title: str
    checks: list[Check]


class Report(BaseModel):
    generated_at: str  # ISO 8601 with the device's offset, to the second
    summary: dict[Status, int]  # every status, 0 when no check has it
    groups: list[Group]


class Context:
    """What the check functions of one report share: the app's settings, manifest, and secrets, and probe results.

    `probe(key, fn)` runs fn once per report (a command's output, an app's status) for every check that asks for
    the same key; `probes` holds the results.
    """

    def __init__(self, settings, manifest, secrets):
        self.settings = settings
        self.manifest = manifest
        self.secrets = secrets
        self.probes: dict[str, Any] = {}
        self._errors: dict[str, Exception] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._locks_lock = threading.Lock()

    def probe(self, key: str, fn: Callable[[], T]) -> T:
        """fn's result, run by the first caller for this key; later callers wait for it, and an error is re-raised."""
        with self._locks_lock:
            lock = self._locks.setdefault(key, threading.Lock())
        with lock:
            if key in self._errors:
                raise self._errors[key]
            if key not in self.probes:
                try:
                    self.probes[key] = fn()
                except Exception as exc:
                    self._errors[key] = exc
                    raise
            return self.probes[key]


CheckFn = Callable[[Context], list[Check]]


class CheckGroup(NamedTuple):
    id: str
    title: str
    fns: list[CheckFn]


def _unknown(group: CheckGroup, fn: CheckFn, detail: str) -> Check:
    name = getattr(fn, "__name__", "check")
    return Check(id=f"{group.id}.{name}", title=name.replace("_", " ").capitalize(), status="unknown", detail=detail)


def run_group(group: CheckGroup, context: Context, timeout: float = TIMEOUT) -> Group:
    """Run the group's functions at the same time, each in a worker thread, and collect their checks in order.

    A function still running after `timeout` is left to finish on its own (the command runner's timeout bounds it).
    """
    checks: list[Check] = []
    pool = ThreadPoolExecutor(max_workers=max(1, len(group.fns)), thread_name_prefix=f"check-{group.id}")
    try:
        futures = [pool.submit(fn, context) for fn in group.fns]
        _, pending = wait(futures, timeout=timeout)
        for fn, future in zip(group.fns, futures):
            if future in pending:
                checks.append(_unknown(group, fn, f"The check didn't finish within {timeout:g} seconds."))
                continue
            try:
                result = future.result()
                if not isinstance(result, list) or not all(isinstance(check, Check) for check in result):
                    raise TypeError("a check function returns a list of Check")
            except Exception as exc:
                checks.append(_unknown(group, fn, f"The check failed ({type(exc).__name__})."))
            else:
                checks.extend(result)
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    return Group(id=group.id, title=group.title, checks=checks)


class StatusCache:
    """The status report, reused for `ttl` seconds so that page loads and polling don't re-run every probe."""

    def __init__(
        self,
        groups: list[CheckGroup],
        context_factory: Callable[[], Context],
        ttl: float = TTL,
        timeout: float = TIMEOUT,
    ):
        self.groups = list(groups)
        self.context_factory = context_factory
        self.ttl = ttl
        self.timeout = timeout
        self._lock = threading.Lock()  # one report at a time; requests that arrive meanwhile get its result
        self._report: Report | None = None
        self._at = 0.0

    def report(self, force: bool = False) -> Report:
        with self._lock:
            if not force and self._report is not None and time.monotonic() - self._at < self.ttl:
                return self._report
            context = self.context_factory()
            # Every group at once, so a hung app that several groups ask about costs one timeout, not one per group.
            with ThreadPoolExecutor(max_workers=max(1, len(self.groups)), thread_name_prefix="status") as pool:
                groups = list(pool.map(lambda group: run_group(group, context, self.timeout), self.groups))
            summary = dict.fromkeys(STATUSES, 0)
            for group in groups:
                for check in group.checks:
                    summary[check.status] += 1
            self._report = Report(
                generated_at=datetime.now().astimezone().isoformat(timespec="seconds"),
                summary=summary,
                groups=groups,
            )
            self._at = time.monotonic()
            return self._report
