"""Skip a test when the machine lacks a tool it needs, or fail it when TM_TESTS_REQUIRE_TOOLS=1.

A contributor's laptop may not have Podman, node, git, or a recent systemd, and the checks that need them skip there.
CI sets TM_TESTS_REQUIRE_TOOLS=1 (.github/workflows/tests.yml), so a runner that loses one of them fails the job
instead of passing with a check that didn't run (#303). Skips that depend on who runs the tests, such as root or not
root, aren't about a missing tool and stay plain skips.
"""

import functools
import os
import shutil

import pytest

REQUIRE_TOOLS = "TM_TESTS_REQUIRE_TOOLS"


def missing_tool(reason):
    """Skip with this reason, or fail with it when TM_TESTS_REQUIRE_TOOLS=1."""
    __tracebackhide__ = True  # report the test's line, not this one
    if os.environ.get(REQUIRE_TOOLS) == "1":
        pytest.fail(f"{reason} ({REQUIRE_TOOLS}=1, so a missing tool is a failure)", pytrace=False)
    pytest.skip(reason)


def needs(tool, reason=None):
    """Mark a test that runs `tool`: skipped where it isn't on PATH, or failed there when TM_TESTS_REQUIRE_TOOLS=1."""
    reason = reason or f"needs {tool}"
    missing = shutil.which(tool) is None
    if not (missing and os.environ.get(REQUIRE_TOOLS) == "1"):
        return pytest.mark.skipif(missing, reason=reason)

    def decorate(test):
        @functools.wraps(test)
        def wrapper(*args, **kwargs):
            missing_tool(reason)
        return wrapper
    return decorate
