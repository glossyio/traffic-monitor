"""Where updates come from: the GitHub repository the install recorded, if it passes the one rule the installer,
tm-update, and the update job apply to it."""

import re

from ...core.manifest import Manifest

# owner/name, each part 1 to 100 characters, and neither part made only of dots (. and .. are not names)
_REPO = re.compile(r"[A-Za-z0-9._-]{1,100}/[A-Za-z0-9._-]{1,100}")


def is_repo(value: object) -> bool:
    """Whether value is owner/name under the rule above."""
    if not isinstance(value, str) or not _REPO.fullmatch(value):
        return False
    return not any(set(part) == {"."} for part in value.split("/"))


def repo_of(manifest: Manifest) -> str | None:
    """The recorded repository, or None when it is empty or not owner/name."""
    repo = manifest.update.repo
    return repo if is_repo(repo) else None
