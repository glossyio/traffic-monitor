"""What Frigate was tracking on a camera around a reference picture's two frames: the control app asks Node-RED (which
asks Frigate) before the first frame and after the second, and says in the take's answer and in the data file whether a
person was listed.

The check blocks nothing: a question that gets no list, whatever the reason, leaves that part of the answer unknown.
Frigate lists an object only once it is confident of it, and only while its detection is on for the camera. Nothing
here logs: no list, label, or count reaches a log line, an audit row, or an error message.
"""

from typing import Literal

from tm_control.adapters.nodered import NodeRedError

PERSON = "person"  # Frigate's label; "person-verified" reaches here already without its suffix
Result = Literal["seen", "none", "unchecked"]


def ask(nodered, camera: str) -> list[dict] | None:
    """The objects Frigate is tracking on the camera (its sensors.cameras key) now, or None when there is no list to
    trust, Node-RED refuses, or it doesn't answer. Logs nothing."""
    try:
        return nodered.tracked(camera)
    except NodeRedError:
        return None


def _has_person(objects: list[dict] | None) -> bool:
    return any(one.get("label") == PERSON for one in objects or ())


def facts(before: list[dict] | None, after: list[dict] | None) -> dict:
    """The data file's `objects` block. `person` is true when either list holds a person, false when both are lists
    and neither does, and null otherwise; `checked` is true when both are lists."""
    checked = before is not None and after is not None
    if _has_person(before) or _has_person(after):
        person: bool | None = True
    else:
        person = False if checked else None
    return {"checked": checked, "before": before, "after": after, "person": person}


def result(objects: dict) -> Result:
    """The take's answer for an `objects` block."""
    person = objects["person"]
    return "unchecked" if person is None else "seen" if person else "none"
