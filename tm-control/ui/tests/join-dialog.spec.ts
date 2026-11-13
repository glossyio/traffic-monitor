// The Join dialog: what will happen to the unit's radio, the MAC address to list, and the password. Every password
// here is a placeholder.
import { beforeEach, describe, expect, it } from 'vitest'
import type { components } from '../src/api/schema'
import JoinDialog from '../src/modules/network/JoinDialog.vue'
import { wifiPasswordRule } from '../src/modules/network/rules'
import { NETWORK_STATE } from './fake-api'
import { clickInDialog, dialogButtons, dialogField, dialogText, mountAlone, typeInto } from './mount'

type Nearby = components['schemas']['Nearby']
type Wifi = components['schemas']['Wifi']

const NEIGHBOUR: Nearby = { name: 'Neighbour', signal: 41, security: 'password', saved: false, in_use: false }
const SAVED: Nearby = { name: 'HomeNet', signal: 82, security: 'password', saved: true, in_use: false }
const MAC = '2C:CF:67:00:AB:12'
const NO_SECOND_SENTENCE = /hotspot stops/

// The dialog's paragraphs, read one after the other
const paragraphs = () => [...document.querySelectorAll('.v-dialog p')].map((p) => p.textContent?.trim()).join(' ')

function mountDialog(changes: Record<string, unknown> = {}) {
  const props = {
    modelValue: true,
    network: NEIGHBOUR,
    mac: MAC,
    wifi: NETWORK_STATE.wifi,
    hotspot: NETWORK_STATE.hotspot,
    onHotspot: false,
    ...changes,
  }
  const wrapper = mountAlone(JoinDialog, {
    ...props,
    'onUpdate:modelValue': (open: boolean) => wrapper.setProps({ modelValue: open }),
  })
  return wrapper
}

const onNetwork: Wifi = { ...NETWORK_STATE.wifi!, mode: 'network', network: 'HomeNet', addresses: ['192.168.1.60'] }
const idle: Wifi = { ...NETWORK_STATE.wifi!, mode: 'off', connected: false }

describe('the Wi-Fi password rule', () => {
  it('takes 8 to 63 characters from space to tilde, spaces included', () => {
    expect(wifiPasswordRule('placeholder-pass-1')).toBe(true)
    expect(wifiPasswordRule('12345678')).toBe(true)
    expect(wifiPasswordRule('a'.repeat(63))).toBe(true)
    expect(wifiPasswordRule(' pass word ')).toBe(true)
    const message = 'A Wi-Fi password is 8 to 63 letters, digits, and symbols.'
    expect(wifiPasswordRule('1234567')).toBe(message)
    expect(wifiPasswordRule('a'.repeat(64))).toBe(message)
    expect(wifiPasswordRule('pässword-1')).toBe(message)
    expect(wifiPasswordRule('tab\tpassword')).toBe(message)
  })
})

