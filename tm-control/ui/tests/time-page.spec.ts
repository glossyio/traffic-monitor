// The Date and time page: the device's clock beside this browser's, and for admins setting the time, the time zone,
// and NTP.
import { flushPromises, type VueWrapper } from '@vue/test-utils'
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import { ADMIN, PHONE_NOW, TIMEZONES, TIME_STATE, VIEWER, apiError, json, signedIn, timeResult } from './fake-api'
import { click, field, mountApp } from './mount'

const TIME = '/api/v1/time'

function admin(answers: Record<string, unknown> = {}) {
  return signedIn(ADMIN, { [`GET ${TIME}`]: TIME_STATE, [`GET ${TIME}/timezones`]: TIMEZONES, ...answers })
}

function posts(sent: { method: string; path: string; body: unknown }[]) {
  return sent.filter((r) => r.method === 'POST' && r.path === TIME).map((r) => r.body)
}

function buttonTexts(wrapper: VueWrapper) {
  return wrapper.findAll('button').map((b) => b.text().trim())
}

describe('the Date and time page', () => {
  const zone = process.env.TZ
  // This browser, for these tests, is in Los Angeles: 21:35:12 UTC is 14:35:12 there
  beforeAll(() => {
    process.env.TZ = 'America/Los_Angeles'
  })
  afterAll(() => {
    process.env.TZ = zone
  })
  beforeEach(() => {
    document.body.replaceChildren()
    vi.useFakeTimers({ now: PHONE_NOW })
  })
  afterEach(() => vi.useRealTimers())

  it('shows both clocks, ticking', async () => {
    admin()
    const { wrapper } = await mountApp('/time')
    expect(wrapper.text()).toContain('14:32:12') // the device
    expect(wrapper.text()).toContain('14:35:12') // this browser
    await vi.advanceTimersByTimeAsync(2_000)
    expect(wrapper.text()).toContain('14:32:14')
    expect(wrapper.text()).toContain('14:35:14')
  })

  it('says how far the device is behind this browser', async () => {
    admin()
    const { wrapper } = await mountApp('/time')
    expect(wrapper.text()).toContain('The device is 3 minutes behind this browser.')
  })

  it('says when the device and this browser agree', async () => {
    admin({ [`GET ${TIME}`]: { ...TIME_STATE, device_time: '2026-10-28T14:35:10-07:00' } })
    const { wrapper } = await mountApp('/time')
    expect(wrapper.text()).toContain('The device and this browser agree.')
  })

  it("says when the device's time zone differs from this browser's", async () => {
    admin({ [`GET ${TIME}`]: { ...TIME_STATE, device_time: '2026-10-28T21:35:12+00:00', timezone: 'Etc/UTC' } })
    const { wrapper } = await mountApp('/time')
    expect(wrapper.text()).toContain("The device's time zone differs from this browser's.")
  })

  it('shows a viewer the clocks and the time zone, with nothing to change', async () => {
    const api = signedIn(VIEWER, { [`GET ${TIME}`]: TIME_STATE })
    const { wrapper } = await mountApp('/time')
    expect(wrapper.text()).toContain('14:32:12')
    expect(wrapper.text()).toContain('The device is 3 minutes behind this browser.')
    expect(wrapper.text()).toContain('America/Los_Angeles')
    expect(wrapper.text()).toContain('The device has no time source right now, so its clock runs on its own.')
    expect(wrapper.text()).toContain('An administrator can set the time and time zone here.')
    expect(buttonTexts(wrapper)).toEqual([])
    expect(wrapper.find('input').exists()).toBe(false) // no time zone picker, no NTP switch
    expect(api.sent.some((r) => r.path === `${TIME}/timezones`)).toBe(false)
  })

  it("sets the time from this browser's clock and time zone", async () => {
    const api = admin({ [`POST ${TIME}`]: timeResult({ device_time: '2026-10-28T14:35:12-07:00' }) })
    const { wrapper } = await mountApp('/time')
    await click(wrapper, 'Set from this browser')
    expect(posts(api.sent)).toEqual([{ time: '2026-10-28T21:35:12.000Z', timezone: 'America/Los_Angeles' }])
    expect(wrapper.text()).toContain('Time set from this browser.')
    expect(wrapper.text()).not.toContain('restarting')
    expect(wrapper.text()).toContain('The device and this browser agree.')
  })

  it('says when the device kept the time it had from the internet, and only the time zone changed', async () => {
    admin({
      [`GET ${TIME}`]: { ...TIME_STATE, timezone: 'Etc/UTC', device_time: '2026-10-28T21:35:12+00:00' },
      [`POST ${TIME}`]: timeResult({
        device_time: '2026-10-28T14:35:12-07:00',
        time_kept_from_ntp: true,
        restarting: ['traffic-monitor.service', 'revproxy.service'],
      }),
    })
    const { wrapper } = await mountApp('/time')
    await click(wrapper, 'Set from this browser')
    expect(wrapper.text()).toContain(
      'The device already keeps time from the internet, so only the time zone changed. Frigate and Node-RED are restarting.',
    )
  })

  it('says when nothing changed because the device already had the time from the internet and this zone', async () => {
    admin({ [`POST ${TIME}`]: timeResult({ time_kept_from_ntp: true }) })
    const { wrapper } = await mountApp('/time')
    await click(wrapper, 'Set from this browser')
    expect(wrapper.text()).toContain(
      "The device already keeps time from the internet and uses this browser's time zone, so nothing changed.",
    )
  })

  it("sets the time when the device doesn't know this browser's time zone, and asks for one from the list", async () => {
    admin({ [`POST ${TIME}`]: timeResult({ timezone_unknown: true }) })
    const { wrapper } = await mountApp('/time')
    await click(wrapper, 'Set from this browser')
    expect(wrapper.text()).toContain(
      "Time set from this browser. The device doesn't know this browser's time zone (America/Los_Angeles), so pick one below.",
    )
    expect(wrapper.text()).not.toContain('restarting')
  })

  it("says the time didn't change when the device keeps time from the internet and doesn't know this browser's zone", async () => {
    admin({ [`POST ${TIME}`]: timeResult({ time_kept_from_ntp: true, timezone_unknown: true }) })
    const { wrapper } = await mountApp('/time')
    await click(wrapper, 'Set from this browser')
    expect(wrapper.text()).toContain(
      "The device already keeps time from the internet, so its time didn't change. The device doesn't know this " +
        "browser's time zone (America/Los_Angeles), so pick one below.",
    )
  })

  it('says when internet time was left off so that the time stays set', async () => {
    admin({
      [`POST ${TIME}`]: timeResult({
        device_time: '2026-10-28T14:35:12-07:00',
        ntp: { enabled: false, synchronized: false, available: true },
        ntp_left_off: true,
      }),
    })
    const { wrapper } = await mountApp('/time')
    await click(wrapper, 'Set from this browser')
    expect(wrapper.text()).toContain(
      "Time set from this browser. Internet time is now off, because turning it back on put the device's own, " +
        'wrong time back. Turn on Keep time from the internet once the device is online.',
    )
  })

  it("shows the API's message when the time couldn't be set", async () => {
    admin({ [`POST ${TIME}`]: apiError(500, 'internal', "The time couldn't be set.") })
    const { wrapper } = await mountApp('/time')
    await click(wrapper, 'Set from this browser')
    expect(wrapper.text()).toContain("The time couldn't be set.")
  })

  it('saves a time zone chosen from the list, sending only the zone', async () => {
    const api = admin({
      [`POST ${TIME}`]: () =>
        json(200, timeResult({ timezone: 'Europe/Berlin', restarting: ['traffic-monitor.service', 'revproxy.service'] })),
    })
    const { wrapper } = await mountApp('/time')
    await wrapper.findComponent({ name: 'VAutocomplete' }).setValue('Europe/Berlin')
    await click(wrapper, 'Save time zone')
    expect(posts(api.sent)).toEqual([{ timezone: 'Europe/Berlin' }])
    expect(wrapper.text()).toContain('Time zone saved. Frigate and Node-RED are restarting.')
  })

  it("clears an earlier change's result once a newer change could make it untrue", async () => {
    let answer = timeResult({ time_kept_from_ntp: true, restarting: ['traffic-monitor.service'] })
    admin({ [`POST ${TIME}`]: () => json(200, answer) })
    const { wrapper } = await mountApp('/time')
    await click(wrapper, 'Set from this browser')
    expect(wrapper.text()).toContain('The device already keeps time from the internet')

    answer = timeResult({ ntp: { enabled: false, synchronized: false, available: true } })
    await wrapper.findComponent({ name: 'VSwitch' }).setValue(false)
    await vi.runOnlyPendingTimersAsync()
    expect(wrapper.text()).not.toContain('The device already keeps time from the internet')
  })

  it('selects the zone in the picker when it gets focus, so typing replaces it', async () => {
    admin()
    const { wrapper } = await mountApp('/time')
    const input = field(wrapper, 'Time zone').element
    input.focus()
    await flushPromises()
    expect([input.selectionStart, input.selectionEnd]).toEqual([0, 'America/Los_Angeles'.length])
  })

  it('turns keeping time from the internet off', async () => {
    const api = admin({
      [`POST ${TIME}`]: timeResult({ ntp: { enabled: false, synchronized: false, available: true } }),
    })
    const { wrapper } = await mountApp('/time')
    expect(wrapper.text()).toContain('Keep time from the internet')
    await wrapper.findComponent({ name: 'VSwitch' }).setValue(false)
    await vi.runOnlyPendingTimersAsync()
    expect(posts(api.sent)).toEqual([{ ntp: false }])
    expect(wrapper.text()).toContain("The device doesn't check the time on the internet, so its clock runs on its own.")
  })
})
