"""The hardware checks (AI accelerators in layers, the HEVC decoder, radars) and the hardware adapter. Synthetic data
only: bus listings, unit files, /proc/modules, and the media devices are text in tmp_path, and the apps answer
through the `apps` fixture (conftest.FakeApps)."""

import shutil

import pytest

from tm_control.adapters import hardware
from tm_control.adapters.command import CommandResult
from tm_control.core.checks import Fix, run_group
from tm_control.modules import MODULES
from tm_control.modules.hardware import checks as hardware_checks
from tm_control.modules.hardware.probes import DETECTOR_PROBES
from tm_control.modules.services import units

CONFIG = "http://127.0.0.1:5000/api/config"
STATS = "http://127.0.0.1:5000/api/stats"
NODE_RED_STATUS = "http://127.0.0.1:1880/tm-internal/status"

RESCAN = Fix(kind="rescan", text="Re-scan hardware")
RESTART_FRIGATE = Fix(kind="restart", text="Restart Frigate", unit="frigate.service")
RESTART_NODE_RED = Fix(kind="restart", text="Restart Node-RED", unit="node-red-tm.service")

USB_HUB = ("1d6b", "0002")  # the Linux Foundation's root hub
USB_CORAL = ("1a6e", "089a")  # a Coral USB before its runtime loads the firmware
USB_CORAL_RUNNING = ("18d1", "9302")  # and after (#217)
LSPCI_BRIDGE = "0001:00:00.0 PCI bridge [0604]: Broadcom Inc. and subsidiaries BCM2712 PCIe Bridge [14e4:2712]\n"
LSPCI_CORAL = "0001:01:00.0 System peripheral [0880]: Global Unichip Corp. Coral Edge TPU [1ac1:089a]\n"
LSPCI_HAILO = "0001:01:00.0 Co-processor [0b40]: Hailo Technologies Ltd. Hailo-8 AI Processor [1e60:2864] (rev 01)\n"
PROC_MODULES = "apex 24576 0 - Live 0x0000000000000000\ngasket 98304 1 apex, Live 0x0000000000000000\n"

FRIGATE_UNIT = """[Container]
ContainerName=frigate
AddDevice=/dev/bus/usb:/dev/bus/usb
AddDevice=/dev/rpi-hevc-dec
AddDevice=/dev/video19:/dev/video19
"""
NODE_RED_UNIT = """[Container]
ContainerName=node-red-tm
AddDevice=/dev/ttyACM0
"""
NODE_RED_ENV = """NODE_RED_CREDENTIAL_SECRET=test-credential-secret
TM_MQTT_BROKER_PASSWORD=test-broker-password
TM_RADAR_SERIAL_PORT_00=/dev/ttyACM0
TM_RADAR_SERIAL_PORT_01=/dev/ttyACM1
TM_RADAR_SERIAL_PORT_02=/dev/ttyACM2
TM_RADAR_SERIAL_PORT_03=/dev/ttyACM3
"""


