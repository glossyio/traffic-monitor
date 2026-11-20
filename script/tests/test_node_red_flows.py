"""Check Node-RED's flows.json off-device."""

import copy
import json
import re
import sqlite3
import subprocess
import textwrap
from datetime import datetime
from pathlib import Path

import pytest
import yaml
from required_tools import needs
from tmsetup_render import load_role_yaml, render

FLOWS = Path(__file__).resolve().parents[2] / "container" / "node-red-tm" / "data" / "flows.json"
needs_node = needs("node")


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

# Runs function nodes the way Node-RED 5.0.8 does: each node's On Start code once, then its body with msg, env,
# global, flow, and node. The code runs in a vm context that holds only the names the function node's sandbox has
# (10-function.js: console, util, Buffer, URL, URLSearchParams, Date, RED, context, flow, global, env, the timer
# functions, promisify), so a host-only global such as structuredClone or fetch is a ReferenceError here too, as it
# is on the device. Global context is one object for all the steps, read and written by dotted keys like Node-RED's
# memory store, so a test can run several nodes in turn. Flow context is a plain object read and written by key.
HARNESS = r"""
const vm = require("vm");
const util = require("util");
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
const flowStore = input.flow;
const flow = {
    get: (key) => flowStore[key],
    set: (key, value) => { flowStore[key] = value; },
};
const env = { get: (name) => input.env[name] };
const sandbox = {
    console, util, Buffer, URL, URLSearchParams, Date, RED: { util: {} }, context: {}, flow, global, env,
    setTimeout, clearTimeout, setInterval, clearInterval, promisify: util.promisify,
};
const context = vm.createContext(sandbox);
const started = new Set();
const results = [];
for (const step of input.steps) {
    const logged = [];
    // Each entry records whether a msg came with it: Node-RED gives an error to catch nodes only then
    const log = (level) => (text, msg) => logged.push([level, String(text), msg !== undefined]);
    const node = { error: log("error"), warn: log("warn"), log: log("log"), status: () => {} };
    if (step.initialize && !started.has(step.id)) {
        new vm.Script("(function(node) {" + step.initialize + "\n})").runInContext(context)(node);
    }
    started.add(step.id);
    const result = new vm.Script("(function(msg, node) {" + step.func + "\n})").runInContext(context)(step.msg, node);
    // a key whose value is undefined vanishes in JSON, so the payload's keys are reported on their own
    const payload = result == null ? undefined : result.payload;
    const keys = payload !== null && typeof payload === "object" && !Array.isArray(payload) ? Object.keys(payload) : null;
    results.push({ result: result === undefined ? null : result, logged, keys });
}
console.log(JSON.stringify({ results, global: store, flow: flowStore }));
"""


