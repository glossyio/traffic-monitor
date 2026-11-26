"""The one function every outside command goes through, so a test can replace it."""

import os
import signal
import subprocess
import time

# How long a command that ran out of time gets to end after the TERM, before the KILL
_GRACE = 10.0
_POLL = 0.05


class TimedOut(subprocess.TimeoutExpired):
    """A command ran past its limit and was ended with everything it started. It is a TimeoutExpired, so a caller
    that catches that (or SubprocessError) catches this too."""

    def __init__(self, argv0: str, seconds: float):
        super().__init__(argv0, seconds)
        self.seconds = seconds

    @property
    def detail(self) -> str:
        """The state file's detail for a step that ran out of time: its limit in whole minutes."""
        return f"timed out after {int(self.seconds // 60)} min"


def _signal_group(group: int, number: int) -> None:
    try:
        os.killpg(group, number)
    except ProcessLookupError:
        pass  # every process of the group has ended


def _group_alive(group: int) -> bool:
    try:
        os.killpg(group, 0)
    except ProcessLookupError:
        return False
    return True


def _end_group(child: subprocess.Popen) -> None:
    """TERM to the command's process group, up to _GRACE seconds for all of it to end, then KILL to what is left.

    The group's id is the command's pid, which stays taken while any process of the group is left, so the KILL
    can't reach anything else."""
    group = child.pid
    _signal_group(group, signal.SIGTERM)
    deadline = time.monotonic() + _GRACE
    while time.monotonic() < deadline:
        child.poll()  # a command that ended is reaped, or it would keep the group alive
        if not _group_alive(group):
            break
        time.sleep(_POLL)
    _signal_group(group, signal.SIGKILL)
    child.wait()


def run(argv, *, env=None, log=None, check=False, timeout=None, cwd=None):
    """Run argv (a list, never a shell string) with stdin from /dev/null, in a session of its own.

    With a log, stdout and stderr go to that open file, in order; without one they are captured as text (stdout,
    stderr). A command that is missing raises FileNotFoundError, and a nonzero status with check=True
    CalledProcessError. One that runs past its timeout is ended with every process of its session (TERM, then KILL
    after _GRACE seconds) and raises TimedOut; what it wrote to the log stays there.
    """
    if not isinstance(argv, (list, tuple)) or not argv:
        raise TypeError("argv must be a list of arguments")
    command = [os.fspath(part) for part in argv]
    if log is not None:
        log.flush()
        output = {"stdout": log, "stderr": subprocess.STDOUT}
    else:
        output = {"stdout": subprocess.PIPE, "stderr": subprocess.PIPE, "text": True, "errors": "replace"}
    # Its own session and process group, so a time-out ends what it started as well (Ansible's workers, pip's
    # builds), and nothing of it is left holding a lock or a file
    child = subprocess.Popen(command, stdin=subprocess.DEVNULL, env=env, cwd=cwd, start_new_session=True, **output)
    try:
        try:
            stdout, stderr = child.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            _end_group(child)
            raise TimedOut(command[0], timeout) from None
        except BaseException:
            # Interrupted (a KeyboardInterrupt, say): the command's session no longer gets the terminal's signals
            _end_group(child)
            raise
    finally:
        for stream in (child.stdout, child.stderr):
            if stream is not None:
                stream.close()
    if check and child.returncode:
        raise subprocess.CalledProcessError(child.returncode, command, stdout, stderr)
    return subprocess.CompletedProcess(command, child.returncode, stdout, stderr)
