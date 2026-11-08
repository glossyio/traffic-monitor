// Coordinates and the Location page's choices. The rules live in the backend (modules/location/coordinates.py):
// parsePair is only the form's quick check before it sends, and the API's answer wins. Nothing here rounds a
// coordinate: the API sends the stored values already rounded, and the exact ones already kept to five places.

// A number with an optional sign and fraction: no exponent, no decimal comma, as the backend accepts
const NUMBER = String.raw`[+-]?(?:\d+(?:\.\d+)?|\.\d+)`
// Two numbers separated by a comma (spaces around it allowed) or by spaces alone
const PAIR = new RegExp(String.raw`^\s*(${NUMBER})(?:\s*,\s*|\s+)(${NUMBER})\s*$`)

// A pasted "latitude, longitude", or null when it isn't one (a decimal comma, the wrong order, out of range)
export function parsePair(text: string): { lat: number; lon: number } | null {
  const match = PAIR.exec(text)
  if (!match) return null
  const lat = Number(match[1])
  const lon = Number(match[2])
  if (Math.abs(lat) > 90 || Math.abs(lon) > 180) return null
  return { lat, lon }
}

// What the database stores for a place. `places`, the precision's decimal places, pads 45 to "45.0"; the values
// are already rounded to it, so padding changes no digit.
export function formatStored(lat: number | null, lon: number | null, places?: number): string {
  if (lat === null || lon === null) return 'No location stored'
  const show = (value: number) => (places === undefined ? String(value) : value.toFixed(places))
  return `${show(lat)}, ${show(lon)}`
}

// The exact location, at the five places the device keeps it to
export function formatExact(lat: number | null, lon: number | null): string {
  if (lat === null || lon === null) return 'No location'
  return `${lat.toFixed(5)}, ${lon.toFixed(5)}`
}

// Which way a sensor faces, as config.yml writes it ('' when it isn't set)
export const BEARINGS = [
  { value: 'n', title: 'N' },
  { value: 'ne', title: 'NE' },
  { value: 'e', title: 'E' },
  { value: 'se', title: 'SE' },
  { value: 's', title: 'S' },
  { value: 'sw', title: 'SW' },
  { value: 'w', title: 'W' },
  { value: 'nw', title: 'NW' },
  { value: '', title: 'Not set' },
]

export function bearingTitle(value: string): string {
  return BEARINGS.find((bearing) => bearing.value === value.trim().toLowerCase())?.title ?? value
}

export type Precision = 'none' | '1' | '2'

// How precisely the database stores each place, coarsest first. `places` is the number of decimal places kept.
export const PRECISIONS: { value: Precision; title: string; places: number | undefined }[] = [
  { value: 'none', title: 'No location stored', places: undefined },
  { value: '1', title: 'About 10 km (default)', places: 1 },
  { value: '2', title: 'About 1 km', places: 2 },
]

// Whether `next` stores less than `current`, which is when the rows already stored can be rounded to it
export function isCoarser(next: Precision, current: Precision): boolean {
  const rank = (precision: Precision) => PRECISIONS.findIndex((choice) => choice.value === precision)
  return rank(next) < rank(current)
}
