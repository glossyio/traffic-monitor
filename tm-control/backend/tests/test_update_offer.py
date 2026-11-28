"""What an update channel offers: GitHub's answers turned into an Offer. github is replaced by a table."""

from datetime import datetime, timedelta, timezone

import pytest

from tm_control.adapters.github import GithubError
from tm_control.modules.update import offer
from tm_control.modules.update.offer import Offer, check

REPO = "glossyio/traffic-monitor"
INSTALLED = "1" * 40
TARGET = "2" * 40
NOW = datetime(2026, 11, 26, 12, 30, 5, tzinfo=timezone.utc)


class FakeGithub:
    def __init__(self, release=None, commits=None, compares=None):
        self.release = release if release is not None else {"tag": "v1.2.3", "published_at": "2026-11-01T10:00:00Z"}
        self.commits = commits if commits is not None else {"v1.2.3": TARGET, "dev": TARGET}
        self.compares = compares if compares is not None else {}
        self.calls = []

    def latest_release(self, repo):
        self.calls.append(("release", repo))
        return self._answer(self.release)

    def commit_id(self, repo, ref):
        self.calls.append(("commit", repo, ref))
        return self._answer(self.commits[ref])

    def compare(self, repo, base, head):
        self.calls.append(("compare", repo, base, head))
        return self._answer(self.compares.get((base, head), self.compares.get("any")))

    @staticmethod
    def _answer(value):
        if isinstance(value, Exception):
            raise value
        return value


@pytest.fixture
def github(monkeypatch):
    def install(**tables):
        fake = FakeGithub(**tables)
        monkeypatch.setattr(offer, "github", fake)
        return fake

    return install


@pytest.mark.parametrize(("status", "relation"), [
    ("ahead", "ahead"), ("identical", "identical"), ("behind", "behind"), ("diverged", "diverged"),
])
@pytest.mark.parametrize("channel", ["stable", "development"])
def test_the_offer_takes_githubs_word_for_how_the_two_relate(github, status, relation, channel):
    fake = github(compares={"any": {"status": status, "ahead_by": 4}})
    result = check(REPO, INSTALLED, "1.0.0", channel, NOW)
    assert result.relation == relation
    assert result.ahead_by == 4
    assert result.commit == TARGET
    assert result.channel == channel
    assert result.checked_at == "2026-11-26T12:30:05Z"
    assert ("compare", REPO, INSTALLED, TARGET) in fake.calls


def test_a_stable_offer_names_the_release(github):
    github(compares={"any": {"status": "ahead", "ahead_by": 12}})
    assert check(REPO, INSTALLED, "1.0.0", "stable", NOW) == Offer(
        channel="stable", relation="ahead", version="1.2.3", commit=TARGET, tag="v1.2.3",
        released_at="2026-11-01T10:00:00Z", ahead_by=12, checked_at="2026-11-26T12:30:05Z")


def test_a_development_offer_is_a_commit_without_a_version(github):
    fake = github(compares={"any": {"status": "ahead", "ahead_by": 7}})
    result = check(REPO, INSTALLED, "1.0.0-dev", "development", NOW)
    assert (result.version, result.tag, result.released_at) == (None, None, None)
    assert ("commit", REPO, "dev") in fake.calls
    assert not any(call[0] == "release" for call in fake.calls)


def test_the_time_is_given_in_utc(github):
    github(compares={"any": {"status": "ahead", "ahead_by": 1}})
    local = timezone(timedelta(hours=5))
    assert check(REPO, INSTALLED, "1.0.0", "stable", NOW.astimezone(local)).checked_at == "2026-11-26T12:30:05Z"


@pytest.mark.parametrize(("installed_version", "relation"), [
    ("1.0.0", "ahead"), ("1.2.2", "ahead"), ("0.9.9", "ahead"), ("1.2.3-dev", "ahead"),
    ("1.2.3", "identical"), ("1.2.4-dev", "behind"), ("1.2.4", "behind"), ("2.0.0", "behind"),
    ("1.10.0", "behind"), ("1.2", "unknown"), ("garbage", "unknown"), ("", "unknown"),
])
def test_stable_falls_back_to_versions_when_github_does_not_know_the_installed_commit(
    github, installed_version, relation
):
    fake = github(compares={"any": GithubError("not_found")})
    result = check(REPO, INSTALLED, installed_version, "stable", NOW)
    assert result.relation == relation
    assert result.ahead_by is None
    assert (result.version, result.tag, result.commit) == ("1.2.3", "v1.2.3", TARGET)
    assert ("compare", REPO, INSTALLED, TARGET) in fake.calls


@pytest.mark.parametrize("installed", ["unknown", "None", "", "ABCDEF" * 7, "1" * 39, "1" * 41, "g" * 40])
def test_a_commit_that_is_not_an_id_is_never_asked_about(github, installed):
    fake = github()
    result = check(REPO, installed, "1.0.0", "stable", NOW)
    assert result.relation == "ahead"
    assert not any(call[0] == "compare" for call in fake.calls)
    result = check(REPO, installed, "1.0.0", "development", NOW)
    assert result.relation == "unknown"
    assert not any(call[0] == "compare" for call in fake.calls)


# The same order as the job's (script/tests/test_update_job_control_app.py)
def test_an_unknown_commit_on_stable_is_judged_by_version(github):
    github(compares={"any": GithubError("not_found")})
    assert check(REPO, INSTALLED, "1.2.3-dev", "stable", NOW).relation == "ahead"  # -dev comes first
    assert check(REPO, INSTALLED, "1.2.3", "stable", NOW).relation == "identical"


def test_development_is_unknown_then(github):
    github(compares={"any": GithubError("not_found")})
    result = check(REPO, INSTALLED, "1.0.0", "development", NOW)
    assert result.relation == "unknown"
    assert result.ahead_by is None
    assert result.commit == TARGET
    assert (result.version, result.tag, result.released_at) == (None, None, None)


@pytest.mark.parametrize("tag", ["1.2.3", "v1.2", "v1.2.3-dev", "latest", "v1.2.3\n", "v1.2.3/../x", "v1.2.3.4", "V1.2.3", ""])
def test_a_latest_release_with_another_kind_of_tag_is_refused(github, tag):
    fake = github(release={"tag": tag, "published_at": None})
    with pytest.raises(GithubError) as error:
        check(REPO, INSTALLED, "1.0.0", "stable", NOW)
    assert error.value.kind == "refused"
    assert not any(call[0] in ("commit", "compare") for call in fake.calls)


@pytest.mark.parametrize("kind", ["offline", "rate_limited", "refused"])
def test_other_errors_pass_through(github, kind):
    github(compares={"any": GithubError(kind)})
    with pytest.raises(GithubError) as error:
        check(REPO, INSTALLED, "1.0.0", "stable", NOW)
    assert error.value.kind == kind


def test_a_rate_limit_keeps_its_wait(github):
    github(commits={"dev": GithubError("rate_limited", retry_after=42)})
    with pytest.raises(GithubError) as error:
        check(REPO, INSTALLED, "1.0.0", "development", NOW)
    assert error.value.retry_after == 42


def test_a_missing_release_is_not_found(github):
    github(release=GithubError("not_found"))
    with pytest.raises(GithubError) as error:
        check(REPO, INSTALLED, "1.0.0", "stable", NOW)
    assert error.value.kind == "not_found"


def test_another_channel_is_a_mistake_in_the_caller(github):
    github()
    with pytest.raises(ValueError):
        check(REPO, INSTALLED, "1.0.0", "nightly", NOW)
