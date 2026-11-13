"""The hotspot-profile root helper, run as a script against a fake nmcli (fixtures/fake_nmcli.py).

fixtures/run_job.py runs it with a non-root euid, so the NMCLI stand-in is used even when the suite runs as root, and
the password file's owner is left alone. Profiles are dicts of nmcli property names to values, keyed by name. Every
password here is a placeholder.
"""

import importlib.machinery
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

JOB = Path(__file__).resolve().parents[2] / "jobs" / "tm-hotspot-setup"
RUNNER = Path(__file__).resolve().parent / "fixtures" / "run_job.py"
FAKE = Path(__file__).resolve().parent / "fixtures" / "fake_nmcli.py"
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
KEEP = object()  # run again on the state the last run left


def right_hotspot(psk="placeholder-psk", **changes):
    """A tm-hotspot profile with everything the helper wants, so that nothing needs changing."""
    return {
        "connection.interface-name": "wlan0",
        "connection.autoconnect": "yes",
        "connection.autoconnect-priority": "-100",
        "802-11-wireless.mode": "ap",
        "802-11-wireless.ssid": "TM-AB12",
        "802-11-wireless-security.key-mgmt": "wpa-psk",
        "802-11-wireless-security.psk": psk,
        "ipv4.method": "shared",
        "ipv4.addresses": "10.42.0.1/24",
        "ipv6.method": "disabled",
        **changes,
    }


def hand_made(ssid="Depot", psk="placeholder-psk", **changes):
    """A hotspot made by hand: access-point mode, no address of ours, not set to start by itself."""
    props = {"802-11-wireless.mode": "ap", "802-11-wireless.ssid": ssid, "connection.autoconnect": "no",
             "ipv4.method": "shared"}
    if psk is not None:
        props |= {"802-11-wireless-security.key-mgmt": "wpa-psk", "802-11-wireless-security.psk": psk}
    return props | changes


def invoke(tmp_path, profiles=None, password=None, active=(), fail=()):
    """Run the helper once; returns the finished process. The password file is tmp_path/hotspot-password."""
    state, log, file = tmp_path / "nmcli-state.json", tmp_path / "nmcli.log", tmp_path / "hotspot-password"
    if profiles is not KEEP:
        state.write_text(json.dumps({"profiles": profiles or {}, "active": list(active), "fail": list(fail)}))
    if password is not None:
        file.write_text(password)
    log.unlink(missing_ok=True)
    env = {
        "PATH": os.environ["PATH"],
        "NMCLI": str(FAKE),
        "FAKE_NMCLI_STATE": str(state),
        "FAKE_NMCLI_LOG": str(log),
    }
    argv = ["--profile", "tm-hotspot", "--device", "wlan0", "--address", "10.42.0.1/24", "--ssid", "TM-AB12",
            "--password-file", str(file), "--group", "tm-code"]
    return subprocess.run(
        [sys.executable, "-I", str(RUNNER), str(JOB), *argv], env=env, capture_output=True, text=True, timeout=30
    )


def run(tmp_path, **kwargs):
    """The JSON line, the profiles after, the password file's text (None if absent), and the nmcli calls (argv lists)."""
    result = invoke(tmp_path, **kwargs)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stderr == "" and result.stdout.count("\n") == 1
    file = tmp_path / "hotspot-password"
    log = tmp_path / "nmcli.log"
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    profiles = json.loads((tmp_path / "nmcli-state.json").read_text())["profiles"]
    return json.loads(result.stdout), profiles, file.read_text() if file.exists() else None, calls


def verbs(calls):
    """The words after `connection` in each call: show, add, modify, up, down."""
    return [call[call.index("connection") + 1] for call in calls]


def modifies(calls):
    return [call for call in calls if "modify" in call]


def load_job_module():
    loader = importlib.machinery.SourceFileLoader("tm_hotspot_setup", str(JOB))
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    before, sys.dont_write_bytecode = sys.dont_write_bytecode, True  # no __pycache__ beside the script
    try:
        loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = before
    return module


def test_the_script_and_the_fake_are_executable():
    assert os.access(JOB, os.X_OK) and os.access(FAKE, os.X_OK)