class FakeHardware:
    """The host's hardware as the hardware adapter sees it. Change the fields, then call `context()`.

    `usb` lists the (idVendor, idProduct) of each USB device in sysfs (None: sysfs can't be read); `pci` is
    lspci -nn's output (None: the program is missing); `paths` the device paths that exist; `links` what each
    symlink resolves to; `runs` counts each lspci run and each read of the USB devices.
    """

    def __init__(self, tmp_path, monkeypatch, apps):
        self.apps = apps
        self.usb: list[tuple[str, str]] | None = [USB_HUB, USB_CORAL_RUNNING]
        self.pci: str | None = LSPCI_BRIDGE
        self.paths = {"/dev/bus/usb", "/dev/ttyACM0", "/dev/rpi-hevc-dec", "/dev/media0"}
        self.links = {"/dev/rpi-hevc-dec": "/dev/media0"}
        self.runs: dict[str, int] = {}
        self.usb_devices = tmp_path / "usb"
        self.units = tmp_path / "systemd"
        self.units.mkdir()
        (self.units / "frigate.container").write_text(FRIGATE_UNIT)
        (self.units / "node-red-tm.container").write_text(NODE_RED_UNIT)
        self.proc_modules = tmp_path / "modules"
        self.proc_modules.write_text(PROC_MODULES)
        self.media = tmp_path / "media"
        for name, model in (("media0", "rpi-hevc-dec"), ("media1", "rpi1-isp"), ("media2", "rp1-cfe")):
            (self.media / name).mkdir(parents=True)
            (self.media / name / "model").write_text(f"{model}\n")
        self.env = apps.codedir / "node-red-tm" / "node-red-tm.env"
        self.env.write_text(NODE_RED_ENV)
        self.service_states = {"frigate.service": {"LoadState": "loaded", "ActiveState": "active"}}
        monkeypatch.setattr(hardware, "run", self.run)
        monkeypatch.setattr(hardware, "USB_DEVICES", self.usb_devices)
        usb_ids = hardware.usb_ids

        def counted_usb_ids():
            self.runs["usb"] = self.runs.get("usb", 0) + 1
            return usb_ids()

        monkeypatch.setattr(hardware, "usb_ids", counted_usb_ids)
        monkeypatch.setattr(hardware, "UNIT_DIR", self.units)
        monkeypatch.setattr(hardware, "PROC_MODULES", self.proc_modules)
        monkeypatch.setattr(hardware, "MEDIA_DEVICES", self.media)
        monkeypatch.setattr(hardware, "path_exists", lambda path: path in self.paths)
        monkeypatch.setattr(hardware, "resolve", lambda path: self.links.get(path, path))

    def run(self, argv, **kwargs):
        assert kwargs["timeout"] <= 4 and kwargs["max_output"], kwargs
        assert argv == ["lspci", "-nn"]
        self.runs["lspci"] = self.runs.get("lspci", 0) + 1
        if self.pci is None:
            raise FileNotFoundError(argv[0])
        return CommandResult(0, self.pci, "", False)

    def write_usb(self):
        """self.usb as sysfs has it: a directory per device with idVendor and idProduct, and interfaces without."""
        shutil.rmtree(self.usb_devices, ignore_errors=True)
        if self.usb is None:
            return
        self.usb_devices.mkdir()
        for index, (vendor, product) in enumerate(self.usb, start=1):
            device = self.usb_devices / f"1-{index}"
            device.mkdir()
            (device / "idVendor").write_text(f"{vendor}\n")
            (device / "idProduct").write_text(f"{product}\n")
            (self.usb_devices / f"1-{index}:1.0").mkdir()

    def frigate_unit(self, text):
        (self.units / "frigate.container").write_text(text)

    def context(self, detectors=None):
        self.write_usb()
        context = self.apps.context()
        if detectors is not None:
            probes = context.manifest.probes.model_copy(update={"detectors": detectors})
            context.manifest = context.manifest.model_copy(update={"probes": probes})
        context.probes[units.SHOW_UNITS] = self.service_states
        return context


@pytest.fixture
def hw(tmp_path, monkeypatch, apps):
    return FakeHardware(tmp_path, monkeypatch, apps)


def hardware_group(hw, **kwargs):
    group = run_group(hardware_checks.GROUP, hw.context(**kwargs))
    assert (group.id, group.title) == ("hardware", "Hardware")
    return {check.id: check for check in group.checks}


def test_hardware_module_comes_after_apps_and_before_system():
    ids = [m.id for m in MODULES]
    assert ids[ids.index("apps") + 1] == "hardware"
    assert ids[ids.index("hardware") + 1] == "system"
    (module,) = [m for m in MODULES if m.id == "hardware"]
    assert [g.id for g in module.check_groups] == ["hardware"]
    assert module.router.routes == []


def test_a_healthy_device_with_a_coral_usb_is_all_ok(hw):
    checks = hardware_group(hw)
    assert list(checks) == [
        "hardware.detector.edgetpu_usb", "hardware.hevc.present", "hardware.hevc.passed", "hardware.radar.ttyACM0",
    ]
    assert {c.id: (c.status, c.detail) for c in checks.values() if c.status != "ok"} == {}
    assert [c.title for c in checks.values()] == [
        "Coral USB Accelerator", "HEVC decoder", "HEVC decoder in Frigate", "Radar on /dev/ttyACM0",
    ]
    assert "8.4 ms" in checks["hardware.detector.edgetpu_usb"].detail
    assert all(c.fix is None for c in checks.values())


# Detectors


def test_detector_probe_table():
    assert DETECTOR_PROBES["edgetpu_usb"][:3] == ("usb", r"1a6e:089a|18d1:9302", None)
    assert DETECTOR_PROBES["edgetpu_pci"][:3] == ("pci", r"(?i)coral|1ac1:089a", "apex")
    assert DETECTOR_PROBES["hailo8l"][:3] == ("pci", r"(?i)hailo", "hailo_pci")


