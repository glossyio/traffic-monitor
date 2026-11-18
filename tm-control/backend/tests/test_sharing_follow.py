"""The follow step: config.yml's sharing: block kept equal to the consents in state.sqlite."""

import logging
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from tm_control.adapters import nodered
from tm_control.core.checks import Context
from tm_control.modules.apps import contracts
from tm_control.modules.location.config import NodeRedConfig, SharingBlock
from tm_control.modules.sharing import follow
from tm_control.modules.sharing.consents import MAINTAINER, OWN_SERVER, PRE_CONSENT, Consent, Consents

FIXTURES = Path(__file__).parent / "fixtures"
HOST, OTHER = "tb.example.invalid", "other.example.invalid"
NOTICE = "2026-11"
OFF_NOTE = "the upload was off in config.yml"
FOUND_NOTE = "the upload was on in config.yml with no choice recorded on the Sharing page"
CHANGED_NOTE = "the server changed in config.yml"
NO_BLOCK_NOTE = "config.yml had no sharing block"
HAND_BLOCK = (
    "\nsharing:\n"
    "    target: maintainer\n"
    "    host: tb.example.invalid\n"
    "    exact_location: true\n"
    "    public_map: none\n"
    "    notice_version: '2026-11'\n"
)


@pytest.fixture
def unit(claimed_client, tmp_path, monkeypatch):
    """The claimed app's state with Node-RED's config.yml (the fixture's) in tmp_path; `writes` counts the calls to
    after_config_write."""
    app_state = claimed_client.app.state
    assert app_state.manifest.sharing.maintainer_host == HOST
    path = tmp_path / "node-red" / "config.yml"
    path.parent.mkdir()
    shutil.copy(FIXTURES / "node_red_config_ok.yml", path)
    app_state.config_path = path
    writes = []
    monkeypatch.setattr(app_state.nodered, "after_config_write", lambda: writes.append(True))
    return SimpleNamespace(app_state=app_state, path=path, writes=writes, consents=Consents(app_state.state))


def edit(unit, old, new):
    text = unit.path.read_text()
    assert old in text
    unit.path.write_text(text.replace(old, new, 1))


def turn_on(unit):
    edit(unit, "    enabled: false\n    host:", "    enabled: true\n    host:")


def block(unit) -> SharingBlock | None:
    return NodeRedConfig(unit.path).sharing_block()


def rows(unit) -> list[tuple]:
    con = unit.app_state.state.connect()
    try:
        return [tuple(row) for row in con.execute(
            "SELECT target, consent, granted, notice_version, user_id, note FROM sharing_consents ORDER BY id"
        )]
    finally:
        con.close()


def grant(unit, *names, target=MAINTAINER, version=NOTICE):
    for name in names:
        unit.consents.record(target, name, True, version, None)


def save(unit, *names):
    """As the Sharing page saves `names` for the maintainer's server: the block first, the rows second."""
    share = Consent(consent="share_data", granted="share_data" in names, notice_version=NOTICE, at="x", user_id=None,
                    note=None)
    config = NodeRedConfig(unit.path)
    config.set_sharing(follow.wanted_block(MAINTAINER, HOST, share, "exact_location" in names, "public_map" in names))
    assert config.save()
    grant(unit, *names)


def reset(unit):
    shutil.copy(FIXTURES / "node_red_config_ok.yml", unit.path)  # as tmsetup.sh -f leaves it: off, no block


def sharing_check(unit):
    """The Status page's Sharing check, on a copy of the unit's config.yml where the check reads it."""
    codedir = unit.path.parent.parent / "codedir"
    path = nodered.config_path(codedir)
    path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(unit.path, path)
    app_state = unit.app_state
    manifest = app_state.manifest.model_copy(update={"codedir": str(codedir)})
    context = Context(None, manifest, None, app_state.state, app_state.notice.version)
    [check] = contracts.sharing(context)
    return check


