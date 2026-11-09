import logging
import shutil
import sqlite3
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from tm_control.adapters.nodered import NodeRedError
from tm_control.adapters.yamlfile import read_config
from tm_control.core.auth import Users
from tm_control.core.manifest import load_manifest
from tm_control.core.state import State
from tm_control.modules.location import reconcile
from tm_control.modules.location.places import Bearing, Places

FIXTURES = Path(__file__).parent / "fixtures"
FIXTURE_POINT = "lat: 45.0\n    lon: -122.0\n"
SENSORS = [Bearing(sensor_type="cameras", sensor_name="picam_h265", bearing="n"),
           Bearing(sensor_type="radars", sensor_name="TM_RADAR_SERIAL_PORT_00", bearing="n")]
FIRST, SECOND = "0000000a-si", "0000000b-si"
# 2023-11-14T22:13:20Z and a day later, in ms, as Node-RED's usage answers them
FIRST_START, FIRST_END, SECOND_START = 1_700_000_000_000, 1_700_086_400_000, 1_700_172_800_000


class StubNodeRed:
    """Node-RED's /tm-internal/ answers, by hand. Set `down` to make every call raise NodeRedError("unreachable")."""

    def __init__(self, schema_version=2):
        self.down = False
        self.schema_version = schema_version
        self.surveys = []  # what usage() answers
        self.rows = {}  # survey id -> what deployments(id) answers
        self.calls = []
        self.corrections = []
        self.correction_error = None

    def _call(self, name, *args):
        self.calls.append((name, *args))
        if self.down:
            raise NodeRedError("unreachable")

    def report(self):
        self._call("report")
        return {"schema_version": self.schema_version, "deployment": {"survey_id": None, "database_precision": "1"}}

    def usage(self):
        self._call("usage")
        return self.surveys

    def deployments(self, survey_id):
        self._call("deployments", survey_id)
        return self.rows.get(survey_id, [])

    def correct_location(self, survey_id, lat, lon):
        self._call("correct_location", survey_id, lat, lon)
        if self.correction_error is not None:
            raise self.correction_error
        self.corrections.append((survey_id, lat, lon))

    def named(self, name):
        return [call for call in self.calls if call[0] == name]


@pytest.fixture
def unit(tmp_path):
    """An app state as ensure() reads it: a migrated state.sqlite, the fixture manifest with its codedir in tmp_path,
    Node-RED's config.yml (the fixture's) in that codedir, and a stub Node-RED that answers schema version 2."""
    (tmp_path / "state").mkdir()
    state = State(tmp_path / "state" / "state.sqlite")
    state.migrate()
    codedir = tmp_path / "codedir"
    config = codedir / "node-red-tm" / "config" / "config.yml"
    config.parent.mkdir(parents=True)
    shutil.copy(FIXTURES / "node_red_config_ok.yml", config)
    manifest = load_manifest(FIXTURES / "manifest.json").model_copy(update={"codedir": str(codedir)})
    return SimpleNamespace(
        state=state, manifest=manifest, nodered=StubNodeRed(), config_path=config, reconcile_lock=threading.Lock(),
        admin=Users(state).create("admin", "correct horse 1", "admin").id,
    )


def edit(unit, old, new):
    text = unit.config_path.read_text()
    assert old in text
    unit.config_path.write_text(text.replace(old, new, 1))


def file_deployment(unit):
    return read_config(unit.config_path).data["deployment"]


def sensor_bearing(unit, sensor_type, name):
    """The bearing in the sensor's own deployment block, or None when it has none."""
    sensor = read_config(unit.config_path).data["sensors"][sensor_type][name]
    return (sensor.get("deployment") or {}).get("bearing")


RADAR = "        TM_RADAR_SERIAL_PORT_00:\n            enabled: true\n"


def write_backup(unit, rows, schema=None, name="tmdb-v0-20261101T000000Z.sqlite"):
    """A pre-migration tmdb copy with a deployment table in the baseline shape (or `schema`) holding `rows`."""
    directory = reconcile.backup_dir(unit.manifest)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    con = sqlite3.connect(path)
    con.execute(schema or "CREATE TABLE deployment (id TEXT PRIMARY KEY, entryStartDateTime REAL, "
                          "entryEndDateTime REAL, lat REAL, lon REAL, bearing TEXT, sensorType TEXT, "
                          "sensorName TEXT, deviceName TEXT)")
    con.executemany("INSERT INTO deployment (id, lat, lon) VALUES (?, ?, ?)", rows)
    con.commit()
    con.close()
    return path


INVALID_POINTS = ["lat: 45,0\n    lon: -122.0\n", "lat: 45.0\n    lon:\n"]  # a decimal comma; one of the two
BACKUP_ROWS = [("A", 45.52252, -122.6912), ("B", 45.52252, -122.6912), ("C", 45.0, -122.0), ("D", 45.0, -122.0)]


