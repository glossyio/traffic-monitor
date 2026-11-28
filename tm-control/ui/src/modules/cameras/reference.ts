// The reference picture on the Cameras page: which rows offer one, where the held pictures are, the legend's rows, and
// the line about people.
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

// The one line above the pictures, from the device's answer to "was Frigate tracking a person" at the two takes. Only
// `seen` is a warning: neither of the others is a finding, and none of the three stops the admin from saving. The
// warning is solid, so it doesn't read as part of the tonal warning (the note) above it; the other two stay tonal.
export function peopleLine(people: ReferenceOut['people']): {
  type: 'warning' | 'info'
  variant: 'flat' | 'tonal'
  text: string
} {
  if (people === 'seen') {
    return {
      type: 'warning',
      variant: 'flat',
      text:
        'Frigate was tracking a person on this camera when the pictures were taken. Wait until nobody is in view, ' +
        'then take them again.',
    }
  }
  if (people === 'none') {
    return {
      type: 'info',
      variant: 'tonal',
      text:
        "Frigate wasn't tracking a person when the pictures were taken. It can miss people, so look at both pictures " +
        'yourself.',
    }
  }
  return {
    type: 'info',
    variant: 'tonal',
    text:
      "The device couldn't check for people, because Frigate's detection is off for this camera or Frigate didn't " +
      'answer. Look at both pictures yourself.',
  }
}
