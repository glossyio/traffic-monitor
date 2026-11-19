"""A camera's reference pictures: Frigate's current frame and the same view with its zone outlines, held in memory under
a ticket for a few minutes so that the pictures an admin looks at are the pictures saved, and the files they are saved
in.

Nothing here touches the disk or logs: the pictures, the ticket, and the place's point stay in memory and in answers to
the admin who took them. The picture and zip addresses carry the ticket, so `HideTickets` takes it out of uvicorn's
access log (`cli.serve` installs it). nginx's own access log still holds it, as it holds a download link's token.
"""

import io
import json
import logging
import re
import secrets
import threading
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from tm_control.modules.cameras.svg import reference_svg
from tm_control.modules.cameras.zones import ZoneFacts

NO_PLACE = "no-place"  # the stem's survey part when no place is in use
FORMAT = "traffic-monitor-reference"
FORMAT_VERSION = 1
_UNSAFE = re.compile(r"[^A-Za-z0-9_-]")
# A held picture's address: the camera's name, then the ticket. A camera's name never holds a slash (it is URL-encoded).
_TICKET_IN_PATH = re.compile(r"(/api/v1/cameras/[^/?\s]+/reference/)[^/?\s]+")


class HideTickets(logging.Filter):
    """Replaces the ticket in a uvicorn access record's path (its third argument) with "-". Other records pass as they
    are."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3 and isinstance(args[2], str):
            record.args = (*args[:2], _TICKET_IN_PATH.sub(r"\1-", args[2]), *args[3:])
        return True


@dataclass(frozen=True)
class Reference:
    ticket: str
    user_id: int
    camera: str  # the sensors.cameras key, never Frigate's name
    survey_id: str | None
    point: tuple[float, float] | None  # the place's exact lat, lon
    deployment_id: str | None
    clean: bytes
    zones_picture: bytes
    clean_at: float  # Unix seconds, when each answer arrived
    zones_at: float
    width: int  # the detect frame's
    height: int
    unit: Literal["m", "ft"]  # Frigate's unit system: metric or imperial
    zones: list[ZoneFacts]
    tm_version: str
    frigate_version: str | None
    expires: float  # on time.monotonic()'s clock


class References:
    """The reference pictures held in memory, under tickets. A ticket answers only the user who took it, until it
    expires. Each user holds one; the store holds at most LIMIT, so at most 2 * LIMIT frames are in memory."""

    TTL = 600.0  # seconds a take's pictures are held
    LIMIT = 2

    def __init__(self):
        self._held: dict[str, Reference] = {}  # ticket -> reference, oldest first
        self._lock = threading.Lock()

    def __len__(self) -> int:
        return len(self._held)

    def keep(self, now: float, **fields) -> Reference:
        """Hold a new take's pictures; drops the user's earlier take, every expired one, then the oldest past LIMIT."""
        kept = Reference(ticket=secrets.token_urlsafe(16), expires=now + self.TTL, **fields)
        with self._lock:
            for ticket in [t for t, old in self._held.items() if old.user_id == kept.user_id or now >= old.expires]:
                del self._held[ticket]
            while len(self._held) >= self.LIMIT:
                del self._held[next(iter(self._held))]
            self._held[kept.ticket] = kept
        return kept

    def get(self, ticket: str, user_id: int, now: float) -> Reference | None:
        with self._lock:
            held = self._held.get(ticket)
        if held is None or held.user_id != user_id or now >= held.expires:
            return None
        return held

    def drop(self, ticket: str, user_id: int) -> None:
        with self._lock:
            held = self._held.get(ticket)
            if held is not None and held.user_id == user_id:
                del self._held[ticket]


def jpeg_size(data: bytes) -> tuple[int, int] | None:
    """The width and height in a JPEG's frame header; None for truncated or malformed bytes."""
    if not data.startswith(b"\xff\xd8"):
        return None
    at = 2
    while at + 1 < len(data):
        if data[at] != 0xFF:
            return None
        marker = data[at + 1]
        if marker == 0xFF:  # fill byte before a marker
            at += 1
            continue
        if 0xD0 <= marker <= 0xD9 or marker == 0x01:  # no length
            if marker == 0xD9:  # end of the image, with no frame header before it
                return None
            at += 2
            continue
        if at + 4 > len(data):
            return None
        length = int.from_bytes(data[at + 2:at + 4], "big")
        if length < 2:
            return None
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            if length < 7 or at + 9 > len(data):
                return None
            height = int.from_bytes(data[at + 5:at + 7], "big")
            width = int.from_bytes(data[at + 7:at + 9], "big")
            return (width, height) if width and height else None
        at += 2 + length
    return None


