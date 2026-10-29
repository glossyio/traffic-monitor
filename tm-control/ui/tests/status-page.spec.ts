// The Status page: the verdict, the checks refreshing while the page is visible, and an admin's restart and re-scan.
import { flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  ADMIN,
  HARDWARE_RESCAN,
  RESCAN,
  SERVICES,
  VIEWER,
  apiError,
  type Check,
  counts,
  json,
  report,
  signedIn,
} from './fake-api'
import { button, click, clickInDialog, dialogText, mountApp } from './mount'

const STATUS = '/api/v1/status'

function statusCalls(sent: { method: string; path: string }[]) {
  return sent.filter((r) => r.method === 'GET' && r.path === STATUS).length
}

// Hide or show the page, as switching tabs or locking the phone does. jsdom's document.visibilityState is a getter
// on Document.prototype; an own property on `document` takes its place until it's deleted.
function setVisibility(state: DocumentVisibilityState) {
  Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => state })
  document.dispatchEvent(new Event('visibilitychange'))
}

describe('the Status page', () => {
  beforeEach(() => document.body.replaceChildren())
  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
    Reflect.deleteProperty(document, 'visibilityState')
  })

  it.each([
    [[5, 1, 0, 0], 'Working, with 1 thing to look at'],
    [[5, 2, 0, 0], 'Working, with 2 things to look at'],
    [[5, 1, 1, 1], '1 problem needs attention'],
    [[5, 0, 3, 0], '3 problems need attention'],
    [[5, 0, 0, 2], "Some checks couldn't run"],
    [[5, 0, 0, 0], 'Everything is working'],
  ])('sums up %j as "%s"', async ([ok, warn, error, unknown], verdict) => {
    signedIn(VIEWER, { [`GET ${STATUS}`]: report([counts(ok, warn, error, unknown)]) })
    const { wrapper } = await mountApp('/status')
    expect(wrapper.find('[role="status"]').text()).toBe(verdict)
  })

  it('checks again every 10 seconds while the page is visible', async () => {
    vi.useFakeTimers()
    const api = signedIn(VIEWER, { [`GET ${STATUS}`]: report([SERVICES]) })
    await mountApp('/status')
    const first = statusCalls(api.sent)
    await vi.advanceTimersByTimeAsync(10_000)
    expect(statusCalls(api.sent)).toBe(first + 1)
  })

  it("doesn't check while the page is hidden, and checks as soon as it's visible again", async () => {
    vi.useFakeTimers()
    const api = signedIn(VIEWER, { [`GET ${STATUS}`]: report([SERVICES]) })
    await mountApp('/status')
    setVisibility('hidden')
    const calls = statusCalls(api.sent)
    await vi.advanceTimersByTimeAsync(60_000)
    expect(statusCalls(api.sent)).toBe(calls)

    setVisibility('visible')
    await flushPromises()
    expect(statusCalls(api.sent)).toBe(calls + 1)
  })

  it('stops checking once the page is left', async () => {
    vi.useFakeTimers()
    const api = signedIn(VIEWER, { [`GET ${STATUS}`]: report([SERVICES]) })
    const { wrapper } = await mountApp('/status')
    wrapper.unmount()
    const calls = statusCalls(api.sent)
    await vi.advanceTimersByTimeAsync(60_000)
    expect(statusCalls(api.sent)).toBe(calls)
  })

  it('says how long ago the device was checked', async () => {
    vi.useFakeTimers()
    let answer: Response | object = report([SERVICES])
    signedIn(VIEWER, { [`GET ${STATUS}`]: () => (answer instanceof Response ? answer : json(200, answer)) })
    const { wrapper } = await mountApp('/status')
    expect(wrapper.text()).toContain('Checked just now')
    answer = apiError(500, 'internal', 'The device answered with an error (HTTP 500).')
    await vi.advanceTimersByTimeAsync(25_000)
    expect(wrapper.text()).toContain('Checked 20 seconds ago')
  })

  it("keeps the last checks when the device doesn't answer, and says so", async () => {
    vi.useFakeTimers()
    let down = false
    signedIn(VIEWER, {
      [`GET ${STATUS}`]: () => (down ? Promise.reject(new TypeError('Failed to fetch')) : json(200, report([SERVICES]))),
    })
    const { wrapper } = await mountApp('/status')
    down = true
    await vi.advanceTimersByTimeAsync(10_000)
    expect(wrapper.text()).toContain("The device didn't answer.")
    expect(wrapper.text()).toContain('Stopped after a failure.')
  })

  it('restarts a unit only after the admin confirms, from the button the API named', async () => {
    const api = signedIn(ADMIN, {
      [`GET ${STATUS}`]: report([SERVICES]),
      'POST /api/v1/services/frigate.service/restart': json(202, { unit: 'frigate.service' }),
    })
    const { wrapper } = await mountApp('/status')
    await click(wrapper, 'Restart Frigate')
    expect(dialogText()).toContain('Restart Frigate?')
    expect(dialogText()).toContain('The camera view stops for about a minute while Frigate restarts.')
    expect(api.sent.some((r) => r.method === 'POST')).toBe(false)

    await clickInDialog('Restart Frigate')
    expect(api.sent.filter((r) => r.method === 'POST').map((r) => r.path)).toEqual([
      '/api/v1/services/frigate.service/restart',
    ])
    expect(wrapper.text()).toContain('Frigate is restarting.')
  })

  it("forgets a restart's result once the check no longer offers the restart", async () => {
    vi.useFakeTimers()
    let frigate: Check = SERVICES.checks[1]
    signedIn(ADMIN, {
      [`GET ${STATUS}`]: () => json(200, report([{ ...SERVICES, checks: [SERVICES.checks[0], frigate] }])),
      'POST /api/v1/services/frigate.service/restart': json(202, { unit: 'frigate.service' }),
    })
    const { wrapper } = await mountApp('/status')
    await click(wrapper, 'Restart Frigate')
    await clickInDialog('Restart Frigate')
    frigate = { ...SERVICES.checks[1], status: 'ok', detail: 'Running since 14:40.', fix: null }
    await vi.advanceTimersByTimeAsync(10_000)
    frigate = SERVICES.checks[1] // it fails again later
    await vi.advanceTimersByTimeAsync(10_000)
    expect(wrapper.text()).toContain('Stopped after a failure.')
    expect(wrapper.text()).not.toContain('Frigate is restarting.')
  })

  it("shows the API's message under the button when a restart is refused", async () => {
    signedIn(ADMIN, {
      [`GET ${STATUS}`]: report([SERVICES]),
      'POST /api/v1/services/frigate.service/restart': apiError(404, 'not_found', 'There is no such service to restart.'),
    })
    const { wrapper } = await mountApp('/status')
    await click(wrapper, 'Restart Frigate')
    await clickInDialog('Restart Frigate')
    expect(wrapper.text()).toContain('There is no such service to restart.')
  })

  it('re-scans the hardware and shows the new checks in place', async () => {
    const found: Check = { ...HARDWARE_RESCAN.checks[0], status: 'ok', detail: 'Found it.', fix: null }
    const fresh = report([{ ...HARDWARE_RESCAN, checks: [found] }])
    const api = signedIn(ADMIN, {
      [`GET ${STATUS}`]: report([HARDWARE_RESCAN]),
      'POST /api/v1/status/rescan': fresh,
    })
    const { wrapper } = await mountApp('/status')
    expect(button(wrapper, RESCAN.text)).toBeTruthy()
    await click(wrapper, RESCAN.text)
    expect(api.sent.filter((r) => r.method === 'POST').map((r) => r.path)).toEqual(['/api/v1/status/rescan'])
    expect(wrapper.text()).toContain('Found it.')
    expect(wrapper.find('[role="status"]').text()).toBe('Everything is working')
  })

  it('shows a viewer the checks with no buttons but Refresh', async () => {
    signedIn(VIEWER, { [`GET ${STATUS}`]: report([SERVICES, HARDWARE_RESCAN]) })
    const { wrapper } = await mountApp('/status')
    expect(wrapper.text()).toContain('Stopped after a failure.')
    expect(wrapper.findAll('button').map((b) => b.text().trim())).toEqual(['Refresh'])
  })
})
