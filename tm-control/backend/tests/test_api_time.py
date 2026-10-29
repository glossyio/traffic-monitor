import sqlite3
import time
from datetime import datetime, timedelta, timezone

import pytest

from tm_control.adapters import timedate
from tm_control.adapters.command import CommandResult
from tm_control.core.checks import Context, Fix
from tm_control.modules import MODULES
from tm_control.modules.time.checks import clock

ORIGIN = {"Origin": "http://tm-test.local"}
ADMIN = ("admin", "correct horse 1")
VIEWER = ("viewer", "viewer pass 1")
STDERR = "Failed to set time zone: synthetic-stderr-detail"
ZONES = ["America/Los_Angeles", "Etc/UTC", "Europe/Berlin", "Pacific/Auckland"]
CONTAINERS = ["traffic-monitor.service", "revproxy.service"]
PROPERTIES = ["Timezone", "NTP", "NTPSynchronized", "CanNTP", "RTCTimeUSec"]


class FakeTimedatectl:
    """Stands in for command.run in the timedate adapter: answers `timedatectl show` and `list-timezones` from its
    attributes, records every argv and its keyword arguments, and applies the set-* commands it accepts."""

    def __init__(self):
        self.props = {
            "Timezone": "America/Los_Angeles",
            "LocalRTC": "no",
            "CanNTP": "yes",
            "NTP": "yes",
            "NTPSynchronized": "yes",
            "TimeUSec": "Wed 2026-10-28 14:41:35 PDT",
            "RTCTimeUSec": "Wed 2026-10-28 21:41:35 2026",
        }
        self.zones = list(ZONES)
        self.failing = {}  # verb, or verb and argument ("set-ntp true") -> exit status
        self.calls = []

    def __call__(self, argv, **kwargs):
        argv = list(argv)
        self.calls.append((argv, kwargs))
        assert argv[0] == "timedatectl", argv
        verb = argv[1]
        for key in (verb, " ".join(argv[1:3])):
            if key in self.failing:
                return CommandResult(self.failing[key], "", STDERR, False)
        if verb == "show":
            asked = [arg.removeprefix("--property=") for arg in argv[2:]]
            assert asked and all(arg.startswith("--property=") for arg in argv[2:]), argv
            return CommandResult(0, "".join(f"{key}={self.props[key]}\n" for key in asked if key in self.props),
                                 "", False)
        if verb == "list-timezones":
            return CommandResult(0, "".join(f"{zone}\n" for zone in self.zones), "", False)
        if verb == "set-timezone":
            self.props["Timezone"] = argv[2]
        elif verb == "set-ntp":
            enabled = argv[2] == "true"
            self.props["NTP"] = "yes" if enabled else "no"
            if not enabled:  # turning it on doesn't reach a time source by itself
                self.props["NTPSynchronized"] = "no"
        elif verb != "set-time":
            raise AssertionError(f"unexpected command {argv}")
        return CommandResult(0, "", "", False)

    def changes(self):
        return [argv[1:] for argv, _ in self.calls if argv[1].startswith("set-")]

    def ran(self, verb):
        return sum(1 for argv, _ in self.calls if argv[1] == verb)


@pytest.fixture(autouse=True)
def no_cached_timezones(monkeypatch):
    monkeypatch.setattr(timedate, "_timezones", None)


@pytest.fixture
def timedatectl(monkeypatch):
    fake = FakeTimedatectl()
    monkeypatch.setattr(timedate, "run", fake)
    return fake


@pytest.fixture
def systemctl(monkeypatch):
    calls = []

    def run(argv, **kwargs):
        calls.append(list(argv))
        return CommandResult(0, "", "", False)

    monkeypatch.setattr("tm_control.adapters.systemd.run", run)
    return calls


@pytest.fixture
def tzset(monkeypatch):
    calls = []
    monkeypatch.setattr(time, "tzset", lambda: calls.append(True))
    return calls


def audit_rows(client):
    con = sqlite3.connect(client.app.state.settings.state_dir / "state.sqlite")
    try:
        return [tuple(row) for row in con.execute("SELECT action, detail FROM audit ORDER BY id")]
    finally:
        con.close()


