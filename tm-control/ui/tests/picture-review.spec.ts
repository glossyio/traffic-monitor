// The review step before a stored picture leaves the device: both views of that one picture, the mark's line above them,
// the restart note under them, the location box, and the tick without which Download stays off.
import { flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import PictureReview from '../src/modules/location/PictureReview.vue'
import { ADMIN, apiError, pictureOut, signedIn } from './fake-api'
import { buttonsIn, clickIn, dialogText, fieldIn, mountAlone } from './mount'

const ID = '0123456789abcdef'
const OTHER = 'fedcba9876543210'
const PACKAGE = `POST /api/v1/pictures/${ID}/package`
const ZIP = new Uint8Array([0x50, 0x4b, 0x03, 0x04, 0, 0, 0, 0])
const TITLE = 'Look at both views before this picture leaves the device'
const INTRO =
  'This picture shows your street and whoever was in view. Anyone who has it can tell where the unit is. Look at both views before you download it.'
const TICK = 'I have looked at both views'
const LOCATION = "Include this place's exact location"
const PERSON = 'Frigate was tracking a person. Blur them before you share it, or leave it out.'
const UNCHECKED = "The device couldn't check for people. Look closely before you share it."
const RESTART = 'The unit restarted before this picture, so it may not show this place.'
const GONE = 'This picture is no longer on the device. Reload the page.'
const WAITING = 'You can tick this once both views have loaded.'
const VIEW_FAILED = "A view didn't load. Close this and open it again."

function zipAnswer(name = 'tm-reference_3f9a1c2e-si_camera_1_3fa9c2_20261118T183005Z.zip') {
  return new Response(ZIP, {
    status: 200,
    headers: { 'Content-Type': 'application/zip', 'Content-Disposition': `attachment; filename="${name}"` },
  })
}

function review(props: Record<string, unknown> = {}) {
  return mountAlone(PictureReview, { open: true, picture: pictureOut(), hasLocation: true, ...props })
}

function dialog(): Element | null {
  return document.querySelector('.v-overlay-container .v-dialog')
}

function images(): HTMLImageElement[] {
  return [...(dialog()?.querySelectorAll('img') ?? [])]
}

function tick() {
  return fieldIn(dialog(), TICK)
}

// jsdom loads no images, so a test says when a view has loaded, or failed
async function loaded(...which: number[]) {
  const found = images()
  for (const index of which.length ? which : found.keys()) found[index].dispatchEvent(new Event('load'))
  await flushPromises()
}

async function failed(index: number) {
  images()[index].dispatchEvent(new Event('error'))
  await flushPromises()
}

function download() {
  const found = buttonsIn(dialog(), 'Download')
  expect(found).toHaveLength(1)
  return found[0]
}

async function ticked() {
  await loaded() // both views, so the box can be ticked (a view that already loaded loads again, harmlessly)
  tick().click()
  await flushPromises()
}

function saveSpies() {
  const blobs: Blob[] = []
  vi.spyOn(URL, 'createObjectURL').mockImplementation((blob) => {
    blobs.push(blob as Blob)
    return 'blob:http://localhost/picture'
  })
  vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {})
  const saved: string[] = []
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
    saved.push(this.download)
  })
  return { blobs, saved }
}

