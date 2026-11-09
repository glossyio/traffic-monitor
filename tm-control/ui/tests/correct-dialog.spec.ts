// The correction dialog: a used place's location (POST /surveys/{id}/location), with a second confirmation for a
// point far enough to look like a move, or one deployment's bearing (POST /surveys/{id}/deployments/{id}/bearing).
import { flushPromises, type VueWrapper } from '@vue/test-utils'
import { beforeEach, describe, expect, it } from 'vitest'
import type { components } from '../src/api/schema'
import CorrectDialog from '../src/modules/location/CorrectDialog.vue'
import { apiError, fakeApi } from './fake-api'
import { clickInDialog, dialogButtons, dialogField, dialogText, mountAlone, typeInto } from './mount'

type SurveyOut = components['schemas']['SurveyOut']
type DeploymentOut = components['schemas']['DeploymentOut']

function place(changes: Partial<SurveyOut>): SurveyOut {
  return {
    id: 'c0ffee01-si',
    description: 'Front of the school',
    lat: 45.52252,
    lon: -122.6912,
    status: 'used',
    source: 'ui',
    created_at: '2026-10-01T12:00:00+00:00',
    updated_at: '2026-10-01T12:00:00+00:00',
    bearings: [],
    stored_lat: 45.52,
    stored_lon: -122.69,
    first_used: null,
    last_used: null,
    open_count: 0,
    deployment_count: 1,
    imported: false,
    ...changes,
  }
}

const NEAR = place({})
const FAR = place({ lat: 45.0, lon: -122.0, stored_lat: 45.0, stored_lon: -122.0 })

const DEPLOYMENT: DeploymentOut = {
  id: '1790000000000-0a1b2c3d-d',
  started: 1790000000000,
  ended: 1790500000000,
  lat: 45.52,
  lon: -122.69,
  bearing: 'ne',
  sensor_type: 'cameras',
  sensor_name: 'picam_h265',
  location_precision: 2,
}

const LOCATION = 'POST /api/v1/surveys/c0ffee01-si/location'
const BEARING = 'POST /api/v1/surveys/c0ffee01-si/deployments/1790000000000-0a1b2c3d-d/bearing'
const FAR_TEXT = "That's far enough to look like a move. Correct it anyway?"

function mountCorrect(kind: 'location' | 'bearing', survey: SurveyOut, deployment?: DeploymentOut) {
  return mountAlone(CorrectDialog, { open: true, kind, place: survey, deployment })
}

function correctButton() {
  const buttons = dialogButtons('Correct')
  expect(buttons).toHaveLength(1)
  return buttons[0]
}

// Choose a bearing in the dialog's select, as picking from its menu would
async function choose(wrapper: VueWrapper, bearing: string) {
  await wrapper.findComponent({ name: 'VSelect' }).setValue(bearing)
  await flushPromises()
}

