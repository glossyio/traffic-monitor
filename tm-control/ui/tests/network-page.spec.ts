// The Network page: this device's names, links, and internet, and the hotspot read-only.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { components } from '../src/api/schema'
import {
  ADMIN,
  JOIN_COUNTDOWN,
  NETWORK_STATE,
  VIEWER,
  WIFI_NETWORKS,
  apiError,
  joinState,
  json,
  networkState,
  signedIn,
} from './fake-api'
import { click, clickInDialog, dialogField, mountApp, typeInto } from './mount'

type Job = components['schemas']['Job']
type JoinState = components['schemas']['JoinState']

const NETWORK = 'GET /api/v1/network'
const WIFI = 'GET /api/v1/network/wifi'

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
    signedIn(VIEWER, { [WIFI]: WIFI_NETWORKS, [NETWORK]: NETWORK_STATE })
    const { wrapper } = await mountApp('/network')
    expect(wrapper.findAll('h2').map((h) => h.text().trim())).toEqual(['This device', 'Wi-Fi networks', 'Hotspot'])
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
    signedIn(VIEWER, { [WIFI]: WIFI_NETWORKS, [NETWORK]: NETWORK_STATE })
    const { wrapper } = await mountApp('/network')
    expect(wrapper.text()).toContain('On its hotspot (TM-AB12)')
    expect(wrapper.text()).toContain('10.42.0.1')
  })

  it('shows the joined network with its signal, gateway, and DNS servers', async () => {
    signedIn(VIEWER, { [WIFI]: WIFI_NETWORKS, [NETWORK]: networkState({ wifi: JOINED }) })
    const { wrapper } = await mountApp('/network')
    const text = wrapper.text()
    for (const part of ['HomeNet, signal 72%', '192.168.1.60', '9.9.9.9']) expect(text).toContain(part)
    expect(text).not.toContain('On its hotspot')
    expect(copyButtons(wrapper)).toEqual(expect.arrayContaining(['Copy Wi-Fi gateway', 'Copy Wi-Fi DNS server']))
  })

  it('leaves Ethernet out on a unit without it, and says "No built-in Wi-Fi radio" without one', async () => {
    signedIn(VIEWER, { [WIFI]: WIFI_NETWORKS, [NETWORK]: networkState({ ethernet: null }) })
    let { wrapper } = await mountApp('/network')
    expect(wrapper.text()).not.toContain('Ethernet')
    expect(wrapper.text()).not.toContain('No built-in Wi-Fi radio')

    document.body.replaceChildren()
    signedIn(VIEWER, { [WIFI]: WIFI_NETWORKS, [NETWORK]: networkState({ wifi: null, hotspot: null }) })
    ;({ wrapper } = await mountApp('/network'))
    expect(wrapper.text()).toContain('No built-in Wi-Fi radio')
    expect(wrapper.text()).toContain('Ethernet')
  })

  it('copies a MAC address when its Copy button is tapped', async () => {
    signedIn(VIEWER, { [WIFI]: WIFI_NETWORKS, [NETWORK]: NETWORK_STATE })
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
    signedIn(VIEWER, { [WIFI]: WIFI_NETWORKS, [NETWORK]: NETWORK_STATE })
    Object.defineProperty(document, 'execCommand', { value: vi.fn(() => false), configurable: true })
    const { wrapper } = await mountApp('/network')
    expect(wrapper.text()).not.toContain('Select the text to copy it.')
    await wrapper.find('button[aria-label="Copy Ethernet MAC address"]').trigger('click')
    await vi.waitFor(() => expect(wrapper.text()).toContain('Select the text to copy it.'))
  })

  it('shows a viewer the hotspot read-only, with no password row and no controls', async () => {
    signedIn(VIEWER, { [WIFI]: WIFI_NETWORKS, [NETWORK]: NETWORK_STATE })
    const { wrapper } = await mountApp('/network')
    const section = wrapper.findAll('section').find((s) => s.find('h2').text() === 'Hotspot')!
    const text = section.text()
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
    signedIn(ADMIN, { [WIFI]: WIFI_NETWORKS, [NETWORK]: NETWORK_STATE })
    const { wrapper } = await mountApp('/network')
    expect(wrapper.text()).toContain('Hotspot on')
    expect(wrapper.text()).toContain('Hide the name')
    expect(wrapper.text()).not.toContain('An administrator can change the hotspot here.')
    expect(wrapper.text()).not.toMatch(/Name hidden\s/)
  })

  it("warns that the network state couldn't be read when NetworkManager didn't answer", async () => {
    const unread = networkState({ readable: false, ethernet: null, wifi: null, internet: 'unknown', hotspot: null })
    signedIn(VIEWER, { [WIFI]: WIFI_NETWORKS, [NETWORK]: unread })
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

  it('puts Wi-Fi networks between This device and Hotspot', async () => {
    signedIn(VIEWER, { [WIFI]: WIFI_NETWORKS, [NETWORK]: NETWORK_STATE })
    const { wrapper } = await mountApp('/network')
    const sections = wrapper.findAll('section')
    expect(sections.map((s) => s.find('h2').text())).toEqual(['This device', 'Wi-Fi networks', 'Hotspot'])
    expect(sections[1].text()).toContain('HomeNet')
  })

  it('leaves Wi-Fi networks out when the network state could not be read', async () => {
    const unread = networkState({ readable: false, ethernet: null, wifi: null, internet: 'unknown', hotspot: null })
    signedIn(VIEWER, { [WIFI]: WIFI_NETWORKS, [NETWORK]: unread })
    const { wrapper } = await mountApp('/network')
    expect(wrapper.text()).not.toContain('Wi-Fi networks')
  })

  it('says why the networks are missing, with Try again, when only they fail to load', async () => {
    let loads = 0
    signedIn(VIEWER, {
      [NETWORK]: NETWORK_STATE,
      [WIFI]: () => {
        loads += 1
        return loads === 1 ? apiError(500, 'error', 'The device answered with an error.') : json(200, WIFI_NETWORKS)
      },
    })
    const { wrapper } = await mountApp('/network')
    expect(wrapper.text()).toContain('This device')
    expect(wrapper.text()).toContain('The device answered with an error.')
    await click(wrapper, 'Try again')
    expect(wrapper.text()).toContain('HomeNet')
    expect(wrapper.text()).not.toContain('The device answered with an error.')
  })

  it("says the hotspot isn't set up on a unit without one", async () => {
    signedIn(VIEWER, { [WIFI]: WIFI_NETWORKS, [NETWORK]: networkState({ hotspot: null }) })
    const { wrapper } = await mountApp('/network')
    expect(wrapper.text()).toContain("The hotspot isn't set up on this unit.")
  })
})

