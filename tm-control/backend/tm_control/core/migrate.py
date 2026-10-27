"""Bring config files from older installs up to date. Each step is idempotent: running it again changes nothing."""

import re
import sys
from urllib.parse import urlsplit

from ruamel.yaml import YAMLError

from tm_control.adapters.yamlfile import ConcurrentEditError, RoundTripFile

PREFIX = "tm-control migrate:"

# Frigate reads the Pi camera from go2rtc on the host, through its camera inputs and through the sources of
# its own bundled go2rtc's streams. Since the host's go2rtc RTSP server requires credentials, both must carry
# them; Frigate fills in {FRIGATE_*} from frigate.env.
HOST_GO2RTC_RTSP = "rtsp://host.containers.internal:8554/"
HOST_GO2RTC_RTSP_WITH_CREDENTIALS = (
    "rtsp://{FRIGATE_GO2RTC_RTSP_USER}:{FRIGATE_GO2RTC_RTSP_PASSWORD}@host.containers.internal:8554/"
)
HOST_GO2RTC_RTSP_USER_PLACEHOLDER = "{FRIGATE_GO2RTC_RTSP_USER}"
# The host's go2rtc inside another source type, such as ffmpeg:rtsp://host.containers.internal:8554/<stream>#...;
# the group is the stream name, which is all a warning prints.
_WRAPPED_HOST_STREAM = re.compile(r"host\.containers\.internal:8554/([^#?\s]*)")
# Hosts that are Frigate's own container (its bundled go2rtc), not the host's go2rtc.
FRIGATE_LOCAL_HOSTS = {"127.0.0.1", "localhost"}


def _camera_inputs(config):
    """Yield (camera name, input mapping) for every ffmpeg input in a Frigate config."""
    cameras = config.get("cameras") if isinstance(config, dict) else None
    for name, camera in (cameras if isinstance(cameras, dict) else {}).items():
        ffmpeg = camera.get("ffmpeg") if isinstance(camera, dict) else None
        inputs = ffmpeg.get("inputs") if isinstance(ffmpeg, dict) else None
        for item in inputs if isinstance(inputs, list) else []:
            if isinstance(item, dict) and isinstance(item.get("path"), str):
                yield name, item


def _go2rtc_stream_sources(config):
    """Yield (stream name, container, key) for every string source under go2rtc: streams:.

    A stream is one source string or a list of them, so container[key] is the source. Anything else, such as a
    source with options written as a mapping, is skipped.
    """
    go2rtc = config.get("go2rtc") if isinstance(config, dict) else None
    streams = go2rtc.get("streams") if isinstance(go2rtc, dict) else None
    for name, sources in (streams if isinstance(streams, dict) else {}).items():
        if isinstance(sources, str):
            yield name, streams, name
        elif isinstance(sources, list):
            for index, source in enumerate(sources):
                if isinstance(source, str):
                    yield name, sources, index


def _with_credentials(source):
    """The credentialed form of a source that reads the host's go2rtc, or None if it doesn't."""
    if not source.startswith(HOST_GO2RTC_RTSP):
        return None
    # Same str subclass, so the quoting style is kept.
    return type(source)(HOST_GO2RTC_RTSP_WITH_CREDENTIALS + source[len(HOST_GO2RTC_RTSP):])


def _add_credentials_to_inputs(config):
    changed = 0
    for _, item in _camera_inputs(config):
        new_path = _with_credentials(item["path"])
        if new_path is not None:
            item["path"] = new_path
            changed += 1
    return changed


def _add_credentials_to_streams(config):
    changed = 0
    for _, container, key in list(_go2rtc_stream_sources(config)):
        new_source = _with_credentials(container[key])
        if new_source is not None:
            container[key] = new_source
            changed += 1
    return changed


