// A stored reference picture's words and addresses: where its two frames are, why it was taken, the line for its mark,
// and the note for the first picture after a restart. The rules about which pictures exist are the backend's.
import type { components } from '../../api/schema'

export type PictureOut = components['schemas']['PictureOut']
export type StoredFrame = 'clean.jpg' | 'zones.jpg'

// The device's address for one of a picture's frames; the session cookie authorizes it and the page keeps no copy
export function storedUrl(id: string, picture: StoredFrame): string {
  return `/api/v1/pictures/${encodeURIComponent(id)}/${picture}`
}

const REASONS: Record<PictureOut['reason'], string> = {
  deployed: 'The unit was deployed here',
  opted_in: 'Pictures were turned on for this place',
  mounting: "The camera's mounting changed",
  setup: "The camera's setup changed in Frigate",
  daylight: 'Taken again in daylight',
  manual: 'Kept by an administrator',
}

export function reasonWords(reason: PictureOut['reason']): string {
  return REASONS[reason]
}

// The line for a picture's mark: a warning for a person, information for a picture the device couldn't check, and
// none for a clear one. A restart never changes it.
export function markLine(picture: Pick<PictureOut, 'mark'>): { type: 'warning' | 'info'; text: string } | null {
  if (picture.mark === 'person') {
    return { type: 'warning', text: 'Frigate was tracking a person. Blur them before you share it, or leave it out.' }
  }
  if (picture.mark === 'unchecked') {
    return { type: 'info', text: "The device couldn't check for people. Look closely before you share it." }
  }
  return null
}

// Plain text under the reason, never an alert: the first picture after a restart may not show this place
export function restartNote(picture: Pick<PictureOut, 'after_restart'>): string | null {
  return picture.after_restart ? 'The unit restarted before this picture, so it may not show this place.' : null
}
