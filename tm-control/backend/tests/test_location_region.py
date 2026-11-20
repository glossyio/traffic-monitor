"""Where the Location page's map opens with no place to start from: the time zone's city (modules/location/region.py).

The table is hand-made, in zone1970.tab's format, so the tests don't depend on the machine's tzdata.
"""

import importlib
from types import SimpleNamespace

import pytest

from tm_control.adapters.timedate import Ntp, TimeState
from tm_control.modules.location.region import LatLon, parse_iso_6709, region

# The module, not the APIRouter the package's __init__ binds to the same name.
surveys_router = importlib.import_module("tm_control.modules.location.router")

TABLE = (
    "# tzdata zone table\n"
    "#\n"
    "GB,GG,IM,JE\t+513030-0000731\tEurope/London\n"
    "US\t+340308-1181434\tAmerica/Los_Angeles\tPacific\n"
    "AU\t-3352+15113\tAustralia/Sydney\tNew South Wales\n"
    "AR\t-3436-05827\tAmerica/Argentina/Buenos_Aires\tBuenos Aires\n"
)


# zone.tab, which lists each country's own zones, including the names zone1970.tab merged away
FULL_TABLE = (
    "# tzdata zone table, one country per row\n"
    "GB\t+513030-0000731\tEurope/London\n"
    "JE\t+491101-0020624\tEurope/Jersey\n"
    "NL\t+5222+00454\tEurope/Amsterdam\n"
    "US\t+340308-1181434\tAmerica/Los_Angeles\tPacific\n"
)


@pytest.fixture
def table(tmp_path):
    path = tmp_path / "zone1970.tab"
    path.write_text(TABLE, encoding="utf-8")
    return path


@pytest.fixture
def full_table(tmp_path):
    path = tmp_path / "zone.tab"
    path.write_text(FULL_TABLE, encoding="utf-8")
    return path


def test_both_forms_and_both_signs_parse():
    assert parse_iso_6709("+340308-1181434") == LatLon(lat=34.05, lon=-118.24)  # degrees, minutes, seconds
    assert parse_iso_6709("+513030-0000731") == LatLon(lat=51.51, lon=-0.13)
    assert parse_iso_6709("-3352+15113") == LatLon(lat=-33.87, lon=151.22)  # degrees and minutes
    assert parse_iso_6709("-3436-05827") == LatLon(lat=-34.6, lon=-58.45)


@pytest.mark.parametrize(
    "text",
    ["", "34.05,-118.24", "+3403-11814x", "+34-118", "+3460+01000", "+340368-1181434", "+9100+00000", "+0000+18100"],
)
def test_a_pair_that_is_not_iso_6709_is_none(text):
    assert parse_iso_6709(text) is None


def test_a_zone_in_its_countrys_gives_its_city(table):
    assert region("America/Los_Angeles", "US", table) == LatLon(lat=34.05, lon=-118.24)
    assert region("Europe/London", "GB", table) == LatLon(lat=51.51, lon=-0.13)
    assert region("Europe/London", "JE", table) == LatLon(lat=51.51, lon=-0.13)  # one of the row's countries
    assert region("America/Los_Angeles", "us", table) == LatLon(lat=34.05, lon=-118.24)


def test_a_zone_in_another_country_is_none(table):
    assert region("Europe/London", "US", table) is None


def test_a_zone_only_the_second_table_lists_gives_its_city(table, full_table):
    assert region("Europe/Amsterdam", "NL", table, full_table) == LatLon(lat=52.37, lon=4.9)


def test_that_zone_with_another_country_is_none(table, full_table):
    assert region("Europe/Amsterdam", "US", table, full_table) is None
    assert region("Europe/Amsterdam", "NO", table, full_table) is None


def test_a_zone_in_both_tables_is_answered_by_the_first(table, full_table):
    assert region("Europe/London", "JE", table, full_table) == LatLon(lat=51.51, lon=-0.13)  # the merged row's country
    assert region("Europe/London", "GB", table, full_table) == LatLon(lat=51.51, lon=-0.13)
    assert region("Europe/London", "GG", table, full_table) == LatLon(lat=51.51, lon=-0.13)
    assert region("Europe/London", "NL", table, full_table) is None


