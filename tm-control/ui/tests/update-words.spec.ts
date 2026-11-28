// The Software update page's words for the run's stages and the reasons a run or a start failed (words.ts).
import { describe, expect, it } from 'vitest'
import { GENERIC_FAILURE, reasonLink, reasonWords, stageNote, stageTitle } from '../src/modules/update/words'

// The stage ids and reason codes this version of tm-update and its job write (docs/development/software-update.md)
const STAGES: [string, string][] = [
  ['fetch', 'Download'],
  ['verify', 'Check'],
  ['prepare', 'Prepare'],
  ['images', 'Build'],
  ['restore_point', 'Restore point'],
  ['switch', 'Switch'],
  ['reboot', 'Restart'],
  ['health', 'Verify'],
  ['cleanup', 'Clean up'],
]
const REASONS = [
  'busy',
  'needs_manual_update',
  'addon_needs_installer',
  'reboot_pending',
  'low_space',
  'hardware_needs_installer',
  'no_internet',
  'settings_need_attention',
  'prepare_failed',
  'build_failed',
  'switch_failed',
  'health_failed',
  'fetch_failed',
  'stale_check',
  'not_forward',
  'target_not_updatable',
  'schema_newer',
]
const DOCS = 'https://docs.trafficmonitor.ai/latest/build-your-own-device-diy/update/'

describe('the update words', () => {
  it('has words for every stage id and reason code this version knows', () => {
    for (const [id, title] of STAGES) expect(stageTitle(id)).toBe(title)
    for (const code of REASONS) {
      const words = reasonWords(code)
      expect(words, code).not.toBe(GENERIC_FAILURE)
      expect(words, code).toMatch(/^[A-Z].*\.$/) // a sentence, not a code
      expect(words, code).not.toContain('_')
    }
    expect(reasonWords('busy')).toBe('Another install or update is running on this device. Wait for it to end.')
  })

  it('links the docs for the four that need the installer, and the Status page after a switch', () => {
    const installer = ['needs_manual_update', 'addon_needs_installer', 'hardware_needs_installer', 'target_not_updatable']
    for (const code of installer) {
      expect(reasonWords(code), code).toMatch(/Update it with the installer\.$/)
      expect(reasonLink(code)?.href, code).toBe(DOCS)
    }
    const switching = ['switch_failed', 'health_failed']
    for (const code of switching) {
      expect(reasonWords(code), code).toContain('may be on the new version')
      expect(reasonLink(code)?.href, code).toBe('/status')
    }
    const others = REASONS.filter((code) => !installer.includes(code) && !switching.includes(code))
    for (const code of others) expect(reasonLink(code), code).toBeNull()
  })

  it('adds a note to the switch and the restart, and to no other stage', () => {
    expect(stageNote('switch')).toBe('(the device stops answering for about 3 minutes)')
    expect(stageNote('reboot')).toBe('(a few more minutes while it restarts)')
    for (const [id] of STAGES.filter(([id]) => id !== 'switch' && id !== 'reboot')) expect(stageNote(id), id).toBeNull()
    expect(stageNote('calibrate_radar')).toBeNull()
  })

  it('shows an unknown stage by its id and an unknown reason as a generic failure', () => {
    expect(stageTitle('calibrate_radar')).toBe('calibrate_radar')
    expect(reasonWords('flux_capacitor')).toBe(GENERIC_FAILURE)
    expect(reasonWords(null)).toBe(GENERIC_FAILURE)
    expect(GENERIC_FAILURE).toBe('The update failed. The log below has the details.')
    expect(reasonLink('flux_capacitor')).toBeNull()
    expect(reasonLink(null)).toBeNull()
  })
})
