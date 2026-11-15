// The words for the unit's network, in one place so the Network page and the Device page's card say the same thing.
import type { components } from '../../api/schema'

type NetworkState = components['schemas']['NetworkState']
type Wifi = components['schemas']['Wifi']
type HotspotState = components['schemas']['HotspotState']

export function wifiLine(wifi: Wifi, hotspot: HotspotState | null): string {
  switch (wifi.mode) {
    case 'network': {
      const name = wifi.network || 'Connected'
      return wifi.signal === null ? name : `${name}, signal ${wifi.signal}%`
    }
    case 'hotspot':
      return hotspot ? `On its hotspot (${hotspot.name})` : 'On its hotspot'
    case 'joining':
      return 'Joining a network'
    case 'off':
      return 'Switched off'
    default:
      return 'Not connected'
  }
}

export function internetLine(internet: NetworkState['internet']): string {
  return {
    reachable: 'Reachable',
    not_reachable: 'Not reachable',
    sign_in_page: 'Needs a sign-in page',
    unknown: 'Not checked yet',
  }[internet]
}

// What the Hotspot panel says while the unit is on a Wi-Fi network and the hotspot would start by itself;
// null at any other time. The timings are tm-network-retry's, as in "When the hotspot runs" in the docs.
export function fallbackNote(wifi: Wifi | null, hotspot: HotspotState | null): { line: string; detail: string } | null {
  if (wifi?.mode !== 'network' || !hotspot?.enabled) return null
  return {
    line: `Fallback only. This unit is on ${wifi.network || 'a Wi-Fi network'}.`,
    detail:
      `The hotspot is a fallback. If this unit loses ${wifi.network || 'its Wi-Fi network'}, the hotspot starts about ` +
      'a minute later. While nobody is joined to the hotspot, the unit looks for its saved networks every 5 minutes ' +
      'and joins one that is back.',
  }
}

// One entry per connected link, for the Device page's card: "192.168.1.57 · <MAC>"
export function summaryFacts(state: NetworkState): { label: string; value: string }[] {
  const facts: { label: string; value: string }[] = []
  const join = (parts: (string | null | undefined)[]) => parts.filter(Boolean).join(' · ')
  const { ethernet, wifi, hotspot } = state
  if (ethernet?.connected) facts.push({ label: 'Ethernet', value: join([ethernet.addresses[0], ethernet.mac]) })
  if (wifi?.connected) {
    const joined = wifi.mode === 'hotspot' ? `Its hotspot${hotspot ? ` ${hotspot.name}` : ''}` : wifi.network || 'Connected'
    facts.push({ label: 'Wi-Fi', value: join([joined, wifi.addresses[0], wifi.mac]) })
  }
  return facts
}
