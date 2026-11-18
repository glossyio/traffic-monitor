"""check_name: what the offline name check says about a name an operator typed."""

import pytest

from tm_control.modules.apps.name_check import ADDRESS_WORDS, KNOWN_WORDS, STREET_ABBREVIATIONS, check_name


@pytest.mark.parametrize("name", [
    "zone_north", "zone_lane_bus", "zone_capture", "zone_near", "zone_far", "zone_radar", "zone_2", "lane_12",
    "zone_a", "Zone_NORTH", "zone-north east", "zone_bus_lane", "zone_main_road", "crosswalk_north", "", "___",
    "zone_1st", "zone_2nd", "zone_3rd", "zone_4th", "zone_22ND",
])
def test_a_name_made_of_known_words_passes(name):
    assert check_name(name) is None


@pytest.mark.parametrize("name", [
    "zone_maple", "zone_nord", "zone_smith", "zone_bergstrasse", "зона_север", "zone_café", "北", "김", "李_家",
])
def test_a_word_the_lists_dont_know_is_a_note(name):
    assert check_name(name) == "unknown_word"


@pytest.mark.parametrize("name", [
    "zone_1420_oak_st", "zone_main_st", "zone_first_ave", "zone_oak_lane", "zone_berg_strasse", "zone_smiths_house",
    "john's_drive", "john’s_drive", "zone_100",
    "zone_1st_lane", "zone_5th_street", "zone_3rd_ave", "zone_100th", "lane_1st", "zone_1_st",
])
def test_what_looks_like_an_address_or_a_person_is_a_warning(name):
    assert check_name(name) == "pattern"


def test_the_lists_are_small_lower_case_and_apart():
    for words in (KNOWN_WORDS, ADDRESS_WORDS, STREET_ABBREVIATIONS):
        assert all(word.isalpha() and word == word.casefold() for word in words)
    assert 150 <= len(KNOWN_WORDS) <= 220
    assert not KNOWN_WORDS & ADDRESS_WORDS
    assert not STREET_ABBREVIATIONS & (KNOWN_WORDS | ADDRESS_WORDS)
