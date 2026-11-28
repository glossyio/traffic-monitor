"""The rule for the update repository's name, which the installer, tm-update, the update job, and the control app each
apply: owner/name, each part 1 to 100 characters, and neither part made only of dots (. and .. are not names).

It imports nothing from the app, so the GitHub adapter and the update module can both use it."""

import re

_REPO = re.compile(r"[A-Za-z0-9._-]{1,100}/[A-Za-z0-9._-]{1,100}")


def is_repo(value: object) -> bool:
    """Whether value is owner/name under the rule above."""
    if not isinstance(value, str) or not _REPO.fullmatch(value):
        return False
    return not any(set(part) == {"."} for part in value.split("/"))
