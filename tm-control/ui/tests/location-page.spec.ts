// The Location page: the place in use, the precision, and the list of places, for admins only.
import { flushPromises, type VueWrapper } from '@vue/test-utils'
import { beforeEach, describe, expect, it } from 'vitest'
import type { components } from '../src/api/schema'
import { ADMIN, VIEWER, apiError, json, signedIn } from './fake-api'
import { button, click, clickInDialog, dialogButtons, dialogField, dialogText, field, mountApp, typeInto } from './mount'

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

// A deployment of the used place, as GET /surveys/{id}/deployments lists it
const DEPLOYMENT = {
  id: '1790000000000-0a1b2c3d-d',
  started: 1790000000000,
  ended: 1790500000000,
  lat: 45.0,
  lon: -122.0,
  bearing: 'ne',
  sensor_type: 'cameras',
  sensor_name: 'picam_h265',
  location_precision: 1,
}

// The title (a button) of the place's panel, found by the text it starts with
function panel(wrapper: VueWrapper, title: string) {
  const found = wrapper.findAll('.v-expansion-panel-title').filter((t) => t.text().trim().startsWith(title))
  expect(found.length, `one panel titled "${title}…"`).toBe(1)
  return found[0]
}

function panelIsOpen(wrapper: VueWrapper, title: string) {
  return panel(wrapper, title).element.closest('.v-expansion-panel')?.classList.contains('v-expansion-panel--active')
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
    expect(titles).toHaveLength(4) // and the precision, last
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
    expect(button(wrapper, 'Re-deploy here').exists()).toBe(true)
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

  it('heads the precision like the places, says why under the header, and keeps the choices closed', async () => {
    signedIn(ADMIN, { [SURVEYS]: PLACES })
    const { wrapper } = await mountApp('/location')
    const sections = wrapper.findAll('section > h2')
    expect(sections.map((h) => h.text())).toEqual(['Places', 'Precision'])
    expect(sections[1].classes()).toEqual(sections[0].classes())

    const note = sections[1].element.nextElementSibling as HTMLElement
    expect(note.textContent?.replace(/\s+/g, ' ').trim()).toBe(
      "To better protect your privacy, by default the database stores each place's location rounded to about 1 km. A " +
        'shared copy of the database holds only the rounded location. This device keeps the exact location you enter, ' +
        "outside the database. A later update will let you choose to export the database with each place's exact " +
        'location, for analysis and mapping.',
    )
    const card = wrapper.find('.v-card').element
    expect(card.nextElementSibling?.tagName).toBe('SECTION') // nothing else between the card and the places

    const title = panel(wrapper, 'Change the precision')
    expect(title.text()).toContain('Now: About 10 km (45.5, -122.7)')
    expect(panelIsOpen(wrapper, 'Change the precision')).toBe(false)
    expect(wrapper.text()).not.toContain('This setting is for the whole device')

    await expand(wrapper, 'Change the precision')
    expect(wrapper.text()).toContain(
      'This setting is for the whole device: every place, the deployments running now, and every new one.',
    )
    expect(wrapper.text().match(/keeps the exact location|exact location is kept/g)).toHaveLength(1) // said once
    expect(wrapper.text()).not.toContain('Exporting it is coming in a later update.')
  })

  it('offers to round the stored rows only when the precision goes down and confirms it', async () => {
    const api = signedIn(ADMIN, {
      [SURVEYS]: { ...PLACES, precision: '2' },
      'PUT /api/v1/surveys/precision': PLACES,
    })
    const { wrapper } = await mountApp('/location')
    await expand(wrapper, 'Change the precision')
    const label = 'Also round the rows already stored'
    expect(wrapper.text()).not.toContain(label)

    await field(wrapper, 'About 10 km (45.5, -122.7)').setValue(true) // coarser
    expect(wrapper.text()).toContain('Older rows keep theirs unless you tick the box.')
    await field(wrapper, label).setValue(true)
    await click(wrapper, 'Save')
    expect(dialogText()).toContain('Round the rows already stored?')
    expect(dialogText()).toContain("This can't be undone.")
    expect(api.sent.some((r) => r.method === 'PUT')).toBe(false)
    await clickInDialog('Save and round')
    const put = api.sent.filter((r) => r.method === 'PUT')
    expect(put.map((r) => [r.path, r.body])).toEqual([
      ['/api/v1/surveys/precision', { precision: '1', round_stored: true }],
    ])
    expect(wrapper.text()).toContain('Saved. The rows already stored are rounded.')
    expect(panelIsOpen(wrapper, 'Change the precision')).toBe(true) // so the result can be read
  })

  it('offers nothing to round for a finer choice', async () => {
    signedIn(ADMIN, { [SURVEYS]: PLACES })
    const { wrapper } = await mountApp('/location')
    await expand(wrapper, 'Change the precision')
    await field(wrapper, 'About 1 km (45.52, -122.69), the default').setValue(true)
    expect(wrapper.text()).not.toContain('Also round the rows already stored')
    expect(wrapper.text()).toContain('A finer precision applies from the next deployment.')
  })

  it('says No location stored removes the stored location, and asks in those words', async () => {
    const api = signedIn(ADMIN, {
      [SURVEYS]: PLACES,
      'PUT /api/v1/surveys/precision': { ...PLACES, precision: 'none' },
    })
    const { wrapper } = await mountApp('/location')
    await expand(wrapper, 'Change the precision')
    await field(wrapper, 'No location stored').setValue(true)
    expect(wrapper.text()).toContain(
      'No location stored removes the stored location from the deployments running now at once. Tick the box to ' +
        'remove it from every row already in the database as well. The exact location stays on this device, but the ' +
        "database can't get the rounded values back.",
    )
    expect(wrapper.text()).not.toContain('Older rows keep theirs')
    await field(wrapper, 'Also remove it from the rows already stored').setValue(true)
    await click(wrapper, 'Save')
    expect(dialogText()).toContain('Remove the stored location from every row?')
    expect(dialogText()).toContain("Every row in the database loses its stored location. This can't be undone.")
    await clickInDialog('Save and remove')
    expect(api.sent.filter((r) => r.method === 'PUT').map((r) => r.body)).toEqual([
      { precision: 'none', round_stored: true },
    ])
    expect(wrapper.text()).toContain('Saved. The rows already stored no longer hold a location.')
  })

  it('saves without asking when the box is left clear', async () => {
    const api = signedIn(ADMIN, {
      [SURVEYS]: PLACES,
      'PUT /api/v1/surveys/precision': { ...PLACES, precision: 'none' },
    })
    const { wrapper } = await mountApp('/location')
    await expand(wrapper, 'Change the precision')
    await field(wrapper, 'No location stored').setValue(true)
    await click(wrapper, 'Save')
    expect(api.sent.filter((r) => r.method === 'PUT').map((r) => r.body)).toEqual([
      { precision: 'none', round_stored: false },
    ])
    expect(panel(wrapper, 'Change the precision').text()).toContain('No location stored') // the title follows the device
  })

  it('loads the places again when saving the precision is refused because config.yml changed', async () => {
    const api = signedIn(ADMIN, {
      [SURVEYS]: PLACES,
      'PUT /api/v1/surveys/precision': apiError(
        409,
        'config_changed',
        'config.yml changed since it was read. Reload the page and try again.',
      ),
    })
    const { wrapper } = await mountApp('/location')
    await expand(wrapper, 'Change the precision')
    await field(wrapper, 'No location stored').setValue(true)
    await click(wrapper, 'Save')
    expect(wrapper.text()).toContain('config.yml changed since it was read.')
    expect(api.sent.filter((r) => r.method === 'GET' && r.path === '/api/v1/surveys')).toHaveLength(2)
    expect(button(wrapper, 'Save').attributes('disabled')).toBeDefined() // the choice follows the device again
  })

  it('stays as it is when Node-RED refuses to round the rows, so Save can be pressed again', async () => {
    const api = signedIn(ADMIN, {
      [SURVEYS]: PLACES,
      'PUT /api/v1/surveys/precision': apiError(
        502,
        'nodered',
        "config.yml now has the new precision, but the stored rows weren't changed.",
      ),
    })
    const { wrapper } = await mountApp('/location')
    await expand(wrapper, 'Change the precision')
    await field(wrapper, 'No location stored').setValue(true)
    await click(wrapper, 'Save')
    expect(wrapper.text()).toContain("the stored rows weren't changed.")
    expect(api.sent.filter((r) => r.method === 'GET' && r.path === '/api/v1/surveys')).toHaveLength(1)
    expect(button(wrapper, 'Save').attributes('disabled')).toBeUndefined()
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
    expect(titles.at(-2)).toContain('4 deployments') // after the places, before the precision
    await expand(wrapper, 'Before any place was recorded')
    expect(wrapper.text()).toContain('recorded before the unit had a place')
    expect(wrapper.text()).toContain('60 days ago')
  })

  it('opens the form from Add a place and reloads the list after saving', async () => {
    const api = signedIn(ADMIN, { [SURVEYS]: PLACES, 'POST /api/v1/surveys': json(201, PLANNED) })
    const { wrapper } = await mountApp('/location')
    expect(dialogText()).toBe('')
    await click(wrapper, 'Add a place')
    expect(dialogText()).toContain('Add a place')
    await typeInto(dialogField('Description'), 'Corner by the park')
    await clickInDialog('Save')
    expect(api.sent.filter((r) => r.method === 'POST').map((r) => r.path)).toEqual(['/api/v1/surveys'])
    expect(api.sent.filter((r) => r.method === 'GET' && r.path === '/api/v1/surveys')).toHaveLength(2) // reloaded
  })

  it("opens the form from Edit with the planned place's values", async () => {
    signedIn(ADMIN, {
      [SURVEYS]: PLACES,
      'GET /api/v1/surveys/0f0e0d0c-si/events': { event_count: 0, first_event: null, last_event: null },
      'GET /api/v1/surveys/0f0e0d0c-si/deployments': { deployments: [] },
    })
    const { wrapper } = await mountApp('/location')
    await expand(wrapper, 'Corner by the park')
    await click(wrapper, 'Edit')
    expect(dialogField('Description').value).toBe('Corner by the park')
    expect(dialogField('Coordinates').value).toBe('45.00000, -122.00000')
  })

  it('opens the review from Re-deploy here on a used place', async () => {
    signedIn(ADMIN, {
      [SURVEYS]: PLACES,
      'GET /api/v1/surveys/c0ffee01-si/events': { event_count: 0, first_event: null, last_event: null },
      'GET /api/v1/surveys/c0ffee01-si/deployments': { deployments: [] },
    })
    const { wrapper } = await mountApp('/location')
    await expand(wrapper, 'No description')
    await click(wrapper, 'Re-deploy here')
    expect(dialogText()).toContain('c0ffee01-si')
    expect(dialogText()).toContain('New deployment starts')
    expect(dialogText()).toContain('Counts from now on attach to the new deployment.')
  })

  it('offers Modify deployment on the place in use, to record a turn of the unit', async () => {
    signedIn(ADMIN, {
      [SURVEYS]: PLACES,
      'GET /api/v1/surveys/a1b2c3d4-si/events': { event_count: 0, first_event: null, last_event: null },
      'GET /api/v1/surveys/a1b2c3d4-si/deployments': { deployments: [] },
    })
    const { wrapper } = await mountApp('/location')
    await expand(wrapper, 'Front of the school')
    expect(wrapper.findAll('button').some((b) => b.text().trim() === 'Deploy here')).toBe(false)
    await click(wrapper, 'Modify deployment')
    expect(dialogText()).toContain('Unchanged')
    expect(document.querySelector('.v-overlay-container .v-dialog')?.getAttribute('aria-label')).toBe(
      'Modify deployment',
    )
  })

  it('offers Deploy here on a planned place', async () => {
    signedIn(ADMIN, {
      [SURVEYS]: PLACES,
      'GET /api/v1/surveys/0f0e0d0c-si/events': { event_count: 0, first_event: null, last_event: null },
      'GET /api/v1/surveys/0f0e0d0c-si/deployments': { deployments: [] },
    })
    const { wrapper } = await mountApp('/location')
    await expand(wrapper, 'Corner by the park')
    await click(wrapper, 'Deploy here')
    expect(document.querySelector('.v-overlay-container .v-dialog')?.getAttribute('aria-label')).toBe('Deploy here')
    expect(dialogButtons('Deploy')).toHaveLength(1)
  })

  it('keeps the import dialog open on a click beside it, so its result is seen', async () => {
    signedIn(ADMIN, { [SURVEYS]: PLACES })
    const { wrapper } = await mountApp('/location')
    await click(wrapper, 'Import places')
    const dialog = wrapper
      .findAllComponents({ name: 'VDialog' })
      .find((found) => found.vm.$attrs['aria-label'] === 'Import places')
    expect(dialog?.props('persistent')).toBe(true)
  })

  it('loads the places again when a deploy is refused because config.yml changed', async () => {
    const api = signedIn(ADMIN, {
      [SURVEYS]: PLACES,
      'GET /api/v1/surveys/c0ffee01-si/events': { event_count: 0, first_event: null, last_event: null },
      'GET /api/v1/surveys/c0ffee01-si/deployments': { deployments: [] },
      'POST /api/v1/surveys/c0ffee01-si/deploy': apiError(
        409,
        'config_changed',
        'config.yml changed since it was read. Reload the page and try again.',
      ),
    })
    const { wrapper } = await mountApp('/location')
    await expand(wrapper, 'No description')
    await click(wrapper, 'Re-deploy here')
    await clickInDialog('Re-deploy')
    expect(dialogText()).toContain('config.yml changed since it was read.')
    expect(api.sent.filter((r) => r.method === 'GET' && r.path === '/api/v1/surveys')).toHaveLength(2)
  })

  it('keeps the review in the dialog while it closes', async () => {
    signedIn(ADMIN, {
      [SURVEYS]: PLACES,
      'GET /api/v1/surveys/c0ffee01-si/events': { event_count: 0, first_event: null, last_event: null },
      'GET /api/v1/surveys/c0ffee01-si/deployments': { deployments: [] },
    })
    const { wrapper } = await mountApp('/location')
    await expand(wrapper, 'No description')
    await click(wrapper, 'Re-deploy here')
    await clickInDialog('Cancel')
    // The dialog fades out; until it's gone it still shows the review, not an empty box
    expect(dialogText()).toContain('c0ffee01-si')
  })

  it('loads the places and the open panel again after a deploy', async () => {
    const api = signedIn(ADMIN, {
      [SURVEYS]: PLACES,
      'GET /api/v1/surveys/c0ffee01-si/events': { event_count: 0, first_event: null, last_event: null },
      'GET /api/v1/surveys/c0ffee01-si/deployments': { deployments: [] },
      'POST /api/v1/surveys/c0ffee01-si/deploy': { deployed_at: 1762000000000, reloaded: false, deployments: [] },
    })
    const { wrapper } = await mountApp('/location')
    await expand(wrapper, 'No description')
    await click(wrapper, 'Re-deploy here')
    await clickInDialog('Re-deploy')
    expect(dialogText()).toContain("Don't deploy again.")
    const gets = (path: string) => api.sent.filter((r) => r.method === 'GET' && r.path === path)
    expect(gets('/api/v1/surveys')).toHaveLength(2)
    expect(gets('/api/v1/surveys/c0ffee01-si/deployments')).toHaveLength(2)
  })

  it("opens the location correction from Correct location, starting at the place's point", async () => {
    signedIn(ADMIN, {
      [SURVEYS]: PLACES,
      'GET /api/v1/surveys/c0ffee01-si/events': { event_count: 0, first_event: null, last_event: null },
      'GET /api/v1/surveys/c0ffee01-si/deployments': { deployments: [] },
    })
    const { wrapper } = await mountApp('/location')
    await expand(wrapper, 'No description')
    await click(wrapper, 'Correct location')
    expect(dialogText()).toContain('Use this only if the location was entered wrong.')
    expect(dialogField('Coordinates').value).toBe('45.00000, -122.00000')
  })

  it('offers no Correct location for a used place with no point', async () => {
    const pointless = place({ id: 'c0ffee01-si', status: 'used', deployment_count: 1 })
    signedIn(ADMIN, {
      [SURVEYS]: { ...PLACES, surveys: [IN_USE, pointless] },
      'GET /api/v1/surveys/c0ffee01-si/events': { event_count: 0, first_event: null, last_event: null },
      'GET /api/v1/surveys/c0ffee01-si/deployments': { deployments: [] },
    })
    const { wrapper } = await mountApp('/location')
    await expand(wrapper, 'No description')
    expect(button(wrapper, 'Re-deploy here').exists()).toBe(true)
    expect(wrapper.findAll('button').some((b) => b.text().trim() === 'Correct location')).toBe(false)
  })

  it('opens the bearing correction from Correct bearing on a deployment', async () => {
    signedIn(ADMIN, {
      [SURVEYS]: PLACES,
      'GET /api/v1/surveys/c0ffee01-si/events': { event_count: 1, first_event: 1790000000, last_event: 1790000000 },
      'GET /api/v1/surveys/c0ffee01-si/deployments': { deployments: [DEPLOYMENT] },
    })
    const { wrapper } = await mountApp('/location')
    await expand(wrapper, 'No description')
    await click(wrapper, 'Correct bearing')
    expect(dialogText()).toContain('Use this only if the bearing was entered wrong.')
    expect(dialogText()).toContain('picam_h265')
    expect(document.querySelector('.v-overlay-container .v-dialog')?.getAttribute('aria-label')).toBe('Correct bearing')
  })

  it('loads the places and the open panel again after a correction', async () => {
    const api = signedIn(ADMIN, {
      [SURVEYS]: PLACES,
      'GET /api/v1/surveys/c0ffee01-si/events': { event_count: 1, first_event: 1790000000, last_event: 1790000000 },
      'GET /api/v1/surveys/c0ffee01-si/deployments': { deployments: [DEPLOYMENT] },
      'POST /api/v1/surveys/c0ffee01-si/deployments/1790000000000-0a1b2c3d-d/bearing': { ...DEPLOYMENT, bearing: 'se' },
    })
    const { wrapper } = await mountApp('/location')
    await expand(wrapper, 'No description')
    await click(wrapper, 'Correct bearing')
    await wrapper.findAllComponents({ name: 'VSelect' }).at(-1)!.setValue('se')
    await flushPromises()
    await clickInDialog('Correct')
    const gets = (path: string) => api.sent.filter((r) => r.method === 'GET' && r.path === path)
    expect(gets('/api/v1/surveys')).toHaveLength(2)
    expect(gets('/api/v1/surveys/c0ffee01-si/deployments')).toHaveLength(2)
  })

  it('opens the import from Import places and loads the places again after an import', async () => {
    const preview = { rows: [{ line: 2, description: 'Bus stop on the hill', lat: null, lon: null, bearings: [] }] }
    const api = signedIn(ADMIN, {
      [SURVEYS]: PLACES,
      'POST /api/v1/surveys/import': async (request: Request) => {
        const body = (await request.clone().json()) as { dry_run: boolean }
        return json(200, { ...preview, errors: [], created: body.dry_run ? [] : ['0f0e0d0c-si'] })
      },
    })
    const { wrapper } = await mountApp('/location')
    await click(wrapper, 'Import places')
    expect(document.querySelector('.v-overlay-container .v-dialog')?.getAttribute('aria-label')).toBe('Import places')
    await typeInto(dialogField('Places as CSV'), 'description,lat,lon\nBus stop on the hill,,\n')
    await clickInDialog('Preview')
    await clickInDialog('Import')
    expect(dialogText()).toContain('Added 1 place')
    expect(api.sent.filter((r) => r.method === 'GET' && r.path === '/api/v1/surveys')).toHaveLength(2)
  })
})
