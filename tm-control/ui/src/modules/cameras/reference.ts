// The reference picture on the Cameras page: which rows offer one, where the held pictures are, and the legend's rows.
// The rules about the pictures themselves are the backend's.
import type { components } from '../../api/schema'
import { rowState, type CameraRow } from './rows'

export type ReferenceOut = components['schemas']['ReferenceOut']
export type Picture = 'clean.jpg' | 'zones.jpg'

// Drawn for a zone Frigate gave no colour, as in the drawing (FALLBACK_COLOR in zones.py)
const FALLBACK_COLOR = '#888888'

// An entry whose camera is on in Frigate and that repeats no other entry: the take asks Frigate for that camera
export function canTake(row: CameraRow): boolean {
  return rowState(row) === 'in-step'
}

export function pictureUrl(name: string, ticket: string, picture: Picture): string {
  return `/api/v1/cameras/${encodeURIComponent(name)}/reference/${encodeURIComponent(ticket)}/${picture}`
}

// One row per zone, as in the drawing's legend: a zone that is off says so first, then side lengths, then a zone with
// no outline
export function legendRows(reference: ReferenceOut): { key: string; color: string; detail: string }[] {
  return reference.zones.map((zone) => {
    let detail = ''
    if (!zone.enabled) detail = 'off in Frigate, not drawn'
    else if (zone.sides.length) {
      detail = zone.sides.map((side) => `${side.start}–${side.end} ${side.length} ${reference.unit}`).join(', ')
    } else if (!zone.drawn) detail = 'no outline'
    return { key: zone.key, color: zone.color ?? FALLBACK_COLOR, detail }
  })
}
