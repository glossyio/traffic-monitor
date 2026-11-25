"""Every pinned source of an install still resolves: the base images' digests, the ffmpeg commit, the Coral files.

A registry can drop a digest when a tag is pushed again, and a repository can lose a commit. Nothing on a Pi's install
would show it until a build failed on a device, so this asks the sources. The tests that reach the network run only
with TM_TESTS_ONLINE=1 (`.github/workflows/pins.yml` sets it); everywhere else they skip, so a laptop or a run
without a connection isn't failed by a registry that is down. The two tests at the top read recorded answers
(fixtures/) and always run.
"""

import hashlib
import json
import os
import re
import subprocess
import urllib.request
from pathlib import Path

import jinja2
import pins
import pytest
from required_tools import needs
from tmsetup_render import load_role_yaml

FIXTURES = Path(__file__).parent / "fixtures"

online = pytest.mark.skipif(os.environ.get("TM_TESTS_ONLINE") != "1", reason="reaches the network: set TM_TESTS_ONLINE=1")


def test_the_token_request_is_built_from_the_challenge():
    """The registry says where its tokens come from; no registry's address is written in the code."""
    challenge = (FIXTURES / "www-authenticate-ghcr.txt").read_text().strip()
    assert pins.token_url(challenge) == (
        "https://ghcr.io/token?service=ghcr.io&scope=repository%3Ablakeblackshear%2Ffrigate%3Apull")


def test_a_challenge_for_another_scheme_or_a_plain_address_is_refused():
    with pytest.raises(ValueError):
        pins.token_url('Basic realm="registry"')
    with pytest.raises(ValueError):
        pins.token_url('Bearer realm="http://registry.example/token",service="registry.example"')


def test_an_index_is_read_for_its_arm64_image():
    body = (FIXTURES / "frigate-0.18.2-index.json").read_bytes()
    assert pins.has_linux_arm64(body)
    index = json.loads(body)
    index["manifests"] = [m for m in index["manifests"] if m["platform"]["architecture"] != "arm64"]
    assert not pins.has_linux_arm64(json.dumps(index))


def test_a_token_answer_without_a_token_is_an_error_that_does_not_quote_it(monkeypatch):
    challenge = (FIXTURES / "www-authenticate-ghcr.txt").read_text().strip()
    answers = iter([(401, {"WWW-Authenticate": challenge}, b""), (200, {}, b'{"secret": "do-not-print"}')])
    monkeypatch.setattr(pins, "_get", lambda url, headers: next(answers))
    with pytest.raises(RuntimeError, match="had no token") as error:
        pins.manifest(pins.BaseImage("t", "ghcr.io", "o/i", "1", "sha256:" + "0" * 64))
    assert "do-not-print" not in str(error.value)


@online
@pytest.mark.parametrize("image", pins.base_images(), ids=lambda image: f"{image.name}:{image.tag}")
def test_the_registry_still_serves_the_pinned_digest(image):
    status, media_type, body = pins.manifest(image)
    if status == 429:
        pytest.fail(f"{image.name}@{image.digest}: the registry limited the requests (registry answered 429): "
                    "re-run later; the digest is not known to be gone")
    assert status == 200, (f"{image.name}@{image.digest} no longer resolves (registry answered {status}): "
                           "take the tag's digest again if it is 404; a 401 or 403 is the registry's login, not the digest")
    assert "index" in media_type or "list" in media_type, (
        f"{image.name}@{image.digest} is a single image ({media_type}), not the multi-arch list: "
        "take the tag's list digest, so the device gets its own architecture")
    assert pins.has_linux_arm64(body), f"{image.name}@{image.digest} has no linux/arm64 image"


@online
@needs("git")
def test_the_ffmpeg_commit_can_still_be_fetched(tmp_path):
    """The Containerfile fetches this one commit by its hash, as the build on a device does."""
    commit = load_role_yaml("vars/main.yml")["tmsetup_frigate_ffmpeg_commit"]
    fetch = re.search(r"fetch --depth 1 (\S+) \{\{ tmsetup_frigate_ffmpeg_commit \}\}",
                      (pins.REPO / "container/frigate/Containerfile.j2").read_text())
    assert fetch, "the Containerfile's fetch line changed: update this test with it"
    git = ["git", "-C", str(tmp_path)]
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True, capture_output=True)
    fetched = subprocess.run([*git, "fetch", "--quiet", "--depth", "1", fetch.group(1), commit],
                             capture_output=True, text=True, timeout=300)
    assert fetched.returncode == 0, f"{commit} can't be fetched from {fetch.group(1)}: {fetched.stderr.strip()}"
    head = subprocess.run([*git, "rev-parse", "FETCH_HEAD"], check=True, capture_output=True, text=True)
    assert head.stdout.strip() == commit


@online
@pytest.mark.parametrize("which", ["model", "labels"])
def test_a_coral_download_still_has_its_checksum(which):
    names = {"model": "TMSetup - Frigate Setup - Coral TPU model - Download the open source yolov9 model",
             "labels": "TMSetup - Frigate Setup - Coral TPU model - Download the labels for the open source yolov9 model"}
    variables = load_role_yaml("vars/main.yml")
    task = {task["name"]: task for task in load_role_yaml("tasks/frigate_setup.yml")}[names[which]]
    get_url = task["ansible.builtin.get_url"]
    url = jinja2.Environment().from_string(get_url["url"]).render(**variables)
    expected = jinja2.Environment().from_string(get_url["checksum"]).render(**variables).removeprefix("sha256:")
    with urllib.request.urlopen(urllib.request.Request(url), timeout=30) as response:
        actual = hashlib.sha256(response.read()).hexdigest()
    assert actual == expected, f"{url} no longer has the pinned checksum: it is {actual}; stop and find out why"
