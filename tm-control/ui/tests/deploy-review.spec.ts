// The review step before a deploy: what each sensor does, what the database stores, and the result of
// POST /surveys/{id}/deploy, which waits for Node-RED to start the deployments.
import { flushPromises, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { components } from '../src/api/schema'
import DeployReview from '../src/modules/location/DeployReview.vue'
import TimeZonePick from '../src/modules/location/TimeZonePick.vue'
import { apiError, fakeApi, json } from './fake-api'
import { button, click, mountAlone } from './mount'

type PlacesState = components['schemas']['PlacesState']
type SurveyOut = components['schemas']['SurveyOut']
type DeploymentOut = components['schemas']['DeploymentOut']

function place(changes: Partial<SurveyOut>): SurveyOut {
  return {
    id: 'c0ffee01-si',
    description: 'Corner by the park',
    lat: 45.0,
    lon: -122.0,
    status: 'used',
    source: 'ui',
    created_at: '2026-10-01T12:00:00+00:00',
    updated_at: '2026-10-01T12:00:00+00:00',
    headings: [],
    timezone: null,
    stored_lat: 45.0,
    stored_lon: -122.0,
    first_used: 1760000000000,
    last_used: 1761000000000,
    open_count: 0,
    deployment_count: 2,
    imported: false,
    ...changes,
  }
}

const IN_USE = place({
  id: 'a1b2c3d4-si',
  description: 'Front of the school',
  lat: 45.52252,
  lon: -122.6912,
  stored_lat: 45.5,
  stored_lon: -122.7,
  status: 'in_use',
  open_count: 2,
  headings: [
    { sensor_type: 'cameras', sensor_name: 'picam_h265', heading_deg: 0 },
    { sensor_type: 'radars', sensor_name: 'TM_RADAR_SERIAL_PORT_00', heading_deg: null },
  ],
})
// Used before, facing NE then; it has no heading for the radar
const USED = place({ headings: [{ sensor_type: 'cameras', sensor_name: 'picam_h265', heading_deg: 45 }] })

const STATE: PlacesState = {
  precision: '1',
  in_use: IN_USE.id,
  sensors: [
    { sensor_type: 'cameras', sensor_name: 'picam_h265', heading_deg: 0 },
    { sensor_type: 'radars', sensor_name: 'TM_RADAR_SERIAL_PORT_00', heading_deg: null },
  ],
  sharing: 'none',
  surveys: [IN_USE, USED],
  unassigned: null,
  reconcile: 'done',
  nodered: true,
  map: { style_url: 'https://tiles.example.invalid/style' },
  clock_timezone: null,
}

const DEPLOY = 'POST /api/v1/surveys/c0ffee01-si/deploy'
const SET_TIME_ZONE = 'PUT /api/v1/surveys/c0ffee01-si/timezone'

const LIST = ['America/New_York', 'Asia/Tokyo', 'Europe/Berlin']
const CLOCK = 'America/New_York'
const WITH_CLOCK: PlacesState = { ...STATE, clock_timezone: CLOCK }
const DEPLOYED = { deployed_at: 1762000000000, reloaded: true, deployments: [] as DeploymentOut[], previous: [] }

function review(
  changes: Partial<SurveyOut> = {},
  props: Record<string, unknown> = {},
) {
  return mountAlone(DeployReview, {
    place: place({ ...USED, ...changes }),
    state: WITH_CLOCK,
    timeZones: LIST,
    timeZonesError: '',
    ...props,
  })
}

// The time zone control's list, once its box is ticked
async function pickTimeZone(wrapper: VueWrapper, name: string) {
  const box = wrapper.find<HTMLInputElement>('input[type="checkbox"]')
  if (!box.element.checked) await box.setValue(true)
  await wrapper.findComponent({ name: 'VAutocomplete' }).setValue(name)
  await flushPromises()
}

function row(id: string, sensorType: string, sensorName: string, heading: number | null): DeploymentOut {
  return {
    id,
    started: 1762000000000,
    ended: null,
    lat: 45.0,
    lon: -122.0,
    heading_deg: heading,
    pitch_deg: null,
    height_m: null,
    view_distance_m: null,
    mount: null,
    sensor_type: sensorType,
    sensor_name: sensorName,
    location_precision: 1,
  }
}

const ROWS = [
  row('1762000000000-0123abcd-d', 'cameras', 'picam_h265', 45),
  row('1762000000000-4567cdef-d', 'radars', 'TM_RADAR_SERIAL_PORT_00', null),
]

// One sensor's part of the review, found by the sensor's name
function sensorRow(wrapper: VueWrapper, name: string) {
  const found = wrapper.findAll('[data-sensor]').filter((r) => r.attributes('data-sensor') === name)
  expect(found.length, `one review row for ${name}`).toBe(1)
  return found[0]
}

// Choose a heading in a sensor's select, as picking from its menu would
async function choose(wrapper: VueWrapper, name: string, heading: number | null) {
  const index = STATE.sensors.findIndex((sensor) => sensor.sensor_name === name)
  await wrapper.findAllComponents({ name: 'VSelect' })[index].setValue(heading)
  await flushPromises()
}

describe('the deploy review', () => {
  beforeEach(() => document.body.replaceChildren())
  afterEach(() => {
    Reflect.deleteProperty(navigator, 'clipboard')
    Reflect.deleteProperty(window, 'isSecureContext')
  })

  it.each([
    ['planned', 'Deploy here', 'Deploy'],
    ['used', 'Re-deploy here', 'Re-deploy'],
  ] as const)('names itself for a %s place', (status, title, confirm) => {
    const wrapper = mountAlone(DeployReview, { place: place({ status }), state: STATE, timeZones: LIST, timeZonesError: '' })
    expect(wrapper.find('.v-card-title').text()).toBe(title)
    expect(button(wrapper, confirm).exists()).toBe(true)
  })

  it('starts a new deployment for every sensor at a place not in use', async () => {
    const wrapper = mountAlone(DeployReview, { place: USED, state: STATE, timeZones: LIST, timeZonesError: '' })
    expect(wrapper.text()).toContain('Corner by the park')
    expect(wrapper.text()).toContain('c0ffee01-si')
    const camera = sensorRow(wrapper, 'picam_h265')
    expect(camera.text()).toContain('New deployment starts')
    expect(camera.text()).toContain('Was N (0°), now')
    expect(camera.text()).toContain('NE') // the place's own heading, from when it was used
    expect(sensorRow(wrapper, 'TM_RADAR_SERIAL_PORT_00').text()).toContain('New deployment starts')
    expect(wrapper.text()).toContain('Stored in the database: 45.0, -122.0')
    expect(wrapper.text()).toContain('Not sharing')
    expect(wrapper.text()).toContain('Counts from now on attach to the new deployment.')
  })

  it('says what is shared: not sharing, data with a rounded location, or data and the exact location', () => {
    const lines = (sharing: PlacesState['sharing']) =>
      mountAlone(DeployReview, { place: USED, state: { ...STATE, sharing }, timeZones: LIST, timeZonesError: '' }).text()
    expect(lines('none')).toContain('Not sharing')
    expect(lines('data')).toContain('Sharing: data, rounded location')
    const exact = lines('exact')
    expect(exact).toContain('Sharing: data and the exact location')
    expect(exact).not.toContain('rounded location')
  })

  it('starts every sensor anew, whichever heading is chosen', async () => {
    const wrapper = mountAlone(DeployReview, { place: USED, state: STATE, timeZones: LIST, timeZonesError: '' })
    await choose(wrapper, 'picam_h265', 0)
    expect(sensorRow(wrapper, 'picam_h265').text()).toContain('New deployment starts')
    expect(wrapper.text()).not.toContain('Unchanged')
    expect(button(wrapper, 'Re-deploy').attributes('disabled')).toBeUndefined()
    const radar = sensorRow(wrapper, 'TM_RADAR_SERIAL_PORT_00').text()
    expect(radar).toContain('Was not set, now')
    expect(radar).toContain('Not set') // the select shows an empty heading by its title
  })

  it('shows a measured heading as it is', () => {
    const measured = {
      ...STATE,
      sensors: [{ sensor_type: 'cameras', sensor_name: 'picam_h265', heading_deg: 40 }, STATE.sensors[1]],
    }
    const wrapper = mountAlone(DeployReview, { place: place({ status: 'planned' }), state: measured, timeZones: LIST, timeZonesError: '' })
    expect(sensorRow(wrapper, 'picam_h265').text()).toContain('Was NE (40°), now')
    expect(sensorRow(wrapper, 'picam_h265').text()).toContain('NE (40°)') // the pick, starting at the heading now
  })

  it('says nothing is stored when the precision stores no location', async () => {
    const wrapper = mountAlone(DeployReview, {
      place: { ...USED, stored_lat: null, stored_lon: null },
      state: { ...STATE, precision: 'none' },
      timeZones: LIST,
      timeZonesError: '',
    })
    expect(wrapper.text()).toContain('Nothing stored')
    expect(wrapper.text()).not.toContain('Stored in the database:')
  })

  it("deploys with every sensor's heading", async () => {
    const api = fakeApi({ [DEPLOY]: { deployed_at: 1762000000000, reloaded: true, deployments: ROWS, previous: [] } })
    const wrapper = mountAlone(DeployReview, { place: USED, state: STATE, timeZones: LIST, timeZonesError: '' })
    await choose(wrapper, 'TM_RADAR_SERIAL_PORT_00', 90)
    await click(wrapper, 'Re-deploy')
    expect(api.sent).toEqual([
      {
        method: 'POST',
        path: '/api/v1/surveys/c0ffee01-si/deploy',
        body: {
          headings: [
            { sensor_type: 'cameras', sensor_name: 'picam_h265', heading_deg: 45 },
            { sensor_type: 'radars', sensor_name: 'TM_RADAR_SERIAL_PORT_00', heading_deg: 90 },
          ],
        },
      },
    ])
    expect(wrapper.emitted('deployed')).toHaveLength(1)
  })

  it("a place with no time zone starts with the clock's", () => {
    const wrapper = review()
    expect(wrapper.text()).toContain("America/New_York, the same as the unit's clock")
    expect(wrapper.find<HTMLInputElement>('input[type="checkbox"]').element.checked).toBe(false)
  })

  it("puts the time zone after the sensors and before what's stored", () => {
    const text = review().text()
    expect(text.indexOf('New deployment starts')).toBeLessThan(text.indexOf('Time zone'))
    expect(text.indexOf('Time zone')).toBeLessThan(text.indexOf('Stored in the database'))
  })

  it('starts with the place\'s own time zone, ticked when it differs from the clock\'s', () => {
    const wrapper = review({ timezone: 'Asia/Tokyo' })
    expect(wrapper.find<HTMLInputElement>('input[type="checkbox"]').element.checked).toBe(true)
    expect(wrapper.findComponent({ name: 'VAutocomplete' }).props('modelValue')).toBe('Asia/Tokyo')
  })

  it('an unchanged time zone sends no PUT', async () => {
    const api = fakeApi({ [DEPLOY]: DEPLOYED })
    const wrapper = review({ timezone: 'Asia/Tokyo' })
    await click(wrapper, 'Re-deploy')
    expect(api.sent.map((r) => `${r.method} ${r.path}`)).toEqual([DEPLOY])
  })

  it('a changed time zone is saved before the deploy', async () => {
    const api = fakeApi({ [SET_TIME_ZONE]: place({ timezone: 'Europe/Berlin' }), [DEPLOY]: DEPLOYED })
    const wrapper = review({ timezone: 'Asia/Tokyo' })
    await pickTimeZone(wrapper, 'Europe/Berlin')
    await click(wrapper, 'Re-deploy')
    expect(api.sent.map((r) => `${r.method} ${r.path}`)).toEqual([SET_TIME_ZONE, DEPLOY])
    expect(api.sent[0].body).toEqual({ timezone: 'Europe/Berlin' })
    expect(wrapper.emitted('deployed')).toHaveLength(1)
  })

  it("a place with none has the clock's saved before the deploy", async () => {
    const api = fakeApi({ [SET_TIME_ZONE]: place({ timezone: CLOCK }), [DEPLOY]: DEPLOYED })
    const wrapper = review()
    await click(wrapper, 'Re-deploy')
    expect(api.sent.map((r) => `${r.method} ${r.path}`)).toEqual([SET_TIME_ZONE, DEPLOY])
    expect(api.sent[0].body).toEqual({ timezone: CLOCK })
  })

  it('sends no PUT when neither the place nor the clock has a time zone', async () => {
    const api = fakeApi({ [DEPLOY]: DEPLOYED })
    const wrapper = review({}, { state: STATE })
    await click(wrapper, 'Re-deploy')
    expect(api.sent.map((r) => `${r.method} ${r.path}`)).toEqual([DEPLOY])
  })

  it('a refused time zone shows the message and deploys nothing', async () => {
    const api = fakeApi({
      [SET_TIME_ZONE]: apiError(422, 'invalid_timezone', 'That is not a time zone this device lists.'),
      [DEPLOY]: DEPLOYED,
    })
    const wrapper = review()
    await click(wrapper, 'Re-deploy')
    expect(wrapper.find('.v-alert').text()).toContain('That is not a time zone this device lists.')
    expect(api.sent.map((r) => `${r.method} ${r.path}`)).toEqual([SET_TIME_ZONE])
    expect(wrapper.emitted('deployed')).toBeUndefined()
    expect(button(wrapper, 'Re-deploy').attributes('disabled')).toBeUndefined() // it can be tried again
  })

  it('a time zone refused as out of date asks the page to load the places again', async () => {
    fakeApi({ [SET_TIME_ZONE]: apiError(409, 'not_found', 'This place changed. Reload the page and try again.') })
    const wrapper = review()
    await click(wrapper, 'Re-deploy')
    expect(wrapper.emitted('stale')).toHaveLength(1)
    expect(wrapper.emitted('deployed')).toBeUndefined()
  })

  it('a dropped connection on the time zone is an ordinary error, and deploys nothing', async () => {
    const api = fakeApi({ [SET_TIME_ZONE]: () => Promise.reject(new TypeError('fetch failed')), [DEPLOY]: DEPLOYED })
    const wrapper = review()
    await click(wrapper, 'Re-deploy')
    expect(wrapper.text()).not.toContain('The connection dropped before the answer came')
    expect(wrapper.find('.v-alert').exists()).toBe(true)
    expect(api.sent.map((r) => r.path)).toEqual(['/api/v1/surveys/c0ffee01-si/timezone'])
    expect(wrapper.emitted('deployed')).toBeUndefined()
  })

  it("a retried deploy doesn't save the time zone again", async () => {
    let tries = 0
    const api = fakeApi({
      [SET_TIME_ZONE]: place({ timezone: CLOCK }),
      [DEPLOY]: () =>
        ++tries === 1 ? apiError(500, 'internal', 'Node-RED did not answer.') : json(200, DEPLOYED),
    })
    const wrapper = review()
    await click(wrapper, 'Re-deploy')
    expect(wrapper.text()).toContain('Node-RED did not answer.')
    await click(wrapper, 'Re-deploy')
    expect(api.sent.map((r) => `${r.method} ${r.path}`)).toEqual([SET_TIME_ZONE, DEPLOY, DEPLOY])
  })

  it('disables the time zone control while it deploys', async () => {
    fakeApi({ [SET_TIME_ZONE]: place({ timezone: CLOCK }), [DEPLOY]: () => new Promise<Response>(() => {}) })
    const wrapper = review()
    await click(wrapper, 'Re-deploy')
    expect(wrapper.find<HTMLInputElement>('input[type="checkbox"]').element.disabled).toBe(true)
  })

  it('sends no PUT for a null time zone, and deploys', async () => {
    const api = fakeApi({ [DEPLOY]: DEPLOYED })
    const wrapper = review({ timezone: 'Asia/Tokyo' })
    // The control never hands up null itself; a sender must not pass it on if it ever did
    wrapper.findComponent(TimeZonePick).vm.$emit('update:modelValue', null)
    await flushPromises()
    await click(wrapper, 'Re-deploy')
    expect(api.sent.map((r) => `${r.method} ${r.path}`)).toEqual([DEPLOY])
    expect(wrapper.emitted('deployed')).toHaveLength(1)
  })

  describe('when the saved time zone is not followed by a deploy', () => {
    it('a deploy refused after the time zone was saved asks the page to load the places again', async () => {
      const api = fakeApi({
        [SET_TIME_ZONE]: place({ timezone: CLOCK }),
        [DEPLOY]: apiError(500, 'internal', 'Node-RED did not answer.'),
      })
      const wrapper = review()
      await click(wrapper, 'Re-deploy')
      expect(api.sent.map((r) => `${r.method} ${r.path}`)).toEqual([SET_TIME_ZONE, DEPLOY])
      expect(wrapper.text()).toContain('Node-RED did not answer.')
      expect(wrapper.emitted('stale')).toHaveLength(1)
      expect(wrapper.emitted('deployed')).toBeUndefined()
    })

    it('a retried deploy that fails again asks again, since the time zone was saved by an earlier try', async () => {
      fakeApi({
        [SET_TIME_ZONE]: place({ timezone: CLOCK }),
        [DEPLOY]: apiError(500, 'internal', 'Node-RED did not answer.'),
      })
      const wrapper = review()
      await click(wrapper, 'Re-deploy')
      await click(wrapper, 'Re-deploy')
      expect(wrapper.emitted('stale')).toHaveLength(2)
    })

    it.each([
      [0, () => Promise.reject(new TypeError('fetch failed'))],
      [422, () => apiError(422, 'invalid_timezone', 'That is not a time zone this device lists.')],
      [502, () => apiError(502, 'nodered_unreachable', 'Node-RED did not answer.')],
    ])('a time zone that failed with %s asks the page to load the places again, and deploys nothing', async (_, fail) => {
      const api = fakeApi({ [SET_TIME_ZONE]: fail, [DEPLOY]: DEPLOYED })
      const wrapper = review()
      await click(wrapper, 'Re-deploy')
      expect(api.sent.map((r) => `${r.method} ${r.path}`)).toEqual([SET_TIME_ZONE])
      expect(wrapper.find('.v-alert').exists()).toBe(true)
      expect(wrapper.emitted('stale')).toHaveLength(1)
      expect(wrapper.emitted('deployed')).toBeUndefined()
    })

    it('a time zone refused as out of date asks once', async () => {
      fakeApi({ [SET_TIME_ZONE]: apiError(409, 'not_found', 'This place changed. Reload the page and try again.') })
      const wrapper = review()
      await click(wrapper, 'Re-deploy')
      expect(wrapper.emitted('stale')).toHaveLength(1)
    })

    it('a deploy refused as out of date asks once, after a saved time zone too', async () => {
      fakeApi({
        [SET_TIME_ZONE]: place({ timezone: CLOCK }),
        [DEPLOY]: apiError(409, 'config_changed', 'config.yml changed since it was read.'),
      })
      const wrapper = review()
      await click(wrapper, 'Re-deploy')
      expect(wrapper.emitted('stale')).toHaveLength(1)
    })

    it('a deploy refused with no time zone sent asks for nothing', async () => {
      fakeApi({ [DEPLOY]: apiError(500, 'internal', 'Node-RED did not answer.') })
      const wrapper = review({ timezone: CLOCK })
      await click(wrapper, 'Re-deploy')
      expect(wrapper.text()).toContain('Node-RED did not answer.')
      expect(wrapper.emitted('stale')).toBeUndefined()
    })

    it("a deploy that dropped after a saved time zone emits deployed, which loads the places", async () => {
      fakeApi({ [SET_TIME_ZONE]: place({ timezone: CLOCK }), [DEPLOY]: () => Promise.reject(new TypeError('fetch failed')) })
      const wrapper = review()
      await click(wrapper, 'Re-deploy')
      expect(wrapper.emitted('deployed')).toHaveLength(1)
      expect(wrapper.emitted('stale')).toBeUndefined()
    })
  })

  describe("the line about a used place's stored deployments", () => {
    const LINE = "Changing it corrects this place's stored deployments."

    it('shows for a used place whose time zone was changed', async () => {
      const wrapper = review({ timezone: 'Asia/Tokyo' })
      expect(wrapper.text()).not.toContain(LINE)
      await pickTimeZone(wrapper, 'Europe/Berlin')
      expect(wrapper.text()).toContain(LINE)
      expect(wrapper.text()).not.toContain('It starts no new deployment')
    })

    it("shows for a used place with none, which gets the clock's", () => {
      expect(review().text()).toContain(LINE)
    })

    it('sits right under the control, before what is stored', () => {
      const text = review().text()
      expect(text.indexOf(LINE)).toBeGreaterThan(text.indexOf('Recorded with this place'))
      expect(text.indexOf(LINE)).toBeLessThan(text.indexOf('Stored in the database'))
    })

    it('does not show for a planned place', () => {
      expect(review({ status: 'planned' }).text()).not.toContain(LINE)
    })

    it('does not show while the time zone is the one the place has', () => {
      expect(review({ timezone: CLOCK }).text()).not.toContain(LINE)
    })

    it('is gone once the time zone was saved, though the deploy failed and the review stays', async () => {
      fakeApi({
        [SET_TIME_ZONE]: place({ timezone: CLOCK }),
        [DEPLOY]: apiError(500, 'internal', 'Node-RED did not answer.'),
      })
      const wrapper = review()
      expect(wrapper.text()).toContain(LINE)
      await click(wrapper, 'Re-deploy')
      expect(wrapper.text()).toContain('Node-RED did not answer.')
      expect(wrapper.text()).not.toContain(LINE)
    })
  })

  it("treats an empty clock time zone as unknown: no line, the list shows", () => {
    const wrapper = review({}, { state: { ...WITH_CLOCK, clock_timezone: '' } })
    expect(wrapper.text()).not.toContain("the same as the unit's clock")
    expect(wrapper.find('input[type="checkbox"]').exists()).toBe(false)
    expect(wrapper.findComponent({ name: 'VAutocomplete' }).exists()).toBe(true)
  })

  it("passes the list's failure to the control, so the box still works", () => {
    const wrapper = review({ timezone: 'Asia/Tokyo' }, { timeZones: [], timeZonesError: 'The list is unavailable.' })
    expect(wrapper.text()).toContain('The list is unavailable.')
  })

  it('says it waits for Node-RED while the deploy runs', async () => {
    let answer: (response: Response) => void = () => {}
    fakeApi({ [DEPLOY]: () => new Promise<Response>((resolve) => (answer = resolve)) })
    const wrapper = mountAlone(DeployReview, { place: USED, state: STATE, timeZones: LIST, timeZonesError: '' })
    await click(wrapper, 'Re-deploy')
    expect(wrapper.text()).toContain('Waiting for Node-RED to reload the settings')
    expect(button(wrapper, 'Cancel').attributes('disabled')).toBeDefined()
    answer(json(200, { deployed_at: 1762000000000, reloaded: true, deployments: ROWS, previous: [] }))
    await flushPromises()
    expect(wrapper.text()).not.toContain('Waiting for Node-RED')
  })

  it("says Node-RED hasn't reloaded yet and not to deploy again", async () => {
    fakeApi({ [DEPLOY]: { deployed_at: 1762000000000, reloaded: false, deployments: [], previous: [] } })
    const wrapper = mountAlone(DeployReview, { place: USED, state: STATE, timeZones: LIST, timeZonesError: '' })
    await click(wrapper, 'Re-deploy')
    expect(wrapper.text()).toContain(
      "The settings are saved. Node-RED hasn't reloaded them yet; the deployments appear once it does. " +
        "Don't deploy again.",
    )
    expect(wrapper.findAll('button').some((b) => b.text().trim() === 'Re-deploy')).toBe(false)
    expect(wrapper.emitted('deployed')).toHaveLength(1)
  })

  it('lists the new deployment ids with a Copy button each', async () => {
    const writeText = vi.fn(async () => {})
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
    Object.defineProperty(window, 'isSecureContext', { value: true, configurable: true })
    fakeApi({ [DEPLOY]: { deployed_at: 1762000000000, reloaded: true, deployments: ROWS, previous: [] } })
    const wrapper = mountAlone(DeployReview, { place: USED, state: STATE, timeZones: LIST, timeZonesError: '' })
    await click(wrapper, 'Re-deploy')
    expect(wrapper.text()).toContain('1762000000000-0123abcd-d')
    expect(wrapper.text()).toContain('1762000000000-4567cdef-d')
    const copies = wrapper.findAll('button').filter((b) => b.text().trim() === 'Copy')
    expect(copies).toHaveLength(2)
    await copies[1].trigger('click')
    await vi.waitFor(() => expect(wrapper.text()).toContain('Copied.'))
    expect(writeText).toHaveBeenCalledWith('1762000000000-4567cdef-d')
  })

  it('says to record the mounting next, with a Mounting button', async () => {
    fakeApi({ [DEPLOY]: { deployed_at: 1762000000000, reloaded: true, deployments: ROWS, previous: [] } })
    const wrapper = mountAlone(DeployReview, { place: USED, state: STATE, timeZones: LIST, timeZonesError: '' })
    await click(wrapper, 'Re-deploy')
    expect(wrapper.text()).toContain('Next, record how the unit is mounted.')
    expect(wrapper.text()).not.toContain('from the last time')
    const mounting = wrapper.findAll('a').filter((a) => a.text().trim() === 'Mounting')
    expect(mounting.map((a) => a.attributes('href'))).toEqual(['/location/mounting'])
  })

  it('a return to a place says its last values wait to be confirmed', async () => {
    const previous = [{ sensor_type: 'cameras', sensor_name: 'picam_h265' }]
    fakeApi({ [DEPLOY]: { deployed_at: 1762000000000, reloaded: false, deployments: [], previous } })
    const wrapper = mountAlone(DeployReview, { place: USED, state: STATE, timeZones: LIST, timeZonesError: '' })
    await click(wrapper, 'Re-deploy')
    expect(wrapper.text()).toContain(
      "This place has mounting values from the last time the unit was here. They aren't recorded until you confirm " +
        'them.',
    )
    expect(wrapper.text()).not.toContain('Next, record how the unit is mounted.')
    expect(wrapper.findAll('a').some((a) => a.text().trim() === 'Mounting')).toBe(true)
  })

  it("shows the API's message when the deploy is refused", async () => {
    fakeApi({
      [DEPLOY]: apiError(409, 'config_changed', 'config.yml changed since it was read. Reload the page and try again.'),
    })
    const wrapper = mountAlone(DeployReview, { place: USED, state: STATE, timeZones: LIST, timeZonesError: '' })
    await click(wrapper, 'Re-deploy')
    expect(wrapper.text()).toContain('config.yml changed since it was read.')
    expect(wrapper.emitted('deployed')).toBeUndefined()
    expect(wrapper.emitted('stale')).toHaveLength(1) // the page loads the places again
  })

  it('says the settings may be saved when the connection drops, and offers no second deploy', async () => {
    fakeApi({ [DEPLOY]: () => Promise.reject(new TypeError('fetch failed')) })
    const wrapper = mountAlone(DeployReview, { place: USED, state: STATE, timeZones: LIST, timeZonesError: '' })
    await click(wrapper, 'Re-deploy')
    expect(wrapper.text()).toContain(
      'The connection dropped before the answer came. The settings may already be saved: close this and check the ' +
        'place before deploying again.',
    )
    expect(wrapper.text()).not.toContain('try again')
    expect(wrapper.findAll('button').some((b) => b.text().trim() === 'Re-deploy')).toBe(false)
    expect(wrapper.emitted('deployed')).toHaveLength(1) // the page loads the places, to show what happened
  })
})
