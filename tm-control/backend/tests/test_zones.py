from pathlib import Path

import pytest

from tm_control.modules.location import zones
from tm_control.modules.location.zones import ZONE_MAX, read_zone


@pytest.mark.parametrize("given, expected", [
    ("America/New_York", "America/New_York"),
    (" Europe/Berlin ", "Europe/Berlin"),
    ("Asia/Tokyo\n", "Asia/Tokyo"),
    ("UTC", "UTC"),
    ("Etc/GMT+5", "Etc/GMT+5"),
    ("America/Argentina/Buenos_Aires", "America/Argentina/Buenos_Aires"),
    (None, None),
    ("", None),
    ("   ", None),
    (5, None),
    (True, None),
    (["Asia/Tokyo"], None),
    ("not a zone!", None),
    ("../../etc/passwd", None),
    ("a/b/c/d", None),
    ("/Asia/Tokyo", None),
    ("Asia/Tokyo/", None),
    ("Asia//Tokyo", None),
    ("Mars/Olympus", "Mars/Olympus"),  # the shape only: whether the device lists a name is the API's check
    ("America/" + "x" * 56, "America/" + "x" * 56),
    ("America/" + "x" * 57, None),
    ("\x1cAsia/Tokyo", None),  # not whitespace to JavaScript's trim
    ("\ufeffAsia/Tokyo", "Asia/Tokyo"),  # whitespace to JavaScript's trim
])
def test_read_zone(given, expected):
    """A zone is trimmed text of 1 to 64 characters, one to three parts of letters, digits, _, +, or - joined by /;
    anything else is none. It never raises."""
    assert read_zone(given) == expected


def test_the_longest_zone_is_64_characters():
    assert ZONE_MAX == 64
    assert read_zone("a" * 64) == "a" * 64
    assert read_zone("a" * 65) is None


def test_trimmed_is_exactly_what_javascript_trims():
    """The code points of String.prototype.trim: white space and line terminators."""
    expected = {0x9, 0xA, 0xB, 0xC, 0xD, 0x20, 0xA0, 0x1680, *range(0x2000, 0x200B), 0x2028, 0x2029, 0x202F, 0x205F,
                0x3000, 0xFEFF}
    assert {ord(char) for char in zones._TRIMMED} == expected
    assert len(zones._TRIMMED) == len(expected)


def test_the_source_has_no_character_above_ascii():
    """_TRIMMED is written as escapes, so no invisible character hides in the file."""
    text = Path(zones.__file__).read_text(encoding="utf-8")
    assert [hex(ord(char)) for char in text if ord(char) > 0x7F] == []
