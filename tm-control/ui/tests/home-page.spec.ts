// The home page's device card carries the Status page's verdict, as a link to it.
import { beforeEach, describe, expect, it } from 'vitest'
import { VIEWER, counts, report, signedIn } from './fake-api'
import { mountApp } from './mount'

const DEVICE = { hostname: 'tm-fake', serial: '0000000012345678', tm_version: '0.8.0', time: '2026-10-28T14:32:00-07:00', apps: [] }

describe('the home page', () => {
  beforeEach(() => document.body.replaceChildren())

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
})
