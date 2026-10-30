"""The diagnostics text (GET /system/diagnostics) that an admin sends with a request for help: the device's facts, its
time state, the status report, the services, the manifest, and the last lines of each unit's journal.

The whole text is redacted before it leaves the device: every device secret's value, every secret-looking value in
the apps' .env files (the broker password can show up inside a URL in a log line), config.yml's ThingsBoard access
token (Node-RED's journal can show it as the MQTT username), and the value after any password-, token-, or
secret-style key.
"""

import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from tm_control import fake
from tm_control.adapters import nodered, sysinfo, systemd
from tm_control.adapters.redact import redact
from tm_control.core.checks import Report
from tm_control.core.secrets import DEVICE_SECRETS, MissingSecret
from tm_control.modules.services.units import read_units, service, units_for
from tm_control.modules.system.info import SystemInfo

JOURNAL_LINES = 50
# Relative to the code directory; a missing or unreadable one is skipped.
ENV_FILES = ("node-red-tm/node-red-tm.env", "frigate/frigate.env", "plate-recognizer/plate-recognizer.env")
ENV_SECRET_KEY = re.compile(r"PASSWORD|PASSWD|SECRET|TOKEN|KEY", re.IGNORECASE)
ENV_MIN_VALUE = 4  # shorter values would redact ordinary words


def env_secret_values(codedir: Path) -> list[str]:
    """The values of KEY=value lines in ENV_FILES whose key names a secret, as written, unquoted, and URL-encoded."""
    values = []
    for relative in ENV_FILES:
        try:
            text = (Path(codedir) / relative).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, sep, value = line.partition("=")
            if not sep or not ENV_SECRET_KEY.search(key):
                continue
            value = value.strip()
            unquoted = value.strip("\"'")
            values += [v for v in {value, unquoted, quote(unquoted, safe="")} if len(v) >= ENV_MIN_VALUE]
    return values


def config_secret_values(codedir: Path) -> list[str]:
    """config.yml's thingsboard.access_token, its one secret, as written and URL-encoded; none when it's blank or
    short, or config.yml can't be read."""
    thingsboard = (nodered.config(codedir).data or {}).get("thingsboard")
    token = thingsboard.get("access_token") if isinstance(thingsboard, dict) else None
    if not isinstance(token, (str, int)) or isinstance(token, bool):
        return []
    token = str(token).strip()
    return [v for v in {token, quote(token, safe="")} if len(v) >= ENV_MIN_VALUE]


def secret_values(app_state) -> list[str]:
    """Every value to redact: each device secret that can be read, and on a device the .env files' secret values and
    the ThingsBoard access token."""
    values = []
    for name in DEVICE_SECRETS:
        try:
            values.append(app_state.secrets.read(name))
        except (MissingSecret, ValueError):
            continue
    if not app_state.settings.fake:
        values += env_secret_values(Path(app_state.manifest.codedir))
        values += config_secret_values(Path(app_state.manifest.codedir))
    return values


def _lines(lines: list[str] | None, what: str) -> str:
    if lines is None:
        return f"({what} couldn't be read.)"
    return "\n".join(lines) if lines else "(No entries.)"


def _status(report: Report) -> str:
    counts = ", ".join(f"{count} {status}" for status, count in report.summary.items())
    out = [f"Generated: {report.generated_at}", f"Summary: {counts}"]
    for group in report.groups:
        out.append(f"{group.title}:")
        for check in group.checks:
            fix = f" Fix: {check.fix.text}" if check.fix else ""
            out.append(f"  [{check.status}] {check.title} ({check.id}): {check.detail}{fix}")
    return "\n".join(out)


def _services(app_state) -> str:
    units = units_for(app_state.manifest)
    values = read_units(app_state.settings, units)
    out = []
    for unit in units:
        state = service(unit, values.get(unit.unit))
        since = f", since {state.since}" if state.since else ""
        out.append(f"{state.unit}: {state.active_state} ({state.sub_state}){since}, {state.restarts} restarts")
    return "\n".join(out)


def build(app_state, info: SystemInfo, hostname: str, now: datetime) -> str:
    """The diagnostics text, redacted. hostname is already limited to [A-Za-z0-9.-]."""
    settings = app_state.settings
    time_state = fake.time_state() if settings.fake else sysinfo.time_state()
    sections = [
        ("Device", json.dumps(info.model_dump(), indent=2)),
        ("Date and time", _lines(time_state, "timedatectl")),
        ("Status", _status(app_state.status.report())),
        ("Services", _services(app_state)),
        ("Manifest", app_state.manifest.model_dump_json(indent=2)),
    ]
    units = units_for(app_state.manifest)
    tail = fake.journal_tail if settings.fake else systemd.journal_tail
    # All at once, so a slow journal costs one timeout rather than one per unit.
    with ThreadPoolExecutor(max_workers=max(1, len(units)), thread_name_prefix="journal-tail") as pool:
        tails = list(pool.map(lambda unit: tail(unit.unit, JOURNAL_LINES), units))
    for unit, lines in zip(units, tails):
        sections.append((f"Journal: {unit.unit} (last {JOURNAL_LINES} lines)", _lines(lines, "The journal")))
    header = [
        "Traffic Monitor diagnostics",
        f"Device: {hostname}",
        f"Generated: {now.isoformat(timespec='seconds')}",
        "Passwords, tokens, and other secrets in this text are replaced with <redacted>.",
    ]
    text = "\n".join(header) + "\n" + "".join(f"\n== {title} ==\n{body}\n" for title, body in sections)
    return redact(text, secret_values(app_state))