@pytest.mark.parametrize("ids", [USB_CORAL, USB_CORAL_RUNNING])
def test_coral_usb_is_present_under_both_ids(hw, ids):
    """#217: before its runtime loads the firmware the Coral USB is 1a6e:089a, after it 18d1:9302."""
    hw.usb = [USB_HUB, ids]
    assert hardware_group(hw)["hardware.detector.edgetpu_usb"].status == "ok"


def _no_dev_path(hw):
    hw.paths.discard("/dev/bus/usb")


def _not_passed(hw):
    hw.frigate_unit(FRIGATE_UNIT.replace("AddDevice=/dev/bus/usb:/dev/bus/usb\n", ""))


def _not_configured(hw):
    hw.apps.edit_json(CONFIG, lambda body: body.update(detectors={"cpu": {"type": "cpu"}}))


def _no_pid(hw):
    hw.apps.edit_json(STATS, lambda body: body["detectors"]["coral"].pop("pid"))


@pytest.mark.parametrize("change, status, fragment, fix", [
    (_no_dev_path, "error", "driver isn't ready", RESCAN),
    (_not_passed, "error", "isn't passed to Frigate", RESCAN),
    (_not_configured, "error", "isn't in Frigate's config", RESCAN),
    (_no_pid, "error", "isn't running", RESTART_FRIGATE),
    (lambda hw: None, "ok", "8.4 ms", None),
])
def test_detector_layers_name_the_first_failure(hw, change, status, fragment, fix):
    change(hw)
    check = hardware_group(hw)["hardware.detector.edgetpu_usb"]
    assert (check.status, check.fix) == (status, fix)
    assert fragment in check.detail


def test_detector_hints_name_the_installer_tags(hw):
    _no_dev_path(hw)
    detail = hardware_group(hw)["hardware.detector.edgetpu_usb"].detail
    assert "tmsetup.sh -t detectors" in detail and "-t frigate" not in detail
    hw.paths.add("/dev/bus/usb")
    _not_passed(hw)
    assert "tmsetup.sh -t detectors -t frigate" in hardware_group(hw)["hardware.detector.edgetpu_usb"].detail


def test_detector_layers_unknown_kind(hw):
    """A kind the manifest lists but tm-control has no probe for (a newer installer's) can't be checked."""
    detectors = {**hw.context().manifest.probes.detectors, "npu_next": {
        "dev_path": "/dev/npu0", "check_exists": "lspci -nn | grep -i npu", "frigate_type": "npu",
        "frigate_device": "pci"}}
    checks = hardware_group(hw, detectors=detectors)
    check = checks["hardware.detector.npu_next"]
    assert (check.status, check.fix) == ("unknown", RESCAN)
    assert "npu_next" in check.detail
    assert checks["hardware.detector.edgetpu_usb"].status == "ok"


def test_driver_layer_needs_the_module_when_the_probe_names_one(hw):
    hw.usb = [USB_HUB]
    hw.pci = LSPCI_BRIDGE + LSPCI_CORAL
    hw.paths.add("/dev/apex_0")
    hw.frigate_unit(FRIGATE_UNIT.replace("/dev/bus/usb:/dev/bus/usb", "/dev/apex_0:/dev/apex_0"))
    hw.apps.edit_json(CONFIG, lambda body: body["detectors"]["coral"].update(device="pci"))
    checks = hardware_group(hw)
    assert checks["hardware.detector.edgetpu_pci"].title == "Coral PCIe Accelerator"
    assert checks["hardware.detector.edgetpu_pci"].status == "ok"

    hw.proc_modules.write_text("gasket 98304 0 - Live 0x0000000000000000\n")
    check = hardware_group(hw)["hardware.detector.edgetpu_pci"]
    assert check.status == "error" and "driver isn't ready" in check.detail

    hw.proc_modules.unlink()
    assert hardware_group(hw)["hardware.detector.edgetpu_pci"].status == "unknown"


def test_coral_detector_must_be_on_its_own_bus_in_frigates_config(hw):
    """A Coral USB isn't served by an edgetpu detector on the PCIe bus."""
    hw.apps.edit_json(CONFIG, lambda body: body["detectors"]["coral"].update(device="pci:0"))
    check = hardware_group(hw)["hardware.detector.edgetpu_usb"]
    assert check.status == "error" and "isn't in Frigate's config" in check.detail