def test_a_unit_without_a_hotspot_gets_one(tmp_path):
    out, profiles, password, calls = run(tmp_path, profiles={})
    assert out == {"changed": True, "created": True, "adopted": None, "ssid": "TM-AB12",
                   "secured": True, "autoconnect": True, "active": False}
    hotspot = profiles["tm-hotspot"]
    assert hotspot["ipv4.addresses"] == "10.42.0.1/24" and hotspot["ipv4.method"] == "shared"
    assert hotspot["connection.autoconnect-priority"] == "-100" and hotspot["ipv6.method"] == "disabled"
    assert hotspot["connection.autoconnect"] == "yes" and hotspot["connection.interface-name"] == "wlan0"
    assert hotspot["802-11-wireless.mode"] == "ap" and hotspot["802-11-wireless.ssid"] == "TM-AB12"
    assert hotspot["802-11-wireless.band"] == "bg" and hotspot["802-11-wireless.hidden"] == "no"
    assert hotspot["802-11-wireless.cloned-mac-address"] == "permanent"
    assert hotspot["802-11-wireless-security.key-mgmt"] == "wpa-psk"
    assert hotspot["802-11-wireless-security.proto"] == "rsn"
    assert hotspot["802-11-wireless-security.pairwise"] == "ccmp" and hotspot["802-11-wireless-security.group"] == "ccmp"
    assert re.fullmatch(f"[{ALPHABET}]{{4}}-[{ALPHABET}]{{4}}-[{ALPHABET}]{{4}}", password)
    assert hotspot["802-11-wireless-security.psk"] == password
    assert (tmp_path / "hotspot-password").stat().st_mode & 0o777 == 0o640
    assert verbs(calls).count("add") == 1 and not {"up", "down"} & set(verbs(calls))


def test_a_second_run_changes_nothing(tmp_path):
    first, _, password, _ = run(tmp_path, profiles={})
    assert first["created"]
    out, profiles, again, calls = run(tmp_path, profiles=KEEP)
    assert out == {"changed": False, "created": False, "adopted": None, "ssid": "TM-AB12",
                   "secured": True, "autoconnect": True, "active": False}
    assert again == password and profiles["tm-hotspot"]["802-11-wireless-security.psk"] == password
    assert not {"add", "modify", "up", "down"} & set(verbs(calls))


def test_the_password_file_is_the_source_of_truth(tmp_path):
    out, profiles, password, calls = run(
        tmp_path, profiles={"tm-hotspot": right_hotspot(psk="OLDPLACEHOLDER1")}, password="NEWPLACEHOLDER1"
    )
    assert out["changed"] and not out["created"] and out["adopted"] is None
    assert password == "NEWPLACEHOLDER1"
    assert profiles["tm-hotspot"]["802-11-wireless-security.psk"] == "NEWPLACEHOLDER1"
    assert len(modifies(calls)) == 1
    assert "***" in modifies(calls)[0] and "NEWPLACEHOLDER1" not in modifies(calls)[0]


def test_other_settings_are_put_back_but_the_name_on_air_is_not(tmp_path):
    drifted = right_hotspot(
        psk="placeholder-psk",
        **{"ipv4.addresses": "192.168.7.1/24", "ipv6.method": "auto", "connection.autoconnect-priority": "0",
           "802-11-wireless.ssid": "Our Own Name", "802-11-wireless.band": "a", "802-11-wireless.hidden": "yes"},
    )
    out, profiles, _, calls = run(tmp_path, profiles={"tm-hotspot": drifted}, password="placeholder-psk")
    hotspot = profiles["tm-hotspot"]
    assert out["changed"] and out["ssid"] == "Our Own Name"
    assert (hotspot["ipv4.addresses"], hotspot["ipv6.method"]) == ("10.42.0.1/24", "disabled")
    assert hotspot["connection.autoconnect-priority"] == "-100"
    assert (hotspot["802-11-wireless.ssid"], hotspot["802-11-wireless.band"], hotspot["802-11-wireless.hidden"]) == (
        "Our Own Name", "a", "yes")
    assert len(modifies(calls)) == 1


