// The Time zone dialog: a used place's or the place in use's time zone (PUT /surveys/{id}/timezone), with the one
// control the other places use. Saving is allowed with no change, so a refused or half-finished save can be finished.
import { flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it } from 'vitest'
import type { components } from '../src/api/schema'
import TimeZoneDialog from '../src/modules/location/TimeZoneDialog.vue'
import { apiError, fakeApi } from './fake-api'
import { clickInDialog, dialogButtons, dialogText, mountAlone } from './mount'

type SurveyOut = components['schemas']['SurveyOut']

function place(changes: Partial<SurveyOut> = {}): SurveyOut {
  return {
    id: 'c0ffee01-si',
    description: 'Front of the school',
    lat: 45.52252,
    lon: -122.6912,
    status: 'used',
    source: 'ui',
    created_at: '2026-10-01T12:00:00+00:00',
    updated_at: '2026-10-01T12:00:00+00:00',
    headings: [],
    timezone: null,
    stored_lat: 45.52,
    stored_lon: -122.69,
    first_used: null,
    last_used: null,
    open_count: 0,
    deployment_count: 1,
    imported: false,
    pictures: 0,
    ...changes,
  }
}

const LIST = ['America/New_York', 'Asia/Tokyo', 'Europe/Berlin']
const CLOCK = 'America/New_York'
const SET_TIME_ZONE = 'PUT /api/v1/surveys/c0ffee01-si/timezone'

function mountDialog(survey: SurveyOut, props: Record<string, unknown> = {}) {
  return mountAlone(TimeZoneDialog, {
    open: true,
    place: survey,
    timeZones: LIST,
    timeZonesError: '',
    clockTimeZone: CLOCK,
    ...props,
  })
}

function box() {
  return document.querySelector<HTMLInputElement>('.v-overlay-container .v-dialog input[type="checkbox"]')!
}

describe('the Time zone dialog', () => {
  beforeEach(() => document.body.replaceChildren())

  it("starts from the place's time zone", async () => {
    const dialog = mountDialog(place({ timezone: 'Asia/Tokyo' }))
    await flushPromises()
    expect(dialogText()).toContain('Time zone')
    expect(dialogText()).toContain('Front of the school')
    expect(dialogText()).toContain('c0ffee01-si')
    expect(dialogText()).toContain("Changing it corrects this place's stored deployments. It starts no new deployment.")
    expect(document.querySelector('.v-overlay-container .v-dialog')?.getAttribute('aria-label')).toBe('Time zone')
    expect(box().checked).toBe(true)
    expect(dialog.findComponent({ name: 'VAutocomplete' }).props('modelValue')).toBe('Asia/Tokyo')
  })

  it("starts from the clock's when the place has none", async () => {
    mountDialog(place())
    await flushPromises()
    expect(dialogText()).toContain("America/New_York, the same as the unit's clock")
    expect(box().checked).toBe(false)
  })

  it('saves and closes', async () => {
    const api = fakeApi({ [SET_TIME_ZONE]: place({ timezone: 'Europe/Berlin' }) })
    const dialog = mountDialog(place({ timezone: 'Asia/Tokyo' }))
    await flushPromises()
    await dialog.findComponent({ name: 'VAutocomplete' }).setValue('Europe/Berlin')
    await clickInDialog('Save')
    expect(api.sent).toEqual([
      { method: 'PUT', path: '/api/v1/surveys/c0ffee01-si/timezone', body: { timezone: 'Europe/Berlin' } },
    ])
    expect(dialog.emitted('saved')).toEqual([[place({ timezone: 'Europe/Berlin' })]])
    expect(dialog.emitted('update:open')).toEqual([[false]])
  })

  it("saves the clock's for a place with none", async () => {
    const api = fakeApi({ [SET_TIME_ZONE]: place({ timezone: CLOCK }) })
    const dialog = mountDialog(place())
    await flushPromises()
    await clickInDialog('Save')
    expect(api.sent[0].body).toEqual({ timezone: CLOCK })
    expect(dialog.emitted('saved')).toHaveLength(1)
  })

  it('waits for a choice when there is no time zone to save', async () => {
    const api = fakeApi({ [SET_TIME_ZONE]: place({ timezone: CLOCK }) })
    const dialog = mountDialog(place({ timezone: null }), { clockTimeZone: null })
    await flushPromises()
    const [save] = dialogButtons('Save')
    expect(save.disabled).toBe(true)
    save.click()
    await flushPromises()
    expect(api.sent).toEqual([])
    expect(dialog.emitted('saved')).toBeUndefined()
  })

  it('saves the same time zone again', async () => {
    const api = fakeApi({ [SET_TIME_ZONE]: place({ timezone: 'Asia/Tokyo' }) })
    const dialog = mountDialog(place({ timezone: 'Asia/Tokyo' }))
    await flushPromises()
    await clickInDialog('Save')
    expect(api.sent).toHaveLength(1)
    expect(api.sent[0].body).toEqual({ timezone: 'Asia/Tokyo' })
    expect(dialog.emitted('saved')).toHaveLength(1)
  })

  it("shows the API's message and stays open", async () => {
    fakeApi({ [SET_TIME_ZONE]: apiError(422, 'invalid_timezone', 'That is not a time zone this device lists.') })
    const dialog = mountDialog(place({ timezone: 'Asia/Tokyo' }))
    await flushPromises()
    await clickInDialog('Save')
    expect(dialogText()).toContain('That is not a time zone this device lists.')
    expect(dialog.emitted('saved')).toBeUndefined()
    expect(dialog.emitted('update:open')).toBeUndefined()
    expect(dialog.emitted('stale')).toBeUndefined()
  })

  it('a 409 asks the page to load again', async () => {
    fakeApi({ [SET_TIME_ZONE]: apiError(409, 'not_found', 'This place changed. Reload the page and try again.') })
    const dialog = mountDialog(place({ timezone: 'Asia/Tokyo' }))
    await flushPromises()
    await clickInDialog('Save')
    expect(dialogText()).toContain('This place changed.')
    expect(dialog.emitted('stale')).toHaveLength(1)
    expect(dialog.emitted('saved')).toBeUndefined()
  })

  it('a 5xx asks the page to load again, since the time zone may be saved though its rows were not', async () => {
    fakeApi({
      [SET_TIME_ZONE]: apiError(502, 'nodered_unreachable', "The time zone was changed, but its stored rows weren't updated. Save it again."),
    })
    const dialog = mountDialog(place({ timezone: 'Asia/Tokyo' }))
    await flushPromises()
    await clickInDialog('Save')
    expect(dialogText()).toContain("The time zone was changed, but its stored rows weren't updated.")
    expect(dialog.emitted('stale')).toHaveLength(1)
    expect(dialog.emitted('saved')).toBeUndefined()
    expect(dialog.emitted('update:open')).toBeUndefined() // the dialog stays open
  })

  it('starts over each time it opens', async () => {
    const dialog = mountDialog(place({ timezone: 'Asia/Tokyo' }))
    await flushPromises()
    await dialog.findComponent({ name: 'VAutocomplete' }).setValue('Europe/Berlin')
    await dialog.setProps({ open: false })
    await flushPromises()
    await dialog.setProps({ open: true })
    await flushPromises()
    expect(dialog.findComponent({ name: 'VAutocomplete' }).props('modelValue')).toBe('Asia/Tokyo')
  })
})
