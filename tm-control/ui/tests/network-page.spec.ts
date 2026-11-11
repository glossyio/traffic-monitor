// The Network page: this device's names, links, and internet, and the hotspot read-only.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ADMIN, NETWORK_STATE, VIEWER, apiError, json, networkState, signedIn } from './fake-api'
import { click, mountApp } from './mount'

const NETWORK = 'GET /api/v1/network'

const JOINED = {
  ...NETWORK_STATE.wifi!,
  addresses: ['192.168.1.60'],
  gateway: '192.168.1.1',
  dns: ['192.168.1.1', '9.9.9.9'],
  mode: 'network' as const,
  network: 'HomeNet',
  signal: 72,
}

function copyButtons(wrapper: { findAll: (selector: string) => { attributes: (name: string) => string | undefined }[] }) {
  return wrapper.findAll('button[aria-label^="Copy "]').map((b) => b.attributes('aria-label'))
}

describe('the Network page', () => {
  beforeEach(() => document.body.replaceChildren())
  afterEach(() => {
    vi.restoreAllMocks()
    vi.useRealTimers()
    Reflect.deleteProperty(document, 'execCommand')
  })

  it('shows this device: its names, each link with its MAC and addresses, and the internet line', async () => {
    signedIn(VIEWER, { [NETWORK]: NETWORK_STATE })
    const { wrapper } = await mountApp('/network')
    expect(wrapper.findAll('h2').map((h) => h.text().trim())).toEqual(['This device', 'Hotspot'])
    const text = wrapper.text()
    for (const part of [
      'tm-ab12',
      'tm-ab12.local',
      'Ethernet',
      'Connected',
      '2C:CF:67:00:AB:11',
      '192.168.1.57',
      '192.168.1.1',
      '1.1.1.1',
      '2C:CF:67:00:AB:12',
      'Internet',
      'Reachable',
    ]) {
      expect(text).toContain(part)
    }
    expect(copyButtons(wrapper)).toEqual(
      expect.arrayContaining([
        'Copy name',
        'Copy local name',
        'Copy Ethernet MAC address',
        'Copy Ethernet IP address',
        'Copy Ethernet gateway',
        'Copy Ethernet DNS server',
        'Copy Wi-Fi MAC address',
        'Copy Wi-Fi IP address',
        'Copy hotspot name',
      ]),
    )
  })

  it('says "On its hotspot (TM-AB12)" with the hotspot address when the radio runs the hotspot', async () => {
    signedIn(VIEWER, { [NETWORK]: NETWORK_STATE })
    const { wrapper } = await mountApp('/network')
    expect(wrapper.text()).toContain('On its hotspot (TM-AB12)')
    expect(wrapper.text()).toContain('10.42.0.1')
  })

  it('shows the joined network with its signal, gateway, and DNS servers', async () => {
    signedIn(VIEWER, { [NETWORK]: networkState({ wifi: JOINED }) })
    const { wrapper } = await mountApp('/network')
    const text = wrapper.text()
    for (const part of ['HomeNet, signal 72%', '192.168.1.60', '9.9.9.9']) expect(text).toContain(part)
    expect(text).not.toContain('On its hotspot')
    expect(copyButtons(wrapper)).toEqual(expect.arrayContaining(['Copy Wi-Fi gateway', 'Copy Wi-Fi DNS server']))
  })

  it('leaves Ethernet out on a unit without it, and says "No built-in Wi-Fi radio" without one', async () => {
    signedIn(VIEWER, { [NETWORK]: networkState({ ethernet: null }) })
    let { wrapper } = await mountApp('/network')
    expect(wrapper.text()).not.toContain('Ethernet')
    expect(wrapper.text()).not.toContain('No built-in Wi-Fi radio')

    document.body.replaceChildren()
    signedIn(VIEWER, { [NETWORK]: networkState({ wifi: null, hotspot: null }) })
    ;({ wrapper } = await mountApp('/network'))
    expect(wrapper.text()).toContain('No built-in Wi-Fi radio')
    expect(wrapper.text()).toContain('Ethernet')
  })

  it('copies a MAC address when its Copy button is tapped', async () => {
    signedIn(VIEWER, { [NETWORK]: NETWORK_STATE })
    const copied: string[] = []
    Object.defineProperty(document, 'execCommand', {
      value: vi.fn((command: string) => {
        const area = document.activeElement as HTMLTextAreaElement
        if (command === 'copy') copied.push(area.value.slice(area.selectionStart, area.selectionEnd))
        return true
      }),
      configurable: true,
    })
    vi.spyOn(HTMLTextAreaElement.prototype, 'select').mockImplementation(() => {})
    const { wrapper } = await mountApp('/network')
    const copy = wrapper.find('button[aria-label="Copy Ethernet MAC address"]')
    await copy.trigger('click')
    await vi.waitFor(() => expect(copied).toEqual(['2C:CF:67:00:AB:11']))
  })

  it('says it could not copy, and shows nothing wrong when the browser agrees', async () => {
    signedIn(VIEWER, { [NETWORK]: NETWORK_STATE })
    Object.defineProperty(document, 'execCommand', { value: vi.fn(() => false), configurable: true })
    const { wrapper } = await mountApp('/network')
    expect(wrapper.text()).not.toContain('Select the text to copy it.')
    await wrapper.find('button[aria-label="Copy Ethernet MAC address"]').trigger('click')
    await vi.waitFor(() => expect(wrapper.text()).toContain('Select the text to copy it.'))
  })

  it('shows a viewer the hotspot read-only, with no password row and no controls', async () => {
    signedIn(VIEWER, { [NETWORK]: NETWORK_STATE })
    const { wrapper } = await mountApp('/network')
    const text = wrapper.text()
    for (const part of ['TM-AB12', 'Name hidden', 'http://10.42.0.1/', 'http://tm-ab12.local/']) {
      expect(text).toContain(part)
    }
    expect(text).toContain('An administrator can change the hotspot here.')
    expect(text).not.toMatch(/password/i)
    const labels = wrapper.findAll('button').map((b) => b.attributes('aria-label') ?? b.text().trim())
    expect(labels.filter((label) => !label.startsWith('Copy '))).toEqual([])
    expect(wrapper.findAll('input')).toEqual([])
  })

  it('gives an admin the hotspot controls where a viewer has the read-only facts', async () => {
    signedIn(ADMIN, { [NETWORK]: NETWORK_STATE })
    const { wrapper } = await mountApp('/network')
    expect(wrapper.text()).toContain('Hotspot on')
    expect(wrapper.text()).toContain('Hide the name')
    expect(wrapper.text()).not.toContain('An administrator can change the hotspot here.')
    expect(wrapper.text()).not.toMatch(/Name hidden\s/)
  })

  it("warns that the network state couldn't be read when NetworkManager didn't answer", async () => {
    const unread = networkState({ readable: false, ethernet: null, wifi: null, internet: 'unknown', hotspot: null })
    signedIn(VIEWER, { [NETWORK]: unread })
    const { wrapper } = await mountApp('/network')
    expect(wrapper.text()).toContain("The network state couldn't be read")
    expect(wrapper.text()).toContain('tm-ab12.local') // the names are still true
    expect(wrapper.text()).not.toContain('No built-in Wi-Fi radio')
    expect(wrapper.text()).not.toContain('Internet')
    expect(wrapper.text()).not.toContain("hotspot isn't set up")
  })

  it('offers Try again when the page fails to load', async () => {
    let loads = 0
    signedIn(VIEWER, {
      [NETWORK]: () => {
        loads += 1
        return loads === 1 ? apiError(500, 'error', 'The device answered with an error.') : json(200, NETWORK_STATE)
      },
    })
    const { wrapper } = await mountApp('/network')
    expect(wrapper.text()).toContain('The device answered with an error.')
    expect(wrapper.text()).not.toContain('This device')
    await click(wrapper, 'Try again')
    expect(wrapper.text()).toContain('This device')
    expect(wrapper.text()).not.toContain('The device answered with an error.')
  })

  it("says the hotspot isn't set up on a unit without one", async () => {
    signedIn(VIEWER, { [NETWORK]: networkState({ hotspot: null }) })
    const { wrapper } = await mountApp('/network')
    expect(wrapper.text()).toContain("The hotspot isn't set up on this unit.")
  })
})
