// The Network page's hotspot controls for an admin: Show the password, rename, change or set the password, hide the
// name, turn the hotspot off or on. Every password here is a placeholder.
import { flushPromises, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { components } from '../src/api/schema'
import { ADMIN, NETWORK_STATE, json, networkState, signedIn, status } from './fake-api'
import { clickInDialog, dialogButtons, dialogField, dialogText, field, mountApp, typeInto } from './mount'

type Job = components['schemas']['Job']
type HotspotState = components['schemas']['HotspotState']

const NETWORK = 'GET /api/v1/network'
const PASSWORD = 'GET /api/v1/network/hotspot/password'
const CHANGE = 'POST /api/v1/network/hotspot'
const JOB = 'GET /api/v1/jobs/job1'

const RESTART = 'The hotspot restarts, and phones on it are disconnected. Each phone must rejoin by hand.'
const WRITE_DOWN = 'Write the new password down before you save. Every phone needs it to rejoin.'
const TURN_OFF =
  'With the hotspot off, this unit has no wireless way in when its Wi-Fi network is missing. You would need an Ethernet cable.'
const HIDING = 'The hotspot is still on and can still be found by scanning. Only its name is hidden.'
const ANDROID = 'On Android, add the network by hand and tick Hidden network, or the phone never connects.'
const ON_IT = "You're on the hotspot now, so this page stops answering when you save."
const NAME_RULE = 'A hotspot name is 1 to 32 characters (fewer with accents or emoji), with no space at either end.'
const PASSWORD_RULE = 'A hotspot password is 8 to 63 letters, digits, and symbols, with no space at either end.'

function hotspot(changes: Partial<HotspotState> = {}): HotspotState {
  return { ...NETWORK_STATE.hotspot!, ...changes }
}

function job(status: Job['status'], log: string[] = []): Job {
  const done = status === 'succeeded' || status === 'failed'
  return {
    id: 'job1', name: 'network', status, requested_at: '2026-11-10T12:00:00+00:00',
    finished_at: done ? '2026-11-10T12:00:30+00:00' : null, log,
  }
}

// An admin on the Network page, with a change that is accepted and a job that has finished
async function open(state = NETWORK_STATE, answers: Record<string, unknown> = {}, onHotspot = false) {
  const api = signedIn(ADMIN, {
    [NETWORK]: state,
    [CHANGE]: json(202, { id: 'job1' }),
    [JOB]: json(200, job('succeeded')),
    ...(onHotspot ? { 'GET /api/v1/setup/status': status(true, true, { local_name: 'tm-ab12.local' }) } : {}),
    ...answers,
  })
  const { wrapper } = await mountApp('/network')
  return { api, wrapper }
}

const posts = (api: { sent: { method: string; body: unknown }[] }) =>
  api.sent.filter((r) => r.method === 'POST').map((r) => r.body)

async function tap(wrapper: VueWrapper, ariaLabel: string) {
  const buttons = wrapper.findAll(`button[aria-label="${ariaLabel}"]`)
  expect(buttons.length, `one button "${ariaLabel}"`).toBe(1)
  await buttons[0].trigger('click')
  await flushPromises()
}

async function turn(wrapper: VueWrapper, label: string, on: boolean) {
  await field(wrapper, label).setValue(on)
  await flushPromises()
}

describe('the hotspot settings', () => {
  beforeEach(() => document.body.replaceChildren())
  afterEach(() => vi.restoreAllMocks())

  it('shows the password only after Show, asks the device each time, and forgets it on Hide', async () => {
    let asked = 0
    const { wrapper } = await open(NETWORK_STATE, {
      [PASSWORD]: () => {
        asked += 1
        return json(200, { password: `placeholder-pass-${asked}` })
      },
    })
    expect(asked).toBe(0)
    expect(wrapper.text()).not.toContain('placeholder-pass')

    await tap(wrapper, 'Show the hotspot password')
    expect(wrapper.text()).toContain('placeholder-pass-1')
    expect(wrapper.find('button[aria-label="Copy hotspot password"]').exists()).toBe(true)

    await tap(wrapper, 'Hide the hotspot password')
    expect(wrapper.text()).not.toContain('placeholder-pass')

    await tap(wrapper, 'Show the hotspot password')
    expect(asked).toBe(2)
    expect(wrapper.text()).toContain('placeholder-pass-2')
  })

  it('changes the name after a warning that phones must rejoin', async () => {
    const { api, wrapper } = await open()
    await tap(wrapper, 'Change the hotspot name')
    expect(dialogText()).toContain(RESTART)
    await typeInto(dialogField('New name'), 'TM-ROAD')
    expect(posts(api)).toEqual([])
    await clickInDialog('Change name')
    expect(posts(api)).toEqual([{ name: 'TM-ROAD' }])
  })

  it('refuses a name over 32 bytes and a password under 8 characters before asking the device', async () => {
    const { api, wrapper } = await open()
    await tap(wrapper, 'Change the hotspot name')
    await typeInto(dialogField('New name'), 'é'.repeat(17)) // 17 characters, 34 bytes
    expect(dialogText()).toContain(NAME_RULE)
    expect(dialogButtons('Change name')[0].disabled).toBe(true)
    await typeInto(dialogField('New name'), ' TM-ROAD')
    expect(dialogText()).toContain(NAME_RULE)
    await typeInto(dialogField('New name'), 'é'.repeat(16)) // 32 bytes
    expect(dialogText()).not.toContain(NAME_RULE)
    expect(dialogButtons('Change name')[0].disabled).toBe(false)

    document.body.replaceChildren()
    const second = await open()
    await tap(second.wrapper, 'Change the hotspot password')
    await typeInto(dialogField('New password'), 'short')
    expect(dialogText()).toContain(PASSWORD_RULE)
    expect(dialogButtons('Change password')[0].disabled).toBe(true)
    expect(posts(api)).toEqual([])
    expect(posts(second.api)).toEqual([])
  })

  it('shows the new password as it is typed, in one field, and says to write it down', async () => {
    const { api, wrapper } = await open()
    await tap(wrapper, 'Change the hotspot password')
    const dialog = document.querySelector('.v-overlay-container .v-dialog')!
    expect(dialog.querySelectorAll('input')).toHaveLength(1)
    const input = dialogField('New password')
    expect(input.type).toBe('text')
    await typeInto(input, 'placeholder-pass-9')
    expect(input.value).toBe('placeholder-pass-9')
    const text = dialogText()
    expect(text).toContain(WRITE_DOWN)
    expect(text).toContain(RESTART)
    expect(text.indexOf(WRITE_DOWN)).toBeLessThan(text.indexOf(RESTART))
    await clickInDialog('Change password')
    expect(posts(api)).toEqual([{ password: 'placeholder-pass-9' }])
  })

  it('asks before turning the hotspot off, with the Ethernet warning', async () => {
    const { api, wrapper } = await open()
    await turn(wrapper, 'Hotspot on', false)
    expect(dialogText()).toContain(TURN_OFF)
    expect(posts(api)).toEqual([])
    await clickInDialog('Turn off')
    expect(posts(api)).toEqual([{ enabled: false }])
  })

  it('turns the hotspot on without asking', async () => {
    const off = networkState({ hotspot: hotspot({ enabled: false, active: false }) })
    const { api, wrapper } = await open(off)
    await turn(wrapper, 'Hotspot on', true)
    expect(dialogText()).toBe('')
    expect(posts(api)).toEqual([{ enabled: true }])
  })

  it('warns that a hidden name can still be found and that Android needs Hidden network', async () => {
    const { api, wrapper } = await open()
    await turn(wrapper, 'Hide the name', true)
    const text = dialogText()
    for (const part of [RESTART, HIDING, ANDROID]) expect(text).toContain(part)
    expect(posts(api)).toEqual([])
    await clickInDialog('Hide the name')
    expect(posts(api)).toEqual([{ hidden: true }])
  })

  it('says to rejoin when the page loses the unit after a change that restarts the hotspot', async () => {
    const { wrapper } = await open(NETWORK_STATE, {
      [JOB]: () => {
        throw new TypeError('Failed to fetch')
      },
    })
    await tap(wrapper, 'Change the hotspot name')
    await typeInto(dialogField('New name'), 'TM-ROAD')
    await clickInDialog('Change name')
    expect(wrapper.text()).toContain(
      'This page lost the unit, which is expected when your phone is on the hotspot. Join TM-ROAD again, then reload this page.',
    )
    expect(wrapper.text()).not.toContain("The device didn't answer")
  })

  it('says to rejoin when a poll of the job never gets an answer', async () => {
    const hung = (request: Request) =>
      new Promise<Response>((_, reject) => {
        request.signal.addEventListener('abort', () => reject(new TypeError('The request was aborted')))
      })
    const { wrapper } = await open(NETWORK_STATE, { [JOB]: hung })
    vi.useFakeTimers()
    try {
      await tap(wrapper, 'Change the hotspot name')
      await typeInto(dialogField('New name'), 'TM-ROAD')
      await clickInDialog('Change name')
      expect(wrapper.text()).toContain('Saving. The hotspot is restarting.')
      await vi.advanceTimersByTimeAsync(10_000)
      await flushPromises()
      expect(wrapper.text()).toContain(
        'This page lost the unit, which is expected when your phone is on the hotspot. Join TM-ROAD again, then reload this page.',
      )
      expect(wrapper.text()).not.toContain('Saving.')
    } finally {
      vi.useRealTimers()
    }
  })

  it('says how to reach the unit when the page loses it after the hotspot is turned off', async () => {
    const { wrapper } = await open(NETWORK_STATE, {
      [JOB]: () => {
        throw new TypeError('Failed to fetch')
      },
    })
    await turn(wrapper, 'Hotspot on', false)
    await clickInDialog('Turn off')
    expect(wrapper.text()).toContain('The hotspot is off. Reach the unit on its Wi-Fi network or by Ethernet.')
  })

  it('adds that this page stops answering when it was opened over the hotspot', async () => {
    const { wrapper } = await open(NETWORK_STATE, {}, true)
    await tap(wrapper, 'Change the hotspot name')
    expect(dialogText()).toContain(`${RESTART} ${ON_IT}`)
    document.body.replaceChildren()
    const away = await open(NETWORK_STATE, {}, false)
    await tap(away.wrapper, 'Change the hotspot name')
    expect(dialogText()).toContain(RESTART)
    expect(dialogText()).not.toContain(ON_IT)
  })

  it('adds that sentence to the off and hide warnings too', async () => {
    const { wrapper } = await open(NETWORK_STATE, {}, true)
    await turn(wrapper, 'Hotspot on', false)
    expect(dialogText()).toContain(ON_IT)
    expect(dialogText().indexOf(ON_IT)).toBeGreaterThan(dialogText().indexOf(TURN_OFF))
    await clickInDialog('Cancel')
    await turn(wrapper, 'Hide the name', true)
    expect(dialogText()).toContain(ON_IT)
    expect(dialogText().indexOf(ON_IT)).toBeGreaterThan(dialogText().indexOf(ANDROID))
  })

  it('reloads the state when the job succeeds, and shows the job log when it fails', async () => {
    let loads = 0
    const failure = ['failed: restart the hotspot (nmcli exit status 4); the settings are saved']
    let result = job('succeeded')
    const { wrapper } = await open(NETWORK_STATE, {
      [NETWORK]: () => {
        loads += 1
        return json(200, NETWORK_STATE)
      },
      [JOB]: () => json(200, result),
    })
    expect(loads).toBe(1)
    await tap(wrapper, 'Change the hotspot name')
    await typeInto(dialogField('New name'), 'TM-ROAD')
    await clickInDialog('Change name')
    expect(loads).toBe(2)
    expect(wrapper.text()).toContain('Saved. The hotspot restarted.')

    result = job('failed', failure)
    await tap(wrapper, 'Change the hotspot name')
    await typeInto(dialogField('New name'), 'TM-ROAD-2')
    await clickInDialog('Change name')
    expect(wrapper.text()).toContain("The settings were saved, but the hotspot didn't restart.")
    expect(wrapper.text()).toContain(failure[0])
    expect(loads).toBe(3) // the settings may have been saved, so the page shows what the device has

    result = job('failed', ['refused: the unit is trying a saved network right now; try again in a minute'])
    await tap(wrapper, 'Change the hotspot name')
    await typeInto(dialogField('New name'), 'TM-ROAD-3')
    await clickInDialog('Change name')
    expect(wrapper.text()).toContain("The change wasn't made.")
    expect(wrapper.text()).not.toContain('the settings were saved')
  })

  it('keeps every control disabled while a job runs', async () => {
    let finish = () => {}
    const waiting = new Promise<void>((resolve) => (finish = resolve))
    const { wrapper } = await open(NETWORK_STATE, {
      [JOB]: async () => {
        await waiting
        return json(200, job('succeeded'))
      },
    })
    await tap(wrapper, 'Change the hotspot name')
    await typeInto(dialogField('New name'), 'TM-ROAD')
    await clickInDialog('Change name')
    const controls = wrapper.findAll('button[aria-label^="Change the"], button[aria-label$="the hotspot password"], input[type="checkbox"]')
    expect(controls.length).toBeGreaterThanOrEqual(5)
    for (const control of controls) expect(control.attributes('disabled'), control.html()).toBeDefined()
    finish()
    await flushPromises()
    await vi.waitFor(() => expect(wrapper.text()).toContain('Saved. The hotspot restarted.'))
  })

  it('shows the 422 message the device gives', async () => {
    const { wrapper } = await open(NETWORK_STATE, {
      [CHANGE]: json(422, { error: { code: 'validation', message: NAME_RULE, detail: null } }),
    })
    await tap(wrapper, 'Change the hotspot name')
    await typeInto(dialogField('New name'), 'TM-ROAD')
    await clickInDialog('Change name')
    expect(wrapper.find('.v-alert').text()).toContain(NAME_RULE)
  })

  it('offers Set a password on a hotspot without one', async () => {
    const { api, wrapper } = await open(networkState({ hotspot: hotspot({ security: 'none' }) }))
    expect(wrapper.text()).toContain('None. Anyone nearby can join.')
    expect(wrapper.find('button[aria-label="Show the hotspot password"]').exists()).toBe(false)
    await tap(wrapper, 'Set a password for the hotspot')
    await typeInto(dialogField('New password'), 'placeholder-pass-3')
    await clickInDialog('Set password')
    expect(posts(api)).toEqual([{ password: 'placeholder-pass-3' }])
  })

  it('saves without the restart warning while the hotspot is not up', async () => {
    const down = networkState({ hotspot: hotspot({ enabled: false, active: false }) })
    const { api, wrapper } = await open(down)
    await tap(wrapper, 'Change the hotspot name')
    expect(dialogText()).not.toContain(RESTART)
    await typeInto(dialogField('New name'), 'TM-ROAD')
    await clickInDialog('Change name')
    expect(posts(api)).toEqual([{ name: 'TM-ROAD' }])
    expect(wrapper.text()).toContain('applies when the hotspot next starts')
  })

  it("says the hotspot isn't set up, with no controls, on a unit without one", async () => {
    const { wrapper } = await open(networkState({ hotspot: null }))
    expect(wrapper.text()).toContain("The hotspot isn't set up on this unit.")
    expect(wrapper.findAll('input')).toEqual([])
  })
})
