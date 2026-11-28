"""tm-control starts with only the files tmsetup writes: the secrets tasks/secrets.yml generates, and the install
manifest that tasks/tm-control_service.yml collects and templates/tm-control/manifest.json.j2 renders. Off-device.

The manifest is built by evaluating the role's own set_fact against the role's vars and defaults, so a field the role
stops collecting, or a name tm-control needs that the role doesn't generate, fails here rather than on a device.
"""

import json
import re
import sys
from pathlib import Path

import jinja2
import pytest
from tmsetup_render import REPO, evaluate, load_role_yaml, render

sys.path.insert(0, str(REPO / "tm-control" / "backend"))

# These need tm-control/backend on sys.path.
from fastapi.testclient import TestClient  # noqa: E402

import tm_control  # noqa: E402
from tm_control.app import create_app  # noqa: E402
from tm_control.core import secrets  # noqa: E402
from tm_control.core.manifest import Manifest  # noqa: E402
from tm_control.core.settings import Settings  # noqa: E402

FIXTURE_MANIFEST = REPO / "tm-control" / "backend" / "tests" / "fixtures" / "manifest.json"
GIT_OK = {
    "tmsetup_tm_control_git_commit_register": {"rc": 0, "stdout": "0123456789abcdef0123456789abcdef01234567"},
    "tmsetup_tm_control_git_branch_register": {"rc": 0, "stdout": "dev"},
    "tmsetup_tm_control_git_status_register": {"rc": 0, "stdout": ""},
}


def expanded_coral_model(variables):
    """The vars file's Coral model section with its path expanded, as Ansible's lazy templating gives it."""
    model = variables["tmsetup_frigate_coral_model"]
    return {**model, "path": jinja2.Environment().from_string(model["path"]).render(**variables)}


def collected_manifest(**registers):
    """tmsetup_tm_control_manifest as the role's set_fact builds it, for a device without Plate Recognizer."""
    task = next(task for task in load_role_yaml("tasks/tm-control_service.yml")
                if task["name"] == "TMSetup - tm-control Service - Collect the install manifest")
    variables = {**load_role_yaml("defaults/main.yml"), **load_role_yaml("vars/main.yml")}
    variables.update({
        "tmsetup_frigate_coral_model": expanded_coral_model(variables),
        "ansible_facts": {"user_id": "pi"},
        "tmsetup_tm_control_plate_recognizer_stat_register": {"stat": {"exists": False}},
        **GIT_OK, **registers,
    })
    return evaluate(task["ansible.builtin.set_fact"]["tmsetup_tm_control_manifest"], **variables)


def rendered_manifest(**registers):
    return render("script/ansible/roles/tmsetup/templates/tm-control/manifest.json.j2",
                  tmsetup_tm_control_manifest=collected_manifest(**registers))


def keys(value, prefix=""):
    """Every key path in a JSON document, as a.b.c."""
    if not isinstance(value, dict):
        return set()
    return {f"{prefix}{key}" for key in value} | {
        path for key, item in value.items() for path in keys(item, f"{prefix}{key}.")
    }


def test_manifest_renders_valid_json_with_the_fields_tm_control_reads():
    manifest = Manifest.model_validate(json.loads(rendered_manifest()))
    defaults, role_vars = load_role_yaml("defaults/main.yml"), load_role_yaml("vars/main.yml")
    assert manifest.manifest_version == 1
    assert manifest.tm_version == role_vars["tmsetup_tm_version"]
    assert (manifest.git.commit, manifest.git.branch) == ("0123456789abcdef0123456789abcdef01234567", "dev")
    assert manifest.git.modified is False
    assert (manifest.installing_user, manifest.codeowner, manifest.codedir) == ("pi", "tmadmin", "/opt/traffic-monitor")
    assert manifest.components == {
        "frigate": role_vars["tmsetup_frigate_version"], "node_red": role_vars["tmsetup_node_red_tm_version"],
        "go2rtc": role_vars["tmsetup_go2rtc_version"], "nginx": role_vars["tmsetup_nginx_version"],
        "hailo": role_vars["tmsetup_hailo_version"],
    }
    assert manifest.options == {"plate_recognizer": False}
    assert manifest.revproxy_locations == role_vars["tmsetup_revproxy_locations"]
    assert manifest.frigate.coral_model == {
        "model_type": "yolo-generic", "width": 512, "height": 512,
        "path": f"/config/model_cache/{role_vars['tmsetup_frigate_coral_model_file']}",
        "labelmap_path": "/config/labels-coco17.txt",
    }
    assert manifest.probes.radar_paths == defaults["tmsetup_radar_paths"]
    assert manifest.probes.hevc_device == role_vars["tmsetup_hevc_device"]
    assert manifest.homepage.colors == defaults["tmsetup_homepage_colors"]


