"""Bring config files from older installs up to date. Each step is idempotent: running it again changes nothing."""

import sys
from urllib.parse import urlsplit

from ruamel.yaml import YAMLError

from tm_control.adapters.yamlfile import ConcurrentEditError, RoundTripFile

PREFIX = "tm-control migrate:"

# Frigate reads the Pi camera from go2rtc on the host. Since go2rtc's RTSP server requires credentials,
# camera inputs must carry them; Frigate fills in {FRIGATE_*} from frigate.env.
HOST_GO2RTC_RTSP = "rtsp://host.containers.internal:8554/"
HOST_GO2RTC_RTSP_WITH_CREDENTIALS = (
    "rtsp://{FRIGATE_GO2RTC_RTSP_USER}:{FRIGATE_GO2RTC_RTSP_PASSWORD}@host.containers.internal:8554/"
)
# Hosts that are Frigate's own container (its bundled go2rtc), not the host's go2rtc.
FRIGATE_LOCAL_HOSTS = {"127.0.0.1", "localhost"}


def _camera_inputs(config):
    """Yield (camera name, input mapping) for every ffmpeg input in a Frigate config."""
    cameras = config.get("cameras") if isinstance(config, dict) else None
    for name, camera in (cameras or {}).items():
        ffmpeg = camera.get("ffmpeg") if isinstance(camera, dict) else None
        inputs = ffmpeg.get("inputs") if isinstance(ffmpeg, dict) else None
        for item in inputs or []:
            if isinstance(item, dict) and isinstance(item.get("path"), str):
                yield name, item


def add_go2rtc_rtsp_credentials(config):
    """Point inputs that read the host's go2rtc at its credentialed URL. Return how many changed."""
    changed = 0
    for _, item in _camera_inputs(config):
        path = item["path"]
        if path.startswith(HOST_GO2RTC_RTSP):
            new_path = HOST_GO2RTC_RTSP_WITH_CREDENTIALS + path[len(HOST_GO2RTC_RTSP):]
            item["path"] = type(path)(new_path)  # same str subclass, so quoting style is kept
            changed += 1
    return changed


def uncredentialed_rtsp_8554_inputs(config):
    """Inputs on port 8554 without credentials that this migration can't safely rewrite (e.g. a LAN IP)."""
    found = []
    for name, item in _camera_inputs(config):
        url = urlsplit(item["path"])
        if url.scheme != "rtsp" or url.username:
            continue
        try:
            port = url.port
        except ValueError:
            continue
        if port == 8554 and url.hostname not in FRIGATE_LOCAL_HOSTS:
            found.append((name, item["path"]))
    return found


def run(frigate_config, dry_run=False):
    """Apply every migration step to Frigate's config.yml. Return a process exit code."""
    try:
        document = RoundTripFile(frigate_config)
    except (OSError, YAMLError) as error:
        print(f"{PREFIX} ERROR reading {frigate_config}: {error}", file=sys.stderr)
        return 1

    changed = add_go2rtc_rtsp_credentials(document.data)
    for camera, path in uncredentialed_rtsp_8554_inputs(document.data):
        print(
            f"{PREFIX} WARNING camera '{camera}' reads {path} without credentials. If that is this "
            "device's go2rtc, add {FRIGATE_GO2RTC_RTSP_USER}:{FRIGATE_GO2RTC_RTSP_PASSWORD}@ before the host.",
            file=sys.stderr,
        )
    if not changed:
        print(f"{PREFIX} {frigate_config}: up to date")
        return 0
    if dry_run:
        print(f"{PREFIX} {frigate_config}: would update {changed} camera input(s) to use go2rtc RTSP credentials")
        return 0
    try:
        backup = document.save()
    except (OSError, ConcurrentEditError) as error:
        print(f"{PREFIX} ERROR writing {frigate_config}: {error}", file=sys.stderr)
        return 1
    print(f"{PREFIX} {frigate_config}: updated {changed} camera input(s) to use go2rtc RTSP credentials (backup: {backup})")
    return 0
