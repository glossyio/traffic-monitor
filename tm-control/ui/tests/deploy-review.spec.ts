// The review step before "Deploy here": what each sensor does, what the database stores, and the result of
// POST /surveys/{id}/deploy, which waits for Node-RED to start the deployments.
import { flushPromises, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { components } from '../src/api/schema'
import DeployReview from '../src/modules/location/DeployReview.vue'
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
    bearings: [],
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
  bearings: [
    { sensor_type: 'cameras', sensor_name: 'picam_h265', bearing: 'n' },
    { sensor_type: 'radars', sensor_name: 'TM_RADAR_SERIAL_PORT_00', bearing: '' },
  ],
})
// Used before, facing NE then; it has no bearing for the radar
const USED = place({ bearings: [{ sensor_type: 'cameras', sensor_name: 'picam_h265', bearing: 'ne' }] })

const STATE: PlacesState = {
  precision: '1',
  in_use: IN_USE.id,
  sensors: [
    { sensor_type: 'cameras', sensor_name: 'picam_h265', bearing: 'n' },
    { sensor_type: 'radars', sensor_name: 'TM_RADAR_SERIAL_PORT_00', bearing: '' },
  ],
  sharing: 'none',
  surveys: [IN_USE, USED],
  unassigned: null,
  reconcile: 'done',
  nodered: true,
}

const DEPLOY = 'POST /api/v1/surveys/c0ffee01-si/deploy'

function row(id: string, sensorType: string, sensorName: string, bearing: string): DeploymentOut {
  return {
    id,
    started: 1762000000000,
    ended: null,
    lat: 45.0,
    lon: -122.0,
    bearing,
    sensor_type: sensorType,
    sensor_name: sensorName,
    location_precision: 1,
  }
}

const ROWS = [
  row('1762000000000-0123abcd-d', 'cameras', 'picam_h265', 'ne'),
  row('1762000000000-4567cdef-d', 'radars', 'TM_RADAR_SERIAL_PORT_00', ''),
]

// One sensor's part of the review, found by the sensor's name
function sensorRow(wrapper: VueWrapper, name: string) {
  const found = wrapper.findAll('[data-sensor]').filter((r) => r.attributes('data-sensor') === name)
  expect(found.length, `one review row for ${name}`).toBe(1)
  return found[0]
}

// Choose a bearing in a sensor's select, as picking from its menu would
async function choose(wrapper: VueWrapper, name: string, bearing: string) {
  const index = STATE.sensors.findIndex((sensor) => sensor.sensor_name === name)
  await wrapper.findAllComponents({ name: 'VSelect' })[index].setValue(bearing)
  await flushPromises()
}

