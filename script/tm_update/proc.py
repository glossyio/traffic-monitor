"""The one function every outside command goes through, so a test can replace it."""

import os
import subprocess


def run(argv, *, env=None, log=None, check=False, timeout=None, cwd=None):
    """Run argv (a list, never a shell string) with stdin from /dev/null.

    With a log, stdout and stderr go to that open file, in order; without one they are captured as text (stdout,
    stderr). A command that is missing raises FileNotFoundError, one that takes too long TimeoutExpired, and a
    nonzero status with check=True CalledProcessError.
    """
    if not isinstance(argv, (list, tuple)) or not argv:
        raise TypeError("argv must be a list of arguments")
    command = [os.fspath(part) for part in argv]
    if log is not None:
        log.flush()
        return subprocess.run(command, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, env=env,
                              check=check, timeout=timeout, cwd=cwd)
    return subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True, text=True, errors="replace",
                          env=env, check=check, timeout=timeout, cwd=cwd)
