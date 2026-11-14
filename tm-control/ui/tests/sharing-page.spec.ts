// The Sharing page: what this device shares and with which server, for everyone, and the form for admins.
import type { VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ADMIN, SHARING_ON, VIEWER, apiError, json, sharingState, signedIn, type SharingState } from './fake-api'
import { click, field, mountApp } from './mount'

const SHARING = 'GET /api/v1/sharing'
const SAVE = 'PUT /api/v1/sharing'
const REVIEWED = 'POST /api/v1/sharing/reviewed'
const REVIEW_TEXT =
  'This device was sharing before the sharing choices existed. It keeps sharing data with the location as the ' +
  'database stores it. Review the choices.'

function menu(wrapper: VueWrapper) {
  return wrapper.findAll('.v-navigation-drawer .v-list-item-title').map((t) => t.text().trim())
}

// What a viewer is sent: no token, and the host only because it is the maintainer's
const FOR_VIEWER: SharingState = { ...SHARING_ON, token: null, writable: false }

// The summary card's value for a label
function fact(wrapper: VueWrapper, label: string) {
  const labelBox = wrapper.findAll('.v-card .text-body-2').find((d) => d.text() === label)
  expect(labelBox, `a summary line "${label}"`).toBeDefined()
  return labelBox!.element.nextElementSibling?.textContent?.trim()
}

