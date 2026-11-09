"""The setup-code commands: `claim-status` and `set-setup-code` (run by tmsetup as the code owner) and
`reset-admin` (run by an operator with sudo).

Each one creates and migrates the state database first, so they work before tm-control.service has ever run. The
service's user owns state.sqlite and its -wal and -shm files, so a command run as root first drops to the owner of
the state directory; root never opens the database.
"""

import os
import pwd
import socket
import sys

from tm_control.core.auth import Audit, Device, SetupCode
from tm_control.core.settings import Settings
from tm_control.core.state import State


class CommandError(Exception):
    """A refusal: its message goes to stderr and the command exits with exit_code."""

    def __init__(self, message: str, exit_code: int = 1):
        super().__init__(message)
        self.exit_code = exit_code


def _state_owner(settings: Settings) -> pwd.struct_passwd:
    """The account that owns the state directory, which the service created. Root can't be it."""
    try:
        uid = os.stat(settings.state_dir).st_uid
    except FileNotFoundError:
        raise CommandError(f"{settings.state_dir} doesn't exist. Run the installer (tmsetup.sh) first.") from None
    if uid == 0:
        raise CommandError(
            f"{settings.state_dir} is owned by root, so tm-control.service didn't create it. "
            "Run the installer (tmsetup.sh) to repair it."
        )
    try:
        return pwd.getpwuid(uid)
    except KeyError:
        raise CommandError(f"{settings.state_dir} is owned by uid {uid}, which has no account.") from None


def open_state(settings: Settings) -> State:
    """The state database, created and migrated, opened as the state directory's owner when run as root."""
    if os.geteuid() == 0:
        owner = _state_owner(settings)
        os.setgroups([])
        os.setgid(owner.pw_gid)
        os.setuid(owner.pw_uid)
    settings.state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    state = State(settings.state_dir / "state.sqlite")
    state.migrate()
    return state


def claim_status(settings: Settings) -> int:
    print("claimed" if Device(open_state(settings)).is_claimed() else "unclaimed")
    return 0


def set_setup_code(settings: Settings) -> int:
    """Store the hash of the code on stdin (one line) while the device is unclaimed. Never prints the code."""
    device = Device(open_state(settings))
    if device.is_claimed():
        print("claimed")
        return 3
    code = SetupCode.normalize(sys.stdin.readline())
    if len(code) != 8 or any(c not in SetupCode.ALPHABET for c in code):
        raise CommandError("A setup code is 8 characters, letters and digits other than 0, O, 1, and I, as XXXX-XXXX.")
    device.set_setup_code_hash(SetupCode.hash_code(code))
    print("stored")
    return 0


def _write_code_file(path, code: str) -> None:
    """Write the code to a root-only file. Created 0600, and an existing file is made 0600 before the code goes in."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.fchmod(fd, 0o600)
        os.write(fd, f"{code}\n".encode("ascii"))
    finally:
        os.close(fd)


def reset_admin(settings: Settings, setup_code_file=None) -> int:
    """Delete every user and print a new setup code, for an operator who has lost the admin's password."""
    if os.geteuid() != 0:
        raise CommandError("reset-admin must run as root: sudo tm-control reset-admin", exit_code=2)
    _state_owner(settings)  # refuse before writing anything
    code = SetupCode.generate()
    _write_code_file(setup_code_file or settings.setup_code_file, code)  # as root, before the drop
    state = open_state(settings)
    Device(state).unclaim(SetupCode.hash_code(code))
    Audit(state).record(None, "reset-admin")
    print(f"Device unclaimed. Setup code: {code}")
    print(
        f"Open http://{socket.gethostname()}.local/setup (or the device's IP address followed by /setup) and enter "
        "the setup code to create the administrator account. The code works once."
    )
    return 0


def run(command, settings: Settings, **options) -> int:
    """Run one of the commands above, turning a CommandError into its message on stderr and its exit code."""
    try:
        return command(settings, **options)
    except CommandError as error:
        print(f"tm-control: {error}", file=sys.stderr)
        return error.exit_code