def test_a_hand_made_hotspot_is_adopted_with_its_name_and_password(tmp_path):
    out, profiles, password, calls = run(tmp_path, profiles={"Hotspot": hand_made()})
    assert out == {"changed": True, "created": False, "adopted": "Hotspot", "ssid": "Depot",
                   "secured": True, "autoconnect": True, "active": False}
    assert list(profiles) == ["tm-hotspot"]
    hotspot = profiles["tm-hotspot"]
    assert hotspot["802-11-wireless.ssid"] == "Depot" and password == "placeholder-psk"
    assert hotspot["802-11-wireless-security.psk"] == "placeholder-psk"
    assert hotspot["connection.autoconnect"] == "yes" and hotspot["ipv4.addresses"] == "10.42.0.1/24"
    assert hotspot["connection.interface-name"] == "wlan0" and hotspot["ipv6.method"] == "disabled"
    assert hotspot["connection.autoconnect-priority"] == "-100"
    assert (tmp_path / "hotspot-password").stat().st_mode & 0o777 == 0o640
    assert "add" not in verbs(calls) and len(modifies(calls)) == 1


def test_adoption_never_overwrites_an_existing_password_file(tmp_path):
    out, profiles, password, _ = run(tmp_path, profiles={"Hotspot": hand_made()}, password="EXISTING-PLACEHOLDER")
    assert out["adopted"] == "Hotspot"
    assert password == "EXISTING-PLACEHOLDER"
    assert profiles["tm-hotspot"]["802-11-wireless-security.psk"] == "EXISTING-PLACEHOLDER"


def test_among_several_the_one_that_starts_by_itself_is_adopted(tmp_path):
    profiles = {
        "Newest but off": hand_made(ssid="A", **{"connection.timestamp": "900"}),
        "Starts by itself": hand_made(ssid="B", **{"connection.autoconnect": "yes", "connection.timestamp": "100"}),
        "Starts, used last": hand_made(ssid="C", **{"connection.autoconnect": "yes", "connection.timestamp": "200"}),
        "Client": {"802-11-wireless.mode": "infrastructure", "connection.autoconnect": "yes"},
        "Wired": {"connection.type": "802-3-ethernet", "connection.autoconnect": "yes"},
    }
    out, after, _, _ = run(tmp_path, profiles=profiles)
    assert out["adopted"] == "Starts, used last" and out["ssid"] == "C"
    assert after["tm-hotspot"]["connection.autoconnect"] == "yes"
    assert after["Newest but off"]["connection.autoconnect"] == "no"
    assert after["Starts by itself"]["connection.autoconnect"] == "no"
    assert after["Client"]["connection.autoconnect"] == "yes" and after["Wired"]["connection.autoconnect"] == "yes"


def test_when_none_starts_by_itself_the_most_recently_used_is_adopted(tmp_path):
    profiles = {
        "Old": hand_made(ssid="A", **{"connection.timestamp": "100"}),
        "Recent": hand_made(ssid="B", **{"connection.timestamp": "300"}),
        "Middle": hand_made(ssid="C", **{"connection.timestamp": "200"}),
    }
    out, after, _, _ = run(tmp_path, profiles=profiles)
    assert out["adopted"] == "Recent" and out["autoconnect"] is True
    assert {name: after[name]["connection.autoconnect"] for name in ("Old", "Middle", "tm-hotspot")} == {
        "Old": "no", "Middle": "no", "tm-hotspot": "yes"}


def test_choose_adoptee_picks_only_access_points():
    job = load_job_module()
    assert job.choose_adoptee([]) is None
    client = {"name": "Home", "mode": "infrastructure", "autoconnect": True, "timestamp": 5}
    assert job.choose_adoptee([client]) is None
    ap = {"name": "Hotspot", "mode": "ap", "autoconnect": False, "timestamp": 0}
    assert job.choose_adoptee([client, ap]) is ap


def test_an_open_hand_made_hotspot_is_adopted_as_it_is(tmp_path):
    out, profiles, password, calls = run(tmp_path, profiles={"Open": hand_made(psk=None)})
    assert out["secured"] is False and out["adopted"] == "Open" and out["autoconnect"] is True
    assert password == "" and (tmp_path / "hotspot-password").exists()
    assert not any(arg.startswith("802-11-wireless-security") for call in modifies(calls) for arg in call)
    assert "802-11-wireless-security.key-mgmt" not in profiles["tm-hotspot"]
    # and a second run leaves the open hotspot as it is
    again, _, _, calls = run(tmp_path, profiles=KEEP)
    assert again["changed"] is False and again["secured"] is False and not {"add", "modify"} & set(verbs(calls))


def test_an_active_adopted_hotspot_is_changed_but_never_reactivated(tmp_path):
    out, profiles, _, calls = run(tmp_path, profiles={"Hotspot": hand_made()}, active=["Hotspot"])
    assert out["adopted"] == "Hotspot" and out["changed"] is True and out["active"] is True
    assert "tm-hotspot" in profiles
    assert not {"up", "down"} & set(verbs(calls))