describe('the Join dialog', () => {
  beforeEach(() => document.body.replaceChildren())

  it('shows the Wi-Fi MAC address with a Copy button and says what it is for', () => {
    mountDialog()
    const text = dialogText()
    expect(text).toContain('Join Neighbour')
    expect(text).toContain("The unit's Wi-Fi MAC address")
    expect(text).toContain(MAC)
    expect(text).toContain('A network that only admits listed devices needs this address on its list first.')
    expect(document.querySelector('.v-dialog button[aria-label="Copy Wi-Fi MAC address"]')).not.toBeNull()
  })

  it('leaves the MAC address out when the unit has not reported one', () => {
    mountDialog({ mac: null })
    expect(dialogText()).not.toContain("The unit's Wi-Fi MAC address")
  })

  it('says the hotspot will be away and the phone must rejoin by hand, naming the hotspot', () => {
    mountDialog()
    expect(paragraphs()).toContain(
      'The unit tests Neighbour first. Its hotspot is away for up to a minute, then comes back with the result. ' +
        'A phone on the hotspot must rejoin TM-AB12 by hand to see it. ' +
        'If the test passes, the unit joins Neighbour 5 minutes later, or when you tap Switch now, and the hotspot stops.',
    )
  })

  it('says the unit leaves its current network when it is on one', () => {
    mountDialog({ wifi: onNetwork })
    const text = paragraphs()
    expect(text).toContain(
      'The unit tests Neighbour first. It leaves HomeNet for up to a minute, then comes back with the result. ' +
        'If the test passes, the unit joins Neighbour 5 minutes later, or when you tap Switch now.',
    )
    expect(text).not.toMatch(NO_SECOND_SENTENCE)
    expect(text).not.toContain('Its hotspot is away')
  })

  it('says how long the test takes when the radio is on neither', () => {
    mountDialog({ wifi: idle })
    expect(paragraphs()).toContain(
      'The unit tests Neighbour first, which takes up to a minute. ' +
        'If the test passes, the unit joins Neighbour 5 minutes later, or when you tap Switch now.',
    )
  })

  it('adds that this page stops answering when it was opened over the hotspot', () => {
    const line = "You're on the hotspot now, so this page stops answering during the test."
    mountDialog({ onHotspot: true })
    expect(dialogText()).toContain(line)
    document.body.replaceChildren()
    mountDialog({ onHotspot: false })
    expect(dialogText()).not.toContain(line)
  })

  it('shows the password as it is typed, in one field, and refuses one under 8 characters', async () => {
    const wrapper = mountDialog()
    const input = dialogField('Password for Neighbour')
    expect(input.type).toBe('text')
    expect(input.getAttribute('autocomplete')).toBe('off')
    expect(input.getAttribute('autocapitalize')).toBe('off')
    expect(input.getAttribute('spellcheck')).toBe('false')
    expect(document.querySelectorAll('.v-dialog input')).toHaveLength(1)

    const go = () => dialogButtons('Test and join')[0]
    expect(go().disabled).toBe(true)
    await typeInto(input, 'short')
    expect(dialogText()).toContain('A Wi-Fi password is 8 to 63 letters, digits, and symbols.')
    expect(go().disabled).toBe(true)
    await typeInto(input, 'placeholder-pass-1')
    expect(go().disabled).toBe(false)
    await clickInDialog('Test and join')
    expect(wrapper.emitted('join')).toEqual([['placeholder-pass-1']])
    expect((wrapper.props() as { modelValue: boolean }).modelValue).toBe(false)
  })

  it('accepts a password with a space at its end', async () => {
    const wrapper = mountDialog()
    await typeInto(dialogField('Password for Neighbour'), 'placeholder pass ')
    expect(dialogButtons('Test and join')[0].disabled).toBe(false)
    await clickInDialog('Test and join')
    expect(wrapper.emitted('join')).toEqual([['placeholder pass ']])
  })

  it('uses the saved password for a saved network, and takes a new one after "Enter a new password"', async () => {
    const wrapper = mountDialog({ network: SAVED })
    expect(dialogText()).toContain('Uses the saved password.')
    expect(document.querySelectorAll('.v-dialog input')).toHaveLength(0)
    await clickInDialog('Test and join')
    expect(wrapper.emitted('join')).toEqual([[null]])

    await wrapper.setProps({ modelValue: true })
    expect(dialogText()).toContain('Uses the saved password.')
    await clickInDialog('Enter a new password')
    expect(dialogText()).not.toContain('Uses the saved password.')
    expect(dialogButtons('Test and join')[0].disabled).toBe(true)
    await typeInto(dialogField('Password for HomeNet'), 'placeholder-pass-2')
    await clickInDialog('Test and join')
    expect(wrapper.emitted('join')).toEqual([[null], ['placeholder-pass-2']])
  })

  it('forgets a typed password when it is closed and opened again', async () => {
    const wrapper = mountDialog()
    await typeInto(dialogField('Password for Neighbour'), 'placeholder-pass-1')
    await clickInDialog('Cancel')
    await wrapper.setProps({ modelValue: true })
    expect(dialogField('Password for Neighbour').value).toBe('')
  })
})
