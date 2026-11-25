"""A place's time zone, by its shape: the rule for a value read from config.yml, and the one Node-RED's init config
defaults repeats (a test runs one table through both). Whether the device lists a name is the API's check, not this.

Standard library only, no I/O. Nothing here logs or raises with a value.
"""

import re

ZONE_MAX = 64  # characters, after trimming
_ZONE = re.compile(r"[A-Za-z0-9_+-]+(/[A-Za-z0-9_+-]+){0,2}")
# What JavaScript's String.prototype.trim removes, which Python's str.strip() doesn't match exactly (it also strips
# \x1c to \x1f and \x85, and keeps the byte order mark \ufeff). Written as escapes, so no invisible character
# hides here.
_TRIMMED = (
    "\t\n\v\f\r \xa0\u1680"
    "\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a"
    "\u2028\u2029\u202f\u205f\u3000\ufeff"
)


def read_zone(value) -> str | None:
    """The trimmed text when value is text of a zone name's shape (1 to 64 characters, one to three parts of letters,
    digits, _, +, or - joined by /), else None. A blank or whitespace-only string is None too. Never raises."""
    if not isinstance(value, str):
        return None
    text = value.strip(_TRIMMED)
    if 1 <= len(text) <= ZONE_MAX and _ZONE.fullmatch(text):
        return text
    return None
