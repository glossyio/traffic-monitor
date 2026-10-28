"""The Device page's facts (GET /system/info): the host's readings, the install's versions, and its components."""

from typing import Literal

from pydantic import BaseModel

from tm_control import fake
from tm_control.adapters import sysinfo

Flag = Literal["under-voltage", "frequency-capped", "throttled", "soft-temperature-limit"]


class Memory(BaseModel):
    total: int  # bytes
    available: int


class Disk(BaseModel):
    path: str
    total: int  # bytes
    used: int
    free: int  # what tm-control's user may use


class TmInstall(BaseModel):
    version: str
    commit: str
    branch: str
    installing_user: str


class Throttled(BaseModel):
    raw: str  # vcgencmd's value, such as 0x50000
    now: list[Flag]
    since_boot: list[Flag]


class SystemInfo(BaseModel):
    hostname: str
    serial: str
    model: str | None
    os: str | None
    kernel: str | None
    uptime_seconds: int | None
    memory: Memory | None
    disks: list[Disk]  # / and the code directory, each when it could be read
    tm: TmInstall
    components: dict[str, str]  # component versions, from the manifest
    soc_temperature_c: float | None
    throttled: Throttled | None


def _throttled() -> dict | None:
    try:
        return sysinfo.throttled()
    except sysinfo.NeedsVideoGroup:
        return None  # the device checks say why


def system_info(app_state, hostname: str, serial: str) -> SystemInfo:
    manifest = app_state.manifest
    paths = list(dict.fromkeys(["/", manifest.codedir]))
    if app_state.settings.fake:
        readings = fake.system_info(paths)
    else:
        readings = {
            "model": sysinfo.model(),
            "os": sysinfo.os_release(),
            "kernel": sysinfo.kernel(),
            "uptime_seconds": sysinfo.uptime_seconds(),
            "memory": sysinfo.memory(),
            "disks": [usage for usage in map(sysinfo.disk, paths) if usage is not None],
            "soc_temperature_c": sysinfo.soc_temperature_c(),
            "throttled": _throttled(),
        }
    return SystemInfo(
        hostname=hostname,
        serial=serial,
        tm=TmInstall(
            version=manifest.tm_version,
            commit=manifest.git.commit,
            branch=manifest.git.branch,
            installing_user=manifest.installing_user,
        ),
        components=dict(manifest.components),
        **readings,
    )
