"""Who may use the device: passwords, session cookies, the Node-RED editor token, login backoff, the setup code,
and the users, claim, EULA, and audit records in tm-control's state database.

Passwords and the setup code are hashed with argon2id and compared only through argon2's verifier.
"""

import base64
import hashlib
import hmac
import json
import re
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Literal, NamedTuple

import argon2
from itsdangerous import BadSignature, TimestampSigner, URLSafeTimedSerializer
from pydantic import BaseModel, Field

from tm_control.core.errors import ApiError
from tm_control.core.state import State

COOKIE_NAME = "tm_session"
MAX_AGE = 7 * 86400  # a session cookie's lifetime, in seconds
REFRESH_AFTER = 86400  # re-issue a cookie once it is older than this
ROLES = ("viewer", "admin")  # in rising order of rights

USERNAME_RULE = re.compile(r"[a-z0-9._-]{3,32}")
PASSWORD_MIN, PASSWORD_MAX = 10, 256

_hasher = argon2.PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(hash: str, password: str) -> bool:
    try:
        return _hasher.verify(hash, password)
    except (argon2.exceptions.VerificationError, argon2.exceptions.InvalidHashError):
        return False


# A hash no password matches, verified for unknown usernames so they take as long as a wrong password. Made at
# import, so the first such login doesn't also pay for hashing it.
_DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


def check_password_rules(password: str) -> None:
    if not PASSWORD_MIN <= len(password) <= PASSWORD_MAX:
        raise ApiError(422, "validation", f"A password must be {PASSWORD_MIN} to {PASSWORD_MAX} characters long.")


def check_username_rules(username: str) -> None:
    """Usernames are lowercased on input, so the rule applies to the lowercased form."""
    if not USERNAME_RULE.fullmatch(username.lower()):
        raise ApiError(
            422, "validation", "A username must be 3 to 32 characters: letters, digits, dots, dashes, underscores."
        )


def _clean_username(username: str) -> str:
    check_username_rules(username)
    return username.lower()


# Session cookies


class SessionClaims(NamedTuple):
    uid: int
    epoch: int  # must equal the user's session_epoch; bumping it ends every session the user has
    iat: int  # issued at, Unix time


class _ClockSigner(TimestampSigner):
    """itsdangerous's timestamp signer, with the clock passed in so tests can set it."""

    def __init__(self, *args, now: float, **kwargs):
        super().__init__(*args, **kwargs)
        self._now = now

    def get_timestamp(self) -> int:
        return int(self._now)


