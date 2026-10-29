// One group of the status report: each check's status mark, title, and detail, and its fix for admins.
import { mdiAlert, mdiCheckCircle, mdiCloseCircle, mdiHelpCircle } from '@mdi/js'
import type { VueWrapper } from '@vue/test-utils'
import { beforeEach, describe, expect, it } from 'vitest'
import CheckList from '../src/components/CheckList.vue'
import { RESCAN, RESTART_FRIGATE } from './fake-api'
import { mountAlone } from './mount'

const FOUR = {
  id: 'apps',
  title: 'Apps',
  checks: [
    { id: 'a', title: 'Node-RED', status: 'ok', detail: 'Node-RED up 2 hours.' },
    { id: 'b', title: 'Location', status: 'warn', detail: 'No location is set.' },
    { id: 'c', title: 'Frigate', status: 'error', detail: "Frigate isn't answering.", fix: RESTART_FRIGATE },
    { id: 'd', title: 'Cameras', status: 'unknown', detail: "Frigate isn't answering, so its cameras can't be checked." },
  ],
}

const HARDWARE = {
  id: 'hardware',
  title: 'Hardware',
  checks: [
    { id: 'h1', title: 'Coral USB Accelerator', status: 'unknown', detail: "It's unknown whether Frigate uses it.", fix: RESCAN },
    { id: 'h2', title: 'HEVC decoder', status: 'ok', detail: '/dev/media1.' },
    { id: 'h3', title: 'Radar on /dev/ttyACM1', status: 'warn', detail: "It isn't enabled.", fix: RESCAN },
  ],
}

function list(group: object, admin = true, extra: Record<string, unknown> = {}) {
  return mountAlone(CheckList, { group, admin, busy: null, ...extra })
}

// The visible text of each button in the list
function buttons(wrapper: VueWrapper) {
  return wrapper.findAll('button').map((b) => b.text().trim())
}

// The icon drawn in front of the check titled `title`
function iconOf(wrapper: VueWrapper, title: string) {
  const row = wrapper.findAll('li, [role="listitem"]').find((r) => r.text().includes(title))
  return row?.find('svg path').attributes('d')
}

describe('CheckList', () => {
  beforeEach(() => document.body.replaceChildren())

  it('shows the group title, and each check with its status mark, title, and detail', () => {
    const wrapper = list(FOUR)
    expect(wrapper.find('h2').text()).toBe('Apps')
    expect(iconOf(wrapper, 'Node-RED')).toBe(mdiCheckCircle)
    expect(iconOf(wrapper, 'Location')).toBe(mdiAlert)
    expect(iconOf(wrapper, 'Frigate')).toBe(mdiCloseCircle)
    expect(iconOf(wrapper, 'Cameras')).toBe(mdiHelpCircle)
    expect(wrapper.text()).toContain("Frigate isn't answering, so its cameras can't be checked.")
  })

  it('names each status in words for screen readers', () => {
    const text = list(FOUR).text()
    for (const word of ['OK', 'Warning', 'Problem', 'Unknown']) expect(text).toContain(word)
  })

  it("offers an admin the restart fix as a button named by the API, and emits its unit", async () => {
    const wrapper = list(FOUR)
    expect(buttons(wrapper)).toEqual(['Restart Frigate'])
    await wrapper.find('button').trigger('click')
    expect(wrapper.emitted('restart')).toEqual([['frigate.service']])
  })

  it('shows a viewer no buttons', () => {
    expect(buttons(list(FOUR, false))).toEqual([])
    expect(buttons(list(HARDWARE, false))).toEqual([])
  })

  it('offers one "Re-scan hardware" button at the end of a group with any re-scan fix', async () => {
    const wrapper = list(HARDWARE)
    expect(buttons(wrapper)).toEqual(['Re-scan hardware'])
    expect(wrapper.text().trim().endsWith('Re-scan hardware')).toBe(true)
    await wrapper.find('button').trigger('click')
    expect(wrapper.emitted('rescan')).toHaveLength(1)
  })

  it('shows a hint fix as text, for everyone', () => {
    const group = {
      id: 'device',
      title: 'Device',
      checks: [
        {
          id: 'p',
          title: 'Power supply and throttling',
          status: 'unknown',
          detail: "tm-control can't read the firmware's power flags.",
          fix: { kind: 'hint', text: 'Run the installer (tmsetup.sh) again.' },
        },
      ],
    }
    const wrapper = list(group, false)
    expect(wrapper.text()).toContain('Run the installer (tmsetup.sh) again.')
    expect(buttons(wrapper)).toEqual([])
  })

  it('shows a link fix as a link to that page inside the detail', () => {
    const group = {
      id: 'time',
      title: 'Date and time',
      checks: [
        {
          id: 't',
          title: 'Clock',
          status: 'warn',
          detail: 'No time source reachable (offline?); the clock runs on its own.',
          fix: { kind: 'link', text: 'Set the date and time', href: '/time' },
        },
      ],
    }
    const link = list(group, false).find('a')
    expect(link.text()).toBe('Set the date and time')
    expect(link.attributes('href')).toBe('/time')
  })

  it('makes the button of the action under way wait', () => {
    const wrapper = list(FOUR, true, { busy: 'frigate.service' })
    expect(wrapper.find('button').classes()).toContain('v-btn--loading')
  })

  it('writes what the last action said under its button', () => {
    const notes = { 'frigate.service': { text: 'Frigate is restarting.', error: false } }
    expect(list(FOUR, true, { notes }).text()).toContain('Frigate is restarting.')
    const failed = { rescan: { text: 'The device answered with an error (HTTP 500).', error: true } }
    expect(list(HARDWARE, true, { notes: failed }).text()).toContain('The device answered with an error (HTTP 500).')
  })
})
