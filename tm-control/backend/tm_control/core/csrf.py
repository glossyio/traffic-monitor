"""Cross-site request checks for the API: a request under /api/ that isn't GET or HEAD must send a JSON body and
come from a page on this device.

"From this device" means the Origin header (or, without one, the Referer) names the same host[:port] as the Host
header. nginx forwards Host as the browser sent it ($http_host), port included. A failed check is a 403 `forbidden`.
"""

import logging
from urllib.parse import urlsplit

from starlette.datastructures import Headers

from tm_control.core.errors import error_response

log = logging.getLogger(__name__)

SAFE_METHODS = frozenset({"GET", "HEAD"})


def _netloc(url: str) -> str | None:
    """host[:port] of an absolute http(s) URL, lowercased; None for anything else, such as Origin: null."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return None
    return parts.netloc.rpartition("@")[2].lower()


def _problem(headers: Headers) -> str | None:
    """Why the request fails the check, or None when it passes."""
    if headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
        return "not JSON"
    source = headers.get("origin") or headers.get("referer")
    if not source:
        return "no Origin or Referer"
    host = headers.get("host", "").lower()
    if not host or _netloc(source) != host:
        return "another origin"
    return None


class CsrfMiddleware:
    """A pure ASGI middleware, so request bodies stream through untouched."""

    def __init__(self, app, prefix: str = "/api/"):
        self.app = app
        self.prefix = prefix

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["method"] not in SAFE_METHODS and scope["path"].startswith(self.prefix):
            problem = _problem(Headers(scope=scope))
            if problem:
                log.info("403 cross-site check (%s) on %s %s", problem, scope["method"], scope["path"])
                response = error_response(403, "forbidden", "This request must come from the device's own pages.")
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)