def answer_usage(nodered):
    """Two surveys: FIRST holds rows A and B (closed), SECOND rows C and D (still open); and the rows with none."""
    nodered.surveys = [
        {"survey_id": FIRST, "first_start": FIRST_START, "last_end": FIRST_END, "open_count": 0,
         "deployment_count": 2},
        {"survey_id": SECOND, "first_start": SECOND_START, "last_end": None, "open_count": 2, "deployment_count": 2},
        {"survey_id": None, "first_start": FIRST_START, "last_end": FIRST_END, "open_count": 0,
         "deployment_count": 3},
    ]
    nodered.rows = {FIRST: [{"id": "A"}, {"id": "B"}], SECOND: [{"id": "C"}, {"id": "D"}]}


def corrections(unit):
    con = unit.state.connect()
    try:
        return [tuple(row) for row in con.execute(
            "SELECT survey_id, field, old_value, new_value, reason, source, user_id FROM survey_corrections ORDER BY id"
        )]
    finally:
        con.close()


def test_first_run_creates_the_default_place_and_writes_its_id(unit):
    edit(unit, FIXTURE_POINT, "lat:\n    lon:\n")
    before = unit.config_path.read_text()
    outcome = reconcile.ensure(unit, user_id=unit.admin)
    assert outcome == reconcile.Outcome(state="done", imported=0, created_default=True, followed="none")
    places = Places(unit.state)
    (place,) = places.list()
    assert (place.status, place.description, place.source) == ("in_use", "First location", "default")
    assert (place.lat, place.lon) == (None, None)
    assert place.bearings == SENSORS
    deployment = file_deployment(unit)
    assert deployment["survey_id"] == place.id
    assert deployment["database_precision"] == "2"
    assert (deployment["lat"], deployment["lon"]) == (None, None)
    assert unit.config_path.read_text() == before.replace(
        "    bearing: 'n'\n", f"    bearing: 'n'\n    survey_id: {place.id}\n    database_precision: '2'\n", 1
    )
    assert places.reconciled_at() is not None
    assert unit.nodered.calls == []
    con = unit.state.connect()
    assert con.execute("SELECT created_by FROM surveys").fetchone()[0] == unit.admin
    con.close()


def test_first_run_keeps_a_precision_already_in_the_file(unit):
    edit(unit, FIXTURE_POINT, "lat:\n    lon:\n    database_precision: '2'\n")
    reconcile.ensure(unit)
    assert file_deployment(unit)["database_precision"] == "2"


def test_an_unreadable_file_stops_there(unit):
    unit.config_path.unlink()
    outcome = reconcile.ensure(unit)
    assert outcome.state == "config_unreadable"
    assert Places(unit.state).list() == [] and Places(unit.state).reconciled_at() is None
    assert unit.nodered.calls == []


def test_waits_for_nodered_when_the_file_has_coordinates(unit):
    places = Places(unit.state)
    unit.nodered.down = True
    assert reconcile.ensure(unit).state == "waiting_nodered"
    assert places.list() == [] and places.reconciled_at() is None

    unit.nodered.down = False
    unit.nodered.schema_version = 1  # Node-RED answers, but tmdb isn't migrated yet
    assert reconcile.ensure(unit).state == "waiting_nodered"
    assert places.list() == [] and places.reconciled_at() is None

    unit.nodered.schema_version = 2
    outcome = reconcile.ensure(unit)
    assert outcome == reconcile.Outcome(state="done", imported=0, created_default=False, followed="none")
    (place,) = places.list()
    assert (place.status, place.source, place.lat, place.lon) == ("in_use", "imported_config", 45.0, -122.0)
    assert place.bearings == SENSORS
    assert file_deployment(unit)["survey_id"] == place.id
    assert (file_deployment(unit)["lat"], file_deployment(unit)["lon"]) == (45.0, -122.0)
    assert places.reconciled_at() is not None
    assert unit.nodered.named("usage") == []  # no backup, so nothing to ask about


def test_import_from_the_backup_groups_places_by_survey_id(unit):
    write_backup(unit, BACKUP_ROWS)
    answer_usage(unit.nodered)
    edit(unit, FIXTURE_POINT, "lat: 45.522520\n    lon: -122.69120\n")  # the same point at five places
    before = unit.config_path.read_text()
    outcome = reconcile.ensure(unit, user_id=unit.admin)
    assert outcome == reconcile.Outcome(state="done", imported=2, created_default=False, followed="none")
    assert unit.config_path.read_text() == before.replace(
        "    bearing: 'n'\n", f"    bearing: 'n'\n    survey_id: {FIRST}\n", 1
    )
    places = Places(unit.state)
    first, second = places.get(FIRST), places.get(SECOND)
    assert len(places.list()) == 2
    assert (first.status, first.source, first.lat, first.lon) == ("in_use", "imported_backup", 45.52252, -122.6912)
    assert (second.status, second.source, second.lat, second.lon) == ("used", "imported_backup", 45.0, -122.0)
    assert (first.description, second.description, second.bearings) == (None, None, [])
    assert first.created_at == "2023-11-14T22:13:20+00:00"
    assert (second.created_at, second.updated_at) == ("2023-11-16T22:13:20+00:00", "2023-11-16T22:13:20+00:00")
    assert file_deployment(unit)["survey_id"] == FIRST
    assert unit.nodered.named("deployments") == [("deployments", FIRST), ("deployments", SECOND)]
    assert corrections(unit) == [] and unit.nodered.corrections == []


