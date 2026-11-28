"""What an update channel offers this device: GitHub's answers about the channel's newest version, turned into an
Offer the page shows."""

import re
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel

from ...adapters import github
from ...adapters.github import GithubError

_COMMIT = re.compile(r"[0-9a-f]{40}")
_TAG = re.compile(r"v[0-9]{1,9}\.[0-9]{1,9}\.[0-9]{1,9}")
_VERSION = re.compile(r"([0-9]{1,9})\.([0-9]{1,9})\.([0-9]{1,9})(-dev)?")


class Offer(BaseModel):
    channel: Literal["stable", "development"]
    relation: Literal["ahead", "identical", "behind", "diverged", "unknown"]
    version: str | None
    commit: str
    tag: str | None
    released_at: str | None
    ahead_by: int | None
    checked_at: str


def _version_key(value: str) -> tuple[int, int, int, bool] | None:
    """<n>.<n>.<n> with an optional -dev, which comes before the same numbers without it (the update job's rule)."""
    match = _VERSION.fullmatch(value) if isinstance(value, str) else None
    return match and (int(match[1]), int(match[2]), int(match[3]), match[4] is None)


def _by_version(installed: str, offered: str) -> Literal["ahead", "identical", "behind", "unknown"]:
    old, new = _version_key(installed), _version_key(offered)
    if not (old and new):
        return "unknown"
    return "ahead" if new > old else "identical" if new == old else "behind"


def check(repo: str, installed_commit: str, installed_version: str, channel: str, now: datetime) -> Offer:
    """The channel's newest version and how it stands to the installed one. Raises GithubError."""
    if channel not in ("stable", "development"):
        raise ValueError("the channel is stable or development")
    tag = released_at = version = None
    if channel == "stable":
        release = github.latest_release(repo)
        tag = release["tag"]
        if not _TAG.fullmatch(tag):
            raise GithubError("refused")
        version, released_at = tag[1:], release["published_at"]
        commit = github.commit_id(repo, tag)
    else:
        commit = github.commit_id(repo, "dev")
    relation, ahead_by = "unknown", None
    known = bool(_COMMIT.fullmatch(installed_commit)) if isinstance(installed_commit, str) else False
    if known:
        try:
            found = github.compare(repo, installed_commit, commit)
            relation, ahead_by = found["status"], found["ahead_by"]
        except GithubError as error:
            if error.kind != "not_found":
                raise
            known = False
    if not known and channel == "stable":
        relation = _by_version(installed_version, version)
    return Offer(
        channel=channel, relation=relation, version=version, commit=commit, tag=tag, released_at=released_at,
        ahead_by=ahead_by, checked_at=now.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    )
