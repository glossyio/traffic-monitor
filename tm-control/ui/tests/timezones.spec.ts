// The Location page's time zone helpers: which time zone a place starts with, and the device's list of them.
import { beforeEach, describe, expect, it } from 'vitest'
import { loadTimeZones, startingTimeZone } from '../src/modules/location/timezones'
import { apiError, fakeApi } from './fake-api'

const LIST = ['America/New_York', 'Asia/Tokyo', 'Europe/Berlin']

describe('startingTimeZone', () => {
  it("gives the place's time zone", () => {
    expect(startingTimeZone('Asia/Tokyo', 'Europe/Berlin')).toBe('Asia/Tokyo')
  })

  it("gives the clock's when the place has none", () => {
    expect(startingTimeZone(null, 'Europe/Berlin')).toBe('Europe/Berlin')
    expect(startingTimeZone(undefined, 'Europe/Berlin')).toBe('Europe/Berlin')
    expect(startingTimeZone('', 'Europe/Berlin')).toBe('Europe/Berlin')
  })

  it('gives null when neither is known', () => {
    expect(startingTimeZone(null, null)).toBeNull()
  })
})

describe('loadTimeZones', () => {
  beforeEach(() => document.body.replaceChildren())

  it('asks the device for its list', async () => {
    const { sent } = fakeApi({ 'GET /api/v1/time/timezones': LIST })
    expect(await loadTimeZones()).toEqual(LIST)
    expect(sent.map((r) => `${r.method} ${r.path}`)).toEqual(['GET /api/v1/time/timezones'])
  })

  it('throws what the client throws', async () => {
    fakeApi({ 'GET /api/v1/time/timezones': apiError(500, 'internal', 'The list is unavailable.') })
    await expect(loadTimeZones()).rejects.toThrow()
  })
})
