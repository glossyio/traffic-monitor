"""Login, logout, the session the UI routes on, nginx's auth_request check (/api/v1/auth/verify), and the one-time
download links verify also accepts.

verify's status codes and X-TM-* headers are a contract with the auth snippets in revproxy's tm/snippets/, and its
answer to a download link with the /_auth locations in tm-control-auth.conf (X-Forwarded-For) and the two Dashboard
templates that ask for a link.
"""

import logging
import time
from urllib.parse import parse_qsl, quote, unquote_plus, urlsplit

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from tm_control.core.auth import DOWNLOAD_PATH, DOWNLOAD_TOKEN, ROLES, Device, User, Users
from tm_control.core.errors import ApiError
from tm_control.modules.auth.deps import (
    clear_session_cookie,
    client_ip,
    rate_limited,
    refresh_if_old,
    require_admin,
    session_user,
    set_session_cookie,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])
root_router = APIRouter()  # at the app root, outside /api/v1


def safe_next(uri: str) -> str:
    """The path and query of a same-site URI to return to after login, or "/" for anything else.

    Refuses URIs a browser could read as another site: "//host", "/\\host", or ones with whitespace or controls.
    """
    if not uri.startswith("/") or uri[1:2] in ("/", "\\") or not uri.isascii():
        return "/"
    if any(c <= " " or c in "\\\x7f" for c in uri):
        return "/"
    parts = urlsplit(uri)
    return parts.path + (f"?{parts.query}" if parts.query else "")


def without_download_token(uri: str) -> str:
    """uri with every tm_token pair cut from its query, the rest as sent, so a login redirect never holds a link."""
    path, mark, rest = uri.partition("?")
    if not mark:
        return uri
    query, hash_mark, fragment = rest.partition("#")
    kept = [pair for pair in query.split("&") if unquote_plus(pair.partition("=")[0]) != DOWNLOAD_TOKEN]
    return path + (f"?{'&'.join(kept)}" if kept else "") + hash_mark + fragment


def _download_link_user(request: Request, required: str, uri: str) -> User | None:
    """The admin a request without a session may pass as, because its URI is a good download link; else None.

    The link must be exactly /storefiles?files=...&tm_token=... on an admin location, from the address it was made
    for. It is spent once it is presented here, whether or not the rest matched. A link is checked like a session:
    the user still exists, is an admin, and has the same session epoch, and the current license agreement is accepted.
    """
    if required != "admin":
        return None
    parts = urlsplit(uri)
    pairs = parse_qsl(parts.query, keep_blank_values=True)
    if parts.path != DOWNLOAD_PATH or sorted(name for name, _ in pairs) != ["files", DOWNLOAD_TOKEN]:
        return None
    values = dict(pairs)
    app_state = request.app.state
    token, files = values[DOWNLOAD_TOKEN], values["files"]
    grant = app_state.download_grants.redeem(token, client_ip(request), files, time.monotonic())
    if grant is None:
        return None
    user = Users(app_state.state).get(grant.uid)
    if user is None or user.session_epoch != grant.epoch or user.role != "admin":
        return None
    if not Device(app_state.state).eula_accepted(app_state.eula.version):
        return None
    return user


class DownloadLinkRequest(BaseModel):
    files: str = Field(min_length=1, max_length=2048)


class DownloadLink(BaseModel):
    url: str


@router.post("/download-link", response_model=DownloadLink)
def download_link(body: DownloadLinkRequest, request: Request, admin: User = Depends(require_admin)):
    """A link to /storefiles?files=<files> that passes the login check once without the cookie.

    For browsers that hand a download to a helper without the cookie (Android's sign-in window). It works once, for
    600 seconds, from this browser's address, for these files only.
    """
    address = client_ip(request)
    token = request.app.state.download_grants.issue(admin, address, body.files, time.monotonic())
    log.info("download link made for %s from %s", admin.username, address)
    return {"url": f"{DOWNLOAD_PATH}?files={quote(body.files, safe='/,')}&{DOWNLOAD_TOKEN}={token}"}


VERIFY_PATH = "/api/v1/auth/verify"


