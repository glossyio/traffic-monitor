"""What stands in the way of starting an update, and what is only worth a warning. Only the checks that apply are
listed, in this order."""

from ...core.checks import Check, Fix
from ...core.manifest import Manifest
from .run import Run
from .source import repo_of

RUN_THE_INSTALLER = Fix(kind="hint", text="Run the full installer by hand (bash script/tmsetup.sh).")


def before_start(manifest: Manifest, run: Run | None) -> list[Check]:
    found = []
    if repo_of(manifest) is None:
        found.append(
            Check(
                id="update.source", title="Update source", status="error",
                detail="This unit doesn't record where its updates come from, so it can't look for one.",
                fix=RUN_THE_INSTALLER,
            )
        )
    if manifest.options.get("plate_recognizer"):
        found.append(
            Check(
                id="update.addon", title="Plate Recognizer add-on", status="error",
                detail="The Plate Recognizer add-on is installed, and an update doesn't rebuild it.",
                fix=RUN_THE_INSTALLER,
            )
        )
    if run is not None and run.status == "running":
        found.append(
            Check(id="update.running", title="Update running", status="error", detail="An update is already running.")
        )
    if manifest.git.modified:
        found.append(
            Check(
                id="update.modified", title="Installed files changed", status="warn",
                detail="Files in the installed version were changed by hand. An update replaces them.",
            )
        )
    return found
