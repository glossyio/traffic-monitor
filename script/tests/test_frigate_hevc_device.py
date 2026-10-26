"""The HEVC decoder reaches Frigate by a stable udev symlink, whatever /dev/media number it has (#231)."""

import shutil
import subprocess
from pathlib import Path

import pytest
from tmsetup_render import load_role_yaml, render

REPO = Path(__file__).resolve().parents[2]
ROLE = REPO / "script" / "ansible" / "roles" / "tmsetup"
SYMLINK = "/dev/rpi-hevc-dec"
RULE = 'SUBSYSTEM=="media", ATTR{model}=="rpi-hevc-dec", SYMLINK+="rpi-hevc-dec", TAG+="systemd"'
RULE_DEST = "/etc/udev/rules.d/60-traffic-monitor-hevc-dec.rules"


def rule_lines():
    text = render("script/ansible/roles/tmsetup/templates/60-traffic-monitor-hevc-dec.rules.j2",
                  tmsetup_hevc_device=SYMLINK)
    return [line for line in text.splitlines() if line.strip() and not line.startswith("#")]


def udevadm_version():
    if not shutil.which("udevadm"):
        return 0
    return int(subprocess.run(["udevadm", "--version"], capture_output=True, text=True).stdout.split()[0])


def test_symlink_path_is_fixed_in_vars():
    assert load_role_yaml("vars/main.yml")["tmsetup_hevc_device"] == SYMLINK
    assert "tmsetup_default_hevc_device" not in load_role_yaml("defaults/main.yml")


def test_rule_matches_the_decoder_model_and_tags_it_for_systemd():
    assert rule_lines() == [RULE]


def test_rule_passes_udevadm_verify(tmp_path):
    if udevadm_version() < 254:
        pytest.skip("udevadm verify needs systemd 254 or newer")
    rule = tmp_path / "60-traffic-monitor-hevc-dec.rules"
    rule.write_text("\n".join(rule_lines()) + "\n")
    assert subprocess.run(["udevadm", "verify", str(rule)], capture_output=True, text=True).returncode == 0


def test_frigate_setup_installs_the_rule_then_restarts_frigate():
    tasks = {task["name"]: task for task in load_role_yaml("tasks/frigate_setup.yml")}
    task = tasks["TMSetup - Frigate Setup - Create udev rule for the HEVC decoder symlink"]
    template = task["ansible.builtin.template"]
    assert (template["src"], template["dest"], template["mode"]) == ("60-traffic-monitor-hevc-dec.rules.j2", RULE_DEST, "0644")
    assert task["notify"] == ["Reload udev rules and trigger", "Restart frigate.service"]
    handlers = [handler["name"] for handler in load_role_yaml("handlers/main.yml")]
    assert handlers.index("Reload udev rules and trigger") < handlers.index("Restart frigate.service")
    reload = next(h for h in load_role_yaml("handlers/main.yml") if h["name"] == "Reload udev rules and trigger")
    assert reload["ansible.builtin.shell"].split(" && ") == ["udevadm control --reload", "udevadm trigger", "udevadm settle"]
    cleanup = tasks["TMSetup - Frigate Setup - Remove the install-time HEVC scan script"]
    assert cleanup["ansible.builtin.file"] == {"path": "{{ tmsetup_codedir }}/utils/find_hevc_device.sh", "state": "absent"}


def test_install_time_scan_is_gone():
    names = [task["name"] for task in load_role_yaml("tasks/set_vars.yml")]
    assert "TMSetup - Main - Find HEVC hardware device" not in names
    assert "TMSetup - Main - Set HEVC device fact" not in names
    assert not (REPO / "utils" / "find_hevc_device.sh").exists()
    assert "hevc" not in (ROLE / "tasks" / "set_vars.yml").read_text().lower()
