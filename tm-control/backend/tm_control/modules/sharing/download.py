"""The Sharing page's download card: what it shows an admin, and the link its plain download starts from.

The size is Node-RED's (its status's database_bytes, read for the server's state already); the control app never opens
tmdb. The count is of the places the device has been at that have an exact location, which a copy with them would hold.
The link is made as POST /auth/download-link makes one, for the name the Dashboard's download sends and "Validate
filenames, setup tar" takes for the whole database. Nothing here logs a link or a token.
"""

import time

from pydantic import BaseModel

from tm_control.adapters.nodered import NodeRedError
from tm_control.core.auth import DOWNLOAD_PATH, DOWNLOAD_TOKEN, User
from tm_control.core.errors import ApiError
from tm_control.modules.location.places import Places
from tm_control.modules.location.router import NODERED_MESSAGES

DATABASE_FILES = "/db/tmdb.sqlite"


class DownloadFacts(BaseModel):
    database_bytes: int | None  # None when Node-RED didn't answer or gave anything but a whole number from 0
    exact_places: int  # the places in use or used that have both coordinates


def database_bytes(report: dict | None) -> int | None:
    """The report's database_bytes when it is a whole number from 0 up; anything else is no size, not an error (an
    older Node-RED leaves the key out)."""
    if not isinstance(report, dict):
        return None
    size = report.get("database_bytes")
    if isinstance(size, int) and not isinstance(size, bool) and size >= 0:
        return size
    return None


def facts(app_state, report: dict | None) -> DownloadFacts:
    # The store as it is, without the reconcile GET /surveys runs: the copy's own route runs it before it reads them.
    return DownloadFacts(
        database_bytes=database_bytes(report), exact_places=len(Places(app_state.state).located())
    )


def link(app_state, admin: User, address: str) -> str:
    """A one-time /storefiles link to the whole database, once Node-RED answers its status (so a stopped Node-RED is a
    message on the card, not nginx's error page after the browser has left)."""
    try:
        app_state.nodered.report()
    except NodeRedError as error:
        text = NODERED_MESSAGES.get(error.code, "Node-RED answered an error.")
        raise ApiError(502, "nodered_error", f"The download wasn't started. {text}") from None
    token = app_state.download_grants.issue(admin, address, DATABASE_FILES, time.monotonic())
    return f"{DOWNLOAD_PATH}?files={DATABASE_FILES}&{DOWNLOAD_TOKEN}={token}"
