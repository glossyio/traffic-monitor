"""Keep config.yml's sharing: block equal to the consents recorded in state.sqlite.

Node-RED reads the block, never state.sqlite, so the block is how a recorded choice reaches the upload; a hand edit of
it never grants anything. Each run, for the target the upload goes to (the thingsboard: block's host):

1. The upload is off: every choice granted for the target is withdrawn.
2. The upload is on and sharing data isn't granted for the target (a unit upgraded with the upload on, or one turned
   on by hand): it is recorded as granted before consent was recorded (pre-consent, no user), and an admin is asked to
   review it. Nothing else is granted.
3. The block names another server than the upload's (the host was changed in the file): every choice granted for the
   server it names is withdrawn.
4. The block is rewritten to what the store asks for (wanted_block) when it means something else, or when the file has
   none and the store grants the exact location or the public map; then Node-RED is told.

Runs from reconcile.ensure and reconcile.for_status_report, under app_state.reconcile_lock. Nothing here logs a host,
a notice version, or a note: only counts and exception class names.
"""

import logging

from tm_control.modules.location.config import ConfigError, NodeRedConfig, SharingBlock
from tm_control.modules.sharing.consents import MAINTAINER, PRE_CONSENT, Consent, Consents, normalize_host, target_key

log = logging.getLogger(__name__)

OFF_NOTE = "the upload was off in config.yml"
FOUND_NOTE = "the upload was on in config.yml with no choice recorded on the Sharing page"
CHANGED_NOTE = "the server changed in config.yml"


def wanted_block(
    target: str | None, host: str | None, share_data: Consent | None, exact_location: bool, public_map: bool
) -> SharingBlock:
    """The sharing: block for these choices. target is the target key ('maintainer', 'own:<host>', or None), host the
    upload's; share_data the latest share_data row for the target (None when there is none), whose notice version the
    block carries while it is granted."""
    kind = None if target is None else ("maintainer" if target == MAINTAINER else "own")
    return SharingBlock(
        target=kind,
        host=normalize_host(host),
        exact_location=exact_location,
        public_map="rounded_point" if public_map else "none",
        notice_version=share_data.notice_version if share_data is not None and share_data.granted else None,
    )


def run(app_state) -> bool:
    """Follow config.yml (see the module's docstring); True when it wrote the file. The caller holds
    app_state.reconcile_lock. A file that can't be read is left alone (False); a ConfigError from saving it (changed
    since it was read, or not writable) is raised."""
    try:
        config = NodeRedConfig(app_state.config_path)
    except ConfigError:
        return False
    consents = Consents(app_state.state)
    maintainer_host = app_state.manifest.sharing.maintainer_host
    upload = config.upload()
    host = normalize_host(upload.host)
    target = target_key(host, maintainer_host)
    current = config.sharing_block()

    if target is not None:
        if not upload.enabled:
            withdrawn = consents.withdraw_all(target, None, OFF_NOTE)
            if withdrawn:
                log.info("sharing: %d choices withdrawn, as the upload is off", len(withdrawn))
        elif not consents.granted(target, "share_data"):
            consents.record(target, "share_data", True, PRE_CONSENT, None, note=FOUND_NOTE)
            consents.set_review_needed(True)
            log.info("sharing: an upload found on was recorded for review")
    if current is not None and current.host is not None and current.host != host:
        withdrawn = consents.withdraw_all(target_key(current.host, maintainer_host), None, CHANGED_NOTE)
        if withdrawn:
            log.info("sharing: %d choices withdrawn, as the server changed", len(withdrawn))

    latest = consents.latest(target) if target is not None else {}
    share_data = latest.get("share_data")
    wanted = wanted_block(
        target, host, share_data, _granted(latest.get("exact_location")), _granted(latest.get("public_map"))
    )
    if current is not None:
        if current == wanted:
            return False
    elif not wanted.exact_location and wanted.public_map == "none":
        return False
    config.set_sharing(wanted)
    if not config.save():
        return False
    app_state.nodered.after_config_write()
    log.info("sharing: the sharing block was written")
    return True


def _granted(consent: Consent | None) -> bool:
    return consent is not None and consent.granted
