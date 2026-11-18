"""The end-user license agreement in EULA.md, whose first line names its version: <!-- eula-version: 1 -->.

Acceptance is per device. A new version keeps everyone out of the apps until an admin accepts it.

load_versioned reads any markdown file versioned the same way under another marker's name (the sharing notice's is
<!-- notice-version: … -->).
"""

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Eula:
    version: str
    markdown: str


def load_versioned(path: Path, name: str) -> Eula:
    """The file's version, from a first line <!-- <name>-version: … -->, and the markdown after that line."""
    first, _, rest = Path(path).read_text(encoding="utf-8").partition("\n")
    match = re.fullmatch(rf"<!--\s*{re.escape(name)}-version:\s*(\S+)\s*-->", first.strip())
    if not match:
        raise ValueError(f"{path} must start with a line like <!-- {name}-version: 1 -->")
    return Eula(version=match.group(1), markdown=rest.lstrip("\n"))


def load_eula(path: Path) -> Eula:
    return load_versioned(path, "eula")
