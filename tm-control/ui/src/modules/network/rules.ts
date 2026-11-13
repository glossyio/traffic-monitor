// The hotspot name and password rules, the same as the API's (modules/network/router.py), so a bad value is refused
// on the page before the device is asked. The API checks again; its message is the same.
export const NAME_MESSAGE = 'A hotspot name is 1 to 32 characters (fewer with accents or emoji), with no space at either end.'
export const PASSWORD_MESSAGE = 'A hotspot password is 8 to 63 letters, digits, and symbols, with no space at either end.'

const NAME_MAX_BYTES = 32
const NAME_PATTERN = /^[^\x00-\x20\x7f](?:[^\x00-\x1f\x7f]*[^\x00-\x20\x7f])?$/u // no control characters or edge spaces
const PASSWORD_PATTERN = /^[\x21-\x7e][\x20-\x7e]{6,61}[\x21-\x7e]$/ // 8 to 63 printable ASCII

export function nameRule(value: string): true | string {
  const fits = new TextEncoder().encode(value).length <= NAME_MAX_BYTES
  return NAME_PATTERN.test(value) && fits ? true : NAME_MESSAGE
}

export function passwordRule(value: string): true | string {
  return PASSWORD_PATTERN.test(value) ? true : PASSWORD_MESSAGE
}

// A Wi-Fi network's password is what the network says it is, so a space is allowed anywhere (the hotspot's is not).
// The same rule as the API's (NETWORK_PASSWORD_PATTERN in modules/network/router.py), and its message.
export const WIFI_PASSWORD_MESSAGE = 'A Wi-Fi password is 8 to 63 letters, digits, and symbols.'

const WIFI_PASSWORD_PATTERN = /^[\x20-\x7e]{8,63}$/

export function wifiPasswordRule(value: string): true | string {
  return WIFI_PASSWORD_PATTERN.test(value) ? true : WIFI_PASSWORD_MESSAGE
}