def test_hailo_matches_by_type(hw):
    hw.usb = [USB_HUB]
    hw.pci = LSPCI_BRIDGE + LSPCI_HAILO
    hw.paths.add("/dev/hailo0")
    hw.proc_modules.write_text("hailo_pci 131072 0 - Live 0x0000000000000000\n")
    hw.frigate_unit(FRIGATE_UNIT.replace("/dev/bus/usb:/dev/bus/usb", "/dev/hailo0:/dev/hailo0"))
    hw.apps.edit_json(CONFIG, lambda body: body.update(detectors={"hailo8l": {"type": "hailo8l", "device": "PCIe"}}))
    hw.apps.edit_json(STATS, lambda body: body.update(
        detectors={"hailo8l": {"inference_speed": 12.0, "detection_start": 0.0, "pid": 410}}))
    check = hardware_group(hw)["hardware.detector.hailo8l"]
    assert (check.title, check.status) == ("Hailo accelerator", "ok")


def test_frigate_not_answering_leaves_the_frigate_layers_unknown(hw):
    hw.apps.answers["http://127.0.0.1:5000/api/version"] = (None, None)
    check = hardware_group(hw)["hardware.detector.edgetpu_usb"]
    assert (check.status, check.fix) == ("unknown", RESCAN)


def test_no_accelerator_is_a_warning_with_the_cpu_detector(hw):
    hw.usb, hw.pci = [USB_HUB], LSPCI_BRIDGE
    hw.apps.edit_json(CONFIG, lambda body: body.update(detectors={"cpu": {"type": "cpu"}}))
    checks = hardware_group(hw)
    assert not any(check_id.startswith("hardware.detector.edgetpu") for check_id in checks)
    check = checks["hardware.detector.none"]
    assert (check.title, check.status, check.fix) == ("No AI accelerator", "warn", RESCAN)
    assert "CPU" in check.detail

    hw.apps.edit_json(CONFIG, lambda body: body.update(detectors={"coral": {"type": "edgetpu", "device": "usb"}}))
    assert hardware_group(hw)["hardware.detector.none"].status == "error"


def test_missing_bus_listing_is_unknown_not_an_error(hw):
    """A laptop has no lspci; a program that's missing or fails, or a sysfs that can't be read, makes presence
    unknown."""
    hw.pci = None
    checks = hardware_group(hw)
    assert checks["hardware.detector.edgetpu_pci"].status == "unknown"
    assert checks["hardware.detector.hailo8l"].status == "unknown"
    assert checks["hardware.detector.edgetpu_usb"].status == "ok"
    assert "hardware.detector.none" not in checks

    hw.pci, hw.usb = LSPCI_BRIDGE, None
    checks = hardware_group(hw)
    assert checks["hardware.detector.edgetpu_usb"].status == "unknown"
    assert "USB" in checks["hardware.detector.edgetpu_usb"].detail
    assert "hardware.detector.none" not in checks


def test_hardware_checks_memoize_the_bus_listings(hw):
    hw.pci = LSPCI_BRIDGE + LSPCI_CORAL
    hw.paths.add("/dev/apex_0")
    hardware_group(hw)
    assert hw.runs == {"usb": 1, "lspci": 1}


# The HEVC decoder


def test_hevc_present_compares_symlink_and_scan(hw):
    assert hardware_group(hw)["hardware.hevc.present"].status == "ok"

    hw.links["/dev/rpi-hevc-dec"] = "/dev/media1"
    check = hardware_group(hw)["hardware.hevc.present"]
    assert (check.status, check.fix) == ("error", RESCAN)
    assert "stale" in check.detail

    hw.paths.discard("/dev/rpi-hevc-dec")
    assert "stale" in hardware_group(hw)["hardware.hevc.present"].detail

    (hw.media / "media0" / "model").write_text("rpi1-isp\n")
    check = hardware_group(hw)["hardware.hevc.present"]
    assert check.status == "error"
    assert "no HEVC decoder" in check.detail


def test_hevc_passed_needs_the_unit_line_and_a_running_frigate(hw):
    hw.frigate_unit(FRIGATE_UNIT.replace("AddDevice=/dev/rpi-hevc-dec\n", ""))
    check = hardware_group(hw)["hardware.hevc.passed"]
    assert (check.status, check.fix) == ("error", RESCAN)
    assert "tmsetup.sh -t frigate" in check.detail

    hw.frigate_unit(FRIGATE_UNIT)
    hw.service_states["frigate.service"]["ActiveState"] = "failed"
    check = hardware_group(hw)["hardware.hevc.passed"]
    assert (check.status, check.fix) == ("error", RESTART_FRIGATE)