describe('the Sharing page', () => {
  beforeEach(() => document.body.replaceChildren())
  afterEach(() => vi.useRealTimers())

  it('is in the menu for everyone and shows a viewer no form', async () => {
    signedIn(VIEWER, { [SHARING]: FOR_VIEWER })
    const viewer = await mountApp('/sharing')
    expect(menu(viewer.wrapper)).toContain('Sharing')
    expect(viewer.wrapper.find('h1').text()).toBe('Sharing')
    expect(viewer.wrapper.text()).toContain('An administrator chooses what this device shares.')
    expect(viewer.wrapper.find('input[type="checkbox"]').exists()).toBe(false)
    expect(viewer.wrapper.findAll('button').some((b) => b.text() === 'Save')).toBe(false)
    viewer.wrapper.unmount()

    signedIn(ADMIN, { [SHARING]: SHARING_ON })
    const admin = await mountApp('/sharing')
    expect(menu(admin.wrapper)).toContain('Sharing')
    expect(admin.wrapper.text()).not.toContain('An administrator chooses')
    field(admin.wrapper, 'Share data')
  })

  it('shows what is shared in the summary', async () => {
    signedIn(VIEWER, { [SHARING]: FOR_VIEWER })
    const data = (await mountApp('/sharing')).wrapper
    expect(fact(data, 'Sharing')).toBe('Data')
    expect(fact(data, 'Server')).toBe("Traffic Monitor's server")
    expect(fact(data, 'Location sent')).toBe('As the database stores it')
    data.unmount()

    const exact = { granted: true, at: '2026-11-02T12:00:00+00:00', notice_version: '1' }
    signedIn(VIEWER, { [SHARING]: { ...FOR_VIEWER, exact_location: exact } })
    const both = (await mountApp('/sharing')).wrapper
    expect(fact(both, 'Sharing')).toBe('Data and the exact location')
    expect(fact(both, 'Location sent')).toBe('Exact')
    both.unmount()

    signedIn(VIEWER, { [SHARING]: { ...FOR_VIEWER, target: 'own', host: null } })
    expect(fact((await mountApp('/sharing')).wrapper, 'Server')).toBe('Your own server')
  })

  it('shows a device that was never asked as off, with no server chosen', async () => {
    signedIn(VIEWER, { [SHARING]: { ...sharingState(), token: null, writable: false } })
    const wrapper = (await mountApp('/sharing')).wrapper
    expect(fact(wrapper, 'Sharing')).toBe('Off')
    expect(fact(wrapper, 'Server')).toBe('Not chosen')
    expect(fact(wrapper, 'Server status')).toBe('Off')
  })

  it('asks for a review and clears it', async () => {
    let reviewed = false
    const api = signedIn(ADMIN, {
      [SHARING]: () => json(200, { ...SHARING_ON, review_needed: !reviewed }),
      [REVIEWED]: () => {
        reviewed = true
        return json(204, null)
      },
    })
    const { wrapper } = await mountApp('/sharing')
    expect(wrapper.text()).toContain(REVIEW_TEXT)
    await click(wrapper, "I've reviewed this")
    expect(api.sent.some((r) => r.method === 'POST' && r.path === '/api/v1/sharing/reviewed')).toBe(true)
    expect(wrapper.text()).not.toContain(REVIEW_TEXT)
  })

  it('shows a viewer the review notice without the button', async () => {
    signedIn(VIEWER, { [SHARING]: { ...FOR_VIEWER, review_needed: true } })
    const { wrapper } = await mountApp('/sharing')
    expect(wrapper.text()).toContain(REVIEW_TEXT)
    expect(wrapper.findAll('button').some((b) => b.text() === "I've reviewed this")).toBe(false)
  })

  it('shows the API error and a way to try again when the state cannot be read', async () => {
    signedIn(ADMIN, { [SHARING]: apiError(500, 'error', 'The device answered with an error (HTTP 500).') })
    const { wrapper } = await mountApp('/sharing')
    expect(wrapper.text()).toContain('The device answered with an error')
    expect(wrapper.findAll('button').some((b) => b.text() === 'Try again')).toBe(true)
    expect(wrapper.find('input[type="checkbox"]').exists()).toBe(false)
  })

  it.each([
    ['refused', null, 'Refused the token'],
    ['rejected', null, 'Refused an upload'],
    ['server_error', null, 'Answered with an error'],
    ['unreachable', null, "Can't be reached"],
    ['waiting', null, 'Waiting for the first upload'],
    ['unknown', null, "Not known: Node-RED didn't answer"],
    ['off', null, 'Off'],
    ['ok', 300, 'Accepted an upload 5 minutes ago'],
    ['stale', 1200, 'No upload accepted since 20 minutes ago'],
    ['stale', null, 'No upload accepted for a while'],
  ] as const)('says how the server answered, to viewers too (%s)', async (state, secondsAgo, words) => {
    const at = secondsAgo === null ? null : new Date(Date.now() - secondsAgo * 1000).toISOString()
    signedIn(VIEWER, { [SHARING]: { ...FOR_VIEWER, server: { state, at } } })
    const { wrapper } = await mountApp('/sharing')
    expect(fact(wrapper, 'Server status')).toBe(words)
  })

  it('checks again after a save until the first upload has an answer', async () => {
    vi.useFakeTimers()
    let reads = 0
    const waiting = { ...SHARING_ON, server: { state: 'waiting', at: null } }
    const accepted = () => ({ ...SHARING_ON, server: { state: 'ok', at: new Date().toISOString() } }) // taken just now
    const api = signedIn(ADMIN, {
      [SHARING]: () => json(200, ++reads === 1 ? waiting : accepted()), // the page's first read, then each check
      [SAVE]: json(200, { ...waiting, protocol: 'http' }), // the form starts again from this, and still says Saved
    })
    const { wrapper } = await mountApp('/sharing')
    const gets = () => api.sent.filter((r) => r.method === 'GET' && r.path === '/api/v1/sharing').length
    await vi.advanceTimersByTimeAsync(30_000)
    expect(gets()).toBe(1) // nothing was saved, so nothing is checked again

    await click(wrapper, 'Save')
    expect(wrapper.text()).toContain('Saved.')
    expect(fact(wrapper, 'Server status')).toBe('Waiting for the first upload')
    await vi.advanceTimersByTimeAsync(5000)
    expect(gets()).toBe(2)
    expect(fact(wrapper, 'Server status')).toBe('Accepted an upload just now')
    await vi.advanceTimersByTimeAsync(30_000)
    expect(gets()).toBe(2) // an answer came, so the checking stopped
  })

  it('stops checking after a minute when the server stays silent', async () => {
    vi.useFakeTimers()
    const waiting = { ...SHARING_ON, server: { state: 'waiting', at: null } }
    const api = signedIn(ADMIN, { [SHARING]: waiting, [SAVE]: json(200, waiting) })
    const { wrapper } = await mountApp('/sharing')
    await click(wrapper, 'Save')
    await vi.advanceTimersByTimeAsync(120_000)
    const gets = api.sent.filter((r) => r.method === 'GET' && r.path === '/api/v1/sharing').length
    expect(gets).toBe(1 + 12) // the first read and one every 5 seconds for a minute
  })

  it('does not check again after a save that turned the upload off', async () => {
    vi.useFakeTimers()
    const off = sharingState({ ...SHARING_ON, enabled: false, server: { state: 'off', at: null } })
    const api = signedIn(ADMIN, { [SHARING]: SHARING_ON, [SAVE]: json(200, off) })
    const { wrapper } = await mountApp('/sharing')
    await field(wrapper, 'Share data').setValue(false)
    await click(wrapper, 'Save')
    await vi.advanceTimersByTimeAsync(30_000)
    expect(api.sent.filter((r) => r.method === 'GET' && r.path === '/api/v1/sharing')).toHaveLength(1)
  })

  it('stops checking when the page is left', async () => {
    vi.useFakeTimers()
    const waiting = { ...SHARING_ON, server: { state: 'waiting', at: null } }
    const api = signedIn(ADMIN, { [SHARING]: waiting, [SAVE]: json(200, waiting) })
    const { wrapper } = await mountApp('/sharing')
    await click(wrapper, 'Save')
    await vi.advanceTimersByTimeAsync(5000)
    const gets = () => api.sent.filter((r) => r.method === 'GET' && r.path === '/api/v1/sharing').length
    expect(gets()).toBe(2)
    wrapper.unmount()
    await vi.advanceTimersByTimeAsync(30_000)
    expect(gets()).toBe(2)
  })

  it('stops checking quietly when a check fails, leaving the form without an error', async () => {
    vi.useFakeTimers()
    let reads = 0
    const waiting = { ...SHARING_ON, server: { state: 'waiting', at: null } }
    const api = signedIn(ADMIN, {
      [SHARING]: () => (++reads === 1 ? json(200, waiting) : apiError(500, 'error', 'The device answered with an error.')),
      [SAVE]: json(200, waiting),
    })
    const { wrapper } = await mountApp('/sharing')
    await click(wrapper, 'Save')
    await vi.advanceTimersByTimeAsync(5000)
    expect(wrapper.text()).not.toContain('The device answered with an error.')
    expect(wrapper.find('.v-alert').exists()).toBe(false)
    expect(wrapper.text()).toContain('Saved.')
    await vi.advanceTimersByTimeAsync(30_000)
    expect(api.sent.filter((r) => r.method === 'GET' && r.path === '/api/v1/sharing')).toHaveLength(2)
  })
})
