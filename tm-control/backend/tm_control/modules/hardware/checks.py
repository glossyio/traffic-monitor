"""The hardware check group: each AI accelerator on the host, the HEVC decoder, and each radar, checked in layers
from the host to the app that uses it. A check's status is its first layer that fails.

Every check that isn't ok offers to re-scan, unless its cure is a restart; the next step is in its detail.
"""

from datetime import datetime, timezone
from pathlib import Path

from tm_control.adapters import hardware
from tm_control.core.checks import Check, CheckGroup, Context, Fix
from tm_control.modules.apps import probes as apps
from tm_control.modules.apps.checks import duration
from tm_control.modules.hardware import probes
from tm_control.modules.hardware.probes import DETECTOR_PROBES, Probe
from tm_control.modules.services.units import restart_fix, unit_states

RESCAN = Fix(kind="rescan", text="Re-scan hardware")
FRIGATE_UNIT = "frigate.container"
NODE_RED_UNIT = "node-red-tm.container"
BUS_NAMES = {"usb": "USB", "pci": "PCIe"}


def _check(check_id: str, title: str, status, detail: str, fix: Fix | None = None) -> Check:
    if status != "ok" and fix is None:
        fix = RESCAN
    return Check(id=check_id, title=title, status=status, detail=detail, fix=fix)


# AI accelerators


def _serves(detector, facts: dict) -> bool:
    """Whether a detector in Frigate's config is this accelerator's: the same type and, for a Coral, the same bus
    (a Coral detector without a device uses whichever Coral it finds)."""
    detector = apps.mapping(detector)
    if str(detector.get("type", "")) != str(facts.get("frigate_type")):
        return False
    if detector.get("type") != "edgetpu":
        return True
    device, bus = str(detector.get("device") or "").lower(), str(facts.get("frigate_device", "")).lower()
    return device in ("", bus) or device.startswith(f"{bus}:")


def _speed(stats_detector: dict) -> str:
    speed = stats_detector.get("inference_speed")
    if isinstance(speed, (int, float)) and not isinstance(speed, bool):
        return f"Frigate detects with it, {speed:.1f} ms per detection."
    return "Frigate detects with it."


def _detector(context: Context, kind: str, probe: Probe, facts: dict) -> Check:
    def check(status, detail, fix=None):
        return _check(f"hardware.detector.{kind}", probe.title, status, detail, fix)

    dev_path = str(facts.get("dev_path", ""))
    driver = "It's plugged in, but its driver isn't ready ({}). Re-run the installer with tmsetup.sh -t detectors."
    if not hardware.path_exists(dev_path):
        return check("error", driver.format(f"{dev_path} is missing"))
    if probe.module:
        loaded = hardware.module_loaded(probe.module)
        if loaded is None:
            return check("unknown", "The loaded kernel modules couldn't be read, so its driver couldn't be checked.")
        if not loaded:
            return check("error", driver.format(f"the {probe.module} module isn't loaded"))

    passed = hardware.unit_adds_device(FRIGATE_UNIT, f"{dev_path}:{dev_path}")
    if passed is None:
        return check("unknown", "Frigate's unit file couldn't be read, so it's unknown whether Frigate gets it.")
    if not passed:
        return check("error", "It's ready on the host, but isn't passed to Frigate. Re-run the installer with "
                              "tmsetup.sh -t detectors -t frigate.")

    config = apps.frigate_config(context)
    if config is None:
        return check("unknown", "Frigate isn't answering, so it's unknown whether Frigate uses it.")
    names = [name for name, detector in apps.mapping(config.get("detectors")).items() if _serves(detector, facts)]
    if not names:
        return check("error", f"Frigate gets it, but it isn't in Frigate's config. Add a detector of type "
                              f"{facts.get('frigate_type')} with device {facts.get('frigate_device')} to the "
                              "detectors section of Frigate's config.")

    stats = apps.frigate_stats(context)
    if stats is None:
        return check("unknown", "Frigate didn't give its stats, so it's unknown whether its detector is running.")
    running = [apps.mapping(apps.mapping(stats.get("detectors")).get(name)) for name in names]
    running = [detector for detector in running if detector.get("pid")]
    if not running:
        return check("error", "It's in Frigate's config, but Frigate's detector for it isn't running. Restart "
                              "Frigate; if that doesn't help, download the diagnostics on the Device page.",
                     restart_fix("frigate.service"))
    return check("ok", _speed(running[0]))


def _no_accelerator(context: Context) -> Check:
    def check(status, detail):
        return _check("hardware.detector.none", "No AI accelerator", status, detail)

    config = apps.frigate_config(context)
    if config is None:
        return check("unknown", "No AI accelerator is plugged in, and Frigate isn't answering, so it's unknown "
                                "whether it detects on the CPU.")
    types = [apps.mapping(detector).get("type") for detector in apps.mapping(config.get("detectors")).values()]
    if "cpu" in types:
        return check("warn", "No AI accelerator is plugged in, so Frigate detects on the CPU, which is slow. "
                             "A Coral or Hailo accelerator makes detection much faster.")
    return check("error", "No AI accelerator is plugged in, and Frigate's config has no CPU detector, so Frigate "
                          "can't detect anything. Plug the accelerator back in, then re-scan.")


