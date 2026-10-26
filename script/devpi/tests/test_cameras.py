"""Cameras: sensors detected, the HEVC decoder's symlink and the decoder passed to Frigate, and frames flowing end to end."""

import re

import pytest
from devpi_checks import find_hevc_decoder, frigate_host_devices, pi_json, role_vars

HEVC_SYMLINK = role_vars()["tmsetup_hevc_device"]
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


def test_hevc_decoder_symlink_follows_the_decoder(host):
    """udev's symlink points at the media device whose model is rpi-hevc-dec, whatever its number is on this boot (#231)."""
    decoder = find_hevc_decoder(host)
    target = host.run(f"readlink -f {HEVC_SYMLINK}").stdout.strip()
    assert target == decoder, f"{HEVC_SYMLINK} -> {target or 'missing'}, but the decoder is {decoder}; re-run tmsetup.sh -t frigate"


def test_frigate_gets_the_hevc_decoder(host):
    """The unit passes the symlink, and the running container got the decoder's device for this boot."""
    unit = host.file("/etc/containers/systemd/frigate.container").content_string.splitlines()
    assert f"AddDevice={HEVC_SYMLINK}" in unit, f"frigate.container lacks AddDevice={HEVC_SYMLINK}; re-run tmsetup.sh -t frigate"
    decoder = find_hevc_decoder(host)
    devices = frigate_host_devices(host)
    assert decoder in devices, f"the frigate container has {devices}, not the decoder {decoder} (started before the number changed?)"


def test_frigate_cameras_running(cameras, frigate_config, frigate_stats):
    config = frigate_config.get("cameras", {})
    stats = frigate_stats.get("cameras", {})
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


def test_go2rtc_streams_have_producers(host, cameras, frigate_config):
    """Each CSI camera's Frigate input is a stream on the host go2rtc that is producing."""
    config = frigate_config.get("cameras", {})
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
