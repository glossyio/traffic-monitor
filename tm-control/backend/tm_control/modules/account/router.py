"""The account page (/account) and the admin's user list (/users), where an admin adds and removes viewers.

Accounts made here are always viewers; the one admin comes from claiming the device. Every change is audited.
"""

import logging
import time
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Request, Response
from pydantic import BaseModel, Field

from tm_control.core.auth import Audit, User, Users, check_password_rules
from tm_control.core.errors import ApiError
from tm_control.modules.auth.deps import client_ip, current_user, rate_limited, require_admin, set_session_cookie

log = logging.getLogger(__name__)

router = APIRouter(tags=["account"])

UserId = Annotated[int, Path(ge=1, le=2**63 - 1)]  # SQLite's integer range: a larger id would be a 500, not a 404


@router.get("/account")
def account(user: User = Depends(current_user)):
    return {"user": user}


class PasswordChange(BaseModel):
    current_password: str = Field(max_length=1024)
    new_password: str = Field(max_length=1024)


@router.post("/account/password", status_code=204)
def change_password(body: PasswordChange, request: Request, response: Response, user: User = Depends(current_user)):
    """Change one's own password. Ends the user's other sessions; this browser gets a new cookie and stays in."""
    check_password_rules(body.new_password)
    app_state = request.app.state
    ip = client_ip(request)
    # The login backoff and its keys: a wrong current password here is a password guess like a failed login.
    keys = (f"ip:{ip}", f"user:{user.username}")
    backoff = app_state.login_backoff
    wait = max(backoff.check(key, time.monotonic()) for key in keys)
    if wait > 0:
        raise rate_limited(wait, "Too many wrong passwords. Try again later.")
    for key in keys:
        backoff.record_failure(key, time.monotonic())
    users = Users(app_state.state)
    if users.authenticate(user.username, body.current_password) is None:
        log.warning("wrong current password from %s for %r", ip, user.username)
        raise ApiError(401, "unauthenticated", "The current password is wrong.")
    for key in keys:
        backoff.reset(key)

    users.set_password(user.id, body.new_password)
    Audit(app_state.state).record(user.id, "account.password")
    updated = users.get(user.id)
    if updated is not None:  # None only if an admin deleted the user meanwhile
        set_session_cookie(request, response, updated)


@router.get("/users")
def list_users(request: Request, admin: User = Depends(require_admin)):
    return {"users": Users(request.app.state.state).list()}


class NewUser(BaseModel):
    username: str = Field(max_length=64)
    password: str = Field(max_length=1024)


@router.post("/users", status_code=201)
def create_user(body: NewUser, request: Request, admin: User = Depends(require_admin)):
    app_state = request.app.state
    user = Users(app_state.state).create(body.username, body.password, "viewer")
    Audit(app_state.state).record(admin.id, "user.create", user.username)
    return {"user": user}


def _other_user(users: Users, user_id: int, admin: User, refusal: str) -> User:
    """The user with that id, who must not be the admin acting (422 with `refusal`)."""
    user = users.get(user_id)
    if user is None:
        raise ApiError(404, "not_found", "There is no such user.")
    if user.id == admin.id:
        raise ApiError(422, "validation", refusal)
    return user


@router.delete("/users/{user_id}", status_code=204)
def delete_user(user_id: UserId, request: Request, admin: User = Depends(require_admin)):
    app_state = request.app.state
    users = Users(app_state.state)
    user = _other_user(users, user_id, admin, "You can't delete your own account.")
    if user.role == "admin" and users.count_admins() <= 1:
        raise ApiError(422, "validation", "The device must keep at least one admin.")
    users.delete(user.id)
    Audit(app_state.state).record(admin.id, "user.delete", user.username)


class NewPassword(BaseModel):
    new_password: str = Field(max_length=1024)


@router.post("/users/{user_id}/password", status_code=204)
def reset_password(user_id: UserId, body: NewPassword, request: Request, admin: User = Depends(require_admin)):
    """Set another user's password and end their sessions. Admins change their own on the account page, which asks
    for the current password, so a session left open can't be used to take the account over."""
    app_state = request.app.state
    users = Users(app_state.state)
    user = _other_user(users, user_id, admin, "Change your own password on the account page.")
    users.set_password(user.id, body.new_password)
    Audit(app_state.state).record(admin.id, "user.password", user.username)
