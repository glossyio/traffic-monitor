// The Location page: the place in use, the precision, and the list of places, for admins only.
import { flushPromises, type VueWrapper } from '@vue/test-utils'
import { beforeEach, describe, expect, it } from 'vitest'
import type { components } from '../src/api/schema'
import { ADMIN, VIEWER, json, signedIn } from './fake-api'
import { button, click, clickInDialog, dialogText, field, mountApp } from './mount'

type PlacesState = components['schemas']['PlacesState']
type SurveyOut = components['schemas']['SurveyOut']

const SURVEYS = 'GET /api/v1/surveys'
const DAY = 86400 * 1000

function place(changes: Partial<SurveyOut>): SurveyOut {
  return {
    id: 'a1b2c3d4-si',
    description: null,
    lat: null,
    lon: null,
    status: 'used',
    source: 'ui',
    created_at: '2026-10-01T12:00:00+00:00',
    updated_at: '2026-10-01T12:00:00+00:00',
    bearings: [],
    stored_lat: null,
    stored_lon: null,
    first_used: null,
    last_used: null,
    open_count: 0,
    deployment_count: 0,
    imported: false,
    ...changes,
  }
}

const IN_USE = place({
  id: 'a1b2c3d4-si',
  description: 'Front of the school',
  lat: 45.52252,
  lon: -122.6912,
  stored_lat: 45.5,
  stored_lon: -122.7,
  status: 'in_use',
  first_used: Date.now() - 3 * DAY,
  open_count: 2,
  deployment_count: 2,
})
const PLANNED = place({
  id: '0f0e0d0c-si',
  description: 'Corner by the park',
  lat: 45.0,
  lon: -122.0,
  stored_lat: 45.0,
  stored_lon: -122.0,
  status: 'planned',
})
const USED = place({
  id: 'c0ffee01-si',
  lat: 45.0,
  lon: -122.0,
  stored_lat: 45.0,
  stored_lon: -122.0,
  status: 'used',
  source: 'imported_backup',
  imported: true,
  first_used: Date.now() - 40 * DAY,
  last_used: Date.now() - 5 * DAY,
  deployment_count: 3,
})

const PLACES: PlacesState = {
  precision: '1',
  in_use: IN_USE.id,
  sensors: [
    { sensor_type: 'cameras', sensor_name: 'picam_h265', bearing: 'n' },
    { sensor_type: 'radars', sensor_name: 'TM_RADAR_SERIAL_PORT_00', bearing: '' },
  ],
  sharing: 'none',
  surveys: [IN_USE, PLANNED, USED],
  unassigned: null,
  reconcile: 'done',
  nodered: true,
}

// The title (a button) of the place's panel, found by the text it starts with
function panel(wrapper: VueWrapper, title: string) {
  const found = wrapper.findAll('.v-expansion-panel-title').filter((t) => t.text().trim().startsWith(title))
  expect(found.length, `one panel titled "${title}…"`).toBe(1)
  return found[0]
}

// Open a place's panel and wait for what it asks the API
async function expand(wrapper: VueWrapper, title: string) {
  await panel(wrapper, title).trigger('click')
  await flushPromises()
}

function menu(wrapper: VueWrapper) {
  return wrapper.findAll('.v-navigation-drawer .v-list-item-title').map((t) => t.text().trim())
}

