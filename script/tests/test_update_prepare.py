"""What an update builds and installs: the image list in vars/main.yml, and the tasks and units that list must match."""

import re

from tmsetup_render import REPO, ROLE, evaluate, load_role_yaml, render

CODEDIR = "/opt/traffic-monitor"


def role_vars():
    return dict(load_role_yaml("vars/main.yml"), tmsetup_codedir=CODEDIR)


def images():
    variables = role_vars()
    return evaluate(variables["tmsetup_update_images"], **variables)


def test_every_build_unit_but_the_addons_is_in_the_image_list():
    units = {path.parent.name for path in (REPO / "container").glob("*/*.build.j2")} - {"plate-recognizer"}
    assert units == {image["dir"] for image in images()}


def test_each_listed_tag_is_the_one_its_build_unit_gives():
    for image in images():
        unit = render(f"container/{image['dir']}/{image['name']}.build.j2", **role_vars())
        assert f"ImageTag=localhost/{image['name']}:{image['tag']}\n" in unit, image["name"]
        assert f"SetWorkingDirectory={CODEDIR}/{image['dir']}\n" in unit, image["name"]


def test_every_named_stage_of_a_containerfile_is_listed_and_no_other():
    for image in images():
        text = (REPO / "container" / image["dir"] / "Containerfile.j2").read_text()
        # The image is not \S+: a template's FROM names its digest as {{ variable }}, with spaces inside the braces.
        assert re.findall(r"(?mi)^FROM\s+.+?\s+AS\s+(\S+)\s*$", text) == image["stages"], image["name"]


def test_podman_setup_installs_the_listed_packages():
    variables = role_vars()
    install = next(
        task for task in load_role_yaml("tasks/podman_setup.yml")
        if task["name"] == "TMSetup - Podman Setup - Install Podman packages"
    )
    assert install["ansible.builtin.apt"]["name"] == "{{ tmsetup_podman_packages }}"
    assert variables["tmsetup_podman_packages"] == ["podman-docker", "podman-compose"]
