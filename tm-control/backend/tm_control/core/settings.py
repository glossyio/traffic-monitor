"""Where tm-control keeps its files and where it listens, read from the environment that tm-control.service sets."""

import os
from dataclasses import dataclass
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parents[1]
# Fake mode (a dev machine, no device files) reads the test fixture unless TM_CONTROL_MANIFEST says otherwise.
FAKE_MANIFEST = PACKAGE_DIR.parent / "tests" / "fixtures" / "manifest.json"


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

    @classmethod
    def from_env(cls, environ=None):
        env = os.environ if environ is None else environ
        fake = env.get("TM_CONTROL_FAKE") == "1"
        state_dir = (
            env.get("TM_CONTROL_STATE_DIR") or _systemd_directory(env.get("STATE_DIRECTORY")) or "/var/lib/tm-control"
        )
        runtime_dir = (
            env.get("TM_CONTROL_RUNTIME_DIR") or _systemd_directory(env.get("RUNTIME_DIRECTORY")) or "/run/tm-control"
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
            eula_path=PACKAGE_DIR / "modules" / "setup" / "EULA.md",
        )
