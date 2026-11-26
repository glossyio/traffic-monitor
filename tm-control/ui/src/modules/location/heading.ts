// Which way a sensor faces: a heading in whole degrees clockwise from true north, 0 to 359. A compass point is only a
// way to pick a heading and to read one, and nothing stores a point. The rule is the backend's (coordinates.py,
// pinned there by test_compass_point); this copy only titles a pick, and a test holds it to the same table.

export const POINTS = ['n', 'ne', 'e', 'se', 's', 'sw', 'w', 'nw'] as const
export type Point = (typeof POINTS)[number]

// The point a heading belongs to: 0 to 22 is n, 23 to 67 ne, 68 to 112 e, and so on round to 338 to 359, n
export function compassPoint(heading: number): Point {
  return POINTS[Math.floor((((heading + 22.5) % 360) + 360) % 360 / 45)]
}

// The heading at the centre of one of the eight points: N is 0, NE 45, and so on
export function centreOf(point: Point): number {
  return POINTS.indexOf(point) * 45
}

// The heading at the centre of a point, after trimming and lower-casing; null for anything that isn't one of the eight
export function pointCentre(point: string): number | null {
  const found = POINTS.find((each) => each === point.trim().toLowerCase())
  return found === undefined ? null : centreOf(found)
}

// Each point in words, for the heading dial's buttons and its readout
export const POINT_WORDS: Record<Point, string> = {
  n: 'north',
  ne: 'north-east',
  e: 'east',
  se: 'south-east',
  s: 'south',
  sw: 'south-west',
  w: 'west',
  nw: 'north-west',
}

// A heading with its point, "NE (40°)"; "Not set" for none
export function facing(heading: number | null): string {
  if (heading === null) return 'Not set'
  return `${compassPoint(heading).toUpperCase()} (${heading}°)`
}

export type HeadingChoice = { value: number | null; title: string }

// What a pick offers: the eight points, each as its centre, then Not set. A heading that isn't a centre comes first,
// titled by `facing`, so opening a pick and leaving it never changes a measured heading.
export function headingChoices(current: number | null): HeadingChoice[] {
  const choices: HeadingChoice[] = [
    ...POINTS.map((point) => ({ value: centreOf(point), title: point.toUpperCase() })),
    { value: null, title: 'Not set' },
  ]
  if (current !== null && current % 45 !== 0) choices.unshift({ value: current, title: facing(current) })
  return choices
}

// The heading dial's readout: "52°, north-east."; "Not set." for none
export function facingWords(heading: number | null): string {
  if (heading === null) return 'Not set.'
  return `${heading}°, ${POINT_WORDS[compassPoint(heading)]}.`
}

// The heading of a point (x, y) seen from a centre (cx, cy), in screen coordinates, where y grows downward: whole
// degrees clockwise with up as 0 and right as 90, so 359.5 and above round to 0. The centre itself is 0.
export function angleAt(x: number, y: number, cx: number, cy: number): number {
  const degrees = (Math.atan2(x - cx, cy - y) * 180) / Math.PI
  return ((Math.round(degrees) % 360) + 360) % 360
}
