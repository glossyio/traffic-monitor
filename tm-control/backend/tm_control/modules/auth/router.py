"""Login, logout, the session the UI routes on, and nginx's auth_request check (/api/v1/auth/verify).

verify's status codes and X-TM-* headers are a contract with the auth snippets in revproxy's tm/snippets/.
"""

import logging
import time
from urllib.parse import quote, urlsplit

from fastapi import APIRouter, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from tm_control.core.auth import ROLES, Device, Users
from tm_control.core.errors import ApiError
from tm_control.modules.auth.deps import (
    clear_session_cookie,
    client_ip,
    rate_limited,
    refresh_if_old,
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


VERIFY_PATH = "/api/v1/auth/verify"


@router.get("/verify")
def verify(request: Request):
    """nginx's auth_request: may this browser have X-Original-URI, which needs X-TM-Required-Role?

    Only nginx's internal /_auth locations call verify, and only they set X-TM-Required-Role (viewer or admin);
    nginx refuses the path from the network and clears the header on /api/. Any other call gets 404 and no identity.
    401 with X-TM-Redirect sends the browser to /setup, /login?next=..., /welcome (an admin, while a new license
    agreement waits), or /waiting (a viewer, meanwhile). 403 is forbidden.
    200 carries X-TM-User, X-TM-Role, X-TM-Frigate-Secret, and for admins X-TM-NR-Token.
    """
    required = request.headers.get("x-tm-required-role")
    # The exact path too: Starlette's route pattern ends in $, which also matches before a trailing newline (%0A)
    if required not in ROLES or request.scope["path"] != VERIFY_PATH:
        raise ApiError(404, "not_found", "Not Found")

    app_state = request.app.state
    device = Device(app_state.state)
    if not device.is_claimed():
        raise ApiError(401, "not_claimed", "Set up this device first.", headers={"X-TM-Redirect": "/setup"})

    found = session_user(request)
    if found is None:
        target = quote(safe_next(request.headers.get("x-original-uri", "/")), safe="/")
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
