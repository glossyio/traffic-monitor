"""The offline check of a name an operator typed, such as a Frigate zone's, which is saved with every event and shared
with the data.

It warns and never blocks: the name stays as typed. It works from two hand-written lists, so it needs no network and no
dependency. It can't know whether a word is a street's name, so a word the lists don't know is only a note
("unknown_word"); a name is a warning ("pattern") only when its shape looks like an address or a person's name.
"""

import re
from typing import Literal

# The words a zone is usually named with: places on a road, directions, what moves, and a few small words.
KNOWN_WORDS = frozenset("""
zone zones area areas region section segment side sides part line lines point spot box strip edge corner center centre
middle mid whole half full
capture radar near far
north south east west northeast northwest southeast southwest ne nw se sw northbound southbound eastbound westbound
nb sb eb wb
left right top bottom upper lower front back rear inner outer inside outside in out inbound outbound entry exit enter
leave start end first second third last main this that other both all across opposite
lanes roads roadway sidewalk pavement footpath path crosswalk crossing zebra intersection junction roundabout curb kerb
shoulder median island verge driveway entrance parking parked bay stop sign signal light lights yield turn turning merge
ramp bridge tunnel track tracks rail tram busway bikeway cycleway greenway shared mixed travel traffic through thru
oncoming direction flow
car cars truck trucks lorry van vans bus buses bike bikes bicycle bicycles motorcycle motorbike scooter person people
pedestrian pedestrians ped peds cyclist cyclists vehicle vehicles rider riders
count counting counter model speed slow fast test temp new old one two three four five six and or of the to from at on by for
with no not school loading delivery taxi
""".split())

# The words of an address: a street's kind, in English and a few other languages, and the words for a home.
ADDRESS_WORDS = frozenset("""
street road lane way drive avenue boulevard court place square circle terrace highway parkway alley trail route row
close crescent grove hill park plaza house home residence apartment flat unit suite building number
strasse weg gasse platz allee rue chemin calle avenida via viale straat laan gata vej
""".split())

# A street's kind, shortened: no zone is named with these but an address.
STREET_ABBREVIATIONS = frozenset("""
st ave av rd blvd dr ln ct pl hwy pkwy cir ter sq trl rte str apt bldg
""".split())

# An ordinal (5th) as one word, then runs of letters (any script) and runs of digits.
_WORDS = re.compile(r"\d+(?:st|nd|rd|th)(?![^\W\d_])|[^\W\d_]+|\d+")
_NUMBER = re.compile(r"(\d+)(st|nd|rd|th)?")  # a number or an ordinal: its digits, and its suffix if any
_APOSTROPHES = ("'", "’")


def _number(word: str) -> re.Match[str] | None:
    return _NUMBER.fullmatch(word)


def _known(word: str) -> bool:
    if number := _number(word):
        return len(number[1]) <= 2
    # A single letter is known only in ASCII: one character of another script can be a whole word or a name.
    return (len(word) == 1 and word.isascii()) or word in KNOWN_WORDS or word in ADDRESS_WORDS


def _words(name: str) -> list[str]:
    return _WORDS.findall(name.casefold())


def check_name(name: str) -> Literal["unknown_word", "pattern"] | None:
    """"pattern" when the name looks like an address or a person's name: a number or an ordinal of three or more
    digits, an apostrophe, a shortened street kind, or an address word together with a word the lists don't know or
    an ordinal (5th). Otherwise "unknown_word" when a word isn't in the lists, and None when every word is."""
    words = _words(name)
    numbers = [number for word in words if (number := _number(word))]
    unknown = [word for word in words if not _known(word)]
    if (
        any(len(number[1]) >= 3 for number in numbers)
        or any(mark in name for mark in _APOSTROPHES)
        or any(word in STREET_ABBREVIATIONS for word in words)
        or (
            (unknown or any(number[2] for number in numbers))
            and any(word in ADDRESS_WORDS for word in words)
        )
    ):
        return "pattern"
    return "unknown_word" if unknown else None


def check_title(title: str) -> Literal["pattern"] | None:
    """"pattern" when a model's title looks like an address or a person's name: an apostrophe, a shortened street kind,
    or an address word together with a word that is neither a number nor known. A title is a made-up name, so an
    unknown word alone is nothing, and a number of any length is a size or a date."""
    words = _words(title)
    if (
        any(mark in title for mark in _APOSTROPHES)
        or any(word in STREET_ABBREVIATIONS for word in words)
        or (
            any(word in ADDRESS_WORDS for word in words)
            and any(not _number(word) and not _known(word) for word in words)
        )
    ):
        return "pattern"
    return None
