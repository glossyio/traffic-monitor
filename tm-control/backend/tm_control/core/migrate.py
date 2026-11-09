"""Bring config files from older installs up to date. Each step is idempotent: running it again changes nothing."""

import os
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

from ruamel.yaml import YAMLError
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.error import CommentMark
from ruamel.yaml.scalarstring import DoubleQuotedScalarString
from ruamel.yaml.tokens import CommentToken

from tm_control.adapters.yamlfile import ConcurrentEditError, RoundTripFile, back_up, read_text, write_atomic
from tm_control.core.secrets import PLATE_RECOGNIZER_LICENSE_KEY, PLATE_RECOGNIZER_TOKEN, THINGSBOARD_ACCESS_TOKEN
from tm_control.core.secrets import VALUE_RULES, is_valid_value

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


# Entered secrets (core/secrets.py). Older installs kept the ThingsBoard token and the Plate Recognizer token in
# Node-RED's config.yml, and a person typed the Plate Recognizer token and license key into plate-recognizer.env.
# tmsetup runs these two steps as root, before it renders either file, so that -f can't throw away a value's only
# copy. Each key path, the secret file it moves to, and whether mappings it leaves empty go too.
# Only a value that meets its secret's pattern (core/secrets.py) moves, as through the Device page: a value the env
# line or the upload URL can't carry never reaches an env file.
CONFIG_SECRETS = (
    (("thingsboard", "access_token"), THINGSBOARD_ACCESS_TOKEN, False),
    (("addons", "plate_recognizer", "token"), PLATE_RECOGNIZER_TOKEN, True),
)
ENV_SECRETS = (("TOKEN", PLATE_RECOGNIZER_TOKEN), ("LICENSE_KEY", PLATE_RECOGNIZER_LICENSE_KEY))
# What plate-recognizer.env.j2 wrote before it rendered the secrets: none of them is a value.
ENV_PLACEHOLDERS = {"", "YYYYY", "XXXXX"}
SECRET_FILE_MODE = 0o640  # as tasks/secrets.yml creates them, root:<code group>
CONFIG_REMEDY = "Enter it on the control app's Device page and delete the key."
# A number's text as YAML wrote it, up to whatever ends a plain scalar in block or flow style.
_PLAIN_SCALAR = re.compile(r"[^\s,\[\]{}#]+")


class _SecretsUnreadable(Exception):
    """The secrets directory or a file in it can't be read. The message names the path, never a value."""


def _read_secret(secrets_dir, name):
    """A secret file's value, stripped; empty when the file is empty or missing."""
    if not secrets_dir.is_dir():
        raise _SecretsUnreadable(f"ERROR reading the secrets directory {secrets_dir}: not a directory")
    path = secrets_dir / name
    try:
        return path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return ""
    except OSError as error:
        raise _SecretsUnreadable(f"ERROR reading {path}: {error}") from None
    except UnicodeError as error:  # its message quotes a byte of the file
        raise _SecretsUnreadable(f"ERROR reading {path}: {_not_utf8(error)}") from None


def _not_utf8(error):
    """A decoding error without its message, which quotes a byte of the file."""
    return f"not UTF-8 ({type(error).__name__})"


def _write_secret(secrets_dir, name, text):
    """Write a secret file. A missing one is made first as tmsetup makes it: 0640, the directory's group, and as
    root, owned by root."""
    path = secrets_dir / name
    if not path.exists():
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, SECRET_FILE_MODE)
        try:
            os.fchmod(fd, SECRET_FILE_MODE)  # whatever the umask
            os.fchown(fd, 0 if os.geteuid() == 0 else -1, secrets_dir.stat().st_gid)
        finally:
            os.close(fd)
    write_atomic(path, text + "\n")


def _find(config, path):
    """(mapping, key) for a key path whose mappings are all there and that holds the key, else None."""
    node = config
    for key in path[:-1]:
        node = node.get(key) if isinstance(node, dict) else None
    if isinstance(node, dict) and path[-1] in node:
        return node, path[-1]
    return None