def detector_checks(context: Context) -> list[Check]:
    """One check for each accelerator plugged in; one for none when nothing is."""
    checks: list[Check] = []
    found = undetermined = False
    for kind, facts in context.manifest.probes.detectors.items():
        probe = DETECTOR_PROBES.get(kind)
        if probe is None:
            undetermined = True
            checks.append(_check(f"hardware.detector.{kind}", kind, "unknown",
                                 f"This version of tm-control can't check {kind} accelerators. Run the installer "
                                 "(tmsetup.sh) again to update it."))
            continue
        present = probes.present(context, probe)
        if present is None:
            undetermined = True
            checks.append(_check(f"hardware.detector.{kind}", probe.title, "unknown",
                                 f"The {BUS_NAMES[probe.bus]} device list couldn't be read, so it's unknown whether "
                                 "one is plugged in."))
        elif present:
            found = True
            checks.append(_detector(context, kind, probe, apps.mapping(facts)))
    if not found and not undetermined:
        checks.append(_no_accelerator(context))
    return checks


# The HEVC decoder


def hevc_checks(context: Context) -> list[Check]:
    """The kernel has the decoder and its udev symlink leads to it; Frigate's unit passes it, and Frigate runs."""
    symlink_path = context.manifest.probes.hevc_device
    return [_hevc_present(symlink_path), _hevc_passed(context, symlink_path)]


def _hevc_present(symlink_path: str) -> Check:
    def check(status, detail):
        return _check("hardware.hevc.present", "HEVC decoder", status, detail)

    decoder = hardware.hevc_decoder(symlink_path)
    if decoder["scanned"] is None:
        return check("error", "The kernel shows no HEVC decoder, so Frigate can't decode the camera's video. Reboot "
                              "the device from the Device page.")
    if decoder["symlink"] != decoder["scanned"]:
        return check("error", f"The decoder is {decoder['scanned']}, but its symlink {symlink_path} is stale. Reboot "
                              "the device from the Device page, or re-run the installer with tmsetup.sh -t frigate.")
    return check("ok", f"{decoder['scanned']}, reached through {symlink_path}.")


def _hevc_passed(context: Context, symlink_path: str) -> Check:
    def check(status, detail, fix=None):
        return _check("hardware.hevc.passed", "HEVC decoder in Frigate", status, detail, fix)

    passed = hardware.unit_adds_device(FRIGATE_UNIT, symlink_path)
    if passed is None:
        return check("unknown", "Frigate's unit file couldn't be read, so it's unknown whether Frigate gets the "
                                "decoder.")
    if not passed:
        return check("error", "Frigate's unit doesn't pass the decoder to Frigate. Re-run the installer with "
                              "tmsetup.sh -t frigate.")
    state = unit_states(context).get("frigate.service")
    if state is None:
        return check("unknown", "Frigate's state couldn't be read from systemd.")
    if state.get("ActiveState") != "active":
        return check("error", "Frigate gets the decoder, but isn't running. Restart Frigate.",
                     restart_fix("frigate.service"))
    return check("ok", "Passed to Frigate, which is running.")


# Radars


def _last_reading(value) -> str:
    if not isinstance(value, str):
        return "No reading yet."
    try:
        at = datetime.fromisoformat(value)
    except ValueError:
        return "No reading yet."
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    seconds = int((datetime.now(timezone.utc) - at).total_seconds())
    return f"Last reading {duration(max(0, seconds))} ago."


def _radar(context: Context, path: str, name: str | None, radars: dict | None) -> Check | None:
    def check(status, detail, fix=None):
        return _check(f"hardware.radar.{Path(path).name}", f"Radar on {path}", status, detail, fix)

    if name is None:
        configured = False
    elif radars is None:
        configured = None
    else:
        configured = apps.mapping(radars.get(name)).get("enabled") is True

    if not hardware.path_exists(path):
        if configured:
            return check("error", f"{name} is enabled in config.yml, but its radar is not plugged in. Plug it in, "
                                  f"or disable sensors.radars.{name} in config.yml.")
        return None
    passed = hardware.unit_adds_device(NODE_RED_UNIT, path)
    if passed is None:
        return check("unknown", "Node-RED's unit file couldn't be read, so it's unknown whether Node-RED gets the "
                                "radar.")
    if not passed:
        return check("error", "A radar is plugged in, but isn't passed to Node-RED. Re-run the installer with "
                              "tmsetup.sh -t node-red-tm.")
    if name is None:
        return check("warn", "A radar is plugged in, but no TM_RADAR_SERIAL_PORT_ line in node-red-tm.env names "
                             "this port, so Node-RED doesn't read it. Name it there, then restart Node-RED.")
    if configured is None:
        return check("unknown", f"config.yml couldn't be read, so it's unknown whether {name} is enabled.")
    if not configured:
        return check("warn", f"A radar is plugged in as {name}, but it isn't enabled. Enable "
                             f"sensors.radars.{name} in config.yml.")

    report = apps.nodered_report(context)
    if report is None:
        return check("unknown", "Node-RED didn't give its status, so it's unknown whether it opened the radar's "
                                "port.")
    radar = apps.mapping(apps.mapping(report.get("radars")).get(name))
    if radar.get("port_open") is not True:
        return check("error", f"Node-RED hasn't opened {name}'s port. Restart Node-RED; if that doesn't help, "
                              "unplug the radar and plug it back in.", restart_fix("node-red-tm.service"))
    return check("ok", f"{name}, open in Node-RED. {_last_reading(radar.get('last_reading_at'))}")


def radar_checks(context: Context) -> list[Check]:
    """One check for each radar path that has a radar plugged in or enabled in config.yml."""
    names = probes.radar_names(context)
    data = apps.config_yml(context).data
    radars = None if data is None else apps.mapping(apps.mapping(data.get("sensors")).get("radars"))
    checks = [_radar(context, path, names.get(path), radars) for path in context.manifest.probes.radar_paths]
    return [check for check in checks if check is not None]


GROUP = CheckGroup("hardware", "Hardware", [detector_checks, hevc_checks, radar_checks])
