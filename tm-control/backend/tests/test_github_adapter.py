"""The GitHub adapter: one host, https, no proxy, no redirect, a size cap, ETags. A fake opener answers from a table;
nothing here touches the network."""

import io
import json
import socket
import urllib.error
import urllib.parse
import urllib.request

import pytest

from tm_control.adapters import github
from tm_control.adapters.github import GithubError

REPO = "glossyio/traffic-monitor"
COMMIT = "a" * 40
OTHER = "b" * 40


class Reply:
    def __init__(self, status=200, body=b"", headers=None):
        self.status = status
        self.body = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.headers = headers or {}


class FakeOpener:
    """Records each request; answers by path from a table, or raises what the table holds."""

    def __init__(self, table):
        self.table = table
        self.requests = []
        self.timeouts = []

    def open(self, request, timeout=None):
        self.requests.append(request)
        self.timeouts.append(timeout)
        parts = urllib.parse.urlsplit(request.full_url)
        reply = self.table[parts.path + ("?" + parts.query if parts.query else "")]
        if isinstance(reply, BaseException):
            raise reply
        if reply.status >= 300:
            raise urllib.error.HTTPError(request.full_url, reply.status, "x", reply.headers, io.BytesIO(reply.body))
        return FakeResponse(reply)


class FakeResponse:
    def __init__(self, reply):
        self.status = reply.status
        self.headers = reply.headers
        self._body = io.BytesIO(reply.body)

    def read(self, amount=-1):
        return self._body.read(amount)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def ask(monkeypatch):
    """Install a fake opener with a fresh answer cache; returns the installer."""
    monkeypatch.setattr(github, "_KEPT", {})

    def install(table):
        opener = FakeOpener(table)
        monkeypatch.setattr(github, "_OPENER", opener)
        return opener

    return install


def test_only_api_github_com_is_ever_asked_and_only_over_https(ask):
    opener = ask({
        f"/repos/{REPO}/releases/latest": Reply(body={"tag_name": "v1.2.3", "published_at": "2026-01-01T00:00:00Z"}),
        f"/repos/{REPO}/commits/dev": Reply(body=COMMIT.encode()),
        f"/repos/{REPO}/compare/{COMMIT}...{OTHER}?per_page=1&page=2": Reply(body={"status": "ahead", "ahead_by": 3}),
    })
    github.latest_release(REPO)
    github.commit_id(REPO, "dev")
    github.compare(REPO, COMMIT, OTHER)
    assert len(opener.requests) == 3
    for request in opener.requests:
        parts = urllib.parse.urlsplit(request.full_url)
        assert (parts.scheme, parts.netloc) == ("https", "api.github.com")
        assert parts.path.startswith("/repos/")
    assert set(opener.timeouts) == {10}


def test_the_real_opener_has_no_proxy_and_does_not_follow_a_redirect(monkeypatch):
    monkeypatch.setenv("https_proxy", "http://127.0.0.1:9")
    opener = github._build_opener()
    # an empty ProxyHandler adds nothing to an opener, and the environment's proxy is then never read
    assert not any(isinstance(handler, urllib.request.ProxyHandler) and handler.proxies for handler in opener.handlers)
    assert not any(hasattr(handler, "https_open") and hasattr(handler, "proxies") for handler in opener.handlers)
    assert not any(isinstance(handler, urllib.request.HTTPHandler) for handler in opener.handlers)
    request = urllib.request.Request("https://api.github.com/repos/a/b")
    for handler in opener.handlers:
        if isinstance(handler, urllib.request.HTTPRedirectHandler):
            assert handler.redirect_request(request, None, 302, "Found", {}, "https://example.com/") is None


@pytest.mark.parametrize("status", [301, 302, 307])
def test_a_redirect_is_refused_not_followed(ask, status):
    opener = ask({f"/repos/{REPO}/commits/dev": Reply(status, headers={"Location": "https://example.com/x"})})
    with pytest.raises(GithubError) as error:
        github.commit_id(REPO, "dev")
    assert error.value.kind == "refused"
    assert len(opener.requests) == 1


def test_an_answer_over_the_cap_is_refused(ask):
    body = b'{"tag_name": "v1.2.3", "pad": "' + b"x" * github.MAX_BODY + b'"}'
    ask({f"/repos/{REPO}/releases/latest": Reply(body=body)})
    with pytest.raises(GithubError) as error:
        github.latest_release(REPO)
    assert error.value.kind == "refused"


def test_an_answer_at_the_cap_is_read(ask):
    body = b'{"tag_name": "v1.2.3", "pad": "'
    body += b"x" * (github.MAX_BODY - len(body) - 2) + b'"}'
    assert len(body) == github.MAX_BODY
    ask({f"/repos/{REPO}/releases/latest": Reply(body=body)})
    assert github.latest_release(REPO)["tag"] == "v1.2.3"


