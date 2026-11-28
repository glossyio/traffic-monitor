"""The control app's one way to the internet: GitHub's API, for the one repository the install records.

The host is fixed (api.github.com, https), no proxy from the environment is used, a redirect is never followed, an
answer over MAX_BODY bytes is refused, and the request names nothing but the program. Every failure is a
GithubError with a kind the page turns into words; none of these functions returns a half answer.
"""

import json
import re
import socket
import time
import urllib.error
import urllib.request
from http.client import HTTPException
from typing import Any
from urllib.parse import urlsplit

from ..core.repository import is_repo

HOST = "api.github.com"
TIMEOUT = 10  # seconds for the connection and for each read
MAX_BODY = 1_048_576  # bytes; a longer answer is refused

_USER_AGENT = "traffic-monitor-update"
_API_VERSION = "2022-11-28"
_COMMIT = re.compile(r"[0-9a-f]{40}")
_REF = re.compile(r"dev|[0-9a-f]{40}|v[0-9]{1,9}\.[0-9]{1,9}\.[0-9]{1,9}")
_STATUSES = ("ahead", "behind", "identical", "diverged")
_KEPT_MAX = 32  # paths whose answers are kept; the app asks about a handful


class GithubError(Exception):
    """kind: offline, rate_limited, not_found, or refused. retry_after: seconds to wait, for rate_limited if known."""

    def __init__(self, kind: str, retry_after: int | None = None):
        super().__init__(kind)
        self.kind = kind
        self.retry_after = retry_after


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # urllib then raises the 3xx as an HTTPError


def _build_opener() -> urllib.request.OpenerDirector:
    opener = urllib.request.OpenerDirector()
    for handler in (
        urllib.request.ProxyHandler({}),
        urllib.request.HTTPSHandler(),
        _NoRedirect(),
        urllib.request.HTTPDefaultErrorHandler(),
        urllib.request.HTTPErrorProcessor(),
    ):
        opener.add_handler(handler)
    return opener


# Tests replace these two. Nothing here is plain http: the opener has no handler for it.
_OPENER = _build_opener()
_clock = time.time

# path (with its query) -> (ETag, body): a 304 answers with the body kept here, which saves the download. GitHub
# leaves a 304 out of its rate limit only for a request with a login, and these send none, so it still counts.
_KEPT: dict[str, tuple[str, bytes]] = {}


def _headers(response) -> dict[str, str]:
    return {name.lower(): value for name, value in response.headers.items()}


def _read(response) -> bytes:
    data = response.read(MAX_BODY + 1)
    if len(data) > MAX_BODY:
        raise GithubError("refused")
    return data


def _rate_limited(code: int, headers: dict[str, str]) -> GithubError | None:
    if code == 403 and headers.get("x-ratelimit-remaining") != "0":
        return None
    if code not in (403, 429):
        return None
    wait = None
    try:
        wait = max(0, int(int(headers["x-ratelimit-reset"]) - _clock()))
    except (KeyError, ValueError):
        pass
    return GithubError("rate_limited", wait)


def _get(path: str, accept: str) -> bytes:
    """The body of GET https://api.github.com<path>; path starts with /repos/ and is made by this module."""
    if not path.startswith("/repos/"):
        raise GithubError("refused")
    url = f"https://{HOST}{path}"
    if urlsplit(url).hostname != HOST:
        raise GithubError("refused")
    request = urllib.request.Request(url, headers={
        "Accept": accept, "User-Agent": _USER_AGENT, "X-GitHub-Api-Version": _API_VERSION,
    })
    kept = _KEPT.get(path)
    if kept:
        request.add_header("If-None-Match", kept[0])
    try:
        with _OPENER.open(request, timeout=TIMEOUT) as response:
            body, headers = _read(response), _headers(response)
    except GithubError:
        raise
    except urllib.error.HTTPError as error:
        headers = _headers(error)
        if error.code == 304 and kept:
            return kept[1]
        limited = _rate_limited(error.code, headers)
        if limited:
            raise limited from None
        if error.code == 404:
            raise GithubError("not_found") from None
        if error.code >= 500:
            raise GithubError("offline") from None
        raise GithubError("refused") from None  # a redirect, a 304 with nothing kept, or anything else unexpected
    except (urllib.error.URLError, socket.timeout, HTTPException, OSError):
        raise GithubError("offline") from None
    etag = headers.get("etag")
    if etag:
        if path not in _KEPT and len(_KEPT) >= _KEPT_MAX:
            _KEPT.clear()
        _KEPT[path] = (etag, body)
    return body


def _json(path: str) -> Any:
    body = _get(path, "application/vnd.github+json")
    try:
        return json.loads(body)
    except (ValueError, RecursionError):
        raise GithubError("refused") from None


def _repo(repo: str) -> str:
    if not is_repo(repo):
        raise GithubError("refused")
    return repo


def _ref(ref: str) -> str:
    if not isinstance(ref, str) or not _REF.fullmatch(ref):
        raise GithubError("refused")
    return ref


def latest_release(repo: str) -> dict:
    """{"tag": str, "published_at": str | None} for the repository's latest release."""
    data = _json(f"/repos/{_repo(repo)}/releases/latest")
    if not isinstance(data, dict) or not isinstance(data.get("tag_name"), str):
        raise GithubError("refused")
    published = data.get("published_at")
    if published is not None and not isinstance(published, str):
        raise GithubError("refused")
    return {"tag": data["tag_name"], "published_at": published}


def commit_id(repo: str, ref: str) -> str:
    """The 40-character id of ref (dev, a commit id, or a vX.Y.Z tag)."""
    path = f"/repos/{_repo(repo)}/commits/{_ref(ref)}"
    text = _get(path, "application/vnd.github.sha").decode("ascii", "replace").strip()
    if not _COMMIT.fullmatch(text):
        raise GithubError("refused")
    return text


def compare(repo: str, base: str, head: str) -> dict:
    """{"status": ahead | behind | identical | diverged, "ahead_by": int}: how head stands to base.

    Page 2 of one-item pages is asked for: the answer is 12 KB where the default is over 1 MB, and still carries both.
    """
    data = _json(f"/repos/{_repo(repo)}/compare/{_ref(base)}...{_ref(head)}?per_page=1&page=2")
    if not isinstance(data, dict) or data.get("status") not in _STATUSES:
        raise GithubError("refused")
    ahead_by = data.get("ahead_by")
    if isinstance(ahead_by, bool) or not isinstance(ahead_by, int) or ahead_by < 0:
        raise GithubError("refused")
    return {"status": data["status"], "ahead_by": ahead_by}
