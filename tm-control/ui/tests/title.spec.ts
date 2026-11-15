// The tab and the bar name the unit and the page: "tm-01 · Status | Traffic Monitor". The name comes with
// /setup/status, so setup, login, and the license pages carry it too. Only the page shown when the control app isn't
// answering says just "Traffic Monitor".
import { flushPromises } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { useSession } from '../src/stores/session'
import { pageTitle } from '../src/title'
import { ADMIN, THEME, VIEWER, apiError, fakeApi, session, status } from './fake-api'
import { mountApp } from './mount'

it.each([
  ['tm-01', 'Status', 'tm-01 · Status | Traffic Monitor'],
  ['tm-01', undefined, 'tm-01 | Traffic Monitor'],
  ['', 'Status', 'Traffic Monitor'],
  ['', undefined, 'Traffic Monitor'],
])('%j on %j is %j', (hostname, page, expected) => {
  expect(pageTitle(hostname, page)).toBe(expected)
})

describe('the tab and the bar', () => {
  const answers = (user: typeof ADMIN | null, name: unknown = 'tm-01') =>
    fakeApi({
      'GET /api/v1/setup/status': status(true, true, null, name),
      'GET /api/v1/auth/session': { user },
      'GET /api/v1/system/device': { hostname: 'tm-01', apps: [], theme: THEME },
      'GET /api/v1/status': apiError(500, 'x', 'x'),
    })
  const bar = (wrapper: { find: (selector: string) => { text: () => string } }) =>
    wrapper.find('.v-app-bar').text().replace(/\s+/g, ' ')
  // A page that stands alone (setup, login, the license pages) has the same line above it
  const standaloneLine = (wrapper: { find: (selector: string) => { text: () => string } }) =>
    wrapper.find('main p').text().replace(/\s+/g, ' ')

  it('name the unit and the page after login', async () => {
    answers(ADMIN)
    const { wrapper } = await mountApp('/account')
    expect(document.title).toBe('tm-01 · Account | Traffic Monitor')
    expect(bar(wrapper)).toBe('tm-01 | Traffic Monitor')
  })

  it('follow the page', async () => {
    answers(ADMIN)
    const { router } = await mountApp('/')
    expect(document.title).toBe('tm-01 · Home | Traffic Monitor')
    await router.push('/time')
    await flushPromises()
    expect(document.title).toBe('tm-01 · Date and time | Traffic Monitor')
  })

  it.each([
    ['login', '/login', status(true), null],
    ['setup', '/setup', status(false), null],
    ['the license page', '/welcome', status(true, false), ADMIN],
    ['the waiting page', '/waiting', status(true, false), VIEWER],
  ])('name the unit on %s, before anyone is in', async (_, path, setupStatus, user) => {
    fakeApi({
      'GET /api/v1/setup/status': setupStatus,
      'GET /api/v1/auth/session': session(setupStatus.claimed, user, setupStatus.eula.accepted),
      'GET /api/v1/setup/eula': { version: '1', markdown: '# Terms' },
    })
    const { wrapper, router } = await mountApp(path)
    expect(router.currentRoute.value.path).toBe(path)
    expect(document.title).toBe('tm-01 | Traffic Monitor')
    expect(standaloneLine(wrapper)).toBe('tm-01 | Traffic Monitor')
  })

  it('take the name from /setup/status, with no other request', async () => {
    const api = answers(ADMIN)
    await mountApp('/account')
    expect(api.sent.map((r) => r.path)).not.toContain('/api/v1/system/device')
  })

  it('say only "Traffic Monitor" when the answer has no usable name', async () => {
    answers(ADMIN, 42)
    const { wrapper } = await mountApp('/account')
    expect(useSession().hostname).toBe('')
    expect(document.title).toBe('Traffic Monitor')
    expect(bar(wrapper)).toBe('Traffic Monitor')
  })

  it('say only "Traffic Monitor" when the control app is not answering', async () => {
    fakeApi({
      'GET /api/v1/setup/status': apiError(502, 'x', 'x'),
      'GET /api/v1/auth/session': apiError(502, 'x', 'x'),
    })
    const { wrapper } = await mountApp('/login')
    expect(wrapper.text()).toContain("The control app isn't answering")
    expect(document.title).toBe('Traffic Monitor')
    expect(standaloneLine(wrapper)).toBe('Traffic Monitor')
  })

  it('keep the name when the session ends, for the login page that follows', async () => {
    answers(ADMIN)
    await mountApp('/account')
    useSession().sessionEnded()
    expect(useSession().hostname).toBe('tm-01')
  })
})
