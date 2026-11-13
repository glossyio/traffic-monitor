// What the Cameras page says about a row, kept out of the components so each rule can be tested on its own and the
// page's later actions can ask the same questions.
import type { components } from '../../api/schema'

export type CameraRow = components['schemas']['CameraRow']
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
