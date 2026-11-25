"""What an install's image builds start from, read from the rendered Containerfiles, for the tests that pin it.

Not a test file. The tests of the base images, the ffmpeg commit, and the Node-RED lock use it, as does the online
check that every pin still resolves.
"""

import re
from typing import NamedTuple

from tmsetup_render import REPO, load_role_yaml, render

# The service folders under container/ whose build is left as it is. A new service is pinned like the rest unless
# its folder is added here on purpose.
UNPINNED = {"plate-recognizer"}


def _templates(pattern):
    paths = sorted(path.relative_to(REPO).as_posix() for path in (REPO / "container").glob(pattern))
    return [path for path in paths if path.split("/")[1] not in UNPINNED]


CONTAINERFILES = _templates("*/Containerfile.j2")
PINNED_BUILD_UNITS = _templates("*/*.build.j2")


class BaseImage(NamedTuple):
    template: str
    registry: str
    name: str
    tag: str
    digest: str


FROM_LINE = re.compile(
    r"FROM (?P<registry>[a-z0-9.]+\.[a-z]+)/(?P<name>[a-z0-9._/-]+):(?P<tag>[A-Za-z0-9._-]+)"
    r"@(?P<digest>sha256:[0-9a-f]{64})( AS [a-z][a-z0-9-]*)?")


def rendered_containerfile(template):
    """A Containerfile template rendered with the role's vars/main.yml."""
    return render(template, **load_role_yaml("vars/main.yml"))


def base_images():
    """Every base image of the pinned Containerfiles, one per FROM line. A line that isn't named in full and pinned
    by digest isn't listed: the test of the lines' form fails on it."""
    images = []
    for template in CONTAINERFILES:
        for line in rendered_containerfile(template).splitlines():
            match = FROM_LINE.fullmatch(line) if line.startswith("FROM ") else None
            if match:
                images.append(BaseImage(template, *match.group("registry", "name", "tag", "digest")))
    return images
