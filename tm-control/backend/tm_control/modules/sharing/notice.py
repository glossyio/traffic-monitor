"""The sharing notice in NOTICE.md, whose first line names its version: <!-- notice-version: 2026-11 -->.

A choice to share with the maintainer's server is recorded with the version of the notice it was made under.
"""

from pathlib import Path

from tm_control.modules.setup.eula import Eula, load_versioned

NOTICE_PATH = Path(__file__).with_name("NOTICE.md")


def load_notice(path: Path = NOTICE_PATH) -> Eula:
    return load_versioned(path, "notice")