def test_unreadable_unit_file_is_unknown(hw):
    (hw.units / "frigate.container").unlink()
    (hw.units / "node-red-tm.container").unlink()
    checks = hardware_group(hw)
    for check_id in ("hardware.detector.edgetpu_usb", "hardware.hevc.passed", "hardware.radar.ttyACM0"):
        assert (checks[check_id].status, checks[check_id].fix) == ("unknown", RESCAN), check_id


# Radars


def _radar(hw):
    return hardware_group(hw).get("hardware.radar.ttyACM0")


def test_radar_layers(hw):
    check = _radar(hw)
    assert check.status == "ok"
    assert "Last reading" in check.detail and "TM_RADAR_SERIAL_PORT_00" in check.detail

    hw.paths.add("/dev/ttyACM1")
    check = hardware_group(hw)["hardware.radar.ttyACM1"]
    assert (check.status, check.fix) == ("error", RESCAN)
    assert "tmsetup.sh -t node-red-tm" in check.detail
    hw.paths.discard("/dev/ttyACM1")

    hw.paths.discard("/dev/ttyACM0")
    check = _radar(hw)
    assert (check.status, check.fix) == ("error", RESCAN)
    assert "not plugged in" in check.detail
    hw.paths.add("/dev/ttyACM0")

    hw.apps.edit_config_yml(lambda data: data["sensors"]["radars"]["TM_RADAR_SERIAL_PORT_00"].update(enabled=False))
    check = _radar(hw)
    assert (check.status, check.fix) == ("warn", RESCAN)
    assert "sensors.radars.TM_RADAR_SERIAL_PORT_00" in check.detail
    hw.apps.edit_config_yml(lambda data: data["sensors"]["radars"]["TM_RADAR_SERIAL_PORT_00"].update(enabled=True))

    hw.apps.edit_json(NODE_RED_STATUS, lambda body: body["radars"]["TM_RADAR_SERIAL_PORT_00"].update(port_open=False))
    check = _radar(hw)
    assert (check.status, check.fix) == ("error", RESTART_NODE_RED)

    checks = hardware_group(hw)
    assert not any(check_id in checks for check_id in
                   ("hardware.radar.ttyACM1", "hardware.radar.ttyACM2", "hardware.radar.ttyACM3"))


def test_radar_open_is_unknown_when_node_red_doesnt_answer(hw):
    hw.apps.answers[NODE_RED_STATUS] = (None, None)
    check = _radar(hw)
    assert (check.status, check.fix) == ("unknown", RESCAN)


def test_radar_names_come_from_node_red_env(hw):
    """A person can point TM_RADAR_SERIAL_PORT_01 at /dev/ttyACM0 in node-red-tm.env."""
    hw.env.write_text(NODE_RED_ENV.replace("PORT_00=/dev/ttyACM0", "PORT_00=/dev/ttyACM9")
                      .replace("PORT_01=/dev/ttyACM1", "PORT_01=/dev/ttyACM0"))
    check = _radar(hw)
    assert (check.status, check.fix) == ("warn", RESCAN)
    assert "sensors.radars.TM_RADAR_SERIAL_PORT_01" in check.detail

    hw.env.unlink()
    assert _radar(hw).status == "ok"  # the template's mapping: TM_RADAR_SERIAL_PORT_00 is /dev/ttyACM0


def test_every_check_that_isnt_ok_has_a_fix(hw):
    hw.usb, hw.pci = [USB_HUB, USB_CORAL], None
    hw.paths = set()
    hw.apps.answers[NODE_RED_STATUS] = (None, None)
    checks = hardware_group(hw)
    assert any(check.status != "ok" for check in checks.values())
    for check in checks.values():
        assert check.status == "ok" or check.fix is not None, check.id


# The adapter


def test_lspci_is_none_when_the_program_fails(monkeypatch):
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        raise FileNotFoundError("lspci")

    monkeypatch.setattr(hardware, "run", run)
    assert hardware.lspci() is None
    monkeypatch.setattr(hardware, "run", lambda argv, **kwargs: calls.append((argv, kwargs)) or
                        CommandResult(1, "", "pcilib: cannot open", False))
    assert hardware.lspci() is None
    monkeypatch.setattr(hardware, "run", lambda argv, **kwargs: calls.append((argv, kwargs)) or
                        CommandResult(-9, "", "", True))
    assert hardware.lspci() is None
    assert all(argv == ["lspci", "-nn"] and kwargs["timeout"] <= 4 and kwargs["max_output"] for argv, kwargs in calls)


