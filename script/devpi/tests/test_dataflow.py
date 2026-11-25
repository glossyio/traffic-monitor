"""The database: schema current, no plate reads, new radar and event rows when there's traffic, and
deployment rows that are rounded, one open per enabled sensor, and on the configured survey.

Every test here but the manifest's reads tmdb.sqlite, so they run only on units marked pii_free, and they
print only counts, timestamps, sensor names, and survey ids.
"""

import json
import re
from datetime import datetime

import pytest
from devpi_checks import (db_query, pi_now, places_state, read_root_file, require_pii_free, role_vars, session,
                          tm_internal_answer, tm_internal_token)

MAX_RADAR_AGE_SECONDS = 15 * 60
MAX_EVENT_AGE_SECONDS = 60 * 60


@pytest.fixture(autouse=True)
def pii_free_only(expect):
    require_pii_free(expect)


@pytest.fixture(scope="module")
def admin_session(address, tm_login):
    """The inventory admin's session cookie (Redacted); skips when the inventory has no tm_control_login."""
    username, password = tm_login
    return session(address, username, password)


def test_schema_current(host, codedir, codeowner):
    """tmdb_migrate.py --check exits 0: no pending migrations and no drift."""
    runner = f"{codedir}/node-red-tm/schema/tmdb_migrate.py"
    # Code from before the migrations (#208) leaves no ExecStartPre; a runner left by an
    # earlier deploy would then report the unmigrated database as pending.
    if runner not in host.file("/etc/containers/systemd/node-red-tm.container").content_string:
        pytest.skip("the deployed node-red-tm.container doesn't run tmdb_migrate.py (code from before #208)")
    with host.sudo():
        result = host.run(f"runuser -u {codeowner} -- python3 {runner} "
                          f"--db {codedir}/node-red-tm/db/tmdb.sqlite --check")
    assert result.rc == 0, f"exit {result.rc}: {result.stderr.strip()}"


def test_no_plate_reads(host, codedir):
    count = db_query(host, codedir, "SELECT COUNT(*) FROM plate_recognizer")[0][0]
    assert count == 0, f"plate_recognizer has {count} rows on a unit marked pii_free"


def newest_age(host, codedir, table, column):
    newest = db_query(host, codedir, f"SELECT MAX({column}) FROM {table}")[0][0]
    return None if newest is None else pi_now(host) - newest


def test_new_radar_rows(host, expect, codedir):
    if not (expect["live_traffic"] and expect["radars"]):
        pytest.skip("needs live_traffic and a radar")
    age = newest_age(host, codedir, "radar_dov", "time")
    assert age is not None, "radar_dov is empty"
    assert age < MAX_RADAR_AGE_SECONDS, f"newest radar_dov row is {age / 60:.0f} minutes old"


def test_new_events(host, expect, codedir):
    if not (expect["live_traffic"] and expect["cameras"]):
        pytest.skip("needs live_traffic and a camera")
    age = newest_age(host, codedir, "events", "end_time")
    assert age is not None, "events is empty"
    assert age < MAX_EVENT_AGE_SECONDS, f"newest event is {age / 60:.0f} minutes old"


def test_deployment_rows_are_never_finer_than_two_decimals(host, codedir):
    """tmdb keeps no coordinate finer than two decimal places, and lat, lon and location_precision
    are all set or all NULL."""
    # lat * 100 against its nearest whole number, so a value stored as Number(x.toFixed(2)) and one
    # from SQLite's ROUND both pass even if they differ in the last bit
    finer = db_query(host, codedir, "SELECT COUNT(*) FROM deployment WHERE lat IS NOT NULL AND "
                                    "(ABS(lat * 100 - ROUND(lat * 100)) > 1e-6 "
                                    "OR ABS(lon * 100 - ROUND(lon * 100)) > 1e-6)")[0][0]
    assert finer == 0, f"{finer} deployment rows have a coordinate finer than two decimal places"
    half = db_query(host, codedir, "SELECT COUNT(*) FROM deployment WHERE (lat IS NULL) != (lon IS NULL) "
                                   "OR (lat IS NULL) != (location_precision IS NULL)")[0][0]
    assert half == 0, f"{half} deployment rows have only some of lat, lon and location_precision"


