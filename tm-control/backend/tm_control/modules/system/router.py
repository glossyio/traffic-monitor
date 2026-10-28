"""The device: the home page's device card and app tiles (GET /system/device), and the Linux password of the user who
installed Traffic Monitor (POST /system/password), which the system-password root job sets."""

import socket
import string
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from tm_control.core.auth import Audit, User, check_password_rules
from tm_control.core.errors import ApiError
from tm_control.modules.auth.deps import current_user, require_admin

router = APIRouter(prefix="/system", tags=["system"])

SERIAL_PATH = Path("/sys/firmware/devicetree/base/serial-number")
FAKE_SERIAL = "0000000012345678"

# The home page's app tiles, in order: (revproxy location file, id, path, title, admin_only). A tile shows only when
# tmsetup installed its location (the manifest's revproxy_locations); viewers don't see admin_only tiles.
APPS = [
    ("dashboard.conf", "dashboard", "/dashboard/", "Dashboard", False),
    ("frigate.conf", "frigate", "/frigate/", "Frigate", False),
    ("legacy-ui.conf", "legacy-ui", "/ui/", "Legacy Dashboard", False),
    ("nodered.conf", "nodered", "/nr/", "Node-RED editor", True),
    ("go2rtc.conf", "feeds", "/feeds/", "Camera feeds", True),
    ("cockpit.conf", "cockpit", "/system/", "Cockpit", True),
]


def read_serial(path: Path = SERIAL_PATH) -> str:
    """The Pi's serial number from the devicetree, which pads it with a NUL; "unknown" if it can't be read."""
    try:
        text = Path(path).read_bytes().decode("ascii", errors="replace")
    except OSError:
        return "unknown"
    return text.strip("\x00" + string.whitespace) or "unknown"


@router.get("/device")
def device(request: Request, user: User = Depends(current_user)):
    app_state = request.app.state
    manifest = app_state.manifest
    installed = set(manifest.revproxy_locations)
    apps = [
        {"id": app_id, "path": path, "title": title, "admin_only": admin_only}
        for location, app_id, path, title, admin_only in APPS
        if location in installed and (user.role == "admin" or not admin_only)
    ]
    return {
        "hostname": socket.gethostname(),
        "serial": FAKE_SERIAL if app_state.settings.fake else read_serial(),
        "tm_version": manifest.tm_version,
        "time": datetime.now().astimezone().isoformat(timespec="seconds"),
        "apps": apps,
        "theme": {"font": manifest.homepage.font, "colors": manifest.homepage.colors},
    }


class SystemPassword(BaseModel):
    password: str = Field(max_length=1024)


@router.post("/password", status_code=202)
def set_system_password(body: SystemPassword, request: Request, admin: User = Depends(require_admin)):
    """Start the job that sets the installing user's Linux password; the UI polls GET /jobs/{id} for the outcome."""
    check_password_rules(body.password)
    # chpasswd reads one user:password line, so a line break would end the password early (or start another line).
    if any(char in body.password for char in "\n\r\x00"):
        raise ApiError(422, "validation", "A password can't contain line breaks.")
    try:
        body.password.encode("utf-8")  # FastAPI's body validation refuses a lone surrogate today; don't rely on it
    except UnicodeEncodeError:
        raise ApiError(422, "validation", "The password is not valid text.") from None
    app_state = request.app.state
    request_body = {"username": app_state.manifest.installing_user, "password": body.password}
    job = app_state.jobs.start("system-password", request_body, admin.id)
    Audit(app_state.state).record(admin.id, "system.password")
    return {"id": job.id}
