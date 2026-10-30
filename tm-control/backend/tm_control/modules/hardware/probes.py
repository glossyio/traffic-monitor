"""How tm-control finds each AI accelerator the installer knows, and the host's hardware listings, read at most once
per status report through the Context's probe memo."""

import re
from typing import NamedTuple

from tm_control.adapters import hardware
from tm_control.core.checks import Context

USB_IDS = "hardware.usb_ids"
LSPCI = "hardware.lspci"
RADAR_PORTS = "hardware.radar_ports"


class Probe(NamedTuple):
    bus: str  # "usb" (the USB devices' vvvv:pppp ids) or "pci" (lspci -nn)
    pattern: str  # a regular expression that finds it in the bus listing
    module: str | None  # the kernel module its driver needs, if any
    title: str = ""


# Keyed like the manifest's probes.detectors (tmsetup_detectors). A Coral USB is 1a6e:089a until its runtime loads
# the firmware, and 18d1:9302 after (#217). The Hailo probe finds a Hailo-8 as well as a Hailo-8L.
DETECTOR_PROBES = {
    "edgetpu_usb": Probe(bus="usb", pattern=r"1a6e:089a|18d1:9302", module=None, title="Coral USB Accelerator"),
    "edgetpu_pci": Probe(bus="pci", pattern=r"(?i)coral|1ac1:089a", module="apex", title="Coral PCIe Accelerator"),
    "hailo8l": Probe(bus="pci", pattern=r"(?i)hailo", module="hailo_pci", title="Hailo accelerator"),
}


def bus_listing(context: Context, bus: str) -> str | None:
    """The USB devices' ids, or lspci -nn's output; None when they couldn't be read."""
    if bus == "usb":
        return context.probe(USB_IDS, hardware.usb_ids)
    return context.probe(LSPCI, hardware.lspci)


def present(context: Context, probe: Probe) -> bool | None:
    listing = bus_listing(context, probe.bus)
    return None if listing is None else re.search(probe.pattern, listing) is not None


def radar_names(context: Context) -> dict[str, str]:
    """Each radar path's env name, the radar's name in config.yml and in Node-RED: from node-red-tm.env, or, when
    that can't be read, the template's TM_RADAR_SERIAL_PORT_0N for the manifest's Nth radar path."""
    ports = context.probe(RADAR_PORTS, lambda: hardware.radar_ports(context.manifest.codedir))
    if ports is None:
        paths = context.manifest.probes.radar_paths
        return {path: f"TM_RADAR_SERIAL_PORT_{index:02d}" for index, path in enumerate(paths)}
    names: dict[str, str] = {}
    for name, path in sorted(ports.items()):
        names.setdefault(path, name)
    return names
