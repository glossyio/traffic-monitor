"""Check Node-RED's flows.json off-device."""

import json
from pathlib import Path

FLOWS = Path(__file__).resolve().parents[2] / "container" / "node-red-tm" / "data" / "flows.json"


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
