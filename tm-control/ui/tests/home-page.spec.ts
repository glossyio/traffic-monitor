// The home page's device card carries the Status page's verdict, as a link to it.
import { beforeEach, describe, expect, it } from 'vitest'
import { appHref } from '../src/modules/home/apps'
import { ADMIN, VIEWER, counts, report, signedIn } from './fake-api'
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

  it('links an app on its own port to that port, on the name the browser used', async () => {
    const apps = [
      { id: 'frigate', path: '/frigate/', title: 'Frigate', admin_only: false, port: null },
      { id: 'cockpit', path: '/', title: 'Cockpit', admin_only: true, port: 9090 },
    ]
    signedIn(ADMIN, { 'GET /api/v1/system/device': { ...DEVICE, apps } })
    const { wrapper } = await mountApp('/')
    expect(wrapper.find('main a[href="/frigate/"]').exists()).toBe(true)
    expect(wrapper.find(`main a[href="http://${window.location.hostname}:9090/"]`).exists()).toBe(true)
  })

  it('builds a port link from any kind of hostname', () => {
    expect(appHref({ path: '/frigate/', port: null }, 'tm.local')).toBe('/frigate/')
    expect(appHref({ path: '/', port: 9090 }, 'tm.local')).toBe('http://tm.local:9090/')
    expect(appHref({ path: '/', port: 9090 }, '192.0.2.10')).toBe('http://192.0.2.10:9090/')
    expect(appHref({ path: '/', port: 9090 }, '[2001:db8::1]')).toBe('http://[2001:db8::1]:9090/')
  })

  it('links to the path when an older answer has no port', () => {
    const app = { path: '/frigate/' } as { path: string; port: number | null }
    expect(appHref(app, 'tm.local')).toBe('/frigate/')
  })

  const COCKPIT = { id: 'cockpit', path: '/', title: 'Cockpit', admin_only: true, port: 9090 }

  it('names the system account on the Cockpit tile', async () => {
    signedIn(ADMIN, { 'GET /api/v1/system/device': { ...DEVICE, system_user: 'pi', apps: [COCKPIT] } })
    const { wrapper } = await mountApp('/')
    expect(wrapper.find('main a[href$=":9090/"]').text()).toContain('Log in as pi with the system password.')
  })

  it("leaves the account's name out of the Cockpit tile when the answer has none", async () => {
    signedIn(ADMIN, { 'GET /api/v1/system/device': { ...DEVICE, system_user: null, apps: [COCKPIT] } })
    const { wrapper } = await mountApp('/')
    const tile = wrapper.find('main a[href$=":9090/"]').text()
    expect(tile).toContain('Log in with the system password.')
    expect(tile).not.toContain('Log in as')
  })
})