def _token_text(mapping, key, loaded_text):
    """The value as text, or None if it isn't text or a number: a boolean, a date, a list or mapping.

    YAML reads a token of digits as a number, which would lose leading zeros, a long int's digits as a float, or an
    exponent's form, so a number's text is read from the file as it was written.
    """
    value = mapping[key]
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return None
    if isinstance(value, str):
        text = value.strip()
    else:
        line, column = mapping.lc.value(key)
        written = _PLAIN_SCALAR.match(loaded_text.split("\n")[line], column)
        text = written.group(0) if written else str(value)
    return text


def _is_empty(value):
    return value is None or (isinstance(value, str) and not value.strip())


def _is_blank(line):
    return not line.strip()


def _last_entry(mapping, key):
    """(mapping, key) of the entry on the last line of the one at key: itself, or the deepest last key of a block
    mapping. None when that line ends a list or a flow-style mapping, after which ruamel keeps lines on the next key
    instead."""
    value = mapping[key]
    while isinstance(value, CommentedMap) and value and not value.fa.flow_style():
        mapping, key = value, list(value)[-1]
        value = mapping[key]
    if isinstance(value, (CommentedMap, CommentedSeq)):
        return None
    return mapping, key


def _append_after(mapping, key, lines):
    """Put comment and blank lines after the entry at key. ruamel keeps such lines on the key whose line they
    follow, as the text after its value: the rest of that line, then whole lines. Blank lines that would follow
    blank lines are dropped, so taking out a section between two others leaves one blank line, not two."""
    found = _last_entry(mapping, key)
    if found is None:
        return False
    tokens = found[0].ca.items.setdefault(found[1], [None, None, None, None])
    existing = tokens[2].value if tokens[2] is not None else "\n"
    after_line = existing.split("\n")
    if len(after_line) >= 3 and _is_blank(after_line[-2]):
        kept = lines.splitlines(keepends=True)
        while kept and _is_blank(kept[0]):
            kept.pop(0)
        lines = "".join(kept)
    if not lines:
        return True
    if tokens[2] is None:
        tokens[2] = CommentToken(existing + lines, CommentMark(0), None)
    else:
        tokens[2].value += lines
    return True


def _put_before(mapping, key, lines):
    """Put comment and blank lines before the entry at key, where ruamel keeps the lines that follow a list or a
    flow-style mapping."""
    tokens = mapping.ca.items.setdefault(key, [None, None, None, None])
    before = [CommentToken(line, CommentMark(0), None) for line in lines.splitlines(keepends=True)]
    tokens[1] = before + (tokens[1] or [])


def _end_with(config, lines):
    """End the document with these lines in place of the blank lines its last entry is followed by."""
    found = _last_entry(config, list(config)[-1]) if config else None
    if found is None:
        return
    tokens = found[0].ca.items.setdefault(found[1], [None, None, None, None])
    line_end, _, after = (tokens[2].value if tokens[2] is not None else "\n").partition("\n")
    kept = after.splitlines(keepends=True)
    while kept and _is_blank(kept[-1]):
        kept.pop()
    text = line_end + "\n" + "".join(kept) + lines
    if tokens[2] is None:
        tokens[2] = CommentToken(text, CommentMark(0), None)
    else:
        tokens[2].value = text


def _delete(config, path, prune):
    """Delete the key at path and, with prune, every mapping on the path that leaves empty.

    The comment and blank lines that followed the key's line move to the entry before it, so the sections around it
    keep their spacing. The key's own end-of-line comment goes with it.
    """
    parents = [config]
    for key in path[:-1]:
        parents.append(parents[-1][key])
    at_the_end = all(list(parent)[-1] == key for parent, key in zip(parents, path))
    tokens = parents[-1].ca.items.get(path[-1])
    following = tokens[2].value.partition("\n")[2] if tokens and tokens[2] is not None else ""
    depth = len(path) - 1
    while True:
        mapping, key = parents[depth], path[depth]
        keys = list(mapping)
        index = keys.index(key)
        del mapping[key]
        mapping.ca.items.pop(key, None)
        if mapping or depth == 0 or not prune:
            break
        depth -= 1
    if at_the_end:
        # The blank lines that came before the key would now end the file.
        _end_with(config, following)
    elif not following:
        return
    elif index > 0 and _append_after(mapping, keys[index - 1], following):
        pass
    else:
        # After a list, a flow-style or empty mapping (such as thingsboard: {}), or nothing: before the next entry
        next_entry = _next_entry(parents, path, depth, keys, index)
        if next_entry:
            _put_before(*next_entry, following)


