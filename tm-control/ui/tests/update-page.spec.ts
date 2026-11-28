// The Software update page (/update): what is installed, the check, the offer, the start, the run, its end, and the log.
import type { VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { UPDATE_POLL_MS } from '../src/modules/update/update'
import {
  ADMIN,
  DEVELOPMENT_OFFER,
  STABLE_OFFER,
  VIEWER,
  apiError,
  json,
  signedIn,
  updateRun,
  updateState,
  type Sent,
  type UpdateState,
} from './fake-api'
import { button, click, clickInDialog, dialogText, mountApp } from './mount'

const UPDATE = 'GET /api/v1/update'
const CHECK = 'POST /api/v1/update/check'
const START = 'POST /api/v1/update/start'
const LOG = 'GET /api/v1/update/log'
const DOCS = 'https://docs.trafficmonitor.ai/latest/build-your-own-device-diy/update/'
const CONFIRM_TEXT =
  'The device keeps counting while it downloads and builds the new version, which can take half an hour. Then it ' +
  'stops counting, and this page stops answering, for about 3 minutes while it switches, and longer if it restarts.'
const AWAY =
  "The device isn't answering. That is expected for a few minutes while it switches or restarts. This page keeps trying."

function menu(wrapper: VueWrapper) {
  return wrapper
    .find('.v-navigation-drawer .v-list')
    .findAll('.v-list-item-title')
    .map((t) => t.text().trim())
}

const posts = (sent: Sent[]) => sent.filter((r) => r.method === 'POST')

// The page for an admin, with GET /update answering `state` (or a function of nothing, for a changing answer)
async function page(state: UpdateState | (() => UpdateState), answers: Record<string, unknown> = {}) {
  const read = typeof state === 'function' ? state : () => state
  const api = signedIn(ADMIN, { [UPDATE]: () => json(200, read()), ...answers })
  const { wrapper } = await mountApp('/update')
  return { api, wrapper }
}

// A failed run's stages as both writers leave them: the failing one has a finish time too
const FAILED_STAGES = [
  { id: 'prepare', started_at: '2026-11-26T10:15:02Z', finished_at: '2026-11-26T10:20:40Z' },
  { id: 'images', started_at: '2026-11-26T10:20:41Z', finished_at: '2026-11-26T10:30:00Z' },
]

const updateButton = (wrapper: VueWrapper) => wrapper.findAll('button').find((b) => b.text().trim().startsWith('Update to'))

describe('the Software update page', () => {
  beforeEach(() => document.body.replaceChildren())
  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  it('sends a viewer home, and shows the entry in the admin menu after Date and time', async () => {
    signedIn(VIEWER)
    const viewer = await mountApp('/update')
    expect(viewer.router.currentRoute.value.fullPath).toBe('/')
    expect(menu(viewer.wrapper)).not.toContain('Software update')
    viewer.wrapper.unmount()

    const { wrapper } = await page(updateState())
    const titles = menu(wrapper)
    expect(titles.indexOf('Software update')).toBe(titles.indexOf('Date and time') + 1)
    expect(wrapper.find('h1').text()).toBe('Software update')
  })

  it('asks GitHub nothing until Check is pressed', async () => {
    const { api, wrapper } = await page(updateState(), {
      [CHECK]: json(200, updateState({ offer: STABLE_OFFER })),
    })
    expect(posts(api.sent)).toEqual([])
    expect(wrapper.text()).toContain('Checking asks GitHub. Nothing is sent until you press it.')
    await click(wrapper, 'Check for updates')
    expect(posts(api.sent)).toEqual([{ method: 'POST', path: '/api/v1/update/check', body: { channel: 'stable' } }])
    expect(wrapper.text()).toContain('Version 0.8.1 is available')
    expect(wrapper.text()).toContain('Last checked')
  })

  it("shows a check's failure, with the API's message, beside the button", async () => {
    const tooSoon = new Response(
      JSON.stringify({ error: { code: 'rate_limited', message: 'A check was made a moment ago.', detail: null } }),
      { status: 429, headers: { 'Content-Type': 'application/json', 'Retry-After': '42' } },
    )
    const { wrapper } = await page(updateState(), { [CHECK]: tooSoon })
    await click(wrapper, 'Check for updates')
    expect(wrapper.find('.v-alert').text()).toContain('A check was made a moment ago. Wait 42 seconds before the next try.')
  })

  it('preselects the installed channel and warns under Development', async () => {
    const warning = 'A device on Development goes back to Stable only when the next release comes out.'
    const { api, wrapper } = await page(
      updateState({ installed: { ...updateState().installed, channel: 'development' } }),
      { [CHECK]: json(200, updateState({ offer: DEVELOPMENT_OFFER })) },
    )
    const radios = wrapper.findAll<HTMLInputElement>('input[type="radio"]')
    const checked = radios.filter((r) => r.element.checked).map((r) => r.element.value)
    expect(checked).toEqual(['development'])
    expect(wrapper.text()).toContain('Stable releases')
    expect(wrapper.text()).toContain('Development (newest, can break)')
    expect(wrapper.text()).toContain(warning)
    await click(wrapper, 'Check for updates')
    expect(posts(api.sent)[0].body).toEqual({ channel: 'development' })

    // The other choice is what the next check asks about
    await radios.find((r) => r.element.value === 'stable')!.setValue(true)
    expect(wrapper.text()).not.toContain('changes since this version') // the offer was for Development
    await click(wrapper, 'Check for updates')
    expect(posts(api.sent)[1].body).toEqual({ channel: 'stable' })
  })

  it('shows "modified" beside the commit of a changed copy', async () => {
    const clean = await page(updateState())
    expect(clean.wrapper.text()).toContain('Traffic Monitor 0.8.0 · Stable · commit 2da617a')
    expect(clean.wrapper.text()).not.toContain('modified')
    clean.wrapper.unmount()

    const { wrapper } = await page(updateState({ installed: { ...updateState().installed, modified: true } }))
    expect(wrapper.text()).toContain('Traffic Monitor 0.8.0 · Stable · commit 2da617a, modified')
  })

  it.each(['ahead', 'identical', 'behind', 'diverged', 'unknown'] as const)('words the offer for %s', async (relation) => {
    const { wrapper } = await page(updateState({ offer: { ...STABLE_OFFER, relation } }))
    const text = wrapper.text()
    const words = {
      ahead: 'Version 0.8.1 is available',
      identical: 'This device is up to date.',
      behind: 'This device is newer than the latest release.',
      diverged: "This device can't be updated from here. Update it with the installer.",
      unknown: "This device can't be updated from here. Update it with the installer.",
    }[relation]
    expect(text).toContain(words)
    const docs = wrapper.findAll('a').filter((a) => a.attributes('href') === DOCS)
    expect(docs.length).toBe(relation === 'diverged' || relation === 'unknown' ? 1 : 0)
    if (relation === 'ahead') {
      const day = new Date(Date.parse(STABLE_OFFER.released_at!)).toLocaleDateString(undefined, {
        day: 'numeric',
        month: 'short',
        year: 'numeric',
      })
      expect(text).toContain(`Released ${day}`)
      expect(updateButton(wrapper)?.text()).toBe('Update to 0.8.1')
    } else {
      expect(updateButton(wrapper)).toBeUndefined()
    }
  })

  it('words a development offer by its changes and its commit', async () => {
    const { wrapper } = await page(
      updateState({
        installed: { ...updateState().installed, channel: 'development' },
        offer: DEVELOPMENT_OFFER,
      }),
    )
    expect(wrapper.text()).toContain('12 changes since this version are available (commit 6666666)')
    expect(updateButton(wrapper)?.text()).toBe('Update to commit 6666666')
    wrapper.unmount()

    const one = await page(
      updateState({
        installed: { ...updateState().installed, channel: 'development' },
        offer: { ...DEVELOPMENT_OFFER, ahead_by: 1 },
      }),
    )
    expect(one.wrapper.text()).toContain('1 change since this version is available (commit 6666666)')
  })

  it('enables Update only for an offer that is ahead with no failing check', async () => {
    const ready = await page(updateState({ offer: STABLE_OFFER }))
    expect(updateButton(ready.wrapper)?.attributes('disabled')).toBeUndefined()
    // Before you start: the checks with the Status page's marks, and the restore point's limits
    expect(ready.wrapper.text()).toContain('Before you start')
    expect(ready.wrapper.text()).toContain(
      "The update saves the settings as a restore point. It doesn't save the counted data: download the database first.",
    )
    // the sentence's link goes to the Sharing page's Download your data card (the menu has a Sharing link too)
    const download = ready.wrapper.findAll('a').find((a) => a.text() === 'download the database')
    expect(download?.attributes('href')).toBe('/sharing')
    ready.wrapper.unmount()

    const addon = {
      id: 'update.addon',
      title: 'Plate Recognizer add-on',
      status: 'error' as const,
      detail: "The Plate Recognizer add-on is installed, and an update doesn't rebuild it.",
      fix: { kind: 'hint' as const, text: 'Run the full installer by hand (bash script/tmsetup.sh).', external: false },
    }
    const blocked = await page(updateState({ offer: STABLE_OFFER, checks: [addon], can_start: false }))
    expect(updateButton(blocked.wrapper)?.attributes('disabled')).toBeDefined()
    expect(blocked.wrapper.text()).toContain('Problem: Plate Recognizer add-on')
    expect(blocked.wrapper.text()).toContain('Run the full installer by hand (bash script/tmsetup.sh).')
    blocked.wrapper.unmount()

    const modified = {
      id: 'update.modified',
      title: 'Installed files changed',
      status: 'warn' as const,
      detail: 'Files in the installed version were changed by hand. An update replaces them.',
    }
    const warned = await page(updateState({ offer: STABLE_OFFER, checks: [modified], can_start: true }))
    expect(updateButton(warned.wrapper)?.attributes('disabled')).toBeUndefined()
    expect(warned.wrapper.text()).toContain('Warning: Installed files changed')
  })

  it('asks before it starts, then posts the offered channel and commit and nothing else', async () => {
    let state = updateState({ offer: STABLE_OFFER })
    const { api, wrapper } = await page(() => state, {
      [START]: () => {
        state = updateState({ offer: STABLE_OFFER, run: updateRun() }) // fake mode answers with the run itself
        return json(202, state)
      },
    })
    await updateButton(wrapper)!.trigger('click')
    expect(dialogText()).toContain(CONFIRM_TEXT)
    expect(posts(api.sent)).toEqual([])
    await clickInDialog('Start the update')
    expect(posts(api.sent)).toEqual([
      { method: 'POST', path: '/api/v1/update/start', body: { channel: 'stable', commit: STABLE_OFFER.commit } },
    ])
    expect(wrapper.text()).toContain('You can close this page. The update carries on.')
    expect(updateButton(wrapper)).toBeUndefined() // one thing at a time
  })

  it("shows the start's refusal beside the button", async () => {
    const { wrapper } = await page(updateState({ offer: STABLE_OFFER }), {
      [START]: apiError(409, 'stale_check', "That isn't the version the last check found. Check again."),
    })
    await updateButton(wrapper)!.trigger('click')
    await clickInDialog('Start the update')
    expect(wrapper.find('.v-alert').text()).toContain("That isn't the version the last check found. Check again.")
  })

  it('follows the run that is there when a start is refused because one is running', async () => {
    let state = updateState({ offer: STABLE_OFFER })
    const { wrapper } = await page(() => state, {
      [START]: () => {
        state = updateState({ run: updateRun() }) // another tab's start got there first
        return apiError(409, 'update_running', 'An update is already running.')
      },
    })
    await updateButton(wrapper)!.trigger('click')
    await clickInDialog('Start the update')
    expect(wrapper.find('h2').text()).toBe('Updating to 0.8.1')
    expect(wrapper.findAll('[data-stage]').length).toBeGreaterThan(0)
    expect(updateButton(wrapper)).toBeUndefined()
  })

  it('sends one start for a double press', async () => {
    let answer: (response: Response) => void = () => {}
    const { api, wrapper } = await page(updateState({ offer: STABLE_OFFER }), {
      [START]: () => new Promise<Response>((resolve) => (answer = resolve)),
    })
    await updateButton(wrapper)!.trigger('click')
    await clickInDialog('Start the update')
    await updateButton(wrapper)!.trigger('click')
    await clickInDialog('Start the update')
    expect(posts(api.sent).length).toBe(1)
    answer(json(202, updateState({ run: updateRun() })))
  })

  it("draws the stages from the answer, a later version's ids included", async () => {
    const run = updateRun({
      stage: 'calibrate_radar',
      stages: [
        { id: 'fetch', started_at: 'a', finished_at: 'b' },
        { id: 'calibrate_radar', started_at: 'b', finished_at: null },
      ],
    })
    const { wrapper } = await page(updateState({ run }))
    const rows = wrapper.findAll('[data-stage]').map((row) => row.text().replace(/\s+/g, ' ').trim())
    expect(rows).toEqual(['Done: Download', 'Running: calibrate_radar'])

    wrapper.unmount()
    const known = await page(updateState({ run: updateRun() })) // in Prepare
    const lines = known.wrapper.findAll('[data-stage]').map((row) => row.text().replace(/\s+/g, ' ').trim())
    expect(lines).toEqual([
      'Done: Download',
      'Done: Check',
      'Running: Prepare',
      'Not started: Build',
      'Not started: Restore point',
      'Not started: Switch (the device stops answering for about 3 minutes)',
      'Not started: Verify',
      'Not started: Clean up',
    ])
    expect(known.wrapper.text()).toContain('Updating to 0.8.1')
  })

  it('puts the switch and restart notes on those rows only, whatever state the row is in', async () => {
    const note = '(the device stops answering for about 3 minutes)'
    const restart = '(a few more minutes while it restarts)'
    const done = { started_at: 'a', finished_at: 'b' }
    const rowsOf = async (run: ReturnType<typeof updateRun>) => {
      const { wrapper } = await page(updateState({ run }))
      const rows = wrapper.findAll('[data-stage]').map((row) => row.text().replace(/\s+/g, ' ').trim())
      wrapper.unmount()
      return rows
    }
    const switching = await rowsOf(
      updateRun({ stage: 'switch', stages: [{ id: 'prepare', ...done }, { id: 'switch', started_at: 'b', finished_at: null }] }),
    )
    expect(switching).toContain(`Running: Switch ${note}`)
    expect(switching.filter((row) => row.includes('('))).toEqual([`Running: Switch ${note}`])
    const restarting = await rowsOf(
      updateRun({
        stage: 'reboot',
        stages: [{ id: 'switch', ...done }, { id: 'reboot', started_at: 'b', finished_at: null }],
      }),
    )
    expect(restarting).toContain(`Done: Switch ${note}`)
    expect(restarting).toContain(`Running: Restart ${restart}`)
    expect(restarting.slice(-2)).toEqual(['Not started: Verify', 'Not started: Clean up']) // what follows a restart
  })

  it('draws a run read over an older run\'s final file as running, with no stages', async () => {
    const { wrapper } = await page(updateState({ run: { status: 'running', readable: true, stages: [] } }))
    expect(wrapper.find('h2').text()).toBe('An update is running')
    expect(wrapper.text()).toContain('You can close this page. The update carries on.')
    expect(wrapper.findAll('[data-stage]')).toEqual([])
  })

  it("says only that an update is running when this version can't read its state", async () => {
    const { wrapper } = await page(updateState({ run: { status: 'running', readable: false, stages: [] } }))
    expect(wrapper.find('h2').text()).toBe('An update is running')
    expect(wrapper.text()).toContain("This version of the page can't read its stages. The log below shows how it goes.")
    expect(wrapper.text()).toContain('Log')
  })

  it('names a Stable target by its tag until the device knows its version', async () => {
    const fetching = updateRun({
      stage: 'fetch',
      to_version: null,
      stages: [{ id: 'fetch', started_at: 'a', finished_at: null }],
    })
    const { wrapper } = await page(updateState({ run: fetching }))
    expect(wrapper.find('h2').text()).toBe('Updating to 0.8.1')
  })

  it("draws only that the update is starting while the start is pending, nothing of an older run", async () => {
    const older = updateRun({
      run_id: '20261120T090000Z',
      status: 'failed',
      to_version: '0.7.9',
      stage: 'images',
      reason: 'build_failed',
      stages: [{ id: 'images', started_at: 'a', finished_at: 'b' }],
    })
    const pending = { run_id: '20261126T120500Z', status: 'starting' as const, reason: null }
    const { wrapper } = await page(updateState({ run: older, started: pending }))
    expect(wrapper.find('h2').text()).toBe('Starting the update')
    expect(wrapper.text()).toContain('You can close this page. The update carries on.')
    expect(wrapper.findAll('[data-stage]')).toEqual([])
    expect(wrapper.text()).not.toContain('0.7.9')
    expect(wrapper.text()).not.toContain('Last update')
  })

  it('shows the away notice once while a start is pending with no run yet', async () => {
    vi.useFakeTimers()
    let away = false
    const pending = updateState({ started: { run_id: 'r', status: 'starting', reason: null } })
    signedIn(ADMIN, {
      [UPDATE]: () => (away ? Promise.reject(new TypeError('Failed to fetch')) : json(200, pending)),
    })
    const { wrapper } = await mountApp('/update')
    await vi.advanceTimersByTimeAsync(0)
    expect(wrapper.text()).not.toContain(AWAY)
    away = true
    await vi.advanceTimersByTimeAsync(UPDATE_POLL_MS)
    expect(wrapper.text().split(AWAY).length - 1).toBe(1)
    expect(wrapper.text().split('You can close this page.').length - 1).toBe(1)
  })

  it('shows a notice, not an error, while the device is away, and recovers', async () => {
    vi.useFakeTimers()
    let away = false
    const switching = updateRun({
      stage: 'switch',
      stages: [
        { id: 'prepare', started_at: 'a', finished_at: 'b' },
        { id: 'switch', started_at: 'b', finished_at: null },
      ],
    })
    let state = updateState({ run: switching })
    const api = signedIn(ADMIN, {
      [UPDATE]: () => (away ? Promise.reject(new TypeError('Failed to fetch')) : json(200, state)),
    })
    const { wrapper } = await mountApp('/update')
    await vi.advanceTimersByTimeAsync(0)
    expect(wrapper.text()).not.toContain(AWAY)
    away = true
    await vi.advanceTimersByTimeAsync(UPDATE_POLL_MS)
    expect(wrapper.text()).toContain(AWAY)
    expect(wrapper.find('.v-alert--type-error, .v-alert.text-error').exists()).toBe(false)
    expect(wrapper.text()).toContain('Switch') // the last stages stay
    const asked = api.sent.filter((r) => r.path === '/api/v1/update').length
    await vi.advanceTimersByTimeAsync(3 * UPDATE_POLL_MS)
    expect(api.sent.filter((r) => r.path === '/api/v1/update').length).toBeGreaterThan(asked)
    away = false
    state = updateState({ run: updateRun({ stage: 'health' }) })
    await vi.advanceTimersByTimeAsync(UPDATE_POLL_MS)
    expect(wrapper.text()).not.toContain(AWAY)
  })

  it('offers Reload after an update that ended ok while the page was open', async () => {
    vi.useFakeTimers()
    let state = updateState({ run: updateRun({ stage: 'health' }) })
    const { wrapper } = await page(() => state)
    const done = updateRun({ status: 'ok', stage: 'cleanup', finished_at: '2026-11-26T12:40:00Z' })
    state = updateState({ installed: { ...updateState().installed, version: '0.8.1' }, run: done })
    await vi.advanceTimersByTimeAsync(UPDATE_POLL_MS)
    expect(wrapper.text()).toContain('Updated to 0.8.1.')
    expect(wrapper.text()).toContain('This page is from the version before.')
    expect(button(wrapper, 'Reload').exists()).toBe(true)
    wrapper.unmount()

    // Opened after the update: the page is already the new version's
    const later = await page(state)
    expect(later.wrapper.text()).toContain('Updated to 0.8.1.')
    expect(later.wrapper.text()).not.toContain('This page is from the version before.')
    expect(later.wrapper.findAll('button').some((b) => b.text().trim() === 'Reload')).toBe(false)
  })

  it("offers Try again with the run's own target after a failure, and Finish the update after a cut-off switch", async () => {
    const target = { channel: 'development', commit: '7'.repeat(40) }
    const failed = updateRun({
      status: 'failed',
      channel: 'development',
      to_version: null,
      to_commit: target.commit,
      to_tag: null,
      stage: 'images',
      stages: FAILED_STAGES,
      reason: 'build_failed',
      detail: 'frigate',
    })
    const tried = await page(updateState({ run: failed, retry: target }), {
      [START]: json(202, updateState({ run: updateRun() })),
    })
    expect(tried.wrapper.text()).toContain("The new version's images didn't build")
    expect(tried.wrapper.text()).toContain('Detail: frigate')
    await click(tried.wrapper, 'Try again')
    expect(dialogText()).toContain(CONFIRM_TEXT)
    await clickInDialog('Start the update')
    expect(posts(tried.api.sent)).toEqual([{ method: 'POST', path: '/api/v1/update/start', body: target }])
    tried.wrapper.unmount()

    // No usable target: no Try again
    const stuck = await page(updateState({ run: failed, retry: null }))
    expect(stuck.wrapper.findAll('button').some((b) => b.text().trim() === 'Try again')).toBe(false)
    stuck.wrapper.unmount()

    const interrupted = await page(updateState({ run: updateRun({ status: 'interrupted', stage: 'images' }), retry: target }))
    expect(interrupted.wrapper.text()).toContain('The update stopped before it finished (a restart or a power cut).')
    expect(interrupted.wrapper.text()).toContain('Nothing was changed.')
    expect(button(interrupted.wrapper, 'Try again').exists()).toBe(true)
    interrupted.wrapper.unmount()

    const late = await page(updateState({ run: updateRun({ status: 'interrupted', stage: 'health' }), retry: target }))
    expect(late.wrapper.text()).not.toContain('Nothing was changed.')
    late.wrapper.unmount()

    const cut = await page(updateState({ run: updateRun({ status: 'cut_off', stage: 'switch' }), retry: target }), {
      [START]: json(202, updateState({ run: updateRun({ stage: 'switch' }) })),
    })
    expect(cut.wrapper.text()).toContain('The update was cut off while it was switching.')
    await click(cut.wrapper, 'Finish the update')
    expect(posts(cut.api.sent)).toEqual([{ method: 'POST', path: '/api/v1/update/start', body: target }])
  })

  it('marks the last row of a failed run failed, though both writers give it a finish time', async () => {
    const rowsOf = async (run: ReturnType<typeof updateRun>) => {
      const { wrapper } = await page(updateState({ run }))
      const rows = wrapper.findAll('[data-stage]').map((row) => row.text().replace(/\s+/g, ' ').trim())
      wrapper.unmount()
      return rows
    }
    // As the device's own fixture holds it (update_state_failed.json): every row finished
    const failed = await rowsOf(
      updateRun({ status: 'failed', stage: 'images', stages: FAILED_STAGES, reason: 'build_failed' }),
    )
    expect(failed).toEqual(['Done: Prepare', 'Failed: Build'])
    // Refused by the job in its check: both rows finished
    const refused = await rowsOf(
      updateRun({
        status: 'failed',
        stage: 'verify',
        reason: 'stale_check',
        stages: [
          { id: 'fetch', started_at: 'a', finished_at: 'b' },
          { id: 'verify', started_at: 'b', finished_at: 'c' },
        ],
      }),
    )
    expect(refused).toEqual(['Done: Download', 'Failed: Check'])
    // Stopped by a restart or a power cut, and cut off in the switch: the unfinished row is stopped
    const interrupted = await rowsOf(updateRun({ status: 'interrupted', stage: 'prepare' }))
    expect(interrupted).toEqual(['Done: Download', 'Done: Check', 'Stopped: Prepare'])
    const cut = await rowsOf(
      updateRun({
        status: 'cut_off',
        stage: 'switch',
        stages: [
          { id: 'images', started_at: 'a', finished_at: 'b' },
          { id: 'switch', started_at: 'b', finished_at: null },
        ],
      }),
    )
    expect(cut).toEqual(['Done: Build', 'Stopped: Switch (the device stops answering for about 3 minutes)'])
  })

  it.each([
    ['needs_manual_update', false],
    ['build_failed', true],
    ['flux_capacitor', true],
  ])('offers Try again after a run that failed with %s only when trying again can help', async (reason, offered) => {
    const target = { channel: 'stable', commit: STABLE_OFFER.commit }
    const run = updateRun({ status: 'failed', stage: 'images', stages: FAILED_STAGES, reason })
    const { wrapper } = await page(updateState({ run, retry: target }))
    expect(wrapper.findAll('button').some((b) => b.text().trim() === 'Try again')).toBe(offered)
  })

  it('makes Check the main button only while there is nothing else to press', async () => {
    const filled = (wrapper: VueWrapper) => button(wrapper, 'Check for updates').classes().includes('v-btn--variant-flat')
    const plain = await page(updateState())
    expect(filled(plain.wrapper)).toBe(true)
    plain.wrapper.unmount()

    const offered = await page(updateState({ offer: STABLE_OFFER }))
    expect(filled(offered.wrapper)).toBe(false)
    offered.wrapper.unmount()

    const target = { channel: 'stable', commit: STABLE_OFFER.commit }
    const cut = await page(updateState({ run: updateRun({ status: 'cut_off', stage: 'switch' }), retry: target }))
    expect(filled(cut.wrapper)).toBe(false)
  })

  it('says another install is running when the start was refused as busy', async () => {
    const busy = await page(updateState({ offer: STABLE_OFFER, started: { run_id: 'r', status: 'failed', reason: 'busy' } }))
    expect(busy.wrapper.text()).toContain('Another install or update is running on this device. Wait for it to end.')
    expect(busy.wrapper.find('h2').text()).toBe("The update didn't start")
    busy.wrapper.unmount()

    const other = await page(updateState({ offer: STABLE_OFFER, started: { run_id: 'r', status: 'failed', reason: 'error' } }))
    expect(other.wrapper.text()).toContain('The update failed. The log below has the details.')
    expect(other.wrapper.findAll('h2').map((h) => h.text())).not.toContain('Last update') // no run: the refusal alone
  })

  it.each(['busy', 'error'])(
    'keeps the way to finish or retry the last run when a start is refused (%s)',
    async (reason) => {
      const target = { channel: 'stable', commit: STABLE_OFFER.commit }
      const refused = { run_id: '20261126T130000Z', status: 'failed' as const, reason }
      const refusal =
        reason === 'busy'
          ? 'Another install or update is running on this device. Wait for it to end.'
          : 'The update failed. The log below has the details.'

      // A switch that was cut off: Finish the update pressed, and the start refused
      const cut = await page(
        updateState({ run: updateRun({ status: 'cut_off', stage: 'switch' }), retry: target, started: refused }),
        { [START]: json(202, updateState({ run: updateRun({ stage: 'switch' }) })) },
      )
      expect(cut.wrapper.text()).toContain(refusal)
      expect(cut.wrapper.text()).toContain('The update was cut off while it was switching.')
      expect(cut.wrapper.findAll('[data-stage]').length).toBeGreaterThan(0) // the run's stages still show
      await click(cut.wrapper, 'Finish the update')
      expect(posts(cut.api.sent)).toEqual([{ method: 'POST', path: '/api/v1/update/start', body: target }])
      cut.wrapper.unmount()

      // A run that failed: Try again pressed, and the start refused
      const failed = updateRun({ status: 'failed', stage: 'images', stages: FAILED_STAGES, reason: 'build_failed' })
      const again = await page(updateState({ run: failed, retry: target, started: refused }))
      expect(again.wrapper.text()).toContain(refusal)
      expect(again.wrapper.text()).toContain("The new version's images didn't build")
      expect(button(again.wrapper, 'Try again').exists()).toBe(true)
    },
  )

  it('loads the log only when its panel is opened', async () => {
    const { api, wrapper } = await page(updateState({ run: updateRun({ status: 'ok', stage: 'cleanup' }) }), {
      [LOG]: { run_id: '20261126T120500Z', job: ['systemd: Started tm-job-update.service.'], log: ['fetch: done'] },
    })
    const logs = () => api.sent.filter((r) => r.path === '/api/v1/update/log').length
    expect(logs()).toBe(0)
    await click(wrapper, 'Log')
    expect(logs()).toBe(1)
    expect(wrapper.text()).toContain('fetch: done')
    expect(wrapper.text()).toContain('systemd: Started tm-job-update.service.')
    expect(wrapper.find('[aria-label="Copy the log"]').exists()).toBe(true)
  })
})
