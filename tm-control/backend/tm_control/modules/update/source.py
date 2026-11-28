"""Where updates come from: the GitHub repository the install recorded, if it passes the one rule the installer,
tm-update, and the update job apply to it (core/repository.py)."""

from ...core.manifest import Manifest
from ...core.repository import is_repo

__all__ = ["is_repo", "repo_of"]


def repo_of(manifest: Manifest) -> str | None:
    """The recorded repository, or None when it is empty or not owner/name."""
    repo = manifest.update.repo
    return repo if is_repo(repo) else None
