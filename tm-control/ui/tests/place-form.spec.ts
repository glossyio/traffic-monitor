// The place form: adding a place (POST /surveys) or editing a planned one (PATCH /surveys/{id}), with the coordinates
// typed, pasted, or read from the phone, and a bearing per sensor.
import { flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { components } from '../src/api/schema'
import PlaceForm from '../src/modules/location/PlaceForm.vue'
import { apiError, fakeApi, json } from './fake-api'
import { clickInDialog, dialogButtons, dialogField, dialogText, mountAlone, typeInto } from './mount'

type Bearing = components['schemas']['Bearing']
type SurveyOut = components['schemas']['SurveyOut']

const SENSORS: Bearing[] = [
  { sensor_type: 'cameras', sensor_name: 'picam_h265', bearing: 'n' },
  { sensor_type: 'radars', sensor_name: 'TM_RADAR_SERIAL_PORT_00', bearing: '' },
]

const PLANNED: SurveyOut = {
  id: '0f0e0d0c-si',
  description: 'Corner by the park',
  lat: 45.0,
  lon: -122.0,
  status: 'planned',
  source: 'ui',
  created_at: '2026-10-01T12:00:00+00:00',
  updated_at: '2026-10-01T12:00:00+00:00',
  bearings: [{ sensor_type: 'cameras', sensor_name: 'picam_h265', bearing: 'se' }],
  stored_lat: 45.0,
  stored_lon: -122.0,
  first_used: null,
  last_used: null,
  open_count: 0,
  deployment_count: 0,
  imported: false,
}

const COMMA_ERROR = 'Enter latitude, longitude with a dot as the decimal mark'

// Whether the page is a secure context (HTTPS), as the browser says
function secure(value: boolean) {
  Object.defineProperty(window, 'isSecureContext', { value, configurable: true })
}

// A phone that answers getCurrentPosition with this reading, or refuses with this message
function phone(answer: { latitude: number; longitude: number } | string) {
  const getCurrentPosition = vi.fn(
    (ok: (position: unknown) => void, refused: (error: unknown) => void, options: unknown) => {
      void options
      if (typeof answer === 'string') refused({ code: 1, message: answer })
      else ok({ coords: answer })
    },
  )
  Object.defineProperty(navigator, 'geolocation', { value: { getCurrentPosition }, configurable: true })
  return getCurrentPosition
}

function mountForm(survey?: SurveyOut) {
  return mountAlone(PlaceForm, { open: true, sensors: SENSORS, survey })
}

function saveButton() {
  const buttons = dialogButtons('Save')
  expect(buttons).toHaveLength(1)
  return buttons[0]
}

describe('the place form', () => {
  beforeEach(() => {
    document.body.replaceChildren()
    secure(false)
  })
  afterEach(() => {
    Reflect.deleteProperty(window, 'isSecureContext')
    Reflect.deleteProperty(navigator, 'geolocation')
  })

  it('fills in a pair pasted from a maps app', async () => {
    mountForm()
    await flushPromises()
    expect(dialogText()).toContain('Paste latitude, longitude from a maps app, such as 45.52252, -122.69120')
    await typeInto(dialogField('Coordinates'), '45.52252,-122.69120')
    expect(dialogText()).not.toContain(COMMA_ERROR)
    expect(saveButton().disabled).toBe(false)
  })

  it('shows the error and disables Save for a decimal comma', async () => {
    mountForm()
    await flushPromises()
    await typeInto(dialogField('Coordinates'), '45,52252, -122,69120')
    expect(dialogText()).toContain(COMMA_ERROR)
    expect(saveButton().disabled).toBe(true)
  })

  it('refuses a pair in the wrong order, whose latitude is out of range', async () => {
    mountForm()
    await flushPromises()
    await typeInto(dialogField('Coordinates'), '-122.69120, 45.52252')
    expect(dialogText()).toContain(COMMA_ERROR)
    expect(saveButton().disabled).toBe(true)
  })

  it("offers the phone's location only on a secure page", async () => {
    const reading = phone({ latitude: 45.52252, longitude: -122.6912 })
    const plain = mountForm()
    await flushPromises()
    expect(dialogButtons("Use this phone's location")).toHaveLength(0)
    expect(dialogText()).toContain(
      'Browsers only share your location with secure pages. Paste coordinates instead.',
    )
    plain.unmount()
    document.body.replaceChildren()

    secure(true)
    mountForm()
    await flushPromises()
    expect(dialogText()).not.toContain('Browsers only share your location')
    await clickInDialog("Use this phone's location")
    expect(reading).toHaveBeenCalledTimes(1)
    expect(reading.mock.calls[0][2]).toMatchObject({ enableHighAccuracy: true })
    expect(dialogField('Coordinates').value).toBe('45.52252, -122.69120')
  })

  it("shows the browser's message when the phone doesn't share its location", async () => {
    secure(true)
    phone('User denied Geolocation')
    mountForm()
    await flushPromises()
    await clickInDialog("Use this phone's location")
    expect(dialogText()).toContain('User denied Geolocation')
    expect(dialogField('Coordinates').value).toBe('')
  })

  it("posts the description, the coordinates, and every sensor's bearing", async () => {
    const api = fakeApi({ 'POST /api/v1/surveys': json(201, PLANNED) })
    const form = mountForm()
    await flushPromises()
    expect(dialogText()).toContain('Private: it never leaves the device')
    expect(dialogText()).toContain('A map pin is coming in a later update.')
    await typeInto(dialogField('Description'), 'Corner by the park')
    await typeInto(dialogField('Coordinates'), '45.52252, -122.69120')
    await clickInDialog('Save')
    expect(api.sent).toEqual([
      {
        method: 'POST',
        path: '/api/v1/surveys',
        body: {
          description: 'Corner by the park',
          lat: 45.52252,
          lon: -122.6912,
          bearings: SENSORS, // a new place starts at each sensor's current bearing
        },
      },
    ])
    expect(form.emitted('saved')).toHaveLength(1)
    expect(form.emitted('update:open')).toEqual([[false]])
  })

  it('sends no coordinates when the field is left blank', async () => {
    const api = fakeApi({ 'POST /api/v1/surveys': json(201, PLANNED) })
    mountForm()
    await flushPromises()
    await clickInDialog('Save')
    expect(api.sent[0].body).toEqual({ description: null, lat: null, lon: null, bearings: SENSORS })
  })

  it("edits a planned place with PATCH, starting from its values", async () => {
    const api = fakeApi({ 'PATCH /api/v1/surveys/0f0e0d0c-si': PLANNED })
    mountForm(PLANNED)
    await flushPromises()
    expect(dialogField('Description').value).toBe('Corner by the park')
    expect(dialogField('Coordinates').value).toBe('45.00000, -122.00000')
    await clickInDialog('Save')
    expect(api.sent).toEqual([
      {
        method: 'PATCH',
        path: '/api/v1/surveys/0f0e0d0c-si',
        body: {
          description: 'Corner by the park',
          lat: 45,
          lon: -122,
          // the place's own bearing where it has one, else the sensor's current one
          bearings: [
            { sensor_type: 'cameras', sensor_name: 'picam_h265', bearing: 'se' },
            { sensor_type: 'radars', sensor_name: 'TM_RADAR_SERIAL_PORT_00', bearing: '' },
          ],
        },
      },
    ])
  })

  it('asks the page to reload the places when the save is refused as out of date', async () => {
    fakeApi({
      'PATCH /api/v1/surveys/0f0e0d0c-si': apiError(
        409,
        'not_planned',
        'Only a planned place can be edited. Correct a used place instead.',
      ),
    })
    const form = mountForm(PLANNED)
    await flushPromises()
    await clickInDialog('Save')
    expect(dialogText()).toContain('Only a planned place can be edited.')
    expect(form.emitted('stale')).toHaveLength(1)
    expect(form.emitted('saved')).toBeUndefined()
  })

  it('names the dialog by its title', async () => {
    mountForm()
    await flushPromises()
    expect(document.querySelector('.v-overlay-container .v-dialog')?.getAttribute('aria-label')).toBe('Add a place')
  })

  it("shows the API's message when the save is refused", async () => {
    fakeApi({ 'POST /api/v1/surveys': apiError(422, 'validation', 'lat must be between -90 and 90.') })
    const form = mountForm()
    await flushPromises()
    await clickInDialog('Save')
    expect(dialogText()).toContain('lat must be between -90 and 90.')
    expect(form.emitted('saved')).toBeUndefined()
  })
})
