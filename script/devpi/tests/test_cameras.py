"""Cameras: sensors detected, the HEVC decoder passed to Frigate, and frames flowing end to end."""

import re

import pytest
from devpi_checks import pi_json

# The same scan as utils/find_hevc_device.sh: the /dev/media* device whose model is rpi-hevc-dec.
FIND_HEVC = """for device in /dev/media*; do
  udevadm info -a -n "$device" 2>/dev/null | grep -q 'ATTR{model}=="rpi-hevc-dec"' && echo "$device"
done; true"""
# Kernel names of the V4L2 sub-devices, sensors among them (e.g. imx708_wide). Readable without
# camera access and while go2rtc holds the camera, unlike rpicam-hello --list-cameras.
SUBDEV_NAMES = "cat /sys/class/video4linux/v4l-subdev*/name 2>/dev/null"


@pytest.fixture
def cameras(expect):
    if not expect["cameras"]:
        pytest.skip("no cameras expected")
    return expect["cameras"]


def test_csi_sensors_detected(host, cameras):
    """Each expected CSI sensor model is present. sysfs doesn't say which port it's on, so ports aren't checked."""
    wanted = [camera["sensor"] for camera in cameras if camera["source"] == "csi" and camera.get("sensor")]
    if not wanted:
        pytest.skip("no CSI camera with a sensor expected")
    names = [line.split()[0] for line in host.run(SUBDEV_NAMES).stdout.splitlines() if line.strip()]
    unmatched = list(names)
    missing = []
    for sensor in wanted:
        match = next((name for name in unmatched if name == sensor or name.startswith(sensor + "_")), None)
        if match:
            unmatched.remove(match)
        else:
            missing.append(sensor)
    assert not missing, f"sensors not found: {missing} (V4L2 sub-devices: {names or 'none'})"


def test_frigate_gets_the_hevc_decoder(host, cameras):
    with host.sudo():
        decoders = host.check_output(FIND_HEVC).split()
    assert decoders, "no /dev/media* device with model rpi-hevc-dec"
    unit = host.file("/etc/containers/systemd/frigate.container").content_string
    line = f"AddDevice={decoders[0]}:{decoders[0]}"
    passed = line in unit
    assert passed, f"frigate.container lacks {line}; the HEVC decoder is {decoders[0]}"


def test_frigate_cameras_running(host, cameras):
    config = pi_json(host, "http://localhost:5000/api/config").get("cameras", {})
    stats = pi_json(host, "http://localhost:5000/api/stats").get("cameras", {})
    problems = []
    for camera in cameras:
        name = camera["name"]
        if name not in config:
            problems.append(f"{name} isn't in Frigate's config")
        elif not config[name].get("enabled", True):
            problems.append(f"{name} is disabled in Frigate")
        elif not (stats.get(name) or {}).get("camera_fps", 0) > 0:
            problems.append(f"{name} has camera_fps {(stats.get(name) or {}).get('camera_fps')}")
    assert not problems, "; ".join(problems)


def test_go2rtc_streams_have_producers(host, cameras):
    """Each CSI camera's Frigate input is a stream on the host go2rtc that is producing."""
    config = pi_json(host, "http://localhost:5000/api/config").get("cameras", {})
    streams = pi_json(host, "http://localhost:1984/api/streams")
    problems = []
    for camera in (camera for camera in cameras if camera["source"] == "csi"):
        inputs = (config.get(camera["name"]) or {}).get("ffmpeg", {}).get("inputs", [])
        names = [match.group(1) for item in inputs if (match := re.search(r":8554/([^/?\s]+)", item.get("path", "")))]
        if not names:
            problems.append(f"{camera['name']} has no input from the host go2rtc")
        for stream in names:
            if not (streams.get(stream) or {}).get("producers"):
                problems.append(f"go2rtc stream {stream} has no producer")
    assert not problems, "; ".join(problems)


def test_node_red_camera_config(cameras, expect, node_red_config):
    configured = (node_red_config.get("sensors") or {}).get("cameras") or {}
    radar_names = {radar["env_name"] for radar in expect["radars"]}
    problems = []
    for camera in cameras:
        entry = configured.get(camera["name"]) or {}
        if not entry.get("enabled"):
            problems.append(f"sensors.cameras.{camera['name']} isn't enabled in config.yml; its events are dropped")
        paired = entry.get("camera_radar")
        if radar_names and paired not in radar_names:
            problems.append(f"{camera['name']} is paired with radar {paired!r}, not one of {sorted(radar_names)}")
    assert not problems, "; ".join(problems)
