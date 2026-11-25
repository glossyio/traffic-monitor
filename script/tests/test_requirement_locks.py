"""The Python locks: every package a device (and the installer's Ansible) gets is an exact version with hashes.

`script/requirements` and `tm-control/backend/requirements.txt` name the packages we choose; each has a lock beside it
that `uv pip compile` made for the device's Python, with the indirect packages and the hash of every file. The first
lines of a lock hold the command that made it.
"""

import re
from collections import namedtuple

import pytest
from tmsetup_render import REPO

PAIRS = [
    (REPO / "script/requirements", REPO / "script/requirements.lock"),
    (REPO / "tm-control/backend/requirements.txt", REPO / "tm-control/backend/requirements.lock"),
]
IDS = ["ansible", "tm-control"]

Locked = namedtuple("Locked", "version hashes")


def normalize(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def pinned(path):
    """Every requirement of a direct list, as {normalized name: version}; each must be name==version."""
    found = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.fullmatch(r"([A-Za-z0-9._-]+)==([^\s;]+)", line)
        assert match, f"{path.name}: {line!r} is not name==version"
        found[normalize(match.group(1))] = match.group(2)
    return found


def locked(path):
    """A lock's packages as {normalized name: Locked(version, [hashes])}."""
    text = path.read_text().replace("\\\n", " ")  # a package's hashes continue on following lines
    found = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(("#", "--")):
            continue
        match = re.match(r"([A-Za-z0-9._-]+)==([^\s;]+)(.*)", line)
        assert match, f"{path.name}: can't read {line!r}"
        found[normalize(match.group(1))] = Locked(match.group(2), re.findall(r"--hash=(\S+)", match.group(3)))
    return found


@pytest.mark.parametrize(("direct", "lock"), PAIRS, ids=IDS)
def test_every_locked_package_is_exact_and_hashed(direct, lock):
    packages = locked(lock)
    assert packages, f"{lock.name} holds no packages"
    for name, entry in packages.items():
        assert entry.version and entry.hashes, name
        assert all(h.startswith("sha256:") for h in entry.hashes), name


@pytest.mark.parametrize(("direct", "lock"), PAIRS, ids=IDS)
def test_the_lock_holds_every_direct_dependency_at_its_version(direct, lock):
    packages = locked(lock)
    for name, version in pinned(direct).items():
        assert name in packages, f"{name}: remake {lock.name} (see its first lines)"
        assert packages[name].version == version, f"{name}: remake {lock.name} (see its first lines)"


@pytest.mark.parametrize(("direct", "lock"), PAIRS, ids=IDS)
def test_the_lock_was_made_for_the_devices_python(direct, lock):
    header = "\n".join(lock.read_text().splitlines()[:3])
    assert "--python-version 3.13" in header and "--python-platform aarch64-unknown-linux-gnu" in header
    assert "--generate-hashes" in header


def test_the_installer_asks_for_one_ansible_version():
    assert re.fullmatch(r"ansible==\d+\.\d+\.\d+\n?", (REPO / "script/requirements").read_text())
