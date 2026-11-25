"""Every path tm-update uses outside its own tree. One object, so a test can move the whole device under a folder."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Paths:
    root: Path = Path("/")

    def rooted(self, absolute: Path) -> Path:
        """An absolute path of the device, as it is under this object's root."""
        return self.root / str(absolute).lstrip("/")

    @property
    def update_dir(self) -> Path:
        return self.rooted(Path("/var/lib/traffic-monitor/update"))

    @property
    def lock(self) -> Path:
        return self.update_dir / "lock"

    @property
    def state(self) -> Path:
        return self.update_dir / "state.json"

    @property
    def log_dir(self) -> Path:
        return self.update_dir / "log"

    @property
    def work_root(self) -> Path:
        return self.update_dir / "work"

    @property
    def resume(self) -> Path:
        return self.update_dir / "resume.json"

    @property
    def restore_root(self) -> Path:
        return self.rooted(Path("/var/lib/traffic-monitor/restore"))

    @property
    def src_root(self) -> Path:
        return self.rooted(Path("/var/lib/traffic-monitor/src"))

    @property
    def venv_root(self) -> Path:
        return self.rooted(Path("/var/lib/traffic-monitor/venv"))

    @property
    def manifest(self) -> Path:
        return self.rooted(Path("/etc/traffic-monitor/manifest.json"))

    @property
    def secrets_dir(self) -> Path:
        return self.rooted(Path("/etc/traffic-monitor/secrets"))

    @property
    def reboot_required(self) -> Path:
        return self.rooted(Path("/var/run/reboot-required"))

    @property
    def boot_id(self) -> Path:
        return self.rooted(Path("/proc/sys/kernel/random/boot_id"))

    @property
    def tm_control_state(self) -> Path:
        return self.rooted(Path("/var/lib/tm-control/state.sqlite"))

    @property
    def plate_recognizer_unit(self) -> Path:
        return self.rooted(Path("/etc/containers/systemd/plate-recognizer.container"))