def change(client, body):
    return client.post("/api/v1/time", json=body, headers=ORIGIN)


# Registration


def test_the_time_module_comes_last_with_its_group():
    assert MODULES[-1].id == "time"
    assert [(g.id, g.title) for g in MODULES[-1].check_groups] == [("time", "Date and time")]
    groups = [group.id for module in MODULES for group in module.check_groups]
    assert groups[-1] == "time"


# Reading


def test_time_state_for_a_viewer(device_client, login, timedatectl):
    login(device_client, *VIEWER)
    r = device_client.get("/api/v1/time")
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"device_time", "timezone", "ntp", "rtc_time"}
    assert body["timezone"] == "America/Los_Angeles"
    assert body["ntp"] == {"enabled": True, "synchronized": True, "available": True}
    assert body["rtc_time"] == "Wed 2026-10-28 21:41:35 2026"
    device_time = datetime.fromisoformat(body["device_time"])
    assert device_time.utcoffset() is not None and device_time.microsecond == 0
    assert abs(device_time - datetime.now(timezone.utc)) < timedelta(seconds=5)
    (show,) = [(argv, kwargs) for argv, kwargs in timedatectl.calls if argv[1] == "show"]
    assert set(show[0][2:]) == {f"--property={name}" for name in PROPERTIES}
    assert show[1]["timeout"] <= 4

    timedatectl.props |= {"CanNTP": "no", "NTP": "no", "NTPSynchronized": "no", "RTCTimeUSec": "n/a"}
    body = device_client.get("/api/v1/time").json()
    assert body["ntp"] == {"enabled": False, "synchronized": False, "available": False}
    assert body["rtc_time"] is None
    del timedatectl.props["RTCTimeUSec"]
    assert device_client.get("/api/v1/time").json()["rtc_time"] is None


def test_time_needs_a_session(device_client, timedatectl):
    assert device_client.get("/api/v1/time").status_code == 401
    assert device_client.get("/api/v1/time/timezones").status_code == 401
    assert timedatectl.calls == []


def test_timezones_list_is_cached(device_client, login, timedatectl):
    login(device_client, *VIEWER)
    for _ in range(2):
        r = device_client.get("/api/v1/time/timezones")
        assert r.status_code == 200, r.text
        assert r.json() == ZONES
    assert timedatectl.ran("list-timezones") == 1


def test_a_failed_timezones_list_is_not_cached(device_client, login, timedatectl):
    login(device_client, *VIEWER)
    timedatectl.failing["list-timezones"] = 1
    r = device_client.get("/api/v1/time/timezones")
    assert r.status_code == 500 and r.json()["error"]["code"] == "internal"
    del timedatectl.failing["list-timezones"]
    assert device_client.get("/api/v1/time/timezones").json() == ZONES


def test_device_card_uses_the_same_clock(device_client, login, timedatectl, monkeypatch):
    fixed = datetime(2026, 10, 28, 14, 41, 35, tzinfo=timezone(timedelta(hours=-7)))
    monkeypatch.setattr(timedate, "now", lambda: fixed)
    login(device_client, *VIEWER)
    assert device_client.get("/api/v1/system/device").json()["time"] == "2026-10-28T14:41:35-07:00"
    assert device_client.get("/api/v1/time").json()["device_time"] == "2026-10-28T14:41:35-07:00"


# Setting


