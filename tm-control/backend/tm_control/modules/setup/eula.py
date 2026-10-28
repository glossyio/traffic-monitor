"""The end-user license agreement in EULA.md, whose first line names its version: <!-- eula-version: 1 -->.

Acceptance is per device. A new version keeps everyone out of the apps until an admin accepts it.
"""

import re
from dataclasses import dataclass
from pathlib import Path

VERSION_LINE = re.compile(r"<!--\s*eula-version:\s*(\S+)\s*-->")


@dataclass(frozen=True)
class Eula:
    version: str
    markdown: str


def load_eula(path: Path) -> Eula:
    first, _, rest = Path(path).read_text(encoding="utf-8").partition("\n")
    match = VERSION_LINE.fullmatch(first.strip())
    if not match:
        raise ValueError(f"{path} must start with a line like <!-- eula-version: 1 -->")
    return Eula(version=match.group(1), markdown=rest.lstrip("\n"))
