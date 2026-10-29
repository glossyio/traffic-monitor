// How long ago something happened, and how long something lasts, in words.
import { describe, expect, it } from 'vitest'
import { ago, duration } from '../src/components/relative-time'

describe('ago', () => {
  it.each([
    [0, 'just now'],
    [19, 'just now'],
    [20, '20 seconds ago'],
    [29, '20 seconds ago'],
    [59, '50 seconds ago'],
    [60, '1 minute ago'],
    [150, '2 minutes ago'],
    [3600, '1 hour ago'],
    [5 * 3600, '5 hours ago'],
    [3 * 86400, '3 days ago'],
  ])('reads %d seconds as "%s"', (seconds, words) => {
    expect(ago(seconds)).toBe(words)
  })
})

describe('duration', () => {
  it.each([
    [1, '1 second'],
    [45, '45 seconds'],
    [90, '2 minutes'],
    [180, '3 minutes'],
    [3600, '1 hour'],
    [3 * 3600 + 20 * 60, '3 hours'],
    [2 * 86400 + 3 * 3600, '2 days'],
    [-180, '3 minutes'],
  ])('reads %d seconds as "%s"', (seconds, words) => {
    expect(duration(seconds)).toBe(words)
  })
})
