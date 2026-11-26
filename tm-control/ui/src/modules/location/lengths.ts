// Lengths on the Mounting page. The control app stores metres; feet exist only on the page: what a field shows, what
// is typed into it, and the unit the browser remembers.

export type Unit = 'ft' | 'm'

const METRES_PER_FOOT = 0.3048
const STORAGE_KEY = 'tm.mounting.unit'

// `toFixed` rounds the number's exact value and a tie to the larger magnitude, a minus sign aside, which is how the
// backend rounds (half away from zero). A tiny negative would read "-0.00", so the sign goes with it.
function fixed(value: number, places: number): string {
  const text = value.toFixed(places)
  return /^-0(\.0+)?$/.test(text) ? text.slice(1) : text
}

// The text of a length in a field: one decimal in feet, two in metres, nothing for no length
export function shown(metres: number | null, unit: Unit): string {
  if (metres === null) return ''
  return unit === 'ft' ? fixed(metres / METRES_PER_FOOT, 1) : fixed(metres, 2)
}

// A plain number as typed, or null. One comma and no dot is the decimal mark ("3,66"), since a phone's keypad in many
// regions has a comma and no dot; a comma before exactly three digits ("1,000") may be a thousands separator, so it
// isn't read.
export function decimal(text: string): number | null {
  const trimmed = text.trim()
  const dotted = /^-?\d*,\d*$/.test(trimmed) && !/,\d{3}$/.test(trimmed) ? trimmed.replace(',', '.') : trimmed
  return /^-?(\d+\.?\d*|\.\d+)$/.test(dotted) ? Number(dotted) : null
}

// What was typed, as metres to two decimals; null for nothing or for text that isn't a number
export function typed(text: string, unit: Unit): number | null {
  const value = decimal(text)
  if (value === null) return null
  return Number(fixed(unit === 'ft' ? value * METRES_PER_FOOT : value, 2)) + 0
}

// A length in both units, the chosen one first: "7.0 ft (2.13 m)"
export function both(metres: number | null, unit: Unit): string {
  if (metres === null) return ''
  const other: Unit = unit === 'ft' ? 'm' : 'ft'
  return `${shown(metres, unit)} ${unit} (${shown(metres, other)} ${other})`
}

// Feet unless the browser remembers metres. A browser may refuse its storage, and then it is feet.
export function savedUnit(): Unit {
  try {
    return localStorage.getItem(STORAGE_KEY) === 'm' ? 'm' : 'ft'
  } catch {
    return 'ft'
  }
}

export function saveUnit(unit: Unit): void {
  try {
    localStorage.setItem(STORAGE_KEY, unit)
  } catch {
    // The choice then lasts only until the page is closed
  }
}