def run_functions(steps, env=None, context=None, flow=None):
    """Run (node, msg) steps under node; returns each step's return value and log, and the global context after."""
    payload = {
        "env": env or {},
        "global": context or {},
        "flow": flow or {},
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


TB_ENV = {"TM_THINGSBOARD_ACCESS_TOKEN": "tb-placeholder-0001"}


@needs_node
def test_thingsboard_without_a_host_is_a_config_error():
    """Only this init config defaults error passes msg, so the catch records it in tm_status.config.errors. The lat,
    lon, and bearing checks stay log-only: they flag values that aren't coordinates or bearings, and tm-control checks
    those keys."""
    flows = json.loads(FLOWS.read_text())
    defaults = named(flows, "init config defaults")
    assert INIT_DEFAULTS in named(flows, "catch: config.yml load errors")["scope"]
    values = {**load_role_yaml("defaults/main.yml"), "tmsetup_latitude": 0.0, "tmsetup_longitude": 0.0,
              "tmsetup_bearing": "n"}
    config = yaml.safe_load(render("container/node-red-tm/config/config.yml.j2", **values))
    config["thingsboard"] = {"enabled": True}
    config["deployment"] = {"lat": "north", "lon": "west", "bearing": "up"}
    [step] = run_functions([(defaults, {"payload": config})], env=TB_ENV)["results"]
    # The key each message names ("Node-RED config.yml key thingsboard.host needs ..."), and whether msg came with it
    errors = {text.split()[3]: with_msg for level, text, with_msg in step["logged"] if level == "error"}
    assert errors == {"thingsboard.host": True, "deployment.lat": False, "deployment.lon": False,
                      "deployment.bearing": False}
    assert step["result"]["payload"]["thingsboard"]["enabled"] is False


def new_device_config():
    """The config.yml a new device gets, with its coordinates set to 0.0 and its bearing to n."""
    values = {**load_role_yaml("defaults/main.yml"), "tmsetup_latitude": 0.0, "tmsetup_longitude": 0.0,
              "tmsetup_bearing": "n"}
    return yaml.safe_load(render("container/node-red-tm/config/config.yml.j2", **values))


def init_defaults_thingsboard(thingsboard, env):
    """Run init config defaults on a new device's config with this thingsboard section; returns it and the log."""
    config = new_device_config()
    config["thingsboard"] = thingsboard
    defaults = named(json.loads(FLOWS.read_text()), "init config defaults")
    [step] = run_functions([(defaults, {"payload": config})], env=env)["results"]
    return step["result"]["payload"]["thingsboard"], step["logged"]


@needs_node
@pytest.mark.parametrize("given, url", [
    ({"host": "tb.example.invalid"}, "https://tb.example.invalid"),
    ({"host": "tb.example.invalid", "protocol": ""}, "https://tb.example.invalid"),
    ({"host": "tb.example.invalid", "protocol": "http"}, "http://tb.example.invalid"),
    ({"host": "tb.example.invalid", "protocol": "https", "port": 8443}, "https://tb.example.invalid:8443"),
    ({"host": "http://tb.example.invalid", "protocol": "https"}, "http://tb.example.invalid"),
    ({"host": "HTTPS://tb.example.invalid"}, "HTTPS://tb.example.invalid"),
], ids=["default-https", "empty-protocol", "http", "port", "scheme-in-host-wins", "scheme-in-host-any-case"])
def test_thingsboard_url_honours_protocol(given, url):
    """The upload URL gets protocol's scheme, https when it's missing; a host that already has a scheme keeps it."""
    thingsboard, logged = init_defaults_thingsboard({"enabled": True, **given}, TB_ENV)
    assert thingsboard["url"] == url
    assert thingsboard["enabled"] is True
    assert logged == []


@needs_node
@pytest.mark.parametrize("host", ["", None], ids=["empty", "null"])
def test_thingsboard_with_an_empty_host_is_a_config_error(host):
    thingsboard, logged = init_defaults_thingsboard({"enabled": True, "host": host}, TB_ENV)
    assert [(level, text.split()[3], with_msg) for level, text, with_msg in logged] == [
        ("error", "thingsboard.host", True)]
    assert thingsboard["enabled"] is False


@needs_node
def test_thingsboard_is_off_without_a_token():
    thingsboard, logged = init_defaults_thingsboard({"enabled": True, "host": "tb.example.invalid"}, {})
    assert thingsboard["enabled"] is False
    [(level, text, _)] = logged
    assert level == "warn" and "TM_THINGSBOARD_ACCESS_TOKEN" in text
    thingsboard, logged = init_defaults_thingsboard({"enabled": False, "host": "tb.example.invalid"}, {})
    assert thingsboard["enabled"] is False
    assert logged == []


@needs_node
def test_thingsboard_switch_still_sees_http_for_https():
    """tb protocol? routes on http or mqtt, so the function still rewrites https after building the URL."""
    thingsboard, _ = init_defaults_thingsboard({"enabled": True, "host": "tb.example.invalid", "protocol": "https"},
                                               TB_ENV)
    assert thingsboard["protocol"] == "http"
    assert thingsboard["url"] == "https://tb.example.invalid"


def test_thingsboard_url_nodes_take_the_token_from_the_environment():
    """The token is rendered from Node-RED's environment by template nodes: an http request node's URL sees only msg."""
    flows = json.loads(FLOWS.read_text())
    by_id = {node["id"]: node for node in flows}
    for node in (by_id["9c944328e288b2dc"], by_id["d739b10ce5fa8f40"]):
        assert node["type"] == "template"
        assert (node["field"], node["fieldType"], node["syntax"]) == ("url", "msg", "mustache")
        assert "{{{env.TM_THINGSBOARD_ACCESS_TOKEN}}}" in node["template"]
        assert "{{{global.config.thingsboard.url}}}" in node["template"]


@needs_node
def test_plate_recognizer_token_comes_from_the_environment():
    flows = json.loads(FLOWS.read_text())
    by_id = {node["id"]: node for node in flows}
    msg = {"frigate_event": {"frame_time": 1761800000.5}, "frigate_event_api_thumbnail": "thumbnail"}
    context = {"config": {"addons": {"plate_recognizer": {"url": "http://plate-recognizer:8080"}}}}
    [step] = run_functions([(by_id["ce5360091646c733"], msg)], env={"TM_PLATE_RECOGNIZER_TOKEN": "pr-placeholder-0002"},
                           context=context)["results"]
    assert step["result"]["headers"]["Authorization"] == "Token pr-placeholder-0002"
    assert step["result"]["url"] == "http://plate-recognizer:8080/v1/plate-reader/"
    switch = by_id["5e642eb684a874ef"]
    assert (switch["propertyType"], switch["property"]) == ("env", "TM_PLATE_RECOGNIZER_TOKEN")
    assert switch["rules"] == [{"t": "nempty"}]
    assert switch["name"] == "is there a plate_recognizer token?"
    assert switch["wires"] == [["53d832d8012b843b"]]


def test_no_flow_reads_a_secret_from_config():
    for node in json.loads(FLOWS.read_text()):
        for key in ("func", "template", "url", "property"):
            text = str(node.get(key, ""))
            assert "access_token" not in text, (node["id"], key)
            assert "addons.plate_recognizer.token" not in text, (node["id"], key)


@needs_node
@pytest.mark.parametrize("given, expected, errors", [
    ({}, {"survey_id": None, "database_precision": "2"}, set()),
    ({"survey_id": "3f9a1c2e-si", "database_precision": "2"},
     {"survey_id": "3f9a1c2e-si", "database_precision": "2"}, set()),
    ({"survey_id": "3F9A1C2E-si"}, {"survey_id": "3f9a1c2e-si", "database_precision": "2"}, set()),
    ({"survey_id": "home"}, {"survey_id": None, "database_precision": "2"}, {"deployment.survey_id"}),
    ({"database_precision": "3"}, {"survey_id": None, "database_precision": "2"}, {"deployment.database_precision"}),
    ({"database_precision": 1}, {"survey_id": None, "database_precision": "1"}, set()),
    ({"database_precision": "none"}, {"survey_id": None, "database_precision": "none"}, set()),
    ({"database_precision": None}, {"survey_id": None, "database_precision": "2"}, set()),
], ids=["defaults", "both-set", "case-folded", "not-a-survey-id", "precision-3", "precision-yaml-number",
        "precision-none", "precision-blank"])
def test_init_config_defaults_survey_keys(given, expected, errors):
    """survey_id is a valid id or null, and database_precision is none, 1, or 2 (missing or invalid: the default, 2);
    a bad value is logged and dropped."""
    config = new_device_config()
    config["deployment"].update(given)
    defaults = named(json.loads(FLOWS.read_text()), "init config defaults")
    [step] = run_functions([(defaults, {"payload": config})])["results"]
    deployment = step["result"]["payload"]["deployment"]
    assert {key: deployment[key] for key in expected} == expected
    logged = [text for level, text, _ in step["logged"] if level == "error"]
    assert {text.split()[3] for text in logged} == errors
    assert all(text.endswith("using '2'") for text in logged if "database_precision" in text)


@needs_node
@pytest.mark.parametrize("coordinates", [
    {"lat": "", "lon": ""},
    {"lat": None, "lon": None},
    {},
    {"lat": "45.52252", "lon": "-122.69120"},
], ids=["empty", "null", "missing", "quoted-number"])
def test_init_config_defaults_allows_blank_coordinates(coordinates):
    """Blank coordinates mean no location yet, and a number quoted in YAML is still a number; neither is an error."""
    config = new_device_config()
    config["deployment"] = {"bearing": "", **coordinates}
    defaults = named(json.loads(FLOWS.read_text()), "init config defaults")
    [step] = run_functions([(defaults, {"payload": config})])["results"]
    assert [text for level, text, _ in step["logged"] if level == "error"] == []
    deployment = step["result"]["payload"]["deployment"]
    expected = {key: coordinates.get(key) or "" for key in ("lat", "lon")}
    assert {key: deployment[key] for key in ("lat", "lon")} == expected


MISSING = object()


@needs_node
@pytest.mark.parametrize("top, sensor, expected_top, expected_sensor, errors", [
    ("", None, "", "", []),
    (None, None, "", "", []),
    (MISSING, None, "", "", []),
    ("NE", None, "ne", "ne", []),
    ("up", None, "up", "up", ["top-level"]),
    ("n", {"bearing": ""}, "n", "", []),
    ("n", {"bearing": None}, "n", "", []),
    ("n", {}, "n", "n", []),
    (None, {}, "", "", []),
    (None, {"lat": 0.0}, "", "", []),
    (None, {"bearing": None}, "", "", []),
    ("n", {"bearing": "up"}, "n", "", ["sensor"]),
], ids=["top-empty", "top-null", "top-missing", "top-upper-case", "top-invalid", "sensor-empty", "sensor-null",
        "sensor-block-empty", "top-null-sensor-block-empty", "top-null-sensor-block", "both-null", "sensor-invalid"])
def test_init_config_defaults_allows_a_blank_bearing(top, sensor, expected_top, expected_sensor, errors):
    """A blank bearing means none yet, at the top level and per sensor; only a bearing that isn't one is an error."""
    config = new_device_config()
    if top is MISSING:
        del config["deployment"]["bearing"]
    else:
        config["deployment"]["bearing"] = top
    camera = config["sensors"]["cameras"]["picam_h265"]
    if sensor is not None:
        camera["deployment"] = sensor
    defaults = named(json.loads(FLOWS.read_text()), "init config defaults")
    [step] = run_functions([(defaults, {"payload": config})])["results"]
    logged = [text for level, text, _ in step["logged"] if level == "error"]
    assert ["top-level" if "top-level deployment.bearing" in text else "sensor" if text.startswith("Invalid bearing")
            else text for text in logged] == errors
    payload = step["result"]["payload"]
    assert payload["deployment"]["bearing"] == expected_top
    assert payload["sensors"]["cameras"]["picam_h265"]["deployment"]["bearing"] == expected_sensor


def test_config_template_has_the_survey_keys():
    """A new device starts with no survey and two decimal places stored; the Location page sets survey_id later."""
    deployment = new_device_config()["deployment"]
    assert deployment["database_precision"] == "2"
    assert "survey_id" in deployment and deployment["survey_id"] is None


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
    pickers = [node_id for node_id in by_id[SET_CONFIG]["wires"][0] if by_id[node_id]["type"] == "link out"]
    assert by_id[SET_CONFIG]["wires"] == [["ac8b2de05ec27001", loaded["id"], *pickers]] and len(pickers) == 1
    # A load that set global.config clears the upload's results: they were about the last load's server and token
    assert 'global.set("tm_status.upload", { last_ok_at: null, last_failure_at: null, last_failure: null });' in (
        loaded["func"])


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

    config = {"deployment": {"survey_id": None, "database_precision": "1", "lat": 0.0, "lon": 0.0, "bearing": "n"},
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
    assert body["deployment"] == {"survey_id": None, "database_precision": "1"}
    radars = body["radars"]
    assert sorted(radars) == RADAR_NAMES
    assert radars["TM_RADAR_SERIAL_PORT_00"]["enabled"] is True
    assert radars["TM_RADAR_SERIAL_PORT_00"]["port_open"] is True
    assert radars["TM_RADAR_SERIAL_PORT_00"]["last_reading_at"].endswith("Z")
    assert radars["TM_RADAR_SERIAL_PORT_01"] == {"enabled": False, "port_open": False, "last_reading_at": None}
    assert radars["TM_RADAR_SERIAL_PORT_02"]["port_open"] is False
    assert radars["TM_RADAR_SERIAL_PORT_03"] == {"enabled": False, "port_open": False, "last_reading_at": None}


RADAR_JUNCTION, RADAR_DIRECTOR = "05a58d9ee463c696", "e9bd400bfc06d988"  # where the hourly time sync goes
RADAR_REPLIES = "05e485cfcada03a3"  # where the radars' parsed lines pass


def test_a_reopened_radar_port_gets_the_time_through_the_radar_director():
    """A radar that lost power restarts its clock at zero, and its readings carry that clock's time. So when a port
    opens, the port-status node sends that radar the time, the way the hourly sync does, a few seconds later: while
    the port opens, Linux echoes the start of the radar's greeting back to it, and the radar drops a command that
    follows that echo within a moment (seen on a bench unit)."""
    flows = json.loads(FLOWS.read_text())
    by_id = {node["id"]: node for node in flows}
    port_status = named(flows, "tm-internal: radar port status")
    [[delay_id]] = port_status["wires"]
    delay = by_id[delay_id]
    assert (delay["type"], delay["pauseType"], delay["timeout"], delay["timeoutUnits"]) == (
        "delay", "delay", "5", "seconds")
    assert delay["z"] == port_status["z"] and delay["g"] == port_status["g"]
    assert delay_id in by_id[port_status["g"]]["nodes"]
    # The time is read after the delay, as the hourly sync reads it, so the radar isn't set 5 seconds behind.
    [[set_time_id]] = delay["wires"]
    set_time = by_id[set_time_id]
    hourly = named(flows, "init: sync radar time, every 60-min")
    assert set_time["type"] == "change" and set_time["g"] == port_status["g"]
    assert set_time["rules"] == [{"t": "set", "p": "payload", "pt": "msg", "to": hourly["payload"], "tot": "jsonata"}]
    assert set_time["wires"] == [[RADAR_JUNCTION]]
    assert by_id[RADAR_JUNCTION]["wires"] == [[RADAR_DIRECTOR]]
    assert hourly["wires"] == [[RADAR_JUNCTION]]


@needs_node
def test_a_reopened_radar_port_is_sent_the_time_only_when_enabled():
    """Only to an enabled radar: the radar director's "enabled?" switch sends anything for a disabled radar, or one
    whose config isn't loaded yet, on as PI (idle), which would idle a radar that's about to be set up."""
    flows = json.loads(FLOWS.read_text())
    port_status = named(flows, "tm-internal: radar port status")

    def port(serial_id, text):
        return (port_status, {"status": {"text": text, "source": {"id": serial_id, "type": "serial in"}}})

    config = {"sensors": {"radars": {"TM_RADAR_SERIAL_PORT_00": {"enabled": True},
                                     "TM_RADAR_SERIAL_PORT_01": {"enabled": False}}}}
    out = run_functions([
        port("926ac6db07adc540", "node-red:common.status.connected"),
        port("926ac6db07adc540", "node-red:common.status.not-connected"),
        port("917b8f4b46895cee", "node-red:common.status.connected"),
        port("9353b933e36e8b9e", "node-red:common.status.connected"),
    ], context={"config": config})
    opened, closed, disabled, unconfigured = (step["result"] for step in out["results"])
    assert opened == {"topic": "TM_RADAR_SERIAL_PORT_00"}  # the change node after the delay adds the time
    assert closed is None and disabled is None and unconfigured is None
    assert out["global"]["tm_status"]["radars"]["TM_RADAR_SERIAL_PORT_00"]["port_open"] is False
    # Before config.yml's first load, nothing is sent; startup's own time sync follows 30 seconds after the start.
    [early] = run_functions([port("926ac6db07adc540", "node-red:common.status.connected")])["results"]
    assert early["result"] is None


@needs_node
def test_a_radar_removed_from_the_config_is_no_longer_enabled():
    flows = json.loads(FLOWS.read_text())
    loaded = named(flows, "tm-internal: config loaded")
    before = {"sensors": {"radars": {"TM_RADAR_SERIAL_PORT_00": {"enabled": True}}}}
    after = {"deployment": {"survey_id": None, "database_precision": "none", "lat": None, "lon": None, "bearing": ""},
             "sensors": {"radars": {}}}
    out = run_functions([(loaded, {}), status_step()], context={"config": before})
    assert out["results"][1]["result"]["payload"]["radars"]["TM_RADAR_SERIAL_PORT_00"]["enabled"] is True
    out = run_functions([(loaded, {}), status_step()], context={**out["global"], "config": after})
    body = out["results"][1]["result"]["payload"]
    assert body["radars"]["TM_RADAR_SERIAL_PORT_00"]["enabled"] is False
    assert body["deployment"] == {"survey_id": None, "database_precision": "none"}


@needs_node
def test_config_loaded_records_the_survey_not_the_coordinates():
    """tm-control's status page shows which survey the device records and how finely, never the exact location."""
    flows = json.loads(FLOWS.read_text())
    loaded = named(flows, "tm-internal: config loaded")
    config = {"deployment": {"survey_id": "3f9a1c2e-si", "database_precision": "1", "lat": 45.52252,
                             "lon": -122.69120, "bearing": "n"},
              "sensors": {"radars": {}}}
    out = run_functions([(loaded, {}), status_step()], context={"config": config})
    assert out["global"]["tm_status"]["deployment"] == {"survey_id": "3f9a1c2e-si", "database_precision": "1"}
    assert out["results"][1]["result"]["payload"]["deployment"] == {"survey_id": "3f9a1c2e-si",
                                                                    "database_precision": "1"}


def test_no_init_config_node_puts_coordinates_in_tm_status():
    """tm_status.deployment holds the survey only. The engine's tm_status.deployments (the rounded tmdb rows) may
    hold coordinates."""
    flows = json.loads(FLOWS.read_text())
    tab = tab_id(flows, "init-config")
    offenders = [node["name"] for node in flows if node["type"] == "function" and node["z"] == tab
                 and re.search(r"tm_status\.deployment\b", node["func"]) and "lat" in node["func"]]
    assert offenders == []


def test_deployment_attribute_has_no_top_level_coordinates():
    """The deployments client attribute names the survey at the top level; only the per-sensor rows, which tmdb
    stores rounded, carry coordinates."""
    template = {node["id"]: node for node in json.loads(FLOWS.read_text())}["9b0f7197fe82bbfa"]["template"]
    for key in ("lat", "lon", "bearing"):
        assert f"global.config.deployment.{key}" not in template
    top = template[template.index('"deploymentTopLevel"'):]
    assert '"survey_id": "{{global.config.deployment.survey_id}}"' in top
    assert '"database_precision": "{{global.config.deployment.database_precision}}"' in top


# The deployment engine on init-config: after each config load it compares every enabled sensor's open deployment
# row with config.yml's survey id and that sensor's bearing, and writes the rows that start, end, or change.

ENGINE_SURVEY = "3f9a1c2e-si"
ENGINE_PLACE = {"survey_id": ENGINE_SURVEY, "database_precision": "1", "lat": 45.52252, "lon": -122.69120}
ENGINE_SQL = {
    "close deployment": "UPDATE deployment SET entryEndDateTime = $ended WHERE id = $id",
    "insert deployment": "INSERT INTO deployment (id, entryStartDateTime, lat, lon, bearing, sensorType, sensorName, "
                         "deviceName, survey_id, location_precision) VALUES ($id, $started, $lat, $lon, $bearing, "
                         "$sensorType, $sensorName, $deviceName, $survey_id, $location_precision)",
    "rewrite deployment": "UPDATE deployment SET survey_id = $survey_id, lat = $lat, lon = $lon, "
                          "location_precision = $location_precision, bearing = $bearing WHERE id = $id",
}
OPEN_ROWS_SQL = ("SELECT id, entryStartDateTime, lat, lon, bearing, sensorType, sensorName, deviceName, survey_id, "
                 "location_precision FROM deployment WHERE entryEndDateTime IS NULL "
                 "ORDER BY sensorType, sensorName, entryStartDateTime DESC;")
ROW_KEYS = {"id", "entryStartDateTime", "entryEndDateTime", "lat", "lon", "bearing", "sensorType", "sensorName",
            "deviceName", "survey_id", "location_precision"}


def engine_sensors(camera_deployment=None):
    camera_deployment = {"bearing": "n"} if camera_deployment is None else camera_deployment
    return {"cameras": {"picam_h265": {"enabled": True, "deployment": camera_deployment}},
            "radars": {"TM_RADAR_SERIAL_PORT_00": {"enabled": True, "deployment": {"bearing": "s"}},
                       "TM_RADAR_SERIAL_PORT_01": {"enabled": False}}}


def open_row(sensor_type, sensor_name, bearing, survey_id=ENGINE_SURVEY, lat=45.5, lon=-122.7, precision=1,
             started=10, row_id=None):
    """An open deployment row as the open-rows SELECT returns it."""
    return {"id": row_id or f"{started}-{sensor_name}-d",
            "entryStartDateTime": started, "lat": lat, "lon": lon, "bearing": bearing, "sensorType": sensor_type,
            "sensorName": sensor_name, "deviceName": "serial-1", "survey_id": survey_id,
            "location_precision": precision}


def camera_row(**kwargs):
    return open_row("cameras", "picam_h265", kwargs.pop("bearing", "n"), **kwargs)


def radar_row(**kwargs):
    return open_row("radars", "TM_RADAR_SERIAL_PORT_00", kwargs.pop("bearing", "s"), **kwargs)


class EngineRun:
    """One run of the engine: its four outputs as lists of messages, and the global context and log after it."""

    def __init__(self, out):
        [step] = out["results"]
        self.close, self.insert, self.rewrite, self.result = (
            [] if output is None else output if isinstance(output, list) else [output] for output in step["result"])
        self.global_context = out["global"]
        self.logged = step["logged"]

    @property
    def payload(self):
        [message] = self.result
        return message["payload"]

    def written(self):
        return self.close + self.insert + self.rewrite


def engine(sensors, open_rows, deployment, env=None):
    flows = json.loads(FLOWS.read_text())
    out = run_functions([(named(flows, "deployment engine"), {"sensors": sensors, "sqlActiveDeployments": open_rows})],
                        env={"TM_RPI_SN": "serial-1", **(env or {})},
                        context={"config": {"deployment": deployment, "sensors": sensors}})
    return EngineRun(out)


def deployment_ids(run):
    sensors = run.global_context["config"]["sensors"]
    return {name: sensor.get("deployment", {}).get("id") for kind in sensors.values() for name, sensor in kind.items()}


@needs_node
def test_engine_inserts_a_row_per_enabled_sensor_on_a_fresh_database():
    run = engine(engine_sensors(), [], ENGINE_PLACE)
    assert run.close == [] and run.rewrite == []
    params = {message["params"]["$sensorName"]: message["params"] for message in run.insert}
    assert set(params) == {"picam_h265", "TM_RADAR_SERIAL_PORT_00"}
    for name, bearing, sensor_type in [("picam_h265", "n", "cameras"), ("TM_RADAR_SERIAL_PORT_00", "s", "radars")]:
        row = params[name]
        assert {key: row[key] for key in ("$survey_id", "$lat", "$lon", "$location_precision", "$deviceName",
                                          "$bearing", "$sensorType")} == {
            "$survey_id": ENGINE_SURVEY, "$lat": 45.5, "$lon": -122.7, "$location_precision": 1,
            "$deviceName": "serial-1", "$bearing": bearing, "$sensorType": sensor_type}
        assert re.fullmatch(r"\d{13}-[0-9a-f]{8}-d", row["$id"])
        assert isinstance(row["$started"], int)
    current = run.payload["currentDeployment"]
    assert len(current) == 2 and all(set(row) == ROW_KEYS for row in current)
    assert run.payload["updatedDeployment"] == []
    assert deployment_ids(run) == {"picam_h265": params["picam_h265"]["$id"],
                                   "TM_RADAR_SERIAL_PORT_00": params["TM_RADAR_SERIAL_PORT_00"]["$id"],
                                   "TM_RADAR_SERIAL_PORT_01": None}
    assert run.global_context["tm_status"]["deployments"] == current


@needs_node
@pytest.mark.parametrize("precision", [MISSING, "3"], ids=["missing", "invalid"])
def test_engine_stores_two_decimals_without_a_valid_precision(precision):
    """The engine's own fallback matches init config defaults: about 1 km, two decimal places."""
    place = {key: value for key, value in ENGINE_PLACE.items() if key != "database_precision"}
    if precision is not MISSING:
        place["database_precision"] = precision
    run = engine(engine_sensors(), [], place)
    assert {(m["params"]["$lat"], m["params"]["$lon"], m["params"]["$location_precision"]) for m in run.insert} == {
        (45.52, -122.69, 2)}


@needs_node
def test_engine_leaves_matching_open_rows_alone():
    rows = [camera_row(), radar_row()]
    run = engine(engine_sensors(), rows, ENGINE_PLACE)
    assert run.written() == []
    assert run.payload["currentDeployment"] == [{**row, "entryEndDateTime": None} for row in rows]
    assert deployment_ids(run) == {"picam_h265": rows[0]["id"], "TM_RADAR_SERIAL_PORT_00": rows[1]["id"],
                                   "TM_RADAR_SERIAL_PORT_01": None}


@needs_node
def test_engine_adopts_an_open_row_without_a_survey():
    camera = camera_row(survey_id=None, lat=None, lon=None, precision=None)
    run = engine(engine_sensors(), [camera, radar_row()], ENGINE_PLACE)
    assert run.close == [] and run.insert == []
    assert [message["params"] for message in run.rewrite] == [
        {"$id": camera["id"], "$survey_id": ENGINE_SURVEY, "$lat": 45.5, "$lon": -122.7, "$location_precision": 1,
         "$bearing": "n"}]
    [current] = [row for row in run.payload["currentDeployment"] if row["id"] == camera["id"]]
    assert (current["survey_id"], current["lat"], current["lon"], current["location_precision"]) == (
        ENGINE_SURVEY, 45.5, -122.7, 1)


@needs_node
def test_engine_starts_a_deployment_on_a_new_survey_or_bearing():
    rows = [camera_row(survey_id="aaaaaaaa-si"), radar_row(bearing="e")]
    run = engine(engine_sensors(), rows, ENGINE_PLACE)
    assert {message["params"]["$id"] for message in run.close} == {row["id"] for row in rows}
    assert all(isinstance(message["params"]["$ended"], int) for message in run.close)
    assert {(m["params"]["$sensorName"], m["params"]["$survey_id"], m["params"]["$bearing"]) for m in run.insert} == {
        ("picam_h265", ENGINE_SURVEY, "n"), ("TM_RADAR_SERIAL_PORT_00", ENGINE_SURVEY, "s")}
    assert run.rewrite == []
    updated = run.payload["updatedDeployment"]
    assert {row["id"] for row in updated} == {row["id"] for row in rows}
    ended = {message["params"]["$id"]: message["params"]["$ended"] for message in run.close}
    assert all(row["entryEndDateTime"] == ended[row["id"]] for row in updated)
    assert {row["id"] for row in run.payload["currentDeployment"]} == {m["params"]["$id"] for m in run.insert}


@needs_node
def test_engine_adopts_only_when_the_bearing_matches():
    camera = camera_row(survey_id=None, bearing="w")
    run = engine(engine_sensors(), [camera, radar_row()], ENGINE_PLACE)
    assert [message["params"]["$id"] for message in run.close] == [camera["id"]]
    assert [message["params"]["$sensorName"] for message in run.insert] == ["picam_h265"]
    assert run.rewrite == []


@needs_node
def test_engine_never_compares_coordinates():
    run = engine(engine_sensors(), [camera_row(), radar_row()], {**ENGINE_PLACE, "lat": 45.6})
    assert run.written() == []


@needs_node
def test_engine_ignores_coordinates_under_a_sensor():
    sensors = engine_sensors({"bearing": "n", "lat": 40.0, "lon": -100.0})
    run = engine(sensors, [], ENGINE_PLACE)
    [camera] = [m["params"] for m in run.insert if m["params"]["$sensorName"] == "picam_h265"]
    assert (camera["$lat"], camera["$lon"]) == (45.5, -122.7)


@needs_node
def test_engine_lowers_precision_in_place_and_ignores_a_raise():
    rows = [camera_row(lat=45.52, lon=-122.69, precision=2), radar_row(lat=45.52, lon=-122.69, precision=2)]
    run = engine(engine_sensors(), rows, ENGINE_PLACE)
    assert run.close == [] and run.insert == []
    assert sorted((m["params"] for m in run.rewrite), key=lambda params: params["$id"]) == sorted(
        ({"$id": row["id"], "$survey_id": ENGINE_SURVEY, "$lat": 45.5, "$lon": -122.7, "$location_precision": 1,
          "$bearing": row["bearing"]} for row in rows), key=lambda params: params["$id"])
    run = engine(engine_sensors(), [camera_row(), radar_row()], {**ENGINE_PLACE, "database_precision": "2"})
    assert run.written() == []


@needs_node
@pytest.mark.parametrize("survey_id", [ENGINE_SURVEY, None], ids=["survey", "no-survey"])
def test_engine_lowers_precision_from_the_rows_own_coordinates(survey_id):
    """A lower precision re-rounds the row's own lat and lon and keeps its survey id, whatever config.yml says now."""
    camera = camera_row(lat=45.52, lon=-122.69, precision=2)
    place = {**ENGINE_PLACE, "survey_id": survey_id, "lat": 47.0, "lon": -120.0}
    run = engine(engine_sensors(), [camera, radar_row()], place)
    assert run.close == [] and run.insert == []
    assert [m["params"] for m in run.rewrite] == [
        {"$id": camera["id"], "$survey_id": ENGINE_SURVEY, "$lat": 45.5, "$lon": -122.7, "$location_precision": 1,
         "$bearing": "n"}]
    rows = [camera_row(), radar_row()]
    run = engine(engine_sensors(), rows, {**place, "database_precision": "none"})
    assert run.close == [] and run.insert == []
    assert sorted((m["params"] for m in run.rewrite), key=lambda params: params["$id"]) == sorted(
        ({"$id": row["id"], "$survey_id": ENGINE_SURVEY, "$lat": None, "$lon": None, "$location_precision": None,
          "$bearing": row["bearing"]} for row in rows), key=lambda params: params["$id"])


@needs_node
@pytest.mark.parametrize("place", [
    {**ENGINE_PLACE, "database_precision": "none"},
    {**ENGINE_PLACE, "lat": ""},
    {**ENGINE_PLACE, "lon": ""},
    {**ENGINE_PLACE, "lat": None, "lon": None},
], ids=["precision-none", "lat-blank", "lon-blank", "both-null"])
def test_engine_stores_null_for_none_or_missing_coordinates(place):
    """Review Focus 4: a half-blank location stores no coordinates at all, and no precision."""
    run = engine(engine_sensors(), [], place)
    assert len(run.insert) == 2
    assert all((m["params"]["$lat"], m["params"]["$lon"], m["params"]["$location_precision"]) == (None, None, None)
               for m in run.insert)
    assert [text for level, text, _ in run.logged if level == "error"] == []


@needs_node
def test_engine_without_a_survey_id_creates_missing_rows_and_closes_nothing():
    camera = camera_row(survey_id="aaaaaaaa-si", bearing="w")
    run = engine(engine_sensors(), [camera], {**ENGINE_PLACE, "survey_id": None})
    assert run.close == [] and run.rewrite == []
    assert [(m["params"]["$sensorName"], m["params"]["$survey_id"]) for m in run.insert] == [
        ("TM_RADAR_SERIAL_PORT_00", None)]
    assert camera["id"] in {row["id"] for row in run.payload["currentDeployment"]}


@needs_node
def test_engine_rounds_string_coordinates():
    """Review Focus 1: a coordinate quoted in YAML arrives as a string and is stored as the rounded number."""
    run = engine(engine_sensors(), [], {**ENGINE_PLACE, "lat": "45.52252", "lon": "-122.69120"})
    assert {(m["params"]["$lat"], m["params"]["$lon"], m["params"]["$location_precision"]) for m in run.insert} == {
        (45.5, -122.7, 1)}
    run = engine(engine_sensors(), [], {**ENGINE_PLACE, "lat": "north"})
    assert {(m["params"]["$lat"], m["params"]["$lon"], m["params"]["$location_precision"]) for m in run.insert} == {
        (None, None, None)}
    errors = [text for level, text, _ in run.logged if level == "error"]
    assert len(errors) == 1 and "deployment.lat" in errors[0]


@needs_node
def test_engine_rounds_halves_away_from_zero():
    """As SQLite's ROUND does in the migration; JavaScript's Math.round would give -122.2."""
    run = engine(engine_sensors(), [], {**ENGINE_PLACE, "lat": 45.25, "lon": -122.25})
    assert {(m["params"]["$lat"], m["params"]["$lon"]) for m in run.insert} == {(45.3, -122.3)}


@needs_node
@pytest.mark.parametrize("survey_id", [ENGINE_SURVEY, None], ids=["survey", "no-survey"])
def test_engine_closes_duplicate_open_rows(survey_id):
    """Review Focus 2: two open rows for one sensor (left by the old engine) leave one, the newest, open."""
    older, newer = camera_row(started=10, row_id="10-00000001-d"), camera_row(started=20, row_id="20-00000002-d")
    run = engine(engine_sensors(), [older, newer, radar_row()], {**ENGINE_PLACE, "survey_id": survey_id})
    assert [message["params"]["$id"] for message in run.close] == [older["id"]]
    assert run.insert == [] and run.rewrite == []
    assert newer["id"] in {row["id"] for row in run.payload["currentDeployment"]}
    assert older["id"] not in {row["id"] for row in run.payload["currentDeployment"]}
    assert [row["id"] for row in run.payload["updatedDeployment"]] == [older["id"]]


@needs_node
def test_engine_skips_disabled_sensors():
    disabled = open_row("radars", "TM_RADAR_SERIAL_PORT_01", "e", survey_id="aaaaaaaa-si")
    run = engine(engine_sensors(), [camera_row(), radar_row(), disabled], ENGINE_PLACE)
    assert run.written() == []
    assert disabled["id"] not in {row["id"] for row in run.payload["currentDeployment"]}


@needs_node
def test_engine_closes_the_row_of_a_sensor_that_left_the_file():
    gone = open_row("cameras", "main_st", "n")
    run = engine(engine_sensors(), [camera_row(), radar_row(), gone], ENGINE_PLACE)
    assert [c["params"]["$id"] for c in run.close] == [gone["id"]] and run.insert == []
    assert gone["id"] in {row["id"] for row in run.payload["updatedDeployment"]}
    assert gone["id"] not in {row["id"] for row in run.payload["currentDeployment"]}


@needs_node
@pytest.mark.parametrize("sensors", [None, "broken"])
def test_engine_closes_nothing_without_a_sensors_object(sensors):
    assert engine(sensors, [camera_row()], ENGINE_PLACE).written() == []


@needs_node
def test_engine_closes_an_empty_blocks_rows_and_keeps_an_empty_entrys_row():
    """`cameras:` with nothing under it lists no camera; `main_st:` with nothing under it is a camera that is off."""
    radars = engine_sensors()["radars"]
    run = engine({"cameras": None, "radars": radars}, [camera_row(), radar_row()], ENGINE_PLACE)
    assert [c["params"]["$id"] for c in run.close] == [camera_row()["id"]] and run.insert == []
    off = open_row("cameras", "main_st", "n")
    run = engine({"cameras": {"picam_h265": {"enabled": True, "deployment": {"bearing": "n"}}, "main_st": None},
                  "radars": radars}, [camera_row(), radar_row(), off], ENGINE_PLACE)
    assert run.written() == []
    assert [text for level, text, _ in run.logged if level == "error"] == []


@needs_node
@pytest.mark.parametrize("row_bearing, sensor_bearing",
                         [(None, ""), ("", ""), ("N", "n"), ("n", "N"), ("null", ""), ("undefined", None),
                          (" NULL ", ""), ("Undefined", "null")],
                         ids=["null-row", "blank", "upper-case-row", "upper-case-config", "null-string-row",
                              "undefined-string-row", "padded-upper-case-null-row", "null-string-config"])
def test_engine_treats_blank_and_upper_case_bearings_as_equal(row_bearing, sensor_bearing):
    """Releases 0.6.0 to 0.7.1 stored a blank bearing as the string 'null' (or 'undefined')."""
    rows = [camera_row(bearing=row_bearing), radar_row()]
    run = engine(engine_sensors({"bearing": sensor_bearing}), rows, ENGINE_PLACE)
    assert run.close == [] and run.insert == []
    legacy = (row_bearing or "").strip().lower() in ("null", "undefined")  # stored as '' once; see the next test
    assert [m["params"]["$id"] for m in run.rewrite] == ([rows[0]["id"]] if legacy else [])


@needs_node
@pytest.mark.parametrize("survey_id", [ENGINE_SURVEY, None], ids=["survey", "no-survey"])
@pytest.mark.parametrize("row_bearing", ["null", "undefined", " NULL "])
def test_engine_stores_a_legacy_blank_bearing_as_blank(survey_id, row_bearing):
    """An open row keeps its deployment, and its 'null' or 'undefined' bearing is written back as ''."""
    camera = camera_row(bearing=row_bearing)
    run = engine(engine_sensors({"bearing": ""}), [camera, radar_row()], {**ENGINE_PLACE, "survey_id": survey_id})
    assert run.close == [] and run.insert == []
    assert [m["params"] for m in run.rewrite] == [
        {"$id": camera["id"], "$survey_id": ENGINE_SURVEY, "$lat": 45.5, "$lon": -122.7, "$location_precision": 1,
         "$bearing": ""}]
    [current] = [row for row in run.payload["currentDeployment"] if row["id"] == camera["id"]]
    assert current["bearing"] == ""
    again = engine(engine_sensors({"bearing": ""}), [{**camera, "bearing": ""}, radar_row()],
                   {**ENGINE_PLACE, "survey_id": survey_id})
    assert again.written() == []


@needs_node
@pytest.mark.parametrize("row_bearing", ["null", "undefined"])
def test_engine_adopts_a_row_with_a_legacy_blank_bearing(row_bearing):
    rows = [camera_row(bearing=row_bearing, survey_id=None), radar_row()]
    run = engine(engine_sensors({"bearing": ""}), rows, ENGINE_PLACE)
    assert run.close == [] and run.insert == []
    assert [(m["params"]["$id"], m["params"]["$survey_id"], m["params"]["$bearing"]) for m in run.rewrite] == [
        (rows[0]["id"], ENGINE_SURVEY, "")]


def test_engine_wiring():
    flows = json.loads(FLOWS.read_text())
    by_id = {node["id"]: node for node in flows}
    engine_node = named(flows, "deployment engine")
    assert engine_node["z"] == tab_id(flows, "init-config")
    assert engine_node["outputs"] == 4
    assert "node.send" not in engine_node["func"] and "node.done" not in engine_node["func"]
    for output, name in zip(engine_node["wires"][:3], ENGINE_SQL):
        [target] = [by_id[node_id] for node_id in output]
        assert (target["type"], target["name"], target["sqlquery"], target["mydb"]) == ("sqlite", name, "prepared",
                                                                                         TMDB)
        assert target["z"] == engine_node["z"]
        assert " ".join(target["sql"].split()).rstrip(";") == ENGINE_SQL[name]
    assert engine_node["wires"][3] == ["05c37560dd57ea90"]
    assert "24efdc7f1231f7f0" not in by_id and "bc398ad5de3bd112" not in by_id
    assert " ".join(by_id["696c3a7b0b83f7b5"]["template"].split()) == OPEN_ROWS_SQL
    assert by_id["6d2f607b324415b4"]["wires"] == [[engine_node["id"]]]
    group = by_id[engine_node["g"]]
    assert set(group["nodes"]) >= {target_id for output in engine_node["wires"] for target_id in output}
    assert not {"24efdc7f1231f7f0", "bc398ad5de3bd112"} & set(group["nodes"])


# The camera pickers on the two dashboards: each tab's change node sets the options and the selection, and its
# dropdown shows them. A start-up inject fills them once, and each config load fills them again.

PICKERS = {  # tab: (start-up inject, change node, dropdown, the options property)
    "ui-monitoring": ("e3b795e05d7650b2", "f50a7968e032532a", "bb08a223f0aaef0f", "options"),
    "Dashboard 2 - Monitoring": ("22bc03eebc06aa57", "2e49ae46131b1b63", "3132d36d148e80d2", "ui_update.options"),
}


def test_the_pickers_refill_on_every_config_load():
    flows = json.loads(FLOWS.read_text())
    by_id = {node["id"]: node for node in flows}
    [link_out] = [by_id[node_id] for node_id in by_id[SET_CONFIG]["wires"][0] if by_id[node_id]["type"] == "link out"]
    assert link_out["z"] == tab_id(flows, "init-config") and link_out["mode"] == "link"
    assert link_out["id"] in by_id[link_out["g"]]["nodes"]
    links_in = [by_id[node_id] for node_id in link_out["links"]]
    assert sorted(link_in["z"] for link_in in links_in) == sorted(tab_id(flows, tab) for tab in PICKERS)
    for tab, (inject, change, dropdown, _) in PICKERS.items():
        [link_in] = [node for node in links_in if node["z"] == tab_id(flows, tab)]
        assert link_in["type"] == "link in" and link_in["links"] == [link_out["id"]]
        assert link_in["wires"] == [[change]]
        assert link_in["id"] in by_id[by_id[change]["g"]]["nodes"]
        assert change in by_id[inject]["wires"][0]  # the start-up fill stays
        assert dropdown in by_id[change]["wires"][0]
    for node_id in [link_out["id"], *link_out["links"]]:
        assert re.fullmatch(r"[0-9a-f]{16}", node_id)


def test_the_pickers_keep_a_selection_that_is_still_there_and_label_from_camera_labels():
    flows = json.loads(FLOWS.read_text())
    by_id = {node["id"]: node for node in flows}
    for tab, (_, change, _, options_property) in PICKERS.items():
        rules = {rule["p"]: rule for rule in by_id[change]["rules"]}
        assert set(rules) == {"payload", options_property}
        assert all(rule["t"] == "set" and rule["pt"] == "msg" and rule["tot"] == "jsonata" for rule in rules.values())
        # the selection: the tab's own, while camera_labels still lists it; else the file's first camera
        payload = rules["payload"]["to"]
        assert '$flowContext("camera_selection")' in payload and '$keys($globalContext("camera_labels"))' in payload
        assert '$keys($globalContext("config.sensors.cameras"))[0]' in payload
        # the options: one per camera_labels entry, labelled from it, valued with the key, and always a list
        options = " ".join(rules[options_property]["to"].split())
        assert options.startswith("[") and options.endswith("]")
        assert '$each($globalContext("camera_labels"), function($label, $key)' in options
        assert "config.sensors.cameras" not in options

    def options_of(tab):
        _, change, _, options_property = PICKERS[tab]
        [rule] = [rule for rule in by_id[change]["rules"] if rule["p"] == options_property]
        return " ".join(rule["to"].split())

    assert "{ $label: $key }" in options_of("ui-monitoring")  # ui_dropdown: {<label>: <value>}
    assert '{ "label": $label, "value": $key }' in options_of("Dashboard 2 - Monitoring")  # ui-dropdown


RADAR_PICKERS = {  # tab: (radar change node, radar dropdown)
    "ui-monitoring": ("59d0c8b142295eee", "62c9240d45e9c8d6"),
    "Dashboard 2 - Monitoring": ("f3ebd7067c32beb0", "95215b45c821d24a"),
}


def test_the_radar_pickers_keep_a_selection_that_is_still_there():
    """Only the camera change node feeds a tab's radar change node (at start-up and on each config load; a viewer's
    camera choice doesn't), so a radar the file still lists stays selected, else the camera's camera_radar."""
    flows = json.loads(FLOWS.read_text())
    by_id = {node["id"]: node for node in flows}
    for tab, (radar_change, radar_dropdown) in RADAR_PICKERS.items():
        camera_change = PICKERS[tab][1]
        feeds = {node["id"] for node in flows if any(radar_change in output for output in node.get("wires", []))}
        assert feeds == {camera_change}
        assert sorted(by_id[camera_change]["wires"][0]) == sorted([PICKERS[tab][2], radar_change])
        assert radar_dropdown in by_id[radar_change]["wires"][0]
        [payload] = [rule for rule in by_id[radar_change]["rules"] if rule["p"] == "payload"]
        assert (payload["t"], payload["pt"], payload["tot"]) == ("set", "msg", "jsonata")
        assert '$flowContext("radar_selection")' in payload["to"]
        assert '$keys($globalContext("config.sensors.radars"))' in payload["to"]
        assert '$globalContext("config.sensors.cameras." & payload & ".camera_radar")' in payload["to"]


# The per-survey endpoints tm-control calls on loopback, each behind its own copy of the status endpoint's token check.

STATUS_TOKEN_CHECK = "cbc268130cc14c58"
TM_INTERNAL_PATHS = {"/tm-internal/status", "/tm-internal/deployments", "/tm-internal/surveys/usage",
                     "/tm-internal/surveys/:id/events", "/tm-internal/deployments/precision",
                     "/tm-internal/surveys/:id/location", "/tm-internal/deployments/:id/bearing"}
TM_INTERNAL_METHODS = {"/tm-internal/status": "get", "/tm-internal/deployments": "get",
                       "/tm-internal/surveys/usage": "get", "/tm-internal/surveys/:id/events": "get",
                       "/tm-internal/deployments/precision": "post",
                       "/tm-internal/surveys/:id/location": "post", "/tm-internal/deployments/:id/bearing": "post"}
SURVEY_SQL = {
    "/tm-internal/deployments": ("read survey deployments",
                                 "SELECT id, entryStartDateTime, entryEndDateTime, lat, lon, bearing, sensorType, "
                                 "sensorName, survey_id, location_precision FROM deployment WHERE survey_id = "
                                 "$survey_id ORDER BY entryStartDateTime"),
    "/tm-internal/surveys/usage": ("read survey usage",
                                   "SELECT survey_id, MIN(entryStartDateTime) AS first_start, MAX(entryEndDateTime) "
                                   "AS last_end, SUM(entryEndDateTime IS NULL) AS open_count, COUNT(*) AS "
                                   "deployment_count FROM deployment GROUP BY survey_id"),
    "/tm-internal/surveys/:id/events": ("read survey events",
                                        "SELECT COUNT(*) AS event_count, MIN(start_time) AS first_event, "
                                        "MAX(start_time) AS last_event FROM events WHERE deployment_id IN (SELECT id "
                                        "FROM deployment WHERE survey_id = $survey_id)"),
}
PRECISION_SQL = {
    "rewrite precision": "UPDATE deployment SET lat = ROUND(lat, $p), lon = ROUND(lon, $p), location_precision = $p "
                         "WHERE location_precision > $p",
    "rewrite precision to none": "UPDATE deployment SET lat = NULL, lon = NULL, location_precision = NULL "
                                 "WHERE lat IS NOT NULL OR lon IS NOT NULL",
}
VALIDATORS = {"/tm-internal/deployments": "tm-internal: validate survey query",
              "/tm-internal/surveys/:id/location": "tm-internal: validate location correction",
              "/tm-internal/deployments/:id/bearing": "tm-internal: validate bearing correction",
              "/tm-internal/surveys/:id/events": "tm-internal: validate survey path",
              "/tm-internal/deployments/precision": "tm-internal: validate precision"}


def tm_internal_endpoints():
    flows = json.loads(FLOWS.read_text())
    endpoints = {node["url"]: node for node in flows
                 if node["type"] == "http in" and node.get("url", "").startswith("/tm-internal/")}
    return flows, {node["id"]: node for node in flows}, endpoints


def reachable(by_id, start_ids):
    """Every node a message can reach from start_ids, following wires."""
    seen, todo = set(), list(start_ids)
    while todo:
        node_id = todo.pop()
        if node_id not in seen:
            seen.add(node_id)
            todo.extend(target for output in by_id[node_id].get("wires", []) for target in output)
    return [by_id[node_id] for node_id in seen]


def sql_text(node):
    return " ".join(node["sql"].split()).rstrip(";")


def test_every_tm_internal_endpoint_checks_the_token_first():
    flows, by_id, endpoints = tm_internal_endpoints()
    assert set(endpoints) == TM_INTERNAL_PATHS
    for url, endpoint in endpoints.items():
        assert endpoint["method"] == TM_INTERNAL_METHODS[url], url
        assert endpoint["z"] == tab_id(flows, "init-config"), url
        [[check_id]] = endpoint["wires"]
        check = by_id[check_id]
        assert check["type"] == "function" and check["outputs"] == 2, url
        assert check["name"] == "tm-internal: check token", url
        assert check["func"] == by_id[STATUS_TOKEN_CHECK]["func"], url
        refused = reachable(by_id, check["wires"][1])
        assert [(node["type"], str(node["statusCode"])) for node in refused] == [("http response", "401")], url


def test_refused_requests_reach_no_sql():
    """Review Focus 5: a request without the token, or with a malformed value, answers before any sqlite node."""
    _, by_id, endpoints = tm_internal_endpoints()
    for url in TM_INTERNAL_PATHS - {"/tm-internal/status"}:
        [[check_id]] = endpoints[url]["wires"]
        refusals = list(by_id[check_id]["wires"][1])
        if url in VALIDATORS:
            [validate_id] = by_id[check_id]["wires"][0]
            validator = by_id[validate_id]
            assert (validator["type"], validator["name"], validator["outputs"]) == ("function", VALIDATORS[url], 2)
            refusals += validator["wires"][1]
            bad = reachable(by_id, validator["wires"][1])
            assert [(node["type"], str(node["statusCode"])) for node in bad] == [("http response", "400")], url
        assert [node["type"] for node in reachable(by_id, refusals) if node["type"] != "http response"] == [], url


@pytest.mark.parametrize("url", sorted(SURVEY_SQL))
def test_survey_reads_run_one_prepared_statement(url):
    _, by_id, endpoints = tm_internal_endpoints()
    [[check_id]] = endpoints[url]["wires"]
    [[before_id], _] = by_id[check_id]["wires"]
    [[query_id]] = by_id[before_id]["wires"][:1]
    query = by_id[query_id]
    name, sql = SURVEY_SQL[url]
    assert (query["type"], query["name"], query["sqlquery"], query["mydb"]) == ("sqlite", name, "prepared", TMDB)
    assert sql_text(query) == sql
    [[shape_id]] = query["wires"]
    [[answer_id]] = by_id[shape_id]["wires"]
    assert by_id[shape_id]["type"] == "function"
    assert (by_id[answer_id]["type"], by_id[answer_id]["statusCode"]) == ("http response", "")


def test_precision_rewrite_uses_two_statements():
    _, by_id, endpoints = tm_internal_endpoints()
    [[check_id]] = endpoints["/tm-internal/deployments/precision"]["wires"]
    [[validate_id], _] = by_id[check_id]["wires"]
    [[switch_id]] = by_id[validate_id]["wires"][:1]
    switch = by_id[switch_id]
    assert (switch["type"], switch["property"], switch["propertyType"]) == ("switch", "precision_none", "msg")
    assert [rule["t"] for rule in switch["rules"]] == ["false", "true"]
    queries = [by_id[target] for [target] in switch["wires"]]
    assert [node["name"] for node in queries] == list(PRECISION_SQL)
    shapes = set()
    for query in queries:
        assert (query["type"], query["sqlquery"], query["mydb"]) == ("sqlite", "prepared", TMDB)
        assert sql_text(query) == PRECISION_SQL[query["name"]]
        [[shape_id]] = query["wires"]
        shapes.add(shape_id)
    [shape_id] = shapes
    [[answer_id]] = by_id[shape_id]["wires"]
    assert (by_id[answer_id]["type"], by_id[answer_id]["statusCode"]) == ("http response", "")


def test_survey_endpoints_sit_with_the_status_endpoint():
    flows, by_id, endpoints = tm_internal_endpoints()
    status_group = by_id[endpoints["/tm-internal/status"]["g"]]
    new = reachable(by_id, [endpoints[url]["id"] for url in TM_INTERNAL_PATHS - {"/tm-internal/status"}])
    groups = {node["g"] for node in new}
    assert len(groups) == 1
    [group_id] = groups
    assert by_id[group_id]["g"] == status_group["id"] and group_id in status_group["nodes"]
    assert set(by_id[group_id]["nodes"]) >= {node["id"] for node in new}


SURVEY_ID = "3f9a1c2e-si"


def bad_request(detail):
    return {"error": "bad_request", "detail": detail}


@needs_node
@pytest.mark.parametrize("name, msg, ok", [
    ("tm-internal: validate survey query", {"req": {"query": {"survey_id": "3f9a1c2e-si"}}}, True),
    ("tm-internal: validate survey query", {"req": {"query": {"survey_id": "x' OR 1=1"}}}, False),
    ("tm-internal: validate survey query", {"req": {"query": {"survey_id": "3F9A1C2E-si"}}}, False),
    ("tm-internal: validate survey query", {"req": {"query": {"survey_id": ["3f9a1c2e-si", "3f9a1c2e-si"]}}}, False),
    ("tm-internal: validate survey query", {"req": {"query": {}}}, False),
    ("tm-internal: validate survey path", {"req": {"params": {"id": "3f9a1c2e-si"}}}, True),
    ("tm-internal: validate survey path", {"req": {"params": {"id": "3f9a1c2e"}}}, False),
    ("tm-internal: validate survey path", {"req": {"params": {"id": "3f9a1c2e-si "}}}, False),
    ("tm-internal: validate precision", {"req": {}, "payload": {"precision": "2"}}, True),
    ("tm-internal: validate precision", {"req": {}, "payload": {"precision": "1"}}, True),
    ("tm-internal: validate precision", {"req": {}, "payload": {"precision": "none"}}, True),
    ("tm-internal: validate precision", {"req": {}, "payload": {"precision": "3"}}, False),
    ("tm-internal: validate precision", {"req": {}, "payload": {"precision": 2}}, False),
    ("tm-internal: validate precision", {"req": {}, "payload": {"precision": "None"}}, False),
    ("tm-internal: validate precision", {"req": {}, "payload": "precision=2"}, False),
    ("tm-internal: validate precision", {"req": {}, "payload": {}}, False),
])
def test_tm_internal_validators(name, msg, ok):
    validator = named(json.loads(FLOWS.read_text()), name)
    [step] = run_functions([(validator, msg)])["results"]
    passed, refused = step["result"]
    if not ok:
        assert passed is None
        detail = "precision" if name == "tm-internal: validate precision" else "survey_id"
        assert refused["statusCode"] == 400 and refused["payload"] == bad_request(detail)
        return
    assert refused is None
    if name == "tm-internal: validate precision":
        given = msg["payload"]["precision"]
        if given == "none":
            assert passed["params"] == {} and passed["precision_none"] is True
        else:
            assert passed["params"] == {"$p": int(given)} and passed["precision_none"] is False
    else:
        assert passed["params"] == {"$survey_id": SURVEY_ID}


@needs_node
def test_survey_usage_binds_no_parameters():
    """A prepared sqlite node refuses a message without msg.params, and the usage request has nothing to bind."""
    _, by_id, endpoints = tm_internal_endpoints()
    [[check_id]] = endpoints["/tm-internal/surveys/usage"]["wires"]
    [[params_id], _] = by_id[check_id]["wires"]
    [step] = run_functions([(by_id[params_id], {"req": {}, "payload": {}})])["results"]
    assert step["result"]["params"] == {}


def shape(url):
    _, by_id, endpoints = tm_internal_endpoints()
    [[check_id]] = endpoints[url]["wires"]
    for node in reachable(by_id, [check_id]):
        if node["type"] == "function" and any(by_id[t]["type"] == "http response" and by_id[t]["statusCode"] == ""
                                              for output in node["wires"] for t in output):
            return node
    raise AssertionError(url)


DEPLOYMENT_ROW = {"id": "1761800000000-0a1b2c3d-d", "entryStartDateTime": "2026-10-30T12:00:00.000Z",
                  "entryEndDateTime": None, "lat": 45.5, "lon": -122.7, "bearing": "n", "sensorType": "camera",
                  "sensorName": "picam_h265", "survey_id": SURVEY_ID, "location_precision": 1}


@needs_node
@pytest.mark.parametrize("rows", [[DEPLOYMENT_ROW], []], ids=["rows", "none"])
def test_deployments_answer(rows):
    msg = {"params": {"$survey_id": SURVEY_ID}, "payload": rows}
    [step] = run_functions([(shape("/tm-internal/deployments"), msg)])["results"]
    assert step["result"]["payload"] == {"deployments": rows}
    assert step["result"].get("statusCode") in (None, 200)


@needs_node
@pytest.mark.parametrize("rows", [
    [{"survey_id": SURVEY_ID, "first_start": "2026-10-30T12:00:00.000Z", "last_end": None, "open_count": 2,
      "deployment_count": 3}],
    [],
], ids=["rows", "none"])
def test_survey_usage_answer(rows):
    msg = {"params": {}, "payload": rows}
    [step] = run_functions([(shape("/tm-internal/surveys/usage"), msg)])["results"]
    assert step["result"]["payload"] == {"surveys": rows}


@needs_node
@pytest.mark.parametrize("row, expected", [
    ({"event_count": 12, "first_event": 1761800000.5, "last_event": 1761890000.25},
     {"event_count": 12, "first_event": 1761800000.5, "last_event": 1761890000.25}),
    ({"event_count": 0, "first_event": None, "last_event": None},
     {"event_count": 0, "first_event": None, "last_event": None}),
], ids=["events", "no-events"])
def test_survey_events_answer(row, expected):
    msg = {"params": {"$survey_id": SURVEY_ID}, "req": {"params": {"id": SURVEY_ID}}, "payload": [row]}
    [step] = run_functions([(shape("/tm-internal/surveys/:id/events"), msg)])["results"]
    assert step["result"]["payload"] == {"survey_id": SURVEY_ID, **expected}


@needs_node
@pytest.mark.parametrize("params", [{"$p": 1}, {}], ids=["rounded", "none"])
def test_precision_rewrite_answers_204(params):
    msg = {"params": params, "precision_none": params == {}, "payload": []}
    [step] = run_functions([(shape("/tm-internal/deployments/precision"), msg)])["results"]
    assert step["result"]["statusCode"] == 204 and step["result"]["payload"] == ""


def test_database_errors_answer_500():
    """A failed query must still answer, or tm-control waits for a reply that never comes."""
    flows, by_id, endpoints = tm_internal_endpoints()
    queries = {node["id"] for node in reachable(by_id, [endpoints[url]["id"] for url in TM_INTERNAL_PATHS])
               if node["type"] == "sqlite"}
    assert len(queries) == 7
    [catch] = [node for node in flows if node["type"] == "catch" and set(node.get("scope") or []) & queries]
    assert set(catch["scope"]) == queries
    answers = [node for node in reachable(by_id, [catch["id"]]) if node["type"] == "http response"]
    assert [str(node["statusCode"]) for node in answers] == ["500"]


def test_flows_json_round_trips_through_json_dumps():
    """Pins the serialisation every flows.json edit relies on: Node-RED's own, 4 spaces, no trailing newline."""
    text = FLOWS.read_text()
    assert text == json.dumps(json.loads(text), indent=4, ensure_ascii=False)


def test_tm_internal_correction_endpoints_exist():
    flows, by_id, endpoints = tm_internal_endpoints()
    for url in ("/tm-internal/surveys/:id/location", "/tm-internal/deployments/:id/bearing"):
        assert endpoints[url]["method"] == "post", url
        [[check_id]] = endpoints[url]["wires"]
        assert by_id[check_id]["name"] == "tm-internal: check token", url


LOCATION_SQL = ("UPDATE deployment SET lat = ROUND($lat, location_precision), "
                "lon = ROUND($lon, location_precision) WHERE survey_id = $survey_id "
                "AND location_precision IS NOT NULL")


def correction_chain(url):
    """The validator, the prepared statement, and the answer of a correction endpoint."""
    _, by_id, endpoints = tm_internal_endpoints()
    [[check_id]] = endpoints[url]["wires"]
    [[validate_id], _] = by_id[check_id]["wires"]
    [[query_id], _] = by_id[validate_id]["wires"]
    [[answer_id]] = by_id[query_id]["wires"]
    return by_id[validate_id], by_id[query_id], by_id[answer_id], by_id[answer_id]["wires"][0][0], by_id


def test_correction_chains_run_one_prepared_statement_and_answer_204():
    for url, name, sql in (("/tm-internal/surveys/:id/location", "re-round survey coordinates", LOCATION_SQL),
                           ("/tm-internal/deployments/:id/bearing", "rewrite deployment bearing",
                            "UPDATE deployment SET bearing = $bearing WHERE id = $id")):
        validator, query, answer, response_id, by_id = correction_chain(url)
        assert validator["outputs"] == 2
        assert (query["type"], query["name"], query["sqlquery"], query["mydb"]) == ("sqlite", name, "prepared", TMDB)
        assert sql_text(query) == sql
        assert (by_id[response_id]["type"], by_id[response_id]["statusCode"]) == ("http response", "")


@needs_node
@pytest.mark.parametrize("answer_url", ["/tm-internal/surveys/:id/location", "/tm-internal/deployments/:id/bearing"])
def test_correction_answers_204(answer_url):
    _, _, answer, *_ = correction_chain(answer_url)
    [step] = run_functions([(answer, {"params": {}, "payload": []})])["results"]
    assert step["result"]["statusCode"] == 204 and step["result"]["payload"] == ""


def location_msg(survey_id, body):
    return {"req": {"params": {"id": survey_id}}, "payload": body}


@needs_node
@pytest.mark.parametrize("survey_id, body, detail", [
    (SURVEY_ID, {"lat": 45.52252, "lon": -122.6912}, None),
    (SURVEY_ID, {"lat": 90, "lon": -180}, None),
    (SURVEY_ID, {"lat": -90, "lon": 180}, None),
    (SURVEY_ID, {"lat": "45", "lon": -122}, "lat"),
    (SURVEY_ID, {"lat": 45, "lon": "-122"}, "lon"),
    (SURVEY_ID, {"lat": 91, "lon": 0}, "lat"),
    (SURVEY_ID, {"lat": 0, "lon": -180.5}, "lon"),
    (SURVEY_ID, {"lat": None, "lon": 0}, "lat"),
    (SURVEY_ID, {"lat": 0}, "lon"),
    (SURVEY_ID, {}, "lat"),
    (SURVEY_ID, "lat=1&lon=2", "lat"),
    (SURVEY_ID.upper(), {"lat": 45.0, "lon": -122.0}, "survey_id"),
    ("3f9a1c2e", {"lat": 45.0, "lon": -122.0}, "survey_id"),
    ("3f9a1c2e-si ", {"lat": 45.0, "lon": -122.0}, "survey_id"),
    (SURVEY_ID.upper(), {"lat": "x", "lon": "y"}, "survey_id"),
])
def test_location_correction_validates_the_id_and_the_pair(survey_id, body, detail):
    validator = named(json.loads(FLOWS.read_text()), "tm-internal: validate location correction")
    [step] = run_functions([(validator, location_msg(survey_id, body))])["results"]
    passed, refused = step["result"]
    if detail is None:
        assert refused is None
        assert passed["params"] == {"$survey_id": survey_id, "$lat": body["lat"], "$lon": body["lon"]}
        return
    assert passed is None
    assert refused["statusCode"] == 400 and refused["payload"] == bad_request(detail)


DEPLOYMENT_ID = "1761800000000-0a1b2c3d-d"


@needs_node
@pytest.mark.parametrize("deployment_id, body, detail, stored", [
    (DEPLOYMENT_ID, {"bearing": "ne"}, None, "ne"),
    (DEPLOYMENT_ID, {"bearing": "NE"}, None, "ne"),
    (DEPLOYMENT_ID, {"bearing": ""}, None, ""),
    (DEPLOYMENT_ID, {"bearing": "s"}, None, "s"),
    (DEPLOYMENT_ID, {"bearing": "north"}, "bearing", None),
    (DEPLOYMENT_ID, {"bearing": "nn"}, "bearing", None),
    (DEPLOYMENT_ID, {"bearing": " n"}, "bearing", None),
    (DEPLOYMENT_ID, {"bearing": None}, "bearing", None),
    (DEPLOYMENT_ID, {"bearing": 1}, "bearing", None),
    (DEPLOYMENT_ID, {}, "bearing", None),
    (DEPLOYMENT_ID, "bearing=n", "bearing", None),
    ("1761800000000-0A1B2C3D-d", {"bearing": "n"}, "deployment_id", None),
    ("0a1b2c3d-d", {"bearing": "n"}, "deployment_id", None),
    ("x-1761800000000-0a1b2c3d-d", {"bearing": "n"}, "deployment_id", None),
    ("1761800000000-0a1b2c3d-d ", {"bearing": "n"}, "deployment_id", None),
    ("1761800000000-0a1b2c3d-d", {"bearing": "north"}, "bearing", None),
    ("nope", {"bearing": "north"}, "deployment_id", None),
])
def test_bearing_correction_validates_the_id_and_the_bearing(deployment_id, body, detail, stored):
    validator = named(json.loads(FLOWS.read_text()), "tm-internal: validate bearing correction")
    msg = {"req": {"params": {"id": deployment_id}}, "payload": body}
    [step] = run_functions([(validator, msg)])["results"]
    passed, refused = step["result"]
    if detail is None:
        assert refused is None
        assert passed["params"] == {"$id": deployment_id, "$bearing": stored}
        return
    assert passed is None
    assert refused["statusCode"] == 400 and refused["payload"] == bad_request(detail)


def test_survey_usage_counts_rows_without_a_survey():
    query = named(json.loads(FLOWS.read_text()), "read survey usage")
    sql = sql_text(query)
    assert "WHERE" not in sql.upper()
    assert sql.endswith("GROUP BY survey_id")
    answer = named(json.loads(FLOWS.read_text()), "tm-internal: answer survey usage")
    assert "no survey" in answer["func"]


# capture-events' "append config" maps Frigate's camera name to the sensors.cameras key, from the map "init config
# defaults" builds on each load. Frigate's name stays on the device: it is never in a log line, and every node after
# "append config" sees the key.

APPEND_CONFIG = "8eaa1d06a29a5d2b"  # append config, deployment properties
UNLISTED_WARNING = ("An event from a Frigate camera that config.yml doesn't list was dropped. "
                    "Open the control app's Cameras page.")


def node_by_id(node_id):
    [node] = [node for node in json.loads(FLOWS.read_text()) if node["id"] == node_id]
    return node


def config_with_cameras(cameras):
    config = new_device_config()
    config["sensors"]["cameras"] = cameras
    return config


def load_config(config, context=None):
    """Run init config defaults on config; returns its step and the global context with global.config set, as
    "set global.config" does after a load."""
    run = run_functions([(node_by_id(INIT_DEFAULTS), {"payload": config})], context=context)
    [step] = run["results"]
    return step, {**run["global"], "config": step["result"]["payload"]}


def frigate_event(camera, payload=None):
    return {"frigate_event": {"camera": camera, "id": "1.0-abc"}, "payload": {} if payload is None else payload}


def frigate_payload(camera, **parts):
    """msg.payload as Frigate sends an end message: the event's state before and after, each with the camera."""
    return {"type": "end", "before": {"camera": camera, "id": "1.0-abc"}, "after": {"camera": camera, "id": "1.0-abc"},
            **parts}


def append_events(cameras, context, payload=None):
    """Run append config on one event per camera, in one run; returns the steps and the global context after."""
    append = node_by_id(APPEND_CONFIG)
    run = run_functions([(append, frigate_event(camera, payload)) for camera in cameras], context=context)
    return run["results"], run["global"]


def append_config(config, camera, context=None, payload=None):
    _, context = load_config(config, context)
    [step], context = append_events([camera], context, payload)
    return step, context


@needs_node
def test_init_defaults_maps_frigate_names_to_keys():
    config = config_with_cameras({
        "camera_1_3fa9c2": {"frigate_camera": "oak_ave_wide"},
        "picam_h265": {},
        "main_st": {"frigate_camera": ""},
    })
    step, context = load_config(config)
    assert context["frigate_cameras"] == {"oak_ave_wide": "camera_1_3fa9c2", "picam_h265": "picam_h265",
                                          "main_st": "main_st"}
    assert context["camera_labels"] == {"camera_1_3fa9c2": "camera_1_3fa9c2 (oak_ave_wide)",
                                        "picam_h265": "picam_h265", "main_st": "main_st"}
    assert context["tm_warned"] == {}
    assert "frigate_cameras" not in step["result"]["payload"] and "camera_labels" not in step["result"]["payload"]
    # The payload becomes global.config: Frigate's names live only in the two maps.
    stored = json.dumps(step["result"]["payload"])
    assert "oak_ave_wide" not in stored and "frigate_camera" not in stored
    assert step["logged"] == []


@needs_node
def test_a_duplicate_frigate_camera_is_a_config_error_that_names_only_keys():
    config = config_with_cameras({
        "camera_1_3fa9c2": {"frigate_camera": "oak_ave_wide", "enabled": True},
        "camera_2_b07e11": {"frigate_camera": "oak_ave_wide", "enabled": True},
    })
    step, context = load_config(config)
    assert context["frigate_cameras"] == {"oak_ave_wide": "camera_1_3fa9c2"}
    [(level, text, with_msg)] = [entry for entry in step["logged"] if "same Frigate camera" in entry[1]]
    assert (level, with_msg) == ("error", True) and "oak_ave_wide" not in text
    assert "camera_1_3fa9c2" in text and "camera_2_b07e11" in text
    assert all("oak_ave_wide" not in text for _, text, _ in step["logged"])


@needs_node
def test_append_config_records_the_key_not_frigates_name():
    config = config_with_cameras({
        "camera_1_3fa9c2": {"frigate_camera": "oak_ave_wide", "enabled": True,
                            "camera_radar": "TM_RADAR_SERIAL_PORT_00"},
    })
    step, _ = append_config(config, "oak_ave_wide")
    assert step["result"]["frigate_event"]["camera"] == "camera_1_3fa9c2"
    assert step["result"]["enabled"] is True and step["result"]["radarEnabled"] is True
    assert step["result"]["frigate_event"]["radarName"] == "TM_RADAR_SERIAL_PORT_00"
    assert "oak_ave_wide" not in json.dumps(step["result"])
    assert step["logged"] == []


@needs_node
def test_append_config_puts_the_key_on_the_whole_frigate_message():
    """msg.payload.before and .after carried Frigate's name on, and "match radar speed to event" keeps
    the whole payload. In the live flow frigate_event is the same object as payload.after; here they are separate."""
    config = config_with_cameras({"camera_1_3fa9c2": {"frigate_camera": "oak_ave_wide", "enabled": True}})
    step, _ = append_config(config, "oak_ave_wide", payload=frigate_payload("oak_ave_wide"))
    result = step["result"]
    assert "oak_ave_wide" not in json.dumps(result)
    assert result["frigate_event"]["camera"] == "camera_1_3fa9c2"
    assert result["payload"]["before"]["camera"] == "camera_1_3fa9c2"
    assert result["payload"]["after"]["camera"] == "camera_1_3fa9c2"
    assert result["payload"]["after"]["id"] == "1.0-abc" and set(result["payload"]) == {"type", "before", "after"}


@needs_node
@pytest.mark.parametrize("payload", [
    {}, {"type": "end", "before": None, "after": None}, {"type": "end", "before": None, "after": {"id": "1.0-abc"}},
    {"type": "end", "before": "x", "after": []},
], ids=["no-before-after", "null", "after-without-camera", "not-objects"])
def test_append_config_survives_a_payload_without_before_and_after(payload):
    config = config_with_cameras({"camera_1_3fa9c2": {"frigate_camera": "oak_ave_wide", "enabled": True}})
    step, _ = append_config(config, "oak_ave_wide", payload=payload)
    assert step["result"]["frigate_event"]["camera"] == "camera_1_3fa9c2"
    assert step["result"]["payload"] == payload  # nothing added, nothing removed
    assert step["logged"] == []


@needs_node
def test_an_event_from_an_unlisted_camera_is_dropped_without_throwing():
    """Issue #54."""
    step, _ = append_config(new_device_config(), "oak_ave_tele")
    assert step["result"] is None


@needs_node
def test_unknown_camera_warns_once_per_config_load():
    """Review Focus 4: a busy road on an unlisted camera logs one warning per config load, and it names no camera."""
    _, context = load_config(new_device_config())
    steps, _ = append_events(["oak_ave_tele", "main_st", "oak_ave_tele"], context)
    assert [step["result"] for step in steps] == [None, None, None]
    all_logged = [entry for step in steps for entry in step["logged"]]
    assert [text for level, text, _ in all_logged if level == "warn"] == [UNLISTED_WARNING]


@needs_node
def test_a_missing_radar_is_treated_like_a_disabled_one():
    """Issue #255: the event is recorded, with no radar."""
    config = config_with_cameras({
        "camera_1_3fa9c2": {"frigate_camera": "oak_ave_wide", "enabled": True,
                            "camera_radar": "TM_RADAR_SERIAL_PORT_03"},
    })
    step, _ = append_config(config, "oak_ave_wide")
    assert step["result"]["enabled"] is True and step["result"]["radarEnabled"] is False
    assert "radarName" not in step["result"]["frigate_event"]
    assert [level for level, text, _ in step["logged"] if "TM_RADAR_SERIAL_PORT_03" in text] == ["warn"]
    assert all("oak_ave_wide" not in text for _, text, _ in step["logged"])


@needs_node
def test_append_config_survives_an_empty_entry():
    """Review Focus 2: an entry with nothing under it is a camera that is off; "camera enabled?" drops its events."""
    step, _ = append_config(config_with_cameras({"main_st": None}), "main_st")
    assert step["result"] is not None and step["result"].get("enabled") is not True
    assert step["result"]["frigate_event"]["camera"] == "main_st"


@needs_node
@pytest.mark.parametrize("cameras", [None, {}], ids=["block-empty", "no-entries"])
def test_init_defaults_survives_a_cameras_block_with_no_entries(cameras):
    step, context = load_config(config_with_cameras(cameras))
    assert step["logged"] == []
    assert (context["frigate_cameras"], context["camera_labels"]) == ({}, {})


@needs_node
@pytest.mark.parametrize("camera, warning", [
    ("oak_ave_tele", UNLISTED_WARNING),
    ("oak_ave_wide", "Camera camera_1_3fa9c2 is paired with radar TM_RADAR_SERIAL_PORT_03, which isn't in config.yml; "
                     "recording its events without a radar."),
], ids=["unlisted", "missing-radar"])
def test_a_new_config_load_warns_again(camera, warning):
    """Each warning is logged once per name per config load: a second load resets tm_warned."""
    config = config_with_cameras({
        "camera_1_3fa9c2": {"frigate_camera": "oak_ave_wide", "enabled": True,
                            "camera_radar": "TM_RADAR_SERIAL_PORT_03"},
    })
    _, context = load_config(config)
    first, context = append_events([camera, camera], context)
    _, context = load_config(config, context)
    second, _ = append_events([camera, camera], context)
    for steps in (first, second):
        assert [text for step in steps for level, text, _ in step["logged"] if level == "warn"] == [warning]
    assert all(name not in text for step in second for _, text, _ in step["logged"]
               for name in ("oak_ave_wide", "oak_ave_tele"))


# What leaves the device and what the Frigate API is asked, by key. Plate Recognizer is sent the camera's name in
# config.yml and the regions the admin set (issue #249), ThingsBoard gets no copy of the config, and the node that
# asks Frigate for its daily summary maps the key back to the name Frigate uses.

PR_FORMAT = "ce5360091646c733"  # plate-recognizer: format http request
PR_ROW = "f76c2b5b2b99096a"  # plate-recognizer: write params for plate_recognizer insert
SUMMARY = "eb140f61419c6a08"  # ui-monitoring: structure frigate api/summary
DEFAULT_REGIONS = ["us", "us-or", "us-wa"]


def plate_request(regions=MISSING, camera="camera_1_3fa9c2"):
    plate_recognizer = {"url": "http://plate-recognizer:8080"}
    if regions is not MISSING:
        plate_recognizer["regions"] = regions
    msg = {"frigate_event": {"frame_time": 1761800000.5, "camera": camera}, "frigate_event_api_thumbnail": "thumbnail"}
    [step] = run_functions([(node_by_id(PR_FORMAT), msg)],
                           env={"TM_PLATE_RECOGNIZER_TOKEN": "pr-placeholder-0002"},
                           context={"config": {"addons": {"plate_recognizer": plate_recognizer}}})["results"]
    return step["result"]["payload"]


@needs_node
def test_plate_recognizer_is_sent_the_cameras_key_and_the_configured_regions():
    payload = plate_request(regions=["gb"])
    assert payload["camera_id"] == {"value": "camera_1_3fa9c2"}
    assert json.loads(payload["regions"]["value"]) == ["gb"]


@needs_node
@pytest.mark.parametrize("regions", [MISSING, None, [], "us", [1, 2]],
                         ids=["missing", "null", "empty", "a-string", "not-strings"])
def test_plate_recognizer_regions_default(regions):
    assert json.loads(plate_request(regions=regions)["regions"]["value"]) == DEFAULT_REGIONS


@needs_node
def test_the_plate_row_stores_the_cameras_key():
    msg = {"frigate_event": {"id": "1.0-abc", "camera": "camera_1_3fa9c2"},
           "payload": {"filename": "x.jpg", "camera_id": "something-else", "results": []}}
    [step] = run_functions([(node_by_id(PR_ROW), msg)])["results"]
    assert step["result"]["payload"]["camera_id"] == "camera_1_3fa9c2"
    assert step["result"]["params"]["$camera_id"] == "camera_1_3fa9c2"


def thingsboard_nodes():
    flows = json.loads(FLOWS.read_text())
    tab = tab_id(flows, "thingsboard")
    return flows, [node for node in flows if node.get("z") == tab]


def test_the_settings_are_not_uploaded():
    flows, nodes = thingsboard_nodes()
    assert [node["id"] for node in nodes
            if "config_tm" in node.get("func", "") or "config_tm" in node.get("template", "")] == []
    by_id = {node["id"]: node for node in flows}
    capture_radar = tab_id(flows, "capture-radar")
    links = by_id["2fa46892748adc43"]["links"]
    assert links and all(by_id[link]["z"] == capture_radar for link in links)


def test_backup_and_restore_are_gone():
    flows, nodes = thingsboard_nodes()
    assert [node["id"] for node in nodes if node["type"] in ("ui_button", "ui_template", "ui_toast")] == []
    assert [node["id"] for node in nodes
            if any("backup" in str(node.get(key, "")).lower() for key in ("name", "func", "template"))] == []
    assert [node["id"] for node in flows if node["type"] == "ui_group" and node.get("name") == "Backup & Restore"] == []
    assert {node["id"] for node in nodes if node["type"] == "http request"} == {"677a57bbf3619854"}


def test_no_reference_to_a_removed_node():
    flows = json.loads(FLOWS.read_text())
    ids = {node["id"] for node in flows}
    missing = []
    for node in flows:
        references = [target for output in node.get("wires", []) for target in output]
        references += node.get("links", []) + node.get("nodes", [])
        references += [node[key] for key in ("g", "group", "z") if node.get(key)]
        missing += [(node["id"], target) for target in references if target not in ids]
    assert missing == []


@needs_node
def test_system_info_attributes_have_no_network_slots():
    payload = {"tmVersion": "0.9.0", "osHostname": "host", "osRelease": "13", "osTimeZone": "UTC",
               "deviceName": "unit", "frigateVersion": "0.16", "ssid": "net", "ipv4Address": "10.0.0.2"}
    [step] = run_functions([(node_by_id("e507fdc9cbf67095"), {"payload": payload})])["results"]
    assert sorted(step["result"]["payload"]) == sorted(
        ["sysinfo_tmVersion", "sysinfo_osHostname", "sysinfo_osRelease", "sysinfo_osTimeZone",
         "sysinfo_deviceName", "sysinfo_frigateVersion"])


@needs_node
def test_flow_tests_run_in_the_function_nodes_sandbox():
    """Node-RED's function nodes don't have structuredClone (or fetch): the harness must not either."""
    node = {"id": "sandbox", "func": "return { payload: typeof structuredClone + ' ' + typeof fetch + ' ' + typeof JSON };"}
    [step] = run_functions([(node, {})])["results"]
    assert step["result"]["payload"] == "undefined undefined object"


def summary_rows():
    today = "2026-11-10"
    return [
        {"camera": "oak_ave_wide", "day": today, "label": "car", "count": 4},
        {"camera": "oak_ave_tele", "day": today, "label": "car", "count": 100},
        {"camera": "oak_ave_wide", "day": today, "label": "bicycle", "count": 1},
    ]


@needs_node
def test_the_frigate_summary_chart_follows_the_selected_cameras_key():
    rows = [{**row, "day": "2099-01-01"} for row in summary_rows()]
    run = run_functions([(node_by_id(SUMMARY), {"payload": rows})],
                        context={"frigate_cameras": {"oak_ave_wide": "camera_1_3fa9c2",
                                                     "oak_ave_tele": "camera_2_b07e11"}},
                        flow={"camera_selection": "camera_1_3fa9c2"})
    [chart] = run["results"][0]["result"]["payload"]
    assert chart["series"] == ["car", "bicycle"]
    assert [[point["y"] for point in series] for series in chart["data"]] == [[4], [1]]


@needs_node
def test_the_frigate_summary_chart_is_empty_without_the_map():
    rows = [{**row, "day": "2099-01-01"} for row in summary_rows()]
    run = run_functions([(node_by_id(SUMMARY), {"payload": rows})], flow={"camera_selection": "camera_1_3fa9c2"})
    [chart] = run["results"][0]["result"]["payload"]
    assert chart["series"] == [] and chart["data"] == []


@needs_node
def test_the_frigate_summary_chart_is_empty_with_no_camera_selected():
    """An unmapped camera's frigate_cameras lookup is undefined, as is an unset selection: they must not match."""
    rows = [{**row, "day": "2099-01-01"} for row in summary_rows()]
    run = run_functions([(node_by_id(SUMMARY), {"payload": rows})],
                        context={"frigate_cameras": {"oak_ave_wide": "camera_1_3fa9c2"}}, flow={})
    [chart] = run["results"][0]["result"]["payload"]
    assert chart["series"] == [] and chart["data"] == []


def test_every_node_that_asks_frigate_for_a_camera_by_name_maps_the_key_back():
    """Nodes that call Frigate's API (frigate:5000): version, events/summary, config (for the frigate facts, and
    again for the watch log's camera switches), and the thumbnail and snapshot of an event id. None puts a camera
    name in its URL. Frigate's summary lists every camera by Frigate's name, and the one node that picks a camera out of it is "structure frigate api/summary"
    (eb140f61419c6a08), which compares with flow.camera_selection (a key). Every function that reads
    camera_selection and isn't a query of tmdb (which stores the key) must map the key back through
    frigate_cameras."""
    flows = json.loads(FLOWS.read_text())
    calls = [node for node in flows if "frigate:5000" in (node.get("url") or "")]
    assert len(calls) == 6 and not [node["id"] for node in calls if "camera" in node["url"]]
    selects = [node["id"] for node in flows
               if "camera_selection" in (node.get("func") or "") and "SELECT" not in node["func"]]
    assert selects == [SUMMARY]
    assert 'global.get("frigate_cameras")' in node_by_id(SUMMARY)["func"]


# Data downloads from Android's sign-in window: it hands a download to a helper that sends no login cookie, so both
# download templates ask tm-control for a one-time link first, and fall back to the plain address.

LINK_PAGES = {"26223a9168dd0050": "async downloadUrl(files) {", "70073189458c7166": "async function downloadUrl(files) {"}


def download_url_body(node):
    """The body of the template's downloadUrl: from its opening line in LINK_PAGES to the matching brace, dedented."""
    text = node["format"]
    start = text.index(LINK_PAGES[node["id"]]) + len(LINK_PAGES[node["id"]])
    depth = 1
    for end in range(start, len(text)):
        depth += {"{": 1, "}": -1}.get(text[end], 0)
        if depth == 0:
            return textwrap.dedent(text[start:end].strip("\n").rstrip() + "\n")
    raise AssertionError(f"{node['id']}: downloadUrl has no closing brace")


def test_both_download_pages_ask_the_control_app_for_a_link():
    _, by_id = _download_nodes()
    bodies = {download_url_body(by_id[node]) for node in LINK_PAGES}
    assert len(bodies) == 1
    [body] = bodies
    assert "'/api/v1/auth/download-link'" in body and "JSON.stringify({ files })" in body
    for node in LINK_PAGES:
        assert ":href" not in by_id[node]["format"]
        assert "window.location.href = await" in by_id[node]["format"]


# Runs downloadUrl's body as an async function of (files, fetch), with a fetch that answers ANSWER (or throws for null)
DOWNLOAD_URL_HARNESS = r"""
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
const calls = [];
const fetch = async (url, options) => {
    calls.push({ url, method: options.method, headers: options.headers, body: options.body,
                 signal: options.signal instanceof AbortSignal });
    const answer = ANSWER;
    if (answer === null) throw new TypeError("Failed to fetch");
    return answer;
};
new AsyncFunction("files", "fetch", BODY)("a.json", fetch).then((url) => console.log(JSON.stringify({ url, calls })));
"""


@needs_node
@pytest.mark.parametrize(
    "answer, expected",
    [
        (
            '{"ok": true, "json": async () => ({"url": "/storefiles?files=a.json&tm_token=T"})}',
            "/storefiles?files=a.json&tm_token=T",
        ),
        ('{"ok": false}', "/storefiles?files=a.json"),  # a viewer's 403
        ("null", "/storefiles?files=a.json"),  # fetch throws: the control app doesn't answer
    ],
    ids=["link", "refused", "no-answer"],
)
def test_a_download_falls_back_to_the_plain_address(answer, expected):
    _, by_id = _download_nodes()
    body = download_url_body(by_id["26223a9168dd0050"])
    script = DOWNLOAD_URL_HARNESS.replace("ANSWER", answer).replace("BODY", json.dumps(body))
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    assert out["url"] == expected
    assert out["calls"] == [{
        "url": "/api/v1/auth/download-link",
        "method": "POST",
        "headers": {"Content-Type": "application/json"},
        "body": '{"files":"a.json"}',
        "signal": True,
    }]


def test_a_download_says_it_is_gzip():
    _, by_id = _download_nodes()
    assert "'Content-Type', 'application/gzip'" in by_id["857384c653c6a46c"]["func"]
    assert "octet-stream" not in by_id["857384c653c6a46c"]["func"]


# What leaves the unit for ThingsBoard, and how the server answered. The sharing: block in config.yml says what an
# operator chose on the Sharing page, and for which server. Every upload passes the "upload gate", which sends only
# the listed kinds of data, deployment rows at the precision tmdb stores, and, on the deployments attribute, what was
# chosen. "record upload result" keeps how the server answered the last upload for GET /tm-internal/status.

UPLOAD_REQUEST = "677a57bbf3619854"  # thingsboard: tb post http api
ENABLED_SWITCH = "93aa421659d2c20b"  # thingsboard: thingsboard.enabled
RATE_LIMIT = "21944450ecc08385"  # thingsboard: the rate limit after thingsboard.enabled
PROTOCOL_SWITCH = "9b8c2bcc16a637fd"  # thingsboard: tb protocol?
TB_CATCH = "695200d405f2d323"  # thingsboard: the tab's catch node
CONFIG_LOADED = "2b50b0bfb900ff09"  # init-config: tm-internal: config loaded
SHARING_OFF = {"target": None, "host": None, "exact_location": False, "public_map": "none", "notice_version": None}
SHARING_ON = {"target": "maintainer", "host": "tb.example.invalid", "exact_location": True,
              "public_map": "rounded_point", "notice_version": "2026-11"}
# The host rule, shared with tm-control: trim, lower-case, drop a leading http:// or https://, drop one trailing /.
SHARING_HOST_CASES = [
    ("tb.example.invalid", "tb.example.invalid"),
    ("HTTPS://TB.Example.invalid/", "tb.example.invalid"),
    ("http://tb.example.invalid", "tb.example.invalid"),
    ("https://tb.example.invalid/", "tb.example.invalid"),
    ("  tb.example.invalid  ", "tb.example.invalid"),
    ("tb.example.invalid//", "tb.example.invalid/"),
    ("https://", None),
    ("", None),
    ("   ", None),
    (42, None),
    (None, None),
]
GATE_PLACE = {"survey_id": "3f9a1c2e-si", "lat": 45.52252, "lon": -122.69120, "database_precision": "2"}
GATE_THINGSBOARD = {"host": "tb.example.invalid", "url": "https://tb.example.invalid"}
GATE_ADDED = {"consents", "exact_location", "public_map"}
CONSENTS_OFF = {"share_data": True, "exact_location": False, "public_map": "none", "notice_version": None,
                "target": None}
UPLOAD_LISTS = FLOWS.parent / "upload-lists.json"
EVENT_COLUMNS = [
    "id", "camera", "label", "sub_label", "top_score", "frame_time", "start_time", "end_time", "entered_zones",
    "score", "area", "ratio", "motionless_count", "position_changes", "attributes", "direction_calc", "speed_calc",
    "provenance", "deployment_id", "radarName", "path_data", "box", "best_box", "best_frame_time", "frigate_speed",
    "frigate_speed_unit", "frigate_velocity_angle", "speed_unit", "speed_source", "radar_readings", "direction_source",
]
KEPT_ON_THE_UNIT = set()  # event fields that are saved and never uploaded; adding one is a decision
LISTS_WARNING = "ThingsBoard upload: the lists of what is shared didn't load, so nothing is sent."


def upload_lists():
    return json.loads(UPLOAD_LISTS.read_text())


TS = 1761800000000
GATE_ROW = {"id": "1761800000000-0a1b2c3d-d", "entryStartDateTime": TS, "lat": 45.52, "lon": -122.69,
            "location_precision": 2, "bearing": "n", "sensorType": "cameras", "sensorName": "picam_h265",
            "survey_id": "3f9a1c2e-si"}
TICK = 1761800100  # a five-minute mark
TICK_MS = TICK * 1000
WATCH_CAMERA_COLUMNS = ["time", "camera", "config_enabled", "deployment_id", "frigate_answers", "camera_answers",
                        "camera_fps", "process_fps", "skipped_fps", "detection_fps", "detection_enabled", "camera_on"]
WATCH_RADAR_COLUMNS = ["time", "radar", "config_enabled", "deployment_id", "port_open", "last_reading_at",
                       "radar_answers", "radar_on"]
STATS_WARNING = "Watch log: a frigate/stats message couldn't be read, so it wasn't counted."
EMPTY_WINDOW = {"since": TICK_MS - 300000, "messages": 0, "cameras": {}, "switches": {}, "radars": {}}
WATCH_SENSORS = {
    "cameras": {"camera_1_3fa9c2": {"enabled": True, "deployment": {"id": "1761700000000-0a1b2c3d-d"}},
                "side_st": {"enabled": False}},
    "radars": {"TM_RADAR_SERIAL_PORT_00": {"enabled": True, "deployment": {"id": "1761700000000-4e5f6a7b-d"}},
               "TM_RADAR_SERIAL_PORT_01": {"enabled": False}},
}
WATCH_WINDOW = {"since": TICK_MS - 300000, "messages": 5, "cameras": {"camera_1_3fa9c2": {
    "messages": 5, "camera_fps": 25.0, "process_fps": 24.5, "skipped_fps": 0.0, "detection_fps": 2.0,
    "detection_off": 0}}, "switches": {"camera_1_3fa9c2": {"answers": 5, "off": 0}},
    "radars": {"TM_RADAR_SERIAL_PORT_00": {"checks": 5, "port_closed": 0, "answers": 5, "idle": 0, "unknown": 0}}}
RADAR_STATUS = {"TM_RADAR_SERIAL_PORT_00": {"enabled": True, "port_open": True,
                                            "last_reading_at": "2025-10-30T04:54:58.400Z"}}
NO_NUMBERS = {"camera_answers": 0, "camera_fps": None, "process_fps": None, "skipped_fps": None,
              "detection_fps": None, "detection_enabled": None}
CAMERA_ROWS = [
    {"time": TICK, "camera": "camera_1_3fa9c2", "config_enabled": 1, "deployment_id": "1761700000000-0a1b2c3d-d",
     "frigate_answers": 5, "camera_answers": 5, "camera_fps": 5.0, "process_fps": 4.9, "skipped_fps": 0.0,
     "detection_fps": 0.4, "detection_enabled": 1, "camera_on": 1},
    {"time": TICK, "camera": "side_st", "config_enabled": 0, "deployment_id": None, "frigate_answers": 5, **NO_NUMBERS,
     "camera_on": None},
]
RADAR_ROWS = [
    {"time": TICK, "radar": "TM_RADAR_SERIAL_PORT_00", "config_enabled": 1, "deployment_id": "1761700000000-4e5f6a7b-d",
     "port_open": 1, "last_reading_at": 1761800098.4, "radar_answers": 5, "radar_on": 1},
    {"time": TICK, "radar": "TM_RADAR_SERIAL_PORT_01", "config_enabled": 0, "deployment_id": None, "port_open": 0,
     "last_reading_at": None, "radar_answers": 0, "radar_on": None},
]
GATE_TELEMETRY = {
    "event": {"id": "1761800000.0-abc", "label": "car", "camera": "picam_h265", "frame_time": 1761800000.0},
    "radar": {"radar_dov": {"time": 1761800000, "velocity": 12.3, "radarName": "TM_RADAR_SERIAL_PORT_00"}},
    "airquality": {"entryDateTime": 1761800000, "pm025": 4.0, "sensorName": "aq"},
    "system_metrics": {"time_ms_utc": TS, "cpu_percent": 12.5},
    "deployments": {"updatedDeployment": [{**GATE_ROW, "entryEndDateTime": TS}], "currentDeployment": [GATE_ROW]},
    "watch": {"cameras": [CAMERA_ROWS[0]], "radars": [RADAR_ROWS[0]]},
}
GATE_ATTRIBUTES = {
    "deployments": {
        "picam_h265": {"sensorType": "cameras", "lat": "45.52", "lon": "-122.69", "bearing": "n",
                       "id": "1761800000000-0a1b2c3d-d"},
        "deploymentTopLevel": {"survey_id": "3f9a1c2e-si", "database_precision": "2"},
    },
    "radarinfo": {"TM_RADAR_SERIAL_PORT_00": {"Product": "OPS243-C", "SamplingRate": "20000"}},
    "sysinfo_tmVersion": "0.9.0",
    "sysinfo_osHostname": "traffic-monitor",
    "sysinfo_osRelease": "13",
    "sysinfo_osTimeZone": "UTC",
    "sysinfo_deviceName": "0000000000000000",
    "sysinfo_frigateVersion": "0.16.0",
}


@needs_node
@pytest.mark.parametrize("given, expected", [
    (MISSING, SHARING_OFF),
    ({**SHARING_ON, "host": "HTTPS://TB.Example.invalid/"}, SHARING_ON),
    ({"exact_location": "true"}, SHARING_OFF),
    ({"public_map": "block"}, SHARING_OFF),
    (["maintainer"], SHARING_OFF),
    (None, SHARING_OFF),
    ({"target": "own"}, {**SHARING_OFF, "target": "own"}),
    ({"target": "everyone"}, SHARING_OFF),
    ({"notice_version": 3}, SHARING_OFF),
] + [({"host": given}, {**SHARING_OFF, "host": expected}) for given, expected in SHARING_HOST_CASES],
    ids=["missing", "all-on", "exact-location-string", "public-map-block", "list", "empty", "target-own",
         "target-unknown", "notice-version-number"] + [f"host-{index}" for index in range(len(SHARING_HOST_CASES))])
def test_init_config_defaults_sharing(given, expected):
    """sharing: always has all five keys; anything that isn't one of a key's values is that key's off value, and a
    missing block logs nothing."""
    config = new_device_config()
    config.pop("sharing", None)
    if given is not MISSING:
        config["sharing"] = given
    [step] = run_functions([(node_by_id(INIT_DEFAULTS), {"payload": config})])["results"]
    assert step["result"]["payload"]["sharing"] == expected
    assert step["logged"] == []


def gate_node():
    return named(json.loads(FLOWS.read_text()), "upload gate")


def gate_run(msgs, sharing=None, thingsboard=None, deployment=None, lists=MISSING):
    """Run the upload gate on each message in turn, with this config and the upload lists (upload-lists.json unless
    given; none at all for None); returns the run (results, global)."""
    config = {"sharing": SHARING_OFF if sharing is None else sharing,
              "thingsboard": {"enabled": True, **(GATE_THINGSBOARD if thingsboard is None else thingsboard)},
              "deployment": GATE_PLACE if deployment is None else deployment}
    context = {"config": config, "tm_warned": {}}
    if lists is MISSING:
        context["upload_lists"] = upload_lists()
    elif lists is not None:
        context["upload_lists"] = lists
    gate = gate_node()
    return run_functions([(gate, msg) for msg in msgs], context=context)


def gate(msg, sharing=None, thingsboard=None, deployment=None, lists=MISSING):
    """The upload gate's output for one message (None when it sends nothing), and its log."""
    [step] = gate_run([msg], sharing, thingsboard, deployment, lists)["results"]
    return step["result"], step["logged"]


def attributes(payload, **kwargs):
    out, _ = gate({"type": "attributes", "payload": payload}, **kwargs)
    return None if out is None else out["payload"]


def deployments_attribute(**kwargs):
    return attributes({"deployments": GATE_ATTRIBUTES["deployments"]}, **kwargs)


@needs_node
def test_gate_passes_each_listed_kind():
    for kind, values in GATE_TELEMETRY.items():
        item = {"ts": TS, "values": {kind: values}}
        out, logged = gate({"type": "telemetry", "payload": item})
        assert out["payload"] == item, kind
        assert logged == [], kind
    for key, value in GATE_ATTRIBUTES.items():
        out, logged = gate({"type": "attributes", "payload": {key: value}})
        assert logged == [], key
        if key == "deployments":
            assert {k: v for k, v in out["payload"].items() if k not in GATE_ADDED} == {key: value}
            assert set(out["payload"]) == {key} | GATE_ADDED
        else:
            assert out["payload"] == {key: value}, key


@needs_node
def test_gate_drops_an_unlisted_key_and_warns_once():
    surprise = {"ts": TS, "values": {"event": GATE_TELEMETRY["event"], "surprise": {"note": "kept-on-the-unit"}}}
    settings = {"config_tm": {"thingsboard": {"host": "tb.example.invalid"}, "note": "kept-on-the-unit"}}
    run = gate_run([{"type": "telemetry", "payload": surprise}, {"type": "telemetry", "payload": surprise},
                    {"type": "attributes", "payload": settings}])
    first, second, third = run["results"]
    for step in (first, second):
        assert step["result"]["payload"] == {"ts": TS, "values": {"event": GATE_TELEMETRY["event"]}}
    assert third["result"] is None
    warnings = [text for step in run["results"] for level, text, _ in step["logged"] if level == "warn"]
    assert len(warnings) == 2
    assert "surprise" in warnings[0] and "config_tm" in warnings[1]
    assert all(entry[0] == "warn" for step in run["results"] for entry in step["logged"])
    logged = json.dumps([step["logged"] for step in run["results"]])
    assert "kept-on-the-unit" not in logged and "tb.example.invalid" not in logged and "note" not in logged
    assert run["global"]["tm_warned"] == {"upload:surprise": True, "upload:config_tm": True}


@needs_node
def test_gate_passes_a_radar_array_item_by_item():
    radar = {"ts": TS, "values": {"radar": GATE_TELEMETRY["radar"]}}
    unlisted = {"ts": TS + 1, "values": {"surprise": 1}}
    out, _ = gate({"type": "telemetry", "payload": [radar, unlisted, radar]})
    assert out["payload"] == [radar, radar]
    out, _ = gate({"type": "telemetry", "payload": [unlisted, unlisted]})
    assert out is None


def deployment_row(**changes):
    row = {**GATE_ROW, "lat": 45.52252, "lon": -122.69120}
    for key, value in changes.items():
        if value is MISSING:
            row.pop(key, None)
        else:
            row[key] = value
    return row


@needs_node
@pytest.mark.parametrize("row, unit, lat, lon", [
    (deployment_row(location_precision=1), "2", 45.5, -122.7),
    (deployment_row(location_precision=2), "1", 45.5, -122.7),
    (deployment_row(location_precision=2), "2", 45.52, -122.69),
    (deployment_row(location_precision=MISSING), "2", 45.52, -122.69),
    (deployment_row(location_precision=MISSING), "1", 45.5, -122.7),
    (deployment_row(location_precision=2), "none", None, None),
    (deployment_row(location_precision=None), "2", None, None),
    (deployment_row(location_precision=1, lat=-0.05, lon=0.05), "2", -0.1, 0.1),
    (deployment_row(location_precision=2, lat=None, lon=None), "2", None, None),
], ids=["row-1", "unit-1", "both-2", "missing-is-the-units", "missing-unit-1", "unit-none", "row-null",
        "half-away-from-zero", "no-location"])
def test_gate_re_rounds_deployment_rows(row, unit, lat, lon):
    """lat and lon to min(the row's location_precision, the unit's database_precision) places, half away from zero."""
    place = {**GATE_PLACE, "database_precision": unit}
    payload = {"ts": TS, "values": {"deployments": {"updatedDeployment": [row], "currentDeployment": [row]}}}
    out, _ = gate({"type": "telemetry", "payload": payload}, deployment=place)
    deployments = out["payload"]["values"]["deployments"]
    for rows in (deployments["updatedDeployment"], deployments["currentDeployment"]):
        [sent] = rows
        assert (sent["lat"], sent["lon"]) == (lat, lon)
        assert {k: v for k, v in sent.items() if k not in ("lat", "lon")} == {
            k: v for k, v in row.items() if k not in ("lat", "lon")}


@needs_node
@pytest.mark.parametrize("precision, places, lat, lon", [("1", 1, 45.5, -122.7), ("2", 2, 45.52, -122.69),
                                                       ("none", None, None, None)])
def test_gate_leaves_the_engines_rows_as_they_are(precision, places, lat, lon):
    """The engine rounds the same way, so the rows it sends at the unit's precision (a new one, one it closes, one it
    keeps) pass unchanged. A closed row stored finer than the unit's precision now goes out at the unit's."""
    place = {**ENGINE_PLACE, "database_precision": precision}
    run = engine(engine_sensors({"bearing": "w"}), [camera_row(lat=lat, lon=lon, precision=places), radar_row()],
                 place)
    [step] = run_functions([(named(json.loads(FLOWS.read_text()), "format deployment telemetry"),
                             {"payload": run.payload})])["results"]
    out, logged = gate({"type": "telemetry", "payload": step["result"]["payload"]}, deployment=place)
    assert out["payload"] == step["result"]["payload"] and logged == []
    assert run.payload["updatedDeployment"] and run.payload["currentDeployment"]


@needs_node
@pytest.mark.parametrize("given, unit, expected", [
    (("45.52252", "-122.69120"), "2", ("45.52", "-122.69")),
    (("45.52252", "-122.69120"), "1", ("45.5", "-122.7")),
    (("", ""), "2", ("", "")),
    (("45.52252", "-122.69120"), "none", (None, None)),
    (("-0.05", "0.05"), "1", ("-0.1", "0.1")),
], ids=["strings-2", "strings-1", "empty", "unit-none", "half-away-from-zero"])
def test_gate_re_rounds_the_deployments_attribute(given, unit, expected):
    """The attribute's per-sensor rows hold strings (a template renders them): they go out as strings, at the
    unit's precision. deploymentTopLevel names the survey and holds no coordinates."""
    rows = {"picam_h265": {"sensorType": "cameras", "lat": given[0], "lon": given[1], "bearing": "n", "id": "x-d"},
            "deploymentTopLevel": {"survey_id": "3f9a1c2e-si", "database_precision": unit}}
    sent = attributes({"deployments": rows}, deployment={**GATE_PLACE, "database_precision": unit})["deployments"]
    assert (sent["picam_h265"]["lat"], sent["picam_h265"]["lon"]) == expected
    assert sent["deploymentTopLevel"] == rows["deploymentTopLevel"]


@needs_node
def test_gate_adds_the_three_attributes_to_the_deployments_attribute():
    sent = deployments_attribute()
    assert sent["consents"] == CONSENTS_OFF
    assert sent["exact_location"] == {}
    assert sent["public_map"] == {}
    for key in GATE_ATTRIBUTES:
        if key.startswith("sysinfo_"):
            assert set(attributes({key: GATE_ATTRIBUTES[key]})) == {key}


@needs_node
def test_gate_sends_the_exact_location_with_consent_a_matching_host_and_https():
    sent = deployments_attribute(sharing=SHARING_ON)
    assert sent["consents"] == {"share_data": True, "exact_location": True, "public_map": "rounded_point",
                                "notice_version": "2026-11", "target": "maintainer"}
    assert sent["exact_location"] == {"survey_id": "3f9a1c2e-si", "lat": 45.52252, "lon": -122.6912}
    sent = deployments_attribute(sharing=SHARING_ON,
                                 thingsboard={**GATE_THINGSBOARD, "url": "http://tb.example.invalid"})
    assert sent["exact_location"] == {}
    assert sent["consents"]["exact_location"] is True
    sent = deployments_attribute(sharing=SHARING_ON,
                                 thingsboard={**GATE_THINGSBOARD, "url": "HTTPS://tb.example.invalid"})
    assert sent["exact_location"] == {"survey_id": "3f9a1c2e-si", "lat": 45.52252, "lon": -122.6912}


@needs_node
def test_gate_sends_no_exact_location_to_a_host_the_choice_was_not_made_for():
    sent = deployments_attribute(sharing=SHARING_ON, thingsboard={"host": "other.example.invalid",
                                                                  "url": "https://other.example.invalid"})
    assert sent["exact_location"] == {}
    assert sent["public_map"] == {}
    assert sent["consents"]["exact_location"] is False
    assert sent["consents"]["public_map"] == "none"
    sent = deployments_attribute(sharing={**SHARING_ON, "host": None},
                                 thingsboard={"url": "https://tb.example.invalid"})
    assert (sent["consents"]["exact_location"], sent["exact_location"]) == (False, {})


@needs_node
@pytest.mark.parametrize("sharing, thingsboard", [
    (SHARING_ON, {"host": "other.example.invalid", "url": "https://other.example.invalid"}),
    ({**SHARING_ON, "host": None}, GATE_THINGSBOARD),
    (SHARING_ON, {"url": "https://tb.example.invalid"}),
], ids=["other-host", "no-block-host", "no-upload-host"])
def test_gate_names_no_target_or_notice_for_a_server_the_choice_was_not_made_for(sharing, thingsboard):
    """The consents attribute describes the server it is sent to: the block's target and notice version go only to
    the host the block was made for."""
    sent = deployments_attribute(sharing=sharing, thingsboard=thingsboard)
    assert sent["consents"] == {"share_data": True, "exact_location": False, "public_map": "none",
                                "notice_version": None, "target": None}


@needs_node
def test_gate_names_the_target_and_notice_for_the_server_the_choice_was_made_for():
    sent = deployments_attribute(sharing={**SHARING_ON, "target": "own", "exact_location": False,
                                          "public_map": "none"})
    assert (sent["consents"]["target"], sent["consents"]["notice_version"]) == ("own", "2026-11")


@needs_node
@pytest.mark.parametrize("given, expected", SHARING_HOST_CASES,
                         ids=[f"host-{index}" for index in range(len(SHARING_HOST_CASES))])
def test_gate_compares_hosts_by_the_shared_rule(given, expected):
    """thingsboard.host is normalised by the same rule as sharing.host before the two are compared."""
    sent = deployments_attribute(sharing=SHARING_ON, thingsboard={"host": given, "url": "https://tb.example.invalid"})
    assert sent["consents"]["exact_location"] is (expected == "tb.example.invalid")


@needs_node
def test_gate_exact_location_needs_a_point_and_reads_quoted_numbers():
    sent = deployments_attribute(sharing=SHARING_ON, deployment={**GATE_PLACE, "lat": ""})
    assert sent["exact_location"] == {} and sent["public_map"] == {}
    sent = deployments_attribute(sharing=SHARING_ON, deployment={**GATE_PLACE, "lat": "45.522520", "lon": "-122.69120"})
    assert sent["exact_location"] == {"survey_id": "3f9a1c2e-si", "lat": 45.52252, "lon": -122.6912}
    sent = deployments_attribute(sharing=SHARING_ON, deployment={**GATE_PLACE, "survey_id": None})
    assert sent["exact_location"] == {}


@needs_node
def test_gate_public_map_is_a_rounded_point_for_the_maintainer_target_only():
    sent = deployments_attribute(sharing=SHARING_ON)
    assert sent["public_map"] == {"survey_id": "3f9a1c2e-si", "mode": "rounded_point", "lat": 45.523, "lon": -122.691}
    sent = deployments_attribute(sharing={**SHARING_ON, "target": "own"})
    assert sent["public_map"] == {}
    sent = deployments_attribute(sharing={**SHARING_ON, "public_map": "none"})
    assert sent["public_map"] == {} and sent["consents"]["public_map"] == "none"


@needs_node
@pytest.mark.parametrize("given, expected", [("2026-11", "2026-11"), ("", None), (3, None), (None, None)])
def test_gate_reads_notice_version_as_init_config_defaults_does(given, expected):
    sent = deployments_attribute(sharing={**SHARING_ON, "notice_version": given})
    assert sent["consents"]["notice_version"] == expected


@needs_node
@pytest.mark.parametrize("msg", [
    {"type": "settings", "payload": {"event": {}}},
    {"payload": {"ts": TS, "values": {"event": {}}}},
    {"type": "attributes", "payload": "radarinfo"},
    {"type": "telemetry", "payload": None},
    {"type": "telemetry"},
], ids=["unknown-type", "no-type", "attributes-not-a-mapping", "telemetry-null", "no-payload"])
def test_gate_sends_nothing_it_cannot_read(msg):
    out, logged = gate(msg)
    assert out is None
    assert all(level == "warn" for level, _, _ in logged)


@needs_node
@pytest.mark.parametrize("msg", [
    {"type": "attributes", "payload": {"deployments": "picam_h265"}},
    {"type": "attributes", "payload": {"deployments": [GATE_ATTRIBUTES["deployments"]]}},
    {"type": "telemetry", "payload": {"ts": TS, "values": {"deployments": [GATE_ROW]}}},
    {"type": "telemetry", "payload": {"ts": TS, "values": {"deployments": {"surprise": [GATE_ROW]}}}},
    {"type": "telemetry", "payload": {"ts": TS, "values": {"deployments": {"updatedDeployment": "kept-on-the-unit"}}}},
], ids=["attribute-not-a-mapping", "attribute-a-list", "telemetry-not-a-mapping", "telemetry-unknown-key-only",
        "telemetry-list-not-an-array"])
def test_gate_leaves_out_a_deployments_value_it_cannot_read(msg):
    out, logged = gate(msg)
    assert out is None
    assert logged and all(level == "warn" for level, _, _ in logged)
    assert "kept-on-the-unit" not in json.dumps(logged)


@needs_node
def test_gate_keeps_the_rest_when_a_deployments_attribute_is_left_out():
    out, _ = gate({"type": "attributes", "payload": {"deployments": "picam_h265", "sysinfo_tmVersion": "0.9.0"}})
    assert out["payload"] == {"sysinfo_tmVersion": "0.9.0"}


@needs_node
def test_gate_keeps_only_the_two_lists_of_telemetry_deployments_and_only_arrays():
    deployments = {"currentDeployment": [GATE_ROW], "updatedDeployment": "kept-on-the-unit",
                   "surprise": [{"note": "kept-on-the-unit"}]}
    out, logged = gate({"type": "telemetry", "payload": {"ts": TS, "values": {"deployments": deployments}}})
    assert out["payload"] == {"ts": TS, "values": {"deployments": {"currentDeployment": [GATE_ROW]}}}
    assert "kept-on-the-unit" not in json.dumps(logged)
    assert all(level == "warn" for level, _, _ in logged)


@needs_node
def test_gate_drops_rows_that_are_not_mappings():
    rows = [GATE_ROW, "kept-on-the-unit", None, ["kept-on-the-unit"], 7]
    payload = {"ts": TS, "values": {"deployments": {"updatedDeployment": rows, "currentDeployment": [GATE_ROW]}}}
    out, logged = gate({"type": "telemetry", "payload": payload})
    assert out["payload"]["values"]["deployments"] == {"updatedDeployment": [GATE_ROW], "currentDeployment": [GATE_ROW]}
    assert logged and "kept-on-the-unit" not in json.dumps(logged)
    attribute = {**GATE_ATTRIBUTES["deployments"], "picam_h265": "kept-on-the-unit", "extra": None}
    sent = attributes({"deployments": attribute})["deployments"]
    assert set(sent) == {"deploymentTopLevel"}
    assert sent["deploymentTopLevel"] == GATE_ATTRIBUTES["deployments"]["deploymentTopLevel"]


@needs_node
def test_gate_warns_once_about_a_shape_it_cannot_read():
    bad = {"type": "attributes", "payload": {"deployments": "picam_h265"}}
    run = gate_run([bad, bad])
    warnings = [text for step in run["results"] for level, text, _ in step["logged"] if level == "warn"]
    assert len(warnings) == 1 and "picam_h265" not in warnings[0]


@needs_node
@pytest.mark.parametrize("thingsboard", [
    {**GATE_THINGSBOARD, "enabled": False},
    {**GATE_THINGSBOARD, "enabled": "true"},
    {**GATE_THINGSBOARD, "enabled": None},
    {**GATE_THINGSBOARD, "enabled": 1},
], ids=["off", "string", "null", "number"])
def test_gate_sends_nothing_while_the_upload_is_off(thingsboard):
    """A message that waited in the rate limit while Share data was turned off is not sent on."""
    item = {"ts": TS, "values": {"event": GATE_TELEMETRY["event"]}}
    for msg in ({"type": "telemetry", "payload": item}, {"type": "attributes", "payload": {"sysinfo_tmVersion": "1"}}):
        [step] = run_functions([(gate_node(), msg)], context={
            "config": {"sharing": SHARING_OFF, "thingsboard": thingsboard, "deployment": GATE_PLACE},
            "tm_warned": {}})["results"]
        assert step["result"] is None and step["logged"] == []


@needs_node
def test_gate_sends_nothing_without_a_thingsboard_block():
    [step] = run_functions([(gate_node(), {"type": "telemetry", "payload": {"ts": TS, "values": {"event": {}}}})],
                           context={"config": {"sharing": SHARING_OFF}, "tm_warned": {}})["results"]
    assert step["result"] is None and step["logged"] == []


@needs_node
def test_gate_sends_only_the_type_and_the_payload():
    """Properties an upstream node left on msg (headers, cookies) would reach the http request node: none pass."""
    item = {"ts": TS, "values": {"event": GATE_TELEMETRY["event"]}}
    out, _ = gate({"type": "telemetry", "payload": item, "headers": {"x-note": "kept-on-the-unit"}, "topic": "t"})
    assert out == {"type": "telemetry", "payload": item}


def test_everything_uploaded_passes_the_gate():
    """The gate comes after the rate limit: a message waiting there is judged under the config it is sent with, the
    one the URL templates read."""
    flows, nodes = thingsboard_nodes()
    by_id = {node["id"]: node for node in flows}
    gate = named(flows, "upload gate")
    assert gate["z"] == tab_id(flows, "thingsboard")
    assert (gate["type"], gate["outputs"], gate["initialize"], gate["finalize"]) == ("function", 1, "", "")
    def into(node_id):
        return [node["id"] for node in flows if node_id in sum(node.get("wires", []), [])]

    assert by_id[ENABLED_SWITCH]["wires"] == [[RATE_LIMIT]] and into(RATE_LIMIT) == [ENABLED_SWITCH]
    assert by_id[RATE_LIMIT]["wires"] == [[gate["id"]]] and into(gate["id"]) == [RATE_LIMIT]
    assert gate["wires"] == [[PROTOCOL_SWITCH]] and into(PROTOCOL_SWITCH) == [gate["id"]]
    downstream = {node["id"] for node in reachable(by_id, [gate["id"]])}
    assert UPLOAD_REQUEST in downstream
    cut = {**by_id, gate["id"]: {**gate, "wires": [[]]}}
    starts = [node["id"] for node in nodes if node["id"] not in downstream]
    assert UPLOAD_REQUEST not in {node["id"] for node in reachable(cut, starts)}
    assert {node["id"] for node in nodes if node["type"] == "http request"} == {UPLOAD_REQUEST}


def test_upload_lists_file():
    lists = upload_lists()
    assert list(lists) == ["telemetry", "attributes", "event", "watch_camera", "watch_radar"]
    assert lists["telemetry"] == ["event", "radar", "airquality", "system_metrics", "deployments", "watch"]
    assert lists["attributes"] == ["deployments", "radarinfo", "sysinfo_tmVersion", "sysinfo_osHostname",
                                   "sysinfo_osRelease", "sysinfo_osTimeZone", "sysinfo_deviceName",
                                   "sysinfo_frigateVersion"]
    assert lists["event"] == [name for name in EVENT_COLUMNS if name not in KEPT_ON_THE_UNIT]
    assert lists["watch_camera"] == WATCH_CAMERA_COLUMNS and lists["watch_radar"] == WATCH_RADAR_COLUMNS
    assert all(len(names) == len(set(names)) for names in lists.values())
    # one name per line, so two changes that each add a field merge without touching the same line
    assert all(line.count('"') <= 2 for line in UPLOAD_LISTS.read_text().splitlines())


def test_the_gate_holds_no_list_of_its_own():
    func = gate_node()["func"]
    assert 'global.get("upload_lists")' in func
    assert "const TELEMETRY" not in func and "const ATTRIBUTES" not in func and '"sysinfo_tmVersion"' not in func


@needs_node
@pytest.mark.parametrize("lists", [
    None, {}, [], "event", {"telemetry": ["event"], "attributes": []},
    {"telemetry": "event", "attributes": [], "event": []},
    {"telemetry": ["event"], "attributes": [], "event": ["id", 7]},
    {key: names for key, names in upload_lists().items() if key != "watch_camera"},
    {**upload_lists(), "watch_radar": ["time", 7]},
], ids=["missing", "empty", "list", "text", "no-event-list", "telemetry-not-a-list", "a-name-that-is-not-text",
        "no-watch-camera-list", "watch-radar-name-not-text"])
def test_gate_sends_nothing_without_readable_lists(lists):
    msgs = [{"type": "telemetry", "payload": {"ts": TS, "values": {"event": GATE_TELEMETRY["event"]}}},
            {"type": "attributes", "payload": {"sysinfo_tmVersion": "0.9.0"}}]
    run = gate_run(msgs, lists=lists)
    assert [step["result"] for step in run["results"]] == [None, None]
    assert [entry for step in run["results"] for entry in step["logged"]] == [["warn", LISTS_WARNING, False]]
    assert run["global"]["tm_warned"] == {"upload:lists": True}


@needs_node
def test_gate_keeps_only_the_listed_event_fields():
    event = {**GATE_TELEMETRY["event"], "surprise": "kept-on-the-unit"}
    item = {"type": "telemetry", "payload": {"ts": TS, "values": {"event": event}}}
    run = gate_run([item, item])
    for step in run["results"]:
        assert step["result"]["payload"] == {"ts": TS, "values": {"event": GATE_TELEMETRY["event"]}}
    warnings = [text for step in run["results"] for _, text, _ in step["logged"]]
    assert warnings == ["ThingsBoard upload: left out event.surprise, which isn't on the list of what is shared."]
    assert "kept-on-the-unit" not in json.dumps(run["results"])
    assert run["global"]["tm_warned"] == {"upload:event.surprise": True}


@needs_node
@pytest.mark.parametrize("event", ["text", ["id"], None, 7, {"surprise": 1}],
                         ids=["text", "list", "null", "number", "no-listed-field"])
def test_gate_leaves_out_an_event_it_cannot_read(event):
    radar = GATE_TELEMETRY["radar"]
    out, _ = gate({"type": "telemetry", "payload": {"ts": TS, "values": {"event": event, "radar": radar}}})
    assert out["payload"] == {"ts": TS, "values": {"radar": radar}}
    out, _ = gate({"type": "telemetry", "payload": {"ts": TS, "values": {"event": event}}})
    assert out is None


WATCH_VALUE = {"cameras": [CAMERA_ROWS[0]], "radars": [RADAR_ROWS[0]]}


def watch_item(value):
    return {"type": "telemetry", "payload": {"ts": TICK_MS, "values": {"watch": value}}}


@needs_node
def test_gate_keeps_only_the_listed_watch_fields():
    value = {"cameras": [{**CAMERA_ROWS[0], "surprise": "kept-on-the-unit"}],
             "radars": [{**RADAR_ROWS[0], "note": "kept-on-the-unit"}], "extra": [1]}
    run = gate_run([watch_item(value), watch_item(value)])
    for step in run["results"]:
        assert step["result"]["payload"] == {"ts": TICK_MS, "values": {"watch": WATCH_VALUE}}
    warnings = [text for step in run["results"] for _, text, _ in step["logged"]]
    assert sorted(warnings) == sorted(
        f"ThingsBoard upload: left out {key}, which isn't on the list of what is shared."
        for key in ("watch.extra", "watch_camera.surprise", "watch_radar.note"))
    assert "kept-on-the-unit" not in json.dumps(run["results"])


@needs_node
@pytest.mark.parametrize("value", [
    "text", ["cameras"], None, 7, {}, {"extra": []}, {"cameras": "all", "radars": 7}, {"cameras": [], "radars": []},
    {"cameras": ["text", None, 7]}, {"cameras": [{"surprise": 1}]},
], ids=["text", "list", "null", "number", "empty", "no-listed-key", "not-lists", "no-rows", "rows-not-mappings",
        "no-listed-field"])
def test_gate_leaves_out_watch_rows_it_cannot_read(value):
    radar = GATE_TELEMETRY["radar"]
    out, _ = gate({"type": "telemetry", "payload": {"ts": TICK_MS, "values": {"watch": value, "radar": radar}}})
    assert out["payload"] == {"ts": TICK_MS, "values": {"radar": radar}}
    out, _ = gate(watch_item(value))
    assert out is None


@needs_node
def test_gate_keeps_the_list_that_has_rows():
    out, logged = gate(watch_item({"cameras": [CAMERA_ROWS[0], "text"], "radars": []}))
    assert out["payload"]["values"]["watch"] == {"cameras": [CAMERA_ROWS[0]]}
    assert logged == [["warn", "ThingsBoard upload: left out watch rows that aren't mappings.", False]]


@needs_node
def test_watch_rows_are_sent_as_one_telemetry_value():
    flows = json.loads(FLOWS.read_text())
    by_id = {node["id"]: node for node in flows}
    out, link_in, fmt = named(flows, "watch link out"), named(flows, "watch link in"), named(flows, "format watch telemetry")
    assert out["links"] == [link_in["id"]] and link_in["links"] == [out["id"]]
    assert (link_in["type"], link_in["z"], fmt["z"]) == ("link in", tab_id(flows, "thingsboard"), link_in["z"])
    assert link_in["wires"] == [[fmt["id"]]] and fmt["wires"] == [["8c521232f464d27a"]]
    group = by_id[fmt["g"]]
    assert (group["name"], group["g"], link_in["g"]) == ("watch", "2f27e270200485b9", group["id"])
    payload = {"time": TICK, "cameras": CAMERA_ROWS, "radars": RADAR_ROWS}
    [step] = run_functions([(fmt, {"payload": payload, "params": {"$time": TICK}})])["results"]
    assert step["result"] == {"payload": {"ts": TICK_MS, "values": {"watch": {"cameras": CAMERA_ROWS,
                                                                              "radars": RADAR_ROWS}}}}
    assert gate({"type": "telemetry", "payload": step["result"]["payload"]})[0]["payload"] == step["result"]["payload"]


def record_node():
    return named(json.loads(FLOWS.read_text()), "record upload result")


EARLIER = "2026-11-13T00:00:00.000Z"


@needs_node
@pytest.mark.parametrize("code, failure", [
    (200, None), (204, None),
    (401, "refused"), (403, "refused"),
    (400, "rejected"), (404, "rejected"), (429, "rejected"),
    (500, "server_error"), (503, "server_error"),
    ("ECONNREFUSED", "unreachable"), (MISSING, "unreachable"), ("401", "unreachable"),
], ids=lambda value: str(value) if value is not MISSING else "missing")
def test_upload_result_is_classed_by_status_code(code, failure):
    msg = {} if code is MISSING else {"statusCode": code}
    before = {"last_ok_at": EARLIER, "last_failure_at": EARLIER, "last_failure": "rejected"}
    run = run_functions([(record_node(), msg)], context={"tm_status": {"upload": before}})
    [step] = run["results"]
    assert step["result"] is None and step["logged"] == []
    upload = run["global"]["tm_status"]["upload"]
    assert set(upload) == {"last_ok_at", "last_failure_at", "last_failure"}
    if failure is None:
        assert upload["last_ok_at"] > EARLIER and upload["last_ok_at"].endswith("Z")
        assert (upload["last_failure_at"], upload["last_failure"]) == (EARLIER, "rejected")
    else:
        assert upload["last_ok_at"] == EARLIER
        assert upload["last_failure_at"] > EARLIER and upload["last_failure_at"].endswith("Z")
        assert upload["last_failure"] == failure


@needs_node
def test_upload_result_starts_from_nothing():
    run = run_functions([(record_node(), {"statusCode": 200})])
    upload = run["global"]["tm_status"]["upload"]
    assert upload["last_ok_at"].endswith("Z")
    assert (upload["last_failure_at"], upload["last_failure"]) == (None, None)


@needs_node
def test_upload_result_keeps_nothing_else():
    url = "https://tb.example.invalid/api/v1/tb-placeholder-0001/telemetry"
    answered = {"statusCode": 401, "payload": "tb-placeholder-0001 is not a device", "url": url,
                "headers": {"x-token": "tb-placeholder-0001"}, "responseUrl": url}
    caught = {"payload": {"values": {"event": {}}}, "url": url,
              "error": {"message": f"RequestError: connect ECONNREFUSED : {url}",
                        "source": {"id": UPLOAD_REQUEST, "type": "http request", "name": "tb post http api"}}}
    run = run_functions([(record_node(), answered), (record_node(), caught)])
    assert "tb-placeholder-0001" not in json.dumps(run["global"])
    assert "tb.example.invalid" not in json.dumps(run["global"])
    assert all(step["logged"] == [] for step in run["results"])
    assert run["global"]["tm_status"]["upload"]["last_failure"] == "unreachable"


@needs_node
def test_a_caught_error_counts_only_when_it_came_from_the_upload():
    def caught(source_id):
        return {"error": {"message": "Error", "source": {"id": source_id, "type": "function", "name": "x"}}}

    run = run_functions([(record_node(), caught(UPLOAD_REQUEST))])
    upload = run["global"]["tm_status"]["upload"]
    assert upload["last_failure"] == "unreachable" and upload["last_failure_at"].endswith("Z")
    assert upload["last_ok_at"] is None
    for other in ("4bec488857c0553f", None):
        run = run_functions([(record_node(), caught(other))])
        assert "tm_status" not in run["global"]
    run = run_functions([(record_node(), {"error": None})])
    assert "tm_status" not in run["global"]


@needs_node
def test_status_reports_the_upload():
    loaded = node_by_id(CONFIG_LOADED)
    nulls = {"last_ok_at": None, "last_failure_at": None, "last_failure": None}
    config = {"thingsboard": {"enabled": True}, "deployment": {}, "sensors": {"radars": {}}}
    out = run_functions([status_step()], context={"config": config})
    assert out["results"][0]["result"]["payload"]["upload"] == {"enabled": True, **nulls}
    out = run_functions([(record_node(), {"statusCode": 503}), status_step()], context={"config": config})
    upload = out["results"][1]["result"]["payload"]["upload"]
    assert upload == {"enabled": True, **out["global"]["tm_status"]["upload"]}
    assert upload["last_failure"] == "server_error" and upload["last_failure_at"].endswith("Z")
    off = {**config, "thingsboard": {"enabled": False}}
    out = run_functions([(loaded, {}), status_step()], context={**out["global"], "config": off})
    assert out["results"][1]["result"]["payload"]["upload"] == {"enabled": False, **nulls}
    [step] = run_functions([status_step()])["results"]
    assert step["result"]["payload"]["upload"] == {"enabled": False, **nulls}


def test_upload_result_wiring():
    flows, nodes = thingsboard_nodes()
    by_id = {node["id"]: node for node in flows}
    record = named(flows, "record upload result")
    assert record["z"] == tab_id(flows, "thingsboard")
    assert (record["type"], record["outputs"], record["wires"]) == ("function", 0, [])
    feeding = {node["id"] for node in flows if record["id"] in sum(node.get("wires", []), [])}
    assert feeding == {UPLOAD_REQUEST, TB_CATCH}
    assert by_id[UPLOAD_REQUEST]["wires"] == [["df6ac2f42ac6d8c7", record["id"]]]
    assert by_id[TB_CATCH]["wires"] == [["5fc376fb123914c0", record["id"]]]
    assert by_id[TB_CATCH]["scope"] is None  # every node on the tab; the record node keeps only the upload's
    func = record["func"]
    for forbidden in ("msg.payload", "msg.url", "msg.headers", "error.message", "node.warn", "node.error", "node.log"):
        assert forbidden not in func, forbidden


FINALIZE = "a8aeffd2e5bc17f2"  # capture-events: event finalize output
EVENT_PARAMS = "a96d834e3571c549"  # capture-events: write params for events insert
EVENT_INSERT = "61d6a19c99c60e0b"  # capture-events: tmdb.events, Prepared Statement
JSON_COLUMNS = {"entered_zones", "attributes", "provenance", "path_data", "box", "best_box"}
SCHEMA_SQL = FLOWS.parents[1] / "schema" / "schema.sql"
EVENT = {
    "id": "1761800000.123456-abc123", "camera": "camera_1_3fa9c2", "label": "car", "sub_label": None,
    "top_score": 0.91, "frame_time": 1761800004.2, "start_time": 1761800000.1, "end_time": 1761800004.3,
    "entered_zones": ["zone_near", "zone_far"], "score": 0.88, "area": 57600, "ratio": 1.78, "motionless_count": 0,
    "position_changes": 3, "attributes": {}, "deployment_id": "1761800000000-0a1b2c3d-d",
}


def finalize_msg(direction=None, speed=None, readings=None, radar="TM_RADAR_SERIAL_PORT_00", fields=MISSING,
                 source=MISSING):
    """The message "event finalize output" gets: the event under its camera's key, and what the speed nodes found."""
    found = {"status_radarMatch": speed is not None, "calc_event_direction": direction, "calc_event_speed": speed,
             "calc_radar_readings": readings}
    if source is not MISSING:
        found["calc_direction_source"] = source
    msg = {"frigate_event": {**EVENT, **({"radarName": radar} if radar else {})}, "radarEnabled": radar is not None,
           "payload": found, "event_direction_speed": found}
    if fields is not MISSING:
        msg["frigate_fields"] = fields
    return msg


def event_keys():
    [step] = run_functions([(node_by_id(FINALIZE), finalize_msg("inbound", 22.5, 7))])["results"]
    return step["keys"]


def event_insert():
    """The INSERT's columns and the parameter each one takes."""
    match = re.fullmatch(r"\s*INSERT INTO events \(([^)]*)\)\s*VALUES \((.*)\);\s*", node_by_id(EVENT_INSERT)["sql"],
                         re.DOTALL)
    return ([name.strip() for name in match[1].split(",")], [value.strip() for value in match[2].split(",")])


@needs_node
def test_event_fields_agree():
    """One list of event fields, in one order: what finalize builds, what the INSERT names, what its parameters are,
    what the table has, and (less what is kept on the unit) what the upload gate lets through."""
    assert event_keys() == EVENT_COLUMNS
    names, values = event_insert()
    assert names == EVENT_COLUMNS
    assert all(value in (f"${name}", f"json(${name})") for name, value in zip(names, values, strict=True))
    [step] = run_functions([(node_by_id(EVENT_PARAMS), {"payload": {name: None for name in EVENT_COLUMNS}})])["results"]
    assert list(step["result"]["params"]) == [f"${name}" for name in EVENT_COLUMNS]
    con = sqlite3.connect(":memory:")
    con.executescript(SCHEMA_SQL.read_text())
    assert {row[1] for row in con.execute("PRAGMA table_info(events)")} >= set(EVENT_COLUMNS)
    assert upload_lists()["event"] == [name for name in EVENT_COLUMNS if name not in KEPT_ON_THE_UNIT]


@needs_node
def test_event_params_bind_only_the_columns():
    payload = {**EVENT, "direction_calc": "inbound", "provenance": ["frigate"], "surprise": "no column"}
    del payload["sub_label"]
    [step] = run_functions([(node_by_id(EVENT_PARAMS), {"payload": payload})])["results"]
    params = step["result"]["params"]
    assert "$surprise" not in params and len(params) == len(EVENT_COLUMNS)
    assert params["$sub_label"] is None and params["$speed_calc"] is None and params["$radarName"] is None
    assert params["$entered_zones"] == '["zone_near","zone_far"]'
    assert params["$attributes"] == "{}" and params["$provenance"] == '["frigate"]'
    assert params["$top_score"] == 0.91 and params["$motionless_count"] == 0
    assert step["result"]["payload"]["entered_zones"] == ["zone_near", "zone_far"]  # the payload isn't changed


@needs_node
@pytest.mark.parametrize("column", sorted(JSON_COLUMNS))
@pytest.mark.parametrize("absent", [True, False], ids=["absent", "null"])
def test_event_params_keep_a_missing_json_column_empty(column, absent):
    """Today an absent one becomes the text "undefined", which json() refuses, so the row is lost, and a null one
    becomes the text "null"."""
    payload = {name: None for name in EVENT_COLUMNS if not (absent and name == column)}
    [step] = run_functions([(node_by_id(EVENT_PARAMS), {"payload": payload})])["results"]
    assert step["result"]["params"][f"${column}"] is None


SET_FRIGATE_EVENT = "76911cc7f28e7da2"  # capture-events: set frigate_event from payload.after
VETTED = ["amazon", "an_post", "canada_post", "dhl", "dpd", "fedex", "gls", "nzpost", "postnl", "postnord",
          "purolator", "royal_mail", "ups", "usps"]


def vet(sub_label):
    after = {"camera": "oak_ave_wide", "id": "1.0-abc", "sub_label": sub_label}
    msg = {"frigate_event": dict(after), "payload": {"type": "end", "before": dict(after), "after": dict(after)}}
    [step] = run_functions([(named(json.loads(FLOWS.read_text()), "vet sub_label"), msg)])["results"]
    return step


@needs_node
@pytest.mark.parametrize("given, kept", [
    (["amazon", 0.91], "amazon"), ("ups", "ups"), (["royal_mail", 0.5], "royal_mail"),
    (["Jane Doe", 0.97], None), ("ABC123", None), (["Amazon", 0.9], None), (["amazon ", 0.9], None),
    (["my_custom_class", 0.8], None), (None, None), ([], None), ([["amazon"], 0.9], None),
    ({"text": "amazon"}, None), (42, None), ("", None),
])
def test_only_a_vetted_sub_label_is_kept(given, kept):
    step = vet(given)
    result = step["result"]
    assert result["frigate_event"]["sub_label"] == kept
    assert result["payload"]["after"]["sub_label"] == kept and result["payload"]["before"]["sub_label"] == kept
    assert step["logged"] == []
    if kept is None and given:
        assert "Jane Doe" not in json.dumps(step) and "ABC123" not in json.dumps(step)


@needs_node
def test_vetting_survives_a_message_without_before_or_after():
    node = named(json.loads(FLOWS.read_text()), "vet sub_label")
    for payload in ({}, {"before": None, "after": None}, "text", None):
        [step] = run_functions([(node, {"frigate_event": {"sub_label": ["Jane Doe", 0.9]}, "payload": payload})])["results"]
        assert step["result"]["frigate_event"]["sub_label"] is None


def test_the_vetted_list_is_frigates_logo_labels():
    func = named(json.loads(FLOWS.read_text()), "vet sub_label")["func"]
    assert "const VETTED = " + json.dumps(VETTED) + ";" in func


def test_every_event_is_vetted_before_any_other_node_reads_it():
    flows = json.loads(FLOWS.read_text())
    by_id = {node["id"]: node for node in flows}
    vetting = named(flows, "vet sub_label")
    assert by_id[SET_FRIGATE_EVENT]["wires"] == [[vetting["id"]]]
    assert (vetting["type"], vetting["outputs"], vetting["z"]) == ("function", 1, tab_id(flows, "capture-events"))
    assert [node["id"] for node in flows if vetting["id"] in sum(node.get("wires", []), [])] == [SET_FRIGATE_EVENT]
    assert APPEND_CONFIG in {node["id"] for node in reachable(by_id, [vetting["id"]])}


FRIGATE_CONFIG = {
    "ui": {"unit_system": "imperial", "timezone": None},
    "cameras": {
        "oak_ave_wide": {"detect": {"width": 1280, "height": 720, "fps": 10}, "zones": {}},
        "side_gate": {"detect": {"width": 1920, "height": 1080}},
        "no_size": {"detect": {"width": 0, "height": None}},
        "text_size": {"detect": {"width": "1280", "height": "720"}},
        "odd": "text",
    },
}
FACTS = {"unit_system": "imperial", "detect": {"oak_ave_wide": {"width": 1280, "height": 720},
                                                "side_gate": {"width": 1920, "height": 1080}}}


def keep_facts(msg, flow=None):
    node = named(json.loads(FLOWS.read_text()), "keep frigate facts")
    run = run_functions([(node, msg)], flow={} if flow is None else flow)
    return run["results"][0], run["flow"]


@needs_node
@pytest.mark.parametrize("tries", [None, 5], ids=["first-read", "a-later-try"])
def test_frigate_facts_are_kept(tries):
    msg = {"statusCode": 200, "payload": FRIGATE_CONFIG}
    if tries is not None:
        msg["tries"] = tries
    step, flow = keep_facts(msg)
    assert flow == {"frigate_facts": FACTS}
    assert step["result"] is None and step["logged"] == []


@needs_node
@pytest.mark.parametrize("ui, expected", [
    ({"unit_system": "metric"}, "metric"), ({"unit_system": "imperial"}, "imperial"), ({"unit_system": "Metric"}, None),
    ({"unit_system": None}, None), ({}, None), (None, None), ("metric", None),
])
def test_the_unit_system_is_one_of_frigates_two_or_unknown(ui, expected):
    _, flow = keep_facts({"statusCode": 200, "payload": {**FRIGATE_CONFIG, "ui": ui}})
    assert flow["frigate_facts"]["unit_system"] == expected


UNREADABLE_ANSWERS = [
    {"statusCode": 500, "payload": FRIGATE_CONFIG}, {"statusCode": 200, "payload": "<html>"},
    {"statusCode": 200, "payload": None}, {"statusCode": 200, "payload": []}, {"payload": FRIGATE_CONFIG},
    {"statusCode": 200, "payload": {"ui": {"unit_system": "metric"}}},
    {"statusCode": "ECONNREFUSED", "payload": "Error: connect ECONNREFUSED : http://frigate:5000/api/config"},
]
UNREADABLE_IDS = ["error", "text", "null", "list", "no-status", "no-cameras", "refused"]


@needs_node
@pytest.mark.parametrize("msg", UNREADABLE_ANSWERS, ids=UNREADABLE_IDS)
def test_an_answer_that_cannot_be_read_keeps_the_last_facts(msg):
    """With facts in hand a failed read asks nothing more: the ten-minute read comes round."""
    before = {"frigate_facts": {"unit_system": "metric", "detect": {"oak_ave_wide": {"width": 640, "height": 360}}}}
    step, flow = keep_facts({**msg, "tries": 3}, flow=json.loads(json.dumps(before)))
    assert flow == before and step["result"] is None and step["logged"] == []


@needs_node
@pytest.mark.parametrize("msg", UNREADABLE_ANSWERS, ids=UNREADABLE_IDS)
def test_without_facts_an_answer_that_cannot_be_read_asks_again(msg):
    """Frigate says it is online before its API listens, so the read that follows fails; it is tried again.

    The retry is a new message holding only its count: the failed one carries the answer's headers, which the request
    node would send back to Frigate as request headers.
    """
    answer = {**msg, "headers": {"content-type": "text/html", "server": "nginx"}, "responseUrl": "x", "_msgid": "a1"}
    step, flow = keep_facts(answer)
    assert step["result"] == [None, {"tries": 1}]
    assert flow == {} and step["logged"] == []


@needs_node
@pytest.mark.parametrize("tries, expected", [
    (1, 2), (2, 3), (19, 20), (0, 1), (None, 1), ("3", 1), (2.5, 1), (-1, 1), ([4], 1),
], ids=["1", "2", "19", "0", "null", "text", "fraction", "negative", "list"])
def test_each_try_counts_up_in_a_new_message(tries, expected):
    step, _ = keep_facts({"statusCode": 500, "payload": "<html>", "headers": {"server": "nginx"}, "tries": tries})
    assert step["result"] == [None, {"tries": expected}]


@needs_node
@pytest.mark.parametrize("tries", [20, 21])
def test_it_stops_asking_after_twenty_tries(tries):
    """Node-RED's request node logs each failed try, so the tries are bounded."""
    step, flow = keep_facts({"statusCode": 500, "payload": "<html>", "tries": tries})
    assert step["result"] is None and flow == {} and step["logged"] == []


def forget_facts(payload, flow):
    node = named(json.loads(FLOWS.read_text()), "forget frigate facts")
    run = run_functions([(node, {"topic": "frigate/available", "payload": payload, "retain": True})], flow=flow)
    return run["results"][0], run["flow"]


@needs_node
@pytest.mark.parametrize("payload", ["stopped", "offline", "restarting", ""])
def test_frigate_going_away_forgets_the_facts(payload):
    """A box or a unit from before Frigate restarts is never applied after it: a new detect size may come with it."""
    step, flow = forget_facts(payload, {"frigate_facts": json.loads(json.dumps(FACTS)), "other": 1})
    assert flow == {"other": 1}
    assert step["result"] is None and step["logged"] == []


@needs_node
def test_after_forgetting_the_next_failed_read_asks_again():
    flows = json.loads(FLOWS.read_text())
    forget, keep = named(flows, "forget frigate facts"), named(flows, "keep frigate facts")
    run = run_functions([(forget, {"payload": "offline"}), (keep, {"statusCode": 500, "payload": "<html>"})],
                        flow={"frigate_facts": json.loads(json.dumps(FACTS))})
    assert [step["result"] for step in run["results"]] == [None, [None, {"tries": 1}]]
    assert run["flow"] == {}


def test_frigate_facts_are_read_at_start_when_frigate_comes_back_and_every_ten_minutes():
    flows = json.loads(FLOWS.read_text())
    by_id = {node["id"]: node for node in flows}
    keep = named(flows, "keep frigate facts")
    forget = named(flows, "forget frigate facts")
    [request] = [node for node in flows if node["type"] == "http request" and keep["id"] in sum(node["wires"], [])]
    assert (request["method"], request["url"], request["ret"]) == ("GET", "http://frigate:5000/api/config", "obj")
    sources = [node for node in flows if request["id"] in sum(node.get("wires", []), [])]
    assert sorted(node["type"] for node in sources) == ["delay", "inject", "switch"]
    inject = next(node for node in sources if node["type"] == "inject")
    assert (inject["once"], str(inject["onceDelay"]), str(inject["repeat"])) == (True, "10", "600")
    switch = next(node for node in sources if node["type"] == "switch")
    assert (switch["property"], switch["rules"]) == ("payload", [{"t": "eq", "v": "online", "vt": "str"},
                                                                 {"t": "else"}])
    assert (switch["outputs"], switch["wires"]) == (2, [[request["id"]], [forget["id"]]])
    [available] = [node for node in flows if switch["id"] in sum(node.get("wires", []), [])]
    assert (available["type"], available["topic"], available["broker"]) == ("mqtt in", "frigate/available",
                                                                           "a5d65dd0e3566daa")
    delay = next(node for node in sources if node["type"] == "delay")
    assert (delay["pauseType"], str(delay["timeout"]), delay["timeoutUnits"]) == ("delay", "15", "seconds")
    assert (keep["outputs"], keep["wires"]) == (2, [[], [delay["id"]]])
    assert [node["id"] for node in flows if delay["id"] in sum(node.get("wires", []), [])] == [keep["id"]]
    assert (forget["type"], forget["outputs"], forget["wires"]) == ("function", 1, [[]])
    capture = tab_id(flows, "capture-events")
    nodes = (keep, request, inject, switch, available, delay, forget)
    assert {node["z"] for node in nodes} == {capture}
    group = by_id[keep["g"]]
    assert group["name"] == "frigate facts" and {node["g"] for node in nodes} == {group["id"]}
    assert set(group["nodes"]) == {node["id"] for node in nodes}
    for node in nodes:
        assert group["x"] < node["x"] < group["x"] + group["w"] and group["y"] < node["y"] < group["y"] + group["h"]


AFTER = {
    "id": "1761800000.123456-abc123", "camera": "oak_ave_wide", "label": "car", "sub_label": None,
    "frame_time": 1761800004.2, "start_time": 1761800000.1, "end_time": 1761800004.3,
    "box": [960, 360, 1280, 540], "snapshot": {"frame_time": 1761800002.1, "box": [320, 180, 640, 360], "score": 0.9},
    "average_estimated_speed": 38.6, "velocity_angle": 172.4, "entered_zones": ["zone_near", "zone_far"],
    "path_data": [[[0.25, 0.5], 1761800000.1], [[0.5, 0.52], 1761800002.1], [[0.8751, 0.55], 1761800004.2]],
}
METRIC = {"unit_system": "metric", "detect": {"oak_ave_wide": {"width": 1280, "height": 720}}}
FIELDS = {
    "path_data": AFTER["path_data"], "box": [0.75, 0.5, 0.25, 0.25], "best_box": [0.25, 0.25, 0.25, 0.25],
    "best_frame_time": 1761800002.1, "frigate_speed": 38.6, "frigate_speed_unit": "kph",
    "frigate_velocity_angle": 172.4,
}
NO_FIELDS = dict.fromkeys(FIELDS)


def frigate_fields(facts=METRIC, **changes):
    node = named(json.loads(FLOWS.read_text()), "frigate fields")
    msg = {"frigate_event": {**AFTER, **changes}, "payload": {"type": "end"}}
    [step] = run_functions([(node, msg)], flow={} if facts is None else {"frigate_facts": facts})["results"]
    assert step["logged"] == []
    assert step["result"]["frigate_event"] == msg["frigate_event"]  # the event itself is left alone
    return step["result"]["frigate_fields"]


@needs_node
def test_frigate_fields_from_an_end_message():
    fields = frigate_fields()
    assert fields == FIELDS and list(fields) == list(FIELDS)
    assert "oak_ave_wide" not in json.dumps(fields)


@needs_node
@pytest.mark.parametrize("facts", [None, {"unit_system": None, "detect": {}},
                                   {"unit_system": "metric", "detect": {"another_camera": {"width": 1280, "height": 720}}}],
                         ids=["not-read-yet", "empty", "another-camera"])
def test_without_the_cameras_facts_there_are_no_boxes(facts):
    fields = frigate_fields(facts)
    assert fields["box"] is None and fields["best_box"] is None
    assert fields["path_data"] == AFTER["path_data"] and fields["best_frame_time"] == 1761800002.1
    assert fields["frigate_speed"] == 38.6 and fields["frigate_velocity_angle"] == 172.4
    assert fields["frigate_speed_unit"] == ("kph" if facts and facts["unit_system"] else None)


@needs_node
def test_imperial_is_mph():
    assert frigate_fields({**METRIC, "unit_system": "imperial"})["frigate_speed_unit"] == "mph"


@needs_node
@pytest.mark.parametrize("speed", [0, 0.0, -3.2, None, "38", MISSING])
def test_frigates_zero_is_no_estimate(speed):
    after = dict(AFTER)
    if speed is MISSING:
        del after["average_estimated_speed"]
    else:
        after["average_estimated_speed"] = speed
    node = named(json.loads(FLOWS.read_text()), "frigate fields")
    [step] = run_functions([(node, {"frigate_event": after})], flow={"frigate_facts": METRIC})["results"]
    fields = step["result"]["frigate_fields"]
    assert (fields["frigate_speed"], fields["frigate_speed_unit"], fields["frigate_velocity_angle"]) == (None, None, None)
    assert fields["box"] == FIELDS["box"]


@needs_node
def test_a_long_path_keeps_a_hundred_points_first_and_last():
    path = [[[round(index / 250, 4), 0.5], 1761800000.0 + index] for index in range(250)]
    kept = frigate_fields(path_data=path)["path_data"]
    assert kept == [path[int(index * 249 / 99 + 0.5)] for index in range(100)]
    assert kept[0] == path[0] and kept[-1] == path[-1]
    assert frigate_fields(path_data=path[:100])["path_data"] == path[:100]
    assert len(frigate_fields(path_data=path[:101])["path_data"]) == 100


@needs_node
def test_a_path_holds_numbers_only():
    good = AFTER["path_data"]
    mixed = [good[0], [[0.1, 0.2], "t"], ["x"], [[0.1], 1.0], [[None, 0.2], 1.0], {"a": 1}, "Jane Doe", good[1],
             [[0.1, 0.2, 0.3], 1.0], [[0.1, 0.2], 1.0, 2.0], good[2]]
    assert frigate_fields(path_data=mixed)["path_data"] == good
    for path in ("Jane Doe", None, {}, [], [["x"]], 7):
        assert frigate_fields(path_data=path)["path_data"] is None


@needs_node
@pytest.mark.parametrize("box", [[960, 360, 1280], [960, 360, 1280, "540"], [1280, 360, 960, 540], None, "box",
                                 [960, 360, 1280, 540, 1], [960, 360, 1280, None]])
def test_a_box_that_is_not_four_numbers_in_order_is_empty(box):
    fields = frigate_fields(box=box, snapshot={"frame_time": "soon", "box": box})
    assert (fields["box"], fields["best_box"], fields["best_frame_time"]) == (None, None, None)


@needs_node
@pytest.mark.parametrize("snapshot", [None, "text", {}, MISSING])
def test_an_event_without_a_best_frame(snapshot):
    after = {key: value for key, value in AFTER.items() if key != "snapshot"}
    node = named(json.loads(FLOWS.read_text()), "frigate fields")
    event = after if snapshot is MISSING else {**after, "snapshot": snapshot}
    [step] = run_functions([(node, {"frigate_event": event})], flow={"frigate_facts": METRIC})["results"]
    fields = step["result"]["frigate_fields"]
    assert (fields["best_box"], fields["best_frame_time"], fields["box"]) == (None, None, FIELDS["box"])


@needs_node
def test_frigate_fields_survive_an_event_that_is_not_a_mapping():
    node = named(json.loads(FLOWS.read_text()), "frigate fields")
    for event in (None, "text", []):
        [step] = run_functions([(node, {"frigate_event": event})], flow={"frigate_facts": METRIC})["results"]
        assert step["result"]["frigate_fields"] == NO_FIELDS


def test_frigate_fields_are_worked_out_while_frigates_name_is_on_the_event():
    flows = json.loads(FLOWS.read_text())
    fields, vetting = named(flows, "frigate fields"), named(flows, "vet sub_label")
    assert vetting["wires"] == [[fields["id"]]] and fields["wires"] == [[APPEND_CONFIG]]
    assert [node["id"] for node in flows if APPEND_CONFIG in sum(node.get("wires", []), [])] == [fields["id"]]


MEDIAN = "c123fc5ed5e14e8a"  # capture-events: calculate median per direction
MATCH = "673e45159a2dfccf"  # capture-events: match radar speed to event, assign direction
DOV_PARAMS = "1acba66197b7b0fa"  # capture-radar: write params for radar_dov insert
FRIGATE_MESSAGE = {"type": "end", "before": {"id": "1.0-abc"}, "after": {"id": "1.0-abc"}}


def match(zone_direction, medians, counts=None, radar=True):
    event = {"id": "1.0-abc", **({"calc_zone_direction": zone_direction} if zone_direction else {})}
    msg = {"frigate_event": event, "radarEnabled": radar, "payload": medians if radar else FRIGATE_MESSAGE,
           "radar_reading_counts": counts or {}}
    [step] = run_functions([(node_by_id(MATCH), msg)])["results"]
    found = step["result"]["payload"]
    return (found.get("calc_event_direction"), found.get("calc_event_speed"), found["status_radarMatch"],
            found.get("calc_radar_readings"), found.get("calc_direction_source"))


@needs_node
@pytest.mark.parametrize("zones, medians, counts, expected", [
    ("inbound", {"inbound": 22.5, "outbound": -30.0}, {"inbound": 7, "outbound": 2},
     ("inbound", 22.5, True, 7, "zones_radar")),
    ("inbound", {"inbound": 22.5}, {"inbound": 4}, ("inbound", 22.5, True, 4, "zones_radar")),
    ("inbound", {"outbound": -30.0}, {"outbound": 5}, ("inbound", None, False, None, "zones_radar_opposite")),
    (None, {"outbound": -30.0}, {"outbound": 5}, ("outbound", -30.0, True, 5, "radar")),
    (None, {"inbound": 22.5, "outbound": -30.0}, {"inbound": 7, "outbound": 2}, (None, None, False, None, None)),
    ("outbound", {}, {}, ("outbound", None, False, None, "zones")),
    (None, {}, {}, (None, None, False, None, None)),
    ("inbound", {"inbound": 0}, {"inbound": 3}, ("inbound", 0, True, 3, "zones_radar")),
    (None, {"outbound": 0}, {"outbound": 1}, ("outbound", 0, True, 1, "radar")),
    ("inbound", {"inbound": 0, "outbound": -30.0}, {"inbound": 3, "outbound": 2}, ("inbound", 0, True, 3, "zones_radar")),
    # a reading with no direction is grouped under "null" by "calculate median per direction"
    ("outbound", {"inbound": 22.5, "null": 3.0}, {"inbound": 4, "null": 1},
     ("outbound", None, False, None, "zones_radar_opposite")),
], ids=["match-of-two", "match", "other-direction-only", "radars-direction", "two-and-no-zones", "none", "nothing",
        "zero-match", "zero-assigned", "zero-of-two", "other-direction-and-no-direction"])
def test_direction_and_speed_with_a_radar(zones, medians, counts, expected):
    assert match(zones, medians, counts) == expected


@needs_node
def test_the_statuses_stay_when_the_radar_saw_only_the_other_direction():
    event = {"id": "1.0-abc", "calc_zone_direction": "inbound"}
    found = {}
    for medians in ({"outbound": -30.0}, {"outbound": -30.0, "null": 3.0}):
        msg = {"frigate_event": event, "radarEnabled": True, "payload": medians, "radar_reading_counts": {}}
        [step] = run_functions([(node_by_id(MATCH), msg)])["results"]
        found[len(medians)] = step["result"]["payload"]
    assert "status_match_event_radar_direction" not in found[1] and found[1]["status_radarMatch"] is False
    assert found[2]["status_match_event_radar_direction"] == "radar_speed_direction_mismatch"


@needs_node
@pytest.mark.parametrize("zones", ["inbound", "outbound", None])
def test_a_camera_without_a_radar_gets_its_direction_from_the_zones(zones):
    assert match(zones, None, radar=False) == (zones, None, False, None, "zones" if zones else None)


NO_ZONE = "entered no zone"
DIRECTION_TABLE = [
    # zones' direction (or NO_ZONE), radar medians (None: no enabled radar)
    #   -> direction_calc, direction_source, speed_calc, speed_source; Frigate's speed is 38.6 kph, 23.98 mph
    ("outbound", {"outbound": -30.0, "inbound": 20.0}, ("outbound", "zones_radar", -30.0, "radar")),
    ("inbound", {"inbound": 22.5}, ("inbound", "zones_radar", 22.5, "radar")),
    ("outbound", {"inbound": 22.5}, ("outbound", "zones_radar_opposite", -23.98, "frigate")),
    ("inbound", {"outbound": -30.0}, ("inbound", "zones_radar_opposite", 23.98, "frigate")),
    ("outbound", {}, ("outbound", "zones", -23.98, "frigate")),
    ("inbound", None, ("inbound", "zones", 23.98, "frigate")),
    ("outbound", None, ("outbound", "zones", -23.98, "frigate")),
    (None, {"outbound": -30.0}, ("outbound", "radar", -30.0, "radar")),
    (None, {"inbound": 0}, ("inbound", "radar", 0, "radar")),
    (None, {"inbound": 22.5, "outbound": -30.0}, (None, None, 23.98, "frigate")),
    (None, {}, (None, None, 23.98, "frigate")),
    (None, None, (None, None, 23.98, "frigate")),
    (NO_ZONE, None, (None, None, 23.98, "frigate")),
]
DIRECTION_IDS = ["zones-radar-of-two", "zones-radar", "opposite-outbound", "opposite-inbound", "zones-radar-none",
                 "zones-no-radar-inbound", "zones-no-radar-outbound", "radar", "radar-zero", "no-direction-two",
                 "no-direction-none", "no-direction-no-radar", "no-zone"]


def direction_and_speed(zones, medians):
    """The match node (or, for an object that entered no zone, the skip node), then "event finalize output"."""
    radar = medians is not None
    event = {**EVENT, **({"radarName": "TM_RADAR_SERIAL_PORT_00"} if radar else {}),
             **({"calc_zone_direction": zones} if zones not in (None, NO_ZONE) else {})}
    msg = {"frigate_event": event, "radarEnabled": radar, "payload": medians if radar else FRIGATE_MESSAGE,
           "radar_reading_counts": {direction: 3 for direction in (medians or {})}}
    node = named(json.loads(FLOWS.read_text()), "skip camera direction calc AND radar lookup") if zones == NO_ZONE \
        else node_by_id(MATCH)
    [step] = run_functions([(node, msg)])["results"]
    found = step["result"]["payload"]
    payload, step, _ = finalize({**step["result"], "event_direction_speed": found, "frigate_fields": FIELDS})
    assert step["logged"] == []
    return payload


@needs_node
@pytest.mark.parametrize("zones, medians, expected", DIRECTION_TABLE, ids=DIRECTION_IDS)
def test_direction_source_says_how_the_direction_was_decided(zones, medians, expected):
    payload = direction_and_speed(zones, medians)
    assert (payload["direction_calc"], payload["direction_source"], payload["speed_calc"],
            payload["speed_source"]) == expected


@needs_node
@pytest.mark.parametrize("zones, medians, expected", DIRECTION_TABLE, ids=DIRECTION_IDS)
def test_speed_calc_is_negative_only_when_the_direction_is_outbound(zones, medians, expected):
    """One rule for every event: a negative speed_calc means outbound, and without a direction the speed is
    Frigate's, positive, and its sign says nothing."""
    payload = direction_and_speed(zones, medians)
    speed, direction = payload["speed_calc"], payload["direction_calc"]
    if speed:
        assert (speed < 0) == (direction == "outbound")
    if direction is None:
        assert payload["speed_source"] in (None, "frigate") and (speed is None or speed >= 0)
    if payload["speed_source"] == "radar":
        assert direction is not None


@needs_node
def test_medians_come_with_the_number_of_readings():
    rows = [{"direction": "inbound", "velocity": value, "unit": "mph"} for value in (21.0, 22.0, 26.0)]
    rows += [{"direction": "outbound", "velocity": value, "unit": "mph"} for value in (-30.0, -32.0)]
    [step] = run_functions([(node_by_id(MEDIAN), {"payload": rows})])["results"]
    assert step["result"]["payload"] == {"inbound": 22.0, "outbound": -31.0}
    assert step["result"]["radar_reading_counts"] == {"inbound": 3, "outbound": 2}
    [step] = run_functions([(node_by_id(MEDIAN), {"payload": []})])["results"]
    assert step["result"]["payload"] == {} and step["result"]["radar_reading_counts"] == {}


@needs_node
def test_the_last_unit_each_radar_reported_is_remembered():
    reading = {"time": 1761800000.5, "unit": "mph", "direction": "inbound", "DetectedObjectVelocity": 21.3,
               "radarName": "TM_RADAR_SERIAL_PORT_00", "deployment_id": "1761800000000-0a1b2c3d-d"}
    other = {**reading, "radarName": "TM_RADAR_SERIAL_PORT_01", "unit": "kmph"}
    no_unit = {key: value for key, value in reading.items() if key != "unit"}
    node = node_by_id(DOV_PARAMS)
    run = run_functions([(node, {"payload": dict(reading)}), (node, {"payload": other}), (node, {"payload": no_unit})])
    assert run["global"]["radar_units"] == {"TM_RADAR_SERIAL_PORT_00": "mph", "TM_RADAR_SERIAL_PORT_01": "kmph"}
    assert run["results"][0]["result"]["params"] == {
        "$time": 1761800000.5, "$unit": "mph", "$direction": "inbound", "$velocity": 21.3,
        "$radarName": "TM_RADAR_SERIAL_PORT_00", "$deployment_id": "1761800000000-0a1b2c3d-d"}


RADARS_ON = {"TM_RADAR_SERIAL_PORT_00": {"enabled": True}}
NO_SPEED = {"speed_calc": None, "speed_unit": None, "speed_source": None, "radar_readings": None}


def finalize(msg, radars=None, units=None):
    context = {"config": {"sensors": {"radars": RADARS_ON if radars is None else radars}},
               "radar_units": units or {}, "tm_warned": {}}
    run = run_functions([(node_by_id(FINALIZE), msg)], context=context)
    [step] = run["results"]
    payload = step["result"]["payload"]
    return {key: payload.get(key) for key in step["keys"]}, step, run["global"]


def speed_of(payload):
    return {key: payload[key] for key in NO_SPEED}


@needs_node
def test_a_radar_speed_is_saved_with_frigates_beside_it():
    payload, step, _ = finalize(finalize_msg("inbound", 22.5, 7, fields=FIELDS), units={"TM_RADAR_SERIAL_PORT_00": "mph"})
    assert list(payload) == EVENT_COLUMNS and step["logged"] == []
    assert speed_of(payload) == {"speed_calc": 22.5, "speed_unit": "mph", "speed_source": "radar", "radar_readings": 7}
    assert {key: payload[key] for key in FIELDS} == FIELDS
    assert payload["direction_calc"] == "inbound" and payload["provenance"] == ["frigate", "radar"]


@needs_node
@pytest.mark.parametrize("direction, units, expected", [
    ("outbound", {}, {"speed_calc": -23.98, "speed_unit": "mph"}),
    ("inbound", {}, {"speed_calc": 23.98, "speed_unit": "mph"}),
    (None, {}, {"speed_calc": 23.98, "speed_unit": "mph"}),
    ("outbound", {"TM_RADAR_SERIAL_PORT_00": "mps"}, {"speed_calc": -10.72, "speed_unit": "mps"}),
])
def test_frigates_speed_fills_in_when_the_radar_gave_none(direction, units, expected):
    payload, step, _ = finalize(finalize_msg(direction, None, None, fields=FIELDS), units=units)
    assert speed_of(payload) == {**expected, "speed_source": "frigate", "radar_readings": None}
    assert payload["frigate_speed"] == 38.6 and payload["frigate_speed_unit"] == "kph"
    assert payload["provenance"] == ["frigate"] and step["logged"] == []


@needs_node
@pytest.mark.parametrize("radars", [{}, {"TM_RADAR_SERIAL_PORT_00": {"enabled": False}},
                                    {"TM_RADAR_SERIAL_PORT_00": None}, "text"],
                         ids=["none", "disabled", "empty-entry", "not-a-mapping"])
def test_a_device_without_a_radar_keeps_frigates_unit(radars):
    msg = finalize_msg("outbound", None, None, radar=None, fields=FIELDS)
    payload, _, _ = finalize(msg, radars=radars)
    assert speed_of(payload) == {"speed_calc": -38.6, "speed_unit": "kph", "speed_source": "frigate",
                                 "radar_readings": None}
    assert payload["radarName"] is None


@needs_node
def test_a_camera_without_a_radar_uses_the_units_of_the_devices_radar():
    """One device's speed_calc stays in one unit."""
    imperial = {**FIELDS, "frigate_speed": 30.0, "frigate_speed_unit": "mph"}
    msg = finalize_msg("inbound", None, None, radar=None, fields=imperial)
    radars = {"TM_RADAR_SERIAL_PORT_01": {"enabled": True}, "TM_RADAR_SERIAL_PORT_00": {"enabled": False}}
    payload, _, _ = finalize(msg, radars=radars, units={"TM_RADAR_SERIAL_PORT_01": "kmph"})
    assert speed_of(payload) == {"speed_calc": 48.28, "speed_unit": "kmph", "speed_source": "frigate",
                                 "radar_readings": None}


@needs_node
@pytest.mark.parametrize("direction, source, expected", [
    ("inbound", "zones_radar", "zones_radar"), ("outbound", "zones", "zones"),
    ("outbound", "zones_radar_opposite", "zones_radar_opposite"), ("inbound", "radar", "radar"),
    (None, "zones", None), ("inbound", "frigate", None), ("inbound", "", None), ("inbound", None, None),
    ("inbound", MISSING, None), ("inbound", ["zones"], None),
], ids=["zones-radar", "zones", "opposite", "radar", "no-direction", "other-word", "empty", "null", "missing", "list"])
def test_direction_source_is_one_of_four_words_or_empty(direction, source, expected):
    payload, step, _ = finalize(finalize_msg(direction, None, None, fields=FIELDS, source=source))
    assert payload["direction_source"] == expected and list(payload)[-1] == "direction_source"
    assert step["logged"] == []


@needs_node
def test_a_radar_speed_of_zero_is_saved():
    payload, _, _ = finalize(finalize_msg("inbound", 0, 3, fields=FIELDS))
    assert speed_of(payload) == {"speed_calc": 0, "speed_unit": "mph", "speed_source": "radar", "radar_readings": 3}


@needs_node
@pytest.mark.parametrize("fields", [
    {**FIELDS, "frigate_speed_unit": None}, {**FIELDS, "frigate_speed": None, "frigate_speed_unit": None,
                                             "frigate_velocity_angle": None}, NO_FIELDS, MISSING, None, "text",
], ids=["unit-not-read", "no-estimate", "nothing", "missing", "null", "text"])
def test_no_speed_without_a_radar_speed_or_a_usable_frigate_speed(fields):
    payload, step, _ = finalize(finalize_msg("inbound", None, None, fields=fields))
    assert speed_of(payload) == NO_SPEED and step["logged"] == []
    assert list(payload) == EVENT_COLUMNS
    expected = fields if isinstance(fields, dict) else NO_FIELDS
    assert {key: payload[key] for key in FIELDS} == expected


@needs_node
def test_a_radar_unit_the_flow_cannot_convert_to_gets_no_fallback_and_one_warning():
    msg = finalize_msg("inbound", None, None, fields=FIELDS)
    context = {"config": {"sensors": {"radars": RADARS_ON}}, "radar_units": {"TM_RADAR_SERIAL_PORT_00": "furlongs"},
               "tm_warned": {}}
    run = run_functions([(node_by_id(FINALIZE), msg), (node_by_id(FINALIZE), msg)], context=context)
    for step in run["results"]:
        assert step["result"]["payload"].get("speed_calc") is None
        assert step["result"]["payload"].get("speed_source") is None
    warnings = [text for step in run["results"] for _, text, _ in step["logged"]]
    assert warnings == ["Frigate's speed wasn't used for speed_calc: this flow can't convert to the radar's unit furlongs."]
    assert run["global"]["tm_warned"] == {"speed_unit:furlongs": True}


@needs_node
def test_event_params_turn_the_new_lists_into_json_text():
    payload, _, _ = finalize(finalize_msg("inbound", 22.5, 7, fields=FIELDS))
    [step] = run_functions([(node_by_id(EVENT_PARAMS), {"payload": payload})])["results"]
    params = step["result"]["params"]
    assert json.loads(params["$path_data"]) == FIELDS["path_data"]
    assert params["$box"] == "[0.75,0.5,0.25,0.25]" and params["$best_box"] == "[0.25,0.25,0.25,0.25]"
    assert params["$radar_readings"] == 7 and params["$speed_source"] == "radar"


def run_chain(names_or_ids, msg, context, flow):
    """Run nodes one after another, each on the message the one before returned; None if one of them drops it."""
    flows = json.loads(FLOWS.read_text())
    by_id = {node["id"]: node for node in flows}
    for name in names_or_ids:
        node = by_id.get(name) or named(flows, name)
        run = run_functions([(node, msg)], context=context, flow=flow)
        msg, context, flow = run["results"][0]["result"], run["global"], run["flow"]
        if msg is None:
            return None
    return msg


@needs_node
def test_a_made_up_event_on_a_camera_without_a_radar_becomes_a_row():
    """The whole chain of function nodes, then the node's own INSERT against the migrated schema."""
    config = config_with_cameras({"camera_1_3fa9c2": {"frigate_camera": "oak_ave_wide", "enabled": True}})
    config["sensors"]["radars"] = {}
    _, context = load_config(config)
    after = {**AFTER, "sub_label": ["Jane Doe", 0.97], "entered_zones": ["zone_near", "zone_far"], "top_score": 0.91,
             "score": 0.88, "area": 57600, "ratio": 1.78, "motionless_count": 0, "position_changes": 3,
             "attributes": {}}
    msg = {"frigate_event": after, "payload": {"type": "end", "before": dict(after), "after": after}}
    msg = run_chain(["vet sub_label", "frigate fields", APPEND_CONFIG,
                     "calculate direction based on frigate event zones", MATCH], msg, context,
                    {"frigate_facts": METRIC})
    msg = {**msg, "event_direction_speed": msg["payload"]}
    msg = run_chain([FINALIZE, EVENT_PARAMS], msg, context, {})
    con = sqlite3.connect(":memory:")
    con.executescript(SCHEMA_SQL.read_text())
    con.execute(node_by_id(EVENT_INSERT)["sql"], {key[1:]: value for key, value in msg["params"].items()})
    row = con.execute("SELECT camera, sub_label, direction_calc, speed_calc, speed_unit, speed_source, radar_readings, "
                      "frigate_speed, frigate_speed_unit, json_array_length(path_data), json_extract(box, '$[0]'), "
                      "best_frame_time, radarName, direction_source FROM events").fetchone()
    assert row == ("camera_1_3fa9c2", None, "outbound", -38.6, "kph", "frigate", None, 38.6, "kph", 3, 0.75,
                   1761800002.1, None, "zones")
    assert "Jane Doe" not in json.dumps(msg) and "oak_ave_wide" not in json.dumps(msg["payload"])


SPEED_STATS = "584504e6c8935eaf"  # ui-monitoring: query events, daily cum car counts in zone_radar with speed_calc


@needs_node
def test_the_car_speed_statistics_count_each_source():
    [step] = run_functions([(node_by_id(SPEED_STATS), {"payload": {}})],
                           flow={"camera_selection": "camera_1_3fa9c2"})["results"]
    con = sqlite3.connect(":memory:")
    con.executescript(SCHEMA_SQL.read_text())
    # 05:00 today, local time: inside "since 04:00 today" whenever the test runs
    today = datetime.now().replace(hour=5, minute=0, second=0, microsecond=0).timestamp()
    zones = '["zone_capture", "zone_radar"]'
    rows = [("a", 22.0, "radar"), ("b", -31.0, "radar"), ("c", 27.0, None), ("d", 24.5, "frigate"),
            ("e", -19.0, "frigate"), ("f", None, None)]
    con.executemany("INSERT INTO events (id, camera, label, frame_time, entered_zones, speed_calc, speed_source) "
                    "VALUES (?, 'camera_1_3fa9c2', 'car', ?, ?, ?, ?)",
                    [(name, today, zones, speed, source) for name, speed, source in rows])
    con.row_factory = sqlite3.Row
    result = dict(con.execute(step["result"]["topic"]).fetchone())
    assert list(result)[:3] == ["count", "count_radar", "count_frigate"]
    assert (result["count"], result["count_radar"], result["count_frigate"]) == (5, 3, 2)
    assert result["max_speed"] == 31.0


# The watch log: what Frigate's stats reports and the radar facts add up to over five minutes, one row each in
# watch_camera and watch_radar. "keep frigate stats" adds the reports up; the mark node starts and closes the windows.


def camera_stats(camera_fps=5.0, detection_enabled=True, **changes):
    return {"camera_fps": camera_fps, "process_fps": 4.5, "skipped_fps": 0.0, "detection_fps": 0.5,
            "detection_enabled": detection_enabled, "pid": 123, "ffmpeg_pid": 456, **changes}


def keep_stats(payloads, window=MISSING):
    """Run "keep frigate stats" on each payload in turn, with one camera that config.yml lists under another key."""
    flow = {} if window is None else {"watch_window": copy.deepcopy(EMPTY_WINDOW if window is MISSING else window)}
    node = named(json.loads(FLOWS.read_text()), "keep frigate stats")
    return run_functions([(node, {"topic": "frigate/stats", "payload": payload}) for payload in payloads],
                         context={"frigate_cameras": {"oak_ave_wide": "camera_1_3fa9c2"}, "tm_warned": {}}, flow=flow)


@needs_node
def test_reports_are_added_up_under_the_cameras_key():
    run = keep_stats([
        {"cameras": {"oak_ave_wide": camera_stats(5.0), "back_lane": camera_stats(9.0)}, "service": {"uptime": 60}},
        {"cameras": {"oak_ave_wide": camera_stats(4.0, detection_enabled=False)}},
    ])
    assert run["flow"]["watch_window"] == {**EMPTY_WINDOW, "messages": 2, "cameras": {"camera_1_3fa9c2": {
        "messages": 2, "camera_fps": 9.0, "process_fps": 9.0, "skipped_fps": 0.0, "detection_fps": 1.0,
        "detection_off": 1}}}
    assert [step["result"] for step in run["results"]] == [None, None]
    assert [step["logged"] for step in run["results"]] == [[], []]
    # Frigate's names, the listed camera's and the unlisted one's, are kept nowhere
    kept = json.dumps([run["flow"], run["results"]])
    assert "oak_ave_wide" not in kept and "back_lane" not in kept


@needs_node
def test_a_frigate_with_no_cameras_still_answered():
    assert keep_stats([{"cameras": {}}])["flow"]["watch_window"] == {**EMPTY_WINDOW, "messages": 1}


@needs_node
@pytest.mark.parametrize("payload", ["online", None, 7, [], {}, {"cameras": []}, {"cameras": "none"}],
                         ids=["text", "null", "number", "list", "no-cameras-key", "cameras-list", "cameras-text"])
def test_a_report_that_cannot_be_read_is_not_counted(payload):
    run = keep_stats([payload, payload])
    assert run["flow"]["watch_window"] == EMPTY_WINDOW
    assert [entry for step in run["results"] for entry in step["logged"]] == [["warn", STATS_WARNING, False]]
    assert run["global"]["tm_warned"] == {"watch:stats": True}


@needs_node
@pytest.mark.parametrize("entry", [
    None, "busy", camera_stats(camera_fps="5.0"), camera_stats(detection_enabled=1),
    {key: value for key, value in camera_stats().items() if key != "detection_fps"},
], ids=["null", "text", "fps-as-text", "detection-as-number", "an-fps-missing"])
def test_a_camera_entry_that_cannot_be_read_is_left_out(entry):
    run = keep_stats([{"cameras": {"oak_ave_wide": entry}}])
    assert run["flow"]["watch_window"] == {**EMPTY_WINDOW, "messages": 1}
    assert run["results"][0]["logged"] == []


@needs_node
def test_before_the_first_mark_nothing_is_kept():
    run = keep_stats([{"cameras": {"oak_ave_wide": camera_stats()}}], window=None)
    assert run["flow"] == {} and run["results"][0]["logged"] == []


def test_frigate_stats_reach_the_keeper():
    flows = json.loads(FLOWS.read_text())
    by_id = {node["id"]: node for node in flows}
    keep = named(flows, "keep frigate stats")
    [source] = [node for node in flows if keep["id"] in sum(node.get("wires", []), [])]
    assert (source["type"], source["topic"], source["broker"], source["qos"], source["datatype"]) == (
        "mqtt in", "frigate/stats", "a5d65dd0e3566daa", "0", "auto-detect")
    assert (keep["type"], keep["outputs"], keep["wires"], keep["initialize"], keep["finalize"]) == (
        "function", 1, [[]], "", "")
    group = by_id[keep["g"]]
    assert group["name"] == "watch log" and group["z"] == keep["z"] == source["z"] == tab_id(flows, "system")
    assert source["g"] == group["id"] and {keep["id"], source["id"]} <= set(group["nodes"])


def frigate_switches(**cameras):
    """Frigate's /api/config answer, cut down to cameras with the given enabled values."""
    return {"statusCode": 200, "payload": {
        "cameras": {name: {"enabled": on, "detect": {"enabled": False}} for name, on in cameras.items()}, "mqtt": {}}}


def keep_switch(messages, window=MISSING):
    """Run "keep frigate camera switch" on each message in turn, with one camera config.yml lists under another key."""
    flow = {} if window is None else {"watch_window": copy.deepcopy(EMPTY_WINDOW if window is MISSING else window)}
    node = named(json.loads(FLOWS.read_text()), "keep frigate camera switch")
    return run_functions([(node, message) for message in messages],
                         context={"frigate_cameras": {"oak_ave_wide": "camera_1_3fa9c2"}, "tm_warned": {}}, flow=flow)


@needs_node
def test_frigates_answers_are_counted_under_the_cameras_key():
    run = keep_switch([frigate_switches(oak_ave_wide=True, back_lane=False), frigate_switches(oak_ave_wide=False)])
    assert run["flow"]["watch_window"] == {**EMPTY_WINDOW,
                                           "switches": {"camera_1_3fa9c2": {"answers": 2, "off": 1}}}
    assert [step["result"] for step in run["results"]] == [None, None]
    assert [step["logged"] for step in run["results"]] == [[], []]
    # Frigate's names, the listed camera's and the unlisted one's, are kept nowhere
    kept = json.dumps([run["flow"], run["results"], run["global"]["tm_warned"]])
    assert "oak_ave_wide" not in kept and "back_lane" not in kept


@needs_node
@pytest.mark.parametrize("message", [
    {"statusCode": 503, "payload": "Service Unavailable"},
    {"statusCode": "ECONNREFUSED", "payload": "RequestError: connect ECONNREFUSED : http://frigate:5000/api/config"},
    {"payload": frigate_switches(oak_ave_wide=True)["payload"]},
    {"statusCode": 200, "payload": "text"}, {"statusCode": 200, "payload": None}, {"statusCode": 200, "payload": {}},
    {"statusCode": 200, "payload": {"cameras": []}},
], ids=["an-error-status", "no-connection", "no-status", "text", "null", "no-cameras-key", "cameras-list"])
def test_an_answer_that_cannot_be_read_is_no_answer(message):
    run = keep_switch([message])
    assert run["flow"]["watch_window"] == EMPTY_WINDOW
    assert run["results"][0]["result"] is None and run["results"][0]["logged"] == []


@needs_node
@pytest.mark.parametrize("camera", [None, "on", {}, {"enabled": 1}, {"enabled": "true"}, {"enabled": None}],
                         ids=["null", "text", "no-enabled", "a-number", "text-true", "null-enabled"])
def test_a_camera_whose_switch_cannot_be_read_is_left_out(camera):
    run = keep_switch([{"statusCode": 200, "payload": {"cameras": {"oak_ave_wide": camera}}}])
    assert run["flow"]["watch_window"] == EMPTY_WINDOW and run["results"][0]["logged"] == []


@needs_node
def test_before_the_first_mark_no_answer_is_kept():
    run = keep_switch([frigate_switches(oak_ave_wide=True)], window=None)
    assert run["flow"] == {} and run["results"][0]["logged"] == []


@needs_node
def test_a_window_opened_before_this_change_takes_answers():
    """A deploy in the middle of a window leaves one without `switches`."""
    run = keep_switch([frigate_switches(oak_ave_wide=True)],
                      window={"since": TICK_MS - 300000, "messages": 0, "cameras": {}})
    assert run["flow"]["watch_window"]["switches"] == {"camera_1_3fa9c2": {"answers": 1, "off": 0}}


def test_each_stats_report_asks_frigate_for_its_configuration():
    flows = json.loads(FLOWS.read_text())
    by_id = {node["id"]: node for node in flows}
    keep = named(flows, "keep frigate camera switch")
    ask = named(flows, "frigate api/config, watch log")
    base = by_id["c58a1e3d7f96b024"]  # the base PR's request node, which this one copies
    same = ("type", "method", "ret", "paytoqs", "url", "tls", "persist", "proxy", "insecureHTTPParser", "authType",
            "senderr", "headers")
    assert {field: ask[field] for field in same} == {field: base[field] for field in same}
    assert ask["url"] == "http://frigate:5000/api/config" and ask["wires"] == [[keep["id"]]]
    [source] = [node for node in flows if ask["id"] in sum(node.get("wires", []), [])]
    assert (source["type"], source["topic"]) == ("mqtt in", "frigate/stats")
    assert source["wires"] == [[named(flows, "keep frigate stats")["id"], ask["id"]]]
    assert (keep["type"], keep["outputs"], keep["wires"], keep["initialize"], keep["finalize"]) == (
        "function", 1, [[]], "", "")
    group = by_id[keep["g"]]
    assert group["name"] == "watch log" and ask["g"] == group["id"] and {keep["id"], ask["id"]} <= set(group["nodes"])
    assert keep["z"] == ask["z"] == tab_id(flows, "system")


def watch_tick(window=WATCH_WINDOW, config=MISSING, radars=RADAR_STATUS, now=TICK_MS):
    """Run "watch rows" on one mark. Returns its three outputs (camera messages, radar messages, the upload
    message), each None when it sent none, and the flow context after."""
    context = {"tm_status": {"radars": radars}}
    if config is not None:
        context["config"] = {"sensors": WATCH_SENSORS} if config is MISSING else config
    flow = {} if window is None else {"watch_window": copy.deepcopy(window)}
    node = named(json.loads(FLOWS.read_text()), "watch rows")
    run = run_functions([(node, {"payload": now})], context=context, flow=flow)
    [step] = run["results"]
    assert step["logged"] == []
    outputs = step["result"] if step["result"] is not None else [None, None, None]
    return (*outputs, run["flow"])


@needs_node
def test_a_whole_window_gives_a_row_per_sensor():
    cameras, radars, upload, flow = watch_tick()
    assert [msg["payload"] for msg in cameras] == CAMERA_ROWS
    assert [msg["payload"] for msg in radars] == RADAR_ROWS
    assert [list(msg["payload"]) for msg in cameras] == [WATCH_CAMERA_COLUMNS] * 2
    assert [list(msg["payload"]) for msg in radars] == [WATCH_RADAR_COLUMNS] * 2
    for msg in cameras + radars:
        assert msg["params"] == {f"${name}": value for name, value in msg["payload"].items()}
    assert upload == {"payload": {"time": TICK, "cameras": CAMERA_ROWS, "radars": RADAR_ROWS}}
    assert flow["watch_window"] == {"since": TICK_MS, "messages": 0, "cameras": {}, "switches": {}, "radars": {}}


@needs_node
@pytest.mark.parametrize("counts, expected", [
    ({"answers": 5, "idle": 0, "unknown": 0}, (5, 1)), ({"answers": 7, "idle": 0, "unknown": 0}, (7, 1)),
    ({"answers": 2, "idle": 0, "unknown": 0}, (2, 1)), ({"answers": 5, "idle": 1, "unknown": 0}, (5, 0)),
    ({"answers": 5, "idle": 5, "unknown": 0}, (5, 0)), ({"answers": 5, "idle": 1, "unknown": 2}, (5, 0)),
    ({"answers": 5, "idle": 0, "unknown": 1}, (5, None)), ({"answers": 0, "idle": 0, "unknown": 0}, (0, None)),
], ids=["on", "on-with-a-setups-answers", "on-in-the-few-answers", "idle-once", "idle-throughout", "idle-and-unknown",
        "a-text-not-known", "no-answer"])
def test_the_radars_row_says_how_often_it_answered_and_whether_it_was_on(counts, expected):
    window = copy.deepcopy(WATCH_WINDOW)
    window["radars"]["TM_RADAR_SERIAL_PORT_00"].update(counts)
    _, radars, upload, _ = watch_tick(window=window)
    row = radars[0]["payload"]
    assert (row["radar_answers"], row["radar_on"]) == expected
    assert radars[0]["params"]["$radar_on"] == expected[1] and upload["payload"]["radars"][0] == row


@needs_node
@pytest.mark.parametrize("entry", [MISSING, None, "broken", {}, {"answers": "5", "idle": 0, "unknown": 0},
                                   {"answers": 5, "unknown": 0}],
                         ids=["none", "null", "text", "empty", "answers-as-text", "no-idle-count"])
def test_a_radar_whose_checks_cannot_be_read_answered_nothing_that_counts(entry):
    window = copy.deepcopy(WATCH_WINDOW)
    window["radars"] = {} if entry is MISSING else {"TM_RADAR_SERIAL_PORT_00": entry}
    _, radars, _, _ = watch_tick(window=window)
    row = radars[0]["payload"]
    assert row["radar_on"] is None and row["port_open"] == 1
    assert row["radar_answers"] == (5 if entry == {"answers": 5, "unknown": 0} else 0)


@needs_node
def test_a_port_that_was_closed_at_any_check_was_not_open_for_the_window():
    window = copy.deepcopy(WATCH_WINDOW)
    window["radars"]["TM_RADAR_SERIAL_PORT_00"]["port_closed"] = 1
    _, radars, _, _ = watch_tick(window=window)
    assert radars[0]["payload"] == {**RADAR_ROWS[0], "port_open": 0}


@needs_node
def test_when_frigate_did_not_answer_every_camera_still_has_its_row():
    cameras, _, _, _ = watch_tick(window=EMPTY_WINDOW)
    assert [msg["payload"] for msg in cameras] == [
        {**CAMERA_ROWS[0], "frigate_answers": 0, **NO_NUMBERS, "camera_on": None},
        {**CAMERA_ROWS[1], "frigate_answers": 0}]


@needs_node
def test_frigate_answering_without_the_camera_is_not_frigate_not_answering():
    cameras, _, _, _ = watch_tick(window={**EMPTY_WINDOW, "messages": 5})
    assert [(msg["payload"]["frigate_answers"], msg["payload"]["camera_answers"], msg["payload"]["camera_fps"])
            for msg in cameras] == [(5, 0, None), (5, 0, None)]


@needs_node
def test_frigate_answers_is_the_windows_message_count_on_every_row():
    cameras, _, _, _ = watch_tick(window={**WATCH_WINDOW, "messages": 2})
    assert [msg["payload"]["frigate_answers"] for msg in cameras] == [2, 2]


@needs_node
def test_detection_off_in_any_report_is_off_for_the_window():
    window = copy.deepcopy(WATCH_WINDOW)
    window["cameras"]["camera_1_3fa9c2"]["detection_off"] = 1
    cameras, _, _, _ = watch_tick(window=window)
    assert cameras[0]["payload"]["detection_enabled"] == 0


NO_FRAME_RATES = {"camera_fps": None, "process_fps": None, "skipped_fps": None, "detection_fps": None}


@needs_node
@pytest.mark.parametrize("off", [1, 5], ids=["turned-off-partway", "off-all-window"])
def test_a_camera_off_in_frigate_is_off_for_the_window_and_has_no_frame_rates(off):
    """Frigate keeps reporting the last frame rates of a camera that is off, so the row leaves them out. What
    Frigate said about its reports and its detection switch stays."""
    window = copy.deepcopy(WATCH_WINDOW)
    window["switches"]["camera_1_3fa9c2"] = {"answers": 5, "off": off}
    cameras, _, upload, _ = watch_tick(window=window)
    assert cameras[0]["payload"] == {**CAMERA_ROWS[0], **NO_FRAME_RATES, "camera_on": 0}
    assert cameras[0]["params"]["$camera_on"] == 0 and cameras[0]["params"]["$camera_fps"] is None
    assert upload["payload"]["cameras"][0] == cameras[0]["payload"]


@needs_node
@pytest.mark.parametrize("switches", [
    {}, None, "broken", {"camera_1_3fa9c2": None}, {"camera_1_3fa9c2": {"answers": 0, "off": 0}},
    {"camera_1_3fa9c2": {"answers": "5", "off": 0}}, {"camera_1_3fa9c2": {"answers": 5}},
], ids=["none", "null", "text", "null-entry", "no-answers", "answers-as-text", "no-off-count"])
def test_without_an_answer_the_switch_is_unknown_and_the_frame_rates_stay(switches):
    cameras, _, _, _ = watch_tick(window={**copy.deepcopy(WATCH_WINDOW), "switches": switches})
    assert cameras[0]["payload"] == {**CAMERA_ROWS[0], "camera_on": None}


@needs_node
def test_frigates_switch_is_recorded_for_a_camera_its_reports_leave_out():
    window = {**EMPTY_WINDOW, "messages": 5, "switches": {"side_st": {"answers": 5, "off": 5}}}
    cameras, _, _, _ = watch_tick(window=window)
    assert cameras[1]["payload"] == {**CAMERA_ROWS[1], "camera_on": 0}


@needs_node
def test_a_window_with_no_report_says_nothing_about_the_switch():
    """An answer to the last report of the window before can land just after the mark."""
    window = {**EMPTY_WINDOW, "switches": {"camera_1_3fa9c2": {"answers": 1, "off": 0}}}
    cameras, _, _, _ = watch_tick(window=window)
    assert (cameras[0]["payload"]["frigate_answers"], cameras[0]["payload"]["camera_on"]) == (0, None)


@needs_node
@pytest.mark.parametrize("age, rows", [(295000, True), (300000, True), (305000, True), (120000, False),
                                       (294000, False), (306000, False), (900000, False), (-3600000, False)])
def test_only_a_window_about_five_minutes_long_gives_rows(age, rows):
    """Not the first mark after a start, a mark after a missed one, or one after the clock jumped."""
    cameras, radars, upload, flow = watch_tick(window={**WATCH_WINDOW, "since": TICK_MS - age})
    assert (cameras is not None, radars is not None, upload is not None) == (rows, rows, rows)
    assert flow["watch_window"] == {"since": TICK_MS, "messages": 0, "cameras": {}, "switches": {}, "radars": {}}


@needs_node
@pytest.mark.parametrize("window, config", [
    (None, MISSING), (WATCH_WINDOW, None), (WATCH_WINDOW, {}), (WATCH_WINDOW, {"sensors": "broken"}),
    (WATCH_WINDOW, {"sensors": {"cameras": None, "radars": []}}),
], ids=["first-mark", "no-config", "no-sensors", "sensors-text", "nothing-listed"])
def test_no_rows_without_a_window_or_sensors(window, config):
    cameras, radars, upload, flow = watch_tick(window=window, config=config)
    assert (cameras, radars, upload) == (None, None, None)
    assert flow["watch_window"] == {"since": TICK_MS, "messages": 0, "cameras": {}, "switches": {}, "radars": {}}


@needs_node
def test_rows_follow_config_yml_as_it_is_at_the_mark():
    """A camera that left config.yml gets no row; an entry with nothing under it is a camera that is off."""
    config = {"sensors": {"cameras": {"new_key": None}, "radars": {}}}
    cameras, radars, upload, _ = watch_tick(config=config)
    assert [msg["payload"] for msg in cameras] == [
        {"time": TICK, "camera": "new_key", "config_enabled": 0, "deployment_id": None, "frigate_answers": 5,
         **NO_NUMBERS, "camera_on": None}]
    assert radars is None
    assert upload["payload"] == {"time": TICK, "cameras": [cameras[0]["payload"]], "radars": []}


@needs_node
@pytest.mark.parametrize("now", [TICK_MS - 40, TICK_MS + 40, TICK_MS + 2000])
def test_the_time_is_the_five_minute_mark(now):
    cameras, _, _, _ = watch_tick(window={**WATCH_WINDOW, "since": now - 300000}, now=now)
    assert cameras[0]["payload"]["time"] == TICK


@needs_node
@pytest.mark.parametrize("status", [None, {}, {"TM_RADAR_SERIAL_PORT_00": {"port_open": "yes",
                                                                           "last_reading_at": "not a time"}}])
def test_a_radar_the_status_knows_nothing_about_is_not_open(status):
    _, radars, _, _ = watch_tick(radars=status)
    assert [(msg["payload"]["port_open"], msg["payload"]["last_reading_at"]) for msg in radars] == [(0, None)] * 2


POWER_WARNING = "Watch log: a radar gave a power state this version doesn't know, so its radar_on is empty."
NO_CHECKS = {"checks": 0, "port_closed": 0, "answers": 0, "idle": 0, "unknown": 0}


def radar_check(window=MISSING, config=MISSING, radars=RADAR_STATUS):
    """Run "radar minute check" once. Returns what it sent (None when nothing) and the flow context after."""
    context = {"tm_status": {"radars": radars}}
    if config is not None:
        context["config"] = {"sensors": WATCH_SENSORS} if config is MISSING else config
    flow = {} if window is None else {"watch_window": copy.deepcopy(EMPTY_WINDOW if window is MISSING else window)}
    node = named(json.loads(FLOWS.read_text()), "radar minute check")
    run = run_functions([(node, {"payload": TICK_MS})], context=context, flow=flow)
    [step] = run["results"]
    assert step["logged"] == []
    return step["result"], run["flow"]


@needs_node
def test_each_minute_every_enabled_radar_is_asked_its_power_state():
    """A radar that config.yml switches off isn't asked: the director would turn the question into PI. Its port is
    still noted."""
    sent, flow = radar_check()
    assert sent == [[{"topic": "TM_RADAR_SERIAL_PORT_00", "payload": "P?"}]]
    assert flow["watch_window"]["radars"] == {
        "TM_RADAR_SERIAL_PORT_00": {**NO_CHECKS, "checks": 1},
        "TM_RADAR_SERIAL_PORT_01": {**NO_CHECKS, "checks": 1, "port_closed": 1}}


@needs_node
@pytest.mark.parametrize("status", [{}, None, {"TM_RADAR_SERIAL_PORT_00": {"port_open": False}},
                                    {"TM_RADAR_SERIAL_PORT_00": {"port_open": "true"}}],
                         ids=["unknown-radar", "no-status", "closed", "text"])
def test_a_port_that_is_not_open_at_a_check_is_counted(status):
    sent, flow = radar_check(radars=status)
    assert flow["watch_window"]["radars"]["TM_RADAR_SERIAL_PORT_00"] == {**NO_CHECKS, "checks": 1, "port_closed": 1}
    assert sent == [[{"topic": "TM_RADAR_SERIAL_PORT_00", "payload": "P?"}]]  # asked all the same


@needs_node
def test_checks_add_up_over_the_window():
    window = copy.deepcopy(WATCH_WINDOW)
    _, flow = radar_check(window=window)
    assert flow["watch_window"]["radars"]["TM_RADAR_SERIAL_PORT_00"] == {**NO_CHECKS, "checks": 6, "answers": 5}


@needs_node
@pytest.mark.parametrize("window, config", [
    (None, MISSING), (MISSING, None), (MISSING, {}), (MISSING, {"sensors": "broken"}),
    (MISSING, {"sensors": {"radars": []}}), (MISSING, {"sensors": {"radars": {}}}),
], ids=["no-window", "no-config", "empty-config", "broken-sensors", "radars-list", "no-radars"])
def test_no_check_without_a_window_or_radars(window, config):
    sent, flow = radar_check(window=window, config=config)
    assert sent is None
    assert flow == ({} if window is None else {"watch_window": EMPTY_WINDOW})


def power_answer(mode, radar="TM_RADAR_SERIAL_PORT_00"):
    """A radar's answer to P?, PA, or PI as it reaches the keeper: parsed, with the radar's name added."""
    return {"payload": {"PowerMode": mode, "radarName": radar, "deployment_id": "1761700000000-4e5f6a7b-d"}}


def keep_power(messages, window=MISSING):
    flow = {} if window is None else {"watch_window": copy.deepcopy(EMPTY_WINDOW if window is MISSING else window)}
    node = named(json.loads(FLOWS.read_text()), "keep radar power")
    return run_functions([(node, message) for message in messages], context={"tm_warned": {}}, flow=flow)


@needs_node
@pytest.mark.parametrize("mode, counted", [
    ("Active Continuously", {}), ("Continuous", {}), ("active continuously", {}),
    ("Idle or Pulse", {"idle": 1}), ("Idle", {"idle": 1}), ("IDLE", {"idle": 1}),
], ids=["active", "the-api-notes-word", "lower-case", "idle", "idle-short", "upper-case"])
def test_a_power_answer_is_counted_for_its_radar(mode, counted):
    run = keep_power([power_answer(mode)])
    assert run["flow"]["watch_window"]["radars"] == {"TM_RADAR_SERIAL_PORT_00": {**NO_CHECKS, "answers": 1, **counted}}
    assert run["results"][0]["result"] is None and run["results"][0]["logged"] == []


@needs_node
def test_a_power_state_this_version_does_not_know_is_counted_apart_and_warned_of_once():
    run = keep_power([power_answer("Hibernating"), power_answer("Hibernating")])
    assert run["flow"]["watch_window"]["radars"] == {
        "TM_RADAR_SERIAL_PORT_00": {**NO_CHECKS, "answers": 2, "unknown": 2}}
    assert [entry for step in run["results"] for entry in step["logged"]] == [["warn", POWER_WARNING, False]]
    assert run["global"]["tm_warned"] == {"watch:power": True}


@needs_node
@pytest.mark.parametrize("payload", [
    "text", None, {}, {"PowerMode": "Active Continuously"}, {"PowerMode": 1, "radarName": "TM_RADAR_SERIAL_PORT_00"},
    {"PowerMode": "Active Continuously", "radarName": 7}, {"PowerMode": "Active Continuously", "radarName": ""},
], ids=["text", "null", "empty", "no-radar", "mode-as-number", "radar-as-number", "empty-radar"])
def test_a_power_answer_that_cannot_be_read_is_not_counted(payload):
    run = keep_power([{"payload": payload}])
    assert run["flow"]["watch_window"] == EMPTY_WINDOW and run["results"][0]["logged"] == []


@needs_node
def test_before_the_first_mark_no_power_answer_is_kept():
    run = keep_power([power_answer("Active Continuously")], window=None)
    assert run["flow"] == {} and run["results"][0]["logged"] == []


def test_the_radars_are_asked_every_minute_and_their_answers_reach_the_keeper():
    flows = json.loads(FLOWS.read_text())
    by_id = {node["id"]: node for node in flows}
    system, radar_tab = tab_id(flows, "system"), tab_id(flows, "capture-radar")
    check, keep = named(flows, "radar minute check"), named(flows, "keep radar power")
    [inject] = [node for node in flows if check["id"] in sum(node.get("wires", []), [])]
    assert (inject["type"], inject["name"], inject["crontab"], inject["repeat"], inject["once"]) == (
        "inject", "every minute", "*/1 0-23 * * *", "", False)
    ask_out, ask_in = named(flows, "radar check link out"), named(flows, "radar check link in")
    assert check["wires"] == [[ask_out["id"]]] and (check["outputs"], keep["outputs"], keep["wires"]) == (1, 1, [[]])
    assert (ask_out["links"], ask_in["links"], ask_in["wires"]) == ([ask_in["id"]], [ask_out["id"]], [[RADAR_JUNCTION]])
    picked = named(flows, "a power state answer?")
    assert (picked["type"], picked["property"], picked["propertyType"], picked["rules"]) == (
        "switch", "payload", "msg", [{"t": "hask", "v": "PowerMode", "vt": "str"}])
    assert picked["id"] in by_id[RADAR_REPLIES]["wires"][0]
    answer_out, answer_in = named(flows, "radar power link out"), named(flows, "radar power link in")
    assert picked["wires"] == [[answer_out["id"]]]
    assert (answer_out["links"], answer_in["links"], answer_in["wires"]) == (
        [answer_in["id"]], [answer_out["id"]], [[keep["id"]]])
    group = by_id[check["g"]]
    on_system = (inject, check, ask_out, answer_in, keep)
    assert group["name"] == "watch log" and {node["g"] for node in on_system} == {group["id"]}
    assert {node["id"] for node in on_system} <= set(group["nodes"]) and {node["z"] for node in on_system} == {system}
    assert {node["z"] for node in (ask_in, picked, answer_out)} == {radar_tab}


@needs_node
@pytest.mark.parametrize("line, a_reading", [
    ('{"DetectedObjectVelocity":"3.2"}', True), ('{"Clock":"54"}', True), ("garbled", True),
    ('{"PowerMode" : "Active Continuously"}', False), ('{"PowerMode" : "Idle or Pulse"}', False),
    ('{"Power" : "Max"}', False),
])
def test_an_answer_to_the_minute_check_is_not_a_reading(line, a_reading):
    flows = json.loads(FLOWS.read_text())
    for number in range(4):
        node = named(flows, f"tm-internal: RADAR_0{number} last reading")
        run = run_functions([(node, {"payload": line})], context={})
        radar = ((run["global"].get("tm_status") or {}).get("radars") or {}).get(f"TM_RADAR_SERIAL_PORT_0{number}")
        assert (radar is not None and "last_reading_at" in radar) == a_reading
        assert run["results"][0]["result"] is None and run["results"][0]["logged"] == []


def watch_insert(table):
    """The INSERT for a watch table: its node, its columns, and the parameter each one takes."""
    [node] = [node for node in json.loads(FLOWS.read_text())
              if node["type"] == "sqlite" and f"INSERT INTO {table} " in node.get("sql", "")]
    match = re.fullmatch(rf"\s*INSERT INTO {table} \(([^)]*)\)\s*VALUES \((.*)\);\s*", node["sql"], re.DOTALL)
    return node, [name.strip() for name in match[1].split(",")], [value.strip() for value in match[2].split(",")]


WATCH_TABLES = {"watch_camera": WATCH_CAMERA_COLUMNS, "watch_radar": WATCH_RADAR_COLUMNS}


def test_watch_fields_agree():
    """For each table, one list of fields in one order: what "watch rows" builds (checked above), what the INSERT
    names, what its parameters are, and what the table has."""
    con = sqlite3.connect(":memory:")
    con.executescript(SCHEMA_SQL.read_text())
    for table, columns in WATCH_TABLES.items():
        node, names, values = watch_insert(table)
        assert names == columns and values == [f"${name}" for name in columns]
        assert (node["sqlquery"], node["mydb"]) == ("prepared", TMDB)
        assert [row[1] for row in con.execute(f"PRAGMA table_info({table})")] == columns
        assert upload_lists()[table] == columns


def test_the_watch_log_is_written_every_five_minutes():
    flows = json.loads(FLOWS.read_text())
    by_id = {node["id"]: node for node in flows}
    rows = named(flows, "watch rows")
    [inject] = [node for node in flows if rows["id"] in sum(node.get("wires", []), [])]
    assert (inject["type"], inject["crontab"], inject["repeat"], inject["once"], inject["payloadType"]) == (
        "inject", "*/5 0-23 * * *", "", False, "date")
    camera_insert, radar_insert = watch_insert("watch_camera")[0], watch_insert("watch_radar")[0]
    link = named(flows, "watch link out")
    assert (rows["type"], rows["outputs"], rows["initialize"], rows["finalize"]) == ("function", 3, "", "")
    assert rows["wires"] == [[camera_insert["id"]], [radar_insert["id"]], [link["id"]]]
    assert (link["type"], link["mode"]) == ("link out", "link")
    nodes = (inject, rows, camera_insert, radar_insert, link)
    group = by_id[rows["g"]]
    assert group["name"] == "watch log" and {node["g"] for node in nodes} == {group["id"]}
    assert {node["id"] for node in nodes} <= set(group["nodes"])
    assert {node["z"] for node in nodes} == {tab_id(flows, "system")}
    for node_id in group["nodes"]:
        node = by_id[node_id]
        assert group["x"] < node["x"] < group["x"] + group["w"] and group["y"] < node["y"] < group["y"] + group["h"]


# Time stopped and time in each zone. Frigate sends no times, only whether the object is stationary and which zones
# it is in, on every frigate/events message. "tally time stopped and time in zones" adds the time between messages
# up for each object, from its new message to its end, and hands the totals to the end message as msg.time_tally.

TALLY = "tally time stopped and time in zones"
T0 = 1761800000.0  # the first frame's time
TALLY_ID = "1761800000.0-abc123"


def frigate_message(kind, at, before_at, stationary=False, zones=(), event_id=TALLY_ID):
    """One frigate/events message, cut down to what the tally reads, with a camera name and a sub-label that must go
    no further. Times are seconds after T0. An end message's end_time is five seconds after its last frame."""
    after = {"id": event_id, "camera": "oak_ave_wide", "sub_label": ["Jane Doe", 0.97], "frame_time": T0 + at,
             "end_time": T0 + at + 5 if kind == "end" else None, "stationary": stationary,
             "current_zones": list(zones)}
    return {"topic": "frigate/events",
            "payload": {"type": kind, "before": {"id": event_id, "frame_time": T0 + before_at}, "after": after}}


def one_object(steps, event_id=TALLY_ID):
    """Frigate's messages for one object, from (type, seconds after T0, stationary, zones) steps. Each message's
    `before` holds the frame time of the message before it, as Frigate's does."""
    messages, last = [], steps[0][1]
    for kind, at, stationary, zones in steps:
        messages.append(frigate_message(kind, at, last, stationary, zones, event_id))
        last = at
    return messages


def run_tally(messages, flow=None):
    """Run the tally node on each message in turn. Returns the message the last one sent on and the flow context
    after. Every message must go on with its payload as it came, and nothing may be logged."""
    node = named(json.loads(FLOWS.read_text()), TALLY)
    run = run_functions([(node, copy.deepcopy(msg)) for msg in messages], context={"tm_warned": {}}, flow=flow or {})
    for step, msg in zip(run["results"], messages, strict=True):
        assert step["logged"] == [] and step["result"]["payload"] == msg["payload"]
    return run["results"][-1]["result"], run["flow"]


DRIVE_THROUGH = [("new", 0, False, []), ("update", 1, False, ["zone_far"]),
                 ("update", 2.5, False, ["zone_far", "zone_radar"]), ("update", 4, False, ["zone_near"]),
                 ("end", 5.5, False, ["zone_near"])]
STOP = [("new", 0, False, []), ("update", 2, False, ["zone_stop"]), ("update", 14, True, ["zone_stop"]),
        ("update", 40, False, ["zone_stop"]), ("update", 43, False, []), ("end", 45, False, [])]
STOP_TALLY = {"stationary_time": 26, "stops": 1, "zone_times": {"zone_stop": {"time": 41, "stationary": 26}},
              "stopped": [[T0 + 14, T0 + 40]]}


@needs_node
def test_a_drive_through_has_its_time_in_each_zone_and_no_stop():
    """The last stretch ends at the last frame the object was seen in: zone_near has 1.5 seconds, not 6.5."""
    out, flow = run_tally(one_object(DRIVE_THROUGH))
    assert out["time_tally"] == {"stationary_time": 0, "stops": 0, "stopped": [], "zone_times": {
        "zone_far": {"time": 3, "stationary": 0}, "zone_radar": {"time": 1.5, "stationary": 0},
        "zone_near": {"time": 1.5, "stationary": 0}}}
    assert flow["time_tallies"] == {}


@needs_node
def test_a_stop_in_a_zone_runs_from_frigates_flag_to_the_frame_the_object_moved_in():
    out, flow = run_tally(one_object(STOP))
    assert out["time_tally"] == STOP_TALLY and flow["time_tallies"] == {}


@needs_node
def test_until_the_end_the_figures_stay_in_the_tally():
    out, flow = run_tally(one_object(STOP)[:-1])
    assert out["time_tally"] is None
    assert flow["time_tallies"] == {TALLY_ID: {
        "at": T0 + 43, "stationary": False, "zones": [], "stationary_time": 26, "stops": 1,
        "zone_times": {"zone_stop": {"time": 41, "stationary": 26}}, "stopped": [[T0 + 14, T0 + 40]],
        "stopped_since": None, "broken": False}}
    # Frigate's name for the camera and the sub-label are kept nowhere
    assert "oak_ave_wide" not in json.dumps(flow) and "Jane Doe" not in json.dumps(flow)


@needs_node
def test_two_stops_are_counted_and_added_up():
    steps = [("new", 0, False, ["zone_a"]), ("update", 12, True, ["zone_a"]), ("update", 20, False, ["zone_a"]),
             ("update", 30, False, ["zone_b"]), ("update", 45, True, ["zone_b"]), ("update", 50, False, ["zone_b"]),
             ("end", 52, False, ["zone_b"])]
    out, _ = run_tally(one_object(steps))
    assert out["time_tally"] == {"stationary_time": 13, "stops": 2, "stopped": [[T0 + 12, T0 + 20], [T0 + 45, T0 + 50]],
                                 "zone_times": {"zone_a": {"time": 30, "stationary": 8},
                                                "zone_b": {"time": 22, "stationary": 5}}}


@needs_node
def test_an_object_that_is_stationary_when_first_heard_of_has_one_stop():
    out, _ = run_tally(one_object([("new", 0, True, ["zone_bay"]), ("update", 30, False, ["zone_bay"]),
                                   ("end", 34, False, [])]))
    assert out["time_tally"] == {"stationary_time": 30, "stops": 1, "stopped": [[T0, T0 + 30]],
                                 "zone_times": {"zone_bay": {"time": 34, "stationary": 30}}}


@needs_node
def test_no_figure_says_more_than_six_hours():
    out, _ = run_tally(one_object([("new", 0, False, ["zone_bay"]), ("update", 12, True, ["zone_bay"]),
                                   ("update", 30012, False, ["zone_bay"]), ("end", 30020, False, [])]))
    assert out["time_tally"] == {"stationary_time": 21600, "stops": 1, "stopped": [[T0 + 12, T0 + 30012]],
                                 "zone_times": {"zone_bay": {"time": 21600, "stationary": 21600}}}


@needs_node
def test_figures_are_rounded_to_two_decimals():
    out, _ = run_tally(one_object([("new", 0, False, ["zone_a"]), ("end", 0.123456, False, ["zone_a"])]))
    assert out["time_tally"]["zone_times"] == {"zone_a": {"time": 0.12, "stationary": 0}}


@needs_node
def test_an_object_first_heard_of_after_a_restart_gets_no_figures():
    """Node-RED restarted while Frigate was following it: no tally is started by an update or an end."""
    for count in (1, 2, 5):
        out, flow = run_tally(one_object(STOP)[count:])
        assert out["time_tally"] is None and flow.get("time_tallies", {}) == {}


@needs_node
def test_a_missed_message_leaves_the_figures_empty():
    messages = one_object(STOP)
    del messages[3]  # the update at 40 never arrived, so the next one's `before` isn't the last message seen
    _, flow = run_tally(messages[:-1])
    assert flow["time_tallies"][TALLY_ID]["broken"] is True
    out, flow = run_tally(messages)
    assert out["time_tally"] is None and flow["time_tallies"] == {}


@needs_node
def test_time_running_backwards_leaves_the_figures_empty():
    messages = [frigate_message("new", 3, 3), frigate_message("update", 1, 3), frigate_message("end", 5, 1)]
    out, _ = run_tally(messages)
    assert out["time_tally"] is None


@needs_node
def test_a_second_new_message_starts_the_tally_again():
    steps = [("new", 0, False, ["zone_a"]), ("update", 5, False, ["zone_a"]), ("new", 6, False, []),
             ("end", 8, False, [])]
    out, _ = run_tally(one_object(steps))
    assert out["time_tally"] == {"stationary_time": 0, "stops": 0, "stopped": [], "zone_times": {}}


@needs_node
def test_at_most_300_objects_are_followed_and_the_one_heard_of_longest_ago_goes_first():
    ids = [f"{T0 + i}-{i:06d}" for i in range(301)]
    messages = [frigate_message("new", i, i, event_id=ids[i]) for i in range(300)]
    messages.append(frigate_message("update", 300, 0, event_id=ids[0]))
    messages.append(frigate_message("new", 301, 301, event_id=ids[300]))
    _, flow = run_tally(messages)
    assert len(flow["time_tallies"]) == 300
    assert ids[1] not in flow["time_tallies"] and {ids[0], ids[2], ids[300]} <= set(flow["time_tallies"])


@needs_node
@pytest.mark.parametrize("later, kept", [(86400, True), (86401, False)])
def test_an_object_not_heard_of_for_more_than_a_day_is_dropped(later, kept):
    messages = [frigate_message("new", 0, 0), frigate_message("new", later, later, event_id="1761886400.0-zzz999")]
    _, flow = run_tally(messages)
    assert (TALLY_ID in flow["time_tallies"]) is kept and "1761886400.0-zzz999" in flow["time_tallies"]


@needs_node
def test_only_the_twenty_longest_stops_are_kept():
    steps = [("new", 0, False, [])]
    at = 0
    for length in [30, 5] + [40] * 20:  # the 5-second stop is the shortest of 22, then the 30-second one
        steps += [("update", at + 10, True, []), ("update", at + 10 + length, False, [])]
        at += 10 + length
    steps.append(("end", at + 1, False, []))
    out, _ = run_tally(one_object(steps))
    lengths = sorted(round(to - start) for start, to in out["time_tally"]["stopped"])
    assert lengths == [40] * 20 and out["time_tally"]["stops"] == 22
    assert out["time_tally"]["stationary_time"] == 835


@needs_node
@pytest.mark.parametrize("zones, expected", [
    ("zone_a", []), (None, []), ({"zone_a": 1}, []),
    (["zone_a", 7, None, "zone_a", "zone_b", ""], ["zone_a", "zone_b"]),
    ([f"zone_{i}" for i in range(60)], [f"zone_{i}" for i in range(50)]),
], ids=["text", "null", "mapping", "junk-in-the-list", "more-than-fifty"])
def test_only_zone_names_are_tallied_and_at_most_fifty(zones, expected):
    messages = one_object([("new", 0, False, []), ("end", 2, False, [])])
    for msg in messages:
        msg["payload"]["after"]["current_zones"] = zones
    out, _ = run_tally(messages)
    assert list(out["time_tally"]["zone_times"]) == expected


@needs_node
@pytest.mark.parametrize("payload", [
    "online", None, 7, [], {}, {"type": "end"}, {"type": "end", "after": None},
    {"type": "end", "after": {"id": "", "frame_time": T0}}, {"type": "end", "after": {"id": 7, "frame_time": T0}},
    {"type": "end", "after": {"id": TALLY_ID, "frame_time": "soon"}},
    {"type": "sideways", "before": {"frame_time": T0}, "after": {"id": TALLY_ID, "frame_time": T0}},
], ids=["text", "null", "number", "list", "empty", "no-after", "after-null", "no-id", "id-number", "time-text",
        "unknown-type"])
def test_a_message_that_is_not_frigates_shape_goes_on_untouched(payload):
    out, flow = run_tally([{"topic": "frigate/events", "payload": payload, "time_tally": {"stationary_time": 999}}])
    assert out["time_tally"] is None and flow.get("time_tallies", {}) == {}


@needs_node
@pytest.mark.parametrize("flow", [{"time_tallies": "junk"}, {"time_tallies": [1]}, {"time_tallies": {TALLY_ID: "junk"}}])
def test_junk_in_flow_context_is_replaced(flow):
    out, _ = run_tally(one_object(STOP), flow=flow)
    assert out["time_tally"] == STOP_TALLY


def test_every_frigate_event_message_passes_the_tally_first():
    flows = json.loads(FLOWS.read_text())
    by_id = {node["id"]: node for node in flows}
    tally, source, switch = named(flows, TALLY), by_id["f20c74c0ccfd256c"], by_id["2deec9d340d5ed26"]
    assert (source["type"], source["topic"]) == ("mqtt in", "frigate/events")
    assert source["wires"] == [["86c86b0d82d13028", tally["id"]]] and by_id["86c86b0d82d13028"]["type"] == "debug"
    assert tally["wires"] == [[switch["id"]]] and switch["name"] == 'payload.type == "end"'
    assert [node["id"] for node in flows if switch["id"] in sum(node.get("wires", []), [])] == [tally["id"]]
    assert (tally["type"], tally["outputs"], tally["initialize"], tally["finalize"]) == ("function", 1, "", "")
    group = by_id[tally["g"]]
    assert group["id"] == "0a5faeac9fbd6d55" and tally["id"] in group["nodes"] and tally["z"] == source["z"]
    assert group["x"] < tally["x"] < group["x"] + group["w"] and group["y"] < tally["y"] < group["y"] + group["h"]
