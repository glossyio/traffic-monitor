// The Download your data card: the database's size, the box for the exact locations, the question, and the two
// requests behind one button.
import { flushPromises, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as download from '../src/components/download'
import DownloadCard from '../src/modules/sharing/DownloadCard.vue'
import { ADMIN, DOWNLOAD_FACTS, apiError, json, signedIn } from './fake-api'
import { clickInDialog, dialogText, field, mountAlone } from './mount'

const PLAIN = 'POST /api/v1/sharing/download'
const EXACT = 'POST /api/v1/surveys/database-copy'
const PLAIN_LINK = '/storefiles?files=/db/tmdb.sqlite&tm_token=abc'
const EXACT_LINK = '/storefiles?files=tmdb-exact-0123456789abcdef0123456789abcdef&tm_token=def'
const BOX = "Include each place's exact location"

const SUBTITLE = "Save a copy of this device's database on the computer or phone you're using. Nothing is uploaded."
const WHAT_IT_HOLDS =
  "The file holds everything in this device's database: the events, radar readings, and air quality readings it recorded, its deployments, its watch log and setup history, and any comments."
const ROUNDED =
  "Each place's location is in it as the database stores it, rounded. The file holds no exact location, no pictures or video, and no passwords or tokens."
const COPY_FIRST = 'The device makes a copy first, so the download can take a few minutes to start.'
const WARNING =
  'This copy of the database includes the exact location of each place the device has been at. The database on this device keeps its rounded locations. Give the copy only to someone who should know where the device was.'
const NO_MEDIA = 'The file holds no pictures or video, and no passwords or tokens.'
// The API's own words: modules/sharing/download.py with NODERED_MESSAGES, and modules/location/router.py's 409
const NOT_STARTED = "The download wasn't started. Node-RED didn't answer."
const NO_EXACT_LOCATIONS =
  'No place this device has been at has an exact location, so a copy would hold nothing more than the download without the box ticked.'
const NOTE_START =
  'The device is making a copy of the database. The download starts by itself when the copy is ready, which can take a few minutes for a large database. The file\'s name ends in '

const answers = (extra: Record<string, unknown> = {}) => ({
  [PLAIN]: { url: PLAIN_LINK },
  [EXACT]: { url: EXACT_LINK, places: 2 },
  ...extra,
})

function mountCard(facts: { database_bytes: number | null; exact_places: number; pictures: number } = DOWNLOAD_FACTS) {
  return mountAlone(DownloadCard, { facts })
}

const posts = (api: { sent: { method: string; path: string }[] }, path: string) =>
  api.sent.filter((r) => r.method === 'POST' && r.path === path)

function sizeShown(wrapper: VueWrapper) {
  const label = wrapper.findAll('.text-body-2').find((d) => d.text() === 'Database size')
  return label?.element.nextElementSibling?.textContent?.trim()
}

const downloadButton = (wrapper: VueWrapper) => wrapper.findAll('button').find((b) => b.text().trim() === 'Download')!

async function press(wrapper: VueWrapper, text: string) {
  const buttons = wrapper.findAll('button').filter((b) => b.text().trim() === text)
  expect(buttons.length, `one button reading "${text}"`).toBe(1)
  await buttons[0].trigger('click')
  await flushPromises()
}

describe('the Download your data card', () => {
  beforeEach(() => document.body.replaceChildren())
  afterEach(() => vi.restoreAllMocks())

  it("shows the database's size", () => {
    signedIn(ADMIN, answers())
    const wrapper = mountCard()
    expect(wrapper.find('h2').text()).toBe('Download your data')
    expect(wrapper.text()).toContain(SUBTITLE)
    const label = wrapper.findAll('.text-body-2').find((d) => d.text() === 'Database size')
    expect(label?.element.nextElementSibling?.textContent?.trim()).toBe('700 MB')
  })

  it('shows no size when the device has none', () => {
    signedIn(ADMIN, answers())
    const wrapper = mountCard({ database_bytes: null, exact_places: 2, pictures: 0 })
    expect(wrapper.text()).not.toContain('Database size')
    expect(wrapper.text()).toContain(SUBTITLE)
    expect(wrapper.findAll('button').some((b) => b.text() === 'Download')).toBe(true)
  })

  describe('the stored reference pictures', () => {
    const LINE =
      "They aren't part of this download. Download or delete them under each place on the Location page."
    const stored = (wrapper: VueWrapper) => {
      const label = wrapper.findAll('.text-body-2').find((d) => d.text() === 'Reference pictures stored')
      return label?.element.nextElementSibling?.textContent?.trim()
    }

    it('says how many there are, and that they are not in the download, when there are some', () => {
      signedIn(ADMIN, answers())
      const wrapper = mountCard({ ...DOWNLOAD_FACTS, pictures: 3 })
      expect(stored(wrapper)).toBe('3')
      expect(wrapper.text()).toContain(LINE)
    })

    it('says nothing when there are none', () => {
      signedIn(ADMIN, answers())
      const wrapper = mountCard({ ...DOWNLOAD_FACTS, pictures: 0 })
      expect(wrapper.text()).not.toContain('Reference pictures stored')
      expect(wrapper.text()).not.toContain(LINE)
    })

    it('still says it when the database has no size', () => {
      signedIn(ADMIN, answers())
      const wrapper = mountCard({ database_bytes: null, exact_places: 0, pictures: 1 })
      expect(stored(wrapper)).toBe('1')
      expect(wrapper.text()).toContain(LINE)
    })

    it('follows the facts the page reads again', async () => {
      signedIn(ADMIN, answers())
      const wrapper = mountCard({ ...DOWNLOAD_FACTS, pictures: 2 })
      expect(stored(wrapper)).toBe('2')
      await wrapper.setProps({ facts: { ...DOWNLOAD_FACTS, pictures: 0 } })
      expect(stored(wrapper)).toBeUndefined()
    })
  })

  it('starts with the box unticked', () => {
    signedIn(ADMIN, answers())
    const wrapper = mountCard()
    const box = field(wrapper, BOX)
    expect(box.element.checked).toBe(false)
    expect(box.element.disabled).toBe(false)
    expect(wrapper.text()).toContain(
      "Without it, the file holds each place's location rounded, as the database stores it.",
    )
  })

  it('turns the box off and says why when no place has an exact location', () => {
    signedIn(ADMIN, answers())
    const wrapper = mountCard({ database_bytes: 734003200, exact_places: 0, pictures: 0 })
    expect(field(wrapper, BOX).element.disabled).toBe(true)
    expect(wrapper.text()).toContain('No place this device has been at has an exact location yet.')
    expect(wrapper.text()).not.toContain('Without it, the file holds')
  })

  it('asks before a download and says what the file holds', async () => {
    const api = signedIn(ADMIN, answers())
    const open = vi.spyOn(download, 'openDownload').mockImplementation(() => {})
    const wrapper = mountCard()
    await press(wrapper, 'Download')
    const text = dialogText()
    expect(text).toContain('Download the database?')
    expect(text).toContain(WHAT_IT_HOLDS)
    expect(text).toContain(ROUNDED)
    expect(text).toContain(COPY_FIRST)
    expect(text).not.toContain(WARNING)
    expect(api.sent.some((r) => r.method === 'POST')).toBe(false)
    expect(open).not.toHaveBeenCalled()
  })

  it('sends nothing when the question is cancelled', async () => {
    const api = signedIn(ADMIN, answers())
    const open = vi.spyOn(download, 'openDownload').mockImplementation(() => {})
    const wrapper = mountCard()
    await press(wrapper, 'Download')
    await clickInDialog('Cancel')
    expect(api.sent.some((r) => r.method === 'POST')).toBe(false)
    expect(open).not.toHaveBeenCalled()
    expect(wrapper.text()).not.toContain(NOTE_START)
  })

  it('asks the Sharing API for a plain download and opens its link', async () => {
    const api = signedIn(ADMIN, answers())
    const open = vi.spyOn(download, 'openDownload').mockImplementation(() => {})
    const wrapper = mountCard()
    await press(wrapper, 'Download')
    await clickInDialog('Download')
    expect(posts(api, '/api/v1/sharing/download')).toHaveLength(1)
    expect(posts(api, '/api/v1/surveys/database-copy')).toHaveLength(0)
    expect(open).toHaveBeenCalledTimes(1)
    expect(open).toHaveBeenCalledWith(PLAIN_LINK)
    expect(wrapper.text()).toContain(`${NOTE_START}tmdb.tar.gz.`)
  })

  it('shows the warning when the box is ticked', async () => {
    const api = signedIn(ADMIN, answers())
    const wrapper = mountCard()
    await field(wrapper, BOX).setValue(true)
    await press(wrapper, 'Download')
    const text = dialogText()
    expect(text).toContain('Download the database with exact locations?')
    expect(text).toContain(WHAT_IT_HOLDS)
    expect(text).toContain(WARNING)
    expect(text).toContain(NO_MEDIA)
    expect(text).toContain(COPY_FIRST)
    expect(text).not.toContain('The file holds no exact location')
    expect(api.sent.some((r) => r.method === 'POST')).toBe(false)
  })

  it('asks the Location API for a download with exact locations', async () => {
    const api = signedIn(ADMIN, answers())
    const open = vi.spyOn(download, 'openDownload').mockImplementation(() => {})
    const wrapper = mountCard()
    await field(wrapper, BOX).setValue(true)
    await press(wrapper, 'Download')
    await clickInDialog('Download')
    expect(posts(api, '/api/v1/surveys/database-copy')).toHaveLength(1)
    expect(posts(api, '/api/v1/sharing/download')).toHaveLength(0)
    expect(open).toHaveBeenCalledTimes(1)
    expect(open).toHaveBeenCalledWith(EXACT_LINK)
    expect(wrapper.text()).toContain(`${NOTE_START}tmdb-exact-locations.tar.gz.`)
  })

  it('keeps Download and the box off after a download has started', async () => {
    const api = signedIn(ADMIN, answers())
    const open = vi.spyOn(download, 'openDownload').mockImplementation(() => {})
    const wrapper = mountCard()
    await press(wrapper, 'Download')
    await clickInDialog('Download')
    const button = wrapper.findAll('button').find((b) => b.text().trim() === 'Download')!
    expect(button.element.disabled).toBe(true)
    expect(field(wrapper, BOX).element.disabled).toBe(true)
    await button.trigger('click')
    await flushPromises()
    expect(document.querySelector('.v-overlay--active')).toBeNull() // no question opened again
    expect(api.sent.filter((r) => r.method === 'POST')).toHaveLength(1)
    expect(open).toHaveBeenCalledTimes(1)
  })

  it('keeps the note and leaves Download and the box off when the page reads new facts', async () => {
    signedIn(ADMIN, answers())
    vi.spyOn(download, 'openDownload').mockImplementation(() => {})
    const wrapper = mountCard()
    await press(wrapper, 'Download')
    await clickInDialog('Download')
    await wrapper.setProps({ facts: { database_bytes: 1, exact_places: 2, pictures: 0 } })
    expect(wrapper.text()).toContain(`${NOTE_START}tmdb.tar.gz.`)
    expect(downloadButton(wrapper).element.disabled).toBe(true)
    expect(field(wrapper, BOX).element.disabled).toBe(true)
    expect(sizeShown(wrapper)).toBe('less than 1 MB')
  })

  it("keeps a refused download's message when the page reads new facts", async () => {
    signedIn(ADMIN, answers({ [PLAIN]: apiError(502, 'nodered_error', NOT_STARTED) }))
    const wrapper = mountCard()
    await press(wrapper, 'Download')
    await clickInDialog('Download')
    await wrapper.setProps({ facts: { database_bytes: 1, exact_places: 2, pictures: 0 } })
    expect(wrapper.text()).toContain(NOT_STARTED)
  })

  it('leaves a ticked box usable when the count of places drops to 0, so it can be unticked', async () => {
    const api = signedIn(ADMIN, answers())
    const wrapper = mountCard()
    await field(wrapper, BOX).setValue(true)
    await wrapper.setProps({ facts: { database_bytes: 734003200, exact_places: 0, pictures: 0 } })
    expect(field(wrapper, BOX).element.checked).toBe(true)
    expect(field(wrapper, BOX).element.disabled).toBe(false)
    expect(wrapper.text()).toContain('No place this device has been at has an exact location yet.')
    await field(wrapper, BOX).setValue(false)
    expect(field(wrapper, BOX).element.disabled).toBe(true)
    await press(wrapper, 'Download')
    const text = dialogText()
    expect(text).toContain('Download the database?')
    expect(text).toContain(ROUNDED)
    expect(text).not.toContain(WARNING)
    expect(api.sent.some((r) => r.method === 'POST')).toBe(false)
  })

  it.each([
    ['the plain route', false, PLAIN, 502, 'nodered_error', NOT_STARTED],
    ['the exact route', true, EXACT, 409, 'no_exact_locations', NO_EXACT_LOCATIONS],
  ])("shows the API's message and opens nothing when the download can't start (%s)", async (_n, ticked, route, status, code, message) => {
    const api = signedIn(ADMIN, answers({ [route]: apiError(status, code, message) }))
    const open = vi.spyOn(download, 'openDownload').mockImplementation(() => {})
    const wrapper = mountCard()
    if (ticked) await field(wrapper, BOX).setValue(true)
    await press(wrapper, 'Download')
    await clickInDialog('Download')
    expect(wrapper.text()).toContain(message)
    expect(wrapper.text()).not.toContain(NOTE_START)
    expect(open).not.toHaveBeenCalled()
    // it can be tried again
    const button = wrapper.findAll('button').find((b) => b.text().trim() === 'Download')!
    expect(button.element.disabled).toBe(false)
    expect(api.sent.filter((r) => r.method === 'POST')).toHaveLength(1)
  })

  it('clears an earlier message when the admin tries again', async () => {
    let calls = 0
    signedIn(
      ADMIN,
      answers({ [PLAIN]: () => (++calls === 1 ? apiError(502, 'nodered_error', NOT_STARTED) : json(200, { url: PLAIN_LINK })) }),
    )
    const open = vi.spyOn(download, 'openDownload').mockImplementation(() => {})
    const wrapper = mountCard()
    await press(wrapper, 'Download')
    await clickInDialog('Download')
    expect(wrapper.text()).toContain(NOT_STARTED)
    await press(wrapper, 'Download')
    await clickInDialog('Download')
    expect(wrapper.text()).not.toContain(NOT_STARTED)
    expect(open).toHaveBeenCalledWith(PLAIN_LINK)
    expect(wrapper.text()).toContain(NOTE_START)
  })
})
