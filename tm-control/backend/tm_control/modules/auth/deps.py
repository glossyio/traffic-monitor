"""FastAPI dependencies and helpers for the logged-in user and their session cookie."""

import math
import time

from fastapi import Depends, Request, Response

from tm_control.core.auth import COOKIE_NAME, MAX_AGE, SessionClaims, User, Users
from tm_control.core.errors import ApiError


def client_ip(request: Request) -> str:
    """The browser's address. uvicorn's proxy headers take it from nginx's X-Forwarded-For."""
    return request.client.host if request.client else "unknown"


def rate_limited(wait: float, message: str) -> ApiError:
    """The 429 for an attempt made while its backoff key must still wait `wait` seconds."""
    seconds = math.ceil(wait)
    return ApiError(
        429, "rate_limited", message, detail={"retry_after": seconds}, headers={"Retry-After": str(seconds)}
    )


def session_user(request: Request) -> tuple[User, SessionClaims] | None:
    """The user the request's cookie names, if the cookie is valid and the user still has that session epoch.

    The user is read from the state database on every call, so a deleted user or a bumped epoch takes effect at once.
    """
    cookie = request.cookies.get(COOKIE_NAME)
    claims = request.app.state.sessions.load(cookie) if cookie else None
    if claims is None:
        return None
    user = Users(request.app.state.state).get(claims.uid)
    if user is None or user.session_epoch != claims.epoch:
        return None
    return user, claims


def set_session_cookie(request: Request, response: Response, user: User) -> None:
    """Give the browser a new cookie for the user's current epoch."""
    cookie = request.app.state.sessions.issue(user.id, user.session_epoch)
    response.set_cookie(COOKIE_NAME, cookie, max_age=MAX_AGE, path="/", httponly=True, samesite="lax")


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/", httponly=True, samesite="lax")


def refresh_if_old(request: Request, response: Response, user: User, claims: SessionClaims) -> None:
    """Re-issue a cookie that is more than a day old, so a session in use doesn't end at 7 days."""
    if request.app.state.sessions.needs_refresh(claims, time.time()):
        set_session_cookie(request, response, user)


def current_user(request: Request, response: Response) -> User:
    """The logged-in user (401 `unauthenticated` without one). Re-issues an old cookie on the endpoint's response.

    The re-issued cookie reaches the browser only when the endpoint lets FastAPI build the response (it returns
    data, or None with a status_code). An endpoint that returns its own Response object must copy the cookie over.
    """
    found = session_user(request)
    if found is None:
        raise ApiError(401, "unauthenticated", "Log in to continue.")
    user, claims = found
    refresh_if_old(request, response, user, claims)
    return user


def require_admin(user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise ApiError(403, "forbidden", "Only an admin can do this.")
    return user
