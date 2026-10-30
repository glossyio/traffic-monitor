"""Run a command: an argv list (never a shell), with a timeout and a cap on the output kept from each stream."""

import os
import signal
import subprocess
import threading
from collections.abc import Mapping
from dataclasses import dataclass

TRUNCATED = "\n[output truncated]"


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool


class _Capture:
    """Read a pipe to its end, keeping the first max_output bytes. Reading on keeps the command from blocking."""

    def __init__(self, stream, max_output):
        self.stream = stream
        self.max_output = max_output
        self.data = bytearray()
        self.truncated = False

    def drain(self):
        with self.stream:
            while chunk := self.stream.read1(65536):
                room = self.max_output - len(self.data)
                self.data += chunk[:room]
                self.truncated = self.truncated or len(chunk) > room

    def text(self):
        return self.data.decode("utf-8", errors="replace") + (TRUNCATED if self.truncated else "")


def _feed(stream, data):
    try:
        with stream:
            stream.write(data)
    except BrokenPipeError:
        pass  # the command exited without reading all of it


def run(
    argv: list[str],
    *,
    timeout: float = 30,
    max_output: int = 65536,
    input: bytes | None = None,
    env: Mapping[str, str] | None = None,
) -> CommandResult:
    """Run argv and wait at most timeout seconds; on timeout, kill it and everything it started.

    env adds to (or replaces) tm-control's own environment variables for this command. Output is decoded as UTF-8
    (bad bytes replaced). A missing program raises FileNotFoundError.
    """
    if isinstance(argv, (str, bytes)) or not argv:
        raise TypeError("run() takes a non-empty argv list, not a command string")
    process = subprocess.Popen(
        list(argv),
        stdin=subprocess.DEVNULL if input is None else subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,  # its own process group, so a timeout kills its children too
        env=None if env is None else {**os.environ, **env},
    )
    stdout, stderr = _Capture(process.stdout, max_output), _Capture(process.stderr, max_output)
    threads = [threading.Thread(target=capture.drain, daemon=True) for capture in (stdout, stderr)]
    if input is not None:
        threads.append(threading.Thread(target=_feed, args=(process.stdin, input), daemon=True))
    for thread in threads:
        thread.start()

    timed_out = False
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()
    for thread in threads:
        # A child that outlives the command can hold a pipe open; don't wait on it for long.
        thread.join(timeout=1)
    return CommandResult(process.returncode, stdout.text(), stderr.text(), timed_out)