def test_the_manifest_carries_the_coral_model_section():
    role_vars = load_role_yaml("vars/main.yml")
    model = collected_manifest()["frigate"]["coral_model"]
    assert isinstance(model, dict)
    assert model == expanded_coral_model(role_vars)
    assert json.loads(rendered_manifest())["frigate"]["coral_model"] == model


def test_manifest_records_only_the_static_detector_probes():
    """tmsetup_detectors also holds per-run results (exists, device_address, ...) that aren't install facts."""
    detectors = Manifest.model_validate(json.loads(rendered_manifest())).probes.detectors
    assert set(detectors) == set(load_role_yaml("defaults/main.yml")["tmsetup_detectors"])
    for name, probe in detectors.items():
        assert set(probe) == {"dev_path", "check_exists", "frigate_type", "frigate_device"}, name


def test_the_manifest_carries_the_hotspot_values():
    role_vars = load_role_yaml("vars/main.yml")
    network = collected_manifest()["network"]
    assert network == {
        "wifi_device": role_vars["tmsetup_wifi_device"],
        "hotspot_profile": role_vars["tmsetup_hotspot_profile"],
        "hotspot_address": role_vars["tmsetup_hotspot_address"],
    }
    assert json.loads(rendered_manifest())["network"] == network
    parsed = Manifest.model_validate(json.loads(rendered_manifest())).network
    assert (parsed.wifi_device, parsed.hotspot_profile, parsed.hotspot_address) == ("wlan0", "tm-hotspot", "10.42.0.1")


def test_the_manifest_carries_the_sharing_values():
    role_vars = load_role_yaml("vars/main.yml")
    sharing = collected_manifest()["sharing"]
    assert sharing == {
        "maintainer_host": role_vars["tmsetup_sharing_maintainer_host"],
        "public_map_live": role_vars["tmsetup_sharing_public_map_live"],
    }
    assert json.loads(rendered_manifest())["sharing"] == sharing
    parsed = Manifest.model_validate(json.loads(rendered_manifest())).sharing
    assert (parsed.maintainer_host, parsed.public_map_live) == ("tb.roadwaybiome.com", False)


def test_the_manifest_carries_the_map_values():
    role_vars = load_role_yaml("vars/main.yml")
    wanted = {"style_url": role_vars["tmsetup_map_style_url"]}
    assert all(value.startswith("https://") for value in wanted.values())
    assert collected_manifest()["map"] == wanted
    assert json.loads(rendered_manifest())["map"] == wanted
    parsed = Manifest.model_validate(json.loads(rendered_manifest())).map
    assert parsed.style_url == wanted["style_url"]


def test_manifest_has_the_same_fields_as_tm_controls_fixture():
    assert keys(json.loads(rendered_manifest())) == keys(json.loads(FIXTURE_MANIFEST.read_text()))


def test_the_manifest_carries_the_update_source():
    defaults = load_role_yaml("defaults/main.yml")
    assert re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", defaults["tmsetup_update_repo"])
    assert collected_manifest()["update"]["repo"] == defaults["tmsetup_update_repo"] == "glossyio/traffic-monitor"
    parsed = Manifest.model_validate(json.loads(rendered_manifest())).update
    assert parsed.repo == "glossyio/traffic-monitor"


@pytest.mark.parametrize(("version", "channel"), [
    ("0.8.0-dev", "development"), ("0.8.0", "stable"), ("1.12.3", "stable"), ("1.12.3-dev", "development"),
])
def test_the_manifest_channel_follows_the_version(version, channel):
    assert collected_manifest(tmsetup_tm_version=version)["update"]["channel"] == channel


@pytest.mark.parametrize(("enabled", "unit_exists", "expected"), [
    ("true", False, True),  # -C plate_recognizer on a first install: the stat runs before the add-on's setup
    (False, True, True),  # a later run without -C leaves the installed add-on in place
    (False, False, False),
])
def test_manifest_records_plate_recognizer_when_enabled_or_installed(enabled, unit_exists, expected):
    manifest = collected_manifest(tmsetup_bool_plate_recognizer=enabled,
                                  tmsetup_tm_control_plate_recognizer_stat_register={"stat": {"exists": unit_exists}})
    assert manifest["options"]["plate_recognizer"] is expected


@pytest.mark.parametrize("register", [
    {"rc": 128, "stdout": "", "stderr": "fatal: detected dubious ownership in repository"},
    {"rc": 2, "msg": "[Errno 2] No such file or directory: b'git'"},  # no git: the module fails without stdout
    {"skipped": True},
])
def test_manifest_says_unknown_when_git_fails(register):
    git = collected_manifest(tmsetup_tm_control_git_commit_register=register,
                             tmsetup_tm_control_git_branch_register=register)["git"]
    assert git == {"commit": "unknown", "branch": "unknown", "modified": False}