const JOIN = 'GET /api/v1/network/join'
const START = 'POST /api/v1/network/wifi/join'
const SCAN = 'POST /api/v1/network/wifi/scan'
const CHANGE = 'POST /api/v1/network/hotspot'
const JOB = 'GET /api/v1/jobs/job1'
const LOCKED_BY_JOIN = 'Finish or cancel the Wi-Fi join first.'
const LOCKED_BY_JOB = 'Wait for the Wi-Fi change to finish.'

function job(status: Job['status']): Job {
  return {
    id: 'job1', name: 'network', status, requested_at: '2026-11-11T12:00:00+00:00',
    finished_at: null, log: [],
  }
}

const disabled = (wrapper: { find: (selector: string) => { attributes: (name: string) => string | undefined } }, selector: string) =>
  wrapper.find(selector).attributes('disabled') !== undefined

// An admin on the Network page, with the join the device reports (a function answers each ask)
async function openAdmin(answers: Record<string, unknown> = {}) {
  const api = signedIn(ADMIN, { [NETWORK]: NETWORK_STATE, [WIFI]: WIFI_NETWORKS, [JOIN]: json(200, null), ...answers })
  const { wrapper } = await mountApp('/network')
  return { api, wrapper }
}

const posts = (api: { sent: { method: string; path: string; body: unknown }[] }) =>
  api.sent.filter((r) => r.method === 'POST').map((r) => [r.path, r.body])

// Tap Join on a network, type a password in the dialog, and send it
async function joinNeighbour(wrapper: Awaited<ReturnType<typeof openAdmin>>['wrapper'], password = 'placeholder-pass-1') {
  await wrapper.find('button[aria-label="Join Neighbour"]').trigger('click')
  await typeInto(dialogField('Password for Neighbour'), password)
  await clickInDialog('Test and join')
}

