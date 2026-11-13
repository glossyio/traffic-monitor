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