def test_an_upgraded_unit_with_no_location_still_imports(unit):
    """A backup means the unit was upgraded, so a file with no location and no survey_id takes the import path, not
    the fresh unit's default place: it waits for Node-RED, imports the past places, and puts a new one in use."""
    write_backup(unit, BACKUP_ROWS)
    answer_usage(unit.nodered)
    edit(unit, FIXTURE_POINT, "lat:\n    lon:\n")
    unit.nodered.down = True
    assert reconcile.ensure(unit).state == "waiting_nodered"
    assert Places(unit.state).list() == []
    unit.nodered.down = False
    outcome = reconcile.ensure(unit, user_id=unit.admin)
    assert outcome == reconcile.Outcome(state="done", imported=2, created_default=False, followed="none")
    places = Places(unit.state)
    current = places.in_use()
    assert (current.source, current.description, current.lat, current.lon) == ("imported_config", None, None, None)
    assert current.id not in (FIRST, SECOND) and current.bearings == SENSORS
    assert {places.get(FIRST).status, places.get(SECOND).status} == {"used"}
    assert [place.status for place in places.list()].count("in_use") == 1
    deployment = file_deployment(unit)
    assert (deployment["survey_id"], deployment["lat"], deployment["lon"]) == (current.id, None, None)
    assert corrections(unit) == [] and unit.nodered.named("correct_location") == []


def test_no_matching_point_creates_the_place_from_the_file(unit):
    write_backup(unit, BACKUP_ROWS)
    answer_usage(unit.nodered)
    edit(unit, FIXTURE_POINT, "lat: 45.5\n    lon: -122.7\n")
    outcome = reconcile.ensure(unit)
    assert (outcome.state, outcome.imported) == ("done", 2)
    places = Places(unit.state)
    assert len(places.list()) == 3
    current = places.in_use()
    assert (current.source, current.lat, current.lon) == ("imported_config", 45.5, -122.7)
    assert current.id not in (FIRST, SECOND)
    assert current.bearings == SENSORS
    assert file_deployment(unit)["survey_id"] == current.id
    assert {places.get(FIRST).status, places.get(SECOND).status} == {"used"}


def test_the_file_naming_an_imported_survey_puts_that_one_in_use(unit):
    write_backup(unit, BACKUP_ROWS)
    answer_usage(unit.nodered)
    edit(unit, "bearing: 'n'\n", f"bearing: 'n'\n    survey_id: {SECOND}\n")  # the file stays at 45.0, -122.0
    reconcile.ensure(unit)
    places = Places(unit.state)
    assert places.in_use().id == SECOND and places.get(FIRST).status == "used"
    assert len(places.list()) == 2 and corrections(unit) == []


@pytest.mark.parametrize(
    "content, error",
    [
        (b"not a database", "DatabaseError"),
        # a deployment table without lat and lon (not a shape a release wrote, but the import must not fail on it)
        ("CREATE TABLE deployment (id TEXT PRIMARY KEY, entryDateTime REAL, orientation TEXT, address TEXT)",
         "OperationalError"),
        ("CREATE TABLE other (id TEXT)", "OperationalError"),  # no deployment table at all
    ],
)
def test_unreadable_backup_is_skipped(unit, caplog, content, error):
    if isinstance(content, bytes):
        directory = reconcile.backup_dir(unit.manifest)
        directory.mkdir(parents=True)
        (directory / "tmdb-v0-20261101T000000Z.sqlite").write_bytes(content)
    else:
        path = reconcile.backup_dir(unit.manifest) / "tmdb-v0-20261101T000000Z.sqlite"
        path.parent.mkdir(parents=True)
        con = sqlite3.connect(path)
        con.execute(content)
        con.commit()
        con.close()
    answer_usage(unit.nodered)
    with caplog.at_level(logging.INFO, logger=reconcile.__name__):
        outcome = reconcile.ensure(unit)
    assert (outcome.state, outcome.imported) == ("done", 0)
    warnings = [r for r in caplog.records if r.name == reconcile.__name__ and r.levelno >= logging.WARNING]
    assert [r.getMessage() for r in warnings] == [f"skipping the tmdb backup: {error}"]
    assert not any("codedir" in m or "45" in m for m in (r.getMessage() for r in caplog.records))
    places = Places(unit.state)
    (place,) = places.list()
    assert (place.status, place.source, place.lat, place.lon) == ("in_use", "imported_config", 45.0, -122.0)
    assert places.reconciled_at() is not None
    assert unit.nodered.named("usage") == []


