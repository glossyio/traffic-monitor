// First run: welcome, license, the claim form, and the optional system password, against a fake API.
import { flushPromises, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ADMIN, SHARING_STATE, apiError, fakeApi, json, session, sharingState, status } from './fake-api'
import { button, click, field, mountApp } from './mount'

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
    expect(wrapper.text()).toContain("from the card that came with the device or the end of the installer's output")
  })

  it('keeps all of a pasted code that starts with a space', async () => {
    unclaimedDevice()
    const { wrapper } = await mountApp('/setup')
    await fillClaimForm(wrapper)
    const code = field(wrapper, 'Setup code')
    expect(code.attributes('maxlength')).toBeUndefined() // a length limit would cut " ABCD-EFGH" to ABCD-EFG
    await code.setValue(' ABCD-EFGH')
    expect(code.element.value).toBe('ABCD-EFGH')
  })

  it("doesn't spend a try on a code that is too short", async () => {
    const api = unclaimedDevice()
    const { wrapper } = await mountApp('/setup')
    await fillClaimForm(wrapper)
    await field(wrapper, 'Setup code').setValue('ABCD-EFG')
    await click(wrapper, 'Claim this device')
    expect(api.sent.some((r) => r.path === '/api/v1/setup/claim')).toBe(false)
    expect(wrapper.text()).toContain('The setup code has 8 letters and digits.')
  })

  it("doesn't cut a longer paste down to 8 characters and spend a try on it", async () => {
    const api = unclaimedDevice()
    const { wrapper } = await mountApp('/setup')
    await fillClaimForm(wrapper)
    await field(wrapper, 'Setup code').setValue('Code: ABCD-EFGH')
    await click(wrapper, 'Claim this device')
    expect(api.sent.some((r) => r.path === '/api/v1/setup/claim')).toBe(false)
    expect(wrapper.text()).toContain('The setup code has 8 letters and digits.')
  })

  it('says what to do when the device does not answer', async () => {
    unclaimedDevice({ 'POST /api/v1/setup/claim': () => Promise.reject(new TypeError('Failed to fetch')) })
    const { wrapper } = await mountApp('/setup')
    await fillClaimForm(wrapper)
    await click(wrapper, 'Claim this device')
    expect(wrapper.text()).toContain("Check that this phone or computer is still connected to the device's network")
  })

  it("moves the keyboard focus to each step's heading", async () => {
    unclaimedDevice()
    const { wrapper } = await mountApp('/setup')
    await click(wrapper, 'Start setup')
    expect(document.activeElement?.textContent?.trim()).toBe('Read the license agreement')
    await field(wrapper, 'I accept the license agreement').setValue(true)
    await click(wrapper, 'Continue')
    expect(document.activeElement?.textContent?.trim()).toBe('Create the administrator account')
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
    expect(wrapper.text()).toContain("Check the code on the card or in the installer's output and try again.")
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

  function systemPasswordJob(id: string) {
    let polls = 0
    return {
      'POST /api/v1/system/password': json(202, { id }),
      [`GET /api/v1/jobs/${id}`]: () => {
        polls += 1
        const done = polls > 1
        return json(200, {
          id, name: 'system-password', status: done ? 'succeeded' : 'running',
          requested_at: '2026-10-27T12:00:00+00:00', finished_at: done ? '2026-10-27T12:00:02+00:00' : null, log: [],
        })
      },
    }
  }

  async function setSystemPasswordUntilDone(wrapper: VueWrapper) {
    vi.useFakeTimers()
    await field(wrapper, 'Use the same password as my account').setValue(true)
    await click(wrapper, 'Set system password')
    await vi.advanceTimersByTimeAsync(1000)
    await flushPromises()
  }

  it('names the system account on the system-password step and in its result', async () => {
    unclaimedDevice({ 'GET /api/v1/system/device': { system_user: 'pi' }, ...systemPasswordJob('job4') })
    const { wrapper } = await mountApp('/setup')
    await fillClaimForm(wrapper)
    await click(wrapper, 'Claim this device')
    await flushPromises()
    expect(wrapper.text()).toContain('a system account, pi, for Cockpit')
    await setSystemPasswordUntilDone(wrapper)
    expect(wrapper.find('.v-alert').text()).toContain('as pi')
  })

  it("leaves the account's name out when the device card can't be read, and still sets the password", async () => {
    const api = unclaimedDevice(systemPasswordJob('job5'))
    const { wrapper } = await mountApp('/setup')
    await fillClaimForm(wrapper)
    await click(wrapper, 'Claim this device')
    await flushPromises()
    expect(wrapper.text()).toContain('a system account, for Cockpit')
    await setSystemPasswordUntilDone(wrapper)
    expect(api.sent.find((r) => r.path === '/api/v1/system/password')?.body).toEqual({ password: PASSWORD })
    expect(wrapper.text()).toContain('System password set.')
    expect(wrapper.text()).not.toMatch(/null|undefined|, ,/)
  })

  it('goes home when the system password is skipped', async () => {
    const api = unclaimedDevice()
    const { wrapper, router } = await mountApp('/setup')
    await fillClaimForm(wrapper)
    await click(wrapper, 'Claim this device')
    await click(wrapper, 'Skip for now')
    expect(wrapper.find('h1').text()).toBe('Sharing')
    await click(wrapper, 'Not now')
    await vi.waitFor(() => expect(router.currentRoute.value.fullPath).toBe('/'))
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
    await click(wrapper, 'Continue')
    await click(wrapper, 'Not now')
    await vi.waitFor(() => expect(router.currentRoute.value.fullPath).toBe('/'))
  })

  it('says plainly that the system password was not set when the job fails', async () => {
    unclaimedDevice({
      'POST /api/v1/system/password': json(202, { id: 'job3' }),
      'GET /api/v1/jobs/job3': json(200, {
        id: 'job3', name: 'system-password', status: 'failed',
        requested_at: '2026-10-27T12:00:00+00:00', finished_at: '2026-10-27T12:00:01+00:00',
        log: ["refused: root is a root account (uid 0), and root's password is never set from tm-control"],
      }),
    })
    const { wrapper } = await mountApp('/setup')
    await fillClaimForm(wrapper)
    await click(wrapper, 'Claim this device')
    await field(wrapper, 'Use the same password as my account').setValue(true)
    await click(wrapper, 'Set system password')
    await flushPromises()
    expect(wrapper.text()).toContain("The system password wasn't set, so the account keeps the password it had.")
    expect(wrapper.text()).toContain('refused: root is a root account (uid 0)')
    expect(wrapper.text()).not.toContain('System password set.')
    expect(button(wrapper, 'Skip for now').attributes('disabled')).toBeUndefined()
  })

  function jobThatNeverFinishes(answers: Record<string, unknown> = {}) {
    const job = { polls: 0 }
    const api = unclaimedDevice({
      ...answers,
      'POST /api/v1/system/password': json(202, { id: 'job2' }),
      'GET /api/v1/jobs/job2': () => {
        job.polls += 1
        return json(200, {
          id: 'job2', name: 'system-password', status: 'running',
          requested_at: '2026-10-27T12:00:00+00:00', finished_at: null, log: [],
        })
      },
    })
    return { api, job }
  }

  async function startSystemPassword(wrapper: VueWrapper) {
    await fillClaimForm(wrapper)
    await click(wrapper, 'Claim this device')
    vi.useFakeTimers()
    await field(wrapper, 'Use the same password as my account').setValue(true)
    await click(wrapper, 'Set system password')
  }

  it('lets setup go on when the job never reports a result, and stops asking after two minutes', async () => {
    const { job } = jobThatNeverFinishes()
    const { wrapper, router } = await mountApp('/setup')
    await startSystemPassword(wrapper)
    expect(button(wrapper, 'Skip for now').attributes('disabled')).toBeUndefined() // usable while waiting

    await vi.advanceTimersByTimeAsync(121_000)
    await flushPromises()
    expect(wrapper.text()).toContain("The device hasn't reported whether the system password changed.")
    const polls = job.polls
    await vi.advanceTimersByTimeAsync(10_000)
    expect(job.polls).toBe(polls)

    await click(wrapper, 'Continue')
    await click(wrapper, 'Not now')
    await vi.waitFor(() => expect(router.currentRoute.value.fullPath).toBe('/'))
  })

  it('names the system account when the job never reports a result', async () => {
    jobThatNeverFinishes({ 'GET /api/v1/system/device': { system_user: 'pi' } })
    const { wrapper } = await mountApp('/setup')
    await startSystemPassword(wrapper)
    await vi.advanceTimersByTimeAsync(121_000)
    await flushPromises()
    expect(wrapper.text()).toContain('log in to Cockpit as pi with the new password')
  })

  it('stops asking about the job once the page is left', async () => {
    const { job } = jobThatNeverFinishes()
    const { wrapper } = await mountApp('/setup')
    await startSystemPassword(wrapper)
    await vi.advanceTimersByTimeAsync(3_000)
    wrapper.unmount()
    const polls = job.polls
    await vi.advanceTimersByTimeAsync(10_000)
    expect(job.polls).toBe(polls)
  })

  describe('the Sharing step', () => {
    const SHARING = 'GET /api/v1/sharing'
    const SAVE = 'PUT /api/v1/sharing'
    const INTRO =
      'This device shares nothing unless you turn it on. You can send its counts and speeds to Traffic Monitor\'s ' +
      'server or to your own, and choose how much of its location goes with them. You can do this now or later on ' +
      'the Sharing page.'
    const WITH_TOKEN = sharingState({
      token: { ...SHARING_STATE.token!, set: true, ends_with: '0001' },
    })

    async function toSharingStep(wrapper: VueWrapper) {
      await fillClaimForm(wrapper)
      await click(wrapper, 'Claim this device')
      await click(wrapper, 'Skip for now')
    }

    it('has five steps, the last one Sharing, after the system password is set or skipped', async () => {
      unclaimedDevice({ [SHARING]: sharingState() })
      const { wrapper } = await mountApp('/setup')
      await fillClaimForm(wrapper)
      expect(wrapper.text()).toContain('Step 3 of 5: Administrator account')
      await click(wrapper, 'Claim this device')
      expect(wrapper.text()).toContain('Step 4 of 5: System password')
      await click(wrapper, 'Skip for now')
      expect(wrapper.text()).toContain('Step 5 of 5: Sharing')
      expect(wrapper.find('h1').text()).toBe('Sharing')
    })

    it('moves the keyboard focus to the Sharing heading', async () => {
      unclaimedDevice({ [SHARING]: sharingState() })
      const { wrapper } = await mountApp('/setup')
      await toSharingStep(wrapper)
      expect(document.activeElement?.textContent?.trim()).toBe('Sharing')
    })

    it('says what sharing is and offers only Not now when no token is set', async () => {
      unclaimedDevice({ [SHARING]: sharingState() })
      const { wrapper, router } = await mountApp('/setup')
      await toSharingStep(wrapper)
      expect(wrapper.text().replace(/\s+/g, ' ')).toContain(INTRO)
      expect(wrapper.find('input[type="checkbox"]').exists()).toBe(false)
      await click(wrapper, 'Not now')
      await vi.waitFor(() => expect(router.currentRoute.value.fullPath).toBe('/'))
    })

    it('shows the form when a token is set, and "Save and finish" sends the choices and goes home', async () => {
      const api = unclaimedDevice({
        [SHARING]: WITH_TOKEN,
        [SAVE]: () => json(200, { ...WITH_TOKEN, enabled: true }),
        'GET /api/v1/sharing/notice': { version: '1', markdown: 'Placeholder notice.' },
      })
      const { wrapper, router } = await mountApp('/setup')
      await toSharingStep(wrapper)
      expect(wrapper.text().replace(/\s+/g, ' ')).toContain(INTRO)
      await field(wrapper, 'Share data').setValue(true)
      await field(wrapper, "I've read the notice").setValue(true)
      await click(wrapper, 'Save and finish')
      const put = api.sent.find((r) => r.method === 'PUT' && r.path === '/api/v1/sharing')
      expect(put?.body).toMatchObject({ target: 'maintainer', enabled: true, exact_location: false, notice_version: '1' })
      await vi.waitFor(() => expect(router.currentRoute.value.fullPath).toBe('/'))
    })

    it('stays on the step when the save fails, reads the state again, and Not now still goes home', async () => {
      let reads = 0
      unclaimedDevice({
        [SHARING]: () => {
          reads += 1
          return json(200, WITH_TOKEN)
        },
        [SAVE]: apiError(409, 'config_changed', 'The settings file changed.'),
      })
      const { wrapper, router } = await mountApp('/setup')
      await toSharingStep(wrapper)
      await field(wrapper, 'Share data').setValue(true)
      await field(wrapper, "I've read the notice").setValue(true)
      await click(wrapper, 'Save and finish')
      expect(router.currentRoute.value.fullPath).toBe('/setup')
      expect(wrapper.text()).toContain('The settings file changed.')
      expect(reads).toBe(2) // the step read the state again, as the form asked
      await click(wrapper, 'Not now')
      await vi.waitFor(() => expect(router.currentRoute.value.fullPath).toBe('/'))
    })

    it('shows the paragraph and Not now when the state cannot be read', async () => {
      unclaimedDevice({ [SHARING]: apiError(500, 'error', 'The device answered with an error.') })
      const { wrapper, router } = await mountApp('/setup')
      await toSharingStep(wrapper)
      expect(wrapper.text().replace(/\s+/g, ' ')).toContain(INTRO)
      expect(wrapper.find('input[type="checkbox"]').exists()).toBe(false)
      await click(wrapper, 'Not now')
      await vi.waitFor(() => expect(router.currentRoute.value.fullPath).toBe('/'))
    })
  })
})