def _utc(when: float, layout: str) -> str:
    return datetime.fromtimestamp(when, UTC).strftime(layout)


def iso(when: float) -> str:
    """Unix seconds as 2026-11-18T18:30:05Z."""
    return _utc(when, "%Y-%m-%dT%H:%M:%SZ")


def stem(reference: Reference) -> str:
    """The name the four files share: tm-reference_<survey id or no-place>_<camera>_<clean picture's UTC time>, with
    every character of the camera's key outside A-Z a-z 0-9 _ - replaced by _."""
    camera = _UNSAFE.sub("_", reference.camera)
    return f"tm-reference_{reference.survey_id or NO_PLACE}_{camera}_{_utc(reference.clean_at, '%Y%m%dT%H%M%SZ')}"


def data_file(reference: Reference, with_location: bool) -> dict:
    """The data file: the place, the camera, the pictures, the versions, the detect size, and every zone."""
    name = stem(reference)
    location = None
    if with_location and reference.point is not None:
        location = {"lat": reference.point[0], "lon": reference.point[1]}
    return {
        "format": FORMAT,
        "format_version": FORMAT_VERSION,
        "survey_id": reference.survey_id,
        "camera": reference.camera,
        "deployment_id": reference.deployment_id,
        "location": location,
        "pictures": {
            "clean": {"file": f"{name}_clean.jpg", "taken_at": iso(reference.clean_at)},
            "zones": {"file": f"{name}_zones.jpg", "taken_at": iso(reference.zones_at)},
            "drawing": {"file": f"{name}_zones.svg"},
        },
        "traffic_monitor_version": reference.tm_version,
        "frigate_version": reference.frigate_version,
        "detect": {"width": reference.width, "height": reference.height},
        "distance_unit": reference.unit,
        "zones": [zone.model_dump() for zone in reference.zones],
    }


def caption(reference: Reference) -> str:
    """The drawing's caption: the place, the camera, and the clean picture's time in UTC."""
    return (
        f"Traffic Monitor reference picture  ·  place {reference.survey_id or 'none'}  ·  camera {reference.camera}"
        f"  ·  {_utc(reference.clean_at, '%Y-%m-%d %H:%M:%S')} UTC"
    )


def package(reference: Reference, with_location: bool) -> bytes:
    """The zip of the four files, built in memory: the two pictures as they were taken (stored), the data file and
    the drawing (deflated), each dated with the clean picture's UTC time."""
    name = stem(reference)
    when = datetime.fromtimestamp(reference.clean_at, UTC).timetuple()[:6]
    data = json.dumps(data_file(reference, with_location), indent=2, ensure_ascii=False) + "\n"
    drawing = reference_svg(
        reference.clean, reference.width, reference.height, reference.zones, reference.unit, caption(reference)
    )
    entries = [
        (f"{name}_clean.jpg", reference.clean, zipfile.ZIP_STORED),
        (f"{name}_zones.jpg", reference.zones_picture, zipfile.ZIP_STORED),
        (f"{name}.json", data.encode("utf-8"), zipfile.ZIP_DEFLATED),
        (f"{name}_zones.svg", drawing.encode("utf-8"), zipfile.ZIP_DEFLATED),
    ]
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for filename, content, method in entries:
            info = zipfile.ZipInfo(filename, date_time=when)
            info.compress_type = method
            info.external_attr = 0o100644 << 16
            archive.writestr(info, content)
    return buffer.getvalue()
