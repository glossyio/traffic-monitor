// The Cameras page's reference picture dialog: the note before any picture, the take, the two pictures as the device
// holds them, the legend, the location box, the zip, and starting over when the pictures are gone.
import { flushPromises } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ADMIN, apiError, camerasState, cameraRow, json, newRow, referenceOut, signedIn } from './fake-api'
import { buttonsIn, clickIn, dialogButtons, dialogText, fieldIn, mountApp } from './mount'

const NAME = 'camera_1_3fa9c2'
const TAKE = `POST /api/v1/cameras/${NAME}/reference`
const BASE = `/api/v1/cameras/${NAME}/reference/made-up-ticket`
const PACKAGE = `GET ${BASE}/package`
const DROP = `DELETE ${BASE}`
const ZIP = new Uint8Array([0x50, 0x4b, 0x03, 0x04, 0, 0, 0, 0])
const EXPIRED = 'These pictures are no longer held on the device. Take them again.'
const NOTE =
  'This picture shows your street. Anyone who has it can tell where the unit is, and it shows whoever was in view. ' +
  "The device doesn't check the pictures for people. You are responsible for making sure nobody is in either " +
  'picture before you save them: look at both, and if anyone is in them, wait and take them again. Share them only ' +
  "with people you would give the unit's exact location. The data file also holds that location unless you clear " +
  'the box below.'
const INTRO =
  'A still picture of what this camera sees, and the same view with its zones marked, for a tool that places ' +
  'recorded paths on a street. You get one zip with both pictures, a data file with the zones, and a labelled drawing.'
const LOCATION = "Include this place's exact location"

function zipAnswer() {
  return new Response(ZIP, { status: 200, headers: { 'Content-Type': 'application/zip' } })
}

async function openPage(answers: Record<string, unknown> = {}, rows = [cameraRow()], frigate = 'ok' as const) {
  const api = signedIn(ADMIN, {
    'GET /api/v1/cameras': camerasState({ rows, frigate }),
    [TAKE]: referenceOut(),
    [PACKAGE]: zipAnswer(),
    [DROP]: json(204, null),
    ...answers,
  })
  const { wrapper } = await mountApp('/cameras')
  return { api, wrapper }
}

function dialog(): Element | null {
  return document.querySelector('.v-overlay-container .v-dialog')
}

function pictures(): HTMLImageElement[] {
  return [...(dialog()?.querySelectorAll('img') ?? [])]
}

// The URL of each request the page sent, with its query, in order
function urls(api: { fetch: { mock: { calls: unknown[][] } } }): string[] {
  return api.fetch.mock.calls.map(([input]) => {
    const url = new URL(input instanceof Request ? input.url : String(input), window.location.href)
    return `${input instanceof Request ? input.method : 'GET'} ${url.pathname}${url.search}`
  })
}

async function openDialog(wrapper: Awaited<ReturnType<typeof openPage>>['wrapper']) {
  await clickIn(wrapper.element, 'Reference picture')
}

async function takePictures() {
  await clickIn(dialog(), 'Take the pictures')
}

