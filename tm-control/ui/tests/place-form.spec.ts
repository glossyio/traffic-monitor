// The place form: adding a place (POST /surveys) or editing a planned one (PATCH /surveys/{id}), with the coordinates
// typed, pasted, or read from the phone, and a heading per sensor.
import { flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { components } from '../src/api/schema'
import PlaceForm from '../src/modules/location/PlaceForm.vue'
import TimeZonePick from '../src/modules/location/TimeZonePick.vue'
import { apiError, fakeApi, json } from './fake-api'
import { clickInDialog, dialogButtons, dialogField, dialogText, mountAlone, typeInto } from './mount'

type SensorHeading = components['schemas']['SensorHeading']
type SurveyOut = components['schemas']['SurveyOut']

// PinMap is stubbed: a button drops the pin at the docs' example point
vi.mock('../src/modules/location/PinMap.vue', async () => {
  const { defineComponent, h } = await import('vue')
  return {
    __esModule: true,
    default: defineComponent({
      props: { styleUrl: String, centre: Object, pin: Object },
      emits: ['ready', 'failed', 'update:pin'],
      setup(_props, { emit }) {
        return () =>
          h(
            'button',
            { type: 'button', onClick: () => emit('update:pin', { lat: 45.52252, lon: -122.6912 }) },
            'Drop the pin',
          )
      },
    }),
  }
})

const MAP = { style_url: 'https://tiles.example.invalid/style' }

const SENSORS: SensorHeading[] = [
  { sensor_type: 'cameras', sensor_name: 'picam_h265', heading_deg: 0 },
  { sensor_type: 'radars', sensor_name: 'TM_RADAR_SERIAL_PORT_00', heading_deg: null },
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
  headings: [{ sensor_type: 'cameras', sensor_name: 'picam_h265', heading_deg: 135 }],
  timezone: null,
  stored_lat: 45.0,
  stored_lon: -122.0,
  first_used: null,
  last_used: null,
  open_count: 0,
  deployment_count: 0,
  imported: false,
  pictures: 0,
}

const FEW_WARNING =
  'For an exact location, use at least four decimal places (about 10 m). This is rounded to about 1 km.'

// Open the picker from the form, drop the pin, and take the point
async function pickOnMap() {
  await clickInDialog('Pick on a map')
  await flushPromises()
  await clickInDialog('Drop the pin')
  await clickInDialog('Use this point')
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

const LIST = ['America/New_York', 'Asia/Tokyo', 'Europe/Berlin']
const CLOCK = 'America/New_York'

function mountForm(survey?: SurveyOut, props: Record<string, unknown> = {}) {
  return mountAlone(PlaceForm, {
    open: true,
    sensors: SENSORS,
    survey,
    map: MAP,
    centre: null,
    timeZones: LIST,
    timeZonesError: '',
    clockTimeZone: CLOCK,
    ...props,
  })
}

// The time zone control's box, in the open dialog
function differentBox() {
  return document.querySelector<HTMLInputElement>('.v-overlay-container .v-dialog input[type="checkbox"]')
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

  it("posts the description, the coordinates, and every sensor's heading", async () => {
    const api = fakeApi({ 'POST /api/v1/surveys': json(201, PLANNED) })
    const form = mountForm()
    await flushPromises()
    expect(dialogText()).toContain('Private: it never leaves the device')
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
          headings: SENSORS, // a new place starts at each sensor's current heading
          timezone: CLOCK,
        },
      },
    ])
    expect(form.emitted('saved')).toHaveLength(1)
    expect(form.emitted('update:open')).toEqual([[false]])
  })

  it('asks which way each sensor faces, and sends the one chosen as degrees', async () => {
    const api = fakeApi({ 'POST /api/v1/surveys': json(201, PLANNED) })
    const form = mountForm()
    await flushPromises()
    expect(dialogText()).toContain('Which way each sensor faces here')
    expect(dialogText()).toContain('Facing, picam_h265')
    expect(dialogText()).toContain('Facing, TM_RADAR_SERIAL_PORT_00')
    expect(dialogText()).not.toMatch(/bearing/i)
    await form.findAllComponents({ name: 'VSelect' })[1].setValue(270)
    await clickInDialog('Save')
    expect((api.sent[0].body as { headings: SensorHeading[] }).headings).toEqual([
      SENSORS[0],
      { ...SENSORS[1], heading_deg: 270 },
    ])
  })

  it('sends no coordinates when the field is left blank', async () => {
    const api = fakeApi({ 'POST /api/v1/surveys': json(201, PLANNED) })
    mountForm()
    await flushPromises()
    await clickInDialog('Save')
    expect(api.sent[0].body).toEqual({ description: null, lat: null, lon: null, headings: SENSORS, timezone: CLOCK })
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
          // the place's own heading where it has one, else the sensor's current one
          headings: [
            { sensor_type: 'cameras', sensor_name: 'picam_h265', heading_deg: 135 },
            { sensor_type: 'radars', sensor_name: 'TM_RADAR_SERIAL_PORT_00', heading_deg: null },
          ],
          timezone: CLOCK, // the place has none, so it gets the clock's
        },
      },
    ])
  })

  it("doesn't offer one place's measured heading when it opens on another", async () => {
    const measured = { ...PLANNED, headings: [{ sensor_type: 'cameras', sensor_name: 'picam_h265', heading_deg: 40 }] }
    const other = { ...PLANNED, id: '0a0b0c0d-si', headings: [] }
    const form = mountForm(measured)
    await flushPromises()
    const titles = () =>
      (form.findAllComponents({ name: 'VSelect' })[0].props('items') as { title: string }[]).map((item) => item.title)
    expect(titles()).toContain('NE (40°)')
    await form.setProps({ open: false })
    await form.setProps({ survey: other, open: true })
    await flushPromises()
    expect(titles()).not.toContain('NE (40°)')
  })

  it("a new place starts with the clock's time zone", async () => {
    const api = fakeApi({ 'POST /api/v1/surveys': json(201, PLANNED) })
    mountForm()
    await flushPromises()
    expect(dialogText()).toContain("America/New_York, the same as the unit's clock")
    expect(dialogText()).toContain('This place is in a different time zone')
    expect(differentBox()?.checked).toBe(false)
    await clickInDialog('Save')
    expect((api.sent[0].body as { timezone: string }).timezone).toBe(CLOCK)
  })

  it('puts the time zone after the coordinates and before the headings', async () => {
    mountForm()
    await flushPromises()
    const text = dialogText()
    expect(text.indexOf('Coordinates')).toBeLessThan(text.indexOf('Time zone'))
    expect(text.indexOf('Time zone')).toBeLessThan(text.indexOf('Which way each sensor faces here'))
  })

  it("an edited place starts with its own time zone", async () => {
    const api = fakeApi({ 'PATCH /api/v1/surveys/0f0e0d0c-si': PLANNED })
    const form = mountForm({ ...PLANNED, timezone: 'Asia/Tokyo' })
    await flushPromises()
    expect(differentBox()?.checked).toBe(true)
    expect(form.findComponent({ name: 'VAutocomplete' }).props('modelValue')).toBe('Asia/Tokyo')
    await clickInDialog('Save')
    expect((api.sent[0].body as { timezone: string }).timezone).toBe('Asia/Tokyo')
  })

  it("an edited place with none starts with the clock's", async () => {
    const api = fakeApi({ 'PATCH /api/v1/surveys/0f0e0d0c-si': PLANNED })
    mountForm(PLANNED)
    await flushPromises()
    expect(dialogText()).toContain("America/New_York, the same as the unit's clock")
    expect(differentBox()?.checked).toBe(false)
    await clickInDialog('Save')
    expect((api.sent[0].body as { timezone: string }).timezone).toBe(CLOCK)
  })

  it('a different time zone picked is sent', async () => {
    const api = fakeApi({ 'POST /api/v1/surveys': json(201, PLANNED) })
    const form = mountForm()
    await flushPromises()
    differentBox()!.click()
    await flushPromises()
    await form.findComponent({ name: 'VAutocomplete' }).setValue('Europe/Berlin')
    await flushPromises()
    await clickInDialog('Save')
    expect((api.sent[0].body as { timezone: string }).timezone).toBe('Europe/Berlin')
  })

  it('unticking the box sends the clock\'s time zone again', async () => {
    const api = fakeApi({ 'PATCH /api/v1/surveys/0f0e0d0c-si': PLANNED })
    mountForm({ ...PLANNED, timezone: 'Asia/Tokyo' })
    await flushPromises()
    differentBox()!.click()
    await flushPromises()
    await clickInDialog('Save')
    expect((api.sent[0].body as { timezone: string }).timezone).toBe(CLOCK)
  })

  it('starts over each time it opens, at the place now being edited', async () => {
    const form = mountForm({ ...PLANNED, timezone: 'Asia/Tokyo' })
    await flushPromises()
    expect(differentBox()?.checked).toBe(true)
    await form.setProps({ open: false })
    await form.setProps({ survey: undefined, open: true })
    await flushPromises()
    expect(differentBox()?.checked).toBe(false)
    expect(dialogText()).toContain("America/New_York, the same as the unit's clock")
  })

  it('saves without the list of time zones, sending the time zone the place has', async () => {
    const api = fakeApi({ 'PATCH /api/v1/surveys/0f0e0d0c-si': PLANNED })
    mountForm({ ...PLANNED, timezone: 'Asia/Tokyo' }, { timeZones: [], timeZonesError: 'The list is unavailable.' })
    await flushPromises()
    expect(dialogText()).toContain('The list is unavailable.')
    await clickInDialog('Save')
    expect((api.sent[0].body as { timezone: string }).timezone).toBe('Asia/Tokyo')
  })

  it("saves a new place with the clock's time zone when the list didn't load", async () => {
    const api = fakeApi({ 'POST /api/v1/surveys': json(201, PLANNED) })
    mountForm(undefined, { timeZones: [], timeZonesError: 'The list is unavailable.' })
    await flushPromises()
    await clickInDialog('Save')
    expect((api.sent[0].body as { timezone: string }).timezone).toBe(CLOCK)
  })

  it('leaves the time zone out of a new place when the clock is unknown and none was picked', async () => {
    const api = fakeApi({ 'POST /api/v1/surveys': json(201, PLANNED) })
    mountForm(undefined, { clockTimeZone: null })
    await flushPromises()
    await clickInDialog('Save')
    expect(api.sent[0].body).not.toHaveProperty('timezone')
  })

  it('leaves the time zone out of an edit of a place with none when the clock is unknown', async () => {
    const api = fakeApi({ 'PATCH /api/v1/surveys/0f0e0d0c-si': PLANNED })
    mountForm(PLANNED, { clockTimeZone: null })
    await flushPromises()
    await clickInDialog('Save')
    expect(api.sent[0].body).not.toHaveProperty('timezone')
  })

  it('sends the time zone picked from the list when the clock is unknown', async () => {
    const api = fakeApi({ 'POST /api/v1/surveys': json(201, PLANNED) })
    const form = mountForm(undefined, { clockTimeZone: null })
    await flushPromises()
    await form.findComponent({ name: 'VAutocomplete' }).setValue('Europe/Berlin')
    await flushPromises()
    await clickInDialog('Save')
    expect((api.sent[0].body as { timezone: string }).timezone).toBe('Europe/Berlin')
  })

  it('never sends null: a time zone the control handed up empty is left out, so an edit keeps the stored one', async () => {
    const api = fakeApi({ 'PATCH /api/v1/surveys/0f0e0d0c-si': PLANNED })
    const form = mountForm({ ...PLANNED, timezone: 'Asia/Tokyo' })
    await flushPromises()
    form.findComponent(TimeZonePick).vm.$emit('update:modelValue', null)
    await flushPromises()
    await clickInDialog('Save')
    expect(api.sent[0].body).not.toHaveProperty('timezone')
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

  it('the form no longer says a map pin is coming', async () => {
    mountForm()
    await flushPromises()
    expect(dialogText()).not.toContain('A map pin is coming')
    expect(dialogButtons('Pick on a map')).toHaveLength(1)
  })

  it('fewer than four decimal places warns and still saves', async () => {
    const api = fakeApi({ 'POST /api/v1/surveys': json(201, PLANNED) })
    mountForm()
    await flushPromises()
    await typeInto(dialogField('Coordinates'), '45.52, -122.69')
    expect(dialogText()).toContain(FEW_WARNING)
    expect(document.querySelector('.text-warning')?.textContent).toBe(FEW_WARNING)
    expect(dialogText()).not.toContain(COMMA_ERROR)
    expect(saveButton().disabled).toBe(false)
    await clickInDialog('Save')
    expect(api.sent[0].body).toMatchObject({ lat: 45.52, lon: -122.69 })
  })

  it('four decimal places give no warning', async () => {
    mountForm()
    await flushPromises()
    await typeInto(dialogField('Coordinates'), '45.5225, -122.6912')
    expect(dialogText()).not.toContain('For an exact location')
    expect(document.querySelector('.text-warning')).toBeNull()
  })

  it('saved says whether the map set the coordinates', async () => {
    fakeApi({ 'POST /api/v1/surveys': json(201, PLANNED) })
    // typed
    const typed = mountForm()
    await flushPromises()
    await typeInto(dialogField('Coordinates'), '45.52252, -122.69120')
    await clickInDialog('Save')
    expect(typed.emitted('saved')![0][1]).toBe(false)
    typed.unmount()
    document.body.replaceChildren()

    // picked
    const picked = mountForm()
    await flushPromises()
    await pickOnMap()
    expect(dialogField('Coordinates').value).toBe('45.52252, -122.69120')
    await clickInDialog('Save')
    expect(picked.emitted('saved')![0][1]).toBe(true)
    picked.unmount()
    document.body.replaceChildren()

    // picked, then retyped
    const retyped = mountForm()
    await flushPromises()
    await pickOnMap()
    await typeInto(dialogField('Coordinates'), '45.52252, -122.69121')
    await clickInDialog('Save')
    expect(retyped.emitted('saved')![0][1]).toBe(false)
  })

  it("saved says the map didn't set it when the phone's location replaced a pick", async () => {
    fakeApi({ 'POST /api/v1/surveys': json(201, PLANNED) })
    secure(true)
    phone({ latitude: 45.52, longitude: -122.69 })
    const wrapper = mountForm()
    await flushPromises()
    await pickOnMap()
    await clickInDialog("Use this phone's location")
    expect(dialogField('Coordinates').value).toBe('45.52000, -122.69000')
    await clickInDialog('Save')
    expect(wrapper.emitted('saved')![0][1]).toBe(false)
  })
})
