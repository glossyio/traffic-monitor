// One entered secret's form (the Device page's "Tokens and keys"): its state, Save, a confirmed Remove, and the root
// job each one starts. Values here are placeholders, never real tokens.
import { flushPromises, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { components } from '../src/api/schema'
import EnteredSecret from '../src/components/EnteredSecret.vue'
import { fakeApi, json } from './fake-api'
import { button, click, clickInDialog, dialogText, field, mountAlone } from './mount'

type SecretState = components['schemas']['SecretState']
type Job = components['schemas']['Job']

const TOKEN: SecretState = {
  name: 'thingsboard_access_token',
  title: 'ThingsBoard access token',
  set: true,
  ends_with: '0001',
  restarts: ['node-red-tm.service'],
}
const UNSET: SecretState = { ...TOKEN, set: false, ends_with: null }
const LICENSE_KEY: SecretState = {
  name: 'plate_recognizer_license_key',
  title: 'Plate Recognizer license key',
  set: true,
  ends_with: null,
  restarts: ['plate-recognizer.service'],
}
const PLATE_TOKEN: SecretState = {
  name: 'plate_recognizer_token',
  title: 'Plate Recognizer API token',
  set: true,
  ends_with: '0002',
  restarts: ['plate-recognizer.service', 'node-red-tm.service'],
}

const PATH = '/api/v1/secrets/thingsboard_access_token'
const PLACEHOLDER = 'tb-placeholder-0001'

function job(id: string, status: Job['status'], log: string[] = []): Job {
  const done = status === 'succeeded' || status === 'failed'
  return {
    id, name: 'set-secret', status, requested_at: '2026-11-03T12:00:00+00:00',
    finished_at: done ? '2026-11-03T12:00:30+00:00' : null, log,
  }
}

async function mountSecret(secret: SecretState) {
  const wrapper = mountAlone(EnteredSecret, { secret })
  await flushPromises()
  return wrapper
}

async function type(wrapper: VueWrapper, title: string, value: string) {
  await field(wrapper, title).setValue(value)
}

describe('an entered secret', () => {
  beforeEach(() => document.body.replaceChildren())
  afterEach(() => vi.useRealTimers())

  it('says when the value is not set, and offers no Remove', async () => {
    fakeApi({})
    const wrapper = await mountSecret(UNSET)
    expect(wrapper.find('h3').text()).toBe('ThingsBoard access token')
    expect(wrapper.text()).toContain('Not set.')
    expect(wrapper.findAll('button').some((b) => b.text().trim() === 'Remove')).toBe(false)
    expect(field(wrapper, 'ThingsBoard access token').element.value).toBe('')
  })

  it('shows the ending of a set token and the Remove button', async () => {
    fakeApi({})
    const wrapper = await mountSecret(TOKEN)
    expect(wrapper.text()).toContain('Set, ending in 0001.')
    expect(button(wrapper, 'Remove').exists()).toBe(true)
    expect(field(wrapper, 'ThingsBoard access token').element.value).toBe('')
  })

  it('shows "Set." without an ending for a license key', async () => {
    fakeApi({})
    const wrapper = await mountSecret(LICENSE_KEY)
    expect(wrapper.text()).toContain('Set.')
    expect(wrapper.text()).not.toContain('ending in')
  })

  it('refuses an empty submit without calling the API', async () => {
    const api = fakeApi({})
    const wrapper = await mountSecret(TOKEN)
    await type(wrapper, 'ThingsBoard access token', '   ')
    await click(wrapper, 'Save')
    expect(wrapper.text()).toContain('Enter a value, or leave this as it is.')
    expect(api.sent).toEqual([])
  })

  it('saves: posts the value, polls the job, clears the field, emits changed', async () => {
    let polls = 0
    const api = fakeApi({
      [`POST ${PATH}`]: json(202, { id: 'job1' }),
      'GET /api/v1/jobs/job1': () => {
        polls += 1
        return json(200, job('job1', polls > 1 ? 'succeeded' : 'running'))
      },
    })
    const wrapper = await mountSecret(TOKEN)
    vi.useFakeTimers()
    await type(wrapper, 'ThingsBoard access token', PLACEHOLDER)
    await click(wrapper, 'Save')
    expect(api.sent.find((r) => r.method === 'POST')).toEqual({ method: 'POST', path: PATH, body: { value: PLACEHOLDER } })
    expect(field(wrapper, 'ThingsBoard access token').element.value).toBe('')
    expect(wrapper.emitted('changed')).toBeUndefined()
    expect(wrapper.text()).toContain('Saving. Node-RED restarts, which takes about thirty seconds.') // a wait, said

    await vi.advanceTimersByTimeAsync(1000)
    await flushPromises()
    expect(polls).toBe(2)
    expect(wrapper.text()).toContain('Saved. Node-RED restarted.')
    expect(wrapper.text()).not.toContain('Saving.')
    expect(wrapper.emitted('changed')).toHaveLength(1)
  })

  it('removes only after the confirm, with DELETE', async () => {
    const api = fakeApi({
      [`DELETE ${PATH}`]: json(202, { id: 'job2' }),
      'GET /api/v1/jobs/job2': json(200, job('job2', 'succeeded')),
    })
    const wrapper = await mountSecret(TOKEN)
    await click(wrapper, 'Remove')
    expect(dialogText()).toContain('Remove the ThingsBoard access token?')
    expect(dialogText()).toContain(
      'Node-RED restarts, which takes about thirty seconds. The upload to ThingsBoard stops until a token is set again.',
    )
    expect(api.sent).toEqual([])

    await clickInDialog('Remove')
    expect(api.sent.filter((r) => r.method !== 'GET')).toEqual([{ method: 'DELETE', path: PATH, body: null }])
    expect(wrapper.text()).toContain('Removed. Node-RED restarted.')
    expect(wrapper.emitted('changed')).toHaveLength(1)
  })

  it('names every app that restarts', async () => {
    fakeApi({
      'DELETE /api/v1/secrets/plate_recognizer_token': json(202, { id: 'job3' }),
      'GET /api/v1/jobs/job3': json(200, job('job3', 'succeeded')),
    })
    const wrapper = await mountSecret(PLATE_TOKEN)
    await click(wrapper, 'Remove')
    expect(dialogText()).toContain('Remove the Plate Recognizer API token?')
    expect(dialogText()).toContain(
      "Plate Recognizer and Node-RED restart, which takes about a minute. Plates aren't read until it's set again.",
    )
    await clickInDialog('Remove')
    expect(wrapper.text()).toContain('Removed. Plate Recognizer and Node-RED restarted.')
  })

  it('shows the job log when the job fails', async () => {
    fakeApi({
      [`POST ${PATH}`]: json(202, { id: 'job4' }),
      'GET /api/v1/jobs/job4': json(200, job('job4', 'failed', ['refused: the value has a character it cannot carry'])),
    })
    const wrapper = await mountSecret(TOKEN)
    await type(wrapper, 'ThingsBoard access token', PLACEHOLDER)
    await click(wrapper, 'Save')
    expect(wrapper.text()).toContain("The value wasn't saved.")
    expect(wrapper.text()).toContain('refused: the value has a character it cannot carry')
    expect(wrapper.text()).not.toContain('Saved.')
    expect(wrapper.emitted('changed')).toHaveLength(1) // the secret may be written even so; the page reloads its state
  })

  it('says the value was not removed when the remove job fails', async () => {
    fakeApi({
      [`DELETE ${PATH}`]: json(202, { id: 'job7' }),
      'GET /api/v1/jobs/job7': json(200, job('job7', 'failed', ['failed: CalledProcessError'])),
    })
    const wrapper = await mountSecret(TOKEN)
    await click(wrapper, 'Remove')
    await clickInDialog('Remove')
    expect(wrapper.text()).toContain("The value wasn't removed.")
    expect(wrapper.text()).toContain('failed: CalledProcessError')
    expect(wrapper.text()).not.toContain('Removed.')
  })

  it("shows the API's message when the device refuses the value", async () => {
    const refused = 'A ThingsBoard access token is 1 to 256 letters, digits, dots, dashes, underscores, or tildes.'
    fakeApi({ [`POST ${PATH}`]: json(422, { error: { code: 'validation', message: refused, detail: null } }) })
    const wrapper = await mountSecret(TOKEN)
    await type(wrapper, 'ThingsBoard access token', 'tb-placeholder/0001')
    await click(wrapper, 'Save')
    expect(wrapper.text()).toContain(refused)
    expect(field(wrapper, 'ThingsBoard access token').element.value).toBe('tb-placeholder/0001') // to correct it
    expect(wrapper.emitted('changed')).toBeUndefined()
  })

  it('warns when the job never reports', async () => {
    let polls = 0
    fakeApi({
      [`POST ${PATH}`]: json(202, { id: 'job5' }),
      'GET /api/v1/jobs/job5': () => {
        polls += 1
        return json(200, job('job5', 'running'))
      },
    })
    const wrapper = await mountSecret(TOKEN)
    vi.useFakeTimers()
    await type(wrapper, 'ThingsBoard access token', PLACEHOLDER)
    await click(wrapper, 'Save')
    // Setup's two minutes are too short here: the job can wait out two restarts of up to two minutes each
    await vi.advanceTimersByTimeAsync(130_000)
    expect(wrapper.text()).not.toContain("The device hasn't reported")

    await vi.advanceTimersByTimeAsync(180_000)
    await flushPromises()
    expect(wrapper.text()).toContain(
      "The device hasn't reported whether the value was saved. Reload this page in a minute to check.",
    )
    const seen = polls
    await vi.advanceTimersByTimeAsync(10_000)
    expect(polls).toBe(seen)
    expect(button(wrapper, 'Save').attributes('disabled')).toBeUndefined()
  })

  it('toggles between hidden and shown text', async () => {
    fakeApi({})
    const wrapper = await mountSecret(TOKEN)
    const input = field(wrapper, 'ThingsBoard access token')
    expect(input.attributes('type')).toBe('password')
    expect(input.attributes('autocomplete')).toBe('off')
    await wrapper.find('button[aria-label="Show"]').trigger('click')
    expect(input.attributes('type')).toBe('text')
    await wrapper.find('button[aria-label="Hide"]').trigger('click')
    expect(input.attributes('type')).toBe('password')
  })

  it('stops asking about the job once the page is left', async () => {
    let polls = 0
    fakeApi({
      [`POST ${PATH}`]: json(202, { id: 'job6' }),
      'GET /api/v1/jobs/job6': () => {
        polls += 1
        return json(200, job('job6', 'running'))
      },
    })
    const wrapper = await mountSecret(TOKEN)
    vi.useFakeTimers()
    await type(wrapper, 'ThingsBoard access token', PLACEHOLDER)
    await click(wrapper, 'Save')
    await vi.advanceTimersByTimeAsync(3_000)
    wrapper.unmount()
    const seen = polls
    await vi.advanceTimersByTimeAsync(10_000)
    expect(polls).toBe(seen)
  })
})
