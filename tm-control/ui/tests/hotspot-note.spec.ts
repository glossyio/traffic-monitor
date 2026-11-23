// The login and setup pages say when the phone is on the unit's own hotspot.
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fakeApi, json, session, status } from './fake-api'
import { click, mountApp } from './mount'

const HOTSPOT = { local_name: 'tm-fake.local' }
const ADDRESS = 'http://tm-fake.local/'
const INTRO = "You're on this unit's hotspot. It has no internet. To save downloads, open the unit in a browser:"
// The address comes first: keeping the network closes the phone's sign-in window, and the note with it.
const STEPS = [
  `Copy this address: ${ADDRESS}`,
  "Keep this network. On Android, open this window's menu and choose Use this network as is. On an iPhone, tap Cancel, then Use Without Internet.",
  'Open the address in a browser. On Android 17, allow Nearby devices for the browser.',
]

function device(claimed: boolean, hotspot: typeof HOTSPOT | null) {
  return fakeApi({
    'GET /api/v1/setup/status': () => json(200, status(claimed, claimed, hotspot)),
    'GET /api/v1/auth/session': () => json(200, session(claimed, null)),
    'GET /api/v1/setup/eula': { version: '1', markdown: '# License\n\nPlaceholder text.' },
  })
}

describe('the hotspot note', () => {
  beforeEach(() => document.body.replaceChildren())

  it("the login page shows the hotspot note: the unit's .local address, then the steps to a browser", async () => {
    device(true, HOTSPOT)
    const { wrapper } = await mountApp('/login')
    const note = wrapper.find('.v-alert')
    expect(note.text().startsWith(INTRO)).toBe(true)
    expect(note.findAll('ol li').map((step) => step.text())).toEqual(STEPS)
  })

  it('the setup page shows it on every step', async () => {
    device(false, HOTSPOT)
    const { wrapper } = await mountApp('/setup')
    expect(wrapper.text()).toContain(INTRO)
    await click(wrapper, 'Start setup')
    expect(wrapper.text()).toContain(INTRO)
    await wrapper.find('input[type="checkbox"]').setValue(true)
    await click(wrapper, 'Continue')
    expect(wrapper.text()).toContain(INTRO)
  })

  it('neither page shows it off the hotspot', async () => {
    device(true, null)
    const login = await mountApp('/login')
    expect(login.wrapper.text()).not.toContain('hotspot')
    device(false, null)
    const setup = await mountApp('/setup')
    expect(setup.wrapper.text()).not.toContain('hotspot')
  })

  it('the address in the note is not a link: in a sign-in window a link would open in that window', async () => {
    device(true, HOTSPOT)
    const { wrapper } = await mountApp('/login')
    expect(wrapper.find('.v-alert').text()).toContain(ADDRESS)
    expect(wrapper.find('.v-alert a').exists()).toBe(false)
  })

  it('Copy beside the address copies it, over plain HTTP too', async () => {
    const copied: string[] = []
    Object.defineProperty(document, 'execCommand', {
      value: vi.fn((command: string) => {
        const area = document.activeElement as HTMLTextAreaElement
        if (command === 'copy') copied.push(area.value.slice(area.selectionStart, area.selectionEnd))
        return true
      }),
      configurable: true,
    })
    device(true, HOTSPOT)
    const { wrapper } = await mountApp('/login')
    await wrapper.find('.v-alert ol li button[aria-label="Copy the address"]').trigger('click')
    await vi.waitFor(() => expect(copied).toEqual([ADDRESS]))
    Reflect.deleteProperty(document, 'execCommand')
  })
})