def _next_entry(parents, path, depth, keys, index):
    """(mapping, key) of the entry after the deleted one at path[depth], whose keys were keys, or None."""
    if index + 1 < len(keys):
        return parents[depth], keys[index + 1]
    for level in range(depth - 1, -1, -1):
        siblings = list(parents[level])
        position = siblings.index(path[level])
        if position + 1 < len(siblings):
            return parents[level], siblings[position + 1]
    return None


def _warn_secret(path, message):
    print(f"{PREFIX} WARNING {path}: {message}", file=sys.stderr)


def _unexpected(path, step, *args):
    """Run a step and turn any error it didn't foresee into an ERROR line with the error's kind only: its message, or
    a traceback in the install log, could quote a value."""
    try:
        return step(*args)
    except Exception as error:
        print(f"{PREFIX} ERROR {path}: {type(error).__name__}", file=sys.stderr)
        return 1


def run_node_red(config_path, secrets_dir, dry_run=False):
    """Move thingsboard.access_token and addons.plate_recognizer.token from Node-RED's config.yml to the secret files,
    and delete keys left with no value. Return a process exit code.

    A secret file that already holds a value keeps it, and the key is deleted all the same (with a warning when the
    two differ; the backup keeps the other value). Nothing printed holds a value or the file's text.
    """
    return _unexpected(config_path, _run_node_red, Path(config_path), Path(secrets_dir), dry_run)


def _run_node_red(config_path, secrets_dir, dry_run):
    try:
        document = RoundTripFile(config_path, mapping_indent=4)  # as config.yml.j2 indents
    except OSError as error:
        print(f"{PREFIX} ERROR reading {config_path}: {error}", file=sys.stderr)
        return 1
    except YAMLError as error:
        print(f"{PREFIX} ERROR reading {config_path}: {_describe_yaml_error(error)}", file=sys.stderr)
        return 1
    except UnicodeError as error:
        print(f"{PREFIX} ERROR reading {config_path}: {_not_utf8(error)}", file=sys.stderr)
        return 1

    steps = []  # (what a dry run would do, what was done)
    writes = []  # (secret file, text)
    deletions = []  # (key path, prune)
    for path, name, prune in CONFIG_SECRETS:
        found = _find(document.data, path)
        if found is None:
            continue
        mapping, key = found
        dotted = ".".join(path)
        if _is_empty(mapping[key]):
            steps.append((f"remove the empty {dotted}", f"removed the empty {dotted}"))
            deletions.append((path, prune))
            continue
        text = _token_text(mapping, key, document.loaded_text)
        if text is None:
            _warn_secret(config_path, f"{dotted} isn't text; left as it is. {CONFIG_REMEDY}")
            continue
        if not is_valid_value(name, text):
            _warn_secret(config_path, f"{dotted} isn't {VALUE_RULES[name]}; left as it is. {CONFIG_REMEDY}")
            continue
        try:
            current = _read_secret(secrets_dir, name)
        except _SecretsUnreadable as error:
            print(f"{PREFIX} {error}", file=sys.stderr)
            return 1
        if current:
            if current != text:
                removal = "would be removed" if dry_run else "is removed"
                _warn_secret(
                    config_path,
                    f"{dotted} differs from the secrets file {name}, which is kept; the key {removal} from "
                    "config.yml, and the backup keeps its value.",
                )
            steps.append((
                f"remove {dotted} from config.yml, which the secrets file already holds",
                f"removed {dotted} from config.yml, which the secrets file already holds",
            ))
        else:
            writes.append((name, text))
            steps.append((f"move {dotted} to the secrets file", f"moved {dotted} to the secrets file"))
        deletions.append((path, prune))

    if not steps:
        print(f"{PREFIX} {config_path}: up to date")
        return 0
    if dry_run:
        print(f"{PREFIX} {config_path}: would " + ", ".join(would for would, _ in steps))
        return 0
    # The secret files first: if saving config.yml fails, the next run finds the same value in both and only
    # deletes the key.
    for name, text in writes:
        try:
            _write_secret(secrets_dir, name, text)
        except OSError as error:
            print(f"{PREFIX} ERROR writing {secrets_dir / name}: {error}", file=sys.stderr)
            return 1
    for path, prune in deletions:
        _delete(document.data, path, prune)
    try:
        backup = document.save()
    except (OSError, ConcurrentEditError) as error:
        print(f"{PREFIX} ERROR writing {config_path}: {error}", file=sys.stderr)
        return 1
    print(f"{PREFIX} {config_path}: " + ", ".join(done for _, done in steps) + f" (backup: {backup})")
    return 0


