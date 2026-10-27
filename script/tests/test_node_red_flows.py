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
