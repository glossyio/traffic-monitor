"""Check Node-RED's flows.json off-device."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml
from tmsetup_render import load_role_yaml, render

FLOWS = Path(__file__).resolve().parents[2] / "container" / "node-red-tm" / "data" / "flows.json"
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="needs node")


def test_http_errors_set_msg_status_code():
    """The http response node takes its status from msg.statusCode. A status put on msg.res is ignored, so the reply is a 200 (#223)."""
    flows = json.loads(FLOWS.read_text())
    offenders = [node["name"] for node in flows if node["type"] == "function" and "msg.res.statusCode" in node["func"]]
    assert offenders == []


def test_download_headers_wait_for_the_first_chunk():
    """Headers set before tar runs make the browser save an early error as a small ".tar.gz" holding the message."""
    flows = json.loads(FLOWS.read_text())
    setters = sorted(node["name"] for node in flows if node["type"] == "function" and "Content-Disposition" in node["func"])
    assert setters == ["download chunks"]


def test_database_download_tars_a_copy():
    """Node-RED keeps writing tmdb.sqlite, so tar reads a VACUUM INTO copy instead of the live file."""
    flows = json.loads(FLOWS.read_text())

    def one(name):
        [node] = [node for node in flows if node.get("name") == name]
        return node

    assert one("zip files")["addpay"] == "tarArgs"
    copy = one("copy database for download")
    assert (copy["type"], copy["sqlquery"], copy["mydb"]) == ("sqlite", "msg.topic", "2f60c1ab30a6fc8f")
    assert "VACUUM INTO" in one("copy database first?")["func"]
    assert set(one("catch database copy")["scope"]) == {copy["id"], one("copy database first?")["id"]}


def test_download_names_cannot_become_tar_options():
    """tar gets each requested name as an argument, so a name with spaces or a leading "-" could add tar options."""
    flows = json.loads(FLOWS.read_text())
    [validate] = [node for node in flows if node.get("name") == "Validate filenames, setup tar"]
    assert '!/^[A-Za-z0-9][A-Za-z0-9._-]*$/.test(fileName)' in validate["func"]
    assert "msg.tarArgs = ' -C ' + baseDir + ' --' + filepath;" in validate["func"]
    assert "msg.tarArgs = ' -C ' + msg.snapshot + ' -- tmdb.sqlite';" in validate["func"]


def test_mqtt_nodes_keep_their_ids():
    """flows_cred.json stores the broker login by node id, so these nodes must keep their ids (Task 10)."""
    types = {node["id"]: node["type"] for node in json.loads(FLOWS.read_text())}
    assert types.get("9ca3b6ed1a6334c0") == "aedes broker"
    assert types.get("a5d65dd0e3566daa") == "mqtt-broker"


def test_flows_cred_is_still_encrypted():
    assert list(json.loads((FLOWS.parent / "flows_cred.json").read_text())) == ["$"]


def _download_nodes():
    """The data download group's nodes by name, and every node by id."""
    flows = json.loads(FLOWS.read_text())
    by_id = {node["id"]: node for node in flows}
    by_name = {}
    for node in flows:
        if node.get("g") == "c3e71a6b79637b6f" and node.get("name"):
            by_name.setdefault(node["name"], node)
    return by_name, by_id


def test_refused_download_hides_the_processing_window():
    """A refused request must also close the "compressing file(s)" window, or it stays open."""
    by_name, _ = _download_nodes()
    assert "8f8958d08aa3a85d" in by_name["Test for error"]["wires"][1]


def test_repeated_files_parameter_is_handled():
    """?files=a&files=b makes msg.payload.files an array, which has no split()."""
    by_name, _ = _download_nodes()
    assert "Array.isArray(msg.payload.files)" in by_name["Validate filenames, setup tar"]["func"]


def test_database_copy_checks_free_space_and_records_the_cancel_count():
    """The copy must not fill the disk, and "stop if cancelled" needs the Cancel count from when the copy started."""
    by_name, _ = _download_nodes()
    func = by_name["copy database first?"]["func"]
    assert "statfsSync" in func
    assert 'msg.cancelCountAtCopy = flow.get("downloadCancelCount") || 0;' in func
    assert "copyStartedAt" not in func
    assert func.index("statfsSync") < func.index("mkdirSync(msg.snapshot")


def test_cancel_stops_a_database_download_during_the_copy():
    """tar hasn't started while the copy runs, so Cancel's kill signal alone can't stop it."""
    by_name, by_id = _download_nodes()
    stop = by_name["stop if cancelled"]
    assert by_name["copy database for download"]["wires"] == [[stop["id"]]]
    assert stop["outputs"] == 2
    assert stop["wires"][0] == [by_name["zip files"]["id"]]
    assert set(stop["wires"][1]) == {"8a12d83e700bcaa6", "9297900926075b54"}
    assert '(flow.get("downloadCancelCount") || 0) !== msg.cancelCountAtCopy' in stop["func"]
    assert "Date.now()" not in stop["func"]
    remember = by_name["remember Cancel"]
    assert remember["id"] in by_id["88d154342ef138bf"]["wires"][0]
    assert 'flow.set("downloadCancelCount", (flow.get("downloadCancelCount") || 0) + 1);' in remember["func"]


def test_database_copies_left_by_a_restart_are_removed_at_start():
    """A restart mid-download leaves its copy under /db/snapshot, and nothing else would remove it for an hour."""
    by_name, by_id = _download_nodes()
    cleanup = by_name["remove database copies left by a restart"]
    starts = [node for node in by_id.values() if node["type"] == "inject" and node.get("once") is True and cleanup["id"] in node["wires"][0]]
    assert len(starts) == 1 and starts[0]["repeat"] == ""
    # Runs before a download can start, so it can't remove a copy a download is making
    assert float(starts[0]["onceDelay"]) == 0.1
    assert '"/db/snapshot"' in cleanup["func"]
    for name in ("on start", "remove database copies left by a restart", "stop if cancelled", "remember Cancel"):
        assert by_name[name]["id"] in by_id["c3e71a6b79637b6f"]["nodes"]


def test_failed_removal_of_the_database_copy_still_answers_the_download():
    """An error from rmSync would stop the function before it ends or fails the response."""
    by_name, _ = _download_nodes()
    func = by_name["handle end of file or error"]["func"]
    removal = func.index("rmSync(msg.snapshot")
    assert func.rindex("try {", 0, removal) < removal < func.index("} catch (err) {", removal)


def test_database_copies_in_progress_count_against_free_space():
    """Copies run one after another, so a download that arrives while another is copying must leave room for both."""
    by_name, _ = _download_nodes()
    func = by_name["copy database first?"]["func"]
    assert 'const copies = flow.get("databaseCopiesInProgress") || 0;' in func
    assert "Math.max(copies * size - written, 0) + size + 256 * 1024 * 1024" in func
    increment = func.index('flow.set("databaseCopiesInProgress", copies + 1);')
    assert func.index("throw new Error(") < increment < func.index("msg.countsAsCopy = true;") < func.index("mkdirSync(msg.snapshot")


def test_every_end_of_a_database_copy_releases_its_count():
    """A count left behind would refuse every later database download until Node-RED restarts."""
    by_name, _ = _download_nodes()
    release = 'flow.set("databaseCopiesInProgress", Math.max((flow.get("databaseCopiesInProgress") || 0) - 1, 0));'
    for name in ("handle end of file or error", "database copy failed", "stop if cancelled"):
        func = by_name[name]["func"]
        assert func.count(release) == 1, name
        guard = func.index("if (msg.countsAsCopy) {")
        assert guard < func.index(release) < func.index("delete msg.countsAsCopy;"), name
    stop = by_name["stop if cancelled"]["func"]
    # Only the stop path: a copy that goes on to tar is released by "handle end of file or error"
    assert stop.index("!== msg.cancelCountAtCopy") < stop.index(release) < stop.index('msg.payload = "Download stopped";')
    cleanup = by_name["remove database copies left by a restart"]["func"]
    assert 'flow.set("databaseCopiesInProgress", 0);' in cleanup


# GET /tm-internal/status: what tm-control's status page reads from Node-RED (config-load errors, the tmdb schema
# version, the radars), kept in global.tm_status by nodes on init-config and capture-radar.

INIT_DEFAULTS = "94136e5a6f092bb6"  # init config defaults
SET_CONFIG = "b0252bd49dc8e61d"  # sets global.config after a load
CONFIG_SOURCES = {"ecc317fcd059b4c3", "5ffb7c9c38b8c5b0"}  # the inject at start and the watch on config.yml
CONFIG_FILE_IN, CONFIG_YAML = "7e988d24a7912d71", "a328d3aa7640102a"
TMDB = "2f60c1ab30a6fc8f"
SERIAL_IN = {
    "926ac6db07adc540": "TM_RADAR_SERIAL_PORT_00",
    "917b8f4b46895cee": "TM_RADAR_SERIAL_PORT_01",
    "9353b933e36e8b9e": "TM_RADAR_SERIAL_PORT_02",
    "e221212a505a78ac": "TM_RADAR_SERIAL_PORT_03",
}
RADAR_NAMES = sorted(SERIAL_IN.values())
TOKEN = "placeholder-internal-token"

# Runs function nodes the way Node-RED does: each node's On Start code once, then its body with msg, env, global,
# and node. Global context is one object for all the steps, read and written by dotted keys like Node-RED's memory
# store, so a test can run several nodes in turn.
HARNESS = r"""
const input = JSON.parse(require("fs").readFileSync(0, "utf8"));
const store = input.global;
const global = {
    get: (key) => key.split(".").reduce((value, part) => (value == null ? undefined : value[part]), store),
    set: (key, value) => {
        const parts = key.split(".");
        let target = store;
        for (const part of parts.slice(0, -1)) {
            if (typeof target[part] !== "object" || target[part] === null) target[part] = {};
            target = target[part];
        }
        target[parts[parts.length - 1]] = value;
    },
};
const env = { get: (name) => input.env[name] };
const started = new Set();
const results = [];
for (const step of input.steps) {
    const logged = [];
    // Each entry records whether a msg came with it: Node-RED gives an error to catch nodes only then
    const log = (level) => (text, msg) => logged.push([level, String(text), msg !== undefined]);
    const node = { error: log("error"), warn: log("warn"), log: log("log"), status: () => {} };
    if (step.initialize && !started.has(step.id)) {
        new Function("env", "global", "node", step.initialize)(env, global, node);
    }
    started.add(step.id);
    const result = new Function("msg", "env", "global", "node", step.func)(step.msg, env, global, node);
    results.push({ result: result === undefined ? null : result, logged });
}
console.log(JSON.stringify({ results, global: store }));
"""


def run_functions(steps, env=None, context=None):
    """Run (node, msg) steps under node; returns each step's return value and log, and the global context after."""
    payload = {
        "env": env or {},
        "global": context or {},
        "steps": [{"id": node["id"], "func": node["func"], "initialize": node.get("initialize", ""), "msg": msg}
                  for node, msg in steps],
    }
    result = subprocess.run(["node", "-e", HARNESS], input=json.dumps(payload), capture_output=True, text=True,
                            timeout=30)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def tab_id(flows, label):
    [tab] = [node for node in flows if node["type"] == "tab" and node["label"] == label]
    return tab["id"]


def named(flows, name):
    [node] = [node for node in flows if node.get("name") == name]
    return node


def endpoint_nodes():
    """The status endpoint's nodes: http in, the token check, the status builder, and the two responses."""
    flows = json.loads(FLOWS.read_text())
    by_id = {node["id"]: node for node in flows}
    [endpoint] = [node for node in flows if node["type"] == "http in" and node.get("url") == "/tm-internal/status"]
    [[check_id]] = endpoint["wires"]
    [[build_id], [refused_id]] = by_id[check_id]["wires"]
    [[answer_id]] = by_id[build_id]["wires"]
    return endpoint, by_id[check_id], by_id[build_id], by_id[answer_id], by_id[refused_id]


def test_tm_internal_status_endpoint_exists():
    flows = json.loads(FLOWS.read_text())
    endpoint, check, build, answer, refused = endpoint_nodes()
    assert endpoint["method"] == "get"
    assert endpoint["z"] == tab_id(flows, "init-config")
    assert check["type"] == "function" and check["outputs"] == 2
    assert "x-tm-internal-token" in check["func"] and "TM_INTERNAL_TOKEN" in check["func"]
    assert build["type"] == "function" and "tm_status" in build["func"]
    assert (answer["type"], answer["statusCode"]) == ("http response", "")
    assert (refused["type"], str(refused["statusCode"])) == ("http response", "401")


@needs_node
@pytest.mark.parametrize("env, header, allowed", [
    ({}, "anything", False),
    ({}, "", False),
    ({}, None, False),
    ({"TM_INTERNAL_TOKEN": ""}, "", False),
    ({"TM_INTERNAL_TOKEN": ""}, None, False),
    ({"TM_INTERNAL_TOKEN": TOKEN}, None, False),
    ({"TM_INTERNAL_TOKEN": TOKEN}, "", False),
    ({"TM_INTERNAL_TOKEN": TOKEN}, "wrong", False),
    ({"TM_INTERNAL_TOKEN": TOKEN}, TOKEN + " ", False),
    ({"TM_INTERNAL_TOKEN": TOKEN}, TOKEN.upper(), False),
    ({"TM_INTERNAL_TOKEN": TOKEN}, TOKEN, True),
], ids=["unset", "unset-empty-header", "unset-no-header", "empty", "empty-no-header", "no-header", "empty-header",
        "wrong", "trailing-space", "case", "right"])
def test_tm_internal_token_check_fails_closed(env, header, allowed):
    """Review Focus 5: the right header passes; anything else, and every request without a token, gets the 401."""
    _, check, *_ = endpoint_nodes()
    headers = {} if header is None else {"x-tm-internal-token": header}
    [step] = run_functions([(check, {"req": {"headers": headers}, "payload": {}})], env=env)["results"]
    passed, refused = step["result"]
    if allowed:
        assert passed is not None and refused is None
    else:
        assert passed is None and refused["payload"] == {"error": "unauthorized"}


def test_init_config_no_longer_reads_time():
    func = named(json.loads(FLOWS.read_text()), "init config defaults")["func"]
    assert "payload.time" not in func
    assert "npt_set" not in func


@needs_node
def test_init_config_defaults_loads_the_new_config_template():
    """A new device's config.yml has no time: section; init config defaults must still pass it on."""
    values = {**load_role_yaml("defaults/main.yml"), "tmsetup_latitude": 0.0, "tmsetup_longitude": 0.0,
              "tmsetup_bearing": "n"}
    config = yaml.safe_load(render("container/node-red-tm/config/config.yml.j2", **values))
    defaults = named(json.loads(FLOWS.read_text()), "init config defaults")
    [step] = run_functions([(defaults, {"payload": config})])["results"]
    assert step["logged"] == []
    assert step["result"]["payload"]["sensors"]["radars"]["TM_RADAR_SERIAL_PORT_00"]["enabled"] is True


@needs_node
def test_thingsboard_without_a_host_is_a_config_error():
    """Only this init config defaults error passes msg, so the catch records it in tm_status.config.errors. The lat,
    lon, and bearing checks stay log-only: they flag the shipped empty defaults, and tm-control checks those keys."""
    flows = json.loads(FLOWS.read_text())
    defaults = named(flows, "init config defaults")
    assert INIT_DEFAULTS in named(flows, "catch: config.yml load errors")["scope"]
    values = {**load_role_yaml("defaults/main.yml"), "tmsetup_latitude": 0.0, "tmsetup_longitude": 0.0,
              "tmsetup_bearing": "n"}
    config = yaml.safe_load(render("container/node-red-tm/config/config.yml.j2", **values))
    config["thingsboard"] = {"enabled": True, "access_token": "tb-token-1"}
    config["deployment"] = {"lat": "north", "lon": "west", "bearing": ""}
    [step] = run_functions([(defaults, {"payload": config})])["results"]
    # The key each message names ("Node-RED config.yml key thingsboard.host needs ..."), and whether msg came with it
    errors = {text.split()[3]: with_msg for level, text, with_msg in step["logged"] if level == "error"}
    assert errors == {"thingsboard.host": True, "deployment.lat": False, "deployment.lon": False,
                      "deployment.bearing": False}
    assert step["result"]["payload"]["thingsboard"]["enabled"] is False


def test_schema_version_is_recorded():
    """tm-control compares tmdb's user_version with the newest migration, and never opens the database itself."""
    flows = json.loads(FLOWS.read_text())
    by_id = {node["id"]: node for node in flows}
    [read] = [node for node in flows if node["type"] == "sqlite" and "PRAGMA user_version" in node.get("sql", "")]
    assert read["z"] == tab_id(flows, "init-config")
    assert (read["sqlquery"], read["mydb"]) == ("fixed", TMDB)
    [[record_id]] = read["wires"]
    assert "tm_status.schema_version" in by_id[record_id]["func"]


def test_each_config_load_resets_the_status_and_reads_the_schema_version():
    """The inject at start and the watch on config.yml start a load; its errors and the schema read follow it."""
    flows = json.loads(FLOWS.read_text())
    by_id = {node["id"]: node for node in flows}
    start = named(flows, "tm-internal: config load started")
    assert {node["id"] for node in flows if start["id"] in sum(node.get("wires", []), [])} == CONFIG_SOURCES
    for source in CONFIG_SOURCES:
        assert by_id[source]["wires"] == [[start["id"]]]
    [read] = [node for node in flows if node["type"] == "sqlite" and "PRAGMA user_version" in node.get("sql", "")]
    assert set(start["wires"][0]) == {CONFIG_FILE_IN, read["id"]}
    catch = named(flows, "catch: config.yml load errors")
    assert catch["type"] == "catch"
    assert set(catch["scope"]) == {CONFIG_FILE_IN, CONFIG_YAML, INIT_DEFAULTS}
    assert catch["wires"] == [[named(flows, "tm-internal: record config error")["id"]]]
    loaded = named(flows, "tm-internal: config loaded")
    assert by_id[SET_CONFIG]["wires"] == [["ac8b2de05ec27001", loaded["id"]]]


def test_radar_status_follows_the_four_serial_nodes():
    flows = json.loads(FLOWS.read_text())
    by_id = {node["id"]: node for node in flows}
    [status] = [node for node in flows if node["type"] == "status" and node["z"] == tab_id(flows, "capture-radar")]
    assert set(status["scope"]) == set(SERIAL_IN)
    [[port_status_id]] = status["wires"]
    for serial_id, name in SERIAL_IN.items():
        assert f'"{serial_id}": "{name}"' in by_id[port_status_id]["func"]
        first, reading = by_id[serial_id]["wires"][0]
        assert by_id[first]["type"] == "switch"  # the existing enabled? check, unchanged
        assert f'"tm_status.radars.{name}.last_reading_at"' in by_id[reading]["func"]


def status_step():
    """The status endpoint's builder as a step, with an empty request."""
    _, _, build, _, _ = endpoint_nodes()
    return (build, {"req": {"headers": {}}, "payload": {}})


@needs_node
def test_status_answers_before_the_first_config_load():
    [step] = run_functions([status_step()], env={"TM_VERSION": "9.9.9"})["results"]
    body = step["result"]["payload"]
    assert body["status"] == "ok"
    assert body["tm_version"] == "9.9.9"
    assert 0 <= body["uptime_seconds"] <= 5
    assert body["config"] == {"loaded_at": None, "errors": []}
    assert body["schema_version"] is None
    assert body["deployment"] is None
    assert body["radars"] == {name: {"enabled": False, "port_open": False, "last_reading_at": None}
                              for name in RADAR_NAMES}


@needs_node
def test_config_errors_are_kept_until_the_next_load():
    """Only an error's first line: a YAML error goes on to quote config.yml, which can hold the ThingsBoard token."""
    flows = json.loads(FLOWS.read_text())
    start = named(flows, "tm-internal: config load started")
    record = named(flows, "tm-internal: record config error")
    yaml_error = {"error": {"message": "bad indentation of a mapping entry (5:5)\n\n 4 |     access_token: tb-token-1\n"
                                       " 5 |   x\n---------^"}}
    out = run_functions([
        (start, {"payload": "/config/config.yml"}),
        (record, yaml_error),
        (record, yaml_error),  # the watch can fire twice for one save
        (record, {"error": {"message": "TypeError: Cannot read properties of undefined (reading 'enabled')"}}),
        status_step(),
        (start, {"payload": "/config/config.yml"}),
        status_step(),
    ])
    first, _, _, _, before, _, after = out["results"]
    assert first["result"] == {"payload": "/config/config.yml"}  # passed on to the file read
    config = before["result"]["payload"]["config"]
    assert config["errors"] == ["bad indentation of a mapping entry (5:5)",
                                "TypeError: Cannot read properties of undefined (reading 'enabled')"]
    assert config["loaded_at"].endswith("Z")
    assert "tb-token-1" not in json.dumps(out)
    assert after["result"]["payload"]["config"]["errors"] == []
    assert after["result"]["payload"]["config"]["loaded_at"] >= config["loaded_at"]


@needs_node
@pytest.mark.parametrize("payload, expected", [([{"user_version": 3}], 3), ([{"user_version": 0}], 0), ([], None),
                                               ([{"user_version": "3"}], None), (None, None)])
def test_schema_version_is_reported(payload, expected):
    flows = json.loads(FLOWS.read_text())
    [read] = [node for node in flows if node["type"] == "sqlite" and "PRAGMA user_version" in node.get("sql", "")]
    record = {node["id"]: node for node in flows}[read["wires"][0][0]]
    out = run_functions([(record, {"payload": payload}), status_step()])
    assert out["results"][1]["result"]["payload"]["schema_version"] == expected


@needs_node
def test_radars_report_config_port_and_last_reading():
    flows = json.loads(FLOWS.read_text())
    by_id = {node["id"]: node for node in flows}
    loaded = named(flows, "tm-internal: config loaded")
    [status] = [node for node in flows if node["type"] == "status" and node["z"] == tab_id(flows, "capture-radar")]
    port_status = by_id[status["wires"][0][0]]
    reading_00 = by_id[by_id["926ac6db07adc540"]["wires"][0][1]]

    def port(serial_id, text):
        return (port_status, {"status": {"text": text, "source": {"id": serial_id, "type": "serial in"}}})

    config = {"deployment": {"lat": 0.0, "lon": 0.0, "bearing": "n"},
              "sensors": {"radars": {"TM_RADAR_SERIAL_PORT_00": {"enabled": True},
                                     "TM_RADAR_SERIAL_PORT_01": {"enabled": False}}}}
    out = run_functions([
        (loaded, {"payload": config}),
        port("926ac6db07adc540", "node-red:common.status.connected"),
        port("917b8f4b46895cee", "node-red:common.status.connected"),
        port("917b8f4b46895cee", "node-red:common.status.not-connected"),
        port("9353b933e36e8b9e", "serial.status.stopped"),
        (reading_00, {"payload": '{"speed":12.3}', "port": "/dev/ttyACM0"}),
        status_step(),
    ], context={"config": config})
    body = out["results"][-1]["result"]["payload"]
    assert body["deployment"] == {"lat": 0.0, "lon": 0.0, "bearing": "n"}
    radars = body["radars"]
    assert sorted(radars) == RADAR_NAMES
    assert radars["TM_RADAR_SERIAL_PORT_00"]["enabled"] is True
    assert radars["TM_RADAR_SERIAL_PORT_00"]["port_open"] is True
    assert radars["TM_RADAR_SERIAL_PORT_00"]["last_reading_at"].endswith("Z")
    assert radars["TM_RADAR_SERIAL_PORT_01"] == {"enabled": False, "port_open": False, "last_reading_at": None}
    assert radars["TM_RADAR_SERIAL_PORT_02"]["port_open"] is False
    assert radars["TM_RADAR_SERIAL_PORT_03"] == {"enabled": False, "port_open": False, "last_reading_at": None}


@needs_node
def test_a_radar_removed_from_the_config_is_no_longer_enabled():
    flows = json.loads(FLOWS.read_text())
    loaded = named(flows, "tm-internal: config loaded")
    before = {"sensors": {"radars": {"TM_RADAR_SERIAL_PORT_00": {"enabled": True}}}}
    after = {"deployment": {"lat": None, "lon": None, "bearing": ""}, "sensors": {"radars": {}}}
    out = run_functions([(loaded, {}), status_step()], context={"config": before})
    assert out["results"][1]["result"]["payload"]["radars"]["TM_RADAR_SERIAL_PORT_00"]["enabled"] is True
    out = run_functions([(loaded, {}), status_step()], context={**out["global"], "config": after})
    body = out["results"][1]["result"]["payload"]
    assert body["radars"]["TM_RADAR_SERIAL_PORT_00"]["enabled"] is False
    assert body["deployment"] == {"lat": None, "lon": None, "bearing": None}