def test_set_from_browser_with_ntp_synchronized_keeps_the_time(device_client, login, timedatectl, systemctl, tzset):
    login(device_client, *ADMIN)
    r = change(device_client, {"time": "2026-10-28T21:41:35.123Z", "timezone": "Europe/Berlin"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert timedatectl.ran("set-time") == 0
    assert timedatectl.changes() == [["set-timezone", "Europe/Berlin"]]
    assert body["time_kept_from_ntp"] is True
    assert body["restarting"] == CONTAINERS
    assert body["timezone"] == "Europe/Berlin"
    assert body["ntp"] == {"enabled": True, "synchronized": True, "available": True}
    assert systemctl == [["systemctl", "restart", "--no-block", unit] for unit in CONTAINERS]
    assert tzset == [True]


def test_set_from_browser_without_ntp_sync_sets_the_time_turns_ntp_back_on_then_the_zone(
    device_client, login, timedatectl, systemctl, tzset
):
    """NTP on but unsynchronized (offline): NTP off for set-time, back on after it so the device resyncs once it
    reaches a time source, then the zone."""
    timedatectl.props["NTPSynchronized"] = "no"
    login(device_client, *ADMIN)
    r = change(device_client, {"time": "2026-10-28T23:41:35.500+02:00", "timezone": "Pacific/Auckland"})
    assert r.status_code == 200, r.text
    assert timedatectl.changes() == [
        ["set-ntp", "false"],
        ["set-time", "2026-10-28 21:41:35"],
        ["set-ntp", "true"],
        ["set-timezone", "Pacific/Auckland"],
    ]
    (set_time,) = [kwargs for argv, kwargs in timedatectl.calls if argv[1] == "set-time"]
    assert set_time["env"] == {"TZ": "UTC"}
    body = r.json()
    assert body["time_kept_from_ntp"] is False
    assert body["restarting"] == CONTAINERS
    assert body["ntp"]["enabled"] is True
    assert systemctl == [["systemctl", "restart", "--no-block", unit] for unit in CONTAINERS] and tzset == [True]


def test_a_zone_change_alone_queues_the_restart(device_client, login, timedatectl, systemctl, tzset):
    login(device_client, *ADMIN)
    r = change(device_client, {"timezone": "Europe/Berlin"})
    assert r.status_code == 200, r.text
    assert timedatectl.changes() == [["set-timezone", "Europe/Berlin"]]
    assert r.json()["restarting"] == CONTAINERS
    assert systemctl == [["systemctl", "restart", "--no-block", unit] for unit in CONTAINERS] and tzset == [True]


def test_an_ntp_toggle_runs_before_the_zone_and_its_failure_leaves_the_zone(
    device_client, login, timedatectl, systemctl, tzset
):
    login(device_client, *ADMIN)
    r = change(device_client, {"timezone": "Europe/Berlin", "ntp": False})
    assert r.status_code == 200, r.text
    assert timedatectl.changes() == [["set-ntp", "false"], ["set-timezone", "Europe/Berlin"]]
    assert r.json()["restarting"] == CONTAINERS and len(systemctl) == 2

    timedatectl.calls.clear()
    systemctl.clear()
    tzset.clear()
    timedatectl.failing["set-ntp"] = 1
    r = change(device_client, {"timezone": "Pacific/Auckland", "ntp": True})
    assert r.status_code == 500 and r.json()["error"]["code"] == "internal"
    assert timedatectl.changes() == [["set-ntp", "true"]]
    assert timedatectl.props["Timezone"] == "Europe/Berlin"
    assert systemctl == [] and tzset == []


def test_a_failed_set_time_offline_turns_ntp_back_on(device_client, login, timedatectl, systemctl):
    timedatectl.props["NTPSynchronized"] = "no"
    timedatectl.failing["set-time"] = 1
    login(device_client, *ADMIN)
    r = change(device_client, {"time": "2026-10-28T21:41:35Z"})
    assert r.status_code == 500, r.text
    assert r.json()["error"]["message"] == "The time couldn't be set; NTP is back on."
    assert "synthetic-stderr-detail" not in r.text
    assert timedatectl.changes() == [["set-ntp", "false"], ["set-time", "2026-10-28 21:41:35"], ["set-ntp", "true"]]
    assert timedatectl.props["NTP"] == "yes"
    (check,) = clock(Context(None, None, None))
    assert check.status == "warn" and check.detail != "Set by hand."
    assert [row for row in audit_rows(device_client) if row[0] == "time.set"] == []


@pytest.mark.parametrize(
    ("set_time_fails", "message", "audited"),
    [
        (True, "The time couldn't be set, and NTP couldn't be turned back on, so it's now off.", "ntp"),
        (False, "The time was set, but NTP couldn't be turned back on, so it's now off.", "ntp, time"),
    ],
)
def test_ntp_that_cant_be_turned_back_on_is_reported_off(
    device_client, login, timedatectl, systemctl, set_time_fails, message, audited
):
    timedatectl.props["NTPSynchronized"] = "no"
    timedatectl.failing["set-ntp true"] = 1
    if set_time_fails:
        timedatectl.failing["set-time"] = 1
    login(device_client, *ADMIN)
    r = change(device_client, {"time": "2026-10-28T21:41:35Z", "timezone": "Europe/Berlin"})
    assert r.status_code == 500, r.text
    assert r.json()["error"]["message"] == message and "synthetic-stderr-detail" not in r.text
    assert timedatectl.changes() == [["set-ntp", "false"], ["set-time", "2026-10-28 21:41:35"], ["set-ntp", "true"]]
    assert systemctl == []
    assert [row for row in audit_rows(device_client) if row[0] == "time.set"] == [("time.set", audited)]


def test_set_time_with_ntp_off_leaves_ntp_alone(device_client, login, timedatectl, systemctl, tzset):
    timedatectl.props |= {"NTP": "no", "NTPSynchronized": "no"}
    login(device_client, *ADMIN)
    r = change(device_client, {"time": "2026-10-28T21:41:35Z"})
    assert r.status_code == 200, r.text
    assert timedatectl.changes() == [["set-time", "2026-10-28 21:41:35"]]
    assert r.json()["restarting"] == [] and systemctl == [] and tzset == []


def test_set_time_then_turn_ntp_back_on(device_client, login, timedatectl, systemctl):
    timedatectl.props["NTPSynchronized"] = "no"
    login(device_client, *ADMIN)
    r = change(device_client, {"time": "2026-10-28T21:41:35Z", "ntp": True})
    assert r.status_code == 200, r.text
    assert timedatectl.changes() == [["set-ntp", "false"], ["set-time", "2026-10-28 21:41:35"], ["set-ntp", "true"]]
    assert r.json()["ntp"]["enabled"] is True


def test_turning_ntp_off_with_a_time_sets_the_time(device_client, login, timedatectl, systemctl):
    login(device_client, *ADMIN)
    r = change(device_client, {"time": "2026-10-28T21:41:35Z", "ntp": False})
    assert r.status_code == 200, r.text
    assert timedatectl.changes() == [["set-ntp", "false"], ["set-time", "2026-10-28 21:41:35"]]
    assert r.json()["time_kept_from_ntp"] is False and r.json()["ntp"]["enabled"] is False


def test_timezone_unchanged_restarts_nothing(device_client, login, timedatectl, systemctl, tzset):
    login(device_client, *ADMIN)
    r = change(device_client, {"timezone": "America/Los_Angeles"})
    assert r.status_code == 200, r.text
    assert r.json()["restarting"] == []
    assert timedatectl.changes() == []
    assert systemctl == [] and tzset == []


def test_ntp_toggle_alone_restarts_nothing(device_client, login, timedatectl, systemctl, tzset):
    login(device_client, *ADMIN)
    r = change(device_client, {"ntp": False})
    assert r.status_code == 200, r.text
    assert timedatectl.changes() == [["set-ntp", "false"]]
    body = r.json()
    assert body["restarting"] == [] and body["time_kept_from_ntp"] is False
    assert body["ntp"]["enabled"] is False
    r = change(device_client, {"ntp": True})
    assert timedatectl.changes() == [["set-ntp", "false"], ["set-ntp", "true"]]
    assert r.json()["restarting"] == []
    assert systemctl == [] and tzset == []


def test_turning_on_ntp_where_there_is_none_is_refused(device_client, login, timedatectl):
    timedatectl.props |= {"CanNTP": "no", "NTP": "no", "NTPSynchronized": "no"}
    login(device_client, *ADMIN)
    r = change(device_client, {"ntp": True})
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation"
    assert timedatectl.changes() == []


@pytest.mark.parametrize(
    "body",
    [
        {"timezone": "Mars/Olympus"},
        {"timezone": ""},
        {"time": "1999-12-31T00:00:00Z"},
        {"time": "2025-12-31T23:59:59Z"},
        {"time": "2046-01-01T00:00:01Z"},
        {"time": "2050-01-01T00:00:00Z"},
        {"time": "2026-10-28T21:41:35"},  # no offset
        {"time": "2026-10-28"},
        {"time": "yesterday"},
        {"time": "2026-10-28T21:41:35Z", "timezone": "Mars/Olympus"},
        {},
        {"timezone": None, "ntp": None, "time": None},
    ],
)
def test_refuses_an_unknown_timezone_and_an_implausible_time(device_client, login, timedatectl, systemctl, body):
    timedatectl.props |= {"NTP": "no", "NTPSynchronized": "no"}
    login(device_client, *ADMIN)
    r = change(device_client, body)
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "validation"
    assert timedatectl.changes() == [] and systemctl == []
    assert [row for row in audit_rows(device_client) if row[0] == "time.set"] == []


@pytest.mark.parametrize(
    ("sent", "argument"),
    [("2026-01-01T00:00:00Z", "2026-01-01 00:00:00"), ("2046-01-01T00:00:00Z", "2046-01-01 00:00:00")],
)
def test_the_bounds_themselves_are_accepted(device_client, login, timedatectl, sent, argument):
    timedatectl.props |= {"NTP": "no", "NTPSynchronized": "no"}
    login(device_client, *ADMIN)
    r = change(device_client, {"time": sent})
    assert r.status_code == 200, r.text
    assert timedatectl.changes() == [["set-time", argument]]


def test_time_change_is_admin_only_and_audited(device_client, login, timedatectl, systemctl):
    timedatectl.props["NTPSynchronized"] = "no"
    login(device_client, *VIEWER)
    r = change(device_client, {"timezone": "Europe/Berlin"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "forbidden"
    assert timedatectl.changes() == [] and systemctl == []

    login(device_client, *ADMIN)
    r = change(device_client, {"time": "2026-10-28T21:41:35Z", "timezone": "Europe/Berlin"})
    assert r.status_code == 200, r.text
    (row,) = [row for row in audit_rows(device_client) if row[0] == "time.set"]
    detail = row[1]
    assert detail == "time, timezone"  # NTP was turned off for set-time and back on, so it did not change
    for value in ("2026", "21:41", "Europe", "Berlin", "false"):
        assert value not in detail


def test_timedatectl_failure_is_an_api_error_without_stderr(device_client, login, timedatectl, systemctl, tzset):
    login(device_client, *ADMIN)
    timedatectl.failing["set-timezone"] = 1
    r = change(device_client, {"timezone": "Europe/Berlin"})
    assert r.status_code == 500, r.text
    error = r.json()["error"]
    assert error["code"] == "internal" and "time zone" in error["message"]
    assert "synthetic-stderr-detail" not in r.text
    assert systemctl == [] and tzset == []

    del timedatectl.failing["set-timezone"]
    timedatectl.props["NTPSynchronized"] = "no"
    timedatectl.failing["set-time"] = 1
    r = change(device_client, {"time": "2026-10-28T21:41:35Z"})
    assert r.status_code == 500 and "synthetic-stderr-detail" not in r.text
    assert r.json()["error"]["code"] == "internal"

    timedatectl.failing["show"] = 1
    r = device_client.get("/api/v1/time")
    assert r.status_code == 500 and r.json()["error"]["code"] == "internal"


def test_a_missing_timedatectl_is_an_api_error(device_client, login, monkeypatch):
    def missing(argv, **kwargs):
        raise FileNotFoundError(2, "No such file or directory")

    monkeypatch.setattr(timedate, "run", missing)
    login(device_client, *ADMIN)
    assert device_client.get("/api/v1/time").status_code == 500
    r = device_client.get("/api/v1/time/timezones")
    assert r.status_code == 500 and r.json()["error"]["code"] == "internal"
    assert timedate.set_ntp(False).returncode == 127


def test_the_response_reports_the_change_even_if_the_reread_fails(
    device_client, login, timedatectl, systemctl, monkeypatch
):
    def run(argv, **kwargs):
        result = timedatectl(argv, **kwargs)
        if argv[1] == "set-timezone":
            timedatectl.failing["show"] = 1
        return result

    monkeypatch.setattr(timedate, "run", run)
    login(device_client, *ADMIN)
    r = change(device_client, {"timezone": "Europe/Berlin"})
    assert r.status_code == 200, r.text
    assert r.json()["timezone"] == "Europe/Berlin" and r.json()["restarting"] == CONTAINERS
    assert len(systemctl) == 2


# Fake mode


def test_fake_mode_keeps_its_own_clock(claimed_client, login, monkeypatch):
    def no_run(argv, **kwargs):
        raise AssertionError(f"fake mode ran {argv}")

    monkeypatch.setattr(timedate, "run", no_run)
    monkeypatch.setattr("tm_control.adapters.systemd.run", no_run)
    login(claimed_client, *ADMIN)
    state = claimed_client.get("/api/v1/time").json()
    assert state["timezone"] == "Etc/UTC"
    assert state["ntp"] == {"enabled": True, "synchronized": True, "available": True}
    assert datetime.fromisoformat(state["device_time"]).utcoffset() == timedelta(0)
    zones = claimed_client.get("/api/v1/time/timezones").json()
    assert set(ZONES) <= set(zones)

    assert change(claimed_client, {"timezone": "Mars/Olympus"}).status_code == 422
    r = change(claimed_client, {"time": "2026-10-28T21:41:35Z", "timezone": "Europe/Berlin"})
    assert r.status_code == 200, r.text
    assert r.json()["time_kept_from_ntp"] is True and r.json()["restarting"] == CONTAINERS
    assert claimed_client.get("/api/v1/time").json()["timezone"] == "Europe/Berlin"

    r = change(claimed_client, {"ntp": False})
    assert r.json()["ntp"]["enabled"] is False and r.json()["restarting"] == []
    r = change(claimed_client, {"time": "2026-10-28T21:41:35Z"})
    assert r.json()["time_kept_from_ntp"] is False
    assert ("time.set", "ntp") in audit_rows(claimed_client)


def test_openapi_declares_the_time_models(client):
    document = client.app.openapi()

    def schema(path, method):
        return document["paths"][path][method]["responses"]["200"]["content"]["application/json"]["schema"]

    assert schema("/api/v1/time", "get") == {"$ref": "#/components/schemas/TimeState"}
    assert schema("/api/v1/time", "post") == {"$ref": "#/components/schemas/TimeResult"}
    assert schema("/api/v1/time/timezones", "get")["type"] == "array"
    result = document["components"]["schemas"]["TimeResult"]
    assert set(result["properties"]) == {"device_time", "timezone", "ntp", "rtc_time", "time_kept_from_ntp",
                                         "restarting"}


# The check


def run_clock(monkeypatch, timedatectl, now=None):
    monkeypatch.setattr(timedate, "run", timedatectl)
    if now is not None:
        monkeypatch.setattr(timedate, "now", lambda: now)
    return clock(Context(None, None, None))


def test_time_checks(monkeypatch):
    fake = FakeTimedatectl()
    (check,) = run_clock(monkeypatch, fake)
    assert (check.id, check.title, check.status, check.detail) == ("time.plausible", "Clock", "ok", "Synchronized.")
    assert check.fix is None

    link = Fix(kind="link", text="Set the date and time", href="/time")
    (check,) = run_clock(monkeypatch, fake, datetime(2020, 5, 1, 12, 0, tzinfo=timezone.utc))
    assert check.status == "error" and check.fix == link
    assert check.detail == "The clock is wrong; set it on the Date and time page."

    monkeypatch.undo()
    fake.props["NTPSynchronized"] = "no"
    (check,) = run_clock(monkeypatch, fake)
    assert check.status == "warn" and check.fix == link
    assert check.detail == "No time source reachable (offline?); the clock runs on its own."

    fake.props["NTP"] = "no"
    (check,) = run_clock(monkeypatch, fake)
    assert (check.status, check.detail, check.fix) == ("ok", "Set by hand.", None)

    fake.failing["show"] = 1
    (check,) = run_clock(monkeypatch, fake)
    assert check.status == "unknown" and check.title == "Clock" and check.fix is None


def test_device_client_reports_the_clock_without_running_timedatectl(device_client, login, monkeypatch):
    monkeypatch.setattr("tm_control.adapters.systemd.run", lambda argv, **kwargs: CommandResult(1, "", "", False))
    login(device_client, *VIEWER)
    groups = device_client.get("/api/v1/status").json()["groups"]
    assert groups[-1]["id"] == "time"
    assert [(c["id"], c["status"]) for c in groups[-1]["checks"]] == [("time.plausible", "unknown")]
