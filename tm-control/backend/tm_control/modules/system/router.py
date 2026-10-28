"""The device: the home page's device card and app tiles (GET /system/device), the Device page's facts (GET
/system/info) and diagnostics download (GET /system/diagnostics, admins), reboot and power off (admins, through
polkit), and the Linux password of the user who installed Traffic Monitor (POST /system/password), which the
system-password root job sets."""

import logging
import re
import socket
import string
from datetime import datetime
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from tm_control.adapters import systemd
from tm_control.core.auth import Audit, User, check_password_rules
from tm_control.core.errors import ApiError
from tm_control.modules.auth.deps import current_user, require_admin
from tm_control.modules.system import diagnostics
from tm_control.modules.system.info import SystemInfo, system_info

log = logging.getLogger(__name__)

router = APIRouter(prefix="/system", tags=["system"])

SERIAL_PATH = Path("/sys/firmware/devicetree/base/serial-number")
FAKE_SERIAL = "0000000012345678"
FAKE_HOSTNAME = "tm-fake"  # fake mode runs on a laptop, whose own name shouldn't end up in screenshots

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


def hostname(app_state) -> str:
    return FAKE_HOSTNAME if app_state.settings.fake else socket.gethostname()


def serial(app_state) -> str:
    return FAKE_SERIAL if app_state.settings.fake else read_serial()


def safe_hostname(name: str) -> str:
    """The hostname with only [A-Za-z0-9.-], for a file name and the diagnostics header."""
    return re.sub(r"[^A-Za-z0-9.-]", "", name) or "device"


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
        "hostname": hostname(app_state),
        "serial": serial(app_state),
        "tm_version": manifest.tm_version,
        "time": datetime.now().astimezone().isoformat(timespec="seconds"),
        "apps": apps,
        "theme": {"font": manifest.homepage.font, "colors": manifest.homepage.colors},
    }


@router.get("/info", response_model=SystemInfo)
def info(request: Request, user: User = Depends(current_user)):
    app_state = request.app.state
    return system_info(app_state, hostname(app_state), serial(app_state))


@router.get("/diagnostics", response_class=PlainTextResponse)
def diagnostics_text(request: Request, admin: User = Depends(require_admin)):
    """The diagnostics text as a download, with every secret redacted."""
    app_state = request.app.state
    name = safe_hostname(hostname(app_state))
    now = datetime.now().astimezone()
    text = diagnostics.build(app_state, system_info(app_state, hostname(app_state), serial(app_state)), name, now)
    filename = f"tm-diagnostics-{name}-{now:%Y%m%d-%H%M%S}.txt"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store"}
    return PlainTextResponse(text, headers=headers)


class PowerQueued(BaseModel):
    action: Literal["reboot", "power_off"]


def _power(action: str) -> None:
    """Reboot or power off, run after the 202 has been sent. Only the exit status is logged, never the output."""
    verb = "reboot" if action == "reboot" else "poweroff"
    try:
        result = systemd.reboot() if action == "reboot" else systemd.power_off()
    except Exception as exc:
        log.error("systemctl %s failed (%s)", verb, type(exc).__name__)
        return
    if result.returncode != 0 or result.timed_out:
        log.error("systemctl %s failed with exit status %s", verb, result.returncode)


def _queue_power(request: Request, background: BackgroundTasks, admin: User, action: str) -> dict:
    """Ask logind first: once the 202 has gone, the UI says "Rebooting", so a refusal must come before it."""
    app_state = request.app.state
    if not app_state.settings.fake and not systemd.can("CanReboot" if action == "reboot" else "CanPowerOff"):
        doing = "reboot" if action == "reboot" else "shut down"
        raise ApiError(
            409,
            "conflict",
            f"The device can't {doing} right now: something, such as an update, is holding it off. "
            "Try again in a few minutes.",
        )
    Audit(app_state.state).record(admin.id, f"system.{action}")
    if not app_state.settings.fake:
        background.add_task(_power, action)
    return {"action": action}


@router.post("/reboot", status_code=202, response_model=PowerQueued)
def reboot(request: Request, background: BackgroundTasks, admin: User = Depends(require_admin)):
    return _queue_power(request, background, admin, "reboot")


@router.post("/power-off", status_code=202, response_model=PowerQueued)
def power_off(request: Request, background: BackgroundTasks, admin: User = Depends(require_admin)):
    return _queue_power(request, background, admin, "power_off")


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