def _env_values(text):
    """KEY=value lines as a dict, the last of a repeated key winning; comment and blank lines skipped."""
    values = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if separator:
            values[key.strip()] = value.strip()
    return values


def _same_backup(path, text):
    """An existing backup of path that holds text, or None."""
    for backup in sorted(path.parent.glob(f"{path.name}.*.bak")):
        try:
            if read_text(backup) == text:
                return backup
        except (OSError, UnicodeError):
            continue
    return None


def run_plate_recognizer_env(env_path, secrets_dir, dry_run=False):
    """Move a hand-entered TOKEN and LICENSE_KEY from plate-recognizer.env to the secret files. Return a process
    exit code.

    The env file isn't rewritten: tmsetup writes those two lines from the secret files on the same run. A secret file
    that already holds a value keeps it; when the env file's value differs, the env file is backed up first, because
    tmsetup's rewrite would lose that value, and so it is when a value doesn't meet its secret's pattern and stays
    out. A missing env file means the add-on isn't installed.
    """
    return _unexpected(env_path, _run_plate_recognizer_env, Path(env_path), Path(secrets_dir), dry_run)


def _run_plate_recognizer_env(env_path, secrets_dir, dry_run):
    try:
        text = read_text(env_path)  # never through a link, as root
    except FileNotFoundError:
        print(f"{PREFIX} {env_path}: up to date")
        return 0
    except OSError as error:
        print(f"{PREFIX} ERROR reading {env_path}: {error}", file=sys.stderr)
        return 1
    except UnicodeError as error:
        print(f"{PREFIX} ERROR reading {env_path}: {_not_utf8(error)}", file=sys.stderr)
        return 1

    values = _env_values(text)
    moves, differ, refused = [], [], []
    for key, name in ENV_SECRETS:
        value = values.get(key, "")
        if value in ENV_PLACEHOLDERS:
            continue
        if not is_valid_value(name, value):
            refused.append((key, name))
            continue
        try:
            current = _read_secret(secrets_dir, name)
        except _SecretsUnreadable as error:
            print(f"{PREFIX} {error}", file=sys.stderr)
            return 1
        if not current:
            moves.append((key, name, value))
        elif current != value:
            differ.append((key, name))

    if differ or refused:
        backup = None
        if not dry_run:
            try:
                # Once per content: the add-on's setup, which rewrites the lines, doesn't run while it's turned off.
                backup = _same_backup(env_path, text) or back_up(env_path)
            except OSError as error:
                print(f"{PREFIX} ERROR writing a backup of {env_path}: {error}", file=sys.stderr)
                return 1
        for key, name in differ:
            where = f" (backup: {backup})" if backup else ""
            _warn_secret(
                env_path,
                f"{key} differs from the secrets file {name}, which is kept; tmsetup writes the kept value into "
                f"this file{where}.",
            )
        for key, name in refused:
            if backup:
                kept = f"the env file was backed up to {backup}"
            else:
                kept = "a run without --dry-run backs up the env file"
            _warn_secret(
                env_path,
                f"{key} isn't {VALUE_RULES[name]}, so it wasn't moved, and tmsetup writes the secrets file's "
                f"value into this file. Enter it on the control app's Device page; {kept}.",
            )
    if not moves:
        print(f"{PREFIX} {env_path}: up to date")
        return 0
    keys = ", ".join(key for key, _, _ in moves)
    if dry_run:
        print(f"{PREFIX} {env_path}: would move {keys} to the secrets files")
        return 0
    for _, name, value in moves:
        try:
            _write_secret(secrets_dir, name, value)
        except OSError as error:
            print(f"{PREFIX} ERROR writing {secrets_dir / name}: {error}", file=sys.stderr)
            return 1
    print(f"{PREFIX} {env_path}: moved {keys} to the secrets files")
    return 0
