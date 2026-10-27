import shutil
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture(params=["frigate_config_v0.17.yml", "frigate_config_v0.18.yml"])
def frigate_config(request, tmp_path):
    """A copy of Frigate's config.yml as tmsetup rendered it before go2rtc RTSP credentials (synthetic).

    v0.17 is from before Frigate 0.18 (#220), with a Coral USB; v0.18 is from after, with the CPU detector (#222).
    """
    (tmp_path / "config").mkdir()
    path = tmp_path / "config" / "config.yml"
    shutil.copy(FIXTURES / request.param, path)
    path.chmod(0o640)
    return path
