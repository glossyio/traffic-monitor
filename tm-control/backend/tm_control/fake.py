"""Fake mode (TM_CONTROL_FAKE=1), for running and reviewing the control app on a laptop without a Pi.

`tm-control fake-reset` starts the fake device over, unclaimed, and prints its new setup code. `tm-control
dump-openapi` prints the API's OpenAPI document, from which the UI's client is typed (tm-control/ui/src/api/).
Neither needs a device's secrets, manifest, or state.
"""

import tempfile
from pathlib import Path

from tm_control.core.auth import Device, SetupCode
from tm_control.core.claim_cli import CommandError
from tm_control.core.settings import EULA_PATH, FAKE_MANIFEST, Settings
from tm_control.core.state import State

STATE_FILES = ("state.sqlite", "state.sqlite-wal", "state.sqlite-shm")


def reset(settings: Settings) -> int:
    """Delete the fake device's state database, create a fresh one, and print a new setup code for it."""
    if not settings.fake:
        raise CommandError("fake-reset only works in fake mode: set TM_CONTROL_FAKE=1.", exit_code=2)
    for name in STATE_FILES:
        (settings.state_dir / name).unlink(missing_ok=True)
    settings.state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    state = State(settings.state_dir / "state.sqlite")
    state.migrate()
    code = SetupCode.generate()
    Device(state).set_setup_code_hash(SetupCode.hash_code(code))
    print(f"Fake device reset in {settings.state_dir}. Setup code: {code}")
    print("Restart `tm-control serve` if it's running, then open the UI's /setup page.")
    return 0


def openapi_document() -> dict:
    """The app's OpenAPI document, from an app built in fake mode with throwaway state."""
    from tm_control.app import create_app  # here, like cli.py's imports, so `migrate` doesn't need FastAPI

    with tempfile.TemporaryDirectory(prefix="tm-control-openapi-") as tmp:
        root = Path(tmp)
        settings = Settings(
            state_dir=root / "state",
            runtime_dir=root / "run",
            secrets_dir=root / "secrets",
            manifest_path=FAKE_MANIFEST,
            host="127.0.0.1",
            port=0,
            fake=True,
            eula_path=EULA_PATH,
            setup_code_file=root / "setup-code",
        )
        return create_app(settings).openapi()
