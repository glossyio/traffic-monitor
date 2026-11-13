"""What the owner agreed to share: one row per change, and the latest row per target and consent is the answer.

A target is 'maintainer' (the maintainer's server) or 'own:<host>' (an operator's own server). Nothing in this module
logs or audits a host; the host is part of a target key and stays in the database.
"""

from pydantic import BaseModel

from tm_control.core.auth import _reading, _timestamp, _writing
from tm_control.core.state import State

CONSENTS = ("share_data", "exact_location", "public_map")
MAINTAINER = "maintainer"
OWN_SERVER = "own-server"  # a row's notice_version for a consent given for an operator's own server
PRE_CONSENT = "pre-consent"  # a row's notice_version for a share that began before consent was recorded

_REVIEW_KEY = "sharing_review_needed"


def normalize_host(value) -> str | None:
    """The host as Node-RED compares it: trimmed, lower-case, without a leading http:// or https:// and without one
    trailing slash. None for a blank or non-string value."""
    if not isinstance(value, str):
        return None
    host = value.strip().lower()
    for scheme in ("http://", "https://"):
        if host.startswith(scheme):
            host = host[len(scheme):]
            break
    if host.endswith("/"):
        host = host[:-1]
    return host or None


def target_key(host, maintainer_host: str) -> str | None:
    """'maintainer' when `host` is the maintainer's, 'own:<host>' for any other, None for no host."""
    normalized = normalize_host(host)
    if normalized is None:
        return None
    if normalized == normalize_host(maintainer_host):
        return MAINTAINER
    return "own:" + normalized


class Consent(BaseModel):
    consent: str
    granted: bool
    notice_version: str
    at: str
    user_id: int | None
    note: str | None


class Consents:
    def __init__(self, state: State):
        self.state = state

    def latest(self, target: str) -> dict[str, Consent]:
        """The newest row per consent for `target`; a consent never recorded is absent. Rows are ordered by id
        (insertion order), not by time: a unit's clock can step back, and rows are never deleted."""
        with _reading(self.state) as con:
            rows = con.execute(
                "SELECT consent, granted, notice_version, at, user_id, note FROM sharing_consents "
                "WHERE target = ? ORDER BY id",
                (target,),
            ).fetchall()
        latest: dict[str, Consent] = {}
        for row in rows:  # oldest first, so a later row replaces an earlier one
            latest[row["consent"]] = Consent(**{**dict(row), "granted": bool(row["granted"])})
        return latest

    def granted(self, target: str, consent: str) -> bool:
        found = self.latest(target).get(consent)
        return found is not None and found.granted

    def record(
        self,
        target: str,
        consent: str,
        granted: bool,
        notice_version: str,
        user_id: int | None,
        note: str | None = None,
        now: float | None = None,
    ) -> None:
        with _writing(self.state) as con:
            con.execute(
                "INSERT INTO sharing_consents (target, consent, granted, notice_version, at, user_id, note) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (target, consent, int(granted), notice_version, _timestamp(now), user_id, note),
            )

    def withdraw_all(self, target: str, user_id: int | None, note: str | None, now: float | None = None) -> list[str]:
        """Withdraw every consent whose latest row is granted, in one transaction; return their names."""
        at = _timestamp(now)
        with _writing(self.state) as con:
            rows = con.execute(
                "SELECT consent, granted, notice_version FROM sharing_consents WHERE target = ? ORDER BY id",
                (target,),
            ).fetchall()
            latest = {row["consent"]: row for row in rows}
            withdrawn = [name for name in CONSENTS if name in latest and latest[name]["granted"]]
            for name in withdrawn:
                con.execute(
                    "INSERT INTO sharing_consents (target, consent, granted, notice_version, at, user_id, note) "
                    "VALUES (?, ?, 0, ?, ?, ?, ?)",
                    (target, name, latest[name]["notice_version"], at, user_id, note),
                )
        return withdrawn

    def review_needed(self) -> bool:
        with _reading(self.state) as con:
            row = con.execute("SELECT value FROM device WHERE key = ?", (_REVIEW_KEY,)).fetchone()
        return row is not None and row["value"] == "1"

    def set_review_needed(self, needed: bool) -> None:
        with _writing(self.state) as con:
            con.execute(
                "INSERT OR REPLACE INTO device (key, value) VALUES (?, ?)", (_REVIEW_KEY, "1" if needed else "0")
            )