SHA = "0123456789abcdef0123456789abcdef01234567"
NO_GIT = {"skipped": True}


def passed_git(commit, branch=None):
    given = {"tmsetup_source_commit": commit} | ({} if branch is None else {"tmsetup_source_branch": branch})
    return collected_manifest(tmsetup_tm_control_git_commit_register=NO_GIT,
                              tmsetup_tm_control_git_branch_register=NO_GIT,
                              tmsetup_tm_control_git_status_register=NO_GIT, **given)["git"]


def test_a_passed_commit_is_recorded_without_git():
    assert passed_git(SHA, "feature/a-b_c/12") == {"commit": SHA, "branch": "feature/a-b_c/12", "modified": False}


def test_a_passed_commit_without_a_branch_says_the_branch_is_unknown():
    assert passed_git(SHA) == {"commit": SHA, "branch": "unknown", "modified": False}


@pytest.mark.parametrize("commit", ["", "0123456", "HEAD", SHA.upper(), SHA + "0", " " + SHA, SHA + "\n"])
def test_a_passed_value_that_is_not_a_commit_id_is_never_recorded(commit):
    assert passed_git(commit, "dev") == {"commit": "unknown", "branch": "unknown", "modified": False}


@pytest.mark.parametrize("branch", ["", "a b", "x;y", "$(id)", "x*", "b" * 201, "dev\n"])
def test_a_passed_branch_in_another_form_says_unknown(branch):
    assert passed_git(SHA, branch) == {"commit": SHA, "branch": "unknown", "modified": False}


DIGITS = int("1" * 40)  # a JSON or YAML -e passes a number, not text; as text it would fit the commit pattern


@pytest.mark.parametrize("branch", [123, 0.8, None, True])
def test_a_passed_branch_that_is_not_text_says_unknown(branch):
    git = collected_manifest(tmsetup_tm_control_git_commit_register=NO_GIT,
                             tmsetup_tm_control_git_branch_register=NO_GIT,
                             tmsetup_tm_control_git_status_register=NO_GIT,
                             tmsetup_source_commit=SHA, tmsetup_source_branch=branch)["git"]
    assert git == {"commit": SHA, "branch": "unknown", "modified": False}


def test_a_passed_commit_that_is_not_text_is_never_recorded():
    assert passed_git(DIGITS, "dev") == {"commit": "unknown", "branch": "unknown", "modified": False}
    git = collected_manifest(tmsetup_source_commit=DIGITS, tmsetup_source_branch="x")["git"]
    assert git == {"commit": SHA, "branch": "dev", "modified": False}  # git is asked: GIT_OK's answers


def test_git_is_asked_when_the_passed_commit_is_not_a_commit_id():
    git = collected_manifest(tmsetup_source_commit="HEAD", tmsetup_source_branch="x")["git"]
    assert git == {"commit": SHA, "branch": "dev", "modified": False}  # GIT_OK's answers


@pytest.mark.parametrize(("given", "runs"), [({}, True), ({"tmsetup_source_commit": "HEAD"}, True),
                                             ({"tmsetup_source_commit": SHA}, False),
                                             ({"tmsetup_source_commit": DIGITS}, True)])
def test_the_git_tasks_run_only_without_a_passed_commit(given, runs):
    tasks = [task for task in load_role_yaml("tasks/tm-control_service.yml")
             if task["name"].startswith("TMSetup - tm-control Service - Read the git ")]
    assert len(tasks) == 3
    for task in tasks:
        assert evaluate("{{ " + task["when"] + " }}", **given) is runs


def test_a_passed_installing_user_is_recorded():
    assert collected_manifest(tmsetup_installing_user="pi2")["installing_user"] == "pi2"


def test_the_installing_user_is_the_connecting_user_unless_passed():
    assert collected_manifest()["installing_user"] == "pi"


def check_passes(**variables):
    """Whether every condition of the role's check on passed values holds, as `assert` evaluates them."""
    task = next(task for task in load_role_yaml("tasks/tm-control_service.yml")
                if task["name"] == "TMSetup - tm-control Service - Check the values a caller passed")
    values = {**load_role_yaml("defaults/main.yml"), **variables}
    return all(evaluate("{{ " + condition + " }}", **values) is True for condition in task["ansible.builtin.assert"]["that"])


def test_the_check_passes_without_anything_passed():
    assert check_passes()


@pytest.mark.parametrize("value", ["pi", "tmadmin", "_svc-1", "a" * 32])
def test_an_installing_user_that_is_a_login_name_passes(value):
    assert check_passes(tmsetup_installing_user=value)


