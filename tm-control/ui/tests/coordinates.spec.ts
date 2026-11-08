// The Location page's coordinate helpers: the form's quick check of a pasted pair, and how places are shown.
import { describe, expect, it } from 'vitest'
import {
  BEARINGS,
  PRECISIONS,
  distanceKm,
  formatExact,
  formatStored,
  isCoarser,
  parsePair,
} from '../src/modules/location/coordinates'

describe('parsePair', () => {
  it('accepts a comma and a space, a comma alone, or spaces alone', () => {
    for (const text of ['45.52252, -122.69120', '45.52252,-122.6912', '  45.52252   -122.6912 ']) {
      expect(parsePair(text), text).toEqual({ lat: 45.52252, lon: -122.6912 })
    }
  })

  it('refuses a decimal comma', () => {
    expect(parsePair('45,52252, -122,69120')).toBeNull()
    expect(parsePair('45,52252 -122,69120')).toBeNull()
  })

  it('refuses a pair in the wrong order, because the latitude is out of range', () => {
    expect(parsePair('-122.69120, 45.52252')).toBeNull()
  })

  it('refuses one number, three, an exponent, or words', () => {
    for (const text of ['45.52252', '45.0, -122.0, 3', '4.5e1, -122.0', 'here', '']) {
      expect(parsePair(text), text).toBeNull()
    }
  })
})

describe('formatStored', () => {
  it('shows what the database stores, or says it stores nothing', () => {
    expect(formatStored(45.5, -122.7)).toBe('45.5, -122.7')
    expect(formatStored(null, null)).toBe('No location stored')
  })

  it('pads to the precision when given, so 45.0 reads as a coordinate', () => {
    expect(formatStored(45, -122, 1)).toBe('45.0, -122.0')
    expect(formatStored(45.52, -122.69, 2)).toBe('45.52, -122.69')
  })
})

describe('formatExact', () => {
  it('pads to five places', () => {
    expect(formatExact(45.52252, -122.6912)).toBe('45.52252, -122.69120')
    expect(formatExact(null, null)).toBe('No location')
  })
})

// Loose bounds: the check only has to tell a typo fixed nearby from a point that looks like a move (over about 1 km)
describe('distanceKm', () => {
  it('measures a small correction as well under 1 km', () => {
    const km = distanceKm({ lat: 45.52252, lon: -122.6912 }, { lat: 45.52, lon: -122.69 })
    expect(km).toBeGreaterThan(0.2)
    expect(km).toBeLessThan(0.5)
  })

  it('measures a far one as tens of kilometres, the same either way', () => {
    const there = distanceKm({ lat: 45.0, lon: -122.0 }, { lat: 45.52252, lon: -122.6912 })
    expect(there).toBeGreaterThan(70)
    expect(there).toBeLessThan(90)
    expect(distanceKm({ lat: 45.52252, lon: -122.6912 }, { lat: 45.0, lon: -122.0 })).toBeCloseTo(there, 6)
  })
})

describe('the choices', () => {
  it('names the bearings, with Not set last', () => {
    expect(BEARINGS.map((b) => b.title)).toEqual(['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW', 'Not set'])
    expect(BEARINGS.at(-1)?.value).toBe('')
  })

  it('names the precisions, coarsest first', () => {
    expect(PRECISIONS.map((p) => p.title)).toEqual([
      'No location stored',
      'About 10 km (45.5, -122.7)',
      'About 1 km (45.52, -122.69), the default',
    ])
    expect(PRECISIONS.map((p) => p.value)).toEqual(['none', '1', '2'])
    expect(isCoarser('none', '1')).toBe(true)
    expect(isCoarser('1', '2')).toBe(true)
    expect(isCoarser('2', '1')).toBe(false)
    expect(isCoarser('1', '1')).toBe(false)
  })
})
