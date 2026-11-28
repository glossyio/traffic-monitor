// The Software update page's words for what the device reports as codes: the run's stages and the reasons a run or a
// start failed. The device never sends a sentence for these (docs/development/software-update.md), so the words live
// here. A later version may write a stage or a reason this one doesn't know: a stage then shows by its id, and a reason
// as the generic failure, so the page never breaks on one.

const STAGE_TITLES: Record<string, string> = {
  fetch: 'Download',
  verify: 'Check',
  prepare: 'Prepare',
  images: 'Build',
  restore_point: 'Restore point',
  switch: 'Switch',
  reboot: 'Restart',
  health: 'Verify',
  cleanup: 'Clean up',
}

// The stages in the order a run goes through them. The page lists the ones after the current stage as not started yet.
// `reboot` is left out of that list: a run restarts the device only when the installer asks for it.
export const STAGE_ORDER = ['fetch', 'verify', 'prepare', 'images', 'restore_point', 'switch', 'health', 'cleanup']

// Stages before the switch, when nothing in use has changed yet
export const BEFORE_SWITCH = new Set(['fetch', 'verify', 'prepare', 'images', 'restore_point'])

export function stageTitle(id: string): string {
  return STAGE_TITLES[id] ?? id
}

// The two stages in which this page stops answering, with a note beside the row so the silence isn't a surprise
const STAGE_NOTES: Record<string, string> = {
  switch: '(the device stops answering for about 3 minutes)',
  reboot: '(a few more minutes while it restarts)',
}

export function stageNote(id: string): string | null {
  return STAGE_NOTES[id] ?? null
}

export const GENERIC_FAILURE = 'The update failed. The log below has the details.'

const INSTALLER = 'Update it with the installer.'
const STATUS_PAGE = 'The device may be on the new version, so look at the Status page.'

const REASONS: Record<string, string> = {
  busy: 'Another install or update is running on this device. Wait for it to end.',
  needs_manual_update: `This device can't be updated from here. ${INSTALLER}`,
  addon_needs_installer: `The Plate Recognizer add-on is installed, and an update from here doesn't rebuild it. ${INSTALLER}`,
  reboot_pending: 'The device has a restart waiting from an earlier change. Restart it on the Device page, then try again.',
  low_space: "There isn't enough free storage for the update. Free some space, then try again.",
  hardware_needs_installer: `A detector on this device needs a driver that only the installer adds. ${INSTALLER}`,
  no_internet: "The device couldn't reach the internet. Connect it, then try again.",
  settings_need_attention:
    "The update couldn't carry this device's settings over to the new version, so nothing was changed. The log below has the details.",
  prepare_failed: 'The update failed while it prepared the new version, so nothing was changed. The log below has the details.',
  build_failed: "The new version's images didn't build, so nothing was changed. The log below has the details.",
  switch_failed: `The update failed while it switched to the new version, and the apps were started again. ${STATUS_PAGE}`,
  health_failed: `The new version didn't answer in time after the switch. ${STATUS_PAGE}`,
  fetch_failed: "The device couldn't download the new version from GitHub. Check its internet connection, then try again.",
  stale_check: "The version the last check found isn't offered any more. Check again.",
  not_forward: "That version isn't newer than the one installed, so it wasn't installed.",
  target_not_updatable: `That version can't be installed from here. ${INSTALLER}`,
  schema_newer: "The device's data comes from a newer version than that one, so it wasn't installed.",
}

export function reasonWords(code: string | null): string {
  return (code !== null && REASONS[code]) || GENERIC_FAILURE
}

// The link that goes with a reason's words: the docs on updating with the installer, or the Status page after a switch
export interface ReasonLink {
  href: string
  text: string
  external: boolean
}

export const INSTALLER_DOCS = 'https://docs.trafficmonitor.ai/latest/build-your-own-device-diy/update/'
const DOCS_LINK: ReasonLink = { href: INSTALLER_DOCS, text: 'How to update with the installer', external: true }
const STATUS_LINK: ReasonLink = { href: '/status', text: 'Status page', external: false }

const NEEDS_INSTALLER = new Set(['needs_manual_update', 'addon_needs_installer', 'hardware_needs_installer', 'target_not_updatable'])
const AFTER_SWITCH = new Set(['switch_failed', 'health_failed'])

export function reasonLink(code: string | null): ReasonLink | null {
  if (code !== null && NEEDS_INSTALLER.has(code)) return DOCS_LINK
  if (code !== null && AFTER_SWITCH.has(code)) return STATUS_LINK
  return null
}
