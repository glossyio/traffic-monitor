"""The clocks a kept picture is timed by: the boot id (which power-on), the boot clock (seconds since it began, which
a wall clock's jump doesn't move and a restart of the control app doesn't reset), and the wall clock."""

import time
from pathlib import Path

BOOT_ID = Path("/proc/sys/kernel/random/boot_id")


class Clock:
    """The device's clocks. Fake mode on a machine with no boot id or no boot clock uses the id "fake" and
    time.monotonic()."""

    def __init__(self, fake: bool = False):
        self._fake = fake
        self._boot_id: str | None = None

    def boot_id(self) -> str:
        if self._boot_id is None:  # read once: it is the same for the whole power-on
            try:
                self._boot_id = BOOT_ID.read_text().strip()
            except OSError:
                if not self._fake:
                    raise
                self._boot_id = "fake"
        return self._boot_id

    def boot(self) -> float:
        boottime = getattr(time, "CLOCK_BOOTTIME", None)
        if boottime is None and self._fake:
            return time.monotonic()
        return time.clock_gettime(boottime)

    def wall(self) -> float:
        return time.time()


class ManualClock(Clock):
    """A clock that answers what a test set."""

    def __init__(self, boot_id: str = "manual", boot: float = 0.0, wall: float = 0.0):
        super().__init__()
        self.set(boot_id=boot_id, boot=boot, wall=wall)

    def set(self, *, boot_id: str | None = None, boot: float | None = None, wall: float | None = None) -> None:
        if boot_id is not None:
            self._id = boot_id
        if boot is not None:
            self._boot = boot
        if wall is not None:
            self._wall = wall

    def advance(self, seconds: float) -> None:
        """Move the boot clock and the wall clock on together."""
        self._boot += seconds
        self._wall += seconds

    def boot_id(self) -> str:
        return self._id

    def boot(self) -> float:
        return self._boot

    def wall(self) -> float:
        return self._wall
