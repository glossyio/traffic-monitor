// The sharing form: the server, the token, the three choices, the notice, and Save (PUT /sharing).
import { flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it } from 'vitest'
import SharingForm from '../src/modules/sharing/SharingForm.vue'
import { SHARING_ON, apiError, fakeApi, json, sharingState } from './fake-api'
import { button, click, clickInDialog, dialogText, field, mountAlone, typeInto } from './mount'

const PUT = 'PUT /api/v1/sharing'
const NOTICE = 'GET /api/v1/sharing/notice'
const OWN = 'own.example.invalid'
const MAP_TEXT = 'A point rounded to about 100 m, and nothing else about where the device is.'
const OWN_WORDS = "Your own server is yours to run. The notice below doesn't apply to it"

const TOKEN_SET = { ...SHARING_ON.token!, set: true, ends_with: '0001' }

// What a save sends: the last PUT's body
function body(api: ReturnType<typeof fakeApi>) {
  return api.sent.filter((r) => r.method === 'PUT').at(-1)?.body
}

function mountForm(changes: Partial<typeof SHARING_ON> = {}, props: Record<string, unknown> = {}) {
  return mountAlone(SharingForm, { state: sharingState(changes), ...props })
}

const checked = (wrapper: ReturnType<typeof mountForm>, label: string) => field(wrapper, label).element.checked
const disabled = (wrapper: ReturnType<typeof mountForm>, label: string) => field(wrapper, label).element.disabled

