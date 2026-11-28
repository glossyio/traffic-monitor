"""The reference picture's people check: what Frigate was tracking on the camera before the first picture and after
the second, and what the data file and the take's answer say of it."""

import logging

import pytest

from tm_control.adapters.nodered import NodeRedError
from tm_control.modules.cameras import people

CAR = {"label": "car", "stationary": True}
WALKER = {"label": "person", "stationary": False}


@pytest.mark.parametrize("before, after, checked, person", [
    ([CAR], [CAR], True, False),
    ([], [], True, False),
    ([CAR], [CAR, WALKER], True, True),
    ([WALKER], [], True, True),
    ([WALKER], None, False, True),
    ([CAR], None, False, None),
    (None, None, False, None),
])
def test_facts(before, after, checked, person):
    assert people.facts(before, after) == {"checked": checked, "before": before, "after": after, "person": person}
    assert list(people.facts(before, after)) == ["checked", "before", "after", "person"]


def test_a_person_standing_still_is_a_person():
    still = {"label": "person", "stationary": True}
    assert people.facts([still], [still])["person"] is True


@pytest.mark.parametrize("label", ["person-verified", "Person", "unknown", "persons", ""])
def test_only_the_label_person_counts(label):
    other = {"label": label, "stationary": False}
    assert people.facts([other], [other])["person"] is False


def test_result():
    assert people.result({"person": True}) == "seen"
    assert people.result({"person": False}) == "none"
    assert people.result({"person": None}) == "unchecked"


class Asked:
    def __init__(self, answer):
        self.answer, self.cameras = answer, []

    def tracked(self, camera):
        self.cameras.append(camera)
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


def test_ask_gives_the_list_for_the_key():
    nodered = Asked([CAR])
    assert people.ask(nodered, "main") == [CAR] and nodered.cameras == ["main"]


@pytest.mark.parametrize("code", ["unreachable", "refused", "unexpected"])
def test_ask_is_none_when_node_red_fails(code, caplog):
    caplog.set_level(logging.DEBUG)
    assert people.ask(Asked(NodeRedError(code)), "main") is None
    assert caplog.records == []
