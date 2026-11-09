// Importing places from a CSV: the text pasted or read from a file, a preview (POST /surveys/import with dry_run),
// then the import itself, only when the preview found no errors.
import { flushPromises, type VueWrapper } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { components } from '../src/api/schema'
import ImportPlaces from '../src/modules/location/ImportPlaces.vue'
import { fakeApi } from './fake-api'
import { button, click, field, mountAlone } from './mount'

type Bearing = components['schemas']['Bearing']
type ImportOut = components['schemas']['ImportOut']
type ImportRow = components['schemas']['ImportRow']

const IMPORT = 'POST /api/v1/surveys/import'

const SENSORS: Bearing[] = [
  { sensor_type: 'cameras', sensor_name: 'picam_h265', bearing: 'n' },
  { sensor_type: 'radars', sensor_name: 'TM_RADAR_SERIAL_PORT_00', bearing: '' },
]

const CSV = [
  'description,lat,lon,picam_h265,TM_RADAR_SERIAL_PORT_00',
  'Corner by the park,45.0,-122.0,ne,',
  'Bus stop on the hill,,,,',
  '',
].join('\n')

const ROWS: ImportRow[] = [
  {
    line: 2,
    description: 'Corner by the park',
    lat: 45.0,
    lon: -122.0,
    bearings: [{ sensor_type: 'cameras', sensor_name: 'picam_h265', bearing: 'ne' }],
  },
  { line: 3, description: 'Bus stop on the hill', lat: null, lon: null, bearings: [] },
]

const BEARING_ERROR = 'The bearing for picam_h265 must be one of n, ne, e, se, s, sw, w, nw, or blank.'

function mountImport() {
  return mountAlone(ImportPlaces, { sensors: SENSORS })
}

async function paste(wrapper: VueWrapper, text: string) {
  await field(wrapper, 'Places as CSV').setValue(text)
  await flushPromises()
}

// The API's answers: the preview's for a dry run, and the import's, which creates one place per row
function importAnswers(preview: ImportOut) {
  return {
    [IMPORT]: async (request: Request) => {
      const body = (await request.clone().json()) as { dry_run: boolean }
      const answer = body.dry_run ? preview : { ...preview, created: ['0f0e0d0c-si', 'a1b2c3d4-si'] }
      return new Response(JSON.stringify(answer), { status: 200, headers: { 'Content-Type': 'application/json' } })
    },
  }
}

describe('importing places', () => {
  beforeEach(() => document.body.replaceChildren())

  it("says the format, with this unit's sensor names as the columns", () => {
    const wrapper = mountImport()
    expect(wrapper.text()).toContain('description,lat,lon,picam_h265,TM_RADAR_SERIAL_PORT_00')
    expect(wrapper.text()).toContain('n, ne, e, se, s, sw, w, nw')
    expect(wrapper.text()).toContain('Leave lat and lon blank for a place with no location.')
  })

  it('previews the pasted rows and the errors by line', async () => {
    const api = fakeApi(
      importAnswers({ rows: [ROWS[0]], errors: [{ line: 3, message: BEARING_ERROR }], created: [] }),
    )
    const wrapper = mountImport()
    expect(button(wrapper, 'Preview').element.disabled).toBe(true) // nothing to preview yet
    await paste(wrapper, CSV)
    await click(wrapper, 'Preview')
    expect(api.sent).toEqual([{ method: 'POST', path: '/api/v1/surveys/import', body: { csv: CSV, dry_run: true } }])
    const text = wrapper.text()
    expect(text).toContain('Corner by the park')
    expect(text).toContain('45.00000, -122.00000')
    expect(text).toContain('picam_h265 faces NE')
    expect(text).toContain('Line 3')
    expect(text).toContain(BEARING_ERROR)
    expect(button(wrapper, 'Import').element.disabled).toBe(true)
  })

  it('imports with dry_run false when the preview found no errors, and says how many were added', async () => {
    const api = fakeApi(importAnswers({ rows: ROWS, errors: [], created: [] }))
    const wrapper = mountImport()
    await paste(wrapper, CSV)
    await click(wrapper, 'Preview')
    expect(wrapper.text()).toContain('No location')
    expect(button(wrapper, 'Import').element.disabled).toBe(false)
    await click(wrapper, 'Import')
    expect(api.sent.map((r) => r.body)).toEqual([
      { csv: CSV, dry_run: true },
      { csv: CSV, dry_run: false },
    ])
    expect(wrapper.text()).toContain('Added 2 places')
    expect(wrapper.emitted('imported')).toHaveLength(1)
    expect(wrapper.findAll('button').some((b) => b.text().trim() === 'Import')).toBe(false) // can't import twice
  })

  it('forgets the preview when the text changes', async () => {
    fakeApi(importAnswers({ rows: ROWS, errors: [], created: [] }))
    const wrapper = mountImport()
    await paste(wrapper, CSV)
    await click(wrapper, 'Preview')
    await paste(wrapper, `${CSV}Another corner,,,,\n`)
    expect(wrapper.text()).not.toContain('Corner by the park')
    expect(button(wrapper, 'Import').element.disabled).toBe(true)
  })

  it('reads a chosen file into the text', async () => {
    const wrapper = mountImport()
    const input = wrapper.find<HTMLInputElement>('input[type="file"]')
    Object.defineProperty(input.element, 'files', { value: [new File([CSV], 'places.csv')], configurable: true })
    await input.trigger('change')
    await vi.waitFor(() => expect(field(wrapper, 'Places as CSV').element.value).toBe(CSV))
  })

  it('refuses a file over 64 KiB, as the API does', async () => {
    const api = fakeApi(importAnswers({ rows: ROWS, errors: [], created: [] }))
    const wrapper = mountImport()
    const input = wrapper.find<HTMLInputElement>('input[type="file"]')
    const big = new File(['a'.repeat(65537)], 'places.csv')
    Object.defineProperty(input.element, 'files', { value: [big], configurable: true })
    await input.trigger('change')
    await flushPromises()
    expect(wrapper.text()).toContain('The file is larger than 64 KiB.')
    expect(field(wrapper, 'Places as CSV').element.value).toBe('')
    expect(api.sent).toEqual([])
  })

  it('refuses pasted text over 64 KiB before sending it', async () => {
    const api = fakeApi(importAnswers({ rows: ROWS, errors: [], created: [] }))
    const wrapper = mountImport()
    await paste(wrapper, 'a'.repeat(65537))
    expect(wrapper.text()).toContain('The text is longer than 64 KiB.')
    expect(button(wrapper, 'Preview').element.disabled).toBe(true)
    expect(api.sent).toEqual([])
  })
})