describe('the sharing form', () => {
  beforeEach(() => document.body.replaceChildren())

  it('starts with every box unchecked on a new device', () => {
    const wrapper = mountForm()
    expect(checked(wrapper, 'Share data')).toBe(false)
    expect(checked(wrapper, 'Share the exact location')).toBe(false)
    expect(wrapper.text()).not.toContain("I've read the notice") // nothing to read until sharing is on
  })

  it('disables Share data until a token is set', () => {
    const without = mountForm()
    expect(disabled(without, 'Share data')).toBe(true)
    expect(without.text()).toContain('Set the access token first.')
    const withToken = mountForm({ token: TOKEN_SET })
    expect(disabled(withToken, 'Share data')).toBe(false)
    expect(withToken.text()).not.toContain('Set the access token first.')
  })

  it('shows the token under its own heading, with the restart note', () => {
    const wrapper = mountForm()
    expect(wrapper.find('#token').exists()).toBe(true)
    expect(wrapper.text()).toContain(
      'The server gives each device a token. Saving it restarts Node-RED, which takes about thirty seconds.',
    )
  })

  it('needs the notice read before turning sharing on', async () => {
    const api = fakeApi({ [PUT]: json(200, SHARING_ON), [NOTICE]: { version: '1', markdown: 'The notice.' } })
    const wrapper = mountForm({ token: TOKEN_SET })
    await field(wrapper, 'Share data').setValue(true)
    expect(wrapper.text()).toContain('Read the sharing notice (version 1)')
    expect(button(wrapper, 'Save').attributes('disabled')).toBeDefined()

    await field(wrapper, "I've read the notice").setValue(true)
    expect(button(wrapper, 'Save').attributes('disabled')).toBeUndefined()
    await click(wrapper, 'Save')
    expect(body(api)).toEqual({
      target: 'maintainer',
      host: null,
      protocol: 'https',
      port: null,
      enabled: true,
      exact_location: false,
      public_map: 'none',
      notice_version: '1',
    })
    expect(wrapper.emitted('saved')?.[0]).toEqual([SHARING_ON])
  })

  it('says Saved, and stops saying it once something is edited', async () => {
    fakeApi({ [PUT]: json(200, { ...SHARING_ON, protocol: 'http' }) })
    const wrapper = mountForm(SHARING_ON)
    await click(wrapper, 'Save')
    expect(wrapper.text()).toContain('Saved.')
    await field(wrapper, 'Share data').setValue(false)
    expect(wrapper.text()).not.toContain('Saved.')
  })

  it('opens the notice from the server when asked', async () => {
    fakeApi({ [NOTICE]: { version: '1', markdown: '# What is shared\n\nCounts and speeds.' } })
    const wrapper = mountForm({ token: TOKEN_SET })
    await field(wrapper, 'Share data').setValue(true)
    await click(wrapper, 'Read the sharing notice (version 1)')
    expect(wrapper.text()).toContain('Counts and speeds.')
  })

  it('offers the notice when it has changed, without needing it for a save that only keeps what is shared', () => {
    const changed = mountForm({ ...SHARING_ON, notice_current: false })
    expect(changed.text()).toContain("I've read the notice")
    expect(checked(changed, "I've read the notice")).toBe(false)
    expect(button(changed, 'Save').attributes('disabled')).toBeUndefined()
  })

  it('shows no notice box when the notice is current and nothing is added', () => {
    const current = mountForm(SHARING_ON)
    expect(current.text()).not.toContain("I've read the notice")
    expect(button(current, 'Save').attributes('disabled')).toBeUndefined()
  })

  it('sends the current notice version when the offered box is ticked, so the grants are recorded again', async () => {
    const api = fakeApi({ [PUT]: json(200, SHARING_ON) })
    const wrapper = mountForm({ ...SHARING_ON, notice_current: false })
    await field(wrapper, "I've read the notice").setValue(true)
    await click(wrapper, 'Save')
    expect(body(api)).toMatchObject({ enabled: true, exact_location: false, notice_version: '1' })
  })

  it('never brings the notice box back ticked after it was hidden', async () => {
    const api = fakeApi({ [PUT]: json(200, SHARING_ON) })
    const wrapper = mountForm({ ...SHARING_ON, notice_current: false })
    await field(wrapper, "I've read the notice").setValue(true)
    await field(wrapper, 'Share data').setValue(false)
    expect(wrapper.text()).not.toContain("I've read the notice")
    await field(wrapper, 'Share data').setValue(true)
    expect(checked(wrapper, "I've read the notice")).toBe(false)
    await click(wrapper, 'Save')
    expect(body(api)).toMatchObject({ enabled: true, notice_version: null })
  })

  it('never brings the notice box back ticked after the server is switched away and back', async () => {
    const wrapper = mountForm({ ...SHARING_ON, notice_current: false })
    await field(wrapper, "I've read the notice").setValue(true)
    await field(wrapper, 'Your own ThingsBoard server').setValue()
    expect(wrapper.text()).not.toContain("I've read the notice")
    await field(wrapper, "Traffic Monitor's server (tb.example.invalid)").setValue()
    expect(checked(wrapper, "I've read the notice")).toBe(false)
  })

  it('needs the notice and sends its version for a choice added under a changed notice', async () => {
    const api = fakeApi({ [PUT]: json(200, SHARING_ON) })
    const wrapper = mountForm({ ...SHARING_ON, notice_current: false })
    await field(wrapper, 'Share the exact location').setValue(true)
    expect(button(wrapper, 'Save').attributes('disabled')).toBeDefined()
    await field(wrapper, "I've read the notice").setValue(true)
    expect(button(wrapper, 'Save').attributes('disabled')).toBeUndefined()
    await click(wrapper, 'Save')
    expect(body(api)).toMatchObject({ exact_location: true, notice_version: '1' })
  })

  it('sends no notice version for an offered box left unticked', async () => {
    const api = fakeApi({ [PUT]: json(200, SHARING_ON) })
    const wrapper = mountForm({ ...SHARING_ON, notice_current: false })
    await click(wrapper, 'Save')
    expect(body(api)).toMatchObject({ enabled: true, notice_version: null })
  })

  it('needs the notice only for a choice newly ticked after the notice changed', async () => {
    const wrapper = mountForm({ ...SHARING_ON, notice_current: false })
    await field(wrapper, 'Share the exact location').setValue(true)
    expect(wrapper.text()).toContain("I've read the notice")
    expect(button(wrapper, 'Save').attributes('disabled')).toBeDefined()
    await field(wrapper, 'Share the exact location').setValue(false)
    expect(button(wrapper, 'Save').attributes('disabled')).toBeUndefined() // still offered, no longer needed
  })

  it('withdraws a choice under a changed notice without reading it', async () => {
    const api = fakeApi({ [PUT]: json(200, SHARING_ON) })
    const wrapper = mountForm({
      ...SHARING_ON,
      notice_current: false,
      exact_location: { granted: true, at: '2026-11-02T12:00:00+00:00', notice_version: '1' },
    })
    await field(wrapper, 'Share the exact location').setValue(false)
    expect(button(wrapper, 'Save').attributes('disabled')).toBeUndefined()
    await click(wrapper, 'Save')
    expect(body(api)).toMatchObject({ enabled: true, exact_location: false, notice_version: null })
  })

  it('names the token\'s Save so it is not taken for the form\'s', () => {
    const wrapper = mountForm(SHARING_ON)
    expect(button(wrapper, 'Save token').exists()).toBe(true)
    expect(button(wrapper, 'Save').exists()).toBe(true)
  })

  it('keeps "On since" for Share data after the server is changed, and drops it for the other choices', async () => {
    const wrapper = mountForm({
      ...SHARING_ON,
      exact_location: { granted: true, at: new Date(Date.now() - 3 * 86_400_000).toISOString(), notice_version: '1' },
      share_data: { granted: true, at: new Date(Date.now() - 5 * 86_400_000).toISOString(), notice_version: '1' },
    })
    expect(wrapper.text()).toContain('On since 3 days ago')
    await field(wrapper, 'Your own ThingsBoard server').setValue()
    expect(wrapper.text()).toContain('On since 5 days ago')
    expect(wrapper.text()).not.toContain('On since 3 days ago')
  })

  it('disables the exact location until Share data is on, and over http, and says why', () => {
    const off = mountForm({ token: TOKEN_SET })
    expect(disabled(off, 'Share the exact location')).toBe(true)
    expect(off.text()).toContain('Turn on Share data first.')

    const http = mountForm({ ...SHARING_ON, target: 'own', host: OWN, protocol: 'http' })
    expect(disabled(http, 'Share the exact location')).toBe(true)
    expect(http.text()).toContain('The exact location is only sent over https.')
  })

  it('allows the exact location over https', () => {
    const https = mountForm({ ...SHARING_ON, target: 'own', host: OWN })
    expect(disabled(https, 'Share the exact location')).toBe(false)
  })

  it('says nothing is sent until the place has a location', () => {
    expect(mountForm({ ...SHARING_ON, has_location: false }).text()).toContain(
      'Nothing is sent until the place in use has a location.',
    )
    expect(mountForm(SHARING_ON).text()).not.toContain('Nothing is sent until')
  })

  it('shows the map as not live', () => {
    const wrapper = mountForm(SHARING_ON)
    expect(disabled(wrapper, 'Show this device on the public map')).toBe(true)
    expect(wrapper.text()).toContain('Not live yet.')
    const live = mountForm({ ...SHARING_ON, public_map_live: true })
    expect(disabled(live, 'Show this device on the public map')).toBe(false)
    expect(live.text()).toContain(MAP_TEXT)
  })

  it('shows an example for each choice, on request', async () => {
    const wrapper = mountForm(SHARING_ON)
    expect(wrapper.findAll('pre')).toHaveLength(0)
    const examples = wrapper.findAll('button').filter((b) => b.text() === 'See an example')
    expect(examples).toHaveLength(3)
    await examples[1].trigger('click')
    expect(wrapper.find('pre').text()).toContain('45.52252')
    expect(wrapper.find('pre').text()).toContain('-122.6912')
  })

  it('hides the notice and the map for your own server and shows the responsibility text', async () => {
    const wrapper = mountForm(SHARING_ON)
    expect(wrapper.text()).toContain('Show this device on the public map')
    expect(wrapper.text()).not.toContain(OWN_WORDS)

    await field(wrapper, 'Your own ThingsBoard server').setValue()
    expect(wrapper.text()).toContain(OWN_WORDS)
    expect(wrapper.text()).toContain('is your responsibility.')
    expect(wrapper.text()).not.toContain('Show this device on the public map')
    expect(wrapper.text()).not.toContain('Read the sharing notice')
    expect(wrapper.text()).not.toContain("I've read the notice")
    field(wrapper, 'Host') // the own server's fields are there
  })

  it('sends the own server as typed, without a notice', async () => {
    const api = fakeApi({ [PUT]: json(200, SHARING_ON) })
    const wrapper = mountForm({ token: TOKEN_SET })
    await field(wrapper, 'Your own ThingsBoard server').setValue()
    await typeInto(field(wrapper, 'Host').element, ` ${OWN} `)
    await typeInto(field(wrapper, 'Port (optional)').element, '8443')
    await field(wrapper, 'Share data').setValue(true)
    await click(wrapper, 'Save')
    expect(body(api)).toEqual({
      target: 'own',
      host: OWN,
      protocol: 'https',
      port: 8443,
      enabled: true,
      exact_location: false,
      public_map: 'none',
      notice_version: null,
    })
  })

  it('asks before changing the server while the exact location is on', async () => {
    const api = fakeApi({ [PUT]: json(200, SHARING_ON) })
    const wrapper = mountForm({
      ...SHARING_ON,
      exact_location: { granted: true, at: '2026-11-02T12:00:00+00:00', notice_version: '1' },
    })
    expect(checked(wrapper, 'Share the exact location')).toBe(true)
    await field(wrapper, 'Your own ThingsBoard server').setValue()
    await typeInto(field(wrapper, 'Host').element, OWN)
    await click(wrapper, 'Save')
    expect(dialogText()).toContain(
      'Changing the server turns off the exact location and the public map. You can turn them on again for the new server.',
    )
    expect(api.sent.filter((r) => r.method === 'PUT')).toHaveLength(0)

    await clickInDialog('Change the server')
    expect(body(api)).toMatchObject({ target: 'own', host: OWN, enabled: true, exact_location: false, public_map: 'none' })
  })

  it('does not ask when no server changes', async () => {
    const api = fakeApi({ [PUT]: json(200, SHARING_ON) })
    const wrapper = mountForm({
      ...SHARING_ON,
      exact_location: { granted: true, at: '2026-11-02T12:00:00+00:00', notice_version: '1' },
    })
    await click(wrapper, 'Save')
    expect(dialogText()).toBe('')
    expect(body(api)).toMatchObject({ exact_location: true })
  })

  it('withdraws by unticking and saving', async () => {
    const api = fakeApi({ [PUT]: json(200, SHARING_ON) })
    const wrapper = mountForm({
      ...SHARING_ON,
      exact_location: { granted: true, at: '2026-11-02T12:00:00+00:00', notice_version: '1' },
    })
    await field(wrapper, 'Share the exact location').setValue(false)
    await click(wrapper, 'Save')
    expect(body(api)).toMatchObject({ enabled: true, exact_location: false, notice_version: null })
  })

  it('withdraws the exact location and the map when Share data is unticked', async () => {
    const api = fakeApi({ [PUT]: json(200, SHARING_ON) })
    const wrapper = mountForm({
      ...SHARING_ON,
      public_map_live: true,
      exact_location: { granted: true, at: '2026-11-02T12:00:00+00:00', notice_version: '1' },
      public_map: { granted: true, at: '2026-11-02T12:00:00+00:00', notice_version: '1' },
    })
    await field(wrapper, 'Share data').setValue(false)
    expect(checked(wrapper, 'Share the exact location')).toBe(false)
    await click(wrapper, 'Save')
    expect(body(api)).toMatchObject({ enabled: false, exact_location: false, public_map: 'none' })
  })

  it('says since when a choice is on', () => {
    const wrapper = mountForm({
      ...SHARING_ON,
      share_data: { granted: true, at: new Date(Date.now() - 3 * 86_400_000).toISOString(), notice_version: '1' },
    })
    expect(wrapper.text()).toContain('On since 3 days ago')
  })

  it('shows the reason for a refused save and keeps what was typed', async () => {
    fakeApi({ [PUT]: apiError(409, 'no_token', 'Set the access token first.') })
    const wrapper = mountForm(SHARING_ON)
    await click(wrapper, 'Save')
    expect(wrapper.text()).toContain('Set the access token first.')
    expect(wrapper.emitted('saved')).toBeUndefined()
  })

  it('shows a host the API refused under the field', async () => {
    const refusal = new Response(
      JSON.stringify({ error: { code: 'validation', message: "Enter the server's name or address, with no https:// and no path.", detail: { field: 'host' } } }),
      { status: 422, headers: { 'Content-Type': 'application/json' } },
    )
    fakeApi({ [PUT]: refusal })
    const wrapper = mountForm(SHARING_ON)
    await field(wrapper, 'Your own ThingsBoard server').setValue()
    await typeInto(field(wrapper, 'Host').element, 'https://x')
    await click(wrapper, 'Save')
    expect(wrapper.find('.v-input--error').text()).toContain("Enter the server's name or address")
  })

  it('says the file changed and asks the page to load it again', async () => {
    const message = 'config.yml changed while you were editing. Reload and try again.'
    fakeApi({ [PUT]: apiError(409, 'config_changed', message) })
    const wrapper = mountForm(SHARING_ON)
    await click(wrapper, 'Save')
    await flushPromises()
    expect(wrapper.text()).toContain(message)
    expect(wrapper.emitted('reload')).toHaveLength(1)
  })

  it('reads "Save and finish" on the first run', () => {
    expect(button(mountForm({}, { firstRun: true }), 'Save and finish').exists()).toBe(true)
  })
})
