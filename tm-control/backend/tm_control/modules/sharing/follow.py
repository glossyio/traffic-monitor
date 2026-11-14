"""Keep config.yml's sharing: block equal to the consents recorded in state.sqlite.

Node-RED reads the block, never state.sqlite, so the block is how a recorded choice reaches the upload; a hand edit of
it never grants anything. Each run, for the target the upload goes to (the thingsboard: block's host):

1. The upload is off: every choice granted for the target is withdrawn, and a review the Status page asks for is
   cleared, since nothing is shared.
2. The upload is on and sharing data isn't granted for the target (a unit upgraded with the upload on, or one turned
   on by hand): it is recorded as granted before consent was recorded (pre-consent, no user), and an admin is asked to
   review it. Nothing else is granted.
3. Every choice granted for any other target is withdrawn: the server changed in the file (whether or not the block
   changed with it), and choices are kept for one target at a time, so switching back never revives old ones. With no
   host in the upload, that is every target.
4. A file with no block (one replaced by tmsetup.sh -f, or a block deleted by hand) means the rounded location only:
   a save writes the block before its rows, so a grant of the exact location or the public map next to no block is
   withdrawn, never restored. Then the block is written to what the store asks for (wanted_block) when the file has
   one that means something else, or has none while the upload is on (an upgraded unit gets one at its first run);
   then Node-RED is told. With the upload off, or no host in it, a missing block stays missing.

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
NO_BLOCK_NOTE = "config.yml had no sharing block"


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

    if not upload.enabled:
        if target is not None:
            withdrawn = consents.withdraw_all(target, None, OFF_NOTE)
            if withdrawn:
                log.info("sharing: %d choices withdrawn, as the upload is off", len(withdrawn))
        if consents.review_needed():
            consents.set_review_needed(False)
            log.info("sharing: the review was cleared, as the upload is off")
    elif target is not None and not consents.granted(target, "share_data"):
        consents.record(target, "share_data", True, PRE_CONSENT, None, note=FOUND_NOTE)
        consents.set_review_needed(True)
        log.info("sharing: an upload found on was recorded for review")
    changed = 0
    for other in consents.targets():
        if other != target:  # the current target's rows were handled above, so no row is withdrawn twice
            changed += len(consents.withdraw_all(other, None, CHANGED_NOTE))
    if changed:
        log.info("sharing: %d choices withdrawn, as the server changed", changed)

    latest = consents.latest(target) if target is not None else {}
    if current is None:
        if target is None:
            return False
        # Rule 4: nothing is restored into a missing block
        withdrawn = 0
        for name in ("exact_location", "public_map"):
            found = latest.get(name)
            if _granted(found):
                consents.record(target, name, False, found.notice_version, None, note=NO_BLOCK_NOTE)
                withdrawn += 1
        if withdrawn:
            log.info("sharing: %d choices withdrawn, as the block was missing", withdrawn)
            latest = consents.latest(target)
        if not upload.enabled:
            return False
    share_data = latest.get("share_data")
    wanted = wanted_block(
        target, host, share_data, _granted(latest.get("exact_location")), _granted(latest.get("public_map"))
    )
    if current == wanted:
        return False
    config.set_sharing(wanted)
    if not config.save():
        return False
    app_state.nodered.after_config_write()
    log.info("sharing: the sharing block was written")
    return True


def _granted(consent: Consent | None) -> bool:
    return consent is not None and consent.granted
