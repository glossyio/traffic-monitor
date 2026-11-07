"""Survey ids, rounding and pasted coordinates for the Location page.

Only the example coordinates allowed in this repo's tests appear here.
"""

import sqlite3

import pytest

from tm_control.modules.location import coordinates as c


def test_new_survey_id_matches_the_pattern():
    first, second = c.new_survey_id(), c.new_survey_id()
    assert c.SURVEY_ID.match(first)
    assert c.SURVEY_ID.match(second)
    assert first != second


def test_normalize_survey_id_folds_case():
    assert c.normalize_survey_id("3F9A1C2E-SI") == "3f9a1c2e-si"
    assert c.normalize_survey_id("3f9a1c2e-d") is None


@pytest.mark.parametrize("value", [None, "", 5, True, "3f9a1c2e", "3f9a1c2e-si\n"])
def test_normalize_survey_id_refuses_anything_else(value):
    assert c.normalize_survey_id(value) is None


def test_deployment_id_pattern():
    assert c.DEPLOYMENT_ID.match("1730000000-3f9a1c2e-d")
    assert not c.DEPLOYMENT_ID.match("3f9a1c2e-si")


@pytest.mark.parametrize(
    "value, expected",
    [
        (1, "1"),
        ("1", "1"),
        ("NONE", "none"),
        (2.0, "2"),
        ("2", "2"),
        # Anything else is refused.
        (True, None),
        (False, None),
        (1.5, None),
        (3, None),
        ("3", None),
        ("", None),
        (None, None),
        ([1], None),
    ],
)
def test_normalize_precision(value, expected):
    assert c.normalize_precision(value) == expected


@pytest.mark.parametrize(
    "value, expected",
    [("n", "n"), (" NE ", "ne"), ("", ""), (None, ""), ("  ", ""), ("up", None), ("north", None), (5, None)],
)
def test_normalize_bearing(value, expected):
    assert c.normalize_bearing(value) == expected


@pytest.mark.parametrize(
    "value, places, expected",
    [
        # Ties that are exact in binary round away from zero.
        (0.25, 1, 0.3),
        (-0.25, 1, -0.3),
        (1.25, 1, 1.3),
        (-1.25, 1, -1.3),
        # Not a tie in binary: 2.675 is stored a hair below 2.675, so it rounds down (as SQLite and toFixed do).
        (2.675, 2, 2.67),
        (-2.675, 2, -2.67),
        (45.55, 1, 45.5),
        (3, 1, 3.0),
        ("4.5", 0, 5.0),
        (-0.04, 1, 0.0),
    ],
)
def test_round_half_away(value, places, expected):
    result = c.round_half_away(value, places)
    assert isinstance(result, float)
    assert result == expected


@pytest.mark.parametrize("places", [1, 2])
@pytest.mark.parametrize("value", [0.25, -0.25, 1.25, -1.25, 2.675, 45.52252, -122.6912, 45.0, 0.05, -0.05, 45.55])
def test_stored_matches_sqlite_round(value, places):
    # stored() predicts what tmdb holds, so it must agree with the database's own ROUND.
    expected = sqlite3.connect(":memory:").execute("SELECT ROUND(?, ?)", (value, places)).fetchone()[0]
    assert c.round_half_away(value, places) == expected


def test_round_half_away_never_returns_negative_zero():
    assert str(c.round_half_away(-0.04, 1)) == "0.0"


def test_exact_quantises_to_five_places():
    assert c.exact("45.522525") == 45.52253  # half away from zero
    assert c.exact("-45.522525") == -45.52253
    assert c.exact(-122.691204) == -122.6912
    assert c.exact(45.52252) == 45.52252
    assert c.exact("") is None
    assert c.exact(None) is None


def test_exact_accepts_integers_and_trims_strings():
    assert c.exact(45) == 45.0
    assert c.exact(" 45.0 ") == 45.0


def test_exact_range_checks():
    for value, kind in ((91, "lat"), (-181, "lon"), ("north", "lat")):
        with pytest.raises(ValueError):
            c.exact(value, kind)
    assert c.exact(90, "lat") == 90.0
    assert c.exact(-180, "lon") == -180.0
    # Without a kind there is no range to check.
    assert c.exact(181) == 181.0


@pytest.mark.parametrize(
    "value",
    [float("nan"), float("inf"), float("-inf"), "nan", "NaN", "inf", "-Infinity", "1e999999999999", True, False, [1], {}],
)
def test_exact_refuses_non_finite_and_non_numbers(value):
    with pytest.raises(ValueError):
        c.exact(value)
    with pytest.raises(ValueError):
        c.exact(value, "lat")


def test_exact_error_messages_never_carry_the_value():
    for value, kind in ((91, "lat"), ("45,52252", "lat"), (-181, "lon"), ("nan", None)):
        with pytest.raises(ValueError) as excinfo:
            c.exact(value, kind)
        assert str(value) not in str(excinfo.value)
    with pytest.raises(ValueError, match="lat"):
        c.exact(91, "lat")


def test_stored_rounds_half_away_from_zero():
    assert c.stored(45.52252, -122.6912, "1") == (45.5, -122.7)
    assert c.stored(45.52252, -122.6912, "2") == (45.52, -122.69)
    assert c.stored(45.0, None, "2") == (None, None)
    assert c.stored(None, -122.0, "1") == (None, None)
    assert c.stored(45.0, -122.0, "none") == (None, None)
    assert c.stored(45.0, -122.0, "1") == (45.0, -122.0)


def test_stored_refuses_an_unknown_precision():
    with pytest.raises(ValueError):
        c.stored(45.0, -122.0, "3")


def test_parse_pair_accepts_comma_or_space():
    expected = (45.52252, -122.6912)
    assert c.parse_pair("45.52252, -122.69120") == expected
    assert c.parse_pair("45.52252 -122.69120") == expected
    assert c.parse_pair("45.52252,-122.69120") == expected
    assert c.parse_pair("  45.52252 ,  -122.69120  ") == expected
    assert c.parse_pair("+45.52252\t-122.69120") == expected
    assert c.parse_pair("45, -122") == (45.0, -122.0)


def test_parse_pair_quantises_and_range_checks():
    assert c.parse_pair("45.522525, -122.691204") == (45.52253, -122.6912)
    with pytest.raises(ValueError):
        c.parse_pair("-122.69120, 45.52252")  # wrong order fails the latitude range
    with pytest.raises(ValueError):
        c.parse_pair("45.52252, -181")


def test_parse_pair_refuses_a_decimal_comma():
    with pytest.raises(ValueError):
        c.parse_pair("45,52252 -122,69120")


@pytest.mark.parametrize(
    "text",
    ["", "   ", "45.52252", "45.52252, -122.6912, 7", "north, west", "45.52252; -122.6912", "1e1, 2", "nan, 1", "45.5. 2", ",", "45.52252,, -122.6912", None, 5],
)
def test_parse_pair_refuses_anything_else(text):
    with pytest.raises(ValueError):
        c.parse_pair(text)
