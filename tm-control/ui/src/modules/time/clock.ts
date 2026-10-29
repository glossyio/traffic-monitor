// The Date and time page's two clocks: an instant shown as the time at some offset from UTC, and the device's clock
// compared with this browser's in words.
import { duration } from '../../components/relative-time'

// Clocks within this many seconds of each other agree: the device reports whole seconds, and the answer takes a
// moment to arrive.
export const TOLERANCE_S = 5

// "2026-10-28T14:32:12-07:00": the instant (milliseconds since 1970) and its offset from UTC in minutes (-420)
export function parseDeviceTime(iso: string): { instant: number; offset: number } | null {
  const instant = Date.parse(iso)
  const match = /(?:Z|([+-])(\d{2}):(\d{2}))$/.exec(iso)
  if (Number.isNaN(instant) || !match) return null
  const minutes = match[1] ? Number(match[2]) * 60 + Number(match[3]) : 0
  return { instant, offset: match[1] === '-' ? -minutes : minutes }
}

// This browser's offset from UTC at that instant, in minutes. (getTimezoneOffset counts the other way round.)
export function browserOffset(instant: number): number {
  return -new Date(instant).getTimezoneOffset()
}

function pad(n: number) {
  return String(n).padStart(2, '0')
}

// The time and date at `offset` minutes from UTC: { time: '14:32:12', date: 'Oct 28, 2026', zone: 'UTC-07:00' }.
// The instant moved by the offset and read as UTC is the clock at that offset, whatever this browser's own zone is.
export function wallClock(instant: number, offset: number) {
  const shifted = new Date(instant + offset * 60_000)
  const time = `${pad(shifted.getUTCHours())}:${pad(shifted.getUTCMinutes())}:${pad(shifted.getUTCSeconds())}`
  const date = shifted.toLocaleDateString(undefined, { timeZone: 'UTC', day: 'numeric', month: 'short', year: 'numeric' })
  const zone = `UTC${offset < 0 ? '-' : '+'}${pad(Math.floor(Math.abs(offset) / 60))}:${pad(Math.abs(offset) % 60)}`
  return { time, date, zone }
}

// The device's clock against this browser's. `seconds` is the device's time minus the browser's; the zones are the
// same when the clocks show the same offset from UTC, so two names for one zone (Etc/UTC and UTC) don't count as
// different.
export function comparison(seconds: number, sameZone: boolean): string {
  const sentences = []
  if (Math.abs(seconds) > TOLERANCE_S) {
    sentences.push(`The device is ${duration(seconds)} ${seconds < 0 ? 'behind' : 'ahead of'} this browser.`)
  }
  if (!sameZone) sentences.push("The device's time zone differs from this browser's.")
  return sentences.length ? sentences.join(' ') : 'The device and this browser agree.'
}