def test_usb_ids_list_each_device_from_sysfs(tmp_path, monkeypatch):
    """lsusb's ids, without lsusb: the service sandbox blocks the netlink socket libusb needs."""
    monkeypatch.setattr(hardware, "USB_DEVICES", tmp_path / "usb")
    assert hardware.usb_ids() is None
    for name, vendor, product in (("usb1", "1d6b", "0002"), ("1-1", "1A6E", "089A"), ("2-1", "18d1", None)):
        device = tmp_path / "usb" / name
        device.mkdir(parents=True)
        (device / "idVendor").write_text(f"{vendor}\n")
        if product:
            (device / "idProduct").write_text(f"{product}\n")
    (tmp_path / "usb" / "1-1:1.0").mkdir()
    monkeypatch.setattr(hardware, "run", lambda argv, **kwargs: pytest.fail(f"ran {argv}"))
    assert hardware.usb_ids() == "1a6e:089a\n1d6b:0002\n"


def test_module_loaded_reads_the_first_field(tmp_path, monkeypatch):
    monkeypatch.setattr(hardware, "PROC_MODULES", tmp_path / "modules")
    assert hardware.module_loaded("apex") is None
    (tmp_path / "modules").write_text(PROC_MODULES)
    assert hardware.module_loaded("apex") is True
    assert hardware.module_loaded("gasket") is True
    assert hardware.module_loaded("hailo_pci") is False
    assert hardware.module_loaded("ape") is False


def test_unit_adds_device_matches_the_whole_line(tmp_path, monkeypatch):
    monkeypatch.setattr(hardware, "UNIT_DIR", tmp_path)
    assert hardware.unit_adds_device("frigate.container", "/dev/rpi-hevc-dec") is None
    (tmp_path / "frigate.container").write_text(FRIGATE_UNIT)
    assert hardware.unit_adds_device("frigate.container", "/dev/rpi-hevc-dec") is True
    assert hardware.unit_adds_device("frigate.container", "/dev/bus/usb:/dev/bus/usb") is True
    assert hardware.unit_adds_device("frigate.container", "/dev/bus/usb") is False
    assert hardware.unit_adds_device("frigate.container", "/dev/video19") is False


def test_hevc_decoder_resolves_the_symlink_and_scans_the_media_models(tmp_path, monkeypatch):
    media = tmp_path / "media"
    for name, model in (("media0", "rp1-cfe"), ("media3", "rpi-hevc-dec")):
        (media / name).mkdir(parents=True)
        (media / name / "model").write_text(f"{model}\n")
    monkeypatch.setattr(hardware, "MEDIA_DEVICES", media)
    target = tmp_path / "media3"
    target.write_text("")
    (tmp_path / "rpi-hevc-dec").symlink_to(target)
    assert hardware.hevc_decoder(str(tmp_path / "rpi-hevc-dec")) == {"symlink": str(target), "scanned": "/dev/media3"}
    assert hardware.hevc_decoder(str(tmp_path / "missing")) == {"symlink": None, "scanned": "/dev/media3"}
    monkeypatch.setattr(hardware, "MEDIA_DEVICES", tmp_path / "no-media")
    assert hardware.hevc_decoder(str(tmp_path / "missing")) == {"symlink": None, "scanned": None}


def test_radar_ports_reads_only_the_radar_lines(tmp_path, monkeypatch):
    env = tmp_path / "node-red-tm" / "node-red-tm.env"
    assert hardware.radar_ports(tmp_path) is None
    env.parent.mkdir()
    env.write_text(NODE_RED_ENV + "# TM_RADAR_SERIAL_PORT_09=/dev/ttyUSB9\nTM_RADAR_SERIAL_PORT_02=\"/dev/ttyUSB0\"\n")
    ports = hardware.radar_ports(tmp_path)
    assert ports == {
        "TM_RADAR_SERIAL_PORT_00": "/dev/ttyACM0",
        "TM_RADAR_SERIAL_PORT_01": "/dev/ttyACM1",
        "TM_RADAR_SERIAL_PORT_02": "/dev/ttyUSB0",
        "TM_RADAR_SERIAL_PORT_03": "/dev/ttyACM3",
    }
    assert "test-broker-password" not in repr(ports) and "test-credential-secret" not in repr(ports)