def test_a_hotspot_turned_off_stays_off(tmp_path):
    off = right_hotspot(**{"connection.autoconnect": "no"})
    out, profiles, _, calls = run(tmp_path, profiles={"tm-hotspot": off}, password="placeholder-psk")
    assert out["changed"] is False and out["autoconnect"] is False
    assert profiles["tm-hotspot"]["connection.autoconnect"] == "no"
    assert not {"add", "modify", "up", "down"} & set(verbs(calls))


def test_an_existing_hotspot_does_not_disable_the_other_hotspots(tmp_path):
    profiles = {"tm-hotspot": right_hotspot(), "Other": hand_made(**{"connection.autoconnect": "yes"})}
    out, after, _, _ = run(tmp_path, profiles=profiles, password="placeholder-psk")
    assert out["changed"] is False and after["Other"]["connection.autoconnect"] == "yes"


def test_the_password_is_in_no_output(tmp_path):
    secrets_seen = []
    for name, profiles in (("create", {}), ("adopt", {"Hotspot": hand_made(psk="adopted-placeholder")})):
        directory = tmp_path / name
        directory.mkdir()
        result = invoke(directory, profiles=profiles)
        assert result.returncode == 0
        password = (directory / "hotspot-password").read_text()
        secrets_seen.append(password)
        everything = result.stdout + result.stderr + (directory / "nmcli.log").read_text()
        assert password not in everything
        if name == "create":
            assert "***" in (directory / "nmcli.log").read_text()
    assert secrets_seen[1] == "adopted-placeholder"


def test_names_with_colons_and_backslashes_are_read_whole(tmp_path):
    name = "a:b\\c"  # a:b\c
    out, profiles, _, _ = run(tmp_path, profiles={name: hand_made()})
    assert out["adopted"] == name
    assert list(profiles) == ["tm-hotspot"]


def test_a_failing_nmcli_is_a_refusal_not_a_traceback(tmp_path):
    result = invoke(tmp_path, profiles={}, fail=["add"])
    assert result.returncode == 1 and result.stdout == ""
    assert result.stderr.startswith("refused: ") and len(result.stderr.strip().splitlines()) == 1
    assert "Traceback" not in result.stderr
    # the fake quotes the command line, psk included, in its error; the helper must not pass that on
    password = (tmp_path / "hotspot-password").read_text()
    assert password and password not in result.stderr


def test_a_failing_listing_is_a_refusal_too(tmp_path):
    result = invoke(tmp_path, profiles={}, fail=["show"])
    assert result.returncode == 1 and result.stderr.startswith("refused: ") and result.stdout == ""
    assert not (tmp_path / "hotspot-password").exists()


def test_a_profile_of_our_name_that_is_not_wi_fi_is_a_refusal(tmp_path):
    result = invoke(tmp_path, profiles={"tm-hotspot": {"connection.type": "802-3-ethernet"}})
    assert result.returncode == 1 and "not a Wi-Fi profile" in result.stderr


def test_an_empty_password_file_beside_no_profile_is_a_refusal(tmp_path):
    result = invoke(tmp_path, profiles={}, password="")
    assert result.returncode == 1 and result.stderr.startswith("refused: ")
    assert (tmp_path / "hotspot-password").read_text() == ""


def test_a_new_password_is_three_groups_of_four_from_the_alphabet():
    job = load_job_module()
    assert job.ALPHABET == ALPHABET and job.PRIORITY == "-100"
    passwords = {job.new_password() for _ in range(50)}
    assert len(passwords) == 50
    assert all(re.fullmatch(f"[{ALPHABET}]{{4}}-[{ALPHABET}]{{4}}-[{ALPHABET}]{{4}}", word) for word in passwords)


def test_root_ignores_nmcli_from_the_environment(monkeypatch, tmp_path):
    job = load_job_module()
    planted = str(tmp_path / "planted-nmcli")
    monkeypatch.setenv("NMCLI", planted)
    monkeypatch.setattr(job.os, "geteuid", lambda: 0)
    assert job.nmcli_binary() == "/usr/bin/nmcli"
    monkeypatch.setattr(job.os, "geteuid", lambda: 1000)
    assert job.nmcli_binary() == planted