def enabled_sensors(node_red_config):
    """(sensorType, sensorName) of each enabled sensor in config.yml. The engine leaves the rows of
    disabled sensors alone, so the deployment checks look only at these."""
    return {(sensor_type, name)
            for sensor_type, sensors in (node_red_config.get("sensors") or {}).items()
            for name, sensor in (sensors or {}).items() if (sensor or {}).get("enabled") is True}


def test_each_enabled_sensor_has_one_open_deployment(host, codedir, node_red_config):
    """Each enabled sensor in config.yml has exactly one open deployment row."""
    counts = {(sensor_type, name): count for sensor_type, name, count in db_query(
        host, codedir, "SELECT sensorType, sensorName, COUNT(*) FROM deployment "
                       "WHERE entryEndDateTime IS NULL GROUP BY sensorType, sensorName")}
    wrong = sorted(f"{sensor_type}.{name}: {counts.get((sensor_type, name), 0)}"
                   for sensor_type, name in enabled_sensors(node_red_config)
                   if counts.get((sensor_type, name), 0) != 1)
    assert not wrong, f"enabled sensors without exactly one open deployment row: {', '.join(wrong)}"


def test_open_deployments_carry_the_configured_survey(host, codedir, node_red_config):
    """Once config.yml names a survey, every enabled sensor's open deployment row carries it."""
    survey_id = str((node_red_config.get("deployment") or {}).get("survey_id") or "").lower()
    if not survey_id:
        pytest.skip("config.yml sets no deployment.survey_id")
    if not re.fullmatch(r"[0-9a-f]{8}-si", survey_id):
        pytest.fail("config.yml's deployment.survey_id isn't a survey id (8 hex characters and -si)", pytrace=False)
    enabled = enabled_sensors(node_red_config)
    rows = db_query(host, codedir, "SELECT sensorType, sensorName, survey_id FROM deployment "
                                   "WHERE entryEndDateTime IS NULL")
    wrong = sorted(f"{sensor_type}.{name}: {row_survey}" for sensor_type, name, row_survey in rows
                   if (sensor_type, name) in enabled and row_survey != survey_id)
    assert not wrong, f"open deployment rows without the configured survey {survey_id}: {', '.join(wrong)}"


def test_open_deployments_name_a_known_place(host, codedir, address, admin_session):
    """Each survey id on an open deployment row is the id of a place on the Location page (GET /surveys), so the
    unit is never recording to a place the page can't show. Closed rows may name a place that was deleted since: the
    page allows deleting a used place, and tmdb keeps its rows. Rows with no survey are the page's unassigned count,
    not a place. Only ids are kept."""
    used = {row[0] for row in db_query(host, codedir, "SELECT DISTINCT survey_id FROM deployment "
                                                        "WHERE survey_id IS NOT NULL AND entryEndDateTime IS NULL")}
    known = {place.get("id") for place in places_state(address, admin_session)["surveys"]}
    assert used <= known, f"open deployment rows name survey ids GET /surveys doesn't list: {sorted(used - known)}"


def test_no_upload_node_sends_the_settings(host, codedir):
    """The deployed flows.json has no config_tm, the name the old upload sent the whole config.yml under, so no node on
    the unit can send the settings to the server. Only the answer is kept, not the file."""
    flows = read_root_file(host, f"{codedir}/node-red-tm/data/flows.json")
    found = "config_tm" in flows
    del flows
    assert not found, "the deployed flows.json still mentions config_tm (run tmsetup.sh -t node-red-tm)"


WATCH_MARK_SECONDS = 300
WATCH_MAX_AGE_SECONDS = 400
# The first mark after a start writes nothing, so the first rows come at the second mark: up to ten minutes
# after the start, plus the time to write them.
WATCH_FIRST_ROWS_SECONDS = 11 * 60


def service_active_seconds(host, unit):
    """How long a service has been active, from systemd's monotonic stamp against the Pi's uptime,
    so a jump of the wall clock since the start doesn't change it."""
    entered = int(host.check_output(f"systemctl show -p ActiveEnterTimestampMonotonic --value {unit}"))
    uptime = float(host.check_output("cut -d' ' -f1 /proc/uptime"))
    return uptime - entered / 1e6


