"""The reference picture's drawing: the clean frame with each zone outlined and named, and a legend below it, as SVG.

It is written as text. Every string an operator typed (zone keys, and the caption with the camera's key) goes through
xml.sax.saxutils.escape, so a key with markup stays text. Sizes are for a frame 1536 wide and scale with its width.
"""

import base64
import math
from xml.sax.saxutils import escape

from tm_control.modules.cameras.zones import FALLBACK_COLOR, ZoneFacts

BASE_WIDTH = 1536
FOOTER = "Lettered corners are in the order Frigate stores them; every zone's corners are in the data file."
_ATTRIBUTE = {'"': "&quot;"}


def _px(value: float) -> str:
    return str(round(value))


def _attr(value: str) -> str:
    return escape(value, _ATTRIBUTE)


def _legend_detail(zone: ZoneFacts, unit: str) -> str:
    if not zone.enabled:
        return "  ·  off in Frigate, not drawn"
    if zone.sides:
        return "  ·  " + ", ".join(f"{side.start}–{side.end} {side.length:g} {unit}" for side in zone.sides)
    if not zone.drawn:
        return "  ·  no outline"
    return ""


def reference_svg(clean: bytes, width: int, height: int, zones: list[ZoneFacts], unit: str, caption: str) -> str:
    """The SVG for a clean frame of width by height pixels and the camera's zones, with caption in its title and its
    strip."""
    s = width / BASE_WIDTH
    strip = (62 + 40 * len(zones) + 44) * s
    total = height + strip
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {_px(total)}" width="{width}" '
        f'height="{_px(total)}" font-family="DejaVu Sans, Arial, Helvetica, sans-serif">',
        f"<style>.halo {{ paint-order: stroke; stroke: #fff; stroke-width: {_px(6 * s)}px; "
        "stroke-linejoin: round; }</style>",
        f"<title>{escape(caption)}</title>",
        f'<image href="data:image/jpeg;base64,{base64.b64encode(clean).decode()}" x="0" y="0" width="{width}" '
        f'height="{height}" preserveAspectRatio="none"/>',
    ]

    drawn = [zone for zone in zones if zone.drawn]
    lettered = [zone for zone in drawn if zone.sides]
    if not any(zone.sides for zone in zones):
        lettered = [zone for zone in drawn if len(zone.corners) == 4]

    names: list[tuple[float, float]] = []  # where each zone's name went
    for zone in drawn:
        color = _attr(zone.color or FALLBACK_COLOR)
        points = [(corner.x * width, corner.y * height) for corner in zone.corners]
        out.append(
            f'<polygon points="{" ".join(f"{_px(x)},{_px(y)}" for x, y in points)}" fill="{color}" '
            f'fill-opacity="0.10" stroke="{color}" stroke-width="{_px(4 * s)}" stroke-linejoin="round"/>'
        )
        cx = sum(x for x, _ in points) / len(points)
        cy = sum(y for _, y in points) / len(points)

        if zone in lettered:
            for corner, (x, y) in zip(zone.corners, points, strict=True):
                out.append(
                    f'<circle cx="{_px(x)}" cy="{_px(y)}" r="{_px(6 * s)}" fill="{color}" stroke="#fff" '
                    f'stroke-width="{_px(2 * s)}"/>'
                )
                dx, dy = cx - x, cy - y
                reach = math.hypot(dx, dy) or 1.0
                lx, ly = x + dx / reach * 34 * s, y + dy / reach * 34 * s
                out.append(
                    f'<text class="halo" x="{_px(lx)}" y="{_px(ly)}" font-size="{_px(24 * s)}" font-weight="bold" '
                    f'text-anchor="middle" dominant-baseline="central" fill="{color}">{escape(corner.letter)}</text>'
                )

        ny = cy
        while any(abs(ny - py) < 34 * s and abs(cx - px) < 240 * s for px, py in names):
            ny += 34 * s
        names.append((cx, ny))
        out.append(
            f'<text class="halo" x="{_px(cx)}" y="{_px(ny)}" font-size="{_px(26 * s)}" text-anchor="middle" '
            f'dominant-baseline="central" fill="{color}">{escape(zone.key)}</text>'
        )

    out.append(f'<rect x="0" y="{height}" width="{width}" height="{_px(strip)}" fill="#fff"/>')
    out.append(
        f'<text x="{_px(40 * s)}" y="{_px(height + 34 * s)}" font-size="{_px(22 * s)}" fill="#000">'
        f"{escape(caption)}</text>"
    )
    for i, zone in enumerate(zones):
        y = height + (80 + 40 * i) * s
        color = _attr(zone.color or FALLBACK_COLOR)
        out.append(
            f'<rect x="{_px(40 * s)}" y="{_px(y - 20 * s)}" width="{_px(34 * s)}" height="{_px(26 * s)}" '
            f'fill="{color}"/>'
        )
        out.append(
            f'<text x="{_px(86 * s)}" y="{_px(y)}" font-size="{_px(22 * s)}" fill="#000">'
            f'<tspan font-weight="bold">{escape(zone.key)}</tspan>'
            f"<tspan>{escape(_legend_detail(zone, unit))}</tspan></text>"
        )
    out.append(
        f'<text x="{_px(40 * s)}" y="{_px(total - 14 * s)}" font-size="{_px(18 * s)}" fill="#555">{FOOTER}</text>'
    )
    out.append("</svg>")
    return "\n".join(out) + "\n"
