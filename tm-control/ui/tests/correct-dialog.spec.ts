// The correction dialog: a used place's location (POST /surveys/{id}/location), with a second confirmation for a
// point far enough to look like a move, or one deployment's heading (POST /surveys/{id}/deployments/{id}/heading).
import { flushPromises, type VueWrapper } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
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
    headings: [],
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

// PinMap is stubbed: a button drops the pin at a point near the docs' example, and another at 45.0, -122.0
vi.mock('../src/modules/location/PinMap.vue', async () => {
  const { defineComponent, h } = await import('vue')
  return {
    __esModule: true,
    default: defineComponent({
      props: { styleUrl: String, centre: Object, pin: Object },
      emits: ['ready', 'failed', 'update:pin'],
      setup(_props, { emit }) {
        return () =>
          h('div', [
            h('button', { type: 'button', onClick: () => emit('update:pin', { lat: 45.52252, lon: -122.6912 }) }, 'Drop the pin'),
          ])
      },
    }),
  }
})

const MAP = { style_url: 'https://tiles.example.invalid/style' }

const NEAR = place({})
const FAR = place({ lat: 45.0, lon: -122.0, stored_lat: 45.0, stored_lon: -122.0 })

const DEPLOYMENT: DeploymentOut = {
  id: '1790000000000-0a1b2c3d-d',
  started: 1790000000000,
  ended: 1790500000000,
  lat: 45.52,
  lon: -122.69,
  heading_deg: 45,
  sensor_type: 'cameras',
  sensor_name: 'picam_h265',
  location_precision: 2,
}

const LOCATION = 'POST /api/v1/surveys/c0ffee01-si/location'
const HEADING = 'POST /api/v1/surveys/c0ffee01-si/deployments/1790000000000-0a1b2c3d-d/heading'
const FAR_TEXT = "That's far enough to look like a move. Correct it anyway?"

function mountCorrect(
  kind: 'location' | 'heading',
  survey: SurveyOut,
  deployment?: DeploymentOut,
  map: { style_url: string | null } = MAP,
) {
  return mountAlone(CorrectDialog, { open: true, kind, place: survey, deployment, map, centre: null })
}

function correctButton() {
  const buttons = dialogButtons('Correct')
  expect(buttons).toHaveLength(1)
  return buttons[0]
}

// Choose a heading in the dialog's select, as picking from its menu would
async function choose(wrapper: VueWrapper, heading: number | null) {
  await wrapper.findComponent({ name: 'VSelect' }).setValue(heading)
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

  it('a point picked more than 1 km away still asks the second question', async () => {
    const api = fakeApi({ [LOCATION]: FAR })
    const dialog = mountCorrect('location', FAR)
    await flushPromises()
    await clickInDialog('Pick on a map')
    await flushPromises()
    await clickInDialog('Drop the pin')
    await clickInDialog('Use this point')
    expect(dialogField('Coordinates').value).toBe('45.52252, -122.69120')
    await clickInDialog('Correct')
    expect(api.sent).toEqual([])
    expect(document.body.textContent).toContain(FAR_TEXT)
    await clickInDialog('Correct it anyway')
    expect(api.sent).toHaveLength(1)
    expect(dialog.emitted('corrected')).toEqual([[true]]) // the map set the point
  })

  it('keeps its old spacing under the field when there is no map to pick on', async () => {
    const field = () => dialogField('Coordinates').closest('.v-input')!
    mountCorrect('location', NEAR, undefined, { style_url: null })
    await flushPromises()
    expect(dialogButtons('Pick on a map')).toHaveLength(0)
    expect(field().classList.contains('mb-4')).toBe(true)
    document.body.replaceChildren()

    mountCorrect('location', NEAR)
    await flushPromises()
    expect(dialogButtons('Pick on a map')).toHaveLength(1)
    expect(field().classList.contains('mb-4')).toBe(false) // the button carries the space below it
  })

  it('warns about fewer than four decimal places and still corrects', async () => {
    const api = fakeApi({ [LOCATION]: NEAR })
    const dialog = mountCorrect('location', NEAR)
    await flushPromises()
    await typeInto(dialogField('Coordinates'), '45.52, -122.69')
    expect(dialogText()).toContain('For an exact location, use at least four decimal places (about 10 m).')
    expect(correctButton().disabled).toBe(false)
    await clickInDialog('Correct')
    expect(api.sent).toHaveLength(1)
    expect(dialog.emitted('corrected')).toEqual([[false]]) // typed
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

describe('correcting a heading', () => {
  beforeEach(() => document.body.replaceChildren())

  it('posts the heading and the reason', async () => {
    const api = fakeApi({ [HEADING]: { ...DEPLOYMENT, heading_deg: 135 } })
    const dialog = mountCorrect('heading', NEAR, DEPLOYMENT)
    await flushPromises()
    expect(dialogText()).toContain('picam_h265')
    expect(dialogText()).toContain('If the unit was turned, use Modify deployment on the place in use instead.')
    expect(dialogText()).toContain('Copies and uploads that already left the device keep the old values.')
    expect(correctButton().disabled).toBe(true) // nothing to correct until the heading changes
    await choose(dialog, 135)
    await typeInto(dialogField('Reason'), 'The compass was read wrong')
    await clickInDialog('Correct')
    expect(api.sent).toEqual([
      {
        method: 'POST',
        path: '/api/v1/surveys/c0ffee01-si/deployments/1790000000000-0a1b2c3d-d/heading',
        body: { heading_deg: 135, reason: 'The compass was read wrong' },
      },
    ])
    expect(dialog.emitted('corrected')).toHaveLength(1)
    expect(dialog.emitted('update:open')).toEqual([[false]])
  })

  it('says the heading was entered wrong, and keeps a measured heading until another is chosen', async () => {
    const dialog = mountCorrect('heading', NEAR, { ...DEPLOYMENT, heading_deg: 40 })
    await flushPromises()
    expect(dialogText()).toContain('Use this only if the heading was entered wrong.')
    expect(dialogText()).not.toMatch(/bearing/i)
    expect(dialogText()).toContain('NE (40°)')
    expect(document.querySelector('.v-overlay-container .v-dialog')?.getAttribute('aria-label')).toBe(
      'Correct heading',
    )
    expect(correctButton().disabled).toBe(true)
    await choose(dialog, 45)
    expect(correctButton().disabled).toBe(false)
  })

  it("doesn't offer one deployment's measured heading when it opens on another", async () => {
    const dialog = mountCorrect('heading', NEAR, { ...DEPLOYMENT, heading_deg: 40 })
    await flushPromises()
    const titles = () =>
      (dialog.findComponent({ name: 'VSelect' }).props('items') as { title: string }[]).map((item) => item.title)
    expect(titles()).toContain('NE (40°)')
    await dialog.setProps({ open: false })
    await dialog.setProps({ deployment: { ...DEPLOYMENT, id: '1790600000000-0a1b2c3d-d' }, open: true })
    await flushPromises()
    expect(titles()).not.toContain('NE (40°)')
  })

  it('sends no reason when the field is left blank', async () => {
    const api = fakeApi({ [HEADING]: { ...DEPLOYMENT, heading_deg: null } })
    const dialog = mountCorrect('heading', NEAR, DEPLOYMENT)
    await flushPromises()
    await choose(dialog, null)
    await clickInDialog('Correct')
    expect(api.sent[0].body).toEqual({ heading_deg: null, reason: null })
  })
})