def test_a_backup_directory_that_cant_be_listed_is_skipped(unit, caplog, monkeypatch):
    def refused(self, pattern):
        raise PermissionError(13, "synthetic")

    monkeypatch.setattr(Path, "glob", refused)
    with caplog.at_level(logging.WARNING, logger=reconcile.__name__):
        outcome = reconcile.ensure(unit)
    assert (outcome.state, outcome.imported) == ("done", 0)
    assert [r.getMessage() for r in caplog.records] == ["skipping the tmdb backup: PermissionError"]
    assert Places(unit.state).in_use().source == "imported_config"


def test_the_oldest_deployment_shape_imports(unit):
    """The shape on the oldest devices (entryDateTime, orientation, address, description) has lat and lon."""
    write_backup(unit, BACKUP_ROWS[2:], schema="CREATE TABLE deployment (id TEXT PRIMARY KEY, entryDateTime REAL, "
                                               "lat REAL, lon REAL, orientation TEXT, address TEXT, description TEXT)")
    answer_usage(unit.nodered)
    outcome = reconcile.ensure(unit)  # the fixture's file is at 45.0, -122.0, as rows C and D are
    assert (outcome.state, outcome.imported) == ("done", 1)
    assert Places(unit.state).in_use().id == SECOND


def test_the_newest_backup_is_read(unit):
    write_backup(unit, BACKUP_ROWS[:2], name="tmdb-v1-20261001T000000Z.sqlite")
    write_backup(unit, BACKUP_ROWS[2:], name="tmdb-v0-20261101T000000Z.sqlite")
    answer_usage(unit.nodered)
    assert reconcile.ensure(unit).imported == 1
    assert Places(unit.state).get(SECOND) is not None and Places(unit.state).get(FIRST) is None


def test_backup_rows_outside_any_survey_are_left_out(unit):
    write_backup(unit, BACKUP_ROWS + [("E", 45.5, -122.7)])
    answer_usage(unit.nodered)
    edit(unit, FIXTURE_POINT, "lat: 45.52252\n    lon: -122.6912\n")
    assert reconcile.ensure(unit).imported == 2
    assert len(Places(unit.state).list()) == 2


def test_nodered_failing_during_the_import_imports_nothing(unit):
    write_backup(unit, BACKUP_ROWS)
    answer_usage(unit.nodered)
    unit.nodered.rows = None  # deployments() fails below
    unit.nodered.deployments = lambda survey_id: (_ for _ in ()).throw(NodeRedError("unreachable"))
    assert reconcile.ensure(unit).state == "waiting_nodered"
    assert Places(unit.state).list() == [] and Places(unit.state).reconciled_at() is None


def test_import_runs_once(unit):
    write_backup(unit, BACKUP_ROWS)
    answer_usage(unit.nodered)
    edit(unit, FIXTURE_POINT, "lat: 45.52252\n    lon: -122.6912\n")
    reconcile.ensure(unit)
    before = Places(unit.state).list()
    unit.nodered.calls.clear()
    outcome = reconcile.ensure(unit)
    assert outcome == reconcile.Outcome(state="done", imported=0, created_default=False, followed="none")
    assert Places(unit.state).list() == before
    assert unit.nodered.calls == []  # a reconciled unit only follows the file, which needs no Node-RED here


def test_following_an_unknown_survey_id_in_the_file(unit):
    edit(unit, FIXTURE_POINT, "lat:\n    lon:\n")
    reconcile.ensure(unit)
    places = Places(unit.state)
    previous = places.in_use()
    edit(unit, f"survey_id: {previous.id}", "survey_id: 3f9a1c2e-si")
    outcome = reconcile.ensure(unit, user_id=unit.admin)
    assert outcome == reconcile.Outcome(state="done", imported=0, created_default=False, followed="unknown_id")
    current = places.in_use()
    assert (current.id, current.source, current.lat, current.lon) == ("3f9a1c2e-si", "imported_config", None, None)
    assert current.bearings == SENSORS
    assert places.get(previous.id).status == "used"
    assert reconcile.ensure(unit).followed == "none"