def test_a_missing_second_table_is_none_and_raises_nothing(table, tmp_path):
    assert region("Europe/Amsterdam", "NL", table, tmp_path / "absent.tab") is None
    assert region("America/Los_Angeles", "US", table, tmp_path / "absent.tab") == LatLon(lat=34.05, lon=-118.24)


def test_an_unreadable_second_table_is_none_and_raises_nothing(table, tmp_path):
    path = tmp_path / "zone.tab"
    path.write_bytes(b"\xff\xfe\x00NL\t+5222+00454\tEurope/Amsterdam\n")
    assert region("Europe/Amsterdam", "NL", table, path) is None


def test_the_second_table_is_the_first_ones_neighbour_unless_given(table, full_table):
    assert region("Europe/Amsterdam", "NL", table) == LatLon(lat=52.37, lon=4.9)  # zone.tab beside zone1970.tab


@pytest.mark.parametrize("country", ["", None])
def test_no_country_is_none(table, country):
    assert region("America/Los_Angeles", country, table) is None


@pytest.mark.parametrize("zone", ["", None, "Etc/UTC", "Mars/Olympus"])
def test_no_zone_or_one_not_in_the_table_is_none(table, zone):
    assert region(zone, "US", table) is None


def test_a_missing_file_is_none(tmp_path):
    assert region("America/Los_Angeles", "US", tmp_path / "absent.tab") is None


def test_a_file_that_is_not_text_is_none(tmp_path):
    path = tmp_path / "zone1970.tab"
    path.write_bytes(b"\xff\xfe\x00US\t+340308-1181434\tAmerica/Los_Angeles\n")
    assert region("America/Los_Angeles", "US", path) is None


def test_a_malformed_row_is_none_and_does_not_stop_the_others(tmp_path):
    path = tmp_path / "zone1970.tab"
    path.write_text(
        "garbage\nUS\tnot-a-pair\tAmerica/Chicago\nUS\t+340308-1181434\tAmerica/Los_Angeles\n", encoding="utf-8"
    )
    assert region("America/Chicago", "US", path) is None
    assert region("America/Los_Angeles", "US", path) == LatLon(lat=34.05, lon=-118.24)


def test_on_a_device_the_zone_is_timedatectls_and_the_country_is_iws(table, full_table, monkeypatch):
    monkeypatch.setattr("tm_control.modules.location.region.ZONE_TAB", table)
    monkeypatch.setattr("tm_control.modules.location.region.ZONE_TAB_ALL", table.with_name("zone.tab"))
    app_state = SimpleNamespace(settings=SimpleNamespace(fake=False))
    ntp = Ntp(enabled=True, synchronized=True, available=True)
    state = TimeState(device_time="2026-11-20T12:00:00-08:00", timezone="America/Los_Angeles", ntp=ntp, rtc_time=None)
    monkeypatch.setattr(surveys_router.timedate, "show", lambda: state)
    monkeypatch.setattr(surveys_router.network, "wifi_country", lambda: "US")
    assert surveys_router._region(app_state) == LatLon(lat=34.05, lon=-118.24)
    state.timezone = "Europe/Amsterdam"  # only the second table lists it
    monkeypatch.setattr(surveys_router.network, "wifi_country", lambda: "NL")
    assert surveys_router._region(app_state) == LatLon(lat=52.37, lon=4.9)
    state.timezone = "America/Los_Angeles"
    monkeypatch.setattr(surveys_router.network, "wifi_country", lambda: None)  # iw can't be read
    assert surveys_router._region(app_state) is None
    monkeypatch.setattr(surveys_router.network, "wifi_country", lambda: "US")
    monkeypatch.setattr(surveys_router.timedate, "show", lambda: None)  # timedatectl can't be read
    assert surveys_router._region(app_state) is None