def _needs_a_person(source):
    """Check whether a source may read a go2rtc stream without credentials in a way this migration can't rewrite.

    Return None if not, or (problem, detail), where problem is one of:
    - "invalid": the source isn't a valid URL (detail is None);
    - "no-login": an RTSP URL on port 8554 of a host other than Frigate's own (e.g. a LAN IP), with no userinfo;
      detail is scheme://host:port/path, with no userinfo, query, or fragment, and without the path if an
      "@" follows the "//" anywhere in the source;
    - "wrapped": the source reads this device's go2rtc inside another source type (e.g. ffmpeg:rtsp://...)
      without the login placeholders; detail is only the stream name.
    The detail is safe to print.
    """
    wrapped = _WRAPPED_HOST_STREAM.search(source)
    if wrapped and not source.startswith("rtsp://") and HOST_GO2RTC_RTSP_USER_PLACEHOLDER not in source:
        return "wrapped", wrapped.group(1)
    try:
        url = urlsplit(source)
    except ValueError:  # e.g. an unencoded [ or ] in a password
        return "invalid", None
    if url.scheme != "rtsp" or url.username or url.password:
        return None
    try:
        port = url.port
    except ValueError:
        return None
    host = url.hostname or ""
    if port != 8554 or host in FRIGATE_LOCAL_HOSTS:
        return None
    if ":" in host:
        host = f"[{host}]"
    # This URL has no userinfo, so an "@" after the "//" (in the path, query, or fragment) means a
    # password held an unencoded "/", "?", or "#", and the path may hold the rest of it.
    path = "" if "@" in source.partition("//")[2] else url.path
    return "no-login", f"{url.scheme}://{host}:{port}{path}"


# What a warning calls the unparsable string, by the kind of entry it came from.
_SOURCE_NOUN = {"camera": "an input path", "go2rtc stream": "a source"}


def uncredentialed_rtsp_8554_inputs(config):
    """Inputs and go2rtc stream sources this migration can't safely rewrite, so a person must check them.

    Return (kind, name, problem, detail) for each, where kind is "camera" or "go2rtc stream" and problem and
    detail are as _needs_a_person describes.
    """
    found = []
    entries = [("camera", name, item["path"]) for name, item in _camera_inputs(config)]
    entries += [("go2rtc stream", name, container[key]) for name, container, key in _go2rtc_stream_sources(config)]
    for kind, name, source in entries:
        result = _needs_a_person(source)
        if result:
            found.append((kind, name, *result))
    return found


def _warn(kind, name, problem, detail):
    login = "{FRIGATE_GO2RTC_RTSP_USER}:{FRIGATE_GO2RTC_RTSP_PASSWORD}@"
    if problem == "invalid":
        message = f"{kind} '{name}' has {_SOURCE_NOUN[kind]} that isn't a valid URL; check it by hand."
    elif problem == "wrapped":
        message = (
            f"{kind} '{name}' reads this device's go2rtc stream '{detail}' inside another source type without "
            f"the login. Add {login} before host.containers.internal."
        )
    else:
        message = (
            f"{kind} '{name}' reads {detail} without credentials. If that is this device's go2rtc, "
            f"add {login} before the host."
        )
    print(f"{PREFIX} WARNING {message}", file=sys.stderr)


def _describe_yaml_error(error):
    """Name a YAML error and where it is.

    Never its message: that quotes the broken line, which may hold a camera password.
    """
    description = f"invalid YAML ({type(error).__name__})"
    mark = getattr(error, "problem_mark", None)
    if mark is not None:
        description += f" at line {mark.line + 1}, column {mark.column + 1}"
    return description


def run(frigate_config, dry_run=False):
    """Apply every migration step to Frigate's config.yml. Return a process exit code.

    Warnings never print a source in full: only its scheme, host, port, and path, or just its stream name, so no
    credential or query string reaches the install log. Errors print the path and what went wrong, never the
    file's text.
    """
    try:
        document = RoundTripFile(frigate_config)
    except OSError as error:
        print(f"{PREFIX} ERROR reading {frigate_config}: {error}", file=sys.stderr)
        return 1
    except YAMLError as error:
        print(f"{PREFIX} ERROR reading {frigate_config}: {_describe_yaml_error(error)}", file=sys.stderr)
        return 1

    inputs_changed = _add_credentials_to_inputs(document.data)
    streams_changed = _add_credentials_to_streams(document.data)
    changed = inputs_changed + streams_changed
    for kind, name, problem, detail in uncredentialed_rtsp_8554_inputs(document.data):
        _warn(kind, name, problem, detail)
    if not changed:
        print(f"{PREFIX} {frigate_config}: up to date")
        return 0
    what = "camera input(s) and stream source(s)" if streams_changed else "camera input(s)"
    if dry_run:
        print(f"{PREFIX} {frigate_config}: would update {changed} {what} to use go2rtc RTSP credentials")
        return 0
    try:
        backup = document.save()
    except (OSError, ConcurrentEditError) as error:
        print(f"{PREFIX} ERROR writing {frigate_config}: {error}", file=sys.stderr)
        return 1
    print(f"{PREFIX} {frigate_config}: updated {changed} {what} to use go2rtc RTSP credentials (backup: {backup})")
    return 0