def test_following_a_known_survey_id_switches_the_place_in_use(unit):
    """A hand edit of survey_id alone is a deploy by hand: the file takes that place's point, and neither place's
    point changes."""
    reconcile.ensure(unit)  # the first place, from the file, at 45.0, -122.0
    places = Places(unit.state)
    first = places.in_use().id
    edit(unit, f"survey_id: {first}", "survey_id: 3f9a1c2e-si")
    edit(unit, FIXTURE_POINT, "lat: 45.52252\n    lon: -122.6912\n")
    assert reconcile.ensure(unit).followed == "unknown_id"  # the second, at the file's point
    unit.nodered.calls.clear()

    edit(unit, "survey_id: 3f9a1c2e-si", f"survey_id: {first.upper()}")  # the id only; case is folded, as Node-RED does
    outcome = reconcile.ensure(unit)
    assert (outcome.state, outcome.followed) == ("done", "none")
    assert (places.in_use().id, places.get("3f9a1c2e-si").status) == (first, "used")
    assert (places.get(first).lat, places.get(first).lon) == (45.0, -122.0)
    assert (places.get("3f9a1c2e-si").lat, places.get("3f9a1c2e-si").lon) == (45.52252, -122.6912)
    assert (file_deployment(unit)["lat"], file_deployment(unit)["lon"]) == (45.0, -122.0)
    # Node-RED started the new deployments from the hand edit, at the file's old point: they take the place's
    assert unit.nodered.named("correct_location") == [("correct_location", first, 45.0, -122.0)]
    assert corrections(unit) == []
    assert len(places.list()) == 2
    assert reconcile.ensure(unit).followed == "none" and corrections(unit) == []


def test_a_failed_re_rounding_after_a_switch_by_hand_is_logged_and_ignored(unit, caplog):
    reconcile.ensure(unit)  # the first place, at 45.0, -122.0
    places = Places(unit.state)
    first = places.in_use().id
    edit(unit, f"survey_id: {first}", "survey_id: 3f9a1c2e-si")
    edit(unit, FIXTURE_POINT, "lat: 45.52252\n    lon: -122.6912\n")
    reconcile.ensure(unit)
    unit.nodered.correction_error = NodeRedError("unreachable")
    edit(unit, "survey_id: 3f9a1c2e-si", f"survey_id: {first}")
    with caplog.at_level(logging.INFO, logger=reconcile.__name__):
        outcome = reconcile.ensure(unit)
    assert (outcome.state, outcome.followed) == ("done", "none")
    assert places.in_use().id == first
    assert (file_deployment(unit)["lat"], file_deployment(unit)["lon"]) == (45.0, -122.0)
    assert unit.nodered.named("correct_location") == [("correct_location", first, 45.0, -122.0)]
    messages = [r.getMessage() for r in caplog.records]
    assert messages == ["re-rounding the place's rows in Node-RED failed: NodeRedError"]


def test_switching_by_hand_to_a_place_with_no_point_blanks_the_files_coordinates(unit):
    edit(unit, FIXTURE_POINT, "lat:\n    lon:\n")
    reconcile.ensure(unit)  # the default place, with no point
    places = Places(unit.state)
    first = places.in_use().id
    edit(unit, f"survey_id: {first}", "survey_id: 3f9a1c2e-si")
    edit(unit, "lat:\n    lon:\n", "lat: 45.52252\n    lon: -122.6912\n")
    reconcile.ensure(unit)
    edit(unit, "survey_id: 3f9a1c2e-si", f"survey_id: {first}")
    reconcile.ensure(unit)
    assert places.in_use().id == first
    assert (file_deployment(unit)["lat"], file_deployment(unit)["lon"]) == (None, None)
    assert (places.get("3f9a1c2e-si").lat, places.get("3f9a1c2e-si").lon) == (45.52252, -122.6912)
    assert corrections(unit) == [] and unit.nodered.named("correct_location") == []


def test_following_changed_coordinates_records_a_config_correction(unit):
    reconcile.ensure(unit)  # the in-use place is created from the file, at 45.0, -122.0
    places = Places(unit.state)
    place = places.in_use()
    edit(unit, FIXTURE_POINT, "lat: 45.52252\n    lon: -122.6912\n")
    outcome = reconcile.ensure(unit)
    assert outcome == reconcile.Outcome(state="done", imported=0, created_default=False, followed="coordinates")
    assert (places.in_use().lat, places.in_use().lon) == (45.52252, -122.6912)
    assert corrections(unit) == [(place.id, "location", "45.0,-122.0", "45.52252,-122.6912", None, "config", None)]
    assert unit.nodered.corrections == [(place.id, 45.52252, -122.6912)]
    assert reconcile.ensure(unit).followed == "none"  # equal now
    assert len(corrections(unit)) == 1


def test_coordinates_compare_at_five_places(unit):
    reconcile.ensure(unit)
    edit(unit, FIXTURE_POINT, "lat: '45.00'\n    lon: -122.00000\n")  # written differently, the same point
    assert reconcile.ensure(unit).followed == "none"
    assert corrections(unit) == []


