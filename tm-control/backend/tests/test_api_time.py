import importlib
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from tm_control.adapters import timedate
from tm_control.adapters.command import CommandResult
from tm_control.core.checks import Context, Fix
from tm_control.modules import MODULES
from tm_control.modules.time.checks import clock

# The module, not the APIRouter that tm_control.modules.time exports under the same name
time_router = importlib.import_module("tm_control.modules.time.router")

ORIGIN = {"Origin": "http://tm-test.local"}
ADMIN = ("admin", "correct horse 1")
VIEWER = ("viewer", "viewer pass 1")
STDERR = "Failed to set time zone: synthetic-stderr-detail"
ZONES = ["America/Los_Angeles", "Etc/UTC", "Europe/Berlin", "Pacific/Auckland"]
CONTAINERS = ["traffic-monitor.service", "revproxy.service"]
PROPERTIES = ["Timezone", "NTP", "NTPSynchronized", "CanNTP", "RTCTimeUSec"]


class FakeTimedatectl:
    """Stands in for command.run in the timedate adapter: answers `timedatectl show` and `list-timezones` from its
    attributes, records every argv and its keyword arguments, and applies the set-* commands it accepts. It also
    keeps the device's clock (now()), which set-time moves; `saved`, when set, is the time systemd-timesyncd saved,
    and turning NTP on moves a clock that's behind it forward to it, as timesyncd does when it starts. With `online`,
    turning NTP on also reaches a time source: the clock takes the real time and NTPSynchronized is yes, at once, or
    with `sync_after_shows` only once that many `show` commands have run since, as a sync that lands a moment after
    the put-back."""

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
        self.offset = timedelta(0)  # the device's clock minus the real one
        self.saved = None
        self.online = False
        self.sync_after_shows = None
        self.pending_sync = None  # shows left until the sync lands

    def now(self):
        return (datetime.now(timezone.utc) + self.offset).astimezone()

    def __call__(self, argv, **kwargs):
        argv = list(argv)
        self.calls.append((argv, kwargs))
        assert argv[0] == "timedatectl", argv
        verb = argv[1]
        for key in (verb, " ".join(argv[1:3])):
            if key in self.failing:
                return CommandResult(self.failing[key], "", STDERR, False)
        if verb == "show":
            if self.pending_sync is not None:
                self.pending_sync -= 1
                if self.pending_sync <= 0:
                    self.pending_sync = None
                    self.props["NTPSynchronized"] = "yes"
                    self.offset = timedelta(0)
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
                self.pending_sync = None
            elif self.online and self.sync_after_shows is None:
                self.props["NTPSynchronized"] = "yes"
                self.offset = timedelta(0)
            else:
                if self.saved is not None and self.now() < self.saved:
                    self.offset = self.saved - datetime.now(timezone.utc)
                if self.online:
                    self.pending_sync = self.sync_after_shows
        elif verb == "set-time":
            when = datetime.fromisoformat(argv[2]).replace(tzinfo=timezone.utc)
            self.offset = when - datetime.now(timezone.utc)
        else:
            raise AssertionError(f"unexpected command {argv}")
        return CommandResult(0, "", "", False)

    def changes(self):
        return [argv[1:] for argv, _ in self.calls if argv[1].startswith("set-")]

    def ran(self, verb):
        return sum(1 for argv, _ in self.calls if argv[1] == verb)


@pytest.fixture(autouse=True)
def no_cached_timezones(monkeypatch):
    monkeypatch.setattr(timedate, "_timezones", None)


@pytest.fixture(autouse=True)
def short_settle(monkeypatch):
    """The offline set-time watches the clock for a moment after NTP is back on; not for a second a test."""
    monkeypatch.setattr(time_router, "SETTLE_SECONDS", 0.05)
    monkeypatch.setattr(time_router, "SETTLE_INTERVAL", 0.01)
    monkeypatch.setattr(time_router, "SYNC_SECONDS", 0.05)


@pytest.fixture
def timedatectl(monkeypatch):
    fake = FakeTimedatectl()
    monkeypatch.setattr(timedate, "run", fake)
    monkeypatch.setattr(timedate, "now", fake.now)
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