def test_a_rate_limit_carries_its_wait(ask, monkeypatch):
    monkeypatch.setattr(github, "_clock", lambda: 1000.0)
    limited = {"x-ratelimit-remaining": "0", "x-ratelimit-reset": "1090"}
    ask({f"/repos/{REPO}/commits/dev": Reply(403, headers=limited)})
    with pytest.raises(GithubError) as error:
        github.commit_id(REPO, "dev")
    assert (error.value.kind, error.value.retry_after) == ("rate_limited", 90)
    ask({f"/repos/{REPO}/commits/dev": Reply(429, headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": "900"})})
    with pytest.raises(GithubError) as error:
        github.commit_id(REPO, "dev")
    assert (error.value.kind, error.value.retry_after) == ("rate_limited", 0)


def test_a_rate_limit_without_a_reset_has_no_wait(ask):
    ask({f"/repos/{REPO}/commits/dev": Reply(429)})
    with pytest.raises(GithubError) as error:
        github.commit_id(REPO, "dev")
    assert (error.value.kind, error.value.retry_after) == ("rate_limited", None)


def test_a_403_that_is_not_a_rate_limit_is_refused(ask):
    ask({f"/repos/{REPO}/commits/dev": Reply(403, headers={"x-ratelimit-remaining": "12"})})
    with pytest.raises(GithubError) as error:
        github.commit_id(REPO, "dev")
    assert error.value.kind == "refused"


def test_a_missing_thing_is_not_found(ask):
    ask({f"/repos/{REPO}/compare/{COMMIT}...{OTHER}?per_page=1&page=2": Reply(404)})
    with pytest.raises(GithubError) as error:
        github.compare(REPO, COMMIT, OTHER)
    assert error.value.kind == "not_found"


@pytest.mark.parametrize("failure", [
    urllib.error.URLError("no route"), socket.timeout("slow"), TimeoutError(), ConnectionResetError(),
])
def test_no_answer_is_offline(ask, failure):
    ask({f"/repos/{REPO}/commits/dev": failure})
    with pytest.raises(GithubError) as error:
        github.commit_id(REPO, "dev")
    assert (error.value.kind, error.value.retry_after) == ("offline", None)


def test_a_server_error_is_offline(ask):
    ask({f"/repos/{REPO}/commits/dev": Reply(502)})
    with pytest.raises(GithubError) as error:
        github.commit_id(REPO, "dev")
    assert error.value.kind == "offline"


def test_an_etag_is_sent_back_and_a_304_gives_the_kept_answer(ask):
    path = f"/repos/{REPO}/releases/latest"
    answer = {"tag_name": "v1.2.3", "published_at": "2026-01-01T00:00:00Z"}
    opener = ask({path: Reply(body=answer, headers={"ETag": 'W/"abc"'})})
    first = github.latest_release(REPO)
    assert "If-none-match" not in opener.requests[0].headers
    opener.table[path] = Reply(304, headers={"ETag": 'W/"abc"'})
    second = github.latest_release(REPO)
    assert second == first == {"tag": "v1.2.3", "published_at": "2026-01-01T00:00:00Z"}
    assert opener.requests[1].get_header("If-none-match") == 'W/"abc"'


def test_a_changed_answer_replaces_the_kept_one(ask):
    path = f"/repos/{REPO}/releases/latest"
    opener = ask({path: Reply(body={"tag_name": "v1.2.3"}, headers={"ETag": '"one"'})})
    github.latest_release(REPO)
    opener.table[path] = Reply(body={"tag_name": "v1.2.4"}, headers={"ETag": '"two"'})
    assert github.latest_release(REPO)["tag"] == "v1.2.4"
    opener.table[path] = Reply(304)
    assert github.latest_release(REPO)["tag"] == "v1.2.4"
    assert opener.requests[2].get_header("If-none-match") == '"two"'


def test_a_304_with_nothing_kept_is_refused(ask):
    ask({f"/repos/{REPO}/releases/latest": Reply(304)})
    with pytest.raises(GithubError) as error:
        github.latest_release(REPO)
    assert error.value.kind == "refused"


def test_the_compare_address_asks_for_the_small_page(ask):
    path = f"/repos/{REPO}/compare/{COMMIT}...{OTHER}?per_page=1&page=2"
    opener = ask({path: Reply(body={"status": "behind", "ahead_by": 0, "files": []})})
    assert github.compare(REPO, COMMIT, OTHER) == {"status": "behind", "ahead_by": 0}
    assert opener.requests[0].full_url == "https://api.github.com" + path
    assert opener.requests[0].full_url.endswith("?per_page=1&page=2")


@pytest.mark.parametrize("body", [
    {"status": "weird", "ahead_by": 1}, {"status": "ahead"}, {"status": "ahead", "ahead_by": -1},
    {"status": "ahead", "ahead_by": True}, {"status": "ahead", "ahead_by": "3"}, [], b"not json",
])
def test_a_compare_answer_of_another_shape_is_refused(ask, body):
    ask({f"/repos/{REPO}/compare/{COMMIT}...{OTHER}?per_page=1&page=2": Reply(body=body)})
    with pytest.raises(GithubError) as error:
        github.compare(REPO, COMMIT, OTHER)
    assert error.value.kind == "refused"


def test_the_commit_id_is_asked_for_as_text_and_must_be_an_id(ask):
    path = f"/repos/{REPO}/commits/dev"
    opener = ask({path: Reply(body=COMMIT.encode() + b"\n")})
    assert github.commit_id(REPO, "dev") == COMMIT
    assert opener.requests[0].get_header("Accept") == "application/vnd.github.sha"
    for bad in (b"", b"A" * 40, b"a" * 39, b"a" * 41, b'{"sha": "' + COMMIT.encode() + b'"}', b"<html>"):
        opener.table[path] = Reply(body=bad)
        github._KEPT.clear()
        with pytest.raises(GithubError) as error:
            github.commit_id(REPO, "dev")
        assert error.value.kind == "refused"


@pytest.mark.parametrize("repo", ["a/b/../c", "a/b?x=1", "../etc", "a", "a/..", "a/b/c", "a b/c", "a/b#f", ""])
def test_a_repo_of_another_form_never_reaches_the_address(ask, repo):
    opener = ask({})
    for call in (lambda: github.latest_release(repo), lambda: github.commit_id(repo, "dev"),
                 lambda: github.compare(repo, COMMIT, OTHER)):
        with pytest.raises(GithubError) as error:
            call()
        assert error.value.kind == "refused"
    assert opener.requests == []


@pytest.mark.parametrize("ref", [
    "dev?x=1", "v1.2.3/../x", "main", "v1.2", "v1.2.3-dev", "a" * 39, "A" * 40, "dev#x", "dev/../x", "", "v1.2.3\n",
    f"{COMMIT}...{OTHER}",
])
def test_a_ref_of_another_form_never_reaches_the_address(ask, ref):
    opener = ask({})
    with pytest.raises(GithubError) as error:
        github.commit_id(REPO, ref)
    assert error.value.kind == "refused"
    with pytest.raises(GithubError):
        github.compare(REPO, ref, OTHER)
    with pytest.raises(GithubError):
        github.compare(REPO, COMMIT, ref)
    assert opener.requests == []


def test_a_tag_is_a_ref(ask):
    opener = ask({f"/repos/{REPO}/commits/v1.2.3": Reply(body=COMMIT.encode())})
    assert github.commit_id(REPO, "v1.2.3") == COMMIT
    assert len(opener.requests) == 1


def test_requests_identify_nothing_but_the_program(ask):
    opener = ask({
        f"/repos/{REPO}/releases/latest": Reply(body={"tag_name": "v1.2.3"}, headers={"ETag": '"e"'}),
        f"/repos/{REPO}/commits/dev": Reply(body=COMMIT.encode()),
    })
    github.latest_release(REPO)
    github.latest_release(REPO)  # the second carries If-None-Match
    github.commit_id(REPO, "dev")
    names = [{name.lower(): value for name, value in request.header_items()} for request in opener.requests]
    for sent in names:
        assert set(sent) <= {"accept", "user-agent", "x-github-api-version", "if-none-match"}
        assert {"accept", "user-agent", "x-github-api-version"} <= set(sent)
        assert sent["user-agent"] == "traffic-monitor-update"
        assert sent["x-github-api-version"] == "2022-11-28"
    assert "if-none-match" in names[1]
    assert "if-none-match" not in names[0] and "if-none-match" not in names[2]
    for request in opener.requests:
        assert request.data is None and request.get_method() == "GET"


@pytest.mark.parametrize("body", [
    {"tag_name": 5}, {"name": "x"}, [], {"tag_name": "v1.2.3", "published_at": 7}, b"{bad",
])
def test_a_release_answer_of_another_shape_is_refused(ask, body):
    ask({f"/repos/{REPO}/releases/latest": Reply(body=body)})
    with pytest.raises(GithubError) as error:
        github.latest_release(REPO)
    assert error.value.kind == "refused"


def test_a_release_without_a_date_has_none(ask):
    ask({f"/repos/{REPO}/releases/latest": Reply(body={"tag_name": "v1.2.3", "published_at": None})})
    assert github.latest_release(REPO) == {"tag": "v1.2.3", "published_at": None}
