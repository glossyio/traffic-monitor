// After login or setup, follow ?next= only to a page on this device.
import { describe, expect, it } from 'vitest'
import { nextStep } from '../src/next'

const ORIGIN = 'http://tm.local'
const SPA_PATHS = ['/', '/account', '/users']

describe('nextStep', () => {
  it.each([
    ['//evil.example'],
    ['/\\evil.example'],
    ['/.//evil.example'],
    ['http://evil.example'],
    // Another site with a path this device would serve: the origin check alone stops these
    ['//evil.example/frigate/'],
    ['/\\evil.example/frigate/'],
    ['/.//evil.example/frigate/'],
    ['http://evil.example/frigate/'],
    ['http://evil.example/account'],
    ['https://tm.local/'],
    ['javascript:alert(1)'],
    ['/unknown-page'],
    [''],
    [undefined],
    [['/account', '/users']],
  ])('goes home for %j', (next) => {
    expect(nextStep(next, ORIGIN, SPA_PATHS)).toEqual({ route: '/' })
  })

  it('routes to a page of this app with its query', () => {
    expect(nextStep('/users?x=1', ORIGIN, SPA_PATHS)).toEqual({ route: '/users?x=1' })
  })

  it.each(['/frigate/', '/dashboard/', '/nr/', '/frigate/review?id=2'])('loads the device app %s', (next) => {
    expect(nextStep(next, ORIGIN, SPA_PATHS)).toEqual({ href: `${ORIGIN}${next}` })
  })

  it('uses the parsed address, never the text it was given', () => {
    expect(nextStep('/frigate/../users', ORIGIN, SPA_PATHS)).toEqual({ route: '/users' })
    expect(nextStep('/frigate/..//evil.example', ORIGIN, SPA_PATHS)).toEqual({ route: '/' })
  })
})