def test_offline_a_time_the_time_service_puts_back_is_set_again_with_ntp_left_off(
    device_client, login, timedatectl, systemctl
):
    """The device's clock is ahead: timesyncd saved a later time than the browser's, and starting it again moves the
    clock forward to that time. So the time is set again, and NTP stays off."""
    timedatectl.props["NTPSynchronized"] = "no"
    sent = datetime.now(timezone.utc).replace(microsecond=0)
    timedatectl.saved = sent + timedelta(minutes=5)
    login(device_client, *ADMIN)
    r = change(device_client, {"time": sent.isoformat()})
    assert r.status_code == 200, r.text
    changes = timedatectl.changes()
    assert changes[:3] == [["set-ntp", "false"], ["set-time", f"{sent:%Y-%m-%d %H:%M:%S}"], ["set-ntp", "true"]]
    assert [argv[0] for argv in changes[3:]] == ["set-ntp", "set-time"] and changes[3] == ["set-ntp", "false"]
    assert abs(timedatectl.now() - datetime.now(timezone.utc)) < timedelta(seconds=5)
    body = r.json()
    assert body["ntp_left_off"] is True and body["ntp"]["enabled"] is False
    assert [row for row in audit_rows(device_client) if row[0] == "time.set"] == [("time.set", "ntp, time")]


def test_offline_a_time_put_back_a_moment_later_is_caught(device_client, login, timedatectl, systemctl, monkeypatch):
    """On a Pi, timesyncd moves the clock 70 to 200 ms after set-ntp has returned, so the watch's first read can
    miss it."""
    timedatectl.props["NTPSynchronized"] = "no"
    sent = datetime.now(timezone.utc).replace(microsecond=0)
    reads = []

    def now():
        reads.append(True)
        # The first read is the state before the change, the second the watch's first: the clock moves on the
        # watch's second read, after a SETTLE_INTERVAL.
        if len(reads) == 3 and timedatectl.props["NTP"] == "yes":
            timedatectl.offset = timedelta(minutes=5)
        return timedatectl.now()

    monkeypatch.setattr(timedate, "now", now)
    login(device_client, *ADMIN)
    reads.clear()
    r = change(device_client, {"time": sent.isoformat()})
    assert r.status_code == 200, r.text
    assert r.json()["ntp_left_off"] is True and timedatectl.props["NTP"] == "no"


def test_offline_a_time_sent_with_ntp_on_is_still_left_with_ntp_off_when_put_back(
    device_client, login, timedatectl, systemctl
):
    """Turning NTP on again after the put-back would put the device's time back once more: the time wins."""
    timedatectl.props["NTPSynchronized"] = "no"
    sent = datetime.now(timezone.utc).replace(microsecond=0)
    timedatectl.saved = sent + timedelta(minutes=5)
    login(device_client, *ADMIN)
    r = change(device_client, {"time": sent.isoformat(), "ntp": True})
    assert r.status_code == 200, r.text
    changes = timedatectl.changes()
    assert len(changes) == 5 and changes[3] == ["set-ntp", "false"] and changes[4][0] == "set-time"
    body = r.json()
    assert body["ntp_left_off"] is True and body["ntp"]["enabled"] is False


