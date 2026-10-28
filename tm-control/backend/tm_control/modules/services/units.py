"""The Traffic Monitor units that the Services list and the services checks show, and their state from systemd."""

from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel

from tm_control import fake
from tm_control.adapters import systemd
from tm_control.core.checks import Fix


@dataclass(frozen=True)
class Unit:
    unit: str
    title: str
    option: str | None = None  # the manifest option that installs it; None when every install has it
    restartable: bool = True  # tm-control can restart it (the unit is in tmsetup_tm_control_polkit)


# tm-control restarting itself is Cockpit's job, or the rescue console's; it isn't in the polkit list.
UNITS = [
    Unit("traffic-monitor.service", "Traffic Monitor pod"),
    Unit("frigate.service", "Frigate"),
    Unit("node-red-tm.service", "Node-RED"),
    Unit("plate-recognizer.service", "Plate Recognizer", option="plate_recognizer"),
    Unit("go2rtc_server.service", "Camera streams (go2rtc)"),
    Unit("revproxy.service", "Web proxy (nginx)"),
    Unit("tm-control.service", "Control app", restartable=False),
]

PROPERTIES = ["LoadState", "ActiveState", "SubState", "NRestarts", "ActiveEnterTimestamp", "InvocationID"]
RUNNING = ("active", "reloading")


def units_for(manifest) -> list[Unit]:
    """UNITS without those whose option the manifest says is off (or doesn't list)."""
    return [unit for unit in UNITS if unit.option is None or manifest.options.get(unit.option, False)]


def restart_fix(unit_name: str) -> Fix | None:
    """The restart fix for a unit in UNITS, worded for the UI's button ("Restart Frigate"); None if it can't be
    restarted from here. Any check whose cure is a unit's restart uses it, so every such button reads the same."""
    unit = next((unit for unit in UNITS if unit.unit == unit_name), None)
    if unit is None or not unit.restartable:
        return None
    return Fix(kind="restart", text=f"Restart {unit.title}", unit=unit.unit)


class Service(BaseModel):
    unit: str
    title: str
    active_state: str  # systemd's ActiveState, or "unknown" when it couldn't be read
    sub_state: str
    since: str | None  # while running: when it became active, ISO 8601 with the device's offset
    restarts: int  # NRestarts: restarts after failures since it was last started by hand
    restartable: bool


def read_units(settings, units: list[Unit]) -> dict[str, dict[str, str]]:
    """PROPERTIES of each unit from systemd, or fake mode's states; a unit that couldn't be read is left out."""
    show = fake.show_units if settings.fake else systemd.show_units
    return show([unit.unit for unit in units], PROPERTIES)


def active_since(values: dict[str, str]) -> datetime | None:
    """When a running unit became active, in the device's time zone; None when it isn't running or has no time."""
    raw = values.get("ActiveEnterTimestamp", "")
    if values.get("ActiveState") not in RUNNING or not raw.startswith("@"):
        return None
    try:
        seconds = int(raw[1:])
    except ValueError:
        return None
    return datetime.fromtimestamp(seconds).astimezone() if seconds > 0 else None


def restarts(values: dict[str, str]) -> int:
    try:
        return max(0, int(values.get("NRestarts", "")))
    except ValueError:
        return 0


def service(unit: Unit, values: dict[str, str] | None) -> Service:
    if values is None:
        return Service(
            unit=unit.unit,
            title=unit.title,
            active_state="unknown",
            sub_state="",
            since=None,
            restarts=0,
            restartable=unit.restartable,
        )
    since = active_since(values)
    return Service(
        unit=unit.unit,
        title=unit.title,
        active_state=values.get("ActiveState", ""),
        sub_state=values.get("SubState", ""),
        since=since.isoformat(timespec="seconds") if since else None,
        restarts=restarts(values),
        restartable=unit.restartable,
    )