def test_coordinates_blanked_by_hand_are_put_back(unit):
    """A place with a point can't be corrected to no location (decision 9): the file gets the point back, so it and
    the engine agree with the store again."""
    reconcile.ensure(unit)
    place = Places(unit.state).in_use()
    unit.nodered.calls.clear()
    edit(unit, FIXTURE_POINT, "lat:\n    lon:\n")
    outcome = reconcile.ensure(unit)
    assert (outcome.state, outcome.followed) == ("done", "restored")
    assert (Places(unit.state).in_use().lat, Places(unit.state).in_use().lon) == (45.0, -122.0)
    deployment = file_deployment(unit)
    assert (deployment["survey_id"], deployment["lat"], deployment["lon"]) == (place.id, 45.0, -122.0)
    assert corrections(unit) == [] and unit.nodered.named("correct_location") == []
    assert reconcile.ensure(unit).followed == "none"


def test_a_file_reset_from_the_template_gets_the_place_in_use_back(unit):
    """After tmsetup.sh -f the file has the template's blank survey_id, location, and bearing: the place in use goes
    back in with its stored point, and each sensor with a blank bearing gets the place's back under its own block, so
    the engine starts no deployment with no bearing. The top-level bearing stays as the file has it, and so does a
    precision when none was ever seen with a survey named (this file had none)."""
    reconcile.ensure(unit)  # the place in use, at 45.0, -122.0
    place = Places(unit.state).in_use()
    unit.nodered.calls.clear()
    edit(unit, f"{FIXTURE_POINT}    bearing: 'n'\n    survey_id: {place.id}\n",
         "lat:\n    lon:\n    bearing: ''\n    survey_id:  # names the place\n    database_precision: '1'\n")
    outcome = reconcile.ensure(unit)
    assert (outcome.state, outcome.followed) == ("done", "restored")
    deployment = file_deployment(unit)
    assert (deployment["survey_id"], deployment["lat"], deployment["lon"]) == (place.id, 45.0, -122.0)
    assert (deployment["bearing"], deployment["database_precision"]) == ("", "1")
    assert sensor_bearing(unit, "cameras", "picam_h265") == "n"
    assert sensor_bearing(unit, "radars", "TM_RADAR_SERIAL_PORT_00") == "n"
    assert "# names the place" in unit.config_path.read_text()
    current = Places(unit.state).in_use()
    assert (current.id, current.lat, current.lon) == (place.id, 45.0, -122.0)
    assert corrections(unit) == [] and unit.nodered.calls == []
    assert len(Places(unit.state).list()) == 1
    assert reconcile.ensure(unit).followed == "none"


def named_with_precision(unit, precision):
    """The first run done, then the file names the place in use and holds this precision. Returns the line to reset."""
    reconcile.ensure(unit)
    place = Places(unit.state).in_use()
    edit(unit, f"survey_id: {place.id}\n", f"survey_id: {place.id}\n    database_precision: '{precision}'\n")
    return f"survey_id: {place.id}\n    database_precision: '{precision}'\n"


@pytest.mark.parametrize("chosen", ["none", "1", "2"])
def test_a_reset_file_gets_back_the_precision_seen_with_the_survey(unit, chosen):
    """tmsetup.sh -f renders the template's '2': an operator who chose less must not store more from then on."""
    named = named_with_precision(unit, chosen)
    assert reconcile.ensure(unit).followed == "none"  # seen with the survey named
    edit(unit, named, "survey_id:\n    database_precision: '2'\n")
    assert reconcile.ensure(unit).followed == "restored"
    assert file_deployment(unit)["database_precision"] == chosen
    assert reconcile.ensure(unit).followed == "none"


def test_a_reset_file_gets_the_precision_back_when_it_also_gets_the_point_back(unit):
    named = named_with_precision(unit, "none")
    reconcile.ensure(unit)
    edit(unit, f"{FIXTURE_POINT}    bearing: 'n'\n    {named}", "lat:\n    lon:\n    bearing: 'n'\n    survey_id:\n"
         "    database_precision: '2'\n")
    assert reconcile.ensure(unit).followed == "restored"
    deployment = file_deployment(unit)
    assert (deployment["lat"], deployment["lon"], deployment["database_precision"]) == (45.0, -122.0, "none")


def test_a_reset_file_with_a_typo_in_its_coordinates_still_gets_the_precision_back(unit):
    named = named_with_precision(unit, "1")
    reconcile.ensure(unit)
    edit(unit, f"{FIXTURE_POINT}    bearing: 'n'\n    {named}", "lat: nope\n    lon: -122.0\n    bearing: 'n'\n"
         "    survey_id:\n    database_precision: '2'\n")
    assert reconcile.ensure(unit).followed == "restored"
    assert file_deployment(unit)["database_precision"] == "1"


