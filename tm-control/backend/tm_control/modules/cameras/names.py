"""The neutral camera name: the sensors.cameras key that tmdb records and the unit shares, in place of Frigate's own
name for the camera.

A name is camera_<N>_<6 hex>, for example camera_1_3fa9c2. N is only there for people (which of two cameras is
which); the six random hex characters are the identity, so a name is never handed out twice on a unit. Letters,
digits, and underscores only, because the flows read cameras by dotted path.
"""

import re
import secrets
from collections.abc import Callable, Iterable

NEUTRAL = re.compile(r"camera_([1-9][0-9]*)_[0-9a-f]{6}")


def is_neutral(name: str) -> bool:
    return NEUTRAL.fullmatch(name) is not None


def new_name(existing: Iterable[str], token: Callable[[int], str] = secrets.token_hex) -> str:
    """A neutral name for a new camera: N one above the highest among the existing neutral names (1 when there are
    none), and a token(3) that no existing neutral name already ends with."""
    neutral = [match for name in existing if (match := NEUTRAL.fullmatch(name))]
    number = max((int(match[1]) for match in neutral), default=0) + 1
    taken = {match[0][-6:] for match in neutral}
    while (drawn := token(3)) in taken:
        pass
    return f"camera_{number}_{drawn}"