describe('correcting a location', () => {
  beforeEach(() => document.body.replaceChildren())

  it('says what a correction does, starting from the place\'s point', async () => {
    mountCorrect('location', NEAR)
    await flushPromises()
    expect(dialogText()).toContain(
      'Use this only if the location was entered wrong. Every record from this place will say it was at the new ' +
        'point. If the unit moved, deploy it to the place it moved to instead.',
    )
    expect(dialogText()).toContain('Copies and uploads that already left the device keep the old values.')
    expect(dialogField('Coordinates').value).toBe('45.52252, -122.69120')
    expect(document.querySelector('.v-overlay-container .v-dialog')?.getAttribute('aria-label')).toBe(
      'Correct location',
    )
  })

  it('posts a correction within 1 km without asking again', async () => {
    const api = fakeApi({ [LOCATION]: NEAR })
    const dialog = mountCorrect('location', NEAR)
    await flushPromises()
    await typeInto(dialogField('Coordinates'), '45.52, -122.69')
    await typeInto(dialogField('Reason'), 'The last digits were typed wrong')
    await clickInDialog('Correct')
    expect(document.body.textContent).not.toContain(FAR_TEXT)
    expect(api.sent).toEqual([
      {
        method: 'POST',
        path: '/api/v1/surveys/c0ffee01-si/location',
        body: { lat: 45.52, lon: -122.69, reason: 'The last digits were typed wrong' },
      },
    ])
    expect(dialog.emitted('corrected')).toHaveLength(1)
    expect(dialog.emitted('update:open')).toEqual([[false]])
  })

  it('asks again for a point far enough to look like a move, and posts after Correct it anyway', async () => {
    const api = fakeApi({ [LOCATION]: FAR })
    const dialog = mountCorrect('location', FAR)
    await flushPromises()
    await typeInto(dialogField('Coordinates'), '45.52252, -122.69120')
    await clickInDialog('Correct')
    expect(api.sent).toEqual([])
    expect(document.body.textContent).toContain(FAR_TEXT)
    await clickInDialog('Correct it anyway')
    expect(api.sent).toEqual([
      {
        method: 'POST',
        path: '/api/v1/surveys/c0ffee01-si/location',
        body: { lat: 45.52252, lon: -122.6912, reason: null },
      },
    ])
    expect(dialog.emitted('corrected')).toHaveLength(1)
  })

  it('sends nothing when the far correction is cancelled', async () => {
    const api = fakeApi({ [LOCATION]: FAR })
    const dialog = mountCorrect('location', FAR)
    await flushPromises()
    await typeInto(dialogField('Coordinates'), '45.52252, -122.69120')
    await clickInDialog('Correct')
    // Two dialogs are open now, each with a Cancel; the confirmation's is the later one
    const cancels = dialogButtons('Cancel')
    expect(cancels).toHaveLength(2)
    cancels[1].click()
    await flushPromises()
    expect(api.sent).toEqual([])
    expect(dialog.emitted('corrected')).toBeUndefined()
  })

  it('refuses a blank point or a decimal comma', async () => {
    mountCorrect('location', NEAR)
    await flushPromises()
    await typeInto(dialogField('Coordinates'), '')
    expect(correctButton().disabled).toBe(true)
    await typeInto(dialogField('Coordinates'), '45,52252, -122,69120')
    expect(dialogText()).toContain('Enter latitude, longitude with a dot as the decimal mark')
    expect(correctButton().disabled).toBe(true)
  })

  it('shows the message and asks the page to reload when config.yml changed meanwhile', async () => {
    fakeApi({
      [LOCATION]: apiError(
        409,
        'config_changed',
        'config.yml changed since it was read. Reload the page and try again.',
      ),
    })
    const dialog = mountCorrect('location', NEAR)
    await flushPromises()
    await clickInDialog('Correct')
    expect(dialogText()).toContain('config.yml changed since it was read.')
    expect(dialog.emitted('stale')).toHaveLength(1)
    expect(dialog.emitted('corrected')).toBeUndefined()
  })
})

describe('correcting a bearing', () => {
  beforeEach(() => document.body.replaceChildren())

  it('posts the bearing and the reason', async () => {
    const api = fakeApi({ [BEARING]: { ...DEPLOYMENT, bearing: 'se' } })
    const dialog = mountCorrect('bearing', NEAR, DEPLOYMENT)
    await flushPromises()
    expect(dialogText()).toContain('picam_h265')
    expect(dialogText()).toContain('If the unit was turned, use Modify deployment on the place in use instead.')
    expect(dialogText()).toContain('Copies and uploads that already left the device keep the old values.')
    expect(correctButton().disabled).toBe(true) // nothing to correct until the bearing changes
    await choose(dialog, 'se')
    await typeInto(dialogField('Reason'), 'The compass was read wrong')
    await clickInDialog('Correct')
    expect(api.sent).toEqual([
      {
        method: 'POST',
        path: '/api/v1/surveys/c0ffee01-si/deployments/1790000000000-0a1b2c3d-d/bearing',
        body: { bearing: 'se', reason: 'The compass was read wrong' },
      },
    ])
    expect(dialog.emitted('corrected')).toHaveLength(1)
    expect(dialog.emitted('update:open')).toEqual([[false]])
  })

  it('sends no reason when the field is left blank', async () => {
    const api = fakeApi({ [BEARING]: { ...DEPLOYMENT, bearing: '' } })
    const dialog = mountCorrect('bearing', NEAR, DEPLOYMENT)
    await flushPromises()
    await choose(dialog, '')
    await clickInDialog('Correct')
    expect(api.sent[0].body).toEqual({ bearing: '', reason: null })
  })
})
