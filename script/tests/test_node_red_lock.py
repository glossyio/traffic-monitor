"""Node-RED's modules install with npm ci from package-lock.json, which is made inside the pinned Node-RED image
(container/node-red-tm/data/README.md). These tests hold the lock to package.json and to the image's Node-RED."""

import json
import re

from tmsetup_render import REPO, load_role_yaml

DATA = REPO / "container/node-red-tm/data"
README = DATA / "README.md"


def lock():
    return json.loads((DATA / "package-lock.json").read_text())


def package():
    return json.loads((DATA / "package.json").read_text())


def remake():
    """How to remake the lock: the commands in the README's package-lock.json section, quoted from it."""
    section = README.read_text().partition("### package-lock.json")[2]
    commands = re.search(r"```sh\n(.*?)```", section, re.DOTALL)
    return (f"remake the lock from the repo root with the commands in {README.relative_to(REPO)}, "
            f"section package-lock.json:\n{commands.group(1) if commands else ''}")


def test_the_lock_has_the_same_direct_dependencies_as_package_json():
    assert lock()["packages"][""]["dependencies"] == package()["dependencies"], remake()


def test_the_locked_node_red_is_the_installed_version():
    version = load_role_yaml("vars/main.yml")["tmsetup_node_red_tm_version"]
    assert lock()["packages"]["node_modules/node-red"]["version"] == version, remake()


def test_every_locked_package_comes_from_the_npm_registry_with_a_hash():
    """npm, a dependency of Node-RED, bundles its own dependencies: they come inside npm's archive, so the lock has no
    address or hash of their own, as for a link. No other package's entries are skipped."""
    assert lock()["lockfileVersion"] == 3, remake()
    for path, entry in lock()["packages"].items():
        bundled_in_npm = entry.get("inBundle") and path.startswith("node_modules/npm/node_modules/")
        if path and not entry.get("link") and not bundled_in_npm:
            assert entry.get("resolved", "").startswith("https://registry.npmjs.org/"), f"{path}: {remake()}"
            assert entry.get("integrity", "").startswith("sha512-"), f"{path}: {remake()}"