@router.get("/verify")
def verify(request: Request):
    """nginx's auth_request: may this browser have X-Original-URI, which needs X-TM-Required-Role?

    Only nginx's internal /_auth locations call verify, and only they set X-TM-Required-Role (viewer or admin);
    nginx refuses the path from the network and clears the header on /api/. Any other call gets 404 and no identity.
    401 with X-TM-Redirect sends the browser to /setup, /login?next=..., /welcome (an admin, while a new license
    agreement waits), or /waiting (a viewer, meanwhile). 403 is forbidden.
    200 carries X-TM-User, X-TM-Role, X-TM-Frigate-Secret, and for admins X-TM-NR-Token.
    Without a session, a good download link (POST /download-link) passes once: 200 with X-TM-User and X-TM-Role only,
    no other secret and no cookie. A login redirect's next= leaves the link's token out.
    """
    required = request.headers.get("x-tm-required-role")
    # The exact path too: Starlette's route pattern ends in $, which also matches before a trailing newline (%0A)
    if required not in ROLES or request.scope["path"] != VERIFY_PATH:
        raise ApiError(404, "not_found", "Not Found")

    app_state = request.app.state
    device = Device(app_state.state)
    if not device.is_claimed():
        raise ApiError(401, "not_claimed", "Set up this device first.", headers={"X-TM-Redirect": "/setup"})

    uri = request.headers.get("x-original-uri", "/")
    found = session_user(request)
    if found is None:
        link_user = _download_link_user(request, required, uri)
        if link_user is not None:
            log.info("download link used by %s from %s", link_user.username, client_ip(request))
            return Response(status_code=200, headers={"X-TM-User": link_user.username, "X-TM-Role": link_user.role})
        target = quote(safe_next(without_download_token(uri)), safe="/")
        redirect = {"X-TM-Redirect": f"/login?next={target}"}
        raise ApiError(401, "unauthenticated", "Log in to continue.", headers=redirect)
    user, claims = found

    if not device.eula_accepted(app_state.eula.version):
        message = "The license agreement has changed; an admin must accept it."
        page = "/welcome" if user.role == "admin" else "/waiting"
        raise ApiError(401, "eula_required", message, headers={"X-TM-Redirect": page})

    if ROLES.index(user.role) < ROLES.index(required):
        raise ApiError(403, "forbidden", "You don't have access to this page.")

    headers = {
        "X-TM-User": user.username,
        "X-TM-Role": user.role,
        "X-TM-Frigate-Secret": app_state.secrets.frigate_proxy_secret,
    }
    if user.role == "admin":
        headers["X-TM-NR-Token"] = app_state.nr_token.mint(user.username, user.role)
    response = Response(status_code=200, headers=headers)
    refresh_if_old(request, response, user, claims)
    return response


class Credentials(BaseModel):
    username: str = Field(max_length=64)
    password: str = Field(max_length=1024)


@router.post("/login")
def login(body: Credentials, request: Request, response: Response):
    app_state = request.app.state
    if not Device(app_state.state).is_claimed():
        raise ApiError(409, "not_claimed", "Set up this device first.")

    ip = client_ip(request)
    username = body.username.lower()
    keys = (f"ip:{ip}", f"user:{username}")
    backoff = app_state.login_backoff
    wait = max(backoff.check(key, time.monotonic()) for key in keys)
    if wait > 0:  # before the password is checked, so guesses during the wait cost nothing and tell nothing
        log.warning("login refused while backing off: from %s as %r", ip, username)
        raise rate_limited(wait, "Too many failed logins. Try again later.")

    # Counted as a failure before the slow password check and forgiven on success, so parallel guesses can't all
    # slip past the check above while argon2 runs.
    for key in keys:
        backoff.record_failure(key, time.monotonic())
    user = Users(app_state.state).authenticate(username, body.password)
    if user is None:
        log.warning("failed login from %s as %r", ip, username)
        raise ApiError(401, "unauthenticated", "The username or password is wrong.")

    for key in keys:
        backoff.reset(key)
    set_session_cookie(request, response, user)
    log.info("login from %s as %r", ip, user.username)
    return {"user": user}


@router.post("/logout", status_code=204)
def logout(response: Response):
    clear_session_cookie(response)


@root_router.get("/logout", include_in_schema=False)
def logout_and_go_to_login():
    """Frigate's logout_url: end the session and show the login page.

    A GET that changes state, on purpose: Frigate's logout_url is a plain link. The worst another site can do with it
    is log the user out.
    """
    response = RedirectResponse("/login", status_code=302)
    clear_session_cookie(response)
    return response


@router.post("/logout-everywhere", status_code=204)
def logout_everywhere(request: Request, response: Response):
    """End every session of the current user, in every browser, including this one."""
    found = session_user(request)
    if found is None:
        raise ApiError(401, "unauthenticated", "Log in to continue.")
    user, _ = found
    Users(request.app.state.state).bump_epoch(user.id)
    clear_session_cookie(response)


@router.get("/session")
def session(request: Request, response: Response):
    """What the UI needs to pick a page. Never 401: without a session, user is null."""
    app_state = request.app.state
    device = Device(app_state.state)
    user = None
    found = session_user(request)
    if found is not None:
        user, claims = found
        refresh_if_old(request, response, user, claims)
    return {
        "claimed": device.is_claimed(),
        "eula_accepted": device.eula_accepted(app_state.eula.version),
        "user": user,
    }
