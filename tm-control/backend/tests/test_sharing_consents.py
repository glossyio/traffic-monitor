import pytest

from tm_control.core.auth import Users
from tm_control.core.state import State
from tm_control.modules.sharing.consents import (
    CONSENTS,
    MAINTAINER,
    OWN_SERVER,
    PRE_CONSENT,
    Consents,
    normalize_host,
    target_key,
)

# The same inputs and answers as SHARING_HOST_CASES in script/tests/test_node_red_flows.py
# (test_init_config_defaults_sharing). The two lists must stay equal.
SHARING_HOST_CASES = [
    ("tb.example.invalid", "tb.example.invalid"),
    ("HTTPS://TB.Example.invalid/", "tb.example.invalid"),
    ("http://tb.example.invalid", "tb.example.invalid"),
    ("https://tb.example.invalid/", "tb.example.invalid"),
    ("  tb.example.invalid  ", "tb.example.invalid"),
    ("tb.example.invalid//", "tb.example.invalid/"),
    ("https://", None),
    ("", None),
    ("   ", None),
    (42, None),
    (None, None),
]

HOST = "tb.example.invalid"


@pytest.fixture
def state(tmp_path):
    state = State(tmp_path / "state.sqlite")
    state.migrate()
    return state


@pytest.fixture
def consents(state):
    return Consents(state)


def test_constants():
    assert CONSENTS == ("share_data", "exact_location", "public_map")
    assert (MAINTAINER, OWN_SERVER, PRE_CONSENT) == ("maintainer", "own-server", "pre-consent")


def test_latest_is_the_newest_row_per_consent_and_target(consents):
    consents.record(MAINTAINER, "share_data", True, "v1", None, now=1000)
    consents.record(MAINTAINER, "share_data", False, "v1", None, note="changed my mind", now=2000)
    consents.record(MAINTAINER, "exact_location", True, "v1", None, now=1500)
    consents.record("own:" + HOST, "share_data", True, OWN_SERVER, None, now=3000)
    latest = consents.latest(MAINTAINER)
    assert set(latest) == {"share_data", "exact_location"}  # public_map was never recorded
    assert latest["share_data"].granted is False
    assert latest["share_data"].note == "changed my mind"
    assert latest["share_data"].at == "1970-01-01T00:33:20+00:00"
    assert latest["exact_location"].granted is True
    assert latest["exact_location"].notice_version == "v1"
    assert consents.latest("own:" + HOST)["share_data"].notice_version == OWN_SERVER
    assert consents.latest("own:other.example.invalid") == {}


def test_two_rows_in_the_same_second_resolve_to_the_later_insert(consents):
    consents.record(MAINTAINER, "share_data", True, "v1", None, now=1000)
    consents.record(MAINTAINER, "share_data", False, "v1", None, now=1000)
    assert consents.latest(MAINTAINER)["share_data"].granted is False
    consents.record(MAINTAINER, "share_data", True, "v1", None, now=1000)
    assert consents.granted(MAINTAINER, "share_data") is True


def test_a_clock_that_steps_back_does_not_reorder_the_rows(consents):
    consents.record(MAINTAINER, "share_data", True, "v1", None, now=5000)
    consents.record(MAINTAINER, "share_data", False, "v1", None, now=1000)  # the clock stepped back
    assert consents.latest(MAINTAINER)["share_data"].granted is False
    assert consents.granted(MAINTAINER, "share_data") is False
    consents.record(MAINTAINER, "share_data", True, "v1", None, now=2000)
    consents.withdraw_all(MAINTAINER, None, "stepped back", now=500)
    assert consents.granted(MAINTAINER, "share_data") is False


def test_record_without_a_time_uses_the_current_time(consents):
    consents.record(MAINTAINER, "share_data", True, PRE_CONSENT, None)
    assert consents.latest(MAINTAINER)["share_data"].at.startswith("20")


def test_granted_is_false_for_a_consent_never_recorded(consents):
    assert consents.granted(MAINTAINER, "share_data") is False
    consents.record(MAINTAINER, "share_data", True, "v1", None, now=1000)
    assert consents.granted(MAINTAINER, "share_data") is True
    assert consents.granted(MAINTAINER, "public_map") is False
    assert consents.granted("own:" + HOST, "share_data") is False


def test_withdraw_all_writes_a_row_only_for_what_is_granted(consents, state):
    consents.record(MAINTAINER, "share_data", True, "v1", None, now=1000)
    consents.record(MAINTAINER, "exact_location", True, "v1", None, now=1000)
    consents.record(MAINTAINER, "exact_location", False, "v1", None, now=1100)
    consents.record(MAINTAINER, "public_map", True, "v1", None, now=1000)
    rows_before = state.connect().execute("SELECT count(*) FROM sharing_consents").fetchone()[0]
    withdrawn = consents.withdraw_all(MAINTAINER, None, "host changed", now=2000)
    assert sorted(withdrawn) == ["public_map", "share_data"]
    rows_after = state.connect().execute("SELECT count(*) FROM sharing_consents").fetchone()[0]
    assert rows_after == rows_before + 2
    latest = consents.latest(MAINTAINER)
    assert [latest[name].granted for name in CONSENTS] == [False, False, False]
    assert latest["share_data"].note == "host changed"
    assert latest["share_data"].at == "1970-01-01T00:33:20+00:00"
    assert consents.withdraw_all(MAINTAINER, None, "again", now=3000) == []


def test_a_deleted_user_leaves_the_row_with_no_user(consents, state):
    user = Users(state).create("admin", "correct horse 1", "admin")
    consents.record(MAINTAINER, "share_data", True, "v1", user.id, now=1000)
    assert consents.latest(MAINTAINER)["share_data"].user_id == user.id
    Users(state).delete(user.id)
    assert consents.latest(MAINTAINER)["share_data"].user_id is None
    assert consents.granted(MAINTAINER, "share_data") is True


@pytest.mark.parametrize(
    "host, maintainer_host, expected",
    [
        ("TB.Example.invalid", "tb.example.invalid", "maintainer"),
        ("https://tb.example.invalid/", "tb.example.invalid", "maintainer"),
        ("other.example.invalid", "tb.example.invalid", "own:other.example.invalid"),
        (None, "tb.example.invalid", None),
        ("  ", "tb.example.invalid", None),
    ],
)
def test_target_key(host, maintainer_host, expected):
    assert target_key(host, maintainer_host) == expected


def test_review_flag_round_trips(consents, state):
    assert consents.review_needed() is False
    consents.set_review_needed(True)
    assert consents.review_needed() is True
    row = state.connect().execute("SELECT value FROM device WHERE key = 'sharing_review_needed'").fetchone()
    assert row is not None
    consents.set_review_needed(False)
    assert consents.review_needed() is False


@pytest.mark.parametrize("value, expected", SHARING_HOST_CASES)
def test_the_host_rule_matches_node_reds(value, expected):
    assert normalize_host(value) == expected
