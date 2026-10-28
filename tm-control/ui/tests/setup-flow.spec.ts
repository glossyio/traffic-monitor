// First run: welcome, license, the claim form, and the optional system password, against a fake API.
import { flushPromises, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ADMIN, apiError, fakeApi, json, session, status } from './fake-api'
import { click, field, mountApp } from './mount'

const PASSWORD = 'owner pass 12'

function unclaimedDevice(answers: Record<string, unknown> = {}) {
  let claimed = false
  return fakeApi({
    'GET /api/v1/setup/status': () => json(200, status(claimed)),
    'GET /api/v1/auth/session': () => json(200, session(claimed, claimed ? ADMIN : null)),
    'GET /api/v1/setup/eula': { version: '1', markdown: '# License\n\nPlaceholder text.' },
    'POST /api/v1/setup/claim': () => {
      claimed = true
      return json(201, { user: ADMIN })
    },
    ...(answers as object),
  })
}

async function fillClaimForm(wrapper: VueWrapper) {
  await click(wrapper, 'Start setup')
  await field(wrapper, 'I accept the license agreement').setValue(true)
  await click(wrapper, 'Continue')
  await field(wrapper, 'Setup code').setValue('abcd efgh')
  await field(wrapper, 'Username').setValue('owner')
  await field(wrapper, 'Password').setValue(PASSWORD)
  await field(wrapper, 'Confirm password').setValue(PASSWORD)
}

describe('setup', () => {
  beforeEach(() => document.body.replaceChildren())
  afterEach(() => vi.useRealTimers())

  it('shows the setup code as two groups of four capitals', async () => {
    unclaimedDevice()
    const { wrapper } = await mountApp('/setup')
    await fillClaimForm(wrapper)
    expect(field(wrapper, 'Setup code').element.value).toBe('ABCD-EFGH')
  })

  it('claims the device with the code, the account, and the license version, then asks for the system password', async () => {
    const api = unclaimedDevice()
    const { wrapper } = await mountApp('/setup')
    await fillClaimForm(wrapper)
    await click(wrapper, 'Claim this device')

    const claim = api.sent.find((r) => r.path === '/api/v1/setup/claim')
    expect(claim?.body).toEqual({ setup_code: 'ABCD-EFGH', username: 'owner', password: PASSWORD, eula_version: '1' })
    expect(wrapper.text()).toContain('Set the system password')
  })

  it("shows the API's message when the setup code is wrong, and stays on the form", async () => {
    unclaimedDevice({ 'POST /api/v1/setup/claim': apiError(403, 'invalid_setup_code', 'That setup code is wrong.') })
    const { wrapper } = await mountApp('/setup')
    await fillClaimForm(wrapper)
    await click(wrapper, 'Claim this device')
    expect(wrapper.text()).toContain('That setup code is wrong.')
    expect(wrapper.text()).toContain('Create the administrator account')
  })

  it('fills in the account password when "same password" is ticked', async () => {
    unclaimedDevice()
    const { wrapper } = await mountApp('/setup')
    await fillClaimForm(wrapper)
    await click(wrapper, 'Claim this device')
    await field(wrapper, 'Use the same password as my account').setValue(true)
    expect(field(wrapper, 'System password').element.value).toBe(PASSWORD)
    expect(field(wrapper, 'Confirm system password').element.value).toBe(PASSWORD)
  })

  it('goes home when the system password is skipped', async () => {
    const api = unclaimedDevice()
    const { wrapper, router } = await mountApp('/setup')
    await fillClaimForm(wrapper)
    await click(wrapper, 'Claim this device')
    await click(wrapper, 'Skip for now')
    expect(router.currentRoute.value.fullPath).toBe('/')
    expect(api.sent.some((r) => r.path === '/api/v1/system/password')).toBe(false)
  })

  it('sets the system password and waits for the job to finish', async () => {
    let polls = 0
    const api = unclaimedDevice({
      'POST /api/v1/system/password': json(202, { id: 'job1' }),
      'GET /api/v1/jobs/job1': () => {
        polls += 1
        const done = polls > 1
        return json(200, {
          id: 'job1', name: 'system-password', status: done ? 'succeeded' : 'running',
          requested_at: '2026-10-27T12:00:00+00:00', finished_at: done ? '2026-10-27T12:00:02+00:00' : null, log: [],
        })
      },
    })
    const { wrapper, router } = await mountApp('/setup')
    await fillClaimForm(wrapper)
    await click(wrapper, 'Claim this device')
    vi.useFakeTimers()
    await field(wrapper, 'Use the same password as my account').setValue(true)
    await click(wrapper, 'Set system password')
    expect(api.sent.find((r) => r.path === '/api/v1/system/password')?.body).toEqual({ password: PASSWORD })
    expect(wrapper.text()).not.toContain('System password set.')

    await vi.advanceTimersByTimeAsync(1000)
    await flushPromises()
    expect(polls).toBe(2)
    expect(wrapper.text()).toContain('System password set.')
    await click(wrapper, 'Go to the home page')
    expect(router.currentRoute.value.fullPath).toBe('/')
  })
})
