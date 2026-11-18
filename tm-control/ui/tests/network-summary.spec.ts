// The words for the unit's network, shared by the Network page and the Device page's card.
import { describe, expect, it } from 'vitest'
import { fallbackNote, internetLine, summaryFacts, wifiLine } from '../src/modules/network/summary'
import { NETWORK_STATE, networkState } from './fake-api'

const wifi = NETWORK_STATE.wifi!
const hotspot = NETWORK_STATE.hotspot

describe('the network summary', () => {
  it('says what the Wi-Fi radio is doing', () => {
    const joined = { ...wifi, mode: 'network' as const, network: 'HomeNet', signal: 72 }
    expect(wifiLine(joined, hotspot)).toBe('HomeNet, signal 72%')
    expect(wifiLine({ ...joined, signal: null }, hotspot)).toBe('HomeNet')
    expect(wifiLine(wifi, hotspot)).toBe('On its hotspot (TM-AB12)')
    expect(wifiLine({ ...wifi, mode: 'joining' }, hotspot)).toBe('Joining a network')
    expect(wifiLine({ ...wifi, mode: 'idle', connected: false }, hotspot)).toBe('Not connected')
    expect(wifiLine({ ...wifi, mode: 'off', connected: false }, hotspot)).toBe('Switched off')
  })

  it('says what the internet is doing', () => {
    expect(internetLine('reachable')).toBe('Reachable')
    expect(internetLine('not_reachable')).toBe('Not reachable')
    expect(internetLine('sign_in_page')).toBe('Needs a sign-in page')
    expect(internetLine('unknown')).toBe('Not checked yet')
  })

  it('gives one line per connected link and none for a link that is down', () => {
    expect(summaryFacts(NETWORK_STATE)).toEqual([
      { label: 'Ethernet', value: '192.168.1.57 · 2C:CF:67:00:AB:11' },
      { label: 'Wi-Fi', value: 'Its hotspot TM-AB12 · 10.42.0.1 · 2C:CF:67:00:AB:12' },
    ])

    const joined = { ...wifi, addresses: ['192.168.1.60'], mode: 'network' as const, network: 'HomeNet', signal: 72 }
    const noCable = { ...NETWORK_STATE.ethernet!, connected: false, addresses: [] }
    expect(summaryFacts(networkState({ ethernet: noCable, wifi: joined }))).toEqual([
      { label: 'Wi-Fi', value: 'HomeNet · 192.168.1.60 · 2C:CF:67:00:AB:12' },
    ])

    const idle = { ...wifi, connected: false, addresses: [], mode: 'idle' as const }
    expect(summaryFacts(networkState({ ethernet: noCable, wifi: idle }))).toEqual([])
    expect(summaryFacts(networkState({ ethernet: null, wifi: null }))).toEqual([])
  })

  it('says the hotspot is only a fallback while the unit is on a Wi-Fi network', () => {
    const joined = { ...wifi, mode: 'network' as const, network: 'HomeNet', signal: 72 }
    const after =
      ', the hotspot starts about a minute later. While nobody is joined to the hotspot, the unit looks for its saved networks every 5 minutes and joins one that is back.'
    expect(fallbackNote(joined, hotspot)).toEqual({
      line: 'Fallback only. This unit is on HomeNet.',
      detail: `The hotspot is a fallback. If this unit loses HomeNet${after}`,
    })
    expect(fallbackNote({ ...joined, network: null }, hotspot)).toEqual({
      line: 'Fallback only. This unit is on a Wi-Fi network.',
      detail: `The hotspot is a fallback. If this unit loses its Wi-Fi network${after}`,
    })
    expect(fallbackNote({ ...joined, network: '' }, hotspot)?.line).toBe(
      'Fallback only. This unit is on a Wi-Fi network.',
    )
  })

  it('has no fallback note at any other time', () => {
    const joined = { ...wifi, mode: 'network' as const, network: 'HomeNet', signal: 72 }
    expect(fallbackNote(wifi, hotspot)).toBeNull() // on its hotspot
    for (const mode of ['joining', 'idle', 'off'] as const) expect(fallbackNote({ ...wifi, mode }, hotspot), mode).toBeNull()
    expect(fallbackNote(joined, { ...hotspot!, enabled: false, active: false })).toBeNull()
    expect(fallbackNote(joined, null)).toBeNull()
    expect(fallbackNote(null, hotspot)).toBeNull()
  })
})
