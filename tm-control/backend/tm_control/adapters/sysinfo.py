"""Readings of the host: model, OS, uptime, memory, storage, SoC temperature, the firmware's throttling flags, and
timedatectl's time state.

Each function returns None when its source can't be read or parsed, except that throttled() raises NeedsVideoGroup
when vcgencmd can't open the firmware's device, so the device checks can say how to fix it.
"""

import os
import platform
import shutil
from pathlib import Path

from tm_control.adapters.command import run

MODEL_PATH = Path("/proc/device-tree/model")
OS_RELEASE_PATH = Path("/etc/os-release")
UPTIME_PATH = Path("/proc/uptime")
MEMINFO_PATH = Path("/proc/meminfo")
THERMAL_PATH = Path("/sys/class/thermal/thermal_zone0/temp")

PROBE_TIMEOUT = 4  # seconds; these are status probes
PROBE_MAX_OUTPUT = 16384

# vcgencmd get_throttled's bits: 0-3 are the state now, 16-19 the same conditions since boot
THROTTLED_FLAGS = ["under-voltage", "frequency-capped", "throttled", "soft-temperature-limit"]
SINCE_BOOT_SHIFT = 16


class NeedsVideoGroup(Exception):
    """vcgencmd couldn't open /dev/vcio_gencmd, which only root and the video group may."""


def _read(path: Path) -> str | None:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def model() -> str | None:
    """The board, such as "Raspberry Pi 5 Model B Rev 1.0", from the devicetree (which ends it with a NUL)."""
    text = _read(MODEL_PATH)
    return (text.strip("\x00 \n") or None) if text is not None else None


def os_release() -> str | None:
    """os-release's PRETTY_NAME, such as "Debian GNU/Linux 13 (trixie)"."""
    for line in (_read(OS_RELEASE_PATH) or "").splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip() == "PRETTY_NAME":
            return value.strip().strip("\"'") or None
    return None


def kernel() -> str | None:
    return platform.release() or None


def uptime_seconds() -> int | None:
    try:
        return int(float((_read(UPTIME_PATH) or "").split()[0]))
    except (IndexError, ValueError):
        return None


def memory() -> dict | None:
    """MemTotal and MemAvailable in bytes, as {"total", "available"}."""
    values = {}
    for line in (_read(MEMINFO_PATH) or "").splitlines():
        key, _, rest = line.partition(":")
        if key in ("MemTotal", "MemAvailable"):
            try:
                values[key] = int(rest.split()[0]) * 1024  # /proc/meminfo's kB are KiB
            except (IndexError, ValueError):
                return None
    if len(values) != 2:
        return None
    return {"total": values["MemTotal"], "available": values["MemAvailable"]}


def disk(path: str) -> dict | None:
    """The filesystem holding path: {"path", "total", "used", "free"} in bytes; free is what the code owner can use."""
    try:
        usage = shutil.disk_usage(path)
    except OSError:
        return None
    return {"path": path, "total": usage.total, "used": usage.used, "free": usage.free}


def filesystem(path: str) -> int | None:
    """The device number of the filesystem holding path, to tell whether two paths share one."""
    try:
        return os.stat(path).st_dev
    except OSError:
        return None


def soc_temperature_c() -> float | None:
    try:
        return int((_read(THERMAL_PATH) or "").strip()) / 1000
    except ValueError:
        return None


def _flags(bits: int) -> list[str]:
    return [name for bit, name in enumerate(THROTTLED_FLAGS) if bits & (1 << bit)]


def throttled() -> dict | None:
    """vcgencmd get_throttled as {"raw": "0x50000", "now": [...], "since_boot": [...]}, flags named as in
    THROTTLED_FLAGS. Raises NeedsVideoGroup when vcgencmd can't open the firmware's device; None on other failures
    (no vcgencmd, as on a laptop, a timeout, or output it doesn't recognize)."""
    try:
        result = run(["vcgencmd", "get_throttled"], timeout=PROBE_TIMEOUT, max_output=PROBE_MAX_OUTPUT)
    except OSError:
        return None
    if result.timed_out:
        return None
    if result.returncode != 0:
        output = f"{result.stdout}\n{result.stderr}"
        if "/dev/vcio" in output or "permission denied" in output.lower():
            raise NeedsVideoGroup()
        return None
    key, sep, value = result.stdout.strip().partition("=")
    if not sep or key != "throttled":
        return None
    try:
        bits = int(value, 16)
    except ValueError:
        return None
    return {"raw": hex(bits), "now": _flags(bits), "since_boot": _flags(bits >> SINCE_BOOT_SHIFT)}


def time_state() -> list[str] | None:
    """timedatectl show's Key=Value lines."""
    try:
        result = run(["timedatectl", "show"], timeout=PROBE_TIMEOUT, max_output=PROBE_MAX_OUTPUT)
    except OSError:
        return None
    if result.returncode != 0 or result.timed_out:
        return None
    return result.stdout.splitlines()
