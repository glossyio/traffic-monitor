"""Run the system-password job for its tests, with stand-in accounts and never as root.

Usage: python -I run_job.py JOB REQUEST. TEST_ACCOUNTS, a JSON object of name to uid, adds accounts that
pwd.getpwnam finds before the machine's own, so a test can name an installing user this machine doesn't have, or one
that maps to uid 0. os.geteuid reports a non-root uid, so the job runs the CHPASSWD stand-in even when the suite runs
as root. The job itself is unchanged: this only patches the process it runs in.
"""

import json
import os
import pwd
import runpy
import sys

ACCOUNTS = json.loads(os.environ.get("TEST_ACCOUNTS") or "{}")
real_getpwnam = pwd.getpwnam


def getpwnam(name):
    if name in ACCOUNTS:
        uid = ACCOUNTS[name]
        return pwd.struct_passwd((name, "x", uid, uid, "", f"/home/{name}", "/bin/sh"))
    return real_getpwnam(name)


pwd.getpwnam = getpwnam
os.geteuid = lambda: 65534
sys.argv = sys.argv[1:]
runpy.run_path(sys.argv[0], run_name="__main__")
