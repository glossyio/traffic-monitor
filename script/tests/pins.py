"""What an install's image builds start from, read from the rendered Containerfiles, for the tests that pin it.

Not a test file. The tests of the base images, the ffmpeg commit, and the Node-RED lock use it, as does the online
check that every pin still resolves.
"""

import json
import re
import urllib.error
import urllib.parse
import urllib.request
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


# Docker Hub's registry API is not on the host its images are named for.
REGISTRY_HOSTS = {"docker.io": "registry-1.docker.io"}

MANIFEST_TYPES = ", ".join([
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.v2+json",
])

TIMEOUT = 30  # seconds, for each request


def token_url(challenge):
    """Where a registry's `WWW-Authenticate: Bearer ...` challenge says to ask for a pull token: its realm, with the
    service and scope it names. Raises ValueError for any other challenge, or a realm that isn't https."""
    scheme, _, rest = challenge.partition(" ")
    fields = dict(re.findall(r'([a-z]+)="([^"]*)"', rest))
    realm = fields.get("realm", "")
    if scheme.lower() != "bearer" or not realm.startswith("https://"):
        raise ValueError(f"not a bearer challenge with an https realm: {challenge!r}")
    query = {key: fields[key] for key in ("service", "scope") if key in fields}
    return f"{realm}?{urllib.parse.urlencode(query)}" if query else realm


def has_linux_arm64(index_body):
    """True when an image index (or Docker manifest list) lists a linux/arm64 image."""
    return any(m.get("platform", {}).get("os") == "linux" and m.get("platform", {}).get("architecture") == "arm64"
               for m in json.loads(index_body).get("manifests", []))


def _get(url, headers):
    """(status, headers, body) of a GET; an HTTP error status is an answer, not an exception."""
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=TIMEOUT) as response:
            return response.status, response.headers, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.headers, error.read()


def manifest(image):
    """Ask the image's registry for the manifest at its pinned digest: (status, Content-Type, body). A registry that
    wants a token says where to get one in its 401's challenge, and that is the only place the address comes from."""
    host = REGISTRY_HOSTS.get(image.registry, image.registry)
    url = f"https://{host}/v2/{image.name}/manifests/{image.digest}"
    headers = {"Accept": MANIFEST_TYPES}
    status, answer, body = _get(url, headers)
    if status == 401 and answer.get("WWW-Authenticate"):
        token_status, _, token_body = _get(token_url(answer["WWW-Authenticate"]), {})
        if token_status == 200:
            granted = json.loads(token_body)
            token = granted.get("token") or granted.get("access_token")
            if not token:
                # Say nothing of the answer itself: it may hold a credential.
                raise RuntimeError("the registry's token answer had no token")
            status, answer, body = _get(url, {**headers, "Authorization": f"Bearer {token}"})
    return status, answer.get("Content-Type", ""), body
