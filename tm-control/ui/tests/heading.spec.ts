// The compass rule for the Location pages, which the backend's coordinates.py holds (test_compass_point): a point is
// a way to pick and to read a heading, and nothing stores one.
import { describe, expect, it } from 'vitest'
import { POINTS, compassPoint, facing, headingChoices, pointCentre } from '../src/modules/location/heading'

describe('compassPoint', () => {
  it.each([
    [0, 'n'], [22, 'n'], [23, 'ne'], [45, 'ne'], [67, 'ne'], [68, 'e'], [90, 'e'], [112, 'e'], [113, 'se'],
    [135, 'se'], [157, 'se'], [158, 's'], [180, 's'], [202, 's'], [203, 'sw'], [225, 'sw'], [247, 'sw'],
    [248, 'w'], [270, 'w'], [292, 'w'], [293, 'nw'], [315, 'nw'], [337, 'nw'], [338, 'n'], [359, 'n'],
  ])('puts %i degrees at %s', (heading, point) => {
    expect(compassPoint(heading)).toBe(point)
  })

  it('has every point, and each centre is its own point', () => {
    const seen = new Set(Array.from({ length: 360 }, (_, heading) => compassPoint(heading)))
    expect([...seen].sort()).toEqual([...POINTS].sort())
    expect(POINTS.map((point) => compassPoint(pointCentre(point)!))).toEqual([...POINTS])
  })
})

describe('pointCentre', () => {
  it.each([
    ['n', 0], ['ne', 45], ['e', 90], ['se', 135], ['s', 180], ['sw', 225], ['w', 270], ['nw', 315],
    [' N ', 0], ['NE', 45], [' Sw\n', 225],
  ])('gives %j the centre %i', (point, centre) => {
    expect(pointCentre(point)).toBe(centre)
  })

  it.each([[''], ['  '], ['north'], ['nne']])('gives %j nothing', (point) => {
    expect(pointCentre(point)).toBeNull()
  })
})

describe('facing', () => {
  it('reads a heading with its point', () => {
    expect(facing(40)).toBe('NE (40°)')
    expect(facing(0)).toBe('N (0°)')
    expect(facing(359)).toBe('N (359°)')
  })

  it('reads no heading as Not set', () => {
    expect(facing(null)).toBe('Not set')
  })
})

describe('headingChoices', () => {
  it('is the eight centres, N to NW, then Not set', () => {
    const choices = headingChoices(null)
    expect(choices).toHaveLength(9)
    expect(choices.map((choice) => choice.title)).toEqual(['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW', 'Not set'])
    expect(choices.map((choice) => choice.value)).toEqual([0, 45, 90, 135, 180, 225, 270, 315, null])
  })

  it('has the same nine when the current heading is a centre', () => {
    expect(headingChoices(90)).toEqual(headingChoices(null))
  })

  it('puts a measured heading first, titled by facing, so opening a pick changes nothing', () => {
    const choices = headingChoices(40)
    expect(choices).toHaveLength(10)
    expect(choices[0]).toEqual({ value: 40, title: 'NE (40°)' })
    expect(choices.slice(1)).toEqual(headingChoices(null))
  })
})