describe('the review step for one stored picture', () => {
  beforeEach(() => document.body.replaceChildren())
  afterEach(() => vi.restoreAllMocks())

  it('says what it is for and shows both views of the one picture', async () => {
    signedIn(ADMIN, {})
    review()
    await flushPromises()
    expect(dialogText()).toContain(TITLE)
    expect(dialogText()).toContain(INTRO)
    // Both load at once: the dialog holds exactly two, and the tick waits for them
    expect(images().map((img) => [img.getAttribute('src'), img.getAttribute('alt'), img.getAttribute('loading')])).toEqual([
      [`/api/v1/pictures/${ID}/clean.jpg`, "The camera's view", null],
      [`/api/v1/pictures/${ID}/zones.jpg`, "The same view with Frigate's zone outlines", null],
    ])
  })

  it('keeps Download off until the tick, and on again only while it is ticked', async () => {
    signedIn(ADMIN, {})
    review()
    await flushPromises()
    expect(tick().checked).toBe(false)
    expect(download().disabled).toBe(true)
    await ticked()
    expect(download().disabled).toBe(false)
    await ticked()
    expect(download().disabled).toBe(true)
  })

  it('keeps the box disabled, with its hint, until both views have loaded', async () => {
    signedIn(ADMIN, {})
    review()
    await flushPromises()
    expect(tick().disabled).toBe(true)
    expect(dialogText()).toContain(WAITING)
    await loaded(0)
    expect(tick().disabled).toBe(true)
    expect(dialogText()).toContain(WAITING)
    await loaded(1)
    expect(tick().disabled).toBe(false)
    expect(dialogText()).not.toContain(WAITING)
    tick().click()
    await flushPromises()
    expect(tick().checked).toBe(true)
    expect(download().disabled).toBe(false)
  })

  it('says a view did not load, keeps the box disabled and Download off, and sends nothing', async () => {
    const api = signedIn(ADMIN, { [PACKAGE]: zipAnswer() })
    review()
    await flushPromises()
    await loaded(0)
    await failed(1)
    expect(dialogText()).toContain(VIEW_FAILED)
    expect(dialogText()).not.toContain(GONE) // the download's own 404 has its own line
    expect(dialogText()).not.toContain(WAITING)
    const alerts = [...(dialog()?.querySelectorAll('.v-alert') ?? [])]
    const alert = alerts.find((one) => one.textContent?.includes(VIEW_FAILED))
    expect(alert?.className).toContain('text-error')
    const first = dialog()?.querySelector('img')
    expect(alert && first && alert.compareDocumentPosition(first) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(tick().disabled).toBe(true)
    expect(download().disabled).toBe(true)
    tick().click()
    await flushPromises()
    expect(download().disabled).toBe(true)
    expect(api.sent.filter((one) => one.method === 'POST')).toEqual([])
  })

  it('counts the views again each time the dialog opens', async () => {
    signedIn(ADMIN, {})
    const wrapper = review()
    await flushPromises()
    await ticked()
    expect(tick().disabled).toBe(false)
    await wrapper.setProps({ open: false })
    await flushPromises()
    await wrapper.setProps({ open: true })
    await flushPromises()
    expect(tick().disabled).toBe(true)
    expect(dialogText()).toContain(WAITING)
    await loaded(0)
    expect(tick().disabled).toBe(true)
    await loaded(1)
    expect(tick().disabled).toBe(false)
  })

  it('counts the views again for another picture, and forgets a failure', async () => {
    signedIn(ADMIN, {})
    const wrapper = review()
    await flushPromises()
    await loaded(0)
    await failed(1)
    expect(dialogText()).toContain(VIEW_FAILED)
    await wrapper.setProps({ picture: pictureOut({ id: OTHER }) })
    await flushPromises()
    expect(dialogText()).not.toContain(VIEW_FAILED)
    expect(tick().disabled).toBe(true)
    await loaded(0)
    expect(tick().disabled).toBe(true) // one view of the new picture is not both
    await loaded(1)
    expect(tick().disabled).toBe(false)
  })

  it('shows a clear picture with no line above it', async () => {
    signedIn(ADMIN, {})
    review()
    await flushPromises()
    expect(dialog()?.querySelector('[data-mark]')).toBeNull()
    expect(dialog()?.querySelector('[data-restart]')).toBeNull()
  })

  it('a person picture shows its warning above the views and still needs the tick', async () => {
    signedIn(ADMIN, {})
    review({ picture: pictureOut({ mark: 'person' }) })
    await flushPromises()
    const line = dialog()?.querySelector('[data-mark]')
    expect(line?.textContent).toContain(PERSON)
    expect(line?.className).toContain('text-warning')
    const first = dialog()?.querySelector('img')
    expect(line && first && line.compareDocumentPosition(first) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(download().disabled).toBe(true)
    await ticked()
    expect(download().disabled).toBe(false)
  })

  it('says when the device could not check, as information', async () => {
    signedIn(ADMIN, {})
    review({ picture: pictureOut({ mark: 'unchecked' }) })
    await flushPromises()
    const line = dialog()?.querySelector('[data-mark]')
    expect(line?.textContent).toContain(UNCHECKED)
    expect(line?.className).toContain('text-info')
    expect(line?.className).not.toContain('text-warning')
  })

  it('a picture taken after a restart shows its note outside any alert, under the views', async () => {
    signedIn(ADMIN, {})
    review({ picture: pictureOut({ after_restart: true }) })
    await flushPromises()
    const note = dialog()?.querySelector('[data-restart]')
    expect(note?.textContent).toBe(RESTART)
    expect(note?.closest('.v-alert')).toBeNull()
    expect(dialog()?.querySelector('[data-mark]')).toBeNull()
    const last = [...(dialog()?.querySelectorAll('img') ?? [])].at(-1)
    expect(note && last && last.compareDocumentPosition(note) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  it("asks for the picture's id, with the location box's value and looked: true", async () => {
    const api = signedIn(ADMIN, { [PACKAGE]: zipAnswer() })
    saveSpies()
    review()
    await flushPromises()
    const box = fieldIn(dialog(), LOCATION)
    expect(box.checked).toBe(true)
    await ticked()
    await clickIn(dialog(), 'Download')
    expect(api.sent.at(-1)).toMatchObject({
      method: 'POST',
      path: `/api/v1/pictures/${ID}/package`,
      body: { location: true, looked: true },
    })

    box.click()
    await flushPromises()
    expect(box.checked).toBe(false)
    await ticked()
    await clickIn(dialog(), 'Download')
    expect(api.sent.at(-1)).toMatchObject({ body: { location: false, looked: true } })
  })

  it('turns the box off, and sends no location, for a place with none', async () => {
    const api = signedIn(ADMIN, { [PACKAGE]: zipAnswer() })
    saveSpies()
    review({ hasLocation: false })
    await flushPromises()
    const box = fieldIn(dialog(), LOCATION)
    expect(box.disabled).toBe(true)
    expect(box.checked).toBe(false)
    expect(dialogText()).toContain('This place has no coordinates, so the data file holds no location.')
    await ticked()
    await clickIn(dialog(), 'Download')
    expect(api.sent.at(-1)).toMatchObject({ body: { location: false, looked: true } })
  })

  it("saves the zip under the answer's file name", async () => {
    signedIn(ADMIN, { [PACKAGE]: zipAnswer('tm-reference_a-si_picam_20261118T183005Z.zip') })
    const { blobs, saved } = saveSpies()
    review()
    await flushPromises()
    await ticked()
    await clickIn(dialog(), 'Download')
    expect(saved).toEqual(['tm-reference_a-si_picam_20261118T183005Z.zip'])
    expect(blobs[0].size).toBe(ZIP.length)
  })

  it('says the picture is gone, and asks for a reload, when the device has no such picture', async () => {
    signedIn(ADMIN, { [PACKAGE]: apiError(404, 'not_found', 'There is no such picture.') })
    const { saved } = saveSpies()
    review()
    await flushPromises()
    await ticked()
    await clickIn(dialog(), 'Download')
    expect(dialogText()).toContain(GONE)
    expect(saved).toEqual([])
  })

  it("shows the API's message for any other refusal", async () => {
    signedIn(ADMIN, { [PACKAGE]: apiError(500, 'storage', 'The picture could not be read from the card.') })
    review()
    await flushPromises()
    await ticked()
    await clickIn(dialog(), 'Download')
    expect(dialogText()).toContain('The picture could not be read from the card.')
    expect(dialogText()).not.toContain(GONE)
  })

  it('clears the tick when the dialog is closed and opened again', async () => {
    signedIn(ADMIN, {})
    const wrapper = review()
    await flushPromises()
    await ticked()
    expect(tick().checked).toBe(true)
    await wrapper.setProps({ open: false })
    await flushPromises()
    await wrapper.setProps({ open: true })
    await flushPromises()
    expect(tick().checked).toBe(false)
    expect(download().disabled).toBe(true)
  })

  it('clears the tick when it opens for another picture', async () => {
    signedIn(ADMIN, {})
    const wrapper = review()
    await flushPromises()
    await ticked()
    expect(tick().checked).toBe(true)
    await wrapper.setProps({ picture: pictureOut({ id: OTHER }) })
    await flushPromises()
    expect(tick().checked).toBe(false)
    expect(images()[0].getAttribute('src')).toBe(`/api/v1/pictures/${OTHER}/clean.jpg`)
  })
})