describe('the Location page', () => {
  beforeEach(() => document.body.replaceChildren())

  it('is in the menu for admins only and sends a viewer home', async () => {
    signedIn(ADMIN, { [SURVEYS]: PLACES })
    const admin = await mountApp('/location')
    expect(menu(admin.wrapper)).toContain('Location')
    expect(admin.router.currentRoute.value.path).toBe('/location')
    admin.wrapper.unmount()

    const api = signedIn(VIEWER)
    const viewer = await mountApp('/location')
    expect(viewer.router.currentRoute.value.path).toBe('/')
    expect(menu(viewer.wrapper)).not.toContain('Location')
    expect(api.sent.some((r) => r.path === '/api/v1/surveys')).toBe(false)
  })

  it('shows the place in use with its stored and exact coordinates and the bearings', async () => {
    signedIn(ADMIN, { [SURVEYS]: PLACES })
    const { wrapper } = await mountApp('/location')
    expect(wrapper.find('h1').text()).toBe('Location')
    const card = wrapper.find('.v-card')
    expect(card.find('h2').text()).toBe('Front of the school')
    const text = card.text()
    expect(text).toContain('In use')
    expect(text).toContain('a1b2c3d4-si')
    expect(text).toContain('Stored in the database')
    expect(text).toContain('45.5, -122.7')
    expect(text).toContain('Exact location')
    expect(text).toContain('45.52252, -122.69120')
    expect(text).toContain('Not sharing')
    expect(text).toContain('Bearing, picam_h265')
    expect(text).toContain('Bearing, TM_RADAR_SERIAL_PORT_00')
    expect(text).toContain('Not set')
  })

  it('lists the places in use, planned, then used, and marks the imported one', async () => {
    signedIn(ADMIN, { [SURVEYS]: PLACES })
    const { wrapper } = await mountApp('/location')
    const titles = wrapper.findAll('.v-expansion-panel-title').map((t) => t.text())
    expect(titles).toHaveLength(3)
    expect(titles[0]).toContain('Front of the school')
    expect(titles[0]).toContain('In use')
    expect(titles[0]).toContain('45.5, -122.7')
    expect(titles[1]).toContain('Corner by the park')
    expect(titles[1]).toContain('Planned')
    expect(titles[1]).toContain('45.0, -122.0')
    expect(titles[2]).toContain('No description')
    expect(titles[2]).toContain('c0ffee01-si')
    expect(titles[2]).toContain('Used')
    expect(button(wrapper, 'Add a place').exists()).toBe(true)
    expect(button(wrapper, 'Import places').exists()).toBe(true)

    await expand(wrapper, 'No description')
    expect(wrapper.text()).toContain('Imported from your previous settings')
  })

  it('loads the events when a place is expanded', async () => {
    const api = signedIn(ADMIN, {
      [SURVEYS]: PLACES,
      'GET /api/v1/surveys/c0ffee01-si/events': { event_count: 120, first_event: 1790000000, last_event: 1790500000 },
      'GET /api/v1/surveys/c0ffee01-si/deployments': {
        deployments: [
          {
            id: '1790000000000-0a1b2c3d-d',
            started: 1790000000000,
            ended: 1790500000000,
            lat: 45.0,
            lon: -122.0,
            bearing: 'ne',
            sensor_type: 'cameras',
            sensor_name: 'picam_h265',
            location_precision: 1,
          },
        ],
      },
    })
    const { wrapper } = await mountApp('/location')
    expect(api.sent.some((r) => r.path.endsWith('/events'))).toBe(false) // nothing until a panel opens
    await expand(wrapper, 'No description')
    expect(wrapper.text()).toContain('120 events from')
    expect(wrapper.text()).toContain('picam_h265')
    expect(wrapper.text()).toContain('Deployments (1)')
    expect(wrapper.text()).toContain('Facing NE')
    expect(button(wrapper, 'Deploy here').exists()).toBe(true)
    expect(button(wrapper, 'Correct location').exists()).toBe(true)
    expect(wrapper.findAll('button').some((b) => b.text().trim() === 'Edit')).toBe(false) // a used place is corrected
  })

  it('asks before deleting and sends DELETE', async () => {
    const api = signedIn(ADMIN, {
      [SURVEYS]: PLACES,
      'GET /api/v1/surveys/c0ffee01-si/events': { event_count: 0, first_event: null, last_event: null },
      'GET /api/v1/surveys/c0ffee01-si/deployments': { deployments: [] },
      'DELETE /api/v1/surveys/c0ffee01-si': json(204, null),
    })
    const { wrapper } = await mountApp('/location')
    await expand(wrapper, 'No description')
    await click(wrapper, 'Delete')
    expect(dialogText()).toContain('exact location')
    expect(api.sent.some((r) => r.method === 'DELETE')).toBe(false)
    await clickInDialog('Delete')
    expect(api.sent.filter((r) => r.method === 'DELETE').map((r) => r.path)).toEqual(['/api/v1/surveys/c0ffee01-si'])
    expect(api.sent.filter((r) => r.method === 'GET' && r.path === '/api/v1/surveys')).toHaveLength(2) // reloaded
  })

  it('offers to round the stored rows only when the precision goes down and confirms it', async () => {
    const api = signedIn(ADMIN, {
      [SURVEYS]: PLACES,
      'PUT /api/v1/surveys/precision': { ...PLACES, precision: 'none' },
    })
    const { wrapper } = await mountApp('/location')
    const label = 'Also round the rows already stored'
    expect(wrapper.text()).not.toContain(label)

    await field(wrapper, 'About 1 km').setValue(true) // finer: applies from the next deployment
    expect(wrapper.text()).not.toContain(label)

    await field(wrapper, 'No location stored').setValue(true) // coarser
    await field(wrapper, label).setValue(true)
    await click(wrapper, 'Save')
    expect(dialogText()).toContain("This can't be undone.")
    expect(api.sent.some((r) => r.method === 'PUT')).toBe(false)
    await clickInDialog('Save and round')
    const put = api.sent.filter((r) => r.method === 'PUT')
    expect(put.map((r) => [r.path, r.body])).toEqual([
      ['/api/v1/surveys/precision', { precision: 'none', round_stored: true }],
    ])
    expect(wrapper.text()).toContain('Saved.')
  })

  it('says when Node-RED has not answered', async () => {
    signedIn(ADMIN, { [SURVEYS]: { ...PLACES, reconcile: 'waiting_nodered' } })
    const { wrapper } = await mountApp('/location')
    expect(wrapper.text()).toContain(
      "Node-RED hasn't answered yet, so past places may be missing. The page checks again when you reload it.",
    )
  })

  it('says the unit records against one place when there is only the default place, with no location', async () => {
    const only = place({ id: 'a1b2c3d4-si', description: 'First location', status: 'in_use', source: 'default' })
    signedIn(ADMIN, { [SURVEYS]: { ...PLACES, surveys: [only] } })
    const { wrapper } = await mountApp('/location')
    expect(wrapper.text()).toContain(
      'This unit records against one place. Add a location only if you plan to move the unit or share data.',
    )
  })

  it('lists the deployments from before any place was recorded', async () => {
    const unassigned = { deployment_count: 4, first_start: Date.now() - 90 * DAY, last_end: Date.now() - 60 * DAY }
    signedIn(ADMIN, { [SURVEYS]: { ...PLACES, unassigned } })
    const { wrapper } = await mountApp('/location')
    const titles = wrapper.findAll('.v-expansion-panel-title').map((t) => t.text())
    expect(titles.at(-1)).toContain('4 deployments') // after the places
    await expand(wrapper, 'Before any place was recorded')
    expect(wrapper.text()).toContain('recorded before the unit had a place')
    expect(wrapper.text()).toContain('60 days ago')
  })
})