@pytest.mark.parametrize("value", ["root", "", "Bad Name", "a" * 33, "pi\n", 0, None, ["pi"]])
def test_an_installing_user_that_is_not_a_login_name_stops_the_install(value):
    assert not check_passes(tmsetup_installing_user=value)


@pytest.mark.parametrize("value", ["glossyio/traffic-monitor", "a-b/c.d_e", "a/" + "b" * 100])
def test_a_repository_in_owner_name_form_passes(value):
    assert check_passes(tmsetup_update_repo=value)


@pytest.mark.parametrize("value", ["glossyio", "a/b/c", "https://github.com/a/b", "a/b.git ", "a/b\n", "", 12, None,
                                   "a/..", "./b", "a/" + "b" * 101])
def test_a_repository_in_another_form_stops_the_install(value):
    assert not check_passes(tmsetup_update_repo=value)


def test_the_check_names_the_variable_and_never_the_value():
    task = next(task for task in load_role_yaml("tasks/tm-control_service.yml")
                if task["name"] == "TMSetup - tm-control Service - Check the values a caller passed")
    fail_msg = task["ansible.builtin.assert"]["fail_msg"]
    assert "tmsetup_installing_user" in fail_msg and "tmsetup_update_repo" in fail_msg
    assert "{{" not in fail_msg


def test_a_checkout_with_changes_is_recorded_as_modified():
    status = {"rc": 0, "stdout": " M CLAUDE.md"}
    assert collected_manifest(tmsetup_tm_control_git_status_register=status)["git"]["modified"] is True


def test_a_checkout_with_a_new_file_is_recorded_as_modified():
    status = {"rc": 0, "stdout": "?? script/new.py"}
    assert collected_manifest(tmsetup_tm_control_git_status_register=status)["git"]["modified"] is True


def test_a_clean_checkout_is_not_modified():
    assert collected_manifest(tmsetup_tm_control_git_status_register={"rc": 0, "stdout": ""})["git"]["modified"] is False


def test_git_failing_says_not_modified():
    failed = {"rc": 128, "stdout": "", "stderr": "fatal: not a git repository"}
    git = collected_manifest(tmsetup_tm_control_git_commit_register=failed,
                             tmsetup_tm_control_git_branch_register=failed,
                             tmsetup_tm_control_git_status_register=failed)["git"]
    assert git == {"commit": "unknown", "branch": "unknown", "modified": False}


@pytest.mark.parametrize(("passed", "expected"), [(True, True), ("true", True), (False, False), (None, False),
                                                  ("x", False)])
def test_a_passed_commit_takes_modified_from_its_caller(passed, expected):
    changed = {"rc": 0, "stdout": " M CLAUDE.md"}  # git isn't asked, so what it would say counts for nothing
    git = collected_manifest(tmsetup_source_commit=SHA, tmsetup_source_branch="dev",
                             tmsetup_tm_control_git_status_register=changed, tmsetup_source_modified=passed)["git"]
    assert git["modified"] is expected


def test_a_passed_commit_with_nothing_said_about_changes_is_not_modified():
    assert passed_git(SHA, "dev")["modified"] is False


def install(tmp_path, secret_names):
    """The files tmsetup writes, in a temp dir: one secret file per name, an empty one per entered secret, and the
    rendered manifest."""
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()
    for name in secret_names:
        (secrets_dir / name).write_text(f"placeholder-{name}-0123456789abcdef")  # as tmsetup: 32 random characters
    for name in load_role_yaml("vars/main.yml")["tmsetup_entered_secret_names"]:
        (secrets_dir / name).write_text("")  # as tmsetup: empty until a person enters one
    manifest = tmp_path / "manifest.json"
    manifest.write_text(rendered_manifest())
    return Settings(
        state_dir=tmp_path / "state",
        runtime_dir=tmp_path / "run",
        secrets_dir=secrets_dir,
        manifest_path=manifest,
        host="127.0.0.1",
        port=8090,
        fake=False,
        eula_path=Path(tm_control.__file__).parent / "modules" / "setup" / "EULA.md",
        setup_code_file=tmp_path / "setup-code",
    )


def test_tm_control_starts_with_only_the_files_tmsetup_writes(tmp_path):
    settings = install(tmp_path, load_role_yaml("vars/main.yml")["tmsetup_secret_names"])
    response = TestClient(create_app(settings)).get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": load_role_yaml("vars/main.yml")["tmsetup_tm_version"]}


@pytest.mark.parametrize("missing", secrets.NAMES)
def test_tm_control_refuses_to_start_without_each_secret_it_needs(tmp_path, missing):
    """The check above is only as good as this: each of tm-control's secrets is one it can't start without."""
    names = [name for name in load_role_yaml("vars/main.yml")["tmsetup_secret_names"] if name != missing]
    with pytest.raises(secrets.MissingSecret):
        create_app(install(tmp_path, names))
