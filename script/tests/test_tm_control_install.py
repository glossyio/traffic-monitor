"""tm-control starts with only the files tmsetup writes: the secrets tasks/secrets.yml generates, and the install
manifest that tasks/tm-control_service.yml collects and templates/tm-control/manifest.json.j2 renders. Off-device.

The manifest is built by evaluating the role's own set_fact against the role's vars and defaults, so a field the role
stops collecting, or a name tm-control needs that the role doesn't generate, fails here rather than on a device.
"""

import json
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


def test_manifest_has_the_same_fields_as_tm_controls_fixture():
    assert keys(json.loads(rendered_manifest())) == keys(json.loads(FIXTURE_MANIFEST.read_text()))


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
    assert git == {"commit": "unknown", "branch": "unknown"}


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
