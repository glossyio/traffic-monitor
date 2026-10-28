"""The hardware as the host shows it: the USB devices' ids and the PCI device list, loaded kernel modules, device
paths, the devices the Quadlet units pass to their containers, the HEVC decoder, and the radar ports node-red-tm.env
names.

None of these raises: a source that can't be read gives None.
"""

import os
import re
from pathlib import Path

from tm_control.adapters.command import run

UNIT_DIR = Path("/etc/containers/systemd")
# Not lsusb: tm-control.service's RestrictAddressFamilies blocks the netlink socket libusb needs, so lsusb fails
# there ("unable to initialize libusb: -99"). sysfs has the same ids.
USB_DEVICES = Path("/sys/bus/usb/devices")
PROC_MODULES = Path("/proc/modules")
MEDIA_DEVICES = Path("/sys/bus/media/devices")  # mediaN/model names each media device; /dev/mediaN is its node
HEVC_MODEL = "rpi-hevc-dec"
# Only these lines of node-red-tm.env are read: the rest of the file holds secrets.
RADAR_PORT = re.compile(r"(TM_RADAR_SERIAL_PORT_\d+)=(.*)")

PROBE_TIMEOUT = 4  # seconds; these are status probes
PROBE_MAX_OUTPUT = 65536


def _listing(argv: list[str]) -> str | None:
    try:
        result = run(argv, timeout=PROBE_TIMEOUT, max_output=PROBE_MAX_OUTPUT)
    except OSError:  # the program is missing, as lspci is on many laptops
        return None
    if result.returncode != 0 or result.timed_out:
        return None
    return result.stdout


def _read_id(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip().lower()
    except OSError:
        return None


def usb_ids() -> str | None:
    """A vvvv:pppp line (idVendor:idProduct, as lsusb shows them) for each USB device; None when sysfs can't be
    read. Entries without both files, such as interfaces, are skipped."""
    try:
        entries = sorted(USB_DEVICES.iterdir())
    except OSError:
        return None
    lines = []
    for entry in entries:
        vendor, product = _read_id(entry / "idVendor"), _read_id(entry / "idProduct")
        if vendor and product:
            lines.append(f"{vendor}:{product}\n")
    return "".join(sorted(lines))


def lspci() -> str | None:
    """lspci -nn: each device with its [vendor:device] ids."""
    return _listing(["lspci", "-nn"])


def module_loaded(name: str) -> bool | None:
    try:
        text = PROC_MODULES.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    return any(line.split(" ", 1)[0] == name for line in text.splitlines())


def path_exists(path: str) -> bool:
    return os.path.exists(path)


def resolve(path: str) -> str:
    """readlink -f"""
    return os.path.realpath(path)


def unit_adds_device(unit_file: str, device: str) -> bool | None:
    """Whether UNIT_DIR/<unit_file> has the line AddDevice=<device>; device is the whole value, such as
    /dev/apex_0:/dev/apex_0. None when the unit file can't be read."""
    try:
        text = (UNIT_DIR / unit_file).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    return f"AddDevice={device}" in (line.strip() for line in text.splitlines())


def _scan_hevc() -> str | None:
    try:
        devices = sorted(MEDIA_DEVICES.iterdir())
    except OSError:
        return None
    for device in devices:
        try:
            model = (device / "model").read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            continue
        if model == HEVC_MODEL:
            return f"/dev/{device.name}"
    return None


def hevc_decoder(hevc_device: str) -> dict[str, str | None]:
    """symlink: the node the udev symlink (the manifest's hevc_device) leads to, or None when it's missing or
    dangling; scanned: the /dev/mediaN whose model is rpi-hevc-dec on this boot, or None."""
    return {"symlink": resolve(hevc_device) if path_exists(hevc_device) else None, "scanned": _scan_hevc()}


def radar_ports(codedir) -> dict[str, str] | None:
    """The TM_RADAR_SERIAL_PORT_NN=<path> lines of <codedir>/node-red-tm/node-red-tm.env, by name; None when the
    file can't be read. No other line is kept."""
    try:
        text = (Path(codedir) / "node-red-tm" / "node-red-tm.env").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    ports = {}
    for line in text.splitlines():
        match = RADAR_PORT.fullmatch(line.strip())
        if match:
            ports[match[1]] = match[2].strip().strip("\"'")
    return ports
