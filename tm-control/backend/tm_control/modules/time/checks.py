"""The time check group: whether the device's clock can be right, and where its time comes from."""

from datetime import datetime

from tm_control.adapters import timedate
from tm_control.core.checks import Check, CheckGroup, Context, Fix

# Before this, the clock was never set: a Pi keeps no time while it's off unless it has an RTC battery.
# POST /time refuses an earlier time too.
FLOOR = datetime.fromisoformat("2026-01-01T00:00:00Z")
SET_IT = Fix(kind="link", text="Set the date and time", href="/time")


def clock(context: Context) -> list[Check]:
    def check(status, detail, fix=None):
        return [Check(id="time.plausible", title="Clock", status=status, detail=detail, fix=fix)]

    state = timedate.show()
    if state is None:
        return check("unknown", "The device's date and time couldn't be read.")
    if datetime.fromisoformat(state.device_time) < FLOOR:
        return check("error", "The clock is wrong; set it on the Date and time page.", SET_IT)
    if state.ntp.enabled and not state.ntp.synchronized:
        return check("warn", "No time source reachable (offline?); the clock runs on its own.", SET_IT)
    if not state.ntp.enabled:
        return check("ok", "Set by hand.")
    return check("ok", "Synchronized.")


GROUP = CheckGroup("time", "Date and time", [clock])