def test_wanted_block_is_the_kind_the_host_and_the_granted_choices():
    share = Consent(consent="share_data", granted=True, notice_version=NOTICE, at="x", user_id=1, note=None)
    assert follow.wanted_block(MAINTAINER, "HTTPS://TB.example.invalid/", share, True, True) == SharingBlock(
        target="maintainer", host=HOST, exact_location=True, public_map="rounded_point", notice_version=NOTICE
    )
    own = share.model_copy(update={"notice_version": OWN_SERVER})
    assert follow.wanted_block("own:" + OTHER, OTHER, own, False, False) == SharingBlock(
        target="own", host=OTHER, exact_location=False, public_map="none", notice_version=OWN_SERVER
    )
    withdrawn = share.model_copy(update={"granted": False})
    assert follow.wanted_block(MAINTAINER, HOST, withdrawn, False, False).notice_version is None
    assert follow.wanted_block(MAINTAINER, HOST, None, False, False).notice_version is None
    assert follow.wanted_block(None, None, None, False, False) == SharingBlock()


def test_an_upload_already_on_is_recorded_flagged_and_given_a_block(unit):
    turn_on(unit)
    assert follow.run(unit.app_state) is True
    assert rows(unit) == [(MAINTAINER, "share_data", 1, PRE_CONSENT, None, FOUND_NOTE)]
    assert unit.consents.review_needed()
    assert block(unit) == SharingBlock(
        target="maintainer", host=HOST, exact_location=False, public_map="none", notice_version=PRE_CONSENT
    )
    assert unit.writes == [True]

    before = unit.path.read_bytes()
    assert follow.run(unit.app_state) is False
    assert len(rows(unit)) == 1
    assert unit.path.read_bytes() == before and unit.writes == [True]


def test_a_review_flag_is_cleared_when_the_upload_is_turned_off(unit):
    turn_on(unit)
    assert follow.run(unit.app_state) is True
    assert unit.consents.review_needed()
    assert sharing_check(unit).status == "warn"

    edit(unit, "    enabled: true\n    host:", "    enabled: false\n    host:")
    follow.run(unit.app_state)
    assert not unit.consents.review_needed()
    check = sharing_check(unit)
    assert (check.status, check.detail, check.fix) == ("ok", "Not sharing.", None)


@pytest.mark.parametrize("host", [HOST, "tb.server.com"])  # the default, and the template's old placeholder
def test_an_untouched_unit_gets_no_block_and_no_row(unit, host):
    edit(unit, "host: tb.example.invalid", f"host: {host}")
    before = unit.path.read_bytes()
    assert follow.run(unit.app_state) is False
    assert rows(unit) == []
    assert not unit.consents.review_needed()
    assert unit.path.read_bytes() == before and unit.writes == []


def test_a_reset_file_withdraws_everything_and_restores_nothing(unit):
    turn_on(unit)
    save(unit, "share_data", "exact_location", "public_map")
    assert follow.run(unit.app_state) is False
    assert block(unit) == SharingBlock(
        target="maintainer", host=HOST, exact_location=True, public_map="rounded_point", notice_version=NOTICE
    )

    reset(unit)
    before = unit.path.read_bytes()
    assert follow.run(unit.app_state) is False
    withdrawn = [row for row in rows(unit) if row[2] == 0]
    assert withdrawn == [
        (MAINTAINER, name, 0, NOTICE, None, OFF_NOTE) for name in ("share_data", "exact_location", "public_map")
    ]
    assert unit.path.read_bytes() == before

    turn_on(unit)
    assert follow.run(unit.app_state) is True
    latest = unit.consents.latest(MAINTAINER)
    assert (latest["share_data"].granted, latest["share_data"].notice_version) == (True, PRE_CONSENT)
    assert latest["exact_location"].note == OFF_NOTE and latest["public_map"].note == OFF_NOTE  # no second withdrawal
    assert block(unit) == SharingBlock(
        target="maintainer", host=HOST, exact_location=False, public_map="none", notice_version=PRE_CONSENT
    )


