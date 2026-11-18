// The home button's logic: which app a page is, where the button sits, and what it remembers.
import { describe, expect, it } from 'vitest'
import { appOf, defaultPlace, dropped, isDrag, readPlaces, savePlace, titled, topOf } from '../src/home-button/place'

describe('appOf', () => {
  it.each([['/frigate/', 'frigate'], ['/frigate/review?x=1', 'frigate'], ['/nr/', 'nr'], ['/ui/', 'ui'],
           ['/dashboard/monitoring', 'dashboard'], ['/feeds/stream.html', 'feeds']])('%s is %s', (path, app) => {
    expect(appOf(path)).toBe(app)
  })
  it.each(['/', '/status', '/frigatex/', '/storefiles', '/api/v1/system/device'])('%s is no app', (path) => {
    expect(appOf(path)).toBeNull()
  })
})

describe('defaultPlace', () => {
  it('is bottom right', () => {
    expect(defaultPlace('dashboard', false)).toEqual({ side: 'right', y: 0.9, tucked: false })
    expect(defaultPlace('frigate', false)).toEqual({ side: 'right', y: 0.9, tucked: false })
  })
  it("is above Frigate's bottom bar on a narrow screen", () => {
    expect(defaultPlace('frigate', true)).toEqual({ side: 'right', y: 0.72, tucked: false })
    expect(defaultPlace('nr', true)).toEqual({ side: 'right', y: 0.9, tucked: false })
  })
})

describe('dropped', () => {
  it('settles on the nearer side at the height it was dropped', () => {
    expect(dropped(300, 400, 1000, 800)).toEqual({ side: 'left', y: 0.5, tucked: false })
    expect(dropped(700, 200, 1000, 800)).toEqual({ side: 'right', y: 0.25, tucked: false })
  })
  it('tucks when dropped within 12 px of an edge', () => {
    expect(dropped(12, 400, 1000, 800)).toEqual({ side: 'left', y: 0.5, tucked: true })
    expect(dropped(988, 400, 1000, 800)).toEqual({ side: 'right', y: 0.5, tucked: true })
    expect(dropped(13, 400, 1000, 800).tucked).toBe(false)
  })
  it('keeps the height between 0 and 1 when dropped outside the window', () => {
    expect(dropped(500, -50, 1000, 800).y).toBe(0)
    expect(dropped(500, 900, 1000, 800).y).toBe(1)
  })
})

it('calls a movement of more than 8 px a drag', () => {
  expect(isDrag(8, 0)).toBe(false)
  expect(isDrag(6, 6)).toBe(true)
})

it('keeps the button at least 8 px inside the window', () => {
  expect(topOf({ side: 'right', y: 0.5, tucked: false }, 800, 40)).toBe(380)
  expect(topOf({ side: 'right', y: 0, tucked: false }, 800, 40)).toBe(8)
  expect(topOf({ side: 'right', y: 1, tucked: false }, 800, 40)).toBe(752)
  expect(topOf({ side: 'right', y: 0.5, tucked: false }, 30, 40)).toBe(8)   // a window shorter than the button
})

describe('titled', () => {
  it.each([
    ['Live - Frigate', 'tm-01 · Live - Frigate'],
    ['', 'tm-01'],
    ['   ', 'tm-01'],
    ['tm-01', 'tm-01'],
    ['tm-01 · Live - Frigate', 'tm-01 · Live - Frigate'],
    ['tm-010 status', 'tm-01 · tm-010 status'],
  ])('%j becomes %j', (title, expected) => {
    expect(titled('tm-01', title)).toBe(expected)
  })
  it('leaves the title alone without a hostname', () => {
    expect(titled('', 'Frigate')).toBe('Frigate')
  })
})

describe('readPlaces and savePlace', () => {
  const stored = (text: string | null) => ({ getItem: () => text })
  it('reads what savePlace wrote, per app', () => {
    const data = new Map<string, string>()
    const storage = { getItem: (k: string) => data.get(k) ?? null, setItem: (k: string, v: string) => void data.set(k, v) }
    savePlace(storage, 'frigate', { side: 'left', y: 0.3, tucked: true })
    savePlace(storage, 'nr', { side: 'right', y: 0.6, tucked: false })
    expect([...data.keys()]).toEqual(['tm-home-button'])
    expect(readPlaces(storage)).toEqual({ frigate: { side: 'left', y: 0.3, tucked: true }, nr: { side: 'right', y: 0.6, tucked: false } })
  })
  it.each([null, '', 'not json', '[]', '"x"', '{"frigate": 5}', '{"frigate": {"side": "top", "y": 0.5, "tucked": false}}',
           '{"frigate": {"side": "left", "y": 7, "tucked": false}}', '{"frigate": {"side": "left", "y": 0.5}}'])(
    'drops an entry it cannot use: %j', (text) => {
      expect(readPlaces(stored(text))).toEqual({})
    })
  it('keeps the good entries beside a bad one', () => {
    const text = '{"frigate": {"side": "left", "y": 0.5, "tucked": false}, "nr": "junk", "other": {"side": "left", "y": 0.5, "tucked": false}}'
    expect(readPlaces(stored(text))).toEqual({ frigate: { side: 'left', y: 0.5, tucked: false } })   // "other" is no app
  })
  it('returns nothing, and does not throw, when storage throws or is missing', () => {
    const broken = { getItem: () => { throw new Error('denied') }, setItem: () => { throw new Error('denied') } }
    expect(readPlaces(broken)).toEqual({})
    expect(readPlaces(null)).toEqual({})
    expect(() => savePlace(broken, 'frigate', { side: 'left', y: 0.5, tucked: false })).not.toThrow()
    expect(() => savePlace(null, 'frigate', { side: 'left', y: 0.5, tucked: false })).not.toThrow()
  })
})
