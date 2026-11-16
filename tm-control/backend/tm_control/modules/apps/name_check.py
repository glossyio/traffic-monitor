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
count counting counter speed slow fast test temp new old one two three four five six and or of the to from at on by for
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

_WORDS = re.compile(r"[^\W\d_]+|\d+")  # runs of letters (any script) and runs of digits
_APOSTROPHES = ("'", "’")


def _known(word: str) -> bool:
    if word.isdigit():
        return len(word) <= 2
    # A single letter is known only in ASCII: one character of another script can be a whole word or a name.
    return (len(word) == 1 and word.isascii()) or word in KNOWN_WORDS or word in ADDRESS_WORDS


def check_name(name: str) -> Literal["unknown_word", "pattern"] | None:
    """"pattern" when the name looks like an address or a person's name: a number of three or more digits, an
    apostrophe, a shortened street kind, or an address word beside a word the lists don't know. Otherwise
    "unknown_word" when a word isn't in the lists, and None when every word is."""
    words = _WORDS.findall(name.casefold())
    unknown = [word for word in words if not _known(word)]
    if (
        any(word.isdigit() and len(word) >= 3 for word in words)
        or any(mark in name for mark in _APOSTROPHES)
        or any(word in STREET_ABBREVIATIONS for word in words)
        or (unknown and any(word in ADDRESS_WORDS for word in words))
    ):
        return "pattern"
    return "unknown_word" if unknown else None