def test_a_reset_file_turned_back_on_unseen_withdraws_the_exact_location_and_the_map(unit):
    """tmsetup.sh -f, then the upload turned on by hand before any page or status check ran the follow step: the store
    still grants all three, and the missing block means the rounded location only."""
    turn_on(unit)
    save(unit, "share_data", "exact_location", "public_map")
    reset(unit)
    turn_on(unit)
    count = len(rows(unit))

    assert follow.run(unit.app_state) is True
    assert rows(unit)[count:] == [
        (MAINTAINER, name, 0, NOTICE, None, NO_BLOCK_NOTE) for name in ("exact_location", "public_map")
    ]
    assert unit.consents.granted(MAINTAINER, "share_data")
    assert not unit.consents.review_needed()
    assert block(unit) == SharingBlock(
        target="maintainer", host=HOST, exact_location=False, public_map="none", notice_version=NOTICE
    )
    assert unit.writes == [True]
    assert follow.run(unit.app_state) is False


def test_a_missing_block_with_the_upload_off_is_left_missing(unit):
    turn_on(unit)
    save(unit, "share_data", "exact_location")
    reset(unit)
    before = unit.path.read_bytes()
    assert follow.run(unit.app_state) is False
    assert unit.path.read_bytes() == before and unit.writes == []
    assert not [row for row in rows(unit) if row[5] == NO_BLOCK_NOTE]  # the upload off withdrew them first


def test_a_missing_block_without_a_host_is_left_missing(unit):
    turn_on(unit)
    save(unit, "share_data", "exact_location")
    reset(unit)
    turn_on(unit)
    edit(unit, "    host: tb.example.invalid\n    protocol:", "    host:\n    protocol:")
    before = unit.path.read_bytes()
    assert follow.run(unit.app_state) is False
    assert unit.path.read_bytes() == before and unit.writes == []
    assert not unit.consents.granted(MAINTAINER, "exact_location")


def test_a_changed_host_withdraws_the_other_choices(unit):
    turn_on(unit)
    save(unit, "share_data", "exact_location")
    assert block(unit).exact_location is True

    edit(unit, "host: tb.example.invalid", "host: other.example.invalid")  # thingsboard: comes first
    writes = len(unit.writes)
    assert follow.run(unit.app_state) is True
    old = unit.consents.latest(MAINTAINER)
    assert not old["exact_location"].granted and old["exact_location"].note == CHANGED_NOTE
    assert not old["share_data"].granted
    new = unit.consents.latest("own:" + OTHER)
    assert (new["share_data"].granted, new["share_data"].notice_version) == (True, PRE_CONSENT)
    assert block(unit) == SharingBlock(
        target="own", host=OTHER, exact_location=False, public_map="none", notice_version=PRE_CONSENT
    )
    assert len(unit.writes) == writes + 1

    assert follow.run(unit.app_state) is False  # nothing left to change


def test_editing_both_hosts_still_withdraws_the_old_server(unit):
    turn_on(unit)
    save(unit, "share_data", "exact_location")
    assert block(unit).exact_location is True

    text = unit.path.read_text()
    assert text.count("host: tb.example.invalid") == 2  # thingsboard: and sharing:
    unit.path.write_text(text.replace("host: tb.example.invalid", "host: other.example.invalid"))
    assert follow.run(unit.app_state) is True
    old = unit.consents.latest(MAINTAINER)
    assert not old["share_data"].granted and not old["exact_location"].granted
    assert old["exact_location"].note == CHANGED_NOTE
    assert block(unit) == SharingBlock(
        target="own", host=OTHER, exact_location=False, public_map="none", notice_version=PRE_CONSENT
    )

    text = unit.path.read_text()
    unit.path.write_text(text.replace("host: other.example.invalid", "host: tb.example.invalid"))
    follow.run(unit.app_state)
    back = unit.consents.latest(MAINTAINER)
    assert (back["share_data"].granted, back["share_data"].notice_version) == (True, PRE_CONSENT)
    assert not back["exact_location"].granted
    assert not unit.consents.granted("own:" + OTHER, "share_data")
    assert block(unit).exact_location is False


