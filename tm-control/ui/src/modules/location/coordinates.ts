// Coordinates and the Location page's choices. The rules live in the backend (modules/location/coordinates.py):
// parsePair is only the form's quick check before it sends, and the API's answer wins. Nothing here rounds a
// coordinate: the API sends the stored values already rounded, and the exact ones already kept to five places.
import type { components } from '../../api/schema'

type SensorHeading = components['schemas']['SensorHeading']

// A number with an optional sign and fraction: no exponent, no decimal comma, as the backend accepts
const NUMBER = String.raw`[+-]?(?:\d+(?:\.\d+)?|\.\d+)`
// Two numbers separated by a comma (spaces around it allowed) or by spaces alone
const PAIR = new RegExp(String.raw`^\s*(${NUMBER})(?:\s*,\s*|\s+)(${NUMBER})\s*$`)

export type LatLon = { lat: number; lon: number }

// A pasted "latitude, longitude", or null when it isn't one (a decimal comma, the wrong order, out of range)
export function parsePair(text: string): LatLon | null {
  const match = PAIR.exec(text)
  if (!match) return null
  const lat = Number(match[1])
  const lon = Number(match[2])
  if (Math.abs(lat) > 90 || Math.abs(lon) > 180) return null
  return { lat, lon }
}

// The fewer digits after the dot of the two numbers in a pair `parsePair` accepts; null for any other text
export function decimalsTyped(text: string): number | null {
  if (!parsePair(text)) return null
  const match = PAIR.exec(text)!
  const digits = (number: string) => (number.split('.')[1] ?? '').length
  return Math.min(digits(match[1]), digits(match[2]))
}

// How wide an area a count of decimal places (0 to 3) keeps a point to
export function roundedTo(decimals: number): string {
  return ['100 km', '10 km', '1 km', '100 m'][decimals]
}

// Four places keep a point to about 10 m, which is what an exact location needs
export const FEW_DECIMALS = 4

// A line under the coordinates field for a pair typed with fewer places than that, or '' for anything else. It is
// advice, never an error: a place at a coarse point is allowed.
export function fewDecimalsWarning(text: string): string {
  const decimals = decimalsTyped(text)
  if (decimals === null || decimals >= FEW_DECIMALS) return ''
  return `For an exact location, use at least four decimal places (about 10 m). This is rounded to about ${roundedTo(decimals)}.`
}

// How far apart two points are, in km, along the earth's surface (the haversine formula, on a sphere of the earth's
// mean radius). Correct location uses it only to tell a typo fixed nearby from a point that looks like a move.
export function distanceKm(from: LatLon, to: LatLon): number {
  const radians = (degrees: number) => (degrees * Math.PI) / 180
  const dLat = radians(to.lat - from.lat)
  const dLon = radians(to.lon - from.lon)
  const a = Math.sin(dLat / 2) ** 2 + Math.cos(radians(from.lat)) * Math.cos(radians(to.lat)) * Math.sin(dLon / 2) ** 2
  return 2 * 6371 * Math.asin(Math.sqrt(a))
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

// The heading each sensor starts at in the place form and the deploy review: the place's own for that sensor, else
// the sensor's heading in config.yml now. One entry per sensor, in the sensors' order.
export function startingHeadings(sensors: SensorHeading[], place?: { headings: SensorHeading[] }): SensorHeading[] {
  return sensors.map((sensor) => {
    const own = place?.headings.find(
      (kept) => kept.sensor_type === sensor.sensor_type && kept.sensor_name === sensor.sensor_name,
    )
    return { ...sensor, heading_deg: own ? own.heading_deg : sensor.heading_deg }
  })
}

// What deploying to a place is called, by the place's status: the button on the place and the review's title
// (`action`), and the review's button that does it (`confirm`). The place in use isn't deployed to: its button is
// Mounting.
export function deployWords(status: string): { action: string; confirm: string } {
  if (status === 'used') return { action: 'Re-deploy here', confirm: 'Re-deploy' }
  return { action: 'Deploy here', confirm: 'Deploy' }
}

export type Precision = 'none' | '1' | '2'

// How precisely the database stores each place, coarsest first. `places` is the number of decimal places kept. Each
// title shows the same point stored at that precision, so the area in words reads as coordinates too.
export const PRECISIONS: { value: Precision; title: string; places: number | undefined }[] = [
  { value: 'none', title: 'No location stored', places: undefined },
  { value: '1', title: 'About 10 km (45.5, -122.7)', places: 1 },
  { value: '2', title: 'About 1 km (45.52, -122.69), the default', places: 2 },
]

// Whether `next` stores less than `current`, which is when the rows already stored can be rounded to it
export function isCoarser(next: Precision, current: Precision): boolean {
  const rank = (precision: Precision) => PRECISIONS.findIndex((choice) => choice.value === precision)
  return rank(next) < rank(current)
}
