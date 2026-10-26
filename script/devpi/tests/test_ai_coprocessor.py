"""The AI co-processor: found on the bus, set up on the host, passed to Frigate, and inferring."""

import re

import pytest
from devpi_checks import role_defaults

# How each co-processor shows up; device paths come from tmsetup_detectors in the role's defaults/main.yml.
# A Coral USB enumerates as 1a6e:089a and re-enumerates as 18d1:9302 once its firmware is loaded.
DETECTORS = {
    "edgetpu_usb": {"probe": "lsusb", "pattern": r"1a6e:089a|18d1:9302", "module": None},
    "edgetpu_pci": {"probe": "lspci -nn", "pattern": r"(?i)coral|1ac1:089a", "module": "apex"},
    "hailo8l": {"probe": "lspci -nn", "pattern": r"(?i)hailo", "module": "hailo_pci"},
}
for kind, detector in DETECTORS.items():
    detector["dev_path"] = role_defaults()["tmsetup_detectors"][kind]["dev_path"]
DETECTORS["hailo8"] = DETECTORS["hailo8l"]
# Frigate's avg_inference_speed starts at 0.01 s, reported as 10.0 ms, until the first inference.
INITIAL_INFERENCE_MS = 10.0


@pytest.fixture(scope="module")
def probe_output(usable_host):
    """Each bus listing, run once per host."""
    return {probe: usable_host.run(probe).stdout for probe in {detector["probe"] for detector in DETECTORS.values()}}


def present(probe_output, kind):
    detector = DETECTORS[kind]
    return re.search(detector["pattern"], probe_output[detector["probe"]]) is not None


@pytest.fixture
def expected(expect):
    if expect["ai_coprocessor"] == "none":
        pytest.skip("no AI co-processor expected")
    return DETECTORS[expect["ai_coprocessor"]]


def test_expected_coprocessor_found(probe_output, expect, expected):
    assert present(probe_output, expect["ai_coprocessor"]), (
        f"{expect['ai_coprocessor']} not found by `{expected['probe']}`; check that it's seated and powered")


def test_no_unexpected_coprocessor(probe_output, expect):
    expected_detector = DETECTORS.get(expect["ai_coprocessor"])
    others = {kind for kind, detector in DETECTORS.items() if detector is not expected_detector and kind != "hailo8"}
    found = sorted(kind for kind in others if present(probe_output, kind))
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


def test_frigate_detector_inferring(expect, expected, frigate_stats):
    """Each detector has a process. With live traffic, it has also run an inference.

    A detector only runs when there's motion, so on a bench unit facing a still scene its
    speed can stay at Frigate's initial value; that's checked only with live_traffic.
    """
    detectors = frigate_stats.get("detectors", {})
    assert detectors, "Frigate reports no detectors"
    problems = [f"{name} has no process" for name, detector in detectors.items() if not detector.get("pid")]
    if expect["live_traffic"]:
        problems += [f"{name} hasn't run an inference (inference_speed is still {INITIAL_INFERENCE_MS} ms)"
                     for name, detector in detectors.items() if detector.get("inference_speed") == INITIAL_INFERENCE_MS]
    assert not problems, "; ".join(problems)