describe('the deploy review', () => {
  beforeEach(() => document.body.replaceChildren())
  afterEach(() => {
    Reflect.deleteProperty(navigator, 'clipboard')
    Reflect.deleteProperty(window, 'isSecureContext')
  })

  it('starts a new deployment for every sensor at a place not in use', async () => {
    const wrapper = mountAlone(DeployReview, { place: USED, state: STATE })
    expect(wrapper.text()).toContain('Corner by the park')
    expect(wrapper.text()).toContain('c0ffee01-si')
    const camera = sensorRow(wrapper, 'picam_h265')
    expect(camera.text()).toContain('New deployment starts')
    expect(camera.text()).toContain('Was N, now')
    expect(camera.text()).toContain('NE') // the place's own bearing, from when it was used
    expect(sensorRow(wrapper, 'TM_RADAR_SERIAL_PORT_00').text()).toContain('New deployment starts')
    expect(wrapper.text()).toContain('Stored in the database: 45.0, -122.0')
    expect(wrapper.text()).toContain('Not sharing')
    expect(wrapper.text()).toContain('Counts from now on attach to the new deployment.')
  })

  it('lists New deployment starts for the sensor whose bearing changes and Unchanged for the other', async () => {
    const wrapper = mountAlone(DeployReview, { place: IN_USE, state: STATE })
    expect(sensorRow(wrapper, 'picam_h265').text()).toContain('Unchanged')
    await choose(wrapper, 'picam_h265', 'e')
    expect(sensorRow(wrapper, 'picam_h265').text()).toContain('New deployment starts')
    const radar = sensorRow(wrapper, 'TM_RADAR_SERIAL_PORT_00').text()
    expect(radar).toContain('Unchanged')
    expect(radar).toContain('Was not set, now')
    expect(radar).toContain('Not set') // the select shows a blank bearing by its title
  })

  it('disables Deploy at the place in use while every bearing is unchanged', async () => {
    const wrapper = mountAlone(DeployReview, { place: IN_USE, state: STATE })
    expect(sensorRow(wrapper, 'picam_h265').text()).toContain('Unchanged')
    expect(sensorRow(wrapper, 'TM_RADAR_SERIAL_PORT_00').text()).toContain('Unchanged')
    expect(button(wrapper, 'Deploy').attributes('disabled')).toBeDefined()
    expect(wrapper.text()).not.toContain('Counts from now on attach to the new deployment.')
    await choose(wrapper, 'TM_RADAR_SERIAL_PORT_00', 'w')
    expect(button(wrapper, 'Deploy').attributes('disabled')).toBeUndefined()
    expect(wrapper.text()).toContain('Counts from now on attach to the new deployment.')
  })

  it("starts the place in use at the bearings config.yml has now, not the place's stored ones", async () => {
    const turned = { ...IN_USE, bearings: [{ sensor_type: 'cameras', sensor_name: 'picam_h265', bearing: 'ne' }] }
    const wrapper = mountAlone(DeployReview, { place: turned, state: STATE })
    expect(sensorRow(wrapper, 'picam_h265').text()).toContain('Unchanged')
    expect(button(wrapper, 'Deploy').attributes('disabled')).toBeDefined()
  })

  it('says nothing is stored when the precision stores no location', async () => {
    const wrapper = mountAlone(DeployReview, {
      place: { ...USED, stored_lat: null, stored_lon: null },
      state: { ...STATE, precision: 'none' },
    })
    expect(wrapper.text()).toContain('Nothing stored')
    expect(wrapper.text()).not.toContain('Stored in the database:')
  })

  it("deploys with every sensor's bearing", async () => {
    const api = fakeApi({ [DEPLOY]: { deployed_at: 1762000000000, reloaded: true, deployments: ROWS } })
    const wrapper = mountAlone(DeployReview, { place: USED, state: STATE })
    await choose(wrapper, 'TM_RADAR_SERIAL_PORT_00', 'e')
    await click(wrapper, 'Deploy')
    expect(api.sent).toEqual([
      {
        method: 'POST',
        path: '/api/v1/surveys/c0ffee01-si/deploy',
        body: {
          bearings: [
            { sensor_type: 'cameras', sensor_name: 'picam_h265', bearing: 'ne' },
            { sensor_type: 'radars', sensor_name: 'TM_RADAR_SERIAL_PORT_00', bearing: 'e' },
          ],
        },
      },
    ])
    expect(wrapper.emitted('deployed')).toHaveLength(1)
  })

  it('says it waits for Node-RED while the deploy runs', async () => {
    let answer: (response: Response) => void = () => {}
    fakeApi({ [DEPLOY]: () => new Promise<Response>((resolve) => (answer = resolve)) })
    const wrapper = mountAlone(DeployReview, { place: USED, state: STATE })
    await click(wrapper, 'Deploy')
    expect(wrapper.text()).toContain('Waiting for Node-RED to reload the settings')
    expect(button(wrapper, 'Cancel').attributes('disabled')).toBeDefined()
    answer(json(200, { deployed_at: 1762000000000, reloaded: true, deployments: ROWS }))
    await flushPromises()
    expect(wrapper.text()).not.toContain('Waiting for Node-RED')
  })

  it("says Node-RED hasn't reloaded yet and not to deploy again", async () => {
    fakeApi({ [DEPLOY]: { deployed_at: 1762000000000, reloaded: false, deployments: [] } })
    const wrapper = mountAlone(DeployReview, { place: USED, state: STATE })
    await click(wrapper, 'Deploy')
    expect(wrapper.text()).toContain(
      "The settings are saved. Node-RED hasn't reloaded them yet; the deployments appear once it does. " +
        "Don't deploy again.",
    )
    expect(wrapper.findAll('button').some((b) => b.text().trim() === 'Deploy')).toBe(false)
    expect(wrapper.emitted('deployed')).toHaveLength(1)
  })

  it('lists the new deployment ids with a Copy button each', async () => {
    const writeText = vi.fn(async () => {})
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
    Object.defineProperty(window, 'isSecureContext', { value: true, configurable: true })
    fakeApi({ [DEPLOY]: { deployed_at: 1762000000000, reloaded: true, deployments: ROWS } })
    const wrapper = mountAlone(DeployReview, { place: USED, state: STATE })
    await click(wrapper, 'Deploy')
    expect(wrapper.text()).toContain('1762000000000-0123abcd-d')
    expect(wrapper.text()).toContain('1762000000000-4567cdef-d')
    const copies = wrapper.findAll('button').filter((b) => b.text().trim() === 'Copy')
    expect(copies).toHaveLength(2)
    await copies[1].trigger('click')
    await vi.waitFor(() => expect(wrapper.text()).toContain('Copied.'))
    expect(writeText).toHaveBeenCalledWith('1762000000000-4567cdef-d')
  })

  it("shows the API's message when the deploy is refused", async () => {
    fakeApi({
      [DEPLOY]: apiError(409, 'config_changed', 'config.yml changed since it was read. Reload the page and try again.'),
    })
    const wrapper = mountAlone(DeployReview, { place: USED, state: STATE })
    await click(wrapper, 'Deploy')
    expect(wrapper.text()).toContain('config.yml changed since it was read.')
    expect(wrapper.emitted('deployed')).toBeUndefined()
    expect(wrapper.emitted('stale')).toHaveLength(1) // the page loads the places again
  })

  it('says the settings may be saved when the connection drops, and offers no second deploy', async () => {
    fakeApi({ [DEPLOY]: () => Promise.reject(new TypeError('fetch failed')) })
    const wrapper = mountAlone(DeployReview, { place: USED, state: STATE })
    await click(wrapper, 'Deploy')
    expect(wrapper.text()).toContain(
      'The connection dropped before the answer came. The settings may already be saved: close this and check the ' +
        'place before deploying again.',
    )
    expect(wrapper.text()).not.toContain('try again')
    expect(wrapper.findAll('button').some((b) => b.text().trim() === 'Deploy')).toBe(false)
    expect(wrapper.emitted('deployed')).toHaveLength(1) // the page loads the places, to show what happened
  })
})