def test_offline_a_sync_during_the_watch_keeps_ntp_on(device_client, login, timedatectl, systemctl):
    """Online but not yet synced: turning NTP back on reaches a time source, which moves the clock to the real time.
    That isn't a put-back, so NTP stays on."""
    timedatectl.props["NTPSynchronized"] = "no"
    timedatectl.online = True
    login(device_client, *ADMIN)
    r = change(device_client, {"time": (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()})
    assert r.status_code == 200, r.text
    changes = timedatectl.changes()
    assert len(changes) == 3 and changes[0] == ["set-ntp", "false"] and changes[1][0] == "set-time"
    assert changes[2] == ["set-ntp", "true"]
    body = r.json()
    assert body["ntp_left_off"] is False and body["ntp_took_over"] is True and body["time_kept_from_ntp"] is False
    assert body["ntp"]["enabled"] is True and body["ntp"]["synchronized"] is True
    assert [row for row in audit_rows(device_client) if row[0] == "time.set"] == [("time.set", "time")]


def test_online_a_sync_just_after_the_put_back_keeps_ntp_on(device_client, login, timedatectl, systemctl):
    """Online with a saved time ahead of the real one (seen on a Pi): timesyncd puts the saved time back and syncs to
    the real time a moment later, after the put-back has been seen. NTP has the time, so it stays on."""
    timedatectl.props["NTPSynchronized"] = "no"
    timedatectl.online = True
    timedatectl.sync_after_shows = 2  # the first read after the put-back still says unsynchronized
    sent = datetime.now(timezone.utc) - timedelta(minutes=2)
    timedatectl.saved = datetime.now(timezone.utc) + timedelta(minutes=3)
    login(device_client, *ADMIN)
    r = change(device_client, {"time": sent.isoformat()})
    assert r.status_code == 200, r.text
    changes = timedatectl.changes()
    assert len(changes) == 3 and changes[2] == ["set-ntp", "true"]
    assert abs(timedatectl.now() - datetime.now(timezone.utc)) < timedelta(seconds=5)
    body = r.json()
    assert body["ntp_left_off"] is False and body["ntp_took_over"] is True
    assert body["ntp"]["enabled"] is True and body["ntp"]["synchronized"] is True


def test_online_a_sync_that_doesnt_come_after_the_put_back_leaves_ntp_off(device_client, login, timedatectl,
                                                                            systemctl):
    """NTP on but no time source answers (such as blocked NTP traffic): the put-back is undone and NTP left off."""
    timedatectl.props["NTPSynchronized"] = "no"
    timedatectl.online = True
    timedatectl.sync_after_shows = 1000  # never, within the wait
    sent = datetime.now(timezone.utc).replace(microsecond=0)
    timedatectl.saved = sent + timedelta(minutes=5)
    login(device_client, *ADMIN)
    r = change(device_client, {"time": sent.isoformat()})
    assert r.status_code == 200, r.text
    assert [argv[0] for argv in timedatectl.changes()[3:]] == ["set-ntp", "set-time"]
    assert timedatectl.ran("show") > 3  # the state was read more than once before giving up
    body = r.json()
    assert body["ntp_left_off"] is True and body["ntp_took_over"] is False and body["ntp"]["enabled"] is False


def test_ntp_off_a_time_sent_with_ntp_on_that_is_put_back_is_set_again_with_ntp_left_off(
    device_client, login, timedatectl, systemctl
):
    """NTP off, and the time sent with ntp: true: turning NTP on after set-time can put timesyncd's saved time back
    just as the offline case does, so the same watch runs."""
    timedatectl.props |= {"NTP": "no", "NTPSynchronized": "no"}
    timedatectl.online = True
    timedatectl.sync_after_shows = 1000  # never, within the wait
    sent = datetime.now(timezone.utc).replace(microsecond=0)
    timedatectl.saved = sent + timedelta(minutes=5)
    login(device_client, *ADMIN)
    r = change(device_client, {"time": sent.isoformat(), "ntp": True})
    assert r.status_code == 200, r.text
    changes = timedatectl.changes()
    assert changes[:2] == [["set-time", f"{sent:%Y-%m-%d %H:%M:%S}"], ["set-ntp", "true"]]
    assert changes[2:3] == [["set-ntp", "false"]] and [argv[0] for argv in changes[3:]] == ["set-time"]
    assert abs(timedatectl.now() - datetime.now(timezone.utc)) < timedelta(seconds=5)
    body = r.json()
    assert body["ntp_left_off"] is True and body["ntp_took_over"] is False and body["ntp"]["enabled"] is False
    assert [row for row in audit_rows(device_client) if row[0] == "time.set"] == [("time.set", "ntp, time")]


def test_ntp_off_a_time_sent_with_ntp_on_and_a_sync_after_the_put_back_keeps_ntp_on(
    device_client, login, timedatectl, systemctl
):
    timedatectl.props |= {"NTP": "no", "NTPSynchronized": "no"}
    timedatectl.online = True
    timedatectl.sync_after_shows = 2
    sent = datetime.now(timezone.utc) - timedelta(minutes=2)
    timedatectl.saved = datetime.now(timezone.utc) + timedelta(minutes=3)
    login(device_client, *ADMIN)
    r = change(device_client, {"time": sent.isoformat(), "ntp": True})
    assert r.status_code == 200, r.text
    assert [argv[0] for argv in timedatectl.changes()] == ["set-time", "set-ntp"]
    body = r.json()
    assert body["ntp_left_off"] is False and body["ntp_took_over"] is True
    assert body["ntp"]["enabled"] is True and body["ntp"]["synchronized"] is True


def test_the_time_set_again_after_a_put_back_counts_the_time_turning_ntp_off_took(
    device_client, login, timedatectl, systemctl, monkeypatch
):
    """The second set-time is the browser's time plus the time since the first, including however long set-ntp false
    took to stop timesyncd (here 30 s on a monotonic clock that the fake moves forward)."""
    timedatectl.props["NTPSynchronized"] = "no"
    sent = datetime.now(timezone.utc).replace(microsecond=0)
    timedatectl.saved = sent + timedelta(minutes=5)
    skew = [0.0]
    monkeypatch.setattr(time_router, "time", SimpleNamespace(
        monotonic=lambda: time.monotonic() + skew[0], sleep=time.sleep, tzset=time.tzset))

    def run(argv, **kwargs):
        if list(argv[1:3]) == ["set-ntp", "false"] and timedatectl.ran("set-time"):
            skew[0] += 30
        return timedatectl(argv, **kwargs)

    monkeypatch.setattr(timedate, "run", run)
    login(device_client, *ADMIN)
    r = change(device_client, {"time": sent.isoformat()})
    assert r.status_code == 200, r.text
    assert r.json()["ntp_left_off"] is True
    (*_, again) = [datetime.fromisoformat(argv[1]) for argv in timedatectl.changes() if argv[0] == "set-time"]
    assert abs(again.replace(tzinfo=timezone.utc) - (sent + timedelta(seconds=30))) < timedelta(seconds=3)


def test_offline_a_time_that_stays_keeps_ntp_on(device_client, login, timedatectl, systemctl):
    timedatectl.props["NTPSynchronized"] = "no"
    timedatectl.saved = datetime.now(timezone.utc) - timedelta(hours=1)  # the device was off for a while
    login(device_client, *ADMIN)
    r = change(device_client, {"time": (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()})
    assert r.status_code == 200, r.text
    assert len(timedatectl.changes()) == 3
    assert r.json()["ntp_left_off"] is False and r.json()["ntp"]["enabled"] is True


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
        {"ntp": False, "timezone": "Mars/Olympus"},
        {"ntp": True, "timezone": "Mars/Olympus"},
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


@pytest.mark.parametrize("ntp", ["synchronized", "offline", "off"])
def test_a_time_with_an_unknown_timezone_sets_the_time_and_skips_the_zone(
    device_client, login, timedatectl, systemctl, tzset, ntp
):
    """A phone can report a zone the device's tzdata lacks; the time still goes on, by the usual NTP rules, and the
    zone is reported back as unknown rather than refusing the whole request."""
    timedatectl.props |= {
        "synchronized": {},
        "offline": {"NTPSynchronized": "no"},
        "off": {"NTP": "no", "NTPSynchronized": "no"},
    }[ntp]
    login(device_client, *ADMIN)
    r = change(device_client, {"time": "2026-10-28T21:41:35Z", "timezone": "Etc/Unknown"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["timezone_unknown"] is True
    assert body["timezone"] == "America/Los_Angeles" and body["restarting"] == []
    assert systemctl == [] and tzset == []
    assert timedatectl.ran("set-timezone") == 0
    expected = {
        "synchronized": [],
        "offline": [["set-ntp", "false"], ["set-time", "2026-10-28 21:41:35"], ["set-ntp", "true"]],
        "off": [["set-time", "2026-10-28 21:41:35"]],
    }[ntp]
    assert timedatectl.changes() == expected
    assert body["time_kept_from_ntp"] is (ntp == "synchronized")
    rows = [row for row in audit_rows(device_client) if row[0] == "time.set"]
    assert rows == [("time.set", None if ntp == "synchronized" else "time")]


def test_a_known_timezone_is_not_reported_unknown(device_client, login, timedatectl, systemctl, tzset):
    login(device_client, *ADMIN)
    r = change(device_client, {"time": "2026-10-28T21:41:35Z", "timezone": "America/Los_Angeles"})
    assert r.status_code == 200, r.text
    assert r.json()["timezone_unknown"] is False


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
    r = change(claimed_client, {"time": "2026-10-28T21:41:35Z", "timezone": "Mars/Olympus"})
    assert r.status_code == 200, r.text
    assert r.json()["timezone_unknown"] is True and r.json()["timezone"] == "Etc/UTC"
    assert r.json()["restarting"] == []
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
                                         "restarting", "timezone_unknown", "ntp_left_off", "ntp_took_over"}


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