def test_a_granted_exact_location_for_the_same_host_is_left_alone(unit):
    turn_on(unit)
    save(unit, "share_data", "exact_location")
    before = unit.path.read_bytes()
    assert follow.run(unit.app_state) is False
    assert unit.writes == [] and unit.path.read_bytes() == before
    assert unit.consents.granted(MAINTAINER, "exact_location")


def test_removing_the_host_withdraws_and_clears_the_block(unit):
    turn_on(unit)
    save(unit, "share_data", "exact_location")

    edit(unit, "    host: tb.example.invalid\n    protocol:", "    host:\n    protocol:")
    assert follow.run(unit.app_state) is True
    latest = unit.consents.latest(MAINTAINER)
    assert not latest["share_data"].granted and not latest["exact_location"].granted
    assert latest["share_data"].note == CHANGED_NOTE
    assert block(unit) == SharingBlock()
    assert follow.run(unit.app_state) is False


def test_a_hand_set_exact_location_is_written_back(unit):
    turn_on(unit)
    grant(unit, "share_data")
    unit.path.write_text(unit.path.read_text() + HAND_BLOCK)
    assert block(unit).exact_location is True

    assert follow.run(unit.app_state) is True
    assert block(unit) == SharingBlock(
        target="maintainer", host=HOST, exact_location=False, public_map="none", notice_version=NOTICE
    )
    assert unit.writes == [True]
    assert not unit.consents.granted(MAINTAINER, "exact_location")

    assert follow.run(unit.app_state) is False
    assert unit.writes == [True]


def test_a_reformatted_block_that_means_the_same_is_left_alone(unit):
    turn_on(unit)
    grant(unit, "share_data")
    unit.path.write_text(
        unit.path.read_text()
        + "\nsharing:\n    notice_version: \"2026-11\"   # moved by hand\n    host: HTTPS://TB.example.invalid/\n"
        "    target: maintainer\n    exact_location: false\n"
    )
    before = unit.path.read_bytes()
    assert follow.run(unit.app_state) is False
    assert unit.path.read_bytes() == before and unit.writes == []


@pytest.mark.parametrize("content", [None, "thingsboard: [\n", "- just a list\n"])
def test_an_unreadable_file_is_left_alone(unit, content):
    if content is None:
        unit.path.unlink()
    else:
        unit.path.write_text(content)
    assert follow.run(unit.app_state) is False
    assert rows(unit) == [] and unit.writes == []
    if content is not None:
        assert unit.path.read_text() == content


def test_no_host_in_any_log_line(unit, caplog):
    caplog.set_level(logging.DEBUG)
    turn_on(unit)
    follow.run(unit.app_state)  # recorded as found on, the block written
    save(unit, "share_data", "exact_location", "public_map")
    follow.run(unit.app_state)  # nothing to do
    reset(unit)
    turn_on(unit)
    follow.run(unit.app_state)  # no block: the exact location and the map withdrawn, the block written
    edit(unit, "host: tb.example.invalid", "host: other.example.invalid")
    follow.run(unit.app_state)  # the server changed
    edit(unit, "    enabled: true\n    host:", "    enabled: false\n    host:")
    grant(unit, "share_data", target="own:" + OTHER, version=OWN_SERVER)
    follow.run(unit.app_state)  # the upload off
    unit.path.write_text("thingsboard: [\n")
    follow.run(unit.app_state)  # unreadable

    messages = [record.getMessage() for record in caplog.records]
    assert any(record.name == follow.__name__ for record in caplog.records)  # it does log, by counts
    texts = ("example.invalid", NOTICE, PRE_CONSENT, OWN_SERVER, OFF_NOTE, FOUND_NOTE, CHANGED_NOTE, NO_BLOCK_NOTE, "own:")
    for text in texts:
        assert not [message for message in messages if text in message], text

