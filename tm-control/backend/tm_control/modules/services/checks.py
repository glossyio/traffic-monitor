"""The services check group: one check per Traffic Monitor unit, from its systemd state."""

from datetime import date

from tm_control.adapters import systemd
from tm_control.core.checks import Check, CheckGroup, Context, Fix
from tm_control.modules.services.units import Unit, active_since, restart_fix, restarts, unit_states, units_for


def _running(values: dict[str, str], today: date) -> str:
    since = active_since(values)
    if since is None:
        return "Running"
    if since.date() == today:
        return f"Running since {since:%H:%M}"
    return f"Running since {since:%Y-%m-%d %H:%M}"


def restarted_itself(context: Context, unit: Unit, count: int) -> bool:
    """Whether each of the unit's last `count` automatic restarts followed the exit it makes when it restarts itself,
    from PID 1's journal this boot (read once per report). False when the journal can't tell."""
    if unit.restarts_itself_with is None or context.settings.fake:
        return False
    exits = context.probe(f"services.restart_exits.{unit.unit}", lambda: systemd.automatic_restart_exits(unit.unit))
    if exits is None or len(exits) < count:
        return False
    return all(status == unit.restarts_itself_with for status in exits[-count:])


def unit_check(unit: Unit, values: dict[str, str] | None, today: date, context: Context) -> Check:
    def check(status, detail, fix=None):
        return Check(id=f"services.{unit.unit}", title=unit.title, status=status, detail=detail, fix=fix)

    restart = restart_fix(unit.unit)
    if values is None:
        return check("unknown", "Its state couldn't be read from systemd.")
    if values.get("LoadState") == "not-found":
        return check("error", "It isn't installed.", Fix(kind="hint", text="Run the installer (tmsetup.sh) again."))
    state = values.get("ActiveState", "")
    if state == "active":
        count = restarts(values)
        if count:
            times = "1 time" if count == 1 else f"{count} times"
            if restarted_itself(context, unit, count):
                return check("ok", f"{_running(values, today)}. It restarted itself {times}, as {unit.title} does "
                                   "when its config is saved.")
            return check("warn", f"{_running(values, today)}, but it restarted {times} after failures.", restart)
        return check("ok", f"{_running(values, today)}.")
    if state == "activating":
        if values.get("SubState") == "auto-restart":
            return check("warn", "Waiting to restart after a failure.")
        return check("warn", "Starting.")
    if state == "reloading":
        return check("warn", "Reloading.")
    if state == "deactivating":
        return check("warn", "Stopping.")
    if state == "inactive":
        return check("error", "Stopped.", restart)
    if state == "failed":
        return check("error", "Stopped after a failure.", restart)
    return check("unknown", "systemd reported a state tm-control doesn't know.")


def service_checks(context: Context) -> list[Check]:
    values = unit_states(context)
    today = date.today()
    return [unit_check(unit, values.get(unit.unit), today, context) for unit in units_for(context.manifest)]


GROUP = CheckGroup("services", "Services", [service_checks])
