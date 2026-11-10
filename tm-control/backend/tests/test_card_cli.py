"""`tm-control card`: the device's card, printed by root. Run in-process like test_claim_cli.py, with the root check
faked (the privilege drop is recorded, not made), `TM_CONTROL_*` pointing into tmp_path and a fake nmcli on PATH.

All names, passwords and codes here are placeholders.
"""

import json
import os
import socket
import stat
import sys
from pathlib import Path

import pytest

from tm_control.cli import main
from tm_control.core import card as card_module
from tm_control.core.auth import Device
from tm_control.core.state import State

FAKE_NMCLI = Path(__file__).resolve().parent / "fixtures" / "fake_nmcli.py"
PASSWORD = "ABCD-EFGH-JKLM"
CODE = "WXYZ-2345"
FULL_CARD = f"""Traffic Monitor tm-ab12
  Open on your network   http://tm-ab12.local/
  Hotspot name           TM-AB12
  Hotspot password       {PASSWORD}
  Open on the hotspot    http://10.42.0.1/ (a phone that joins opens it by itself)
  Setup code             {CODE} (works once)
"""

# The state directory is the test user's, which a run as real root would refuse (see test_claim_cli.py).
pytestmark = pytest.mark.skipif(
    os.geteuid() == 0, reason="the test's state directory is root's, which the CLI refuses as root"
)


class Unit:
    def __init__(self, tmp_path, settings, monkeypatch):
        self.settings = settings
        self.calls = []
        self.nmcli_state = tmp_path / "nmcli.json"
        self.set_profile({"802-11-wireless.ssid": "TM-AB12", "802-11-wireless-security.key-mgmt": "wpa-psk"})
        self.write_password(PASSWORD)
        settings.setup_code_file.parent.mkdir(exist_ok=True)
        settings.setup_code_file.write_text(CODE + "\n")

    def set_profile(self, props):
        profiles = {} if props is None else {"tm-hotspot": props}
        self.nmcli_state.write_text(json.dumps({"profiles": profiles, "active": []}))

    def write_password(self, text):
        self.settings.secrets_dir.mkdir(exist_ok=True)
        (self.settings.secrets_dir / "hotspot_password").write_text(text)

    def claim(self):
        state = State(self.settings.state_dir / "state.sqlite")
        state.migrate()
        Device(state).claim("admin", "correct horse 1", "1")


