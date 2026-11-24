"""Check the About page's credits list (tm-control/ui/src/modules/about/credits.json).

Every runtime dependency and every installed component must have a credit, and no credit may answer for
something that is gone. Without this, a new dependency would ship with no credit and nobody would notice.
"""

import json
from collections import Counter
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CREDITS = ROOT / "tm-control" / "ui" / "src" / "modules" / "about" / "credits.json"
UI_PACKAGE = ROOT / "tm-control" / "ui" / "package.json"
NODE_RED_PACKAGE = ROOT / "container" / "node-red-tm" / "data" / "package.json"
REQUIREMENTS = ROOT / "tm-control" / "backend" / "requirements.txt"
SERVICE_TASKS = ROOT / "script" / "ansible" / "roles" / "tmsetup" / "tasks" / "tm-control_service.yml"

GROUPS = {"built-on", "video", "data", "app", "device"}
KEYS = {"name", "license", "url", "group", "note", "does", "covers"}
BUILT_ON = ["Frigate NVR", "Node-RED"]


def rows():
    return json.loads(CREDITS.read_text())


def manifest_components():
    """The keys of `components:` in the manifest the service tasks write, read from the YAML (not grepped)."""
    for task in yaml.safe_load(SERVICE_TASKS.read_text()):
        manifest = task.get("ansible.builtin.set_fact", {}).get("tmsetup_tm_control_manifest")
        if manifest:
            return set(manifest["components"])
    raise AssertionError(f"No task in {SERVICE_TASKS} sets tmsetup_tm_control_manifest")


def required():
    """What must be credited, as covers tokens: the three dependency files and the manifest's components."""
    tokens = {f"ui:{name}" for name in json.loads(UI_PACKAGE.read_text())["dependencies"]}
    tokens |= {f"node-red:{name}" for name in json.loads(NODE_RED_PACKAGE.read_text())["dependencies"]}
    for line in REQUIREMENTS.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            tokens.add(f"python:{line.split('==')[0].strip()}")
    tokens |= {f"component:{key}" for key in manifest_components()}
    return tokens


def covered():
    return {token for row in rows() for token in row.get("covers", [])}


def test_every_dependency_and_component_has_a_credit():
    missing = required() - covered()
    assert not missing, f"Add a row to credits.json for: {sorted(missing)} (see docs/development/tm-control.md)"


def test_no_credit_answers_for_something_that_is_gone():
    stale = covered() - required()
    assert not stale, f"Remove or fix the covers of rows in credits.json for: {sorted(stale)}"


def test_nothing_is_covered_twice():
    counts = Counter(token for row in rows() for token in row.get("covers", []))
    twice = sorted(token for token, count in counts.items() if count > 1)
    assert not twice, f"Each token belongs to one row's covers, but these are in several: {twice}"


def test_each_row_is_complete():
    names = []
    for row in rows():
        assert set(row) <= KEYS, f"{row.get('name')}: unknown keys {sorted(set(row) - KEYS)}"
        for key in ("name", "license", "url"):
            assert isinstance(row.get(key), str) and row[key].strip(), f"{row.get('name')}: {key} is empty"
        assert row["url"].startswith("https://"), f"{row['name']}: url must start with https://"
        assert row.get("group") in GROUPS, f"{row['name']}: group {row.get('group')!r} is not one of {sorted(GROUPS)}"
        names.append(row["name"])
    assert len(names) == len(set(names)), "Row names must be unique"


def test_frigate_and_node_red_lead():
    data = rows()
    built_on = [row for row in data if row["group"] == "built-on"]
    assert [row["name"] for row in built_on] == BUILT_ON
    assert [row["name"] for row in data[: len(BUILT_ON)]] == BUILT_ON, "The built-on rows come first in the file"
    for row in built_on:
        assert isinstance(row.get("does"), str) and row["does"].strip(), f"{row['name']} needs a non-empty does"
    assert [row["name"] for row in data if "does" in row] == BUILT_ON, "Only the built-on rows have does"


def test_no_license_is_left_to_check():
    for row in rows():
        license_text = row["license"].strip()
        assert license_text and license_text.lower() != "check", f"{row['name']}: find the license"
