// The login and setup pages say when the phone is on the unit's own hotspot.
import { beforeEach, describe, expect, it } from 'vitest'
import { fakeApi, json, session, status } from './fake-api'
import { click, mountApp } from './mount'

const HOTSPOT = { local_name: 'tm-fake.local' }
const NOTE =
  "You're on this unit's hotspot. It has no internet. On an iPhone, tap Cancel, choose Use Without Internet, then open http://tm-fake.local/ in a browser to save downloaded files."

function device(claimed: boolean, hotspot: typeof HOTSPOT | null) {
  return fakeApi({
    'GET /api/v1/setup/status': () => json(200, status(claimed, claimed, hotspot)),
    'GET /api/v1/auth/session': () => json(200, session(claimed, null)),
    'GET /api/v1/setup/eula': { version: '1', markdown: '# License\n\nPlaceholder text.' },
  })
}

describe('the hotspot note', () => {
  beforeEach(() => document.body.replaceChildren())

  it("the login page shows the hotspot note with the unit's .local name", async () => {
    device(true, HOTSPOT)
    const { wrapper } = await mountApp('/login')
    expect(wrapper.find('.v-alert').text()).toBe(NOTE)
  })

  it('the setup page shows it on every step', async () => {
    device(false, HOTSPOT)
    const { wrapper } = await mountApp('/setup')
    expect(wrapper.text()).toContain(NOTE)
    await click(wrapper, 'Start setup')
    expect(wrapper.text()).toContain(NOTE)
    await wrapper.find('input[type="checkbox"]').setValue(true)
    await click(wrapper, 'Continue')
    expect(wrapper.text()).toContain(NOTE)
  })

  it('neither page shows it off the hotspot', async () => {
    device(true, null)
    const login = await mountApp('/login')
    expect(login.wrapper.text()).not.toContain('hotspot')
    device(false, null)
    const setup = await mountApp('/setup')
    expect(setup.wrapper.text()).not.toContain('hotspot')
  })

  it('the address in the note is not a link', async () => {
    device(true, HOTSPOT)
    const { wrapper } = await mountApp('/login')
    expect(wrapper.find('.v-alert a').exists()).toBe(false)
  })
})
