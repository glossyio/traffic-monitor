"""Bring config files from older installs up to date. Each step is idempotent: running it again changes nothing."""

import re
import sys
from urllib.parse import urlsplit

from ruamel.yaml import YAMLError
from ruamel.yaml.comments import CommentedMap
from ruamel.yaml.error import CommentMark
from ruamel.yaml.scalarstring import DoubleQuotedScalarString
from ruamel.yaml.tokens import CommentToken

from tm_control.adapters.yamlfile import ConcurrentEditError, RoundTripFile

PREFIX = "tm-control migrate:"

# nginx serves Frigate's authenticated port (8971) once tm-control has logged the user in, and passes the user, their
# role, and the proxy secret. Frigate's own login and TLS are off, and it trusts those headers only with the secret,
# which it fills in from frigate.env. Keep in step with the same sections of config.yml.j2.
PROXY_AUTH_SECRET_PLACEHOLDER = "{FRIGATE_PROXY_AUTH_SECRET}"
PROXY_HEADER_MAP = {"user": "x-forwarded-user", "role": "x-forwarded-groups"}
PROXY_DEFAULT_ROLE = "viewer"
PROXY_AUTH_SECTIONS = {
    "auth": {"enabled": False},
    "proxy": {
        "header_map": PROXY_HEADER_MAP,
        "auth_secret": PROXY_AUTH_SECRET_PLACEHOLDER,
        "default_role": PROXY_DEFAULT_ROLE,
        "logout_url": "/logout",
    },
    "tls": {"enabled": False},
}
PROXY_AUTH_COMMENT = "The reverse proxy logs users in and passes who they are; Frigate's own login is off (tm-control)."

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


def _round_trip(value):
    """A value from PROXY_AUTH_SECTIONS as ruamel round-trip types, with the placeholder quoted as the template has it."""
    if isinstance(value, dict):
        return CommentedMap((key, _round_trip(item)) for key, item in value.items())
    if value == PROXY_AUTH_SECRET_PLACEHOLDER:
        return DoubleQuotedScalarString(value)  # unquoted, YAML would read {...} as a mapping
    return value


def add_proxy_auth(config):
    """Add whichever of the auth:, proxy:, and tls: sections are missing. Return whether any were.

    They go right after mqtt: (or at the top if there is none), with the comment and blank line config.yml.j2 has, so
    the file reads like a new install's. Sections that exist are left alone; proxy_auth_problems checks them. If an
    existing proxy: section has a problem, auth: isn't added either: Frigate's own login stays on, because turning it
    off would let Frigate trust headers the reverse proxy doesn't set.
    """
    if not isinstance(config, CommentedMap):
        return False
    missing = [key for key in PROXY_AUTH_SECTIONS if key not in config]
    if "auth" in missing and _proxy_section_is_unsafe(config):
        missing.remove("auth")
    if not missing:
        return False
    keys = list(config)
    position = keys.index("mqtt") + 1 if "mqtt" in keys else 0
    for offset, key in enumerate(missing):
        config.insert(position + offset, key, _round_trip(PROXY_AUTH_SECTIONS[key]))
    config.yaml_set_comment_before_after_key(missing[0], before=PROXY_AUTH_COMMENT)
    if position + len(missing) < len(config):
        # ruamel keeps a blank line after a value as a comment token on that value's key.
        last = config[missing[-1]]
        last.ca.items[list(last)[-1]] = [None, None, CommentToken("\n\n", CommentMark(0), None), None]
    return True


def proxy_auth_problems(config):
    """Settings in existing auth:, proxy:, or tls: sections that keep Frigate from accepting the proxy's login.

    Return each as a key path and what's wrong with it, never the value: proxy.auth_secret may hold the secret itself.
    """
    if not isinstance(config, dict):
        return []
    problems = []
    for section in ("auth", "tls"):
        if section not in config:
            continue
        settings = config[section] if isinstance(config[section], dict) else {}
        if "enabled" not in settings:
            problems.append(f"{section}.enabled is missing")  # Frigate's default is true
        elif settings["enabled"] is True:
            problems.append(f"{section}.enabled is true")
        elif settings["enabled"] is not False:
            problems.append(f"{section}.enabled is not false")
    if "proxy" in config:
        proxy = config["proxy"] if isinstance(config["proxy"], dict) else {}
        header_map = proxy.get("header_map") if isinstance(proxy.get("header_map"), dict) else {}
        for key, header in PROXY_HEADER_MAP.items():
            if str(header_map.get(key, "")).lower() != header:  # HTTP header names ignore case
                problems.append(f"proxy.header_map.{key} is not {header}")
        if proxy.get("auth_secret") is None:
            problems.append("proxy.auth_secret is missing")
        elif proxy["auth_secret"] != PROXY_AUTH_SECRET_PLACEHOLDER:
            problems.append(f"proxy.auth_secret is not {PROXY_AUTH_SECRET_PLACEHOLDER}")
        if proxy.get("default_role", PROXY_DEFAULT_ROLE) != PROXY_DEFAULT_ROLE:
            problems.append(f"proxy.default_role is not {PROXY_DEFAULT_ROLE}")
    return problems


def _proxy_section_is_unsafe(config):
    return "proxy" in config and any(problem.startswith("proxy.") for problem in proxy_auth_problems(config))


# What each section's problem does to Frigate behind the reverse proxy, for the warning.
_PROXY_AUTH_CONSEQUENCE = {
    "auth": "so Frigate asks for its own login as well as the reverse proxy's",
    "proxy": "so Frigate may trust headers the reverse proxy doesn't set",
    "tls": "so Frigate serves port 8971 over TLS, which the reverse proxy doesn't use",
}


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
    proxy_auth_added = add_proxy_auth(document.data)
    for problem in proxy_auth_problems(document.data):
        consequence = _PROXY_AUTH_CONSEQUENCE[problem.partition(".")[0]]
        print(
            f"{PREFIX} WARNING {problem}, {consequence}. Set it as a new install's config.yml has it.",
            file=sys.stderr,
        )
    if isinstance(document.data, dict) and "auth" not in document.data:
        print(
            f"{PREFIX} WARNING auth was not added, so Frigate's own login stays on until proxy is fixed.",
            file=sys.stderr,
        )
    if not changed and not proxy_auth_added:
        print(f"{PREFIX} {frigate_config}: up to date")
        return 0
    what = "camera input(s) and stream source(s)" if streams_changed else "camera input(s)"
    # Each step that changed something, as (what a dry run would do, what was done)
    steps = []
    if changed:
        steps.append((f"update {changed} {what}", f"updated {changed} {what}"))
    if proxy_auth_added:
        steps.append(("add proxy auth settings", "added proxy auth settings"))
    if dry_run:
        print(f"{PREFIX} {frigate_config}: would " + ", ".join(would for would, _ in steps))
        return 0
    try:
        backup = document.save()
    except (OSError, ConcurrentEditError) as error:
        print(f"{PREFIX} ERROR writing {frigate_config}: {error}", file=sys.stderr)
        return 1
    print(f"{PREFIX} {frigate_config}: " + ", ".join(done for _, done in steps) + f" (backup: {backup})")
    return 0