def test_a_hand_edit_of_the_precision_is_the_one_a_reset_gives_back(unit):
    named = named_with_precision(unit, "1")
    reconcile.ensure(unit)
    place = Places(unit.state).in_use()
    edit(unit, named, f"survey_id: {place.id}\n    database_precision: 'none'\n")
    reconcile.ensure(unit)
    edit(unit, f"survey_id: {place.id}\n    database_precision: 'none'\n", "survey_id:\n    database_precision: '2'\n")
    reconcile.ensure(unit)
    assert file_deployment(unit)["database_precision"] == "none"


@pytest.mark.parametrize("bad", ["'NONE'", "'3'"])
def test_a_precision_node_red_refuses_is_not_the_one_a_reset_gives_back(unit, bad):
    named = named_with_precision(unit, "1")
    reconcile.ensure(unit)
    place = Places(unit.state).in_use()
    edit(unit, named, f"survey_id: {place.id}\n    database_precision: {bad}\n")
    reconcile.ensure(unit)
    edit(unit, f"survey_id: {place.id}\n    database_precision: {bad}\n", "survey_id:\n    database_precision: '2'\n")
    reconcile.ensure(unit)
    assert file_deployment(unit)["database_precision"] == "1"


def test_a_reset_file_leaves_a_bearing_the_operator_set(unit):
    reconcile.ensure(unit)  # the place in use, its sensors facing n
    place = Places(unit.state).in_use()
    edit(unit, f"bearing: 'n'\n    survey_id: {place.id}\n", "bearing: ''\n    survey_id:\n")
    edit(unit, RADAR, RADAR + "            deployment:\n                bearing: 'e'\n")
    assert reconcile.ensure(unit).followed == "restored"
    assert sensor_bearing(unit, "cameras", "picam_h265") == "n"
    assert sensor_bearing(unit, "radars", "TM_RADAR_SERIAL_PORT_00") == "e"
    assert file_deployment(unit)["survey_id"] == place.id
    assert Places(unit.state).in_use().bearings == SENSORS  # the store keeps the place's own


@pytest.mark.parametrize("block", INVALID_POINTS)
def test_a_reset_file_keeps_coordinates_that_arent_a_point_as_typed(unit, block):
    reconcile.ensure(unit)  # the place in use, at 45.0, -122.0
    place = Places(unit.state).in_use()
    edit(unit, f"survey_id: {place.id}", "survey_id:")
    edit(unit, FIXTURE_POINT, block)
    assert reconcile.ensure(unit).followed == "restored"
    assert file_deployment(unit)["survey_id"] == place.id
    assert block in unit.config_path.read_text()  # as typed, for the Status check to name
    assert (Places(unit.state).in_use().lat, Places(unit.state).in_use().lon) == (45.0, -122.0)
    assert corrections(unit) == [] and unit.nodered.named("correct_location") == []


def test_a_reset_file_with_another_point_gets_the_places_point_back(unit):
    """tmsetup.sh -f renders the installer's lat and lon, which say nothing about where the place is: the store wins,
    with no correction (the Location page is where a place is corrected)."""
    reconcile.ensure(unit)  # the place in use, at 45.0, -122.0
    place = Places(unit.state).in_use()
    unit.nodered.calls.clear()
    edit(unit, f"survey_id: {place.id}", "survey_id:")
    edit(unit, FIXTURE_POINT, "lat: 45.52252\n    lon: -122.6912\n")
    assert reconcile.ensure(unit).followed == "restored"
    deployment = file_deployment(unit)
    assert (deployment["survey_id"], deployment["lat"], deployment["lon"]) == (place.id, 45.0, -122.0)
    assert (Places(unit.state).in_use().lat, Places(unit.state).in_use().lon) == (45.0, -122.0)
    assert corrections(unit) == [] and unit.nodered.calls == []
    assert reconcile.ensure(unit).followed == "none"


def test_a_reset_file_gives_a_place_with_no_point_the_files_point(unit):
    edit(unit, FIXTURE_POINT, "lat:\n    lon:\n")
    reconcile.ensure(unit)  # the default place, with no point
    place = Places(unit.state).in_use()
    edit(unit, f"survey_id: {place.id}", "survey_id:")
    edit(unit, "lat:\n    lon:\n", "lat: 45.52252\n    lon: -122.6912\n")
    assert reconcile.ensure(unit).followed == "coordinates"
    deployment = file_deployment(unit)
    assert (deployment["survey_id"], deployment["lat"], deployment["lon"]) == (place.id, 45.52252, -122.6912)
    assert (Places(unit.state).in_use().lat, Places(unit.state).in_use().lon) == (45.52252, -122.6912)
    assert corrections(unit) == [(place.id, "location", None, "45.52252,-122.6912", None, "config", None)]