class Sessions:
    def __init__(self, secret: str):
        self._secret = secret

    def _serializer(self, now: float) -> URLSafeTimedSerializer:
        return URLSafeTimedSerializer(
            self._secret, salt=COOKIE_NAME, signer=_ClockSigner, signer_kwargs={"now": now}
        )

    def issue(self, user_id: int, epoch: int, now: float | None = None) -> str:
        now = time.time() if now is None else now
        return self._serializer(now).dumps([user_id, epoch, int(now)])

    def load(self, cookie: str, now: float | None = None) -> SessionClaims | None:
        """The cookie's claims, or None when its signature is bad or it is more than MAX_AGE old."""
        now = time.time() if now is None else now
        try:
            payload = self._serializer(now).loads(cookie, max_age=MAX_AGE)
        except BadSignature:  # also covers an expired or future timestamp
            return None
        if not (isinstance(payload, list) and len(payload) == 3 and all(type(v) is int for v in payload)):
            return None
        return SessionClaims(*payload)

    def needs_refresh(self, claims: SessionClaims, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        return now - claims.iat > REFRESH_AFTER


# The Node-RED editor token


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


class NodeRedToken:
    """A short-lived token nginx hands to the Node-RED editor; settings.js checks it with the same key.

    The format is base64url(JSON {"u", "r", "exp"}) "." base64url(HMAC-SHA256(key, first part)), without padding.
    """

    def __init__(self, key: str):
        self._key = key.encode()

    def _sign(self, body: str) -> str:
        return _b64(hmac.new(self._key, body.encode("ascii"), hashlib.sha256).digest())

    def mint(self, username: str, role: str, now: float | None = None, ttl: int = 300) -> str:
        now = time.time() if now is None else now
        claims = {"u": username, "r": role, "exp": int(now) + ttl}
        body = _b64(json.dumps(claims, separators=(",", ":")).encode())
        return f"{body}.{self._sign(body)}"

    def verify(self, token: str, now: float | None = None) -> dict | None:
        now = time.time() if now is None else now
        body, dot, sig = token.partition(".")
        if not dot or not body.isascii() or not hmac.compare_digest(sig.encode(), self._sign(body).encode()):
            return None
        try:
            claims = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        except ValueError:
            return None
        if not isinstance(claims, dict) or not isinstance(claims.get("exp"), int) or now >= claims["exp"]:
            return None
        return claims


# Login backoff


class Backoff:
    """Failure counts per key (such as "ip:<address>" or "user:<name>"), in memory.

    After `threshold` failures, the next attempt must wait base ** (failures - threshold + 1) seconds after the
    last failure, at most `cap`. A key is forgotten FORGET_AFTER seconds after its last failure.
    """

    FORGET_AFTER = 900.0

    def __init__(self, threshold: int = 5, base: float = 2.0, cap: float = 300.0):
        self.threshold = threshold
        self.base = base
        self.cap = cap
        self._failures: dict[str, tuple[int, float]] = {}  # key -> (count, time of the last failure)
        self._lock = threading.Lock()

    def __len__(self):
        return len(self._failures)

    def check(self, key: str, now: float) -> float:
        """Seconds to wait before the next attempt; 0 when it's allowed now."""
        with self._lock:
            count, last = self._failures.get(key, (0, now))
        if count < self.threshold or now - last >= self.FORGET_AFTER:
            return 0.0
        exponent = min(count - self.threshold + 1, 32)  # past the cap long before; keeps base ** n from overflowing
        wait = min(self.base ** exponent, self.cap)
        return max(0.0, last + wait - now)

    def record_failure(self, key: str, now: float) -> None:
        with self._lock:
            for old in [k for k, (_, last) in self._failures.items() if now - last >= self.FORGET_AFTER]:
                del self._failures[old]
            count, _ = self._failures.get(key, (0, now))
            self._failures[key] = (count + 1, now)

    def reset(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)


# The setup code


class SetupCode:
    """The one-time code that claims an unclaimed device: 8 characters as XXXX-XXXX, without 0, O, 1, or I."""

    ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

    @staticmethod
    def generate() -> str:
        code = "".join(secrets.choice(SetupCode.ALPHABET) for _ in range(8))
        return f"{code[:4]}-{code[4:]}"

    @staticmethod
    def normalize(text: str) -> str:
        return re.sub(r"[\s-]", "", text).upper()

    @staticmethod
    def hash_code(code: str) -> str:
        return hash_password(SetupCode.normalize(code))

    @staticmethod
    def verify_code(hash: str, code: str) -> bool:
        return verify_password(hash, SetupCode.normalize(code))


# Records in the state database


def _timestamp(now: float | None = None) -> str:
    return datetime.fromtimestamp(time.time() if now is None else now, timezone.utc).isoformat(timespec="seconds")


@contextmanager
def _reading(state: State):
    con = state.connect()
    try:
        yield con
    finally:
        con.close()


@contextmanager
def _writing(state: State):
    """One write transaction, holding the write lock from its start."""
    con = state.connect()
    con.isolation_level = None  # the transaction is explicit
    try:
        con.execute("BEGIN IMMEDIATE")
        try:
            yield con
            con.execute("COMMIT")
        except BaseException:
            con.execute("ROLLBACK")
            raise
    finally:
        con.close()


class User(BaseModel):
    id: int
    username: str
    role: Literal["admin", "viewer"]
    # Left out of every serialization, so the API never shows it: only the cookie check needs it.
    session_epoch: int = Field(exclude=True)
    created_at: str


_USER_COLUMNS = "id, username, role, session_epoch, created_at"


def _user(row) -> User | None:
    return None if row is None else User(**{k: row[k] for k in User.model_fields})


def _not_found():
    return ApiError(404, "not_found", "There is no such user.")


def _insert_user(con, username: str, password_hash: str, role: str, created_at: str) -> User:
    if role not in ROLES:
        raise ValueError(f"unknown role {role!r}")
    # A random first epoch, so a cookie from an earlier database (a deleted and recreated state.sqlite) never
    # matches a new user. Bumps add 1.
    epoch = secrets.randbits(62)
    try:
        cur = con.execute(
            "INSERT INTO users (username, password_hash, role, session_epoch, created_at) VALUES (?, ?, ?, ?, ?)",
            (username, password_hash, role, epoch, created_at),
        )
    except sqlite3.IntegrityError:
        raise ApiError(409, "conflict", "That username is taken.") from None
    return _user(con.execute(f"SELECT {_USER_COLUMNS} FROM users WHERE id = ?", (cur.lastrowid,)).fetchone())


class Users:
    def __init__(self, state: State):
        self.state = state

    def count_admins(self) -> int:
        with _reading(self.state) as con:
            return con.execute("SELECT count(*) FROM users WHERE role = 'admin'").fetchone()[0]

    def get(self, user_id: int) -> User | None:
        with _reading(self.state) as con:
            return _user(con.execute(f"SELECT {_USER_COLUMNS} FROM users WHERE id = ?", (user_id,)).fetchone())

    def by_username(self, username: str) -> User | None:
        with _reading(self.state) as con:
            row = con.execute(f"SELECT {_USER_COLUMNS} FROM users WHERE username = ?", (username.lower(),)).fetchone()
        return _user(row)

    def authenticate(self, username: str, password: str) -> User | None:
        """The user, if the password is theirs. An unknown username costs one argon2 verify too."""
        with _reading(self.state) as con:
            row = con.execute(
                f"SELECT {_USER_COLUMNS}, password_hash FROM users WHERE username = ?", (username.lower(),)
            ).fetchone()
        if row is None:
            verify_password(_DUMMY_HASH, password)
            return None
        return _user(row) if verify_password(row["password_hash"], password) else None

    def create(self, username: str, password: str, role: str) -> User:
        username = _clean_username(username)
        check_password_rules(password)
        password_hash = hash_password(password)  # before the transaction: argon2 is slow
        with _writing(self.state) as con:
            return _insert_user(con, username, password_hash, role, _timestamp())

    def delete(self, user_id: int) -> None:
        with _writing(self.state) as con:
            if con.execute("DELETE FROM users WHERE id = ?", (user_id,)).rowcount == 0:
                raise _not_found()

    def set_password(self, user_id: int, password: str) -> None:
        """Change the password and end the user's sessions."""
        check_password_rules(password)
        password_hash = hash_password(password)
        with _writing(self.state) as con:
            cur = con.execute(
                "UPDATE users SET password_hash = ?, session_epoch = session_epoch + 1 WHERE id = ?",
                (password_hash, user_id),
            )
            if cur.rowcount == 0:
                raise _not_found()

    def bump_epoch(self, user_id: int) -> None:
        """End every session the user has."""
        with _writing(self.state) as con:
            if con.execute("UPDATE users SET session_epoch = session_epoch + 1 WHERE id = ?", (user_id,)).rowcount == 0:
                raise _not_found()

    def list(self) -> list[User]:
        with _reading(self.state) as con:
            return [_user(row) for row in con.execute(f"SELECT {_USER_COLUMNS} FROM users ORDER BY id")]


class Device:
    """The device's claim: unclaimed until it has an admin, which the setup code creates."""

    def __init__(self, state: State):
        self.state = state

    def is_claimed(self) -> bool:
        with _reading(self.state) as con:
            return con.execute("SELECT 1 FROM users WHERE role = 'admin' LIMIT 1").fetchone() is not None

    def setup_code_hash(self) -> str | None:
        with _reading(self.state) as con:
            row = con.execute("SELECT value FROM device WHERE key = 'setup_code_hash'").fetchone()
        return None if row is None else row["value"]

    def set_setup_code_hash(self, hash: str) -> None:
        with _writing(self.state) as con:
            con.execute("INSERT OR REPLACE INTO device (key, value) VALUES ('setup_code_hash', ?)", (hash,))

    def clear_setup_code(self) -> None:
        with _writing(self.state) as con:
            con.execute("DELETE FROM device WHERE key = 'setup_code_hash'")

    def claim(self, username: str, password: str, eula_version: str, now: float | None = None) -> User:
        """Create the first admin, record their EULA acceptance, and retire the setup code, all in one step."""
        username = _clean_username(username)
        check_password_rules(password)
        password_hash = hash_password(password)
        at = _timestamp(now)
        with _writing(self.state) as con:
            if con.execute("SELECT 1 FROM users WHERE role = 'admin' LIMIT 1").fetchone() is not None:
                raise ApiError(409, "already_claimed", "This device has already been claimed.")
            user = _insert_user(con, username, password_hash, "admin", at)
            con.execute(
                "INSERT INTO eula_acceptances (version, accepted_at, user_id) VALUES (?, ?, ?)",
                (eula_version, at, user.id),
            )
            con.execute("DELETE FROM device WHERE key = 'setup_code_hash'")
            con.execute("INSERT OR REPLACE INTO device (key, value) VALUES ('claimed_at', ?)", (at,))
        return user

    def unclaim(self, new_code_hash: str) -> None:
        """Delete every user (which ends every session) and wait for a new claim with the new code."""
        with _writing(self.state) as con:
            con.execute("DELETE FROM users")
            con.execute("INSERT OR REPLACE INTO device (key, value) VALUES ('setup_code_hash', ?)", (new_code_hash,))
            con.execute("DELETE FROM device WHERE key = 'claimed_at'")

    def eula_accepted(self, version: str) -> bool:
        with _reading(self.state) as con:
            row = con.execute("SELECT 1 FROM eula_acceptances WHERE version = ? LIMIT 1", (version,)).fetchone()
        return row is not None

    def accept_eula(self, version: str, user_id: int, now: float | None = None) -> None:
        with _writing(self.state) as con:
            con.execute(
                "INSERT INTO eula_acceptances (version, accepted_at, user_id) VALUES (?, ?, ?)",
                (version, _timestamp(now), user_id),
            )


class Audit:
    def __init__(self, state: State):
        self.state = state

    def record(self, user_id: int | None, action: str, detail: str | None = None) -> None:
        with _writing(self.state) as con:
            con.execute(
                "INSERT INTO audit (at, user_id, action, detail) VALUES (?, ?, ?, ?)",
                (_timestamp(), user_id, action, detail),
            )
