// Lengths on the Mounting page: stored in metres, shown and typed in feet or metres, the unit remembered in the
// browser.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { both, savedUnit, saveUnit, shown, typed } from '../src/modules/location/lengths'

beforeEach(() => localStorage.clear())
afterEach(() => vi.restoreAllMocks())

describe('shown', () => {
  it('shows 2.13 m as 7.0 in feet and 2.13 in metres', () => {
    expect(shown(2.13, 'ft')).toBe('7.0')
    expect(shown(2.13, 'm')).toBe('2.13')
  })

  it('is empty for no length', () => {
    expect(shown(null, 'ft')).toBe('')
    expect(shown(null, 'm')).toBe('')
  })

  it('keeps two decimals in metres and one in feet, as a whole number too', () => {
    expect(shown(3, 'm')).toBe('3.00')
    expect(shown(0.5, 'ft')).toBe('1.6')
  })

  it('rounds halves away from zero, as the backend does', () => {
    expect(shown(0.125, 'm')).toBe('0.13')
    expect(shown(-0.125, 'm')).toBe('-0.13')
  })
})

describe('typed', () => {
  it('turns feet into metres with two decimals', () => {
    expect(typed('7', 'ft')).toBe(2.13)
    expect(typed('12', 'ft')).toBe(3.66)
    expect(typed('16', 'ft')).toBe(4.88)
  })

  it('keeps metres as typed, to two decimals', () => {
    expect(typed('2.13', 'm')).toBe(2.13)
    expect(typed('2.126', 'm')).toBe(2.13)
    expect(typed(' 4 ', 'm')).toBe(4)
  })

  it('is null for nothing or for text that is not a number', () => {
    expect(typed('', 'ft')).toBeNull()
    expect(typed('   ', 'm')).toBeNull()
    expect(typed('abc', 'ft')).toBeNull()
    expect(typed('1e3', 'm')).toBeNull()
    expect(typed('7 ft', 'ft')).toBeNull()
  })

  it('is a plain zero, never minus zero, for a value that rounds to nothing', () => {
    expect(Object.is(typed('0.01', 'ft'), 0)).toBe(true)
    expect(Object.is(typed('0.001', 'm'), 0)).toBe(true)
    expect(Object.is(typed('-0.001', 'm'), 0)).toBe(true)
    expect(Object.is(typed('0', 'ft'), 0)).toBe(true)
  })

  it('keeps a negative value for the API to refuse', () => {
    expect(typed('-2', 'm')).toBe(-2)
    expect(typed('-7', 'ft')).toBe(-2.13)
  })

  it('reads a leading or trailing point', () => {
    expect(typed('.5', 'm')).toBe(0.5)
    expect(typed('7.', 'ft')).toBe(2.13)
  })

  it('reads one comma with no dot as the decimal mark, as a phone keypad in many regions types it', () => {
    expect(typed('3,66', 'm')).toBe(3.66)
    expect(typed('7,5', 'ft')).toBe(2.29)
    expect(typed(',5', 'm')).toBe(0.5)
    expect(typed('-2,5', 'm')).toBe(-2.5)
  })

  it('does not read a comma before exactly three digits, more than one comma, or a comma and a dot', () => {
    expect(typed('1,000', 'ft')).toBeNull() // a thousands separator, perhaps
    expect(typed('1,2,3', 'm')).toBeNull()
    expect(typed('1,000.5', 'm')).toBeNull()
    expect(typed('1.5,0', 'm')).toBeNull()
  })
})

describe('both', () => {
  it('writes the chosen unit first and the other in brackets', () => {
    expect(both(2.13, 'ft')).toBe('7.0 ft (2.13 m)')
    expect(both(2.13, 'm')).toBe('2.13 m (7.0 ft)')
  })

  it('is empty for no length', () => {
    expect(both(null, 'ft')).toBe('')
  })
})

describe('the remembered unit', () => {
  it('is feet when nothing is remembered', () => {
    expect(savedUnit()).toBe('ft')
  })

  it('is metres after metres was saved, and feet after feet', () => {
    saveUnit('m')
    expect(localStorage.getItem('tm.mounting.unit')).toBe('m')
    expect(savedUnit()).toBe('m')
    saveUnit('ft')
    expect(savedUnit()).toBe('ft')
  })

  it('is feet for anything else that is stored', () => {
    localStorage.setItem('tm.mounting.unit', 'yards')
    expect(savedUnit()).toBe('ft')
  })

  it('is feet when the browser refuses to read', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked')
    })
    expect(savedUnit()).toBe('ft')
  })

  it('does not throw when the browser refuses to write', () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked')
    })
    expect(() => saveUnit('m')).not.toThrow()
  })
})