def test_a_reset_file_gets_back_a_place_with_no_point_as_it_is(unit):
    edit(unit, FIXTURE_POINT, "lat:\n    lon:\n")
    reconcile.ensure(unit)  # the default place, with no point
    place = Places(unit.state).in_use()
    edit(unit, f"survey_id: {place.id}", "survey_id:")
    assert reconcile.ensure(unit).followed == "restored"
    deployment = file_deployment(unit)
    assert (deployment["survey_id"], deployment["lat"], deployment["lon"]) == (place.id, None, None)
    assert corrections(unit) == [] and len(Places(unit.state).list()) == 1


def test_a_failed_correction_in_nodered_is_logged_and_ignored(unit, caplog):
    reconcile.ensure(unit)
    unit.nodered.correction_error = NodeRedError("unreachable")
    edit(unit, FIXTURE_POINT, "lat: 45.52252\n    lon: -122.6912\n")
    with caplog.at_level(logging.INFO, logger=reconcile.__name__):
        outcome = reconcile.ensure(unit)
    assert (outcome.state, outcome.followed) == ("done", "coordinates")
    assert (Places(unit.state).in_use().lat, Places(unit.state).in_use().lon) == (45.52252, -122.6912)
    messages = [r.getMessage() for r in caplog.records]
    assert messages == ["re-rounding the place's rows in Node-RED failed: NodeRedError"]


@pytest.mark.parametrize("block", INVALID_POINTS)
def test_invalid_coordinates_take_the_import_path_and_survive(unit, block):
    """An upgraded unit whose coordinates don't parse still imports, and the file's text is kept."""
    write_backup(unit, BACKUP_ROWS)
    answer_usage(unit.nodered)
    edit(unit, FIXTURE_POINT, block)
    before = unit.config_path.read_text()
    unit.nodered.down = True
    assert reconcile.ensure(unit).state == "waiting_nodered"  # not the fresh-unit default place
    assert Places(unit.state).list() == []
    unit.nodered.down = False
    outcome = reconcile.ensure(unit)
    assert (outcome.state, outcome.imported, outcome.created_default) == ("done", 2, False)
    places = Places(unit.state)
    current = places.in_use()
    assert (current.source, current.lat, current.lon) == ("imported_config", None, None)
    assert len(places.list()) == 3
    assert unit.config_path.read_text() == before.replace(
        "    bearing: 'n'\n", f"    bearing: 'n'\n    survey_id: {current.id}\n", 1
    )
    assert corrections(unit) == [] and unit.nodered.named("correct_location") == []


@pytest.mark.parametrize("block", INVALID_POINTS)
def test_invalid_coordinates_are_not_followed(unit, block):
    reconcile.ensure(unit)  # the in-use place, at 45.0, -122.0
    unit.nodered.calls.clear()
    edit(unit, FIXTURE_POINT, block)
    assert reconcile.ensure(unit).followed == "none"
    assert (Places(unit.state).in_use().lat, Places(unit.state).in_use().lon) == (45.0, -122.0)
    assert corrections(unit) == [] and unit.nodered.calls == []


@pytest.mark.parametrize("block", INVALID_POINTS)
def test_an_unknown_survey_id_with_invalid_coordinates_gets_no_point(unit, block):
    reconcile.ensure(unit)
    place = Places(unit.state).in_use()
    edit(unit, f"survey_id: {place.id}", "survey_id: 3f9a1c2e-si")
    edit(unit, FIXTURE_POINT, block)
    assert reconcile.ensure(unit).followed == "unknown_id"
    current = Places(unit.state).in_use()
    assert (current.id, current.lat, current.lon) == ("3f9a1c2e-si", None, None)
    assert corrections(unit) == []


def test_a_failed_import_is_finished_on_the_next_run(unit, monkeypatch):
    write_backup(unit, BACKUP_ROWS)
    answer_usage(unit.nodered)
    edit(unit, FIXTURE_POINT, "lat: 45.52252\n    lon: -122.6912\n")
    create = Places.create

    def failing(self, survey_id, *args, **kwargs):
        if survey_id == SECOND:
            raise sqlite3.OperationalError("synthetic")
        return create(self, survey_id, *args, **kwargs)

    monkeypatch.setattr(Places, "create", failing)
    with pytest.raises(sqlite3.OperationalError):
        reconcile.ensure(unit)
    places = Places(unit.state)
    assert [place.id for place in places.list()] == [FIRST] and places.reconciled_at() is None

    monkeypatch.setattr(Places, "create", create)
    outcome = reconcile.ensure(unit)
    assert (outcome.state, outcome.imported) == ("done", 1)
    assert sorted(place.id for place in places.list()) == [FIRST, SECOND]  # no duplicate from the file
    assert (places.in_use().id, places.get(SECOND).status) == (FIRST, "used")
    assert file_deployment(unit)["survey_id"] == FIRST