function saveSpies() {
  const blobs: Blob[] = []
  vi.spyOn(URL, 'createObjectURL').mockImplementation((blob) => {
    blobs.push(blob as Blob)
    return 'blob:http://localhost/reference'
  })
  vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {})
  const saved: string[] = []
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
    saved.push(this.download)
  })
  return { blobs, saved }
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('Reference picture', () => {
  it('opens from the row with the intro and the note, and no picture yet', async () => {
    const { api, wrapper } = await openPage()
    await openDialog(wrapper)
    expect(dialogText()).toContain(`Reference picture of ${NAME}`)
    expect(dialogText()).toContain(INTRO)
    expect(dialogText()).toContain(NOTE)
    expect(pictures()).toEqual([])
    expect(buttonsIn(dialog(), 'Take the pictures')).toHaveLength(1)
    expect(api.sent.some((request) => request.method === 'POST')).toBe(false)
  })

  it("isn't offered for a row that can't have one, nor while Frigate is down", async () => {
    const rows = [cameraRow({ in_frigate: 'off' }), newRow()]
    const { wrapper } = await openPage({}, rows)
    expect(buttonsIn(wrapper.element, 'Reference picture')).toHaveLength(0)
  })

  it("isn't offered while Frigate is down", async () => {
    const { wrapper } = await openPage({}, [cameraRow()], 'down' as 'ok')
    expect(buttonsIn(wrapper.element, 'Reference picture')).toHaveLength(0)
  })

  it('takes the pictures and shows them as the device holds them, with the note still above them and the legend', async () => {
    const { api, wrapper } = await openPage()
    await openDialog(wrapper)
    await takePictures()
    expect(api.sent.at(-1)).toMatchObject({ method: 'POST', path: `/api/v1/cameras/${NAME}/reference` })
    expect(pictures().map((img) => [img.getAttribute('src'), img.getAttribute('alt')])).toEqual([
      [`${BASE}/clean.jpg`, "The camera's view"],
      [`${BASE}/zones.jpg`, "The same view with Frigate's zone outlines"],
    ])
    const text = dialogText()
    expect(text).toContain('The two were taken a moment apart.')
    expect(text).toContain('The device holds these pictures in memory for 10 minutes and never saves them.')
    expect(text).toContain(NOTE)
    expect(dialog()?.querySelectorAll('[data-legend-row]')).toHaveLength(4)
    expect(text).toContain('A–B 12 m, B–C 7.3 m, C–D 12 m, D–A 7.3 m')
    expect(text).toContain('off in Frigate, not drawn')
    expect(dialog()?.querySelector('[data-people]')).toBeNull()
    expect(text).not.toContain('Frigate was tracking')
  })

  it('saves the zip with the location while the box is ticked, and without it once cleared', async () => {
    const { blobs, saved } = saveSpies()
    const { api, wrapper } = await openPage()
    await openDialog(wrapper)
    await takePictures()
    const box = fieldIn(dialog(), LOCATION)
    expect(box.checked).toBe(true)
    await clickIn(dialog(), 'Save the zip')
    expect(urls(api).at(-1)).toBe(`GET ${BASE}/package?location=true`)
    expect(saved).toEqual(['tm-reference_3f9a1c2e-si_camera_1_3fa9c2_20261118T183005Z.zip'])
    expect(blobs[0].size).toBe(ZIP.length)

    box.click()
    await flushPromises()
    expect(box.checked).toBe(false)
    await clickIn(dialog(), 'Save the zip')
    expect(urls(api).at(-1)).toBe(`GET ${BASE}/package?location=false`)
  })

  it('greys the box with a hint when the place has no point', async () => {
    const { api, wrapper } = await openPage({ [TAKE]: referenceOut({ has_location: false }) })
    saveSpies()
    await openDialog(wrapper)
    await takePictures()
    const box = fieldIn(dialog(), LOCATION)
    expect(box.disabled).toBe(true)
    expect(box.checked).toBe(false)
    expect(dialogText()).toContain('No place with coordinates is in use, so the data file holds no location.')
    await clickIn(dialog(), 'Save the zip')
    expect(urls(api).at(-1)).toBe(`GET ${BASE}/package?location=false`)
  })

  it('starts over with the expired message when Save finds the pictures gone', async () => {
    saveSpies()
    const { wrapper } = await openPage({ [PACKAGE]: apiError(404, 'reference_expired', EXPIRED) })
    await openDialog(wrapper)
    await takePictures()
    await clickIn(dialog(), 'Save the zip')
    expect(pictures()).toEqual([])
    expect(dialogText()).toContain(EXPIRED)
    expect(buttonsIn(dialog(), 'Take the pictures')).toHaveLength(1)
    expect(buttonsIn(dialog(), 'Save the zip')).toHaveLength(0)
  })

  it('starts over with the expired message when a picture fails to load', async () => {
    const { wrapper } = await openPage()
    await openDialog(wrapper)
    await takePictures()
    pictures()[1].dispatchEvent(new Event('error'))
    await flushPromises()
    expect(pictures()).toEqual([])
    expect(dialogText()).toContain(EXPIRED)
    expect(buttonsIn(dialog(), 'Save the zip')).toHaveLength(0)
  })

  it("shows the API's message when the take is refused, and stays on the first step", async () => {
    const message =
      'Frigate has no live picture from this camera right now. Check the camera on the Status page, then try again.'
    const { wrapper } = await openPage({ [TAKE]: apiError(409, 'no_picture', message) })
    await openDialog(wrapper)
    await takePictures()
    expect(dialog()?.querySelector('.v-alert[class*="error"]')?.textContent).toContain(message)
    expect(buttonsIn(dialog(), 'Take the pictures')).toHaveLength(1)
    expect(pictures()).toEqual([])
  })

  it('drops the old pictures before taking again', async () => {
    const { api, wrapper } = await openPage()
    await openDialog(wrapper)
    await takePictures()
    await clickIn(dialog(), 'Take again')
    const requests = api.sent.slice(-2).map((request) => `${request.method} ${request.path}`)
    expect(requests).toEqual([DROP, TAKE])
    expect(pictures()).toHaveLength(2)
  })

  it('drops the pictures on Close, and opens again at the first step', async () => {
    const { api, wrapper } = await openPage()
    await openDialog(wrapper)
    await takePictures()
    await clickIn(dialog(), 'Close')
    expect(api.sent.at(-1)).toMatchObject({ method: 'DELETE', path: BASE })
    expect(dialogButtons('Save the zip')).toHaveLength(0)
    await openDialog(wrapper)
    expect(pictures()).toEqual([])
    expect(buttonsIn(dialog(), 'Take the pictures')).toHaveLength(1)
  })
})
