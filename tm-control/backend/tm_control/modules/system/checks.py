"""The device check group: free storage, available memory, the SoC temperature, and the firmware's power and
throttling flags."""

from tm_control.adapters import sysinfo
from tm_control.core.checks import Check, CheckGroup, Context, Fix

GIB = 2**30
MIB = 2**20
STORAGE_WARN = 2 * GIB  # free bytes under which storage is a warn
STORAGE_ERROR = 512 * MIB  # and an error
MEMORY_WARN = 200 * MIB  # available bytes under which memory is a warn
TEMPERATURE_WARN = 80.0  # °C; the Pi 5 firmware starts to slow the processor down at 85 °C
TEMPERATURE_ERROR = 85.0

FREE_UP_SPACE = "Free up space, for example by keeping Frigate's recordings for fewer days."
COOLING = "Check the fan or heatsink, and keep the case out of direct sun."


def size(n: int) -> str:
    """Bytes for people, in the binary units that df -h and most file managers use."""
    return f"{n / GIB:.1f} GB" if n >= GIB else f"{n // MIB} MB"


def _storage_check(check_id: str, path: str, usage: dict | None) -> Check:
    def check(status, detail):
        return Check(id=check_id, title=f"Storage on {path}", status=status, detail=detail)

    if usage is None:
        return check("unknown", "Its free space couldn't be read.")
    free = f"{size(usage['free'])} free of {size(usage['total'])}"
    if usage["free"] < STORAGE_ERROR:
        return check("error", f"Only {free}, so recordings and new data may not be saved. {FREE_UP_SPACE}")
    if usage["free"] < STORAGE_WARN:
        return check("warn", f"Only {free}. {FREE_UP_SPACE}")
    return check("ok", f"{free}.")


def storage(context: Context) -> list[Check]:
    """The root filesystem, and the code directory too when it's on another one (such as an SSD)."""
    checks = [_storage_check("device.storage", "/", sysinfo.disk("/"))]
    codedir = context.manifest.codedir
    root, code = sysinfo.filesystem("/"), sysinfo.filesystem(codedir)
    if root is not None and code is not None and root != code:
        checks.append(_storage_check("device.storage.codedir", codedir, sysinfo.disk(codedir)))
    return checks


def memory(context: Context) -> list[Check]:
    def check(status, detail):
        return [Check(id="device.memory", title="Memory", status=status, detail=detail)]

    reading = sysinfo.memory()
    if reading is None:
        return check("unknown", "The memory in use couldn't be read.")
    available = f"{size(reading['available'])} of {size(reading['total'])} available"
    if reading["available"] < MEMORY_WARN:
        return check("warn", f"Only {available}, so apps may slow down or be stopped. Reboot the device to free it.")
    return check("ok", f"{available}.")


def temperature(context: Context) -> list[Check]:
    def check(status, detail):
        return [Check(id="device.temperature", title="Temperature", status=status, detail=detail)]

    celsius = sysinfo.soc_temperature_c()
    if celsius is None:
        return check("unknown", "The processor's temperature couldn't be read.")
    if celsius >= TEMPERATURE_ERROR:
        return check("error", f"{celsius:.1f} °C, so the processor is slowing itself down to cool off. {COOLING}")
    if celsius >= TEMPERATURE_WARN:
        return check("warn", f"{celsius:.1f} °C, close to where the processor slows itself down. {COOLING}")
    return check("ok", f"{celsius:.1f} °C.")


def _named(flags: list[str]) -> str:
    if len(flags) <= 2:
        return " and ".join(flags)
    return f"{', '.join(flags[:-1])}, and {flags[-1]}"


def _next_step(flags: list[str]) -> str:
    if "under-voltage" in flags:
        return "check the power supply and its cable"
    return "check the cooling and the power supply"


def power_supply(context: Context) -> list[Check]:
    def check(status, detail, fix=None):
        return [Check(id="device.power", title="Power supply and throttling", status=status, detail=detail, fix=fix)]

    try:
        flags = sysinfo.throttled()
    except sysinfo.NeedsVideoGroup:
        return check(
            "unknown",
            "tm-control can't read the firmware's power flags: it needs the video group.",
            Fix(kind="hint", text="Run the installer (tmsetup.sh) again."),
        )
    if flags is None:
        return check("unknown", "The firmware's power and throttling flags couldn't be read.")
    if flags["now"]:
        return check("error", f"{_named(flags['now']).capitalize()} now; {_next_step(flags['now'])}.")
    if flags["since_boot"]:
        since = _named(flags["since_boot"]).capitalize()
        return check("warn", f"{since} since the last boot, but not now; if it happens again, "
                             f"{_next_step(flags['since_boot'])}.")
    return check("ok", "No under-voltage or throttling since the last boot.")


GROUP = CheckGroup("device", "Device", [storage, memory, temperature, power_supply])