@pytest.fixture
def device(tmp_path, settings, monkeypatch):
    """A unit as the root command sees it: unclaimed, with a hotspot profile, a password file and a setup code file.

    The CLI runs as "root" (os.geteuid is 0, the drop to the state directory's owner is recorded), the hostname is
    tm-ab12, and PATH starts with a fake nmcli.
    """
    unit = Unit(tmp_path, settings, monkeypatch)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    nmcli = bin_dir / "nmcli"
    nmcli.write_text(f"#!/bin/sh\nexec {sys.executable} {FAKE_NMCLI} \"$@\"\n")
    nmcli.chmod(nmcli.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_NMCLI_STATE", str(unit.nmcli_state))
    monkeypatch.delenv("STATE_DIRECTORY", raising=False)
    monkeypatch.delenv("TM_CONTROL_FAKE", raising=False)
    monkeypatch.setenv("TM_CONTROL_STATE_DIR", str(settings.state_dir))
    monkeypatch.setenv("TM_CONTROL_SECRETS_DIR", str(settings.secrets_dir))
    monkeypatch.setenv("TM_CONTROL_MANIFEST", str(settings.manifest_path))
    monkeypatch.setenv("TM_CONTROL_SETUP_CODE_FILE", str(settings.setup_code_file))
    monkeypatch.setattr(socket, "gethostname", lambda: "tm-ab12")
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    monkeypatch.setattr(os, "setgroups", lambda groups: unit.calls.append("setgroups"))
    monkeypatch.setattr(os, "setgid", lambda gid: unit.calls.append("setgid"))
    monkeypatch.setattr(os, "setuid", lambda uid: unit.calls.append("setuid"))
    settings.state_dir.mkdir(mode=0o700, exist_ok=True)
    return unit


def test_an_unclaimed_unit_prints_the_whole_card(device, capsys):
    assert main(["card"]) == 0
    assert capsys.readouterr().out == FULL_CARD


def test_a_claimed_unit_says_so_and_prints_no_code(device, capsys):
    device.claim()  # the setup-code file is still there
    assert main(["card"]) == 0
    out = capsys.readouterr().out
    assert "  Setup code             Already claimed.\n" in out
    assert CODE not in out
    assert PASSWORD in out


def test_unclaimed_only_prints_nothing_for_a_claimed_unit(device, capsys):
    device.claim()
    assert main(["card", "--unclaimed-only"]) == 3
    out, err = capsys.readouterr()
    assert out == "" and err == ""


def test_unclaimed_only_prints_the_card_for_an_unclaimed_unit(device, capsys):
    assert main(["card", "--unclaimed-only"]) == 0
    assert capsys.readouterr().out == FULL_CARD


def test_json_has_the_same_values(device, capsys):
    assert main(["card", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "hostname": "tm-ab12",
        "local_url": "http://tm-ab12.local/",
        "hotspot": {"name": "TM-AB12", "password": PASSWORD, "url": "http://10.42.0.1/"},
        "claimed": False,
        "setup_code": CODE,
    }


def test_json_for_a_claimed_unit_without_a_hotspot(device, capsys):
    device.claim()
    device.set_profile(None)
    assert main(["card", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "hostname": "tm-ab12",
        "local_url": "http://tm-ab12.local/",
        "hotspot": None,
        "claimed": True,
        "setup_code": None,
    }


def test_a_unit_without_a_hotspot_profile_says_how_to_get_one(device, capsys):
    device.set_profile(None)
    assert main(["card"]) == 0
    assert capsys.readouterr().out == f"""Traffic Monitor tm-ab12
  Open on your network   http://tm-ab12.local/
  Hotspot name           Not set up. Run tmsetup.sh -t wifi.
  Setup code             {CODE} (works once)
"""


def test_a_hotspot_that_networkmanager_cannot_report_is_not_called_unset(device, tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("FAKE_NMCLI_STATE", str(tmp_path / "missing.json"))  # the fake dies: unreadable
    assert main(["card"]) == 0
    out = capsys.readouterr().out
    assert "  Hotspot name           Unknown. NetworkManager did not answer.\n" in out
    assert "Not set up" not in out
    assert f"  Hotspot password       {PASSWORD}\n" in out


def test_an_open_hotspot_is_named_as_open(device, capsys):
    device.write_password("")
    assert main(["card"]) == 0
    out = capsys.readouterr().out
    assert "  Hotspot name           TM-AB12\n" in out
    assert "  Hotspot password       None. Anyone nearby can join.\n" in out


def test_a_missing_password_file_is_not_a_traceback(device, capsys):
    (device.settings.secrets_dir / "hotspot_password").unlink()
    assert main(["card"]) == 0
    out, err = capsys.readouterr()
    assert "  Hotspot password       Not stored on this device.\n" in out
    assert "Traceback" not in out + err


def test_a_missing_setup_code_file_says_how_to_get_one(device, capsys):
    device.settings.setup_code_file.unlink()
    assert main(["card"]) == 0
    assert "  Setup code             Missing. Run tmsetup.sh again to get one.\n" in capsys.readouterr().out


def test_card_refuses_without_root(device, capsys, monkeypatch):
    monkeypatch.setattr(os, "geteuid", lambda: 1000)
    assert main(["card"]) == 2
    out, err = capsys.readouterr()
    assert out == ""
    assert err == "tm-control: card must run as root: sudo tm-control card\n"
    assert PASSWORD not in err and CODE not in err


def test_the_database_is_never_opened_as_root(device, monkeypatch):
    """The manifest, the hotspot, the password and the setup code are read before open_state drops privileges."""
    order = []
    real_open_state = card_module.open_state
    real_load_manifest = card_module.load_manifest
    real_hotspot = card_module.hotspot
    real_read_text = Path.read_text

    def open_state(settings):
        order.append("open_state")
        assert device.calls == []  # nothing dropped yet
        return real_open_state(settings)

    def read_text(path, *args, **kwargs):
        order.append(f"read {path.name}")
        return real_read_text(path, *args, **kwargs)

    monkeypatch.setattr(card_module, "open_state", open_state)
    monkeypatch.setattr(card_module, "load_manifest", lambda path: (order.append("manifest"), real_load_manifest(path))[1])
    monkeypatch.setattr(card_module, "hotspot", lambda profile: (order.append("hotspot"), real_hotspot(profile))[1])
    monkeypatch.setattr(Path, "read_text", read_text)
    assert main(["card"]) == 0
    assert order[-1] == "open_state"
    for step in ("manifest", "hotspot", "read hotspot_password", f"read {device.settings.setup_code_file.name}"):
        assert step in order[:-1], order
    assert device.calls == ["setgroups", "setgid", "setuid"]  # then it dropped, to open the database as its owner


def test_the_card_is_not_written_anywhere(device, tmp_path, capsys):
    before = {path for path in tmp_path.rglob("*")}
    assert main(["card"]) == 0
    capsys.readouterr()
    new = {path for path in tmp_path.rglob("*")} - before
    # opening the state creates state.sqlite (and its -wal and -shm); nothing else is written
    assert all(path.parent == device.settings.state_dir for path in new), new
