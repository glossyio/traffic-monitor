// A place's stored reference pictures: the list with both views of each, Download and Delete on each, and for the place
// in use a button per enabled camera that takes another.
import { flushPromises, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { components } from '../src/api/schema'
import PlacePictures from '../src/modules/location/PlacePictures.vue'
import { ADMIN, apiError, json, pictureOut, referenceOut, signedIn } from './fake-api'
import { buttonsIn, clickIn, clickInDialog, dialogText, mountAlone } from './mount'

type SurveyOut = components['schemas']['SurveyOut']

const PLACE: SurveyOut = {
  id: '3f9a1c2e-si',
  description: 'Corner by the park',
  lat: 45.0,
  lon: -122.0,
  status: 'in_use',
  source: 'ui',
  created_at: '2026-10-01T12:00:00+00:00',
  updated_at: '2026-10-01T12:00:00+00:00',
  headings: [],
  timezone: null,
  stored_lat: 45.0,
  stored_lon: -122.0,
  first_used: null,
  last_used: null,
  open_count: 1,
  deployment_count: 1,
  imported: false,
  pictures: 3,
}
const USED: SurveyOut = { ...PLACE, status: 'used', open_count: 0 }

const A = '000000000000000a'
const B = '000000000000000b'
const C = '000000000000000c'
const NEWEST = pictureOut({ id: C, taken_at: '2026-11-20T10:00:00Z', camera: 'camera_2_77aa10', reason: 'daylight' })
const MIDDLE = pictureOut({ id: B, taken_at: '2026-11-19T10:00:00Z', mark: 'person', reason: 'mounting' })
const OLDEST = pictureOut({ id: A, taken_at: '2026-11-18T10:00:00Z', mark: 'unchecked', after_restart: true, reason: 'deployed' })

const EMPTY = 'No reference picture is stored for this place.'
const DELETE_TITLE = 'Delete this picture?'
const DELETE_TEXT = "Both views are removed from the device. This can't be undone."

function mountPictures(props: Record<string, unknown> = {}) {
  return mountAlone(PlacePictures, {
    place: PLACE,
    pictures: [OLDEST, NEWEST, MIDDLE],
    cameras: [],
    ...props,
  })
}

function rows(wrapper: VueWrapper) {
  return wrapper.findAll('[data-picture]')
}

describe("a place's stored pictures", () => {
  beforeEach(() => document.body.replaceChildren())
  afterEach(() => vi.restoreAllMocks())

  it('lists the pictures newest first, with both views of each', () => {
    signedIn(ADMIN, {})
    const wrapper = mountPictures()
    expect(rows(wrapper).map((row) => row.attributes('data-picture'))).toEqual([C, B, A])
    for (const row of rows(wrapper)) {
      const id = row.attributes('data-picture')
      expect(row.findAll('img').map((img) => [img.attributes('src'), img.attributes('loading')])).toEqual([
        [`/api/v1/pictures/${id}/clean.jpg`, 'lazy'],
        [`/api/v1/pictures/${id}/zones.jpg`, 'lazy'],
      ])
      expect(row.findAll('img').map((img) => img.attributes('alt'))).toEqual([
        "The camera's view",
        "The same view with Frigate's zone outlines",
      ])
    }
  })

  it('shows the time, the camera, why, and the mark of each', () => {
    signedIn(ADMIN, {})
    const wrapper = mountPictures()
    const [newest, middle, oldest] = rows(wrapper)
    const when = (iso: string) => new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
    expect(newest.text()).toContain(when('2026-11-20T10:00:00Z'))
    expect(newest.text()).toContain('camera_2_77aa10')
    expect(newest.text()).toContain('Taken again in daylight')
    expect(newest.find('[data-mark]').exists()).toBe(false)

    expect(middle.text()).toContain("The camera's mounting changed")
    expect(middle.find('[data-mark]').text()).toContain(
      'Frigate was tracking a person. Blur them before you share it, or leave it out.',
    )
    expect(middle.find('[data-mark]').classes().join(' ')).toContain('text-warning')

    expect(oldest.text()).toContain('The unit was deployed here')
    expect(oldest.find('[data-mark]').text()).toContain(
      "The device couldn't check for people. Look closely before you share it.",
    )
    expect(oldest.find('[data-mark]').classes().join(' ')).toContain('text-info')
    // The restart note is plain text under the reason, never inside an alert
    const note = oldest.find('[data-restart]')
    expect(note.text()).toBe('The unit restarted before this picture, so it may not show this place.')
    expect(note.element.closest('.v-alert')).toBeNull()
    expect(newest.find('[data-restart]').exists()).toBe(false)
  })

  it('says so when the place has no picture', () => {
    signedIn(ADMIN, {})
    const wrapper = mountPictures({ pictures: [] })
    expect(wrapper.text()).toContain(EMPTY)
    expect(rows(wrapper)).toHaveLength(0)
  })

  it('waits while the list is being loaded, and says nothing about it being empty', () => {
    signedIn(ADMIN, {})
    const wrapper = mountPictures({ pictures: undefined })
    expect(wrapper.text()).not.toContain(EMPTY)
    expect(wrapper.find('.v-progress-linear').exists()).toBe(true)
  })

  it('shows why the list could not be loaded, and asks to try again', async () => {
    signedIn(ADMIN, {})
    const wrapper = mountPictures({ pictures: undefined, error: 'The device could not list its pictures.' })
    expect(wrapper.text()).toContain('The device could not list its pictures.')
    expect(wrapper.text()).not.toContain(EMPTY)
    await clickIn(wrapper.element, 'Try again')
    expect(wrapper.emitted('retry')).toHaveLength(1)
  })

  it('has a Download and a Delete on each picture, and no button for several', () => {
    signedIn(ADMIN, {})
    const wrapper = mountPictures()
    for (const row of rows(wrapper)) {
      expect(buttonsIn(row.element, 'Download')).toHaveLength(1)
      expect(buttonsIn(row.element, 'Delete')).toHaveLength(1)
    }
    const names = wrapper.findAll('button').map((b) => b.text().trim().toLowerCase())
    expect(names.filter((name) => /all|selected|several|zip/.test(name))).toEqual([])
  })

  it('opens the review for the picture whose Download was pressed', async () => {
    signedIn(ADMIN, {})
    const wrapper = mountPictures()
    await clickIn(rows(wrapper)[1].element, 'Download')
    expect(dialogText()).toContain('Look at both views before this picture leaves the device')
    const sources = [...document.querySelectorAll('.v-overlay-container .v-dialog img')].map((img) => img.getAttribute('src'))
    expect(sources).toEqual([`/api/v1/pictures/${B}/clean.jpg`, `/api/v1/pictures/${B}/zones.jpg`])
  })

  it('tells the review whether the place has a point', async () => {
    signedIn(ADMIN, {})
    const wrapper = mountPictures({ place: { ...PLACE, lat: null, lon: null } })
    await clickIn(rows(wrapper)[0].element, 'Download')
    const box = document.querySelector<HTMLInputElement>('.v-overlay-container .v-dialog input[type="checkbox"]')
    expect(box?.disabled).toBe(true)
  })

  describe('Delete', () => {
    it('asks first, and sends nothing until the admin confirms', async () => {
      const api = signedIn(ADMIN, { [`DELETE /api/v1/pictures/${C}`]: json(204, null) })
      const wrapper = mountPictures()
      await clickIn(rows(wrapper)[0].element, 'Delete')
      expect(dialogText()).toContain(DELETE_TITLE)
      expect(dialogText()).toContain(DELETE_TEXT)
      expect(api.sent.some((request) => request.method === 'DELETE')).toBe(false)
      await clickInDialog('Cancel')
      expect(api.sent.some((request) => request.method === 'DELETE')).toBe(false)
      expect(wrapper.emitted('changed')).toBeUndefined()
    })

    it('deletes that picture and says the list changed', async () => {
      const api = signedIn(ADMIN, { [`DELETE /api/v1/pictures/${B}`]: json(204, null) })
      const wrapper = mountPictures()
      await clickIn(rows(wrapper)[1].element, 'Delete')
      await clickInDialog('Delete')
      expect(api.sent.filter((request) => request.method === 'DELETE')).toEqual([
        { method: 'DELETE', path: `/api/v1/pictures/${B}`, body: null },
      ])
      expect(wrapper.emitted('changed')).toHaveLength(1)
    })

    it("shows the API's message beside the row when it fails, and doesn't say the list changed", async () => {
      signedIn(ADMIN, { [`DELETE /api/v1/pictures/${B}`]: apiError(500, 'storage', 'The picture could not be removed.') })
      const wrapper = mountPictures()
      await clickIn(rows(wrapper)[1].element, 'Delete')
      await clickInDialog('Delete')
      expect(rows(wrapper)[1].text()).toContain('The picture could not be removed.')
      expect(rows(wrapper)[0].text()).not.toContain('The picture could not be removed.')
      expect(wrapper.emitted('changed')).toBeUndefined()
    })
  })

  describe('Take a reference picture', () => {
    const TAKE = 'POST /api/v1/cameras/camera_1_3fa9c2/reference'
    const KEEP = 'POST /api/v1/cameras/camera_1_3fa9c2/reference/made-up-ticket/keep'

    it('is offered for each enabled camera at the place in use', () => {
      signedIn(ADMIN, {})
      const one = mountPictures({ cameras: ['camera_1_3fa9c2'] })
      expect(buttonsIn(one.element, 'Take a reference picture')).toHaveLength(1)
      one.unmount()
      const two = mountPictures({ cameras: ['camera_1_3fa9c2', 'camera_2_77aa10'] })
      const buttons = buttonsIn(two.element, 'Take a reference picture')
      expect(buttons.map((b) => b.getAttribute('aria-label'))).toEqual([
        'Take a reference picture of camera_1_3fa9c2',
        'Take a reference picture of camera_2_77aa10',
      ])
    })

    it('is not offered for another place, or for a place in use with no camera on', () => {
      signedIn(ADMIN, {})
      expect(buttonsIn(mountPictures({ place: USED, cameras: [] }).element, 'Take a reference picture')).toHaveLength(0)
      expect(buttonsIn(mountPictures({ cameras: [] }).element, 'Take a reference picture')).toHaveLength(0)
    })

    it("is offered when the place has no picture yet", () => {
      signedIn(ADMIN, {})
      const wrapper = mountPictures({ pictures: [], cameras: ['camera_1_3fa9c2'] })
      expect(buttonsIn(wrapper.element, 'Take a reference picture')).toHaveLength(1)
    })

    it('opens the dialog for that camera, and says the list changed after a keep', async () => {
      signedIn(ADMIN, { [TAKE]: referenceOut(), [KEEP]: json(201, pictureOut()) })
      const wrapper = mountPictures({ cameras: ['camera_1_3fa9c2'] })
      await clickIn(wrapper.element, 'Take a reference picture')
      expect(dialogText()).toContain('Reference picture of camera_1_3fa9c2')
      await clickInDialog('Take the pictures')
      expect(wrapper.emitted('changed')).toBeUndefined()
      await clickInDialog('Keep on this device')
      await flushPromises()
      expect(wrapper.emitted('changed')).toHaveLength(1)
    })
  })
})
