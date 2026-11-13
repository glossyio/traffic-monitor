// What the Cameras page says about a row, kept out of the components so each rule can be tested on its own and the
// page's later actions can ask the same questions.
import type { components } from '../../api/schema'

export type CameraRow = components['schemas']['CameraRow']
export type CameraIssue = components['schemas']['CameraIssue']
export type CameraRadar = components['schemas']['CameraRadar']

// 'unknown' is a row while Frigate can't be compared (down or in safe mode): the page shows its settings and
// nothing about Frigate's side.
export type RowState = 'in-step' | 'off' | 'new' | 'gone' | 'duplicate' | 'unknown'

export function rowState(row: CameraRow): RowState {
  if (row.name === null) return 'new'
  if (row.duplicate_of !== null) return 'duplicate'
  if (row.in_frigate === 'unknown') return 'unknown'
  if (row.in_frigate === 'absent') return 'gone'
  if (row.in_frigate === 'off') return 'off'
  return 'in-step'
}

// Which of the four zones the flows read Frigate lacks or has turned off for this camera (an event never enters a zone
// that is off); nothing for a camera Frigate doesn't have
export function zonesText(row: CameraRow): string {
  if (row.zones_missing === null) return ''
  const off = row.zones_off ?? []
  if (row.zones_missing.length === 0 && off.length === 0) return 'Zones: all four'
  const parts = []
  if (row.zones_missing.length) parts.push(`Missing in Frigate: ${row.zones_missing.join(', ')}`)
  if (off.length) parts.push(`${parts.length ? 'turned' : 'Turned'} off in Frigate: ${off.join(', ')}`)
  return parts.join('; ')
}

// For a new row: the entries whose Frigate camera is gone, which it could be a rename of. The API allows pointing any
// entry whose camera is absent, so an entry that repeats another is included.
export function pointChoices(row: CameraRow, rows: CameraRow[]): CameraRow[] {
  if (rowState(row) !== 'new') return []
  return rows.filter((other) => other.name !== null && other.in_frigate === 'absent')
}

export interface RadarChoice {
  title: string
  value: string | null
  subtitle?: string
  disabled?: boolean
}

// The Radar drop-down: No radar, then each of the unit's radars with its state. A radar with no entry under
// sensors.radars can't be chosen, because pairing with it would record no speed. The camera's current radar, if it is
// none of the unit's radars, is listed as missing so the field shows what the file says.
export function radarChoices(row: CameraRow, radars: CameraRadar[]): RadarChoice[] {
  const choices: RadarChoice[] = [{ title: 'No radar', value: null }]
  for (const radar of radars) {
    const choice: RadarChoice = { title: radar.name, value: radar.name }
    if (!radar.in_config) {
      choice.subtitle = 'not set up in config.yml'
      choice.disabled = true
    } else {
      const marks = []
      if (!radar.enabled) marks.push('off in config.yml')
      if (radar.port_open === false) marks.push('port closed')
      if (marks.length) choice.subtitle = marks.join(', ')
    }
    choices.push(choice)
  }
  const current = row.camera_radar
  if (current !== null && !radars.some((radar) => radar.name === current)) {
    choices.push({ title: `${current} (missing)`, value: current })
  }
  return choices
}

// Frigate's masks and zones settings, opened at this camera, as Frigate's own UI links there
export function frigateZonesHref(row: CameraRow): string {
  return `/frigate/settings?page=masksAndZones&camera=${encodeURIComponent(row.frigate_camera)}`
}

export interface IssueBox {
  level: 'error' | 'warning' // Vuetify's alert types, for the check's error and warn
  text: string
  link?: { href: string; text: string } // a page outside this app, such as Frigate's zones
}

const DIRECTION_ZONES = ['zone_near', 'zone_far']

// What the Status page's camera checks report about a row (the API's issues), worded for this page: what is wrong,
// and what to do here. One box per issue, none for a row in step.
export function issueBoxes(row: CameraRow): IssueBox[] {
  const words: Record<CameraIssue['code'], () => Omit<IssueBox, 'level'>> = {
    not_paired: () => ({
      text: `${row.frigate_camera} is new in Frigate and isn't recorded. Point an entry at it, or choose Add as new.`,
    }),
    duplicate: () => ({
      text: `${row.duplicate_of} already records this Frigate camera. This entry is unused: Remove it.`,
    }),
    gone: () => ({
      text:
        `Frigate no longer has ${row.frigate_camera}. If you renamed it there, choose Point on its new row; ` +
        'if not, Remove this entry.',
    }),
    camera_off: () => ({
      text:
        `Not recorded: ${row.frigate_camera} is turned off in Frigate. Turn it on in Frigate, or turn Database ` +
        'capture off in Edit.',
    }),
    capture_off: () => ({
      text: 'Not recorded: Database capture is off. Turn it on in Edit if you want these events.',
    }),
    detect_off: () => ({ text: "Not recorded: Frigate's detection is off. Turn it on in Edit." }),
    zones: () => {
      const involved = [...(row.zones_missing ?? []), ...(row.zones_off ?? [])]
      const direction = involved.some((zone) => DIRECTION_ZONES.includes(zone))
        ? ' Without zone_near and zone_far, the direction comes only from the radar.'
        : ''
      return {
        text: `${zonesText(row)}.${direction}`,
        link: { href: frigateZonesHref(row), text: 'Edit its zones in Frigate' },
      }
    },
    radar: () => ({
      text:
        `Radar ${row.camera_radar} isn't turned on in config.yml, so this camera gets no speed or direction. ` +
        'Choose another radar in Edit.',
    }),
  }
  return row.issues.map((issue) => ({
    level: issue.level === 'error' ? 'error' : 'warning',
    ...words[issue.code](),
  }))
}
