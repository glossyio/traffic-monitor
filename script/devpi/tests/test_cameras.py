"""Cameras: sensors detected, the HEVC decoder's symlink and the decoder passed to Frigate, and frames flowing end to end."""

import re

import pytest
from devpi_checks import (ask_frigate_on_pi, broker_login, find_hevc_decoder, frame_sizes_on_pi, frigate_host_devices,
                          pi_json, require_pii_free, role_vars)

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


def test_frigate_answers_on_connect(host, expect, codedir, cameras, frigate_config):
    """Frigate answers an empty frigate/onConnect on the Pi's broker with frigate/camera_activity, one entry for each
    camera in its config, each with a boolean detect. That is what the reference picture's people check asks. A camera
    whose detection is off has no objects to count. Reads the broker's login and Frigate's camera names, so it keeps
    and prints counts and booleans only."""
    require_pii_free(expect)
    answer = ask_frigate_on_pi(host, broker_login(host, expect, codedir), wait=5)
    assert answer is not None, ("Frigate didn't answer frigate/onConnect on the Pi's broker within 5 s: the people "
                                "check has nothing to ask")
    configured = frigate_config.get("cameras", {})
    # Counts, not lists: pytest prints the values an assert compares, and Frigate's camera names stay on the device.
    missing = sum(1 for name in configured if name not in answer)
    no_boolean = sum(1 for name in configured if name in answer and not isinstance(answer[name]["detect"], bool))
    off_with_objects = sum(1 for name in configured if name in answer and answer[name]["detect"] is False
                           and answer[name]["objects"] not in (0, None))
    print(f"cameras in Frigate's config: {len(configured)}, in the answer: {len(answer)}, detection on: "
          f"{sum(1 for name in configured if name in answer and answer[name]['detect'] is True)}")
    assert missing == 0, f"{missing} of {len(configured)} cameras in Frigate's config are not in its answer"
    assert no_boolean == 0, f"{no_boolean} cameras in the answer have no boolean detect"
    assert off_with_objects == 0, f"{off_with_objects} cameras with detection off list objects"


def test_reference_frames_are_whole_jpegs_at_the_detect_size(host, cameras, frigate_config, frigate_stats):
    """For each camera that is on and sending, Frigate's two reference frames (latest.jpg at quality 95, plain and with
    the zones' outlines) are 200 image/jpeg, not an older frame, and at the camera's detect size. Prints each camera's
    four numbers (the two byte counts, the width, the height), one line each, to size the kept pictures' ceiling; run
    with -s. Reads sizes and headers only: no picture is kept, opened, or described, and no camera name is printed."""
    configured = frigate_config.get("cameras", {})
    stats = frigate_stats.get("cameras", {})
    frames = frame_sizes_on_pi(host)
    assert len(frames) == len(configured), f"Frigate's config lists {len(configured)} cameras, the frames {len(frames)}"
    problems = []
    measured = 0
    for number, (name, frame) in enumerate(zip(configured, frames), start=1):
        if not configured[name].get("enabled", True) or not (stats.get(name) or {}).get("camera_fps", 0) > 0:
            print(f"camera {number}: skipped (off or not sending)")
            continue  # Frigate has no current frame to send
        measured += 1
        detect = frame["detect"]
        for kind in ("clean", "zones"):
            answer = frame[kind]
            if answer["status"] != 200 or not answer["type"].startswith("image/jpeg"):
                problems.append(f"camera {number}: {kind} answered {answer['status']} {answer['type'] or 'with no type'}")
            elif answer["offline"]:
                problems.append(f"camera {number}: {kind} is an older frame")
            elif answer["size"] != detect:
                problems.append(f"camera {number}: {kind} is {answer['size']}, the detect size is {detect}")
        print(f"camera {number}: clean {frame['clean']['bytes']} bytes, zones {frame['zones']['bytes']} bytes, "
              f"{detect[0]}x{detect[1]}")
    assert measured, "no camera is on and sending, so there is no frame to measure"
    assert not problems, "; ".join(problems)