def node_red_active_seconds(host):
    return service_active_seconds(host, "node-red-tm.service")


def newest_watch_rows(host, codedir, table, sensor_column, columns):
    """(time, rows) for the newest window in a watch log table: each row a dict of the columns, keyed by its sensor
    name. (None, {}) when the table is empty."""
    selected = ", ".join([sensor_column, *columns])
    rows = db_query(host, codedir, f"SELECT time, {selected} FROM {table} "
                                   f"WHERE time = (SELECT MAX(time) FROM {table})")
    if not rows:
        return None, {}
    return rows[0][0], {row[1]: dict(zip(columns, row[2:])) for row in rows}


def test_the_watch_log_has_a_row_for_each_sensor(host, expect, codedir, node_red_config, frigate_stats,
                                                 frigate_config):
    """The newest watch_camera and watch_radar rows are on a five-minute mark within 400 seconds of now, name each
    camera and radar config.yml lists, and, for a camera Frigate reports on, say Frigate answered, with its stats
    messages, detection setting, and whether the camera is on (as Frigate's configuration says), with no frame rate
    when it is off; an expected radar's port is open, it answered the once-a-minute power-state question, and
    radar_on says whether it is on. Reads only, and passes with the camera on or off and the radar active or idle.
    A radar that answers but is idle (radar_on 0) is a finding for a person, not for this test."""
    active = node_red_active_seconds(host)
    if active < WATCH_FIRST_ROWS_SECONDS:
        pytest.skip(f"node-red-tm.service has been active for {active / 60:.0f} minutes; its first watch log rows "
                    f"come at the second five-minute mark after a start, so check again after 11 minutes")
    sensors = node_red_config.get("sensors") or {}
    cameras = sensors.get("cameras") or {}
    radars = sensors.get("radars") or {}
    if not cameras and not radars:
        pytest.skip("config.yml lists no cameras or radars")
    now = pi_now(host)
    problems = []

    def check_time(table, newest):
        if newest is None:
            problems.append(f"{table} is empty")
            return False
        if newest % WATCH_MARK_SECONDS != 0:
            problems.append(f"the newest {table} time {newest} isn't a multiple of {WATCH_MARK_SECONDS}")
        if not 0 <= now - newest <= WATCH_MAX_AGE_SECONDS:
            problems.append(f"the newest {table} time is {now - newest:.0f} seconds before now, "
                            f"not within {WATCH_MAX_AGE_SECONDS}")
        return True

    if cameras:
        newest, rows = newest_watch_rows(host, codedir, "watch_camera", "camera",
                                         ["frigate_answers", "camera_answers", "detection_enabled", "camera_on",
                                          "camera_fps"])
        if check_time("watch_camera", newest):
            if set(rows) != set(cameras):
                problems.append(f"the newest watch_camera rows are for cameras {sorted(rows)}, "
                                f"config.yml's sensors.cameras has {sorted(cameras)}")
            reported = frigate_stats.get("cameras") or {}
            configured_cameras = frigate_config.get("cameras") or {}
            for key, entry in cameras.items():
                row = rows.get(key)
                frigate_name = (entry or {}).get("frigate_camera") or key
                if row is None or frigate_name not in reported:
                    continue
                if not (row["frigate_answers"] or 0) >= 1:
                    problems.append(f"watch_camera.frigate_answers for camera {key} is {row['frigate_answers']}, "
                                    f"Frigate reports on it now")
                if not (row["camera_answers"] or 0) >= 1:
                    problems.append(f"watch_camera.camera_answers for camera {key} is {row['camera_answers']}, "
                                    f"Frigate reports on it now")
                detecting = reported[frigate_name].get("detection_enabled")
                if detecting is not None and row["detection_enabled"] != int(bool(detecting)):
                    problems.append(f"watch_camera.detection_enabled for camera {key} is {row['detection_enabled']}, "
                                    f"Frigate's stats say {int(bool(detecting))} now")
                if row["camera_on"] is None:
                    problems.append(f"watch_camera.camera_on for camera {key} is empty, Frigate reports on it now")
                else:
                    enabled = (configured_cameras.get(frigate_name) or {}).get("enabled")
                    if enabled is not None and row["camera_on"] != int(bool(enabled)):
                        problems.append(f"watch_camera.camera_on for camera {key} is {row['camera_on']}, "
                                        f"Frigate's configuration says {int(bool(enabled))} now")
                    if row["camera_on"] == 0 and row["camera_fps"] is not None:
                        problems.append(f"watch_camera.camera_fps for camera {key} is {row['camera_fps']}, "
                                        f"empty is expected while the camera is off")
    if radars:
        newest, rows = newest_watch_rows(host, codedir, "watch_radar", "radar",
                                         ["port_open", "radar_answers", "radar_on"])
        if check_time("watch_radar", newest):
            if set(rows) != set(radars):
                problems.append(f"the newest watch_radar rows are for radars {sorted(rows)}, "
                                f"config.yml's sensors.radars has {sorted(radars)}")
            for radar in expect["radars"]:
                row = rows.get(radar["env_name"])
                if row is not None and row["port_open"] != 1:
                    problems.append(f"watch_radar.port_open for radar {radar['env_name']} is {row['port_open']}, "
                                    f"the inventory says it is attached")
                if row is not None and (radars.get(radar["env_name"]) or {}).get("enabled") is True:
                    if not (row["radar_answers"] or 0) >= 1:
                        problems.append(f"watch_radar.radar_answers for radar {radar['env_name']} is "
                                        f"{row['radar_answers']}, config.yml enables it and the inventory says "
                                        f"it is attached")
                    if row["radar_on"] not in (0, 1):
                        problems.append(f"watch_radar.radar_on for radar {radar['env_name']} is "
                                        f"{row['radar_on']}, it should be 1 or 0")
    assert not problems, "; ".join(problems)