describe('joining a network from the Network page', () => {
  beforeEach(() => document.body.replaceChildren())
  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  it('shows the result card above This device and locks the other sections while a join is pending', async () => {
    const { wrapper } = await openAdmin({ [JOIN]: JOIN_COUNTDOWN })
    const text = wrapper.text()
    expect(text).toContain('Neighbour works')
    expect(text.indexOf('Neighbour works')).toBeLessThan(text.indexOf('This device'))
    expect(text.split(LOCKED_BY_JOIN)).toHaveLength(3) // each of the two sections says why
    expect(text).not.toContain(LOCKED_BY_JOB)
    for (const selector of [
      'button[aria-label="Join Neighbour"]',
      'button[aria-label="Forget HomeNet"]',
      'button[aria-label="Change the hotspot name"]',
    ]) {
      expect(disabled(wrapper, selector), selector).toBe(true)
    }
    const refresh = wrapper.findAll('button').find((b) => b.text().trim() === 'Refresh')!
    expect(refresh.attributes('disabled')).toBeDefined()
    expect(wrapper.find<HTMLInputElement>('input[type="checkbox"]').element.disabled).toBe(true)
    // the join's own buttons still work
    expect(wrapper.findAll('button').find((b) => b.text().trim() === 'Switch now')!.attributes('disabled')).toBeUndefined()
  })

  it('shows no card and no lock without a join', async () => {
    const { wrapper } = await openAdmin()
    expect(wrapper.text()).not.toContain(LOCKED_BY_JOIN)
    expect(disabled(wrapper, 'button[aria-label="Join Neighbour"]')).toBe(false)
  })

  it('shows a viewer the card with no buttons', async () => {
    signedIn(VIEWER, { [NETWORK]: NETWORK_STATE, [WIFI]: WIFI_NETWORKS, [JOIN]: JOIN_COUNTDOWN })
    const { wrapper } = await mountApp('/network')
    expect(wrapper.text()).toContain('Joining Neighbour in 3:12')
    const labels = wrapper.findAll('button').map((b) => b.attributes('aria-label') ?? b.text().trim())
    expect(labels.filter((label) => !label.startsWith('Copy '))).toEqual([])
  })

  it('locks the hotspot while a scan runs, and the networks while a hotspot change runs', async () => {
    const { wrapper } = await openAdmin({
      [SCAN]: json(202, { id: 'job1' }),
      [CHANGE]: json(202, { id: 'job1' }),
      [JOB]: json(200, job('running')),
    })
    await click(wrapper, 'Refresh')
    const text = wrapper.text()
    expect(text).toContain('Looking for networks.') // the section that started it says what it is doing
    expect(text).toContain(LOCKED_BY_JOB)
    expect(text).not.toContain(LOCKED_BY_JOIN)
    expect(disabled(wrapper, 'button[aria-label="Change the hotspot name"]')).toBe(true)
    expect(wrapper.find<HTMLInputElement>('input[type="checkbox"]').element.disabled).toBe(true)
  })

  it('locks the networks while a hotspot change runs', async () => {
    const { wrapper } = await openAdmin({ [CHANGE]: json(202, { id: 'job1' }), [JOB]: json(200, job('running')) })
    await wrapper.find('button[aria-label="Change the hotspot name"]').trigger('click')
    await typeInto(dialogField('New name'), 'TM-ROAD')
    await clickInDialog('Change name')
    const text = wrapper.text()
    expect(text).toContain('Saving. The hotspot is restarting.')
    expect(text.split(LOCKED_BY_JOB)).toHaveLength(2) // the networks say why; the section that started it has its own words
    expect(disabled(wrapper, 'button[aria-label="Join Neighbour"]')).toBe(true)
    expect(disabled(wrapper, 'button[aria-label="Forget HomeNet"]')).toBe(true)
    const refresh = wrapper.findAll('button').find((b) => b.text().trim() === 'Refresh')!
    expect(refresh.attributes('disabled')).toBeDefined()
  })

  it('starts a join from the dialog and follows it', async () => {
    vi.useFakeTimers()
    let answer: JoinState | null = null
    const { api, wrapper } = await openAdmin({
      [START]: () => {
        answer = joinState({ stage: 'testing', address: null, internet: null, seconds_left: null })
        return json(202, { id: 'job1' })
      },
      [JOIN]: () => json(200, answer),
    })
    await joinNeighbour(wrapper)
    expect(posts(api)).toEqual([['/api/v1/network/wifi/join', { name: 'Neighbour', password: 'placeholder-pass-1' }]])
    expect(wrapper.text()).toContain('Testing Neighbour. This takes up to a minute.')
    expect(wrapper.text()).toContain(LOCKED_BY_JOIN)

    answer = JOIN_COUNTDOWN
    await vi.advanceTimersByTimeAsync(2000)
    expect(wrapper.text()).toContain('Neighbour works')
    expect(wrapper.text()).toContain('Joining Neighbour in')
  })

  it('sends no password for a saved network that uses its saved one', async () => {
    const { api, wrapper } = await openAdmin({ [START]: json(202, { id: 'job1' }) })
    await wrapper.find('button[aria-label="Join HomeNet"]').trigger('click')
    await clickInDialog('Test and join')
    expect(posts(api)).toEqual([['/api/v1/network/wifi/join', { name: 'HomeNet', password: null }]])
  })

  it("shows the device's refusal when a join cannot start", async () => {
    const refusal = "That network isn't in the list any more. Tap Refresh and pick it again."
    const { wrapper } = await openAdmin({ [START]: apiError(409, 'not_listed', refusal) })
    await joinNeighbour(wrapper)
    expect(wrapper.text()).toContain(refusal)
    expect(wrapper.text()).not.toContain('Testing Neighbour')
    expect(disabled(wrapper, 'button[aria-label="Join Neighbour"]')).toBe(false)
  })

  it('says the test did not start when the unit reports no join within 15 seconds', async () => {
    vi.useFakeTimers()
    const { wrapper } = await openAdmin({ [START]: json(202, { id: 'job1' }) })
    await joinNeighbour(wrapper)
    expect(wrapper.text()).toContain('Testing Neighbour. This takes up to a minute.')
    await vi.advanceTimersByTimeAsync(14_000)
    expect(wrapper.text()).toContain('Testing Neighbour.')
    expect(wrapper.text()).not.toContain("The test didn't start.")
    await vi.advanceTimersByTimeAsync(1_500)
    expect(wrapper.text()).toContain("The test didn't start. Try again.")
    expect(wrapper.text()).not.toContain('Testing Neighbour')
    expect(disabled(wrapper, 'button[aria-label="Join Neighbour"]')).toBe(false)
  })

  it('keeps the testing card, saying the page lost the unit, when the unit cannot be reached for a while', async () => {
    vi.useFakeTimers()
    let reachable = true
    const { wrapper } = await openAdmin({
      [START]: () => {
        reachable = false // the hotspot goes away under this page
        return json(202, { id: 'job1' })
      },
      [JOIN]: () => (reachable ? json(200, null) : Promise.reject(new TypeError('Failed to fetch'))),
    })
    await joinNeighbour(wrapper)
    await vi.advanceTimersByTimeAsync(40_000)
    const text = wrapper.text()
    expect(text).toContain('Testing Neighbour. This takes up to a minute.')
    expect(text).toContain('This page lost the unit, which is expected during the test. When TM-AB12 reappears, join it again.')
    expect(text).not.toContain("The test didn't start.")

    reachable = true
    await vi.advanceTimersByTimeAsync(2_000)
    expect(wrapper.text()).toContain("The test didn't start. Try again.")
  })

  it('loads the networks and the hotspot again when the join changes stage', async () => {
    vi.useFakeTimers()
    let answer: JoinState = JOIN_COUNTDOWN
    const { api, wrapper } = await openAdmin({ [JOIN]: () => json(200, answer) })
    const loads = () => api.sent.filter((r) => r.method === 'GET' && (r.path === '/api/v1/network' || r.path === '/api/v1/network/wifi')).length
    const before = loads()
    await vi.advanceTimersByTimeAsync(2_000)
    expect(loads()).toBe(before) // the same stage: nothing to reload
    answer = joinState({ stage: 'joined', seconds_left: null })
    await vi.advanceTimersByTimeAsync(2_000)
    expect(loads()).toBe(before + 2)
    expect(wrapper.text()).toContain('The unit is on Neighbour.')
    expect(wrapper.text()).not.toContain(LOCKED_BY_JOIN)
  })
})
