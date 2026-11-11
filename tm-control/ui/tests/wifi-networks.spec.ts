// The Network page's "Wi-Fi networks" section: the saved networks in the unit's order (move, forget) and the ones
// nearby (scan). Every password in these tests, if there were one, would be a placeholder.
import { flushPromises, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { components } from '../src/api/schema'
import WifiNetworksSection from '../src/modules/network/WifiNetworks.vue'
import { moved, scanAge, signalIcon, whyNot } from '../src/modules/network/networks'
import { ADMIN, NETWORK_STATE, VIEWER, WIFI_NETWORKS, apiError, json, networkState, signedIn, wifiNetworks } from './fake-api'
import { click, clickInDialog, dialogText, mountAlone, mountApp } from './mount'

type Job = components['schemas']['Job']
type Saved = components['schemas']['Saved']
type Nearby = components['schemas']['Nearby']

const NETWORK = 'GET /api/v1/network'
const WIFI = 'GET /api/v1/network/wifi'
const SCAN = 'POST /api/v1/network/wifi/scan'
const FORGET = 'POST /api/v1/network/wifi/forget'
const ORDER = 'POST /api/v1/network/wifi/order'
const JOB = 'GET /api/v1/jobs/job1'

function saved(name: string, changes: Partial<Saved> = {}): Saved {
  return {
    uuid: `u-${name.toLowerCase()}`, name, in_use: false, automatic: true, hidden: false, in_range: true,
    could_not_join: false, ...changes,
  }
}

function job(status: Job['status'], log: string[] = []): Job {
  const done = status === 'succeeded' || status === 'failed'
  return {
    id: 'job1', name: 'network', status, requested_at: '2026-11-11T12:00:00+00:00',
    finished_at: done ? '2026-11-11T12:00:30+00:00' : null, log,
  }
}

const THREE = [saved('Alpha'), saved('Bravo'), saved('Charlie')]

// The Network page with the signed-in user, the networks the device reports, and changes that are accepted
async function open(wifi = WIFI_NETWORKS, answers: Record<string, unknown> = {}, user: object = ADMIN, state = NETWORK_STATE) {
  const api = signedIn(user, {
    [NETWORK]: state,
    [WIFI]: wifi,
    [SCAN]: json(202, { id: 'job1' }),
    [FORGET]: json(202, { id: 'job1' }),
    [ORDER]: json(202, { id: 'job1' }),
    [JOB]: json(200, job('succeeded')),
    ...answers,
  })
  const { wrapper } = await mountApp('/network')
  return { api, wrapper }
}

const posts = (api: { sent: { method: string; body: unknown; path: string }[] }) =>
  api.sent.filter((r) => r.method === 'POST').map((r) => [r.path, r.body])

const labels = (wrapper: VueWrapper) =>
  wrapper.findAll('button').map((b) => b.attributes('aria-label') ?? b.text().trim())

// The saved network's row, found by its name
function savedRow(wrapper: VueWrapper, name: string) {
  const rows = wrapper.findAll('[role="list"][aria-label="Saved networks"] [role="listitem"]')
  const found = rows.filter((row) => row.text().includes(name))
  expect(found.length, `one saved row for "${name}"`).toBe(1)
  return found[0]
}

const nearbyRows = (wrapper: VueWrapper) =>
  wrapper.findAll('[role="list"][aria-label="Nearby networks"] [role="listitem"]')

async function tap(wrapper: VueWrapper, ariaLabel: string) {
  const buttons = wrapper.findAll(`button[aria-label="${ariaLabel}"]`)
  expect(buttons.length, `one button "${ariaLabel}"`).toBe(1)
  await buttons[0].trigger('click')
  await flushPromises()
}

const sectionProps = { wifi: WIFI_NETWORKS, hotspot: NETWORK_STATE.hotspot, admin: true, locked: false }

describe('the Wi-Fi words', () => {
  it('says how long ago the unit looked', () => {
    expect(scanAge(null)).toBe('Not looked yet. Tap Refresh.')
    expect(scanAge(0)).toBe('Looked just now')
    expect(scanAge(59)).toBe('Looked just now')
    expect(scanAge(60)).toBe('Looked 1 minute ago')
    expect(scanAge(119)).toBe('Looked 1 minute ago')
    expect(scanAge(120)).toBe('Looked 2 minutes ago')
    expect(scanAge(3600)).toBe('Looked 60 minutes ago')
  })

  it('says why a network cannot be joined', () => {
    expect(whyNot('open')).toBe("Open networks can't be joined.")
    expect(whyNot('enterprise')).toBe("Networks with a user name and password can't be joined.")
    expect(whyNot('wpa3')).toBe("WPA3-only networks can't be joined yet.")
    expect(whyNot('other')).toBe("This kind of network can't be joined.")
  })

  it('picks the signal icon by quarter', () => {
    const icons = [0, 25, 26, 50, 51, 75, 76, 100].map(signalIcon)
    expect(new Set(icons).size).toBe(4)
    expect(icons[0]).toBe(icons[1])
    expect(icons[2]).toBe(icons[3])
    expect(icons[4]).toBe(icons[5])
    expect(icons[6]).toBe(icons[7])
    expect(icons[1]).not.toBe(icons[2])
    expect(icons[3]).not.toBe(icons[4])
    expect(icons[5]).not.toBe(icons[6])
  })

  it('moves a network one place and leaves the list it was given alone', () => {
    const uuids = ['a', 'b', 'c']
    expect(moved(uuids, 1, -1)).toEqual(['b', 'a', 'c'])
    expect(moved(uuids, 1, 1)).toEqual(['a', 'c', 'b'])
    expect(moved(uuids, 0, -1)).toEqual(['a', 'b', 'c'])
    expect(moved(uuids, 2, 1)).toEqual(['a', 'b', 'c'])
    expect(uuids).toEqual(['a', 'b', 'c'])
  })
})

describe('the Wi-Fi networks section', () => {
  beforeEach(() => document.body.replaceChildren())
  afterEach(() => {
    vi.restoreAllMocks()
    vi.useRealTimers()
  })

  it("lists the saved networks in the unit's order with the line about the first it finds", async () => {
    const { wrapper } = await open(wifiNetworks({ saved: [saved('Bravo'), saved('Alpha'), saved('Charlie')] }))
    expect(wrapper.text()).toContain('The unit joins the first of these it finds.')
    const names = wrapper
      .findAll('[role="list"][aria-label="Saved networks"] [role="listitem"]')
      .map((row) => row.text().match(/Alpha|Bravo|Charlie/)![0])
    expect(names).toEqual(['Bravo', 'Alpha', 'Charlie'])
  })

  it('says so when no network is saved', async () => {
    const { wrapper } = await open(wifiNetworks({ saved: [] }))
    expect(wrapper.text()).toContain('No saved networks. The unit is on its hotspot whenever it is running.')
    expect(wrapper.text()).not.toContain('The unit joins the first of these it finds.')
  })

  it('marks the network in use, the ones in range, and one that could not be joined', async () => {
    const { wrapper } = await open(
      wifiNetworks({
        saved: [
          saved('Inuse', { in_use: true }),
          saved('Near'),
          saved('Far', { in_range: false }),
          saved('Failing', { could_not_join: true }),
          saved('Secret', { hidden: true }),
          saved('Manual', { automatic: false }),
          saved('Unknown', { in_range: null }),
        ],
      }),
    )
    expect(savedRow(wrapper, 'Inuse').text()).toContain('Joined')
    expect(savedRow(wrapper, 'Near').text()).toContain('In range')
    expect(savedRow(wrapper, 'Near').text()).not.toContain('Not in range')
    expect(savedRow(wrapper, 'Far').text()).toContain('Not in range')
    const failing = savedRow(wrapper, 'Failing').text()
    expect(failing).toContain("Couldn't join")
    expect(failing).toContain(
      "The unit couldn't join this network last time. It tries again by itself, after a wait that grows to an hour.",
    )
    expect(savedRow(wrapper, 'Secret').text()).toContain('Hidden')
    expect(savedRow(wrapper, 'Manual').text()).toContain('Not joined by itself')
    expect(savedRow(wrapper, 'Near').text()).not.toContain('Not joined by itself')
    const unknown = savedRow(wrapper, 'Unknown').text()
    expect(unknown).not.toContain('In range')
    expect(unknown).not.toContain("Couldn't join")
  })

  it('moves a network up and sends the whole new order', async () => {
    const { api, wrapper } = await open(wifiNetworks({ saved: THREE }))
    await tap(wrapper, 'Move Bravo up')
    expect(posts(api)).toEqual([['/api/v1/network/wifi/order', { uuids: ['u-bravo', 'u-alpha', 'u-charlie'] }]])
  })

  it('moves a network down', async () => {
    const { api, wrapper } = await open(wifiNetworks({ saved: THREE }))
    await tap(wrapper, 'Move Bravo down')
    expect(posts(api)).toEqual([['/api/v1/network/wifi/order', { uuids: ['u-alpha', 'u-charlie', 'u-bravo'] }]])
  })

  it('has no Move up on the first and no Move down on the last, and none on a network that is not automatic', async () => {
    const { wrapper } = await open(wifiNetworks({ saved: [saved('Alpha'), saved('Bravo'), saved('Manual', { automatic: false })] }))
    const shown = labels(wrapper)
    expect(shown).not.toContain('Move Alpha up')
    expect(shown).toContain('Move Alpha down')
    expect(shown).toContain('Move Bravo up')
    expect(shown).not.toContain('Move Bravo down')
    expect(shown.filter((label) => label.includes('Manual'))).toEqual(['Forget Manual'])
  })

  it('sends only the automatic networks in the order, so a manual one never moves', async () => {
    const list = [saved('Alpha'), saved('Bravo'), saved('Manual', { automatic: false })]
    const { api, wrapper } = await open(wifiNetworks({ saved: list }))
    await tap(wrapper, 'Move Bravo up')
    expect(posts(api)).toEqual([['/api/v1/network/wifi/order', { uuids: ['u-bravo', 'u-alpha'] }]])
  })

  it('loads the list again after a change', async () => {
    let loads = 0
    const { wrapper } = await open(wifiNetworks({ saved: THREE }), {
      [WIFI]: () => {
        loads += 1
        return json(200, wifiNetworks({ saved: loads === 1 ? THREE : [THREE[1], THREE[0], THREE[2]] }))
      },
    })
    await tap(wrapper, 'Move Bravo up')
    await vi.waitFor(() => expect(loads).toBe(2))
    const names = wrapper
      .findAll('[role="list"][aria-label="Saved networks"] [role="listitem"]')
      .map((row) => row.text().match(/Alpha|Bravo|Charlie/)![0])
    expect(names).toEqual(['Bravo', 'Alpha', 'Charlie'])
  })

  it("shows the device's message when the order is out of date", async () => {
    const { wrapper } = await open(wifiNetworks({ saved: THREE }), {
      [ORDER]: apiError(409, 'stale_order', 'The saved networks changed. Reload the page and try again.'),
    })
    await tap(wrapper, 'Move Bravo up')
    expect(wrapper.text()).toContain('The saved networks changed. Reload the page and try again.')
  })

  it('asks before forgetting, with the hotspot warning for the network in use', async () => {
    const list = [saved('Alpha', { in_use: true }), saved('Bravo')]
    const { api, wrapper } = await open(wifiNetworks({ saved: list }))

    await tap(wrapper, 'Forget Bravo')
    expect(dialogText()).toContain('Forget Bravo?')
    expect(dialogText()).toContain('The unit will no longer join it by itself.')
    expect(posts(api)).toEqual([])
    await clickInDialog('Cancel')
    expect(posts(api)).toEqual([])

    await tap(wrapper, 'Forget Alpha')
    expect(dialogText()).toContain(
      'The unit is on Alpha now. If you forget it, the unit leaves it and starts its hotspot, TM-AB12. Reach the unit there or by Ethernet.',
    )
    await clickInDialog('Forget')
    expect(posts(api)).toEqual([['/api/v1/network/wifi/forget', { uuid: 'u-alpha' }]])
  })

  it('sends the uuid of a network that is not in use when it is forgotten', async () => {
    const { api, wrapper } = await open(wifiNetworks({ saved: THREE }))
    await tap(wrapper, 'Forget Bravo')
    await clickInDialog('Forget')
    expect(posts(api)).toEqual([['/api/v1/network/wifi/forget', { uuid: 'u-bravo' }]])
  })

  it('warns that there is no wireless way in when the network in use is forgotten with the hotspot off', async () => {
    const off = networkState({ hotspot: { ...NETWORK_STATE.hotspot!, enabled: false, active: false } })
    const { wrapper } = await open(wifiNetworks({ saved: [saved('Alpha', { in_use: true })] }), {}, ADMIN, off)
    await tap(wrapper, 'Forget Alpha')
    expect(dialogText()).toContain(
      'The unit is on Alpha now, and its hotspot is off. If you forget it, this unit has no wireless way in. You would need an Ethernet cable.',
    )
  })

  it('says the unit left the network when the page loses it after such a Forget', async () => {
    const { wrapper } = await open(wifiNetworks({ saved: [saved('Alpha', { in_use: true })] }), {
      [JOB]: () => {
        throw new TypeError('Failed to fetch')
      },
    })
    await tap(wrapper, 'Forget Alpha')
    await clickInDialog('Forget')
    expect(wrapper.text()).toContain(
      'This page lost the unit, which is expected: the unit left Alpha. Join its hotspot TM-AB12, then open http://10.42.0.1/.',
    )
    expect(wrapper.text()).not.toContain("The device didn't answer")
  })

  it('shows the device\'s answer when a forget of a network that is not in use cannot reach the unit', async () => {
    const { wrapper } = await open(wifiNetworks({ saved: THREE }), {
      [JOB]: () => {
        throw new TypeError('Failed to fetch')
      },
    })
    await tap(wrapper, 'Forget Bravo')
    await clickInDialog('Forget')
    expect(wrapper.text()).toContain("The device didn't answer")
    expect(wrapper.text()).not.toContain('This page lost the unit')
  })

  it('shows nearby networks strongest first with a lock on password networks, and the reason on the others', async () => {
    const { wrapper } = await open()
    const rows = nearbyRows(wrapper)
    expect(rows.map((row) => row.text().match(/HomeNet|CafeGuest|OfficeCorp|Neighbour|NewerRouter/)![0])).toEqual([
      'HomeNet', 'CafeGuest', 'OfficeCorp', 'Neighbour', 'NewerRouter',
    ])
    const row = (name: string) => rows.find((r) => r.text().includes(name))!
    for (const name of ['HomeNet', 'Neighbour']) {
      expect(row(name).find('[aria-label="Needs a password"]').exists(), name).toBe(true)
    }
    for (const name of ['CafeGuest', 'OfficeCorp', 'NewerRouter']) {
      expect(row(name).find('[aria-label="Needs a password"]').exists(), name).toBe(false)
    }
    expect(row('CafeGuest').text()).toContain("Open networks can't be joined.")
    expect(row('OfficeCorp').text()).toContain("Networks with a user name and password can't be joined.")
    expect(row('NewerRouter').text()).toContain("WPA3-only networks can't be joined yet.")
    expect(row('Neighbour').text()).not.toContain("can't be joined")
    expect(row('HomeNet').find('[aria-label="Signal 82%"]').exists()).toBe(true)
  })

  it('marks a nearby network that is saved or in use', async () => {
    const nearby: Nearby[] = [
      { name: 'Used', signal: 70, security: 'password', saved: true, in_use: true },
      { name: 'Kept', signal: 60, security: 'password', saved: true, in_use: false },
    ]
    const { wrapper } = await open(wifiNetworks({ nearby }))
    const rows = nearbyRows(wrapper)
    expect(rows[0].text()).toContain('Joined')
    expect(rows[1].text()).toContain('Saved')
    expect(rows[1].text()).not.toContain('Joined')
  })

  it('says when the unit last looked, and looks again on Refresh', async () => {
    let loads = 0
    const { api, wrapper } = await open(WIFI_NETWORKS, {
      [WIFI]: () => {
        loads += 1
        return json(200, wifiNetworks({ scanned_seconds_ago: loads === 1 ? 90 : 3 }))
      },
    })
    expect(wrapper.text()).toContain('Looked 1 minute ago')
    await click(wrapper, 'Refresh')
    await vi.waitFor(() => expect(wrapper.text()).toContain('Looked just now'))
    expect(posts(api)).toEqual([['/api/v1/network/wifi/scan', {}]])
    expect(loads).toBe(2)
  })

  it('says what the scan does to phones on the hotspot while it runs', async () => {
    const running = (): Response => json(200, job('running'))
    const { wrapper } = await open(wifiNetworks({ saved: THREE }), { [JOB]: running })
    vi.useFakeTimers()
    await click(wrapper, 'Refresh')
    expect(wrapper.text()).toContain('Looking for networks. Phones on the hotspot pause for a few seconds.')
    const refresh = wrapper.findAll('button').find((b) => b.text().trim() === 'Refresh')!
    expect(refresh.attributes('disabled')).toBeDefined()
    const forgets = wrapper.findAll('button[aria-label^="Forget"]')
    expect(forgets.length).toBe(3)
    for (const button of forgets) expect(button.attributes('disabled')).toBeDefined()
  })

  it('says nothing was looked for yet before the first scan', async () => {
    const { wrapper } = await open(wifiNetworks({ scanned_seconds_ago: null, nearby: [] }))
    expect(wrapper.text()).toContain('Not looked yet. Tap Refresh.')
    expect(nearbyRows(wrapper)).toEqual([])
  })

  it('shows a viewer the lists with no Refresh, Forget, or Move buttons', async () => {
    const { wrapper } = await open(wifiNetworks({ saved: THREE }), {}, VIEWER)
    expect(wrapper.text()).toContain('Alpha')
    expect(wrapper.text()).toContain('CafeGuest')
    expect(wrapper.text()).toContain('Looked 1 minute ago')
    expect(labels(wrapper).filter((l) => !l.startsWith('Copy '))).toEqual([])
  })

  it('shows a viewer that nothing was looked for without telling them to tap a button they do not have', async () => {
    const { wrapper } = await open(wifiNetworks({ scanned_seconds_ago: null, nearby: [] }), {}, VIEWER)
    expect(wrapper.text()).toContain('Not looked yet.')
    expect(wrapper.text()).not.toContain('Tap Refresh')
  })

  it('disables every control while locked', () => {
    const wrapper = mountAlone(WifiNetworksSection, {
      ...sectionProps,
      wifi: wifiNetworks({ saved: THREE }),
      locked: true,
    })
    const buttons = wrapper.findAll('button')
    expect(buttons.length).toBeGreaterThan(4)
    for (const button of buttons) expect(button.attributes('disabled'), button.attributes('aria-label') ?? button.text()).toBeDefined()
  })

  it('leaves every control enabled when not locked', () => {
    const wrapper = mountAlone(WifiNetworksSection, { ...sectionProps, wifi: wifiNetworks({ saved: [saved('Alpha'), saved('Bravo')] }) })
    for (const button of wrapper.findAll('button')) expect(button.attributes('disabled'), button.attributes('aria-label') ?? button.text()).toBeUndefined()
  })

  it('shows the job log when a scan fails', async () => {
    const { wrapper } = await open(WIFI_NETWORKS, {
      [JOB]: json(200, job('failed', ['network-scan: the radio did not answer'])),
    })
    await click(wrapper, 'Refresh')
    expect(wrapper.text()).toContain("The unit couldn't look for networks.")
    expect(wrapper.text()).toContain('network-scan: the radio did not answer')
  })

  it("shows the device's message when it refuses a scan", async () => {
    const { wrapper } = await open(WIFI_NETWORKS, {
      [SCAN]: apiError(409, 'radio_off', 'The Wi-Fi radio is switched off.'),
    })
    await click(wrapper, 'Refresh')
    expect(wrapper.text()).toContain('The Wi-Fi radio is switched off.')
  })

  it('says the radio is switched off, with no lists', async () => {
    const { wrapper } = await open(wifiNetworks({ radio: 'off', saved: THREE, nearby: WIFI_NETWORKS.nearby }))
    expect(wrapper.text()).toContain('The Wi-Fi radio is switched off. Turn the hotspot on to switch it on.')
    expect(wrapper.text()).not.toContain('Alpha')
    expect(wrapper.text()).not.toContain('CafeGuest')
    expect(labels(wrapper)).not.toContain('Refresh')
  })

  it('says only that the unit has no radio when it has none', async () => {
    const { wrapper } = await open(wifiNetworks({ radio: 'none', saved: [], nearby: [], scanned_seconds_ago: null }))
    const section = wrapper.findAll('section').find((s) => s.text().includes('Wi-Fi networks'))!
    expect(section.text()).toContain('This unit has no built-in Wi-Fi radio.')
    expect(section.text()).not.toContain('Not looked yet')
    expect(section.text()).not.toContain('No saved networks')
    expect(section.findAll('button')).toEqual([])
  })

  it('says the networks could not be read when the unit could not read them', async () => {
    const { wrapper } = await open(wifiNetworks({ readable: false, radio: 'none', saved: [], nearby: [] }))
    expect(wrapper.text()).toContain("The Wi-Fi networks couldn't be read, because the network service didn't answer.")
    expect(wrapper.text()).not.toContain('This unit has no built-in Wi-Fi radio.')
  })

  it('offers Join on a password network and not on the one in use or on an open one', async () => {
    const nearby: Nearby[] = [
      { name: 'HomeNet', signal: 82, security: 'password', saved: true, in_use: true },
      { name: 'CafeGuest', signal: 64, security: 'open', saved: false, in_use: false },
      { name: 'OfficeCorp', signal: 55, security: 'enterprise', saved: false, in_use: false },
      { name: 'Neighbour', signal: 41, security: 'password', saved: false, in_use: false },
      { name: 'Depot', signal: 40, security: 'password', saved: true, in_use: false },
      { name: 'NewerRouter', signal: 30, security: 'wpa3', saved: false, in_use: false },
    ]
    const { wrapper } = await open(wifiNetworks({ nearby }))
    expect(labels(wrapper).filter((label) => label.startsWith('Join '))).toEqual(['Join Neighbour', 'Join Depot'])
    expect(wrapper.findAll('button').filter((b) => b.text().trim() === 'Join')).toHaveLength(2)
  })

  it('offers no Join to a viewer', async () => {
    const { wrapper } = await open(WIFI_NETWORKS, {}, VIEWER)
    expect(labels(wrapper).filter((label) => label.startsWith('Join '))).toEqual([])
  })

  it('asks the page to join the network that was tapped, and is disabled while locked', async () => {
    const wrapper = mountAlone(WifiNetworksSection, sectionProps)
    await tap(wrapper, 'Join Neighbour')
    expect(wrapper.emitted('join')).toEqual([[WIFI_NETWORKS.nearby[3]]])

    document.body.replaceChildren()
    const locked = mountAlone(WifiNetworksSection, { ...sectionProps, locked: true })
    expect(locked.find('button[aria-label="Join Neighbour"]').attributes('disabled')).toBeDefined()
  })

})
