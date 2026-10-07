"""The AI co-processor: found on the bus, set up on the host, passed to Frigate, and inferring."""

import re

import pytest
from devpi_checks import pi_json

# How each co-processor shows up. Device paths match tmsetup_detectors in the role's defaults/main.yml.
# A Coral USB enumerates as 1a6e:089a and re-enumerates as 18d1:9302 once its firmware is loaded.
DETECTORS = {
    "edgetpu_usb": {"probe": "lsusb", "pattern": r"1a6e:089a|18d1:9302", "dev_path": "/dev/bus/usb",
                    "module": None},
    "edgetpu_pci": {"probe": "lspci -nn", "pattern": r"(?i)coral|1ac1:089a", "dev_path": "/dev/apex_0",
                    "module": "apex"},
    "hailo8l": {"probe": "lspci -nn", "pattern": r"(?i)hailo", "dev_path": "/dev/hailo0", "module": "hailo_pci"},
}
DETECTORS["hailo8"] = DETECTORS["hailo8l"]


def present(host, kind):
    detector = DETECTORS[kind]
    return re.search(detector["pattern"], host.run(detector["probe"]).stdout) is not None


@pytest.fixture
def expected(expect):
    if expect["ai_coprocessor"] == "none":
        pytest.skip("no AI co-processor expected")
    return DETECTORS[expect["ai_coprocessor"]]


def test_expected_coprocessor_found(host, expect, expected):
    assert present(host, expect["ai_coprocessor"]), (
        f"{expect['ai_coprocessor']} not found by `{expected['probe']}`; check that it's seated and powered")


def test_no_unexpected_coprocessor(host, expect):
    expected_detector = DETECTORS.get(expect["ai_coprocessor"])
    others = {kind for kind, detector in DETECTORS.items() if detector is not expected_detector and kind != "hailo8"}
    found = sorted(kind for kind in others if present(host, kind))
    assert not found, f"found {found}, but the inventory expects {expect['ai_coprocessor']}"


def test_device_and_driver_ready(host, expected):
    assert host.file(expected["dev_path"]).exists, f"{expected['dev_path']} is missing; the driver isn't loaded"
    if expected["module"]:
        loaded = host.run(f"lsmod | grep -qw {expected['module']}").rc == 0
        assert loaded, f"kernel module {expected['module']} isn't loaded"


def test_frigate_gets_the_device(host, expected):
    unit = host.file("/etc/containers/systemd/frigate.container").content_string
    line = f"AddDevice={expected['dev_path']}:{expected['dev_path']}"
    passed = line in unit
    assert passed, f"frigate.container has no {line}; re-run tmsetup.sh -t detectors -t frigate"


def test_frigate_detector_inferring(host, expected):
    detectors = pi_json(host, "http://localhost:5000/api/stats").get("detectors", {})
    assert detectors, "Frigate reports no detectors"
    speeds = {name: detector.get("inference_speed", 0) for name, detector in detectors.items()}
    assert all(speed > 0 for speed in speeds.values()), f"detector inference speeds (ms): {speeds}"