# The first snapshot is posted when tm-control starts and Frigate answers (the retry is 30 seconds); two minutes
# after both services are up is the longest the first rows take
SETUP_FIRST_ROWS_SECONDS = 2 * 60
SETUP_MAX_AGE_SECONDS = 400  # a snapshot every 300 seconds, plus the time to gather and post
MANIFEST = f"{role_vars()['tmsetup_etc_dir']}/manifest.json"


def test_the_manifest_says_what_the_unit_runs(host):
    """The manifest's version is a release's (X.Y.Z) or dev's (X.Y.Z-dev), its update channel is development exactly
    when the version ends in -dev, its update repository is <owner>/<repo>, and its commit is a full commit id or
    unknown. Reads only."""
    manifest = json.loads(read_root_file(host, MANIFEST))
    version = manifest.get("tm_version")
    update = manifest.get("update") or {}
    problems = []
    if not isinstance(version, str) or not re.fullmatch(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(-dev)?", version):
        problems.append(f"tm_version {version!r} is neither X.Y.Z nor X.Y.Z-dev")
    elif update.get("channel") != ("development" if version.endswith("-dev") else "stable"):
        problems.append(f"update.channel {update.get('channel')!r} doesn't follow tm_version {version!r}")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", str(update.get("repo"))):
        problems.append(f"update.repo {update.get('repo')!r} isn't <owner>/<repo>")
    commit = (manifest.get("git") or {}).get("commit")
    if commit != "unknown" and not re.fullmatch(r"[0-9a-f]{40}", str(commit)):
        problems.append(f"git.commit {commit!r} is neither a full commit id nor unknown")
    assert not problems, "; ".join(problems)


def test_the_setup_history_has_a_row_in_force(host, codedir, node_red_config, frigate_config):
    """The setup history has exactly one open setup_device row, matching the manifest's version, the database's
    schema version, and Frigate's version; each camera in config.yml that Frigate has (the first key for each Frigate
    camera) has one open setup_camera row, matching Frigate's detect size and zone keys; events_with_setup lists each
    event once; and Node-RED's status says the last snapshot was complete and arrived within 400 seconds. Reads only.
    Messages name columns and config.yml's camera keys, never Frigate's name for a camera."""
    for unit in ("tm-control.service", "node-red-tm.service"):
        active = service_active_seconds(host, unit)
        if active < SETUP_FIRST_ROWS_SECONDS:
            pytest.skip(f"{unit} has been active for {active:.0f} seconds; the first setup rows come within "
                        f"{SETUP_FIRST_ROWS_SECONDS} seconds of both services being up, so check again then")
    problems = []

    # the unit
    device_columns = ["tm_version", "schema_version", "frigate_version"]
    device = db_query(host, codedir, f"SELECT {', '.join(device_columns)} FROM setup_device WHERE ended IS NULL")
    if len(device) != 1:
        problems.append(f"setup_device has {len(device)} rows with no ended, not 1")
    else:
        row = dict(zip(device_columns, device[0]))
        manifest = json.loads(read_root_file(host, MANIFEST))
        if row["tm_version"] != manifest.get("tm_version"):
            problems.append("setup_device.tm_version isn't the manifest's tm_version")
        user_version = db_query(host, codedir, "PRAGMA user_version")[0][0]
        if row["schema_version"] != user_version:
            problems.append(f"setup_device.schema_version is {row['schema_version']}, PRAGMA user_version is "
                            f"{user_version}")
        version = host.check_output("curl -fsS --max-time 10 http://localhost:5000/api/version").strip().strip('"')
        if row["frigate_version"] != version:
            problems.append("setup_device.frigate_version isn't what Frigate's /api/version answers")

    # each camera
    cameras = (node_red_config.get("sensors") or {}).get("cameras") or {}
    frigate_cameras = frigate_config.get("cameras") or {}
    camera_columns = ["camera", "detect_width", "detect_height", "zones"]
    open_rows = {}
    for row in db_query(host, codedir, f"SELECT {', '.join(camera_columns)} FROM setup_camera WHERE ended IS NULL"):
        open_rows.setdefault(row[0], []).append(dict(zip(camera_columns, row)))
    paired = set()
    for key, entry in cameras.items():
        frigate_name = (entry or {}).get("frigate_camera") or key
        frigate_camera = frigate_cameras.get(frigate_name)
        if frigate_camera is None:
            continue
        if frigate_name in paired:
            continue  # a second key for the same Frigate camera is a duplicate, which the snapshot leaves out
        paired.add(frigate_name)
        rows = open_rows.get(key, [])
        if len(rows) != 1:
            problems.append(f"setup_camera has {len(rows)} rows with no ended for camera {key}, not 1")
            continue
        row, detect = rows[0], frigate_camera.get("detect") or {}
        if (row["detect_width"], row["detect_height"]) != (detect.get("width"), detect.get("height")):
            problems.append(f"setup_camera.detect_width and detect_height for camera {key} aren't Frigate's detect "
                            "size")
        try:
            keys = sorted(zone["key"] for zone in json.loads(row["zones"]))
        except (TypeError, ValueError, KeyError):
            problems.append(f"setup_camera.zones for camera {key} isn't a JSON list of zones with a key")
            continue
        if keys != sorted(frigate_camera.get("zones") or {}):
            problems.append(f"the keys in setup_camera.zones for camera {key} aren't the zone keys Frigate lists")

    # the view
    in_view = db_query(host, codedir, "SELECT count(*) FROM events_with_setup")[0][0]
    events = db_query(host, codedir, "SELECT count(*) FROM events")[0][0]
    if in_view != events:
        problems.append(f"events_with_setup has {in_view} rows, events has {events}")

    # Node-RED's status: only the setup section is kept, which holds no camera or value
    status, body = tm_internal_answer(host, tm_internal_token(host))
    setup = body.get("setup") if isinstance(body, dict) else None
    del body
    if status != "200" or not isinstance(setup, dict):
        problems.append(f"Node-RED's status answered {status} and has no setup section")
    else:
        if setup.get("complete") is not True:
            problems.append("setup.complete in Node-RED's status isn't true")
        try:
            age = pi_now(host) - datetime.fromisoformat(setup["received_at"].replace("Z", "+00:00")).timestamp()
        except (KeyError, AttributeError, ValueError):
            problems.append("setup.received_at in Node-RED's status isn't a time")
        else:
            if not -5 <= age <= SETUP_MAX_AGE_SECONDS:
                problems.append(f"setup.received_at is {age:.0f} seconds before now, not within "
                                f"{SETUP_MAX_AGE_SECONDS}")
    assert not problems, "; ".join(problems)
