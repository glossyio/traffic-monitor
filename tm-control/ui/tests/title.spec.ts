// The tab and the bar name the unit and the page: "tm-01 · Status | Traffic Monitor". Before login, on setup, and on
// the license pages they say only "Traffic Monitor".
import { flushPromises } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { useSession } from '../src/stores/session'
import { pageTitle } from '../src/title'
import { ADMIN, THEME, apiError, fakeApi, status } from './fake-api'
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
  const answers = (user: typeof ADMIN | null, device: Response | object = { hostname: 'tm-01', apps: [], theme: THEME }) =>
    fakeApi({
      'GET /api/v1/setup/status': status(true),
      'GET /api/v1/auth/session': { user },
      'GET /api/v1/system/device': device,
      'GET /api/v1/status': apiError(500, 'x', 'x'),
    })

  it('name the unit and the page after login', async () => {
    answers(ADMIN)
    const { wrapper } = await mountApp('/account')
    expect(document.title).toBe('tm-01 · Account | Traffic Monitor')
    expect(wrapper.find('.v-app-bar').text().replace(/\s+/g, ' ')).toBe('tm-01 | Traffic Monitor')
  })

  it('follow the page', async () => {
    answers(ADMIN)
    const { router } = await mountApp('/')
    expect(document.title).toBe('tm-01 · Home | Traffic Monitor')
    await router.push('/time')
    await flushPromises()
    expect(document.title).toBe('tm-01 · Date and time | Traffic Monitor')
  })

  it('say only "Traffic Monitor" before login', async () => {
    const api = answers(null)
    await mountApp('/login')
    expect(document.title).toBe('Traffic Monitor')
    expect(api.sent.map((r) => r.path)).not.toContain('/api/v1/system/device')
  })

  it('say only "Traffic Monitor" when the name cannot be read', async () => {
    answers(ADMIN, apiError(500, 'x', 'x'))
    const { wrapper } = await mountApp('/account')
    expect(document.title).toBe('Traffic Monitor')
    expect(wrapper.find('.v-app-bar').text()).toBe('Traffic Monitor')
  })

  it('say only "Traffic Monitor" when the answer has no usable name', async () => {
    answers(ADMIN, { hostname: 42, apps: [], theme: THEME })
    await mountApp('/account')
    expect(useSession().hostname).toBe('')
    expect(document.title).toBe('Traffic Monitor')
  })

  it('forget the name when the session ends', async () => {
    answers(ADMIN)
    await mountApp('/account')
    expect(useSession().hostname).toBe('tm-01')
    useSession().sessionEnded()
    expect(useSession().hostname).toBe('')
  })
})
