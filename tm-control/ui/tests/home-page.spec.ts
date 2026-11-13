// The home page's device card carries the Status page's verdict, as a link to it.
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ADMIN, JOIN_COUNTDOWN, VIEWER, counts, joinState, json, report, signedIn } from './fake-api'
import { mountApp } from './mount'

const DEVICE = { hostname: 'tm-fake', serial: '0000000012345678', tm_version: '0.8.0', time: '2026-10-28T14:32:00-07:00', apps: [] }

describe('the home page', () => {
  beforeEach(() => {
    vi.useRealTimers()
    document.body.replaceChildren()
  })

  it("shows the device's health as a link to the Status page", async () => {
    signedIn(VIEWER, { 'GET /api/v1/system/device': DEVICE, 'GET /api/v1/status': report([counts(9, 1, 2, 0)]) })
    const { wrapper } = await mountApp('/')
    const link = wrapper.find('main a[href="/status"]')
    expect(link.text()).toBe('2 problems need attention')
  })

  it('leaves the health line out when the status can\'t be read', async () => {
    signedIn(VIEWER, { 'GET /api/v1/system/device': DEVICE })
    const { wrapper } = await mountApp('/')
    expect(wrapper.text()).toContain('tm-fake')
    expect(wrapper.find('main a[href="/status"]').exists()).toBe(false)
  })

  it('shows the banner on the home page while a join waits, with a link to the Network page', async () => {
    signedIn(ADMIN, { 'GET /api/v1/system/device': DEVICE, 'GET /api/v1/network/join': JOIN_COUNTDOWN })
    const { wrapper } = await mountApp('/')
    const alert = wrapper.find('[role="alert"]')
    expect(alert.text()).toContain('Neighbour works. The unit joins it in 3:12.')
    expect(alert.find('a[href="/network"]').text()).toBe('See it')
    const page = wrapper.find('main').html()
    expect(page.indexOf('Neighbour works')).toBeLessThan(page.indexOf('tm-fake'))
  })

  it('says how a finished join ended', async () => {
    const failed = joinState({ stage: 'failed', joined: false, reason: 'not_joined', seconds_left: null })
    signedIn(ADMIN, { 'GET /api/v1/system/device': DEVICE, 'GET /api/v1/network/join': failed })
    const { wrapper } = await mountApp('/')
    expect(wrapper.find('[role="alert"]').text()).toContain("The unit couldn't join Neighbour.")
  })

  it('shows no banner to a viewer and none without a join', async () => {
    const viewer = signedIn(VIEWER, { 'GET /api/v1/system/device': DEVICE, 'GET /api/v1/network/join': JOIN_COUNTDOWN })
    let { wrapper } = await mountApp('/')
    expect(wrapper.text()).toContain('tm-fake')
    expect(wrapper.text()).not.toContain('Neighbour')
    expect(viewer.sent.filter((r) => r.path === '/api/v1/network/join')).toEqual([])

    document.body.replaceChildren()
    signedIn(ADMIN, { 'GET /api/v1/system/device': DEVICE, 'GET /api/v1/network/join': json(200, null) })
    ;({ wrapper } = await mountApp('/'))
    expect(wrapper.text()).toContain('tm-fake')
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
  })

  it('keeps the line current: the time moves, and a later answer changes the words without a reload', async () => {
    vi.useFakeTimers()
    let answer = joinState({ seconds_left: 252 })
    signedIn(ADMIN, { 'GET /api/v1/system/device': DEVICE, 'GET /api/v1/network/join': () => json(200, answer) })
    const { wrapper } = await mountApp('/')
    expect(wrapper.find('[role="alert"]').text()).toContain('The unit joins it in 4:12.')

    await vi.advanceTimersByTimeAsync(1000)
    expect(wrapper.find('[role="alert"]').text()).toContain('The unit joins it in 4:11.')

    answer = joinState({ stage: 'joined', seconds_left: null })
    await vi.advanceTimersByTimeAsync(2000)
    const text = wrapper.find('[role="alert"]').text()
    expect(text).toContain('The unit is on Neighbour.')
    expect(text).not.toContain('joins it in')
  })

  it("asks nothing on a viewer's home page, even as time passes", async () => {
    vi.useFakeTimers()
    const viewer = signedIn(VIEWER, { 'GET /api/v1/system/device': DEVICE, 'GET /api/v1/network/join': JOIN_COUNTDOWN })
    const { wrapper } = await mountApp('/')
    await vi.advanceTimersByTimeAsync(10_000)
    expect(wrapper.text()).not.toContain('Neighbour')
    expect(viewer.sent.filter((r) => r.path === '/api/v1/network/join')).toEqual([])
  })

  it('still shows the home page when the join state cannot be read', async () => {
    signedIn(ADMIN, { 'GET /api/v1/system/device': DEVICE })
    const { wrapper } = await mountApp('/')
    expect(wrapper.text()).toContain('tm-fake')
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
  })
})
