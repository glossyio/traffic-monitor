"""Where tm-control keeps its files and where it listens, read from the environment that tm-control.service sets."""

import os
from dataclasses import dataclass
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parents[1]
# Fake mode (a dev machine, no device files) reads the test fixture unless TM_CONTROL_MANIFEST says otherwise.
FAKE_MANIFEST = PACKAGE_DIR.parent / "tests" / "fixtures" / "manifest.json"
# Fake mode's files, under the directory it runs in (the repo root's is in .gitignore), unless variables say otherwise
FAKE_DIR = ".tm-control-fake"
EULA_PATH = PACKAGE_DIR / "modules" / "setup" / "EULA.md"


def _systemd_directory(value):
    """The first path of a systemd STATE_DIRECTORY or RUNTIME_DIRECTORY value, which is colon-separated."""
    return value.split(":")[0] if value else None


def _bind(value):
    """Split host:port, as in 127.0.0.1:8090 or [::1]:8090."""
    host, _, port = value.rpartition(":")
    if not host or not port.isdigit():
        raise ValueError(f"TM_CONTROL_BIND must be host:port, not {value!r}")
    return host.removeprefix("[").removesuffix("]"), int(port)


@dataclass(frozen=True)
class Settings:
    state_dir: Path
    runtime_dir: Path
    secrets_dir: Path
    manifest_path: Path
    host: str
    port: int
    fake: bool
    eula_path: Path
    setup_code_file: Path  # the root-only copy of the setup code that tmsetup and reset-admin write

    @classmethod
    def from_env(cls, environ=None):
        env = os.environ if environ is None else environ
        fake = env.get("TM_CONTROL_FAKE") == "1"
        fake_dir = Path.cwd() / FAKE_DIR if fake else None
        state_dir = (
            env.get("TM_CONTROL_STATE_DIR")
            or _systemd_directory(env.get("STATE_DIRECTORY"))
            or (fake_dir / "state" if fake else "/var/lib/tm-control")
        )
        runtime_dir = (
            env.get("TM_CONTROL_RUNTIME_DIR")
            or _systemd_directory(env.get("RUNTIME_DIRECTORY"))
            or (fake_dir / "run" if fake else "/run/tm-control")
        )
        setup_code_file = env.get("TM_CONTROL_SETUP_CODE_FILE") or (
            fake_dir / "setup-code" if fake else "/etc/traffic-monitor/setup-code"
        )
        manifest = env.get("TM_CONTROL_MANIFEST") or (FAKE_MANIFEST if fake else "/etc/traffic-monitor/manifest.json")
        host, port = _bind(env.get("TM_CONTROL_BIND") or "127.0.0.1:8090")
        return cls(
            state_dir=Path(state_dir),
            runtime_dir=Path(runtime_dir),
            secrets_dir=Path(env.get("TM_CONTROL_SECRETS_DIR") or "/etc/traffic-monitor/secrets"),
            manifest_path=Path(manifest),
            host=host,
            port=port,
            fake=fake,
            eula_path=EULA_PATH,
            setup_code_file=Path(setup_code_file),
        )
