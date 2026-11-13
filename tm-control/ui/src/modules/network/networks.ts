// The words and small rules for the Wi-Fi networks section, in one place so the component stays about layout.
import { mdiWifiStrength1, mdiWifiStrength2, mdiWifiStrength3, mdiWifiStrength4 } from '@mdi/js'
import type { components } from '../../api/schema'

type Security = components['schemas']['Nearby']['security']

// When the unit last looked for networks
export function scanAge(seconds: number | null): string {
  if (seconds === null) return 'Not looked yet. Tap Refresh.'
  if (seconds < 60) return 'Looked just now'
  const minutes = Math.floor(seconds / 60)
  return minutes === 1 ? 'Looked 1 minute ago' : `Looked ${minutes} minutes ago`
}

// Why the unit can't join a nearby network of this kind. A network that needs a password has no reason: it can be joined.
export function whyNot(security: Security): string {
  switch (security) {
    case 'open':
      return "Open networks can't be joined."
    case 'enterprise':
      return "Networks with a user name and password can't be joined."
    case 'wpa3':
      return "WPA3-only networks can't be joined yet."
    case 'other':
      return "This kind of network can't be joined."
    default:
      return ''
  }
}

// One icon by quarter of the signal: 1 to 25 percent is the weakest, 76 to 100 the strongest
const SIGNAL = [mdiWifiStrength1, mdiWifiStrength2, mdiWifiStrength3, mdiWifiStrength4]
export function signalIcon(percent: number): string {
  return SIGNAL[Math.min(3, Math.max(0, Math.ceil(percent / 25) - 1))]
}

// The uuids with the one at `index` moved a place up (-1) or down (1); the same order when it can't move
export function moved(uuids: string[], index: number, by: -1 | 1): string[] {
  const to = index + by
  const order = [...uuids]
  if (index < 0 || index >= order.length || to < 0 || to >= order.length) return order
  ;[order[index], order[to]] = [order[to], order[index]]
  return order
}
