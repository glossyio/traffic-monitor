// Which way a sensor faces: a heading in whole degrees clockwise from true north, 0 to 359. A compass point is only a
// way to pick a heading and to read one, and nothing stores a point. The rule is the backend's (coordinates.py,
// pinned there by test_compass_point); this copy only titles a pick, and a test holds it to the same table.

export const POINTS = ['n', 'ne', 'e', 'se', 's', 'sw', 'w', 'nw'] as const

// The point a heading belongs to: 0 to 22 is n, 23 to 67 ne, 68 to 112 e, and so on round to 338 to 359, n
export function compassPoint(heading: number): string {
  return POINTS[Math.floor((((heading + 22.5) % 360) + 360) % 360 / 45)]
}

// The heading at the centre of a point, after trimming and lower-casing; null for anything that isn't one of the eight
export function pointCentre(point: string): number | null {
  const index = (POINTS as readonly string[]).indexOf(point.trim().toLowerCase())
  return index === -1 ? null : index * 45
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
    ...POINTS.map((point, index) => ({ value: index * 45, title: point.toUpperCase() })),
    { value: null, title: 'Not set' },
  ]
  if (current !== null && current % 45 !== 0) choices.unshift({ value: current, title: facing(current) })
  return choices
}
