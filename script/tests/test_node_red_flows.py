"""Check Node-RED's flows.json off-device."""

import json
import re
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
    results.push({ result: result === undefined ? null : result, logged });
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
    """The token is rendered from Node-RED's environment by template nodes; an http request node's URL sees only
    msg, so the restore request gets its URL from a template too."""
    flows = json.loads(FLOWS.read_text())
    by_id = {node["id"]: node for node in flows}
    backup = named(flows, "backup read msg.url")
    for node in (by_id["9c944328e288b2dc"], by_id["d739b10ce5fa8f40"], backup):
        assert node["type"] == "template"
        assert (node["field"], node["fieldType"], node["syntax"]) == ("url", "msg", "mustache")
        assert "{{{env.TM_THINGSBOARD_ACCESS_TOKEN}}}" in node["template"]
        assert "{{{global.config.thingsboard.url}}}" in node["template"]
    assert backup["template"].endswith("/attributes?clientKeys=backup")
    assert backup["z"] == tab_id(flows, "thingsboard")
    assert by_id["0372cefb5e2ec968"]["wires"] == [[backup["id"]]]
    assert backup["wires"] == [["56cafb11de5348b2"]]
    assert by_id["56cafb11de5348b2"]["url"] == ""


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


def frigate_event(camera):
    return {"frigate_event": {"camera": camera, "id": "1.0-abc"}, "payload": {}}


def append_events(cameras, context):
    """Run append config on one event per camera, in one run; returns the steps and the global context after."""
    append = node_by_id(APPEND_CONFIG)
    run = run_functions([(append, frigate_event(camera)) for camera in cameras], context=context)
    return run["results"], run["global"]


def append_config(config, camera, context=None):
    _, context = load_config(config, context)
    [step], context = append_events([camera], context)
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


# What leaves the device and what the Frigate API is asked, by key. Plate Recognizer is sent the camera's name in
# config.yml and the regions the admin set (issue #249), ThingsBoard's copy of the config has no Frigate names,
# and the node that asks Frigate for its daily summary maps the key back to the name Frigate uses.

PR_FORMAT = "ce5360091646c733"  # plate-recognizer: format http request
PR_ROW = "f76c2b5b2b99096a"  # plate-recognizer: write params for plate_recognizer insert
TB_CONFIG = "9941048ea93dc79c"  # thingsboard: format init-config client-side attributes
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


@needs_node
def test_config_tm_has_no_frigate_camera_and_leaves_the_config_alone():
    config = config_with_cameras({
        "camera_1_3fa9c2": {"frigate_camera": "oak_ave_wide", "enabled": True},
        "main_st": {"enabled": False},
    })
    # The node is given the object that is global.config, so the global context shows whether it was edited.
    node = {**node_by_id(TB_CONFIG), "func": 'msg.payload = global.get("config");\n' + node_by_id(TB_CONFIG)["func"]}
    run = run_functions([(node, {})], context={"config": config})
    [step] = run["results"]
    sent = step["result"]["payload"]
    assert "oak_ave_wide" not in json.dumps(sent) and "frigate_camera" not in json.dumps(sent)
    assert sent["config_tm"]["sensors"]["cameras"]["camera_1_3fa9c2"]["enabled"] is True
    assert sent["config_tm"]["sensors"]["cameras"]["main_st"] == {"enabled": False}
    assert run["global"]["config"]["sensors"]["cameras"]["camera_1_3fa9c2"]["frigate_camera"] == "oak_ave_wide"


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


def test_every_node_that_asks_frigate_for_a_camera_by_name_maps_the_key_back():
    """Nodes that call Frigate's API (frigate:5000): config/raw, config/save, version, events/summary, and the
    thumbnail and snapshot of an event id. None puts a camera name in its URL. Frigate's summary lists every camera
    by Frigate's name, and the one node that picks a camera out of it is "structure frigate api/summary"
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
