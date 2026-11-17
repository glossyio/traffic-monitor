"""What the Node-RED editor needs from the repo's files: a developer's project is a clone of this repository (#276)."""

import json
import subprocess

from required_tools import needs
from tmsetup_render import REPO

DATA = REPO / "container/node-red-tm/data"


def test_the_project_files_are_named_from_the_package_file_folder():
    """Node-RED Projects joins these names to the folder that holds package.json. A path such as /data/flows.json
    names a file in data/data/, which doesn't exist, and the project then starts with no flows."""
    settings = json.loads((DATA / "package.json").read_text())["node-red"]["settings"]
    assert settings == {"flowFile": "flows.json", "credentialsFile": "flows_cred.json"}
    for name in settings.values():
        assert (DATA / name).is_file()


@needs("node")
def test_the_editor_does_not_ask_about_update_notifications():
    """Without a telemetry setting, the editor opens with a question about sending usage data to get update
    notices. The installer pins Node-RED's version, so the answer is no."""
    script = f"console.log(JSON.stringify(require({json.dumps(str(DATA / 'settings.js'))}).telemetry ?? null))"
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"enabled": False, "updateNotification": False}
