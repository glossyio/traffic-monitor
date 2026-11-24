// The Location page's coordinate helpers: the form's quick check of a pasted pair, and how places are shown.
import { describe, expect, it } from 'vitest'
import {
  FEW_DECIMALS,
  PRECISIONS,
  decimalsTyped,
  distanceKm,
  formatExact,
  formatStored,
  fewDecimalsWarning,
  isCoarser,
  parsePair,
  roundedTo,
  startingHeadings,
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

describe('decimalsTyped', () => {
  it('counts the digits after the dot of the shorter number', () => {
    expect(decimalsTyped('45.52252, -122.69120')).toBe(5)
    expect(decimalsTyped('45.5, -122.69120')).toBe(1)
    expect(decimalsTyped('45.52252 -122.7')).toBe(1)
    expect(decimalsTyped('45, -122')).toBe(0)
  })

  it('is null for text that is not a pair', () => {
    expect(decimalsTyped('abc')).toBeNull()
    expect(decimalsTyped('45,5 122')).toBeNull()
    expect(decimalsTyped('')).toBeNull()
    expect(decimalsTyped('95.12345, 10.12345')).toBeNull()
  })
})

describe('roundedTo', () => {
  it('names the area a count of decimal places keeps', () => {
    expect([0, 1, 2, 3].map(roundedTo)).toEqual(['100 km', '10 km', '1 km', '100 m'])
  })
})

describe('fewDecimalsWarning', () => {
  it('warns below four decimal places and says how far the rounding reaches', () => {
    expect(FEW_DECIMALS).toBe(4)
    expect(fewDecimalsWarning('45.52, -122.69')).toBe(
      'For an exact location, use at least four decimal places (about 10 m). This is rounded to about 1 km.',
    )
    expect(fewDecimalsWarning('45.123, -122.6912')).toContain('rounded to about 100 m.')
  })

  it('says nothing for four places or more, for a blank field, or for text that is not a pair', () => {
    expect(fewDecimalsWarning('45.5225, -122.6912')).toBe('')
    expect(fewDecimalsWarning('45.52252, -122.69120')).toBe('')
    expect(fewDecimalsWarning('')).toBe('')
    expect(fewDecimalsWarning('abc')).toBe('')
  })
})

describe('startingHeadings', () => {
  const NOW = [
    { sensor_type: 'cameras', sensor_name: 'picam_h265', heading_deg: 0 },
    { sensor_type: 'radars', sensor_name: 'TM_RADAR_SERIAL_PORT_00', heading_deg: null },
  ]

  it("starts each sensor at the sensor's heading in config.yml now with no place", () => {
    expect(startingHeadings(NOW)).toEqual(NOW)
  })

  it("starts each sensor at the place's own heading where it has one, else the current one", () => {
    const place = { headings: [{ sensor_type: 'cameras', sensor_name: 'picam_h265', heading_deg: 40 }] }
    expect(startingHeadings(NOW, place)).toEqual([{ ...NOW[0], heading_deg: 40 }, NOW[1]])
  })

  it("keeps a place's own empty heading rather than the sensor's", () => {
    const place = { headings: [{ sensor_type: 'cameras', sensor_name: 'picam_h265', heading_deg: null }] }
    expect(startingHeadings(NOW, place)[0].heading_deg).toBeNull()
  })

  it('returns copies, so changing a choice leaves the sensors alone', () => {
    startingHeadings(NOW)[0].heading_deg = 90
    expect(NOW[0].heading_deg).toBe(0)
  })
})
